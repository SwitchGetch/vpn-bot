from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline import back_to_main_kb, main_menu_kb
from database.queries import get_or_create_user, get_user_subscription

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    user = await get_or_create_user(
        session,
        chat_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    await message.answer(
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "<b>VPN сервис</b> — персональное защищённое интернет-соединение.\n\n"
        "Оплата картой, Telegram Stars или криптовалютой.\n"
        "Как подключиться — в разделе <b>ℹ️ Помощь</b>.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_kb(has_subscription=bool(sub)),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    user = await get_or_create_user(
        session,
        chat_id=callback.from_user.id,
        username=callback.from_user.username or "",
        full_name=callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu_kb(has_subscription=bool(sub)),
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📖 <b>Как подключиться</b>\n\n"
        "<b>Шаг 1.</b> Скачайте приложение <b>happ</b>:\n"
        "• iPhone / iPad — App Store, поиск «happ»\n"
        "• Android — Google Play, поиск «happ»\n"
        "• Windows / macOS — сайт happ.su\n\n"
        "<b>Шаг 2.</b> Купите подписку в этом боте.\n\n"
        "<b>Шаг 3.</b> Скопируйте Subscription URL из раздела «Моя подписка».\n"
        "Откройте happ → нажмите <b>+</b> → <b>Добавить подписку</b> → вставьте URL.\n\n"
        "<b>Шаг 4.</b> Выберите сервер и нажмите <b>«Подключиться»</b> — готово!\n\n"
        "Одна подписка работает на нескольких устройствах одновременно.\n"
        "Количество устройств выбираете при покупке.",
        reply_markup=back_to_main_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
