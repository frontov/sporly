from __future__ import annotations

from html import escape

from aiogram import Bot, Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.api_client import api_client
from app.flows import (
    delete_current_screen,
    finish_subscription,
    save_interests,
    show_interests_saved,
    start_search,
)
from app.formatting import clean_text, filters_summary
from app.keyboards import category_keyboard, city_keyboard
from app.context import database


router = Router(name="filter_wizard")


class FlowStates(StatesGroup):
    waiting_city = State()


DEFAULT_CATEGORIES = [
    "Бег",
    "Велоспорт",
    "Лыжи",
    "Триатлон",
    "Плавание",
    "Ходьба",
    "Ориентирование и туризм",
    "Единоборства",
    "Бадминтон",
    "ГТО",
    "Детские старты",
    "Легкая атлетика",
    "Другие",
    "ARDF, радиоспорт",
]

PINNED_REGIONS = [
    "Москва",
    "Московская область",
    "Санкт-Петербург",
    "Ленинградская область",
    "Краснодарский край",
    "Республика Татарстан",
    "Свердловская область",
    "Челябинская область",
    "Самарская область",
    "Нижегородская область",
    "Тюменская область",
    "Новосибирская область",
]


async def _options() -> tuple[list[str], list[str]]:
    cities, categories = await api_client.get_filter_options()
    if not categories:
        categories = list(DEFAULT_CATEGORIES)
    else:
        order = {value: index for index, value in enumerate(DEFAULT_CATEGORIES)}
        categories = sorted(
            set(categories),
            key=lambda value: (order.get(value, 999), value.casefold()),
        )
    if not cities:
        cities = list(PINNED_REGIONS)
    else:
        ordered = [city for city in PINNED_REGIONS if city in cities]
        ordered += [city for city in cities if city not in PINNED_REGIONS]
        cities = ordered
    return cities, categories


async def _state_data(state: FSMContext) -> dict:
    data = await state.get_data()
    data.setdefault("mode", "search")
    data.setdefault("categories", [])
    data.setdefault("cities", [])
    data.setdefault("cat_page", 0)
    data.setdefault("city_page", 0)
    return data


def _categories_text(data: dict) -> str:
    selected = data.get("categories") or []
    summary = filters_summary(data.get("cities") or [], selected)
    intro = ""
    if data.get("mode") == "onboarding":
        intro = "<b>Настроим подборку</b>\n\n"
    return (
        f"{intro}<b>Шаг 1 из 2 · Вид спорта</b>\n\n"
        "Можно выбрать несколько вариантов.\n"
        f"Выбрано: {summary}"
    )


def _cities_text(data: dict) -> str:
    selected = data.get("cities") or []
    summary = "📍 " + escape(", ".join(selected)) if selected else "📍 Вся Россия"
    return (
        "<b>Шаг 2 из 2 · Регион</b>\n\n"
        "Выберите один или несколько регионов. Если ничего не выбрать — "
        "будет вся Россия.\n"
        f"Выбрано регионов: <b>{len(selected)}</b>\n"
        f"Сейчас: {summary}"
    )


