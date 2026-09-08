from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NovelCreate(BaseModel):
    title: str
    genre: Optional[str] = None
    description: Optional[str] = None
    length_type: Optional[str] = "short"
    writing_style: Optional[str] = None
    target_word_count: Optional[int] = None
    narrative_pov: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    ordinary_knowledge_base_id: Optional[int] = None
    world_settings: Optional[dict] = None
    characters: Optional[list] = None


class NovelQARequest(BaseModel):
    title: str
    content: str
    writing_style: str
    target_word_count: int
    length_type: str = "short"
    genre: str = ""
    knowledge_base_id: Optional[int] = None
    ordinary_knowledge_base_id: Optional[int] = None


class NovelUpdate(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    description: Optional[str] = None
    length_type: Optional[str] = None
    writing_style: Optional[str] = None
    target_word_count: Optional[int] = None
    narrative_pov: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    ordinary_knowledge_base_id: Optional[int] = None
    world_settings: Optional[dict] = None
    characters: Optional[list] = None


class NovelResponse(BaseModel):
    id: int
    title: str
    genre: Optional[str] = None
    description: Optional[str] = None
    length_type: str = "short"
    writing_style: Optional[str] = None
    target_word_count: Optional[int] = None
    narrative_pov: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    ordinary_knowledge_base_id: Optional[int] = None
    full_outline: dict = {}
    outline: list = []
    world_settings: dict = {}
    characters: list = []
    status: str = "planning"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    chapter_count: int = 0

    class Config:
        from_attributes = True


class NovelListResponse(BaseModel):
    id: int
    title: str
    genre: Optional[str] = None
    length_type: str = "short"
    target_word_count: Optional[int] = None
    status: str = "planning"
    chapter_count: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
