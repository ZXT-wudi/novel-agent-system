from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    title = Column(String(200))
    content = Column(Text, nullable=False, default="")
    version = Column(Integer, default=1)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    novel = relationship("Novel", back_populates="chapters")
    versions = relationship("ChapterVersion", back_populates="chapter", cascade="all, delete-orphan", order_by="ChapterVersion.version")

    __table_args__ = (UniqueConstraint("novel_id", "chapter_number", name="uq_novel_chapter"),)


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"

    id = Column(Integer, primary_key=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String(50))
    review_comments = Column(JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    chapter = relationship("Chapter", back_populates="versions")

    __table_args__ = (UniqueConstraint("chapter_id", "version", name="uq_chapter_version"),)
