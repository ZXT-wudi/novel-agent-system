from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.novel import Novel
from app.models.story_knowledge import StoryKnowledge
from app.agents.outline_agent import (
    generate_outline,
    generate_full_outline,
    generate_chapter_outline,
    revise_outline,
    revise_full_outline,
    _parse_outline_response,
    _parse_full_outline_response,
)
from app.agents.state import NovelState
from app.services.novel_service import get_novel
from app.services.kb_service import build_kb_context_for_agent
from app.services.volume_splitter import volumes_for_chapter_range, resolve_source_volumes, validate_and_backfill_source_volumes
import json


async def generate_novel_outline(db: AsyncSession, novel_id: int, description: str = "", genre: str = "", target_chapters: int = 10) -> list[dict]:
    novel = await get_novel(db, novel_id)
    if not novel:
        return []

    state: NovelState = {
        "novel_id": novel_id,
        "knowledge_base_id": novel.knowledge_base_id,
        "kb_context": await build_kb_context_for_agent(db, novel.knowledge_base_id, description or novel.description or "", comprehensive=True),
        "outline_item": {
            "title": novel.title,
            "genre": genre or novel.genre or "",
            "description": description or novel.description or "",
            "target_chapters": target_chapters,
            "world_settings": novel.world_settings or {},
            "characters": novel.characters or [],
        },
    }

    state = await generate_outline(state)
    outline = state.get("outline", [])

    novel.outline = outline
    await db.commit()
    await db.refresh(novel)

    return outline


async def generate_full_novel_outline(db: AsyncSession, novel_id: int, description: str = "", genre: str = "", length_type: str = "short") -> dict:
    novel = await get_novel(db, novel_id)
    if not novel:
        return {}

    state: NovelState = {
        "novel_id": novel_id,
        "knowledge_base_id": novel.knowledge_base_id,
        "kb_context": await build_kb_context_for_agent(db, novel.knowledge_base_id, description or novel.description or "", comprehensive=True, toc_mode=True),
        "outline_item": {
            "title": novel.title,
            "genre": genre or novel.genre or "",
            "description": description or novel.description or "",
            "length_type": length_type or novel.length_type or "short",
            "writing_style": novel.writing_style,
            "target_word_count": novel.target_word_count,
            "narrative_pov": novel.narrative_pov,
        },
    }

    state = await generate_full_outline(state)
    full_outline = state.get("full_outline", {})

    novel.full_outline = full_outline
    novel.length_type = length_type or novel.length_type or "short"
    await db.commit()
    await db.refresh(novel)

    return full_outline


async def generate_chapter_outline_batch(db: AsyncSession, novel_id: int, start_chapter: int = 1, batch_size: int = 10) -> list[dict]:
    novel = await get_novel(db, novel_id)
    if not novel:
        return []

    knowledge_summary = await _build_knowledge_summary(db, novel_id)

    chapter_vol_nums = volumes_for_chapter_range(novel.full_outline or {}, start_chapter, start_chapter + batch_size - 1)

    source_volumes = resolve_source_volumes(novel.full_outline or {}, chapter_vol_nums) if novel.full_outline else None
    if source_volumes is not None:
        print(f"[CH-OUTLINE-SVC] 有源卷映射: fanfic_volumes={chapter_vol_nums} -> source_kb_volumes={source_volumes}", flush=True)
        kb_context = await build_kb_context_for_agent(
            db,
            novel.knowledge_base_id,
            f"第{start_chapter}章到第{start_chapter + batch_size - 1}章",
            comprehensive=True,
            volume_numbers=source_volumes,
            chapter_numbers=None,
            toc_mode=False,
        )
        print(f"[CH-OUTLINE-SVC]   有源卷映射: kb_context长度={len(kb_context)}", flush=True)
    else:
        print(f"[CH-OUTLINE-SVC] 无源卷映射: volume_numbers={chapter_vol_nums}", flush=True)
        kb_context = await build_kb_context_for_agent(
            db,
            novel.knowledge_base_id,
            f"第{start_chapter}章到第{start_chapter + batch_size - 1}章",
            volume_numbers=chapter_vol_nums,
            chapter_numbers=list(range(start_chapter, start_chapter + batch_size)),
        )
        print(f"[CH-OUTLINE-SVC]   无源卷映射: kb_context长度={len(kb_context)}", flush=True)

    state: NovelState = {
        "novel_id": novel_id,
        "knowledge_base_id": novel.knowledge_base_id,
        "kb_context": kb_context,
        "full_outline": novel.full_outline or {},
        "outline": novel.outline or [],
        "outline_item": {
            "start_chapter": start_chapter,
            "batch_size": batch_size,
            "writing_style": novel.writing_style,
            "target_word_count": novel.target_word_count,
            "narrative_pov": novel.narrative_pov,
        },
        "story_knowledge_summary": knowledge_summary,
    }

    state = await generate_chapter_outline(state)
    outline = state.get("outline", [])

    novel.outline = outline
    await db.commit()
    await db.refresh(novel)

    return outline


