from app.llm.siliconflow import llm_client
from app.rag.retriever import add_to_collection, upsert_to_collection
from app.services.document_parser import extract_text_from_file
from app.rag.chroma_client import chroma_client, get_novel_collection_name
import json


async def import_document_to_knowledge(novel_id: int, file_content: bytes, filename: str, category: str = "imported") -> dict:
    text = await extract_text_from_file(file_content, filename)

    if not text.strip():
        return {"error": "文档内容为空", "imported_count": 0}

    async def _extract_doc_chunk(chunk: str, idx: int, total: int) -> dict:
        chunk_prompt = f"""请从以下文档片段中提取关键知识点，用于小说写作参考。这是第 {idx + 1}/{total} 片段。

【提取准则】
- 只提取片段中明确出现的信息，不臆测、不补脑未交代的内容；
- 各字段内容用平实陈述句详细描述，避免排比堆叠、破折号"——"及"不是……而是……"翻转句；
- 同一设定/人物/情节避免重复登记；
- 没有对应内容则留空数组，不要硬凑。

文档片段：
{chunk}

请提取以下类型的信息，输出严格JSON格式：
{{
  "world_settings": [
    {{"name": "设定名称", "content": "设定详细描述", "category": "设定类别（如地理/政治/文化/科技等）"}}
  ],
  "characters": [
    {{"name": "人物名称", "traits": "性格特征", "background": "背景描述"}}
  ],
  "plot_elements": [
    {{"name": "情节元素", "description": "详细描述", "tags": ["标签1", "标签2"]}}
  ],
  "writing_style": [
    {{"feature": "风格特征", "examples": "文中的示例"}}
  ],
  "key_phrases": ["可以借鉴的关键短语1", "关键短语2"]
}}

只输出JSON，不要输出其他内容。"""
        msgs = [
            {"role": "system", "content": "你是一位文学分析专家，擅长从文档中提取可用于小说创作的知识。"},
            {"role": "user", "content": chunk_prompt},
        ]
        resp = await llm_client.chat(msgs, temperature=0.3, max_tokens=4096)
        clean = (resp or "").strip()
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

    chunk_size = 4000
    overlap = 200
    if len(text) <= chunk_size:
        chunks = [text]
    else:
        chunks = []
        start = 0
        while start < len(text):
            chunks.append(text[start:start + chunk_size])
            if start + chunk_size >= len(text):
                break
            start += chunk_size - overlap
        if len(chunks) > 25:
            chunks = chunks[:25]

    merged = {
        "world_settings": [],
        "characters": [],
        "plot_elements": [],
        "writing_style": [],
        "key_phrases": [],
    }
    seen_ws, seen_char, seen_pe, seen_style, seen_phrase = set(), set(), set(), set(), set()
    try:
        for idx, chunk in enumerate(chunks):
            part = await _extract_doc_chunk(chunk, idx, len(chunks))
            for s in part.get("world_settings", []) or []:
                k = (s.get("name", "") or "").strip().lower()
                if k and k not in seen_ws:
                    seen_ws.add(k)
                    merged["world_settings"].append(s)
            for c in part.get("characters", []) or []:
                k = (c.get("name", "") or "").strip().lower()
                if k and k not in seen_char:
                    seen_char.add(k)
                    merged["characters"].append(c)
            for e in part.get("plot_elements", []) or []:
                k = (e.get("name", "") or "").strip().lower()
                if k and k not in seen_pe:
                    seen_pe.add(k)
                    merged["plot_elements"].append(e)
            for w in part.get("writing_style", []) or []:
                k = (w.get("feature", "") or "").strip().lower()
                if k and k not in seen_style:
                    seen_style.add(k)
                    merged["writing_style"].append(w)
            for ph in part.get("key_phrases", []) or []:
                k = (ph or "").strip().lower()
                if k and k not in seen_phrase:
                    seen_phrase.add(k)
                    merged["key_phrases"].append(ph)
    except Exception as e:
        return {"error": f"AI提取失败: {str(e)}", "imported_count": 0}

    extracted = merged

    imported_count = 0
    doc_id_counter = 0

    for setting in extracted.get("world_settings", []):
        doc_id_counter += 1
        doc_text = f"[世界观-{setting.get('category', '设定')}] {setting.get('name', '')}: {setting.get('content', '')}"
        try:
            await add_to_collection(
                novel_id=novel_id,
                collection_type="world_knowledge",
                documents=[doc_text],
                ids=[f"doc_{filename}_{doc_id_counter}"],
                metadatas=[{"category": setting.get("category", category), "name": setting.get("name", ""), "source": filename}],
            )
            imported_count += 1
        except Exception:
            pass

    for char in extracted.get("characters", []):
        doc_id_counter += 1
        doc_text = f"[人物] {char.get('name', '')}: 性格-{char.get('traits', '')} 背景-{char.get('background', '')}"
        try:
            await add_to_collection(
                novel_id=novel_id,
                collection_type="world_knowledge",
                documents=[doc_text],
                ids=[f"doc_{filename}_{doc_id_counter}"],
                metadatas=[{"category": "character", "name": char.get("name", ""), "source": filename}],
            )
            imported_count += 1
        except Exception:
            pass

    for elem in extracted.get("plot_elements", []):
        doc_id_counter += 1
        tags = ", ".join(elem.get("tags", []))
        doc_text = f"[情节元素] {elem.get('name', '')}: {elem.get('description', '')} 标签: {tags}"
        try:
            await add_to_collection(
                novel_id=novel_id,
                collection_type="world_knowledge",
                documents=[doc_text],
                ids=[f"doc_{filename}_{doc_id_counter}"],
                metadatas=[{"category": "plot_element", "name": elem.get("name", ""), "source": filename}],
            )
            imported_count += 1
        except Exception:
            pass

    for style in extracted.get("writing_style", []):
        doc_id_counter += 1
        doc_text = f"[写作风格] {style.get('feature', '')}: {style.get('examples', '')}"
        try:
            await add_to_collection(
                novel_id=novel_id,
                collection_type="user_preferences",
                documents=[doc_text],
                ids=[f"doc_style_{filename}_{doc_id_counter}"],
                metadatas=[{"category": "writing_style", "source": filename}],
            )
            imported_count += 1
        except Exception:
            pass

    for phrase in extracted.get("key_phrases", []):
        doc_id_counter += 1
        try:
            await add_to_collection(
                novel_id=novel_id,
                collection_type="user_preferences",
                documents=[f"[关键短语] {phrase}"],
                ids=[f"doc_phrase_{filename}_{doc_id_counter}"],
                metadatas=[{"category": "key_phrase", "source": filename}],
            )
            imported_count += 1
        except Exception:
            pass

    if not extracted.get("world_settings") and not extracted.get("characters") and not extracted.get("plot_elements"):
        chunks = [text[i:i+1000] for i in range(0, len(text), 1000)]
        for i, chunk in enumerate(chunks[:10]):
            doc_id_counter += 1
            try:
                await add_to_collection(
                    novel_id=novel_id,
                    collection_type="world_knowledge",
                    documents=[f"[导入文档-{filename}] {chunk}"],
                    ids=[f"doc_raw_{filename}_{doc_id_counter}"],
                    metadatas=[{"category": category, "source": filename, "chunk": i}],
                )
                imported_count += 1
            except Exception:
                pass

    return {
        "filename": filename,
        "extracted_categories": list(extracted.keys()),
        "imported_count": imported_count,
        "text_length": len(text),
    }


