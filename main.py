import asyncio
import logging
from datetime import timezone
from typing import Any, Awaitable, Callable

from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import TelegramObject

from bot.handlers import admin, buy, profile, start, support
from config import settings
from database import async_session, init_db
from database.queries import (
    get_all_active_subscriptions,
    get_hwid_device,
    get_subscription_by_token,
    get_user_by_chat_id,
    register_hwid_device,
    touch_hwid_device,
)
from scheduler.tasks import scheduler, setup_scheduler
from vpn.manager import build_vless_uri, sync_xray_users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Открывает сессию БД на каждый апдейт и отбрасывает апдейты забаненных."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            tg_user = data.get("event_from_user")
            if tg_user and tg_user.id not in settings.ADMIN_IDS:
                db_user = await get_user_by_chat_id(session, tg_user.id)
                if db_user and db_user.is_banned:
                    return None
            data["session"] = session
            return await handler(event, data)


# ── HTTP-сервер для subscription URL ────────────────────────────

_LIMIT_HEADERS = {
    "Content-Type": "text/plain; charset=utf-8",
    "x-hwid-max-devices-reached": "true",
}


async def handle_subscription(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    hwid = request.headers.get("X-Hwid", "").strip()[:64]
    device_model = request.headers.get("X-Device-Model", "")[:64]
    device_os = request.headers.get("X-Device-Os", "")[:32]
    os_version = request.headers.get("X-Ver-Os", "")[:32]
    user_agent = request.headers.get("User-Agent", "")[:128]

    async with async_session() as session:
        sub = await get_subscription_by_token(session, token)
        if not sub or not sub.is_active:
            return web.Response(status=404, text="Not found")

        if hwid:
            existing = await get_hwid_device(session, sub.id, hwid)
            if existing:
                if existing.is_blocked:
                    logger.info("SUB BLOCKED hwid=%s sub=%d", hwid[:8], sub.id)
                    return web.Response(status=200, text="", headers=_LIMIT_HEADERS)
                await touch_hwid_device(session, existing.id)
            else:
                active_count = sum(1 for d in sub.hwid_devices if not d.is_blocked)
                if active_count >= sub.max_devices:
                    logger.info("SUB LIMIT REACHED hwid=%s sub=%d (%d/%d)",
                                hwid[:8], sub.id, active_count, sub.max_devices)
                    return web.Response(status=200, text="", headers=_LIMIT_HEADERS)
                await register_hwid_device(
                    session, sub.id, hwid, device_model, device_os, os_version, user_agent
                )
                logger.info("SUB NEW DEVICE hwid=%s model=%s os=%s sub=%d",
                            hwid[:8], device_model, device_os, sub.id)

        # expires_at хранится как naive UTC — указываем зону явно,
        # иначе timestamp() посчитает от локального времени сервера
        expire_ts = int(sub.expires_at.replace(tzinfo=timezone.utc).timestamp())
        lines = [
            build_vless_uri(d.xray_uuid, f"{settings.SUB_SERVICE_NAME} — {d.device_name}")
            for d in sub.devices
        ]

    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Subscription-Userinfo": f"upload=0; download=0; total=0; expire={expire_ts}",
        "Content-Disposition": f'attachment; filename="{settings.SUB_SERVICE_NAME}.txt"',
        "Profile-Title": settings.SUB_SERVICE_NAME,
        "Profile-Update-Interval": "1",
        "x-hwid-active": "true",
    }
    return web.Response(text="\n".join(lines), headers=headers)


async def run_sub_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/sub/{token}", handle_subscription)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.SUB_PORT)
    await site.start()
    logger.info("Subscription server started on port %d", settings.SUB_PORT)
    return runner


# ── Основная точка входа ────────────────────────────────────────

async def main() -> None:
    await init_db()

    async with async_session() as session:
        active_subs = await get_all_active_subscriptions(session)
        active_uuids = [
            device.xray_uuid
            for sub in active_subs
            for device in sub.devices
        ]
    await sync_xray_users(active_uuids)

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
    runner = await run_sub_server()

    logger.info("Bot started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
