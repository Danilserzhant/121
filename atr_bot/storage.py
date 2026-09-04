"""JSON-backed store: users with roles, "seen" users, subscribed chats."""

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
        self.seen: dict[int, dict] = {}  # everyone who ever wrote to the bot
        self.chats: set[int] = set()     # chats subscribed to hourly pushes
        self._load()

    # ------------------------------------------------------------- persistence
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        self.chats = {int(x) for x in data.get("chats", [])}
        for uid, u in data.get("users", {}).items():
            self.users[int(uid)] = User(
                id=int(uid), role=u.get("role", ROLE_TRADER), username=u.get("username", ""),
                name=u.get("name", ""), added_by=u.get("added_by"), added_at=u.get("added_at", 0.0),
            )
        self.seen = {int(k): v for k, v in data.get("seen", {}).items()}

    def _save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        data = {
            "chats": sorted(self.chats),
            "users": {str(u.id): u.__dict__ for u in self.users.values()},
            "seen": {str(k): v for k, v in self.seen.items()},
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
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
            if user is not None:
                self._save()
            return user

    async def touch(self, user_id: int, username: str | None, name: str) -> None:
        """Remember who wrote to the bot, so admins can add them by @username."""
        async with self._lock:
            info = {"username": username or "", "name": name, "last_seen": time.time()}
            changed = self.seen.get(user_id, {}).get("username") != info["username"] or user_id not in self.seen
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
    def is_subscribed(self, chat_id: int) -> bool:
        return chat_id in self.chats

    async def subscribe(self, chat_id: int) -> bool:
        async with self._lock:
            if chat_id in self.chats:
                return False
            self.chats.add(chat_id)
            self._save()
            return True

    async def unsubscribe(self, chat_id: int) -> bool:
        async with self._lock:
            if chat_id not in self.chats:
                return False
            self.chats.discard(chat_id)
            self._save()
            return True
