"""Candlestick + ATR% chart rendered to PNG bytes with matplotlib."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .indicators import Candle, atr_pct_series, true_ranges_pct  # noqa: E402

UP, DOWN, ATR_COLOR, TR_COLOR, SPIKE_COLOR = "#26a69a", "#ef5350", "#ff9800", "#546e7a", "#ffca28"


def render_chart(symbol: str, interval: str, candles: Sequence[Candle], period: int, spike_ratio: float = 2.0) -> bytes:
    """Return PNG bytes: price candles on top, ATR% and per-candle TR% below.

    TR bars bigger than `spike_ratio` × previous ATR are highlighted as breakouts.
    """
    if len(candles) < 2:
        raise ValueError("not enough candles")
    step_days = (candles[1].open_time - candles[0].open_time) / 86_400_000
    xs = [datetime.fromtimestamp(c.open_time / 1000, tz=timezone.utc) for c in candles]
    atr = atr_pct_series(candles, period)
    trs = true_ranges_pct(candles)

    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), dpi=110, sharex=True, gridspec_kw={"height_ratios": [3, 1.3], "hspace": 0.05}
    )
    fig.patch.set_facecolor("#131722")
    for ax in (ax1, ax2):
        ax.set_facecolor("#131722")
        ax.grid(True, color="#2a2e39", linewidth=0.6)
        ax.tick_params(colors="#b2b5be", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#2a2e39")

    width = step_days * 0.7
    for x, c in zip(xs, candles):
        color = UP if c.close >= c.open else DOWN
        ax1.vlines(x, c.low, c.high, color=color, linewidth=0.9)
        body_low, body_h = min(c.open, c.close), abs(c.close - c.open)
        ax1.bar(x, body_h or (c.high - c.low) * 0.002, bottom=body_low, width=width, color=color, align="center")
    last = candles[-1]
    ax1.axhline(last.close, color="#b2b5be", linewidth=0.6, linestyle="--")
    chg = (last.close / candles[-2].close - 1) * 100
    ax1.set_title(f"{symbol}   {interval}   close {last.close:g}  ({chg:+.2f}%)", color="#e0e3eb", fontsize=12, loc="left", fontweight="bold")
    hi, lo = max(c.high for c in candles), min(c.low for c in candles)
    ax1.axhline(hi, color=UP, linewidth=0.5, linestyle=":", alpha=0.7)
    ax1.axhline(lo, color=DOWN, linewidth=0.5, linestyle=":", alpha=0.7)
    ax1.annotate(f"{hi:g}", xy=(xs[-1], hi), xytext=(4, 0), textcoords="offset points", color=UP, fontsize=8, va="center")
    ax1.annotate(f"{lo:g}", xy=(xs[-1], lo), xytext=(4, 0), textcoords="offset points", color=DOWN, fontsize=8, va="center")
    ax1.set_ylabel("price", color="#b2b5be")

    colors = []
    for i, tr in enumerate(trs):
        prev_atr = atr[i - 1] if i > 0 else None
        colors.append(SPIKE_COLOR if prev_atr and tr >= spike_ratio * prev_atr else TR_COLOR)
    ax2.bar(xs, trs, width=width, color=colors, alpha=0.8, label="TR % свечи")
    ax2.bar([], [], color=SPIKE_COLOR, label=f"свеча ≥ {spike_ratio:g}× ATR")
    ax2.plot(xs, [v if v is not None else float("nan") for v in atr], color=ATR_COLOR, linewidth=1.6, label=f"ATR({period}) %")
    ax2.set_ylabel("%", color="#b2b5be")
    ax2.legend(loc="upper left", fontsize=8, frameon=False, labelcolor="#e0e3eb")
    last_atr = next((v for v in reversed(atr) if v is not None), None)
    if last_atr is not None:
        ax2.annotate(f"{last_atr:.2f}%", xy=(xs[-1], last_atr), xytext=(4, 0), textcoords="offset points",
                     color=ATR_COLOR, fontsize=9, va="center")

    locator = mdates.AutoDateLocator(minticks=5, maxticks=10)
    ax2.xaxis.set_major_locator(locator)
    ax2.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax1.set_xlim(xs[0] - (xs[1] - xs[0]), xs[-1] + (xs[1] - xs[0]) * 3)

    buf = io.BytesIO()
    fig.text(0.99, 0.01, "ATR Bot", color="#4a4f5c", fontsize=8, ha="right", va="bottom")
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
