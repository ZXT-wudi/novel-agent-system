from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class StoryKnowledge(Base):
    __tablename__ = "story_knowledge"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)

    characters = Column(JSON, default=list)
    character_relations = Column(JSON, default=list)
    world_elements = Column(JSON, default=list)
    chapter_summary = Column(Text, default="")
    plot_points = Column(JSON, default=list)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    novel = relationship("Novel", back_populates="story_knowledge")

    __table_args__ = (UniqueConstraint("novel_id", "chapter_number", name="uq_novel_knowledge"),)
