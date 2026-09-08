import json
import re
import math
import asyncio
import logging
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.models.knowledge_base import KnowledgeBase, KnowledgeEntry
from app.rag.retriever import add_to_kb, delete_from_kb, update_in_kb, delete_kb_collection, query_kb
from app.rag.embedder import embed_texts
from app.rag.chroma_client import chroma_client, get_kb_collection_name
from app.services.document_parser import extract_text_from_file
from app.services.volume_splitter import detect_volumes, detect_chapters_in_volume
from app.llm.siliconflow import llm_client

logger = logging.getLogger(__name__)

MAX_CONCURRENT_LLM = 4
CROSS_VOLUME_MERGE_THRESHOLD = 0.15
WORLDVIEW_DEDUP_THRESHOLD = 0.85
KEY_CHAR_MIN_CHAPTERS = 2
KEY_CHAR_MIN_EVENTS = 2
CHAPTER_SUMMARY_MAX_TOKENS = 3072
VOL_SUMMARY_MAX_TOKENS = 2048
VOL_SUMMARY_SEG_LIMIT = 10000


async def create_kb(
    db: AsyncSession,
    name: str,
    genre: str = "",
    source_work: str = "",
    is_fanwork: bool = False,
    description: str = "",
) -> KnowledgeBase:
    kb = KnowledgeBase(
        name=name,
        genre=genre,
        source_work=source_work,
        is_fanwork=is_fanwork,
        description=description,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def get_kb(db: AsyncSession, kb_id: int) -> KnowledgeBase | None:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    return result.scalar_one_or_none()


async def list_kbs(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    kbs = result.scalars().all()

    items = []
    for kb in kbs:
        count_result = await db.execute(
            select(func.count(KnowledgeEntry.id)).where(KnowledgeEntry.kb_id == kb.id)
        )
        entry_count = count_result.scalar() or 0
        items.append({
            "id": kb.id,
            "name": kb.name,
            "genre": kb.genre,
            "source_work": kb.source_work,
            "is_fanwork": kb.is_fanwork if kb.is_fanwork is not None else False,
            "description": kb.description,
            "entry_count": entry_count,
            "import_status": kb.import_status or "idle",
            "import_progress": kb.import_progress or {},
            "volumes": kb.volumes or [],
            "created_at": kb.created_at,
            "updated_at": kb.updated_at,
        })
    return items


async def update_kb(db: AsyncSession, kb_id: int, **fields) -> KnowledgeBase | None:
    kb = await get_kb(db, kb_id)
    if not kb:
        return None
    valid_fields = {"name", "genre", "source_work", "is_fanwork", "description"}
    for key, value in fields.items():
        if key in valid_fields and value is not None:
            setattr(kb, key, value)
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_kb(db: AsyncSession, kb_id: int) -> bool:
    kb = await get_kb(db, kb_id)
    if not kb:
        return False
    await db.delete(kb)
    await db.commit()
    await delete_kb_collection(kb_id)
    return True


async def add_entry(
    db: AsyncSession,
    kb_id: int,
    category: str,
    title: str,
    content: str,
    attributes: dict | None = None,
    source: str = "manual",
    volume: int | None = None,
    volume_title: str | None = None,
) -> KnowledgeEntry | None:
    kb = await get_kb(db, kb_id)
    if not kb:
        return None
    entry = KnowledgeEntry(
        kb_id=kb_id,
        category=category,
        title=title,
        content=content,
        attributes=attributes or {},
        source=source,
        volume=volume,
        volume_title=volume_title,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    document = f"[{category}] {title}: {content}"
    entry_vector_id = f"kb_{kb_id}_entry_{entry.id}"
    metadata = {"category": category, "title": title, "source": source}
    if volume is not None:
        metadata["volume_number"] = volume
    await add_to_kb(kb_id, [document], [entry_vector_id], [metadata])

    return entry


async def list_entries(db: AsyncSession, kb_id: int, category: str | None = None, volume: int | None = None) -> list[KnowledgeEntry]:
    stmt = select(KnowledgeEntry).where(KnowledgeEntry.kb_id == kb_id)
    if category:
        stmt = stmt.where(KnowledgeEntry.category == category)
    if volume is not None:
        stmt = stmt.where(or_(KnowledgeEntry.volume == volume, KnowledgeEntry.volume.is_(None)))
    stmt = stmt.order_by(KnowledgeEntry.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_entry(db: AsyncSession, entry_id: int, **fields) -> KnowledgeEntry | None:
    result = await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return None
    valid_fields = {"category", "title", "content", "attributes", "source", "volume", "volume_title", "chapter_number", "chapter_title"}
    for key, value in fields.items():
        if key in valid_fields and value is not None:
            setattr(entry, key, value)
    await db.commit()
    await db.refresh(entry)

    document = f"[{entry.category}] {entry.title}: {entry.content}"
    entry_vector_id = f"kb_{entry.kb_id}_entry_{entry.id}"
    metadata = {"category": entry.category, "title": entry.title, "source": entry.source}
    if entry.volume is not None:
        metadata["volume_number"] = entry.volume
    if entry.chapter_number is not None:
        metadata["chapter_number"] = entry.chapter_number
    await update_in_kb(entry.kb_id, [entry_vector_id], [document], [metadata])

    return entry


async def delete_entry(db: AsyncSession, entry_id: int) -> bool:
    result = await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return False
    kb_id = entry.kb_id
    entry_vector_id = f"kb_{kb_id}_entry_{entry.id}"
    await db.delete(entry)
    await db.commit()
    await delete_from_kb(kb_id, [entry_vector_id])
    return True


async def get_kb_overview(db: AsyncSession, kb_id: int, volume: int | None = None) -> dict:
    stmt = select(KnowledgeEntry).where(KnowledgeEntry.kb_id == kb_id)
    if volume is not None:
        stmt = stmt.where(or_(KnowledgeEntry.volume == volume, KnowledgeEntry.volume.is_(None)))
    stmt = stmt.order_by(KnowledgeEntry.category, KnowledgeEntry.created_at.desc())
    result = await db.execute(stmt)
    entries = result.scalars().all()

    categories: dict[str, dict] = {}
    for entry in entries:
        cat = entry.category
        if cat not in categories:
            categories[cat] = {"count": 0, "samples": []}
        categories[cat]["count"] += 1
        if len(categories[cat]["samples"]) < 5:
            categories[cat]["samples"].append({
                "id": entry.id,
                "title": entry.title,
                "content": (entry.content or "")[:200],
                "source": entry.source,
                "volume": entry.volume,
            })

    kb = await get_kb(db, kb_id)
    volumes = []
    for v in (kb.volumes or []):
        if isinstance(v, dict):
            volumes.append({
                "volume_number": v.get("volume_number"),
                "title": v.get("title", ""),
                "status": v.get("status", ""),
                "summary": v.get("summary", ""),
                "source": v.get("source", ""),
            })

    return {
        "kb_id": kb_id,
        "total_entries": len(entries),
        "total": len(entries),
        "categories": categories,
        "volumes": volumes,
        "volume_relations": kb.volume_relations if kb else [],
        "import_status": kb.import_status if kb else "idle",
    }


KB_CATEGORY_VOLUME_EVENT = "volume_event"
KB_CATEGORY_CHAPTER_SUMMARY = "chapter_summary"

KB_CATEGORY_LABELS = {
    "worldview": "世界观设定",
    "character": "角色设定",
    "event": "重要事件",
    "timeline": "时间线",
    "faction": "势力组织",
    "setting": "其他设定",
    KB_CATEGORY_VOLUME_EVENT: "卷事件总结",
    KB_CATEGORY_CHAPTER_SUMMARY: "章节摘要",
}

KB_INJECT_PER_CATEGORY = {
    "worldview": 6,
    "character": 15,
    "event": 10,
    "timeline": 6,
    "faction": 8,
    "setting": 8,
}

KB_INJECT_PER_CATEGORY_FULL = {
    "worldview": 200,
    "character": 500,
    "event": 300,
    "timeline": 150,
    "faction": 200,
    "setting": 200,
}

_EVENT_SUBTYPE_LABELS = {"romance": "感情线", "growth": "成长线"}


def _event_suffix(e: KnowledgeEntry) -> str:
    attrs = e.attributes if isinstance(e.attributes, dict) else {}
    parts: list[str] = []
    subtype = attrs.get("subtype")
    if subtype:
        parts.append(_EVENT_SUBTYPE_LABELS.get(str(subtype), str(subtype)))
    chars = attrs.get("characters")
    if isinstance(chars, list) and chars:
        parts.append("涉及：" + "、".join(str(c) for c in chars))
    return f"（{'；'.join(parts)}）" if parts else ""


def _chapter_segment(ch: dict) -> str:
    seg = f"[第{ch.get('chapter_number', 1)}章《{ch.get('chapter_title', '')}》] {(ch.get('summary') or '').strip()}"
    ke = ch.get("key_events")
    if isinstance(ke, list) and ke:
        seg += " 关键事件：" + "；".join(str(x) for x in ke)
    return seg


async def build_kb_context_for_agent(
    db: AsyncSession,
    kb_id: int,
    query_text: str = "",
    comprehensive: bool = False,
    volume_numbers: list[int] | None = None,
    chapter_numbers: list[int] | None = None,
    toc_mode: bool = False,
) -> str:
    limits = KB_INJECT_PER_CATEGORY_FULL if comprehensive else KB_INJECT_PER_CATEGORY
    other_limit = 200 if comprehensive else 3
    if not kb_id:
        return ""

    vol_filter_active = bool(volume_numbers)
    ch_filter_active = bool(chapter_numbers)

    stmt = select(KnowledgeEntry).where(KnowledgeEntry.kb_id == kb_id)
    if vol_filter_active:
        stmt = stmt.where(
            or_(
                KnowledgeEntry.volume.in_(volume_numbers),
                KnowledgeEntry.volume.is_(None),
            )
        )
    if ch_filter_active and not comprehensive:
        stmt = stmt.where(
            or_(
                KnowledgeEntry.chapter_number.in_(chapter_numbers),
                KnowledgeEntry.chapter_number.is_(None),
            )
        )
    stmt = stmt.order_by(KnowledgeEntry.category, KnowledgeEntry.created_at.desc())
    result = await db.execute(stmt)
    all_entries = result.scalars().all()

    vol_nums_in_entries = sorted({e.volume for e in all_entries if e.volume is not None})
    print(f"[KB] build_kb_context_for_agent: kb_id={kb_id}, comprehensive={comprehensive}, toc_mode={toc_mode}, vol_filter={volume_numbers}, ch_filter={chapter_numbers}", flush=True)
    print(f"[KB]   vol_filter_active={vol_filter_active}, ch_filter_active={ch_filter_active}, entries={len(all_entries)}, volumes_in_entries={vol_nums_in_entries}", flush=True)

    if not all_entries:
        print(f"[KB]   No entries found, returning empty", flush=True)
        return ""

    if comprehensive:
        print(f"[KB]   -> path: _build_comprehensive_volume_context (comprehensive=True)", flush=True)
        return await _build_comprehensive_volume_context(db, kb_id, all_entries, query_text, toc_mode)

    if ch_filter_active:
        print(f"[KB]   -> path: _build_chapter_level_context (ch_filter_active=True)", flush=True)
        return await _build_chapter_level_context(db, kb_id, all_entries, chapter_numbers, query_text)

    print(f"[KB]   -> path: default by_category", flush=True)
    by_category: dict[str, list[KnowledgeEntry]] = {}
    for entry in all_entries:
        cat = entry.category
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(entry)

    selected_ids = set()
    sections = []

    for cat, limit in limits.items():
        entries = by_category.get(cat, [])
        if not entries:
            continue
        label = KB_CATEGORY_LABELS.get(cat, cat)
        picked = entries[:limit]
        selected_ids.update(e.id for e in picked)
        items = []
        for e in picked:
            content = (e.content or "").strip()
            suffix = _event_suffix(e) if cat == "event" else ""
            items.append(f"- {e.title}：{content}{suffix}" if e.title else f"- {content}{suffix}")
        sections.append(f"【{label}】\n" + "\n".join(items))

    for cat, entries in by_category.items():
        if cat in limits:
            continue
        picked = entries[:other_limit]
        selected_ids.update(e.id for e in picked)
        label = KB_CATEGORY_LABELS.get(cat, cat)
        items = []
        for e in picked:
            content = (e.content or "").strip()
            items.append(f"- {e.title}：{content}" if e.title else f"- {content}")
        if items:
            sections.append(f"【{label}】\n" + "\n".join(items))

    if query_text:
        try:
            kb_results = await query_kb(kb_id, query_text, n_results=40)
            docs = kb_results.get("documents", [[]])[0] or []
            metas = kb_results.get("metadatas", [[]])[0] or []
            dists = kb_results.get("distances", [[]])[0] or []
            if docs:
                if len(dists) == len(docs):
                    order = sorted(range(len(docs)), key=lambda i: dists[i])
                    kept = [i for i in order if dists[i] <= 0.75]
                    if not kept:
                        kept = order[:3]
                    candidates = [(docs[i], metas[i] if i < len(metas) else {}) for i in kept]
                else:
                    candidates = [(docs[i], metas[i] if i < len(metas) else {}) for i in range(len(docs))]
                if vol_filter_active:
                    candidates = [
                        (d, m) for d, m in candidates
                        if m.get("volume_number") in volume_numbers or m.get("volume_number") is None
                    ]
                supplement = []
                for doc, meta in candidates:
                    title = (meta.get("title", "") or "").lower()
                    already = title in {e.title.lower() for e in all_entries if e.title and e.id in selected_ids}
                    if not already:
                        supplement.append(f"- {doc}")
                if supplement:
                    sections.append("【与当前情节相关的补充参考】\n" + "\n".join(supplement[:50]))
        except Exception:
            pass

    return "\n\n".join(sections)


async def _build_comprehensive_volume_context(
    db: AsyncSession,
    kb_id: int,
    all_entries: list[KnowledgeEntry],
    query_text: str,
    toc_mode: bool = False,
) -> str:
    by_vol: dict[int, list[KnowledgeEntry]] = {}
    no_vol: list[KnowledgeEntry] = []
    for e in all_entries:
        if e.volume is None:
            no_vol.append(e)
        else:
            by_vol.setdefault(e.volume, []).append(e)

    print(f"[KB-COMP] _build_comprehensive_volume_context: toc_mode={toc_mode}, volumes={sorted(by_vol.keys())}, no_vol_entries={len(no_vol)}", flush=True)

    kb = await get_kb(db, kb_id)
    vol_titles = {
        v.get("volume_number"): v.get("title", "")
        for v in (kb.volumes or [])
        if isinstance(v, dict)
    }

    sections = []
    for vol_num in sorted(by_vol.keys()):
        entries = by_vol[vol_num]
        title = vol_titles.get(vol_num, f"第{vol_num}卷")
        vol_event = next((e for e in entries if e.category == KB_CATEGORY_VOLUME_EVENT), None)
        if vol_event and (vol_event.content or "").strip():
            sections.append(f"【卷{vol_num}主要事件总结】\n{vol_event.content.strip()}")
        ch_summaries = [e for e in entries if e.category == KB_CATEGORY_CHAPTER_SUMMARY]
        vol_by_cat: dict[str, list[KnowledgeEntry]] = {}
        for e in entries:
            if e.category in (KB_CATEGORY_VOLUME_EVENT, KB_CATEGORY_CHAPTER_SUMMARY):
                continue
            vol_by_cat.setdefault(e.category, []).append(e)
        cat_counts = {cat: len(v) for cat, v in vol_by_cat.items()}
        print(f"[KB-COMP]   卷{vol_num}《{title}》: ch_summaries={len(ch_summaries)}, 6cat_counts={cat_counts}", flush=True)
        cat_lines = []
        for cat, limit in KB_INJECT_PER_CATEGORY_FULL.items():
            cat_entries = vol_by_cat.get(cat, [])
            if not cat_entries:
                continue
            for e in cat_entries[:limit]:
                content = (e.content or "").strip()
                suffix = _event_suffix(e) if cat == "event" else ""
                cat_lines.append(f"- {e.title}：{content}{suffix}" if e.title else f"- {content}{suffix}")
        if cat_lines:
            sections.append(f"【源卷{vol_num}《{title}》】\n" + "\n".join(cat_lines))
        if ch_summaries:
            ch_lines = []
            for e in sorted(ch_summaries, key=lambda x: (x.chapter_number or 0)):
                if toc_mode:
                    attrs = e.attributes if isinstance(e.attributes, dict) else {}
                    ke = attrs.get("key_events")
                    ke_str = "；".join(str(x) for x in ke) if isinstance(ke, list) and ke else ""
                    ch_lines.append(f"- 第{e.chapter_number}章《{e.chapter_title or ''}》：{ke_str}" if ke_str else f"- 第{e.chapter_number}章《{e.chapter_title or ''}》")
                else:
                    summary = (e.content or "").strip()
                    ch_lines.append(f"- 第{e.chapter_number}章《{e.chapter_title or ''}》：{summary}")
            sections.append(f"【卷{vol_num}{'章节目录' if toc_mode else '章节摘要'}】\n" + "\n".join(ch_lines))

    if no_vol:
        lines = []
        for e in no_vol:
            content = (e.content or "").strip()
            lines.append(f"- {e.title}：{content}" if e.title else f"- {content}")
        sections.append("【通用知识（无卷归属）】\n" + "\n".join(lines))

    relations = kb.volume_relations if kb else []
    if relations:
        rel_lines = []
        for r in relations:
            if isinstance(r, dict):
                rel_lines.append(
                    f"- 第{r.get('from_volume', '?')}卷 → 第{r.get('to_volume', '?')}卷：{r.get('description', '')}"
                )
        if rel_lines:
            sections.append("【跨卷关联】\n" + "\n".join(rel_lines))

    summaries = []
    for v in (kb.volumes or []):
        if isinstance(v, dict) and v.get("summary"):
            summaries.append(f"- 第{v.get('volume_number', '?')}卷《{v.get('title', '')}》：{v.get('summary', '')}")
    if summaries:
        sections.append("【各卷摘要】\n" + "\n".join(summaries))

    print(f"[KB-COMP]   各卷摘要: {len(summaries)} volumes with summaries, total_sections={len(sections)}", flush=True)
    return "\n\n".join(sections)


async def _build_chapter_level_context(
    db: AsyncSession,
    kb_id: int,
    all_entries: list[KnowledgeEntry],
    chapter_numbers: list[int],
    query_text: str,
) -> str:
    ch_set = set(chapter_numbers)
    by_cat: dict[str, list[KnowledgeEntry]] = {}
    for e in all_entries:
        by_cat.setdefault(e.category, []).append(e)

    sections = []

    vol_events = by_cat.get(KB_CATEGORY_VOLUME_EVENT, [])
    seen_vol: set = set()
    ve_lines = []
    for e in vol_events:
        if e.volume in seen_vol:
            continue
        seen_vol.add(e.volume)
        content = (e.content or "").strip()
        ve_lines.append(f"- 第{e.volume}卷《{e.volume_title or ''}》：{content}")
    if ve_lines:
        sections.append("【卷主要事件总结】\n" + "\n".join(ve_lines))

    ch_summaries = by_cat.get(KB_CATEGORY_CHAPTER_SUMMARY, [])
    ch_lines = []
    for e in ch_summaries:
        if e.chapter_number is not None and e.chapter_number not in ch_set:
            continue
        content = (e.content or "").strip()
        ch_lines.append(f"- 第{e.chapter_number}章《{e.chapter_title or ''}》：{content}")
    if ch_lines:
        sections.append("【本章摘要】\n" + "\n".join(ch_lines))

    chars_lines = []
    seen_chars: set = set()
    for e in by_cat.get("character", []):
        if e.chapter_number is not None and e.chapter_number not in ch_set:
            continue
        name = (e.title or "").strip()
        if name in seen_chars:
            continue
        seen_chars.add(name)
        content = (e.content or "").strip()
        chars_lines.append(f"- {name}：{content}" if name else f"- {content}")
    if chars_lines:
        sections.append("【本章角色】\n" + "\n".join(chars_lines[:30]))

    ev_lines = []
    seen_ev: set = set()
    for e in by_cat.get("event", []):
        if e.chapter_number is not None and e.chapter_number not in ch_set:
            continue
        name = (e.title or "").strip().lower()
        if name in seen_ev:
            continue
        seen_ev.add(name)
        content = (e.content or "").strip()
        suffix = _event_suffix(e)
        ev_lines.append(f"- {e.title}：{content}{suffix}" if e.title else f"- {content}{suffix}")
    if ev_lines:
        sections.append("【本章事件】\n" + "\n".join(ev_lines[:30]))

    for cat in ("worldview", "setting", "faction", "timeline"):
        items = by_cat.get(cat, [])
        lines = []
        for e in items:
            if e.chapter_number is not None and e.chapter_number not in ch_set:
                continue
            content = (e.content or "").strip()
            lines.append(f"- {e.title}：{content}" if e.title else f"- {content}")
        if lines:
            label = KB_CATEGORY_LABELS.get(cat, cat)
            sections.append(f"【{label}】\n" + "\n".join(lines[:20]))

    shown_titles: set = set()
    for e in all_entries:
        if e.chapter_number is not None and e.chapter_number not in ch_set:
            continue
        if e.title:
            shown_titles.add(e.title.strip().lower())

    if query_text:
        try:
            kb_results = await query_kb(kb_id, query_text, n_results=20)
            docs = kb_results.get("documents", [[]])[0] or []
            metas = kb_results.get("metadatas", [[]])[0] or []
            dists = kb_results.get("distances", [[]])[0] or []
            if docs and len(dists) == len(docs):
                order = sorted(range(len(docs)), key=lambda i: dists[i])
                kept = [i for i in order if dists[i] <= 0.75]
                if not kept:
                    kept = order[:3]
                candidates = [(docs[i], metas[i] if i < len(metas) else {}) for i in kept]
            else:
                candidates = [(docs[i], metas[i] if i < len(metas) else {}) for i in range(len(docs))]
            candidates = [
                (d, m) for d, m in candidates
                if m.get("chapter_number") in ch_set or m.get("chapter_number") is None
            ]
            supplement = []
            for d, m in candidates:
                t = (m.get("title") or "").strip().lower()
                if t and t in shown_titles:
                    continue
                supplement.append(f"- {d}")
                if len(supplement) >= 20:
                    break
            if supplement:
                sections.append("【与本章相关的补充参考】\n" + "\n".join(supplement))
        except Exception:
            pass

    return "\n\n".join(sections) if sections else ""


def _dedup_entries(entries: list[dict], key: str = "name") -> list[dict]:
    seen = set()
    result = []
    for e in entries:
        k = (e.get(key, "") or "").strip()
        if not k:
            continue
        lk = k.lower()
        if lk in seen:
            continue
        seen.add(lk)
        result.append(e)
    return result


async def _extract_volume_event_summary(chapters_data: list[dict], volume_number: int, volume_title: str) -> str:
    return await _build_volume_summary_from_chapters(chapters_data, volume_number, volume_title)


async def _extract_chapter_summary(chapter_text: str, chapter_number: int, chapter_title: str, volume_number: int, volume_title: str) -> dict:
    text = chapter_text or ""
    _MAX_CHAPTER_CHARS = 12000
    if len(text) > _MAX_CHAPTER_CHARS:
        text = text[:_MAX_CHAPTER_CHARS] + "\n\n（注：本章原文过长，以上为前12000字，请据此生成摘要）"
    base_prompt = f"""请阅读以下第 {volume_number}卷《{volume_title}》中第 {chapter_number}章《{chapter_title}》的全文，生成该章详细内容摘要。
输出严格JSON格式（只输出JSON，不要输出其他内容）：
{{
  "summary": "600-1200字的本章详细摘要，按情节先后完整组织，覆盖全章主要事件、转折与角色互动，平实陈述",
  "characters": ["本章出场的角色名（含次要角色，尽量完整）"],
  "key_events": ["本章关键事件名称（带简短上下文，如'主角与某角色在某地发生某事'）"]
}}

注意：
- summary 必须覆盖全章内容，不得只概括开头；若章较长，分前后两段概述
- characters 尽量列出本章所有出场角色
- key_events 每条带简短上下文，便于后续按章摘要派生提取事件/角色/时间线/势力/设定/世界观
- 没有明确出现的角色/事件不要编造，对应数组留空
- summary 用平实陈述句，避免排比堆叠和"——"破折号

文本：
{text}"""

    for attempt in range(2):
        prompt = base_prompt
        temp = 0.3
        if attempt == 1:
            prompt = base_prompt + "\n\n重要提示：上一次提取返回了空摘要。该章内容可能较短或结构特殊，请务必基于实际文本生成至少一句概述性摘要，不得返回空字符串。"
            temp = 0.1
        messages = [
            {"role": "system", "content": "你是一位文学分析专家，擅长梳理小说章节内容并提取关键信息。"},
            {"role": "user", "content": prompt},
        ]
        try:
            response = await llm_client.chat(messages, temperature=temp, max_tokens=CHAPTER_SUMMARY_MAX_TOKENS)
        except Exception:
            if attempt == 0:
                continue
            return {"summary": "", "characters": [], "key_events": []}
        data = _parse_json_response(response)
        if not isinstance(data, dict):
            if attempt == 0:
                continue
            return {"summary": "", "characters": [], "key_events": []}
        summary = (data.get("summary") or "").strip()
        if not summary and attempt == 0:
            continue
        characters = data.get("characters")
        if not isinstance(characters, list):
            characters = []
        key_events = data.get("key_events")
        if not isinstance(key_events, list):
            key_events = []
        return {
            "summary": summary,
            "characters": [str(c) for c in characters],
            "key_events": [str(e) for e in key_events],
        }
    return {"summary": "", "characters": [], "key_events": []}


async def _extract_chapter_summaries_batch(vtext: str, volume_number: int, volume_title: str) -> list:
    chapters = detect_chapters_in_volume(vtext)
    if not chapters:
        return []
    _MIN_CHAPTER_CHARS = 200
    _APPENDIX_KEYWORDS = ("附录", "设定草案", "人物设定", "返回的附录")
    _before = len(chapters)
    chapters = [
        ch for ch in chapters
        if len((ch.get("text") or "").strip()) >= _MIN_CHAPTER_CHARS
        and not any(kw in (ch.get("chapter_title") or "") for kw in _APPENDIX_KEYWORDS)
    ]
    if _before != len(chapters):
        logger.info("[KB导入] 第%d卷《%s》过滤短章/附录章: %d→%d章", volume_number, volume_title, _before, len(chapters))
    if not chapters:
        return []
    BATCH = 4
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)

    async def process_one(ch: dict):
        async with semaphore:
            return await _extract_chapter_summary(
                ch.get("text", ""),
                ch.get("chapter_number", 1),
                ch.get("chapter_title", ""),
                volume_number,
                volume_title,
            )

    _total_batches = (len(chapters) + BATCH - 1) // BATCH
    results = []
    for batch_start in range(0, len(chapters), BATCH):
        batch = chapters[batch_start:batch_start + BATCH]
        _batch_num = batch_start // BATCH + 1
        logger.info("[KB导入] 第%d卷 章节摘要批次 %d/%d (第%d章起)", volume_number, _batch_num, _total_batches, batch[0].get("chapter_number", 1))
        tasks = [process_one(ch) for ch in batch]
        summaries = await asyncio.gather(*tasks, return_exceptions=True)
        for i, s in enumerate(summaries):
            ch = batch[i]
            if isinstance(s, dict):
                summary_text = (s.get("summary") or "").strip()
                if not summary_text:
                    logger.warning(
                        "[KB导入] 第%d卷第%d章《%s》摘要为空，跳过",
                        volume_number,
                        ch.get("chapter_number", 1),
                        ch.get("chapter_title", ""),
                    )
                results.append({
                    "chapter_number": ch.get("chapter_number", 1),
                    "chapter_title": ch.get("chapter_title", ""),
                    "summary": summary_text,
                    "characters": s.get("characters", []),
                    "key_events": s.get("key_events", []),
                })
            elif isinstance(s, Exception):
                logger.warning(
                    "[KB导入] 第%d卷第%d章摘要提取异常: %s",
                    volume_number,
                    ch.get("chapter_number", 1),
                    s,
                )
    return results


def _salvage_json_mappings(text: str) -> dict | None:
    mappings = []
    pattern = r'\{\s*"canonical"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"aliases"\s*:\s*\[((?:\s*"(?:[^"\\]|\\.)*"\s*,?\s*)*)\]\s*\}'
    for m in re.finditer(pattern, text, re.DOTALL):
        canonical = m.group(1)
        aliases_raw = m.group(2)
        aliases = re.findall(r'"((?:[^"\\]|\\.)*)"', aliases_raw)
        mappings.append({"canonical": canonical, "aliases": aliases})
    if mappings:
        return {"mappings": mappings}
    return None


async def _normalize_character_names(
    chapters_data: list[dict], volume_number: int, volume_title: str,
    existing_canonical: dict[str, list[str]], semaphore: asyncio.Semaphore
) -> dict[str, list[str]]:
    all_names: list[str] = []
    for ch in chapters_data:
        for name in (ch.get("characters") or []):
            n = str(name).strip()
            if n and n not in all_names:
                all_names.append(n)

    if not all_names:
        return {}

    known_list = "\n".join(
        f"- {cano}（别名: {', '.join(alis) if alis else '无'}）"
        for cano, alis in existing_canonical.items()
    ) or "（暂无已知角色）"

    prompt = f"""以下是第 {volume_number}卷《{volume_title}》各章摘要中出现的角色名列表。
请识别哪些是同一个人的不同称呼（全称/简称/职业称呼/别名），将它们统一为一个标准名。

已知角色标准名与别名（来自之前卷，请保持一致）：
{known_list}

本卷出现的角色名列表：
{json.dumps(all_names, ensure_ascii=False)}

输出严格JSON（只输出JSON）：
{{
  "mappings": [
    {{"canonical": "标准名", "aliases": ["别名1", "别名2"]}}
  ]
}}

规则：
- 如果某角色名与已知标准名指同一人，canonical 必须用已知的标准名
- 如果是新角色，canonical 用最完整的称呼（优先全称而非简称）
- 职业称呼（如"女仆"）若能确定指谁，映射到具体人名
- 无法确定的独立列出，不强行合并
- 每个角色名必须出现在某条 mapping 的 canonical 或 aliases 中"""

    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长识别小说中角色的不同称呼。"},
        {"role": "user", "content": prompt},
    ]
    last_data = None
    for attempt in range(2):
        async with semaphore:
            try:
                resp = await llm_client.chat(messages, temperature=0.2 if attempt == 0 else 0.1, max_tokens=8192)
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[角色名归一] 第{volume_number}卷 LLM调用失败将重试: {e}")
                    continue
                logger.error(f"[角色名归一] 第{volume_number}卷 LLM调用重试仍失败: {e}")
                return {}
        data = _parse_json_response(resp)
        if isinstance(data, dict):
            last_data = data
            break
        salvaged = _salvage_json_mappings(resp or "")
        if isinstance(salvaged, dict):
            logger.info(f"[角色名归一] 第{volume_number}卷 JSON被截断，成功抢救{len(salvaged.get('mappings', []))}条角色映射")
            last_data = salvaged
            break
        if attempt == 0:
            logger.warning(f"[角色名归一] 第{volume_number}卷 JSON解析失败将重试，原始响应: {(resp or '')[:200]}")
    if not isinstance(last_data, dict):
        logger.error(f"[角色名归一] 第{volume_number}卷 JSON解析重试仍失败，角色别名将为空，可能产生重复角色")
        return {}
    data = last_data

    mappings = data.get("mappings", [])
    if not isinstance(mappings, list):
        return {}
    name_to_cano: dict[str, str] = {}
    result: dict[str, list[str]] = dict(existing_canonical)
    for m in mappings:
        if not isinstance(m, dict):
            continue
        cano = (m.get("canonical") or "").strip()
        if not cano:
            continue
        alis = [str(a).strip() for a in (m.get("aliases") or []) if str(a).strip()]
        name_to_cano[cano] = cano
        for a in alis:
            name_to_cano[a] = cano
        if cano in result:
            existing_aliases = set(result[cano])
            existing_aliases.update(alis)
            result[cano] = sorted(existing_aliases)
        else:
            result[cano] = sorted(set(alis))

    if name_to_cano:
        for ch in chapters_data:
            raw_chars = ch.get("characters") or []
            normalized = []
            seen = set()
            for name in raw_chars:
                n = str(name).strip()
                cano = name_to_cano.get(n, n)
                if cano not in seen:
                    seen.add(cano)
                    normalized.append(cano)
            ch["characters"] = normalized

    return result


async def _load_existing_character_aliases(db: AsyncSession, kb_id: int, current_vol: int) -> dict[str, list[str]]:
    result = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.kb_id == kb_id,
            KnowledgeEntry.category == "character",
            KnowledgeEntry.volume < current_vol,
        )
    )
    entries = result.scalars().all()
    aliases_map: dict[str, list[str]] = {}
    for e in entries:
        attrs = e.attributes if isinstance(e.attributes, dict) else {}
        alis = attrs.get("aliases")
        if isinstance(alis, list) and alis:
            aliases_map[e.title] = [str(a) for a in alis]
        else:
            aliases_map[e.title] = []
    return aliases_map


