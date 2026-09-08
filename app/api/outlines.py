import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.outline import (
    OutlineGenerateRequest,
    OutlineUpdateRequest,
    OutlineConfirmRequest,
    FullOutlineGenerateRequest,
    FullOutlineUpdateRequest,
    ChapterOutlineGenerateRequest,
)
from app.services import outline_service
from app.services.novel_service import get_novel
from app.agents.outline_agent import (
    generate_outline_stream,
    generate_full_outline_stream,
    generate_chapter_outline_stream,
    _parse_outline_response,
    _parse_full_outline_response,
)
from app.agents.state import NovelState
from app.llm.siliconflow import LLMError

router = APIRouter()


async def _llm_stream_with_keepalive(agen, timeout: float = 8.0):
    """Wrap an async generator, yielding (is_content, payload) tuples.

    Content chunks: (True, chunk_str)
    Keepalive: (False, keepalive_json_str) — yielded when no chunk arrives within timeout.

    Exceptions from the wrapped generator are re-raised after the stream ends.
    """
    queue: asyncio.Queue = asyncio.Queue()
    producer_error: Exception | None = None

    async def _producer():
        nonlocal producer_error
        try:
            async for chunk in agen:
                await queue.put(chunk)
        except Exception as e:
            producer_error = e
        finally:
            await queue.put(None)

    producer_task = asyncio.create_task(_producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                yield False, json.dumps({"type": "keepalive"}, ensure_ascii=False) + "\n"
                continue
            if item is None:
                break
            yield True, item
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except BaseException:
                pass

    if producer_error is not None:
        raise producer_error


@router.post("/{novel_id}/outline/generate-full")
async def generate_full_outline(novel_id: int, data: FullOutlineGenerateRequest, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    if novel.genre == "同人" and not novel.knowledge_base_id:
        raise HTTPException(status_code=400, detail="同人小说需先关联知识库")

    async def stream_generator():
        from app.services.kb_service import build_kb_context_for_agent
        from app.services.volume_splitter import validate_and_backfill_source_volumes
        print(f"\n{'='*60}\n[FULL-OUTLINE] === 全文大纲生成开始: novel_id={novel_id}, genre={novel.genre!r}, kb_id={novel.knowledge_base_id} ===\n{'='*60}", flush=True)
        description = data.description or novel.description or ""

        web_research_context = ""
        if data.use_web_research:
            yield json.dumps({"type": "status", "phase": "web_researching"}, ensure_ascii=False) + "\n"
            try:
                from app.services.web_research import research_for_outline_safe
                wr_task = asyncio.create_task(research_for_outline_safe(
                    novel.title, data.genre or novel.genre or "", description
                ))
                while True:
                    done, _ = await asyncio.wait({wr_task}, timeout=5.0)
                    if wr_task in done:
                        try:
                            web_research_context, wr_err = wr_task.result()
                        except Exception as e:
                            wr_err = f"联网取材失败：{e}"
                            web_research_context = ""
                        break
                    yield json.dumps({"type": "status", "phase": "web_researching"}, ensure_ascii=False) + "\n"
                if wr_err:
                    yield json.dumps({"type": "status", "phase": "web_research_skipped", "message": wr_err}, ensure_ascii=False) + "\n"
                else:
                    yield json.dumps({"type": "status", "phase": "web_research_done"}, ensure_ascii=False) + "\n"
            except Exception as e:
                print(f"[WebResearch] 联网取材失败: {e}")

        kb_save_result = None
        if web_research_context and novel.knowledge_base_id:
            yield json.dumps({"type": "status", "phase": "kb_saving"}, ensure_ascii=False) + "\n"
            try:
                from app.services.web_research import save_web_research_to_kb
                kbs_task = asyncio.create_task(save_web_research_to_kb(
                    db, novel.knowledge_base_id, web_research_context,
                    novel.title, data.genre or novel.genre or "",
                ))
                while True:
                    done, _ = await asyncio.wait({kbs_task}, timeout=5.0)
                    if kbs_task in done:
                        try:
                            kb_save_result = kbs_task.result()
                        except Exception as e:
                            print(f"[KB] 联网取材存入知识库失败: {e}")
                            kb_save_result = {"saved": 0, "skipped": 0, "skipped_titles": [], "reason": str(e)}
                        break
                    yield json.dumps({"type": "status", "phase": "kb_saving"}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "status", "phase": "kb_saved", "data": kb_save_result}, ensure_ascii=False) + "\n"
            except Exception as e:
                print(f"[KB] 联网取材存入知识库失败: {e}")
                yield json.dumps({"type": "status", "phase": "kb_save_failed", "message": str(e)}, ensure_ascii=False) + "\n"

        kb_context = ""
        if novel.knowledge_base_id:
            try:
                print(f"[FULL-OUTLINE] 正在检索知识库: kb_id={novel.knowledge_base_id}, comprehensive=True, toc_mode=True, volume_filter=None(全部卷)", flush=True)
                kbc_task = asyncio.create_task(build_kb_context_for_agent(
                    db, novel.knowledge_base_id, description, comprehensive=True, toc_mode=True
                ))
                while True:
                    done, _ = await asyncio.wait({kbc_task}, timeout=5.0)
                    if kbc_task in done:
                        try:
                            kb_context = kbc_task.result()
                        except Exception as e:
                            print(f"[KB] 全文大纲知识库读取失败: {e}", flush=True)
                        break
                    yield json.dumps({"type": "status", "phase": "kb_loading"}, ensure_ascii=False) + "\n"
            except Exception as e:
                print(f"[KB] 全文大纲知识库读取失败: {e}", flush=True)

        has_vol_summary = "卷摘要" in kb_context or "【卷" in kb_context or "Volume Summary" in kb_context
        has_ch_summary = "章摘要" in kb_context or "章节摘要" in kb_context or "Chapter Summary" in kb_context
        print(f"[FULL-OUTLINE] KB上下文检索完成: 长度={len(kb_context)}字符, 包含卷摘要={has_vol_summary}, 包含章摘要={has_ch_summary}", flush=True)
        if kb_context:
            print(f"[FULL-OUTLINE] KB上下文前300字符预览:\n{kb_context[:300]}\n...", flush=True)
        else:
            print(f"[FULL-OUTLINE] 警告: KB上下文为空! kb_id={novel.knowledge_base_id}", flush=True)

        effective_twc = data.target_word_count or novel.target_word_count or 0
        try:
            effective_twc = int(effective_twc)
        except (TypeError, ValueError):
            effective_twc = novel.target_word_count or 0
        requested_length = data.length_type or novel.length_type or "short"
        if effective_twc < 500000 and requested_length == "long":
            effective_twc = 800000
        elif effective_twc < 500000 and requested_length == "medium":
            effective_twc = 300000
        derived_length = "long" if effective_twc >= 500000 else "short"
        print(f"[OUTLINE] target_word_count: data={data.target_word_count}, db={novel.target_word_count}, effective={effective_twc}, requested_length={requested_length}, derived={derived_length}")
        if effective_twc and effective_twc != (novel.target_word_count or 0):
            novel.target_word_count = effective_twc
            print(f"[OUTLINE] 自纠正 target_word_count -> {effective_twc}")
        if derived_length != (novel.length_type or ""):
            novel.length_type = derived_length
            print(f"[OUTLINE] 自纠正 length_type -> {derived_length}")

        try:
            await db.commit()
            await db.refresh(novel)
        except Exception as e:
            print(f"[OUTLINE] 自纠正值持久化失败: {e}")

        world_settings = data.world_settings if data.world_settings else (novel.world_settings or {})
        characters = data.characters if data.characters else (novel.characters or [])
        print(f"[OUTLINE] settings source: world_settings from={'request' if data.world_settings else 'db'} (keys={list(world_settings.keys()) if isinstance(world_settings, dict) else []}), characters from={'request' if data.characters else 'db'} (n={len(characters) if isinstance(characters, list) else 0})")

        state: NovelState = {
            "novel_id": novel_id,
            "knowledge_base_id": novel.knowledge_base_id,
            "kb_context": kb_context,
            "web_research_context": web_research_context,
            "outline_item": {
                "title": novel.title,
                "genre": data.genre or novel.genre or "",
                "description": description,
                "length_type": derived_length,
                "writing_style": novel.writing_style,
                "target_word_count": effective_twc,
                "narrative_pov": novel.narrative_pov,
                "world_settings": world_settings,
                "characters": characters,
            },
        }

        yield json.dumps({"type": "status", "phase": "generating_full_outline"}, ensure_ascii=False) + "\n"

        full_text = ""
        try:
            async for is_content, payload in _llm_stream_with_keepalive(generate_full_outline_stream(state)):
                if is_content:
                    full_text += payload
                    yield json.dumps({"type": "content", "text": payload}, ensure_ascii=False) + "\n"
                else:
                    yield payload
        except LLMError as e:
            yield json.dumps({"type": "error", "error": f"AI服务错误: {e.message}"}, ensure_ascii=False) + "\n"
            return
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"生成失败: {str(e)}"}, ensure_ascii=False) + "\n"
            return

        full_outline = _parse_full_outline_response(full_text)
        full_outline = validate_and_backfill_source_volumes(full_outline)

        fo_volumes = full_outline.get("volumes", []) if isinstance(full_outline, dict) else []
        print(f"\n[FULL-OUTLINE] 全文大纲解析完成: {len(fo_volumes)}卷", flush=True)
        for v in fo_volumes:
            vn = v.get("volume_number", "?")
            vt = v.get("title", "")[:30]
            sv = v.get("source_volumes", [])
            ch_count = len(v.get("chapters", []))
            print(f"  卷{vn}《{vt}》: source_volumes={sv}, 章节数={ch_count}", flush=True)

        novel.full_outline = full_outline
        novel.length_type = "long" if (novel.target_word_count or 0) >= 500000 else (novel.length_type or "short")
        await db.commit()

        try:
            from app.services.knowledge_service import index_full_outline_to_rag
            indexed = await index_full_outline_to_rag(novel_id, full_outline)
            print(f"[RAG] 全文大纲已索引 {indexed} 条设定到 world_knowledge", flush=True)
        except Exception as e:
            print(f"[RAG] 索引全文大纲失败: {e}", flush=True)

        yield json.dumps({"type": "complete", "data": {"full_outline": full_outline}}, ensure_ascii=False) + "\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.get("/{novel_id}/outline/full")
