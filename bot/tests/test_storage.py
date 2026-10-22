from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sqlite3

from app.storage import Database


class DatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "test.db")
        await self.db.init()

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_user_attribution_and_subscription(self) -> None:
        user = await self.db.ensure_user(1, "roman", "Роман")
        self.assertEqual(user.chat_id, 1)
        self.assertTrue(user.reminders_enabled)
        self.assertTrue(await self.db.reminders_enabled(1))

        toggled_reminders = await self.db.toggle_reminders(1)
        self.assertFalse(toggled_reminders)
        self.assertFalse(await self.db.reminders_enabled(1))

        await self.db.set_attribution(1, source="telegram_ad", campaign="may")
        await self.db.set_attribution(1, source="other", campaign="other")
        user = await self.db.get_user(1)
        self.assertEqual(user.source, "telegram_ad")
        self.assertEqual(user.campaign, "may")

        subscription = await self.db.save_subscription(
            1, cities=["Москва"], categories=["Бег"]
        )
        self.assertEqual(subscription.cities, ["Москва"])
        self.assertTrue(subscription.notify_enabled)
        self.assertFalse(subscription.digest_enabled)

        toggled = await self.db.toggle_subscription(1, "notify_enabled")
        self.assertFalse(toggled.notify_enabled)

        await self.db.ensure_user(2)
        await self.db.set_referrer(2, 1)
        self.assertEqual(await self.db.referral_count(1), 1)

    async def test_reminders_column_is_added_to_old_database(self) -> None:
        path = Path(self.tempdir.name) / "old.db"
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE users (
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
            """
        )
        connection.commit()
        connection.close()

        old_db = Database(path)
        await old_db.init()
        user = await old_db.ensure_user(5)
        self.assertTrue(user.reminders_enabled)
        self.assertTrue(await old_db.reminders_enabled(5))

    async def test_seen_events(self) -> None:
        await self.db.ensure_user(1)
        await self.db.mark_seen(1, ["a", "b", "a"])
        self.assertEqual(await self.db.seen_ids(1), {"a", "b"})

    async def test_favorites_and_reminders(self) -> None:
        await self.db.ensure_user(1)
        await self.db.add_favorite(
            1,
            {
                "event_id": "event-1",
                "title": "Забег",
                "starts_at": "2026-06-01T00:00:00",
                "date_text": "01.06.2026",
                "source_url": "https://example.com/event",
                "city": "Москва",
                "region": "Москва",
                "category": "Бег",
            },
        )
        favorites = await self.db.favorites(1)
        self.assertEqual(len(favorites), 1)
        self.assertEqual(favorites[0].title, "Забег")

        await self.db.mark_reminded(1, "event-1", "7")
        favorites = await self.db.favorites(1)
        self.assertEqual(favorites[0].reminded_offsets, ["7"])

        self.assertTrue(await self.db.remove_favorite(1, "event-1"))
        self.assertEqual(await self.db.favorites(1), [])

    async def test_event_tokens(self) -> None:
        await self.db.ensure_user(1)
        event = {
            "id": "long-event-id-" * 10,
            "title": "Событие",
            "source_url": "https://example.com",
        }
        await self.db.remember_events([event])
        token = self.db.event_token(event["id"])
        self.assertEqual(len(token), 12)
        payload = await self.db.get_event_by_token(token)
        self.assertEqual(payload["title"], "Событие")

    async def test_ui_message_marker(self) -> None:
        await self.db.ensure_user(1)
        self.assertIsNone(await self.db.get_ui_message(1))
        await self.db.set_ui_message(1, 777)
        self.assertEqual(await self.db.get_ui_message(1), 777)
        await self.db.clear_ui_message(1)
        self.assertIsNone(await self.db.get_ui_message(1))

    async def test_partner_counters(self) -> None:
        await self.db.ensure_user(1)
        await self.db.record_partner_impression("partner", 1)
        await self.db.record_partner_impression("partner", 1)
        await self.db.record_partner_click("partner", 1)
        self.assertEqual(await self.db.partner_impressions_today("partner", 1), 2)
        stats = await self.db.partner_stats(days=7)
        self.assertEqual(stats[0]["impressions"], 2)
        self.assertEqual(stats[0]["clicks"], 1)
        self.assertAlmostEqual(stats[0]["ctr"], 50.0)


if __name__ == "__main__":
    unittest.main()


class AnalyticsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "test.db")
        await self.db.init()
        await self.db.ensure_user(1, "roman", "Роман")

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_search_and_click_analytics(self) -> None:
        import json

        await self.db.log_event(
            1,
            "search",
            json.dumps(
                {
                    "query": "бег",
                    "cities": ["Москва"],
                    "categories": ["Бег"],
                },
                ensure_ascii=False,
            ),
        )
        await self.db.log_event(
            1,
            "event_click",
            json.dumps(
                {"id": "event-1", "title": "Забег", "url": "https://example.com"},
                ensure_ascii=False,
            ),
        )
        await self.db.log_event(1, "partner_click", "partner-1")

        analytics = await self.db.analytics(days=7)
        self.assertEqual(analytics["queries"][0]["value"], "бег")
        self.assertEqual(analytics["cities"][0]["value"], "Москва")
        self.assertEqual(analytics["categories"][0]["value"], "Бег")
        self.assertEqual(analytics["events"][0]["title"], "Забег")

        activity = await self.db.user_activity(days=7)
        self.assertEqual(activity[0]["searches"], 1)
        self.assertEqual(activity[0]["clicks"], 1)
        self.assertEqual(activity[0]["partner_clicks"], 1)

        details = await self.db.user_details(1, days=7)
        self.assertEqual(details["search_total"], 1)
        self.assertEqual(details["click_total"], 1)
        self.assertEqual(details["searches"][0]["query"], "бег")
        self.assertEqual(details["clicks"][0]["title"], "Забег")

    async def test_old_pipe_payload_parsing(self) -> None:
        await self.db.log_event(1, "search", "лыжи|Москва,Казань|Лыжи")
        analytics = await self.db.analytics(days=7)
        self.assertEqual(analytics["queries"][0]["value"], "лыжи")
        self.assertEqual(analytics["cities"][0]["value"], "Москва")
