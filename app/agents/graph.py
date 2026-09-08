import asyncio
import logging
from app.agents.state import NovelState
from app.agents.writer_agent import revise_chapter
from app.agents.readers.character_reader import review_character
from app.agents.readers.logic_reader import review_logic
from app.agents.readers.style_reader import review_style
from app.config import settings
from app.llm.siliconflow import LLMError

logger = logging.getLogger(__name__)


async def load_context(state: NovelState) -> NovelState:
    state["current_phase"] = "loading_context"
    state.setdefault("revision_count", 0)
    state.setdefault("is_final", False)
    state.setdefault("review_comments", [])
    state.setdefault("writer_decisions", [])
    state.setdefault("pending_user_decisions", [])
    state.setdefault("user_decisions", [])
    return state


async def review_parallel(state: NovelState) -> NovelState:
    state["current_phase"] = "reviewing"

    async def _safe_review(coro, reader_type: str):
        try:
            return await coro
        except LLMError as e:
            logger.warning("%s 审查失败: %s", reader_type, e.message)
            return {"reader_type": reader_type, "comments": [], "overall_score": 0,
                    "overall_comment": f"审查失败: {e.message}"}
        except Exception as e:
            logger.warning("%s 审查异常: %s", reader_type, e, exc_info=True)
            return {"reader_type": reader_type, "comments": [], "overall_score": 0,
                    "overall_comment": f"审查异常: {e}"}

    results = await asyncio.gather(
        _safe_review(review_character(state), "character"),
        _safe_review(review_logic(state), "logic"),
        _safe_review(review_style(state), "style"),
        return_exceptions=False,
    )

    all_comments = []
    for result in results:
        comments = result.get("comments", [])
        for c in comments:
            c["reader_type"] = result.get("reader_type", "unknown")
        all_comments.extend(comments)

    state["review_comments"] = all_comments
    state["current_phase"] = "reviewed"
    return state


async def auto_revise(state: NovelState) -> NovelState:
    state["current_phase"] = "auto_revising"
    revision_count = state.get("revision_count", 0)
    if revision_count >= settings.MAX_REVISION_ROUNDS:
        logger.info("已达最大修订轮次 %d，跳过自动修订", revision_count)
        state["is_final"] = True
        return state
    state = await revise_chapter(state)
    return state


async def user_decision(state: NovelState) -> NovelState:
    state["current_phase"] = "waiting_user_decision"
    return state


async def apply_user_decision(state: NovelState) -> NovelState:
    state["current_phase"] = "applying_user_decision"
    user_decisions = state.get("user_decisions", [])
    pending = state.get("pending_user_decisions", [])

    accepted_from_user = []
    for decision in user_decisions:
        if decision.get("action") == "accept_suggestion":
            comment_id = decision.get("comment_id", "")
            for p in pending:
                if p.get("comment_id") == comment_id or p.get("original_comment", {}).get("comment_id") == comment_id:
                    accepted_from_user.append({
                        "comment_id": comment_id,
                        "decision": "accept",
                        "reason": "用户采纳建议",
                        "revision_plan": p.get("original_comment", {}).get("suggestion", ""),
                    })
                    break
        elif decision.get("action") == "custom":
            accepted_from_user.append({
                "comment_id": decision.get("comment_id", "custom"),
                "decision": "accept",
                "reason": "用户自定义修改",
                "revision_plan": decision.get("custom_text", ""),
            })

    state["writer_decisions"] = state.get("writer_decisions", []) + accepted_from_user
    state["pending_user_decisions"] = []
    state["user_decisions"] = []

    if accepted_from_user:
        state = await revise_chapter(state)
    else:
        state["is_final"] = True

    return state


async def check_revision(state: NovelState) -> str:
    if state.get("is_final", False):
        return "finalize"

    revision_count = state.get("revision_count", 0)
    if revision_count >= settings.MAX_REVISION_ROUNDS:
        state["is_final"] = True
        return "finalize"

    has_pending = bool(state.get("pending_user_decisions", []))
    if has_pending:
        return "user_decision"

    return "finalize"


async def evaluate_reviews_router(state: NovelState) -> str:
    phase = state.get("current_phase", "")
    if phase == "all_accepted":
        accepted = state.get("writer_decisions", [])
        if accepted:
            return "auto_revise"
        return "finalize"
    if phase == "has_rejected":
        return "user_decision"
    return "finalize"


async def finalize(state: NovelState) -> NovelState:
    state["current_phase"] = "finalized"
    state["is_final"] = True
    return state