def _parse_json_response(response: str):
    clean = (response or "").strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        if len(lines) >= 2:
            clean = "\n".join(lines[1:])
            if clean.endswith("```"):
                clean = clean[:-3]
    try:
        return json.loads(clean)
    except (json.JSONDecodeError, TypeError):
        return None


def _cosine(a, b) -> float:
    if a is None or b is None or len(a) == 0 or len(b) == 0 or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


_BLOB_MAX_CHARS = 30000


def _chapters_blob(chapters_data: list[dict]) -> str:
    blob = "\n\n".join(_chapter_segment(ch) for ch in chapters_data)
    if len(blob) > _BLOB_MAX_CHARS:
        blob = blob[:_BLOB_MAX_CHARS] + "\n\n（注：本卷章节数量较多，以上为前30000字摘要，后续章节摘要已截断）"
    return blob


async def _build_volume_summary_from_chapters(
    chapters_data: list[dict], volume_number: int, volume_title: str
) -> str:
    if not chapters_data:
        return ""
    parts = [_chapter_segment(ch) for ch in chapters_data]
    joined = "\n\n".join(parts)

    async def _seg_summarize(text: str, mid: bool = False) -> str:
        label = "分段小结" if mid else "卷总结"
        prompt = f"""以下是第 {volume_number}卷《{volume_title}》各章详细摘要，请生成该卷{label}：综合该卷主要事件走向、关键情节转折与重要角色弧光变化。
输出 300-600 字连贯总结，按情节先后组织，突出因果与转折。不要罗列条目，不要输出标题。

各章摘要：
{text}"""
        messages = [
            {"role": "system", "content": "你是一位文学分析专家，擅长梳理小说情节脉络。"},
            {"role": "user", "content": prompt},
        ]
        try:
            resp = await llm_client.chat(messages, temperature=0.3, max_tokens=VOL_SUMMARY_MAX_TOKENS)
        except Exception:
            return ""
        return (resp or "").strip()

    if len(joined) <= VOL_SUMMARY_SEG_LIMIT:
        return await _seg_summarize(joined)

    segments: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for p in parts:
        if cur and cur_len + len(p) > VOL_SUMMARY_SEG_LIMIT:
            segments.append(cur)
            cur = [p]
            cur_len = len(p)
        else:
            cur.append(p)
            cur_len += len(p)
    if cur:
        segments.append(cur)

    seg_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
    batch_n = 4

    async def _mid(seg_parts: list[str]) -> str:
        async with seg_semaphore:
            return await _seg_summarize("\n\n".join(seg_parts), mid=True)

    mids: list[str] = []
    for i in range(0, len(segments), batch_n):
        batch = segments[i:i + batch_n]
        res = await asyncio.gather(*[_mid(s) for s in batch], return_exceptions=True)
        for r in res:
            if isinstance(r, str) and r:
                mids.append(r)
    if not mids:
        return ""
    return await _seg_summarize("\n\n".join(mids))


