from __future__ import annotations

from html import escape
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardRemove,
)

from app.config import settings
from app.context import database
from app.flows import (
    delete_current_screen,
    show_favorites,
    show_partners_info,
    show_single_event,
    show_subscription,
    start_nearest,
    start_search,
    toggle_favorite_by_token,
)
from app.formatting import clean_text
from app.filter_wizard import send_onboarding
from app.keyboards import (
    home_keyboard,
    menu_callback_for_text,
    more_keyboard,
    search_hub_keyboard,
)
from app.text import greet_name


router = Router(name="common")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
HERO_PATH = Path(__file__).resolve().parent.parent / "assets" / "hero.png"
_HERO_FILE_ID: str | None = None

HOME_TEXT = (
    "<b>Sporly</b>\n"
    "Спортивные старты в одном месте.\n\n"
    "Найдите свой следующий старт — или подпишитесь на новые."
)

FIND_HUB = (
    "<b>🔍 Что ищем?</b>\n\n"
    "Напишите запрос сообщением или выберите фильтры."
)

MORE_TEXT = (
    "<b>⚙️ Ещё</b>\n\n"
    "Приглашения, реклама и полный каталог на сайте."
)

HELP_TEXT = (
    "<b>Sporly</b>\n\n"
    "🔍 Напишите запрос или выберите фильтры — покажем старты по одному, "
    "как карточки.\n"
    "⭐ Сохраняйте события в избранное — напомним за 7, 3 и 1 день.\n"
    "🎯 «Мои интересы» — виды спорта и регионы. «Ближайшие» показывает\n"
    "только старты из этой подборки.\n\n"
    "Команды:\n"
    "/find — поиск\n"
    "/soon — ближайшие\n"
    "/subscribe — мои интересы\n"
    "/survey — настроить интересы заново\n"
    "/favorites — избранное\n"
    "/help — помощь"
)


def _is_admin(chat_id: int) -> bool:
    return chat_id in settings.admin_ids


async def send_home(bot: Bot, chat_id: int) -> Message | None:
    global _HERO_FILE_ID
    if HERO_PATH.exists():
        try:
            photo = _HERO_FILE_ID or FSInputFile(HERO_PATH)
            sent = await bot.send_photo(
                chat_id,
                photo=photo,
                caption=HOME_TEXT,
                reply_markup=home_keyboard(is_admin=_is_admin(chat_id)),
            )
            if sent.photo:
                _HERO_FILE_ID = sent.photo[-1].file_id
            return sent
        except Exception:
            pass
    return await bot.send_message(
        chat_id,
        HOME_TEXT,
        reply_markup=home_keyboard(is_admin=_is_admin(chat_id)),
        link_preview_options=NO_PREVIEW,
    )


async def send_find_hub(bot: Bot, chat_id: int) -> Message:
    return await bot.send_message(
        chat_id,
        FIND_HUB,
        reply_markup=search_hub_keyboard(),
    )


async def send_more(bot: Bot, chat_id: int, *, bot_username: str = "") -> Message:
    return await bot.send_message(
        chat_id,
        MORE_TEXT,
        reply_markup=more_keyboard(
            bot_username,
            chat_id,
            settings.webapp_url,
            is_admin=_is_admin(chat_id),
        ),
        link_preview_options=NO_PREVIEW,
    )


async def _remove_legacy_keyboard(
    message: Message, chat_id: int, ui_version: int
) -> None:
    if ui_version >= 2:
        return
    try:
        notice = await message.answer(
            "Обновляю интерфейс…",
            reply_markup=ReplyKeyboardRemove(),
            disable_notification=True,
        )
        await notice.delete()
    except Exception:
        pass
    await database.mark_ui_version(chat_id, 2)


