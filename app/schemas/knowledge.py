from pydantic import BaseModel
from typing import Optional


class CharacterInfo(BaseModel):
    name: str
    role: str = "配角"
    description: str = ""
    first_appear: int = 0
    status: str = "active"


class CharacterRelation(BaseModel):
    from_character: str
    to_character: str
    type: str = ""
    description: str = ""


class WorldElement(BaseModel):
    category: str = ""
    name: str = ""
    description: str = ""
    related_characters: list[str] = []


class StoryKnowledgeCreate(BaseModel):
    characters: list[dict] = []
    character_relations: list[dict] = []
    world_elements: list[dict] = []
    chapter_summary: str = ""
    plot_points: list[str] = []


class StoryKnowledgeUpdate(BaseModel):
    characters: Optional[list[dict]] = None
    character_relations: Optional[list[dict]] = None
    world_elements: Optional[list[dict]] = None
    chapter_summary: Optional[str] = None
    plot_points: Optional[list[str]] = None


class StoryKnowledgeResponse(BaseModel):
    id: int
    novel_id: int
    chapter_number: int
    characters: list = []
    character_relations: list = []
    world_elements: list = []
    chapter_summary: str = ""
    plot_points: list = []

    class Config:
        from_attributes = True


class GraphNode(BaseModel):
    id: str
    type: str
    name: str
    role: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    chapters: list[int] = []
    number: Optional[int] = None


class GraphLink(BaseModel):
    source: str
    target: str
    type: str = ""
    label: str = ""


class GraphData(BaseModel):
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []
