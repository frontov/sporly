from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiogram.types import Update

from app.api_client import Event
from app.config import settings
from app.handlers import widgets as widget_handlers
from app.widgets import (
    AnswerWidgetQuery,
    EditMessageWidgetData,
    SendWidget,
    WidgetSession,
    build_list_items,
    clear_sessions,
    demo_event,
    fit_state,
    handle_widget_update,
    is_widget_update,
    remember_session,
    render_card_widget_html,
    render_list_widget_html,
    widget_html_sizes,
)


class WidgetHtmlTest(unittest.TestCase):
    def test_list_widget_fits_telegram_limits(self) -> None:
        raw, compressed = widget_html_sizes(render_list_widget_html())

        self.assertLessEqual(raw, 32768)
        self.assertLessEqual(compressed, 4096)

    def test_card_widget_fits_telegram_limits(self) -> None:
        event = demo_event()
        html = render_card_widget_html(
            event,
            token="abc123",
            is_favorite=False,
            open_url="https://sporly.ru",
            share_url_value="https://t.me/share/url?url=x",
        )
        raw, compressed = widget_html_sizes(html)

        self.assertLessEqual(raw, 32768)
        self.assertLessEqual(compressed, 4096)
        self.assertIn("W.request", html)
        self.assertIn("Московский полумарафон", html)

    def test_card_widget_escapes_event_text(self) -> None:
        event = demo_event().model_copy(
            update={"title": '<script>alert("x")</script>'}
        )
        html = render_card_widget_html(
            event,
            token="abc123",
            is_favorite=False,
            open_url=None,
            share_url_value=None,
        )

        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn("alert(&quot;x&quot;)", html)


class WidgetStateTest(unittest.TestCase):
    def test_state_fits_the_1024_byte_limit(self) -> None:
        events = [
            demo_event().model_copy(
                update={
                    "id": f"event-{index}",
                    "title": "Очень длинное название старта " * 10,
                    "source_url": "https://example.com/" + "x" * 300,
                }
            )
            for index in range(4)
        ]
        items = build_list_items(events, chat_id=1, favorite_ids=set())
        state = fit_state({"p": 1, "g": 3, "n": 24, "e": items})

        self.assertLessEqual(len(state.encode("utf-8")), 1000)
        parsed = json.loads(state)
        self.assertTrue(parsed["e"])
        self.assertEqual(parsed["p"], 1)

    def test_state_keeps_short_data_unchanged(self) -> None:
        items = build_list_items([demo_event()], chat_id=1, favorite_ids=set())
        state = fit_state({"p": 1, "g": 1, "n": 1, "e": items})

        parsed = json.loads(state)
        self.assertEqual(parsed["n"], 1)
        self.assertEqual(len(parsed["e"]), 1)


class WidgetUpdateTest(unittest.TestCase):
    def test_widget_query_update_is_detected(self) -> None:
        update = Update.model_validate(
            {
                "update_id": 1,
                "widget_query": {
                    "id": "42",
                    "from": {"id": 7, "is_bot": False, "first_name": "A"},
                    "chat": {"id": 7, "type": "private"},
                    "message_id": 10,
                    "chat_instance": "x",
                    "data": "more",
                },
            }
        )

        self.assertTrue(is_widget_update(update))

    def test_regular_update_is_not_a_widget_query(self) -> None:
        self.assertFalse(is_widget_update(Update(update_id=2)))

    def test_raw_methods_use_the_new_api_names(self) -> None:
        send = SendWidget(chat_id=1, html="<b>x</b>", chat_data="{}")
        edit = EditMessageWidgetData(chat_id=1, message_id=2, chat_data="{}")
        answer = AnswerWidgetQuery(widget_query_id="q", data="{}")

        self.assertEqual(send.__api_method__, "sendWidget")
        self.assertEqual(edit.__api_method__, "editMessageWidgetData")
        self.assertEqual(answer.__api_method__, "answerWidgetQuery")
        self.assertIn("allow_queries", send.model_dump())


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def __call__(self, method):
        self.calls.append(method)
        return True


class FakeCallback:
    def __init__(self, data: str) -> None:
        self.from_user = SimpleNamespace(id=7)
        self.data = data
        self.message = SimpleNamespace(answer=self._answer)
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        self.answered = True

    async def _answer(self, *args, **kwargs) -> None:
        self.answered = True


class WidgetQueryHandlerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_sessions()
        remember_session(
            WidgetSession(
                kind="list",
                chat_id=7,
                message_id=10,
                page=1,
                total_pages=2,
                total=8,
                demo=True,
            )
        )

    def tearDown(self) -> None:
        clear_sessions()

    async def test_demo_more_is_answered_without_network(self) -> None:
        bot = FakeBot()
        update = Update.model_validate(
            {
                "update_id": 1,
                "widget_query": {
                    "id": "42",
                    "from": {"id": 7, "is_bot": False, "first_name": "A"},
                    "chat": {"id": 7, "type": "private"},
                    "message_id": 10,
                    "chat_instance": "x",
                    "data": "more",
                },
            }
        )

        await handle_widget_update(update, bot)

        self.assertEqual(len(bot.calls), 1)
        answer = bot.calls[0]
        self.assertIsInstance(answer, AnswerWidgetQuery)
        self.assertEqual(answer.widget_query_id, "42")
        self.assertIn("последняя страница", json.loads(answer.data)["e"])

    async def test_unknown_widget_is_answered_as_stale(self) -> None:
        bot = FakeBot()
        update = Update.model_validate(
            {
                "update_id": 2,
                "widget_query": {
                    "id": "43",
                    "from": {"id": 7, "is_bot": False, "first_name": "A"},
                    "chat": {"id": 7, "type": "private"},
                    "message_id": 999,
                    "chat_instance": "x",
                    "data": "refresh",
                },
            }
        )

        await handle_widget_update(update, bot)

        self.assertEqual(len(bot.calls), 1)
        answer = bot.calls[0]
        self.assertIn("устарел", json.loads(answer.data)["e"])


class WidgetCallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_demo_panel_button_sends_the_list(self) -> None:
        original = settings.admin_telegram_ids
        settings.admin_telegram_ids = "7"
        callback = FakeCallback("widget:demo:list")
        sent: list[tuple] = []

        async def fake_send(bot, chat_id, **kwargs):
            sent.append((bot, chat_id, kwargs))
            return True

        try:
            with patch.object(
                widget_handlers, "send_demo_list_widget", fake_send
            ):
                await widget_handlers.demo_callback(callback, bot=object())
        finally:
            settings.admin_telegram_ids = original

        self.assertTrue(callback.answered)
        self.assertEqual(sent[0][1], 7)

    async def test_demo_panel_is_admin_only(self) -> None:
        original = settings.admin_telegram_ids
        settings.admin_telegram_ids = "999"
        callback = FakeCallback("widget:demo:list")
        try:
            with patch.object(
                widget_handlers,
                "send_demo_list_widget",
                side_effect=AssertionError("must not send"),
            ):
                await widget_handlers.demo_callback(callback, bot=object())
        finally:
            settings.admin_telegram_ids = original

        self.assertTrue(callback.answered)


if __name__ == "__main__":
    unittest.main()
