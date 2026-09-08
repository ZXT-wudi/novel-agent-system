import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.services import ordinary_kb_service
from app.models.ordinary_knowledge_base import OrdinaryKnowledgeEntry

router = APIRouter()


class OrdinaryKBCreate(BaseModel):
    name: str
    genre: str = "其他"
    source_work: Optional[str] = ""
    description: Optional[str] = ""


class OrdinaryKBUpdate(BaseModel):
    name: Optional[str] = None
    genre: Optional[str] = None
    source_work: Optional[str] = None
    description: Optional[str] = None


class OrdinaryEntryCreate(BaseModel):
    dimension: str
    content: str = ""
    attributes: Optional[dict] = None


class OrdinaryEntryUpdate(BaseModel):
    content: Optional[str] = None
    attributes: Optional[dict] = None


@router.post("")
async def create_ordinary_kb(data: OrdinaryKBCreate, db: AsyncSession = Depends(get_db)):
    kb = await ordinary_kb_service.create_ordinary_kb(
        db, name=data.name, genre=data.genre, source_work=data.source_work or "", description=data.description or ""
    )
    return {"id": kb.id, "name": kb.name, "genre": kb.genre}


@router.get("")
async def list_ordinary_kbs(genre: str = None, db: AsyncSession = Depends(get_db)):
    return await ordinary_kb_service.list_ordinary_kbs(db, genre)


@router.get("/{base_id}")
async def get_ordinary_kb(base_id: int, db: AsyncSession = Depends(get_db)):
    detail = await ordinary_kb_service.get_ordinary_kb_detail(db, base_id)
    if not detail:
        raise HTTPException(status_code=404, detail="普通知识库不存在")
    return detail


@router.put("/{base_id}")
async def update_ordinary_kb(base_id: int, data: OrdinaryKBUpdate, db: AsyncSession = Depends(get_db)):
    kb = await ordinary_kb_service.update_ordinary_kb(
        db, base_id, name=data.name, genre=data.genre, source_work=data.source_work, description=data.description
    )
    if not kb:
        raise HTTPException(status_code=404, detail="普通知识库不存在")
    return {"id": kb.id, "name": kb.name, "genre": kb.genre}


@router.delete("/{base_id}")
async def delete_ordinary_kb(base_id: int, db: AsyncSession = Depends(get_db)):
    success = await ordinary_kb_service.delete_ordinary_kb(db, base_id)
    if not success:
        raise HTTPException(status_code=404, detail="普通知识库不存在")
    return {"message": "删除成功"}


@router.get("/{base_id}/entries")
async def list_entries(base_id: int, dimension: str = None, db: AsyncSession = Depends(get_db)):
    stmt = select(OrdinaryKnowledgeEntry).where(OrdinaryKnowledgeEntry.base_id == base_id)
    if dimension:
        stmt = stmt.where(OrdinaryKnowledgeEntry.dimension == dimension)
    stmt = stmt.order_by(OrdinaryKnowledgeEntry.id)
    result = await db.execute(stmt)
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "dimension": e.dimension,
            "dimension_name": (e.attributes or {}).get("name", e.dimension),
            "content": e.content,
            "attributes": e.attributes or {},
        }
        for e in entries
    ]


@router.post("/{base_id}/entries")
async def create_entry(base_id: int, data: OrdinaryEntryCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(OrdinaryKnowledgeEntry).where(
            OrdinaryKnowledgeEntry.base_id == base_id,
            OrdinaryKnowledgeEntry.dimension == data.dimension,
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail=f"维度 {data.dimension} 已存在")
    entry = OrdinaryKnowledgeEntry(
        base_id=base_id,
        dimension=data.dimension,
        content=data.content,
        attributes=data.attributes or {"name": data.dimension},
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "dimension": entry.dimension}


@router.put("/{base_id}/entries/{eid}")
async def update_entry(base_id: int, eid: int, data: OrdinaryEntryUpdate, db: AsyncSession = Depends(get_db)):
    entry = await db.get(OrdinaryKnowledgeEntry, eid)
    if not entry or entry.base_id != base_id:
        raise HTTPException(status_code=404, detail="条目不存在")
    if data.content is not None:
        entry.content = data.content
    if data.attributes is not None:
        entry.attributes = data.attributes
    await db.commit()
    return {"id": entry.id}


@router.delete("/{base_id}/entries/{eid}")
async def delete_entry(base_id: int, eid: int, db: AsyncSession = Depends(get_db)):
    entry = await db.get(OrdinaryKnowledgeEntry, eid)
    if not entry or entry.base_id != base_id:
        raise HTTPException(status_code=404, detail="条目不存在")
    await db.delete(entry)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{base_id}/import-file")
async def import_file(base_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    kb = await ordinary_kb_service.get_ordinary_kb(db, base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="普通知识库不存在")
    file_content = await file.read()
    print(f"[普通KB] 开始导入文件: base_id={base_id}, filename={file.filename}, size={len(file_content)}", flush=True)

    async def stream_generator():
        async for event in ordinary_kb_service.extract_ordinary_kb_stream(
            db, base_id, file_content, file.filename or "upload.txt"
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.get("/{base_id}/import-status")
async def get_import_status(base_id: int, db: AsyncSession = Depends(get_db)):
    kb = await ordinary_kb_service.get_ordinary_kb(db, base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="普通知识库不存在")
    progress = kb.import_progress or {}
    return {
        "import_status": kb.import_status,
        "total_chunks": progress.get("total_chunks", 0),
        "done_chunks": len(progress.get("done_chunks", [])),
        "failed_chunks": progress.get("failed", []),
        "level": progress.get("level", ""),
        "chunk_analyses_count": len(progress.get("chunk_analyses", [])),
    }


@router.get("/{base_id}/overview")
async def get_overview(base_id: int, db: AsyncSession = Depends(get_db)):
    detail = await ordinary_kb_service.get_ordinary_kb_detail(db, base_id)
    if not detail:
        raise HTTPException(status_code=404, detail="普通知识库不存在")
    return {
        "id": detail["id"],
        "name": detail["name"],
        "genre": detail["genre"],
        "import_status": detail["import_status"],
        "entry_count": len(detail["entries"]),
        "dimensions": [
            {"key": e["dimension"], "name": e["dimension_name"], "content_length": len(e.get("content", ""))}
            for e in detail["entries"]
        ],
    }
