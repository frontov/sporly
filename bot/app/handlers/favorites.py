from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.context import database
from app.flows import show_favorites, toggle_favorite_by_token


router = Router(name="favorites")


def _toggle_markup(
    markup: InlineKeyboardMarkup | None,
    token: str,
    *,
    active: bool,
) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    for row in markup.inline_keyboard:
        for button in row:
            if button.callback_data in {f"fv:{token}", f"unfv:{token}"}:
                if "⭐" in button.text or "✅" in button.text:
                    text = button.text
                    if active:
                        text = text.replace("⭐", "✅").replace(
                            "В избранное", "В избранном"
                        )
                    else:
                        text = text.replace("✅", "⭐").replace(
                            "В избранном", "В избранное"
                        )
                    button.text = text
                else:
                    button.text = (
                        "✅ В избранном" if active else "⭐ В избранное"
                    )
                button.callback_data = (
                    f"unfv:{token}" if active else f"fv:{token}"
                )
    return markup


@router.message(Command("favorites", "fav"))
async def cmd_favorites(
    message: Message, bot: Bot, bot_username: str = ""
) -> None:
    if message.from_user is None:
        return
    await database.touch_user(message.from_user.id)
    await show_favorites(bot, message.from_user.id, bot_username=bot_username)


@router.callback_query(F.data.startswith("fv:"))
async def add_favorite(
    callback: CallbackQuery,
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    token = (callback.data or "").split(":", 1)[1]
    payload = await database.get_event_by_token(token)
    if payload is None:
        await callback.answer("Ссылка устарела, откройте старт заново", show_alert=True)
        return
    already = await database.is_favorite(
        callback.from_user.id, str(payload.get("id") or "")
    )
    changed, _ = await toggle_favorite_by_token(
        callback.from_user.id, token, add=True
    )
    if not changed:
        await callback.answer("Ссылка устарела, откройте старт заново", show_alert=True)
        return
    await callback.answer("Уже в избранном" if already else "⭐ Добавлено в избранное")
    if callback.message is not None:
        markup = _toggle_markup(callback.message.reply_markup, token, active=True)
        if markup:
            try:
                await callback.message.edit_reply_markup(reply_markup=markup)
            except Exception:
                pass


@router.callback_query(F.data.startswith("unfv:"))
async def remove_favorite(
    callback: CallbackQuery,
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    token = (callback.data or "").split(":", 1)[1]
    changed, _ = await toggle_favorite_by_token(
        callback.from_user.id, token, add=False
    )
    if not changed:
        await callback.answer("Ссылка устарела", show_alert=True)
        return
    await callback.answer("Убрал из избранного")
    if callback.message is not None:
        markup = _toggle_markup(callback.message.reply_markup, token, active=False)
        if markup:
            try:
                await callback.message.edit_reply_markup(reply_markup=markup)
            except Exception:
                pass


@router.callback_query(F.data.startswith("favpg:"))
async def favorites_page(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    try:
        page = int((callback.data or "").split(":", 1)[1])
    except ValueError:
        page = 1
    await callback.answer()
    await show_favorites(
        bot,
        callback.from_user.id,
        page=page,
        message=callback.message,
        bot_username=bot_username,
    )


@router.callback_query(F.data.startswith("favnav:"))
async def legacy_favorites_navigation(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    try:
        index = int((callback.data or "").split(":", 1)[1])
    except ValueError:
        index = 0
    await callback.answer()
    await show_favorites(
        bot,
        callback.from_user.id,
        page=index // 5 + 1,
        message=callback.message,
        bot_username=bot_username,
    )


@router.callback_query(F.data.startswith("favrm:"))
async def remove_favorite_card(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        index = int(parts[1])
    except ValueError:
        index = 0
    token = parts[2]
    changed, _ = await toggle_favorite_by_token(
        callback.from_user.id, token, add=False
    )
    if not changed:
        await callback.answer("Старт уже убран", show_alert=True)
        return
    await callback.answer("Убрал из избранного")
    await show_favorites(
        bot,
        callback.from_user.id,
        page=index // 5 + 1,
        message=callback.message,
        bot_username=bot_username,
    )
