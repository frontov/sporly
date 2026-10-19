from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from html import escape
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.api_client import api_client
from app.config import settings
from app.context import database, partner_registry


logger = logging.getLogger(__name__)
router = Router(name="admin")
MOSCOW_TZ = timezone(timedelta(hours=3))


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.admin_ids


def _display_name(
    username: str | None, first_name: str | None, chat_id: int
) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return str(chat_id)


def _short_time(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "—"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MOSCOW_TZ).strftime("%d.%m %H:%M")


def _stats_keyboard(days: int) -> InlineKeyboardMarkup:
    other = 30 if days == 7 else 7
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Поиски", callback_data=f"admin:searches:{days}"
                ),
                InlineKeyboardButton(
                    text="🖱 Переходы", callback_data=f"admin:clicks:{days}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👤 Пользователи", callback_data=f"admin:users:{days}"
                ),
                InlineKeyboardButton(
                    text=f"📅 {other} дней", callback_data=f"admin:stats:{other}"
                ),
            ],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="menu:home")],
        ]
    )


def _overview_text(overview: dict, days: int) -> str:
    interactions = overview.get("interactions") or {}
    event_clicks = interactions.get("event_click", 0)
    partner_clicks = interactions.get("partner_click", 0)
    lines = [
        f"<b>📊 Статистика · {days} дней</b>",
        "",
        f"👥 Пользователей: <b>{overview['users_total']}</b>",
        f"🆕 Новых: <b>{overview['users_period']}</b> (сегодня {overview['users_today']})",
        f"⚡ Активных: <b>{overview['users_active']}</b>",
        f"🎯 Интересов сохранено: <b>{overview['subscriptions']}</b>",
        f"⭐ В избранном: <b>{overview['favorites']}</b>",
        "",
        f"🔍 Поисков: <b>{overview['searches']}</b>",
        f"🖱 Переходов на старты: <b>{event_clicks}</b>",
        f"🤝 Переходов по рекламе: <b>{partner_clicks}</b>",
        f"🔔 Уведомлений: <b>{overview['notifications']}</b>",
        f"📬 Дайджестов: <b>{overview['digests']}</b>",
    ]
    sources = overview.get("sources") or []
    if sources:
        lines.append("")
        lines.append("<b>Источники трафика</b>")
        for item in sources[:5]:
            campaign = f" / {item['campaign']}" if item["campaign"] else ""
            lines.append(
                f"• {escape(item['source'])}{escape(campaign)} — {item['total']}"
            )
    return "\n".join(lines)


async def _summary_text(days: int) -> str:
    overview = await database.overview(days=days)
    return _overview_text(overview, days)


async def _searches_text(days: int) -> str:
    data = await database.analytics(days=days, limit=12)
    lines = [f"<b>🔍 Поиски · {days} дней</b>", ""]
    if data["queries"]:
        lines.append("<b>Что ищут</b>")
        for item in data["queries"]:
            lines.append(f"• «{escape(item['value'])}» — {item['count']}")
    else:
        lines.append("Запросов пока нет.")
    if data["categories"]:
        lines.append("")
        lines.append("<b>Виды спорта в фильтрах</b>")
        for item in data["categories"][:6]:
            lines.append(f"• {escape(item['value'])} — {item['count']}")
    if data["cities"]:
        lines.append("")
        lines.append("<b>Регионы в фильтрах</b>")
        for item in data["cities"][:6]:
            lines.append(f"• {escape(item['value'])} — {item['count']}")
    return "\n".join(lines)


async def _clicks_text(days: int) -> str:
    data = await database.analytics(days=days, limit=12)
    lines = [f"<b>🖱 Переходы · {days} дней</b>", ""]
    if data["events"]:
        lines.append("<b>Куда переходят</b>")
        for item in data["events"]:
            lines.append(f"• {escape(item['title'])} — {item['count']}")
    else:
        lines.append("Переходов на старты пока нет.")

    partner_stats = await database.partner_stats(days=days)
    if partner_stats:
        lines.append("")
        lines.append("<b>Партнёрские ссылки</b>")
        for item in partner_stats[:6]:
            lines.append(
                f"• {escape(item['partner_id'])} — "
                f"{item['clicks']} переходов, "
                f"{item['impressions']} показов"
            )
    return "\n".join(lines)


