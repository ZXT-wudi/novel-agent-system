import json
import asyncio
import logging
import os
from typing import AsyncGenerator
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from app.llm.siliconflow import LLMError, get_client
from app.services.document_parser import extract_text_from_file
from app.models.ordinary_knowledge_base import OrdinaryKnowledgeBase, OrdinaryKnowledgeEntry

logger = logging.getLogger(__name__)
llm_client = get_client("common")

ORDINARY_DIMENSIONS = {
    "theme": {
        "name": "主题的挖掘与立意",
        "guidance": "作者如何将宏大命题（自由、爱、死亡、正义）落地到具体故事情境而不流于说教；核心冲突是什么；主题通过哪些情节和人物选择自然浮现",
    },
    "character_arc": {
        "name": "人物弧光",
        "guidance": "人物是否有清晰的动机、缺陷、恐惧与渴望；在故事压力下是否发生内在改变（正/负/平向弧光）；主角开头到结尾的价值观变化；配角是否有影子功能",
    },
    "plot_structure": {
        "name": "情节结构与节奏控制",
        "guidance": "三幕剧/英雄之旅结构、悬念设置、伏笔回收、信息差运用、张弛节奏；转折点、留白、加速/放缓位置",
    },
    "narrative_pov": {
        "name": "叙事视角与叙述声音",
        "guidance": "谁在讲故事、怎么讲；第一人称代入感、第三人称有限聚焦、全知视角、不可靠叙述者的运用与效果得失",
    },
    "language_style": {
        "name": "语言风格与细节描写",
        "guidance": "对话是否符合人物身份且推动剧情；描写繁复还是留白；比喻是否新颖准确；句式节奏是否匹配场景情绪；须摘原句分析用词句式感官调动",
    },
    "worldbuilding": {
        "name": "世界观与规则自洽",
        "guidance": "世界运行的物理规则、社会结构、文化习俗是否自洽；设定是否服务主题和人物而非炫技；作者如何展示而非讲述世界观",
    },
    "emotional_resonance": {
        "name": "情感共鸣与余味",
        "guidance": "如何触发读者共情；悲剧净化、喜剧释然、开放式结局引发的长久思索；结尾是情感宣泄后戛然而止还是留白式余音绕梁",
    },
}

DIM_KEYS = list(ORDINARY_DIMENSIONS.keys())

MAX_CONCURRENT = 6
CHUNK_TARGET = 9000
CHUNK_OVERLAP = 400
REDUCE_BATCH = 20
MAX_RETRIES = 3
MAX_MERGE_INPUT_CHARS = 80000


ORDINARY_EXTRACTION_PROMPT = """你是一位资深文学编辑，正在分析一部小说的写作技法。以下是小说的一个片段（约{chunk_len}字），请从中提取可借鉴的写作技法。

请从以下7个维度分析，每个维度输出200-300字的具体、可借鉴的写法分析（指出具体怎么写的、好在哪里、可借鉴什么，不要空泛评价）：

1. theme（主题的挖掘与立意）：作者如何将宏大命题落地到具体故事情境而不流于说教；核心冲突；主题通过哪些情节/人物选择浮现
2. character_arc（人物弧光）：动机/缺陷/恐惧/渴望是否清晰；压力下是否发生内在改变；主角开头到结尾价值观变化；配角影子功能
3. plot_structure（情节结构与节奏控制）：转折点、留白、加速/放缓位置；悬念/伏笔/信息差运用；张弛节奏
4. narrative_pov（叙事视角与叙述声音）：谁在讲故事/怎么讲；视角选择的效果与代价
5. language_style（语言风格与细节描写）：对话是否符合人物身份且推动剧情；描写繁复还是留白；比喻新颖准确度；句式节奏是否匹配情绪（须摘原句分析）
6. worldbuilding（世界观与规则自洽）：规则/社会结构/习俗是否自洽；设定是否服务主题而非炫技；如何展示而非讲述
7. emotional_resonance（情感共鸣与余味）：如何触发共情；悲剧净化/喜剧释然/开放式结局；结尾处理

如果该片段不涉及某维度，输出该维度能观察到的相关写法或简述"本片段未明显体现"。

严格只输出JSON（不要markdown代码块，不要其他文字）：
{{"theme":"","character_arc":"","plot_structure":"","narrative_pov":"","language_style":"","worldbuilding":"","emotional_resonance":""}}

小说片段：
{chunk_text}"""


