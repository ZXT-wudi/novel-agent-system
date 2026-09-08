from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.review import UserDecisionRequest
from app.services import review_service
from app.services.chapter_service import _state_to_response
from app.agents.state import NovelState
import time
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

_active_states: dict[str, dict] = {}
_TTL_SECONDS = 1800


def _cleanup_expired_states():
    now = time.time()
    expired = [k for k, v in _active_states.items() if now - v["timestamp"] > _TTL_SECONDS]
    for k in expired:
        del _active_states[k]
        logger.info("清理过期写作状态: %s", k)


def _set_active_state(key: str, state: NovelState):
    _cleanup_expired_states()
    _active_states[key] = {"state": state, "timestamp": time.time()}


def _get_active_state(key: str) -> NovelState | None:
    _cleanup_expired_states()
    entry = _active_states.get(key)
    return entry["state"] if entry else None


def _del_active_state(key: str):
    _active_states.pop(key, None)


@router.post("/{novel_id}/chapters/{chapter_num}/review")
async def trigger_review(novel_id: int, chapter_num: int, data: dict, db: AsyncSession = Depends(get_db)):
    from app.agents.graph import review_parallel
    from app.agents.writer_agent import evaluate_reviews

    state: NovelState = data.get("state", {})
    if not state:
        raise HTTPException(status_code=400, detail="缺少写作状态数据")

    state = await review_parallel(state)
    state = await evaluate_reviews(state)

    key = f"{novel_id}_{chapter_num}"
    _set_active_state(key, state)

    return _state_to_response(state)


@router.get("/{novel_id}/chapters/{chapter_num}/reviews")
async def get_reviews(novel_id: int, chapter_num: int):
    key = f"{novel_id}_{chapter_num}"
    state = _get_active_state(key)
    if not state:
        return {"review_comments": [], "writer_decisions": [], "pending_user_decisions": []}
    return _state_to_response(state)


@router.post("/{novel_id}/chapters/{chapter_num}/decide")
async def user_decide(novel_id: int, chapter_num: int, data: UserDecisionRequest, db: AsyncSession = Depends(get_db)):
    key = f"{novel_id}_{chapter_num}"
    state = _get_active_state(key)
    if not state:
        raise HTTPException(status_code=400, detail="没有待决策的审查意见或状态已过期")

    decisions = [d.model_dump() if hasattr(d, "model_dump") else d for d in data.decisions]
    result = await review_service.process_user_decisions(db, novel_id, chapter_num, state, decisions)

    if result.get("is_final", False):
        _del_active_state(key)

    return result


@router.post("/{novel_id}/chapters/{chapter_num}/finalize")
async def finalize_chapter(novel_id: int, chapter_num: int, db: AsyncSession = Depends(get_db)):
    key = f"{novel_id}_{chapter_num}"
    state = _get_active_state(key)
    if not state:
        raise HTTPException(status_code=400, detail="没有进行中的写作会话或状态已过期")

    result = await review_service.finalize_chapter(db, novel_id, chapter_num, state)

    _del_active_state(key)

    return result
