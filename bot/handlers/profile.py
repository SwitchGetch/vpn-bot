from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline import back_to_main_kb, config_detail_kb, main_menu_kb
from database.queries import get_config_by_id, get_or_create_user, get_user_configs, rename_config
from vpn.manager import build_client_uri, extract_psk


class ProfileStates(StatesGroup):
    renaming_config = State()  # data: {config_id}

router = Router()


@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    configs = await get_user_configs(session, user.id)

    if not configs:
        await callback.message.edit_text(
            "🔑 <b>Мои ключи</b>\n\nУ вас пока нет ключей.\n\n"
            "Нажмите <b>🛒 Купить ключ</b>!",
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    b = InlineKeyboardBuilder()
    text = "🔑 <b>Мои ключи</b>\n\n"

    for cfg in configs:
        status = "✅" if cfg.is_active else "❌"
        expires = cfg.expires_at.strftime("%d.%m.%Y")
        text += f"{status} <b>{cfg.device_name}</b> — до {expires}\n"
        b.button(text=f"{status} {cfg.device_name}", callback_data=f"config:{cfg.id}")

    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("config:"))
async def show_config_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    config_id = int(callback.data.split(":")[1])
    cfg = await get_config_by_id(session, config_id)

    if not cfg:
        await callback.answer("Ключ не найден.", show_alert=True)
        return

    status = "✅ Активен" if cfg.is_active else "❌ Деактивирован"
    expires = cfg.expires_at.strftime("%d.%m.%Y %H:%M UTC")

    await callback.message.edit_text(
        f"🔑 <b>{cfg.device_name}</b>\n\n"
        f"Статус: {status}\n"
        f"Истекает: <b>{expires}</b>",
        parse_mode="HTML",
        reply_markup=config_detail_kb(config_id, cfg.is_active),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("download:"))
async def download_config(callback: CallbackQuery, session: AsyncSession) -> None:
    config_id = int(callback.data.split(":")[1])
    cfg = await get_config_by_id(session, config_id)

    if not cfg:
        await callback.answer("Ключ не найден.", show_alert=True)
        return

    psk = cfg.peer_psk or extract_psk(cfg.config_text)
    uri = build_client_uri(cfg.peer_private_key, cfg.peer_public_key, cfg.peer_ip, psk)
    await callback.message.answer(
        f"📋 <b>Ключ для {cfg.device_name}</b>\n"
        f"Действителен до: <b>{cfg.expires_at.strftime('%d.%m.%Y')}</b>\n\n"
        f"Скопируйте и вставьте в Amnezia VPN (+ → Вставить ключ):\n\n"
        f"<code>{uri}</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rename:"))
async def rename_config_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    config_id = int(callback.data.split(":")[1])
    cfg = await get_config_by_id(session, config_id)
    if not cfg:
        await callback.answer("Ключ не найден.", show_alert=True)
        return
    await state.update_data(config_id=config_id)
    await state.set_state(ProfileStates.renaming_config)
    await callback.message.answer(
        f"✏️ Текущее название: <b>{cfg.device_name}</b>\n\nВведите новое название:",
        parse_mode="HTML",
        reply_markup=back_to_main_kb(),
    )
    await callback.answer()


@router.message(ProfileStates.renaming_config)
async def rename_config_finish(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    config_id = data["config_id"]
    new_name = message.text.strip()[:32]
    await state.clear()

    cfg = await rename_config(session, config_id, new_name)
    status = "✅ Активен" if cfg.is_active else "❌ Деактивирован"
    expires = cfg.expires_at.strftime("%d.%m.%Y %H:%M UTC")
    await message.answer(
        f"✅ Переименовано в <b>{new_name}</b>.\n\n"
        f"🔑 <b>{cfg.device_name}</b>\n"
        f"Статус: {status}\n"
        f"Истекает: <b>{expires}</b>",
        parse_mode="HTML",
        reply_markup=config_detail_kb(config_id, cfg.is_active),
    )
