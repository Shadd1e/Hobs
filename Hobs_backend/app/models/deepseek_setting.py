from sqlalchemy import Column, String, Boolean, Text, DateTime, ForeignKey, func, UniqueConstraint, Numeric
from sqlalchemy.orm import relationship
from app.db.base import Base
from .utils import generate_uuid


class DeepSeekSetting(Base):
    __tablename__ = "deepseek_settings"

    __table_args__ = (
        UniqueConstraint("client_id", name="uq_deepseek_setting_per_client"),
    )

    id = Column(String(36), primary_key=True, index=True, default=generate_uuid)

    client_id = Column(
        String(20),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    active = Column(Boolean, nullable=False, default=True)

    temperature = Column(Numeric(2, 1), nullable=False, default=0.5)

    extra_system_prompt = Column(Text, nullable=True)

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

    client = relationship("Client", lazy="joined")
