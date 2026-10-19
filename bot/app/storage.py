from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Iterable


logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass(slots=True)
class User:
    chat_id: int
    username: str | None
    first_name: str | None
    source: str | None
    campaign: str | None
    referrer_id: int | None
    onboarded: bool
    ui_version: int
    survey_completed: bool
    created_at: str
    last_active_at: str


@dataclass(slots=True)
class Subscription:
    chat_id: int
    cities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    notify_enabled: bool = True
    digest_enabled: bool = True
    last_digest_day: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def has_filters(self) -> bool:
        return bool(self.cities or self.categories)

    def summary(self) -> str:
        parts: list[str] = []
        if self.categories:
            parts.append("🏃 " + ", ".join(self.categories))
        if self.cities:
            parts.append("📍 " + ", ".join(self.cities))
        return "\n".join(parts) or "🌍 Все виды спорта, вся Россия"


@dataclass(slots=True)
class Favorite:
    chat_id: int
    event_id: str
    title: str
    starts_at: str | None
    date_text: str | None
    source_url: str
    city: str | None = None
    region: str | None = None
    category: str | None = None
    reminded_offsets: list[str] = field(default_factory=list)
    created_at: str | None = None

    @property
    def location(self) -> str:
        city = (self.city or "").strip()
        region = (self.region or "").strip()
        if city and region:
            if region.casefold() in city.casefold():
                return city
            if city.casefold() in region.casefold():
                return region
        return ", ".join(part for part in (city, region) if part)


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def parse_search_payload(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {"query": "", "cities": [], "categories": []}
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        return {
            "query": str(parsed.get("query") or ""),
            "cities": [str(value) for value in parsed.get("cities") or []],
            "categories": [str(value) for value in parsed.get("categories") or []],
        }
    parts = (payload or "").split("|")
    return {
        "query": parts[0] if len(parts) > 0 else "",
        "cities": [value for value in (parts[1] if len(parts) > 1 else "").split(",") if value],
        "categories": [value for value in (parts[2] if len(parts) > 2 else "").split(",") if value],
    }


def parse_event_click_payload(payload: str | None) -> dict[str, str]:
    if not payload:
        return {"id": "", "title": "Старт"}
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        return {
            "id": str(parsed.get("id") or ""),
            "title": str(parsed.get("title") or "Старт"),
            "url": str(parsed.get("url") or ""),
        }
    parts = (payload or "").split("|")
    return {
        "id": parts[0] if parts else "",
        "title": parts[1] if len(parts) > 1 else "Старт",
        "url": parts[2] if len(parts) > 2 else "",
    }


def _loads_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class Database:
    """Small SQLite store for users, subscriptions, favorites and analytics.

    All public methods are async and run SQLite work in a worker thread so the
    polling loop is never blocked by disk I/O.
    """

    def __init__(self, path: Path, legacy_data_dir: Path | None = None) -> None:
        self.path = path
        self.legacy_data_dir = legacy_data_dir or path.parent
        self._ready = False
        self._init_lock = asyncio.Lock()

    # ------------------------------------------------------------------ setup

    async def init(self) -> None:
        async with self._init_lock:
            if self._ready:
                return
            await asyncio.to_thread(self._init_sync)
            self._ready = True

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_sync(self) -> None:
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    source TEXT,
                    campaign TEXT,
                    referrer_id INTEGER,
                    onboarded INTEGER NOT NULL DEFAULT 0,
                    ui_version INTEGER NOT NULL DEFAULT 0,
                    survey_completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    chat_id INTEGER PRIMARY KEY,
                    cities TEXT NOT NULL DEFAULT '[]',
                    categories TEXT NOT NULL DEFAULT '[]',
                    notify_enabled INTEGER NOT NULL DEFAULT 1,
                    digest_enabled INTEGER NOT NULL DEFAULT 1,
                    last_digest_day TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS favorites (
                    chat_id INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    starts_at TEXT,
                    date_text TEXT,
                    source_url TEXT NOT NULL,
                    city TEXT,
                    region TEXT,
                    category TEXT,
                    reminded_offsets TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS favorites_start_idx
                    ON favorites (starts_at);

                CREATE TABLE IF NOT EXISTS seen_events (
                    chat_id INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    seen_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, event_id)
                );

                CREATE TABLE IF NOT EXISTS event_refs (
                    token TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    kind TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS interactions_kind_idx
                    ON interactions (kind, created_at);

                CREATE TABLE IF NOT EXISTS partner_daily (
                    partner_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    impressions INTEGER NOT NULL DEFAULT 0,
                    clicks INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (partner_id, day)
                );

                CREATE TABLE IF NOT EXISTS partner_user_daily (
                    partner_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    impressions INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (partner_id, chat_id, day)
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ui_messages (
                    chat_id INTEGER PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            user_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "ui_version" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN ui_version INTEGER NOT NULL DEFAULT 0"
                )
            if "survey_completed" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN survey_completed INTEGER NOT NULL DEFAULT 0"
                )
            self._migrate_legacy_json(connection)

    def _migrate_legacy_json(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'legacy_json_migrated'"
        ).fetchone()
        if row:
            return

        subscriptions_file = self.legacy_data_dir / "subscriptions.json"
        favorites_file = self.legacy_data_dir / "favorite_events.json"
        migrated = 0

        if subscriptions_file.exists():
            try:
                payload = json.loads(subscriptions_file.read_text("utf-8"))
            except (OSError, ValueError) as error:
                logger.warning("Cannot read legacy subscriptions: %s", error)
                payload = {}
            if isinstance(payload, dict):
                for raw_chat_id, raw in payload.items():
                    if not isinstance(raw, dict):
                        continue
                    try:
                        chat_id = int(raw_chat_id)
                    except (TypeError, ValueError):
                        continue
                    now = utc_now()
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO users
                            (chat_id, username, first_name, onboarded, created_at, last_active_at)
                        VALUES (?, NULL, NULL, ?, ?, ?)
                        """,
                        (chat_id, int(bool(raw.get("onboarded"))), now, now),
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO subscriptions
                            (chat_id, cities, categories, notify_enabled,
                             digest_enabled, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chat_id,
                            json.dumps(raw.get("cities") or [], ensure_ascii=False),
                            json.dumps(raw.get("categories") or [], ensure_ascii=False),
                            int(bool(raw.get("notify_enabled", True))),
                            int(bool(raw.get("digest_enabled", False))),
                            now,
                            now,
                        ),
                    )
                    seen_ids = raw.get("seen_event_ids") or []
                    if isinstance(seen_ids, list):
                        connection.executemany(
                            "INSERT OR IGNORE INTO seen_events (chat_id, event_id, seen_at) VALUES (?, ?, ?)",
                            [(chat_id, str(event_id), now) for event_id in seen_ids if event_id],
                        )
                    migrated += 1

        if favorites_file.exists():
            try:
                payload = json.loads(favorites_file.read_text("utf-8"))
            except (OSError, ValueError) as error:
                logger.warning("Cannot read legacy favorites: %s", error)
                payload = {}
            if isinstance(payload, dict):
                for raw_chat_id, items in payload.items():
                    try:
                        chat_id = int(raw_chat_id)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(items, list):
                        continue
                    now = utc_now()
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO users
                            (chat_id, username, first_name, onboarded, created_at, last_active_at)
                        VALUES (?, NULL, NULL, 1, ?, ?)
                        """,
                        (chat_id, now, now),
                    )
                    for item in items:
                        if not isinstance(item, dict) or not item.get("event_id"):
                            continue
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO favorites
                                (chat_id, event_id, title, starts_at, date_text, source_url,
                                 city, region, category, reminded_offsets, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                chat_id,
                                str(item["event_id"]),
                                str(item.get("title") or "Событие"),
                                item.get("starts_at"),
                                item.get("date_text"),
                                str(item.get("source_url") or ""),
                                item.get("city"),
                                item.get("region"),
                                item.get("category"),
                                json.dumps(
                                    [str(value) for value in item.get("reminded_offsets") or []],
                                    ensure_ascii=False,
                                ),
                                now,
                            ),
                        )

        if migrated:
            logger.info("Migrated %s legacy subscriptions", migrated)
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_json_migrated', ?)",
            (utc_now(),),
        )
        connection.commit()

    # ------------------------------------------------------------------ users

    async def ensure_user(
        self,
        chat_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        return await asyncio.to_thread(self._ensure_user_sync, chat_id, username, first_name)

    def _ensure_user_sync(
        self, chat_id: int, username: str | None, first_name: str | None
    ) -> User:
        now = utc_now()
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (chat_id, username, first_name, ui_version,
                     created_at, last_active_at)
                VALUES (?, ?, ?, 2, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    first_name = COALESCE(excluded.first_name, users.first_name),
                    last_active_at = excluded.last_active_at
                """,
                (chat_id, username, first_name, now, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return self._user_from_row(row)

    @staticmethod
    def _user_from_row(row: sqlite3.Row | None) -> User:
        if row is None:
            raise KeyError("User not found")
        return User(
            chat_id=int(row["chat_id"]),
            username=row["username"],
            first_name=row["first_name"],
            source=row["source"],
            campaign=row["campaign"],
            referrer_id=row["referrer_id"],
            onboarded=bool(row["onboarded"]),
            ui_version=int(row["ui_version"] or 0),
            survey_completed=bool(row["survey_completed"]),
            created_at=row["created_at"],
            last_active_at=row["last_active_at"],
        )

    async def get_user(self, chat_id: int) -> User | None:
        return await asyncio.to_thread(self._get_user_sync, chat_id)

    def _get_user_sync(self, chat_id: int) -> User | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return self._user_from_row(row) if row else None

    async def touch_user(self, chat_id: int) -> None:
        await asyncio.to_thread(self._touch_user_sync, chat_id)

    def _touch_user_sync(self, chat_id: int) -> None:
        with self._db() as connection:
            connection.execute(
                "UPDATE users SET last_active_at = ? WHERE chat_id = ?",
                (utc_now(), chat_id),
            )
            connection.commit()

    async def set_attribution(
        self,
        chat_id: int,
        *,
        source: str | None = None,
        campaign: str | None = None,
    ) -> None:
        await asyncio.to_thread(self._set_attribution_sync, chat_id, source, campaign)

    def _set_attribution_sync(
        self, chat_id: int, source: str | None, campaign: str | None
    ) -> None:
        with self._db() as connection:
            connection.execute(
                """
                UPDATE users SET
                    source = COALESCE(source, ?),
                    campaign = COALESCE(campaign, ?)
                WHERE chat_id = ?
                """,
                (source, campaign, chat_id),
            )
            connection.commit()

    async def set_referrer(self, chat_id: int, referrer_id: int | None) -> bool:
        return await asyncio.to_thread(self._set_referrer_sync, chat_id, referrer_id)

    def _set_referrer_sync(self, chat_id: int, referrer_id: int | None) -> bool:
        if not referrer_id or referrer_id == chat_id:
            return False
        with self._db() as connection:
            exists = connection.execute(
                "SELECT 1 FROM users WHERE chat_id = ?", (referrer_id,)
            ).fetchone()
            if not exists:
                return False
            cursor = connection.execute(
                """
                UPDATE users SET referrer_id = ?
                WHERE chat_id = ? AND referrer_id IS NULL
                """,
                (referrer_id, chat_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    async def referral_count(self, chat_id: int) -> int:
        return await asyncio.to_thread(self._referral_count_sync, chat_id)

    def _referral_count_sync(self, chat_id: int) -> int:
        with self._db() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM users WHERE referrer_id = ?", (chat_id,)
            ).fetchone()
        return int(row[0] or 0) if row else 0

    async def mark_ui_version(self, chat_id: int, version: int) -> None:
        await asyncio.to_thread(self._mark_ui_version_sync, chat_id, version)

    def _mark_ui_version_sync(self, chat_id: int, version: int) -> None:
        with self._db() as connection:
            connection.execute(
                "UPDATE users SET ui_version = ? WHERE chat_id = ?",
                (version, chat_id),
            )

    async def mark_survey_completed(self, chat_id: int) -> None:
        await asyncio.to_thread(self._mark_survey_completed_sync, chat_id)

    def _mark_survey_completed_sync(self, chat_id: int) -> None:
        with self._db() as connection:
            connection.execute(
                "UPDATE users SET survey_completed = 1 WHERE chat_id = ?",
                (chat_id,),
            )

    async def mark_onboarded(self, chat_id: int) -> None:
        await asyncio.to_thread(self._mark_onboarded_sync, chat_id)

    def _mark_onboarded_sync(self, chat_id: int) -> None:
        with self._db() as connection:
            connection.execute(
                "UPDATE users SET onboarded = 1 WHERE chat_id = ?", (chat_id,)
            )
            connection.commit()

    # ---------------------------------------------------------- subscriptions

    async def get_subscription(self, chat_id: int) -> Subscription | None:
        return await asyncio.to_thread(self._get_subscription_sync, chat_id)

    def _get_subscription_sync(self, chat_id: int) -> Subscription | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        if row is None:
            return None
        return Subscription(
            chat_id=int(row["chat_id"]),
            cities=_loads_list(row["cities"]),
            categories=_loads_list(row["categories"]),
            notify_enabled=bool(row["notify_enabled"]),
            digest_enabled=bool(row["digest_enabled"]),
            last_digest_day=row["last_digest_day"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def save_subscription(
        self,
        chat_id: int,
        *,
        cities: list[str],
        categories: list[str],
        notify_enabled: bool = True,
        digest_enabled: bool = True,
    ) -> Subscription:
        return await asyncio.to_thread(
            self._save_subscription_sync,
            chat_id,
            cities,
            categories,
            notify_enabled,
            digest_enabled,
        )

    def _save_subscription_sync(
        self,
        chat_id: int,
        cities: list[str],
        categories: list[str],
        notify_enabled: bool,
        digest_enabled: bool,
    ) -> Subscription:
        now = utc_now()
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO subscriptions
                    (chat_id, cities, categories, notify_enabled, digest_enabled,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    cities = excluded.cities,
                    categories = excluded.categories,
                    notify_enabled = excluded.notify_enabled,
                    digest_enabled = excluded.digest_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    chat_id,
                    json.dumps(cities, ensure_ascii=False),
                    json.dumps(categories, ensure_ascii=False),
                    int(notify_enabled),
                    int(digest_enabled),
                    now,
                    now,
                ),
            )
            connection.commit()
        subscription = self._get_subscription_sync(chat_id)
        if subscription is None:
            raise RuntimeError("Subscription was not saved")
        return subscription

    async def toggle_subscription(
        self, chat_id: int, field: str
    ) -> Subscription | None:
        if field not in {"notify_enabled", "digest_enabled"}:
            raise ValueError(f"Unsupported field: {field}")
        return await asyncio.to_thread(self._toggle_subscription_sync, chat_id, field)

    def _toggle_subscription_sync(
        self, chat_id: int, field: str
    ) -> Subscription | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if row is None:
                return None
            new_value = 0 if row[field] else 1
            connection.execute(
                f"UPDATE subscriptions SET {field} = ?, updated_at = ? WHERE chat_id = ?",
                (new_value, utc_now(), chat_id),
            )
            connection.commit()
        return self._get_subscription_sync(chat_id)

    async def delete_subscription(self, chat_id: int) -> bool:
        return await asyncio.to_thread(self._delete_subscription_sync, chat_id)

    def _delete_subscription_sync(self, chat_id: int) -> bool:
        with self._db() as connection:
            cursor = connection.execute(
                "DELETE FROM subscriptions WHERE chat_id = ?", (chat_id,)
            )
            connection.commit()
            return cursor.rowcount > 0

    async def active_subscriptions(self) -> list[Subscription]:
        return await asyncio.to_thread(self._active_subscriptions_sync)

    def _active_subscriptions_sync(self) -> list[Subscription]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM subscriptions WHERE notify_enabled = 1 OR digest_enabled = 1"
            ).fetchall()
        return [
            Subscription(
                chat_id=int(row["chat_id"]),
                cities=_loads_list(row["cities"]),
                categories=_loads_list(row["categories"]),
                notify_enabled=bool(row["notify_enabled"]),
                digest_enabled=bool(row["digest_enabled"]),
                last_digest_day=row["last_digest_day"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def mark_digest_sent(self, chat_id: int, day: str) -> None:
        await asyncio.to_thread(self._mark_digest_sent_sync, chat_id, day)

    def _mark_digest_sent_sync(self, chat_id: int, day: str) -> None:
        with self._db() as connection:
            connection.execute(
                "UPDATE subscriptions SET last_digest_day = ? WHERE chat_id = ?",
                (day, chat_id),
            )
            connection.commit()

    # ---------------------------------------------------------- seen events

    async def seen_ids(self, chat_id: int) -> set[str]:
        return await asyncio.to_thread(self._seen_ids_sync, chat_id)

    def _seen_ids_sync(self, chat_id: int) -> set[str]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT event_id FROM seen_events WHERE chat_id = ?", (chat_id,)
            ).fetchall()
        return {str(row["event_id"]) for row in rows}

    async def mark_seen(self, chat_id: int, event_ids: Iterable[str]) -> None:
        ids = [str(event_id) for event_id in event_ids if event_id]
        if not ids:
            return
        await asyncio.to_thread(self._mark_seen_sync, chat_id, ids)

    def _mark_seen_sync(self, chat_id: int, event_ids: list[str]) -> None:
        now = utc_now()
        with self._db() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO seen_events (chat_id, event_id, seen_at) VALUES (?, ?, ?)",
                [(chat_id, event_id, now) for event_id in event_ids],
            )
            connection.commit()

    # ------------------------------------------------------------- favorites

    async def add_favorite(self, chat_id: int, event: dict[str, Any]) -> None:
        await asyncio.to_thread(self._add_favorite_sync, chat_id, event)

    def _add_favorite_sync(self, chat_id: int, event: dict[str, Any]) -> None:
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO favorites
                    (chat_id, event_id, title, starts_at, date_text, source_url,
                     city, region, category, reminded_offsets, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)
                ON CONFLICT(chat_id, event_id) DO UPDATE SET
                    title = excluded.title,
                    starts_at = excluded.starts_at,
                    date_text = excluded.date_text,
                    source_url = excluded.source_url,
                    city = excluded.city,
                    region = excluded.region,
                    category = excluded.category
                """,
                (
                    chat_id,
                    str(event["event_id"]),
                    str(event.get("title") or "Событие"),
                    event.get("starts_at"),
                    event.get("date_text"),
                    str(event.get("source_url") or ""),
                    event.get("city"),
                    event.get("region"),
                    event.get("category"),
                    utc_now(),
                ),
            )
            connection.commit()

    async def remove_favorite(self, chat_id: int, event_id: str) -> bool:
        return await asyncio.to_thread(
            self._remove_favorite_sync, chat_id, event_id
        )

    def _remove_favorite_sync(self, chat_id: int, event_id: str) -> bool:
        with self._db() as connection:
            cursor = connection.execute(
                "DELETE FROM favorites WHERE chat_id = ? AND event_id = ?",
                (chat_id, event_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    async def is_favorite(self, chat_id: int, event_id: str) -> bool:
        return await asyncio.to_thread(self._is_favorite_sync, chat_id, event_id)

    def _is_favorite_sync(self, chat_id: int, event_id: str) -> bool:
        with self._db() as connection:
            row = connection.execute(
                "SELECT 1 FROM favorites WHERE chat_id = ? AND event_id = ?",
                (chat_id, event_id),
            ).fetchone()
        return row is not None

    async def favorites(self, chat_id: int) -> list[Favorite]:
        return await asyncio.to_thread(self._favorites_sync, chat_id)

    def _favorites_sync(self, chat_id: int) -> list[Favorite]:
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT * FROM favorites
                WHERE chat_id = ?
                ORDER BY COALESCE(starts_at, '9999') ASC, created_at DESC
                """,
                (chat_id,),
            ).fetchall()
        return [self._favorite_from_row(row) for row in rows]

    @staticmethod
    def _favorite_from_row(row: sqlite3.Row) -> Favorite:
        return Favorite(
            chat_id=int(row["chat_id"]),
            event_id=str(row["event_id"]),
            title=row["title"],
            starts_at=row["starts_at"],
            date_text=row["date_text"],
            source_url=row["source_url"],
            city=row["city"],
            region=row["region"],
            category=row["category"],
            reminded_offsets=_loads_list(row["reminded_offsets"]),
            created_at=row["created_at"],
        )

    async def all_favorites(self) -> list[Favorite]:
        return await asyncio.to_thread(self._all_favorites_sync)

    def _all_favorites_sync(self) -> list[Favorite]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM favorites ORDER BY COALESCE(starts_at, '9999') ASC"
            ).fetchall()
        return [self._favorite_from_row(row) for row in rows]

    async def mark_reminded(self, chat_id: int, event_id: str, offset: str) -> None:
        await asyncio.to_thread(
            self._mark_reminded_sync, chat_id, event_id, offset
        )

    def _mark_reminded_sync(self, chat_id: int, event_id: str, offset: str) -> None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT reminded_offsets FROM favorites WHERE chat_id = ? AND event_id = ?",
                (chat_id, event_id),
            ).fetchone()
            if row is None:
                return
            offsets = _loads_list(row["reminded_offsets"])
            if offset not in offsets:
                offsets.append(offset)
            connection.execute(
                "UPDATE favorites SET reminded_offsets = ? WHERE chat_id = ? AND event_id = ?",
                (json.dumps(offsets, ensure_ascii=False), chat_id, event_id),
            )
            connection.commit()

    # ---------------------------------------------------------- event tokens

    @staticmethod
    def event_token(event_id: str) -> str:
        return hashlib.sha1(event_id.encode("utf-8")).hexdigest()[:12]

    async def remember_events(self, events: Iterable[dict[str, Any]]) -> None:
        payloads = []
        now = utc_now()
        for event in events:
            event_id = str(event.get("id") or event.get("event_id") or "")
            if not event_id:
                continue
            payloads.append(
                (
                    self.event_token(event_id),
                    event_id,
                    json.dumps(event, ensure_ascii=False, default=str),
                    now,
                    now,
                )
            )
        if not payloads:
            return
        await asyncio.to_thread(self._remember_events_sync, payloads)

    def _remember_events_sync(self, payloads: list[tuple[str, str, str, str, str]]) -> None:
        with self._db() as connection:
            connection.executemany(
                """
                INSERT INTO event_refs (token, event_id, payload, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    event_id = excluded.event_id,
                    payload = excluded.payload,
                    last_used_at = excluded.last_used_at
                """,
                payloads,
            )
            connection.commit()

    async def get_event_by_token(self, token: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_event_by_token_sync, token)

    def _get_event_by_token_sync(self, token: str) -> dict[str, Any] | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT payload FROM event_refs WHERE token = ?", (token,)
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE event_refs SET last_used_at = ? WHERE token = ?",
                    (utc_now(), token),
                )
                connection.commit()
        return _loads_json(row["payload"]) if row else None

    # ------------------------------------------------------------- analytics

    async def log_event(
        self, chat_id: int | None, kind: str, payload: str | None = None
    ) -> None:
        await asyncio.to_thread(self._log_event_sync, chat_id, kind, payload)

    def _log_event_sync(
        self, chat_id: int | None, kind: str, payload: str | None
    ) -> None:
        with self._db() as connection:
            connection.execute(
                "INSERT INTO interactions (chat_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, kind, payload, utc_now()),
            )
            connection.commit()

    async def set_ui_message(self, chat_id: int, message_id: int) -> None:
        await asyncio.to_thread(self._set_ui_message_sync, chat_id, message_id)

    def _set_ui_message_sync(self, chat_id: int, message_id: int) -> None:
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO ui_messages (chat_id, message_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    message_id = excluded.message_id,
                    updated_at = excluded.updated_at
                """,
                (chat_id, message_id, utc_now()),
            )

    async def get_ui_message(self, chat_id: int) -> int | None:
        return await asyncio.to_thread(self._get_ui_message_sync, chat_id)

    def _get_ui_message_sync(self, chat_id: int) -> int | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT message_id FROM ui_messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row["message_id"]) if row else None

    async def clear_ui_message(self, chat_id: int) -> None:
        await asyncio.to_thread(self._clear_ui_message_sync, chat_id)

    def _clear_ui_message_sync(self, chat_id: int) -> None:
        with self._db() as connection:
            connection.execute(
                "DELETE FROM ui_messages WHERE chat_id = ?", (chat_id,)
            )

    async def interactions_today(self, chat_id: int, kind: str) -> int:
        return await asyncio.to_thread(
            self._interactions_today_sync, chat_id, kind
        )

    def _interactions_today_sync(self, chat_id: int, kind: str) -> int:
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM interactions
                WHERE chat_id = ? AND kind = ? AND substr(created_at, 1, 10) = ?
                """,
                (chat_id, kind, today_utc()),
            ).fetchone()
        return int(row[0] or 0) if row else 0

    async def record_partner_impression(self, partner_id: str, chat_id: int) -> None:
        await asyncio.to_thread(
            self._record_partner_impression_sync, partner_id, chat_id
        )

    def _record_partner_impression_sync(self, partner_id: str, chat_id: int) -> None:
        day = today_utc()
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO partner_daily (partner_id, day, impressions, clicks)
                VALUES (?, ?, 1, 0)
                ON CONFLICT(partner_id, day) DO UPDATE SET
                    impressions = partner_daily.impressions + 1
                """,
                (partner_id, day),
            )
            connection.execute(
                """
                INSERT INTO partner_user_daily (partner_id, chat_id, day, impressions)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(partner_id, chat_id, day) DO UPDATE SET
                    impressions = partner_user_daily.impressions + 1
                """,
                (partner_id, chat_id, day),
            )
            connection.commit()

    async def partner_impressions_today(self, partner_id: str, chat_id: int) -> int:
        return await asyncio.to_thread(
            self._partner_impressions_today_sync, partner_id, chat_id
        )

    def _partner_impressions_today_sync(self, partner_id: str, chat_id: int) -> int:
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT impressions FROM partner_user_daily
                WHERE partner_id = ? AND chat_id = ? AND day = ?
                """,
                (partner_id, chat_id, today_utc()),
            ).fetchone()
        return int(row["impressions"]) if row else 0

    async def partner_impressions_by_user_today(self, chat_id: int) -> int:
        return await asyncio.to_thread(
            self._partner_impressions_by_user_today_sync, chat_id
        )

    def _partner_impressions_by_user_today_sync(self, chat_id: int) -> int:
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(impressions), 0) AS total
                FROM partner_user_daily
                WHERE chat_id = ? AND day = ?
                """,
                (chat_id, today_utc()),
            ).fetchone()
        return int(row["total"]) if row else 0

    async def record_partner_click(
        self, partner_id: str, chat_id: int | None
    ) -> None:
        await asyncio.to_thread(
            self._record_partner_click_sync, partner_id, chat_id
        )

    def _record_partner_click_sync(
        self, partner_id: str, chat_id: int | None
    ) -> None:
        day = today_utc()
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO partner_daily (partner_id, day, impressions, clicks)
                VALUES (?, ?, 0, 1)
                ON CONFLICT(partner_id, day) DO UPDATE SET
                    clicks = partner_daily.clicks + 1
                """,
                (partner_id, day),
            )
            connection.commit()
        if chat_id is not None:
            self._log_event_sync(chat_id, "partner_click", partner_id)

    async def partner_stats(self, days: int = 7) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._partner_stats_sync, days)

    def _partner_stats_sync(self, days: int) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT partner_id, SUM(impressions) AS impressions, SUM(clicks) AS clicks
                FROM partner_daily
                WHERE day >= ?
                GROUP BY partner_id
                ORDER BY clicks DESC, impressions DESC
                """,
                (since,),
            ).fetchall()
        return [
            {
                "partner_id": row["partner_id"],
                "impressions": int(row["impressions"] or 0),
                "clicks": int(row["clicks"] or 0),
                "ctr": (
                    int(row["clicks"] or 0) / int(row["impressions"]) * 100
                    if row["impressions"]
                    else 0.0
                ),
            }
            for row in rows
        ]

    async def overview(self, days: int = 7) -> dict[str, Any]:
        return await asyncio.to_thread(self._overview_sync, days)

    def _overview_sync(self, days: int) -> dict[str, Any]:
        since_date = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
        since = since_date.isoformat()
        today = today_utc()
        with self._db() as connection:
            def scalar(query: str, params: tuple[Any, ...] = ()) -> int:
                row = connection.execute(query, params).fetchone()
                return int(row[0] or 0) if row else 0

            result = {
                "users_total": scalar("SELECT COUNT(*) FROM users"),
                "users_today": scalar(
                    "SELECT COUNT(*) FROM users WHERE substr(created_at, 1, 10) = ?",
                    (today,),
                ),
                "users_period": scalar(
                    "SELECT COUNT(*) FROM users WHERE substr(created_at, 1, 10) >= ?",
                    (since,),
                ),
                "users_active": scalar(
                    "SELECT COUNT(*) FROM users WHERE substr(last_active_at, 1, 10) >= ?",
                    (since,),
                ),
                "subscriptions": scalar("SELECT COUNT(*) FROM subscriptions"),
                "subscriptions_notify": scalar(
                    "SELECT COUNT(*) FROM subscriptions WHERE notify_enabled = 1"
                ),
                "subscriptions_digest": scalar(
                    "SELECT COUNT(*) FROM subscriptions WHERE digest_enabled = 1"
                ),
                "favorites": scalar("SELECT COUNT(*) FROM favorites"),
                "referrals": scalar(
                    "SELECT COUNT(*) FROM users WHERE referrer_id IS NOT NULL"
                ),
                "searches": scalar(
                    "SELECT COUNT(*) FROM interactions WHERE kind = 'search' AND substr(created_at, 1, 10) >= ?",
                    (since,),
                ),
                "starts": scalar(
                    "SELECT COUNT(*) FROM interactions WHERE kind = 'start' AND substr(created_at, 1, 10) >= ?",
                    (since,),
                ),
                "notifications": scalar(
                    "SELECT COUNT(*) FROM interactions WHERE kind = 'notification_sent' AND substr(created_at, 1, 10) >= ?",
                    (since,),
                ),
                "digests": scalar(
                    "SELECT COUNT(*) FROM interactions WHERE kind = 'digest_sent' AND substr(created_at, 1, 10) >= ?",
                    (since,),
                ),
                "favorites_added": scalar(
                    "SELECT COUNT(*) FROM interactions WHERE kind = 'favorite_add' AND substr(created_at, 1, 10) >= ?",
                    (since,),
                ),
            }

            rows = connection.execute(
                """
                SELECT COALESCE(NULLIF(source, ''), 'direct') AS source,
                       COALESCE(NULLIF(campaign, ''), '') AS campaign,
                       COUNT(*) AS total
                FROM users
                WHERE substr(created_at, 1, 10) >= ?
                GROUP BY source, campaign
                ORDER BY total DESC, source ASC
                LIMIT 12
                """,
                (since,),
            ).fetchall()
            result["sources"] = [
                {
                    "source": row["source"],
                    "campaign": row["campaign"],
                    "total": int(row["total"]),
                }
                for row in rows
            ]

            rows = connection.execute(
                """
                SELECT kind, COUNT(*) AS total
                FROM interactions
                WHERE substr(created_at, 1, 10) >= ?
                GROUP BY kind
                ORDER BY total DESC
                """,
                (since,),
            ).fetchall()
            result["interactions"] = {
                row["kind"]: int(row["total"]) for row in rows
            }
        return result

    # ------------------------------------------------------------- analytics

    async def analytics(self, days: int = 7, limit: int = 10) -> dict[str, Any]:
        return await asyncio.to_thread(self._analytics_sync, days, limit)

    def _analytics_sync(self, days: int, limit: int) -> dict[str, Any]:
        since = (
            datetime.now(timezone.utc).date() - timedelta(days=days - 1)
        ).isoformat()
        with self._db() as connection:
            search_rows = connection.execute(
                """
                SELECT payload FROM interactions
                WHERE kind = 'search' AND substr(created_at, 1, 10) >= ?
                """,
                (since,),
            ).fetchall()
            click_rows = connection.execute(
                """
                SELECT payload FROM interactions
                WHERE kind = 'event_click' AND substr(created_at, 1, 10) >= ?
                """,
                (since,),
            ).fetchall()

        queries: Counter[str] = Counter()
        cities: Counter[str] = Counter()
        categories: Counter[str] = Counter()
        for row in search_rows:
            parsed = parse_search_payload(row["payload"])
            query = parsed["query"].strip()
            if query:
                queries[query] += 1
            cities.update(parsed["cities"])
            categories.update(parsed["categories"])

        events: Counter[str] = Counter()
        event_titles: dict[str, str] = {}
        for row in click_rows:
            parsed = parse_event_click_payload(row["payload"])
            key = parsed["id"] or parsed["title"]
            events[key] += 1
            event_titles[key] = parsed["title"]

        return {
            "queries": [
                {"value": value, "count": count}
                for value, count in queries.most_common(limit)
            ],
            "cities": [
                {"value": value, "count": count}
                for value, count in cities.most_common(limit)
            ],
            "categories": [
                {"value": value, "count": count}
                for value, count in categories.most_common(limit)
            ],
            "events": [
                {
                    "id": key,
                    "title": event_titles.get(key, "Старт"),
                    "count": count,
                }
                for key, count in events.most_common(limit)
            ],
        }

    async def user_activity(self, days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._user_activity_sync, days, limit)

    def _user_activity_sync(self, days: int, limit: int) -> list[dict[str, Any]]:
        since = (
            datetime.now(timezone.utc).date() - timedelta(days=days - 1)
        ).isoformat()
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT
                    u.chat_id,
                    u.username,
                    u.first_name,
                    u.last_active_at,
                    SUM(CASE WHEN i.kind = 'search' THEN 1 ELSE 0 END) AS searches,
                    SUM(CASE WHEN i.kind = 'event_click' THEN 1 ELSE 0 END) AS clicks,
                    SUM(CASE WHEN i.kind = 'partner_click' THEN 1 ELSE 0 END) AS partner_clicks,
                    (SELECT COUNT(*) FROM favorites f WHERE f.chat_id = u.chat_id) AS favorites,
                    EXISTS(
                        SELECT 1 FROM subscriptions s WHERE s.chat_id = u.chat_id
                    ) AS has_subscription
                FROM users u
                LEFT JOIN interactions i
                    ON i.chat_id = u.chat_id
                    AND substr(i.created_at, 1, 10) >= ?
                GROUP BY u.chat_id
                ORDER BY (searches + clicks + partner_clicks) DESC,
                         u.last_active_at DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        return [
            {
                "chat_id": int(row["chat_id"]),
                "username": row["username"],
                "first_name": row["first_name"],
                "last_active_at": row["last_active_at"],
                "searches": int(row["searches"] or 0),
                "clicks": int(row["clicks"] or 0),
                "partner_clicks": int(row["partner_clicks"] or 0),
                "favorites": int(row["favorites"] or 0),
                "has_subscription": bool(row["has_subscription"]),
            }
            for row in rows
        ]

    async def user_details(
        self, chat_id: int, days: int = 7, limit: int = 15
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._user_details_sync, chat_id, days, limit)

    def _user_details_sync(
        self, chat_id: int, days: int, limit: int
    ) -> dict[str, Any] | None:
        since = (
            datetime.now(timezone.utc).date() - timedelta(days=days - 1)
        ).isoformat()
        with self._db() as connection:
            user_row = connection.execute(
                "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if user_row is None:
                return None
            search_rows = connection.execute(
                """
                SELECT payload, created_at FROM interactions
                WHERE chat_id = ? AND kind = 'search'
                    AND substr(created_at, 1, 10) >= ?
                ORDER BY id DESC LIMIT ?
                """,
                (chat_id, since, limit),
            ).fetchall()
            click_rows = connection.execute(
                """
                SELECT payload, created_at FROM interactions
                WHERE chat_id = ? AND kind = 'event_click'
                    AND substr(created_at, 1, 10) >= ?
                ORDER BY id DESC LIMIT ?
                """,
                (chat_id, since, limit),
            ).fetchall()
            partner_rows = connection.execute(
                """
                SELECT payload, created_at FROM interactions
                WHERE chat_id = ? AND kind = 'partner_click'
                    AND substr(created_at, 1, 10) >= ?
                ORDER BY id DESC LIMIT ?
                """,
                (chat_id, since, limit),
            ).fetchall()
            favorites_row = connection.execute(
                "SELECT COUNT(*) FROM favorites WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            subscription_row = connection.execute(
                "SELECT cities, categories FROM subscriptions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            totals_rows = connection.execute(
                """
                SELECT kind, COUNT(*) AS total FROM interactions
                WHERE chat_id = ? AND substr(created_at, 1, 10) >= ?
                    AND kind IN ('search', 'event_click', 'partner_click')
                GROUP BY kind
                """,
                (chat_id, since),
            ).fetchall()
        totals = {row["kind"]: int(row["total"]) for row in totals_rows}

        return {
            "chat_id": int(user_row["chat_id"]),
            "username": user_row["username"],
            "first_name": user_row["first_name"],
            "last_active_at": user_row["last_active_at"],
            "searches": [
                {
                    **parse_search_payload(row["payload"]),
                    "created_at": row["created_at"],
                }
                for row in search_rows
            ],
            "clicks": [
                {
                    **parse_event_click_payload(row["payload"]),
                    "created_at": row["created_at"],
                }
                for row in click_rows
            ],
            "partner_clicks": [
                {"partner_id": row["payload"], "created_at": row["created_at"]}
                for row in partner_rows
            ],
            "favorites": int(favorites_row[0] or 0) if favorites_row else 0,
            "search_total": totals.get("search", 0),
            "click_total": totals.get("event_click", 0),
            "partner_click_total": totals.get("partner_click", 0),
            "subscription": (
                {
                    "cities": _loads_list(subscription_row["cities"]),
                    "categories": _loads_list(subscription_row["categories"]),
                }
                if subscription_row
                else None
            ),
        }

    async def all_user_ids(self) -> list[int]:
        return await asyncio.to_thread(self._all_user_ids_sync)

    def _all_user_ids_sync(self) -> list[int]:
        with self._db() as connection:
            rows = connection.execute("SELECT chat_id FROM users").fetchall()
        return [int(row["chat_id"]) for row in rows]

    async def prune(self) -> None:
        await asyncio.to_thread(self._prune_sync)

    def _prune_sync(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        with self._db() as connection:
            connection.execute(
                "DELETE FROM event_refs WHERE last_used_at < ?", (cutoff,)
            )
            connection.commit()
