import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import build_sub_url
from database import async_session
from database.queries import (
    add_device,
    create_payment,
    create_subscription,
    deactivate_subscription,
    delete_crypto_pending,
    delete_stale_crypto_pending,
    extend_subscription,
    get_all_crypto_pending,
    get_expired_subscriptions,
    get_expiring_soon_subscriptions,
    get_setting,
    get_subscription_by_id,
    get_user_by_chat_id,
    get_user_subscription,
    mark_reminder_sent,
    remove_all_devices,
    update_subscription_devices,
)
from payments.crypto import get_paid_invoices
from vpn.manager import add_xray_users, generate_uuid, remove_xray_users

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler(bot: Bot) -> None:
    scheduler.add_job(check_expired,         "interval", hours=1,   args=[bot], id="check_expired")
    scheduler.add_job(send_reminders,        "interval", hours=12,  args=[bot], id="send_reminders")
    scheduler.add_job(check_crypto_payments, "interval", minutes=5, args=[bot], id="check_crypto")
    scheduler.start()
    logger.info("Scheduler started")


async def check_expired(bot: Bot) -> None:
    async with async_session() as session:
        expired = await get_expired_subscriptions(session)
        for sub in expired:
            try:
                uuids = [d.xray_uuid for d in sub.devices]
                if uuids:
                    await remove_xray_users(uuids)
                await deactivate_subscription(session, sub.id)
                await bot.send_message(
                    sub.user.chat_id,
                    "❌ Ваша подписка истекла и деактивирована.\n\n"
                    "Нажмите /start чтобы купить новую или продлить.",
                )
                logger.info("Deactivated subscription %d for user %d", sub.id, sub.user_id)
            except Exception as e:
                logger.error("Failed to deactivate subscription %d: %s", sub.id, e)


