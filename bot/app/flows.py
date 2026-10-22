from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from html import escape
import json
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from app.api_client import Event, EventQuery, api_client, today_iso
from app.context import database, partner_registry, search_sessions
from app.formatting import (
    clean_text,
    filters_summary,
    format_event_card,
    format_event_details,
    format_event_list,
    format_favorite,
    pick_image,
)
from app.links import event_click_url, share_url
from app.hints import (
    HINT_FAVORITE,
    HINT_LIST_NAV,
    HINT_OPEN_SITE,
    HINT_TAP_DETAIL,
)
from app.keyboards import (
    BUTTON_FIND,
    BUTTON_HOME,
    BUTTON_SHOW_SOON,
    event_detail_keyboard,
    favorites_list_keyboard,
    interests_saved_keyboard,
    no_results_keyboard,
    notification_settings_keyboard,
    search_list_keyboard,
    single_event_keyboard,
    subscription_keyboard,
)
from app.partners import Partner
from app.sessions import SearchSession
from app.storage import Subscription
from app.text import (
    EVENT_COLORS,
    MOSCOW_TZ,
    REMINDER_OFFSETS,
    days_until,
    pluralize,
)


logger = logging.getLogger(__name__)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
PAGE_SIZE = 4
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
SEASON_ASSETS = {
    "winter": ASSETS_DIR / "season-winter.gif",
    "spring": ASSETS_DIR / "season-spring.gif",
    "summer": ASSETS_DIR / "season-summer.gif",
    "autumn": ASSETS_DIR / "season-autumn.gif",
}
_SEASON_FILE_IDS: dict[str, str] = {}


def current_season() -> str:
    from app.config import settings

    override = settings.season_override.strip().lower()
    if override in SEASON_ASSETS:
        return override
    month = datetime.now(MOSCOW_TZ).month
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _season_media(season: str):
    return _SEASON_FILE_IDS.get(season) or FSInputFile(SEASON_ASSETS[season])


def _remember_season(season: str, message: Message | None) -> None:
    animation = getattr(message, "animation", None) if message else None
    file_id = getattr(animation, "file_id", None)
    if file_id:
        _SEASON_FILE_IDS[season] = file_id


# --------------------------------------------------------------------- screens


