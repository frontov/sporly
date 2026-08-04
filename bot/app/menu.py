from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_FIND = "🔍 Найти события"
BTN_BROWSE = "🎯 Другие фильтры"
BTN_FAVORITES = "⭐ Избранное"
BTN_SETTINGS = "⚙️ Настройки"

# Reply keyboards live on the client until the bot sends a new one, so users who
# haven't touched /start still tap yesterday's labels. Keep matching those.
FIND_TEXTS = {BTN_FIND}
BROWSE_TEXTS = {BTN_BROWSE, "🎯 Разовый поиск"}
FAVORITES_TEXTS = {BTN_FAVORITES}
SETTINGS_TEXTS = {BTN_SETTINGS}

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_FIND), KeyboardButton(text=BTN_BROWSE)],
        [KeyboardButton(text=BTN_FAVORITES), KeyboardButton(text=BTN_SETTINGS)],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Выберите действие или напишите /find марафон",
)
