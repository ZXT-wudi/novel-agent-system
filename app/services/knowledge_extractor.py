from app.llm.siliconflow import llm_client, LLMError
from app.models.story_knowledge import StoryKnowledge
from app.models.character_image import CharacterImage
from app.rag.chroma_client import chroma_client, get_novel_collection_name
from app.rag.retriever import add_to_collection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json


KNOWLEDGE_EXTRACTION_PROMPT = """你是一位小说分析专家，需要从章节内容中准确提取结构化信息，供后续章节保持设定一致与上下文衔接使用。

【提取准则】
- 只提取本章正文中实际出现、可明确确认的信息，不臆测、不补脑未交代的设定；
- 角色描述聚焦"本章实际表现"，而非泛泛的角色标签；
- 角色关系只在文本有依据时提取，关系类型严格限定；
- 世界观元素只提取本章真正涉及、有名号或明确规则的条目，不把普通名词当设定；
- 同一角色/关系/元素避免重复登记；状态（active/departed/dead）依据本章事实判定。

请提取以下信息，输出严格JSON：
{
  "characters": [
    {"name": "角色名", "role": "主角/配角/龙套", "description": "角色描述和本章表现", "status": "active/departed/dead"}
  ],
  "character_relations": [
    {"from": "角色A", "to": "角色B", "type": "师徒/敌对/盟友/恋人/亲属/同门", "description": "关系描述"}
  ],
  "world_elements": [
    {"category": "功法/地点/物品/势力/规则", "name": "名称", "description": "描述", "related_characters": ["相关角色"]}
  ],
  "chapter_summary": "本章摘要，200字以内，用平实陈述句，避免排比堆叠、破折号及不是而是翻转句",
  "plot_points": ["关键情节点1", "关键情节点2"]
}

注意：
- 角色关系类型只能是：师徒、敌对、盟友、恋人、亲属、同门
- 世界观元素类别只能是：功法、地点、物品、势力、规则
- 只输出JSON，不要输出其他内容"""


async def extract_chapter_knowledge(
    db: AsyncSession,
    novel_id: int,
    chapter_number: int,
    chapter_content: str,
    outline_item: dict | None = None,
) -> StoryKnowledge:
    outline_text = ""
    if outline_item:
        outline_text = (
            f"\n章节大纲参考：\n"
            f"标题：{outline_item.get('title', '')}\n"
            f"情节摘要：{outline_item.get('plot_summary', '')}\n"
            f"关键事件：{', '.join(outline_item.get('key_events', []))}\n"
            f"涉及人物：{', '.join(outline_item.get('characters', []))}\n"
            f"场景地点：{outline_item.get('location', '')}\n"
            f"本章冲突：{outline_item.get('conflict', '')}\n"
            f"人物变化：{outline_item.get('character_changes', '')}\n"
            f"章末钩子：{outline_item.get('chapter_hook', '')}"
        )

    messages = [
        {"role": "system", "content": KNOWLEDGE_EXTRACTION_PROMPT},
        {"role": "user", "content": f"请从以下章节内容中提取结构化信息：{outline_text}\n\n章节内容：\n{chapter_content[:5000]}"},
    ]

    try:
        response = await llm_client.chat(messages, temperature=0.3, max_tokens=4096)
        data = _parse_knowledge_response(response)
    except LLMError:
        data = {
            "characters": [],
            "character_relations": [],
            "world_elements": [],
            "chapter_summary": chapter_content[:200],
            "plot_points": [],
        }

    result = await db.execute(
        select(StoryKnowledge).where(
            StoryKnowledge.novel_id == novel_id,
            StoryKnowledge.chapter_number == chapter_number,
        )
    )
    knowledge = result.scalar_one_or_none()

    if knowledge:
        knowledge.characters = data.get("characters", [])
        knowledge.character_relations = data.get("character_relations", [])
        knowledge.world_elements = data.get("world_elements", [])
        knowledge.chapter_summary = data.get("chapter_summary", "")
        knowledge.plot_points = data.get("plot_points", [])
    else:
        knowledge = StoryKnowledge(
            novel_id=novel_id,
            chapter_number=chapter_number,
            characters=data.get("characters", []),
            character_relations=data.get("character_relations", []),
            world_elements=data.get("world_elements", []),
            chapter_summary=data.get("chapter_summary", ""),
            plot_points=data.get("plot_points", []),
        )
        db.add(knowledge)

    await db.commit()
    await db.refresh(knowledge)

    try:
        await _index_extracted_knowledge_to_rag(novel_id, chapter_number, data)
    except Exception as e:
        print(f"[RAG] 章节知识索引失败(ch{chapter_number}): {e}")

    return knowledge


