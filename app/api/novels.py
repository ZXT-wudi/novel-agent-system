from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.novel import NovelCreate, NovelResponse, NovelListResponse, NovelQARequest, NovelUpdate
from app.services import novel_service
from app.services.novel_service import derive_length_type

router = APIRouter()


@router.post("", response_model=NovelResponse)
async def create_novel(data: NovelCreate, db: AsyncSession = Depends(get_db)):
    novel = await novel_service.create_novel(db, data)
    return NovelResponse(
        id=novel.id,
        title=novel.title,
        genre=novel.genre,
        description=novel.description,
        length_type=derive_length_type(novel.target_word_count, novel.length_type),
        target_word_count=novel.target_word_count,
        full_outline=novel.full_outline or {},
        outline=novel.outline or [],
        world_settings=novel.world_settings or {},
        characters=novel.characters or [],
        status=novel.status,
        created_at=novel.created_at,
        updated_at=novel.updated_at,
        knowledge_base_id=novel.knowledge_base_id,
        ordinary_knowledge_base_id=novel.ordinary_knowledge_base_id,
        chapter_count=0,
    )


@router.post("/from-qa")
async def create_novel_from_qa(data: NovelQARequest, db: AsyncSession = Depends(get_db)):
    print(f"[NOVEL-CREATE] POST /from-qa received: target_word_count={data.target_word_count}, length_type={data.length_type}, title={data.title}")
    try:
        expanded = await novel_service.expand_novel_from_qa(
            db=db,
            title=data.title,
            content=data.content,
            writing_style=data.writing_style,
            target_word_count=data.target_word_count,
            length_type=data.length_type,
            genre=data.genre,
            knowledge_base_id=data.knowledge_base_id or 0,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"小说设定扩写失败: {str(e)}")

    print(f"[NOVEL-CREATE] expanded target_word_count={expanded.get('target_word_count')}, length_type={expanded.get('length_type')}")

    novel_create = NovelCreate(
        title=expanded.get("title", data.title),
        genre=data.genre or expanded.get("genre"),
        description=expanded.get("description"),
        length_type=expanded.get("length_type", data.length_type),
        world_settings=expanded.get("world_settings"),
        characters=expanded.get("characters"),
        writing_style=expanded.get("writing_style"),
        target_word_count=expanded.get("target_word_count"),
        narrative_pov=expanded.get("narrative_pov"),
        knowledge_base_id=data.knowledge_base_id,
        ordinary_knowledge_base_id=data.ordinary_knowledge_base_id,
    )

    try:
        novel = await novel_service.create_novel(db, novel_create)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"小说创建失败: {str(e)}")

    print(f"[NOVEL-CREATE] DB novel created: id={novel.id}, target_word_count={novel.target_word_count}, length_type={novel.length_type}")

    return {"novel_id": novel.id, "settings": expanded}


@router.get("", response_model=list[NovelListResponse])
async def list_novels(db: AsyncSession = Depends(get_db)):
    return await novel_service.get_novels(db)


@router.get("/{novel_id}", response_model=NovelResponse)
async def get_novel(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await novel_service.get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    from sqlalchemy import select, func
    from app.models.chapter import Chapter
    ch_count = await db.execute(select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id))
    chapter_count = ch_count.scalar() or 0

    return NovelResponse(
        id=novel.id,
        title=novel.title,
        genre=novel.genre,
        description=novel.description,
        length_type=derive_length_type(novel.target_word_count, novel.length_type),
        target_word_count=novel.target_word_count,
        full_outline=novel.full_outline or {},
        outline=novel.outline or [],
        world_settings=novel.world_settings or {},
        characters=novel.characters or [],
        status=novel.status,
        created_at=novel.created_at,
        updated_at=novel.updated_at,
        knowledge_base_id=novel.knowledge_base_id,
        ordinary_knowledge_base_id=novel.ordinary_knowledge_base_id,
        chapter_count=chapter_count,
    )


@router.put("/{novel_id}", response_model=NovelResponse)
async def update_novel(novel_id: int, data: NovelUpdate, db: AsyncSession = Depends(get_db)):
    novel = await novel_service.get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    print(f"[NOVEL-UPDATE] PUT /{novel_id} received: target_word_count={data.target_word_count}, length_type={data.length_type}")
    for field in ["title", "genre", "description", "length_type", "writing_style", "target_word_count", "narrative_pov", "knowledge_base_id", "ordinary_knowledge_base_id", "world_settings", "characters"]:
        val = getattr(data, field, None)
        if val is None:
            continue
        if field == "title" and isinstance(val, str) and not val.strip():
            continue
        if field == "target_word_count" and val == 0:
            continue
        if field in ("world_settings", "characters") and not val:
            continue
        if field in ("knowledge_base_id", "ordinary_knowledge_base_id") and val == 0:
            val = None
        setattr(novel, field, val)
    print(f"[NOVEL-UPDATE] DB novel after update: target_word_count={novel.target_word_count}, length_type={novel.length_type}")
    await db.commit()
    await db.refresh(novel)

    from sqlalchemy import select, func
    from app.models.chapter import Chapter
    ch_count = await db.execute(select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id))
    chapter_count = ch_count.scalar() or 0

    return NovelResponse(
        id=novel.id,
        title=novel.title,
        genre=novel.genre,
        description=novel.description,
        length_type=derive_length_type(novel.target_word_count, novel.length_type),
        full_outline=novel.full_outline or {},
        outline=novel.outline or [],
        world_settings=novel.world_settings or {},
        characters=novel.characters or [],
        status=novel.status,
        writing_style=novel.writing_style,
        target_word_count=novel.target_word_count,
        narrative_pov=novel.narrative_pov,
        knowledge_base_id=novel.knowledge_base_id,
        ordinary_knowledge_base_id=novel.ordinary_knowledge_base_id,
        created_at=novel.created_at,
        updated_at=novel.updated_at,
        chapter_count=chapter_count,
    )


@router.delete("/{novel_id}")
async def delete_novel(novel_id: int, db: AsyncSession = Depends(get_db)):
    try:
        success = await novel_service.delete_novel(db, novel_id)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    if not success:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"message": "删除成功"}
