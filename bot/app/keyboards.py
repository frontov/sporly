from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.api_client import Event
from app.links import share_url
from app.partners import Partner
from app.storage import Subscription
from app.text import EVENT_COLORS


MENU_TEXTS = {
    "🔍 Найти старт": "menu:find",
    "🔥 Ближайшие": "menu:soon",
    "⭐ Избранное": "menu:fav",
    "🎯 Подписка": "menu:sub",
    "⚙️ Настройки": "menu:more",
}

# Reply keyboards stay on the client after a bot update. Map old button labels
# so users who never press /start again do not accidentally trigger a search
# for the button text.
LEGACY_MENU_ALIASES = {
    "найти": "menu:find",
    "поиск": "menu:find",
    "найти события": "menu:find",
    "найти старт": "menu:find",
    "найти старты": "menu:find",
    "поиск стартов": "menu:find",
    "ближайшие": "menu:soon",
    "ближайшие старты": "menu:soon",
    "скоро": "menu:soon",
    "избранное": "menu:fav",
    "избранные": "menu:fav",
    "мои избранные": "menu:fav",
    "подписка": "menu:sub",
    "моя подписка": "menu:sub",
    "мои события": "menu:sub",
    "мои интересы": "menu:sub",
    "интересы": "menu:sub",
    "уведомления": "menu:sub",
    "настройки": "menu:more",
    "еще": "menu:more",
    "ещё": "menu:more",
}


def _normalize_menu_text(text: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in text.casefold()
    )
    return " ".join(cleaned.split())


def menu_callback_for_text(text: str) -> str | None:
    exact = MENU_TEXTS.get(text)
    if exact:
        return exact
    return LEGACY_MENU_ALIASES.get(_normalize_menu_text(text))


def _url_button(text: str, url: str | None) -> InlineKeyboardButton | None:
    if not url or len(url) > 240:
        return None
    return InlineKeyboardButton(text=text, url=url)


def home_keyboard(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
            [
                InlineKeyboardButton(text="🔍 Найти старт", callback_data="menu:find"),
                InlineKeyboardButton(text="🔥 Ближайшие", callback_data="menu:soon"),
            ],
            [
                InlineKeyboardButton(text="🎯 Мои интересы", callback_data="menu:sub"),
                InlineKeyboardButton(text="⭐ Избранное", callback_data="menu:fav"),
            ],
            [InlineKeyboardButton(text="⚙️ Ещё", callback_data="menu:more")],
        ]
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_hub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏃 Вид спорта", callback_data="flow:new:search"),
                InlineKeyboardButton(text="📍 Регион", callback_data="flow:city_only"),
            ],
            [
                InlineKeyboardButton(text="🔥 Ближайшие", callback_data="menu:soon"),
                InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home"),
            ],
        ]
    )


def more_keyboard(
    bot_username: str,
    chat_id: int,
    site_url: str,
    *,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎁 Пригласить друга",
                    url=f"https://t.me/{bot_username}?start=ref_{chat_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="🤝 Реклама", callback_data="menu:partners"),
            _url_button("🌐 Сайт", site_url)
            or InlineKeyboardButton(text="🌐 Сайт", callback_data="menu:site"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="🎯 Мои интересы", callback_data="menu:sub"),
            InlineKeyboardButton(text="⭐ Избранное", callback_data="menu:fav"),
        ]
    )
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")]
        )
    rows.append([InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_list_keyboard(
    *,
    events: list[Event],
    tokens: dict[str, str],
    favorite_ids: set[str],
    bot_username: str,
    session_id: str,
    page: int,
    total_pages: int,
    can_subscribe: bool,
    partner: Partner | None,
    partner_url: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    offset = (page - 1) * 4
    for index, event in enumerate(events, start=1):
        token = tokens.get(event.id)
        if not token:
            continue
        marker = EVENT_COLORS[(index - 1) % len(EVENT_COLORS)]
        is_favorite = event.id in favorite_ids
        row = [
            InlineKeyboardButton(
                text=(
                    f"{marker} ✅ В избранном"
                    if is_favorite
                    else f"{marker} ⭐ В избранное"
                ),
                callback_data=(
                    f"unfv:{token}" if is_favorite else f"fv:{token}"
                ),
            )
        ]
        share = _url_button(
            f"{marker} 📤 Поделиться",
            share_url(bot_username, token, event.title),
        )
        if share:
            row.append(share)
        rows.append(row)

    if total_pages > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="‹", callback_data=f"page:{session_id}:prev"
                ),
                InlineKeyboardButton(
                    text=f"{page} / {total_pages}", callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="›", callback_data=f"page:{session_id}:next"
                ),
            ]
        )

    if can_subscribe:
        rows.append(
            [
                InlineKeyboardButton(text="🎛 Интересы", callback_data="menu:sub"),
                InlineKeyboardButton(
                    text="🔔 Следить", callback_data=f"subf:{session_id}"
                ),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎯 Настроить интересы", callback_data="menu:sub"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home")])

    if partner and partner_url:
        button = _url_button(
            f"{partner.label} · {partner.title}"[:60], partner_url
        )
        if button:
            rows.append([button])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def favorites_list_keyboard(
    *,
    favorites: list,
    tokens: dict[str, str],
    bot_username: str,
    page: int,
    total_pages: int,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    offset = (page - 1) * page_size
    actions: list[InlineKeyboardButton] = []
    shares: list[InlineKeyboardButton] = []
    for index, favorite in enumerate(favorites, start=offset):
        token = tokens.get(favorite.event_id)
        if not token:
            continue
        marker = EVENT_COLORS[index % len(EVENT_COLORS)]
        actions.append(
            InlineKeyboardButton(
                text=f"{marker} 💔 Убрать",
                callback_data=f"favrm:{index}:{token}",
            )
        )
        share = _url_button(
            f"{marker} 📤 Поделиться",
            share_url(bot_username, token, favorite.title),
        )
        if share:
            shares.append(share)
    if actions:
        rows.append(actions)
    if shares:
        rows.append(shares)

    if total_pages > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="‹", callback_data=f"favpg:{max(page - 1, 1)}"
                ),
                InlineKeyboardButton(
                    text=f"{page} / {total_pages}", callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="›", callback_data=f"favpg:{min(page + 1, total_pages)}"
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(text="🔍 Найти", callback_data="menu:find"),
            InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def single_event_keyboard(
    token: str,
    source_url: str | None,
    is_favorite: bool,
    bot_username: str,
    title: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="💔 Убрать из избранного" if is_favorite else "⭐ В избранное",
                callback_data=f"unfv:{token}" if is_favorite else f"fv:{token}",
            )
        ]
    ]
    actions: list[InlineKeyboardButton] = []
    source = _url_button("Открыть ↗", source_url)
    if source:
        actions.append(source)
    share = _url_button("📤 Поделиться", share_url(bot_username, token, title))
    if share:
        actions.append(share)
    if actions:
        rows.append(actions)
    rows.append([InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def no_results_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎛 Изменить фильтры", callback_data="menu:find")],
            [
                InlineKeyboardButton(text="🔥 Ближайшие", callback_data="menu:soon"),
                InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home"),
            ],
        ]
    )


