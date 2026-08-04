from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import settings

# Telegram start-payloads allow only A-Z a-z 0-9 _ - and max 64 chars, while
# event ids are arbitrary source-specific strings. A short stable hash keeps
# links valid and lets the same event reuse the same token across pages.
TOKEN_LENGTH = 10
MAX_ENTRIES = 3000


@dataclass
class EventRef:
    event_id: str
    title: str
    starts_at: str | None = None
    date_text: str | None = None
    source_url: str = ""


def make_token(event_id: str) -> str:
    return hashlib.sha1(event_id.encode("utf-8")).hexdigest()[:TOKEN_LENGTH]


class EventTokenStore:
    """Maps deep-link tokens back to the event they were rendered for.

    Persisted so links stay clickable after a bot restart, and capped so the
    file cannot grow without bound.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, EventRef] = self._load()

    def _load(self) -> dict[str, EventRef]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        try:
            return {token: EventRef(**payload) for token, payload in raw.items()}
        except TypeError:
            return {}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {token: asdict(ref) for token, ref in self._data.items()}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, token: str) -> EventRef | None:
        return self._data.get(token)

    async def remember_many(self, refs: Iterable[EventRef]) -> dict[str, str]:
        """Registers refs and returns {event_id: token}, writing the file once."""
        tokens: dict[str, str] = {}
        changed = False
        async with self._lock:
            for ref in refs:
                token = make_token(ref.event_id)
                tokens[ref.event_id] = token
                if token not in self._data:
                    self._data[token] = ref
                    changed = True
            if changed:
                if len(self._data) > MAX_ENTRIES:
                    # dicts keep insertion order, so this drops the oldest tokens
                    for stale in list(self._data)[: len(self._data) - MAX_ENTRIES]:
                        del self._data[stale]
                self._persist()
        return tokens


token_store = EventTokenStore(settings.event_tokens_file)