async def _derive_key_characters(
    chapters_data: list[dict], volume_number: int, volume_title: str,
    semaphore: asyncio.Semaphore, canonical_map: dict[str, list[str]]
) -> list[dict]:
    chap_appear: dict[str, set] = defaultdict(set)
    char_chap_summary: dict[str, list[str]] = defaultdict(list)
    all_events: list[str] = []
    for ch in chapters_data:
        cn = ch.get("chapter_number", 1)
        for name in (ch.get("characters") or []):
            n = str(name).strip()
            if not n:
                continue
            chap_appear[n].add(cn)
            char_chap_summary[n].append(f"[第{cn}章] {(ch.get('summary') or '').strip()}")
        for ev in (ch.get("key_events") or []):
            all_events.append(str(ev))
    events_blob = "；".join(all_events)
    event_mention: dict[str, int] = {}
    for n in chap_appear:
        event_mention[n] = events_blob.count(n) if n and n in events_blob else 0
    key_names = [
        n for n in chap_appear
        if len(chap_appear[n]) >= KEY_CHAR_MIN_CHAPTERS
        or event_mention.get(n, 0) >= KEY_CHAR_MIN_EVENTS
    ]
    if not key_names:
        return []
    batch_n = 4

    async def _one(name: str):
        ctx = "\n\n".join(char_chap_summary[name])[:12000]
        prompt = f"""以下是第 {volume_number}卷《{volume_title}》中角色"{name}"出场的各章摘要。请综合成该角色一条知识条目：身份背景、性格能力、与本卷其他角色关系、本卷内的成长弧光。250-500字，平实陈述，不编造。
输出严格JSON（只输出JSON）：{{"content": "..."}}

相关章节摘要：
{ctx}"""
        messages = [
            {"role": "system", "content": "你是一位文学分析专家，擅长提炼角色设定。"},
            {"role": "user", "content": prompt},
        ]
        async with semaphore:
            try:
                resp = await llm_client.chat(messages, temperature=0.3, max_tokens=1536)
            except Exception:
                return None
        data = _parse_json_response(resp)
        if isinstance(data, dict):
            content = (data.get("content") or "").strip()
            if content:
                aliases = canonical_map.get(name, [])
                return {"name": name, "content": content, "aliases": aliases}
        return None

    results: list[dict] = []
    for i in range(0, len(key_names), batch_n):
        batch = key_names[i:i + batch_n]
        res = await asyncio.gather(*[_one(n) for n in batch], return_exceptions=True)
        for r in res:
            if isinstance(r, dict):
                results.append(r)
    return _dedup_entries(results)


