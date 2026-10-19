from __future__ import annotations

from html import escape
import re
from urllib.parse import urlparse

from app.api_client import Event
from app.storage import Favorite
from app.links import event_token, share_url
from app.text import EVENT_COLORS, countdown, format_date, pluralize


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None, limit: int = 0) -> str:
    if not value:
        return ""
    text = SPACE_RE.sub(" ", TAG_RE.sub(" ", value)).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def source_link(url: str | None, name: str | None) -> str:
    if not url:
        return ""
    label = escape(clean_text(name or "Открыть сайт", 40))
    return f'<a href="{escape(url, quote=True)}">{label}</a>'


def event_when(event: Event) -> str:
    when = format_date(event.starts_at, event.date_text)
    relative = countdown(event.starts_at)
    return f"{when} · {relative}" if relative else when


def event_facts(event: Event) -> list[str]:
    facts: list[str] = []
    if event.distance_summary:
        facts.append(clean_text(event.distance_summary, 80))
    if event.surface_type:
        facts.append(clean_text(event.surface_type, 40))
    if event.price_from:
        facts.append(clean_text(event.price_from, 40))
    if event.registration_deadline:
        facts.append("регистрация " + clean_text(event.registration_deadline, 60))
    elif event.registration_status == "open":
        facts.append("регистрация открыта")
    elif event.registration_status == "closed":
        facts.append("регистрация закрыта")
    return facts


