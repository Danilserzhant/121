"""Scan every symbol on the exchange and rank by ATR expansion."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import aiohttp

from .config import Settings
from .exchanges import BaseExchange, ExchangeError, SymbolInfo, make_exchange
from .indicators import AtrMetrics, compute_metrics

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
    ranked: list[AtrMetrics] = field(default_factory=list)  # sorted by expansion desc
    errors: int = 0
    duration: float = 0.0

    def top(self, n: int) -> list[AtrMetrics]:
        return self.ranked[:n]

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
        self._lock = asyncio.Lock()
        self._last: ScanResult | None = None
        self._symbols_cache: tuple[float, list[SymbolInfo]] | None = None

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

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
            self._exchange = None

    @property
    def exchange(self) -> BaseExchange:
        if self._exchange is None:
            raise RuntimeError("Scanner is not opened")
        return self._exchange

    @property
    def last(self) -> ScanResult | None:
        return self._last

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

    async def scan(self, force: bool = False) -> ScanResult:
        """Run a full scan, or return the cached result if it is fresh enough."""
        async with self._lock:
            if (
                not force
                and self._last is not None
                and time.time() - self._last.scanned_at < self.settings.cache_ttl
            ):
                return self._last
            result = await self._scan()
            self._last = result
            return result

    async def _scan(self) -> ScanResult:
        s = self.settings
        started = time.time()
        symbols = await self.symbols()
        sem = asyncio.Semaphore(s.concurrency)
        limit = s.candles_needed()
        errors = 0

        async def one(info: SymbolInfo) -> AtrMetrics | None:
            nonlocal errors
            async with sem:
                try:
                    candles = await self.exchange.fetch_candles(info, s.interval, limit)
                except ExchangeError as exc:
                    errors += 1
                    log.warning("%s: %s", info.symbol, exc)
                    return None
            return compute_metrics(info.symbol, candles, s.atr_period, s.lookback, info.quote_volume)

        metrics = await asyncio.gather(*(one(i) for i in symbols))
        ranked = [m for m in metrics if m is not None and m.atr_pct >= s.min_atr_pct]
        ranked.sort(key=lambda m: m.expansion_pct, reverse=True)
        result = ScanResult(
            exchange=self.exchange.name,
            interval=s.interval,
            atr_period=s.atr_period,
            lookback=s.lookback,
            scanned_at=time.time(),
            total_symbols=len(symbols),
            ranked=ranked,
            errors=errors,
            duration=time.time() - started,
        )
        log.info("scan done: %d ranked / %d symbols, %d errors, %.1fs", len(ranked), len(symbols), errors, result.duration)
        return result

    async def symbol_metrics(self, symbol: str) -> AtrMetrics | None:
        """Fresh metrics for one symbol (bypasses volume filter)."""
        symbol = symbol.upper().replace("-", "").replace("/", "")
        if not symbol.endswith(self.settings.quote_asset):
            symbol += self.settings.quote_asset
        all_symbols = await self.exchange.list_symbols()
        info = next((i for i in all_symbols if i.symbol == symbol), None)
        if info is None:
            return None
        candles = await self.exchange.fetch_candles(info, self.settings.interval, self.settings.candles_needed())
        return compute_metrics(info.symbol, candles, self.settings.atr_period, self.settings.lookback, info.quote_volume)
