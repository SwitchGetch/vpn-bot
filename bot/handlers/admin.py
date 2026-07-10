import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.admin import (
    admin_hwid_devices_kb,
    admin_menu_kb,
    admin_payment_detail_kb,
    admin_payments_kb,
    admin_plan_detail_kb,
    admin_plans_kb,
    admin_sub_delete_confirm_kb,
    admin_sub_detail_kb,
    admin_user_detail_kb,
    admin_users_kb,
    back_admin_kb,
)
from config import build_sub_url, settings
from database.queries import (
    activate_subscription,
    add_device,
    block_hwid_device,
    count_users,
    create_plan,
    create_subscription,
    deactivate_subscription,
    delete_plan,
    get_all_plans,
    get_all_settings,
    get_all_users,
    get_hwid_device_by_id,
    get_hwid_devices_for_sub,
    get_plan_by_id,
    get_setting,
    get_stats,
    get_subscription_by_id,
    get_user_by_chat_id,
    get_user_subscription,
    remove_all_devices,
    set_setting,
    set_user_banned,
    update_plan,
)
from vpn.manager import add_xray_users, generate_uuid, remove_xray_users

logger = logging.getLogger(__name__)
router = Router()


def _is_positive_decimal(v: str) -> bool:
    try:
        return float(v) > 0
    except (ValueError, TypeError):
        return False


_PLAN_FIELDS = {
    "label":       ("название",                                               str, None),
    "days":        ("кол-во дней",                                            int, lambda v: v > 0),
    "stars_price": ("цену в Telegram Stars (за 1 устройство)",                int, lambda v: v > 0),
    "rub_kopeks":  ("цену в копейках для ЮKassa (напр. 19900 = 199₽)",       int, lambda v: v > 0),
    "usdt_price":  ("цену в USDT для Крипто (напр. 2.50)",                   str, _is_positive_decimal),
    "sort_order":  ("порядок сортировки",                                     int, None),
}

_PAY_NAMES = {"stars": "Stars", "yookassa": "ЮKassa", "crypto": "Крипто"}


class AdminStates(StatesGroup):
    editing_token       = State()  # data: {method}
    editing_plan_field  = State()  # data: {plan_id, field, field_label, cast}
    adding_plan_days    = State()
    adding_plan_label   = State()
    adding_plan_stars   = State()
    giving_sub_days     = State()  # data: {target_chat_id}
    giving_sub_devices  = State()  # data: {target_chat_id, plan_days}
    messaging_user      = State()  # data: {target_chat_id}


async def _admin_check(event: Message | CallbackQuery) -> bool:
    return event.from_user.id in settings.ADMIN_IDS


router.message.filter(_admin_check)
router.callback_query.filter(_admin_check)


# ── Главное меню ────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer("🔧 <b>Панель администратора</b>", parse_mode="HTML", reply_markup=admin_menu_kb())


