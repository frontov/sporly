from __future__ import annotations

import json
import unittest

from app.widget_app import (
    _place_from_parts,
    _shorten,
    app_html_sizes,
    fit_app_state,
    handle_app_query,
    render_app_html,
)
from app.widgets import (
    AnswerWidgetQuery,
    EditMessageWidgetData,
    WidgetSession,
)


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def __call__(self, method):
        self.calls.append(method)
        return True


class WidgetAppHtmlTest(unittest.TestCase):
    def test_app_fits_telegram_limits(self) -> None:
        raw, compressed = app_html_sizes()

        self.assertLessEqual(raw, 32768)
        self.assertLessEqual(compressed, 4096)
        html = render_app_html("sporly_dev_bot")
        self.assertNotIn("__BOT_JSON__", html)
        self.assertIn('data-nav="list"', html)
        self.assertIn('data-nav="fav"', html)
        self.assertIn('data-nav="filters"', html)
        self.assertIn('data-nav="more"', html)

    def test_list_state_is_trimmed_to_the_limit(self) -> None:
        state = {
            "v": "list",
            "t": "Ближайшие старты",
            "p": 1,
            "g": 20,
            "n": 100,
            "q": "",
            "f": {"c": ["Москва"], "g": ["Бег"]},
            "e": [
                {
                    "k": "abc123456789",
                    "t": "Очень длинное название старта " * 5,
                    "w": "12 ноября",
                    "c": "Санкт-Петербург",
                    "g": "Ориентирование",
                    "f": 0,
                }
                for _ in range(4)
            ],
        }
        raw = fit_app_state(state)

        self.assertLessEqual(len(raw.encode("utf-8")), 1000)
        parsed = json.loads(raw)
        self.assertEqual(parsed["v"], "list")
        self.assertTrue(parsed["e"])

    def test_card_state_drops_the_long_url_when_needed(self) -> None:
        state = {
            "v": "card",
            "c": {
                "k": "abc123456789",
                "t": "Старт " * 40,
                "w": "12 ноября · через 3 дня",
                "l": "Санкт-Петербург",
                "g": "Бег",
                "m": "21,1 км · 2500 ₽ · регистрация открыта",
                "d": "Описание " * 40,
                "u": "https://example.com/" + "x" * 400,
                "f": 0,
            },
        }
        raw = fit_app_state(state)

        self.assertLessEqual(len(raw.encode("utf-8")), 1000)
        parsed = json.loads(raw)
        self.assertEqual(parsed["v"], "card")

class WidgetAppTextTest(unittest.TestCase):
    def test_place_prefers_city_over_region(self) -> None:
        self.assertEqual(
            _place_from_parts("Люберцы, Московская область", None),
            "Люберцы",
        )
        self.assertEqual(
            _place_from_parts("6 к.4, Санкт-Петербург", None),
            "Санкт-Петербург",
        )
        self.assertEqual(
            _place_from_parts("", "Московская область"),
            "Московская область",
        )

    def test_shortening_does_not_cut_a_word(self) -> None:
        self.assertEqual(_shorten("Люберцы, Московская область", 12), "Люберцы…")
        self.assertEqual(_shorten("Ханты-Мансийск", 28), "Ханты-Мансийск")



class WidgetAppActionTest(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_to_more_edits_the_same_widget(self) -> None:
        bot = FakeBot()
        session = WidgetSession(
            kind="app",
            chat_id=7,
            message_id=10,
            state={"v": "list"},
        )

        await handle_app_query(bot, session, "q1", 7, "n:more")

        self.assertEqual(session.state["v"], "more")
        self.assertEqual(len(bot.calls), 2)
        edit = bot.calls[0]
        answer = bot.calls[1]
        self.assertIsInstance(edit, EditMessageWidgetData)
        self.assertIsInstance(answer, AnswerWidgetQuery)
        self.assertEqual(edit.message_id, 10)
        self.assertIn('"v":"more"', edit.chat_data)
        self.assertEqual(answer.widget_query_id, "q1")

    async def test_unknown_action_is_answered_with_an_error(self) -> None:
        bot = FakeBot()
        session = WidgetSession(
            kind="app",
            chat_id=7,
            message_id=10,
            state={"v": "list"},
        )

        await handle_app_query(bot, session, "q2", 7, "wat")

        self.assertEqual(len(bot.calls), 1)
        answer = bot.calls[0]
        self.assertIsInstance(answer, AnswerWidgetQuery)
        self.assertIn("Не понял", json.loads(answer.data)["e"])


if __name__ == "__main__":
    unittest.main()