ORDINARY_MERGE_PROMPT = """你是一位资深文学编辑，正在将多段小说片段的技法分析合并为一份综合分析。

以下是{count}段片段各自的7维度技法分析（JSON）。请将它们合并、去重、提炼成一份更精炼的7维度综合分析，每个维度200-400字。合并时保留最有价值的具体写法，去掉重复，综合不同片段的观察。

严格只输出JSON（不要markdown代码块，不要其他文字）：
{{"theme":"","character_arc":"","plot_structure":"","narrative_pov":"","language_style":"","worldbuilding":"","emotional_resonance":""}}

以下是{count}段片段的分析：
{analyses_json}"""


def _decode_text_robust(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
        if "\ufffd" not in text:
            return text
    except (UnicodeDecodeError, LookupError):
        pass

    try:
        text = raw.decode("utf-8")
        if "\ufffd" not in text:
            return text
    except (UnicodeDecodeError, LookupError):
        pass

    try:
        from charset_normalizer import from_bytes
        sample = raw[:50000] if len(raw) > 50000 else raw
        result = from_bytes(sample).best()
        if result and result.encoding:
            try:
                text = raw.decode(result.encoding)
                if "\ufffd" not in text:
                    return text
            except (UnicodeDecodeError, LookupError):
                pass
    except Exception:
        pass

    try:
        return raw.decode("gb18030")
    except (UnicodeDecodeError, LookupError):
        pass

    try:
        return raw.decode("big5")
    except (UnicodeDecodeError, LookupError):
        pass

    try:
        return raw.decode("utf-16")
    except (UnicodeDecodeError, LookupError):
        pass

    return raw.decode("utf-8", errors="ignore")


async def _decode_file(filename: str, raw: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".docx", ".pdf"):
        return await extract_text_from_file(raw, filename)
    return _decode_text_robust(raw)


def _split_into_chunks(text: str, target: int = CHUNK_TARGET, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text or not text.strip():
        return []
    if len(text) <= target:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + target
        if end >= len(text):
            chunks.append(text[start:])
            break

        search_start = max(start + 1, end - 500)
        boundary = -1
        for marker in ["\n\n", "\n", "。", "！", "？", "…", "；", ";", "，", "、", " ", "　"]:
            pos = text.rfind(marker, search_start, end)
            if pos > boundary:
                boundary = pos + len(marker)

        if boundary > search_start:
            end = boundary

        chunks.append(text[start:end])

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return [c for c in chunks if c.strip()]


def _extract_json_from_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return {}


async def _call_llm(messages: list[dict], temperature: float, max_tokens: int) -> str:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return await llm_client.chat(messages, temperature=temperature, max_tokens=max_tokens)
        except (LLMError, Exception) as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
    raise last_err


def _adjust_batch_size(analyses: list[dict]) -> int:
    if not analyses:
        return REDUCE_BATCH
    total = sum(len(json.dumps({k: a.get(k, "") for k in DIM_KEYS}, ensure_ascii=False)) for a in analyses)
    avg = total / len(analyses)
    if avg > 0:
        batch = int(MAX_MERGE_INPUT_CHARS / avg)
        return max(5, min(REDUCE_BATCH, batch))
    return REDUCE_BATCH


async def extract_ordinary_kb_stream(
    db: AsyncSession, base_id: int, file_content: bytes, filename: str
) -> AsyncGenerator[dict, None]:
    kb = await db.get(OrdinaryKnowledgeBase, base_id)
    if not kb:
        yield {"type": "error", "message": "普通知识库不存在"}
        return

    try:
        text = await _decode_file(filename, file_content)
    except Exception as e:
        yield {"type": "error", "message": f"文件解析失败: {e}"}
        return

    if not text or not text.strip():
        yield {"type": "error", "message": "文件内容为空"}
        return

    chunks = _split_into_chunks(text)
    total_chunks = len(chunks)

    if total_chunks == 0:
        yield {"type": "error", "message": "分块后无有效内容"}
        return

    progress = kb.import_progress or {}
    done_set = set(progress.get("done_chunks", []))
    existing_analyses = list(progress.get("chunk_analyses", []))
    failed_list = list(progress.get("failed", []))

    is_resume = bool(done_set) and kb.import_status in ("processing", "partial")

    if not is_resume:
        progress = {
            "total_chunks": total_chunks,
            "done_chunks": [],
            "chunk_analyses": [],
            "level": "map",
            "status": "processing",
            "failed": [],
        }
        done_set = set()
        existing_analyses = []
        failed_list = []

    progress["total_chunks"] = total_chunks
    progress["status"] = "processing"
    progress["level"] = "map"
    kb.import_status = "processing"
    kb.import_progress = progress
    flag_modified(kb, "import_progress")
    await db.commit()

    yield {"type": "start", "total_chunks": total_chunks, "resume": is_resume, "failed_prev": failed_list}

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def extract_one_chunk(idx: int, chunk: str) -> tuple[int, dict | None]:
        async with sem:
            prompt = ORDINARY_EXTRACTION_PROMPT.format(
                chunk_len=len(chunk),
                chunk_text=chunk,
            )
            messages = [{"role": "user", "content": prompt}]
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await llm_client.chat(messages, temperature=0.4, max_tokens=4096)
                    parsed = _extract_json_from_response(resp)
                    if parsed and any(parsed.get(k) for k in DIM_KEYS):
                        return idx, {k: str(parsed.get(k, "")) for k in DIM_KEYS}
                except Exception as e:
                    logger.warning("普通KB提取 块%d 第%d次失败: %s", idx, attempt + 1, e)
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(2 * (attempt + 1))
            return idx, None

    pending = [(i, chunks[i]) for i in range(total_chunks) if i not in done_set]

    if pending:
        tasks = [extract_one_chunk(idx, chunk) for idx, chunk in pending]
        for coro in asyncio.as_completed(tasks):
            idx, result = await coro
            if result:
                existing_analyses = [a for a in existing_analyses if a.get("idx") != idx]
                existing_analyses.append({"idx": idx, **result})
                done_set.add(idx)
                if idx in failed_list:
                    failed_list.remove(idx)
            else:
                if idx not in failed_list:
                    failed_list.append(idx)

            progress["done_chunks"] = sorted(done_set)
            progress["chunk_analyses"] = existing_analyses
            progress["failed"] = failed_list
            kb.import_progress = progress
            flag_modified(kb, "import_progress")
            await db.commit()

            done = len(done_set)
            pct = round(done / total_chunks * 100, 1) if total_chunks > 0 else 100
            yield {"type": "progress", "done": done, "total": total_chunks, "level": "map", "percent": pct}

    progress["level"] = "reduce"
    kb.import_progress = progress
    flag_modified(kb, "import_progress")
    await db.commit()

    analyses = [a for a in existing_analyses if any(a.get(k) for k in DIM_KEYS)]

    if not analyses:
        kb.import_status = "partial"
        progress["status"] = "partial"
        kb.import_progress = progress
        flag_modified(kb, "import_progress")
        await db.commit()
        yield {"type": "error", "message": "所有块提取失败，无可用分析内容", "failed_chunks": failed_list}
        return

    total_reduce_steps = 0
    current = analyses
    while len(current) > 1:
        total_reduce_steps += (len(current) + _adjust_batch_size(current) - 1) // _adjust_batch_size(current)
        current = [current[i:i + _adjust_batch_size(current)] for i in range(0, len(current), _adjust_batch_size(current))]
        current = [item for batch in current for item in batch]
        break

    current = analyses
    reduce_done = 0
    while len(current) > 1:
        batch_size = _adjust_batch_size(current)
        batches = [current[i:i + batch_size] for i in range(0, len(current), batch_size)]
        next_level = []
        for batch in batches:
            analyses_json = json.dumps(
                [{k: a.get(k, "") for k in DIM_KEYS} for a in batch],
                ensure_ascii=False,
            )
            prompt = ORDINARY_MERGE_PROMPT.format(count=len(batch), analyses_json=analyses_json)
            messages = [{"role": "user", "content": prompt}]
            try:
                resp = await llm_client.chat(messages, temperature=0.3, max_tokens=4096)
                parsed = _extract_json_from_response(resp)
                if parsed and any(parsed.get(k) for k in DIM_KEYS):
                    next_level.append({k: str(parsed.get(k, "")) for k in DIM_KEYS})
                else:
                    next_level.append({k: batch[0].get(k, "") for k in DIM_KEYS})
            except Exception as e:
                logger.warning("普通KB合并批失败: %s", e)
                next_level.append({k: batch[0].get(k, "") for k in DIM_KEYS})

            reduce_done += 1
            total_estimate = total_reduce_steps if total_reduce_steps > 0 else len(batches)
            pct = round(50 + reduce_done / max(total_estimate, 1) * 45, 1)
            yield {"type": "progress", "done": reduce_done, "total": max(total_estimate, 1), "level": "reduce", "percent": min(pct, 95)}

        current = next_level

    final_dims = {k: current[0].get(k, "") for k in DIM_KEYS}

    await db.execute(delete(OrdinaryKnowledgeEntry).where(OrdinaryKnowledgeEntry.base_id == base_id))
    for key, info in ORDINARY_DIMENSIONS.items():
        entry = OrdinaryKnowledgeEntry(
            base_id=base_id,
            dimension=key,
            content=final_dims.get(key, ""),
            attributes={"name": info["name"]},
        )
        db.add(entry)

    has_failed = len(failed_list) > 0
    kb.import_status = "partial" if has_failed else "completed"
    progress["status"] = kb.import_status
    progress["level"] = "done"
    kb.import_progress = progress
    flag_modified(kb, "import_progress")
    await db.commit()

    yield {
        "type": "complete",
        "dimensions": {
            k: {"name": ORDINARY_DIMENSIONS[k]["name"], "content": final_dims.get(k, "")}
            for k in DIM_KEYS
        },
        "failed_chunks": failed_list,
    }


async def build_ordinary_kb_context(db: AsyncSession, base_id: int) -> str:
    if not base_id:
        return ""

    result = await db.execute(
        select(OrdinaryKnowledgeEntry)
        .where(OrdinaryKnowledgeEntry.base_id == base_id)
        .order_by(OrdinaryKnowledgeEntry.id)
    )
    entries = result.scalars().all()

    if not entries:
        return ""

    parts = []
    for entry in entries:
        dim_name = (entry.attributes or {}).get("name") or entry.dimension
        content = entry.content or ""
        if content.strip():
            parts.append(f"【{dim_name}】\n{content}")

    return "\n\n".join(parts)


async def get_ordinary_kb(db: AsyncSession, base_id: int) -> OrdinaryKnowledgeBase | None:
    return await db.get(OrdinaryKnowledgeBase, base_id)


async def create_ordinary_kb(db: AsyncSession, name: str, genre: str, source_work: str = "", description: str = "") -> OrdinaryKnowledgeBase:
    kb = OrdinaryKnowledgeBase(
        name=name,
        genre=genre,
        source_work=source_work,
        description=description,
        import_status="idle",
        import_progress={},
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def update_ordinary_kb(db: AsyncSession, base_id: int, **kwargs) -> OrdinaryKnowledgeBase | None:
    kb = await db.get(OrdinaryKnowledgeBase, base_id)
    if not kb:
        return None
    for k, v in kwargs.items():
        if v is not None and hasattr(kb, k):
            setattr(kb, k, v)
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_ordinary_kb(db: AsyncSession, base_id: int) -> bool:
    kb = await db.get(OrdinaryKnowledgeBase, base_id)
    if not kb:
        return False
    from app.models.novel import Novel
    novels_to_unbind = await db.execute(
        select(Novel).where(Novel.ordinary_knowledge_base_id == base_id)
    )
    for novel in novels_to_unbind.scalars().all():
        novel.ordinary_knowledge_base_id = None
    await db.delete(kb)
    await db.commit()
    return True


async def list_ordinary_kbs(db: AsyncSession, genre: str = None) -> list[dict]:
    stmt = select(OrdinaryKnowledgeBase).order_by(OrdinaryKnowledgeBase.created_at.desc())
    if genre:
        stmt = stmt.where(OrdinaryKnowledgeBase.genre == genre)
    result = await db.execute(stmt)
    kbs = result.scalars().all()

    entries_count_stmt = (
        select(OrdinaryKnowledgeEntry.base_id, func.count(OrdinaryKnowledgeEntry.id))
        .group_by(OrdinaryKnowledgeEntry.base_id)
    )
    count_result = await db.execute(entries_count_stmt)
    count_map = {row[0]: row[1] for row in count_result.all()}

    return [
        {
            "id": kb.id,
            "name": kb.name,
            "genre": kb.genre,
            "source_work": kb.source_work,
            "description": kb.description,
            "import_status": kb.import_status,
            "import_progress": kb.import_progress or {},
            "entry_count": count_map.get(kb.id, 0),
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
            "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
        }
        for kb in kbs
    ]


async def get_ordinary_kb_detail(db: AsyncSession, base_id: int) -> dict | None:
    kb = await db.get(OrdinaryKnowledgeBase, base_id)
    if not kb:
        return None
    result = await db.execute(
        select(OrdinaryKnowledgeEntry)
        .where(OrdinaryKnowledgeEntry.base_id == base_id)
        .order_by(OrdinaryKnowledgeEntry.id)
    )
    entries = result.scalars().all()
    return {
        "id": kb.id,
        "name": kb.name,
        "genre": kb.genre,
        "source_work": kb.source_work,
        "description": kb.description,
        "import_status": kb.import_status,
        "import_progress": kb.import_progress or {},
        "entries": [
            {
                "id": e.id,
                "dimension": e.dimension,
                "dimension_name": (e.attributes or {}).get("name", e.dimension),
                "content": e.content,
                "attributes": e.attributes or {},
            }
            for e in entries
        ],
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
    }
