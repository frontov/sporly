from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.html import escape_html

# Mirrors frontend/src/categories.ts SPORT_OPTIONS.
CATEGORY_OPTIONS = [
    "ARDF, радиоспорт",
    "Бадминтон",
    "Бег",
    "Велоспорт",
    "Плавание",
    "ГТО",
    "Детские старты",
    "Другие",
    "Единоборства",
    "Лыжи",
    "Ориентирование и туризм",
    "Триатлон",
    "Ходьба",
]

# Mirrors frontend/src/App.tsx PINNED_REGIONS.
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

_REGION_SUFFIXES = ("область", "край", "республика", "автономный округ")
_STANDALONE_REGIONS = {"Москва", "Санкт-Петербург", "Севастополь"}


def is_pure_region_option(value: str) -> bool:
    """Mirrors frontend/src/App.tsx isPureRegionOption."""
    normalized = value.strip()
    if not normalized or "," in normalized or " и " in normalized:
        return False
    return normalized.endswith(_REGION_SUFFIXES) or normalized in _STANDALONE_REGIONS


def popular_regions(available_cities: list[str], *, limit: int = 12) -> list[str]:
    regions = sorted(
        {city for city in available_cities if is_pure_region_option(city)},
        key=lambda value: value,
    )
    pinned = [region for region in PINNED_REGIONS if region in regions]
    rest = [region for region in regions if region not in PINNED_REGIONS]
    return (pinned + rest)[:limit]


def format_selection_summary(categories: list[str], cities: list[str], *, with_cities: bool = True) -> str:
    lines = [f"🏅 {escape_html(', '.join(categories)) if categories else 'все виды спорта'}"]
    if with_cities:
        lines.append(f"📍 {escape_html(', '.join(cities)) if cities else 'вся Россия'}")
    return "\n".join(lines)


def _chunk_buttons(
    options: list[str], selected: list[str], *, callback_prefix: str, per_row: int = 2
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, option in enumerate(options):
        mark = "✅ " if option in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{option}", callback_data=f"{callback_prefix}{index}"))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def build_category_keyboard(selected: list[str], *, namespace: str) -> InlineKeyboardMarkup:
    rows = _chunk_buttons(CATEGORY_OPTIONS, selected, callback_prefix=f"{namespace}:cat:")
    rows.append(
        [
            InlineKeyboardButton(text="Сбросить", callback_data=f"{namespace}:cat_clear"),
            InlineKeyboardButton(text="Далее →", callback_data=f"{namespace}:cat_done"),
        ]
    )
    rows.append([InlineKeyboardButton(text="✕ Отмена", callback_data=f"{namespace}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_city_keyboard(
    selected: list[str], options: list[str], *, namespace: str, done_label: str
) -> InlineKeyboardMarkup:
    rows = _chunk_buttons(options, selected, callback_prefix=f"{namespace}:city:")
    rows.append(
        [
            InlineKeyboardButton(text="Сбросить", callback_data=f"{namespace}:city_clear"),
            InlineKeyboardButton(text=done_label, callback_data=f"{namespace}:city_done"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="← Назад", callback_data=f"{namespace}:city_back"),
            InlineKeyboardButton(text="✕ Отмена", callback_data=f"{namespace}:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
