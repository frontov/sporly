from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.api_client import api_client
from app.config import settings
from app.html import escape_html

router = Router(name="admin")


def _is_admin(chat_id: int) -> bool:
    return chat_id in settings.admin_ids


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not _is_admin(message.chat.id):
        return
    try:
        status = await api_client.admin_status()
    except Exception as exc:
        await message.answer(f"Не удалось получить статус: {escape_html(str(exc))}")
        return

    cache_age = status.get("cache_age_seconds")
    cache_age_text = f"{int(cache_age)} с" if cache_age is not None else "нет данных"
    await message.answer(
        "Статус backend:\n"
        f"Обновление кэша идёт: {'да' if status.get('is_loading') else 'нет'}\n"
        f"Возраст кэша: {cache_age_text}\n"
        f"Событий в кэше: {status.get('total_events')}\n"
        f"Источников: {len(status.get('available_sources') or [])}"
    )


@router.message(Command("refresh"))
async def cmd_refresh(message: Message) -> None:
    if not _is_admin(message.chat.id):
        return
    await message.answer("Запускаю принудительное обновление кэша...")
    try:
        result = await api_client.admin_refresh()
    except Exception as exc:
        await message.answer(f"Ошибка обновления: {escape_html(str(exc))}")
        return
    await message.answer(f"Готово. Событий в кэше: {result.get('total_events')}")
