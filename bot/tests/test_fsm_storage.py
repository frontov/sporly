from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aiogram.fsm.storage.base import StorageKey

from app.fsm_storage import SQLiteFSMStorage


class FSMStorageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = SQLiteFSMStorage(Path(self.tempdir.name) / "fsm.db")
        self.key = StorageKey(bot_id=1, chat_id=2, user_id=2)

    async def asyncTearDown(self) -> None:
        await self.storage.close()
        self.tempdir.cleanup()

    async def test_state_and_data_persist(self) -> None:
        await self.storage.set_state(self.key, "FlowStates:waiting_city")
        await self.storage.set_data(self.key, {"cities": ["Москва"]})

        self.assertEqual(
            await self.storage.get_state(self.key), "FlowStates:waiting_city"
        )
        self.assertEqual(
            await self.storage.get_data(self.key), {"cities": ["Москва"]}
        )

        await self.storage.update_data(self.key, {"categories": ["Бег"]})
        self.assertEqual(
            await self.storage.get_data(self.key),
            {"cities": ["Москва"], "categories": ["Бег"]},
        )

    async def test_data_survives_reopen(self) -> None:
        await self.storage.set_data(self.key, {"cities": ["Казань"]})
        other = SQLiteFSMStorage(Path(self.tempdir.name) / "fsm.db")
        self.assertEqual(
            await other.get_data(self.key), {"cities": ["Казань"]}
        )
        await other.close()
