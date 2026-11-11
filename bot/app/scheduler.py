from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import logging
from html import escape

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)

from app.api_client import Event, EventQuery, api_client, today_iso
from app.config import settings
from app.context import database, search_sessions
from app.flows import (
    _event_tokens,
    _favorite_ids,
    _find_partner,
    render_search_page,
)
from app.formatting import (
    clean_text,
    filters_summary,
    format_digest_event,
    format_favorite,
)
from app.keyboards import BUTTON_HOME, BUTTON_INTERESTS, BUTTON_OPEN
from app.links import event_click_url
from app.storage import Favorite, Subscription, event_identity, stable_event_id
from app.text import (
    MOSCOW_TZ,
    REGISTRATION_END_OFFSET,
    REGISTRATION_START_OFFSET,
    REMINDER_OFFSETS,
    days_until,
    local_today,
    parse_date,
)


logger = logging.getLogger(__name__)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
REGISTRATION_OPEN_STATUSES = frozenset({"open", "limited"})
_UNSET = object()


def _quiet_hour(hour: int) -> bool:
    """Whether a local Moscow hour is inside the configured quiet window."""

    start = settings.quiet_hours_start % 24
    end = settings.quiet_hours_end % 24
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def is_quiet_hours(now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now(MOSCOW_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=MOSCOW_TZ)
    else:
        now = now.astimezone(MOSCOW_TZ)
    return _quiet_hour(now.hour)


def seconds_until_quiet_end(now: datetime | None = None) -> int:
    """Seconds to sleep before the next daytime delivery window opens."""

    if now is None:
        now = datetime.now(MOSCOW_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=MOSCOW_TZ)
    else:
        now = now.astimezone(MOSCOW_TZ)
    if not _quiet_hour(now.hour):
        return 0
    target = now.replace(
        hour=settings.quiet_hours_end % 24,
        minute=0,
        second=0,
        microsecond=0,
    )
    if target <= now:
        target += timedelta(days=1)
    return max(int((target - now).total_seconds()), 60)


def _effective_digest_hour_utc() -> int:
    """Move the digest out of quiet hours if it was configured at night."""

    local_hour = (settings.digest_hour_utc + 3) % 24
    if _quiet_hour(local_hour):
        return (settings.quiet_hours_end - 3) % 24
    return settings.digest_hour_utc % 24


def _today() -> str:
    return local_today().isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_new_since(first_seen_at: str | None, cutoff: str | None) -> bool:
    """Whether an event appeared after the subscription was (re)configured."""

    cutoff_dt = _parse_datetime(cutoff)
    if cutoff_dt is None:
        return True
    first_seen_dt = _parse_datetime(first_seen_at)
    if first_seen_dt is None:
        return True
    return first_seen_dt >= cutoff_dt


NEW_EVENTS_TITLE = "🆕 Новые старты по вашим интересам"


async def _send_new_events_batch(
    bot: Bot,
    subscription: Subscription,
    events: list[Event],
    *,
    bot_username: str = "",
) -> bool:
    """Send fresh events as the same list screen as «Ближайшие старты»."""

    chat_id = subscription.chat_id
    session = search_sessions.create(
        chat_id,
        cities=subscription.cities,
        categories=subscription.categories,
        events=events,
        title=NEW_EVENTS_TITLE,
    )
    sent = await render_search_page(
        bot,
        chat_id,
        session,
        page=1,
        bot_username=bot_username,
        silent=True,
    )
    if sent is None:
        return False

    for event in events:
        await database.mark_seen(chat_id, [event.id])
        await database.log_event(chat_id, "notification_sent", event.id)
    await database.log_event(
        chat_id, "new_events_digest_sent", str(len(events))
    )
    return True


async def check_new_events(bot: Bot, bot_username: str = "") -> int:
    # Proactive messages are daytime-only.
    if is_quiet_hours():
        return 0

    subscriptions = await database.active_subscriptions()

    # Users often share the same filters. Group them so the catalog is queried
    # once per filter combination instead of once per subscriber.
    grouped: dict[tuple[tuple[str, ...], tuple[str, ...]], list] = {}
    for subscription in subscriptions:
        if not subscription.notify_enabled:
            continue
        key = (
            tuple(sorted(subscription.cities)),
            tuple(sorted(subscription.categories)),
        )
        grouped.setdefault(key, []).append(subscription)

    sent_total = 0
    for (cities, categories), subscribers in grouped.items():
        cutoffs = [
            subscription.updated_at or subscription.created_at
            for subscription in subscribers
            if subscription.updated_at or subscription.created_at
        ]
        earliest_cutoff = min(cutoffs) if cutoffs else None
        try:
            page = await api_client.get_events(
                EventQuery(
                    cities=list(cities),
                    categories=list(categories),
                    date_from=today_iso(),
                    first_seen_after=earliest_cutoff,
                    page=1,
                    page_size=60,
                    sort_by="date_asc",
                )
            )
        except Exception as error:
            logger.warning(
                "Cannot poll events for filters %s/%s: %s", cities, categories, error
            )
            continue

        for subscription in subscribers:
            # At most one new-events message per user per day.
            already_sent = await database.interactions_today(
                subscription.chat_id, "new_events_digest_sent"
            )
            if already_sent:
                continue

            seen = await database.seen_identities(subscription.chat_id)
            cutoff = subscription.updated_at or subscription.created_at
            fresh = [
                event
                for event in page.items
                if event_identity(event.id) not in seen
                and (
                    event.starts_at is None
                    or (days_until(event.starts_at) or 0) >= 0
                )
                and is_new_since(event.first_seen_at, cutoff)
            ]
            if not fresh:
                continue

            limit = max(1, min(settings.max_notifications_per_tick, 24))
            batch = fresh[:limit]
            try:
                delivered = await _send_new_events_batch(
                    bot,
                    subscription,
                    batch,
                    bot_username=bot_username,
                )
                if delivered:
                    sent_total += 1
            except Exception as error:
                logger.warning(
                    "Cannot send new events batch to %s: %s",
                    subscription.chat_id,
                    error,
                )
            await asyncio.sleep(0.05)

    return sent_total


def _next_digest_time(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    target = now.replace(
        hour=max(0, min(_effective_digest_hour_utc(), 23)),
        minute=0,
        second=0,
        microsecond=0,
    )
    if target <= now:
        target += timedelta(days=1)
    return target


async def send_digests(bot: Bot, bot_username: str = "") -> int:
    if is_quiet_hours():
        return 0

    subscriptions = await database.active_subscriptions()
    day = _today()
    sent = 0

    for subscription in subscriptions:
        if not subscription.digest_enabled or subscription.last_digest_day == day:
            continue
        try:
            page = await api_client.get_events(
                EventQuery(
                    cities=subscription.cities,
                    categories=subscription.categories,
                    date_from=today_iso(),
                    page=1,
                    page_size=5,
                    sort_by="date_asc",
                )
            )
        except Exception as error:
            logger.warning("Cannot build digest for %s: %s", subscription.chat_id, error)
            continue
        if not page.items:
            continue

        events = page.items
        tracked_urls = {
            event.id: event_click_url(
                subscription.chat_id, event.id, event.source_url
            )
            for event in events
        }
        display_events = [
            event.model_copy(update={"source_url": tracked_urls.get(event.id)})
            for event in events
        ]
        partner, partner_url = await _find_partner(
            subscription.chat_id,
            placement="digest",
            cities=subscription.cities,
            categories=subscription.categories,
        )
        text = (
            "<b>📬 Дайджест Sporly</b>\n"
            f"{filters_summary(subscription.cities, subscription.categories)}\n"
            + "\n💡 ⭐ с номером — сохранить старт, «🌐 Открыть» — сайт "
            "организатора.\n"
            "\n"
            + "\n\n".join(
                format_digest_event(event, index)
                for index, event in enumerate(display_events, start=1)
            )
        )
        if partner:
            text += (
                "\n\n➖➖➖\n"
                f"<b>{escape(partner.label)}</b> · "
                f"<b>{escape(clean_text(partner.title, 90))}</b>\n"
                f"{escape(clean_text(partner.text, 200))}"
            )

        tokens = await _event_tokens(events)
        favorites = await _favorite_ids(subscription.chat_id)
        rows: list[list[InlineKeyboardButton]] = []
        for index, event in enumerate(events, start=1):
            token = tokens[event.id]
            is_favorite = event.id in favorites
            row = [
                InlineKeyboardButton(
                    text=f"{'✅' if is_favorite else '⭐'} {index}",
                    callback_data=(
                        f"unfv:{token}" if is_favorite else f"fv:{token}"
                    ),
                )
            ]
            source_url = tracked_urls.get(event.id)
            if source_url and len(source_url) <= 240:
                row.append(
                    InlineKeyboardButton(
                        text=BUTTON_OPEN, url=source_url
                    )
                )
            rows.append(row)
        if partner and partner_url:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{partner.label} · {partner.title}"[:60],
                        url=partner_url,
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text=BUTTON_INTERESTS, callback_data="menu:sub"
                )
            ]
        )
        rows.append(
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")]
        )

        try:
            await bot.send_message(
                subscription.chat_id,
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                link_preview_options=NO_PREVIEW,
            )
            await database.mark_digest_sent(subscription.chat_id, day)
            await database.log_event(subscription.chat_id, "digest_sent")
            sent += 1
        except Exception as error:
            logger.warning("Cannot send digest to %s: %s", subscription.chat_id, error)
        await asyncio.sleep(0.05)

    return sent


