from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.chapter import Chapter, ChapterVersion
from app.models.chapter_semantic import ChapterSemantic
from app.models.novel import Novel
from app.models.user_preference import ModificationRecord
from app.agents.state import NovelState
from app.agents.graph import load_context, review_parallel, auto_revise
from app.agents.writer_agent import write_chapter, write_chapter_stream, evaluate_reviews
from app.agents.character_agent import curate_character_psychology
from app.rag.retriever import query_collection, filter_by_distance
from app.services.kb_service import build_kb_context_for_agent
from app.services.volume_splitter import volumes_for_chapter_range, resolve_source_volumes
from app.llm.siliconflow import llm_client, LLMError
from app.config import settings
import json
import logging

logger = logging.getLogger(__name__)


async def _build_chapter_state(db: AsyncSession, novel_id: int, chapter_number: int) -> NovelState:
    novel = await db.get(Novel, novel_id)
    if not novel:
        return {}

    previous_full = []
    result = await db.execute(
        select(Chapter)
        .where(Chapter.novel_id == novel_id, Chapter.status == "final")
        .order_by(Chapter.chapter_number.desc())
        .limit(settings.PREVIOUS_CHAPTERS_FULL_COUNT)
    )
    prev_chapters = result.scalars().all()
    for ch in reversed(prev_chapters):
        previous_full.append(ch.content)

    previous_semantics = []
    if chapter_number > settings.PREVIOUS_CHAPTERS_FULL_COUNT:
        sem_result = await db.execute(
            select(ChapterSemantic)
            .where(ChapterSemantic.novel_id == novel_id, ChapterSemantic.chapter_number < chapter_number - settings.PREVIOUS_CHAPTERS_FULL_COUNT)
            .order_by(ChapterSemantic.chapter_number.desc())
            .limit(10)
        )
        sem_rows = sem_result.scalars().all()
        for sem in reversed(sem_rows):
            previous_semantics.append({
                "chapter_number": sem.chapter_number,
                "summary": sem.summary,
                "keywords": sem.keywords or [],
                "characters_involved": sem.characters_involved or [],
            })

    outline_item = novel.outline or []
    query_text = ""
    for item in outline_item:
        if item.get("chapter_number") == chapter_number:
            query_text = " ".join(filter(None, [
                item.get("plot_summary", ""),
                " ".join(item.get("key_events", [])),
                item.get("location", ""),
                item.get("conflict", ""),
                item.get("chapter_hook", ""),
            ]))
            break

    rag_context = ""
    if query_text:
        sem_results = await query_collection(novel_id, "chapter_semantics", query_text, n_results=3)
        sem_docs = filter_by_distance(sem_results)
        knowledge_results = await query_collection(novel_id, "world_knowledge", query_text, n_results=3)
        knowledge_docs = filter_by_distance(knowledge_results)
        pref_results = await query_collection(novel_id, "user_preferences", query_text, n_results=3)
        pref_docs = filter_by_distance(pref_results)
        parts = []
        if sem_docs:
            parts.append("相关前文语义：\n" + "\n".join(sem_docs))
        if knowledge_docs:
            parts.append("世界观参考：\n" + "\n".join(knowledge_docs))
        if pref_docs:
            parts.append("用户偏好参考：\n" + "\n".join(pref_docs))
        rag_context = "\n\n".join(parts)

    kb_context = ""
    if novel.knowledge_base_id:
        try:
            fanwork_vol_nums = volumes_for_chapter_range(novel.full_outline or {}, chapter_number, chapter_number)
            source_volumes = resolve_source_volumes(novel.full_outline or {}, fanwork_vol_nums) if novel.full_outline else None
            if source_volumes is not None:
                logger.debug("[CH-WRITE] 章节写作(有源卷映射): novel_id=%s, ch=%s, fanfic_volumes=%s -> source_kb_volumes=%s",
                             novel_id, chapter_number, fanwork_vol_nums, source_volumes)
                kb_context = await build_kb_context_for_agent(db, novel.knowledge_base_id, query_text, comprehensive=True, volume_numbers=source_volumes, chapter_numbers=None, toc_mode=False)
                logger.debug("[CH-WRITE]   有源卷映射: KB调用 comprehensive=True, volume_numbers=%s, toc_mode=False, kb_context长度=%s",
                             source_volumes, len(kb_context))
            else:
                logger.debug("[CH-WRITE] 章节写作(无源卷映射): novel_id=%s, ch=%s, volume=%s",
                             novel_id, chapter_number, fanwork_vol_nums)
                kb_context = await build_kb_context_for_agent(db, novel.knowledge_base_id, query_text, volume_numbers=fanwork_vol_nums, chapter_numbers=[chapter_number])
                logger.debug("[CH-WRITE]   无源卷映射: kb_context长度=%s", len(kb_context))
        except Exception:
            logger.exception("构建知识库上下文失败 novel=%s kb=%s", novel_id, novel.knowledge_base_id)

    ordinary_kb_context = ""
    if novel.ordinary_knowledge_base_id:
        try:
            from app.services.ordinary_kb_service import build_ordinary_kb_context
            ordinary_kb_context = await build_ordinary_kb_context(db, novel.ordinary_knowledge_base_id)
            logger.debug("[CH-WRITE] 普通知识库上下文: novel=%s okb=%s len=%s",
                         novel_id, novel.ordinary_knowledge_base_id, len(ordinary_kb_context))
        except Exception:
            logger.exception("构建普通知识库上下文失败 novel=%s okb=%s", novel_id, novel.ordinary_knowledge_base_id)

    user_preference_summary = ""
    pref_result = await db.execute(
        select(ModificationRecord)
        .where(ModificationRecord.novel_id == novel_id)
        .order_by(ModificationRecord.created_at.desc())
        .limit(10)
    )
    mod_records = pref_result.scalars().all()
    if mod_records:
        parts = []
        for r in mod_records:
            parts.append(f"原文：{r.original_text[:200]}... → 修改为：{r.modified_text[:200]}... (类型：{r.modification_type})")
        user_preference_summary = "用户历史修改偏好：\n" + "\n".join(parts)

    story_knowledge = {}
    try:
        from app.models.story_knowledge import StoryKnowledge as SK
        sk_result = await db.execute(
            select(SK).where(SK.novel_id == novel_id).order_by(SK.chapter_number.desc()).limit(3)
        )
        sk_rows = sk_result.scalars().all()
        all_chars = []
        all_rels = []
        all_elems = []
        for sk in sk_rows:
            all_chars.extend(sk.characters or [])
            all_rels.extend(sk.character_relations or [])
            all_elems.extend(sk.world_elements or [])

        baseline_chars = []
        for c in (novel.characters or []):
            if isinstance(c, dict) and c.get("name"):
                parts = []
                if c.get("role"):
                    parts.append(f"定位：{c.get('role')}")
                if c.get("personality"):
                    parts.append(f"性格：{c.get('personality')}")
                if c.get("background"):
                    parts.append(f"背景：{c.get('background')}")
                baseline_chars.append({
                    "name": c.get("name"),
                    "role": c.get("role", ""),
                    "description": "；".join(parts),
                    "status": "active",
                })

        for c in ((novel.full_outline or {}).get("characters") or []):
            if isinstance(c, dict) and c.get("name"):
                name = c.get("name")
                if not any(b["name"] == name for b in baseline_chars):
                    parts = []
                    if c.get("profile"):
                        parts.append(f"设定：{c.get('profile')}")
                    if c.get("motivation"):
                        parts.append(f"动机：{c.get('motivation')}")
                    if c.get("relationships"):
                        parts.append(f"关联：{c.get('relationships')}")
                    if c.get("arc"):
                        parts.append(f"变化轨迹：{c.get('arc')}")
                    baseline_chars.append({
                        "name": name,
                        "role": c.get("role", ""),
                        "description": "；".join(parts),
                        "status": "active",
                    })

        baseline_elems = []
        ws = novel.world_settings or {}
        if isinstance(ws, dict):
            if ws.get("era"):
                baseline_elems.append({"category": "规则", "name": "时代背景", "description": str(ws.get("era")), "related_characters": []})
            if ws.get("location"):
                baseline_elems.append({"category": "地点", "name": str(ws.get("location")), "description": "故事主要发生地", "related_characters": []})
            if ws.get("rules"):
                baseline_elems.append({"category": "规则", "name": "世界规则", "description": str(ws.get("rules")), "related_characters": []})
            for ke in (ws.get("key_elements") or []):
                if isinstance(ke, dict):
                    baseline_elems.append({"category": "物品", "name": ke.get("name", "关键元素"), "description": ke.get("description", ""), "related_characters": []})
                elif isinstance(ke, str) and ke:
                    baseline_elems.append({"category": "物品", "name": ke, "description": "", "related_characters": []})

        wv = (novel.full_outline or {}).get("worldview", "")
        if wv and not any(e.get("name") == "世界观" for e in baseline_elems):
            baseline_elems.append({"category": "规则", "name": "世界观", "description": str(wv), "related_characters": []})

        char_map = {}
        for c in baseline_chars:
            char_map[c["name"]] = c
        for c in all_chars:
            if not isinstance(c, dict):
                continue
            name = c.get("name", "")
            if not name:
                continue
            ext_desc = c.get("description", "") or c.get("behavior", "")
            if name in char_map:
                base = char_map[name]
                merged = dict(base)
                if ext_desc:
                    merged["description"] = (base.get("description") or "") + "｜本章表现：" + str(ext_desc)
                merged["role"] = c.get("role") or base.get("role", "")
                merged["status"] = c.get("status") or base.get("status", "active")
                char_map[name] = merged
            else:
                char_map[name] = {
                    "name": name,
                    "role": c.get("role", ""),
                    "description": str(ext_desc),
                    "status": c.get("status", "active"),
                }

        seen_rels = set()
        unique_rels = []
        for r in all_rels:
            if isinstance(r, dict):
                key = (r.get("from", ""), r.get("to", ""), r.get("type", ""))
                if key not in seen_rels:
                    seen_rels.add(key)
                    unique_rels.append(r)

        elem_map = {}
        for e in baseline_elems:
            if e.get("name"):
                elem_map[e["name"]] = e
        for e in all_elems:
            if not isinstance(e, dict):
                continue
            name = e.get("name", "")
            if not name:
                continue
            if name not in elem_map:
                elem_map[name] = {
                    "category": e.get("category", ""),
                    "name": name,
                    "description": e.get("description", ""),
                    "related_characters": e.get("related_characters", []),
                }

        merged_chars = list(char_map.values())
        merged_elems = list(elem_map.values())
        if merged_chars or unique_rels or merged_elems:
            story_knowledge = {
                "characters": merged_chars,
                "character_relations": unique_rels,
                "world_elements": merged_elems,
            }
    except Exception:
        logger.exception("读取章节故事知识失败 novel=%s chapter=%s", novel_id, chapter_number)

    state: NovelState = {
        "novel_id": novel_id,
        "current_phase": "loading_context",
        "outline": novel.outline or [],
        "current_chapter_number": chapter_number,
        "chapter_draft": "",
        "chapter_title": "",
        "previous_chapters_full": previous_full,
        "previous_semantics": previous_semantics,
        "review_comments": [],
        "writer_decisions": [],
        "pending_user_decisions": [],
        "user_decisions": [],
        "revision_count": 0,
        "is_final": False,
        "rag_context": rag_context,
        "user_preference_summary": user_preference_summary,
        "story_knowledge": story_knowledge,
        "writing_style": novel.writing_style,
        "narrative_pov": novel.narrative_pov,
        "target_word_count": novel.target_word_count,
        "knowledge_base_id": novel.knowledge_base_id,
        "novel_genre": novel.genre,
        "kb_context": kb_context,
        "ordinary_kb_context": ordinary_kb_context,
        "full_outline": novel.full_outline or {},
        "novel_world_settings": novel.world_settings or {},
        "novel_characters": novel.characters or [],
    }
    return state


