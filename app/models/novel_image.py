from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from datetime import datetime, timezone
from app.database import Base


class NovelImage(Base):
    __tablename__ = "novel_images"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    image_type = Column(String(50), nullable=False)
    image_key = Column(String(200), nullable=False, default="")
    image_path = Column(String(500), nullable=False)
    prompt = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("novel_id", "image_type", "image_key", name="uq_novel_type_key"),)
