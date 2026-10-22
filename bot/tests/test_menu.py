from __future__ import annotations

import unittest

from app.hints import HINT_FAVORITE, HINT_HELP, HINT_TAP_DETAIL
from app.keyboards import (
    BUTTON_FAVORITE,
    BUTTON_FAVORITED,
    BUTTON_FIND,
    BUTTON_HOME,
    BUTTON_OPEN,
    BUTTON_SHARE,
    category_keyboard,
    city_keyboard,
    delete_subscription_keyboard,
    event_detail_keyboard,
    favorites_list_keyboard,
    home_keyboard,
    interests_saved_keyboard,
    menu_callback_for_text,
    more_keyboard,
    no_results_keyboard,
    notification_settings_keyboard,
    search_hub_keyboard,
    search_list_keyboard,
    single_event_keyboard,
    subscription_keyboard,
)
from app.storage import Subscription


class MenuTextTest(unittest.TestCase):
    def test_new_buttons(self) -> None:
        self.assertEqual(menu_callback_for_text(BUTTON_FIND), "menu:find")
        self.assertEqual(menu_callback_for_text("🎯 Мои интересы"), "menu:sub")
        self.assertEqual(menu_callback_for_text("⚙️ Ещё"), "menu:more")

    def test_legacy_buttons(self) -> None:
        self.assertEqual(menu_callback_for_text("🔍 Найти события"), "menu:find")
        self.assertEqual(menu_callback_for_text("Ближайшие"), "menu:soon")
        self.assertEqual(menu_callback_for_text("Мои события"), "menu:sub")
        self.assertEqual(menu_callback_for_text("🎯 Подписка"), "menu:sub")
        self.assertEqual(menu_callback_for_text("⚙️ Настройки"), "menu:more")
        self.assertEqual(menu_callback_for_text("уведомления"), "menu:notify")

    def test_regular_query_is_not_a_menu(self) -> None:
        self.assertIsNone(menu_callback_for_text("забег в Казани"))

    def test_help_aliases(self) -> None:
        for label in ("помощь", "справка", "как пользоваться", "help"):
            self.assertEqual(menu_callback_for_text(label), "menu:help")


class HintTest(unittest.TestCase):
    """Each screen should explain the next tap instead of staying silent."""

    def test_hint_texts_are_short_and_non_empty(self) -> None:
        for hint in (HINT_FAVORITE, HINT_HELP, HINT_TAP_DETAIL):
            self.assertTrue(hint)
            self.assertLessEqual(len(hint), 120)

    def test_home_and_more_have_help_button(self) -> None:
        for markup in (
            home_keyboard(),
            more_keyboard("sporly_bot", 1, "https://sporly.ru"),
        ):
            callbacks = {
                button.callback_data
                for row in markup.inline_keyboard
                for button in row
            }
            self.assertIn("menu:help", callbacks)

    def test_notifications_live_only_in_more(self) -> None:
        home_callbacks = {
            button.callback_data
            for row in home_keyboard().inline_keyboard
            for button in row
        }
        more_callbacks = {
            button.callback_data
            for row in more_keyboard("sporly_bot", 1, "https://sporly.ru").inline_keyboard
            for button in row
        }
        saved_callbacks = {
            button.callback_data
            for row in interests_saved_keyboard().inline_keyboard
            for button in row
        }
        self.assertNotIn("menu:notify", home_callbacks)
        self.assertNotIn("menu:notify", saved_callbacks)
        self.assertIn("menu:notify", more_callbacks)

    def test_no_results_offers_helpful_exits(self) -> None:
        callbacks = {
            button.callback_data
            for row in no_results_keyboard().inline_keyboard
            for button in row
        }
        self.assertIn("menu:all", callbacks)
        self.assertIn("menu:sub", callbacks)

    def test_subscription_can_open_the_selection(self) -> None:
        callbacks = {
            button.callback_data
            for row in subscription_keyboard(Subscription(chat_id=1)).inline_keyboard
            for button in row
        }
        self.assertIn("menu:soon", callbacks)

    def test_digest_is_off_by_default(self) -> None:
        labels = [
            button.text
            for row in subscription_keyboard(Subscription(chat_id=1)).inline_keyboard
            for button in row
        ]
        self.assertIn("📭 Дайджест: выкл", labels)

    def test_notification_settings_are_independent(self) -> None:
        markup = notification_settings_keyboard(
            has_subscription=True,
            notify_enabled=True,
            digest_enabled=False,
            reminders_enabled=True,
        )
        callbacks = {
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        }
        self.assertTrue(
            {"sub:toggle_notify", "sub:toggle_digest", "sub:toggle_reminders"}
            <= callbacks
        )

    def test_reminders_can_be_configured_without_subscription(self) -> None:
        markup = notification_settings_keyboard(
            has_subscription=False,
            reminders_enabled=False,
        )
        callbacks = {
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        }
        self.assertIn("sub:toggle_reminders", callbacks)
        self.assertIn("flow:new:onboarding", callbacks)
        self.assertNotIn("sub:toggle_notify", callbacks)
        self.assertNotIn("sub:toggle_digest", callbacks)


