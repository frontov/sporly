from __future__ import annotations

import unittest

from app.config import settings
from app.links import event_click_url, event_token


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
