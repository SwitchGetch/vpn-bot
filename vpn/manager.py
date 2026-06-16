import asyncio
import base64
import ipaddress
import json
import logging
import os
import shlex
import struct
import zlib

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


def generate_psk() -> str:
    """Generates a WireGuard preshared key — 32 random bytes, base64 encoded."""
    return base64.b64encode(os.urandom(32)).decode()


def extract_psk(config_text: str) -> str:
    """Extracts PresharedKey value from a WG config text block."""
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("presharedkey"):
            _, _, v = stripped.partition("=")
            return v.strip()
    return ""


def allocate_ip(used_ips: set[str]) -> str:
    """Выбирает следующий свободный IP из подсети."""
    network = ipaddress.ip_network(settings.WG_SUBNET, strict=False)
    hosts = network.hosts()
    next(hosts)  # .1 — это сервер, пропускаем
    for ip in hosts:
        if str(ip) not in used_ips:
            return str(ip)
    raise RuntimeError("Нет свободных IP в подсети. Расширьте WG_SUBNET.")


def build_client_config(private_key: str, peer_ip: str, psk: str = "") -> str:
    """Текст конфига для хранения в БД. H-значения — диапазоны как у сервера."""
    h1 = f"{settings.AWG_H1_MIN}-{settings.AWG_H1_MAX}"
    h2 = f"{settings.AWG_H2_MIN}-{settings.AWG_H2_MAX}"
    h3 = f"{settings.AWG_H3_MIN}-{settings.AWG_H3_MAX}"
    h4 = f"{settings.AWG_H4_MIN}-{settings.AWG_H4_MAX}"

    psk_line = f"PresharedKey = {psk}\n" if psk else ""

    return (
        "[Interface]\n"
        f"Address = {peer_ip}/32\n"
        f"DNS = {settings.WG_DNS}\n"
        f"PrivateKey = {private_key}\n"
        f"Jc = {settings.AWG_JC}\n"
        f"Jmin = {settings.AWG_JMIN}\n"
        f"Jmax = {settings.AWG_JMAX}\n"
        f"S1 = {settings.AWG_S1}\n"
        f"S2 = {settings.AWG_S2}\n"
        f"S3 = {settings.AWG_S3}\n"
        f"S4 = {settings.AWG_S4}\n"
        f"H1 = {h1}\n"
        f"H2 = {h2}\n"
        f"H3 = {h3}\n"
        f"H4 = {h4}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {settings.WG_SERVER_PUBLIC_KEY}\n"
        f"{psk_line}"
        f"Endpoint = {settings.WG_SERVER_PUBLIC_IP}:{settings.WG_SERVER_PORT}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        "PersistentKeepalive = 25\n"
    )


