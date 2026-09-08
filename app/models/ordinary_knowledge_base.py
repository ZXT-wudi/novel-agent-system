from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class OrdinaryKnowledgeBase(Base):
    __tablename__ = "ordinary_knowledge_bases"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    genre = Column(String(50))
    source_work = Column(String(200))
    description = Column(Text)
    import_status = Column(String(20), default="idle")
    import_progress = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    entries = relationship("OrdinaryKnowledgeEntry", back_populates="ordinary_kb", cascade="all, delete-orphan", passive_deletes=True)


class OrdinaryKnowledgeEntry(Base):
    __tablename__ = "ordinary_knowledge_entries"
    __table_args__ = (UniqueConstraint("base_id", "dimension", name="uq_ordinary_kb_dim"),)

    id = Column(Integer, primary_key=True)
    base_id = Column(Integer, ForeignKey("ordinary_knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    dimension = Column(String(32), nullable=False)
    content = Column(Text, nullable=False, default="")
    attributes = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    ordinary_kb = relationship("OrdinaryKnowledgeBase", back_populates="entries")
