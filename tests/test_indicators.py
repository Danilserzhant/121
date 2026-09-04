from atr_bot.indicators import Candle, compute_metrics, true_ranges, true_ranges_pct, wilder_atr


def mk(i, o, h, l, c):
    return Candle(open_time=i * 3_600_000, open=o, high=h, low=l, close=c, volume=1.0)


def test_true_range_uses_previous_close():
    candles = [mk(0, 10, 11, 9, 10), mk(1, 12, 13, 12, 12.5)]  # gap up
    trs = true_ranges(candles)
    assert trs[0] == 2.0
    assert trs[1] == 13 - 10  # high - prev close dominates


def test_wilder_atr_smoothing():
    trs = [1.0] * 14 + [15.0]
    atrs = wilder_atr(trs, 14)
    assert atrs[12] is None
    assert atrs[13] == 1.0
    assert abs(atrs[14] - (1.0 * 13 + 15.0) / 14) < 1e-12


def test_compute_metrics_expansion():
    period, lookback = 3, 2
    # quiet candles then a burst
    quiet = [mk(i, 100, 101, 99, 100) for i in range(6)]
    burst = [mk(6, 100, 110, 90, 105), mk(7, 105, 120, 95, 110)]
    m = compute_metrics("TESTUSDT", quiet + burst, period, lookback, quote_volume=1e6)
    assert m is not None
    assert m.symbol == "TESTUSDT"
    assert m.expansion_pct > 100  # ATR more than doubled
    assert m.atr_pct > m.atr_prev_pct
    assert abs(m.move_pct - (110 / 100 - 1) * 100) < 1e-9
    assert abs(m.last_tr_pct - 25 / 105 * 100) < 1e-9  # % of previous close
    assert m.vol_ratio == 1.0  # all volumes equal
    assert m.direction == "long"


def test_atr_pct_is_scale_invariant():
    """A crash from 100 to 1 must not inflate ATR% via stale high-priced candles."""
    period, lookback = 3, 2
    calm_high = [mk(i, 100, 101, 99, 100) for i in range(4)]
    crash = [mk(4, 100, 100, 1, 1)]
    calm_low = [mk(5 + i, 1, 1.01, 0.99, 1) for i in range(6)]
    m = compute_metrics("X", calm_high + crash + calm_low, period, lookback)
    assert m is not None
    assert m.atr_pct < 40  # Wilder memory of the crash candle decays, price-unit ATR would give ~2000%
    assert true_ranges_pct(calm_low[:2])[1] == (1.01 - 0.99) / 1 * 100


def test_compute_metrics_needs_history():
    candles = [mk(i, 1, 2, 0.5, 1) for i in range(5)]
    assert compute_metrics("X", candles, period=14, lookback=24) is None
