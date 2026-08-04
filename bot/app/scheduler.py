from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot

from app.api_client import EventQuery, api_client
from app.config import settings
from app.formatting import format_event
from app.html import escape_html
from app.matching import matches
from app.favorites import REMINDER_OFFSET_DAYS, FavoriteEvent, favorites_store
from app.storage import store
from app.text import format_date, pluralize

logger = logging.getLogger(__name__)

FETCH_PAGE_SIZE = 50
DIGEST_EVENTS_LIMIT = 10
MAX_NOTIFICATIONS_PER_TICK = 5


async def poll_new_events(bot: Bot) -> None:
    while True:
        try:
            await _check_new_events(bot)
        except Exception:
            logger.exception("poll_new_events tick failed")
        await asyncio.sleep(settings.poll_interval_seconds)


async def _check_new_events(bot: Bot) -> None:
    subscriptions = [subscription for subscription in store.all() if subscription.notify_enabled]
    if not subscriptions:
        return

    page = await api_client.get_events(
        EventQuery(
            date_from=date.today().isoformat(),
            sort_by="date_asc",
            page=1,
            page_size=FETCH_PAGE_SIZE,
        )
    )

    for subscription in subscriptions:
        new_events = [
            event
            for event in page.items
            if matches(subscription, event) and event.id not in subscription.seen_event_ids
        ]
        if not new_events:
            continue

        for event in new_events[:MAX_NOTIFICATIONS_PER_TICK]:
            try:
                await bot.send_message(
                    subscription.chat_id,
                    f"🆕 <b>Новый старт по вашим фильтрам</b>\n\n{format_event(event)}",
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("failed to notify chat %s", subscription.chat_id)

        await store.mark_seen(subscription.chat_id, [event.id for event in new_events])


async def send_daily_digest(bot: Bot) -> None:
    while True:
        await _sleep_until_next_digest()
        try:
            await _send_digest(bot)
        except Exception:
            logger.exception("send_daily_digest tick failed")


async def _sleep_until_next_digest() -> None:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=settings.digest_hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())


async def _send_digest(bot: Bot) -> None:
    subscribers = [subscription for subscription in store.all() if subscription.digest_enabled]
    if not subscribers:
        return

    page = await api_client.get_events(
        EventQuery(
            date_from=date.today().isoformat(),
            sort_by="date_asc",
            page=1,
            page_size=FETCH_PAGE_SIZE,
        )
    )

    for subscription in subscribers:
        matched = [event for event in page.items if matches(subscription, event)][:DIGEST_EVENTS_LIMIT]
        if not matched:
            continue
        text = "📰 <b>Ближайшие старты</b>\n\n" + "\n\n".join(
            format_event(event, index=index) for index, event in enumerate(matched, start=1)
        )
        try:
            await bot.send_message(subscription.chat_id, text, disable_web_page_preview=True)
        except Exception:
            logger.exception("failed to send digest to chat %s", subscription.chat_id)


async def send_event_reminders(bot: Bot) -> None:
    while True:
        try:
            await _check_event_reminders(bot)
        except Exception:
            logger.exception("send_event_reminders tick failed")
        await asyncio.sleep(settings.reminder_check_interval_seconds)


async def _check_event_reminders(bot: Bot) -> None:
    today = date.today()

    for chat_id_str, items in favorites_store.all().items():
        chat_id = int(chat_id_str)
        for item in items:
            if not item.starts_at:
                continue
            try:
                event_date = date.fromisoformat(item.starts_at[:10])
            except ValueError:
                continue

            days_until = (event_date - today).days
            if days_until < 0:
                await favorites_store.remove(chat_id, item.event_id)
                continue

            for offset in REMINDER_OFFSET_DAYS:
                offset_key = str(offset)
                if offset_key in item.reminded_offsets or days_until > offset:
                    continue
                try:
                    await bot.send_message(
                        chat_id,
                        _format_reminder(item, days_until),
                        disable_web_page_preview=True,
                    )
                except Exception:
                    logger.exception("failed to send reminder to chat %s", chat_id)
                await favorites_store.mark_reminded(chat_id, item.event_id, offset_key)


def _format_reminder(item: FavoriteEvent, days_until: int) -> str:
    if days_until == 0:
        headline = "⏰ <b>Старт сегодня</b>"
    elif days_until == 1:
        headline = "⏰ <b>Старт завтра</b>"
    else:
        headline = f"⏰ <b>Старт через {days_until} {pluralize(days_until, 'день', 'дня', 'дней')}</b>"

    lines = [headline, "", f"<b>{escape_html(item.title)}</b>"]
    date_line = format_date(item.starts_at, item.date_text)
    if date_line:
        lines.append(escape_html(date_line))
    if item.source_url:
        lines.append(f'<a href="{escape_html(item.source_url)}">Подробнее ↗</a>')
    return "\n".join(lines)
