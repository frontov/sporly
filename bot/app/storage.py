from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import settings


@dataclass
class Subscription:
    chat_id: int
    cities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    notify_enabled: bool = False
    digest_enabled: bool = False
    # True once the user has been through the favorites wizard at least once,
    # even if they ended up picking zero cities/categories on purpose (= "any").
    # Distinguishes that from "never set up favorites" for /find's default.
    onboarded: bool = False
    seen_event_ids: list[str] = field(default_factory=list)


class SubscriptionStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, Subscription] = self._load()

    def _load(self) -> dict[str, Subscription]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {
            key: Subscription(
                chat_id=int(key),
                **{field_name: value for field_name, value in payload.items() if field_name != "chat_id"},
            )
            for key, payload in raw.items()
        }

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(subscription) for key, subscription in self._data.items()}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, chat_id: int) -> Subscription | None:
        return self._data.get(str(chat_id))

    def all(self) -> list[Subscription]:
        return list(self._data.values())

    async def upsert(self, subscription: Subscription) -> None:
        async with self._lock:
            self._data[str(subscription.chat_id)] = subscription
            self._persist()

    async def disable_notify(self, chat_id: int) -> None:
        async with self._lock:
            subscription = self._data.get(str(chat_id))
            if not subscription:
                return
            subscription.notify_enabled = False
            self._persist()

    async def remove(self, chat_id: int) -> None:
        async with self._lock:
            self._data.pop(str(chat_id), None)
            self._persist()

    async def mark_seen(self, chat_id: int, event_ids: list[str]) -> None:
        async with self._lock:
            subscription = self._data.get(str(chat_id))
            if not subscription:
                return
            seen = set(subscription.seen_event_ids)
            seen.update(event_ids)
            subscription.seen_event_ids = list(seen)[-500:]
            self._persist()


store = SubscriptionStore(settings.subscriptions_file)