async def _index_extracted_knowledge_to_rag(novel_id: int, chapter_number: int, data: dict) -> int:
    """把章节抽取的角色/关系/世界观元素索引进 RAG world_knowledge，使后续章节写作可检索。"""
    documents: list[str] = []
    ids: list[str] = []

    for c in (data.get("characters") or []):
        if isinstance(c, dict) and c.get("name"):
            parts = [f"[章节{chapter_number}-人物] {c.get('name', '')}({c.get('role', '')})"]
            for k in ("description", "personality", "background", "status"):
                if c.get(k):
                    parts.append(f"{k}:{c[k]}")
            documents.append(" ".join(parts))
            ids.append(f"extract_ch{chapter_number}_char_{str(c.get('name', '')).replace(' ', '_')}")

    for r in (data.get("character_relations") or []):
        if isinstance(r, dict) and r.get("from") and r.get("to"):
            documents.append(
                f"[章节{chapter_number}-关系] {r.get('from', '')} -> {r.get('to', '')}"
                f"({r.get('type', '')}): {r.get('description', '')}"
            )
            ids.append(f"extract_ch{chapter_number}_rel_{r.get('from','')}_{r.get('to','')}")

    for e in (data.get("world_elements") or []):
        if isinstance(e, dict) and e.get("name"):
            documents.append(
                f"[章节{chapter_number}-世界观] [{e.get('category', '')}] {e.get('name', '')}: {e.get('description', '')}"
            )
            ids.append(f"extract_ch{chapter_number}_elem_{str(e.get('name', '')).replace(' ', '_')}")

    if not documents:
        return 0

    collection_name = get_novel_collection_name(novel_id, "world_knowledge")
    collection = chroma_client.get_or_create_collection(collection_name)
    try:
        existing = collection.get(where={"source": "extract", "chapter": chapter_number})
        if existing and existing.get("ids"):
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    metadatas = [{"source": "extract", "chapter": chapter_number}] * len(documents)
    await add_to_collection(
        novel_id=novel_id,
        collection_type="world_knowledge",
        documents=documents,
        ids=ids,
        metadatas=metadatas,
    )
    return len(documents)