def build_client_uri(private_key: str, public_key: str, peer_ip: str, psk: str = "") -> str:
    """Генерирует vpn:// ключ формата Amnezia VPN (amnezia-awg2, qCompress+JSON)."""
    h1 = f"{settings.AWG_H1_MIN}-{settings.AWG_H1_MAX}"
    h2 = f"{settings.AWG_H2_MIN}-{settings.AWG_H2_MAX}"
    h3 = f"{settings.AWG_H3_MIN}-{settings.AWG_H3_MAX}"
    h4 = f"{settings.AWG_H4_MIN}-{settings.AWG_H4_MAX}"

    psk_line = f"PresharedKey = {psk}\n" if psk else ""

    # Встроенный WG-конфиг внутри last_config — DNS как плейсхолдеры, как в оригинале Amnezia
    embedded_wg_config = (
        "[Interface]\n"
        f"Address = {peer_ip}/32\n"
        "DNS = $PRIMARY_DNS, $SECONDARY_DNS\n"
        f"PrivateKey = {private_key}\n"
        f"Jc = {settings.AWG_JC}\n"
        f"Jmin = {settings.AWG_JMIN}\n"
        f"Jmax = {settings.AWG_JMAX}\n"
        f"S1 = {settings.AWG_S1}\n"
        f"S2 = {settings.AWG_S2}\n"
        f"S3 = {settings.AWG_S3}\n"
        f"S4 = {settings.AWG_S4}\n"
        f"H1 = {h1}\n"
        f"H2 = {h2}\n"
        f"H3 = {h3}\n"
        f"H4 = {h4}\n"
        f"I1 = {settings.AWG_I1}\n"
        "I2 = \n"
        "I3 = \n"
        "I4 = \n"
        "I5 = \n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {settings.WG_SERVER_PUBLIC_KEY}\n"
        f"{psk_line}"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"Endpoint = {settings.WG_SERVER_PUBLIC_IP}:{settings.WG_SERVER_PORT}\n"
        "PersistentKeepalive = 25\n"
    )

    subnet_address = str(ipaddress.ip_network(settings.WG_SUBNET, strict=False).network_address)

    last_config_obj = {
        "H1": h1, "H2": h2, "H3": h3, "H4": h4,
        "I1": settings.AWG_I1, "I2": "", "I3": "", "I4": "", "I5": "",
        "Jc": str(settings.AWG_JC),
        "Jmax": str(settings.AWG_JMAX),
        "Jmin": str(settings.AWG_JMIN),
        "S1": str(settings.AWG_S1),
        "S2": str(settings.AWG_S2),
        "S3": str(settings.AWG_S3),
        "S4": str(settings.AWG_S4),
        "allowed_ips": ["0.0.0.0/0", "::/0"],
        "clientId": public_key,
        "client_ip": peer_ip,
        "client_priv_key": private_key,
        "client_pub_key": public_key,
        "config": embedded_wg_config,
        "hostName": settings.WG_SERVER_PUBLIC_IP,
        "mtu": "1376",
        "persistent_keep_alive": "25",
        "port": settings.WG_SERVER_PORT,
        "psk_key": psk,
        "server_pub_key": settings.WG_SERVER_PUBLIC_KEY,
    }

    data = {
        "containers": [
            {
                "awg": {
                    "H1": h1, "H2": h2, "H3": h3, "H4": h4,
                    "I1": settings.AWG_I1, "I2": "", "I3": "", "I4": "", "I5": "",
                    "Jc": str(settings.AWG_JC),
                    "Jmax": str(settings.AWG_JMAX),
                    "Jmin": str(settings.AWG_JMIN),
                    "S1": str(settings.AWG_S1),
                    "S2": str(settings.AWG_S2),
                    "S3": str(settings.AWG_S3),
                    "S4": str(settings.AWG_S4),
                    "last_config": json.dumps(last_config_obj, indent=4, ensure_ascii=False) + "\n",
                    "port": str(settings.WG_SERVER_PORT),
                    "protocol_version": "2",
                    "subnet_address": subnet_address,
                    "subnet_cidr": str(ipaddress.ip_network(settings.WG_SUBNET, strict=False).prefixlen),
                    "transport_proto": "udp",
                },
                "container": "amnezia-awg2",
            }
        ],
        "defaultContainer": "amnezia-awg2",
        "description": "VPS Access",
        "dns1": settings.WG_DNS,
        "dns2": "8.8.8.8",
        "hostName": settings.WG_SERVER_PUBLIC_IP,
    }

    json_bytes = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = struct.pack(">I", len(json_bytes)) + zlib.compress(json_bytes)
    return "vpn://" + base64.urlsafe_b64encode(compressed).rstrip(b"=").decode()


async def add_peer(public_key: str, peer_ip: str, psk: str = "") -> None:
    """Добавляет пира в работающий интерфейс и сохраняет в конфиг."""
    if psk:
        cmd = (
            f"T=$(mktemp) && "
            f"printf '%s\\n' {shlex.quote(psk)} > \"$T\" && "
            f"awg set {shlex.quote(settings.WG_INTERFACE)} peer {shlex.quote(public_key)} "
            f"preshared-key \"$T\" "
            f"allowed-ips {shlex.quote(peer_ip + '/32')} "
            f"persistent-keepalive 25 && "
            f"rm \"$T\""
        )
        await _run(["docker", "exec", settings.WG_CONTAINER, "sh", "-c", cmd])
    else:
        await _run([
            "docker", "exec", settings.WG_CONTAINER,
            "awg", "set", settings.WG_INTERFACE,
            "peer", public_key,
            "allowed-ips", f"{peer_ip}/32",
            "persistent-keepalive", "25",
        ])
    await _persist_config()
    logger.info("Peer added: %s -> %s (psk=%s)", public_key[:8], peer_ip, bool(psk))


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
    """Сохраняет текущее состояние интерфейса в файл конфига внутри контейнера.

    awg showconf не включает Address и PostUp, поэтому мы вставляем Address
    из текущего ip addr, чтобы после перезапуска контейнера маршрут 10.8.x/24
    на awg-интерфейс восстановился корректно.
    """
    iface = settings.WG_INTERFACE
    conf_path = settings.WG_CONFIG_PATH

    # Получаем текущий IPv4-адрес интерфейса (например 10.8.1.1/24)
    addr_out = await _run([
        "docker", "exec", settings.WG_CONTAINER,
        "sh", "-c",
        f"ip -4 addr show {iface} | awk '/inet /{{print $2}}'",
    ])

    if addr_out:
        # Вставляем Address сразу после [Interface]
        script = (
            f"awg showconf {iface} | "
            f"awk '/^\\[Interface\\]$/{{print; print \"Address = {addr_out}\"; next}} {{print}}' "
            f"> {conf_path}"
        )
    else:
        script = f"awg showconf {iface} > {conf_path}"

    await _run(["docker", "exec", settings.WG_CONTAINER, "sh", "-c", script])
