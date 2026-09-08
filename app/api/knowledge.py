from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.story_knowledge import StoryKnowledge
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.services.novel_service import get_novel
from app.services.knowledge_extractor import (
    extract_chapter_knowledge,
    get_all_characters,
    get_all_relations,
    get_all_world_elements,
    build_graph_data,
)
from app.schemas.knowledge import StoryKnowledgeUpdate, StoryKnowledgeResponse
from app.llm.siliconflow import LLMError

router = APIRouter()


@router.get("/{novel_id}/knowledge")
async def get_all_knowledge(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    result = await db.execute(
        select(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id).order_by(StoryKnowledge.chapter_number)
    )
    knowledge_list = result.scalars().all()
    return [
        StoryKnowledgeResponse(
            id=k.id,
            novel_id=k.novel_id,
            chapter_number=k.chapter_number,
            characters=k.characters or [],
            character_relations=k.character_relations or [],
            world_elements=k.world_elements or [],
            chapter_summary=k.chapter_summary or "",
            plot_points=k.plot_points or [],
        ).model_dump()
        for k in knowledge_list
    ]


@router.get("/{novel_id}/knowledge/chapters")
async def get_knowledge_by_chapters(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    result = await db.execute(
        select(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id).order_by(StoryKnowledge.chapter_number)
    )
    knowledge_list = result.scalars().all()
    return {k.chapter_number: StoryKnowledgeResponse(
        id=k.id,
        novel_id=k.novel_id,
        chapter_number=k.chapter_number,
        characters=k.characters or [],
        character_relations=k.character_relations or [],
        world_elements=k.world_elements or [],
        chapter_summary=k.chapter_summary or "",
        plot_points=k.plot_points or [],
    ).model_dump() for k in knowledge_list}


@router.get("/{novel_id}/knowledge/characters")
async def get_characters(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return await get_all_characters(db, novel_id)


@router.get("/{novel_id}/knowledge/relations")
async def get_relations(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return await get_all_relations(db, novel_id)


@router.get("/{novel_id}/knowledge/world")
async def get_world_elements(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return await get_all_world_elements(db, novel_id)


@router.put("/{novel_id}/knowledge/chapters/{chapter_number}")
async def update_chapter_knowledge(
    novel_id: int,
    chapter_number: int,
    data: StoryKnowledgeUpdate,
    db: AsyncSession = Depends(get_db),
):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    result = await db.execute(
        select(StoryKnowledge).where(
            StoryKnowledge.novel_id == novel_id,
            StoryKnowledge.chapter_number == chapter_number,
        )
    )
    knowledge = result.scalar_one_or_none()

    if not knowledge:
        knowledge = StoryKnowledge(
            novel_id=novel_id,
            chapter_number=chapter_number,
        )
        db.add(knowledge)

    if data.characters is not None:
        knowledge.characters = data.characters
    if data.character_relations is not None:
        knowledge.character_relations = data.character_relations
    if data.world_elements is not None:
        knowledge.world_elements = data.world_elements
    if data.chapter_summary is not None:
        knowledge.chapter_summary = data.chapter_summary
    if data.plot_points is not None:
        knowledge.plot_points = data.plot_points

    await db.commit()
    await db.refresh(knowledge)

    return StoryKnowledgeResponse(
        id=knowledge.id,
        novel_id=knowledge.novel_id,
        chapter_number=knowledge.chapter_number,
        characters=knowledge.characters or [],
        character_relations=knowledge.character_relations or [],
        world_elements=knowledge.world_elements or [],
        chapter_summary=knowledge.chapter_summary or "",
        plot_points=knowledge.plot_points or [],
    ).model_dump()


@router.post("/{novel_id}/knowledge/extract/{chapter_number}")
async def manual_extract_knowledge(
    novel_id: int,
    chapter_number: int,
    db: AsyncSession = Depends(get_db),
):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    ch_result = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
    )
    chapter = ch_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    outline_item = None
    for item in (novel.outline or []):
        if item.get("chapter_number") == chapter_number:
            outline_item = item
            break

    try:
        knowledge = await extract_chapter_knowledge(db, novel_id, chapter_number, chapter.content, outline_item)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"AI服务暂时不可用: {e.message}")

    return StoryKnowledgeResponse(
        id=knowledge.id,
        novel_id=knowledge.novel_id,
        chapter_number=knowledge.chapter_number,
        characters=knowledge.characters or [],
        character_relations=knowledge.character_relations or [],
        world_elements=knowledge.world_elements or [],
        chapter_summary=knowledge.chapter_summary or "",
        plot_points=knowledge.plot_points or [],
    ).model_dump()


@router.get("/{novel_id}/knowledge/graph")
async def get_graph_data(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return await build_graph_data(db, novel_id)


@router.post("/{novel_id}/knowledge/character-image")
async def generate_character_image(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    stage_index = data.get("stage_index", 0)
    character_name = data.get("character_name", "")
    description = data.get("description", "")
    role = data.get("role", "")
    force = bool(data.get("force", False))
    if not character_name:
        raise HTTPException(status_code=400, detail="角色名称不能为空")

    if not description or not role:
        try:
            from app.services.knowledge_extractor import get_all_characters
            all_chars = await get_all_characters(db, novel_id)
            for c in (all_chars or []):
                if isinstance(c, dict) and c.get("name", "").strip() == character_name.strip():
                    if not description and c.get("description"):
                        description = c["description"]
                    if not role and c.get("role"):
                        role = c["role"]
                    break
        except Exception:
            pass

    if not description:
        fo_chars = ((novel.full_outline or {}).get("characters") or [])
        for c in fo_chars:
            if isinstance(c, dict) and c.get("name", "").strip() == character_name.strip():
                parts = []
                for k in ("profile", "motivation", "relationships", "arc"):
                    if c.get(k):
                        parts.append(f"{k}：{c[k]}")
                description = "；".join(parts) or description
                if not role:
                    role = c.get("role", "")
                break

    if not description:
        for c in (novel.characters or []):
            if isinstance(c, dict) and c.get("name", "").strip() == character_name.strip():
                parts = []
                for k in ("personality", "background"):
                    if c.get(k):
                        parts.append(f"{k}：{c[k]}")
                description = "；".join(parts) or description
                if not role:
                    role = c.get("role", "")
                break

    from app.services.image_service import _genre_style
    world_style = f"{_genre_style(novel.genre or '')}小说插画风格"

    try:
        from app.services.image_service import generate_and_save_character_image
        result = await generate_and_save_character_image(
            db, novel_id, stage_index, character_name, description, role, world_style, force=force
        )
        return result
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"图片生成失败: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成角色形象失败: {str(e)}")


@router.post("/{novel_id}/knowledge/world-image")
async def generate_world_image(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    force = bool(data.get("force", False))

    try:
        from app.services.image_service import generate_and_save_world_map
        result = await generate_and_save_world_map(db, novel_id, force=force)
        return result or {"image_url": None, "prompt": None}
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"图片生成失败: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.post("/{novel_id}/knowledge/region-image")
async def generate_region_image(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    region_name = (data.get("region_name") or "").strip()
    description = data.get("description", "")
    force = bool(data.get("force", False))
    if not region_name:
        raise HTTPException(status_code=422, detail="区域名称不能为空")

    try:
        from app.services.image_service import generate_and_save_region_image
        result = await generate_and_save_region_image(db, novel_id, region_name, description, force=force)
        return result or {"image_url": None, "prompt": None}
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"图片生成失败: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")