async def _delete(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        pass


async def _send_screen(
    bot: Bot,
    chat_id: int,
    *,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    photo=None,
    animation=None,
    track: bool = True,
) -> Message | None:
    sent: Message | None = None

    if animation:
        try:
            sent = await bot.send_animation(
                chat_id,
                animation=animation,
                caption=text,
                reply_markup=markup,
            )
        except Exception as error:
            logger.info("Cannot send animation: %s", error)

    if sent is None and photo:
        try:
            sent = await bot.send_photo(
                chat_id,
                photo=photo,
                caption=text,
                reply_markup=markup,
            )
        except Exception as error:
            logger.info("Cannot send photo: %s", error)

    if sent is None:
        try:
            sent = await bot.send_message(
                chat_id,
                text,
                reply_markup=markup,
                link_preview_options=NO_PREVIEW,
            )
        except Exception:
            logger.exception("Cannot send screen to %s", chat_id)
            return None

    if track and sent is not None:
        await database.set_ui_message(chat_id, sent.message_id)
    return sent


async def _edit_screen(
    bot: Bot,
    chat_id: int,
    message: Message | None,
    *,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    photo=None,
    animation=None,
) -> Message | None:
    """Edit the current screen in place, switching between text and media.

    Telegram cannot convert a text message into media (or vice versa), so those
    transitions delete the old message and send a new one.
    """

    if message is None:
        return await _send_screen(
            bot,
            chat_id,
            text=text,
            markup=markup,
            photo=photo,
            animation=animation,
        )

    current = (
        "animation"
        if getattr(message, "animation", None)
        else "photo"
        if getattr(message, "photo", None)
        else "text"
    )
    desired = "animation" if animation else "photo" if photo else "text"

    if current == desired and desired in {"animation", "photo"}:
        try:
            await message.edit_caption(caption=text, reply_markup=markup)
            return message
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                return message
            logger.info("Cannot edit caption: %s", error)
        except Exception as error:
            logger.info("Cannot edit caption: %s", error)
    elif current == "text" and desired == "text":
        try:
            await message.edit_text(
                text,
                reply_markup=markup,
                link_preview_options=NO_PREVIEW,
            )
            return message
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                return message
            logger.info("Cannot edit message: %s", error)
        except Exception as error:
            logger.info("Cannot edit message: %s", error)

    await _delete(message)
    return await _send_screen(
        bot,
        chat_id,
        text=text,
        markup=markup,
        photo=photo,
        animation=animation,
    )


async def delete_current_screen(message: Message | None) -> None:
    await _delete(message)


async def show_screen(
    bot: Bot,
    chat_id: int,
    message: Message | None,
    *,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    return await _edit_screen(bot, chat_id, message, text=text, markup=markup)


# ---------------------------------------------------------------------- search


async def _find_partner(
    chat_id: int,
    *,
    placement: str,
    cities: list[str] | None = None,
    categories: list[str] | None = None,
    query: str | None = None,
) -> tuple[Partner | None, str | None]:
    partner = await partner_registry.choose(
        chat_id,
        placement=placement,
        cities=cities,
        categories=categories,
        query=query,
    )
    if partner is None:
        return None, None
    return partner, partner_registry.tracked_url(partner, chat_id)


async def _event_tokens(events: list[Event]) -> dict[str, str]:
    await database.remember_events([event.ref_payload() for event in events])
    return {event.id: database.event_token(event.id) for event in events}


async def _favorite_ids(chat_id: int) -> set[str]:
    return {favorite.event_id for favorite in await database.favorites(chat_id)}


def _session_summary(session: SearchSession) -> str:
    summary = filters_summary(session.cities, session.categories)
    if session.query:
        summary = f"🔎 «{escape(clean_text(session.query, 50))}» · {summary}"
    return summary


async def render_search_page(
    bot: Bot,
    chat_id: int,
    session: SearchSession,
    *,
    page: int = 1,
    message: Message | None = None,
    bot_username: str = "",
    notify: bool = False,
) -> Message | None:
    try:
        result = await api_client.get_events(
            EventQuery(
                query=session.query,
                cities=session.cities,
                categories=session.categories,
                date_from=today_iso(),
                page=max(page, 1),
                page_size=PAGE_SIZE,
                sort_by="date_asc",
            )
        )
    except Exception as error:
        logger.exception("Search failed: %s", error)
        return await _edit_screen(
            bot,
            chat_id,
            message,
            text=(
                "😔 <b>Каталог временно недоступен</b>\n\n"
                "Попробуйте ещё раз через минуту.\n"
                "💡 Можно вернуться на главную или посмотреть сохранённое "
                "в «⭐ Избранном»."
            ),
            markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=BUTTON_FIND, callback_data="menu:find"
                        ),
                        InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home"),
                    ]
                ]
            ),
        )

    session.page = result.page
    session.total = result.total
    session.total_pages = max(result.total_pages, 1)

    if not result.items:
        return await _edit_screen(
            bot,
            chat_id,
            message,
            text=(
                "<b>Ничего не нашлось</b>\n\n"
                + _session_summary(session)
                + "\n\n"
                "Что попробовать:\n"
                "🔍 изменить запрос или выбрать другой регион,\n"
                "🎯 проверить «Мои интересы»,\n"
                "🌍 посмотреть все старты без фильтров."
            ),
            markup=no_results_keyboard(),
        )

    await _event_tokens(result.items)
    partner, partner_url = await _find_partner(
        chat_id,
        placement="search",
        cities=session.cities,
        categories=session.categories,
        query=session.query,
    )
    display_events = [
        event.model_copy(
            update={
                "source_url": event_click_url(
                    chat_id, event.id, event.source_url
                )
            }
        )
        for event in result.items
    ]
    text = format_event_list(
        display_events,
        total=result.total,
        page=result.page,
        total_pages=result.total_pages,
        filters=_session_summary(session),
        page_size=PAGE_SIZE,
        bot_username=bot_username,
        session_id=session.id,
    )
    markup = search_list_keyboard(
        session_id=session.id,
        page=result.page,
        total_pages=result.total_pages,
        partner=partner,
        partner_url=partner_url,
    )

    if notify:
        await database.log_event(
            chat_id,
            "search",
            json.dumps(
                {
                    "query": session.query or "",
                    "cities": session.cities,
                    "categories": session.categories,
                },
                ensure_ascii=False,
            ),
        )

    season = current_season()
    sent = await _edit_screen(
        bot,
        chat_id,
        message,
        text=text,
        markup=markup,
        animation=_season_media(season),
    )
    _remember_season(season, sent)
    return sent


