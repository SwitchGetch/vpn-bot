from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Plan, Subscription


def admin_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика",   callback_data="adm:stats")
    b.button(text="💳 Оплата",       callback_data="adm:pay")
    b.button(text="📋 Тарифы",       callback_data="adm:plans")
    b.button(text="👥 Пользователи", callback_data="adm:users:0")
    b.adjust(2)
    return b.as_markup()


def back_admin_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Главное меню", callback_data="adm:menu")
    return b.as_markup()


# ── Оплата ──────────────────────────────────────────────────────

def admin_payments_kb(stars: bool, yookassa: bool, crypto: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"⭐ Stars {'✅' if stars else '❌'}",       callback_data="adm:pay:stars")
    b.button(text=f"💳 ЮKassa {'✅' if yookassa else '❌'}", callback_data="adm:pay:yookassa")
    b.button(text=f"₮ Крипто {'✅' if crypto else '❌'}",    callback_data="adm:pay:crypto")
    b.button(text="◀️ Назад", callback_data="adm:menu")
    b.adjust(1)
    return b.as_markup()


def admin_payment_detail_kb(method: str, is_enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    toggle = "❌ Отключить" if is_enabled else "✅ Включить"
    b.button(text=toggle, callback_data=f"adm:pay:toggle:{method}")
    if method != "stars":
        b.button(text="✏️ Изменить токен", callback_data=f"adm:pay:token:{method}")
    b.button(text="◀️ Назад", callback_data="adm:pay")
    b.adjust(1)
    return b.as_markup()


# ── Тарифы ──────────────────────────────────────────────────────

def admin_plans_kb(plans: list[Plan]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in plans:
        status = "✅" if plan.is_active else "❌"
        b.button(
            text=f"{status} {plan.label} — {plan.stars_price} ⭐/устр.",
            callback_data=f"adm:plan:{plan.id}",
        )
    b.button(text="➕ Добавить тариф", callback_data="adm:plan:add")
    b.button(text="◀️ Назад",          callback_data="adm:menu")
    b.adjust(1)
    return b.as_markup()


def admin_plan_detail_kb(plan: Plan) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    toggle = "❌ Деактивировать" if plan.is_active else "✅ Активировать"
    b.button(text=toggle,                       callback_data=f"adm:plan:toggle:{plan.id}")
    b.button(text="✏️ Название",               callback_data=f"adm:plan:field:{plan.id}:label")
    b.button(text="✏️ Кол-во дней",            callback_data=f"adm:plan:field:{plan.id}:days")
    b.button(text="✏️ Цена Stars/устр.",       callback_data=f"adm:plan:field:{plan.id}:stars_price")
    b.button(text="✏️ Цена руб. (ЮKassa)",    callback_data=f"adm:plan:field:{plan.id}:rub_kopeks")
    b.button(text="✏️ Цена USDT (Крипто)",    callback_data=f"adm:plan:field:{plan.id}:usdt_price")
    b.button(text="↕️ Порядок сортировки",     callback_data=f"adm:plan:field:{plan.id}:sort_order")
    b.button(text="🗑️ Удалить тариф",         callback_data=f"adm:plan:del:{plan.id}")
    b.button(text="◀️ Назад",                  callback_data="adm:plans")
    b.adjust(1)
    return b.as_markup()


# ── Пользователи ────────────────────────────────────────────────

def admin_users_kb(users: list, page: int, total: int, per_page: int = 20) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in users:
        username = f"@{u.username}" if u.username else "—"
        has_sub = "🔑" if u.subscription and u.subscription.is_active else "·"
        b.button(
            text=f"{has_sub} {u.full_name or username}",
            callback_data=f"adm:user:{u.chat_id}",
        )
    nav = []
    if page > 0:
        nav.append(("◀️", f"adm:users:{page - 1}"))
    if (page + 1) * per_page < total:
        nav.append(("▶️", f"adm:users:{page + 1}"))
    for label, cd in nav:
        b.button(text=label, callback_data=cd)
    b.button(text="◀️ Назад", callback_data="adm:menu")
    b.adjust(1)
    return b.as_markup()


def admin_user_detail_kb(chat_id: int, is_banned: bool, has_sub: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    ban_text = "✅ Разблокировать" if is_banned else "🚫 Заблокировать"
    b.button(text=ban_text, callback_data=f"adm:user:ban:{chat_id}")
    if has_sub:
        b.button(text="🔑 Подписка", callback_data=f"adm:user:sub:{chat_id}")
    b.button(text="🎁 Выдать подписку",         callback_data=f"adm:user:give:{chat_id}")
    b.button(text="✉️ Написать пользователю",   callback_data=f"adm:user:msg:{chat_id}")
    b.button(text="◀️ Назад",                   callback_data="adm:users:0")
    b.adjust(1)
    return b.as_markup()


def admin_sub_detail_kb(sub: Subscription, chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if sub.is_active:
        b.button(text="❌ Деактивировать", callback_data=f"adm:sub:deactivate:{sub.id}:{chat_id}")
    else:
        b.button(text="✅ Активировать",   callback_data=f"adm:sub:activate:{sub.id}:{chat_id}")
    b.button(text="📱 HWID устройства",            callback_data=f"adm:sub:hwid:{sub.id}:{chat_id}")
    b.button(text="📤 Отправить URL пользователю", callback_data=f"adm:sub:send:{sub.id}:{chat_id}")
    b.button(text="🗑️ Удалить подписку",           callback_data=f"adm:sub:delconfirm:{sub.id}:{chat_id}")
    b.button(text="◀️ Назад",                       callback_data=f"adm:user:{chat_id}")
    b.adjust(1)
    return b.as_markup()


def admin_sub_delete_confirm_kb(sub_id: int, chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, удалить", callback_data=f"adm:sub:delete:{sub_id}:{chat_id}")
    b.button(text="◀️ Отмена",      callback_data=f"adm:user:sub:{chat_id}")
    b.adjust(1)
    return b.as_markup()


def admin_hwid_devices_kb(hwid_devices: list, sub_id: int, chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in hwid_devices:
        icon = "✅" if not d.is_blocked else "🚫"
        label = (d.device_model or "Устройство")[:20]
        if d.device_os:
            label += f" ({d.device_os})"
        b.button(
            text=f"{icon} {label}",
            callback_data=f"adm:hwid:toggle:{d.id}:{sub_id}:{chat_id}",
        )
    b.button(text="◀️ Назад", callback_data=f"adm:user:sub:{chat_id}")
    b.adjust(1)
    return b.as_markup()
