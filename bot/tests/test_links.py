from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from app.config import settings
from app.links import event_click_url, event_token, share_text, share_url


class LinkTest(unittest.TestCase):
    def test_token_is_stable(self) -> None:
        self.assertEqual(event_token("abc"), event_token("abc"))
        self.assertEqual(len(event_token("abc")), 12)

    def test_direct_url_without_public_base(self) -> None:
        previous = settings.public_base_url
        try:
            settings.public_base_url = ""
            self.assertEqual(
                event_click_url(1, "event-1", "https://example.com/event"),
                "https://example.com/event",
            )
        finally:
            settings.public_base_url = previous

    def test_tracked_url_with_public_base(self) -> None:
        previous = settings.public_base_url
        try:
            settings.public_base_url = "https://sporly.ru/"
            self.assertEqual(
                event_click_url(42, "event-1", "https://example.com/event"),
                f"https://sporly.ru/go/event/{event_token('event-1')}?uid=42",
            )
        finally:
            settings.public_base_url = previous

    def test_share_text_uses_the_event_title(self) -> None:
        self.assertEqual(share_text("Ночной забег"), "Ночной забег — Sporly")
        self.assertEqual(share_text("  Ночной   забег "), "Ночной забег — Sporly")
        self.assertEqual(share_text(None), "Старт в Sporly")
        self.assertEqual(share_text("   "), "Старт в Sporly")

    def test_long_share_text_is_truncated(self) -> None:
        text = share_text("Очень длинное название старта " * 10)

        self.assertTrue(text.endswith("— Sporly"))
        self.assertLessEqual(len(text), 100 + len(" — Sporly"))

    def test_share_url_carries_title_and_start_token(self) -> None:
        url = share_url("sporly_bot", "abc123456789", "Ночной забег")

        self.assertIsNotNone(url)
        query = parse_qs(urlparse(str(url)).query)
        self.assertEqual(
            query["url"], ["https://t.me/sporly_bot?start=ev_abc123456789"]
        )
        self.assertEqual(query["text"], ["Ночной забег — Sporly"])

    def test_share_url_without_bot_username(self) -> None:
        self.assertIsNone(share_url("", "abc", "Ночной забег"))