def _favorite_to_event(favorite: Favorite) -> Event:
    return Event(
        id=favorite.event_id,
        title=favorite.title,
        starts_at=favorite.starts_at,
        date_text=favorite.date_text,
        source_url=favorite.source_url,
        city=favorite.city,
        region=favorite.region,
        category=favorite.category,
        registration_status=favorite.registration_status,
        registration_opens_at=favorite.registration_opens_at,
        registration_deadline=favorite.registration_deadline,
        source_name="Источник",
    )


def reminder_offset(days: int, sent_offsets: set[str]) -> int | None:
    """Return the closest reminder threshold that is still worth sending.

    If the bot was down for a while, only one reminder is sent: the most
    relevant one. All thresholds at or above the current number of days are
    then treated as sent so the user does not get a burst of stale reminders.
    """

    if days < 0:
        return None
    for offset in REMINDER_OFFSETS:
        if days <= offset and str(offset) not in sent_offsets:
            return offset
    return None


def registration_notice_kind(
    favorite: Favorite,
    today: date | None = None,
    *,
    previous_status: object = _UNSET,
) -> str | None:
    """Return which registration notice is due for a favorite, if any.

    ``previous_status`` is the status stored when the favorite was saved. When
    it transitions from a not-yet-open state to an open one, the notice is sent
    even if the source never published an explicit registration opening date.
    """

    sent = set(favorite.reminded_offsets)
    today = today or local_today()
    deadline_days = days_until(favorite.registration_deadline)
    status = (favorite.registration_status or "").casefold()

    if (
        REGISTRATION_START_OFFSET not in sent
        and status != "closed"
        and (deadline_days is None or deadline_days >= 0)
    ):
        opened_by_date = False
        if (
            (opens_at := parse_date(favorite.registration_opens_at)) is not None
            and opens_at <= today
        ):
            created_at = parse_date(favorite.created_at)
            # A favorite added after registration had already opened should
            # not trigger a stale "registration just started" message.
            opened_by_date = created_at is None or created_at <= opens_at

        opened_by_status = False
        if previous_status is not _UNSET:
            previous = (
                previous_status.casefold()
                if isinstance(previous_status, str)
                else ""
            )
            opened_by_status = (
                status in REGISTRATION_OPEN_STATUSES
                and previous not in REGISTRATION_OPEN_STATUSES
            )

        if opened_by_date or opened_by_status:
            return REGISTRATION_START_OFFSET

    if (
        REGISTRATION_END_OFFSET not in sent
        and deadline_days is not None
        and 0 <= deadline_days <= 1
    ):
        return REGISTRATION_END_OFFSET

    return None


