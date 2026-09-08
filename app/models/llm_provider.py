from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime, timezone
from app.database import Base


class LlmProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True)
    provider_type = Column(String(32), nullable=False)
    purpose = Column(String(32), nullable=False, default="common")
    name = Column(String(64), nullable=False)
    base_url = Column(String(256), nullable=False)
    api_key = Column(String(256), nullable=False, default="")
    chat_model = Column(String(128), nullable=False)
    embedding_model = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
