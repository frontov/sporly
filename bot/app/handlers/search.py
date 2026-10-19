from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.context import database
from app.flows import move_search, start_nearest, start_search


router = Router(name="search")


@router.message(Command("find", "search"))
async def cmd_find(
    message: Message,
    command: CommandObject,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if message.from_user is None:
        return
    query = (command.args or "").strip()
    await database.touch_user(message.from_user.id)
    if query:
        await start_search(
            bot,
            message.from_user.id,
            query=query,
            bot_username=bot_username,
        )
    else:
        from app.handlers.common import send_find_hub

        await send_find_hub(bot, message.from_user.id)


@router.message(Command("soon"))
async def cmd_soon(message: Message, bot: Bot, bot_username: str = "") -> None:
    if message.from_user is None:
        return
    await database.touch_user(message.from_user.id)
    await start_nearest(bot, message.from_user.id, bot_username=bot_username)


@router.callback_query(F.data.startswith(("page:", "card:")))
async def card_navigation(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, session_id, direction = parts
    await database.touch_user(callback.from_user.id)
    error = await move_search(
        bot,
        callback.from_user.id,
        session_id,
        direction,
        callback.message,
        bot_username=bot_username,
    )
    if error:
        if "устарела" in error:
            await callback.answer("Обновляю выдачу")
            await start_search(
                bot,
                callback.from_user.id,
                bot_username=bot_username,
            )
        else:
            await callback.answer(error, show_alert=True)
    else:
        await callback.answer()


@router.callback_query(F.data.startswith("pg:"))
async def legacy_pager(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    """Compatibility with list-style result messages from the previous UI."""

    if callback.from_user is None:
        await callback.answer()
        return
    await callback.answer("Обновляю выдачу")
    await start_search(bot, callback.from_user.id, bot_username=bot_username)