async def _derive_volume_events(
    chapters_data: list[dict], volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    blob = _chapters_blob(chapters_data)

    async def _call(kind: str) -> list[dict]:
        if kind == "main":
            instr = "提取该卷推动主线或角色弧光的主要事件，跳过与主线无关的日常/插曲"
        elif kind == "romance":
            instr = "提取该卷主角及主要角色之间的感情线发展关键节点"
        else:
            instr = "提取该卷主要角色的成长/转变关键节点"
        prompt = f"""以下是第 {volume_number}卷《{volume_title}》各章详细摘要。请{instr}。
输出严格JSON（只输出JSON）：[{{"name":"事件名称","content":"经过/起因/结果/涉及角色","characters":["参与角色名"]}}]
没有则输出 []。content 用平实陈述，不编造。

各章摘要：
{blob}"""
        messages = [
            {"role": "system", "content": "你是一位文学分析专家，擅长提炼小说事件。"},
            {"role": "user", "content": prompt},
        ]
        async with semaphore:
            try:
                resp = await llm_client.chat(messages, temperature=0.3, max_tokens=3072)
            except Exception:
                return []
        data = _parse_json_response(resp)
        out: list[dict] = []
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    out.append(it)
        return out

    main_evs, rom_evs, gro_evs = await asyncio.gather(
        _call("main"), _call("romance"), _call("growth")
    )
    for it in rom_evs:
        it["subtype"] = "romance"
    for it in gro_evs:
        it["subtype"] = "growth"
    merged: list[dict] = []
    seen_names: set = set()
    for it in rom_evs + gro_evs + main_evs:
        name = (it.get("name") or "").strip().lower()
        if name and name in seen_names:
            continue
        if name:
            seen_names.add(name)
        merged.append(it)

    merged = await _consolidate_events(merged, volume_number, volume_title, semaphore)
    return merged


async def _consolidate_events(
    events: list[dict], volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    if len(events) <= 1:
        return events

    event_list = []
    for i, ev in enumerate(events):
        event_list.append({
            "id": i,
            "name": ev.get("name", ""),
            "content": ev.get("content", ""),
            "subtype": ev.get("subtype", ""),
        })

    prompt = f"""以下是第 {volume_number}卷《{volume_title}》从主线/感情线/成长线三个角度提取的事件列表。
其中可能存在重复或高度相似的事件（描述角度不同但指同一件事）。请整合合并，输出最终去重后的事件列表。

输入事件：
{json.dumps(event_list, ensure_ascii=False)}

输出严格JSON（只输出JSON）：
{{
  "merged_groups": [
    {{"source_ids": [0, 3], "name": "整合后事件名", "content": "整合后内容"}}
  ]
}}

规则：
- 将指同一件事的事件合并为一条（即使名称不同但内容高度重叠）
- 合并后 name 用最准确的概括，content 融合多角度描述但不重复
- 保留 source_ids 中第一个事件的 subtype（如果涉及多个 subtype，优先 main > romance > growth）
- 独立事件保持不变，source_ids 只含自身 id
- 不要遗漏任何事件，每个输入 id 必须出现在某个 group 中"""

    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长整合小说事件叙述。"},
        {"role": "user", "content": prompt},
    ]
    async with semaphore:
        try:
            resp = await llm_client.chat(messages, temperature=0.2, max_tokens=4096)
        except Exception:
            return events
    data = _parse_json_response(resp)
    if not isinstance(data, dict):
        return events
    groups = data.get("merged_groups")
    if not isinstance(groups, list) or not groups:
        return events

    subtype_priority = {"main": 0, "romance": 1, "growth": 2}
    result: list[dict] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        source_ids = g.get("source_ids", [])
        if not isinstance(source_ids, list) or not source_ids:
            continue
        name = (g.get("name") or "").strip()
        content = (g.get("content") or "").strip()
        if not name and not content:
            continue
        subtypes = [events[i].get("subtype", "") for i in source_ids if 0 <= i < len(events)]
        chosen_sub = min(subtypes, key=lambda s: subtype_priority.get(s, 99)) if subtypes else ""
        item = {"name": name, "content": content}
        if chosen_sub:
            item["subtype"] = chosen_sub
        all_chars = []
        for i in source_ids:
            if 0 <= i < len(events):
                for c in (events[i].get("characters") or []):
                    if str(c) not in all_chars:
                        all_chars.append(str(c))
        if all_chars:
            item["characters"] = all_chars
        result.append(item)
    return result if result else events


async def _derive_timeline(
    chapters_data: list[dict], events: list[dict],
    volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    blob = _chapters_blob(chapters_data)
    events_text = ""
    if events:
        event_lines = []
        for ev in events:
            name = ev.get("name", "")
            content = ev.get("content", "")
            event_lines.append(f"- {name}：{content}")
        events_text = "\n".join(event_lines)

    prompt = f"""以下是第 {volume_number}卷《{volume_title}》已提取的关键事件及各章摘要。
请据此梳理该卷时间线，以关键事件为主要线索，按故事内时间先后输出重要时间节点。

已提取的关键事件：
{events_text}

各章摘要（作为补充背景）：
{blob}

要求：
- 时间节点名必须使用故事内的时间/阶段描述，例如"成为家庭教师一个月后""抵达王都当日""战斗后的第三天""修炼半年后"等
- 禁止使用"第X章"或章标题作为时间节点名
- 只记录推动情节发展的关键转折点，跳过琐碎细节
- 每个节点简要描述该时间发生的关键事件及其影响
输出严格JSON（只输出JSON）：[{{"name":"时间节点/阶段","content":"关键事件与影响简述"}}]
没有则输出 []。不编造。"""
    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长梳理小说时间线，注重简洁和重点。"},
        {"role": "user", "content": prompt},
    ]
    last_out: list[dict] = []
    for attempt in range(2):
        async with semaphore:
            try:
                resp = await llm_client.chat(messages, temperature=0.2 if attempt == 0 else 0.1, max_tokens=1536)
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[时间线派生] 第{volume_number}卷 LLM调用失败将重试: {e}")
                    continue
                logger.error(f"[时间线派生] 第{volume_number}卷 LLM调用重试仍失败: {e}")
                return []
        data = _parse_json_response(resp)
        out: list[dict] = []
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    out.append(it)
        if out:
            return _dedup_entries(out)
        last_out = out
        if attempt == 0:
            logger.warning(f"[时间线派生] 第{volume_number}卷 LLM返回空或解析为空(resp_len={len(resp) if resp else 0})将重试")
    return _dedup_entries(last_out)


async def _derive_factions(
    chapters_data: list[dict], volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    blob = _chapters_blob(chapters_data)
    prompt = f"""以下是第 {volume_number}卷《{volume_title}》各章摘要（含关键事件）。请提取该卷出现的势力/组织/阵营（有成员、有目标、有立场的团体，如国家、商会、骑士团、暗杀组织等）。
不要提取单纯的剑术流派/技能体系/魔法分类/武功招式——这些属于世界观设定，不是组织势力。
输出严格JSON（只输出JSON）：[{{"name":"势力/组织名称","content":"势力描述、成员、目的、立场"}}]
没有则输出 []。content 用平实陈述，不编造。

各章摘要：
{blob}"""
    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长提炼小说中的势力组织。"},
        {"role": "user", "content": prompt},
    ]
    async with semaphore:
        try:
            resp = await llm_client.chat(messages, temperature=0.3, max_tokens=2048)
        except Exception:
            return []
    data = _parse_json_response(resp)
    out: list[dict] = []
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                out.append(it)
    return _dedup_entries(out)


async def _derive_settings(
    chapters_data: list[dict], volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    blob = _chapters_blob(chapters_data)
    prompt = f"""以下是第 {volume_number}卷《{volume_title}》各章摘要（含关键事件）。请提取与主线相关的设定（功法/地理/规则/道具/种族等），跳过与主线无关的。
输出严格JSON（只输出JSON）：[{{"name":"设定名称","content":"设定描述"}}]
没有则输出 []。content 用平实陈述，不编造。

各章摘要：
{blob}"""
    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长提炼小说设定。"},
        {"role": "user", "content": prompt},
    ]
    async with semaphore:
        try:
            resp = await llm_client.chat(messages, temperature=0.3, max_tokens=2048)
        except Exception:
            return []
    data = _parse_json_response(resp)
    out: list[dict] = []
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                out.append(it)
    out = _dedup_entries(out)
    out = await _consolidate_settings(out, volume_number, volume_title, semaphore)
    return out


async def _consolidate_settings(
    settings: list[dict], volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    if len(settings) <= 1:
        return settings

    setting_list = []
    for i, s in enumerate(settings):
        setting_list.append({
            "id": i,
            "name": s.get("name", ""),
            "content": s.get("content", ""),
        })

    prompt = f"""以下是第 {volume_number}卷《{volume_title}》提取的设定条目列表。
其中可能存在散乱/碎片化的条目，请将相关的条目整合归并为更有条理的分类条目。

输入设定：
{json.dumps(setting_list, ensure_ascii=False)}

输出严格JSON（只输出JSON）：
{{
  "merged_groups": [
    {{"source_ids": [0, 3, 5], "name": "整合后设定名称", "content": "整合后内容（可分条描述各子项）"}}
  ]
}}

规则：
- 将属于同一体系/类别的设定合并为一条（如"治疗魔术""魔术分类""魔力来源"可整合为"魔术体系"）
- 合并后 name 用体系/类别的概括名称
- content 融合各子项描述，可分条/分段描述但不重复
- 独立且不相关的设定保持不变，source_ids 只含自身 id
- 不要遗漏任何条目，每个输入 id 必须出现在某个 group 中"""

    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长整理小说设定体系。"},
        {"role": "user", "content": prompt},
    ]
    async with semaphore:
        try:
            resp = await llm_client.chat(messages, temperature=0.2, max_tokens=4096)
        except Exception:
            return settings
    data = _parse_json_response(resp)
    if not isinstance(data, dict):
        return settings
    groups = data.get("merged_groups")
    if not isinstance(groups, list) or not groups:
        return settings

    result: list[dict] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        source_ids = g.get("source_ids", [])
        if not isinstance(source_ids, list) or not source_ids:
            continue
        name = (g.get("name") or "").strip()
        content = (g.get("content") or "").strip()
        if not name and not content:
            continue
        result.append({"name": name, "content": content})
    return result if result else settings


async def _derive_worldview_with_dedup(
    chapters_data: list[dict],
    volume_number: int,
    volume_title: str,
    cached_embs: list,
    emb_lock: asyncio.Lock,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    blob = _chapters_blob(chapters_data)
    prompt = f"""以下是第 {volume_number}卷《{volume_title}》各章摘要（含关键事件）。请提取该卷展现的世界观要素，包括但不限于：
- 地理/世界格局
- 世界规则/法则
- 体系设定：剑术流派（如剑神流/水神流/北神流）、魔术/魔法体系（分类、来源、用途）、技能体系等
- 风俗/文化
将同一体系下的流派/分类整合为一条（如将"剑神流""水神流""北神流"整合为"剑术流派"条目，content 中分条描述各流派）。
输出严格JSON（只输出JSON）：[{{"name":"要素名称","content":"要素描述"}}]
没有则输出 []。content 用平实陈述，不编造。

各章摘要：
{blob}"""
    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长提炼小说世界观。"},
        {"role": "user", "content": prompt},
    ]
    async with semaphore:
        try:
            resp = await llm_client.chat(messages, temperature=0.3, max_tokens=2048)
        except Exception:
            return []
    data = _parse_json_response(resp)
    candidates: list[dict] = []
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                candidates.append(it)
    candidates = _dedup_entries(candidates)

    valid: list[tuple[str, str, str]] = []
    for cand in candidates:
        name = (cand.get("name") or "").strip()
        content = (cand.get("content") or "").strip()
        if not name and not content:
            continue
        valid.append((name, content, f"[worldview] {name}: {content}"))

    new_items: list[dict] = []
    if not valid:
        return new_items

    embs = await embed_texts([v[2] for v in valid])
    for (name, content, _), emb in zip(valid, embs):
        if not emb or not any(emb):
            new_items.append({"name": name, "content": content})
            continue
        async with emb_lock:
            snapshot = list(cached_embs)
        max_sim = 0.0
        for _, ev in snapshot:
            sim = _cosine(emb, ev)
            if sim > max_sim:
                max_sim = sim
        if max_sim >= WORLDVIEW_DEDUP_THRESHOLD:
            continue
        new_items.append({"name": name, "content": content, "_emb": emb})
        async with emb_lock:
            cached_embs.append((name, emb))
    return new_items


async def _derive_volume_all(
    chapters_data: list[dict],
    volume_number: int,
    volume_title: str,
    cached_embs: list,
    emb_lock: asyncio.Lock,
    canonical_map: dict[str, list[str]],
) -> dict:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
    chars, events, factions, settings = await asyncio.gather(
        _derive_key_characters(chapters_data, volume_number, volume_title, semaphore, canonical_map),
        _derive_volume_events(chapters_data, volume_number, volume_title, semaphore),
        _derive_factions(chapters_data, volume_number, volume_title, semaphore),
        _derive_settings(chapters_data, volume_number, volume_title, semaphore),
    )
    timeline, worldview = await asyncio.gather(
        _derive_timeline(chapters_data, events, volume_number, volume_title, semaphore),
        _derive_worldview_with_dedup(
            chapters_data, volume_number, volume_title, cached_embs, emb_lock, semaphore
        ),
    )
    return {
        "character": chars,
        "event": events,
        "timeline": timeline,
        "faction": factions,
        "setting": settings,
        "worldview": worldview,
    }


async def _reset_volume(db: AsyncSession, kb_id: int, volume_number: int) -> None:
    res = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.kb_id == kb_id,
            KnowledgeEntry.volume == volume_number,
        )
    )
    entries = res.scalars().all()
    ids = [f"kb_{kb_id}_entry_{e.id}" for e in entries]
    for e in entries:
        await db.delete(e)
    if ids:
        try:
            await delete_from_kb(kb_id, ids)
        except Exception:
            pass
    await db.flush()


