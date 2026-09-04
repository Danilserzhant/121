from atr_bot.charts import render_chart
from atr_bot.indicators import Candle


def test_render_chart_png():
    candles = [Candle(i * 3_600_000, 100 + i, 102 + i, 99 + i, 101 + i, 10 + i) for i in range(40)]
    png = render_chart("TESTUSDT", "1h", candles, period=14)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 10_000
