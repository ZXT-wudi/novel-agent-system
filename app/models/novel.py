from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Novel(Base):
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    genre = Column(String(50))
    description = Column(Text)
    length_type = Column(String(20), default="short")
    writing_style = Column(String(200))
    target_word_count = Column(Integer)
    narrative_pov = Column(String(50))
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True)
    ordinary_knowledge_base_id = Column(Integer, ForeignKey("ordinary_knowledge_bases.id", ondelete="SET NULL"), nullable=True)
    full_outline = Column(JSON, default=dict)
    outline = Column(JSON, nullable=False, default=list)
    world_settings = Column(JSON, default=dict)
    characters = Column(JSON, default=list)
    status = Column(String(20), default="planning")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True, order_by="Chapter.chapter_number")
    semantics = relationship("ChapterSemantic", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True, order_by="ChapterSemantic.chapter_number")
    preferences = relationship("UserPreference", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True)
    modifications = relationship("ModificationRecord", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True)
    story_knowledge = relationship("StoryKnowledge", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True, order_by="StoryKnowledge.chapter_number")
