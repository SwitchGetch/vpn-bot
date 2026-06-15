from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: list[int] = []

    DATABASE_URL: str = "sqlite+aiosqlite:///vpn-bot.db"

    WG_CONTAINER: str = "amnezia-wg2"
    WG_INTERFACE: str = "wg0"
    WG_CONFIG_PATH: str = "/opt/amnezia/awg/wg0.conf"
    WG_SERVER_PUBLIC_IP: str
    WG_SERVER_PORT: int = 51820
    WG_SERVER_PUBLIC_KEY: str
    WG_SUBNET: str = "10.8.1.0/24"
    WG_DNS: str = "1.1.1.1"

    AWG_JC: int = 4
    AWG_JMIN: int = 40
    AWG_JMAX: int = 70
    AWG_S1: int = 0
    AWG_S2: int = 0
    AWG_S3: int = 0
    AWG_S4: int = 0
    AWG_H1: int = 1
    AWG_H2: int = 2
    AWG_H3: int = 3
    AWG_H4: int = 4

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    model_config = {"env_file": ".env"}


settings = Settings()

# Используется только для первоначального заполнения БД
DEFAULT_PLANS = [
    {"days": 30,  "label": "30 дней",  "stars_price": 150},
    {"days": 90,  "label": "90 дней",  "stars_price": 350},
    {"days": 180, "label": "180 дней", "stars_price": 600},
]
