import logging

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Integer,
    Boolean,
    ForeignKey,
    func,
)
from sqlalchemy.orm import relationship

from app.infrastructure.db.base import Base

logger = logging.getLogger(__name__)


class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(String(6), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    failed_attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    clients = relationship("Client", back_populates="merchant", cascade="all, delete-orphan", lazy="selectin")
    products = relationship("Product", back_populates="merchant", cascade="all, delete-orphan", lazy="selectin")
    carts = relationship("Cart", back_populates="merchant", cascade="all, delete-orphan", lazy="selectin")
    payments = relationship("Payment", back_populates="merchant", cascade="all, delete-orphan", lazy="selectin")
    orders = relationship("Order", back_populates="merchant", cascade="all, delete-orphan", lazy="selectin")
    inventories = relationship("Inventory", back_populates="merchant", cascade="all, delete-orphan", lazy="selectin")
    human_agent_tasks = relationship("HumanAgent", back_populates="merchant", cascade="all, delete-orphan", lazy="selectin")

    @property
    def all_whatsapp_credentials(self):
        return [c.whatsapp_credential for c in self.clients if c.whatsapp_credential]

    @property
    def active_whatsapp_credentials(self):
        return [c for c in self.all_whatsapp_credentials if c.active]

    def __repr__(self):
        return f"<Merchant(id={self.id}, name={self.name})>"


class Client(Base):
    __tablename__ = "clients"

    id = Column(String(length=6), primary_key=True, index=True)
    name = Column(String, nullable=False)
    whatsapp_number = Column(String(20), nullable=False)
    store_contact_number = Column(String(20), nullable=False)

    # The WhatsApp number authorised to confirm cash orders/pickups.
    # Must be stored without '+' prefix for easy comparison.
    confirm_whatsapp_number = Column(String(30), nullable=True, index=True)

    merchant_id = Column(
        String(length=6),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    merchant = relationship("Merchant", back_populates="clients", lazy="joined")
    whatsapp_credential = relationship(
        "ClientWhatsAppCredential",
        back_populates="client",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
        single_parent=True,
    )

    products = relationship("Product", back_populates="client", cascade="all, delete-orphan", lazy="selectin")
    orders = relationship("Order", back_populates="client", cascade="all, delete-orphan", lazy="selectin")
    carts = relationship("Cart", back_populates="client", cascade="all, delete-orphan", lazy="selectin")
    payments = relationship("Payment", back_populates="client", cascade="all, delete-orphan", lazy="selectin")
    inventories = relationship("Inventory", back_populates="client", cascade="all, delete-orphan", lazy="selectin")
    human_agent_tasks = relationship("HumanAgent", back_populates="client", cascade="all, delete-orphan", lazy="selectin")

    @property
    def has_whatsapp_credential(self) -> bool:
        return self.whatsapp_credential is not None

    @property
    def active_whatsapp_credential(self):
        if self.whatsapp_credential and self.whatsapp_credential.active:
            return self.whatsapp_credential
        return None

    @property
    def meta_phone_number_id(self):
        return self.whatsapp_credential.phone_number_id if self.whatsapp_credential else None

    @property
    def is_whatsapp_verified(self) -> bool:
        return bool(self.whatsapp_credential and self.whatsapp_credential.verified)

    def is_store_number(self, phone: str) -> bool:
        """Return True if `phone` matches the authorised store confirmation number."""
        if not self.confirm_whatsapp_number:
            return False
        return phone.replace("+", "").strip() == self.confirm_whatsapp_number.replace("+", "").strip()

    def __repr__(self):
        return f"<Client(id={self.id}, name={self.name}, merchant_id={self.merchant_id})>"


class ClientWhatsAppCredential(Base):
    __tablename__ = "client_whatsapp_credentials"

    client_id = Column(
        String(length=6),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    phone_number_id = Column(String(255), nullable=False, unique=True, index=True)
    whatsapp_number = Column(String(20), nullable=True)
    active = Column(Boolean, default=True, index=True)
    verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    client = relationship(
        "Client",
        back_populates="whatsapp_credential",
        uselist=False,
        lazy="selectin",
        single_parent=True,
    )

    @property
    def merchant_id(self):
        return self.client.merchant_id if self.client else None