async def start_search(
    bot: Bot,
    chat_id: int,
    *,
    query: str | None = None,
    cities: list[str] | None = None,
    categories: list[str] | None = None,
    bot_username: str = "",
) -> Message | None:
    session = search_sessions.create(
        chat_id,
        query=query,
        cities=cities,
        categories=categories,
    )
    return await render_search_page(
        bot,
        chat_id,
        session,
        page=1,
        bot_username=bot_username,
        notify=True,
    )


async def start_nearest(
    bot: Bot,
    chat_id: int,
    *,
    bot_username: str = "",
) -> Message | None:
    subscription = await database.get_subscription(chat_id)
    return await start_search(
        bot,
        chat_id,
        cities=subscription.cities if subscription else None,
        categories=subscription.categories if subscription else None,
        bot_username=bot_username,
    )


async def move_search(
    bot: Bot,
    chat_id: int,
    session_id: str,
    direction: str,
    message: Message | None,
    *,
    bot_username: str = "",
) -> str | None:
    session = search_sessions.get(session_id)
    if session is None or session.chat_id != chat_id:
        return "Выдача устарела, запустите поиск заново"

    if direction == "next":
        target = session.page + 1
        if target > session.total_pages:
            return "Это последняя страница"
    elif direction == "prev":
        target = session.page - 1
        if target < 1:
            return "Это первая страница"
    else:
        target = session.page

    await render_search_page(
        bot,
        chat_id,
        session,
        page=target,
        message=message,
        bot_username=bot_username,
    )
    return None


# ------------------------------------------------------------------ event card


async def show_event_detail(
    bot: Bot,
    chat_id: int,
    token: str,
    *,
    kind: str,
    page: int,
    index: int,
    session_id: str = "",
    message: Message | None = None,
    bot_username: str = "",
) -> Message | None:
    payload = await database.get_event_by_token(token)
    if payload is None:
        return await _edit_screen(
            bot,
            chat_id,
            message,
            text=(
                "Эта карточка устарела.\n\n"
                "💡 Нажмите «🔍 Найти старт» и откройте её заново."
            ),
            markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=BUTTON_FIND, callback_data="menu:find"
                        ),
                        InlineKeyboardButton(
                            text=BUTTON_HOME, callback_data="menu:home"
                        ),
                    ]
                ]
            ),
        )

    event = event_from_payload(payload)
    await database.remember_events([event.ref_payload()])
    is_favorite = await database.is_favorite(chat_id, event.id)
    marker = EVENT_COLORS[index % len(EVENT_COLORS)]
    text = format_event_details(event, marker)
    back_callback = (
        f"back:s:{session_id}:{page}" if kind == "s" else f"back:f:{page}"
    )
    back_text = "⬅️ К списку" if kind == "s" else "⬅️ К избранному"
    markup = event_detail_keyboard(
        token=token,
        source_url=event_click_url(chat_id, event.id, event.source_url),
        is_favorite=is_favorite,
        share_url_value=share_url(bot_username, token, event.title),
        back_callback=back_callback,
        back_text=back_text,
    )
    return await _edit_screen(
        bot, chat_id, message, text=text, markup=markup
    )