def _registration_notice_line(kind: str, favorite: Favorite) -> str:
    if kind == REGISTRATION_START_OFFSET:
        return "🔔 Регистрация открыта"
    days = days_until(favorite.registration_deadline)
    if days == 0:
        return "⏳ Регистрация закрывается сегодня"
    return "⏳ Регистрация закрывается завтра"


def _favorite_payload(favorite: Favorite) -> dict[str, object]:
    return {
        "event_id": favorite.event_id,
        "title": favorite.title,
        "starts_at": favorite.starts_at,
        "date_text": favorite.date_text,
        "source_url": favorite.source_url,
        "city": favorite.city,
        "region": favorite.region,
        "category": favorite.category,
        "registration_status": favorite.registration_status,
        "registration_opens_at": favorite.registration_opens_at,
        "registration_deadline": favorite.registration_deadline,
    }


async def _refresh_favorite_states(
    favorites: list[Favorite],
) -> dict[tuple[int, str], Favorite]:
    """Re-read favorites from the catalog so later status changes are noticed."""

    if not favorites:
        return {}

    try:
        events = await api_client.get_events_by_ids(
            [favorite.event_id for favorite in favorites]
        )
    except Exception as error:
        logger.warning("Cannot refresh favorites from the catalog: %s", error)
        return {}

    by_id: dict[str, Event] = {}
    for event in events:
        by_id[event.id] = event
        by_id.setdefault(stable_event_id(event.id), event)

    refreshed: dict[tuple[int, str], Favorite] = {}
    for favorite in favorites:
        event = by_id.get(favorite.event_id) or by_id.get(
            stable_event_id(favorite.event_id)
        )
        if event is None:
            continue
        refreshed[(favorite.chat_id, favorite.event_id)] = replace(
            favorite,
            title=event.title or favorite.title,
            starts_at=event.starts_at or favorite.starts_at,
            date_text=event.date_text or favorite.date_text,
            source_url=event.source_url or favorite.source_url,
            city=event.city or favorite.city,
            region=event.region or favorite.region,
            category=event.category or favorite.category,
            registration_status=(
                event.registration_status or favorite.registration_status
            ),
            registration_opens_at=(
                event.registration_opens_at or favorite.registration_opens_at
            ),
            registration_deadline=(
                event.registration_deadline or favorite.registration_deadline
            ),
        )
    return refreshed