async def _enrich_with_psychology(state: NovelState) -> None:
    try:
        await curate_character_psychology(state)
    except Exception:
        logger.exception("角色心理策展失败，跳过")


async def generate_chapter(db: AsyncSession, novel_id: int, chapter_number: int) -> dict:
    state = await _build_chapter_state(db, novel_id, chapter_number)
    if not state:
        return {"error": "小说不存在"}

    state = await load_context(state)
    await _enrich_with_psychology(state)
    state = await write_chapter(state)
    state = await review_parallel(state)
    state = await evaluate_reviews(state)

    route = await evaluate_reviews_router(state)
    if route == "auto_revise":
        state = await auto_revise(state)
    elif route == "user_decision":
        state["current_phase"] = "waiting_user_decision"

    if route != "user_decision":
        from app.agents.readers.polish_reader import polish_chapter
        try:
            polish_result = await polish_chapter(state)
            state["polished_draft"] = polish_result.get("polished_draft", "")
        except LLMError as e:
            logger.warning("润色失败 novel=%s chapter=%s: %s", novel_id, chapter_number, e.message)

    if state.get("pending_user_decisions"):
        try:
            import app.api.reviews as _reviews_mod
            _reviews_mod._set_active_state(f"{novel_id}_{chapter_number}", state)
        except Exception:
            logger.exception("写入待决策状态失败 novel=%s chapter=%s", novel_id, chapter_number)

    return _state_to_response(state)