async def _edit(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise


async def _render_categories(callback: CallbackQuery, state: FSMContext) -> None:
    data = await _state_data(state)
    _, categories = await _options()
    for value in data["categories"]:
        if value not in categories:
            categories.append(value)
    await state.update_data(categories=data["categories"])
    await _edit(
        callback,
        _categories_text(data),
        category_keyboard(
            categories,
            set(data["categories"]),
            page=int(data.get("cat_page") or 0),
            skip=data.get("mode") == "onboarding",
        ),
    )


async def _render_cities(callback: CallbackQuery, state: FSMContext) -> None:
    data = await _state_data(state)
    cities, _ = await _options()
    for value in data["cities"]:
        if value not in cities:
            cities.append(value)
    await _edit(
        callback,
        _cities_text(data),
        city_keyboard(
            cities,
            set(data["cities"]),
            page=int(data.get("city_page") or 0),
            skip=data.get("mode") == "onboarding",
        ),
    )


async def send_onboarding(bot: Bot, chat_id: int, state: FSMContext) -> Message | None:
    subscription = await database.get_subscription(chat_id)
    categories_selected = list(subscription.categories) if subscription else []
    cities_selected = list(subscription.cities) if subscription else []
    await state.clear()
    await state.update_data(
        mode="onboarding",
        categories=categories_selected,
        cities=cities_selected,
        cat_page=0,
        city_page=0,
    )
    data = await _state_data(state)
    _, categories = await _options()
    for value in categories_selected:
        if value not in categories:
            categories.append(value)
    await bot.send_message(
        chat_id,
        _categories_text(data),
        reply_markup=category_keyboard(
            categories,
            set(categories_selected),
            page=0,
            skip=True,
        ),
    )


@router.callback_query(F.data.in_({"flow:new:search", "flow:new:subscribe", "flow:new:onboarding", "flow:city_only"}))
async def start_flow(
    callback: CallbackQuery, state: FSMContext, bot_username: str = ""
) -> None:
    data = callback.data or ""
    if data.endswith("onboarding"):
        mode = "onboarding"
    elif data.endswith("subscribe"):
        mode = "subscribe"
    else:
        mode = "search"
    await state.clear()
    await state.update_data(mode=mode, categories=[], cities=[], cat_page=0, city_page=0)
    await callback.answer()
    if data == "flow:city_only":
        await _render_cities(callback, state)
    else:
        await _render_categories(callback, state)


async def open_existing_flow(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    mode: str,
    cities: list[str],
    categories: list[str],
) -> None:
    await state.clear()
    await state.update_data(
        mode=mode,
        categories=list(categories),
        cities=list(cities),
        cat_page=0,
        city_page=0,
    )
    await callback.answer()
    await _render_categories(callback, state)


@router.callback_query(F.data.startswith("flow:catpage:"))
async def category_page(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        page = int((callback.data or "").split(":", 2)[2])
    except (IndexError, ValueError):
        page = 0
    await state.update_data(cat_page=max(page, 0))
    await callback.answer()
    await _render_categories(callback, state)


@router.callback_query(F.data.startswith("flow:cat:"))
async def toggle_category(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":", 2)[2]
    if action == "done":
        await callback.answer()
        await _render_cities(callback, state)
        return
    if action == "clear":
        await state.update_data(categories=[])
        await callback.answer("Фильтры сброшены")
        await _render_categories(callback, state)
        return

    try:
        index = int(action)
    except ValueError:
        await callback.answer("Не понял выбор", show_alert=False)
        return
    _, categories = await _options()
    if not 0 <= index < len(categories):
        await callback.answer("Список обновился, попробуйте ещё раз")
        await _render_categories(callback, state)
        return
    category = categories[index]
    data = await _state_data(state)
    selected = list(data["categories"])
    if category in selected:
        selected.remove(category)
    else:
        selected.append(category)
    await state.update_data(categories=selected)
    await callback.answer()
    await _render_categories(callback, state)


@router.callback_query(F.data.startswith("flow:citypage:"))
async def city_page(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        page = int((callback.data or "").split(":", 2)[2])
    except (IndexError, ValueError):
        page = 0
    await state.update_data(city_page=max(page, 0))
    await callback.answer()
    await _render_cities(callback, state)


@router.callback_query(F.data.startswith("flow:city:"))
async def city_action(
    callback: CallbackQuery, state: FSMContext, bot: Bot, bot_username: str = ""
) -> None:
    action = (callback.data or "").split(":", 2)[2]
    data = await _state_data(state)

    if action == "all":
        await state.update_data(cities=[])
        await callback.answer("Выбрана вся Россия")
        await _finish(callback, state, bot, bot_username, cities=[], categories=data["categories"])
        return
    if action == "done":
        await callback.answer()
        await _finish(
            callback,
            state,
            bot,
            bot_username,
            cities=data["cities"],
            categories=data["categories"],
        )
        return
    if action == "other":
        await state.update_data(prompt_message_id=callback.message.message_id)
        await state.set_state(FlowStates.waiting_city)
        await callback.answer()
        await _edit(
            callback,
            "<b>Напишите регион или город</b>\n\n"
            "Например: Казань, Сочи, Свердловская область.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")]
                ]
            ),
        )
        return

    try:
        index = int(action)
    except ValueError:
        await callback.answer("Не понял выбор")
        return
    cities, _ = await _options()
    if not 0 <= index < len(cities):
        await callback.answer("Список обновился, попробуйте ещё раз")
        await _render_cities(callback, state)
        return
    city = cities[index]
    selected = list(data["cities"])
    if city in selected:
        selected.remove(city)
    else:
        if len(selected) >= 5:
            await callback.answer("Можно выбрать до 5 регионов", show_alert=True)
            return
        selected.append(city)
    await state.update_data(cities=selected)
    await callback.answer()
    await _render_cities(callback, state)


