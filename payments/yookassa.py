from aiogram.types import LabeledPrice

from database.models import Plan


def new_sub_invoice(
    plan: Plan, rub_kopeks: int, device_count: int, base_price: int, provider_token: str
) -> dict:
    return {
        "title": f"VPN подписка — {plan.label}",
        "description": f"{device_count} устройств на {plan.days} дней",
        "payload": f"new:{plan.days}:{device_count}:{base_price}",
        "provider_token": provider_token,
        "currency": "RUB",
        "prices": [LabeledPrice(label=f"VPN {plan.label}", amount=rub_kopeks)],
        "need_email": False,
        "send_email_to_provider": False,
    }


def extend_sub_invoice(plan: Plan, rub_kopeks: int, provider_token: str) -> dict:
    return {
        "title": f"Продление VPN — {plan.label}",
        "description": f"Продление подписки на {plan.days} дней",
        "payload": f"extend:{plan.days}",
        "provider_token": provider_token,
        "currency": "RUB",
        "prices": [LabeledPrice(label=f"Продление {plan.label}", amount=rub_kopeks)],
        "need_email": False,
        "send_email_to_provider": False,
    }