async def reset_volume_for_reextract(db: AsyncSession, kb_id: int, volume_number: int) -> dict:
    kb = await get_kb(db, kb_id)
    if not kb:
        raise ValueError("知识库不存在")
    await _reset_volume(db, kb_id, volume_number)
    volumes = kb.volumes or []
    found = False
    for v in volumes:
        if isinstance(v, dict) and v.get("volume_number") == volume_number:
            v["status"] = "pending"
            found = True
            break
    if not found:
        volumes.append({
            "volume_number": volume_number,
            "title": "",
            "source": "manual",
            "status": "pending",
            "summary": "",
        })
        kb.volumes = volumes
    kb.import_status = "pending"
    await db.commit()
    return {"kb_id": kb_id, "volume_number": volume_number, "status": "pending"}


async def reextract_single_chapter(
    db: AsyncSession, kb_id: int, volume_number: int, chapter_number: int,
    file_content: bytes, filename: str,
) -> dict:
    kb = await get_kb(db, kb_id)
    if not kb:
        raise ValueError("知识库不存在")
    text = await extract_text_from_file(file_content, filename)
    detected = detect_volumes(text)
    vol = next((d for d in detected if d.get("volume_number") == volume_number), None)
    if not vol:
        raise ValueError(f"文件中未检测到第{volume_number}卷")
    vstart, vend = vol["char_range"]
    vtext = text[vstart:vend]
    chapters = detect_chapters_in_volume(vtext)
    ch = next((c for c in chapters if c.get("chapter_number") == chapter_number), None)
    if not ch:
        raise ValueError(f"第{volume_number}卷中未检测到第{chapter_number}章")
    ch_title = ch.get("chapter_title", "")
    result = await _extract_chapter_summary(
        ch.get("text", ""), chapter_number, ch_title, volume_number, vol["title"]
    )
    summary_text = (result.get("summary") or "").strip()
    if not summary_text:
        raise ValueError("重提取后摘要仍为空，可能该章内容过短或为误识别的卷标题")
    existing_res = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.kb_id == kb_id,
            KnowledgeEntry.volume == volume_number,
            KnowledgeEntry.chapter_number == chapter_number,
            KnowledgeEntry.category == KB_CATEGORY_CHAPTER_SUMMARY,
        )
    )
    existing_entry = existing_res.scalars().first()
    attrs = {
        "characters": result.get("characters", []),
        "key_events": result.get("key_events", []),
    }
    if existing_entry:
        existing_entry.content = summary_text
        existing_entry.chapter_title = ch_title
        existing_entry.attributes = attrs
        entry_id = existing_entry.id
    else:
        new_entry = KnowledgeEntry(
            kb_id=kb_id,
            category=KB_CATEGORY_CHAPTER_SUMMARY,
            title=f"第{chapter_number}章《{ch_title}》摘要",
            content=summary_text,
            attributes=attrs,
            source="upload",
            volume=volume_number,
            volume_title=vol["title"],
            chapter_number=chapter_number,
            chapter_title=ch_title,
        )
        db.add(new_entry)
        await db.flush()
        entry_id = new_entry.id
    doc = f"[{KB_CATEGORY_CHAPTER_SUMMARY}] 第{chapter_number}章《{ch_title}》摘要: {summary_text}"
    vec_id = f"kb_{kb_id}_entry_{entry_id}"
    meta = {
        "category": KB_CATEGORY_CHAPTER_SUMMARY,
        "title": f"第{chapter_number}章《{ch_title}》摘要",
        "source": "upload",
        "volume_number": volume_number,
        "chapter_number": chapter_number,
    }
    try:
        await delete_from_kb(kb_id, [vec_id])
    except Exception:
        pass
    try:
        await add_to_kb(kb_id, [doc], [vec_id], [meta])
    except Exception as e:
        logger.warning(f"[单章重提取] 向量写入失败: {e}")
    await db.commit()
    return {
        "kb_id": kb_id,
        "volume_number": volume_number,
        "chapter_number": chapter_number,
        "chapter_title": ch_title,
        "summary_length": len(summary_text),
        "characters": result.get("characters", []),
        "key_events": result.get("key_events", []),
    }


