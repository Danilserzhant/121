"""Scan every symbol on the exchange and rank by ATR expansion."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Sequence

import aiohttp

from .config import Settings
from .exchanges import BaseExchange, ExchangeError, SymbolInfo, make_exchange
from .indicators import AtrMetrics, Candle, candle_returns, compute_metrics
from .marketcap import MarketCapProvider

log = logging.getLogger(__name__)

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
    ) -> list[AtrMetrics]:
        """Top N with optional filters.

        by: 'atr' (ATR% of price), 'expansion' (ATR growth), 'corr' (least correlated with BTC first),
        'corrhi' (most correlated first). min_volume: 24h quote volume floor; min_cap: market cap floor
        (coins with unknown cap are dropped).
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
        if by == "expansion":
            rows = sorted(rows, key=lambda m: m.expansion_pct, reverse=True)
        elif by in ("corr", "corrhi"):
            rows = [m for m in rows if m.btc_corr is not None]
            rows = sorted(rows, key=lambda m: m.btc_corr, reverse=(by == "corrhi"))
        return rows[:n]

    @property
    def candle_time(self) -> int:
        return self.ranked[0].candle_time if self.ranked else 0

    def find(self, symbol: str) -> AtrMetrics | None:
        symbol = symbol.upper()
        for m in self.ranked:
            if m.symbol == symbol:
                return m
        return None

    def rank_of(self, symbol: str) -> int | None:
        symbol = symbol.upper()
        for i, m in enumerate(self.ranked, start=1):
            if m.symbol == symbol:
                return i
        return None


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

    async def close(self) -> None:
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

    async def symbols(self) -> list[SymbolInfo]:
        """Tradable symbols filtered by quote volume, cached for 10 minutes."""
        now = time.time()
        if self._symbols_cache and now - self._symbols_cache[0] < 600:
            return self._symbols_cache[1]
        all_symbols = await self.exchange.list_symbols()
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

    async def btc_returns(self, interval: str) -> dict[int, float]:
        """Candle returns of BTC on the interval, cached for cache_ttl seconds."""
        cached = self._btc_cache.get(interval)
        if cached and time.time() - cached[0] < self.settings.cache_ttl:
            return cached[1]
        symbol = "BTC" + self.settings.quote_asset
        info = next((i for i in await self.exchange.list_symbols() if i.symbol == symbol), None)
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

    async def scan(self, interval: str | None = None, force: bool = False) -> ScanResult:
        """Run a full scan for the interval, or return a fresh-enough cached result."""
        interval = interval or self.settings.interval
        lock = self._locks.setdefault(interval, asyncio.Lock())
        async with lock:
            cached = self._last.get(interval)
            if not force and cached is not None and time.time() - cached.scanned_at < self.settings.cache_ttl:
                return cached
            result = await self._scan(interval)
            self._last[interval] = result
            return result

    async def _scan(self, interval: str) -> ScanResult:
        s = self.settings
        started = time.time()
        symbols = await self.symbols()
        await self.mcap.get()  # warm the market cap cache (failures are logged, not fatal)
        btc = await self.btc_returns(interval)
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
        ranked = [m for m in metrics if m is not None and m.atr_pct >= s.min_atr_pct]
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
        all_symbols = await self.exchange.list_symbols()
        info = next((i for i in all_symbols if i.symbol == symbol), None)
        if info is None:
            return None

        cap = await self._cap(info.symbol)

        async def one(interval: str) -> AtrMetrics | None:
            candles, btc = await asyncio.gather(
                self.exchange.fetch_candles(info, interval, self.settings.candles_needed(interval)),
                self.btc_returns(interval),
            )
            return compute_metrics(info.symbol, candles, self.settings.atr_period, self.settings.lookback_for(interval), info.quote_volume, cap, btc)

        results = await asyncio.gather(*(one(tf) for tf in intervals))
        return dict(zip(intervals, results))

    async def metrics_for(self, symbols: Sequence[str], interval: str) -> dict[str, AtrMetrics | None]:
        """Metrics for a list of symbols on one interval; uses the cached scan when it has them."""
        cached = self._last.get(interval)
        out: dict[str, AtrMetrics | None] = {}
        missing: list[str] = []
        for sym in symbols:
            m = cached.find(sym) if cached else None
            if m is not None:
                out[sym] = m
            else:
                missing.append(sym)
        if missing:
            all_symbols = await self.exchange.list_symbols()
            by_name = {i.symbol: i for i in all_symbols}
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

            for sym, m in zip(missing, await asyncio.gather(*(one(s) for s in missing))):
                out[sym] = m
        return out

    async def candles(self, symbol: str, interval: str, limit: int) -> list[Candle] | None:
        """Raw closed candles for charts. None if the symbol is unknown."""
        symbol = self.normalize_symbol(symbol)
        all_symbols = await self.exchange.list_symbols()
        info = next((i for i in all_symbols if i.symbol == symbol), None)
        if info is None:
            return None
        return await self.exchange.fetch_candles(info, interval, limit)
