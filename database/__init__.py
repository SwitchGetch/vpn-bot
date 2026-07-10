from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import DEFAULT_PLANS, settings
from .models import Base, BotSetting, Plan

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_migrations()
    async with async_session() as session:
        await _seed_defaults(session)


async def _run_migrations() -> None:
    """Добавляет новые колонки в существующие таблицы без потери данных."""
    async with engine.begin() as conn:
        # payments: добавить subscription_id если нет
        rows = await conn.execute(text("PRAGMA table_info(payments)"))
        payment_cols = {row[1] for row in rows.fetchall()}
        if "subscription_id" not in payment_cols:
            await conn.execute(
                text("ALTER TABLE payments ADD COLUMN subscription_id INTEGER REFERENCES subscriptions(id)")
            )

        # crypto_pending_invoices: добавить device_count, subscription_id и base_device_price
        rows = await conn.execute(text("PRAGMA table_info(crypto_pending_invoices)"))
        inv_cols = {row[1] for row in rows.fetchall()}
        if "device_count" not in inv_cols:
            await conn.execute(
                text("ALTER TABLE crypto_pending_invoices ADD COLUMN device_count INTEGER NOT NULL DEFAULT 1")
            )
        if "subscription_id" not in inv_cols:
            await conn.execute(
                text("ALTER TABLE crypto_pending_invoices ADD COLUMN subscription_id INTEGER")
            )
        if "base_device_price" not in inv_cols:
            await conn.execute(
                text("ALTER TABLE crypto_pending_invoices ADD COLUMN base_device_price INTEGER NOT NULL DEFAULT 0")
            )

        # subscriptions: флаг отправленного напоминания
        rows = await conn.execute(text("PRAGMA table_info(subscriptions)"))
        sub_cols = {row[1] for row in rows.fetchall()}
        if "reminder_sent" not in sub_cols:
            await conn.execute(
                text("ALTER TABLE subscriptions ADD COLUMN reminder_sent BOOLEAN NOT NULL DEFAULT 0")
            )

        # hwid_devices: создаётся через create_all, но добавляем индекс если нет
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hwid_devices_sub_hwid "
            "ON hwid_devices (subscription_id, hwid)"
        ))


async def _seed_defaults(session) -> None:
    from sqlalchemy import func, select

    defaults = {
        "payment_stars_enabled": "1",
        "payment_yookassa_enabled": "0",
        "payment_yookassa_token": "",
        "payment_crypto_enabled": "0",
        "payment_crypto_token": "",
    }
    for key, value in defaults.items():
        existing = await session.execute(select(BotSetting).where(BotSetting.key == key))
        if not existing.scalar_one_or_none():
            session.add(BotSetting(key=key, value=value))

    count = await session.execute(select(func.count()).select_from(Plan))
    if (count.scalar() or 0) == 0:
        for i, p in enumerate(DEFAULT_PLANS):
            session.add(Plan(days=p["days"], label=p["label"], stars_price=p["stars_price"], sort_order=i))

    await session.commit()