async def index_full_outline_to_rag(novel_id: int, full_outline: dict) -> int:
    """把全文框架的世界观/人物/卷六要素索引进 world_knowledge 集合，使写作时 RAG 能检索到设定。"""
    if not isinstance(full_outline, dict):
        return 0

    documents: list[str] = []
    ids: list[str] = []

    wv = (full_outline.get("worldview") or "").strip()
    if wv:
        documents.append(f"[世界观-背景] 世界观设定：{wv}")
        ids.append("outline_worldview")

    for c in (full_outline.get("characters") or []):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        parts = [f"[人物设定] {c.get('name', '')}（{c.get('role', '')}）"]
        if c.get("profile"):
            parts.append(f"设定：{c['profile']}")
        if c.get("motivation"):
            parts.append(f"动机：{c['motivation']}")
        if c.get("relationships"):
            parts.append(f"关联：{c['relationships']}")
        if c.get("arc"):
            parts.append(f"变化轨迹：{c['arc']}")
        if c.get("ability_baseline"):
            parts.append(f"能力基线：{c['ability_baseline']}")
        documents.append(" ".join(parts))
        safe_name = str(c.get("name", "")).replace(" ", "_")
        ids.append(f"outline_char_{safe_name}")

    vol_field_labels = [
        ("setting", "环境地点"),
        ("opening", "开端"),
        ("development", "发展阻力"),
        ("climax", "高潮"),
        ("ending", "结尾"),
    ]
    for vol in (full_outline.get("volumes") or []):
        if not isinstance(vol, dict):
            continue
        vol_num = vol.get("volume_number", "")
        vol_title = vol.get("title", "")
        for field, label in vol_field_labels:
            val = (vol.get(field) or "").strip()
            if val:
                documents.append(f"[卷{vol_num}-{label}] {vol_title}：{val}")
                ids.append(f"outline_vol{vol_num}_{field}")
        for di, d in enumerate(vol.get("character_dynamics") or []):
            if not isinstance(d, dict):
                continue
            documents.append(
                f"[卷{vol_num}-角色情感] {vol_title}：{d.get('character', '')} 情感[{d.get('emotion_state', '')}]，事件[{d.get('key_event', '')}]，变化[{d.get('emotion_change', '')}]"
            )
            ids.append(f"outline_vol{vol_num}_char_dynamics_{di}")
        for ai, a in enumerate(vol.get("protagonist_abilities") or []):
            if not isinstance(a, dict):
                continue
            documents.append(
                f"[卷{vol_num}-主角能力] {vol_title}：{a.get('ability', '')}（{a.get('state', '')}）变化[{a.get('change', '')}]，触发[{a.get('trigger_event', '')}]"
            )
            ids.append(f"outline_vol{vol_num}_protag_abilities_{ai}")

    for fi, f in enumerate(full_outline.get("foreshadowing") or []):
        if not isinstance(f, dict) or not f.get("id"):
            continue
        payoff = f.get("payoff_in_volume")
        payoff_txt = f"回收于第{payoff}卷" if payoff else "未回收"
        documents.append(
            f"[伏笔] {f.get('id')}：{f.get('description', '')}（埋于第{f.get('planted_in_volume', '?')}卷，{payoff_txt}，状态：{f.get('status', '')}）"
        )
        ids.append(f"outline_foreshadowing_{f.get('id')}")

    print(f"[RAG-IDX] 全文大纲待索引: documents={len(documents)}条, ids={len(ids)}条", flush=True)
    if not documents:
        return 0

    collection_name = get_novel_collection_name(novel_id, "world_knowledge")
    collection = chroma_client.get_or_create_collection(collection_name)
    try:
        existing = collection.get(where={"source": "outline"})
        existing_count = len(existing.get("ids", [])) if existing else 0
        if existing_count:
            print(f"[RAG-IDX] 清理旧索引: 删除{existing_count}条已存在的outline条目", flush=True)
            collection.delete(ids=existing["ids"])
    except Exception as e:
        print(f"[RAG-IDX] 清理旧索引失败(忽略): {type(e).__name__}: {e}", flush=True)

    metadatas = []
    for doc in documents:
        meta = {"source": "outline", "type": "full_outline"}
        if doc.startswith("[卷"):
            tail = doc[2:]
            dash = tail.find("-")
            if dash > 0 and tail[:dash].isdigit():
                meta["volume_number"] = int(tail[:dash])
        metadatas.append(meta)
    try:
        await upsert_to_collection(
            novel_id=novel_id,
            collection_type="world_knowledge",
            documents=documents,
            ids=ids,
            metadatas=metadatas,
        )
        print(f"[RAG-IDX] 全文大纲索引成功: {len(documents)}条已写入world_knowledge", flush=True)
    except Exception as e:
        print(f"[RAG-IDX] 全文大纲索引失败: {type(e).__name__}: {e}", flush=True)
        return 0

    return len(documents)


