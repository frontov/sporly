from __future__ import annotations

from dataclasses import replace
from datetime import date

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.api_client import EventItem, EventQuery, api_client
from app.category_city_flow import CategoryCityFlow, UNAVAILABLE_TEXT
from app.category_city_flow import register as register_flow
from app.category_city_flow import start as start_flow
from app.deeplinks import FAVORITE_PREFIX, UNFAVORITE_PREFIX, start_link
from app.event_tokens import EventRef, token_store
from app.favorites import favorites_store
from app.formatting import format_events_page
from app.menu import BROWSE_TEXTS, FIND_TEXTS
from app.storage import store

router = Router(name="search")

NS = "brw"
PAGE_SIZE = 6

# Keeps the last query/filters per chat so pagination callbacks don't need to
# smuggle free-form text or filter lists through Telegram's callback_data.
_last_query: dict[int, EventQuery] = {}


class BrowseStates(StatesGroup):
    waiting_for_categories = State()
    waiting_for_cities = State()


@router.message(Command("find"))
async def cmd_find(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if query:
        _last_query[message.chat.id] = EventQuery(
            query=query,
            date_from=date.today().isoformat(),
            page=1,
            page_size=PAGE_SIZE,
        )
        await _send_page(message.chat.id, page=1, message=message)
        return
    await show_favorites_or_picker(message, state)


@router.message(F.text.in_(FIND_TEXTS))
async def on_menu_find(message: Message, state: FSMContext) -> None:
    await show_favorites_or_picker(message, state)


async def show_favorites_or_picker(message: Message, state: FSMContext) -> None:
    subscription = store.get(message.chat.id)
    if subscription and subscription.onboarded:
        _last_query[message.chat.id] = EventQuery(
            cities=subscription.cities,
            categories=subscription.categories,
            date_from=date.today().isoformat(),
            sort_by="date_asc",
            page=1,
            page_size=PAGE_SIZE,
        )
        await _send_page(message.chat.id, page=1, message=message)
        return

    # No favorites saved yet - fall back to the full chip picker.
    await start_flow(message, state, _FLOW)


@router.message(Command("browse"))
@router.message(F.text.in_(BROWSE_TEXTS))
async def cmd_browse(message: Message, state: FSMContext) -> None:
    await start_flow(message, state, _FLOW)


@router.callback_query(F.data.startswith("find_page:"))
async def on_find_page(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    page = int(callback.data.split(":", 1)[1])
    await _send_page(chat_id, page=page, message=callback.message, edit=True)
    await callback.answer()


@router.callback_query(F.data == f"{NS}:start")
async def on_browse_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    await start_flow(callback.message, state, _FLOW)
    await callback.answer()


async def _on_browse_done(
    callback: CallbackQuery, state: FSMContext, categories: list[str], cities: list[str]
) -> None:
    if not callback.message:
        return
    chat_id = callback.message.chat.id
    _last_query[chat_id] = EventQuery(
        cities=cities,
        categories=categories,
        date_from=date.today().isoformat(),
        sort_by="date_asc",
        page=1,
        page_size=PAGE_SIZE,
    )
    await _send_page(chat_id, page=1, message=callback.message, edit=True)


_FLOW = CategoryCityFlow(
    namespace=NS,
    categories_state=BrowseStates.waiting_for_categories,
    cities_state=BrowseStates.waiting_for_cities,
    on_done=_on_browse_done,
    done_label="Показать →",
    cancel_text="Поиск отменён.",
)
register_flow(router, _FLOW)


async def _build_favorite_links(chat_id: int, events: list[EventItem]) -> dict[str, list[str]]:
    """Renders a per-event add/remove-favorite deep link.

    Links beat inline buttons here because they stay bound to their own event:
    tapping a star in an old results message would otherwise act on whatever
    page the chat looked at last.
    """
    datable = [event for event in events if event.starts_at]
    if not datable:
        return {}

    tokens = await token_store.remember_many(
        EventRef(
            event_id=event.id,
            title=event.title,
            starts_at=event.starts_at,
            date_text=event.date_text,
            source_url=event.source_url,
        )
        for event in datable
    )
    favorite_ids = {item.event_id for item in favorites_store.get(chat_id)}

    lines: dict[str, list[str]] = {}
    for event in datable:
        token = tokens.get(event.id)
        if not token:
            continue
        if event.id in favorite_ids:
            link = start_link(f"{UNFAVORITE_PREFIX}{token}")
            label = "⭐ В избранном · убрать"
        else:
            link = start_link(f"{FAVORITE_PREFIX}{token}")
            label = "⭐ Сохранить"
        if link:
            lines[event.id] = [f'<a href="{link}">{label}</a>']
    return lines


async def _send_page(chat_id: int, *, page: int, message: Message, edit: bool = False) -> None:
    base_query = _last_query.get(chat_id)
    if not base_query:
        return
    query = replace(base_query, page=page)

    try:
        result = await api_client.get_events(query)
    except httpx.HTTPError:
        if edit:
            await message.edit_text(UNAVAILABLE_TEXT)
        else:
            await message.answer(UNAVAILABLE_TEXT)
        return

    action_links = await _build_favorite_links(chat_id, result.items)
    text = format_events_page(
        result.items,
        page=result.page,
        total_pages=result.total_pages,
        total=result.total,
        action_links_by_id=action_links,
    )
    if action_links:
        text += "\n\n«⭐ Сохранить» — напомню за 7, 3 и 1 день до старта."

    keyboard = _build_footer(result.page, result.total_pages)
    if edit:
        await message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


def _build_footer(page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"find_page:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Ещё →", callback_data=f"find_page:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="🎯 Другие фильтры", callback_data=f"{NS}:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
