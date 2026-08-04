from __future__ import annotations

from datetime import date

MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def pluralize(value: int, one: str, few: str, many: str) -> str:
    mod10, mod100 = value % 10, value % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return few
    return many


def parse_date(starts_at: str | None) -> date | None:
    if not starts_at:
        return None
    try:
        return date.fromisoformat(starts_at[:10])
    except ValueError:
        return None


def format_date(starts_at: str | None, fallback: str | None = None) -> str:
    """Human date: "7 августа", plus the year when it is not the current one."""
    parsed = parse_date(starts_at)
    if not parsed:
        return fallback or ""
    text = f"{parsed.day} {MONTHS[parsed.month - 1]}"
    if parsed.year != date.today().year:
        text = f"{text} {parsed.year}"
    return text


def format_countdown(starts_at: str | None) -> str:
    """Relative distance to the start: "сегодня", "завтра", "через 5 дней"."""
    parsed = parse_date(starts_at)
    if not parsed:
        return ""
    days = (parsed - date.today()).days
    if days < 0:
        return "уже прошёл"
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return f"через {days} {pluralize(days, 'день', 'дня', 'дней')}"
