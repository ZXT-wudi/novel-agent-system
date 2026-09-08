from pydantic import BaseModel
from typing import Optional


class PreferenceCreate(BaseModel):
    preference_type: str
    preference_key: str
    preference_value: str
    source: Optional[str] = "user_explicit"
    weight: Optional[float] = 1.0


class PreferenceResponse(BaseModel):
    id: int
    novel_id: int
    preference_type: str
    preference_key: str
    preference_value: str
    source: Optional[str] = None
    weight: float = 1.0

    class Config:
        from_attributes = True


class KnowledgeCreate(BaseModel):
    category: str
    name: str
    content: str
    related_characters: list[str] = []


class KnowledgeResponse(BaseModel):
    id: str
    category: str
    name: str
    content: str
    related_characters: list[str] = []
