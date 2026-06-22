from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import DEFAULT_PLANS, settings
from .models import Base, BotSetting, Config, Plan

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_migrations()
    async with async_session() as session:
        await _seed_defaults(session)


async def _run_migrations() -> None:
    """Схемные миграции, которые create_all не умеет делать (добавление колонок)."""
    from sqlalchemy import select

    async with engine.begin() as conn:
        rows = await conn.execute(text("PRAGMA table_info(configs)"))
        existing = {row[1] for row in rows.fetchall()}
        if "peer_psk" not in existing:
            await conn.execute(
                text("ALTER TABLE configs ADD COLUMN peer_psk TEXT NOT NULL DEFAULT ''")
            )

    # Бэкфилл: заполняем peer_psk из config_text для старых записей
    async with async_session() as session:
        result = await session.execute(select(Config).where(Config.peer_psk == ""))
        for cfg in result.scalars().all():
            for line in cfg.config_text.splitlines():
                if line.strip().lower().startswith("presharedkey"):
                    cfg.peer_psk = line.split("=", 1)[1].strip()
                    break
        await session.commit()


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
