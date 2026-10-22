from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.context import database, search_sessions
from app.filter_wizard import open_existing_flow
from app.flows import (
    delete_current_screen,
    finish_subscription,
    show_notifications,
    show_screen,
    show_subscription,
)
from app.keyboards import (
    BUTTON_HOME,
    BUTTON_SETUP_INTERESTS,
    delete_subscription_keyboard,
)


router = Router(name="subscriptions")


@router.message(Command("subscribe", "my"))
async def cmd_subscribe(
    message: Message, bot: Bot, bot_username: str = ""
) -> None:
    if message.from_user is None:
        return
    await database.touch_user(message.from_user.id)
    await show_subscription(bot, message.from_user.id, bot_username=bot_username)


@router.message(Command("notifications", "notify"))
async def cmd_notifications(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    await database.touch_user(message.from_user.id)
    await show_notifications(bot, message.from_user.id)


@router.callback_query(F.data.startswith("subf:"))
async def subscribe_from_search(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    session = search_sessions.get((callback.data or "").split(":", 1)[1])
    if session is None:
        await callback.answer("Выдача устарела, запустите поиск заново", show_alert=True)
        return
    await callback.answer("Сохраняю подписку")
    await finish_subscription(
        bot,
        callback.from_user.id,
        cities=session.cities,
        categories=session.categories,
        bot_username=bot_username,
        delete_message=callback.message,
    )


async def _refresh_settings_screen(
    callback: CallbackQuery,
    bot: Bot,
    *,
    screen: str,
    bot_username: str = "",
) -> None:
    if callback.message is None or callback.from_user is None:
        return
    if screen == "notifications":
        await show_notifications(
            bot, callback.from_user.id, message=callback.message
        )
    else:
        await show_subscription(
            bot,
            callback.from_user.id,
            message=callback.message,
            bot_username=bot_username,
        )


async def _apply_notification_toggle(
    callback: CallbackQuery,
    bot: Bot,
    field: str,
    *,
    screen: str,
    bot_username: str = "",
) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    chat_id = callback.from_user.id

    if field == "reminders_enabled":
        enabled = await database.toggle_reminders(chat_id)
        if enabled is None:
            await callback.answer("Сначала запустите /start", show_alert=True)
            return
        await callback.answer(
            "Напоминания включены" if enabled else "Напоминания выключены"
        )
        await _refresh_settings_screen(
            callback, bot, screen=screen, bot_username=bot_username
        )
        return

    subscription = await database.toggle_subscription(chat_id, field)
    if subscription is None:
        await callback.answer("Сначала создайте подписку", show_alert=True)
        return
    if field == "notify_enabled":
        await callback.answer(
            "Новые старты по фильтрам включены"
            if subscription.notify_enabled
            else "Новые старты по фильтрам выключены"
        )
    else:
        await callback.answer(
            "Дайджест включён — пришлём подборку раз в день"
            if subscription.digest_enabled
            else "Дайджест выключен"
        )
    await _refresh_settings_screen(
        callback, bot, screen=screen, bot_username=bot_username
    )


@router.callback_query(F.data == "sub:toggle_notify")
async def toggle_notify(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    await _apply_notification_toggle(
        callback,
        bot,
        "notify_enabled",
        screen="subscription",
        bot_username=bot_username,
    )


@router.callback_query(F.data == "sub:toggle_digest")
async def toggle_digest(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    await _apply_notification_toggle(
        callback,
        bot,
        "digest_enabled",
        screen="subscription",
        bot_username=bot_username,
    )


@router.callback_query(F.data == "sub:toggle_reminders")
async def toggle_reminders(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    await _apply_notification_toggle(
        callback,
        bot,
        "reminders_enabled",
        screen="subscription",
        bot_username=bot_username,
    )


@router.callback_query(F.data.startswith("notif:toggle:"))
async def toggle_notification(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    name = (callback.data or "").split(":", 2)[2]
    field = f"{name}_enabled"
    if field not in {"notify_enabled", "digest_enabled", "reminders_enabled"}:
        await callback.answer("Не понял настройку", show_alert=True)
        return
    await _apply_notification_toggle(
        callback,
        bot,
        field,
        screen="notifications",
        bot_username=bot_username,
    )


@router.callback_query(F.data == "sub:edit")
async def edit_subscription(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    subscription = await database.get_subscription(callback.from_user.id)
    if subscription is None:
        await callback.answer("Сначала создайте подписку", show_alert=True)
        return
    await open_existing_flow(
        callback,
        state,
        mode="subscribe",
        cities=subscription.cities,
        categories=subscription.categories,
    )


@router.callback_query(F.data == "sub:delete")
async def confirm_delete(callback: CallbackQuery, bot: Bot) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.answer()
    await show_screen(
        bot,
        callback.from_user.id,
        callback.message,
        text=(
            "<b>Удалить подписку?</b>\n\n"
            "Новые события и дайджест больше не будут приходить. "
            "Избранное и напоминания останутся."
        ),
        markup=delete_subscription_keyboard(),
    )


@router.callback_query(F.data == "sub:delete_confirm")
async def delete_subscription(callback: CallbackQuery, bot: Bot) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    await database.delete_subscription(callback.from_user.id)
    await database.log_event(callback.from_user.id, "subscription_deleted")
    await callback.answer("Подписка удалена")
    await show_screen(
        bot,
        callback.from_user.id,
        callback.message,
        text=(
            "<b>Подписка удалена</b>\n\n"
            "Можно создать новую в любой момент — это бесплатно."
        ),
        markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=BUTTON_SETUP_INTERESTS,
                        callback_data="flow:new:onboarding",
                    )
                ],
                [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")],
            ]
        ),
    )


@router.callback_query(F.data == "sub:noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