def category_keyboard(
    categories: list[str],
    selected: set[str],
    *,
    page: int = 0,
    per_page: int = 10,
    skip: bool = False,
) -> InlineKeyboardMarkup:
    start = page * per_page
    visible = categories[start : start + per_page]
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for offset, category in enumerate(visible):
        mark = "✅ " if category in selected else ""
        pair.append(
            InlineKeyboardButton(
                text=f"{mark}{category}"[:60],
                callback_data=f"flow:cat:{start + offset}",
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    if len(categories) > per_page:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(text="‹", callback_data=f"flow:catpage:{page - 1}")
            )
        nav.append(InlineKeyboardButton(text=f"{page + 1}", callback_data="noop"))
        if start + per_page < len(categories):
            nav.append(
                InlineKeyboardButton(text="›", callback_data=f"flow:catpage:{page + 1}")
            )
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(text="Далее →", callback_data="flow:cat:done"),
            InlineKeyboardButton(text="Сбросить", callback_data="flow:cat:clear"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Пропустить" if skip else "Отмена",
                callback_data="flow:skip" if skip else "flow:cancel",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def city_keyboard(
    cities: list[str],
    selected: set[str],
    *,
    page: int = 0,
    per_page: int = 10,
    skip: bool = False,
) -> InlineKeyboardMarkup:
    start = page * per_page
    visible = cities[start : start + per_page]
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"✅ Подтвердить · {len(selected)}",
                callback_data="flow:city:done",
            )
        ]
    ]
    pair: list[InlineKeyboardButton] = []
    for offset, city in enumerate(visible):
        mark = "✅ " if city in selected else ""
        pair.append(
            InlineKeyboardButton(
                text=f"{mark}{city}"[:60],
                callback_data=f"flow:city:{start + offset}",
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    if len(cities) > per_page:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(text="‹", callback_data=f"flow:citypage:{page - 1}")
            )
        nav.append(InlineKeyboardButton(text=f"{page + 1}", callback_data="noop"))
        if start + per_page < len(cities):
            nav.append(
                InlineKeyboardButton(text="›", callback_data=f"flow:citypage:{page + 1}")
            )
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(text="🌍 Вся Россия", callback_data="flow:city:all"),
            InlineKeyboardButton(text="✍️ Другой город", callback_data="flow:city:other"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ К видам спорта", callback_data="flow:back"),
            InlineKeyboardButton(
                text="Пропустить" if skip else "Отмена",
                callback_data="flow:skip" if skip else "flow:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_keyboard(subscription: Subscription) -> InlineKeyboardMarkup:
    notify = "🔔 Уведомления: вкл" if subscription.notify_enabled else "🔕 Уведомления: выкл"
    digest = "📬 Дайджест: вкл" if subscription.digest_enabled else "📭 Дайджест: выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=notify, callback_data="sub:toggle_notify")],
            [InlineKeyboardButton(text=digest, callback_data="sub:toggle_digest")],
            [InlineKeyboardButton(text="✏️ Изменить интересы", callback_data="sub:edit")],
            [InlineKeyboardButton(text="🗑 Удалить интересы", callback_data="sub:delete")],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home")],
        ]
    )


def delete_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data="sub:delete_confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="sub:noop"),
            ]
        ]
    )
