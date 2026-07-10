import logging
import secrets
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline import back_to_main_kb, device_count_kb, payment_method_kb, plans_kb
from database.queries import (
    activate_subscription,
    add_device,
    clear_hwid_devices,
    create_crypto_pending,
    create_payment,
    create_subscription,
    extend_subscription,
    get_active_plans,
    get_or_create_user,
    get_plan_by_id,
    get_setting,
    get_user_by_chat_id,
    get_user_subscription,
    remove_all_devices,
    update_subscription_devices,
)
from payments.crypto import create_invoice as crypto_create_invoice
from payments.stars import add_device_invoice, extend_sub_invoice, new_sub_invoice
from payments.yookassa import extend_sub_invoice as yk_extend_invoice
from payments.yookassa import new_sub_invoice as yk_new_invoice
from vpn.manager import (
    add_xray_users,
    calc_price,
    calc_price_usd,
    calc_upgrade_cost,
    generate_uuid,
    remove_xray_users,
)
from config import build_sub_url

logger = logging.getLogger(__name__)
router = Router()


class BuyStates(StatesGroup):
    entering_device_count = State()   # для action=new
    choosing_payment = State()
    paying = State()
    entering_extra_devices = State()  # для action=add_device


# ── Купить / Продлить ───────────────────────────────────────────

@router.callback_query(F.data == "buy:new")
async def show_plans_new(callback: CallbackQuery, session: AsyncSession) -> None:
    plans = await get_active_plans(session)
    if not plans:
        await callback.answer("Тарифы временно недоступны.", show_alert=True)
        return
    await callback.message.edit_text(
        "🛒 <b>Новая подписка</b>\n\n"
        "Одна подписка включает любое количество устройств.\n"
        "Цена за устройство снижается при большем количестве.\n\n"
        "Выберите срок подписки:",
        parse_mode="HTML",
        reply_markup=plans_kb(plans, action="new"),
    )
    await callback.answer()


