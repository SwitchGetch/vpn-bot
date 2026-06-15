from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_banned = Column(Boolean, default=False)

    configs = relationship("Config", back_populates="user", lazy="selectin")
    payments = relationship("Payment", back_populates="user", lazy="selectin")


class Config(Base):
    __tablename__ = "configs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    device_name = Column(String, nullable=False)
    peer_public_key = Column(String, nullable=False)
    peer_private_key = Column(String, nullable=False)
    peer_ip = Column(String, nullable=False)
    config_text = Column(String, nullable=False)
    plan_days = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="configs", lazy="selectin")
    payments = relationship("Payment", back_populates="config", lazy="selectin")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    config_id = Column(Integer, ForeignKey("configs.id"), nullable=True)
    amount = Column(String, nullable=False)          # "150" (stars) / "19900" (kopeks) / "2.50" (usdt)
    currency = Column(String, nullable=False)        # XTR / RUB / USDT / TON
    payment_method = Column(String, nullable=False)  # stars / yookassa / crypto
    charge_id = Column(String, nullable=True)        # telegram charge id или cryptopay invoice id
    plan_days = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="payments", lazy="selectin")
    config = relationship("Config", back_populates="payments", lazy="selectin")


class Plan(Base):
    """Тариф — управляется через админ-панель."""
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    days = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    stars_price = Column(Integer, nullable=False)
    rub_kopeks = Column(Integer, nullable=True)   # цена в копейках для ЮKassa (199₽ = 19900)
    usdt_price = Column(String, nullable=True)    # цена в USDT для CryptoPay ("2.50")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class BotSetting(Base):
    """Динамические настройки бота — управляются через админ-панель."""
    __tablename__ = "bot_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False, default="")


class CryptoPendingInvoice(Base):
    """Ожидающий оплаты крипто-инвойс."""
    __tablename__ = "crypto_pending_invoices"

    id = Column(Integer, primary_key=True)
    cryptopay_invoice_id = Column(Integer, nullable=False, unique=True)
    user_chat_id = Column(BigInteger, nullable=False)
    action = Column(String, nullable=False)       # new / extend
    plan_days = Column(Integer, nullable=False)
    asset = Column(String, nullable=False)        # USDT / TON
    device_name = Column(String, nullable=True)   # для action=new
    config_id = Column(Integer, nullable=True)    # для action=extend
    created_at = Column(DateTime, default=datetime.utcnow)