async def generate_chapter_with_stream(db: AsyncSession, novel_id: int, chapter_number: int):
    from app.agents.readers.polish_reader import polish_chapter_stream
    from app.agents.readers.character_reader import review_character
    from app.agents.readers.logic_reader import review_logic
    from app.agents.readers.style_reader import review_style

    state = await _build_chapter_state(db, novel_id, chapter_number)
    if not state:
        yield json.dumps({"type": "error", "error": "小说不存在"}, ensure_ascii=False) + "\n"
        return

    state = await load_context(state)

    yield json.dumps({"type": "status", "phase": "curating_psychology", "chapter_number": chapter_number}, ensure_ascii=False) + "\n"
    await _enrich_with_psychology(state)

    yield json.dumps({"type": "status", "phase": "writing", "chapter_number": chapter_number}, ensure_ascii=False) + "\n"

    full_draft = ""
    async for chunk in write_chapter_stream(state):
        full_draft += chunk
        yield json.dumps({"type": "content", "text": chunk}, ensure_ascii=False) + "\n"

    state["chapter_draft"] = full_draft

    yield json.dumps({"type": "status", "phase": "reviewing", "message": "人物审查员正在审查...", "reviewer": "character"}, ensure_ascii=False) + "\n"
    try:
        char_result = await review_character(state)
    except LLMError as e:
        char_result = {"reader_type": "character", "comments": [], "overall_score": 0, "overall_comment": f"审查失败: {e.message}"}

    yield json.dumps({"type": "status", "phase": "reviewing", "message": "逻辑审查员正在审查...", "reviewer": "logic"}, ensure_ascii=False) + "\n"
    try:
        logic_result = await review_logic(state)
    except LLMError as e:
        logic_result = {"reader_type": "logic", "comments": [], "overall_score": 0, "overall_comment": f"审查失败: {e.message}"}

    yield json.dumps({"type": "status", "phase": "reviewing", "message": "文笔审查员正在审查...", "reviewer": "style"}, ensure_ascii=False) + "\n"
    try:
        style_result = await review_style(state)
    except LLMError as e:
        style_result = {"reader_type": "style", "comments": [], "overall_score": 0, "overall_comment": f"审查失败: {e.message}"}

    all_comments = []
    for result in [char_result, logic_result, style_result]:
        comments = result.get("comments", [])
        for c in comments:
            c["reader_type"] = result.get("reader_type", "unknown")
        all_comments.extend(comments)

    state["review_comments"] = all_comments
    state["current_phase"] = "reviewed"

    yield json.dumps({"type": "status", "phase": "evaluating", "message": "写手智能体正在评估审查意见..."}, ensure_ascii=False) + "\n"
    state = await evaluate_reviews(state)

    route = await evaluate_reviews_router(state)
    if route == "auto_revise":
        yield json.dumps({"type": "status", "phase": "revising", "message": "写手智能体正在修订章节..."}, ensure_ascii=False) + "\n"
        state = await auto_revise(state)
    elif route == "user_decision":
        state["current_phase"] = "waiting_user_decision"

    if route != "user_decision":
        yield json.dumps({"type": "status", "phase": "polishing", "message": "AI 文章润色师正在润色全章...", "reviewer": "polish"}, ensure_ascii=False) + "\n"
        try:
            async for pc in polish_chapter_stream(state):
                if "text" in pc:
                    yield json.dumps({"type": "polish_content", "text": pc["text"]}, ensure_ascii=False) + "\n"
                elif pc.get("done"):
                    state["polished_draft"] = pc.get("polished", "")
        except LLMError as e:
            logger.warning("润色失败 novel=%s chapter=%s: %s", novel_id, chapter_number, e.message)

    if state.get("pending_user_decisions"):
        try:
            import app.api.reviews as _reviews_mod
            _reviews_mod._set_active_state(f"{novel_id}_{chapter_number}", state)
        except Exception:
            logger.exception("写入待决策状态失败 novel=%s chapter=%s", novel_id, chapter_number)

    response = _state_to_response(state)
    yield json.dumps({"type": "complete", "data": response}, ensure_ascii=False) + "\n"


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


