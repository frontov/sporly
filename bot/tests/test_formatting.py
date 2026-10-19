from __future__ import annotations

import unittest

from app.api_client import Event
from app.formatting import format_event, format_event_card, format_event_list, pick_image
from app.storage import Favorite


class FormattingTest(unittest.TestCase):
    def test_event_card_escapes_html(self) -> None:
        event = Event(
            id="1",
            title="<script>alert(1)</script>",
            description="Описание",
            starts_at="2027-06-01T00:00:00",
            category="Бег",
            city="Москва",
            region="Москва",
            source_name="Сайт",
            source_url="https://example.com/?a=1&b=2",
        )
        text = format_event(event)
        self.assertNotIn("<script>", text)
        self.assertIn("alert(1)", text)
        self.assertIn("1 июня 2027", text)
        self.assertIn("https://example.com/?a=1&amp;b=2", text)

    def test_event_list_uses_colored_markers(self) -> None:
        events = [
            Event(id=str(index), title=f"Старт {index}", source_name="Сайт")
            for index in range(1, 3)
        ]
        text = format_event_list(
            events, total=10, page=2, total_pages=5, page_size=4
        )
        self.assertIn("🔴 Старт 1", text)
        self.assertIn("🟠 Старт 2", text)
        self.assertNotIn("6. Старт", text)
        self.assertIn("стр. 2/5", text)

    def test_event_list_titles_are_not_external_links(self) -> None:
        events = [
            Event(
                id="1",
                title="Старт",
                source_name="Сайт",
                source_url="https://example.com/event",
            )
        ]
        text = format_event_list(
            events, total=1, page=1, total_pages=1, page_size=4
        )
        self.assertNotIn("https://example.com/event", text)
        self.assertIn("🔴 Старт", text)

    def test_event_card_fits_photo_caption(self) -> None:
        event = Event(
            id="1",
            title="Очень длинное название старта " * 10,
            description="Описание " * 100,
            starts_at="2027-06-01T00:00:00",
            category="Бег",
            city="Москва",
            distance_summary="42 км",
            price_from="от 3000 ₽",
            source_name="Очень длинное название источника " * 3,
            source_url="https://example.com",
        )
        text = format_event_card(event)
        self.assertLessEqual(len(text), 1024)

    def test_pick_image_skips_svg(self) -> None:
        event = Event(
            id="1",
            title="Старт",
            image_url="https://example.com/poster.svg",
        )
        self.assertIsNone(pick_image(event))
        event.image_url = "https://example.com/poster.jpg"
        self.assertEqual(pick_image(event), "https://example.com/poster.jpg")

    def test_event_list_has_no_deep_start_links(self) -> None:
        events = [Event(id="1", title="Старт", source_name="Сайт")]
        text = format_event_list(
            events, total=1, page=1, total_pages=1, page_size=4
        )
        self.assertNotIn("start=fav_", text)
        self.assertNotIn("t.me/", text)

    def test_event_list_has_detail_deep_link(self) -> None:
        events = [Event(id="1", title="Старт", source_name="Сайт")]
        text = format_event_list(
            events,
            total=1,
            page=1,
            total_pages=1,
            page_size=4,
            bot_username="sporly_bot",
        )
        self.assertIn("start=ev_", text)
        self.assertIn("Подробнее", text)

        linked = format_event_list(
            events,
            total=1,
            page=2,
            total_pages=3,
            page_size=4,
            bot_username="sporly_bot",
            session_id="abcd1234",
        )
        self.assertIn("start=evl_", linked)
        self.assertIn("abcd1234_2", linked)

    def test_favorite_location(self) -> None:
        favorite = Favorite(
            chat_id=1,
            event_id="1",
            title="Старт",
            starts_at="2027-06-01T00:00:00",
            date_text=None,
            source_url="https://example.com",
            city="Казань",
            region="Республика Татарстан",
        )
        self.assertEqual(favorite.location, "Казань, Республика Татарстан")


if __name__ == "__main__":
    unittest.main()
