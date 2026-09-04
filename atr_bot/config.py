"""Configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _env_lookbacks(name: str, default: dict[str, int]) -> dict[str, int]:
    """Parse '1h:24,4h:6,1d:7,1w:4' into a dict, falling back to defaults."""
    out = dict(default)
    raw = os.getenv(name, "")
    for part in raw.replace(";", ",").split(","):
        if ":" in part:
            tf, n = part.split(":", 1)
            try:
                out[tf.strip()] = int(n)
            except ValueError:
                continue
    return out


def _env_list_int(name: str) -> list[int]:
    raw = os.getenv(name, "")
    return [int(x) for x in raw.replace(";", ",").split(",") if x.strip()]


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    # Exchange: binance_futures | binance_spot | bybit | okx
    exchange: str = field(default_factory=lambda: os.getenv("EXCHANGE", "binance_futures"))
    quote_asset: str = field(default_factory=lambda: os.getenv("QUOTE_ASSET", "USDT"))
    # Default candle interval for /top and the auto push.
    interval: str = field(default_factory=lambda: os.getenv("INTERVAL", "1h"))
    # Timeframes users can ask for.
    intervals: tuple[str, ...] = ("1h", "4h", "1d", "1w")
    # ATR period in candles.
    atr_period: int = field(default_factory=lambda: _env_int("ATR_PERIOD", 14))
    # How many candles back to compare the current ATR against ("expansion"), per timeframe.
    lookbacks: dict[str, int] = field(
        default_factory=lambda: _env_lookbacks("EXPANSION_LOOKBACK", {"1h": 24, "4h": 6, "1d": 7, "1w": 4})
    )
    # How many coins to show by default.
    top_n: int = field(default_factory=lambda: _env_int("TOP_N", 15))
    # Filter out illiquid coins: minimum 24h quote volume (in quote asset).
    min_quote_volume: float = field(default_factory=lambda: _env_float("MIN_QUOTE_VOLUME", 5_000_000))
    # Minimum ATR% (average hourly move) to be listed at all.
    min_atr_pct: float = field(default_factory=lambda: _env_float("MIN_ATR_PCT", 0.0))
    # Max parallel kline requests to the exchange.
    concurrency: int = field(default_factory=lambda: _env_int("CONCURRENCY", 16))
    # Cache scan results for this many seconds (protects from /top spam).
    cache_ttl: int = field(default_factory=lambda: _env_int("CACHE_TTL", 60))
    # Seconds after the hourly candle close to wait before the auto scan.
    close_delay: int = field(default_factory=lambda: _env_int("CLOSE_DELAY", 20))
    # Breakout alert: last closed candle's true range >= this many "old" ATRs …
    alert_tr_ratio: float = field(default_factory=lambda: _env_float("ALERT_TR_RATIO", 2.5))
    # … and at least this big in % of price (filters noise on dead coins).
    alert_min_tr_pct: float = field(default_factory=lambda: _env_float("ALERT_MIN_TR_PCT", 1.0))
    # Watchlist alerts: candle >= this many old ATRs, or ATR% grew by this many % vs the lookback.
    watch_tr_ratio: float = field(default_factory=lambda: _env_float("WATCH_TR_RATIO", 2.0))
    watch_expansion_pct: float = field(default_factory=lambda: _env_float("WATCH_EXPANSION_PCT", 50.0))
    # How many symbols per interval to remember for "how long in the top" streaks.
    history_top: int = field(default_factory=lambda: _env_int("HISTORY_TOP", 20))
    # Market cap cache lifetime, seconds (CoinPaprika / CoinGecko).
    mcap_ttl: int = field(default_factory=lambda: _env_int("MCAP_TTL", 1800))
    # Overlap view: a coin must be in the top-N by ATR% on several timeframes.
    overlap_top: int = field(default_factory=lambda: _env_int("OVERLAP_TOP", 30))
    # Chart: number of candles to draw.
    chart_candles: int = field(default_factory=lambda: _env_int("CHART_CANDLES", 120))
    # Telegram user id of the bot owner. If empty, the first person who sends
    # /start to a fresh bot becomes the owner.
    owner_id: int = field(default_factory=lambda: _env_int("OWNER_ID", 0))
    # Extra admin user ids granted on startup (comma separated).
    admin_ids: list[int] = field(default_factory=lambda: _env_list_int("ADMIN_IDS"))
    # Where the subscriber list is stored.
    storage_path: str = field(default_factory=lambda: os.getenv("STORAGE_PATH", "data/store.json"))
    # TradingView symbol template override, e.g. "BINANCE:{sym}.P" (default depends on EXCHANGE).
    tv_symbol: str = field(default_factory=lambda: os.getenv("TV_SYMBOL", ""))
    # Optional HTTP(S) proxy for the exchange API (useful where Binance is geo-blocked).
    exchange_proxy: str = field(default_factory=lambda: os.getenv("EXCHANGE_PROXY", ""))

    def lookback_for(self, interval: str) -> int:
        return self.lookbacks.get(interval, self.lookbacks.get(self.interval, 24))

    def candles_needed(self, interval: str) -> int:
        # Enough history for a stable Wilder ATR before the lookback window.
        # Exchanges return fewer candles for young coins; the metric still works
        # with atr_period + lookback + 1 candles.
        return self.atr_period * 3 + self.lookback_for(interval) + 2


settings = Settings()
