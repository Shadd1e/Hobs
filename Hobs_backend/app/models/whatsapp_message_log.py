import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Enum
from sqlalchemy.sql import func

from app.db.base import Base   # IMPORTANT: use your existing SQLAlchemy Base


class WhatsappMessageLog(Base):
    __tablename__ = "whatsapp_message_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    merchant_id = Column(String, nullable=False)
    client_id = Column(String, nullable=True)

    from_number = Column(String, nullable=False)
    to_number = Column(String, nullable=True)

    direction = Column(Enum('incoming', 'outgoing', name='whatsapp_message_direction'), nullable=False)

    message = Column(Text, nullable=True)

    # JSON string (DeepSeek payloads, intent, etc)
    meta = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())