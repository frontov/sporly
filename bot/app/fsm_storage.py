from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Dict, Optional

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey


StateType = Optional[str | State]


class SQLiteFSMStorage(BaseStorage):
    """Small persistent FSM storage so a deploy does not reset a survey.

    It lives in the same SQLite file as the rest of the bot data.
    """

    def __init__(self, path) -> None:
        self.path = str(path)
        self._init_done = False
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
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
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=14)
        ).isoformat()
        with self._db() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fsm_states (
                    bot_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    state TEXT,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (bot_id, chat_id, user_id)
                )
                """
            )
            connection.execute(
                "DELETE FROM fsm_states WHERE updated_at < ?", (cutoff,)
            )
            connection.commit()

    async def _ensure(self) -> None:
        if self._init_done:
            return
        async with self._lock:
            if self._init_done:
                return
            await asyncio.to_thread(self._init_sync)
            self._init_done = True

    @staticmethod
    def _params(key: StorageKey) -> tuple[int, int, int]:
        return int(key.bot_id), int(key.chat_id), int(key.user_id)

    @staticmethod
    def _state_value(state: StateType) -> str | None:
        if state is None:
            return None
        if isinstance(state, State):
            return state.state
        return str(state)

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        await self._ensure()
        await asyncio.to_thread(
            self._set_state_sync, key, self._state_value(state)
        )

    def _set_state_sync(self, key: StorageKey, state: str | None) -> None:
        bot_id, chat_id, user_id = self._params(key)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO fsm_states
                    (bot_id, chat_id, user_id, state, data, updated_at)
                VALUES (?, ?, ?, ?, '{}', ?)
                ON CONFLICT(bot_id, chat_id, user_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (bot_id, chat_id, user_id, state, now),
            )
            connection.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        await self._ensure()
        return await asyncio.to_thread(self._get_state_sync, key)

    def _get_state_sync(self, key: StorageKey) -> str | None:
        bot_id, chat_id, user_id = self._params(key)
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT state FROM fsm_states
                WHERE bot_id = ? AND chat_id = ? AND user_id = ?
                """,
                (bot_id, chat_id, user_id),
            ).fetchone()
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        await self._ensure()
        await asyncio.to_thread(self._set_data_sync, key, data)

    def _set_data_sync(self, key: StorageKey, data: Dict[str, Any]) -> None:
        bot_id, chat_id, user_id = self._params(key)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = json.dumps(data, ensure_ascii=False, default=str)
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO fsm_states
                    (bot_id, chat_id, user_id, state, data, updated_at)
                VALUES (?, ?, ?, NULL, ?, ?)
                ON CONFLICT(bot_id, chat_id, user_id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (bot_id, chat_id, user_id, payload, now),
            )
            connection.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        await self._ensure()
        return await asyncio.to_thread(self._get_data_sync, key)

    def _get_data_sync(self, key: StorageKey) -> Dict[str, Any]:
        bot_id, chat_id, user_id = self._params(key)
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT data FROM fsm_states
                WHERE bot_id = ? AND chat_id = ? AND user_id = ?
                """,
                (bot_id, chat_id, user_id),
            ).fetchone()
        if row is None:
            return {}
        try:
            parsed = json.loads(row["data"])
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    async def close(self) -> None:
        return None
