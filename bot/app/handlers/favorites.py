from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.deeplinks import FAVORITE_PREFIX, UNFAVORITE_PREFIX, start_link
from app.event_tokens import EventRef, make_token, token_store
from app.favorites import FavoriteEvent, already_passed_offsets, favorites_store
from app.html import escape_html
from app.menu import FAVORITES_TEXTS
from app.text import format_countdown, format_date, pluralize

router = Router(name="favorites")

EMPTY_TEXT = (
    "⭐ <b>Избранное пусто</b>\n\n"
    "Найдите старт через «🔍 Найти события» и нажмите под ним «⭐ Сохранить».\n"
    "Напомню за неделю, за 3 дня и за день до старта."
)

STALE_LINK_TEXT = "🔗 Ссылка устарела. Откройте событие заново через «🔍 Найти события»."


@router.message(Command("favorites"))
@router.message(F.text.in_(FAVORITES_TEXTS))
async def cmd_favorites(message: Message) -> None:
    items = _sorted_favorites(message.chat.id)
    await message.answer(
        await render_favorites(items),
        disable_web_page_preview=True,
    )


def _sorted_favorites(chat_id: int) -> list[FavoriteEvent]:
    # Nearest start first; events without a parsable date sink to the bottom.
    return sorted(favorites_store.get(chat_id), key=lambda item: item.starts_at or "9999")


async def render_favorites(items: list[FavoriteEvent]) -> str:
    if not items:
        return EMPTY_TEXT

    # Refresh the token registry: favorites outlive its capped window, and the
    # "убрать" link must stay resolvable however long the event was saved.
    await token_store.remember_many(
        EventRef(
            event_id=item.event_id,
            title=item.title,
            starts_at=item.starts_at,
            date_text=item.date_text,
            source_url=item.source_url,
        )
        for item in items
    )

    header = f"⭐ <b>Избранное</b> · {len(items)} {pluralize(len(items), 'старт', 'старта', 'стартов')}"
    cards = []
    for index, item in enumerate(items, start=1):
        title = escape_html(item.title)
        if item.source_url:
            title = f'<a href="{escape_html(item.source_url)}">{title}</a>'
        lines = [f"<b>{index}.</b> {title}"]

        when = " · ".join(
            part
            for part in (format_date(item.starts_at, item.date_text), format_countdown(item.starts_at))
            if part
        )
        if when:
            lines.append(escape_html(when))

        remove_link = start_link(f"{UNFAVORITE_PREFIX}{make_token(item.event_id)}")
        if remove_link:
            lines.append(f'<a href="{remove_link}">✕ Убрать</a>')
        cards.append("\n".join(lines))

    footer = "Напомню за 7, 3 и 1 день до старта."
    return "\n\n".join([header, *cards, footer])


async def handle_favorite_payload(message: Message, payload: str) -> bool:
    """Handles `/start fav_<token>` / `/start unfav_<token>` deep links.

    Returns True when the payload was a favorites link, so the caller can skip
    the regular /start greeting.
    """
    if payload.startswith(FAVORITE_PREFIX):
        token, adding = payload[len(FAVORITE_PREFIX) :], True
    elif payload.startswith(UNFAVORITE_PREFIX):
        token, adding = payload[len(UNFAVORITE_PREFIX) :], False
    else:
        return False

    ref = token_store.get(token)
    if not ref:
        await message.answer(STALE_LINK_TEXT)
        return True

    chat_id = message.chat.id
    title = escape_html(ref.title)
    when = " · ".join(
        part
        for part in (format_date(ref.starts_at, ref.date_text), format_countdown(ref.starts_at))
        if part
    )
    when_line = f"\n{escape_html(when)}" if when else ""

    if not adding:
        await favorites_store.remove(chat_id, ref.event_id)
        undo = start_link(f"{FAVORITE_PREFIX}{token}")
        undo_line = f'\n\n<a href="{undo}">↩ Вернуть в избранное</a>' if undo else ""
        await message.answer(
            f"✕ <b>Убрано из избранного</b>\n\n{title}{when_line}{undo_line}",
            disable_web_page_preview=True,
        )
        return True

    if favorites_store.is_favorite(chat_id, ref.event_id):
        await message.answer(
            f"⭐ <b>Уже в избранном</b>\n\n{title}{when_line}\n\nВесь список — «⭐ Избранное» внизу.",
            disable_web_page_preview=True,
        )
        return True

    await favorites_store.add(
        chat_id,
        FavoriteEvent(
            event_id=ref.event_id,
            title=ref.title,
            starts_at=ref.starts_at,
            date_text=ref.date_text,
            source_url=ref.source_url,
            reminded_offsets=already_passed_offsets(ref.starts_at),
        ),
    )
    undo = start_link(f"{UNFAVORITE_PREFIX}{token}")
    undo_line = f'\n<a href="{undo}">✕ Убрать</a>' if undo else ""
    await message.answer(
        f"⭐ <b>Сохранено</b>\n\n{title}{when_line}\n\n"
        f"Напомню за 7, 3 и 1 день до старта. Весь список — «⭐ Избранное» внизу.{undo_line}",
        disable_web_page_preview=True,
    )
    return True