async def send_reminders(bot: Bot) -> None:
    async with async_session() as session:
        expiring = await get_expiring_soon_subscriptions(session, days=3)
        for sub in expiring:
            try:
                expires = sub.expires_at.strftime("%d.%m.%Y")
                await bot.send_message(
                    sub.user.chat_id,
                    f"⚠️ Ваша подписка истекает <b>{expires}</b>.\n\n"
                    "Продлите доступ через /start",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            # Помечаем в любом случае, чтобы не долбить пользователя, заблокировавшего бота
            await mark_reminder_sent(session, sub.id)


async def check_crypto_payments(bot: Bot) -> None:
    async with async_session() as session:
        # Инвойс CryptoPay живёт 1 час — записи старше 2 часов уже не оплатить
        removed = await delete_stale_crypto_pending(session, max_age_hours=2)
        if removed:
            logger.info("Removed %d stale crypto invoices", removed)

        pending = await get_all_crypto_pending(session)
        if not pending:
            return

        token = await get_setting(session, "payment_crypto_token", "")
        if not token:
            return

        invoice_ids = [p.cryptopay_invoice_id for p in pending]
        try:
            paid_items = await get_paid_invoices(token, invoice_ids)
        except Exception as e:
            logger.error("CryptoPay getInvoices failed: %s", e)
            return

        paid_map = {item["invoice_id"]: item for item in paid_items}

        for inv in pending:
            if inv.cryptopay_invoice_id not in paid_map:
                continue

            paid_item = paid_map[inv.cryptopay_invoice_id]
            paid_currency = paid_item.get("paid_asset") or inv.asset
            paid_amount = paid_item.get("paid_amount") or paid_item["amount"]

            try:
                user = await get_user_by_chat_id(session, inv.user_chat_id)
                if not user:
                    await delete_crypto_pending(session, inv.cryptopay_invoice_id)
                    continue

                if inv.action == "new":
                    existing = await get_user_subscription(session, user.id)
                    if existing:
                        old_uuids = await remove_all_devices(session, existing.id)
                        if old_uuids:
                            await remove_xray_users(old_uuids)
                        await session.delete(existing)
                        await session.commit()

                    sub = await create_subscription(
                        session,
                        user_id=user.id,
                        plan_days=inv.plan_days,
                        max_devices=inv.device_count,
                        base_device_price=inv.base_device_price,
                        is_active=True,
                    )
                    uuids = []
                    for i in range(inv.device_count):
                        uid = generate_uuid()
                        await add_device(session, sub.id, uid, device_name=f"Устройство {i + 1}")
                        uuids.append(uid)
                    await add_xray_users(uuids)

                    await create_payment(
                        session, user.id, sub.id,
                        amount=str(paid_amount),
                        currency=paid_currency,
                        payment_method="crypto",
                        plan_days=inv.plan_days,
                        charge_id=str(inv.cryptopay_invoice_id),
                    )
                    sub_url = build_sub_url(sub.sub_token)
                    await bot.send_message(
                        inv.user_chat_id,
                        f"✅ <b>Оплата получена! Подписка активирована.</b>\n\n"
                        f"Устройств: <b>{inv.device_count}</b>\n"
                        f"Действует до: <b>{sub.expires_at.strftime('%d.%m.%Y')}</b>\n\n"
                        f"📋 Subscription URL для happ:\n<code>{sub_url}</code>\n\n"
                        f"<i>В happ: + → Добавить подписку → вставьте URL</i>",
                        parse_mode="HTML",
                    )

                elif inv.action == "extend":
                    sub_id = inv.subscription_id
                    if not sub_id:
                        await delete_crypto_pending(session, inv.cryptopay_invoice_id)
                        continue
                    sub = await extend_subscription(session, sub_id, inv.plan_days)
                    uuids = [d.xray_uuid for d in sub.devices]
                    if uuids:
                        await add_xray_users(uuids)
                    await create_payment(
                        session, user.id, sub.id,
                        amount=str(paid_amount),
                        currency=paid_currency,
                        payment_method="crypto",
                        plan_days=inv.plan_days,
                        charge_id=str(inv.cryptopay_invoice_id),
                    )
                    await bot.send_message(
                        inv.user_chat_id,
                        f"✅ <b>Оплата получена! Подписка продлена.</b>\n\n"
                        f"Действует до: <b>{sub.expires_at.strftime('%d.%m.%Y')}</b>",
                        parse_mode="HTML",
                    )

                elif inv.action == "add_device":
                    sub_id = inv.subscription_id
                    if not sub_id:
                        await delete_crypto_pending(session, inv.cryptopay_invoice_id)
                        continue
                    sub = await get_subscription_by_id(session, sub_id)
                    if not sub:
                        await delete_crypto_pending(session, inv.cryptopay_invoice_id)
                        continue
                    uuids = []
                    current_count = len(sub.devices)
                    for i in range(inv.device_count):
                        uid = generate_uuid()
                        await add_device(session, sub.id, uid, device_name=f"Устройство {current_count + i + 1}")
                        uuids.append(uid)
                    await add_xray_users(uuids)
                    await update_subscription_devices(session, sub.id, sub.max_devices + inv.device_count)
                    await create_payment(
                        session, user.id, sub.id,
                        amount=str(paid_amount),
                        currency=paid_currency,
                        payment_method="crypto",
                        plan_days=inv.plan_days,
                        charge_id=str(inv.cryptopay_invoice_id),
                    )
                    await bot.send_message(
                        inv.user_chat_id,
                        f"✅ <b>Оплата получена! Устройства добавлены.</b>\n\n"
                        f"Добавлено устройств: <b>+{inv.device_count}</b>",
                        parse_mode="HTML",
                    )

                await delete_crypto_pending(session, inv.cryptopay_invoice_id)
                logger.info("Processed crypto payment for invoice %d", inv.cryptopay_invoice_id)

            except Exception as e:
                logger.error("Error processing crypto invoice %d: %s", inv.cryptopay_invoice_id, e)
