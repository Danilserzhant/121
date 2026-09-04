from datetime import datetime

from atr_bot.extras import in_quiet


def test_in_quiet_overnight_and_daytime():
    p = {"quiet_on": True, "quiet_start": 23, "quiet_end": 8, "tz": 0}
    assert in_quiet(p, datetime(2026, 1, 1, 23, 30))
    assert in_quiet(p, datetime(2026, 1, 1, 3))
    assert not in_quiet(p, datetime(2026, 1, 1, 8))
    assert not in_quiet(p, datetime(2026, 1, 1, 12))
    day = {**p, "quiet_start": 1, "quiet_end": 6}
    assert in_quiet(day, datetime(2026, 1, 1, 3)) and not in_quiet(day, datetime(2026, 1, 1, 23))
    assert not in_quiet({**p, "quiet_on": False}, datetime(2026, 1, 1, 3))
    assert not in_quiet({**p, "quiet_start": 5, "quiet_end": 5}, datetime(2026, 1, 1, 5))
