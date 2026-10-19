from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.context import database
from app.flows import (
    back_to_favorites,
    back_to_search,
    move_search,
    show_event_detail,
    start_nearest,
    start_search,
)


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
            await start_nearest(
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
    await start_nearest(bot, callback.from_user.id, bot_username=bot_username)


@router.callback_query(F.data.startswith("detail:"))
async def event_detail(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    parts = (callback.data or "").split(":")
    # detail:s:<session_id>:<page>:<index>:<token>
    # detail:f:<page>:<index>:<token>
    try:
        if len(parts) == 6 and parts[1] == "s":
            kind = "s"
            session_id = parts[2]
            page = int(parts[3])
            index = int(parts[4])
            token = parts[5]
        elif len(parts) == 5 and parts[1] == "f":
            kind = "f"
            session_id = ""
            page = int(parts[2])
            index = int(parts[3])
            token = parts[4]
        else:
            await callback.answer("Не понял кнопку", show_alert=False)
            return
    except ValueError:
        await callback.answer("Не понял кнопку", show_alert=False)
        return

    await callback.answer()
    await show_event_detail(
        bot,
        callback.from_user.id,
        token,
        kind=kind,
        page=page,
        index=index,
        session_id=session_id,
        message=callback.message,
        bot_username=bot_username,
    )


@router.callback_query(F.data.startswith("back:"))
async def back_to_list(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    parts = (callback.data or "").split(":")
    await callback.answer()
    if len(parts) == 4 and parts[1] == "s":
        try:
            page = int(parts[3])
        except ValueError:
            page = 1
        await back_to_search(
            bot,
            callback.from_user.id,
            parts[2],
            page,
            callback.message,
            bot_username=bot_username,
        )
    elif len(parts) == 3 and parts[1] == "f":
        try:
            page = int(parts[2])
        except ValueError:
            page = 1
        await back_to_favorites(
            bot,
            callback.from_user.id,
            page,
            callback.message,
            bot_username=bot_username,
        )
    else:
        await callback.answer("Кнопка устарела", show_alert=True)