async def back_to_search(
    bot: Bot,
    chat_id: int,
    session_id: str,
    page: int,
    message: Message | None,
    *,
    bot_username: str = "",
) -> Message | None:
    session = search_sessions.get(session_id)
    if session is None or session.chat_id != chat_id:
        return await start_nearest(bot, chat_id, bot_username=bot_username)
    return await render_search_page(
        bot,
        chat_id,
        session,
        page=page,
        message=message,
        bot_username=bot_username,
    )


async def back_to_favorites(
    bot: Bot,
    chat_id: int,
    page: int,
    message: Message | None,
    *,
    bot_username: str = "",
) -> Message | None:
    return await show_favorites(
        bot,
        chat_id,
        page=page,
        message=message,
        bot_username=bot_username,
    )


# ------------------------------------------------------------------ favorites


FAVORITES_PAGE_SIZE = 5


async def show_favorites(
    bot: Bot,
    chat_id: int,
    *,
    page: int = 1,
    message: Message | None = None,
    bot_username: str = "",
) -> Message | None:
    favorites = await database.favorites(chat_id)
    if not favorites:
        return await _edit_screen(
            bot,
            chat_id,
            message,
            text=(
                "<b>⭐ Избранное</b>\n\n"
                "Здесь будут старты, которые вы сохранили.\n\n"
                "<b>Как добавить:</b>\n"
                "1. Откройте «🔍 Найти старт» или «🔥 Ближайшие».\n"
                "2. Нажмите «Подробнее →» под стартом.\n"
                "3. Нажмите «⭐ В избранное».\n\n"
                "Бот напомнит за 7, 3 и 1 день до старта и в день старта."
            ),
            markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=BUTTON_FIND, callback_data="menu:find"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=BUTTON_SHOW_SOON, callback_data="menu:soon"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=BUTTON_HOME, callback_data="menu:home"
                        )
                    ],
                ]
            ),
        )

    total_pages = max(
        (len(favorites) + FAVORITES_PAGE_SIZE - 1) // FAVORITES_PAGE_SIZE, 1
    )
    page = min(max(page, 1), total_pages)
    start = (page - 1) * FAVORITES_PAGE_SIZE
    visible = favorites[start : start + FAVORITES_PAGE_SIZE]

    payloads = [
        {
            "id": favorite.event_id,
            "event_id": favorite.event_id,
            "title": favorite.title,
            "starts_at": favorite.starts_at,
            "date_text": favorite.date_text,
            "source_url": favorite.source_url,
            "city": favorite.city,
            "region": favorite.region,
            "category": favorite.category,
        }
        for favorite in visible
    ]
    await database.remember_events(payloads)
    tokens = {
        favorite.event_id: database.event_token(favorite.event_id)
        for favorite in visible
    }

    display_favorites = [
        replace(
            favorite,
            source_url=event_click_url(
                chat_id, favorite.event_id, favorite.source_url
            ),
        )
        for favorite in visible
    ]
    text = f"<b>⭐ Избранное</b> · {len(favorites)}\n\n"
    text += "\n\n".join(
        format_favorite(
            favorite,
            index=start + index,
            bot_username=bot_username,
            page=page,
        )
        for index, favorite in enumerate(display_favorites, start=1)
    )
    text += "\n\nНапомним за 7, 3 и 1 день до старта."
    text += "\n" + HINT_TAP_DETAIL
    if total_pages > 1:
        text += "\n" + HINT_LIST_NAV

    markup = favorites_list_keyboard(
        page=page,
        total_pages=total_pages,
    )
    season = current_season()
    sent = await _edit_screen(
        bot,
        chat_id,
        message,
        text=text,
        markup=markup,
        animation=_season_media(season),
    )
    _remember_season(season, sent)
    return sent


# ----------------------------------------------------------------- subscriptions


async def save_interests(
    chat_id: int,
    *,
    cities: list[str],
    categories: list[str],
) -> Subscription:
    await database.ensure_user(chat_id)
    existing = await database.get_subscription(chat_id)
    return await database.save_subscription(
        chat_id,
        cities=cities,
        categories=categories,
        notify_enabled=existing.notify_enabled if existing else True,
        digest_enabled=existing.digest_enabled if existing else False,
    )