async def _persist_favorite_states(
    chat_id: int, favorites: list[Favorite]
) -> None:
    for favorite in favorites:
        try:
            await database.refresh_favorite(
                chat_id, _favorite_payload(favorite)
            )
        except Exception as error:
            logger.warning(
                "Cannot refresh favorite %s/%s: %s",
                chat_id,
                favorite.event_id,
                error,
            )


async def send_registration_notices(bot: Bot, bot_username: str = "") -> int:
    # Registration notices are never sent at night.
    if is_quiet_hours():
        return 0

    favorites = await database.all_favorites()
    if not favorites:
        return 0

    # Favorites keep the state that was current when the user saved them.
    # Registration often opens later, so compare against the live catalog.
    refreshed = await _refresh_favorite_states(favorites)

    reminders_cache: dict[int, bool] = {}
    due_by_chat: dict[int, list[tuple[Favorite, str]]] = {}
    chats: dict[int, list[Favorite]] = {}

    for favorite in favorites:
        if favorite.chat_id not in reminders_cache:
            reminders_cache[favorite.chat_id] = await database.reminders_enabled(
                favorite.chat_id
            )
        current = refreshed.get(
            (favorite.chat_id, favorite.event_id), favorite
        )
        chats.setdefault(favorite.chat_id, []).append(current)
        if not reminders_cache[favorite.chat_id]:
            continue
        kind = registration_notice_kind(
            current, previous_status=favorite.registration_status
        )
        if kind is None:
            continue
        due_by_chat.setdefault(favorite.chat_id, []).append((current, kind))

    sent = 0
    for chat_id, due in due_by_chat.items():
        events = [_favorite_to_event(favorite) for favorite, _ in due]
        tokens = await _event_tokens(events)
        rows: list[list[InlineKeyboardButton]] = []
        text_parts: list[str] = ["<b>📋 Регистрация в избранном</b>"]
        for index, (favorite, kind) in enumerate(due, start=1):
            text_parts.append(
                format_favorite(
                    favorite,
                    index=index,
                    bot_username=bot_username,
                    page=1,
                )
                + "\n"
                + _registration_notice_line(kind, favorite)
            )
            token = tokens[favorite.event_id]
            row = [
                InlineKeyboardButton(
                    text=f"✅ {index}", callback_data=f"unfv:{token}"
                )
            ]
            source_url = event_click_url(
                chat_id, favorite.event_id, favorite.source_url
            )
            if source_url and len(source_url) <= 240:
                row.append(InlineKeyboardButton(text=BUTTON_OPEN, url=source_url))
            rows.append(row)

        text_parts.append(
            "💡 «Подробнее →» откроет карточку, ✅ — убрать из избранного."
        )
        rows.append(
            [InlineKeyboardButton(text=BUTTON_INTERESTS, callback_data="menu:sub")]
        )
        rows.append(
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")]
        )

        try:
            await bot.send_message(
                chat_id,
                "\n\n".join(text_parts),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                link_preview_options=NO_PREVIEW,
            )
            for favorite, kind in due:
                await database.mark_reminded(
                    chat_id, favorite.event_id, kind
                )
                await database.log_event(
                    chat_id, "registration_notice_sent", favorite.event_id
                )
            await database.log_event(
                chat_id, "registration_notices_sent", str(len(due))
            )
            # Only advance the snapshot after delivery: if sending fails, the
            # upcoming -> open transition must still be visible on the next run.
            await _persist_favorite_states(chat_id, chats.get(chat_id, []))
            sent += 1
        except Exception as error:
            logger.warning(
                "Cannot send registration notices to %s: %s", chat_id, error
            )
        await asyncio.sleep(0.05)

    for chat_id, chat_favorites in chats.items():
        if chat_id in due_by_chat:
            continue
        await _persist_favorite_states(chat_id, chat_favorites)

    return sent


