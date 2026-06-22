import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline import back_to_main_kb, extend_plans_kb, payment_method_kb, plans_kb
from database.queries import (
    activate_config,
    create_config,
    create_crypto_pending,
    create_payment,
    delete_config,
    extend_config,
    get_active_plans,
    get_or_create_user,
    get_plan_by_id,
    get_setting,
    get_used_ips,
)
from payments.crypto import create_invoice as crypto_create_invoice
from payments.stars import extend_config_invoice as stars_extend, new_config_invoice as stars_new
from payments.yookassa import extend_config_invoice as yookassa_extend, new_config_invoice as yookassa_new
from vpn.manager import add_peer, allocate_ip, build_client_config, build_client_uri, generate_keypair, generate_psk

logger = logging.getLogger(__name__)
router = Router()


class BuyStates(StatesGroup):
    choosing_payment = State()
    entering_device_name = State()
    paying = State()  # ожидаем successful_payment от Telegram (Stars / ЮKassa)


# ── Покупка нового конфига ──────────────────────────────────────

@router.callback_query(F.data == "buy")
async def show_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    plans = await get_active_plans(session)
    if not plans:
        await callback.answer("Тарифы временно недоступны. Попробуйте позже.", show_alert=True)
        return
    await callback.message.edit_text(
        "🛒 <b>Купить ключ</b>\n\n"
        "Один ключ = одно устройство.\n"
        "После оплаты получите ключ для Amnezia VPN.\n\n"
        "Выберите тариф:",
        parse_mode="HTML",
        reply_markup=plans_kb(plans),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plan:new:"))
async def select_new_plan(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    plan_id = int(callback.data.split(":")[2])
    plan = await get_plan_by_id(session, plan_id)
    if not plan or not plan.is_active:
        await callback.answer("Этот тариф недоступен.", show_alert=True)
        return
    await state.update_data(plan_id=plan_id, plan_days=plan.days, action="new")
    await state.set_state(BuyStates.choosing_payment)

    stars_on, yookassa_on, crypto_on = await _get_enabled_methods(session)
    await callback.message.edit_text(
        f"💰 <b>{plan.label}</b>\n\nВыберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=payment_method_kb(plan, stars_on, yookassa_on, crypto_on),
    )
    await callback.answer()


# ── Продление конфига ───────────────────────────────────────────

@router.callback_query(F.data.startswith("extend:"))
async def show_extend_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    config_id = int(callback.data.split(":")[1])
    plans = await get_active_plans(session)
    if not plans:
        await callback.answer("Тарифы временно недоступны.", show_alert=True)
        return
    await callback.message.edit_text(
        "🔄 <b>Продление ключа</b>\n\nВыберите тариф:",
        parse_mode="HTML",
        reply_markup=extend_plans_kb(config_id, plans),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plan:extend:"))
async def select_extend_plan(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    parts = callback.data.split(":")
    config_id = int(parts[2])
    plan_id = int(parts[3])
    plan = await get_plan_by_id(session, plan_id)
    if not plan or not plan.is_active:
        await callback.answer("Этот тариф недоступен.", show_alert=True)
        return
    await state.update_data(config_id=config_id, plan_id=plan_id, plan_days=plan.days, action="extend")
    await state.set_state(BuyStates.choosing_payment)

    stars_on, yookassa_on, crypto_on = await _get_enabled_methods(session)
    await callback.message.edit_text(
        f"💰 <b>{plan.label}</b>\n\nВыберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=payment_method_kb(
            plan, stars_on, yookassa_on, crypto_on,
            back_callback=f"extend:{config_id}",
        ),
    )
    await callback.answer()


# ── Выбор способа оплаты ───────────────────────────────────────

@router.callback_query(BuyStates.choosing_payment, F.data == "pm:na")
async def payment_method_unavailable(callback: CallbackQuery) -> None:
    await callback.answer("Этот способ оплаты недоступен для данного тарифа.", show_alert=True)


@router.callback_query(BuyStates.choosing_payment, F.data.startswith("pm:"))
async def payment_method_chosen(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    method = callback.data[3:]  # "stars" / "yookassa" / "crypto"
    await state.update_data(payment_method=method)
    data = await state.get_data()
    action = data.get("action", "new")

    if action == "new":
        await state.set_state(BuyStates.entering_device_name)
        await callback.message.edit_text(
            "✏️ Введите название устройства:\n\n"
            "<i>Примеры: iPhone, Ноутбук, Работа, Android</i>",
            parse_mode="HTML",
            reply_markup=back_to_main_kb(),
        )
    else:
        plan = await get_plan_by_id(session, data["plan_id"])
        error = await _send_payment(
            bot=bot,
            chat_id=callback.message.chat.id,
            method=method,
            plan=plan,
            device_name=None,
            action="extend",
            config_id=data.get("config_id"),
            session=session,
            state=state,
        )
        if error:
            await callback.message.edit_text(error, reply_markup=back_to_main_kb())

    await callback.answer()


@router.message(BuyStates.entering_device_name)
async def process_device_name(message: Message, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    device_name = message.text.strip()[:32]
    data = await state.get_data()
    await state.update_data(device_name=device_name)

    plan = await get_plan_by_id(session, data["plan_id"])
    error = await _send_payment(
        bot=bot,
        chat_id=message.chat.id,
        method=data.get("payment_method", "stars"),
        plan=plan,
        device_name=device_name,
        action="new",
        config_id=None,
        session=session,
        state=state,
    )
    if error:
        await message.answer(error, reply_markup=back_to_main_kb())


# ── Отправка платёжного инвойса ─────────────────────────────────

async def _send_payment(
    bot: Bot,
    chat_id: int,
    method: str,
    plan,
    device_name: str | None,
    action: str,
    config_id: int | None,
    session: AsyncSession,
    state: FSMContext,
) -> str | None:
    """Отправляет инвойс выбранным методом. Возвращает текст ошибки или None."""

    if method == "stars":
        await state.set_state(BuyStates.paying)
        if action == "new":
            await bot.send_invoice(chat_id=chat_id, **stars_new(plan.label, plan.stars_price, plan.days, device_name))
        else:
            await bot.send_invoice(chat_id=chat_id, **stars_extend(plan.label, plan.stars_price, plan.days, config_id))

    elif method == "yookassa":
        token = await get_setting(session, "payment_yookassa_token", "")
        if not token:
            return "❌ ЮKassa временно недоступна. Попробуйте другой способ оплаты."
        if not plan.rub_kopeks:
            return "❌ Цена в рублях для этого тарифа не задана. Попробуйте другой способ оплаты."
        await state.set_state(BuyStates.paying)
        if action == "new":
            await bot.send_invoice(chat_id=chat_id, **yookassa_new(plan, device_name, token))
        else:
            await bot.send_invoice(chat_id=chat_id, **yookassa_extend(plan, config_id, token))

    elif method == "crypto":
        token = await get_setting(session, "payment_crypto_token", "")
        if not token:
            return "❌ Крипто-оплата временно недоступна. Попробуйте другой способ оплаты."
        if not plan.usdt_price:
            return "❌ Цена в USDT для этого тарифа не задана. Попробуйте другой способ оплаты."

        description = f"VPN конфиг — {plan.label}"
        if device_name:
            description += f" для {device_name}"
        try:
            invoice_data = await crypto_create_invoice(token, plan.usdt_price, description)
        except Exception as e:
            logger.error("CryptoPay createInvoice error: %s", e)
            return "❌ Ошибка при создании крипто-платежа. Попробуйте позже."

        await create_crypto_pending(
            session,
            cryptopay_invoice_id=invoice_data["invoice_id"],
            user_chat_id=chat_id,
            action=action,
            plan_days=plan.days,
            asset="USD",
            device_name=device_name,
            config_id=config_id,
        )

        b = InlineKeyboardBuilder()
        b.button(text="₮ Оплатить криптой", url=invoice_data["pay_url"])
        b.adjust(1)

        await bot.send_message(
            chat_id,
            f"₮ <b>Оплата через CryptoPay</b>\n\n"
            f"Сумма: <b>${plan.usdt_price} USD</b>\n"
            f"Тариф: <b>{plan.label}</b>\n\n"
            "Выберите удобную криптовалюту для оплаты.\n"
            "После оплаты ключ будет создан автоматически (до 5 минут).",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
        await state.clear()

    return None


# ── Обработка Telegram-платежа (Stars / ЮKassa) ─────────────────

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def payment_success(message: Message, state: FSMContext, session: AsyncSession) -> None:
    payment = message.successful_payment
    data = await state.get_data()
    await state.clear()

    action = data.get("action", "new")
    plan_days = data.get("plan_days", 30)
    payment_method = data.get("payment_method", "stars")

    user = await get_or_create_user(
        session,
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or "",
    )

    if action == "new":
        try:
            device_name = data.get("device_name", "Устройство")

            used_ips = await get_used_ips(session)
            priv_key, pub_key = generate_keypair()
            psk = generate_psk()
            peer_ip = allocate_ip(used_ips)
            config_text = build_client_config(priv_key, peer_ip, psk)
            config = await create_config(
                session, user.id, device_name,
                pub_key, priv_key, peer_ip, config_text, plan_days,
                psk=psk, is_active=False,
            )
            try:
                await add_peer(pub_key, peer_ip, psk)
            except Exception:
                await delete_config(session, config.id)
                raise
            await activate_config(session, config.id)
            await create_payment(
                session, user.id, config.id,
                amount=str(payment.total_amount),
                currency=payment.currency,
                payment_method=payment_method,
                plan_days=plan_days,
                charge_id=payment.telegram_payment_charge_id,
            )
            uri = build_client_uri(priv_key, pub_key, peer_ip, psk)
            await message.answer(
                f"✅ <b>Ключ готов!</b>\n\n"
                f"Устройство: <b>{device_name}</b>\n"
                f"Действителен до: <b>{config.expires_at.strftime('%d.%m.%Y')}</b>\n\n"
                f"Скопируйте ключ и вставьте в Amnezia VPN (+ → Вставить ключ):\n\n"
                f"<code>{uri}</code>",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("Ошибка создания конфига после оплаты: %s", e)
            await message.answer(
                "⚠️ Оплата прошла, но произошла ошибка при создании конфига.\n"
                "Напишите нам через кнопку ✉️ Поддержка — ключ будет выдан вручную."
            )

    elif action == "extend":
        config_id = data.get("config_id")
        try:
            config = await extend_config(session, config_id, plan_days)
            await create_payment(
                session, user.id, config.id,
                amount=str(payment.total_amount),
                currency=payment.currency,
                payment_method=payment_method,
                plan_days=plan_days,
                charge_id=payment.telegram_payment_charge_id,
            )
            await message.answer(
                f"✅ <b>Ключ продлён!</b>\n\n"
                f"Устройство: <b>{config.device_name}</b>\n"
                f"Новая дата окончания: <b>{config.expires_at.strftime('%d.%m.%Y')}</b>",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("Ошибка продления конфига: %s", e)
            await message.answer(
                "⚠️ Оплата прошла, но произошла ошибка при продлении.\n"
                "Обратитесь в поддержку."
            )


# ── Утилита ─────────────────────────────────────────────────────

async def _get_enabled_methods(session: AsyncSession) -> tuple[bool, bool, bool]:
    stars = await get_setting(session, "payment_stars_enabled", "1") == "1"
    yookassa = await get_setting(session, "payment_yookassa_enabled", "0") == "1"
    crypto = await get_setting(session, "payment_crypto_enabled", "0") == "1"
    return stars, yookassa, crypto
