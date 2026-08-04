from __future__ import annotations

from datetime import date

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.api_client import EventQuery, api_client
from app.category_city_flow import CategoryCityFlow, UNAVAILABLE_TEXT
from app.category_city_flow import register as register_flow
from app.category_city_flow import start as start_flow
from app.filter_ui import format_selection_summary
from app.matching import matches
from app.menu import SETTINGS_TEXTS
from app.storage import Subscription, store

router = Router(name="subscriptions")

NS = "sub"
BASELINE_PAGE_SIZE = 50


class SubscribeStates(StatesGroup):
    waiting_for_categories = State()
    waiting_for_cities = State()


class NotifyChoiceStates(StatesGroup):
    waiting_for_choice = State()


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, state: FSMContext) -> None:
    await start_flow(message, state, FLOW)


def _notify_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔔 Да, присылать", callback_data=f"{NS}:notify_yes"),
                InlineKeyboardButton(text="Не сейчас", callback_data=f"{NS}:notify_no"),
            ],
            [InlineKeyboardButton(text="✕ Отмена", callback_data=f"{NS}:notify_cancel")],
        ]
    )


async def _on_favorites_picked(
    callback: CallbackQuery, state: FSMContext, categories: list[str], cities: list[str]
) -> None:
    if not callback.message:
        return
    await state.set_state(NotifyChoiceStates.waiting_for_choice)
    await state.update_data(categories=categories, cities=cities)
    await callback.message.edit_text(
        "✅ <b>Фильтры сохранены</b>\n\n"
        f"{format_selection_summary(categories, cities)}\n\n"
        "Присылать уведомления, когда появляются новые подходящие старты?",
        reply_markup=_notify_confirm_keyboard(),
    )


FLOW = CategoryCityFlow(
    namespace=NS,
    categories_state=SubscribeStates.waiting_for_categories,
    cities_state=SubscribeStates.waiting_for_cities,
    on_done=_on_favorites_picked,
    done_label="Сохранить →",
    cancel_text="Настройка отменена.",
)
register_flow(router, FLOW)


@router.callback_query(NotifyChoiceStates.waiting_for_choice, F.data.in_({f"{NS}:notify_yes", f"{NS}:notify_no"}))
async def on_notify_choice(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return

    data = await state.get_data()
    categories: list[str] = data.get("categories", [])
    cities: list[str] = data.get("cities", [])
    notify_enabled = callback.data == f"{NS}:notify_yes"
    chat_id = callback.message.chat.id

    existing = store.get(chat_id)
    subscription = Subscription(
        chat_id=chat_id,
        cities=cities,
        categories=categories,
        notify_enabled=notify_enabled,
        digest_enabled=existing.digest_enabled if existing else False,
        onboarded=True,
    )

    if notify_enabled:
        # Baseline on today's matching events so the first notification poll
        # only reports events that show up after subscribing, not the backlog.
        try:
            page = await api_client.get_events(
                EventQuery(
                    date_from=date.today().isoformat(),
                    sort_by="date_asc",
                    page=1,
                    page_size=BASELINE_PAGE_SIZE,
                )
            )
        except httpx.HTTPError:
            await state.clear()
            await callback.message.edit_text(UNAVAILABLE_TEXT)
            await callback.answer()
            return
        subscription.seen_event_ids = [event.id for event in page.items if matches(subscription, event)]

    await store.upsert(subscription)
    await state.clear()

    notify_line = (
        "🔔 Уведомления о новых стартах включены."
        if notify_enabled
        else "🔕 Уведомления выключены — включить можно в «⚙️ Настройки»."
    )
    await callback.message.edit_text(
        "✅ <b>Всё готово</b>\n\n"
        f"{format_selection_summary(categories, cities)}\n"
        f"{notify_line}\n\n"
        "Жмите «🔍 Найти события» — покажу старты по этим фильтрам."
    )
    await callback.answer()


@router.callback_query(NotifyChoiceStates.waiting_for_choice, F.data == f"{NS}:notify_cancel")
async def on_notify_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Настройка отменена.")
    await callback.answer()


def _settings_text(subscription: Subscription | None) -> str:
    if not subscription or not subscription.onboarded:
        return (
            "⚙️ <b>Настройки</b>\n\n"
            "Фильтры пока не заданы — задайте виды спорта и регионы, "
            "и «🔍 Найти события» будет показывать только их."
        )
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"{format_selection_summary(subscription.categories, subscription.cities)}\n"
        f"{'🔔' if subscription.notify_enabled else '🔕'} новые старты: "
        f"{'вкл' if subscription.notify_enabled else 'выкл'}\n"
        f"📰 дайджест: {'вкл' if subscription.digest_enabled else 'выкл'}"
    )


