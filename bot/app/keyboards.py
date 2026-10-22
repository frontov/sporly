from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.api_client import Event
from app.links import share_url
from app.partners import Partner
from app.storage import Subscription
from app.text import EVENT_COLORS


BUTTON_FIND = "🔍 Найти старт"
BUTTON_SOON = "🔥 Ближайшие"
BUTTON_INTERESTS = "🎯 Мои интересы"
BUTTON_FAVORITES = "⭐ Избранное"
BUTTON_MORE = "⚙️ Ещё"
BUTTON_HOME = "🏠 Домой"
BUTTON_HELP = "❓ Как пользоваться"
BUTTON_NOTIFICATIONS = "🔔 Уведомления"
BUTTON_SETUP_INTERESTS = "🎯 Настроить интересы"
BUTTON_ALL = "🌍 Все старты"
BUTTON_SHOW_SOON = "🔥 Смотреть ближайшие"
BUTTON_OPEN = "🌐 Открыть"
BUTTON_SHARE = "📤 Поделиться"
BUTTON_FAVORITE = "⭐ В избранное"
BUTTON_FAVORITED = "✅ В избранном"

MENU_TEXTS = {
    BUTTON_FIND: "menu:find",
    BUTTON_SOON: "menu:soon",
    BUTTON_FAVORITES: "menu:fav",
    BUTTON_INTERESTS: "menu:sub",
    BUTTON_MORE: "menu:more",
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
    "уведомления": "menu:notify",
    "настройки уведомлений": "menu:notify",
    "настройки": "menu:more",
    "еще": "menu:more",
    "ещё": "menu:more",
    "помощь": "menu:help",
    "справка": "menu:help",
    "как пользоваться": "menu:help",
    "как пользоваться ботом": "menu:help",
    "help": "menu:help",
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


def _favorite_button(token: str, is_favorite: bool) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=BUTTON_FAVORITED if is_favorite else BUTTON_FAVORITE,
        callback_data=f"unfv:{token}" if is_favorite else f"fv:{token}",
    )


def _event_action_row(
    source_url: str | None, share_url_value: str | None
) -> list[InlineKeyboardButton]:
    actions: list[InlineKeyboardButton] = []
    source = _url_button(BUTTON_OPEN, source_url)
    if source:
        actions.append(source)
    share = _url_button(BUTTON_SHARE, share_url_value)
    if share:
        actions.append(share)
    return actions


def home_keyboard(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
            [
                InlineKeyboardButton(text=BUTTON_FIND, callback_data="menu:find"),
                InlineKeyboardButton(text=BUTTON_SOON, callback_data="menu:soon"),
            ],
            [
                InlineKeyboardButton(text=BUTTON_INTERESTS, callback_data="menu:sub"),
                InlineKeyboardButton(text=BUTTON_FAVORITES, callback_data="menu:fav"),
            ],
            [InlineKeyboardButton(text=BUTTON_MORE, callback_data="menu:more")],
            [InlineKeyboardButton(text=BUTTON_HELP, callback_data="menu:help")],
        ]
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BUTTON_FIND, callback_data="menu:find"),
                InlineKeyboardButton(text=BUTTON_SOON, callback_data="menu:soon"),
            ],
            [
                InlineKeyboardButton(
                    text=BUTTON_INTERESTS, callback_data="menu:sub"
                ),
                InlineKeyboardButton(
                    text=BUTTON_FAVORITES, callback_data="menu:fav"
                ),
            ],
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")],
        ]
    )


def interests_saved_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_SHOW_SOON, callback_data="menu:soon"
                )
            ],
            [
                InlineKeyboardButton(
                    text=BUTTON_INTERESTS, callback_data="menu:sub"
                ),
                InlineKeyboardButton(
                    text=BUTTON_FIND, callback_data="menu:find"
                ),
            ],
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")],
        ]
    )


