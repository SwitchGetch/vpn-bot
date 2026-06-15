import asyncio
import base64
import ipaddress
import json
import logging

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

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


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_b64, public_key_b64) — Curve25519, совместимо с WireGuard."""
    private_key = X25519PrivateKey.generate()
    priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(priv_bytes).decode(), base64.b64encode(pub_bytes).decode()


def allocate_ip(used_ips: set[str]) -> str:
    """Выбирает следующий свободный IP из подсети."""
    network = ipaddress.ip_network(settings.WG_SUBNET, strict=False)
    hosts = network.hosts()
    next(hosts)  # .1 — это сервер, пропускаем
    for ip in hosts:
        if str(ip) not in used_ips:
            return str(ip)
    raise RuntimeError("Нет свободных IP в подсети. Расширьте WG_SUBNET.")


def build_client_config(private_key: str, peer_ip: str) -> str:
    """Генерирует .conf файл для клиента Amnezia VPN."""
    awg_lines = (
        f"Jc = {settings.AWG_JC}\n"
        f"Jmin = {settings.AWG_JMIN}\n"
        f"Jmax = {settings.AWG_JMAX}\n"
        f"S1 = {settings.AWG_S1}\n"
        f"S2 = {settings.AWG_S2}\n"
        f"S3 = {settings.AWG_S3}\n"
        f"S4 = {settings.AWG_S4}\n"
        f"H1 = {settings.AWG_H1}\n"
        f"H2 = {settings.AWG_H2}\n"
        f"H3 = {settings.AWG_H3}\n"
        f"H4 = {settings.AWG_H4}\n"
    )

    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {peer_ip}/32\n"
        f"DNS = {settings.WG_DNS}\n"
        f"{awg_lines}\n"
        "[Peer]\n"
        f"PublicKey = {settings.WG_SERVER_PUBLIC_KEY}\n"
        f"Endpoint = {settings.WG_SERVER_PUBLIC_IP}:{settings.WG_SERVER_PORT}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        "PersistentKeepalive = 25\n"
    )


def _strip_awg_params(conf: str) -> str:
    """Убирает AWG-специфичные параметры из текста конфига, оставляя чистый WireGuard."""
    awg_keys = {"Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"}
    lines = [ln for ln in conf.splitlines() if ln.split("=")[0].strip() not in awg_keys]
    return "\n".join(lines) + "\n"


def build_client_uri(conf_content: str) -> str:
    """Генерирует vpn:// ключ для приложения Amnezia VPN.

    last_config содержит чистый WireGuard конфиг без AWG параметров —
    AWG параметры передаются отдельными полями JSON, как ожидает Amnezia VPN.
    """
    data = {
        "containers": [
            {
                "container": "amnezia-awg",
                "awg": {
                    "last_config": _strip_awg_params(conf_content),
                    "transport_proto": "udp",
                    "port": str(settings.WG_SERVER_PORT),
                    "junkPacketCount": str(settings.AWG_JC),
                    "junkPacketMinSize": str(settings.AWG_JMIN),
                    "junkPacketMaxSize": str(settings.AWG_JMAX),
                    "initPacketJunkSize": str(settings.AWG_S1),
                    "responsePacketJunkSize": str(settings.AWG_S2),
                    "initPacketMagicHeader": str(settings.AWG_H1),
                    "responsePacketMagicHeader": str(settings.AWG_H2),
                    "underloadPacketMagicHeader": str(settings.AWG_H3),
                    "transportPacketMagicHeader": str(settings.AWG_H4),
                }
            }
        ],
        "defaultContainer": "amnezia-awg",
        "description": "VPS Access",
        "dns1": settings.WG_DNS,
        "dns2": "8.8.8.8",
        "hostName": settings.WG_SERVER_PUBLIC_IP,
    }
    json_bytes = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "vpn://" + base64.b64encode(json_bytes).decode()


async def add_peer(public_key: str, peer_ip: str) -> None:
    """Добавляет пира в работающий интерфейс и сохраняет в конфиг."""
    await _run([
        "docker", "exec", settings.WG_CONTAINER,
        "awg", "set", settings.WG_INTERFACE,
        "peer", public_key,
        "allowed-ips", f"{peer_ip}/32",
        "persistent-keepalive", "25",
    ])
    await _persist_config()
    logger.info("Peer added: %s -> %s", public_key[:8], peer_ip)


async def remove_peer(public_key: str) -> None:
    """Удаляет пира из интерфейса и сохраняет конфиг."""
    await _run([
        "docker", "exec", settings.WG_CONTAINER,
        "awg", "set", settings.WG_INTERFACE,
        "peer", public_key, "remove",
    ])
    await _persist_config()
    logger.info("Peer removed: %s", public_key[:8])


async def _persist_config() -> None:
    """Сохраняет текущее состояние интерфейса в файл конфига внутри контейнера."""
    await _run([
        "docker", "exec", settings.WG_CONTAINER,
        "sh", "-c",
        f"awg showconf {settings.WG_INTERFACE} > {settings.WG_CONFIG_PATH}",
    ])
