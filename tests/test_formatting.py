from atr_bot.config import Settings
from atr_bot.bot import _parse_top_args
from atr_bot.formatting import fmt_big, parse_amount, parse_direction, parse_filter, parse_timeframe


def test_parse_helpers():
    assert parse_timeframe("4h") == "4h" and parse_timeframe("день") == "1d" and parse_timeframe("x") is None
    assert parse_direction("лонг") == "long" and parse_direction("short") == "short"
    assert parse_amount("20m") == 20e6 and parse_amount("1.5b") == 1.5e9 and parse_amount("500k") == 500e3
    assert parse_amount("5000000") == 5e6 and parse_amount("abc") is None
    assert parse_filter("vol>20m") == ("vol", 20e6)
    assert parse_filter("cap1b") == ("cap", 1e9)
    assert parse_filter("капа") == ("cap", None)
    assert parse_filter("foo") is None


def test_parse_top_args():
    s = Settings()
    q = _parse_top_args("4h 20 long vol 20m cap>1b table сами", s, "atr")
    assert (q.interval, q.n, q.direction, q.view, q.min_volume, q.min_cap, q.corr) == ("4h", 20, "long", "table", 20e6, 1e9, "lo")
    assert _parse_top_args("вместе", s, "atr").corr == "hi" and _parse_top_args("ρ<0.5", s, "atr").corr == "mid"
    assert _parse_top_args("", s, "expansion").by == "expansion"
    assert _parse_top_args("garbage", s, "atr") is None
    assert _parse_top_args("cap", s, "atr") is None  # missing value


def test_fmt_big():
    assert fmt_big(20e6) == "20M" and fmt_big(1.5e9) == "1.5B" and fmt_big(72_600_000) == "72.6M"
    assert fmt_big(500_000) == "500K"