async def rederive_volume_timeline(db: AsyncSession, kb_id: int, volume_number: int) -> dict:
    kb = await get_kb(db, kb_id)
    if not kb:
        raise ValueError("知识库不存在")
    volumes = kb.volumes or []
    vol = next((v for v in volumes if isinstance(v, dict) and v.get("volume_number") == volume_number), None)
    volume_title = (vol.get("title") if vol else "") or ""
    cs_res = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.kb_id == kb_id,
            KnowledgeEntry.volume == volume_number,
            KnowledgeEntry.category == KB_CATEGORY_CHAPTER_SUMMARY,
        ).order_by(KnowledgeEntry.chapter_number)
    )
    chapters_data = []
    for e in cs_res.scalars().all():
        attrs = e.attributes if isinstance(e.attributes, dict) else {}
        chapters_data.append({
            "chapter_number": e.chapter_number or 0,
            "chapter_title": e.chapter_title or "",
            "summary": e.content or "",
            "key_events": attrs.get("key_events", []),
            "characters": attrs.get("characters", []),
        })
    ev_res = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.kb_id == kb_id,
            KnowledgeEntry.volume == volume_number,
            KnowledgeEntry.category == "event",
        )
    )
    events = []
    for e in ev_res.scalars().all():
        events.append({"name": e.title or "", "content": e.content or ""})
    if not chapters_data and not events:
        raise ValueError(f"第{volume_number}卷无章摘要与事件，无法派生时间线")
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
    timeline = await _derive_timeline(chapters_data, events, volume_number, volume_title, semaphore)
    if not timeline:
        raise ValueError(f"第{volume_number}卷时间线重提取仍为空（LLM可能返回[]或调用失败，请看服务端日志）")
    old_res = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.kb_id == kb_id,
            KnowledgeEntry.volume == volume_number,
            KnowledgeEntry.category == "timeline",
        )
    )
    old_entries = old_res.scalars().all()
    old_ids = [f"kb_{kb_id}_entry_{e.id}" for e in old_entries]
    for e in old_entries:
        await db.delete(e)
    if old_ids:
        try:
            await delete_from_kb(kb_id, old_ids)
        except Exception:
            pass
    new_objs: list[KnowledgeEntry] = []
    for it in timeline:
        title = (it.get("name", "") or "").strip()
        content = (it.get("content", "") or "").strip()
        if not title and not content:
            continue
        obj = KnowledgeEntry(
            kb_id=kb_id,
            category="timeline",
            title=title,
            content=content,
            attributes={},
            source="upload",
            volume=volume_number,
            volume_title=volume_title,
        )
        db.add(obj)
        new_objs.append(obj)
    await db.flush()
    docs: list[str] = []
    ids: list[str] = []
    metas: list[dict] = []
    for obj in new_objs:
        docs.append(f"[{obj.category}] {obj.title}: {obj.content}")
        ids.append(f"kb_{kb_id}_entry_{obj.id}")
        metas.append({"category": obj.category, "title": obj.title, "source": "upload", "volume_number": volume_number})
    if ids:
        try:
            await add_to_kb(kb_id, docs, ids, metas)
        except Exception as e:
            logger.warning(f"[时间线重提取] 第{volume_number}卷向量写入失败: {e}")
    await db.commit()
    return {
        "kb_id": kb_id,
        "volume_number": volume_number,
        "timeline_count": len(new_objs),
        "timeline": [{"name": o.title, "content": o.content} for o in new_objs],
    }


async def delete_volumes_from(db: AsyncSession, kb_id: int, start_volume: int) -> dict:
    kb = await get_kb(db, kb_id)
    if not kb:
        raise ValueError("知识库不存在")
    res = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.kb_id == kb_id,
            KnowledgeEntry.volume >= start_volume,
        )
    )
    entries = res.scalars().all()
    vec_ids = [f"kb_{kb_id}_entry_{e.id}" for e in entries]
    deleted_count = len(entries)
    for e in entries:
        await db.delete(e)
    volumes = kb.volumes or []
    kept_volumes = [v for v in volumes if isinstance(v, dict) and (v.get("volume_number") or 0) < start_volume]
    removed_nums = [v.get("volume_number") for v in volumes if isinstance(v, dict) and (v.get("volume_number") or 0) >= start_volume]
    kb.volumes = kept_volumes
    kb.import_status = "running" if kept_volumes else "pending"
    await db.flush()
    if vec_ids:
        try:
            await delete_from_kb(kb_id, vec_ids)
        except Exception as e:
            logger.warning(f"[删卷] 向量删除失败: {e}")
    await db.commit()
    return {
        "kb_id": kb_id,
        "deleted_from_volume": start_volume,
        "deleted_entries": deleted_count,
        "removed_volumes": removed_nums,
    }


async def append_file_continuation_stream(
    db: AsyncSession,
    kb_id: int,
    file_content: bytes,
    filename: str,
    start_volume: int,
    body_count: int | None = None,
    afterword_title: str = "后记/特典",
    skip_volumes: int = 0,
):
    kb = await get_kb(db, kb_id)
    if not kb:
        yield {"type": "error", "error": "知识库不存在", "filename": filename}
        return
    text = await extract_text_from_file(file_content, filename)
    if not text.strip():
        yield {"type": "error", "error": "文档内容为空", "filename": filename}
        return
    detected = detect_volumes(text)
    if not detected:
        yield {"type": "error", "error": "未检测到卷结构", "filename": filename}
        return
    if skip_volumes > 0:
        if skip_volumes >= len(detected):
            yield {"type": "error", "error": f"skip_volumes({skip_volumes})大于等于检测到的卷数({len(detected)})", "filename": filename}
            return
        detected = detected[skip_volumes:]

    target_vols: list[tuple[int, str, list, str]] = []
    n = len(detected)
    if body_count is not None and 0 < body_count < n:
        for i in range(body_count):
            d = detected[i]
            target_vols.append((start_volume + i, d["title"], d["char_range"], d["source"]))
        rest = detected[body_count:]
        merged_start = rest[0]["char_range"][0]
        merged_end = rest[-1]["char_range"][1]
        target_vols.append((start_volume + body_count, afterword_title, [merged_start, merged_end], "merged"))
    else:
        for i, d in enumerate(detected):
            target_vols.append((start_volume + i, d["title"], d["char_range"], d["source"]))

    prev_volumes = kb.volumes or []
    prev_nums = {v.get("volume_number") for v in prev_volumes if isinstance(v, dict)}
    volumes = [dict(v) for v in prev_volumes if isinstance(v, dict)]
    for vn, title, cr, src in target_vols:
        if vn in prev_nums:
            for v in volumes:
                if v.get("volume_number") == vn:
                    v["title"] = title
                    v["char_range"] = cr
                    v["source"] = src
                    v["status"] = "pending"
                    break
        else:
            volumes.append({
                "volume_number": vn,
                "title": title,
                "char_range": cr,
                "source": src,
                "status": "pending",
                "summary": "",
            })
    kb.volumes = volumes
    kb.import_status = "running"
    local_progress = {
        "phase": "extracting",
        "current_volume": 0,
        "total_volumes": len(target_vols),
        "extracted_volumes": [],
        "total_entries": 0,
    }
    kb.import_progress = dict(local_progress)
    await db.commit()

    yield {
        "type": "start",
        "filename": filename,
        "text_length": len(text),
        "total_volumes": len(target_vols),
        "start_volume": start_volume,
        "volumes": [{"volume_number": vn, "title": t} for vn, t, cr, src in target_vols],
    }

    cached_embs: list = []
    emb_lock = asyncio.Lock()
    try:
        coll = chroma_client.get_or_create_collection(get_kb_collection_name(kb_id))
        existing = coll.get(where={"category": "worldview"}, include=["embeddings", "metadatas"])
        cached_embs = [
            (m.get("title", ""), e.tolist() if hasattr(e, "tolist") else e)
            for m, e in zip(existing.get("metadatas", []), existing.get("embeddings", []))
        ]
    except Exception:
        pass

    imported_count = 0
    errors: list[str] = []
    relations_all = list(kb.volume_relations or [])

    for vi, (vn, vol_title, char_range, src) in enumerate(target_vols):
        await _reset_volume(db, kb_id, vn)
        vstart, vend = char_range
        vtext = text[vstart:vend]
        if not vtext.strip():
            for v in volumes:
                if v.get("volume_number") == vn:
                    v["status"] = "extracted"
                    break
            kb.volumes = [dict(v) for v in volumes]
            await db.commit()
            yield {
                "type": "progress", "phase": "extracting", "volume_number": vn,
                "volume_title": vol_title, "index": vi, "total": len(target_vols),
                "skipped": True, "cumulative_entries": imported_count,
            }
            continue

        print(f"[KB续接] 开始提取第{vn}卷《{vol_title}》(索引{vi}/{len(target_vols)})", flush=True)
        chapters_data = await _extract_chapter_summaries_batch(vtext, vn, vol_title)
        existing_aliases = await _load_existing_character_aliases(db, kb_id, vn)
        norm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
        canonical_map = await _normalize_character_names(
            chapters_data, vn, vol_title, existing_aliases, norm_semaphore
        )

        new_objs: list[KnowledgeEntry] = []
        for ch in chapters_data:
            if not (ch.get("summary") or "").strip():
                continue
            ch_obj = KnowledgeEntry(
                kb_id=kb_id,
                category=KB_CATEGORY_CHAPTER_SUMMARY,
                title=f"第{ch['chapter_number']}章《{ch['chapter_title']}》摘要",
                content=ch["summary"],
                attributes={"characters": ch.get("characters", []), "key_events": ch.get("key_events", [])},
                source="upload",
                volume=vn,
                volume_title=vol_title,
                chapter_number=ch["chapter_number"],
                chapter_title=ch["chapter_title"],
            )
            db.add(ch_obj)
            new_objs.append(ch_obj)
        for v in volumes:
            if v.get("volume_number") == vn:
                v["chapters"] = [
                    {"chapter_number": ch.get("chapter_number", 1), "chapter_title": ch.get("chapter_title", "")}
                    for ch in chapters_data
                ]
                break

        vol_event_text = await _extract_volume_event_summary(chapters_data, vn, vol_title)
        if vol_event_text:
            ve_obj = KnowledgeEntry(
                kb_id=kb_id,
                category=KB_CATEGORY_VOLUME_EVENT,
                title=f"第{vn}卷《{vol_title}》主要事件总结",
                content=vol_event_text,
                attributes={},
                source="upload",
                volume=vn,
                volume_title=vol_title,
            )
            db.add(ve_obj)
            new_objs.append(ve_obj)

        derived = await _derive_volume_all(chapters_data, vn, vol_title, cached_embs, emb_lock, canonical_map)
        for category, items in derived.items():
            for it in items:
                title = (it.get("name", "") or "").strip()
                content = (it.get("content", "") or "").strip()
                if not title and not content:
                    continue
                attrs: dict = {}
                if category == "character":
                    aliases = it.get("aliases")
                    if isinstance(aliases, list) and aliases:
                        attrs["aliases"] = [str(a) for a in aliases]
                if category == "event":
                    chars = it.get("characters")
                    attrs["characters"] = [str(c) for c in chars] if isinstance(chars, list) else []
                    subtype = it.get("subtype")
                    if subtype:
                        attrs["subtype"] = subtype
                obj = KnowledgeEntry(
                    kb_id=kb_id,
                    category=category,
                    title=title,
                    content=content,
                    attributes=attrs,
                    source="upload",
                    volume=vn,
                    volume_title=vol_title,
                )
                pre_emb = it.get("_emb")
                if pre_emb:
                    obj._precomputed_emb = pre_emb
                db.add(obj)
                new_objs.append(obj)
        await db.flush()

        docs_with_emb: list[str] = []
        ids_with_emb: list[str] = []
        metas_with_emb: list[dict] = []
        embs_with_emb: list[list[float]] = []
        docs_without: list[str] = []
        ids_without: list[str] = []
        metas_without: list[dict] = []
        for obj in new_objs:
            doc = f"[{obj.category}] {obj.title}: {obj.content}"
            id_ = f"kb_{kb_id}_entry_{obj.id}"
            meta = {"category": obj.category, "title": obj.title, "source": "upload", "volume_number": vn}
            if obj.chapter_number is not None:
                meta["chapter_number"] = obj.chapter_number
            if obj.category == "event":
                a = obj.attributes if isinstance(obj.attributes, dict) else {}
                if a.get("subtype"):
                    meta["subtype"] = a.get("subtype")
            pre_emb = getattr(obj, "_precomputed_emb", None)
            if pre_emb:
                docs_with_emb.append(doc)
                ids_with_emb.append(id_)
                metas_with_emb.append(meta)
                embs_with_emb.append(pre_emb)
            else:
                docs_without.append(doc)
                ids_without.append(id_)
                metas_without.append(meta)
            imported_count += 1
        if docs_with_emb:
            for i in range(0, len(docs_with_emb), 50):
                try:
                    await add_to_kb(kb_id, docs_with_emb[i:i + 50], ids_with_emb[i:i + 50], metas_with_emb[i:i + 50], embeddings=embs_with_emb[i:i + 50])
                except Exception as e:
                    errors.append(f"向量写入失败: {str(e)}")
                    logger.warning(f"[KB续接] 向量写入失败: {str(e)}")
        if docs_without:
            for i in range(0, len(docs_without), 50):
                try:
                    await add_to_kb(kb_id, docs_without[i:i + 50], ids_without[i:i + 50], metas_without[i:i + 50])
                except Exception as e:
                    errors.append(f"向量写入失败: {str(e)}")
                    logger.warning(f"[KB续接] 向量写入失败: {str(e)}")

        try:
            rels = await _cross_volume_dedup(db, kb_id, vn, list(new_objs))
            relations_all.extend(rels)
        except Exception as e:
            errors.append(f"跨卷查重失败: {str(e)}")
            logger.warning(f"[KB续接] 跨卷查重失败: {str(e)}")

        for v in volumes:
            if v.get("volume_number") == vn:
                v["status"] = "extracted"
                break
        local_progress["current_volume"] = vn
        local_progress["extracted_volumes"].append(vn)
        local_progress["total_entries"] = imported_count
        kb.volumes = [dict(v) for v in volumes]
        kb.volume_relations = [dict(r) for r in relations_all]
        kb.import_progress = dict(local_progress)
        await db.commit()
        print(f"[KB续接] 第{vn}卷提取完成，累计 {imported_count} 条", flush=True)
        yield {
            "type": "progress", "phase": "extracting", "volume_number": vn,
            "volume_title": vol_title, "index": vi, "total": len(target_vols),
            "entries_added": len(new_objs), "chapters_extracted": len(chapters_data),
            "cumulative_entries": imported_count,
        }

    local_progress["phase"] = "relations"
    kb.volumes = [dict(v) for v in volumes]
    kb.volume_relations = [dict(r) for r in relations_all]
    kb.import_progress = dict(local_progress)
    await db.commit()
    yield {"type": "progress", "phase": "relations", "message": "正在生成卷摘要与跨卷关联..."}

    try:
        await _build_volume_relations_and_summaries(db, kb_id)
    except Exception as e:
        errors.append(f"卷摘要/关联生成失败: {str(e)}")
        logger.warning(f"[KB续接] 卷摘要/关联生成失败: {str(e)}")

    kb = await get_kb(db, kb_id)
    if kb:
        final_res = await db.execute(
            select(func.count(KnowledgeEntry.id)).where(KnowledgeEntry.kb_id == kb_id)
        )
        imported_count = final_res.scalar() or 0
        local_progress["phase"] = "completed"
        local_progress["total_entries"] = imported_count
        kb.import_status = "completed"
        kb.import_progress = dict(local_progress)
        await db.commit()

    result = {
        "type": "complete",
        "filename": filename,
        "imported_count": imported_count,
        "text_length": len(text),
        "total_volumes": len(target_vols),
        "start_volume": start_volume,
    }
    if errors:
        result["warnings"] = errors
    print(f"[KB续接] 全部完成: imported={imported_count}, errors={len(errors)}, total_volumes={len(target_vols)}", flush=True)
    yield result