async def _users_text(days: int) -> tuple[str, InlineKeyboardMarkup]:
    users = await database.user_activity(days=days, limit=10)
    header = f"<b>👤 Пользователи · {days} дней</b>"
    lines: list[str] = []
    rows: list[list[InlineKeyboardButton]] = []
    if not users:
        lines.append("Пока нет пользователей.")
    for user in users:
        name = _display_name(
            user["username"], user["first_name"], user["chat_id"]
        )
        lines.append(
            f"<b>{escape(name)}</b> · <code>{user['chat_id']}</code>\n"
            f"🔍 {user['searches']} · 🖱 {user['clicks']} · "
            f"🤝 {user['partner_clicks']} · ⭐ {user['favorites']}\n"
            f"был(а): {_short_time(user['last_active_at'])}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Открыть {name}"[:60],
                    callback_data=f"admin:user:{user['chat_id']}:{days}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Статистика", callback_data=f"admin:stats:{days}"
            )
        ]
    )
    body = "\n\n".join(lines)
    text = header + ("\n\n" + body if body else "")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _user_text(chat_id: int, days: int) -> str | None:
    details = await database.user_details(chat_id, days=days, limit=8)
    if details is None:
        return None
    name = _display_name(details["username"], details["first_name"], chat_id)
    lines = [
        f"<b>👤 {escape(name)}</b>",
        f"ID: <code>{chat_id}</code>",
        f"Последняя активность: {_short_time(details['last_active_at'])}",
        "",
        f"🔍 Поисков: <b>{details['search_total']}</b> · "
        f"🖱 Переходов: <b>{details['click_total']}</b> · "
        f"🤝 По рекламе: <b>{details['partner_click_total']}</b>",
        f"⭐ В избранном: <b>{details['favorites']}</b>",
    ]
    subscription = details.get("subscription")
    if subscription:
        from app.formatting import filters_summary

        lines.append(
            "🎯 Интересы: "
            + filters_summary(subscription["cities"], subscription["categories"])
        )
    else:
        lines.append("🎯 Интересы: не настроены")

    lines.append("")
    lines.append("<b>Последние поиски</b>")
    if details["searches"]:
        for item in details["searches"][:8]:
            query = item["query"].strip()
            if query:
                what = f"«{escape(query)}»"
            else:
                what = "фильтры"
            filters = ", ".join(item["cities"][:2] + item["categories"][:2])
            suffix = f" · {escape(filters)}" if filters else ""
            lines.append(f"• {what}{suffix} · {_short_time(item['created_at'])}")
    else:
        lines.append("• нет")

    lines.append("")
    lines.append("<b>Последние переходы</b>")
    if details["clicks"]:
        for item in details["clicks"][:8]:
            lines.append(
                f"• {escape(item['title'])} · {_short_time(item['created_at'])}"
            )
    else:
        lines.append("• нет")
    return "\n".join(lines)


