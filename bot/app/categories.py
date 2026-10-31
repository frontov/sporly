from __future__ import annotations

from collections.abc import Iterable


CANONICAL_CATEGORIES = (
    "Бег",
    "Велоспорт",
    "Плавание",
    "Триатлон",
    "Лыжи",
    "Ориентирование",
    "Силовые виды",
    "ГТО",
    "Разное",
)

# Old labels kept for saved subscriptions and search sessions. The backend
# already returns canonical names, but users may still have older values in
# SQLite or FSM state after a deploy.
CATEGORY_ALIASES = {
    "Ориентирование и туризм": "Ориентирование",
    "ARDF, радиоспорт": "Разное",
    "ARDF": "Разное",
    "радиоспорт": "Разное",
    "Фастпакинг": "Разное",
    "Скайсноу": "Разное",
    "Ходьба": "Разное",
    "Боевые искусства": "Разное",
    "Единоборства": "Разное",
    "Бадминтон": "Разное",
    "Ездовой спорт": "Разное",
    "Гонки приключенческие; с препятствиями": "Разное",
    "Детские старты": "Разное",
    "Фиджитал": "Разное",
    "Другие": "Разное",
    "Легкая атлетика": "Разное",
}


def normalize_category(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return CATEGORY_ALIASES.get(cleaned, cleaned)


def normalize_categories(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        category = normalize_category(value)
        if category is None or category in seen:
            continue
        seen.add(category)
        normalized.append(category)
    return normalized
