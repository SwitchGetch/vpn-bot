from aiogram.types import LabeledPrice


def new_config_invoice(label: str, stars_amount: int, plan_days: int, device_name: str) -> dict:
    return {
        "title": f"Config — {label}",
        "description": f"Конфиг для устройства: {device_name}",
        "payload": f"new:{plan_days}",
        "provider_token": "",
        "currency": "XTR",
        "prices": [LabeledPrice(label=f"VPN {label}", amount=stars_amount)],
    }


def extend_config_invoice(label: str, stars_amount: int, plan_days: int, config_id: int) -> dict:
    return {
        "title": f"Продление VPN — {label}",
        "description": f"Продление конфига на {plan_days} дней",
        "payload": f"extend:{config_id}:{plan_days}",
        "provider_token": "",
        "currency": "XTR",
        "prices": [LabeledPrice(label=f"Продление {label}", amount=stars_amount)],
    }