async def _llm_merge_entries(old_entry: KnowledgeEntry, new_entry: KnowledgeEntry) -> str:
    prompt = f"""以下是关于同一主题《{old_entry.title}》但来自不同卷的两条知识条目，请合并为一条内容更完整、不重复的条目。

类别：{old_entry.category}
条目A（第{old_entry.volume}卷《{old_entry.volume_title or ''}》）：
{old_entry.content}

条目B（第{new_entry.volume}卷《{new_entry.volume_title or ''}》）：
{new_entry.content}

要求：
- 用平实陈述句整合两者信息，保留各自独有的细节；
- 避免排比堆叠、破折号"——"及"不是……而是……"翻转句；
- 只输出合并后的正文内容，不要标题、不要JSON、不要解释。"""
    messages = [
        {"role": "system", "content": "你是一位知识整合专家。"},
        {"role": "user", "content": prompt},
    ]
    try:
        resp = await llm_client.chat(messages, temperature=0.3, max_tokens=2048)
    except Exception:
        return ""
    return (resp or "").strip()


async def _cross_volume_dedup(
    db: AsyncSession,
    kb_id: int,
    current_vol: int,
    new_entries: list[KnowledgeEntry],
) -> list[dict]:
    relations_added: list[dict] = []

    for entry in list(new_entries):
        if entry.category in (KB_CATEGORY_CHAPTER_SUMMARY, KB_CATEGORY_VOLUME_EVENT):
            continue
        if entry.category == "character":
            continue

        doc = f"[{entry.category}] {entry.title}: {entry.content}"
        try:
            res = await query_kb(kb_id, doc, n_results=3)
        except Exception:
            continue
        docs = res.get("documents", [[]])[0] or []
        metas = res.get("metadatas", [[]])[0] or []
        dists = res.get("distances", [[]])[0] or []
        if not docs or len(dists) != len(docs):
            continue
        best_i = min(range(len(dists)), key=lambda i: dists[i])
        best_dist = dists[best_i]
        best_meta = metas[best_i] if best_i < len(metas) else {}
        best_vol = best_meta.get("volume_number")
        if best_vol is None or best_vol == current_vol:
            continue
        if best_dist <= CROSS_VOLUME_MERGE_THRESHOLD:
            old_title = best_meta.get("title", "")
            old_cat = best_meta.get("category", "")
            old_result = await db.execute(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.kb_id == kb_id,
                    KnowledgeEntry.category == old_cat,
                    KnowledgeEntry.volume == best_vol,
                )
            )
            candidates = old_result.scalars().all()
            old_entry = next((c for c in candidates if c.title == old_title), None)
            if old_entry:
                merged = await _llm_merge_entries(old_entry, entry)
                if merged:
                    old_entry.content = merged
                    old_doc = f"[{old_entry.category}] {old_entry.title}: {old_entry.content}"
                    old_meta = {
                        "category": old_entry.category,
                        "title": old_entry.title,
                        "source": old_entry.source,
                        "volume_number": old_entry.volume,
                    }
                    try:
                        await update_in_kb(
                            kb_id,
                            [f"kb_{kb_id}_entry_{old_entry.id}"],
                            [old_doc],
                            [old_meta],
                        )
                    except Exception:
                        pass
            new_vec_id = f"kb_{kb_id}_entry_{entry.id}"
            await db.delete(entry)
            try:
                await delete_from_kb(kb_id, [new_vec_id])
            except Exception:
                pass
            if entry in new_entries:
                new_entries.remove(entry)
        else:
            if (best_meta.get("title", "") or "").lower() == (entry.title or "").lower():
                relations_added.append({
                    "from_volume": best_vol,
                    "to_volume": current_vol,
                    "description": f"同名条目《{entry.title}》跨卷出现",
                    "title": entry.title,
                })
    return relations_added


async def _build_volume_relations_and_summaries(db: AsyncSession, kb_id: int) -> None:
    kb = await get_kb(db, kb_id)
    if not kb:
        print(f"[KB-REL] _build_volume_relations_and_summaries: kb_id={kb_id} not found")
        return
    result = await db.execute(
        select(KnowledgeEntry)
        .where(KnowledgeEntry.kb_id == kb_id)
        .order_by(KnowledgeEntry.volume, KnowledgeEntry.category)
    )
    entries = result.scalars().all()
    by_vol: dict[int, list[KnowledgeEntry]] = {}
    for e in entries:
        v = e.volume if e.volume is not None else 0
        by_vol.setdefault(v, []).append(e)
    vol_titles = {
        v.get("volume_number"): v.get("title", "")
        for v in (kb.volumes or [])
        if isinstance(v, dict)
    }

    vol_blocks = []
    for v in sorted(by_vol.keys()):
        el = by_vol[v]
        title = vol_titles.get(v, f"第{v}卷") if v else "通用知识"
        lines = [f"- [{e.category}] {e.title}：{(e.content or '')[:120]}" for e in el[:30]]
        vol_blocks.append(f"第{v}卷《{title}》（{len(el)}条）：\n" + "\n".join(lines))

    if not vol_blocks:
        print(f"[KB-REL] kb_id={kb_id}: no vol_blocks (entries empty?), aborting")
        return

    print(f"[KB-REL] kb_id={kb_id}: entries={len(entries)}, volumes={len(by_vol)}, vol_blocks={len(vol_blocks)}, calling LLM...")
    prompt = f"""以下是各卷已提取知识条目的概览。请输出两部分：
1. 每卷一句话摘要（概括该卷核心设定/人物/事件走向）；
2. 卷与卷之间的关联（如同一人物跨卷成长、伏笔跨卷回收、势力跨卷变化等）。

{chr(10).join(vol_blocks)}

输出严格JSON：
{{
  "summaries": [{{"volume_number": 1, "summary": "该卷摘要"}}],
  "relations": [{{"from_volume": 1, "to_volume": 2, "description": "关联描述"}}]
}}
只输出JSON，不要输出其他内容。"""
    messages = [
        {"role": "system", "content": "你是一位小说结构分析专家。"},
        {"role": "user", "content": prompt},
    ]
    try:
        resp = await llm_client.chat(messages, temperature=0.3, max_tokens=3000)
    except Exception as e:
        print(f"[KB-REL] kb_id={kb_id}: LLM调用失败: {e}")
        return
    print(f"[KB-REL] kb_id={kb_id}: LLM响应长度={len(resp or '')}")
    clean = (resp or "").strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        if len(lines) >= 2:
            clean = "\n".join(lines[1:])
            if clean.rstrip().endswith("```"):
                clean = clean.rstrip()[:-3]
    try:
        data = json.loads(clean)
    except Exception as e:
        print(f"[KB-REL] kb_id={kb_id}: JSON解析失败: {e}, resp_preview={clean[:300]}")
        return
    if not isinstance(data, dict):
        print(f"[KB-REL] kb_id={kb_id}: LLM返回非dict: {type(data)}")
        return
    summaries = data.get("summaries", []) or []
    relations = data.get("relations", []) or []
    print(f"[KB-REL] kb_id={kb_id}: 解析成功 summaries={len(summaries)}, relations={len(relations)}")

    volumes = kb.volumes or []
    sum_map: dict = {}
    for s in summaries:
        if isinstance(s, dict):
            sum_map[s.get("volume_number")] = s.get("summary", "")
    updated = 0
    for v in volumes:
        if isinstance(v, dict):
            vn = v.get("volume_number")
            if vn in sum_map:
                v["summary"] = sum_map[vn]
                updated += 1
    kb.volumes = [dict(v) for v in volumes]
    print(f"[KB-REL] kb_id={kb_id}: 写入卷摘要 updated={updated}/{len(volumes)} volumes")

    existing_rels = list(kb.volume_relations or [])
    prev_rel_count = len(existing_rels)
    seen = {
        (r.get("from_volume"), r.get("to_volume"), r.get("description"))
        for r in existing_rels
        if isinstance(r, dict)
    }
    for r in relations:
        if isinstance(r, dict):
            key = (r.get("from_volume"), r.get("to_volume"), r.get("description"))
            if key not in seen:
                seen.add(key)
                existing_rels.append(r)
    kb.volume_relations = [dict(r) for r in existing_rels]
    print(f"[KB-REL] kb_id={kb_id}: 跨卷关联 new={len(existing_rels) - prev_rel_count}, total={len(existing_rels)}")
    await db.commit()