async def index_chapter_outline_to_rag(novel_id: int, chapter_outline: list) -> int:
    """把章节大纲的场景地点/冲突/人物变化/章末钩子索引进 chapter_semantics 集合，使写作时 RAG 能检索到相关章节的情节要素。"""
    if not isinstance(chapter_outline, list):
        return 0

    documents: list[str] = []
    ids: list[str] = []

    for ch in chapter_outline:
        if not isinstance(ch, dict):
            continue
        ch_num = ch.get("chapter_number", "")
        parts = [f"[章节大纲-第{ch_num}章] {ch.get('title', '')}"]
        if ch.get("plot_summary"):
            parts.append(f"情节摘要：{ch['plot_summary']}")
        if ch.get("key_events"):
            parts.append(f"关键事件：{', '.join(ch['key_events'])}")
        if ch.get("characters"):
            parts.append(f"涉及人物：{', '.join(ch['characters'])}")
        if ch.get("location"):
            parts.append(f"场景地点：{ch['location']}")
        if ch.get("conflict"):
            parts.append(f"本章冲突：{ch['conflict']}")
        if ch.get("character_changes"):
            parts.append(f"人物变化：{ch['character_changes']}")
        if ch.get("chapter_hook"):
            parts.append(f"章末钩子：{ch['chapter_hook']}")
        documents.append(" ".join(parts))
        ids.append(f"outline_ch_{ch_num}")

    print(f"[RAG-IDX] 章节大纲待索引: documents={len(documents)}条", flush=True)
    if not documents:
        return 0

    collection_name = get_novel_collection_name(novel_id, "chapter_semantics")
    collection = chroma_client.get_or_create_collection(collection_name)
    try:
        existing = collection.get(where={"source": "outline"})
        existing_count = len(existing.get("ids", [])) if existing else 0
        if existing_count:
            print(f"[RAG-IDX] 清理旧章纲索引: 删除{existing_count}条", flush=True)
            collection.delete(ids=existing["ids"])
    except Exception as e:
        print(f"[RAG-IDX] 清理旧章纲索引失败(忽略): {type(e).__name__}: {e}", flush=True)

    metadatas = [{"source": "outline", "type": "chapter_outline"}] * len(documents)
    try:
        await upsert_to_collection(
            novel_id=novel_id,
            collection_type="chapter_semantics",
            documents=documents,
            ids=ids,
            metadatas=metadatas,
        )
        print(f"[RAG-IDX] 章节大纲索引成功: {len(documents)}条已写入chapter_semantics", flush=True)
    except Exception as e:
        print(f"[RAG-IDX] 章节大纲索引失败: {type(e).__name__}: {e}", flush=True)
        return 0

    return len(documents)
