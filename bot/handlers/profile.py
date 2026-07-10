from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline import (
    back_to_profile_kb,
    hwid_devices_kb,
    main_menu_kb,
    subscription_kb,
)
from database.queries import (
    delete_hwid_device,
    get_hwid_device_by_id,
    get_or_create_user,
    get_user_subscription,
)
from config import build_sub_url

router = Router()


def _devices_view(sub) -> tuple[str, InlineKeyboardMarkup]:
    hwid_devices = sub.hwid_devices
    kb = hwid_devices_kb(hwid_devices)

    if not hwid_devices:
        text = (
            f"📱 <b>Мои устройства (0/{sub.max_devices})</b>\n\n"
            "Ни одно устройство ещё не подключалось.\n\n"
            "Добавьте Subscription URL в happ — устройство появится здесь автоматически."
        )
        return text, kb

    connected = sum(1 for d in hwid_devices if not d.is_blocked)
    lines = []
    for d in hwid_devices:
        icon = "🚫" if d.is_blocked else "✅"
        model = d.device_model or "Устройство"
        os_info = f" · {d.device_os}" if d.device_os else ""
        last = d.last_seen.strftime("%d.%m.%Y")
        lines.append(f"{icon} <b>{model}</b>{os_info} — {last}")

    text = (
        f"📱 <b>Мои устройства ({connected}/{sub.max_devices})</b>\n\n"
        + "\n".join(lines)
        + "\n\n<i>Нажмите на устройство чтобы отключить его от подписки.</i>"
    )
    return text, kb


@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)

    if not sub:
        await callback.message.edit_text(
            "🔑 <b>Моя подписка</b>\n\nУ вас нет активной подписки.\n\nНажмите <b>🛒 Купить подписку</b>!",
            parse_mode="HTML",
            reply_markup=main_menu_kb(has_subscription=False),
        )
        await callback.answer()
        return

    status = "✅ Активна" if sub.is_active else "❌ Неактивна"
    expires = sub.expires_at.strftime("%d.%m.%Y")
    active_hwid = sum(1 for d in sub.hwid_devices if not d.is_blocked)

    text = (
        f"🔑 <b>Моя подписка</b>\n\n"
        f"Статус: {status}\n"
        f"Действует до: <b>{expires}</b>\n"
        f"Подключено устройств: <b>{active_hwid}/{sub.max_devices}</b>\n"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=subscription_kb(sub)
    )
    await callback.answer()


@router.callback_query(F.data == "sub:url")
async def show_sub_url(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return

    sub_url = build_sub_url(sub.sub_token)
    await callback.message.answer(
        f"📋 <b>Subscription URL</b>\n\n"
        f"Добавьте в happ как подписку:\n\n"
        f"<code>{sub_url}</code>\n\n"
        f"<i>В happ: + → Добавить подписку → вставьте URL</i>\n\n"
        f"Подписка обновляется автоматически каждый час.",
        parse_mode="HTML",
        reply_markup=back_to_profile_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "sub:devices")
async def show_devices(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return

    text, kb = _devices_view(sub)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("hwid:kick:"))
async def kick_hwid_device(callback: CallbackQuery, session: AsyncSession) -> None:
    device_id = int(callback.data.split(":")[2])
    device = await get_hwid_device_by_id(session, device_id)
    if not device:
        await callback.answer("Устройство не найдено.", show_alert=True)
        return

    if device.is_blocked:
        await callback.answer(
            "🚫 Устройство заблокировано администратором. Обратитесь в поддержку.",
            show_alert=True,
        )
        return

    await delete_hwid_device(session, device_id)
    await callback.answer(
        "✅ Устройство откреплено. Оно сможет подключиться снова при следующем обновлении подписки.",
        show_alert=True,
    )

    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    if not sub:
        return

    text, kb = _devices_view(sub)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
