import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers import admin, buy, profile, start, support
from config import settings
from database import async_session, init_db
from scheduler.tasks import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class DatabaseMiddleware(BaseMiddleware):
    """Создаёт сессию БД для каждого апдейта и передаёт в хендлер."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            data["session"] = session
            return await handler(event, data)


async def main() -> None:
    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(DatabaseMiddleware())

    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(buy.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)

    setup_scheduler(bot)

    logging.info("Bot started")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