def _parse_knowledge_response(response: str) -> dict:
    try:
        clean = response.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1])
        result = json.loads(clean)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(response[start:end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass
    return {
        "characters": [],
        "character_relations": [],
        "world_elements": [],
        "chapter_summary": "",
        "plot_points": [],
    }


async def get_all_characters(db: AsyncSession, novel_id: int) -> list[dict]:
    result = await db.execute(
        select(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id).order_by(StoryKnowledge.chapter_number)
    )
    all_knowledge = result.scalars().all()

    character_map = {}
    for k in all_knowledge:
        for char in (k.characters or []):
            if not isinstance(char, dict):
                continue
            name = char.get("name", "")
            if not name:
                continue
            if name in character_map:
                existing = character_map[name]
                if char.get("role", "") in ("主角", "配角") and existing.get("role", "") == "龙套":
                    existing["role"] = char["role"]
                if char.get("description", ""):
                    existing["description"] = char["description"]
                if char.get("status", "") in ("dead", "departed"):
                    existing["status"] = char["status"]
                if k.chapter_number not in existing.get("chapters", []):
                    existing.setdefault("chapters", []).append(k.chapter_number)
            else:
                character_map[name] = {
                    "name": name,
                    "role": char.get("role", "龙套"),
                    "description": char.get("description", ""),
                    "status": char.get("status", "active"),
                    "first_appear": char.get("first_appear", k.chapter_number),
                    "chapters": [k.chapter_number],
                }

    return list(character_map.values())


async def get_all_relations(db: AsyncSession, novel_id: int) -> list[dict]:
    result = await db.execute(
        select(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id).order_by(StoryKnowledge.chapter_number)
    )
    all_knowledge = result.scalars().all()

    seen = set()
    relations = []
    for k in all_knowledge:
        for rel in (k.character_relations or []):
            if not isinstance(rel, dict):
                continue
            key = (rel.get("from", ""), rel.get("to", ""), rel.get("type", ""))
            if key not in seen:
                seen.add(key)
                relations.append(rel)

    return relations


async def get_all_world_elements(db: AsyncSession, novel_id: int) -> list[dict]:
    result = await db.execute(
        select(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id).order_by(StoryKnowledge.chapter_number)
    )
    all_knowledge = result.scalars().all()

    element_map = {}
    for k in all_knowledge:
        for elem in (k.world_elements or []):
            if not isinstance(elem, dict):
                continue
            name = elem.get("name", "")
            if not name:
                continue
            if name in element_map:
                existing = element_map[name]
                if elem.get("description", ""):
                    existing["description"] = elem["description"]
                for rc in elem.get("related_characters", []):
                    if rc not in existing.get("related_characters", []):
                        existing.setdefault("related_characters", []).append(rc)
                if k.chapter_number not in existing.get("chapters", []):
                    existing.setdefault("chapters", []).append(k.chapter_number)
            else:
                element_map[name] = {
                    "category": elem.get("category", ""),
                    "name": name,
                    "description": elem.get("description", ""),
                    "related_characters": elem.get("related_characters", []),
                    "chapters": [k.chapter_number],
                }

    return list(element_map.values())


async def build_graph_data(db: AsyncSession, novel_id: int) -> dict:
    from app.models.chapter import Chapter
    from app.models.novel import Novel

    characters = await get_all_characters(db, novel_id)
    relations = await get_all_relations(db, novel_id)
    world_elements = await get_all_world_elements(db, novel_id)

    ch_result = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_number)
    )
    chapters = ch_result.scalars().all()

    novel_result = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_result.scalar_one_or_none()
    full_outline = novel.full_outline if novel else {}

    nodes = []
    links = []

    for char in characters:
        nodes.append({
            "id": f"char_{char['name']}",
            "type": "character",
            "name": char["name"],
            "role": char.get("role", "配角"),
            "description": char.get("description", ""),
            "chapters": char.get("chapters", []),
        })

    for ch in chapters:
        nodes.append({
            "id": f"chapter_{ch.chapter_number}",
            "type": "chapter",
            "name": f"第{ch.chapter_number}章 {ch.title or ''}",
            "number": ch.chapter_number,
            "chapters": [ch.chapter_number],
        })

    for elem in world_elements:
        nodes.append({
            "id": f"world_{elem['name']}",
            "type": "world",
            "name": elem["name"],
            "category": elem.get("category", ""),
            "description": elem.get("description", ""),
            "chapters": elem.get("chapters", []),
        })

    for rel in relations:
        links.append({
            "source": f"char_{rel.get('from', '')}",
            "target": f"char_{rel.get('to', '')}",
            "type": rel.get("type", ""),
            "label": rel.get("type", ""),
        })

    for char in characters:
        for ch_num in char.get("chapters", []):
            links.append({
                "source": f"char_{char['name']}",
                "target": f"chapter_{ch_num}",
                "type": "appears_in",
                "label": "出场",
            })

    for elem in world_elements:
        for rc in elem.get("related_characters", []):
            links.append({
                "source": f"char_{rc}",
                "target": f"world_{elem['name']}",
                "type": "related",
                "label": "关联",
            })

    regions = _build_world_regions(world_elements, full_outline)
    stages = await _build_story_stages(db, novel_id, full_outline, chapters)

    volumes_list: list[dict] = []
    vols = (full_outline or {}).get("volumes", []) if full_outline else []
    for vol in vols:
        cr = vol.get("chapter_range")
        if (
            not cr
            or len(cr) < 2
            or cr[0] is None
            or cr[1] is None
            or cr[1] < cr[0]
        ):
            continue
        vol_num = vol.get("volume_number", "?")
        title = vol.get("title", "")
        name = f"第{vol_num}卷 {title}" if title else f"第{vol_num}卷"
        volumes_list.append({"name": name, "range": [int(cr[0]), int(cr[1])]})
    if not volumes_list:
        nums = [c.chapter_number for c in chapters] if chapters else []
        if nums:
            lo, hi = min(nums), max(nums)
            block = 25
            for start in range(lo, hi + 1, block):
                end = min(start + block - 1, hi)
                volumes_list.append({"name": f"第{start}-{end}章", "range": [start, end]})

    from app.services.image_service import get_novel_image_maps

    images = await get_novel_image_maps(db, novel_id)

    ci_result = await db.execute(
        select(CharacterImage)
        .where(CharacterImage.novel_id == novel_id)
        .order_by(CharacterImage.id.desc())
    )
    character_images = {}
    for r in ci_result.scalars().all():
        if r.character_name in character_images:
            continue
        path = r.image_path if r.image_path.startswith("/") else f"/static/character_images/{r.image_path}"
        character_images[r.character_name] = path

    return {
        "nodes": nodes,
        "links": links,
        "regions": regions,
        "stages": stages,
        "volumes": volumes_list,
        "images": images,
        "character_images": character_images,
    }