async def show_interests_saved(
    bot: Bot,
    chat_id: int,
    subscription: Subscription,
) -> Message | None:
    text = (
        "<b>✅ Готово — подборка сохранена</b>\n\n"
        f"{filters_summary(subscription.cities, subscription.categories)}\n\n"
        "<b>Куда дальше:</b>\n"
        "🔥 «Смотреть ближайшие» — старты по этой подборке\n"
        "🎯 «Мои интересы» — изменить фильтры и уведомления\n"
        "🔍 «Найти старт» — поиск вручную\n\n"
        "Новые подходящие старты пришлём автоматически."
    )
    return await _send_screen(
        bot,
        chat_id,
        text=text,
        markup=interests_saved_keyboard(),
    )


async def finish_subscription(
    bot: Bot,
    chat_id: int,
    *,
    cities: list[str],
    categories: list[str],
    notify_enabled: bool | None = None,
    digest_enabled: bool | None = None,
    bot_username: str = "",
    delete_message: Message | None = None,
) -> Message | None:
    await database.ensure_user(chat_id)
    existing = await database.get_subscription(chat_id)
    subscription = await database.save_subscription(
        chat_id,
        cities=cities,
        categories=categories,
        notify_enabled=(
            existing.notify_enabled
            if existing and notify_enabled is None
            else bool(notify_enabled)
        ),
        digest_enabled=(
            existing.digest_enabled
            if existing and digest_enabled is None
            else bool(digest_enabled)
        ),
    )
    await database.log_event(
        chat_id,
        "subscription_saved",
        f"{','.join(cities)}|{','.join(categories)}",
    )

    current: list[Event] = []
    total = 0
    baseline_ok = True
    try:
        page = await api_client.get_events(
            EventQuery(
                cities=cities,
                categories=categories,
                date_from=today_iso(),
                page=1,
                page_size=60,
            )
        )
        current = page.items
        total = page.total
        if current:
            await database.mark_seen(chat_id, [event.id for event in current])
    except Exception as error:
        baseline_ok = False
        logger.warning("Cannot baseline subscription: %s", error)

    if delete_message is not None:
        await _delete(delete_message)

    title = "Интересы обновлены" if existing else "Интересы сохранены"
    text = f"✅ <b>{title}</b>\n\n{filters_summary(cities, categories)}\n\n"
    if baseline_ok:
        text += (
            f"Сейчас подходит <b>{total}</b> "
            f"{pluralize(total, 'старт', 'старта', 'стартов')}. "
            "Пришлём, когда появятся новые.\n\n"
        )
    else:
        text += "Каталог сейчас недоступен, но подписка сохранена.\n\n"

    text += (
        "<b>Куда нажать:</b>\n"
        "🔥 «Смотреть ближайшие» — текущая подборка\n"
        "🔔 «Новые старты по фильтрам» — раз в день одним сообщением\n"
        "📬 «Дайджест» — раз в день утром\n"
        "⏰ «Напоминания об избранном» — за 7, 3 и 1 день\n"
        "✏️ «Изменить интересы» — поменять фильтры\n\n"
        "🌙 Ночью уведомления не приходят."
    )

    reminders_enabled = await database.reminders_enabled(chat_id)
    rows = subscription_keyboard(
        subscription, reminders_enabled=reminders_enabled
    ).inline_keyboard
    return await _send_screen(
        bot,
        chat_id,
        text=text,
        markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def show_notifications(
    bot: Bot,
    chat_id: int,
    *,
    message: Message | None = None,
) -> Message | None:
    subscription = await database.get_subscription(chat_id)
    reminders_enabled = await database.reminders_enabled(chat_id)
    has_subscription = subscription is not None

    text = (
        "<b>🔔 Уведомления</b>\n\n"
        "Три независимые настройки — включите только то, что нужно.\n\n"
        "🔔 <b>Новые старты по фильтрам</b> — раз в день одним сообщением, "
        "когда появляются старты под «🎯 Мои интересы».\n"
        "📬 <b>Дайджест</b> — раз в день утром: подборка ближайших стартов.\n"
        "⏰ <b>Напоминания об избранном</b> — за 7, 3 и 1 день до старта "
        "и в день старта. Работают отдельно от подписки.\n\n"
        "🌙 Ночью бот не присылает уведомления.\n\n"
    )
    if subscription is not None:
        text += (
            "Сейчас: "
            f"🔔 {'вкл' if subscription.notify_enabled else 'выкл'} · "
            f"📬 {'вкл' if subscription.digest_enabled else 'выкл'} · "
            f"⏰ {'вкл' if reminders_enabled else 'выкл'}\n\n"
            "Фильтры для первых двух настраиваются в «🎯 Мои интересы»."
        )
    else:
        text += (
            "Сейчас: ⏰ напоминания "
            f"<b>{'включены' if reminders_enabled else 'выключены'}</b>.\n\n"
            "Чтобы присылать новые старты и дайджест, сначала настройте "
            "интересы."
        )

    return await _edit_screen(
        bot,
        chat_id,
        message,
        text=text,
        markup=notification_settings_keyboard(
            has_subscription=has_subscription,
            notify_enabled=(
                subscription.notify_enabled if subscription else False
            ),
            digest_enabled=(
                subscription.digest_enabled if subscription else False
            ),
            reminders_enabled=reminders_enabled,
        ),
    )


async def show_subscription(
    bot: Bot,
    chat_id: int,
    *,
    message: Message | None = None,
    bot_username: str = "",
) -> Message | None:
    subscription = await database.get_subscription(chat_id)
    reminders_enabled = await database.reminders_enabled(chat_id)
    if subscription is None:
        return await _edit_screen(
            bot,
            chat_id,
            message,
            text=(
                "<b>🎯 Мои интересы</b>\n\n"
                "Здесь вы выбираете, какие старты показывать в «🔥 Ближайших» "
                "и присылать в уведомлениях.\n\n"
                "<b>Как настроить:</b>\n"
                "1. Нажмите «🎯 Настроить интересы».\n"
                "2. Отметьте виды спорта — можно несколько.\n"
                "3. Выберите регион или оставьте «🌍 Вся Россия».\n\n"
                "⏰ Напоминания об избранном работают отдельно от подписки — "
                "их можно включить или выключить ниже.\n\n"
                "Это бесплатно, изменить можно в любой момент."
            ),
            markup=notification_settings_keyboard(
                has_subscription=False,
                reminders_enabled=reminders_enabled,
            ),
        )

    total: int | None = None
    try:
        page = await api_client.get_events(
            EventQuery(
                cities=subscription.cities,
                categories=subscription.categories,
                date_from=today_iso(),
                page=1,
                page_size=1,
            )
        )
        total = page.total
    except Exception:
        pass

    text = (
        "<b>🎯 Мои интересы</b>\n\n"
        f"{filters_summary(subscription.cities, subscription.categories)}\n"
    )
    if total is not None:
        text += (
            f"\nПодходит сейчас: <b>{total}</b> "
            f"{pluralize(total, 'старт', 'старта', 'стартов')}.\n"
        )
    text += (
        "\n<b>Что делают кнопки:</b>\n"
        "🔥 «Смотреть ближайшие» — показать подборку\n"
        "🔔 новые старты по фильтрам — раз в день одним сообщением\n"
        "📬 дайджест — раз в день утром\n"
        "⏰ напоминания об избранном — за 7, 3 и 1 день\n"
        "✏️ изменить — виды спорта и регионы\n"
        "🗑 удалить — отключить подписку, избранное останется\n\n"
        "🌙 Ночью уведомления не приходят."
    )

    return await _edit_screen(
        bot,
        chat_id,
        message,
        text=text,
        markup=subscription_keyboard(
            subscription, reminders_enabled=reminders_enabled
        ),
    )


# ------------------------------------------------------------------- one event


def event_from_payload(payload: dict) -> Event:
    return Event.model_validate(payload)


async def show_single_event(
    bot: Bot,
    chat_id: int,
    token: str,
    *,
    message: Message | None = None,
    bot_username: str = "",
    prefix: str = "",
    back_callback: str | None = None,
) -> Message | None:
    payload = await database.get_event_by_token(token)
    if payload is None:
        return await _edit_screen(
            bot,
            chat_id,
            message,
            text=(
                "Эта ссылка устарела.\n\n"
                "💡 Найдите старт заново через поиск — карточка откроется "
                "с актуальными деталями."
            ),
            markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=BUTTON_FIND, callback_data="menu:find"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=BUTTON_HOME, callback_data="menu:home"
                        )
                    ],
                ]
            ),
        )

    event = event_from_payload(payload)
    await database.remember_events([event.ref_payload()])
    is_favorite = await database.is_favorite(chat_id, event.id)
    text = (prefix + "\n\n" if prefix else "") + format_event_card(event)
    if not prefix:
        text += f"\n\n💡 ⭐ — напомним о старте · {HINT_OPEN_SITE}"
    markup = single_event_keyboard(
        token,
        event_click_url(chat_id, event.id, event.source_url),
        is_favorite,
        bot_username,
        event.title,
        back_callback=back_callback,
    )
    return await _edit_screen(
        bot,
        chat_id,
        message,
        text=text,
        markup=markup,
        photo=pick_image(event),
    )


