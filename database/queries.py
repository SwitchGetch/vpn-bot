from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BotSetting, Config, CryptoPendingInvoice, Payment, Plan, User


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
    await session.execute(
        update(User).where(User.chat_id == chat_id).values(is_banned=banned)
    )
    await session.commit()


# ── Configs ─────────────────────────────────────────────────────

async def get_user_configs(session: AsyncSession, user_id: int) -> list[Config]:
    result = await session.execute(
        select(Config).where(Config.user_id == user_id).order_by(Config.created_at.desc())
    )
    return list(result.scalars().all())


async def get_config_by_id(session: AsyncSession, config_id: int) -> Config | None:
    result = await session.execute(select(Config).where(Config.id == config_id))
    return result.scalar_one_or_none()


async def get_used_ips(session: AsyncSession) -> set[str]:
    result = await session.execute(select(Config.peer_ip))
    return {row[0] for row in result.fetchall()}


async def create_config(
    session: AsyncSession,
    user_id: int,
    device_name: str,
    public_key: str,
    private_key: str,
    peer_ip: str,
    config_text: str,
    plan_days: int,
) -> Config:
    config = Config(
        user_id=user_id,
        device_name=device_name,
        peer_public_key=public_key,
        peer_private_key=private_key,
        peer_ip=peer_ip,
        config_text=config_text,
        plan_days=plan_days,
        expires_at=datetime.utcnow() + timedelta(days=plan_days),
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


async def extend_config(session: AsyncSession, config_id: int, days: int) -> Config:
    result = await session.execute(select(Config).where(Config.id == config_id))
    config = result.scalar_one()
    base = max(config.expires_at, datetime.utcnow())
    config.expires_at = base + timedelta(days=days)
    config.is_active = True
    await session.commit()
    await session.refresh(config)
    return config


async def deactivate_config(session: AsyncSession, config_id: int) -> None:
    await session.execute(update(Config).where(Config.id == config_id).values(is_active=False))
    await session.commit()


async def get_expired_configs(session: AsyncSession) -> list[Config]:
    result = await session.execute(
        select(Config).where(Config.is_active == True, Config.expires_at < datetime.utcnow())
    )
    return list(result.scalars().all())


async def get_expiring_soon(session: AsyncSession, days: int = 3) -> list[Config]:
    now = datetime.utcnow()
    result = await session.execute(
        select(Config).where(
            Config.is_active == True,
            Config.expires_at > now,
            Config.expires_at < now + timedelta(days=days),
        )
    )
    return list(result.scalars().all())


# ── Payments ────────────────────────────────────────────────────

async def create_payment(
    session: AsyncSession,
    user_id: int,
    config_id: int | None,
    amount: str,
    currency: str,
    payment_method: str,
    plan_days: int,
    charge_id: str = "",
) -> Payment:
    payment = Payment(
        user_id=user_id,
        config_id=config_id,
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
    device_name: str | None = None,
    config_id: int | None = None,
) -> CryptoPendingInvoice:
    obj = CryptoPendingInvoice(
        cryptopay_invoice_id=cryptopay_invoice_id,
        user_chat_id=user_chat_id,
        action=action,
        plan_days=plan_days,
        asset=asset,
        device_name=device_name,
        config_id=config_id,
    )
    session.add(obj)
    await session.commit()
    return obj


async def get_all_crypto_pending(session: AsyncSession) -> list[CryptoPendingInvoice]:
    result = await session.execute(select(CryptoPendingInvoice))
    return list(result.scalars().all())


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
        select(func.count()).select_from(Config).where(Config.is_active == True)
    )
    total_cfg_res = await session.execute(select(func.count()).select_from(Config))

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
        "active_configs": active_res.scalar() or 0,
        "total_configs": total_cfg_res.scalar() or 0,
        "total_stars": total_stars,
        "yookassa_count": yookassa_res.scalar() or 0,
        "crypto_count": crypto_res.scalar() or 0,
    }
