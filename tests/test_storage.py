import asyncio

from atr_bot.storage import ROLE_ADMIN, ROLE_OWNER, ROLE_TRADER, Store


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_roles_and_persistence(tmp_path):
    path = str(tmp_path / "store.json")
    s = Store(path)
    assert not s.has_owner()
    run(s.set_role(1, ROLE_OWNER))
    run(s.set_role(2, ROLE_ADMIN, added_by=1))
    run(s.touch(3, "trader_joe", "Joe"))
    assert s.pending()[0][0] == 3
    assert s.resolve("@Trader_Joe") == 3
    assert s.resolve("3") == 3
    assert s.resolve("@nobody") is None
    run(s.set_role(3, ROLE_TRADER, added_by=2))
    assert s.pending() == []
    run(s.subscribe(-100, "1h"))
    run(s.subscribe(-100, "alerts"))
    run(s.watch_add(3, "SOLUSDT"))

    s2 = Store(path)  # reload from disk
    assert s2.is_owner(1) and s2.is_admin(2) and not s2.is_admin(3)
    assert s2.has_access(3) and not s2.has_access(4)
    assert s2.users[3].username == "trader_joe"
    assert s2.subscribed("1h") == [-100] and s2.subscribed("alerts") == [-100] and s2.subscribed("1d") == []
    assert run(s2.unsubscribe(-100, "alerts")) == {"alerts"}
    assert s2.chat_subs(-100) == {"1h"}
    assert s2.watchlist(3) == ["SOLUSDT"] and s2.all_watched() == {"SOLUSDT"}
    assert run(s2.remove_user(3)).id == 3
    assert not s2.has_access(3)
    assert s2.all_watched() == set()


def test_legacy_subscribers_file(tmp_path):
    path = tmp_path / "store.json"
    path.write_text('{"chats": [5, 6]}')
    s = Store(str(path))
    assert s.subscribed("1h") == [5, 6]
    assert s.users == {}


def test_top_history_streaks(tmp_path):
    s = Store(str(tmp_path / "store.json"))
    h = 3_600_000
    assert s.streaks("1h", 0, ["A"]) == {"A": 0}  # nothing to compare with
    run(s.record_top("1h", 1 * h, ["A", "B"]))
    run(s.record_top("1h", 2 * h, ["A", "C"]))
    run(s.record_top("1h", 2 * h, ["A", "C"]))  # idempotent
    assert len(s.history["1h"]) == 2
    st = s.streaks("1h", 3 * h, ["A", "B", "C", "D"])
    assert st == {"A": 3, "B": 1, "C": 2, "D": 1}
    # asking again for the same candle ignores that candle's own snapshot
    run(s.record_top("1h", 3 * h, ["A", "D"]))
    assert s.streaks("1h", 3 * h, ["A", "D"]) == {"A": 3, "D": 1}


def test_presets_prefs_queue(tmp_path):
    s = Store(str(tmp_path / "store.json"))
    assert run(s.preset_save(1, {"name": "Лонг 4ч", "interval": "4h", "by": "atr"}))
    assert run(s.preset_save(1, {"name": "лонг 4ч", "interval": "4h", "by": "expansion"}))  # replace, case-insensitive
    assert len(s.user_presets(1)) == 1 and s.user_presets(1)[0]["by"] == "expansion"
    assert run(s.preset_toggle_auto(1, 0)) is True
    assert s.auto_presets("4h") == [(1, s.user_presets(1)[0])] and s.auto_presets("1h") == []
    assert run(s.preset_delete(1, 5)) is None and run(s.preset_delete(1, 0))["name"] == "лонг 4ч"
    assert s.user_prefs(2)["tz"] == 0
    assert run(s.set_pref(2, tz=3, quiet_on=True))["tz"] == 3
    run(s.enqueue(2, "watch", "hello", 1.0))
    s2 = Store(s.path)
    assert s2.user_prefs(2)["quiet_on"] is True
    assert run(s2.drain_queue(2)) == [{"ts": 1.0, "kind": "watch", "text": "hello"}]
    assert run(s2.drain_queue(2)) == []
