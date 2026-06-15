from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import DEFAULT_PLANS, settings
from .models import Base, BotSetting, Plan

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        await _seed_defaults(session)


async def _seed_defaults(session) -> None:
    from sqlalchemy import func, select

    # Дефолтные настройки (добавляются только если ключа ещё нет)
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

    # Дефолтные тарифы (добавляются только если таблица пуста)
    count = await session.execute(select(func.count()).select_from(Plan))
    if (count.scalar() or 0) == 0:
        for i, p in enumerate(DEFAULT_PLANS):
            session.add(Plan(days=p["days"], label=p["label"], stars_price=p["stars_price"], sort_order=i))

    await session.commit()
