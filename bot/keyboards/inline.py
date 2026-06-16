from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Plan


def main_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔑 Мои ключи",    callback_data="profile")
    b.button(text="🛒 Купить ключ",  callback_data="buy")
    b.button(text="✉️ Поддержка",    callback_data="support")
    b.button(text="ℹ️ Помощь",       callback_data="help")
    b.adjust(2, 2)
    return b.as_markup()


def _plan_price_line(plan: Plan) -> str:
    parts = []
    if plan.rub_kopeks:
        parts.append(f"💳 {plan.rub_kopeks // 100}₽")
    parts.append(f"⭐ {plan.stars_price}")
    if plan.usdt_price:
        parts.append(f"₮ {plan.usdt_price}$")
    return " · ".join(parts)


def plans_kb(plans: list[Plan]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in plans:
        b.button(
            text=f"{plan.label} — {_plan_price_line(plan)}",
            callback_data=f"plan:new:{plan.id}",
        )
    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def extend_plans_kb(config_id: int, plans: list[Plan]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in plans:
        b.button(
            text=f"{plan.label} — {_plan_price_line(plan)}",
            callback_data=f"plan:extend:{config_id}:{plan.id}",
        )
    b.button(text="◀️ Назад", callback_data=f"config:{config_id}")
    b.adjust(1)
    return b.as_markup()


def payment_method_kb(
    plan: Plan,
    stars_on: bool = True,
    yookassa_on: bool = False,
    crypto_on: bool = False,
    back_callback: str = "buy",
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()

    if yookassa_on and plan.rub_kopeks:
        b.button(text=f"💳 Картой (ЮKassa) — {plan.rub_kopeks // 100} ₽", callback_data="pm:yookassa")
    elif yookassa_on:
        b.button(text="💳 Картой (ЮKassa) — цена не задана", callback_data="pm:na")
    else:
        b.button(text="💳 Картой (ЮKassa) — недоступно", callback_data="pm:na")

    if stars_on:
        b.button(text=f"⭐ Telegram Stars — {plan.stars_price} ★", callback_data="pm:stars")
    else:
        b.button(text="⭐ Telegram Stars — недоступно", callback_data="pm:na")

    if crypto_on and plan.usdt_price:
        b.button(text=f"₮ Крипто (CryptoPay) — ${plan.usdt_price}", callback_data="pm:crypto")
    elif crypto_on:
        b.button(text="₮ Крипто (CryptoPay) — цена не задана", callback_data="pm:na")
    else:
        b.button(text="₮ Крипто (CryptoPay) — недоступно", callback_data="pm:na")

    b.button(text="◀️ Назад", callback_data=back_callback)
    b.adjust(1)
    return b.as_markup()


def config_detail_kb(config_id: int, is_active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 Получить ключ", callback_data=f"download:{config_id}")
    if is_active:
        b.button(text="🔄 Продлить", callback_data=f"extend:{config_id}")
    b.button(text="✏️ Переименовать", callback_data=f"rename:{config_id}")
    b.button(text="◀️ Мои ключи", callback_data="profile")
    b.adjust(1)
    return b.as_markup()


def back_to_main_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Главное меню", callback_data="back_main")
    return b.as_markup()