def pick_image(event: Event) -> str | None:
    """Telegram can render raster photos only; SVG previews are skipped."""

    url = (event.image_url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    path = urlparse(url).path.lower()
    if not path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return None
    if any(marker in path for marker in ("50_50", "50x50", "100x100", "logo")):
        return None
    return url


def format_event_card(event: Event) -> str:
    """Compact card used as a photo caption or a standalone message."""

    title = escape(clean_text(event.title, 120))
    lines = [f"<b>{title}</b>", ""]

    meta: list[str] = []
    if event.category:
        meta.append(clean_text(event.category, 40))
    if event.distance_summary:
        meta.append(clean_text(event.distance_summary, 50))
    if event.surface_type:
        meta.append(clean_text(event.surface_type, 30))
    if meta:
        lines.append("🏁 " + escape(" · ".join(meta)))

    lines.append(f"📅 {escape(event_when(event))}")

    if event.location:
        lines.append(f"📍 {escape(clean_text(event.location, 90))}")
    elif event.venue:
        lines.append(f"📍 {escape(clean_text(event.venue, 90))}")

    money: list[str] = []
    if event.price_from:
        money.append(clean_text(event.price_from, 40))
    if event.registration_deadline:
        money.append("регистрация " + clean_text(event.registration_deadline, 50))
    elif event.registration_status == "open":
        money.append("регистрация открыта")
    elif event.registration_status == "closed":
        money.append("регистрация закрыта")
    if money:
        lines.append("💳 " + escape(" · ".join(money)))

    description = clean_text(event.description, 90)
    if description and description.casefold() not in title.casefold():
        lines.append(f"\n<i>{escape(description)}</i>")

    return "\n".join(lines)


def format_favorite_card(favorite: Favorite) -> str:
    title = escape(clean_text(favorite.title, 120))
    lines = [f"<b>{title}</b>", ""]

    meta: list[str] = []
    if favorite.category:
        meta.append(clean_text(favorite.category, 40))
    if meta:
        lines.append("🏁 " + escape(" · ".join(meta)))

    when = format_date(favorite.starts_at, favorite.date_text)
    relative = countdown(favorite.starts_at)
    lines.append(f"📅 {escape(when + (f' · {relative}' if relative else ''))}")
    if favorite.location:
        lines.append(f"📍 {escape(clean_text(favorite.location, 90))}")
    lines.append("\n🔔 Напомним за 7, 3 и 1 день до старта.")
    return "\n".join(lines)


def format_event(event: Event, index: int | None = None) -> str:
    title = escape(clean_text(event.title, 160))
    prefix = f"{index}. " if index is not None else ""
    lines = [f"<b>{prefix}{title}</b>"]

    if event.category:
        lines.append(f"🏷 {escape(clean_text(event.category, 40))}")

    lines.append(f"📅 {escape(event_when(event))}")

    if event.location:
        lines.append(f"📍 {escape(clean_text(event.location, 100))}")
    elif event.venue:
        lines.append(f"📍 {escape(clean_text(event.venue, 100))}")

    facts = event_facts(event)
    if facts:
        lines.append("🏁 " + escape(" · ".join(facts)))

    description = clean_text(event.description, 180)
    if description and description.casefold() not in title.casefold():
        lines.append(f"<i>{escape(description)}</i>")

    link = source_link(event.source_url, event.source_name)
    if link:
        lines.append(f"🔗 {link}")

    return "\n".join(lines)


def format_favorite(
    favorite: Favorite,
    index: int | None = None,
) -> str:
    title = escape(clean_text(favorite.title, 120))
    marker = (
        EVENT_COLORS[(index - 1) % len(EVENT_COLORS)] + " "
        if index is not None
        else ""
    )
    prefix = marker
    heading = f"<b>{prefix}{title}</b>"

    when = format_date(favorite.starts_at, favorite.date_text, short=True)
    relative = countdown(favorite.starts_at)
    meta = " · ".join(
        part
        for part in (
            when + (f", {relative}" if relative else ""),
            clean_text(favorite.location, 45),
        )
        if part
    )
    lines = [heading]
    if meta:
        lines.append(f"📅 {escape(meta)}")
    if favorite.category:
        lines.append(f"🏁 {escape(clean_text(favorite.category, 40))}")
    return "\n".join(lines)


def format_event_list(
    events: list[Event],
    *,
    total: int,
    page: int,
    total_pages: int,
    filters: str | None = None,
    title: str = "Ближайшие старты",
    page_size: int = 4,
) -> str:
    header = f"<b>{title}</b>\n"
    if filters:
        header += f"{filters}\n"
    header += (
        f"Найдено {total} {pluralize(total, 'старт', 'старта', 'стартов')}"
        f" · стр. {page}/{max(total_pages, 1)}"
    )

    cards: list[str] = []
    for position, event in enumerate(events, start=1):
        event_title = escape(clean_text(event.title, 95))
        marker = EVENT_COLORS[(position - 1) % len(EVENT_COLORS)]
        heading = f"<b>{marker} {event_title}</b>"

        when = format_date(event.starts_at, event.date_text, short=True)
        place = clean_text(event.location or event.venue, 42)
        meta = " · ".join(part for part in (when, place) if part)

        facts = [
            clean_text(event.category, 28),
            clean_text(event.distance_summary, 28),
            clean_text(event.price_from, 24),
        ]
        facts_line = " · ".join(part for part in facts if part)

        card = heading
        if meta:
            card += f"\n📅 {escape(meta)}"
        if facts_line:
            card += f"\n🏁 {escape(facts_line)}"
        cards.append(card)

    text = header
    for card in cards:
        candidate = text + "\n\n" + card
        if len(candidate) > 3900:
            break
        text = candidate
    return text


def format_event_details(event: Event, marker: str = "") -> str:
    title = escape(clean_text(event.title, 180))
    prefix = f"{marker} " if marker else ""
    lines = [f"<b>{prefix}{title}</b>", ""]

    facts: list[str] = []
    if event.category:
        facts.append(clean_text(event.category, 40))
    if event.distance_summary:
        facts.append(clean_text(event.distance_summary, 80))
    if event.surface_type:
        facts.append(clean_text(event.surface_type, 40))
    if facts:
        lines.append("🏁 " + escape(" · ".join(facts)))

    lines.append(f"📅 {escape(event_when(event))}")
    if event.location:
        lines.append(f"📍 {escape(clean_text(event.location, 120))}")
    elif event.venue:
        lines.append(f"📍 {escape(clean_text(event.venue, 120))}")

    money: list[str] = []
    if event.price_from:
        money.append(clean_text(event.price_from, 50))
    if event.registration_deadline:
        money.append("регистрация " + clean_text(event.registration_deadline, 60))
    elif event.registration_status == "open":
        money.append("регистрация открыта")
    elif event.registration_status == "closed":
        money.append("регистрация закрыта")
    if money:
        lines.append("💳 " + escape(" · ".join(money)))

    if event.organizer_name:
        lines.append(f"👤 {escape(clean_text(event.organizer_name, 80))}")

    description = clean_text(event.description, 600)
    if description and description.casefold() not in title.casefold():
        lines.append("")
        lines.append(escape(description))

    if event.source_name:
        lines.append("")
        lines.append(f"<i>{escape(clean_text(event.source_name, 50))}</i>")

    return "\n".join(lines)


def format_digest_event(event: Event, index: int) -> str:
    title = escape(clean_text(event.title, 120))
    when = format_date(event.starts_at, event.date_text, short=True)
    place = clean_text(event.location or event.venue, 45)
    meta = " · ".join(part for part in (when, place) if part)
    link = source_link(event.source_url, "Открыть")
    return f"<b>{index}. {title}</b>\n{escape(meta)}\n{link}"


def filters_summary(cities: list[str], categories: list[str]) -> str:
    parts: list[str] = []
    if categories:
        parts.append("🏃 " + escape(", ".join(categories[:4])))
    if cities:
        parts.append("📍 " + escape(", ".join(cities[:3])))
    if not parts:
        return "🌍 Все виды спорта, вся Россия"
    return " · ".join(parts)
