import json
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseListItem,
    KnowledgeEntryCreate,
    KnowledgeEntryUpdate,
    KnowledgeEntryResponse,
)
from app.services import kb_service

router = APIRouter()


@router.post("", response_model=KnowledgeBaseResponse)
async def create_kb(data: KnowledgeBaseCreate, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.create_kb(
        db,
        name=data.name,
        genre=data.genre or "",
        source_work=data.source_work or "",
        is_fanwork=data.is_fanwork if data.is_fanwork is not None else False,
        description=data.description or "",
    )
    return kb


@router.get("", response_model=list[KnowledgeBaseListItem])
async def list_kbs(db: AsyncSession = Depends(get_db)):
    items = await kb_service.list_kbs(db)
    return [KnowledgeBaseListItem(**item) for item in items]


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_kb(kb_id: int, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_kb(kb_id: int, data: KnowledgeBaseUpdate, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.update_kb(db, kb_id, **data.model_dump(exclude_unset=True))
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.delete("/{kb_id}")
async def delete_kb(kb_id: int, db: AsyncSession = Depends(get_db)):
    success = await kb_service.delete_kb(db, kb_id)
    if not success:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"message": "删除成功"}


@router.post("/{kb_id}/entries", response_model=KnowledgeEntryResponse)
async def add_entry(kb_id: int, data: KnowledgeEntryCreate, db: AsyncSession = Depends(get_db)):
    entry = await kb_service.add_entry(
        db,
        kb_id=kb_id,
        category=data.category,
        title=data.title,
        content=data.content,
        attributes=data.attributes,
        source=data.source or "manual",
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return entry


@router.get("/{kb_id}/entries", response_model=list[KnowledgeEntryResponse])
async def list_entries(
    kb_id: int,
    category: str | None = Query(default=None),
    volume: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await kb_service.list_entries(db, kb_id, category, volume)


@router.put("/{kb_id}/entries/{entry_id}", response_model=KnowledgeEntryResponse)
async def update_entry(
    kb_id: int,
    entry_id: int,
    data: KnowledgeEntryUpdate,
    db: AsyncSession = Depends(get_db),
):
    entry = await kb_service.update_entry(db, entry_id, **data.model_dump(exclude_unset=True))
    if not entry:
        raise HTTPException(status_code=404, detail="条目不存在")
    return entry


@router.delete("/{kb_id}/entries/{entry_id}")
async def delete_entry(kb_id: int, entry_id: int, db: AsyncSession = Depends(get_db)):
    success = await kb_service.delete_entry(db, entry_id)
    if not success:
        raise HTTPException(status_code=404, detail="条目不存在")
    return {"message": "删除成功"}


@router.get("/{kb_id}/overview")
async def get_kb_overview(
    kb_id: int,
    volume: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return await kb_service.get_kb_overview(db, kb_id, volume)


@router.get("/{kb_id}/import-status")
async def get_import_status(kb_id: int, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {
        "kb_id": kb_id,
        "import_status": kb.import_status or "idle",
        "import_progress": kb.import_progress or {},
        "volumes": kb.volumes or [],
        "volume_relations": kb.volume_relations or [],
    }


@router.get("/{kb_id}/vector-status")
async def get_kb_vector_status(kb_id: int, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    from app.rag.chroma_client import chroma_client, get_kb_collection_name
    collection_name = get_kb_collection_name(kb_id)
    try:
        collection = chroma_client.get_collection(collection_name)
        count = collection.count()
        peek = collection.peek(limit=5)
        return {
            "kb_id": kb_id,
            "collection_name": collection_name,
            "vector_count": count,
            "sample_ids": peek.get("ids", []),
            "sample_documents": [d[:200] for d in peek.get("documents", [])],
            "sample_metadatas": peek.get("metadatas", []),
        }
    except Exception as e:
        return {"kb_id": kb_id, "collection_name": collection_name, "vector_count": 0, "error": str(e)}


@router.post("/{kb_id}/import-file")
async def import_file(kb_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    file_content = await file.read()
    print(f"[API] 开始导入文件: kb_id={kb_id}, filename={file.filename}, size={len(file_content)}", flush=True)

    async def stream_generator():
        async for event in kb_service.import_file_to_kb_stream(
            db, kb_id, file_content, file.filename or "upload.txt"
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.post("/{kb_id}/reset-volume/{volume_number}")
async def reset_volume(kb_id: int, volume_number: int, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await kb_service.reset_volume_for_reextract(db, kb_id, volume_number)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{kb_id}/reextract-chapter/{volume_number}/{chapter_number}")
async def reextract_chapter(
    kb_id: int,
    volume_number: int,
    chapter_number: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    file_content = await file.read()
    try:
        return await kb_service.reextract_single_chapter(
            db, kb_id, volume_number, chapter_number, file_content, file.filename or "upload.txt"
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{kb_id}/rederive-timeline/{volume_number}")
async def rederive_timeline(kb_id: int, volume_number: int, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await kb_service.rederive_volume_timeline(db, kb_id, volume_number)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{kb_id}/rebuild-volume-summaries")
async def rebuild_volume_summaries(kb_id: int, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        await kb_service._build_volume_relations_and_summaries(db, kb_id)
        kb = await kb_service.get_kb(db, kb_id)
        summary_count = sum(1 for v in (kb.volumes or []) if isinstance(v, dict) and v.get("summary"))
        return {"ok": True, "kb_id": kb_id, "volumes_with_summaries": summary_count, "total_volumes": len(kb.volumes or [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重建失败: {e}")


@router.delete("/{kb_id}/volumes-from/{start_volume}")
async def delete_volumes_from(kb_id: int, start_volume: int, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        return await kb_service.delete_volumes_from(db, kb_id, start_volume)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{kb_id}/append-continuation")
async def append_continuation(
    kb_id: int,
    start_volume: int = Form(...),
    body_count: int = Form(None),
    skip_volumes: int = Form(0),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    file_content = await file.read()
    print(
        f"[API] 续接导入: kb_id={kb_id}, filename={file.filename}, size={len(file_content)}, "
        f"start_volume={start_volume}, body_count={body_count}, skip_volumes={skip_volumes}",
        flush=True,
    )

    async def stream_generator():
        async for event in kb_service.append_file_continuation_stream(
            db,
            kb_id,
            file_content,
            file.filename or "upload.txt",
            start_volume=start_volume,
            body_count=body_count,
            skip_volumes=skip_volumes,
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.post("/{kb_id}/bulk-entries")
async def bulk_add_entries(kb_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    entries = body.get("entries", [])
    if not isinstance(entries, list):
        raise HTTPException(status_code=422, detail="entries 必须为数组")
    return await kb_service.bulk_add_entries(db, kb_id, entries)