async def save_chapter(db: AsyncSession, novel_id: int, chapter_number: int, content: str, title: str = "", status: str = "final") -> Chapter:
    result = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
    )
    chapter = result.scalar_one_or_none()

    if chapter:
        if chapter.content != content:
            version = ChapterVersion(
                chapter_id=chapter.id,
                version=chapter.version,
                content=chapter.content,
                source=status,
            )
            db.add(version)
            chapter.version += 1
        chapter.content = content
        chapter.title = title or chapter.title
        chapter.status = status
    else:
        chapter = Chapter(
            novel_id=novel_id,
            chapter_number=chapter_number,
            title=title or f"第{chapter_number}章",
            content=content,
            status=status,
        )
        db.add(chapter)

    await db.commit()
    await db.refresh(chapter)

    if status == "final":
        try:
            from app.services.knowledge_extractor import extract_chapter_knowledge
            novel = await db.get(Novel, novel_id)
            outline_item = None
            if novel and novel.outline:
                for item in novel.outline:
                    if item.get("chapter_number") == chapter_number:
                        outline_item = item
                        break
            await extract_chapter_knowledge(db, novel_id, chapter_number, content, outline_item)
        except Exception:
            logger.exception("提取章节知识失败 novel=%s chapter=%s", novel_id, chapter_number)

    return chapter


