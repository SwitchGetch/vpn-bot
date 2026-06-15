import aiohttp

_API_URL = "https://pay.crypt.bot/api"


async def create_invoice(token: str, amount: str, description: str) -> dict:
    """Создаёт инвойс в USD через CryptoPay API (fiat mode).

    Пользователь сам выбирает криптовалюту для оплаты.
    Возвращает dict: {invoice_id, pay_url, amount, fiat}
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            f"{_API_URL}/createInvoice",
            headers={"Crypto-Pay-API-Token": token},
            json={
                "currency_type": "fiat",
                "fiat": "USD",
                "amount": amount,
                "description": description,
                "expires_in": 3600,
            },
        )
        resp.raise_for_status()
        data = await resp.json()

    if not data.get("ok"):
        raise RuntimeError(f"CryptoPay createInvoice error: {data}")

    item = data["result"]
    return {
        "invoice_id": item["invoice_id"],
        "pay_url": item["pay_url"],
        "amount": item["amount"],
        "fiat": item.get("fiat", "USD"),
    }


async def get_paid_invoices(token: str, invoice_ids: list[int]) -> list[dict]:
    """Возвращает список оплаченных инвойсов из переданных ID."""
    if not invoice_ids:
        return []
    async with aiohttp.ClientSession() as session:
        resp = await session.get(
            f"{_API_URL}/getInvoices",
            headers={"Crypto-Pay-API-Token": token},
            params={
                "invoice_ids": ",".join(str(i) for i in invoice_ids),
                "status": "paid",
            },
        )
        resp.raise_for_status()
        data = await resp.json()

    if not data.get("ok"):
        return []

    return data["result"]["items"]
