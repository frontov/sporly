from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from app.api_client import api_client
from app.filter_ui import (
    CATEGORY_OPTIONS,
    build_category_keyboard,
    build_city_keyboard,
    format_selection_summary,
    popular_regions,
)

UNAVAILABLE_TEXT = "⚠️ Сервис сейчас недоступен. Попробуйте через пару минут."

OnDone = Callable[[CallbackQuery, FSMContext, list[str], list[str]], Awaitable[None]]


@dataclass(frozen=True)
class CategoryCityFlow:
    """A reusable two-step "pick sport chips, then city chips" wizard.

    Shared by /subscribe (finishes by saving a subscription) and /find with
    no query (finishes by listing matching events) - both need the exact
    same chip UI mirrored from the frontend filters panel.
    """

    namespace: str
    categories_state: State
    cities_state: State
    on_done: OnDone
    categories_title: str = "🏅 <b>Виды спорта</b> · шаг 1 из 2"
    cities_title: str = "📍 <b>Где</b> · шаг 2 из 2"
    done_label: str = "Готово →"
    cancel_text: str = "Отменено."


def _categories_text(flow: CategoryCityFlow, categories: list[str]) -> str:
    return (
        f"{flow.categories_title}\n"
        "Отметьте нужные. Ничего не выбрано — покажу все.\n\n"
        f"{format_selection_summary(categories, [], with_cities=False)}"
    )


def _cities_text(flow: CategoryCityFlow, categories: list[str], cities: list[str]) -> str:
    return (
        f"{flow.cities_title}\n"
        "Отметьте регионы. Ничего не выбрано — вся Россия.\n\n"
        f"{format_selection_summary(categories, cities)}"
    )


async def start(message: Message, state: FSMContext, flow: CategoryCityFlow) -> None:
    await state.clear()
    await state.set_state(flow.categories_state)
    await state.update_data(categories=[])
    await message.answer(
        _categories_text(flow, []),
        reply_markup=build_category_keyboard([], namespace=flow.namespace),
    )


def register(router: Router, flow: CategoryCityFlow) -> None:
    ns = flow.namespace

    @router.callback_query(flow.categories_state, F.data.startswith(f"{ns}:cat:"))
    async def on_toggle_category(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.message or not callback.data:
            await callback.answer()
            return
        index = int(callback.data.rsplit(":", 1)[1])
        if index >= len(CATEGORY_OPTIONS):
            await callback.answer()
            return

        option = CATEGORY_OPTIONS[index]
        data = await state.get_data()
        categories = list(data.get("categories", []))
        if option in categories:
            categories.remove(option)
        else:
            categories.append(option)
        await state.update_data(categories=categories)

        await callback.message.edit_text(
            _categories_text(flow, categories),
            reply_markup=build_category_keyboard(categories, namespace=ns),
        )
        await callback.answer()

    @router.callback_query(flow.categories_state, F.data == f"{ns}:cat_clear")
    async def on_clear_categories(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.message:
            await callback.answer()
            return
        await state.update_data(categories=[])
        await callback.message.edit_text(
            _categories_text(flow, []),
            reply_markup=build_category_keyboard([], namespace=ns),
        )
        await callback.answer()

    @router.callback_query(flow.categories_state, F.data == f"{ns}:cat_done")
    async def on_categories_done(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.message:
            await callback.answer()
            return
        try:
            available_cities, _ = await api_client.get_filter_options()
        except httpx.HTTPError:
            await state.clear()
            await callback.message.edit_text(UNAVAILABLE_TEXT)
            await callback.answer()
            return

        city_options = popular_regions(available_cities)
        await state.update_data(city_options=city_options, cities=[])
        await state.set_state(flow.cities_state)

        data = await state.get_data()
        await callback.message.edit_text(
            _cities_text(flow, data.get("categories", []), []),
            reply_markup=build_city_keyboard([], city_options, namespace=ns, done_label=flow.done_label),
        )
        await callback.answer()

    @router.callback_query(flow.cities_state, F.data.startswith(f"{ns}:city:"))
    async def on_toggle_city(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.message or not callback.data:
            await callback.answer()
            return
        data = await state.get_data()
        city_options: list[str] = data.get("city_options", [])
        index = int(callback.data.rsplit(":", 1)[1])
        if index >= len(city_options):
            await callback.answer()
            return

        option = city_options[index]
        cities = list(data.get("cities", []))
        if option in cities:
            cities.remove(option)
        else:
            cities.append(option)
        await state.update_data(cities=cities)

        await callback.message.edit_text(
            _cities_text(flow, data.get("categories", []), cities),
            reply_markup=build_city_keyboard(cities, city_options, namespace=ns, done_label=flow.done_label),
        )
        await callback.answer()

    @router.callback_query(flow.cities_state, F.data == f"{ns}:city_clear")
    async def on_clear_cities(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.message:
            await callback.answer()
            return
        data = await state.get_data()
        await state.update_data(cities=[])
        await callback.message.edit_text(
            _cities_text(flow, data.get("categories", []), []),
            reply_markup=build_city_keyboard([], data.get("city_options", []), namespace=ns, done_label=flow.done_label),
        )
        await callback.answer()

    @router.callback_query(flow.cities_state, F.data == f"{ns}:city_back")
    async def on_cities_back(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.message:
            await callback.answer()
            return
        data = await state.get_data()
        await state.set_state(flow.categories_state)
        categories = data.get("categories", [])
        await callback.message.edit_text(
            _categories_text(flow, categories),
            reply_markup=build_category_keyboard(categories, namespace=ns),
        )
        await callback.answer()

    @router.callback_query(flow.cities_state, F.data == f"{ns}:city_done")
    async def on_cities_done(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.message:
            await callback.answer()
            return
        data = await state.get_data()
        categories: list[str] = data.get("categories", [])
        cities: list[str] = data.get("cities", [])
        await state.clear()
        await flow.on_done(callback, state, categories, cities)
        await callback.answer()

    @router.callback_query(F.data == f"{ns}:cancel")
    async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if callback.message:
            await callback.message.edit_text(flow.cancel_text)
        await callback.answer()
