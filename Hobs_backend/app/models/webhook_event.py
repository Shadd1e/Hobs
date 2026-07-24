from sqlalchemy import Column, String, Text, DateTime, func, Index
from app.db.base import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    # Provider event ID (Meta message id, Paystack event id, etc)
    id = Column(String(128), primary_key=True)

    provider = Column(String(50), nullable=False, index=True)

    client_id = Column(String(20), nullable=False, index=True)

    phone_number_id = Column(String(255), nullable=True, index=True)

    details = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_webhook_provider_client", "provider", "client_id"),
    )
