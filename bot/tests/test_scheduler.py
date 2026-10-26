from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
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
import app.flows as flows
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
    async def test_batch_is_rendered_as_the_nearest_starts_screen(self) -> None:
        bot = AsyncMock()
        subscription = Subscription(
            chat_id=1, cities=["Москва"], categories=["Бег"]
        )
        events = [
            Event(
                id="1",
                title="Первый старт",
                source_url="https://example.com/1",
                starts_at="2026-11-01T00:00:00",
                city="Москва",
            ),
            Event(
                id="2",
                title="Второй старт",
                source_url="https://example.com/2",
                starts_at="2026-11-02T00:00:00",
                city="Москва",
            ),
        ]
        screen = AsyncMock(return_value=object())
        mark_seen = AsyncMock()
        with (
            patch.object(scheduler, "render_search_page", screen),
            patch.object(scheduler.database, "mark_seen", mark_seen),
            patch.object(scheduler.database, "log_event", AsyncMock()),
        ):
            delivered = await scheduler._send_new_events_batch(
                bot, subscription, events, bot_username="sporly_bot"
            )

        self.assertTrue(delivered)
        screen.assert_awaited_once()
        session = screen.await_args.args[2]
        self.assertEqual(session.events, events)
        self.assertEqual(session.title, scheduler.NEW_EVENTS_TITLE)
        self.assertEqual(session.cities, ["Москва"])
        self.assertEqual(
            screen.await_args.kwargs,
            {"page": 1, "bot_username": "sporly_bot", "silent": True},
        )
        self.assertEqual(mark_seen.await_count, 2)

    async def test_batch_marks_nothing_when_screen_is_not_sent(self) -> None:
        subscription = Subscription(chat_id=1, cities=[], categories=[])
        events = [Event(id="1", title="Старт", source_url="https://e/1")]
        with (
            patch.object(
                scheduler, "render_search_page", AsyncMock(return_value=None)
            ),
            patch.object(scheduler.database, "mark_seen", AsyncMock()) as mark_seen,
            patch.object(scheduler.database, "log_event", AsyncMock()),
        ):
            delivered = await scheduler._send_new_events_batch(
                AsyncMock(), subscription, events
            )

        self.assertFalse(delivered)
        mark_seen.assert_not_awaited()


class NewEventsScreenTest(unittest.IsolatedAsyncioTestCase):
    async def test_notification_uses_the_nearest_starts_card_layout(self) -> None:
        bot = AsyncMock()
        bot.send_message.return_value = SimpleNamespace(message_id=42)
        events = [
            Event(
                id="1",
                title="Первый старт",
                source_url="https://example.com/1",
                starts_at="2026-11-01T00:00:00",
                date_text="01.11.2026",
                city="Москва",
                region="Москва",
                category="Бег",
                distance_summary="21 км",
                price_from="от 1500 ₽",
            ),
            Event(
                id="2",
                title="Второй старт",
                source_url="https://example.com/2",
                starts_at="2026-11-02T00:00:00",
                date_text="02.11.2026",
                city="Москва",
                region="Москва",
            ),
        ]
        session = scheduler.search_sessions.create(
            1,
            cities=["Москва"],
            categories=["Бег"],
            events=events,
            title=scheduler.NEW_EVENTS_TITLE,
        )
        with (
            patch.object(flows, "_season_media", lambda _season: None),
            patch.object(
                flows, "_find_partner", AsyncMock(return_value=(None, None))
            ),
            patch.object(flows.database, "remember_events", AsyncMock()),
            patch.object(flows.database, "set_ui_message", AsyncMock()),
        ):
            sent = await scheduler.render_search_page(
                bot, 1, session, bot_username="sporly_bot", silent=True
            )

        self.assertIsNotNone(sent)
        text = bot.send_message.await_args.args[1]
        self.assertIn("🆕 Новые старты по вашим интересам", text)
        self.assertIn("🔴 Первый старт", text)
        self.assertIn("🟠 Второй старт", text)
        self.assertIn("📅", text)
        self.assertIn("📅 1 ноя · Москва", text)
        self.assertIn("Подробнее →", text)
        self.assertNotIn("⭐", text)

        keyboard = bot.send_message.await_args.kwargs["reply_markup"]
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("menu:find", callbacks)
        self.assertIn("menu:home", callbacks)
        self.assertFalse(any(str(cb).startswith("fv:") for cb in callbacks))

    async def test_snapshot_pagination_splits_events_into_pages(self) -> None:
        events = [
            Event(id=str(index), title=f"Старт {index}") for index in range(5)
        ]
        session = scheduler.search_sessions.create(1, events=events)
        page_one = flows._snapshot_page(session, 1)
        page_two = flows._snapshot_page(session, 2)

        self.assertEqual(len(page_one.items), flows.PAGE_SIZE)
        self.assertEqual(page_one.total_pages, 2)
        self.assertEqual(page_two.page, 2)
        self.assertEqual(len(page_two.items), 5 - flows.PAGE_SIZE)


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
