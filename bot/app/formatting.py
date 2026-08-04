from __future__ import annotations

from collections.abc import Sequence

from app.api_client import EventItem
from app.html import escape_html
from app.text import format_date, pluralize


def format_event(
    event: EventItem,
    *,
    index: int | None = None,
    action_links: Sequence[str] = (),
) -> str:
    """One event card: title, when/where, facts, then a row of links."""
    title = escape_html(event.title)
    lines = [f"<b>{index}. {title}</b>" if index else f"<b>{title}</b>"]

    when_where = _join(format_date(event.starts_at, event.date_text), _location(event))
    if when_where:
        lines.append(escape_html(when_where))

    facts = _join(event.category, event.price_from)
    if facts:
        lines.append(escape_html(facts))

    links = [f'<a href="{escape_html(event.source_url)}">Подробнее ↗</a>', *action_links]
    lines.append(" · ".join(links))
    return "\n".join(lines)


def format_events_page(
    events: list[EventItem],
    *,
    page: int,
    total_pages: int,
    total: int,
    action_links_by_id: dict[str, list[str]] | None = None,
) -> str:
    if not events:
        return (
            "😕 <b>Ничего не нашлось</b>\n\n"
            "Попробуйте изменить фильтры — «🎯 Другие фильтры» внизу."
        )

    counter = f"{total} {pluralize(total, 'старт', 'старта', 'стартов')}"
    header = f"🔎 <b>{counter}</b>"
    if total_pages > 1:
        header = f"{header} · стр. {page} из {total_pages}"

    cards = [
        format_event(
            event,
            index=index,
            action_links=(action_links_by_id or {}).get(event.id, ()),
        )
        for index, event in enumerate(events, start=1)
    ]
    return "\n\n".join([header, *cards])


def _location(event: EventItem) -> str:
    city, region = event.city, event.region
    # Sources often already spell the region into the city ("Кинешма, Ивановская
    # область"), so only append it when it is not there yet.
    if city and region and region.casefold() not in city.casefold():
        return f"{city}, {region}"
    return city or region or event.venue or ""


def _join(*parts: str | None) -> str:
    return " · ".join(part for part in parts if part)