def _payload_campaign(payload: str) -> str | None:
    if not payload.startswith("src_"):
        return None
    campaign = payload[4:].strip()[:64]
    return campaign or None


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    bot: Bot,
    bot_username: str = "",
) -> None:
    await state.clear()
    user = message.from_user
    if user is None:
        return
    payload = (command.args or "").strip()
    chat_id = user.id

    profile = await database.ensure_user(chat_id, user.username, user.first_name)
    await database.mark_onboarded(chat_id)

    event_token = payload[3:] if payload.startswith("ev_") else None
    event_back: str | None = None
    if payload.startswith("evl_"):
        parts = payload.split("_")
        if len(parts) >= 4:
            event_token = parts[1]
            event_back = f"back:s:{parts[2]}:{parts[3]}"
        else:
            event_token = None
    favorite_token = payload[4:] if payload.startswith("fav_") else None
    unfavorite_token = payload[6:] if payload.startswith("unfav_") else None
    referrer_id: int | None = None
    if payload.startswith("ref_"):
        value = payload[4:].strip()
        if value.isdigit():
            referrer_id = int(value)

    campaign = _payload_campaign(payload)
    if campaign:
        await database.set_attribution(
            chat_id, source="telegram_ad", campaign=campaign
        )
        await database.log_event(chat_id, "campaign", campaign)
    elif referrer_id is not None:
        await database.set_attribution(chat_id, source="telegram", campaign="referral")
    else:
        await database.set_attribution(chat_id, source="telegram")

    if referrer_id is not None:
        added = await database.set_referrer(chat_id, referrer_id)
        if added:
            await database.log_event(chat_id, "referral", str(referrer_id))
            try:
                count = await database.referral_count(referrer_id)
                await bot.send_message(
                    referrer_id,
                    "🎁 По вашей ссылке пришёл новый пользователь Sporly. "
                    f"Всего приглашено: <b>{count}</b>. Спасибо!",
                )
            except Exception:
                pass

    await database.log_event(chat_id, "start", payload[:80] or "direct")
    await _remove_legacy_keyboard(message, chat_id, profile.ui_version)

    subscription = await database.get_subscription(chat_id)
    if (
        not event_token
        and not favorite_token
        and not unfavorite_token
        and not profile.survey_completed
        and subscription is None
    ):
        await send_onboarding(bot, chat_id, state)
        return

    if event_token:
        await show_single_event(
            bot,
            chat_id,
            event_token,
            bot_username=bot_username,
            back_callback=event_back,
        )
    elif favorite_token:
        changed, _ = await toggle_favorite_by_token(
            chat_id, favorite_token, add=True
        )
        if changed:
            await show_single_event(
                bot,
                chat_id,
                favorite_token,
                bot_username=bot_username,
                prefix="⭐ Добавил в избранное.",
            )
        else:
            await bot.send_message(
                chat_id, "Эта ссылка устарела. Найдите старт заново."
            )
    elif unfavorite_token:
        changed, _ = await toggle_favorite_by_token(
            chat_id, unfavorite_token, add=False
        )
        if changed:
            await show_single_event(
                bot,
                chat_id,
                unfavorite_token,
                bot_username=bot_username,
                prefix="💔 Убрал из избранного.",
            )
        else:
            await bot.send_message(
                chat_id, "Эта ссылка устарела. Найдите старт заново."
            )
    else:
        await send_home(bot, chat_id)


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot, bot_username: str = "") -> None:
    if message.from_user is None:
        return
    await bot.send_message(
        message.from_user.id,
        HELP_TEXT,
        reply_markup=home_keyboard(
            is_admin=message.from_user.id in settings.admin_ids
        ),
        link_preview_options=NO_PREVIEW,
    )


@router.message(Command("survey"))
async def cmd_survey(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:
    if message.from_user is None:
        return
    await send_onboarding(bot, message.from_user.id, state)


@router.message(Command("settings", "more"))
async def cmd_settings(message: Message, bot: Bot, bot_username: str = "") -> None:
    if message.from_user:
        await send_more(bot, message.from_user.id, bot_username=bot_username)


@router.message(Command("forpartners"))
async def cmd_for_partners(message: Message, bot: Bot) -> None:
    if message.from_user:
        await show_partners_info(bot, message.from_user.id)


@router.message(Command("app", "site"))
async def cmd_app(message: Message) -> None:
    await message.answer(
        "Полный каталог с календарём и фильтрами — на сайте.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Открыть sporly.ru", url=settings.webapp_url)]
            ]
        ),
    )


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def _handle_menu_action(
    bot: Bot,
    chat_id: int,
    action: str,
    *,
    bot_username: str = "",
) -> None:
    if action == "home":
        await send_home(bot, chat_id)
    elif action == "find":
        await send_find_hub(bot, chat_id)
    elif action == "soon":
        await start_nearest(bot, chat_id, bot_username=bot_username)
    elif action == "sub":
        await show_subscription(bot, chat_id, bot_username=bot_username)
    elif action == "fav":
        await show_favorites(bot, chat_id, bot_username=bot_username)
    elif action in {"more", "settings"}:
        await send_more(bot, chat_id, bot_username=bot_username)
    elif action == "partners":
        await show_partners_info(bot, chat_id)
    elif action == "site":
        await bot.send_message(
            chat_id,
            "Полный каталог с календарём и фильтрами — на сайте.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Открыть sporly.ru", url=settings.webapp_url
                        )
                    ]
                ]
            ),
        )


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(
    callback: CallbackQuery,
    bot: Bot,
    bot_username: str = "",
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    action = (callback.data or "").split(":", 1)[1]
    chat_id = callback.from_user.id
    await database.touch_user(chat_id)
    await callback.answer()
    await delete_current_screen(callback.message)
    await _handle_menu_action(bot, chat_id, action, bot_username=bot_username)


@router.message(F.text, F.chat.type == "private")
async def free_text(
    message: Message,
    bot: Bot,
    bot_username: str = "",
) -> None:
    text = clean_text(message.text, 120)
    if not text or text.startswith("/"):
        return
    if message.from_user is None:
        return
    chat_id = message.from_user.id
    await database.ensure_user(
        chat_id, message.from_user.username, message.from_user.first_name
    )
    await database.touch_user(chat_id)

    callback = menu_callback_for_text(text)
    if callback:
        action = callback.split(":", 1)[1]
        await _handle_menu_action(bot, chat_id, action, bot_username=bot_username)
        return

    if text.casefold() in {"привет", "здравствуйте", "хай", "ку"}:
        await send_home(bot, chat_id)
        return

    if len(text) < 2:
        await message.answer("Напишите хотя бы два символа — например, «бег» или «Казань».")
        return

    await bot.send_chat_action(chat_id, "typing")
    await start_search(bot, chat_id, query=text, bot_username=bot_username)


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    command = (message.text or "").split(maxsplit=1)[0]
    await message.answer(
        f"Не знаю команду {escape(command)}. Напишите запрос текстом или откройте меню.",
        reply_markup=home_keyboard(
            is_admin=message.from_user.id in settings.admin_ids
        ),
    )
