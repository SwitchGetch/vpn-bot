from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_kb
from config import settings

router = Router()


class SupportStates(StatesGroup):
    entering_message = State()


@router.callback_query(F.data == "support")
async def show_support(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SupportStates.entering_message)
    await callback.message.edit_text(
        "✉️ <b>Поддержка</b>\n\n"
        "Опишите ваш вопрос или проблему — мы ответим в ближайшее время.",
        parse_mode="HTML",
        reply_markup=back_to_main_kb(),
    )
    await callback.answer()


@router.message(SupportStates.entering_message)
async def process_support_message(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = message.text or "[медиа без текста]"
    username = f"@{message.from_user.username}" if message.from_user.username else "—"

    admin_text = (
        f"📨 <b>Обращение в поддержку</b>\n\n"
        f"От: <b>{message.from_user.full_name}</b> ({username})\n"
        f"Chat ID: <code>{message.from_user.id}</code>\n\n"
        f"{text}\n\n"
        f"<i>Ответить: /reply {message.from_user.id} ваш ответ</i>"
    )

    for admin_id in settings.ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, admin_text, parse_mode="HTML")
        except Exception:
            pass

    await message.answer(
        "✅ Обращение отправлено. Мы ответим вам в ближайшее время.",
        reply_markup=back_to_main_kb(),
    )
