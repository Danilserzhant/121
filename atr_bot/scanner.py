"""Scan every symbol on the exchange and rank by ATR expansion."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from typing import Sequence

import aiohttp

from .config import Settings
from .exchanges import BaseExchange, Deriv, ExchangeError, SymbolInfo, interval_ms, make_exchange
from .indicators import AtrMetrics, Candle, candle_returns, compute_metrics
from .marketcap import MarketCapProvider

log = logging.getLogger(__name__)

# Correlation-with-BTC filters for ScanResult.top()
CORR_FILTERS = {
    "any": lambda r: True,
    "lo": lambda r: abs(r) < 0.3,
    "mid": lambda r: abs(r) < 0.5,
    "hi": lambda r: r > 0.7,
}

# Stablecoins and wrapped fiat: their "volatility" is noise, never rank them.
STABLE_BASES = {
    "USDC", "USDT", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USD1", "USDE", "PYUSD",
    "EUR", "EURI", "EURC", "AEUR", "GBP", "TRY", "BRL", "USDD", "USDS", "USDY", "XUSD", "GUSD", "LUSD", "FRAX",
}


@dataclass
class ScanResult:
    exchange: str
    interval: str
    atr_period: int
    lookback: int
    scanned_at: float
    total_symbols: int
    ranked: list[AtrMetrics] = field(default_factory=list)  # sorted by ATR% desc
    errors: int = 0
    duration: float = 0.0

    def top(
        self, n: int, by: str = "atr", direction: str = "all", min_volume: float = 0.0, min_cap: float = 0.0,
        corr: str = "any",
    ) -> list[AtrMetrics]:
        """Top N with optional filters.

        by: 'atr' (ATR% of price), 'expansion' (ATR growth), 'corr' (least correlated with BTC first),
        'corrhi' (most correlated first). min_volume: 24h quote volume floor; min_cap: market cap floor
        (coins with unknown cap are dropped). corr: 'any' | 'lo' (|ρ|<0.3) | 'mid' (|ρ|<0.5) | 'hi' (ρ>0.7).
        """
        rows = self.ranked
        if direction == "long":
            rows = [m for m in rows if m.move_pct > 0]
        elif direction == "short":
            rows = [m for m in rows if m.move_pct < 0]
        if min_volume > 0:
            rows = [m for m in rows if m.quote_volume >= min_volume]
        if min_cap > 0:
            rows = [m for m in rows if m.market_cap >= min_cap]
        if corr in CORR_FILTERS and corr != "any":
            rows = [m for m in rows if m.btc_corr is not None and CORR_FILTERS[corr](m.btc_corr)]
        if by == "expansion":
            rows = sorted(rows, key=lambda m: m.expansion_pct, reverse=True)
        elif by in ("corr", "corrhi"):
            rows = [m for m in rows if m.btc_corr is not None]
            rows = sorted(rows, key=lambda m: m.btc_corr, reverse=(by == "corrhi"))
        return rows[:n]

    @property
    def candle_time(self) -> int:
        return self.ranked[0].candle_time if self.ranked else 0

    _index: dict[str, int] = field(default_factory=dict, repr=False)

    def _idx(self) -> dict[str, int]:
        if len(self._index) != len(self.ranked):
            self._index = {m.symbol: i for i, m in enumerate(self.ranked)}
        return self._index

    def find(self, symbol: str) -> AtrMetrics | None:
        i = self._idx().get(symbol.upper())
        return self.ranked[i] if i is not None else None

    def rank_of(self, symbol: str) -> int | None:
        i = self._idx().get(symbol.upper())
        return i + 1 if i is not None else None


class Scanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._exchange: BaseExchange | None = None
        self._mcap: MarketCapProvider | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, ScanResult] = {}
        self._symbols_cache: tuple[float, list[SymbolInfo]] | None = None
        self._btc_cache: dict[str, tuple[float, dict[int, float]]] = {}  # interval -> (time, returns)
        self._deriv_cache: tuple[float, dict[str, Deriv]] | None = None
        self._all_symbols_cache: tuple[float, list[SymbolInfo]] | None = None
        self._bg: set[asyncio.Task] = set()
        self._deriv_task: asyncio.Task | None = None
        # Hourly open-interest snapshots [{"t": ms, "oi": {symbol: usd}}], shared with the store for persistence.
        self.oi_history: list[dict] = []

    async def __aenter__(self) -> "Scanner":
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def open(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(headers={"User-Agent": "atr-expansion-bot/0.1"})
            self._exchange = make_exchange(
                self.settings.exchange, self._session, self.settings.quote_asset, self.settings.exchange_proxy
            )
            self._mcap = MarketCapProvider(self._session, ttl=self.settings.mcap_ttl, proxy=self.settings.exchange_proxy)

    def _spawn(self, coro) -> asyncio.Task:  # noqa: ANN001
        """Run a coroutine in the background, keeping a reference so it is not garbage-collected."""
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    async def warm_up(self) -> None:
        """Pre-fetch everything so that the first user request is served from cache."""
        started = time.time()
        try:
            await self.mcap.get()
            await self.derivatives(force=True)
            for tf in self.settings.intervals:
                await self.scan(tf)
        except Exception:  # noqa: BLE001
            log.exception("warm-up failed")
        log.info("warm-up done in %.1fs", time.time() - started)

    async def refresh_stale(self) -> None:
        """Rescan every interval whose last closed candle has changed (called after each hourly close)."""
        for tf in self.settings.intervals:
            if not self.is_fresh(tf):
                try:
                    await self.scan(tf)
                except ExchangeError:
                    log.exception("refresh %s failed", tf)

    async def close(self) -> None:
        for t in self._bg:
            t.cancel()
        if self._session is not None:
            await self._session.close()
            self._session = None
            self._exchange = None

    @property
    def mcap(self) -> MarketCapProvider:
        if self._mcap is None:
            raise RuntimeError("Scanner is not opened")
        return self._mcap

    async def _cap(self, symbol: str) -> float:
        await self.mcap.get()
        return self.mcap.cap(symbol, self.settings.quote_asset)

    @property
    def exchange(self) -> BaseExchange:
        if self._exchange is None:
            raise RuntimeError("Scanner is not opened")
        return self._exchange

    def last(self, interval: str | None = None) -> ScanResult | None:
        return self._last.get(interval or self.settings.interval)

    def invalidate(self) -> None:
        """Drop cached results (after settings change)."""
        self._last = {}
        self._symbols_cache = None
        self._btc_cache = {}

    async def all_symbols(self) -> list[SymbolInfo]:
        """Every tradable symbol on the exchange (two HTTP calls), cached for 10 minutes."""
        now = time.time()
        if self._all_symbols_cache and now - self._all_symbols_cache[0] < 600:
            return self._all_symbols_cache[1]
        symbols = await self.exchange.list_symbols()
        self._all_symbols_cache = (now, symbols)
        return symbols

    async def symbol_info(self, symbol: str) -> SymbolInfo | None:
        symbol = self.normalize_symbol(symbol)
        return next((i for i in await self.all_symbols() if i.symbol == symbol), None)

    async def symbols(self) -> list[SymbolInfo]:
        """Tradable symbols filtered by quote volume, cached for 10 minutes."""
        now = time.time()
        if self._symbols_cache and now - self._symbols_cache[0] < 600:
            return self._symbols_cache[1]
        all_symbols = await self.all_symbols()
        quote = self.settings.quote_asset
        symbols = [
            s for s in all_symbols
            if s.quote_volume >= self.settings.min_quote_volume
            and s.symbol.removesuffix(quote) not in STABLE_BASES
        ]
        log.info("%s: %d symbols, %d after volume filter (>= %.0f %s)",
                 self.exchange.name, len(all_symbols), len(symbols), self.settings.min_quote_volume, self.settings.quote_asset)
        self._symbols_cache = (now, symbols)
        return symbols

    async def derivatives(self, force: bool = False) -> dict[str, Deriv]:
        """Funding + open interest for all scanned symbols, cached for 10 minutes.

        Without `force` a stale cache is returned immediately and refreshed in the background,
        so user requests never wait for hundreds of open-interest calls.
        """
        fresh = self._deriv_cache is not None and time.time() - self._deriv_cache[0] < 600
        if fresh and not force:
            return self._deriv_cache[1]
        if self._deriv_cache is not None and not force:
            if self._deriv_task is None or self._deriv_task.done():
                self._deriv_task = self._spawn(self._fetch_derivatives())
            return self._deriv_cache[1]
        if self._deriv_task is not None and not self._deriv_task.done():
            await self._deriv_task
            return self._deriv_cache[1] if self._deriv_cache else {}
        self._deriv_task = self._spawn(self._fetch_derivatives())
        await self._deriv_task
        return self._deriv_cache[1] if self._deriv_cache else {}

    async def _fetch_derivatives(self) -> None:
        try:
            data = await self.exchange.fetch_derivatives(await self.symbols(), self.settings.concurrency)
        except ExchangeError as exc:
            log.warning("derivatives fetch failed: %s", exc)
            data = self._deriv_cache[1] if self._deriv_cache else {}
        self._deriv_cache = (time.time(), data)

    def record_oi(self, candle_time: int, derivs: dict[str, Deriv]) -> None:
        """Store an hourly OI snapshot (idempotent per candle)."""
        snap = {sym: d.oi_usd for sym, d in derivs.items() if d.oi_usd}
        if not snap:
            return
        for h in self.oi_history:
            if h["t"] == candle_time:
                h["oi"] = snap
                break
        else:
            self.oi_history.append({"t": candle_time, "oi": snap})
        self.oi_history.sort(key=lambda h: h["t"])
        del self.oi_history[:-30]

    def _oi_change(self, symbol: str, now_oi: float | None, hours: int) -> float | None:
        if not now_oi or not self.oi_history:
            return None
        target = self.oi_history[-1]["t"] - hours * 3_600_000
        # newest snapshot that is at least `hours` old
        older = [h for h in self.oi_history if h["t"] <= target]
        if not older:
            return None
        past = older[-1]["oi"].get(symbol)
        return (now_oi / past - 1) * 100 if past else None

    def _with_derivs(self, m: AtrMetrics, derivs: dict[str, Deriv]) -> AtrMetrics:
        d = derivs.get(m.symbol)
        if d is None:
            return m
        return dataclasses.replace(
            m, funding=d.funding, oi_usd=d.oi_usd,
            oi_change_24h=self._oi_change(m.symbol, d.oi_usd, 24), oi_change_1h=self._oi_change(m.symbol, d.oi_usd, 1),
        )

    async def btc_returns(self, interval: str) -> dict[int, float]:
        """Candle returns of BTC on the interval, cached for cache_ttl seconds."""
        cached = self._btc_cache.get(interval)
        if cached and time.time() - cached[0] < self.settings.cache_ttl:
            return cached[1]
        info = await self.symbol_info("BTC" + self.settings.quote_asset)
        if info is None:
            return {}
        try:
            candles = await self.exchange.fetch_candles(info, interval, self.settings.candles_needed(interval))
        except ExchangeError as exc:
            log.warning("BTC candles for correlation failed: %s", exc)
            return {}
        returns = candle_returns(candles)
        self._btc_cache[interval] = (time.time(), returns)
        return returns

    def is_fresh(self, interval: str) -> bool:
        """A cached scan stays valid until the next candle of that interval closes:
        only closed candles are used, so nothing changes in between."""
        cached = self._last.get(interval)
        if cached is None or not cached.ranked:
            return False
        step = interval_ms(interval)
        next_close = (cached.candle_time + 2 * step) / 1000 + self.settings.close_delay
        return time.time() < next_close and time.time() - cached.scanned_at < 6 * 3600

    async def scan(self, interval: str | None = None, force: bool = False) -> ScanResult:
        """Run a full scan for the interval, or return the cached result while it is still valid."""
        interval = interval or self.settings.interval
        lock = self._locks.setdefault(interval, asyncio.Lock())
        async with lock:
            if not force and self.is_fresh(interval):
                return self._last[interval]
            result = await self._scan(interval)
            self._last[interval] = result
            return result

    async def _scan(self, interval: str) -> ScanResult:
        s = self.settings
        started = time.time()
        symbols = await self.symbols()
        if self.mcap.loaded:
            self._spawn(self.mcap.get())  # refresh in background when stale; never block a scan on it
        else:
            await self.mcap.get()
        btc, derivs = await asyncio.gather(self.btc_returns(interval), self.derivatives())
        sem = asyncio.Semaphore(s.concurrency)
        limit = s.candles_needed(interval)
        lookback = s.lookback_for(interval)
        errors = 0

        async def one(info: SymbolInfo) -> AtrMetrics | None:
            nonlocal errors
            async with sem:
                try:
                    candles = await self.exchange.fetch_candles(info, interval, limit)
                except ExchangeError as exc:
                    errors += 1
                    log.warning("%s: %s", info.symbol, exc)
                    return None
            return compute_metrics(
                info.symbol, candles, s.atr_period, lookback, info.quote_volume, self.mcap.cap(info.symbol, s.quote_asset), btc
            )

        metrics = await asyncio.gather(*(one(i) for i in symbols))
        ranked = [self._with_derivs(m, derivs) for m in metrics if m is not None and m.atr_pct >= s.min_atr_pct]
        ranked.sort(key=lambda m: m.atr_pct, reverse=True)
        result = ScanResult(
            exchange=self.exchange.name,
            interval=interval,
            atr_period=s.atr_period,
            lookback=lookback,
            scanned_at=time.time(),
            total_symbols=len(symbols),
            ranked=ranked,
            errors=errors,
            duration=time.time() - started,
        )
        log.info("scan %s done: %d ranked / %d symbols, %d errors, %.1fs", interval, len(ranked), len(symbols), errors, result.duration)
        return result

    def normalize_symbol(self, symbol: str) -> str:
        symbol = symbol.upper().replace("-", "").replace("/", "")
        if not symbol.endswith(self.settings.quote_asset):
            symbol += self.settings.quote_asset
        return symbol

    async def symbol_metrics(self, symbol: str, intervals: Sequence[str] | None = None) -> dict[str, AtrMetrics | None] | None:
        """Fresh metrics for one symbol on every interval (bypasses volume filter).

        Returns None if the symbol is unknown, otherwise {interval: metrics or None}.
        """
        symbol = self.normalize_symbol(symbol)
        intervals = list(intervals or self.settings.intervals)
        info = await self.symbol_info(symbol)
        if info is None:
            return None

        cap = await self._cap(info.symbol)

        async def one(interval: str) -> AtrMetrics | None:
            cached = self._last.get(interval)
            if cached is not None and self.is_fresh(interval):
                m = cached.find(symbol)
                if m is not None:
                    return m
            candles, btc = await asyncio.gather(
                self.exchange.fetch_candles(info, interval, self.settings.candles_needed(interval)),
                self.btc_returns(interval),
            )
            return compute_metrics(info.symbol, candles, self.settings.atr_period, self.settings.lookback_for(interval), info.quote_volume, cap, btc)

        results = await asyncio.gather(*(one(tf) for tf in intervals))
        derivs = await self.derivatives()
        return {tf: (self._with_derivs(m, derivs) if m else None) for tf, m in zip(intervals, results)}

    async def metrics_for(self, symbols: Sequence[str], interval: str) -> dict[str, AtrMetrics | None]:
        """Metrics for a list of symbols on one interval; uses the cached scan when it has them."""
        cached = self._last.get(interval) if self.is_fresh(interval) else None
        out: dict[str, AtrMetrics | None] = {}
        missing: list[str] = []
        for sym in symbols:
            m = cached.find(sym) if cached else None
            if m is not None:
                out[sym] = m
            else:
                missing.append(sym)
        if missing:
            by_name = {i.symbol: i for i in await self.all_symbols()}
            btc = await self.btc_returns(interval)
            sem = asyncio.Semaphore(self.settings.concurrency)

            async def one(sym: str) -> AtrMetrics | None:
                info = by_name.get(sym)
                if info is None:
                    return None
                async with sem:
                    try:
                        candles = await self.exchange.fetch_candles(info, interval, self.settings.candles_needed(interval))
                    except ExchangeError as exc:
                        log.warning("%s: %s", sym, exc)
                        return None
                return compute_metrics(sym, candles, self.settings.atr_period, self.settings.lookback_for(interval), info.quote_volume, await self._cap(sym), btc)

            derivs = await self.derivatives()
            for sym, m in zip(missing, await asyncio.gather(*(one(s) for s in missing))):
                out[sym] = self._with_derivs(m, derivs) if m else None
        return out

    async def candles(self, symbol: str, interval: str, limit: int) -> list[Candle] | None:
        """Raw closed candles for charts. None if the symbol is unknown."""
        info = await self.symbol_info(symbol)
        if info is None:
            return None
        return await self.exchange.fetch_candles(info, interval, limit)
