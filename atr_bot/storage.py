"""Tiny JSON-backed subscriber list."""

from __future__ import annotations

import asyncio
import json
import os


class SubscriberStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self._chats: set[int] = set()
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self._chats = {int(x) for x in data.get("chats", [])}
        except FileNotFoundError:
            self._chats = set()
        except (json.JSONDecodeError, ValueError, AttributeError):
            self._chats = set()

    def _save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"chats": sorted(self._chats)}, fh)
        os.replace(tmp, self.path)

    @property
    def chats(self) -> list[int]:
        return sorted(self._chats)

    def is_subscribed(self, chat_id: int) -> bool:
        return chat_id in self._chats

    async def add(self, chat_id: int) -> bool:
        async with self._lock:
            if chat_id in self._chats:
                return False
            self._chats.add(chat_id)
            self._save()
            return True

    async def remove(self, chat_id: int) -> bool:
        async with self._lock:
            if chat_id not in self._chats:
                return False
            self._chats.discard(chat_id)
            self._save()
            return True
