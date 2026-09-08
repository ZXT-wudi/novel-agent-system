from pydantic import BaseModel
from typing import Optional


class OutlineChapterItem(BaseModel):
    chapter_number: int
    title: str = ""
    plot_summary: str = ""
    key_events: list[str] = []
    characters: list[str] = []
    notes: str = ""


class OutlineGenerateRequest(BaseModel):
    description: Optional[str] = None
    genre: Optional[str] = None
    target_chapters: Optional[int] = None


class FullOutlineGenerateRequest(BaseModel):
    description: Optional[str] = None
    genre: Optional[str] = None
    length_type: Optional[str] = "short"
    target_word_count: Optional[int] = None
    use_web_research: bool = False
    world_settings: Optional[dict] = None
    characters: Optional[list] = None


class ChapterOutlineGenerateRequest(BaseModel):
    batch_size: int = 10
    start_chapter: int = 1


class OutlineUpdateRequest(BaseModel):
    outline: list[OutlineChapterItem]


class FullOutlineUpdateRequest(BaseModel):
    full_outline: dict


class OutlineConfirmRequest(BaseModel):
    confirmed: bool = True