async def get_full_outline(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"full_outline": novel.full_outline or {}}


@router.put("/{novel_id}/outline/full")
async def update_full_outline(novel_id: int, data: FullOutlineUpdateRequest, db: AsyncSession = Depends(get_db)):
    full_outline = await outline_service.update_full_outline(db, novel_id, data.full_outline)
    if not full_outline and full_outline != {}:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"full_outline": full_outline}


@router.post("/{novel_id}/outline/revise-full")
async def ai_revise_full_outline(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    user_feedback = data.get("user_feedback", "")
    if not user_feedback:
        raise HTTPException(status_code=400, detail="请提供修改意见")
    try:
        full_outline = await outline_service.ai_revise_full_outline(db, novel_id, user_feedback)
        if not full_outline and full_outline != {}:
            raise HTTPException(status_code=404, detail="小说不存在")
        return {"full_outline": full_outline}
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"AI服务暂时不可用，请稍后重试: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"修改大纲失败: {str(e)}")


@router.post("/{novel_id}/outline/generate-chapters")
async def generate_chapter_outline(novel_id: int, data: ChapterOutlineGenerateRequest, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    if not novel.full_outline or not novel.full_outline.get("volumes"):
        raise HTTPException(status_code=400, detail="请先生成全文大纲")

    async def stream_generator():
        from app.services.outline_service import _build_knowledge_summary
        from app.services.kb_service import build_kb_context_for_agent
        from app.services.volume_splitter import volumes_for_chapter_range, resolve_source_volumes
        knowledge_summary = await _build_knowledge_summary(db, novel_id)

        chapter_vol_nums = volumes_for_chapter_range(novel.full_outline or {}, data.start_chapter, data.start_chapter + data.batch_size - 1)
        print(f"[CH-OUTLINE] 章节大纲: novel_id={novel_id}, genre={novel.genre}, chapters={data.start_chapter}-{data.start_chapter + data.batch_size - 1}, fanfic_volumes={chapter_vol_nums}")

        kb_context = ""
        if novel.knowledge_base_id:
            try:
                source_volumes = resolve_source_volumes(novel.full_outline or {}, chapter_vol_nums) if novel.full_outline else None
                if source_volumes is not None:
                    print(f"[CH-OUTLINE]   有源卷映射: fanfic_volumes={chapter_vol_nums} -> source_kb_volumes={source_volumes}", flush=True)
                    kb_context = await build_kb_context_for_agent(
                        db, novel.knowledge_base_id,
                        f"第{data.start_chapter}章到第{data.start_chapter + data.batch_size - 1}章",
                        comprehensive=True,
                        volume_numbers=source_volumes,
                        chapter_numbers=None,
                        toc_mode=False,
                    )
                    print(f"[CH-OUTLINE]   有源卷映射: KB调用 comprehensive=True, volume_numbers={source_volumes}, toc_mode=False, kb_context长度={len(kb_context)}", flush=True)
                else:
                    print(f"[CH-OUTLINE]   无源卷映射: KB调用 volume_numbers={chapter_vol_nums}, chapter_numbers={list(range(data.start_chapter, data.start_chapter + data.batch_size))}", flush=True)
                    kb_context = await build_kb_context_for_agent(
                        db, novel.knowledge_base_id,
                        f"第{data.start_chapter}章到第{data.start_chapter + data.batch_size - 1}章",
                        volume_numbers=chapter_vol_nums,
                        chapter_numbers=list(range(data.start_chapter, data.start_chapter + data.batch_size)),
                    )
                    print(f"[CH-OUTLINE]   无源卷映射: kb_context长度={len(kb_context)}", flush=True)
            except Exception as e:
                print(f"[KB] 章节大纲知识库读取失败: {e}")

        state: NovelState = {
            "novel_id": novel_id,
            "knowledge_base_id": novel.knowledge_base_id,
            "kb_context": kb_context,
            "full_outline": novel.full_outline or {},
            "outline": novel.outline or [],
            "outline_item": {
                "start_chapter": data.start_chapter,
                "batch_size": data.batch_size,
                "writing_style": novel.writing_style,
                "target_word_count": novel.target_word_count,
                "narrative_pov": novel.narrative_pov,
                "world_settings": novel.world_settings or {},
                "characters": novel.characters or [],
            },
            "story_knowledge_summary": knowledge_summary,
        }

        yield json.dumps({"type": "status", "phase": "generating_chapter_outline"}, ensure_ascii=False) + "\n"

        full_text = ""
        try:
            async for is_content, payload in _llm_stream_with_keepalive(generate_chapter_outline_stream(state)):
                if is_content:
                    full_text += payload
                    yield json.dumps({"type": "content", "text": payload}, ensure_ascii=False) + "\n"
                else:
                    yield payload
        except LLMError as e:
            yield json.dumps({"type": "error", "error": f"AI服务错误: {e.message}"}, ensure_ascii=False) + "\n"
            return
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"生成失败: {str(e)}"}, ensure_ascii=False) + "\n"
            return

        new_chapters = _parse_outline_response(full_text)
        start_chapter = data.start_chapter
        for i, ch in enumerate(new_chapters):
            ch["chapter_number"] = start_chapter + i

        merged = list(novel.outline or [])
        existing_nums = {item.get("chapter_number") for item in merged}
        for ch in new_chapters:
            if ch.get("chapter_number") not in existing_nums:
                merged.append(ch)
        merged.sort(key=lambda x: x.get("chapter_number", 0))

        novel.outline = merged
        await db.commit()

        try:
            from app.services.knowledge_service import index_chapter_outline_to_rag
            indexed = await index_chapter_outline_to_rag(novel_id, merged)
            print(f"[RAG] 章节大纲已索引 {indexed} 条到 chapter_semantics")
        except Exception as e:
            print(f"[RAG] 索引章节大纲失败: {e}")

        yield json.dumps({"type": "complete", "data": {"outline": merged}}, ensure_ascii=False) + "\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.post("/{novel_id}/outline/generate")