async def send_event_card(
    bot: Bot,
    chat_id: int,
    event: Event,
    *,
    bot_username: str = "",
    prefix: str = "",
) -> Message | None:
    token = database.event_token(event.id)
    await database.remember_events([event.ref_payload()])
    is_favorite = await database.is_favorite(chat_id, event.id)
    text = (prefix + "\n\n" if prefix else "") + format_event_card(event)
    return await _send_screen(
        bot,
        chat_id,
        text=text,
        markup=single_event_keyboard(
            token,
            event_click_url(chat_id, event.id, event.source_url),
            is_favorite,
            bot_username,
            event.title,
        ),
        photo=pick_image(event),
        track=False,
    )


async def toggle_favorite_by_token(
    chat_id: int,
    token: str,
    *,
    add: bool,
) -> tuple[bool, str | None]:
    payload = await database.get_event_by_token(token)
    if payload is None:
        return False, None
    event = event_from_payload(payload)
    if add:
        await database.add_favorite(chat_id, event.ref_payload())
        days = days_until(event.starts_at)
        if days is not None:
            for offset in REMINDER_OFFSETS:
                if offset > days:
                    await database.mark_reminded(chat_id, event.id, str(offset))
        await database.log_event(chat_id, "favorite_add", event.id)
        return True, event.title
    await database.remove_favorite(chat_id, event.id)
    await database.log_event(chat_id, "favorite_remove", event.id)
    return True, event.title


# --------------------------------------------------------------------- partners


async def show_partners_info(
    bot: Bot,
    chat_id: int,
    *,
    message: Message | None = None,
) -> Message | None:
    from app.config import settings

    overview = await database.overview(days=30)
    text = (
        "<b>🤝 Реклама в Sporly</b>\n\n"
        "В боте ищут конкретные старты: забеги, велогонки, лыжные марафоны, "
        "триатлон и другие события. Партнёрские карточки показываются в "
        "поиске и в ежедневном дайджесте.\n\n"
        f"👥 Пользователей: <b>{overview['users_total']}</b>\n"
        f"🎯 Активных подписок: <b>{overview['subscriptions']}</b>\n\n"
        "Таргетинг — по виду спорта, региону и поисковому запросу.\n"
        f"Связаться: {escape(settings.partner_contact)}\n\n"
        "💡 Нажмите «✍️ Написать», чтобы обсудить размещение. "
        "«🏠 Домой» вернёт в меню."
    )
    contact = settings.partner_contact.lstrip("@")
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Написать",
                    url=f"https://t.me/{contact}",
                )
            ],
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")],
        ]
    )
    return await _edit_screen(
        bot, chat_id, message, text=text, markup=markup
    )
