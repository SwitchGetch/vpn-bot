from aiogram.types import LabeledPrice

from database.models import Plan


def new_config_invoice(plan: Plan, device_name: str, provider_token: str) -> dict:
    return {
        "title": f"VPN — {plan.label}",
        "description": f"Конфиг для устройства: {device_name}",
        "payload": f"new:{plan.days}",
        "provider_token": provider_token,
        "currency": "RUB",
        "prices": [LabeledPrice(label=f"VPN {plan.label}", amount=plan.rub_kopeks)],
        "need_email": False,
        "send_email_to_provider": False,
    }


def extend_config_invoice(plan: Plan, config_id: int, provider_token: str) -> dict:
    return {
        "title": f"Продление VPN — {plan.label}",
        "description": "Продление существующего конфига",
        "payload": f"extend:{config_id}:{plan.days}",
        "provider_token": provider_token,
        "currency": "RUB",
        "prices": [LabeledPrice(label=f"Продление {plan.label}", amount=plan.rub_kopeks)],
        "need_email": False,
        "send_email_to_provider": False,
    }
