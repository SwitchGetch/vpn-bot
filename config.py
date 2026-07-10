from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: list[int] = []

    DATABASE_URL: str = "sqlite+aiosqlite:///vpn-bot.db"

    SERVER_IP: str  # публичный IP сервера

    # XRay / VLESS+Reality
    XRAY_CONFIG_PATH: str = "/usr/local/etc/xray/config.json"
    XRAY_PORT: int = 443
    XRAY_PUBLIC_KEY: str = ""
    XRAY_SHORT_ID: str = ""
    XRAY_SERVER_NAME: str = "www.googletagmanager.com"
    XRAY_FINGERPRINT: str = "chrome"

    # HTTP сервер для subscription URL
    SUB_BIND: str = "0.0.0.0"  # 127.0.0.1 — принимать только локальные запросы (от Caddy)
    SUB_PORT: int = 8080
    SUB_SERVICE_NAME: str = "VPN"  # отображается в happ как название подписки
    # Внешний базовый URL подписки (например "https://sub.example.com:8443").
    # Если пусто — используется http://SERVER_IP:SUB_PORT
    SUB_BASE_URL: str = ""

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    # extra="ignore": лишние ключи в .env (например, оставшиеся от старых версий) не роняют запуск
    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


def build_sub_url(token: str) -> str:
    base = settings.SUB_BASE_URL.rstrip("/") or f"http://{settings.SERVER_IP}:{settings.SUB_PORT}"
    return f"{base}/sub/{token}"


DEFAULT_PLANS = [
    {"days": 30,  "label": "30 дней",  "stars_price": 150},
    {"days": 90,  "label": "90 дней",  "stars_price": 350},
    {"days": 180, "label": "180 дней", "stars_price": 600},
]
