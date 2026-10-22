from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    ErrorEvent,
    LinkPreviewOptions,
    MenuButtonCommands,
)

from app.api_client import api_client
from app.config import settings
from app.context import database
from app.handlers import admin, common, favorites, search, subscriptions
from app.filter_wizard import router as filter_router
from app.fsm_storage import SQLiteFSMStorage
from app.redirect_server import start_redirect_server
from app.scheduler import digest_loop, notification_loop, reminder_loop


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


PUBLIC_COMMANDS = [
    BotCommand(command="start", description="Запустить бота"),
    BotCommand(command="find", description="Найти старт"),
    BotCommand(command="soon", description="Ближайшие старты"),
    BotCommand(command="subscribe", description="Мои интересы"),
    BotCommand(command="notifications", description="Настройки уведомлений"),
    BotCommand(command="survey", description="Настроить интересы заново"),
    BotCommand(command="favorites", description="Избранное и напоминания"),
    BotCommand(command="settings", description="Настройки"),
    BotCommand(command="forpartners", description="Реклама в боте"),
    BotCommand(command="help", description="Как пользоваться"),
]

ADMIN_COMMANDS = [
    BotCommand(command="admin", description="Админка"),
    BotCommand(command="status", description="Состояние backend"),
    BotCommand(command="stats", description="Статистика"),
    BotCommand(command="partners", description="Статистика партнёров"),
    BotCommand(command="reload", description="Сбросить кэш"),
    BotCommand(command="broadcast", description="Рассылка"),
]


async def _setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        PUBLIC_COMMANDS, scope=BotCommandScopeDefault()
    )
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(
                PUBLIC_COMMANDS + ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as error:
            logger.warning("Cannot set admin commands for %s: %s", admin_id, error)
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as error:
        logger.warning("Cannot set menu button: %s", error)


async def main() -> None:
    if not settings.bot_token:
        raise SystemExit(
            "BOT_TOKEN is empty. Copy bot/.env.example to bot/.env and fill it in."
        )

    await database.init()
    await database.prune()

    session = (
        AiohttpSession(proxy=settings.telegram_proxy)
        if settings.telegram_proxy
        else None
    )
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview=LinkPreviewOptions(is_disabled=True),
        ),
    )
    storage = SQLiteFSMStorage(settings.database_path)
    dp = Dispatcher(storage=storage)

    # The wizard must see the state before the free-text search handler.
    dp.include_router(filter_router)
    dp.include_router(admin.router)
    dp.include_router(search.router)
    dp.include_router(subscriptions.router)
    dp.include_router(favorites.router)
    dp.include_router(common.router)

    redirect_runner = None
    tasks: list[asyncio.Task] = []
    try:
        me = await bot.me()
        bot_username = me.username or ""
        dp["bot_username"] = bot_username
        logger.info("Starting @%s", bot_username or me.id)
        await _setup_commands(bot)

        try:
            redirect_runner = await start_redirect_server()
        except Exception:
            logger.exception("Partner redirect server failed to start")

        tasks = [
            asyncio.create_task(
                notification_loop(bot, bot_username), name="notifications"
            ),
            asyncio.create_task(digest_loop(bot, bot_username), name="digest"),
            asyncio.create_task(reminder_loop(bot, bot_username), name="reminders"),
        ]

        @dp.errors()
        async def on_error(event: ErrorEvent) -> bool:
            logger.exception(
                "Unhandled update error: %s",
                event.exception,
                exc_info=event.exception,
            )
            return True

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=settings.drop_pending_updates,
            handle_as_tasks=True,
            close_bot_session=False,
        )
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if redirect_runner is not None:
            await redirect_runner.cleanup()
        await api_client.close()
        await storage.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