async def _build_knowledge_summary(db: AsyncSession, novel_id: int) -> str:
    result = await db.execute(
        select(StoryKnowledge)
        .where(StoryKnowledge.novel_id == novel_id)
        .order_by(StoryKnowledge.chapter_number.desc())
        .limit(5)
    )
    knowledge_list = result.scalars().all()

    if not knowledge_list:
        return ""

    parts = []
    for k in reversed(knowledge_list):
        block_lines = [f"【第{k.chapter_number}章】"]
        if k.chapter_summary:
            block_lines.append(f"章节摘要：{k.chapter_summary}")
        if k.plot_points:
            block_lines.append("情节要点：" + "；".join(
                p if isinstance(p, str) else str(p) for p in k.plot_points if p
            ))
        if k.characters:
            char_lines = []
            for c in k.characters:
                if isinstance(c, dict) and c.get("name"):
                    seg = f"{c.get('name', '')}（{c.get('role', '')}）"
                    if c.get("status"):
                        seg += f"状态[{c['status']}]"
                    if c.get("description"):
                        seg += f"：{c['description']}"
                    char_lines.append(seg)
            if char_lines:
                block_lines.append("角色：" + "；".join(char_lines))
        if k.character_relations:
            rel_lines = []
            for r in k.character_relations:
                if isinstance(r, dict) and r.get("from"):
                    rel_lines.append(
                        f"{r.get('from', '')}-{r.get('type', '')}->{r.get('to', '')}"
                        + (f"：{r['description']}" if r.get("description") else "")
                    )
            if rel_lines:
                block_lines.append("角色关系：" + "；".join(rel_lines))
        if k.world_elements:
            elem_lines = []
            for e in k.world_elements:
                if isinstance(e, dict) and e.get("name"):
                    seg = f"[{e.get('category', '')}]{e.get('name', '')}"
                    if e.get("description"):
                        seg += f"：{e['description']}"
                    elem_lines.append(seg)
            if elem_lines:
                block_lines.append("世界观元素：" + "；".join(elem_lines))
        parts.append("\n".join(block_lines))

    return "\n\n".join(parts)


async def update_outline(db: AsyncSession, novel_id: int, outline: list[dict]) -> list[dict]:
    novel = await get_novel(db, novel_id)
    if not novel:
        return []

    novel.outline = outline
    await db.commit()
    await db.refresh(novel)
    return outline


async def update_full_outline(db: AsyncSession, novel_id: int, full_outline: dict) -> dict:
    novel = await get_novel(db, novel_id)
    if not novel:
        return {}

    full_outline = validate_and_backfill_source_volumes(full_outline)
    novel.full_outline = full_outline
    await db.commit()
    await db.refresh(novel)
    return full_outline


async def confirm_outline(db: AsyncSession, novel_id: int) -> Novel | None:
    novel = await get_novel(db, novel_id)
    if not novel:
        return None

    novel.status = "writing"
    await db.commit()
    await db.refresh(novel)
    return novel


async def ai_revise_outline(db: AsyncSession, novel_id: int, user_feedback: str) -> list[dict]:
    novel = await get_novel(db, novel_id)
    if not novel:
        return []

    state: NovelState = {
        "novel_id": novel_id,
        "outline": novel.outline or [],
        "outline_item": {"user_feedback": user_feedback},
    }

    state = await revise_outline(state)
    outline = state.get("outline", [])

    novel.outline = outline
    await db.commit()
    await db.refresh(novel)

    return outline


async def ai_revise_full_outline(db: AsyncSession, novel_id: int, user_feedback: str) -> dict:
    novel = await get_novel(db, novel_id)
    if not novel:
        return {}

    state: NovelState = {
        "novel_id": novel_id,
        "full_outline": novel.full_outline or {},
        "outline_item": {"user_feedback": user_feedback},
    }

    state = await revise_full_outline(state)
    full_outline = state.get("full_outline", {})
    full_outline = validate_and_backfill_source_volumes(full_outline)

    novel.full_outline = full_outline
    await db.commit()
    await db.refresh(novel)

    return full_outline