async def _send_callback_screen(
    callback: CallbackQuery,
    bot: Bot,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    if callback.message is not None:
        try:
            await callback.message.delete()
        except Exception:
            pass
    await bot.send_message(
        callback.from_user.id,
        text,
        reply_markup=markup,
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Команда доступна только администратору.")
        return
    await message.answer(
        "<b>Админка Sporly</b>\n\n"
        "/status — состояние backend и каталога\n"
        "/stats — воронка и источники трафика\n"
        "/partners — показы и переходы по партнёрам\n"
        "/reload — сбросить кэш API и перечитать партнёров\n"
        "/broadcast &lt;текст&gt; — рассылка всем пользователям\n\n"
        "Кнопка «📊 Статистика» есть на главном экране."
    )


@router.callback_query(F.data.startswith("admin:"))
async def admin_callbacks(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    user_id = callback.from_user.id if callback.from_user else None
    if not _is_admin(user_id):
        await callback.answer("Только для администратора", show_alert=True)
        return

    parts = (callback.data or "").split(":")
    action = parts[1] if len(parts) > 1 else "stats"
    days = 7
    if action in {"stats", "searches", "clicks", "users"}:
        if len(parts) > 2 and parts[2].isdigit():
            days = int(parts[2])

    await callback.answer()

    if action == "stats":
        await _send_callback_screen(
            callback, bot, await _summary_text(days), _stats_keyboard(days)
        )
    elif action == "searches":
        await _send_callback_screen(
            callback,
            bot,
            await _searches_text(days),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Статистика",
                            callback_data=f"admin:stats:{days}",
                        )
                    ]
                ]
            ),
        )
    elif action == "clicks":
        await _send_callback_screen(
            callback,
            bot,
            await _clicks_text(days),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Статистика",
                            callback_data=f"admin:stats:{days}",
                        )
                    ]
                ]
            ),
        )
    elif action == "users":
        text, markup = await _users_text(days)
        await _send_callback_screen(callback, bot, text, markup)
    elif action == "user":
        if len(parts) < 3 or not parts[2].isdigit():
            return
        target_id = int(parts[2])
        if len(parts) > 3 and parts[3].isdigit():
            days = int(parts[3])
        text = await _user_text(target_id, days)
        if text is None:
            text = "Пользователь не найден."
        await _send_callback_screen(
            callback,
            bot,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Пользователи",
                            callback_data=f"admin:users:{days}",
                        )
                    ]
                ]
            ),
        )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    lines = ["<b>Состояние</b>", ""]
    try:
        health = await api_client.health()
        lines.append(f"backend: <b>{escape(str(health.get('status', 'unknown')))}</b>")
    except Exception as error:
        lines.append(f"backend: <b>недоступен</b> ({escape(type(error).__name__)})")

    try:
        total, loading = await api_client.total_events()
        lines.append(f"событий в каталоге: <b>{total}</b>")
        lines.append(f"обновление: {'идёт' if loading else 'завершено'}")
    except Exception as error:
        lines.append(f"каталог: <b>ошибка</b> ({escape(type(error).__name__)})")

    overview = await database.overview(days=1)
    lines.append(f"пользователей: <b>{overview['users_total']}</b>")
    lines.append(f"интересов: <b>{overview['subscriptions']}</b>")
    lines.append(f"в избранном: <b>{overview['favorites']}</b>")
    await message.answer("\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer(
        await _summary_text(7),
        reply_markup=_stats_keyboard(7),
    )


@router.message(Command("partners"))
async def cmd_partners(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    stats = await database.partner_stats(days=7)
    rows = partner_registry.admin_rows(stats)
    if not rows:
        await message.answer(
            "Партнёрских слотов нет. Добавьте их в "
            "<code>bot/app/config/partners.json</code>."
        )
        return

    lines = ["<b>Партнёры · 7 дней</b>", ""]
    for row in rows:
        status = "✅" if row.get("enabled") else "⏸"
        lines.append(
            f"{status} <b>{escape(str(row['title']))}</b> "
            f"(<code>{escape(str(row['partner_id']))}</code>)\n"
            f"показы: {row['impressions']} · переходы: {row['clicks']} · CTR: {row['ctr']:.1f}%"
        )
    await message.answer("\n\n".join(lines))


@router.message(Command("reload"))
async def cmd_reload(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    api_client.clear_cache()
    partner_registry._reload()
    await message.answer("Кэш API сброшен, конфиг партнёров перечитан.")


@router.message(Command("broadcast"))
async def cmd_broadcast(
    message: Message, command: CommandObject, bot: Bot
) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    text = (command.args or "").strip()
    if not text:
        await message.answer("Использование: <code>/broadcast текст сообщения</code>")
        return

    user_ids = await database.all_user_ids()
    await message.answer(f"Рассылаю на {len(user_ids)} пользователей…")
    sent = 0
    failed = 0
    for chat_id in user_ids:
        try:
            await bot.send_message(chat_id, text, disable_web_page_preview=True)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await message.answer(
        f"Готово. Отправлено: <b>{sent}</b>, ошибок: <b>{failed}</b>."
    )