async def _build_story_stages(
    db: AsyncSession, novel_id: int, full_outline: dict, chapters: list
) -> list[dict]:
    stage_defs: list[dict] = []
    volumes = (full_outline or {}).get("volumes", []) if full_outline else []

    if volumes:
        for vol in volumes:
            cr = vol.get("chapter_range")
            if (
                not cr
                or len(cr) < 2
                or cr[0] is None
                or cr[1] is None
                or cr[1] < cr[0]
            ):
                continue
            vol_num = vol.get("volume_number", "?")
            title = vol.get("title", "")
            name = f"第{vol_num}卷 {title}" if title else f"第{vol_num}卷"
            stage_defs.append({"name": name, "chapter_range": [int(cr[0]), int(cr[1])]})

    if not stage_defs:
        nums = [c.chapter_number for c in chapters] if chapters else []
        if not nums:
            kn_result = await db.execute(
                select(StoryKnowledge.chapter_number).where(
                    StoryKnowledge.novel_id == novel_id
                )
            )
            nums = [r[0] for r in kn_result.all() if r[0] is not None]
        if nums:
            lo, hi = min(nums), max(nums)
            block = 25
            for start in range(lo, hi + 1, block):
                end = min(start + block - 1, hi)
                stage_defs.append(
                    {"name": f"第{start}-{end}章", "chapter_range": [start, end]}
                )

    if not stage_defs:
        stage_defs.append({"name": "起始阶段", "chapter_range": [1, 1]})

    kn_result = await db.execute(
        select(StoryKnowledge)
        .where(StoryKnowledge.novel_id == novel_id)
        .order_by(StoryKnowledge.chapter_number)
    )
    all_knowledge = kn_result.scalars().all()

    stages: list[dict] = []
    for stage_index, sd in enumerate(stage_defs):
        lo, hi = sd["chapter_range"]
        stage_knowledge = [k for k in all_knowledge if lo <= k.chapter_number <= hi]

        char_map: dict[str, dict] = {}
        for k in stage_knowledge:
            for char in (k.characters or []):
                if not isinstance(char, dict):
                    continue
                name = char.get("name", "")
                if not name:
                    continue
                role = char.get("role", "龙套")
                if name in char_map:
                    existing = char_map[name]
                    if role == "主角":
                        existing["role"] = "主角"
                    elif role == "配角" and existing["role"] == "龙套":
                        existing["role"] = "配角"
                    if char.get("description", ""):
                        existing["description"] = char["description"]
                    if char.get("status", ""):
                        existing["status"] = char["status"]
                    if k.chapter_number not in existing["appeared_chapters"]:
                        existing["appeared_chapters"].append(k.chapter_number)
                else:
                    char_map[name] = {
                        "name": name,
                        "role": role,
                        "description": char.get("description", ""),
                        "status": char.get("status", "active"),
                        "appeared_chapters": [k.chapter_number],
                        "relations": [],
                    }

        seen_rel: set[tuple] = set()
        for k in stage_knowledge:
            for rel in (k.character_relations or []):
                if not isinstance(rel, dict):
                    continue
                f, t, ty = rel.get("from", ""), rel.get("to", ""), rel.get("type", "")
                if not f or not t or not ty:
                    continue
                key = (f, t, ty)
                if key in seen_rel:
                    continue
                seen_rel.add(key)
                if f in char_map and t in char_map:
                    desc = rel.get("description", "")
                    char_map[f]["relations"].append(
                        {"target": t, "type": ty, "description": desc}
                    )
                    char_map[t]["relations"].append(
                        {"target": f, "type": ty, "description": desc}
                    )

        char_list = list(char_map.values())
        for c in char_list:
            c["is_protagonist"] = c["role"] == "主角"
        char_list.sort(key=lambda c: (0 if c["is_protagonist"] else 1, c["name"]))

        img_result = await db.execute(
            select(CharacterImage).where(
                CharacterImage.novel_id == novel_id,
                CharacterImage.stage_index == stage_index,
            )
        )
        img_map = {r.character_name: r.image_path for r in img_result.scalars().all()}
        for c in char_list:
            c["image_url"] = img_map.get(c["name"], "")

        stages.append(
            {
                "name": sd["name"],
                "chapter_range": sd["chapter_range"],
                "characters": char_list,
            }
        )

    return stages