async def send_reminders(bot: Bot, bot_username: str = "") -> int:
    # Reminders are never sent at night.
    if is_quiet_hours():
        return 0

    favorites = await database.all_favorites()
    reminders_cache: dict[int, bool] = {}
    due_by_chat: dict[int, list[Favorite]] = {}

    for favorite in favorites:
        if favorite.chat_id not in reminders_cache:
            reminders_cache[favorite.chat_id] = await database.reminders_enabled(
                favorite.chat_id
            )
        if not reminders_cache[favorite.chat_id]:
            continue
        days = days_until(favorite.starts_at)
        if days is None or days < 0:
            continue
        if reminder_offset(days, set(favorite.reminded_offsets)) is None:
            continue
        due_by_chat.setdefault(favorite.chat_id, []).append(favorite)

    sent = 0
    for chat_id, due in due_by_chat.items():
        # One reminder message per user per day, even with several favorites.
        if await database.interactions_today(chat_id, "reminders_digest_sent"):
            continue

        events = [_favorite_to_event(favorite) for favorite in due]
        tokens = await _event_tokens(events)
        rows: list[list[InlineKeyboardButton]] = []
        text_parts: list[str] = ["<b>⏰ Напоминания об избранном</b>"]
        for index, favorite in enumerate(due, start=1):
            text_parts.append(
                format_favorite(
                    favorite,
                    index=index,
                    bot_username=bot_username,
                    page=1,
                )
            )
            token = tokens[favorite.event_id]
            row = [
                InlineKeyboardButton(
                    text=f"✅ {index}", callback_data=f"unfv:{token}"
                )
            ]
            source_url = event_click_url(
                chat_id, favorite.event_id, favorite.source_url
            )
            if source_url and len(source_url) <= 240:
                row.append(InlineKeyboardButton(text=BUTTON_OPEN, url=source_url))
            rows.append(row)

        text_parts.append(
            "💡 «Подробнее →» откроет карточку, ✅ — убрать из избранного."
        )
        rows.append(
            [InlineKeyboardButton(text=BUTTON_INTERESTS, callback_data="menu:sub")]
        )
        rows.append(
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")]
        )

        try:
            await bot.send_message(
                chat_id,
                "\n\n".join(text_parts),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                link_preview_options=NO_PREVIEW,
            )
            for favorite in due:
                days = days_until(favorite.starts_at) or 0
                for offset in REMINDER_OFFSETS:
                    if offset >= days:
                        await database.mark_reminded(
                            chat_id, favorite.event_id, str(offset)
                        )
                await database.log_event(
                    chat_id, "reminder_sent", favorite.event_id
                )
            await database.log_event(
                chat_id, "reminders_digest_sent", str(len(due))
            )
            sent += 1
        except Exception as error:
            logger.warning(
                "Cannot send reminders to %s: %s", chat_id, error
            )
        await asyncio.sleep(0.05)
    return sent


async def notification_loop(bot: Bot, bot_username: str = "") -> None:
    await asyncio.sleep(5)
    while True:
        if is_quiet_hours():
            await asyncio.sleep(seconds_until_quiet_end())
            continue
        try:
            sent = await check_new_events(bot, bot_username)
            if sent:
                logger.info("Sent %s new-events digests", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification loop failed")
        await asyncio.sleep(max(settings.poll_interval_seconds, 60))


async def digest_loop(bot: Bot, bot_username: str = "") -> None:
    while True:
        target = _next_digest_time()
        delay = max((target - datetime.now(timezone.utc)).total_seconds(), 1)
        logger.info("Next digest at %s UTC", target.isoformat())
        try:
            await asyncio.sleep(delay)
            sent = await send_digests(bot, bot_username)
            logger.info("Sent %s digests", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Digest loop failed")
            await asyncio.sleep(300)


async def reminder_loop(bot: Bot, bot_username: str = "") -> None:
    await asyncio.sleep(10)
    while True:
        if is_quiet_hours():
            await asyncio.sleep(seconds_until_quiet_end())
            continue
        try:
            sent = await send_reminders(bot, bot_username)
            if sent:
                logger.info("Sent %s reminders", sent)
            registration_sent = await send_registration_notices(bot, bot_username)
            if registration_sent:
                logger.info("Sent %s registration notices", registration_sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder loop failed")
        await asyncio.sleep(max(settings.reminder_check_interval_seconds, 300))
