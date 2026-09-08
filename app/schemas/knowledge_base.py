from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class KnowledgeBaseCreate(BaseModel):
    name: str
    genre: Optional[str] = ""
    source_work: Optional[str] = ""
    is_fanwork: Optional[bool] = False
    description: Optional[str] = ""


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    genre: Optional[str] = None
    source_work: Optional[str] = None
    is_fanwork: Optional[bool] = None
    description: Optional[str] = None


class KnowledgeBaseResponse(BaseModel):
    id: int
    name: str
    genre: Optional[str] = None
    source_work: Optional[str] = None
    is_fanwork: bool = False
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    import_status: Optional[str] = None
    import_progress: Optional[dict] = None
    volumes: Optional[list] = None
    volume_relations: Optional[list] = None

    class Config:
        from_attributes = True


class KnowledgeBaseListItem(BaseModel):
    id: int
    name: str
    genre: Optional[str] = None
    source_work: Optional[str] = None
    is_fanwork: bool = False
    description: Optional[str] = None
    entry_count: int = 0
    import_status: Optional[str] = "idle"
    import_progress: Optional[dict] = None
    volumes: Optional[list] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KnowledgeEntryCreate(BaseModel):
    category: str = "other"
    title: str
    content: str = ""
    attributes: Optional[dict] = None
    source: Optional[str] = "manual"
    volume: Optional[int] = None
    volume_title: Optional[str] = None
    chapter_number: Optional[int] = None
    chapter_title: Optional[str] = None


class KnowledgeEntryUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    attributes: Optional[dict] = None
    source: Optional[str] = None
    volume: Optional[int] = None
    volume_title: Optional[str] = None
    chapter_number: Optional[int] = None
    chapter_title: Optional[str] = None


class KnowledgeEntryResponse(BaseModel):
    id: int
    kb_id: int
    category: str
    title: str
    content: str = ""
    attributes: Optional[Any] = None
    source: str = "manual"
    volume: Optional[int] = None
    volume_title: Optional[str] = None
    chapter_number: Optional[int] = None
    chapter_title: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
