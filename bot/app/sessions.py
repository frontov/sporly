from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
import time


@dataclass(slots=True)
class SearchSession:
    id: str
    chat_id: int
    query: str | None
    cities: list[str]
    categories: list[str]
    created_at: float
    page: int = 1
    total: int = 0
    total_pages: int = 1

    @property
    def filters_selected(self) -> bool:
        return bool(self.query or self.cities or self.categories)


class SearchSessionStore:
    def __init__(self, ttl_seconds: int = 6 * 3600) -> None:
        self._items: dict[str, SearchSession] = {}
        self._ttl = ttl_seconds

    def create(
        self,
        chat_id: int,
        *,
        query: str | None = None,
        cities: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> SearchSession:
        self._prune()
        session = SearchSession(
            id=secrets.token_hex(4),
            chat_id=chat_id,
            query=query,
            cities=list(cities or []),
            categories=list(categories or []),
            created_at=time.time(),
        )
        self._items[session.id] = session
        return session

    def get(self, session_id: str) -> SearchSession | None:
        self._prune()
        return self._items.get(session_id)

    def _prune(self) -> None:
        cutoff = time.time() - self._ttl
        stale = [key for key, value in self._items.items() if value.created_at < cutoff]
        for key in stale:
            self._items.pop(key, None)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
