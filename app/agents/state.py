from typing import TypedDict, Optional


class NovelState(TypedDict, total=False):
    novel_id: int
    current_phase: str
    outline: list[dict]
    full_outline: dict
    current_chapter_number: int
    chapter_draft: str
    chapter_title: str
    polished_draft: Optional[str] = None
    previous_chapters_full: list[str]
    previous_semantics: list[dict]
    review_comments: list[dict]
    writer_decisions: list[dict]
    pending_user_decisions: list[dict]
    user_decisions: list[dict]
    revision_count: int
    is_final: bool
    rag_context: str
    outline_item: dict
    user_preference_summary: str
    story_knowledge: dict
    writing_style: str
    narrative_pov: str
    target_word_count: int
    knowledge_base_id: Optional[int]
    kb_context: str
    ordinary_kb_context: str