@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text("🔧 <b>Панель администратора</b>", parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()


# ── Статистика ──────────────────────────────────────────────────

@router.callback_query(F.data == "adm:stats")
async def cb_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    s = await get_stats(session)
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{s['users']}</b>\n"
        f"🔑 Активных подписок: <b>{s['active_subscriptions']}</b>\n"
        f"📱 Устройств всего: <b>{s['total_devices']}</b>\n\n"
        f"⭐ Заработано Stars: <b>{s['total_stars'] or 0}</b>\n"
        f"💳 Платежей ЮKassa: <b>{s['yookassa_count'] or 0}</b>\n"
        f"₮ Крипто-платежей: <b>{s['crypto_count'] or 0}</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_admin_kb())
    await callback.answer()


# ── Оплата ──────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:pay")
async def cb_payments(callback: CallbackQuery, session: AsyncSession) -> None:
    s = await get_all_settings(session)
    await callback.message.edit_text(
        "💳 <b>Способы оплаты</b>\n\nВыберите метод для управления:",
        parse_mode="HTML",
        reply_markup=admin_payments_kb(
            stars=s.get("payment_stars_enabled", "1") == "1",
            yookassa=s.get("payment_yookassa_enabled", "0") == "1",
            crypto=s.get("payment_crypto_enabled", "0") == "1",
        ),
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("adm:pay:")
    & ~F.data.startswith("adm:pay:toggle:")
    & ~F.data.startswith("adm:pay:token:")
)
async def cb_payment_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    method = callback.data.split(":")[2]
    enabled = await get_setting(session, f"payment_{method}_enabled", "0")
    token = await get_setting(session, f"payment_{method}_token", "")
    name = _PAY_NAMES.get(method, method)
    status = "✅ Включён" if enabled == "1" else "❌ Отключён"
    token_line = f"\nТокен: <code>{'задан' if token else 'не задан'}</code>" if method != "stars" else ""
    await callback.message.edit_text(
        f"💳 <b>{name}</b>\n\nСтатус: {status}{token_line}",
        parse_mode="HTML",
        reply_markup=admin_payment_detail_kb(method, enabled == "1"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:pay:toggle:"))
async def cb_toggle_payment(callback: CallbackQuery, session: AsyncSession) -> None:
    method = callback.data.split(":")[3]
    key = f"payment_{method}_enabled"
    current = await get_setting(session, key, "0")
    new_val = "0" if current == "1" else "1"
    await set_setting(session, key, new_val)
    enabled = new_val == "1"
    name = _PAY_NAMES.get(method, method)
    status = "включён ✅" if enabled else "отключён ❌"
    await callback.answer(f"{name} {status}", show_alert=True)
    token = await get_setting(session, f"payment_{method}_token", "")
    token_line = f"\nТокен: <code>{'задан' if token else 'не задан'}</code>" if method != "stars" else ""
    await callback.message.edit_text(
        f"💳 <b>{name}</b>\n\nСтатус: {'✅ Включён' if enabled else '❌ Отключён'}{token_line}",
        parse_mode="HTML",
        reply_markup=admin_payment_detail_kb(method, enabled),
    )


@router.callback_query(F.data.startswith("adm:pay:token:"))
async def cb_edit_token_start(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":")[3]
    await state.update_data(method=method)
    await state.set_state(AdminStates.editing_token)
    name = _PAY_NAMES.get(method, method)
    await callback.message.answer(f"✏️ Введите новый токен для <b>{name}</b>:", parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.editing_token)
async def cb_edit_token_finish(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    method = data["method"]
    token = message.text.strip()
    await set_setting(session, f"payment_{method}_token", token)
    await state.clear()
    name = _PAY_NAMES.get(method, method)
    await message.answer(f"✅ Токен для <b>{name}</b> обновлён.", parse_mode="HTML", reply_markup=back_admin_kb())


# ── Тарифы ──────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:plans")
async def cb_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    plans = await get_all_plans(session)
    await callback.message.edit_text(
        "📋 <b>Тарифы</b>\n\nВсе тарифы (✅ активны, ❌ скрыты от пользователей):",
        parse_mode="HTML",
        reply_markup=admin_plans_kb(plans),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^adm:plan:\d+$"))
async def cb_plan_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_id = int(callback.data.split(":")[2])
    plan = await get_plan_by_id(session, plan_id)
    if not plan:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    rub_str = f"{plan.rub_kopeks // 100}₽" if plan.rub_kopeks else "не задана"
    usdt_str = f"{plan.usdt_price} USDT" if plan.usdt_price else "не задана"
    text = (
        f"📋 <b>Тариф #{plan.id}</b>\n\n"
        f"Название: <b>{plan.label}</b>\n"
        f"Дней: <b>{plan.days}</b>\n"
        f"Цена Stars/устр.: <b>{plan.stars_price} ⭐</b>\n"
        f"Цена рублей: <b>{rub_str}</b>\n"
        f"Цена USDT: <b>{usdt_str}</b>\n"
        f"Порядок: <b>{plan.sort_order}</b>\n"
        f"Статус: {'✅ Активен' if plan.is_active else '❌ Скрыт'}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_plan_detail_kb(plan))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:plan:toggle:"))
async def cb_toggle_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_id = int(callback.data.split(":")[3])
    plan = await get_plan_by_id(session, plan_id)
    if not plan:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    plan = await update_plan(session, plan_id, is_active=not plan.is_active)
    status = "активирован ✅" if plan.is_active else "деактивирован ❌"
    await callback.answer(f"Тариф {status}", show_alert=True)
    rub_str = f"{plan.rub_kopeks // 100}₽" if plan.rub_kopeks else "не задана"
    usdt_str = f"{plan.usdt_price} USDT" if plan.usdt_price else "не задана"
    await callback.message.edit_text(
        f"📋 <b>Тариф #{plan.id}</b>\n\n"
        f"Название: <b>{plan.label}</b>\n"
        f"Дней: <b>{plan.days}</b>\n"
        f"Цена Stars/устр.: <b>{plan.stars_price} ⭐</b>\n"
        f"Цена рублей: <b>{rub_str}</b>\n"
        f"Цена USDT: <b>{usdt_str}</b>\n"
        f"Порядок: <b>{plan.sort_order}</b>\n"
        f"Статус: {'✅ Активен' if plan.is_active else '❌ Скрыт'}",
        parse_mode="HTML",
        reply_markup=admin_plan_detail_kb(plan),
    )


@router.callback_query(F.data.startswith("adm:plan:field:"))
async def cb_plan_field_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    plan_id, field = int(parts[3]), parts[4]
    if field not in _PLAN_FIELDS:
        await callback.answer("Неизвестное поле.", show_alert=True)
        return
    plan = await get_plan_by_id(session, plan_id)
    field_label, cast, _ = _PLAN_FIELDS[field]
    current = getattr(plan, field)
    await state.update_data(plan_id=plan_id, field=field, field_label=field_label, cast=cast.__name__)
    await state.set_state(AdminStates.editing_plan_field)
    await callback.message.answer(
        f"✏️ Введите новое <b>{field_label}</b>:\n<i>Текущее значение: {current}</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.editing_plan_field)
async def cb_plan_field_finish(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    plan_id = data["plan_id"]
    field = data["field"]
    cast_name = data["cast"]
    field_label = data["field_label"]
    _, _, validator = _PLAN_FIELDS[field]
    try:
        cast = int if cast_name == "int" else str
        value = cast(message.text.strip())
        if validator and not validator(value):
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Некорректное значение. Попробуйте ещё раз:")
        return
    await update_plan(session, plan_id, **{field: value})
    await state.clear()
    await message.answer(
        f"✅ Поле <b>{field_label}</b> обновлено на <b>{value}</b>.",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )


@router.callback_query(F.data.startswith("adm:plan:del:"))
async def cb_plan_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_id = int(callback.data.split(":")[3])
    await delete_plan(session, plan_id)
    await callback.answer("🗑️ Тариф удалён.", show_alert=True)
    plans = await get_all_plans(session)
    await callback.message.edit_text("📋 <b>Тарифы</b>", parse_mode="HTML", reply_markup=admin_plans_kb(plans))


@router.callback_query(F.data == "adm:plan:add")
async def cb_plan_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.adding_plan_days)
    await callback.message.answer("➕ <b>Новый тариф</b>\n\nВведите <b>количество дней</b>:", parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.adding_plan_days)
async def cb_plan_add_days(message: Message, state: FSMContext) -> None:
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число больше 0:")
        return
    await state.update_data(days=days)
    await state.set_state(AdminStates.adding_plan_label)
    await message.answer(f"Введите <b>название</b> тарифа (например: <i>{days} дней</i>):", parse_mode="HTML")


@router.message(AdminStates.adding_plan_label)
async def cb_plan_add_label(message: Message, state: FSMContext) -> None:
    await state.update_data(label=message.text.strip()[:64])
    await state.set_state(AdminStates.adding_plan_stars)
    await message.answer("Введите <b>цену в Telegram Stars за 1 устройство</b>:", parse_mode="HTML")


@router.message(AdminStates.adding_plan_stars)
async def cb_plan_add_stars(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        stars = int(message.text.strip())
        if stars <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число больше 0:")
        return
    data = await state.get_data()
    await state.clear()
    all_plans = await get_all_plans(session)
    plan = await create_plan(session, data["days"], data["label"], stars, sort_order=len(all_plans))
    await message.answer(
        f"✅ Тариф <b>{plan.label}</b> ({plan.stars_price} ⭐/устр.) создан.",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )


# ── Пользователи ────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^adm:users:\d+$"))
async def cb_users(callback: CallbackQuery, session: AsyncSession) -> None:
    per_page = 20
    page = int(callback.data.split(":")[2])
    total = await count_users(session)
    users = await get_all_users(session, limit=per_page, offset=page * per_page)
    await callback.message.edit_text(
        f"👥 <b>Пользователи</b> (всего: {total})\nСтраница {page + 1}:",
        parse_mode="HTML",
        reply_markup=admin_users_kb(users, page, total, per_page),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^adm:user:\d+$"))
async def cb_user_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    chat_id = int(callback.data.split(":")[2])
    user = await get_user_by_chat_id(session, chat_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    sub = user.subscription
    username = f"@{user.username}" if user.username else "—"
    sub_line = ""
    if sub:
        status = "✅ активна" if sub.is_active else "❌ неактивна"
        expires = sub.expires_at.strftime("%d.%m.%Y")
        sub_line = f"\nПодписка: {status}, до {expires}, {len(sub.devices)}/{sub.max_devices} устройств"
    text = (
        f"👤 <b>{user.full_name or username}</b>\n\n"
        f"Username: {username}\n"
        f"Chat ID: <code>{user.chat_id}</code>\n"
        f"Статус: {'🚫 Заблокирован' if user.is_banned else '✅ Активен'}\n"
        f"Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}"
        f"{sub_line}"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=admin_user_detail_kb(chat_id, user.is_banned, has_sub=bool(sub)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:user:ban:"))
async def cb_ban_user(callback: CallbackQuery, session: AsyncSession) -> None:
    chat_id = int(callback.data.split(":")[3])
    user = await get_user_by_chat_id(session, chat_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    new_ban = not user.is_banned
    await set_user_banned(session, chat_id, new_ban)
    status = "заблокирован 🚫" if new_ban else "разблокирован ✅"
    await callback.answer(f"Пользователь {status}", show_alert=True)
    user = await get_user_by_chat_id(session, chat_id)
    sub = user.subscription
    username = f"@{user.username}" if user.username else "—"
    sub_line = ""
    if sub:
        sub_status = "✅ активна" if sub.is_active else "❌ неактивна"
        expires = sub.expires_at.strftime("%d.%m.%Y")
        sub_line = f"\nПодписка: {sub_status}, до {expires}, {len(sub.devices)}/{sub.max_devices} устройств"
    await callback.message.edit_text(
        f"👤 <b>{user.full_name or username}</b>\n\n"
        f"Username: {username}\n"
        f"Chat ID: <code>{user.chat_id}</code>\n"
        f"Статус: {'🚫 Заблокирован' if user.is_banned else '✅ Активен'}\n"
        f"Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}"
        f"{sub_line}",
        parse_mode="HTML",
        reply_markup=admin_user_detail_kb(chat_id, user.is_banned, has_sub=bool(sub)),
    )


# ── Подписка пользователя ────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:user:sub:"))
async def cb_user_sub(callback: CallbackQuery, session: AsyncSession) -> None:
    chat_id = int(callback.data.split(":")[3])
    user = await get_user_by_chat_id(session, chat_id)
    if not user or not user.subscription:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    sub = user.subscription
    await _show_sub_detail(callback, sub, chat_id)


async def _show_sub_detail(callback: CallbackQuery, sub, chat_id: int) -> None:
    status = "✅ Активна" if sub.is_active else "❌ Неактивна"
    expires = sub.expires_at.strftime("%d.%m.%Y %H:%M UTC")
    devices_text = ""
    for i, d in enumerate(sub.devices, 1):
        devices_text += f"\n  {i}. {d.device_name}"
    text = (
        f"🔑 <b>Подписка #{sub.id}</b>\n\n"
        f"Статус: {status}\n"
        f"Дней в плане: {sub.plan_days}\n"
        f"Истекает: <b>{expires}</b>\n"
        f"Устройства ({len(sub.devices)}/{sub.max_devices}):{devices_text}"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=admin_sub_detail_kb(sub, chat_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:sub:activate:"))
async def cb_sub_activate(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    sub_id, chat_id = int(parts[3]), int(parts[4])
    await activate_subscription(session, sub_id)
    await callback.answer("✅ Подписка активирована.", show_alert=True)
    sub = await get_subscription_by_id(session, sub_id)
    if sub:
        await _show_sub_detail(callback, sub, chat_id)


@router.callback_query(F.data.startswith("adm:sub:deactivate:"))
async def cb_sub_deactivate(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    sub_id, chat_id = int(parts[3]), int(parts[4])
    await deactivate_subscription(session, sub_id)
    await callback.answer("❌ Подписка деактивирована.", show_alert=True)
    sub = await get_subscription_by_id(session, sub_id)
    if sub:
        await _show_sub_detail(callback, sub, chat_id)


@router.callback_query(F.data.startswith("adm:sub:send:"))
async def cb_sub_send_url(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    sub_id, chat_id = int(parts[3]), int(parts[4])
    sub = await get_subscription_by_id(session, sub_id)
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    sub_url = build_sub_url(sub.sub_token)
    try:
        await callback.bot.send_message(
            chat_id,
            f"📋 <b>Subscription URL</b>\n\n"
            f"Добавьте в happ как подписку:\n\n"
            f"<code>{sub_url}</code>\n\n"
            f"<i>В happ: + → Добавить подписку → вставьте URL</i>",
            parse_mode="HTML",
        )
        await callback.answer("✅ URL отправлен пользователю.", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data.startswith("adm:sub:delconfirm:"))
async def cb_sub_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    sub_id, chat_id = int(parts[3]), int(parts[4])
    sub = await get_subscription_by_id(session, sub_id)
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ <b>Удалить подписку #{sub.id}?</b>\n\n"
        f"Пользователь потеряет доступ к VPN немедленно.\n"
        f"Действие необратимо.",
        parse_mode="HTML",
        reply_markup=admin_sub_delete_confirm_kb(sub_id, chat_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:sub:delete:"))
async def cb_sub_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    sub_id, chat_id = int(parts[3]), int(parts[4])
    sub = await get_subscription_by_id(session, sub_id)
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    uuids = await remove_all_devices(session, sub_id)
    if uuids:
        try:
            await remove_xray_users(uuids)
        except Exception as e:
            logger.error("XRay remove error during sub delete: %s", e)
    await session.delete(sub)
    await session.commit()
    try:
        await callback.bot.send_message(
            chat_id,
            "❌ Ваша подписка была удалена администратором.",
        )
    except Exception:
        pass
    await callback.answer("🗑️ Подписка удалена.", show_alert=True)
    user = await get_user_by_chat_id(session, chat_id)
    if user:
        username = f"@{user.username}" if user.username else "—"
        await callback.message.edit_text(
            f"👤 <b>{user.full_name or username}</b>\n\nПодписка удалена.",
            parse_mode="HTML",
            reply_markup=admin_user_detail_kb(chat_id, user.is_banned, has_sub=False),
        )


# ── Выдать подписку вручную ─────────────────────────────────────

@router.callback_query(F.data.startswith("adm:user:give:"))
async def cb_give_sub_start(callback: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(callback.data.split(":")[3])
    await state.update_data(target_chat_id=chat_id)
    await state.set_state(AdminStates.giving_sub_days)
    await callback.message.answer(
        "🎁 <b>Выдать подписку</b>\n\nВведите количество дней доступа:\n<i>0 = бессрочно (36500 дней)</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.giving_sub_days)
async def cb_give_sub_days(message: Message, state: FSMContext) -> None:
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число >= 0:")
        return
    plan_days = 36500 if days == 0 else days
    await state.update_data(plan_days=plan_days)
    await state.set_state(AdminStates.giving_sub_devices)
    await message.answer("Введите количество устройств:")


@router.message(AdminStates.giving_sub_devices)
async def cb_give_sub_devices(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        device_count = int(message.text.strip())
        if device_count < 1 or device_count > 20:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 1 до 20:")
        return

    data = await state.get_data()
    await state.clear()
    target_chat_id = data["target_chat_id"]
    plan_days = data["plan_days"]

    user = await get_user_by_chat_id(session, target_chat_id)
    if not user:
        await message.answer("❌ Пользователь не найден в базе. Пусть сначала напишет /start боту.")
        return

    try:
        existing_sub = await get_user_subscription(session, user.id)
        if existing_sub:
            old_uuids = await remove_all_devices(session, existing_sub.id)
            if old_uuids:
                await remove_xray_users(old_uuids)
            await session.delete(existing_sub)
            await session.commit()

        sub = await create_subscription(
            session,
            user_id=user.id,
            plan_days=plan_days,
            max_devices=device_count,
            base_device_price=0,
            is_active=True,
        )

        xray_uuid = generate_uuid()
        await add_device(session, sub.id, xray_uuid)
        await add_xray_users([xray_uuid])

        sub_url = build_sub_url(sub.sub_token)
        expires_str = sub.expires_at.strftime("%d.%m.%Y")

        await message.bot.send_message(
            target_chat_id,
            f"🎁 <b>Подписка выдана администратором</b>\n\n"
            f"Устройств: <b>{device_count}</b>\n"
            f"Действует до: <b>{expires_str}</b>\n\n"
            f"📋 Subscription URL для happ:\n<code>{sub_url}</code>\n\n"
            f"<i>В happ: + → Добавить подписку → вставьте URL</i>",
            parse_mode="HTML",
        )
        await message.answer(
            f"✅ Подписка выдана пользователю <code>{target_chat_id}</code> на {plan_days} дней, {device_count} устройств.",
            parse_mode="HTML",
            reply_markup=back_admin_kb(),
        )
    except Exception as e:
        logger.error("Error giving subscription to user %d: %s", target_chat_id, e)
        await message.answer(f"❌ Ошибка при создании подписки: {e}", reply_markup=back_admin_kb())


# ── HWID устройства (админ) ─────────────────────────────────────

@router.callback_query(F.data.startswith("adm:sub:hwid:"))
async def cb_sub_hwid_devices(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    sub_id, chat_id = int(parts[3]), int(parts[4])
    sub = await get_subscription_by_id(session, sub_id)
    if not sub:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return

    hwid_devices = await get_hwid_devices_for_sub(session, sub_id)
    if not hwid_devices:
        await callback.message.edit_text(
            f"📱 <b>HWID устройства подписки #{sub_id}</b>\n\nНи одно устройство ещё не подключалось.",
            parse_mode="HTML",
            reply_markup=admin_hwid_devices_kb(hwid_devices, sub_id, chat_id),
        )
        await callback.answer()
        return

    lines = []
    for d in hwid_devices:
        icon = "🚫" if d.is_blocked else "✅"
        model = d.device_model or "—"
        os_info = f"{d.device_os} {d.os_version}" if d.device_os else "—"
        last = d.last_seen.strftime("%d.%m.%Y %H:%M")
        lines.append(f"{icon} <b>{model}</b> · {os_info}\n   <i>последний визит: {last}</i>")

    active = sum(1 for d in hwid_devices if not d.is_blocked)
    await callback.message.edit_text(
        f"📱 <b>HWID устройства подписки #{sub_id}</b> ({active}/{sub.max_devices})\n\n"
        + "\n\n".join(lines)
        + "\n\n<i>Нажмите на устройство чтобы заблокировать/разблокировать.</i>",
        parse_mode="HTML",
        reply_markup=admin_hwid_devices_kb(hwid_devices, sub_id, chat_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:hwid:toggle:"))
async def cb_hwid_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    hwid_device_id, sub_id, chat_id = int(parts[3]), int(parts[4]), int(parts[5])
    device = await get_hwid_device_by_id(session, hwid_device_id)
    if not device:
        await callback.answer("Устройство не найдено.", show_alert=True)
        return
    new_blocked = not device.is_blocked
    await block_hwid_device(session, hwid_device_id, new_blocked)
    status = "заблокировано 🚫" if new_blocked else "разблокировано ✅"
    await callback.answer(f"Устройство {status}", show_alert=True)

    # Обновить список
    sub = await get_subscription_by_id(session, sub_id)
    hwid_devices = await get_hwid_devices_for_sub(session, sub_id)
    active = sum(1 for d in hwid_devices if not d.is_blocked)
    lines = []
    for d in hwid_devices:
        icon = "🚫" if d.is_blocked else "✅"
        model = d.device_model or "—"
        os_info = f"{d.device_os} {d.os_version}" if d.device_os else "—"
        last = d.last_seen.strftime("%d.%m.%Y %H:%M")
        lines.append(f"{icon} <b>{model}</b> · {os_info}\n   <i>последний визит: {last}</i>")
    await callback.message.edit_text(
        f"📱 <b>HWID устройства подписки #{sub_id}</b> ({active}/{sub.max_devices})\n\n"
        + "\n\n".join(lines)
        + "\n\n<i>Нажмите на устройство чтобы заблокировать/разблокировать.</i>",
        parse_mode="HTML",
        reply_markup=admin_hwid_devices_kb(hwid_devices, sub_id, chat_id),
    )


# ── Написать пользователю ───────────────────────────────────────

@router.callback_query(F.data.startswith("adm:user:msg:"))
async def cb_msg_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(callback.data.split(":")[3])
    await state.update_data(target_chat_id=chat_id)
    await state.set_state(AdminStates.messaging_user)
    await callback.message.answer("✏️ Введите сообщение для пользователя:")
    await callback.answer()


@router.message(AdminStates.messaging_user)
async def cb_msg_user_send(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target = data["target_chat_id"]
    await state.clear()
    try:
        await message.bot.send_message(
            target,
            f"💬 <b>Сообщение от поддержки:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer("✅ Сообщение отправлено.", reply_markup=back_admin_kb())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=back_admin_kb())


@router.message(Command("reply"))
async def cmd_reply(message: Message) -> None:
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        await message.answer("Использование: /reply <chat_id> текст ответа")
        return
    try:
        target_chat_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Некорректный chat_id")
        return
    try:
        await message.bot.send_message(
            target_chat_id,
            f"💬 <b>Ответ поддержки:</b>\n\n{parts[2]}",
            parse_mode="HTML",
        )
        await message.answer("✅ Ответ отправлен.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {e}")


# ── Рассылка ────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, session: AsyncSession) -> None:
    text = message.text.removeprefix("/broadcast").strip()
    if not text:
        await message.answer("Использование: /broadcast текст сообщения")
        return
    users = await get_all_users(session, limit=10000)
    sent, failed = 0, 0
    for user in users:
        try:
            await message.bot.send_message(user.chat_id, text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")