def _build_world_regions(world_elements: list[dict], full_outline: dict) -> list[dict]:
    regions = []
    location_elements = [e for e in world_elements if e.get("category") == "地点"]

    if not location_elements and not full_outline:
        return regions

    if location_elements:
        for i, loc in enumerate(location_elements):
            region = {
                "id": f"region_{loc['name']}",
                "name": loc["name"],
                "description": loc.get("description", ""),
                "elements": [],
                "characters": loc.get("related_characters", []),
                "chapters": loc.get("chapters", []),
            }
            for elem in world_elements:
                if elem.get("category") != "地点" and elem["name"] != loc["name"]:
                    shared_chars = set(elem.get("related_characters", [])) & set(loc.get("related_characters", []))
                    if shared_chars or elem.get("category") in ("势力", "规则"):
                        region["elements"].append({
                            "name": elem["name"],
                            "category": elem.get("category", ""),
                            "description": elem.get("description", ""),
                        })
            regions.append(region)
    elif full_outline:
        volumes = full_outline.get("volumes", [])
        for vol_idx, vol in enumerate(volumes):
            vol_title = vol.get("title", f"第{vol.get('volume_number', '?')}卷")
            region = {
                "id": f"region_vol_{vol.get('volume_number', vol_idx)}",
                "name": f"{vol_title}舞台",
                "description": vol.get("summary", ""),
                "elements": [],
                "characters": vol.get("key_characters", []),
                "chapters": list(range(
                    vol.get("chapter_range", [0, 0])[0],
                    vol.get("chapter_range", [0, 0])[1] + 1
                )) if vol.get("chapter_range") else [],
            }
            for event in vol.get("major_events", []):
                region["elements"].append({
                    "name": event,
                    "category": "事件",
                    "description": "",
                })
            regions.append(region)

    return regions
