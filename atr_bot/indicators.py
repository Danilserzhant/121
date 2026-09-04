"""Pure-python ATR math. No dependencies so it is easy to unit test."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Candle:
    open_time: int  # ms
    open: float
    high: float
    low: float
    close: float
    volume: float


def true_ranges(candles: Sequence[Candle]) -> list[float]:
    """True range for every candle (first candle uses high-low only)."""
    out: list[float] = []
    prev_close: float | None = None
    for c in candles:
        if prev_close is None:
            tr = c.high - c.low
        else:
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        out.append(tr)
        prev_close = c.close
    return out


def true_ranges_pct(candles: Sequence[Candle]) -> list[float]:
    """True range of every candle as % of the previous close (first: of its own open).

    Averaging percentages instead of price units keeps ATR% meaningful when the
    price level changes a lot inside the window (pumps, crashes, new listings).
    """
    out: list[float] = []
    prev_close: float | None = None
    for c, tr in zip(candles, true_ranges(candles)):
        base = prev_close if prev_close else c.open
        out.append(tr / base * 100 if base > 0 else 0.0)
        prev_close = c.close
    return out


def wilder_atr(trs: Sequence[float], period: int) -> list[float | None]:
    """Wilder's smoothed ATR. Returns None for indexes before the first full period."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = [None] * len(trs)
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period - 1] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


@dataclass(frozen=True)
class AtrMetrics:
    symbol: str
    close: float
    atr: float            # current ATR in price units (Wilder on raw true ranges)
    atr_pct: float        # ATR of per-candle true ranges in % of price ("clean" average move)
    atr_prev: float       # ATR (price units) `lookback` candles ago
    atr_prev_pct: float   # ATR% `lookback` candles ago
    expansion_pct: float  # (atr_pct / atr_prev_pct - 1) * 100
    last_tr_pct: float    # true range of the last closed candle in % of price
    last_tr_ratio: float  # last_tr_pct / atr_prev_pct (how many "old" ATRs the last bar moved)
    move_pct: float       # net close-to-close move over the lookback window, %
    vol_ratio: float      # last candle volume / average volume of the lookback window
    quote_volume: float   # 24h quote volume
    candle_time: int      # open time (ms) of the last candle used

    @property
    def direction(self) -> str:
        return "long" if self.move_pct > 0 else "short" if self.move_pct < 0 else "flat"


def compute_metrics(
    symbol: str,
    candles: Sequence[Candle],
    period: int,
    lookback: int,
    quote_volume: float = 0.0,
) -> AtrMetrics | None:
    """Compute ATR expansion metrics for one symbol.

    `candles` must be sorted ascending and contain only *closed* candles.
    Returns None if there is not enough history.
    """
    if len(candles) < period + lookback + 1:
        return None
    trs = true_ranges(candles)
    trs_pct = true_ranges_pct(candles)
    atrs = wilder_atr(trs, period)
    atrs_pct = wilder_atr(trs_pct, period)
    now_i = len(candles) - 1
    prev_i = now_i - lookback
    atr_now, atr_prev = atrs[now_i], atrs[prev_i]
    atr_now_pct, atr_prev_pct = atrs_pct[now_i], atrs_pct[prev_i]
    if None in (atr_now, atr_prev, atr_now_pct, atr_prev_pct) or atr_prev_pct <= 0:
        return None
    last = candles[now_i]
    prev_close = candles[prev_i].close
    if last.close <= 0 or prev_close <= 0:
        return None
    window = candles[prev_i:now_i]
    avg_vol = sum(c.volume for c in window) / len(window) if window else 0.0
    vol_ratio = last.volume / avg_vol if avg_vol > 0 else 0.0
    return AtrMetrics(
        symbol=symbol,
        close=last.close,
        atr=atr_now,
        atr_pct=atr_now_pct,
        atr_prev=atr_prev,
        atr_prev_pct=atr_prev_pct,
        expansion_pct=(atr_now_pct / atr_prev_pct - 1) * 100,
        last_tr_pct=trs_pct[now_i],
        last_tr_ratio=trs_pct[now_i] / atr_prev_pct,
        move_pct=(last.close / prev_close - 1) * 100,
        vol_ratio=vol_ratio,
        quote_volume=quote_volume,
        candle_time=last.open_time,
    )


def atr_pct_series(candles: Sequence[Candle], period: int) -> list[float | None]:
    """ATR% for every candle (used for charts)."""
    return wilder_atr(true_ranges_pct(candles), period)