class NavigationLabelsTest(unittest.TestCase):
    """Navigation buttons must read the same in every section."""

    def _markups(self) -> list:
        return [
            home_keyboard(),
            home_keyboard(is_admin=True),
            search_hub_keyboard(),
            more_keyboard("sporly_bot", 1, "https://sporly.ru"),
            search_list_keyboard(
                session_id="session",
                page=1,
                total_pages=2,
                partner=None,
                partner_url=None,
            ),
            favorites_list_keyboard(page=1, total_pages=2),
            event_detail_keyboard(
                token="token",
                source_url=None,
                is_favorite=False,
                share_url_value=None,
                back_callback="back:s:session:1",
            ),
            single_event_keyboard("token", None, False, "sporly_bot"),
            single_event_keyboard(
                "token",
                None,
                False,
                "sporly_bot",
                back_callback="back:s:session:1",
            ),
            no_results_keyboard(),
            subscription_keyboard(Subscription(chat_id=1)),
            delete_subscription_keyboard(),
            category_keyboard([], set()),
            city_keyboard([], set()),
        ]

    def test_home_buttons_have_one_label(self) -> None:
        for markup in self._markups():
            for row in markup.inline_keyboard:
                for button in row:
                    if button.callback_data == "menu:home":
                        self.assertEqual(button.text, BUTTON_HOME)

    def test_find_buttons_have_one_label(self) -> None:
        for markup in self._markups():
            for row in markup.inline_keyboard:
                for button in row:
                    if button.callback_data == "menu:find":
                        self.assertEqual(button.text, BUTTON_FIND)

    def test_favorite_buttons_show_state(self) -> None:
        for is_favorite, expected in (
            (False, BUTTON_FAVORITE),
            (True, BUTTON_FAVORITED),
        ):
            markup = single_event_keyboard(
                "token", None, is_favorite, "sporly_bot"
            )
            self.assertEqual(markup.inline_keyboard[0][0].text, expected)
            markup = event_detail_keyboard(
                token="token",
                source_url=None,
                is_favorite=is_favorite,
                share_url_value=None,
                back_callback="back:s:session:1",
            )
            self.assertEqual(markup.inline_keyboard[0][0].text, expected)

    def test_list_pager_row_stays_compact(self) -> None:
        search = search_list_keyboard(
            session_id="session",
            page=1,
            total_pages=25,
            partner=None,
            partner_url=None,
        )
        favorites = favorites_list_keyboard(page=1, total_pages=25)
        for markup in (search, favorites):
            self.assertEqual(len(markup.inline_keyboard[0]), 3)
            self.assertNotIn(
                "menu:home",
                {
                    button.callback_data
                    for button in markup.inline_keyboard[0]
                },
            )

    def test_event_links_do_not_repeat_telegram_arrow(self) -> None:
        markup = single_event_keyboard(
            "token", "https://example.com/event", False, "sporly_bot"
        )
        labels = [
            button.text
            for row in markup.inline_keyboard
            for button in row
            if button.url
        ]
        self.assertEqual(labels, [BUTTON_OPEN, BUTTON_SHARE])
        self.assertNotIn("↗", "".join(labels))


if __name__ == "__main__":
    unittest.main()
