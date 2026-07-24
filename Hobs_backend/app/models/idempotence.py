from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    JSON,
    Integer,
    func,
    UniqueConstraint,
    Index,
)
from app.db.base import Base
from .utils import generate_uuid


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "key",
            name="uq_idempotency_merchant_key",
        ),
        Index(
            "ix_idempotency_merchant_key_expires",
            "merchant_id",
            "key",
            "expires_at",
        ),
    )

    # Primary key
    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Tenant scoping
    merchant_id = Column(String(20), nullable=False, index=True)
    key = Column(String, nullable=False, index=True)

    # Request identity
    request_hash = Column(String, nullable=True)

    # Cached response
    response_data = Column(JSON, nullable=True)
    response_status = Column(Integer, nullable=True)  # FIXED
    response_headers = Column(JSON, nullable=True)

    # Processing lock
    is_processing = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )