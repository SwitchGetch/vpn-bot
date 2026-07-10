import secrets
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

    subscription = relationship("Subscription", back_populates="user", uselist=False, lazy="selectin")
    payments = relationship("Payment", back_populates="user", lazy="selectin")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    name = Column(String, nullable=False, default="Моя подписка")
    plan_days = Column(Integer, nullable=False)
    max_devices = Column(Integer, nullable=False, default=1)
    base_device_price = Column(Integer, nullable=False, default=0)  # stars per device per plan_days
    sub_token = Column(String, unique=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    reminder_sent = Column(Boolean, nullable=False, default=False)  # напоминание об истечении уже отправлено

    user = relationship("User", back_populates="subscription", lazy="selectin")
    devices = relationship("Device", back_populates="subscription", lazy="selectin", cascade="all, delete-orphan")
    hwid_devices = relationship("HwidDevice", back_populates="subscription", lazy="selectin", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="subscription", lazy="selectin")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    xray_uuid = Column(String, unique=True, nullable=False)
    device_name = Column(String, nullable=False, default="Устройство")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    subscription = relationship("Subscription", back_populates="devices", lazy="selectin")


class HwidDevice(Base):
    """Физическое устройство, подключившееся по subscription URL (идентифицируется по X-Hwid заголовку)."""
    __tablename__ = "hwid_devices"

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    hwid = Column(String, nullable=False)
    device_model = Column(String, nullable=True)
    device_os = Column(String, nullable=True)
    os_version = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_blocked = Column(Boolean, default=False)

    subscription = relationship("Subscription", back_populates="hwid_devices", lazy="selectin")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    amount = Column(String, nullable=False)       # "150" (stars) / "19900" (kopeks) / "2.50" (usdt)
    currency = Column(String, nullable=False)     # XTR / RUB / USDT / TON
    payment_method = Column(String, nullable=False)  # stars / yookassa / crypto
    charge_id = Column(String, nullable=True)
    plan_days = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="payments", lazy="selectin")
    subscription = relationship("Subscription", back_populates="payments", lazy="selectin")


class Plan(Base):
    """Тариф. stars_price = базовая цена за 1 устройство за период."""
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    days = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    stars_price = Column(Integer, nullable=False)   # base price per device per period
    rub_kopeks = Column(Integer, nullable=True)
    usdt_price = Column(String, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False, default="")


class CryptoPendingInvoice(Base):
    __tablename__ = "crypto_pending_invoices"

    id = Column(Integer, primary_key=True)
    cryptopay_invoice_id = Column(Integer, nullable=False, unique=True)
    user_chat_id = Column(BigInteger, nullable=False)
    action = Column(String, nullable=False)          # new / extend / add_device
    plan_days = Column(Integer, nullable=False)
    device_count = Column(Integer, nullable=False, default=1)
    base_device_price = Column(Integer, nullable=False, default=0)  # stars за устройство, для будущих апгрейдов
    asset = Column(String, nullable=False)
    subscription_id = Column(Integer, nullable=True)  # for extend / add_device
    created_at = Column(DateTime, default=datetime.utcnow)
