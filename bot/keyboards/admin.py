from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Plan


def admin_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика",    callback_data="adm:stats")
    b.button(text="💳 Оплата",        callback_data="adm:pay")
    b.button(text="📋 Тарифы",        callback_data="adm:plans")
    b.button(text="👥 Пользователи",  callback_data="adm:users:0")
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
            text=f"{status} {plan.label} — {plan.stars_price} ⭐",
            callback_data=f"adm:plan:{plan.id}",
        )
    b.button(text="➕ Добавить тариф", callback_data="adm:plan:add")
    b.button(text="◀️ Назад",          callback_data="adm:menu")
    b.adjust(1)
    return b.as_markup()


def admin_plan_detail_kb(plan: Plan) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    toggle = "❌ Деактивировать" if plan.is_active else "✅ Активировать"
    b.button(text=toggle,                      callback_data=f"adm:plan:toggle:{plan.id}")
    b.button(text="✏️ Название",              callback_data=f"adm:plan:field:{plan.id}:label")
    b.button(text="✏️ Кол-во дней",           callback_data=f"adm:plan:field:{plan.id}:days")
    b.button(text="✏️ Цена Stars",            callback_data=f"adm:plan:field:{plan.id}:stars_price")
    b.button(text="✏️ Цена руб. (ЮKassa)",   callback_data=f"adm:plan:field:{plan.id}:rub_kopeks")
    b.button(text="✏️ Цена USDT (Крипто)",   callback_data=f"adm:plan:field:{plan.id}:usdt_price")
    b.button(text="↕️ Порядок сортировки",    callback_data=f"adm:plan:field:{plan.id}:sort_order")
    b.button(text="🗑️ Удалить тариф",        callback_data=f"adm:plan:del:{plan.id}")
    b.button(text="◀️ Назад",                 callback_data="adm:plans")
    b.adjust(1)
    return b.as_markup()


# ── Пользователи ────────────────────────────────────────────────

def admin_users_kb(users: list, page: int, total: int, per_page: int = 20) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in users:
        username = f"@{u.username}" if u.username else "—"
        active = sum(1 for c in u.configs if c.is_active)
        b.button(
            text=f"{u.full_name or username} | {active} конф.",
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


def admin_user_detail_kb(chat_id: int, is_banned: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    ban_text = "✅ Разблокировать" if is_banned else "🚫 Заблокировать"
    b.button(text=ban_text,                    callback_data=f"adm:user:ban:{chat_id}")
    b.button(text="🔑 Ключи",                  callback_data=f"adm:user:configs:{chat_id}")
    b.button(text="➕ Выдать ключ",            callback_data=f"adm:user:give:{chat_id}")
    b.button(text="✉️ Написать пользователю",  callback_data=f"adm:user:msg:{chat_id}")
    b.button(text="◀️ Назад",                  callback_data="adm:users:0")
    b.adjust(1)
    return b.as_markup()


def admin_user_configs_kb(configs: list, chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for cfg in configs:
        status = "✅" if cfg.is_active else "❌"
        expires = cfg.expires_at.strftime("%d.%m.%Y")
        b.button(
            text=f"{status} {cfg.device_name} до {expires}",
            callback_data=f"adm:cfg:{cfg.id}:{chat_id}",
        )
    b.button(text="◀️ Назад", callback_data=f"adm:user:{chat_id}")
    b.adjust(1)
    return b.as_markup()


def admin_config_detail_kb(config_id: int, is_active: bool, user_chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if is_active:
        b.button(text="❌ Отозвать ключ", callback_data=f"adm:cfg:revoke:{config_id}:{user_chat_id}")
    b.button(text="📤 Переслать ключ пользователю", callback_data=f"adm:cfg:send:{config_id}:{user_chat_id}")
    b.button(text="◀️ Назад", callback_data=f"adm:user:configs:{user_chat_id}")
    b.adjust(1)
    return b.as_markup()
