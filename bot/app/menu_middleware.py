from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import Response, TelegramType

from app.menu import MAIN_MENU


class AlwaysShowMenu(BaseRequestMiddleware):
    """Attaches the main reply keyboard to every plain outgoing message.

    A reply keyboard lives on the client until the bot sends a new one, so a
    menu sent once at /start silently goes stale: users who never restart the
    bot keep yesterday's buttons, and anyone who hides the keyboard has no way
    back. Re-sending it with each message keeps it present and current.

    Messages that carry their own markup (inline keyboards for pagination,
    wizards, settings) are left alone - Telegram allows only one markup per
    message, and the client keeps showing the previously sent reply keyboard.
    """

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if isinstance(method, SendMessage) and method.reply_markup is None:
            method.reply_markup = MAIN_MENU
        return await make_request(bot, method)


def setup(bot: Bot) -> None:
    bot.session.middleware(AlwaysShowMenu())
