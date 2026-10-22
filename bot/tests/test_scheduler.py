from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

from app.api_client import Event
from app.scheduler import (
    _effective_digest_hour_utc,
    _next_digest_time,
    is_quiet_hours,
    reminder_offset,
    seconds_until_quiet_end,
)
from app.storage import Subscription
from app.text import MOSCOW_TZ
import app.scheduler as scheduler


class ReminderTest(unittest.TestCase):
    def test_exact_threshold(self) -> None:
        self.assertEqual(reminder_offset(7, set()), 7)
        self.assertEqual(reminder_offset(3, {"7"}), 3)
        self.assertEqual(reminder_offset(1, {"7", "3"}), 1)
        self.assertEqual(reminder_offset(0, {"7", "3", "1"}), 0)

    def test_missed_thresholds_send_only_once(self) -> None:
        self.assertEqual(reminder_offset(2, set()), 7)
        self.assertEqual(reminder_offset(2, {"7", "3"}), None)
        self.assertEqual(reminder_offset(5, {"7"}), None)

    def test_after_start_returns_none(self) -> None:
        self.assertEqual(reminder_offset(-1, set()), None)


class QuietHoursTest(unittest.TestCase):
    @staticmethod
    def _at(hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 10, 22, hour, minute, tzinfo=MOSCOW_TZ)

    def test_night_is_quiet(self) -> None:
        self.assertTrue(is_quiet_hours(self._at(23)))
        self.assertTrue(is_quiet_hours(self._at(8, 59)))

    def test_day_is_not_quiet(self) -> None:
        self.assertFalse(is_quiet_hours(self._at(9)))
        self.assertFalse(is_quiet_hours(self._at(21, 59)))

    def test_sleeps_until_morning(self) -> None:
        self.assertEqual(seconds_until_quiet_end(self._at(23)), 10 * 60 * 60)
        self.assertEqual(seconds_until_quiet_end(self._at(8)), 60 * 60)

    def test_digest_never_lands_at_night(self) -> None:
        # Default digest hour is 06:00 UTC = 09:00 Moscow.
        self.assertEqual(_effective_digest_hour_utc(), 6)
        target = _next_digest_time(
            datetime(2026, 10, 22, 3, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(target.hour, 6)


class NewEventBatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_is_sent_as_one_message(self) -> None:
        bot = AsyncMock()
        subscription = Subscription(
            chat_id=1, cities=["Москва"], categories=["Бег"]
        )
        events = [
            Event(
                id="1",
                title="Первый старт",
                source_url="https://example.com/1",
            ),
            Event(
                id="2",
                title="Второй старт",
                source_url="https://example.com/2",
            ),
        ]
        with (
            patch.object(
                scheduler,
                "_event_tokens",
                AsyncMock(return_value={"1": "token-1", "2": "token-2"}),
            ),
            patch.object(
                scheduler, "_favorite_ids", AsyncMock(return_value=set())
            ),
            patch.object(scheduler.database, "mark_seen", AsyncMock()),
            patch.object(scheduler.database, "log_event", AsyncMock()),
        ):
            await scheduler._send_new_events_batch(bot, subscription, events)

        bot.send_message.assert_awaited_once()
        text = bot.send_message.await_args.args[1]
        self.assertIn("Первый старт", text)
        self.assertIn("Второй старт", text)
        self.assertEqual(
            bot.send_message.await_args.kwargs["reply_markup"]
            .inline_keyboard[-2][0]
            .callback_data,
            "menu:sub",
        )


if __name__ == "__main__":
    unittest.main()


class NewEventTest(unittest.TestCase):
    def test_new_since(self) -> None:
        from app.scheduler import is_new_since

        self.assertTrue(is_new_since("2026-10-19T12:00:00", "2026-10-19T11:00:00"))
        self.assertFalse(is_new_since("2026-10-19T10:00:00", "2026-10-19T11:00:00"))
        self.assertTrue(is_new_since(None, "2026-10-19T11:00:00"))
        self.assertTrue(is_new_since("2026-10-19T12:00:00", None))

    def test_new_since_timezone(self) -> None:
        from app.scheduler import is_new_since

        self.assertTrue(
            is_new_since(
                "2026-10-19T12:00:00+00:00",
                "2026-10-19T14:00:00+03:00",
            )
        )


if __name__ == "__main__":
    unittest.main()
