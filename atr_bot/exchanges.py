"""Exchange adapters: list tradable symbols and fetch closed candles.

All adapters use only *public* endpoints — no API keys are needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from .indicators import Candle

log = logging.getLogger(__name__)

_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def interval_ms(interval: str) -> int:
    try:
        return _INTERVAL_MS[interval]
    except KeyError as exc:  # pragma: no cover - config error
        raise ValueError(f"Unsupported interval: {interval}") from exc


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str        # normalized display name, e.g. BTCUSDT
    native: str        # id used by the exchange API, e.g. BTC-USDT-SWAP
    quote_volume: float  # 24h volume in quote asset


class ExchangeError(RuntimeError):
    pass


class BaseExchange:
    name = "base"

    def __init__(self, session: aiohttp.ClientSession, quote_asset: str = "USDT", proxy: str = ""):
        self.session = session
        self.quote_asset = quote_asset.upper()
        self.proxy = proxy or None

    async def _get(self, url: str, params: dict[str, Any] | None = None, retries: int = 3) -> Any:
        delay = 1.0
        for attempt in range(1, retries + 1):
            try:
                async with self.session.get(url, params=params, proxy=self.proxy, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status in (418, 429) or resp.status >= 500:
                        retry_after = float(resp.headers.get("Retry-After", delay))
                        text = await resp.text()
                        if attempt == retries:
                            raise ExchangeError(f"{resp.status} from {url}: {text[:200]}")
                        log.warning("%s -> %s, retry in %.1fs", url, resp.status, retry_after)
                        await asyncio.sleep(retry_after)
                        delay *= 2
                        continue
                    if resp.status != 200:
                        text = await resp.text()
                        raise ExchangeError(f"{resp.status} from {url}: {text[:200]}")
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt == retries:
                    raise ExchangeError(f"network error for {url}: {exc}") from exc
                log.warning("%s -> %s, retry in %.1fs", url, exc, delay)
                await asyncio.sleep(delay)
                delay *= 2
        raise ExchangeError(f"unreachable: {url}")  # pragma: no cover

    async def list_symbols(self) -> list[SymbolInfo]:
        raise NotImplementedError

    async def fetch_candles(self, info: SymbolInfo, interval: str, limit: int) -> list[Candle]:
        raise NotImplementedError

    @staticmethod
    def _drop_open_candle(candles: list[Candle], interval: str) -> list[Candle]:
        """Keep only candles whose close time is already in the past."""
        now = int(time.time() * 1000)
        step = interval_ms(interval)
        return [c for c in candles if c.open_time + step <= now]


# --------------------------------------------------------------------------- Binance

class BinanceBase(BaseExchange):
    hosts: tuple[str, ...] = ()
    exchange_info_path = ""
    ticker_path = ""
    klines_path = ""

    async def _get_any_host(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for host in self.hosts:
            try:
                data = await self._get(host + path, params)
            except ExchangeError as exc:
                last_exc = exc
                log.warning("host %s failed: %s", host, exc)
                continue
            # Binance error payloads are dicts with "code" and "msg" (e.g. geo restriction).
            if isinstance(data, dict) and "code" in data and "msg" in data:
                last_exc = ExchangeError(f"{host}{path}: {data}")
                log.warning("host %s rejected request: %s", host, data)
                continue
            return data
        raise last_exc or ExchangeError("no hosts configured")

    def _symbol_ok(self, s: dict[str, Any]) -> bool:
        raise NotImplementedError

    async def list_symbols(self) -> list[SymbolInfo]:
        info, tickers = await asyncio.gather(
            self._get_any_host(self.exchange_info_path),
            self._get_any_host(self.ticker_path),
        )
        volumes = {t["symbol"]: float(t.get("quoteVolume", 0.0)) for t in tickers}
        out = []
        for s in info["symbols"]:
            if not self._symbol_ok(s):
                continue
            sym = s["symbol"]
            out.append(SymbolInfo(symbol=sym, native=sym, quote_volume=volumes.get(sym, 0.0)))
        return out

    async def fetch_candles(self, info: SymbolInfo, interval: str, limit: int) -> list[Candle]:
        raw = await self._get_any_host(self.klines_path, {"symbol": info.native, "interval": interval, "limit": limit + 1})
        candles = [
            Candle(open_time=int(k[0]), open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]), volume=float(k[5]))
            for k in raw
        ]
        candles.sort(key=lambda c: c.open_time)
        return self._drop_open_candle(candles, interval)


class BinanceFutures(BinanceBase):
    name = "binance_futures"
    hosts = ("https://fapi.binance.com",)
    exchange_info_path = "/fapi/v1/exchangeInfo"
    ticker_path = "/fapi/v1/ticker/24hr"
    klines_path = "/fapi/v1/klines"

    def _symbol_ok(self, s: dict[str, Any]) -> bool:
        return (
            s.get("quoteAsset") == self.quote_asset
            and s.get("status") == "TRADING"
            and s.get("contractType") == "PERPETUAL"
        )


_LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


class BinanceSpot(BinanceBase):
    name = "binance_spot"
    # data-api.binance.vision serves the same public market data and is not geo-fenced.
    hosts = ("https://api.binance.com", "https://data-api.binance.vision")
    exchange_info_path = "/api/v3/exchangeInfo"
    ticker_path = "/api/v3/ticker/24hr"
    klines_path = "/api/v3/klines"

    def _symbol_ok(self, s: dict[str, Any]) -> bool:
        base = s.get("baseAsset", "")
        return (
            s.get("quoteAsset") == self.quote_asset
            and s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed", True)
            and not base.endswith(_LEVERAGED_SUFFIXES)
        )


# --------------------------------------------------------------------------- Bybit

class Bybit(BaseExchange):
    name = "bybit"
    host = "https://api.bybit.com"
    _intervals = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720", "1d": "D", "1w": "W"}

    async def _v5(self, path: str, params: dict[str, Any]) -> Any:
        data = await self._get(self.host + path, params)
        if data.get("retCode") != 0:
            raise ExchangeError(f"bybit {path}: {data.get('retMsg')}")
        return data["result"]

    async def list_symbols(self) -> list[SymbolInfo]:
        instruments: list[dict[str, Any]] = []
        cursor = ""
        while True:
            params: dict[str, Any] = {"category": "linear", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            res = await self._v5("/v5/market/instruments-info", params)
            instruments.extend(res.get("list", []))
            cursor = res.get("nextPageCursor") or ""
            if not cursor:
                break
        tickers = await self._v5("/v5/market/tickers", {"category": "linear"})
        turnover = {t["symbol"]: float(t.get("turnover24h") or 0.0) for t in tickers.get("list", [])}
        out = []
        for i in instruments:
            if i.get("quoteCoin") != self.quote_asset or i.get("status") != "Trading" or i.get("contractType") != "LinearPerpetual":
                continue
            sym = i["symbol"]
            out.append(SymbolInfo(symbol=sym, native=sym, quote_volume=turnover.get(sym, 0.0)))
        return out

    async def fetch_candles(self, info: SymbolInfo, interval: str, limit: int) -> list[Candle]:
        res = await self._v5(
            "/v5/market/kline",
            {"category": "linear", "symbol": info.native, "interval": self._intervals[interval], "limit": min(limit + 1, 1000)},
        )
        candles = [
            Candle(open_time=int(k[0]), open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]), volume=float(k[5]))
            for k in res.get("list", [])
        ]
        candles.sort(key=lambda c: c.open_time)
        return self._drop_open_candle(candles, interval)


# --------------------------------------------------------------------------- OKX

class Okx(BaseExchange):
    name = "okx"
    host = "https://www.okx.com"
    _bars = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6Hutc", "12h": "12Hutc", "1d": "1Dutc", "1w": "1Wutc"}

    async def _v5(self, path: str, params: dict[str, Any]) -> Any:
        data = await self._get(self.host + path, params)
        if data.get("code") != "0":
            raise ExchangeError(f"okx {path}: {data.get('msg')}")
        return data["data"]

    async def list_symbols(self) -> list[SymbolInfo]:
        instruments, tickers = await asyncio.gather(
            self._v5("/api/v5/public/instruments", {"instType": "SWAP"}),
            self._v5("/api/v5/market/tickers", {"instType": "SWAP"}),
        )
        # volCcy24h for swaps is in base currency; multiply by last price to get quote volume.
        quote_vol: dict[str, float] = {}
        for t in tickers:
            try:
                quote_vol[t["instId"]] = float(t.get("volCcy24h") or 0.0) * float(t.get("last") or 0.0)
            except (TypeError, ValueError):
                continue
        out = []
        for i in instruments:
            if i.get("settleCcy") != self.quote_asset or i.get("state") != "live" or i.get("ctType") != "linear":
                continue
            inst_id = i["instId"]  # BTC-USDT-SWAP
            base = inst_id.split("-")[0]
            out.append(SymbolInfo(symbol=f"{base}{self.quote_asset}", native=inst_id, quote_volume=quote_vol.get(inst_id, 0.0)))
        return out

    async def fetch_candles(self, info: SymbolInfo, interval: str, limit: int) -> list[Candle]:
        data = await self._v5(
            "/api/v5/market/candles",
            {"instId": info.native, "bar": self._bars[interval], "limit": min(limit + 1, 300)},
        )
        candles = [
            Candle(open_time=int(k[0]), open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]), volume=float(k[5]))
            for k in data
            if len(k) < 9 or k[8] == "1"  # confirm flag: "1" = candle closed
        ]
        candles.sort(key=lambda c: c.open_time)
        return self._drop_open_candle(candles, interval)


EXCHANGES: dict[str, type[BaseExchange]] = {
    BinanceFutures.name: BinanceFutures,
    BinanceSpot.name: BinanceSpot,
    Bybit.name: Bybit,
    Okx.name: Okx,
}


def make_exchange(name: str, session: aiohttp.ClientSession, quote_asset: str, proxy: str = "") -> BaseExchange:
    try:
        cls = EXCHANGES[name.lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown exchange '{name}'. Available: {', '.join(EXCHANGES)}") from exc
    return cls(session, quote_asset=quote_asset, proxy=proxy)