async def generate_outline(novel_id: int, data: OutlineGenerateRequest, db: AsyncSession = Depends(get_db)):
    use_stream = data.target_chapters is None or data.target_chapters > 5

    if use_stream:
        async def stream_generator():
            novel = await get_novel(db, novel_id)
            if not novel:
                yield json.dumps({"type": "error", "error": "小说不存在"}, ensure_ascii=False) + "\n"
                return

            from app.services.kb_service import build_kb_context_for_agent
            kb_context = ""
            if novel.knowledge_base_id:
                try:
                    kb_context = await build_kb_context_for_agent(
                        db, novel.knowledge_base_id,
                        data.description or novel.description or "",
                        comprehensive=True,
                    )
                except Exception as e:
                    print(f"[KB] 简单大纲知识库读取失败: {e}")

            state: NovelState = {
                "novel_id": novel_id,
                "knowledge_base_id": novel.knowledge_base_id,
                "kb_context": kb_context,
                "outline_item": {
                    "title": novel.title,
                    "genre": data.genre or novel.genre or "",
                    "description": data.description or novel.description or "",
                    "target_chapters": data.target_chapters or 10,
                },
            }

            yield json.dumps({"type": "status", "phase": "generating"}, ensure_ascii=False) + "\n"

            full_text = ""
            try:
                async for is_content, payload in _llm_stream_with_keepalive(generate_outline_stream(state)):
                    if is_content:
                        full_text += payload
                        yield json.dumps({"type": "content", "text": payload}, ensure_ascii=False) + "\n"
                    else:
                        yield payload
            except LLMError as e:
                yield json.dumps({"type": "error", "error": f"AI服务错误: {e.message}"}, ensure_ascii=False) + "\n"
                return
            except Exception as e:
                yield json.dumps({"type": "error", "error": f"生成失败: {str(e)}"}, ensure_ascii=False) + "\n"
                return

            outline = _parse_outline_response(full_text)

            novel.outline = outline
            await db.commit()

            try:
                from app.services.knowledge_service import index_chapter_outline_to_rag
                indexed = await index_chapter_outline_to_rag(novel_id, outline)
                print(f"[RAG] 章节大纲已索引 {indexed} 条到 chapter_semantics")
            except Exception as e:
                print(f"[RAG] 索引章节大纲失败: {e}")

            yield json.dumps({"type": "complete", "data": {"outline": outline}}, ensure_ascii=False) + "\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        try:
            outline = await outline_service.generate_novel_outline(
                db, novel_id,
                description=data.description or "",
                genre=data.genre or "",
                target_chapters=data.target_chapters or 10,
            )
            if not outline:
                raise HTTPException(status_code=404, detail="小说不存在")
            return {"outline": outline}
        except LLMError as e:
            raise HTTPException(status_code=503, detail=f"AI服务暂时不可用，请稍后重试: {e.message}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"生成大纲失败: {str(e)}")


@router.get("/{novel_id}/outline")
async def get_outline(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel = await get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"outline": novel.outline or []}


@router.put("/{novel_id}/outline")
async def update_outline(novel_id: int, data: OutlineUpdateRequest, db: AsyncSession = Depends(get_db)):
    outline_data = [item.model_dump() for item in data.outline]
    outline = await outline_service.update_outline(db, novel_id, outline_data)
    if not outline:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"outline": outline}


@router.put("/{novel_id}/outline/confirm")
async def confirm_outline(novel_id: int, data: OutlineConfirmRequest, db: AsyncSession = Depends(get_db)):
    if not data.confirmed:
        return {"message": "大纲未确认"}
    novel = await outline_service.confirm_outline(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"message": "大纲已确认", "status": novel.status}


@router.post("/{novel_id}/outline/revise")
async def ai_revise_outline(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    user_feedback = data.get("user_feedback", "")
    if not user_feedback:
        raise HTTPException(status_code=400, detail="请提供修改意见")
    try:
        outline = await outline_service.ai_revise_outline(db, novel_id, user_feedback)
        if not outline:
            raise HTTPException(status_code=404, detail="小说不存在")
        return {"outline": outline}
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"AI服务暂时不可用，请稍后重试: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"修改大纲失败: {str(e)}")
