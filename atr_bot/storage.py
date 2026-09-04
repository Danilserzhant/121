"""JSON-backed store: users with roles, "seen" users, subscriptions, watchlists, top history."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_TRADER = "trader"
ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_TRADER)
ROLE_TITLES = {ROLE_OWNER: "владелец", ROLE_ADMIN: "админ", ROLE_TRADER: "трейдер"}

# Subscription kinds: hourly top, daily top, breakout alerts.
SUB_1H = "1h"
SUB_1D = "1d"
SUB_ALERTS = "alerts"
SUB_KINDS = (SUB_1H, SUB_1D, SUB_ALERTS)
SUB_TITLES = {SUB_1H: "часовой топ", SUB_1D: "дневной топ", SUB_ALERTS: "алерты свеча-выброс"}

HISTORY_KEEP = 200  # snapshots per interval


@dataclass
class User:
    id: int
    role: str
    username: str = ""
    name: str = ""
    added_by: int | None = None
    added_at: float = 0.0

    def label(self) -> str:
        parts = [f"<code>{self.id}</code>"]
        if self.username:
            parts.append(f"@{self.username}")
        if self.name:
            parts.append(self.name)
        return " · ".join(parts)


class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self.users: dict[int, User] = {}
        self.seen: dict[int, dict] = {}                 # everyone who ever wrote to the bot
        self.subs: dict[int, set[str]] = {}             # chat id -> subscription kinds
        self.watch: dict[int, list[str]] = {}           # user id -> symbols
        self.history: dict[str, list[dict]] = {}        # interval -> [{"t": candle_ms, "s": [symbols]}]
        self._load()

    # ------------------------------------------------------------- persistence
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        for uid, u in data.get("users", {}).items():
            self.users[int(uid)] = User(
                id=int(uid), role=u.get("role", ROLE_TRADER), username=u.get("username", ""),
                name=u.get("name", ""), added_by=u.get("added_by"), added_at=u.get("added_at", 0.0),
            )
        self.seen = {int(k): v for k, v in data.get("seen", {}).items()}
        self.subs = {int(k): set(v) for k, v in data.get("subs", {}).items()}
        for chat in data.get("chats", []):  # legacy: plain list of hourly subscribers
            self.subs.setdefault(int(chat), set()).add(SUB_1H)
        self.watch = {int(k): list(v) for k, v in data.get("watch", {}).items()}
        self.history = {k: list(v) for k, v in data.get("history", {}).items()}

    def _save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        data = {
            "users": {str(u.id): u.__dict__ for u in self.users.values()},
            "seen": {str(k): v for k, v in self.seen.items()},
            "subs": {str(k): sorted(v) for k, v in self.subs.items() if v},
            "watch": {str(k): v for k, v in self.watch.items() if v},
            "history": self.history,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ roles
    def role(self, user_id: int) -> str | None:
        u = self.users.get(user_id)
        return u.role if u else None

    def is_owner(self, user_id: int) -> bool:
        return self.role(user_id) == ROLE_OWNER

    def is_admin(self, user_id: int) -> bool:
        return self.role(user_id) in (ROLE_OWNER, ROLE_ADMIN)

    def has_access(self, user_id: int) -> bool:
        return self.role(user_id) in ROLES

    def has_owner(self) -> bool:
        return any(u.role == ROLE_OWNER for u in self.users.values())

    def by_role(self, role: str) -> list[User]:
        return sorted((u for u in self.users.values() if u.role == role), key=lambda u: u.added_at)

    def resolve(self, ref: str) -> int | None:
        """Turn '123456' or '@name' into a user id (usernames only if we have seen them)."""
        ref = ref.strip()
        if ref.lstrip("-").isdigit():
            return int(ref)
        name = ref.lstrip("@").lower()
        if not name:
            return None
        for u in self.users.values():
            if u.username.lower() == name:
                return u.id
        for uid, info in self.seen.items():
            if str(info.get("username", "")).lower() == name:
                return uid
        return None

    async def set_role(self, user_id: int, role: str, added_by: int | None = None) -> User:
        async with self._lock:
            info = self.seen.get(user_id, {})
            existing = self.users.get(user_id)
            user = User(
                id=user_id,
                role=role,
                username=(existing.username if existing else "") or info.get("username", ""),
                name=(existing.name if existing else "") or info.get("name", ""),
                added_by=added_by if existing is None else existing.added_by,
                added_at=existing.added_at if existing else time.time(),
            )
            self.users[user_id] = user
            self._save()
            return user

    async def remove_user(self, user_id: int) -> User | None:
        async with self._lock:
            user = self.users.pop(user_id, None)
            self.watch.pop(user_id, None)
            self.subs.pop(user_id, None)
            if user is not None:
                self._save()
            return user

    async def touch(self, user_id: int, username: str | None, name: str) -> None:
        """Remember who wrote to the bot, so admins can add them by @username."""
        async with self._lock:
            info = {"username": username or "", "name": name, "last_seen": time.time()}
            changed = user_id not in self.seen or self.seen[user_id].get("username") != info["username"]
            self.seen[user_id] = info
            u = self.users.get(user_id)
            if u and (u.username != info["username"] or u.name != name):
                u.username, u.name = info["username"], name
                changed = True
            if changed:
                self._save()

    def pending(self) -> list[tuple[int, dict]]:
        """Users who wrote to the bot but have no role yet."""
        return sorted(
            ((uid, info) for uid, info in self.seen.items() if uid not in self.users),
            key=lambda x: x[1].get("last_seen", 0), reverse=True,
        )

    # ---------------------------------------------------------- subscriptions
    def subscribed(self, kind: str) -> list[int]:
        return sorted(chat for chat, kinds in self.subs.items() if kind in kinds)

    def chat_subs(self, chat_id: int) -> set[str]:
        return set(self.subs.get(chat_id, set()))

    async def subscribe(self, chat_id: int, kind: str) -> bool:
        async with self._lock:
            kinds = self.subs.setdefault(chat_id, set())
            if kind in kinds:
                return False
            kinds.add(kind)
            self._save()
            return True

    async def unsubscribe(self, chat_id: int, kind: str | None = None) -> set[str]:
        """Remove one kind (or all). Returns the kinds that were removed."""
        async with self._lock:
            kinds = self.subs.get(chat_id, set())
            removed = set(kinds) if kind is None else ({kind} & kinds)
            kinds -= removed
            if not kinds:
                self.subs.pop(chat_id, None)
            if removed:
                self._save()
            return removed

    # ----------------------------------------------------------------- watch
    def watchlist(self, user_id: int) -> list[str]:
        return list(self.watch.get(user_id, []))

    def all_watched(self) -> set[str]:
        return {s for lst in self.watch.values() for s in lst}

    async def watch_add(self, user_id: int, symbol: str) -> bool:
        async with self._lock:
            lst = self.watch.setdefault(user_id, [])
            if symbol in lst:
                return False
            lst.append(symbol)
            self._save()
            return True

    async def watch_remove(self, user_id: int, symbol: str | None = None) -> list[str]:
        async with self._lock:
            lst = self.watch.get(user_id, [])
            removed = list(lst) if symbol is None else ([symbol] if symbol in lst else [])
            for s in removed:
                lst.remove(s)
            if not lst:
                self.watch.pop(user_id, None)
            if removed:
                self._save()
            return removed

    # --------------------------------------------------------------- history
    async def record_top(self, interval: str, candle_time: int, symbols: list[str]) -> None:
        """Remember which symbols were in the top for this candle (idempotent per candle)."""
        async with self._lock:
            snaps = self.history.setdefault(interval, [])
            for snap in snaps:
                if snap["t"] == candle_time:
                    if snap["s"] == symbols:
                        return
                    snap["s"] = symbols
                    break
            else:
                snaps.append({"t": candle_time, "s": symbols})
            snaps.sort(key=lambda x: x["t"])
            del snaps[:-HISTORY_KEEP]
            self._save()

    def streaks(self, interval: str, candle_time: int, symbols: list[str]) -> dict[str, int]:
        """How many consecutive candles (including this one) each symbol has been in the top.

        Returns 0 for a symbol when there is no earlier snapshot at all (nothing to compare with).
        """
        earlier = [snap for snap in self.history.get(interval, []) if snap["t"] < candle_time]
        earlier.sort(key=lambda x: x["t"], reverse=True)
        out: dict[str, int] = {}
        for sym in symbols:
            if not earlier:
                out[sym] = 0
                continue
            n = 1
            for snap in earlier:
                if sym in snap["s"]:
                    n += 1
                else:
                    break
            out[sym] = n
        return out
