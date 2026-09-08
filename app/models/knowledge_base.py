from sqlalchemy import Column, Integer, String, Text, JSON, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    genre = Column(String(50))
    source_work = Column(String(200))
    is_fanwork = Column(Boolean, default=False)
    description = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    volumes = Column(JSON, default=list)
    volume_relations = Column(JSON, default=list)
    import_status = Column(String(20), default="idle")
    import_progress = Column(JSON, default=dict)

    entries = relationship("KnowledgeEntry", back_populates="knowledge_base", cascade="all, delete-orphan")


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(50), nullable=False, default="other")
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    attributes = Column(JSON, default=dict)
    source = Column(String(30), default="manual")
    volume = Column(Integer, nullable=True)
    volume_title = Column(String(200), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    chapter_title = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    knowledge_base = relationship("KnowledgeBase", back_populates="entries")
