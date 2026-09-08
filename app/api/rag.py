from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.preference import PreferenceCreate, PreferenceResponse, KnowledgeCreate, KnowledgeResponse
from app.services import preference_service
from app.services.knowledge_service import import_document_to_knowledge
from app.agents.rewrite_agent import rewrite_multi_stream
from app.services.chapter_service import _build_chapter_state
from app.llm.siliconflow import LLMError
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{novel_id}/rag/preferences", response_model=PreferenceResponse)
async def add_preference(novel_id: int, data: PreferenceCreate, db: AsyncSession = Depends(get_db)):
    pref = await preference_service.add_preference(db, novel_id, data)
    return pref


@router.get("/{novel_id}/rag/preferences", response_model=list[PreferenceResponse])
async def list_preferences(novel_id: int, db: AsyncSession = Depends(get_db)):
    return await preference_service.get_preferences(db, novel_id)


@router.delete("/{novel_id}/rag/preferences/{pref_id}")
async def delete_preference(novel_id: int, pref_id: int, db: AsyncSession = Depends(get_db)):
    success = await preference_service.delete_preference(db, novel_id, pref_id)
    if not success:
        raise HTTPException(status_code=404, detail="偏好不存在")
    return {"message": "删除成功"}


@router.post("/{novel_id}/rag/knowledge", response_model=KnowledgeResponse)
async def add_knowledge(novel_id: int, data: KnowledgeCreate, db: AsyncSession = Depends(get_db)):
    return await preference_service.add_knowledge(novel_id, data)


@router.get("/{novel_id}/rag/knowledge", response_model=list[KnowledgeResponse])
async def list_knowledge(novel_id: int, db: AsyncSession = Depends(get_db)):
    return await preference_service.get_knowledge(novel_id)


@router.post("/{novel_id}/rag/learn")
async def learn_preferences(novel_id: int, db: AsyncSession = Depends(get_db)):
    await preference_service.learn_from_modifications(db, novel_id)
    return {"message": "偏好学习完成"}


@router.post("/{novel_id}/rag/import-document")
async def import_document(novel_id: int, file: UploadFile = File(...), category: str = Form("imported")):
    try:
        file_content = await file.read()
        filename = file.filename or "unknown"
        result = await import_document_to_knowledge(novel_id, file_content, filename, category)
        if "error" in result and result.get("imported_count", 0) == 0:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"AI提取失败: {e.message}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档导入失败: {str(e)}")


@router.post("/{novel_id}/rewrite")
async def rewrite_content(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    original_text = data.get("original_text", "")
    instruction = data.get("instruction", "")
    chapter_number = data.get("chapter_number")

    if not original_text:
        raise HTTPException(status_code=400, detail="请提供需要重写的原文")
    if not instruction:
        raise HTTPException(status_code=400, detail="请提供修改方向")

    state = {}
    if chapter_number:
        try:
            state = await _build_chapter_state(db, novel_id, int(chapter_number))
        except Exception as e:
            logger.warning(f"构建章节状态失败: {e}")

    async def stream_generator():
        try:
            async for item in rewrite_multi_stream(state, original_text, instruction):
                yield json.dumps(item, ensure_ascii=False) + "\n"
        except LLMError as e:
            yield json.dumps({"type": "error", "error": f"AI服务错误: {e.message}"}, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"重写失败: {str(e)}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
