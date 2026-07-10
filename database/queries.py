import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BotSetting, CryptoPendingInvoice, Device, HwidDevice, Payment, Plan, Subscription, User


# ── Users ───────────────────────────────────────────────────────

async def get_or_create_user(
    session: AsyncSession, chat_id: int, username: str, full_name: str
) -> User:
    result = await session.execute(select(User).where(User.chat_id == chat_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(chat_id=chat_id, username=username, full_name=full_name)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def get_user_by_chat_id(session: AsyncSession, chat_id: int) -> User | None:
    result = await session.execute(select(User).where(User.chat_id == chat_id))
    return result.scalar_one_or_none()


async def get_all_users(session: AsyncSession, limit: int = 50, offset: int = 0) -> list[User]:
    result = await session.execute(
        select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar() or 0


async def set_user_banned(session: AsyncSession, chat_id: int, banned: bool) -> None:
    await session.execute(update(User).where(User.chat_id == chat_id).values(is_banned=banned))
    await session.commit()


# ── Subscriptions ────────────────────────────────────────────────

async def get_user_subscription(session: AsyncSession, user_id: int) -> Subscription | None:
    result = await session.execute(select(Subscription).where(Subscription.user_id == user_id))
    return result.scalar_one_or_none()


async def get_subscription_by_token(session: AsyncSession, token: str) -> Subscription | None:
    result = await session.execute(select(Subscription).where(Subscription.sub_token == token))
    return result.scalar_one_or_none()


async def get_subscription_by_id(session: AsyncSession, sub_id: int) -> Subscription | None:
    result = await session.execute(select(Subscription).where(Subscription.id == sub_id))
    return result.scalar_one_or_none()


async def create_subscription(
    session: AsyncSession,
    user_id: int,
    plan_days: int,
    max_devices: int,
    base_device_price: int,
    name: str = "Моя подписка",
    is_active: bool = True,
) -> Subscription:
    sub = Subscription(
        user_id=user_id,
        name=name,
        plan_days=plan_days,
        max_devices=max_devices,
        base_device_price=base_device_price,
        sub_token=secrets.token_urlsafe(24),
        expires_at=datetime.utcnow() + timedelta(days=plan_days),
        is_active=is_active,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


async def activate_subscription(session: AsyncSession, sub_id: int) -> None:
    await session.execute(update(Subscription).where(Subscription.id == sub_id).values(is_active=True))
    await session.commit()


async def extend_subscription(session: AsyncSession, sub_id: int, days: int) -> Subscription:
    result = await session.execute(select(Subscription).where(Subscription.id == sub_id))
    sub = result.scalar_one()
    base = max(sub.expires_at, datetime.utcnow())
    sub.expires_at = base + timedelta(days=days)
    sub.is_active = True
    sub.reminder_sent = False
    await session.commit()
    await session.refresh(sub)
    return sub


async def deactivate_subscription(session: AsyncSession, sub_id: int) -> None:
    await session.execute(update(Subscription).where(Subscription.id == sub_id).values(is_active=False))
    await session.commit()


async def update_subscription_devices(
    session: AsyncSession, sub_id: int, max_devices: int
) -> Subscription:
    await session.execute(
        update(Subscription).where(Subscription.id == sub_id).values(max_devices=max_devices)
    )
    await session.commit()
    result = await session.execute(select(Subscription).where(Subscription.id == sub_id))
    return result.scalar_one()


async def get_expired_subscriptions(session: AsyncSession) -> list[Subscription]:
    result = await session.execute(
        select(Subscription).where(
            Subscription.is_active == True,
            Subscription.expires_at < datetime.utcnow(),
        )
    )
    return list(result.scalars().all())


async def get_expiring_soon_subscriptions(session: AsyncSession, days: int = 3) -> list[Subscription]:
    now = datetime.utcnow()
    result = await session.execute(
        select(Subscription).where(
            Subscription.is_active == True,
            Subscription.expires_at > now,
            Subscription.expires_at < now + timedelta(days=days),
            Subscription.reminder_sent == False,
        )
    )
    return list(result.scalars().all())


async def mark_reminder_sent(session: AsyncSession, sub_id: int) -> None:
    await session.execute(
        update(Subscription).where(Subscription.id == sub_id).values(reminder_sent=True)
    )
    await session.commit()


async def get_all_active_subscriptions(session: AsyncSession) -> list[Subscription]:
    result = await session.execute(select(Subscription).where(Subscription.is_active == True))
    return list(result.scalars().all())


# ── Devices ─────────────────────────────────────────────────────

async def add_device(
    session: AsyncSession,
    subscription_id: int,
    xray_uuid: str,
    device_name: str = "Устройство",
) -> Device:
    device = Device(
        subscription_id=subscription_id,
        xray_uuid=xray_uuid,
        device_name=device_name,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


async def remove_all_devices(session: AsyncSession, subscription_id: int) -> list[str]:
    """Удаляет все устройства подписки, возвращает список xray_uuid."""
    result = await session.execute(
        select(Device).where(Device.subscription_id == subscription_id)
    )
    devices = result.scalars().all()
    uuids = [d.xray_uuid for d in devices]
    for device in devices:
        await session.delete(device)
    await session.commit()
    return uuids


# ── HWID Devices ────────────────────────────────────────────────

async def get_hwid_device(
    session: AsyncSession, subscription_id: int, hwid: str
) -> HwidDevice | None:
    result = await session.execute(
        select(HwidDevice).where(
            HwidDevice.subscription_id == subscription_id,
            HwidDevice.hwid == hwid,
        )
    )
    return result.scalar_one_or_none()


async def get_hwid_devices_for_sub(
    session: AsyncSession, subscription_id: int
) -> list[HwidDevice]:
    result = await session.execute(
        select(HwidDevice)
        .where(HwidDevice.subscription_id == subscription_id)
        .order_by(HwidDevice.last_seen.desc())
    )
    return list(result.scalars().all())


async def register_hwid_device(
    session: AsyncSession,
    subscription_id: int,
    hwid: str,
    device_model: str = "",
    device_os: str = "",
    os_version: str = "",
    user_agent: str = "",
) -> HwidDevice:
    device = HwidDevice(
        subscription_id=subscription_id,
        hwid=hwid,
        device_model=device_model or None,
        device_os=device_os or None,
        os_version=os_version or None,
        user_agent=user_agent or None,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


async def touch_hwid_device(session: AsyncSession, hwid_device_id: int) -> None:
    await session.execute(
        update(HwidDevice)
        .where(HwidDevice.id == hwid_device_id)
        .values(last_seen=datetime.utcnow())
    )
    await session.commit()


async def block_hwid_device(session: AsyncSession, hwid_device_id: int, blocked: bool) -> None:
    await session.execute(
        update(HwidDevice).where(HwidDevice.id == hwid_device_id).values(is_blocked=blocked)
    )
    await session.commit()


async def delete_hwid_device(session: AsyncSession, hwid_device_id: int) -> None:
    result = await session.execute(select(HwidDevice).where(HwidDevice.id == hwid_device_id))
    obj = result.scalar_one_or_none()
    if obj:
        await session.delete(obj)
        await session.commit()


async def clear_hwid_devices(session: AsyncSession, subscription_id: int) -> None:
    """Удаляет все HWID устройства подписки (например, при перевыпуске)."""
    await session.execute(delete(HwidDevice).where(HwidDevice.subscription_id == subscription_id))
    await session.commit()


async def get_hwid_device_by_id(session: AsyncSession, hwid_device_id: int) -> HwidDevice | None:
    result = await session.execute(select(HwidDevice).where(HwidDevice.id == hwid_device_id))
    return result.scalar_one_or_none()


# ── Payments ────────────────────────────────────────────────────

async def create_payment(
    session: AsyncSession,
    user_id: int,
    subscription_id: int | None,
    amount: str,
    currency: str,
    payment_method: str,
    plan_days: int,
    charge_id: str = "",
) -> Payment:
    payment = Payment(
        user_id=user_id,
        subscription_id=subscription_id,
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        plan_days=plan_days,
        charge_id=charge_id,
    )
    session.add(payment)
    await session.commit()
    return payment


# ── Plans ───────────────────────────────────────────────────────

async def get_active_plans(session: AsyncSession) -> list[Plan]:
    result = await session.execute(
        select(Plan).where(Plan.is_active == True).order_by(Plan.sort_order, Plan.days)
    )
    return list(result.scalars().all())


async def get_all_plans(session: AsyncSession) -> list[Plan]:
    result = await session.execute(select(Plan).order_by(Plan.sort_order, Plan.days))
    return list(result.scalars().all())


async def get_plan_by_id(session: AsyncSession, plan_id: int) -> Plan | None:
    result = await session.execute(select(Plan).where(Plan.id == plan_id))
    return result.scalar_one_or_none()


async def create_plan(
    session: AsyncSession, days: int, label: str, stars_price: int, sort_order: int = 0
) -> Plan:
    plan = Plan(days=days, label=label, stars_price=stars_price, sort_order=sort_order)
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


async def update_plan(session: AsyncSession, plan_id: int, **kwargs) -> Plan:
    await session.execute(update(Plan).where(Plan.id == plan_id).values(**kwargs))
    await session.commit()
    result = await session.execute(select(Plan).where(Plan.id == plan_id))
    return result.scalar_one()


async def delete_plan(session: AsyncSession, plan_id: int) -> None:
    result = await session.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if plan:
        await session.delete(plan)
        await session.commit()


# ── CryptoPay pending invoices ──────────────────────────────────

async def create_crypto_pending(
    session: AsyncSession,
    cryptopay_invoice_id: int,
    user_chat_id: int,
    action: str,
    plan_days: int,
    asset: str = "USDT",
    device_count: int = 1,
    base_device_price: int = 0,
    subscription_id: int | None = None,
) -> CryptoPendingInvoice:
    obj = CryptoPendingInvoice(
        cryptopay_invoice_id=cryptopay_invoice_id,
        user_chat_id=user_chat_id,
        action=action,
        plan_days=plan_days,
        device_count=device_count,
        base_device_price=base_device_price,
        asset=asset,
        subscription_id=subscription_id,
    )
    session.add(obj)
    await session.commit()
    return obj


async def get_all_crypto_pending(session: AsyncSession) -> list[CryptoPendingInvoice]:
    result = await session.execute(select(CryptoPendingInvoice))
    return list(result.scalars().all())


async def delete_stale_crypto_pending(session: AsyncSession, max_age_hours: int = 2) -> int:
    """Удаляет неоплаченные инвойсы старше max_age_hours (сам инвойс CryptoPay живёт 1 час)."""
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    result = await session.execute(
        delete(CryptoPendingInvoice).where(CryptoPendingInvoice.created_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0


async def delete_crypto_pending(session: AsyncSession, invoice_id: int) -> None:
    result = await session.execute(
        select(CryptoPendingInvoice).where(
            CryptoPendingInvoice.cryptopay_invoice_id == invoice_id
        )
    )
    obj = result.scalar_one_or_none()
    if obj:
        await session.delete(obj)
        await session.commit()


# ── Bot settings ────────────────────────────────────────────────

async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    result = await session.execute(select(BotSetting).where(BotSetting.key == key))
    obj = result.scalar_one_or_none()
    return obj.value if obj else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    result = await session.execute(select(BotSetting).where(BotSetting.key == key))
    obj = result.scalar_one_or_none()
    if obj:
        obj.value = value
    else:
        session.add(BotSetting(key=key, value=value))
    await session.commit()


async def get_all_settings(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(BotSetting))
    return {row.key: row.value for row in result.scalars().all()}


# ── Stats ───────────────────────────────────────────────────────

async def get_stats(session: AsyncSession) -> dict:
    users_res = await session.execute(select(func.count()).select_from(User))
    active_res = await session.execute(
        select(func.count()).select_from(Subscription).where(Subscription.is_active == True)
    )
    devices_res = await session.execute(select(func.count()).select_from(Device))

    stars_amounts = await session.execute(
        select(Payment.amount).where(Payment.payment_method == "stars")
    )
    total_stars = sum(int(a) for a in stars_amounts.scalars().all())

    yookassa_res = await session.execute(
        select(func.count()).select_from(Payment).where(Payment.payment_method == "yookassa")
    )
    crypto_res = await session.execute(
        select(func.count()).select_from(Payment).where(Payment.payment_method == "crypto")
    )

    return {
        "users": users_res.scalar() or 0,
        "active_subscriptions": active_res.scalar() or 0,
        "total_devices": devices_res.scalar() or 0,
        "total_stars": total_stars,
        "yookassa_count": yookassa_res.scalar() or 0,
        "crypto_count": crypto_res.scalar() or 0,
    }
