import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.chapter import ChapterResponse, ChapterListResponse, ChapterUpdate, ChapterVersionResponse
from app.services import chapter_service
from app.llm.siliconflow import LLMError
from app.agents.writer_agent import suggest_continuation
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

_active_writing_sessions: dict[str, dict] = {}


@router.post("/{novel_id}/chapters/generate")
async def generate_chapter(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    chapter_number = data.get("chapter_number", 1)
    use_stream = data.get("stream", True)

    if use_stream:
        async def stream_generator():
            try:
                async for chunk in chapter_service.generate_chapter_with_stream(db, novel_id, chapter_number):
                    yield chunk
            except LLMError as e:
                yield json.dumps({"type": "error", "error": f"AI服务暂时不可用: {e.message}"}, ensure_ascii=False) + "\n"
            except Exception as e:
                yield json.dumps({"type": "error", "error": f"写作失败: {str(e)}"}, ensure_ascii=False) + "\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        try:
            result = await chapter_service.generate_chapter(db, novel_id, chapter_number)
            if "error" in result:
                raise HTTPException(status_code=404, detail=result["error"])
            return result
        except LLMError as e:
            raise HTTPException(status_code=503, detail=f"AI服务暂时不可用，请稍后重试: {e.message}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"写作失败: {str(e)}")


@router.get("/{novel_id}/chapters", response_model=list[ChapterListResponse])
async def list_chapters(novel_id: int, db: AsyncSession = Depends(get_db)):
    chapters = await chapter_service.get_chapters(db, novel_id)
    return [
        ChapterListResponse(
            chapter_number=ch.chapter_number,
            title=ch.title,
            status=ch.status,
            version=ch.version,
        )
        for ch in chapters
    ]


@router.get("/{novel_id}/chapters/{chapter_num}", response_model=ChapterResponse)
async def get_chapter(novel_id: int, chapter_num: int, db: AsyncSession = Depends(get_db)):
    chapter = await chapter_service.get_chapter(db, novel_id, chapter_num)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.put("/{novel_id}/chapters/{chapter_num}", response_model=ChapterResponse)
async def update_chapter(novel_id: int, chapter_num: int, data: ChapterUpdate, db: AsyncSession = Depends(get_db)):
    chapter = await chapter_service.get_chapter(db, novel_id, chapter_num)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    if data.title is not None:
        chapter.title = data.title
    if data.content is not None:
        from app.models.chapter import ChapterVersion
        version = ChapterVersion(
            chapter_id=chapter.id,
            version=chapter.version,
            content=chapter.content,
            source="user_edit",
        )
        db.add(version)
        chapter.version += 1
        chapter.content = data.content

    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.get("/{novel_id}/chapters/{chapter_num}/versions", response_model=list[ChapterVersionResponse])
async def get_chapter_versions(novel_id: int, chapter_num: int, db: AsyncSession = Depends(get_db)):
    versions = await chapter_service.get_chapter_versions(db, novel_id, chapter_num)
    return versions


@router.post("/{novel_id}/chapters/{chapter_num}/save")
async def save_and_finalize(novel_id: int, chapter_num: int, data: dict, db: AsyncSession = Depends(get_db)):
    content = data.get("content", "")
    title = data.get("title", f"第{chapter_num}章")
    status = data.get("status", "final")
    if status not in ("final", "draft"):
        status = "final"

    chapter = await chapter_service.save_chapter(db, novel_id, chapter_num, content, title, status)
    if status == "final":
        try:
            await chapter_service.save_chapter_semantic(db, novel_id, chapter_num, content)
        except LLMError as e:
            logger.warning("章节语义提取失败 novel=%s chapter=%s: %s", novel_id, chapter_num, e.message)

    return {"message": "章节已保存" if status == "final" else "草稿已保存", "chapter_number": chapter_num, "status": status}


@router.post("/{novel_id}/chapters/{chapter_num}/suggest")
async def suggest_chapter_continuation(novel_id: int, chapter_num: int, data: dict, db: AsyncSession = Depends(get_db)):
    current_text = data.get("current_text", "")
    try:
        state = await chapter_service._build_chapter_state(db, novel_id, chapter_num)
        if not state:
            return {"suggestion": ""}
        suggestion = await suggest_continuation(state, current_text)
        return {"suggestion": suggestion}
    except Exception:
        logger.exception("续写建议接口异常 novel=%s chapter=%s", novel_id, chapter_num)
        return {"suggestion": ""}


@router.get("/{novel_id}/chapters/{chapter_num}/state")
async def get_chapter_state(novel_id: int, chapter_num: int):
    key = f"{novel_id}_{chapter_num}"
    state = _active_writing_sessions.get(key)
    if not state:
        return {"current_phase": "idle", "pending_user_decisions": []}
    return chapter_service._state_to_response(state)


@router.post("/{novel_id}/chapters/{chapter_num}/state")
async def set_chapter_state(novel_id: int, chapter_num: int, data: dict):
    key = f"{novel_id}_{chapter_num}"
    _active_writing_sessions[key] = data
    return {"message": "状态已保存"}
