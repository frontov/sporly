from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from app.config import settings

REMINDER_OFFSET_DAYS = (7, 3, 1)


def already_passed_offsets(starts_at: str | None) -> list[str]:
    """Reminder offsets that are already behind us for this start date.

    Pre-marking them as sent keeps favoriting an event 2 days out from firing
    the "7 days left" and "3 days left" reminders in one batch.
    """
    if not starts_at:
        return []
    try:
        event_date = date.fromisoformat(starts_at[:10])
    except ValueError:
        return []
    days_until = (event_date - date.today()).days
    return [str(offset) for offset in REMINDER_OFFSET_DAYS if days_until < offset]


@dataclass
class FavoriteEvent:
    event_id: str
    title: str
    starts_at: str | None = None
    date_text: str | None = None
    source_url: str = ""
    # Which reminder offsets ("7", "3", "1" days before) have already been sent.
    reminded_offsets: list[str] = field(default_factory=list)


class FavoriteEventsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, list[FavoriteEvent]] = self._load()

    def _load(self) -> dict[str, list[FavoriteEvent]]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {
            chat_id: [FavoriteEvent(**item) for item in items]
            for chat_id, items in raw.items()
        }

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            chat_id: [asdict(item) for item in items] for chat_id, items in self._data.items()
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, chat_id: int) -> list[FavoriteEvent]:
        return list(self._data.get(str(chat_id), []))

    def is_favorite(self, chat_id: int, event_id: str) -> bool:
        return any(item.event_id == event_id for item in self._data.get(str(chat_id), []))

    def all(self) -> dict[str, list[FavoriteEvent]]:
        return dict(self._data)

    async def add(self, chat_id: int, event: FavoriteEvent) -> None:
        async with self._lock:
            items = self._data.setdefault(str(chat_id), [])
            if any(existing.event_id == event.event_id for existing in items):
                return
            items.append(event)
            self._persist()

    async def remove(self, chat_id: int, event_id: str) -> None:
        async with self._lock:
            items = self._data.get(str(chat_id))
            if not items:
                return
            self._data[str(chat_id)] = [item for item in items if item.event_id != event_id]
            self._persist()

    async def mark_reminded(self, chat_id: int, event_id: str, offset_key: str) -> None:
        async with self._lock:
            for item in self._data.get(str(chat_id), []):
                if item.event_id == event_id and offset_key not in item.reminded_offsets:
                    item.reminded_offsets.append(offset_key)
                    self._persist()
                    return


favorites_store = FavoriteEventsStore(settings.favorite_events_file)
