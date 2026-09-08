from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    preference_type = Column(String(50), nullable=False)
    preference_key = Column(String(100), nullable=False)
    preference_value = Column(Text, nullable=False)
    source = Column(String(50))
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    novel = relationship("Novel", back_populates="preferences")


class ModificationRecord(Base):
    __tablename__ = "modification_records"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer)
    original_text = Column(Text, nullable=False)
    modified_text = Column(Text, nullable=False)
    modification_type = Column(String(50))
    reader_suggestion = Column(Text)
    user_decision = Column(String(20))
    user_note = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    novel = relationship("Novel", back_populates="modifications")