async def import_file_to_kb_stream(
    db: AsyncSession,
    kb_id: int,
    file_content: bytes,
    filename: str,
):
    kb = await get_kb(db, kb_id)
    if not kb:
        yield {"type": "error", "error": "知识库不存在", "filename": filename}
        return
    if kb.import_status == "completed":
        yield {
            "type": "complete",
            "skipped": True,
            "filename": filename,
            "imported_count": 0,
            "message": "知识库已提取完成，跳过。如需重新提取，请先清空知识库条目。",
        }
        return

    existing = await list_entries(db, kb_id)
    if existing and not (kb.volumes or []):
        yield {
            "type": "error",
            "error": "知识库已有旧版结构化知识，跳过提取。如需重新提取，请先清空知识库条目。",
            "filename": filename,
        }
        return

    text = await extract_text_from_file(file_content, filename)
    print(f"[KB导入] 文件解析完成: {filename}, 文本长度={len(text)}", flush=True)
    if not text.strip():
        yield {"type": "error", "error": "文档内容为空", "filename": filename}
        return

    detected = detect_volumes(text)
    prev_volumes = {
        v.get("volume_number"): v
        for v in (kb.volumes or [])
        if isinstance(v, dict)
    }
    volumes = []
    for d in detected:
        vn = d["volume_number"]
        pv = prev_volumes.get(vn, {})
        volumes.append({
            "volume_number": vn,
            "title": d["title"],
            "char_range": d["char_range"],
            "source": d["source"],
            "status": pv.get("status", "pending"),
            "summary": pv.get("summary", ""),
        })
    kb.volumes = [dict(v) for v in volumes]
    kb.import_status = "running"
    local_progress = {
        "phase": "extracting",
        "current_volume": 0,
        "total_volumes": len(volumes),
        "extracted_volumes": [],
        "total_entries": 0,
    }
    kb.import_progress = dict(local_progress)
    await db.commit()

    yield {
        "type": "start",
        "filename": filename,
        "text_length": len(text),
        "total_volumes": len(volumes),
        "volumes": [{"volume_number": v["volume_number"], "title": v["title"], "source": v["source"]} for v in volumes],
    }

    imported_count = 0
    errors: list[str] = []
    relations_all = list(kb.volume_relations or [])

    cached_embs: list = []
    emb_lock = asyncio.Lock()
    keep_volumes = {vol["volume_number"] for vol in volumes if vol.get("status") == "extracted"}
    try:
        coll = chroma_client.get_or_create_collection(get_kb_collection_name(kb_id))
        existing = coll.get(where={"category": "worldview"}, include=["embeddings", "metadatas"])
        cached_embs = [
            (m.get("title", ""), e.tolist() if hasattr(e, "tolist") else e)
            for m, e in zip(existing.get("metadatas", []), existing.get("embeddings", []))
            if m.get("volume_number") in keep_volumes
        ]
    except Exception:
        pass

    for vi, vol in enumerate(volumes):
        vn = vol["volume_number"]
        if vol["status"] == "extracted":
            cnt_res = await db.execute(
                select(func.count(KnowledgeEntry.id)).where(
                    KnowledgeEntry.kb_id == kb_id,
                    KnowledgeEntry.volume == vn,
                )
            )
            imported_count += cnt_res.scalar() or 0
            yield {
                "type": "progress",
                "phase": "extracting",
                "volume_number": vn,
                "volume_title": vol["title"],
                "index": vi,
                "total": len(volumes),
                "skipped": True,
                "cumulative_entries": imported_count,
            }
            continue

        await _reset_volume(db, kb_id, vn)
        vstart, vend = vol["char_range"]
        vtext = text[vstart:vend]
        if not vtext.strip():
            vol["status"] = "extracted"
            continue

        print(f"[KB导入] 开始提取第{vn}卷《{vol['title']}》(索引{vi}/{len(volumes)})", flush=True)
        chapters_data = await _extract_chapter_summaries_batch(vtext, vn, vol["title"])

        existing_aliases = await _load_existing_character_aliases(db, kb_id, vn)
        norm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
        canonical_map = await _normalize_character_names(
            chapters_data, vn, vol["title"], existing_aliases, norm_semaphore
        )

        new_objs: list[KnowledgeEntry] = []
        for ch in chapters_data:
            if not (ch.get("summary") or "").strip():
                continue
            ch_obj = KnowledgeEntry(
                kb_id=kb_id,
                category=KB_CATEGORY_CHAPTER_SUMMARY,
                title=f"第{ch['chapter_number']}章《{ch['chapter_title']}》摘要",
                content=ch["summary"],
                attributes={"characters": ch.get("characters", []), "key_events": ch.get("key_events", [])},
                source="upload",
                volume=vn,
                volume_title=vol["title"],
                chapter_number=ch["chapter_number"],
                chapter_title=ch["chapter_title"],
            )
            db.add(ch_obj)
            new_objs.append(ch_obj)
        vol["chapters"] = [
            {"chapter_number": ch.get("chapter_number", 1), "chapter_title": ch.get("chapter_title", "")}
            for ch in chapters_data
        ]

        vol_event_text = await _extract_volume_event_summary(chapters_data, vn, vol["title"])
        if vol_event_text:
            ve_obj = KnowledgeEntry(
                kb_id=kb_id,
                category=KB_CATEGORY_VOLUME_EVENT,
                title=f"第{vn}卷《{vol['title']}》主要事件总结",
                content=vol_event_text,
                attributes={},
                source="upload",
                volume=vn,
                volume_title=vol["title"],
            )
            db.add(ve_obj)
            new_objs.append(ve_obj)

        derived = await _derive_volume_all(chapters_data, vn, vol["title"], cached_embs, emb_lock, canonical_map)
        for category, items in derived.items():
            for it in items:
                title = (it.get("name", "") or "").strip()
                content = (it.get("content", "") or "").strip()
                if not title and not content:
                    continue
                attrs: dict = {}
                if category == "character":
                    aliases = it.get("aliases")
                    if isinstance(aliases, list) and aliases:
                        attrs["aliases"] = [str(a) for a in aliases]
                if category == "event":
                    chars = it.get("characters")
                    attrs["characters"] = [str(c) for c in chars] if isinstance(chars, list) else []
                    subtype = it.get("subtype")
                    if subtype:
                        attrs["subtype"] = subtype
                obj = KnowledgeEntry(
                    kb_id=kb_id,
                    category=category,
                    title=title,
                    content=content,
                    attributes=attrs,
                    source="upload",
                    volume=vn,
                    volume_title=vol["title"],
                )
                pre_emb = it.get("_emb")
                if pre_emb:
                    obj._precomputed_emb = pre_emb
                db.add(obj)
                new_objs.append(obj)
        await db.flush()

        docs_with_emb: list[str] = []
        ids_with_emb: list[str] = []
        metas_with_emb: list[dict] = []
        embs_with_emb: list[list[float]] = []
        docs_without: list[str] = []
        ids_without: list[str] = []
        metas_without: list[dict] = []
        for obj in new_objs:
            doc = f"[{obj.category}] {obj.title}: {obj.content}"
            id_ = f"kb_{kb_id}_entry_{obj.id}"
            meta = {"category": obj.category, "title": obj.title, "source": "upload", "volume_number": vn}
            if obj.chapter_number is not None:
                meta["chapter_number"] = obj.chapter_number
            if obj.category == "event":
                attrs = obj.attributes if isinstance(obj.attributes, dict) else {}
                if attrs.get("subtype"):
                    meta["subtype"] = attrs.get("subtype")
            pre_emb = getattr(obj, "_precomputed_emb", None)
            if pre_emb:
                docs_with_emb.append(doc)
                ids_with_emb.append(id_)
                metas_with_emb.append(meta)
                embs_with_emb.append(pre_emb)
            else:
                docs_without.append(doc)
                ids_without.append(id_)
                metas_without.append(meta)
            imported_count += 1
        if docs_with_emb:
            for i in range(0, len(docs_with_emb), 50):
                try:
                    await add_to_kb(kb_id, docs_with_emb[i:i + 50], ids_with_emb[i:i + 50], metas_with_emb[i:i + 50], embeddings=embs_with_emb[i:i + 50])
                except Exception as e:
                    errors.append(f"向量写入失败: {str(e)}")
                    logger.warning(f"[KB导入] 向量写入失败: {str(e)}")
        if docs_without:
            for i in range(0, len(docs_without), 50):
                try:
                    await add_to_kb(kb_id, docs_without[i:i + 50], ids_without[i:i + 50], metas_without[i:i + 50])
                except Exception as e:
                    errors.append(f"向量写入失败: {str(e)}")
                    logger.warning(f"[KB导入] 向量写入失败: {str(e)}")

        try:
            rels = await _cross_volume_dedup(db, kb_id, vn, list(new_objs))
            relations_all.extend(rels)
        except Exception as e:
            errors.append(f"跨卷查重失败: {str(e)}")
            logger.warning(f"[KB导入] 跨卷查重失败: {str(e)}")

        vol["status"] = "extracted"
        local_progress["current_volume"] = vn
        local_progress["extracted_volumes"].append(vn)
        local_progress["total_entries"] = imported_count
        kb.volumes = [dict(v) for v in volumes]
        kb.volume_relations = [dict(r) for r in relations_all]
        kb.import_progress = dict(local_progress)
        await db.commit()
        print(f"[KB导入] 第{vn}卷提取完成，累计 {imported_count} 条", flush=True)
        yield {
            "type": "progress",
            "phase": "extracting",
            "volume_number": vn,
            "volume_title": vol["title"],
            "index": vi,
            "total": len(volumes),
            "entries_added": len(new_objs),
            "chapters_extracted": len(chapters_data),
            "cumulative_entries": imported_count,
        }

    local_progress["phase"] = "relations"
    kb.volumes = [dict(v) for v in volumes]
    kb.volume_relations = [dict(r) for r in relations_all]
    kb.import_progress = dict(local_progress)
    await db.commit()
    yield {"type": "progress", "phase": "relations", "message": "正在生成卷摘要与跨卷关联..."}

    try:
        await _build_volume_relations_and_summaries(db, kb_id)
    except Exception as e:
        errors.append(f"卷摘要/关联生成失败: {str(e)}")
        logger.warning(f"[KB导入] 卷摘要/关联生成失败: {str(e)}")

    kb = await get_kb(db, kb_id)
    if kb:
        final_count_res = await db.execute(
            select(func.count(KnowledgeEntry.id)).where(KnowledgeEntry.kb_id == kb_id)
        )
        imported_count = final_count_res.scalar() or 0
        local_progress["phase"] = "completed"
        local_progress["total_entries"] = imported_count
        kb.import_status = "completed"
        kb.import_progress = dict(local_progress)
        await db.commit()

    result = {
        "type": "complete",
        "filename": filename,
        "imported_count": imported_count,
        "text_length": len(text),
        "total_volumes": len(volumes),
    }
    if errors:
        result["warnings"] = errors
    print(f"[KB导入] 全部完成: imported={imported_count}, errors={len(errors)}, total_volumes={len(volumes)}", flush=True)
    yield result


async def import_file_to_kb(
    db: AsyncSession,
    kb_id: int,
    file_content: bytes,
    filename: str,
) -> dict:
    final = {"filename": filename, "imported_count": 0, "text_length": 0, "total_volumes": 0}
    async for evt in import_file_to_kb_stream(db, kb_id, file_content, filename):
        if evt.get("type") in ("complete", "error"):
            final = evt
    return final


async def bulk_add_entries(db: AsyncSession, kb_id: int, entries: list[dict]) -> dict:
    added_count = 0
    for item in entries:
        entry = await add_entry(
            db,
            kb_id=kb_id,
            category=item.get("category", "other"),
            title=item.get("title", ""),
            content=item.get("content", ""),
            attributes=item.get("attributes"),
            source="ai_search",
            volume=item.get("volume"),
            volume_title=item.get("volume_title"),
        )
        if entry:
            added_count += 1
    return {"added_count": added_count, "kb_id": kb_id}
