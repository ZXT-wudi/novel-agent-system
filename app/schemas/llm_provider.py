from pydantic import BaseModel
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.models.llm_provider import LlmProvider


class ProviderCreate(BaseModel):
    provider_type: str
    purpose: str = "common"
    name: str
    base_url: str
    api_key: str
    chat_model: str
    embedding_model: Optional[str] = None


class ProviderUpdate(BaseModel):
    provider_type: Optional[str] = None
    purpose: Optional[str] = None
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    chat_model: Optional[str] = None
    embedding_model: Optional[str] = None
    is_active: Optional[bool] = None


class ProviderResponse(BaseModel):
    id: int
    provider_type: str
    purpose: str = "common"
    name: str
    base_url: str
    api_key: str
    chat_model: str
    embedding_model: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def mask_api_key(key: str) -> str:
    if not key:
        return "未设置"
    if len(key) >= 4:
        return "****" + key[-4:]
    return "****"


def provider_to_response(p: "LlmProvider") -> ProviderResponse:
    return ProviderResponse(
        id=p.id,
        provider_type=p.provider_type,
        purpose=getattr(p, "purpose", None) or "common",
        name=p.name,
        base_url=p.base_url,
        api_key=mask_api_key(p.api_key),
        chat_model=p.chat_model,
        embedding_model=p.embedding_model,
        is_active=p.is_active,
        created_at=p.created_at,
    )
