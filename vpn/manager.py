import asyncio
import json
import logging
import urllib.parse
import uuid

from config import settings

logger = logging.getLogger(__name__)


async def _run(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstderr: {stderr.decode().strip()}"
        )
    return stdout.decode().strip()


def generate_uuid() -> str:
    return str(uuid.uuid4())


def build_vless_uri(xray_uuid: str, name: str = "VPN") -> str:
    params = (
        f"type=tcp"
        f"&security=reality"
        f"&pbk={settings.XRAY_PUBLIC_KEY}"
        f"&fp={settings.XRAY_FINGERPRINT}"
        f"&sni={settings.XRAY_SERVER_NAME}"
        f"&sid={settings.XRAY_SHORT_ID}"
    )
    encoded_name = urllib.parse.quote(name)
    return f"vless://{xray_uuid}@{settings.SERVER_IP}:{settings.XRAY_PORT}?{params}#{encoded_name}"


def calc_price(n: int, base_price: int) -> int:
    """Цена за n устройств. При n→∞ скидка стремится к 50%."""
    return round(n * base_price * (1 / (n + 1) + 0.5))


def calc_price_usd(n: int, base_usd: float) -> str:
    """Та же формула для USD, результат — строка вида '4.50'."""
    return f"{n * base_usd * (1 / (n + 1) + 0.5):.2f}"


def calc_upgrade_cost(
    old_n: int, new_n: int, base_price: int, plan_days: int, remaining_days: int
) -> int:
    """Стоимость апгрейда: (новая цена - старая цена) * остаток / период."""
    old_price = calc_price(old_n, base_price)
    new_price = calc_price(new_n, base_price)
    return max(1, round((new_price - old_price) * remaining_days / plan_days))


def _load_config() -> dict:
    with open(settings.XRAY_CONFIG_PATH) as f:
        return json.load(f)


def _save_config(config: dict) -> None:
    with open(settings.XRAY_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


async def _reload_xray() -> None:
    await _run(["systemctl", "restart", "xray"])


async def add_xray_users(uuids: list[str]) -> None:
    """Добавляет несколько пользователей одним перезапуском XRay."""
    if not uuids:
        return
    config = _load_config()
    clients = config["inbounds"][0]["settings"]["clients"]
    existing = {c["id"] for c in clients}
    added = 0
    for u in uuids:
        if u not in existing:
            clients.append({"id": u, "email": u})
            added += 1
    if added:
        _save_config(config)
        await _reload_xray()
    logger.info("XRay users added: %d", added)


async def remove_xray_users(uuids: list[str]) -> None:
    """Удаляет несколько пользователей одним перезапуском XRay."""
    if not uuids:
        return
    uuid_set = set(uuids)
    config = _load_config()
    clients = config["inbounds"][0]["settings"]["clients"]
    new_clients = [c for c in clients if c["id"] not in uuid_set]
    if len(new_clients) != len(clients):
        config["inbounds"][0]["settings"]["clients"] = new_clients
        _save_config(config)
        await _reload_xray()
    logger.info("XRay users removed: %d", len(uuids))


async def sync_xray_users(active_uuids: list[str]) -> None:
    """При старте синхронизирует XRay конфиг с активными UUID из БД."""
    try:
        config = _load_config()
    except Exception as e:
        logger.error("sync_xray_users: не удалось прочитать конфиг: %s", e)
        return

    active_set = set(active_uuids)
    current = {c["id"] for c in config["inbounds"][0]["settings"]["clients"]}

    if active_set == current:
        logger.info("sync_xray_users: конфиг актуален (%d пользователей)", len(active_set))
        return

    config["inbounds"][0]["settings"]["clients"] = [
        {"id": u, "email": u} for u in active_uuids
    ]
    _save_config(config)
    await _reload_xray()
    logger.info(
        "sync_xray_users: обновлено %d → %d пользователей",
        len(current), len(active_set),
    )