def _settings_keyboard(subscription: Subscription | None) -> InlineKeyboardMarkup:
    if not subscription or not subscription.onboarded:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎛 Задать фильтры", callback_data=f"{NS}:edit_filters")],
            ]
        )
    notify_label = "🔕 Выключить новые старты" if subscription.notify_enabled else "🔔 Включить новые старты"
    digest_label = "📰 Выключить дайджест" if subscription.digest_enabled else "📰 Включить дайджест"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=notify_label, callback_data=f"{NS}:toggle_notify")],
            [InlineKeyboardButton(text=digest_label, callback_data=f"{NS}:toggle_digest")],
            [InlineKeyboardButton(text="🎛 Изменить фильтры", callback_data=f"{NS}:edit_filters")],
            [InlineKeyboardButton(text="♻️ Сбросить", callback_data=f"{NS}:reset")],
        ]
    )


@router.message(Command("my"))
@router.message(F.text.in_(SETTINGS_TEXTS))
async def cmd_my(message: Message) -> None:
    subscription = store.get(message.chat.id)
    await message.answer(_settings_text(subscription), reply_markup=_settings_keyboard(subscription))


@router.callback_query(F.data == f"{NS}:toggle_notify")
async def on_toggle_notify(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    subscription = store.get(chat_id)
    if not subscription or not subscription.onboarded:
        await callback.answer("Сначала настройте фильтры.", show_alert=True)
        return

    if subscription.notify_enabled:
        await store.disable_notify(chat_id)
    else:
        try:
            page = await api_client.get_events(
                EventQuery(
                    date_from=date.today().isoformat(),
                    sort_by="date_asc",
                    page=1,
                    page_size=BASELINE_PAGE_SIZE,
                )
            )
        except httpx.HTTPError:
            await callback.answer("Сервис временно недоступен, попробуйте позже.", show_alert=True)
            return
        subscription.notify_enabled = True
        subscription.seen_event_ids = [event.id for event in page.items if matches(subscription, event)]
        await store.upsert(subscription)

    updated = store.get(chat_id)
    await callback.message.edit_text(_settings_text(updated), reply_markup=_settings_keyboard(updated))
    await callback.answer()


@router.callback_query(F.data == f"{NS}:toggle_digest")
async def on_toggle_digest(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    subscription = store.get(chat_id) or Subscription(chat_id=chat_id)
    subscription.digest_enabled = not subscription.digest_enabled
    await store.upsert(subscription)
    await callback.message.edit_text(_settings_text(subscription), reply_markup=_settings_keyboard(subscription))
    await callback.answer()


@router.callback_query(F.data == f"{NS}:edit_filters")
async def on_edit_filters(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    await start_flow(callback.message, state, FLOW)
    await callback.answer()


@router.callback_query(F.data == f"{NS}:reset")
async def on_reset_button(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    await store.remove(callback.message.chat.id)
    await callback.message.edit_text(
        "♻️ <b>Сброшено</b>\n\n"
        "Фильтры, уведомления и дайджест очищены. Избранные события остались — «⭐ Избранное» внизу.\n\n"
        "Настроить заново — «⚙️ Настройки»."
    )
    await callback.answer()
