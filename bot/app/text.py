from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re


MOSCOW_TZ = timezone(timedelta(hours=3))
REMINDER_OFFSETS = (7, 3, 1, 0)

MONTHS = (
    "",
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

MONTHS_SHORT = (
    "",
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


def pluralize(value: int, one: str, few: str, many: str) -> str:
    value = abs(value)
    if value % 10 == 1 and value % 100 != 11:
        return one
    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
        return few
    return many


def local_today() -> date:
    return datetime.now(MOSCOW_TZ).date()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", value)
        if match:
            try:
                return date(
                    int(match.group(3)),
                    int(match.group(2)),
                    int(match.group(1)),
                )
            except ValueError:
                return None
    return None


def format_date(value: str | None, fallback: str | None = None, short: bool = False) -> str:
    parsed = parse_date(value)
    if parsed is None:
        return (fallback or "дата уточняется").strip()

    months = MONTHS_SHORT if short else MONTHS
    today = local_today()
    year = "" if parsed.year == today.year else f" {parsed.year}"
    return f"{parsed.day} {months[parsed.month]}{year}"


def countdown(value: str | None) -> str | None:
    parsed = parse_date(value)
    if parsed is None:
        return None
    days = (parsed - local_today()).days
    if days < 0:
        return None
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    if days == 2:
        return "послезавтра"
    return f"через {days} {pluralize(days, 'день', 'дня', 'дней')}"


def days_until(value: str | None) -> int | None:
    parsed = parse_date(value)
    if parsed is None:
        return None
    return (parsed - local_today()).days


def greet_name(first_name: str | None) -> str:
    name = (first_name or "").strip()
    if not name:
        return "друг"
    return name[:32]
