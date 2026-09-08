from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ChapterResponse(BaseModel):
    id: int
    novel_id: int
    chapter_number: int
    title: Optional[str] = None
    content: str = ""
    version: int = 1
    status: str = "draft"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChapterListResponse(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    status: str = "draft"
    version: int = 1

    class Config:
        from_attributes = True


class ChapterUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class ChapterVersionResponse(BaseModel):
    id: int
    chapter_id: int
    version: int
    content: str
    source: Optional[str] = None
    review_comments: Optional[dict] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
