from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from app.schemas.event import Event


logger = logging.getLogger(__name__)

DEFAULT_FEATURED_LABEL = "Рекомендовано Sporly"


def _entry_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class FeaturedEntry:
    id: str
    event_id: str | None
    source_url: str | None
    title: str
    starts_at: str | None
    city: str | None
    region: str | None
    semantic_key: list[str] | None
    label: str = DEFAULT_FEATURED_LABEL
    priority: int = 100
    enabled: bool = True
    until: str | None = None
    created_at: str | None = None

    def is_active(self, today: date | None = None) -> bool:
        if not self.enabled:
            return False
        if not self.until:
            return True
        try:
            until = date.fromisoformat(self.until[:10])
        except (TypeError, ValueError):
            return True
        return (today or date.today()) <= until

    def same_event(
        self,
        event: Event,
        canonical_url: str,
        semantic_key: tuple[str, str, str] | None,
    ) -> bool:
        if self.event_id and event.id == self.event_id:
            return True
        if (
            self.source_url
            and canonical_url
            and self.source_url == canonical_url
        ):
            return True
        if (
            self.semantic_key
            and semantic_key is not None
            and tuple(self.semantic_key) == semantic_key
        ):
            return True
        return False

    def matches(
        self,
        event: Event,
        canonical_url: str,
        semantic_key: tuple[str, str, str] | None,
    ) -> bool:
        return self.is_active() and self.same_event(
            event, canonical_url, semantic_key
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "source_url": self.source_url,
            "title": self.title,
            "starts_at": self.starts_at,
            "city": self.city,
            "region": self.region,
            "semantic_key": self.semantic_key,
            "label": self.label,
            "priority": self.priority,
            "enabled": self.enabled,
            "until": self.until,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeaturedEntry | None":
        entry_id = payload.get("id")
        title = payload.get("title")
        if not isinstance(entry_id, str) or not entry_id:
            return None
        semantic_key = payload.get("semantic_key")
        if not isinstance(semantic_key, list):
            semantic_key = None
        try:
            priority = int(payload.get("priority", 100))
        except (TypeError, ValueError):
            priority = 100
        return cls(
            id=entry_id,
            event_id=payload.get("event_id") if isinstance(payload.get("event_id"), str) else None,
            source_url=payload.get("source_url") if isinstance(payload.get("source_url"), str) else None,
            title=str(title or ""),
            starts_at=payload.get("starts_at") if isinstance(payload.get("starts_at"), str) else None,
            city=payload.get("city") if isinstance(payload.get("city"), str) else None,
            region=payload.get("region") if isinstance(payload.get("region"), str) else None,
            semantic_key=[str(part) for part in semantic_key] if semantic_key else None,
            label=str(payload.get("label") or DEFAULT_FEATURED_LABEL),
            priority=priority,
            enabled=bool(payload.get("enabled", True)),
            until=payload.get("until") if isinstance(payload.get("until"), str) else None,
            created_at=payload.get("created_at") if isinstance(payload.get("created_at"), str) else None,
        )


class FeaturedEventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: list[FeaturedEntry] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Cannot read featured events file %s", self.path)
            return
        raw_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            return
        entries: list[FeaturedEntry] = []
        for raw in raw_items:
            if isinstance(raw, dict):
                entry = FeaturedEntry.from_dict(raw)
                if entry is not None:
                    entries.append(entry)
        self._entries = entries

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [entry.to_dict() for entry in self._entries]}
        temp_file = self.path.with_name(f"{self.path.name}.tmp")
        try:
            temp_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_file, self.path)
        finally:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def all(self) -> list[FeaturedEntry]:
        return list(self._entries)

    def delete(self, entry_id: str) -> bool:
        before = len(self._entries)
        self._entries = [entry for entry in self._entries if entry.id != entry_id]
        if len(self._entries) == before:
            return False
        self._save()
        return True

    def upsert(
        self,
        event: Event,
        canonical_url: str,
        semantic_key: tuple[str, str, str] | None,
        *,
        label: str,
        priority: int,
        until: str | None,
        enabled: bool = True,
    ) -> FeaturedEntry:
        existing = next(
            (
                entry
                for entry in self._entries
                if entry.same_event(event, canonical_url, semantic_key)
            ),
            None,
        )
        entry_id = existing.id if existing else _entry_id(canonical_url or event.id)
        entry = FeaturedEntry(
            id=entry_id,
            event_id=event.id,
            source_url=canonical_url or None,
            title=event.title,
            starts_at=event.starts_at or event.date_text,
            city=event.city,
            region=event.region,
            semantic_key=list(semantic_key) if semantic_key else None,
            label=label.strip() or DEFAULT_FEATURED_LABEL,
            priority=max(int(priority), 0),
            enabled=enabled,
            until=until,
            created_at=existing.created_at if existing else datetime.now().isoformat(),
        )
        if existing is None:
            self._entries.append(entry)
        else:
            index = self._entries.index(existing)
            self._entries[index] = entry
        self._save()
        return entry

    def match(
        self,
        event: Event,
        canonical_url: str,
        semantic_key: tuple[str, str, str] | None,
    ) -> FeaturedEntry | None:
        matches = [
            entry
            for entry in self._entries
            if entry.matches(event, canonical_url, semantic_key)
        ]
        if not matches:
            return None
        return max(matches, key=lambda entry: (entry.priority, entry.created_at or ""))
