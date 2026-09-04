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
    atr: float            # current ATR in price units
    atr_pct: float        # ATR as % of price  ("clean" average hourly move)
    atr_prev: float       # ATR `lookback` candles ago
    atr_prev_pct: float
    expansion_pct: float  # (atr / atr_prev - 1) * 100
    last_tr_pct: float    # true range of the last closed candle in % of price
    last_tr_ratio: float  # last_tr / atr_prev  (how many "old" ATRs the last bar moved)
    move_pct: float       # net close-to-close move over the lookback window, %
    quote_volume: float   # 24h quote volume
    candle_time: int      # open time (ms) of the last candle used


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
    atrs = wilder_atr(trs, period)
    now_i = len(candles) - 1
    prev_i = now_i - lookback
    atr_now = atrs[now_i]
    atr_prev = atrs[prev_i]
    if atr_now is None or atr_prev is None or atr_prev <= 0:
        return None
    last = candles[now_i]
    prev_close = candles[prev_i].close
    if last.close <= 0 or prev_close <= 0:
        return None
    return AtrMetrics(
        symbol=symbol,
        close=last.close,
        atr=atr_now,
        atr_pct=atr_now / last.close * 100,
        atr_prev=atr_prev,
        atr_prev_pct=atr_prev / prev_close * 100,
        expansion_pct=(atr_now / atr_prev - 1) * 100,
        last_tr_pct=trs[now_i] / last.close * 100,
        last_tr_ratio=trs[now_i] / atr_prev,
        move_pct=(last.close / prev_close - 1) * 100,
        quote_volume=quote_volume,
        candle_time=last.open_time,
    )
