from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from app.api_client import api_client
from app.config import settings
from app.deeplinks import set_bot_username
from app.handlers import admin, common, favorites, search, subscriptions
from app.menu_middleware import setup as setup_menu_middleware
from app.scheduler import poll_new_events, send_daily_digest, send_event_reminders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PUBLIC_COMMANDS = [
    BotCommand(command="start", description="Начать / открыть меню"),
    BotCommand(command="help", description="Как пользоваться ботом"),
    BotCommand(command="find", description="Найти по названию (или кнопки меню)"),
    BotCommand(command="browse", description="Разовый поиск с выбором фильтров"),
    BotCommand(command="favorites", description="Избранные события с напоминаниями"),
    BotCommand(command="subscribe", description="Изменить любимые виды спорта и регионы"),
    BotCommand(command="my", description="Настройки: фильтры, уведомления, дайджест"),
]

ADMIN_COMMANDS = [
    *PUBLIC_COMMANDS,
    BotCommand(command="status", description="Статус backend (админ)"),
    BotCommand(command="refresh", description="Принудительно обновить кэш (админ)"),
]


async def _setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            logger.exception("failed to set admin command menu for chat %s", admin_id)


async def main() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Keeps the bottom menu attached to every message that has no markup of its own.
    setup_menu_middleware(bot)
    dispatcher = Dispatcher(storage=MemoryStorage())
    for router in (common.router, search.router, subscriptions.router, favorites.router, admin.router):
        dispatcher.include_router(router)

    background_tasks = [
        asyncio.create_task(poll_new_events(bot)),
        asyncio.create_task(send_daily_digest(bot)),
        asyncio.create_task(send_event_reminders(bot)),
    ]

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        # Deep links in search results are built from the bot's own username.
        set_bot_username((await bot.get_me()).username)
        await _setup_commands(bot)
        await dispatcher.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        await api_client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
