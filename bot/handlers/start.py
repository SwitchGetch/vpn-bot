from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline import back_to_main_kb, main_menu_kb
from database.queries import get_or_create_user

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    await get_or_create_user(
        session,
        chat_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "",
    )
    await message.answer(
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "<b>VPS Access</b> — сервис персонального защищённого интернет-соединения.\n\n"
        "Оплата картой, Telegram Stars или криптовалютой.\n"
        "Как подключиться — в разделе <b>ℹ️ Помощь</b>.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📖 <b>Как подключиться</b>\n\n"
        "<b>Шаг 1.</b> Скачайте приложение <b>Amnezia VPN</b>:\n"
        "• iPhone / iPad — App Store, поиск «AmneziaVPN»\n"
        "• Android — Google Play, поиск «AmneziaVPN»\n"
        "• Windows / macOS / Linux — сайт amnezia.org\n\n"
        "<b>Шаг 2.</b> Купите ключ в этом боте — он придёт прямо в чат.\n\n"
        "<b>Шаг 3.</b> Скопируйте ключ (нажмите на него).\n"
        "Откройте Amnezia VPN → нажмите <b>+</b> → <b>Вставить ключ</b>.\n"
        "Вставьте скопированный ключ.\n\n"
        "<b>Шаг 4.</b> Нажмите <b>«Подключиться»</b> — готово!\n\n"
        "Один ключ работает на одном устройстве.\n"
        "Для второго устройства — купите отдельный ключ.",
        reply_markup=back_to_main_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
