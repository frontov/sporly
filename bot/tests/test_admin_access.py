from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api_client import api_client
from app.config import settings
from app.handlers.admin import _is_admin, admin_callbacks, cmd_featured


class AdminAccessTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.admin_patch = patch.object(
            settings, "admin_telegram_ids", "111,222"
        )
        self.admin_patch.start()

    def tearDown(self) -> None:
        self.admin_patch.stop()

    def test_only_configured_ids_are_admins(self) -> None:
        self.assertTrue(_is_admin(111))
        self.assertFalse(_is_admin(999))
        self.assertFalse(_is_admin(None))

    async def test_featured_command_does_nothing_for_non_admin(self) -> None:
        message = MagicMock()
        message.from_user.id = 999
        message.answer = AsyncMock()
        command = MagicMock()
        command.args = "event-1"

        with patch.object(
            api_client, "admin_feature_event", AsyncMock()
        ) as feature:
            await cmd_featured(message, command)

        message.answer.assert_not_awaited()
        feature.assert_not_awaited()

    async def test_featured_callback_rejects_non_admin(self) -> None:
        callback = MagicMock()
        callback.from_user.id = 999
        callback.data = "admin:rec:token"
        callback.answer = AsyncMock()

        with patch.object(
            api_client, "admin_feature_event", AsyncMock()
        ) as feature:
            await admin_callbacks(callback, bot=MagicMock())

        callback.answer.assert_awaited_once_with(
            "Только для администратора", show_alert=True
        )
        feature.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
