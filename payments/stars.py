from aiogram.types import LabeledPrice


def new_sub_invoice(
    label: str, stars_amount: int, plan_days: int, device_count: int, base_price: int
) -> dict:
    return {
        "title": f"VPN подписка — {label}",
        "description": f"{device_count} устройств на {plan_days} дней",
        "payload": f"new:{plan_days}:{device_count}:{base_price}",
        "provider_token": "",
        "currency": "XTR",
        "prices": [LabeledPrice(label=f"VPN {label}", amount=stars_amount)],
    }


def extend_sub_invoice(label: str, stars_amount: int, plan_days: int) -> dict:
    return {
        "title": f"Продление VPN — {label}",
        "description": f"Продление подписки на {plan_days} дней",
        "payload": f"extend:{plan_days}",
        "provider_token": "",
        "currency": "XTR",
        "prices": [LabeledPrice(label=f"Продление {label}", amount=stars_amount)],
    }


def add_device_invoice(stars_amount: int, extra_devices: int) -> dict:
    return {
        "title": f"Добавить устройств: +{extra_devices}",
        "description": f"Доплата за {extra_devices} дополнительных устройств",
        "payload": f"add_device:{extra_devices}",
        "provider_token": "",
        "currency": "XTR",
        "prices": [LabeledPrice(label=f"+{extra_devices} устройств", amount=stars_amount)],
    }
