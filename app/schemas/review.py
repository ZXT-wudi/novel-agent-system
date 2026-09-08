from pydantic import BaseModel
from typing import Optional


class ReviewComment(BaseModel):
    reader_type: str
    comment: str
    suggestion: str
    severity: str = "medium"


class ReviewResponse(BaseModel):
    chapter_number: int
    reviews: list[ReviewComment]
    writer_decisions: list[dict] = []
    pending_user_decisions: list[dict] = []


class UserDecisionRequest(BaseModel):
    decisions: list[dict]


class UserDecisionItem(BaseModel):
    comment_id: str
    action: str
    custom_text: Optional[str] = None
