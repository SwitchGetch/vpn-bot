from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import HwidDevice, Plan, Subscription


def main_menu_kb(has_subscription: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔑 Моя подписка", callback_data="profile")
    if has_subscription:
        b.button(text="🔄 Продлить", callback_data="buy:extend")
    else:
        b.button(text="🛒 Купить подписку", callback_data="buy:new")
    b.button(text="✉️ Поддержка", callback_data="support")
    b.button(text="ℹ️ Помощь", callback_data="help")
    b.adjust(2, 2)
    return b.as_markup()


def plans_kb(plans: list[Plan], action: str = "new") -> InlineKeyboardMarkup:
    """action: new | extend"""
    b = InlineKeyboardBuilder()
    for plan in plans:
        b.button(
            text=f"{plan.label} — от {plan.stars_price} ⭐/устр.",
            callback_data=f"plan:{action}:{plan.id}",
        )
    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def device_count_kb(action: str) -> InlineKeyboardMarkup:
    """Кнопки выбора количества устройств. action: new | add"""
    b = InlineKeyboardBuilder()
    for n in range(1, 7):
        label = f"+{n}" if action == "add" else str(n)
        b.button(text=label, callback_data=f"devcnt:{action}:{n}")
    b.button(text="◀️ Назад", callback_data="profile" if action == "add" else "back_main")
    b.adjust(3, 3, 1)
    return b.as_markup()


def payment_method_kb(
    stars_amount: int,
    rub_amount: int | None,
    usdt_amount: str | None,
    stars_on: bool = True,
    yookassa_on: bool = False,
    crypto_on: bool = False,
    back_callback: str = "back_main",
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()

    if yookassa_on and rub_amount:
        b.button(text=f"💳 Картой — {rub_amount // 100} ₽", callback_data="pm:yookassa")
    else:
        b.button(text="💳 Картой (ЮKassa) — недоступно", callback_data="pm:na")

    if stars_on:
        b.button(text=f"⭐ Telegram Stars — {stars_amount} ★", callback_data="pm:stars")
    else:
        b.button(text="⭐ Telegram Stars — недоступно", callback_data="pm:na")

    if crypto_on and usdt_amount:
        b.button(text=f"₮ Крипто — ${usdt_amount}", callback_data="pm:crypto")
    else:
        b.button(text="₮ Крипто (CryptoPay) — недоступно", callback_data="pm:na")

    b.button(text="◀️ Назад", callback_data=back_callback)
    b.adjust(1)
    return b.as_markup()


def subscription_kb(sub: Subscription) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 Subscription URL", callback_data="sub:url")
    b.button(text="📱 Мои устройства", callback_data="sub:devices")
    b.button(text="➕ Добавить устройство", callback_data="sub:add_device")
    b.button(text="🔄 Продлить", callback_data="buy:extend")
    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def hwid_devices_kb(hwid_devices: list[HwidDevice]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in hwid_devices:
        icon = "🚫" if d.is_blocked else "📱"
        label = d.device_model or "Устройство"
        if d.device_os:
            label += f" ({d.device_os})"
        b.button(
            text=f"{icon} {label[:30]}",
            callback_data=f"hwid:kick:{d.id}",
        )
    b.button(text="◀️ Назад", callback_data="profile")
    b.adjust(1)
    return b.as_markup()


def back_to_main_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Главное меню", callback_data="back_main")
    return b.as_markup()


def back_to_profile_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Моя подписка", callback_data="profile")
    return b.as_markup()
