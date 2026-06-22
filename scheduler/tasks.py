import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import async_session
from database.queries import (
    activate_config,
    create_config,
    create_payment,
    deactivate_config,
    delete_config,
    delete_crypto_pending,
    extend_config,
    get_all_crypto_pending,
    get_expired_configs,
    get_expiring_soon,
    get_setting,
    get_used_ips,
    get_user_by_chat_id,
)
from payments.crypto import get_paid_invoices
from vpn.manager import add_peer, allocate_ip, build_client_config, build_client_uri, generate_keypair, generate_psk, remove_peer

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler(bot: Bot) -> None:
    scheduler.add_job(check_expired,         "interval", hours=1,   args=[bot], id="check_expired")
    scheduler.add_job(send_reminders,        "interval", hours=12,  args=[bot], id="send_reminders")
    scheduler.add_job(check_crypto_payments, "interval", minutes=5, args=[bot], id="check_crypto")
    scheduler.start()
    logger.info("Scheduler started")


async def check_expired(bot: Bot) -> None:
    """Отзывает конфиги с истёкшим сроком действия."""
    async with async_session() as session:
        expired = await get_expired_configs(session)
        for config in expired:
            try:
                await remove_peer(config.peer_public_key)
                await deactivate_config(session, config.id)
                await bot.send_message(
                    config.user.chat_id,
                    f"❌ Ключ <b>{config.device_name}</b> истёк и деактивирован.\n\n"
                    "Нажмите /start чтобы купить новый или продлить.",
                    parse_mode="HTML",
                )
                logger.info("Deactivated config %d for user %d", config.id, config.user_id)
            except Exception as e:
                logger.error("Failed to deactivate config %d: %s", config.id, e)


async def send_reminders(bot: Bot) -> None:
    """Отправляет напоминания за 3 дня до истечения конфига."""
    async with async_session() as session:
        expiring = await get_expiring_soon(session, days=3)
        for config in expiring:
            try:
                expires = config.expires_at.strftime("%d.%m.%Y")
                await bot.send_message(
                    config.user.chat_id,
                    f"⚠️ Ключ <b>{config.device_name}</b> истекает <b>{expires}</b>.\n\n"
                    "Продлите доступ через /start",
                    parse_mode="HTML",
                )
            except Exception:
                pass


async def check_crypto_payments(bot: Bot) -> None:
    """Проверяет оплаченные CryptoPay-инвойсы и активирует конфиги."""
    async with async_session() as session:
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
            try:
                user = await get_user_by_chat_id(session, inv.user_chat_id)
                if not user:
                    await delete_crypto_pending(session, inv.cryptopay_invoice_id)
                    continue

                if inv.action == "new":
                    used_ips = await get_used_ips(session)
                    priv_key, pub_key = generate_keypair()
                    psk = generate_psk()
                    peer_ip = allocate_ip(used_ips)
                    config_text = build_client_config(priv_key, peer_ip, psk)

                    device_name = inv.device_name or "Устройство"
                    config = await create_config(
                        session, user.id, device_name,
                        pub_key, priv_key, peer_ip, config_text, inv.plan_days,
                        psk=psk, is_active=False,
                    )
                    try:
                        await add_peer(pub_key, peer_ip, psk)
                    except Exception:
                        await delete_config(session, config.id)
                        raise
                    await activate_config(session, config.id)
                    paid_currency = paid_item.get("paid_asset") or inv.asset
                    paid_amount = paid_item.get("paid_amount") or paid_item["amount"]
                    await create_payment(
                        session, user.id, config.id,
                        amount=str(paid_amount),
                        currency=paid_currency,
                        payment_method="crypto",
                        plan_days=inv.plan_days,
                        charge_id=str(inv.cryptopay_invoice_id),
                    )
                    uri = build_client_uri(priv_key, pub_key, peer_ip, psk)
                    await bot.send_message(
                        inv.user_chat_id,
                        f"✅ <b>Оплата получена! Ключ готов.</b>\n\n"
                        f"Устройство: <b>{device_name}</b>\n"
                        f"Действителен до: <b>{config.expires_at.strftime('%d.%m.%Y')}</b>\n\n"
                        f"Скопируйте ключ и вставьте в Amnezia VPN (+ → Вставить ключ):\n\n"
                        f"<code>{uri}</code>",
                        parse_mode="HTML",
                    )

                elif inv.action == "extend":
                    config = await extend_config(session, inv.config_id, inv.plan_days)
                    paid_currency = paid_item.get("paid_asset") or inv.asset
                    paid_amount = paid_item.get("paid_amount") or paid_item["amount"]
                    await create_payment(
                        session, user.id, config.id,
                        amount=str(paid_amount),
                        currency=paid_currency,
                        payment_method="crypto",
                        plan_days=inv.plan_days,
                        charge_id=str(inv.cryptopay_invoice_id),
                    )
                    await bot.send_message(
                        inv.user_chat_id,
                        f"✅ <b>Оплата получена! Ключ продлён.</b>\n\n"
                        f"Устройство: <b>{config.device_name}</b>\n"
                        f"Новая дата: <b>{config.expires_at.strftime('%d.%m.%Y')}</b>",
                        parse_mode="HTML",
                    )

                await delete_crypto_pending(session, inv.cryptopay_invoice_id)
                logger.info("Processed crypto payment for invoice %d", inv.cryptopay_invoice_id)

            except Exception as e:
                logger.error("Error processing crypto invoice %d: %s", inv.cryptopay_invoice_id, e)