async def save_chapter_semantic(db: AsyncSession, novel_id: int, chapter_number: int, content: str) -> ChapterSemantic:
    from app.rag.retriever import upsert_to_collection

    _SEMANTIC_SYSTEM_PROMPT = "你是一位小说分析专家。请分析给定章节内容，提取摘要、关键词、涉及人物、关键情节点和情感走向。\n\n【提取准则】\n- 摘要用平实陈述句概括本章核心事件，避免排比堆叠、破折号\"——\"及\"不是……而是……\"翻转句；\n- 关键词聚焦本章实际出现的核心概念与情节，不臆测；\n- 涉人物只登记本章有出场或被明确提及的角色；\n- 关键情节点按发生顺序列出本章推动剧情发展的事件；\n- 情感走向用简短陈述句概括本章情绪基调变化。\n\n输出严格JSON格式：{\"summary\": \"摘要\", \"keywords\": [\"关键词1\"], \"characters_involved\": [\"人物1\"], \"plot_points\": [\"情节点1\"], \"emotional_arc\": \"情感走向\"}"

    async def _extract_semantic(chunk: str) -> dict:
        messages = [
            {"role": "system", "content": _SEMANTIC_SYSTEM_PROMPT},
            {"role": "user", "content": f"请分析以下章节内容（片段）：\n\n{chunk}"},
        ]
        try:
            response = await llm_client.chat(messages, temperature=0.3, max_tokens=2048)
        except Exception:
            return {}
        clean = (response or "").strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            if len(lines) >= 2:
                clean = "\n".join(lines[1:])
                if clean.rstrip().endswith("```"):
                    clean = clean.rstrip()[:-3]
        try:
            data = json.loads(clean)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, ValueError, TypeError):
            return {}

    chunk_size = 3500
    overlap = 300
    if len(content) <= chunk_size:
        chunks = [content]
    else:
        chunks = []
        start = 0
        while start < len(content):
            chunks.append(content[start:start + chunk_size])
            if start + chunk_size >= len(content):
                break
            start += chunk_size - overlap

    parts = []
    for chunk in chunks:
        parts.append(await _extract_semantic(chunk))

    summaries = [p.get("summary", "") for p in parts if p.get("summary")]
    keywords = []
    characters_involved = []
    plot_points = []
    seen_kw, seen_char = set(), set()
    for p in parts:
        for kw in p.get("keywords", []) or []:
            lk = kw.lower()
            if lk not in seen_kw:
                seen_kw.add(lk)
                keywords.append(kw)
        for ch in p.get("characters_involved", []) or []:
            lc = ch.lower()
            if lc not in seen_char:
                seen_char.add(lc)
                characters_involved.append(ch)
        plot_points.extend(p.get("plot_points", []) or [])
    emotional_arc = parts[-1].get("emotional_arc", "") if parts else ""

    if summaries or plot_points:
        semantic_data = {
            "summary": "；".join(summaries) if summaries else content[:200],
            "keywords": keywords,
            "characters_involved": characters_involved,
            "plot_points": plot_points,
            "emotional_arc": emotional_arc or "未知",
        }
    else:
        semantic_data = {
            "summary": content[:200],
            "keywords": [],
            "characters_involved": [],
            "plot_points": [],
            "emotional_arc": "未知",
        }

    result = await db.execute(
        select(ChapterSemantic).where(ChapterSemantic.novel_id == novel_id, ChapterSemantic.chapter_number == chapter_number)
    )
    semantic = result.scalar_one_or_none()

    doc_text = (
        f"{semantic_data.get('summary', '')} 关键词：{', '.join(semantic_data.get('keywords', []))} "
        f"人物：{', '.join(semantic_data.get('characters_involved', []))} "
        f"情节：{'; '.join(semantic_data.get('plot_points', []))} "
        f"情感：{semantic_data.get('emotional_arc', '')} "
        f"场景地点：{semantic_data.get('location', '')} "
        f"本章冲突：{semantic_data.get('conflict', '')} "
        f"人物变化：{semantic_data.get('character_changes', '')} "
        f"章末钩子：{semantic_data.get('chapter_hook', '')}"
    )
    vector_id = f"semantic_{novel_id}_{chapter_number}"

    try:
        await upsert_to_collection(
            novel_id=novel_id,
            collection_type="chapter_semantics",
            documents=[doc_text],
            ids=[vector_id],
            metadatas=[{"chapter_number": chapter_number, "novel_id": novel_id}],
        )
    except Exception:
        logger.exception("向量写入失败 novel=%s chapter=%s，回滚DB事务", novel_id, chapter_number)
        await db.rollback()
        raise

    if semantic:
        semantic.summary = semantic_data.get("summary", "")
        semantic.keywords = semantic_data.get("keywords", [])
        semantic.characters_involved = semantic_data.get("characters_involved", [])
        semantic.plot_points = semantic_data.get("plot_points", [])
        semantic.emotional_arc = semantic_data.get("emotional_arc", "")
        semantic.vector_id = vector_id
    else:
        semantic = ChapterSemantic(
            novel_id=novel_id,
            chapter_number=chapter_number,
            summary=semantic_data.get("summary", ""),
            keywords=semantic_data.get("keywords", []),
            characters_involved=semantic_data.get("characters_involved", []),
            plot_points=semantic_data.get("plot_points", []),
            emotional_arc=semantic_data.get("emotional_arc", ""),
            vector_id=vector_id,
        )
        db.add(semantic)

    await db.commit()
    await db.refresh(semantic)

    return semantic


async def get_chapter(db: AsyncSession, novel_id: int, chapter_number: int) -> Chapter | None:
    result = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
    )
    return result.scalar_one_or_none()


async def get_chapters(db: AsyncSession, novel_id: int) -> list[Chapter]:
    result = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_number)
    )
    return result.scalars().all()


async def get_chapter_versions(db: AsyncSession, novel_id: int, chapter_number: int) -> list[ChapterVersion]:
    result = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        return []

    ver_result = await db.execute(
        select(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id).order_by(ChapterVersion.version)
    )
    return ver_result.scalars().all()


def _state_to_response(state: NovelState) -> dict:
    return {
        "novel_id": state.get("novel_id", 0),
        "chapter_number": state.get("current_chapter_number", 0),
        "chapter_draft": state.get("chapter_draft", ""),
        "polished_draft": state.get("polished_draft", ""),
        "chapter_title": state.get("chapter_title", ""),
        "current_phase": state.get("current_phase", ""),
        "review_comments": state.get("review_comments", []),
        "writer_decisions": state.get("writer_decisions", []),
        "pending_user_decisions": state.get("pending_user_decisions", []),
        "revision_count": state.get("revision_count", 0),
        "is_final": state.get("is_final", False),
    }
