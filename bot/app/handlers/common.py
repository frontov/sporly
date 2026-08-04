from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.category_city_flow import start as start_flow
from app.handlers.favorites import handle_favorite_payload
from app.handlers.subscriptions import FLOW as FILTERS_FLOW
from app.storage import store

router = Router(name="common")

HELP_TEXT = (
    "<b>Sporly</b> — забеги, велогонки, лыжи и другие старты в одном месте.\n\n"
    "🔍 <b>Найти события</b> — по вашим видам спорта и регионам\n"
    "🎯 <b>Другие фильтры</b> — разовый поиск с другими настройками\n"
    "⭐ <b>Избранное</b> — сохранённые старты и напоминания\n"
    "⚙️ <b>Настройки</b> — фильтры, уведомления, дайджест\n\n"
    "Под каждым событием есть «⭐ Сохранить» — напомню за 7, 3 и 1 день до старта.\n"
    "Ищете конкретный старт? Напишите <code>/find марафон</code>."
)


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(message: Message, command: CommandObject, state: FSMContext) -> None:
    if await handle_favorite_payload(message, (command.args or "").strip()):
        return
    await cmd_start(message, state)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    subscription = store.get(message.chat.id)
    if subscription is None or not subscription.onboarded:
        await message.answer(
            "👋 <b>Привет!</b>\n\n"
            "Sporly собирает спортивные старты с десятков сайтов в один календарь.\n\n"
            "Настроим за полминуты: отметьте виды спорта и регионы — "
            "дальше «🔍 Найти события» будет показывать только их."
        )
        await start_flow(message, state, FILTERS_FLOW)
        return
    await message.answer(f"👋 <b>С возвращением</b>\n\n{HELP_TEXT}")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