@router.callback_query(F.data == "buy:extend")
async def show_plans_extend(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    if not sub:
        await callback.answer("У вас нет подписки.", show_alert=True)
        return
    plans = await get_active_plans(session)
    if not plans:
        await callback.answer("Тарифы временно недоступны.", show_alert=True)
        return
    await callback.message.edit_text(
        f"🔄 <b>Продление подписки</b>\n\n"
        f"Устройств: <b>{sub.max_devices}</b>\n\n"
        "Выберите срок продления:",
        parse_mode="HTML",
        reply_markup=plans_kb(plans, action="extend"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plan:new:"))
async def select_plan_new(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    plan_id = int(callback.data.split(":")[2])
    plan = await get_plan_by_id(session, plan_id)
    if not plan or not plan.is_active:
        await callback.answer("Этот тариф недоступен.", show_alert=True)
        return
    await state.update_data(plan_id=plan_id, plan_days=plan.days, action="new",
                            base_price=plan.stars_price,
                            rub_kopeks=plan.rub_kopeks, usdt_price=plan.usdt_price)
    await state.set_state(BuyStates.entering_device_count)
    await callback.message.edit_text(
        f"📅 <b>{plan.label}</b>\n\n"
        f"Базовая цена: <b>{plan.stars_price} ⭐</b> за устройство\n\n"
        "Сколько устройств хотите подключить?",
        parse_mode="HTML",
        reply_markup=device_count_kb("new"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plan:extend:"))
async def select_plan_extend(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    plan_id = int(callback.data.split(":")[2])
    plan = await get_plan_by_id(session, plan_id)
    if not plan or not plan.is_active:
        await callback.answer("Этот тариф недоступен.", show_alert=True)
        return

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

    total_stars = calc_price(sub.max_devices, plan.stars_price)
    total_rub = calc_price(sub.max_devices, plan.rub_kopeks) if plan.rub_kopeks else None
    total_usdt = calc_price_usd(sub.max_devices, float(plan.usdt_price)) if plan.usdt_price else None

    await state.update_data(
        plan_id=plan_id, plan_days=plan.days, action="extend",
        device_count=sub.max_devices,
        total_stars=total_stars, total_rub=total_rub, total_usdt=total_usdt,
    )
    await state.set_state(BuyStates.choosing_payment)

    stars_on, yookassa_on, crypto_on = await _get_enabled_methods(session)
    await callback.message.edit_text(
        f"🔄 <b>Продление — {plan.label}</b>\n\n"
        f"Устройств: <b>{sub.max_devices}</b>\n"
        f"Итого: <b>{total_stars} ⭐</b>\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=payment_method_kb(
            total_stars, total_rub, total_usdt,
            stars_on, yookassa_on, crypto_on,
            back_callback="buy:extend",
        ),
    )
    await callback.answer()


# ── Выбор количества устройств (для new) ────────────────────────

@router.callback_query(BuyStates.entering_device_count, F.data.startswith("devcnt:new:"))
async def process_device_count(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    n = int(callback.data.split(":")[2])

    data = await state.get_data()
    base_price = data["base_price"]
    plan_days = data["plan_days"]

    total_stars = calc_price(n, base_price)
    total_rub = calc_price(n, data["rub_kopeks"]) if data.get("rub_kopeks") else None
    total_usdt = calc_price_usd(n, float(data["usdt_price"])) if data.get("usdt_price") else None

    await state.update_data(device_count=n, total_stars=total_stars, total_rub=total_rub, total_usdt=total_usdt)
    await state.set_state(BuyStates.choosing_payment)

    stars_on, yookassa_on, crypto_on = await _get_enabled_methods(session)

    per_device = round(total_stars / n)
    await callback.message.edit_text(
        f"💰 <b>Итого за {plan_days} дней, {n} устройств</b>\n\n"
        f"Цена за устройство: <b>{per_device} ⭐</b>\n"
        f"Итого: <b>{total_stars} ⭐</b>\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=payment_method_kb(
            total_stars, total_rub, total_usdt,
            stars_on, yookassa_on, crypto_on,
        ),
    )
    await callback.answer()


# ── Добавить устройство ─────────────────────────────────────────

@router.callback_query(F.data == "sub:add_device")
async def add_device_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    if not sub or not sub.is_active:
        await callback.answer("Нет активной подписки.", show_alert=True)
        return
    await state.update_data(action="add_device", sub_id=sub.id)
    await state.set_state(BuyStates.entering_extra_devices)
    await callback.message.edit_text(
        f"➕ <b>Добавить устройства</b>\n\n"
        f"Текущее количество: <b>{sub.max_devices}</b>\n\n"
        "Сколько устройств добавить?",
        parse_mode="HTML",
        reply_markup=device_count_kb("add"),
    )
    await callback.answer()


@router.callback_query(BuyStates.entering_extra_devices, F.data.startswith("devcnt:add:"))
async def process_extra_devices(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    extra = int(callback.data.split(":")[2])

    user = await get_or_create_user(
        session,
        callback.from_user.id,
        callback.from_user.username or "",
        callback.from_user.full_name or "",
    )
    sub = await get_user_subscription(session, user.id)
    if not sub or not sub.is_active:
        await state.clear()
        await callback.answer("Нет активной подписки.", show_alert=True)
        return

    # У подписок, выданных админом или купленных до апдейта, базовая цена
    # может быть не заполнена — восстанавливаем её из тарифа с тем же сроком.
    base_price = sub.base_device_price
    if not base_price:
        plans = await get_active_plans(session)
        match = next((p for p in plans if p.days == sub.plan_days), None)
        if not match:
            await state.clear()
            await callback.answer(
                "Добавление устройств недоступно для этой подписки. Обратитесь в поддержку.",
                show_alert=True,
            )
            return
        base_price = match.stars_price
        sub.base_device_price = base_price
        await session.commit()

    remaining_days = max(0, (sub.expires_at - datetime.utcnow()).days)
    cost = calc_upgrade_cost(sub.max_devices, sub.max_devices + extra, base_price, sub.plan_days, remaining_days)

    await state.update_data(extra_devices=extra, total_stars=cost, plan_days=sub.plan_days)
    await state.set_state(BuyStates.choosing_payment)

    stars_on, yookassa_on, crypto_on = await _get_enabled_methods(session)
    await callback.message.edit_text(
        f"➕ <b>+{extra} устройств</b>\n\n"
        f"Остаток подписки: <b>{remaining_days} дн.</b>\n"
        f"Доплата: <b>{cost} ⭐</b>\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=payment_method_kb(
            cost, None, None,
            stars_on, yookassa_on, crypto_on,
            back_callback="profile",
        ),
    )
    await callback.answer()


# ── Выбор способа оплаты ────────────────────────────────────────

@router.callback_query(BuyStates.choosing_payment, F.data == "pm:na")
async def payment_method_unavailable(callback: CallbackQuery) -> None:
    await callback.answer("Этот способ оплаты недоступен.", show_alert=True)


@router.callback_query(BuyStates.choosing_payment, F.data.startswith("pm:"))
async def payment_method_chosen(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    method = callback.data[3:]
    await state.update_data(payment_method=method)
    data = await state.get_data()
    action = data["action"]
    plan_days = data.get("plan_days", 30)
    device_count = data.get("device_count", 1)
    extra_devices = data.get("extra_devices", 0)
    total_stars = data["total_stars"]

    plan = await get_plan_by_id(session, data["plan_id"]) if "plan_id" in data else None

    error = await _send_payment(
        bot=bot,
        chat_id=callback.message.chat.id,
        method=method,
        plan=plan,
        action=action,
        plan_days=plan_days,
        device_count=device_count,
        extra_devices=extra_devices,
        total_stars=total_stars,
        session=session,
        state=state,
    )
    if error:
        await callback.message.edit_text(error, reply_markup=back_to_main_kb())
    await callback.answer()


async def _send_payment(
    bot: Bot,
    chat_id: int,
    method: str,
    plan,
    action: str,
    plan_days: int,
    device_count: int,
    extra_devices: int,
    total_stars: int,
    session: AsyncSession,
    state: FSMContext,
) -> str | None:
    data = await state.get_data()

    if method == "stars":
        await state.set_state(BuyStates.paying)
        if action == "new":
            await bot.send_invoice(
                chat_id=chat_id,
                **new_sub_invoice(plan.label, total_stars, plan_days, device_count, plan.stars_price),
            )
        elif action == "extend":
            await bot.send_invoice(
                chat_id=chat_id,
                **extend_sub_invoice(plan.label, total_stars, plan_days),
            )
        elif action == "add_device":
            await bot.send_invoice(
                chat_id=chat_id,
                **add_device_invoice(total_stars, extra_devices),
            )

    elif method == "yookassa":
        token = await get_setting(session, "payment_yookassa_token", "")
        if not token:
            return "❌ ЮKassa временно недоступна."
        if action == "add_device":
            return "❌ Доплата за устройства доступна только через Telegram Stars."
        if not plan or not plan.rub_kopeks:
            return "❌ Цена в рублях не задана для этого тарифа."
        total_rub = data.get("total_rub")
        if not total_rub:
            return "❌ Цена в рублях не рассчитана."
        await state.set_state(BuyStates.paying)
        if action == "new":
            invoice_data = yk_new_invoice(plan, total_rub, device_count, plan.stars_price, token)
        else:
            invoice_data = yk_extend_invoice(plan, total_rub, token)
        await bot.send_invoice(chat_id=chat_id, **invoice_data)

    elif method == "crypto":
        token = await get_setting(session, "payment_crypto_token", "")
        if not token:
            return "❌ Крипто-оплата временно недоступна."
        total_usdt = data.get("total_usdt")
        if not total_usdt:
            return "❌ Цена в USDT не рассчитана для этого тарифа."

        user = await get_user_by_chat_id(session, chat_id)
        sub = await get_user_subscription(session, user.id) if user else None

        try:
            invoice_data = await crypto_create_invoice(token, total_usdt, f"VPN — {plan_days} дн.")
        except Exception as e:
            logger.error("CryptoPay error: %s", e)
            return "❌ Ошибка при создании крипто-платежа."

        await create_crypto_pending(
            session,
            cryptopay_invoice_id=invoice_data["invoice_id"],
            user_chat_id=chat_id,
            action=action,
            plan_days=plan_days,
            device_count=device_count if action != "add_device" else extra_devices,
            base_device_price=plan.stars_price if plan else 0,
            asset="USD",
            subscription_id=sub.id if sub else None,
        )

        b = InlineKeyboardBuilder()
        b.button(text="₮ Оплатить криптой", url=invoice_data["pay_url"])
        b.adjust(1)
        await bot.send_message(
            chat_id,
            f"₮ <b>Оплата через CryptoPay</b>\n\nСумма: <b>${total_usdt}</b>\n"
            "После оплаты подписка будет создана автоматически (до 5 минут).",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
        await state.clear()

    return None


# ── Telegram Payments (Stars / ЮKassa) ──────────────────────────
#
# Все данные заказа зашиты в payload инвойса, а не в FSM:
#   new:{plan_days}:{device_count}:{base_price} | extend:{plan_days} | add_device:{extra}
# Так оплата корректно обрабатывается даже после рестарта бота.

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, session: AsyncSession) -> None:
    ok = False
    parts = (query.invoice_payload or "").split(":")
    try:
        if parts[0] == "new" and len(parts) == 4:
            ok = int(parts[1]) > 0 and int(parts[2]) > 0 and int(parts[3]) >= 0
        elif parts[0] in ("extend", "add_device") and len(parts) == 2 and int(parts[1]) > 0:
            user = await get_user_by_chat_id(session, query.from_user.id)
            sub = await get_user_subscription(session, user.id) if user else None
            ok = sub is not None
    except (ValueError, IndexError):
        ok = False

    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(
            ok=False,
            error_message="Заказ устарел. Начните покупку заново через /start.",
        )


@router.message(F.successful_payment)
async def payment_success(message: Message, state: FSMContext, session: AsyncSession) -> None:
    payment = message.successful_payment
    await state.clear()

    payment_method = "stars" if payment.currency == "XTR" else "yookassa"
    parts = (payment.invoice_payload or "").split(":")
    action = parts[0]

    user = await get_or_create_user(
        session,
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or "",
    )

    try:
        if action == "new":
            plan_days, device_count, base_price = int(parts[1]), int(parts[2]), int(parts[3])
            sub = await get_user_subscription(session, user.id)

            if sub:
                # Перевыпуск: удаляем старые устройства и HWID, обновляем подписку
                old_uuids = await remove_all_devices(session, sub.id)
                await remove_xray_users(old_uuids)
                await clear_hwid_devices(session, sub.id)
                sub.plan_days = plan_days
                sub.max_devices = device_count
                sub.base_device_price = base_price
                sub.expires_at = datetime.utcnow() + timedelta(days=plan_days)
                sub.is_active = False
                sub.reminder_sent = False
                sub.sub_token = secrets.token_urlsafe(24)
                await session.commit()
                sub_id = sub.id
            else:
                sub = await create_subscription(
                    session, user.id, plan_days, device_count, base_price, is_active=False
                )
                sub_id = sub.id

            uuids = [generate_uuid() for _ in range(device_count)]
            for i, u in enumerate(uuids, 1):
                await add_device(session, sub_id, u, f"Устройство {i}")
            await add_xray_users(uuids)
            await activate_subscription(session, sub_id)

            await create_payment(
                session, user.id, sub_id,
                amount=str(payment.total_amount),
                currency=payment.currency,
                payment_method=payment_method,
                plan_days=plan_days,
                charge_id=payment.telegram_payment_charge_id,
            )

            sub = await get_user_subscription(session, user.id)
            sub_url = build_sub_url(sub.sub_token)
            await message.answer(
                f"✅ <b>Подписка активирована!</b>\n\n"
                f"Устройств: <b>{device_count}</b>\n"
                f"Действует до: <b>{sub.expires_at.strftime('%d.%m.%Y')}</b>\n\n"
                f"Добавьте этот URL в happ как подписку:\n\n"
                f"<code>{sub_url}</code>\n\n"
                f"<i>В happ: + → Добавить подписку → вставьте URL</i>",
                parse_mode="HTML",
            )

        elif action == "extend":
            plan_days = int(parts[1])
            sub = await get_user_subscription(session, user.id)
            if not sub:
                raise ValueError("Подписка не найдена")
            sub = await extend_subscription(session, sub.id, plan_days)
            await add_xray_users([d.xray_uuid for d in sub.devices])
            await create_payment(
                session, user.id, sub.id,
                amount=str(payment.total_amount),
                currency=payment.currency,
                payment_method=payment_method,
                plan_days=plan_days,
                charge_id=payment.telegram_payment_charge_id,
            )
            await message.answer(
                f"✅ <b>Подписка продлена!</b>\n\n"
                f"Новая дата окончания: <b>{sub.expires_at.strftime('%d.%m.%Y')}</b>",
                parse_mode="HTML",
            )

        elif action == "add_device":
            extra_devices = int(parts[1])
            sub = await get_user_subscription(session, user.id)
            if not sub:
                raise ValueError("Подписка не найдена")
            new_uuids = [generate_uuid() for _ in range(extra_devices)]
            for i, u in enumerate(new_uuids, sub.max_devices + 1):
                await add_device(session, sub.id, u, f"Устройство {i}")
            await add_xray_users(new_uuids)
            await update_subscription_devices(session, sub.id, sub.max_devices + extra_devices)
            await create_payment(
                session, user.id, sub.id,
                amount=str(payment.total_amount),
                currency=payment.currency,
                payment_method=payment_method,
                plan_days=sub.plan_days,
                charge_id=payment.telegram_payment_charge_id,
            )
            await message.answer(
                f"✅ <b>Добавлено {extra_devices} устройств!</b>\n\n"
                f"Теперь у вас <b>{sub.max_devices + extra_devices}</b> устройств.\n"
                f"Обновите подписку в happ.",
                parse_mode="HTML",
            )

        else:
            raise ValueError(f"Неизвестный payload: {payment.invoice_payload!r}")

    except Exception as e:
        logger.exception("Ошибка после оплаты (payload=%s): %s", payment.invoice_payload, e)
        await message.answer(
            "⚠️ Оплата прошла, но произошла ошибка.\n"
            "Обратитесь в поддержку — всё будет исправлено вручную."
        )


# ── Утилиты ─────────────────────────────────────────────────────

async def _get_enabled_methods(session: AsyncSession) -> tuple[bool, bool, bool]:
    stars = await get_setting(session, "payment_stars_enabled", "1") == "1"
    yookassa = await get_setting(session, "payment_yookassa_enabled", "0") == "1"
    crypto = await get_setting(session, "payment_crypto_enabled", "0") == "1"
    return stars, yookassa, crypto


# Кнопки покупки без подходящего FSM-состояния (например, после рестарта бота).
# Регистрируется последним, поэтому срабатывает только когда state-хэндлеры не подошли.
@router.callback_query(F.data.startswith(("devcnt:", "pm:")))
async def stale_purchase_callback(callback: CallbackQuery) -> None:
    await callback.answer("Сессия покупки устарела. Начните заново.", show_alert=True)


