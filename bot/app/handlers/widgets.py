"""Developer entry points for the HTML-widget experiment."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.api_client import EventQuery, api_client, today_iso
from app.config import settings
from app.context import database
from app.widgets import (
    demo_event,
    send_card_widget,
    send_demo_list_widget,
    send_list_widget,
)


logger = logging.getLogger(__name__)
router = Router(name="widgets")

HELP = (
    "<b>HTML-виджеты</b>\n\n"
    "/widget — ближайшие старты виджетом\n"
    "/widget карточка — один старт карточкой\n"
    "/widget демо — демо-карточка без backend\n"
    "/widget демо список — демо-список без backend\n"
    "/widget панель — кнопки для демо\n\n"
    "Команда доступна администраторам. Виджеты работают в личном чате "
    "с ботом; кнопки внутри виджета обрабатывает бот."
)


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.admin_ids


def demo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🃏 Карточка", callback_data="widget:demo:card"
                ),
                InlineKeyboardButton(
                    text="📋 Список", callback_data="widget:demo:list"
                ),
            ]
        ]
    )


async def _first_event(chat_id: int, query: str | None):
    subscription = await database.get_subscription(chat_id)
    result = await api_client.get_events(
        EventQuery(
            query=query,
            cities=subscription.cities if subscription and not query else [],
            categories=subscription.categories if subscription and not query else [],
            date_from=today_iso(),
            page=1,
            page_size=1,
            sort_by="date_asc",
        )
    )
    return result.items[0] if result.items else None


@router.message(Command("widget"))
async def cmd_widget(
    message: Message,
    command: CommandObject,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if message.from_user is None:
        return
    if not _is_admin(message.from_user.id):
        await message.answer("Команда доступна администраторам.")
        return
    if message.chat.type != "private":
        await message.answer("HTML-виджеты работают только в личном чате с ботом.")
        return

    await database.touch_user(message.from_user.id)
    arg = (command.args or "").strip()
    mode = " ".join(arg.casefold().split())

    if mode in {"help", "?", "справка"}:
        await message.answer(HELP)
        return

    if mode in {"panel", "панель"}:
        await message.answer(
            "Демо HTML-виджетов. Кнопки внутри виджета работают, пока "
            "запущен dev-бот.",
            reply_markup=demo_keyboard(),
        )
        return

    if mode in {"demo", "демо"}:
        sent = await send_card_widget(
            bot,
            message.chat.id,
            demo_event(),
            bot_username=bot_username,
        )
        if sent is None:
            await message.answer("Не удалось отправить HTML-виджет.")
        return

    if mode in {"demo list", "демо список", "list demo"}:
        sent = await send_demo_list_widget(
            bot,
            message.chat.id,
            bot_username=bot_username,
        )
        if sent is None:
            await message.answer("Не удалось отправить HTML-виджет.")
        return

    if mode in {"card", "карточка"}:
        try:
            event = await _first_event(message.chat.id, None)
        except Exception:
            logger.exception("Cannot load event for widget card")
            await message.answer("Каталог временно недоступен.")
            return
        if event is None:
            await message.answer("Стартов пока нет.")
            return
        sent = await send_card_widget(
            bot,
            message.chat.id,
            event,
            bot_username=bot_username,
        )
        if sent is None:
            await message.answer("Не удалось отправить HTML-виджет.")
        return

    subscription = await database.get_subscription(message.chat.id)
    query = arg or None
    sent = await send_list_widget(
        bot,
        message.chat.id,
        query=query,
        cities=subscription.cities if subscription and not query else None,
        categories=subscription.categories if subscription and not query else None,
        bot_username=bot_username,
    )
    if sent is None:
        await message.answer("Не удалось отправить HTML-виджет.")


@router.callback_query(F.data.startswith("widget:demo:"))
async def demo_callback(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    await callback.answer()
    mode = (callback.data or "").rsplit(":", 1)[-1]
    if mode == "list":
        sent = await send_demo_list_widget(
            bot,
            callback.from_user.id,
            bot_username=bot_username,
        )
    else:
        sent = await send_card_widget(
            bot,
            callback.from_user.id,
            demo_event(),
            bot_username=bot_username,
        )
    if sent is None and callback.message is not None:
        await callback.message.answer("Не удалось отправить HTML-виджет.")