def search_hub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏃 Вид спорта", callback_data="flow:new:search"),
                InlineKeyboardButton(text="📍 Регион", callback_data="flow:city_only"),
            ],
            [
                InlineKeyboardButton(text=BUTTON_SOON, callback_data="menu:soon"),
                InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home"),
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
            InlineKeyboardButton(text=BUTTON_INTERESTS, callback_data="menu:sub"),
            InlineKeyboardButton(text=BUTTON_FAVORITES, callback_data="menu:fav"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=BUTTON_NOTIFICATIONS, callback_data="menu:notify"
            )
        ]
    )
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")]
        )
    rows.append(
        [InlineKeyboardButton(text=BUTTON_HELP, callback_data="menu:help")]
    )
    rows.append([InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_list_keyboard(
    *,
    session_id: str,
    page: int,
    total_pages: int,
    partner: Partner | None,
    partner_url: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if total_pages > 1:
        nav.extend(
            [
                InlineKeyboardButton(
                    text="👈", callback_data=f"page:{session_id}:prev"
                ),
                InlineKeyboardButton(
                    text=f"{page} / {total_pages}", callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="👉", callback_data=f"page:{session_id}:next"
                ),
            ]
        )
    if nav:
        rows.append(nav)

    if partner and partner_url:
        button = _url_button(
            f"{partner.label} · {partner.title}"[:60], partner_url
        )
        if button:
            rows.append([button])

    rows.append(
        [
            InlineKeyboardButton(text=BUTTON_FIND, callback_data="menu:find"),
            InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def favorites_list_keyboard(
    *,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if total_pages > 1:
        nav.extend(
            [
                InlineKeyboardButton(
                    text="👈", callback_data=f"favpg:{max(page - 1, 1)}"
                ),
                InlineKeyboardButton(
                    text=f"{page} / {total_pages}", callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="👉", callback_data=f"favpg:{min(page + 1, total_pages)}"
                ),
            ]
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(text=BUTTON_FIND, callback_data="menu:find"),
            InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_detail_keyboard(
    *,
    token: str,
    source_url: str | None,
    is_favorite: bool,
    share_url_value: str | None,
    back_callback: str,
    back_text: str = "⬅️ К списку",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [_favorite_button(token, is_favorite)]
    ]
    actions = _event_action_row(source_url, share_url_value)
    if actions:
        rows.append(actions)
    rows.append(
        [
            InlineKeyboardButton(text=back_text, callback_data=back_callback),
            InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def single_event_keyboard(
    token: str,
    source_url: str | None,
    is_favorite: bool,
    bot_username: str,
    title: str | None = None,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [_favorite_button(token, is_favorite)]
    ]
    actions = _event_action_row(
        source_url, share_url(bot_username, token, title)
    )
    if actions:
        rows.append(actions)
    if back_callback:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️ К списку", callback_data=back_callback
                ),
                InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home"),
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def no_results_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BUTTON_FIND, callback_data="menu:find"),
                InlineKeyboardButton(text=BUTTON_ALL, callback_data="menu:all"),
            ],
            [
                InlineKeyboardButton(text=BUTTON_SOON, callback_data="menu:soon"),
                InlineKeyboardButton(text=BUTTON_INTERESTS, callback_data="menu:sub"),
            ],
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")],
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
            InlineKeyboardButton(text="Сбросить", callback_data="flow:cat:clear"),
            InlineKeyboardButton(
                text="Пропустить" if skip else "Отмена",
                callback_data="flow:skip" if skip else "flow:cancel",
            ),
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="Далее →", callback_data="flow:cat:done")]
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
    rows: list[list[InlineKeyboardButton]] = []
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
            InlineKeyboardButton(text="⬅️ К видам спорта", callback_data="flow:back"),
            InlineKeyboardButton(text="✍️ Другой город", callback_data="flow:city:other"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="🌍 Вся Россия", callback_data="flow:city:all"),
            InlineKeyboardButton(
                text="Пропустить" if skip else "Отмена",
                callback_data="flow:skip" if skip else "flow:cancel",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"✅ Подтвердить · {len(selected)}",
                callback_data="flow:city:done",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _notification_toggle_rows(
    *,
    notify_enabled: bool,
    digest_enabled: bool,
    reminders_enabled: bool,
) -> list[list[InlineKeyboardButton]]:
    notify = (
        "🔔 Новые старты по фильтрам: вкл"
        if notify_enabled
        else "🔕 Новые старты по фильтрам: выкл"
    )
    digest = "📬 Дайджест: вкл" if digest_enabled else "📭 Дайджест: выкл"
    reminders = (
        "⏰ Напоминания об избранном: вкл"
        if reminders_enabled
        else "🔕 Напоминания об избранном: выкл"
    )
    return [
        [InlineKeyboardButton(text=notify, callback_data="sub:toggle_notify")],
        [InlineKeyboardButton(text=digest, callback_data="sub:toggle_digest")],
        [InlineKeyboardButton(text=reminders, callback_data="sub:toggle_reminders")],
    ]


def notification_settings_keyboard(
    *,
    has_subscription: bool,
    notify_enabled: bool = True,
    digest_enabled: bool = False,
    reminders_enabled: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_subscription:
        rows.extend(
            _notification_toggle_rows(
                notify_enabled=notify_enabled,
                digest_enabled=digest_enabled,
                reminders_enabled=reminders_enabled,
            )
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=BUTTON_INTERESTS, callback_data="menu:sub"
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text=BUTTON_SETUP_INTERESTS,
                    callback_data="flow:new:onboarding",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        "⏰ Напоминания об избранном: вкл"
                        if reminders_enabled
                        else "🔕 Напоминания об избранном: выкл"
                    ),
                    callback_data="sub:toggle_reminders",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_keyboard(
    subscription: Subscription, *, reminders_enabled: bool = True
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=BUTTON_SHOW_SOON, callback_data="menu:soon")]
    ]
    rows.extend(
        _notification_toggle_rows(
            notify_enabled=subscription.notify_enabled,
            digest_enabled=subscription.digest_enabled,
            reminders_enabled=reminders_enabled,
        )
    )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="✏️ Изменить интересы", callback_data="sub:edit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить интересы", callback_data="sub:delete"
                )
            ],
            [InlineKeyboardButton(text=BUTTON_HOME, callback_data="menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data="sub:delete_confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="sub:noop"),
            ]
        ]
    )
