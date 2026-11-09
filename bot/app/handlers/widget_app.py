"""``/app`` — the widget-only Sporly interface."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.context import database
from app.widget_app import send_app_widget


logger = logging.getLogger(__name__)
router = Router(name="widget_app")


@router.message(Command("app"))
async def cmd_app(
    message: Message,
    bot: Bot,
    bot_username: str = "",
) -> None:
    user = message.from_user
    if user is None:
        return
    if message.chat.type != "private":
        await message.answer("Виджет-версия работает в личном чате с ботом.")
        return

    await database.ensure_user(user.id, user.username, user.first_name)
    await database.touch_user(user.id)
    await database.set_ui_mode(user.id, "widget")
    sent = await send_app_widget(
        bot,
        user.id,
        bot_username=bot_username,
    )
    if sent is None:
        await message.answer("Не удалось открыть виджет-версию.")
        return
    try:
        await message.delete()
    except Exception:
        pass


@router.message(Command("classic"))
async def cmd_classic(message: Message, bot: Bot) -> None:
    user = message.from_user
    if user is None:
        return
    if message.chat.type != "private":
        await message.answer("Смена интерфейса работает в личном чате с ботом.")
        return
    await database.ensure_user(user.id, user.username, user.first_name)
    await database.touch_user(user.id)
    await database.set_ui_mode(user.id, "classic")
    from app.handlers.common import send_home

    await send_home(bot, user.id)
