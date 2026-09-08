from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.llm_provider import LlmProvider
from app.schemas.llm_provider import (
    ProviderCreate,
    ProviderUpdate,
    provider_to_response,
)

router = APIRouter()

VALID_PURPOSES = {"author", "image", "polish", "common"}
ALL_PURPOSES = ["author", "image", "polish", "common"]


@router.get("/")
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LlmProvider).order_by(LlmProvider.created_at))
    rows = result.scalars().all()
    return [provider_to_response(p) for p in rows]


@router.post("/")
async def create_provider(payload: ProviderCreate, db: AsyncSession = Depends(get_db)):
    if payload.purpose not in VALID_PURPOSES:
        raise HTTPException(status_code=400, detail=f"用途非法，只能是：{', '.join(sorted(VALID_PURPOSES))}")
    try:
        provider = LlmProvider(
            provider_type=payload.provider_type,
            purpose=payload.purpose,
            name=payload.name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            chat_model=payload.chat_model,
            embedding_model=payload.embedding_model,
        )
        db.add(provider)
        await db.commit()
        await db.refresh(provider)
        return provider_to_response(provider)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{provider_id}")
async def update_provider(provider_id: int, payload: ProviderUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    updates = payload.model_dump(exclude_unset=True)
    if "purpose" in updates and updates["purpose"] not in VALID_PURPOSES:
        raise HTTPException(status_code=400, detail=f"用途非法，只能是：{', '.join(sorted(VALID_PURPOSES))}")
    for key, value in updates.items():
        setattr(provider, key, value)
    await db.commit()
    await db.refresh(provider)
    return provider_to_response(provider)


@router.delete("/{provider_id}")
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    await db.delete(provider)
    await db.commit()
    return {"ok": True}


@router.get("/active")
async def get_active_provider(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LlmProvider).where(LlmProvider.is_active == True))
    actives = result.scalars().all()
    if not actives:
        return None
    by_purpose = {}
    for p in actives:
        purpose = getattr(p, "purpose", None) or "common"
        if purpose not in by_purpose:
            by_purpose[purpose] = provider_to_response(p)
    return by_purpose


@router.post("/{provider_id}/activate")
async def activate_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    purpose = getattr(provider, "purpose", None) or "common"
    await db.execute(
        update(LlmProvider).where(LlmProvider.purpose == purpose).values(is_active=False)
    )
    provider.is_active = True
    await db.commit()
    await db.refresh(provider)
    from app.llm.siliconflow import reconfigure_llm_client
    await reconfigure_llm_client()
    return provider_to_response(provider)