@router.callback_query(F.data == "flow:back")
async def back_to_categories(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(city_page=0)
    await callback.answer()
    await _render_categories(callback, state)


@router.callback_query(F.data == "flow:cancel")
async def cancel_flow(
    callback: CallbackQuery, state: FSMContext, bot: Bot, bot_username: str = ""
) -> None:
    data = await state.get_data()
    mode = data.get("mode")
    await state.clear()
    await callback.answer()
    if callback.from_user is None:
        return
    if mode == "onboarding":
        await database.mark_survey_completed(callback.from_user.id)
    await delete_current_screen(callback.message)
    from app.handlers.common import send_home

    await send_home(bot, callback.from_user.id)


@router.callback_query(F.data == "flow:skip")
async def skip_flow(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    await state.clear()
    await callback.answer()
    if callback.from_user is None:
        return
    await database.mark_survey_completed(callback.from_user.id)
    await delete_current_screen(callback.message)
    from app.handlers.common import send_home

    await send_home(bot, callback.from_user.id)


@router.message(FlowStates.waiting_city, F.text)
async def city_text(
    message: Message,
    state: FSMContext,
    bot: Bot,
    bot_username: str = "",
) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Ок, вернулся в меню.")
        return

    from app.handlers.common import send_find_hub, send_more
    from app.flows import show_favorites, show_subscription, start_search
    from app.keyboards import menu_callback_for_text

    data = await _state_data(state)
    prompt_id = data.get("prompt_message_id")
    menu_callback = menu_callback_for_text(text)
    if menu_callback:
        await state.clear()
        if prompt_id:
            try:
                await bot.delete_message(message.chat.id, prompt_id)
            except Exception:
                pass
        action = menu_callback.split(":", 1)[1]
        if action == "find":
            await send_find_hub(bot, message.from_user.id)
        elif action == "soon":
            await start_search(bot, message.from_user.id, bot_username=bot_username)
        elif action == "fav":
            await show_favorites(bot, message.from_user.id, bot_username=bot_username)
        elif action == "sub":
            await show_subscription(bot, message.from_user.id, bot_username=bot_username)
        elif action == "more":
            await send_more(bot, message.from_user.id, bot_username=bot_username)
        return

    value = clean_text(text, 80)
    if not value:
        await message.answer("Напишите название региона текстом.")
        return

    data = await _state_data(state)
    prompt_id = data.get("prompt_message_id")
    selected = list(data["cities"])
    if value.casefold() not in {item.casefold() for item in selected}:
        if len(selected) >= 5:
            await message.answer("Можно выбрать до 5 регионов.")
            return
        selected.append(value)
    await state.update_data(cities=selected, city_page=0)
    await state.set_state(None)

    cities, _ = await _options()
    if value not in cities:
        cities.insert(0, value)
    text_value = _cities_text({**data, "cities": selected})
    markup = city_keyboard(
        cities,
        set(selected),
        page=0,
        skip=data.get("mode") == "onboarding",
    )
    if prompt_id:
        try:
            await bot.edit_message_text(
                text_value,
                chat_id=message.chat.id,
                message_id=prompt_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass
    await message.answer(text_value, reply_markup=markup)


async def _finish(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    bot_username: str,
    *,
    cities: list[str],
    categories: list[str],
) -> None:
    data = await _state_data(state)
    mode = data.get("mode", "search")
    await state.clear()
    await delete_current_screen(callback.message)
    chat_id = callback.from_user.id
    await database.touch_user(chat_id)

    if mode == "onboarding":
        subscription = await save_interests(
            chat_id,
            cities=cities,
            categories=categories,
        )
        await database.mark_survey_completed(chat_id)
        await show_interests_saved(bot, chat_id, subscription)
    elif mode.startswith("subscribe"):
        await finish_subscription(
            bot,
            chat_id,
            cities=cities,
            categories=categories,
            bot_username=bot_username,
        )
    else:
        await start_search(
            bot,
            chat_id,
            cities=cities,
            categories=categories,
            bot_username=bot_username,
        )
