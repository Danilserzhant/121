"""Render every message type from synthetic data so template errors are caught without Telegram."""
import time

from atr_bot.formatting import (
    format_breakouts, format_digest, format_overlap, format_presets, format_prefs, format_queued, format_symbol,
    format_top, format_watch_alert, format_watchlist,
)
from atr_bot.indicators import AtrMetrics
from atr_bot.scanner import ScanResult


def m(sym, atr=3.0, exp=20.0, move=5.0, corr=0.3, cap=1e8):
    return AtrMetrics(symbol=sym, close=1.5, atr=0.05, atr_pct=atr, atr_prev=0.04, atr_prev_pct=atr / 1.2,
                      expansion_pct=exp, last_tr_pct=4.0, last_tr_ratio=2.1, move_pct=move, vol_ratio=1.7,
                      quote_volume=5e7, candle_time=1_700_000_000_000, market_cap=cap, btc_corr=corr, corr_points=60,
                      funding=0.0006, oi_usd=2e7, oi_change_24h=8.0)


def result(interval="1h"):
    return ScanResult(exchange="okx", interval=interval, atr_period=14, lookback=24, scanned_at=time.time(),
                      total_symbols=3, ranked=[m("AAAUSDT", 5, 50, 9, 0.1), m("BBBUSDT", 4, -10, -3, 0.8, 0), m("CCCUSDT", 3)])


def test_render_all_messages():
    r = result()
    streaks = {"AAAUSDT": 3, "BBBUSDT": 1, "CCCUSDT": 0}
    for view in ("list", "table"):
        for by in ("atr", "expansion", "corr", "corrhi"):
            for corr in ("any", "lo", "hi"):
                text = format_top(r, 10, by, "all", streaks, view, 1e6, 0, corr)
                assert any(x in text for x in ("AAA", "BBB", "CCC")) or "Ничего" in text
    assert "<" not in format_top(r, 10, "atr", "all", {}, "list", 0, 0, "lo").replace("<b>", "").replace("</b>", "") \
        .replace("<i>", "").replace("</i>", "").replace("<a ", "").replace("</a>", "").replace("<code>", "").replace("</code>", "")
    assert format_top(r, 10, "atr", "short", {}, "list", 0, 5e9) .endswith("фильтр.")
    assert "AAAUSDT" in format_symbol("AAAUSDT", {"1h": m("AAAUSDT"), "4h": None}, {"1h": (1, 3)}, watched=True)
    assert "Свеча-выброс" in format_breakouts(r.ranked, "1h", 2.5)
    assert "AAAUSDT" in format_watch_alert(m("AAAUSDT"), "1h", ["причина"])
    assert "Мои монеты" in format_watchlist(["AAAUSDT", "ZZZUSDT"], {"AAAUSDT": m("AAAUSDT")}, "1h")
    assert "пуст" in format_watchlist([], {}, "1h")
    assert "AAA" in format_overlap([("AAAUSDT", {"1h": m("AAAUSDT"), "4h": m("AAAUSDT")})], ["1h", "4h", "1d"], 30)
    assert "пересечений" in format_overlap([], ["1h", "4h", "1d"], 30)
    assert "Лонги" in format_presets([{"name": "Лонги", "interval": "4h", "by": "atr", "direction": "long", "min_cap": 3e8, "corr": "lo", "auto": True}])
    assert "пусто" in format_presets([]).lower()
    prefs = {"tz": 3, "quiet_on": True, "quiet_start": 23, "quiet_end": 8, "digest_on": True, "digest_hour": 8}
    assert "UTC+3" in format_prefs(prefs, 2)
    queued = [{"ts": 1.0, "kind": "watch", "text": "x"}] * 3
    assert "Доброе утро" in format_digest("Иван", "top", queued, 4, ["line"])
    assert len(format_queued(queued)) == 1
