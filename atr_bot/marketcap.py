"""Market capitalisation lookup by ticker (CoinPaprika, CoinGecko as fallback), cached."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

log = logging.getLogger(__name__)

PAPRIKA_URL = "https://api.coinpaprika.com/v1/tickers?quotes=USD"
GECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"


class MarketCapProvider:
    """symbol (e.g. 'SOL') -> market cap in USD. Refreshes at most every `ttl` seconds."""

    def __init__(self, session: aiohttp.ClientSession, ttl: int = 1800, proxy: str = ""):
        self.session = session
        self.ttl = ttl
        self.proxy = proxy or None
        self._caps: dict[str, float] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return bool(self._caps)

    async def get(self) -> dict[str, float]:
        if self._caps and time.time() - self._fetched_at < self.ttl:
            return self._caps
        async with self._lock:
            if self._caps and time.time() - self._fetched_at < self.ttl:
                return self._caps
            for fetch in (self._paprika, self._gecko):
                try:
                    caps = await fetch()
                except Exception as exc:  # noqa: BLE001 - any source failure -> try next
                    log.warning("market cap source %s failed: %s", fetch.__name__, exc)
                    continue
                if caps:
                    self._caps, self._fetched_at = caps, time.time()
                    log.info("market caps loaded: %d symbols via %s", len(caps), fetch.__name__.lstrip("_"))
                    break
            else:
                self._fetched_at = time.time() - self.ttl + 120  # retry in 2 minutes, keep stale data
            return self._caps

    def cap(self, symbol: str, quote: str = "USDT") -> float:
        """Market cap for a pair symbol like 'SOLUSDT' (0 if unknown)."""
        base = symbol.removesuffix(quote)
        if base.startswith("1000") and base[4:] in self._caps:  # 1000PEPE, 1000SHIB futures tickers
            base = base[4:]
        return self._caps.get(base.upper(), 0.0)

    async def _paprika(self) -> dict[str, float]:
        async with self.session.get(PAPRIKA_URL, proxy=self.proxy, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        caps: dict[str, float] = {}
        for t in data:
            try:
                cap = float(t["quotes"]["USD"]["market_cap"] or 0)
            except (KeyError, TypeError, ValueError):
                continue
            sym = str(t.get("symbol", "")).upper()
            if cap > 0 and cap > caps.get(sym, 0.0):  # same ticker on several coins: keep the biggest
                caps[sym] = cap
        return caps

    async def _gecko(self) -> dict[str, float]:
        caps: dict[str, float] = {}
        for page in range(1, 5):  # top 1000
            params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": page}
            async with self.session.get(GECKO_URL, params=params, proxy=self.proxy, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 429:
                    await asyncio.sleep(3)
                    continue
                resp.raise_for_status()
                data = await resp.json(content_type=None)
            for t in data:
                cap = float(t.get("market_cap") or 0)
                sym = str(t.get("symbol", "")).upper()
                if cap > 0 and cap > caps.get(sym, 0.0):
                    caps[sym] = cap
            await asyncio.sleep(1.5)
        return caps
