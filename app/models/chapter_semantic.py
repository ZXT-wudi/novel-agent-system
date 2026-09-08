from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class ChapterSemantic(Base):
    __tablename__ = "chapter_semantics"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    summary = Column(Text, nullable=False, default="")
    keywords = Column(JSON, nullable=False, default=list)
    characters_involved = Column(JSON, default=list)
    plot_points = Column(JSON, default=list)
    emotional_arc = Column(String(50))
    timeline_position = Column(Text)
    vector_id = Column(String(200))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    novel = relationship("Novel", back_populates="semantics")

    __table_args__ = (UniqueConstraint("novel_id", "chapter_number", name="uq_novel_semantic"),)
