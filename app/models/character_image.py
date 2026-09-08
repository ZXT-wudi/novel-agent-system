from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from datetime import datetime, timezone
from app.database import Base


class CharacterImage(Base):
    __tablename__ = "character_images"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    stage_index = Column(Integer, nullable=False)
    character_name = Column(String(100), nullable=False)
    image_path = Column(String(500), nullable=False)
    prompt = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("novel_id", "stage_index", "character_name", name="uq_novel_stage_char"),)
