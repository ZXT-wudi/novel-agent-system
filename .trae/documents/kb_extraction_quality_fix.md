# 知识库提取质量优化方案

## 问题概述

用户在提取完一卷内容后发现 4 个质量问题：

| # | 问题 | 根因 |
|---|------|------|
| 1 | 时间线有 16 条记录但前端不显示 | `get_kb_overview` 返回全卷总数，前端按卷过滤查询时返回 0 条 |
| 2 | 角色类未去重（"鲁迪乌斯" vs "鲁迪"） | `_dedup_entries` 仅做精确名称匹配，无别名识别 |
| 3 | 角色名跨卷不一致（"女仆" = "莉莉雅"） | 章摘要的 `characters` 数组由 LLM 逐章自由命名，无标准化映射 |
| 4 | 事件类记录散乱 | 三路并行提取（主线/感情/成长）后仅按名称去重，同事件不同名 = 多条 |

## 回答核心问题：需要从章摘要开始修改吗？

- **角色名一致性（问题 3）**：✅ 是。角色名的根源在章摘要 `characters` 数组，需在提取后、派生前插入标准化步骤
- **角色去重（问题 2）**：✅ 间接是。基于标准化后的角色名 + 别名识别，才能正确去重
- **事件散乱（问题 4）**：❌ 否。散乱根因在 `_derive_volume_events` 三路合并后无整合，修改派生阶段即可
- **时间线显示（问题 1）**：❌ 否。纯前端 + API 显示问题，与提取逻辑无关

## 当前架构（已确认）

### 数据流
```
_extract_chapter_summaries_batch()   ← 章摘要（characters 数组是角色名根源）
         ↓
  chapters_data (list[dict])
         ↓
_derive_volume_all()                ← 并行派生 6 类
  ├─ _derive_key_characters()       ← 角色提取，输出 {name, content}，无 aliases
  ├─ _derive_volume_events()         ← 三路并行(main/romance/growth) + 名称去重
  ├─ _derive_timeline()
  ├─ _derive_factions()
  ├─ _derive_settings()
  └─ _derive_worldview_with_dedup()
         ↓
  KnowledgeEntry 创建 → db.flush()
         ↓
  ChromaDB 写入 → _cross_volume_dedup() → db.commit()
```

### 关键代码位置（已确认）
- `kb_service.py` L674-721: `_extract_chapter_summaries_batch`
- `kb_service.py` L814-873: `_derive_key_characters`（无 aliases 字段）
- `kb_service.py` L876-927: `_derive_volume_events`（L918-926 仅名称去重）
- `kb_service.py` L928-953: `_derive_timeline`
- `kb_service.py` L1078-1103: `_derive_volume_all`
- `kb_service.py` L1150-1224: `_cross_volume_dedup`（距离 ≤ 0.15，太严格）
- `kb_service.py` L1441-1442: 章摘要提取 → chapters_data
- `kb_service.py` L1482: `_derive_volume_all(chapters_data, ...)`
- `kb_service.py` L1483-1510: KnowledgeEntry 创建（L1489-1495 event 的 attrs）
- `kb_service.py` L190-233: `get_kb_overview`（无 volume 参数，返回全卷总数）
- `knowledge_bases.py` L110-115: `GET /{kb_id}/overview`（无 volume 参数）
- `knowledge-base.js` L329-343: `kbSelectVolume`（用缓存 overview，不重新获取）
- `knowledge-base.js` L359-368: `loadKBSectionEntries`（带 volume 过滤查询）

---

## 修改方案

### 修改 1：时间线前端显示修复

**问题**：`get_kb_overview` 返回全卷总数（如 timeline=16），但切换到某卷后 `loadKBSectionEntries` 按卷过滤查询返回 0 条 → "标题显示16但内容为空"

**方案**：overview API 加 volume 参数，前端切换卷时重新获取

#### 后端修改

**文件**: `app/services/kb_service.py` L190-233

`get_kb_overview` 增加 `volume` 参数：

```python
async def get_kb_overview(db: AsyncSession, kb_id: int, volume: int | None = None) -> dict:
    stmt = select(KnowledgeEntry).where(KnowledgeEntry.kb_id == kb_id)
    if volume is not None:
        stmt = stmt.where(or_(KnowledgeEntry.volume == volume, KnowledgeEntry.volume.is_(None)))
    stmt = stmt.order_by(KnowledgeEntry.category, KnowledgeEntry.created_at.desc())
    result = await db.execute(stmt)
    entries = result.scalars().all()
    # ... 后续逻辑不变
```

**文件**: `app/api/knowledge_bases.py` L110-115

`get_kb_overview` 端点增加 volume 查询参数：

```python
@router.get("/{kb_id}/overview")
async def get_kb_overview(
    kb_id: int,
    volume: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get_kb(db, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return await kb_service.get_kb_overview(db, kb_id, volume)
```

#### 前端修改

**文件**: `static/js/knowledge-base.js` L329-343

`kbSelectVolume` 切换卷时重新获取 overview：

```javascript
async function kbSelectVolume(volNum) {
    kbCurrentVolume = volNum;
    document.querySelectorAll(".kb-vol-tab").forEach(btn => {
        const v = btn.dataset.vol;
        const isActive = (v === "all") ? (kbCurrentVolume == null) : (Number(v) === kbCurrentVolume);
        btn.classList.toggle("active", isActive);
    });
    // 重新获取卷过滤后的 overview
    try {
        const overview = await apiGet(
            `/api/knowledge-bases/${kbCurrentId}/overview${kbCurrentVolume != null ? `?volume=${kbCurrentVolume}` : ""}`
        );
        kbDetailCache = { ...kbDetailCache, overview };
        renderKBDetail(kbDetailCache.kb, overview);
    } catch (e) {
        // 静默失败，保持现状
    }
}
```

注意：`renderKBDetail` 内部已调用 `loadKBSectionEntries`，重新渲染后会自动按新 volume 加载条目。

---

### 修改 2：角色名标准化（核心）

**问题**：章摘要 `characters` 数组由 LLM 逐章自由命名，"鲁迪"/"鲁迪乌斯"/"女仆" 各卷不一致

**方案**：在章摘要提取后、派生前，插入 `_normalize_character_names` 步骤

#### 新增函数：`_normalize_character_names`

**文件**: `app/services/kb_service.py`（新增，位于 `_extract_chapter_summaries_batch` 之后，约 L722）

```python
async def _normalize_character_names(
    chapters_data: list[dict], volume_number: int, volume_title: str,
    existing_canonical: dict[str, list[str]], semaphore: asyncio.Semaphore
) -> dict[str, list[str]]:
    """标准化角色名，返回 {canonical_name: [aliases]} 映射。

    existing_canonical: 之前各卷已确立的标准名→别名映射（可为空）
    """
    # 1. 收集本卷所有角色名
    all_names: list[str] = []
    for ch in chapters_data:
        for name in (ch.get("characters") or []):
            n = str(name).strip()
            if n and n not in all_names:
                all_names.append(n)

    if not all_names:
        return {}

    # 2. 构建已有标准名列表（供 LLM 参考）
    known_list = "\n".join(
        f"- {cano}（别名: {', '.join(alis) if alis else '无'}）"
        for cano, alis in existing_canonical.items()
    ) or "（暂无已知角色）"

    # 3. LLM 识别别名并映射到标准名
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
    async with semaphore:
        try:
            resp = await llm_client.chat(messages, temperature=0.2, max_tokens=2048)
        except Exception:
            return {}
    data = _parse_json_response(resp)
    if not isinstance(data, dict):
        return {}

    # 4. 构建 name→canonical 映射，同时合并到 existing_canonical
    mappings = data.get("mappings", [])
    if not isinstance(mappings, list):
        return {}
    name_to_cano: dict[str, str] = {}
    result: dict[str, list[str]] = dict(existing_canonical)  # 继承已有
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
        # 合并到 result（去重）
        if cano in result:
            existing_aliases = set(result[cano])
            existing_aliases.update(alis)
            result[cano] = sorted(existing_aliases)
        else:
            result[cano] = sorted(set(alis))

    # 5. 原地标准化 chapters_data 中的角色名
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
```

#### 新增函数：`_load_existing_character_aliases`

**文件**: `app/services/kb_service.py`（新增，位于 `_normalize_character_names` 附近）

```python
async def _load_existing_character_aliases(db: AsyncSession, kb_id: int, current_vol: int) -> dict[str, list[str]]:
    """加载之前卷已提取的角色标准名与别名映射。"""
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
```

#### 集成到导入流程

**文件**: `app/services/kb_service.py` L1442 之后插入

```python
        chapters_data = await _extract_chapter_summaries_batch(vtext, vn, vol["title"])

        # 角色名标准化（新增）
        existing_aliases = await _load_existing_character_aliases(db, kb_id, vn)
        norm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
        canonical_map = await _normalize_character_names(
            chapters_data, vn, vol["title"], existing_aliases, norm_semaphore
        )
```

`canonical_map` 会在修改 3 中传给 `_derive_volume_all`，在修改 4 中用于创建 KnowledgeEntry 时附加 aliases。

---

### 修改 3：角色派生增加 aliases 字段

**问题**：`_derive_key_characters` 只输出 `{name, content}`，无别名信息

**方案**：`_derive_volume_all` 接收 `canonical_map`，传给 `_derive_key_characters`，角色条目附带 aliases

#### 修改 `_derive_volume_all` 签名

**文件**: `app/services/kb_service.py` L1078-1103

```python
async def _derive_volume_all(
    chapters_data: list[dict],
    volume_number: int,
    volume_title: str,
    cached_embs: list,
    emb_lock: asyncio.Lock,
    canonical_map: dict[str, list[str]],  # 新增
) -> dict:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
    chars, events, timeline, factions, settings = await asyncio.gather(
        _derive_key_characters(chapters_data, volume_number, volume_title, semaphore, canonical_map),
        _derive_volume_events(chapters_data, volume_number, volume_title, semaphore),
        _derive_timeline(chapters_data, volume_number, volume_title, semaphore),
        _derive_factions(chapters_data, volume_number, volume_title, semaphore),
        _derive_settings(chapters_data, volume_number, volume_title, semaphore),
    )
    # ... 后续不变
```

#### 修改 `_derive_key_characters` 签名 + 输出 aliases

**文件**: `app/services/kb_service.py` L814-873

签名增加 `canonical_map`，`_one` 返回值增加 `aliases`：

```python
async def _derive_key_characters(
    chapters_data: list[dict], volume_number: int, volume_title: str,
    semaphore: asyncio.Semaphore, canonical_map: dict[str, list[str]]  # 新增
) -> list[dict]:
    # ... 前面逻辑不变 ...

    async def _one(name: str):
        # ... 不变 ...
        if content:
            # 查找该角色的别名
            aliases = canonical_map.get(name, [])
            return {"name": name, "content": content, "aliases": aliases}
        return None

    # ... 后续不变 ...
```

#### 导入流程调用处修改

**文件**: `app/services/kb_service.py` L1482

```python
        derived = await _derive_volume_all(chapters_data, vn, vol["title"], cached_embs, emb_lock, canonical_map)
```

#### KnowledgeEntry 创建处增加 aliases

**文件**: `app/services/kb_service.py` L1489-1495（attrs 构建）

```python
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
```

---

### 修改 4：事件 LLM 重整合

**问题**：三路并行提取后仅按名称去重，"鲁迪与莉莉雅相遇" 和 "鲁迪和莉莉雅的初遇" 成两条

**方案**：三路合并后增加 `_consolidate_events` LLM 重整合步骤

#### 新增函数：`_consolidate_events`

**文件**: `app/services/kb_service.py`（新增，位于 `_derive_volume_events` 之后，约 L928）

```python
async def _consolidate_events(
    events: list[dict], volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    """LLM 重整合散乱事件，合并重复、统一叙述。"""
    if len(events) <= 1:
        return events

    # 序列化事件供 LLM 分析
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

    # 按输出顺序构建最终事件列表
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
        # 确定 subtype：取 source 中优先级最高的
        subtypes = [events[i].get("subtype", "") for i in source_ids if 0 <= i < len(events)]
        chosen_sub = min(subtypes, key=lambda s: subtype_priority.get(s, 99)) if subtypes else ""
        item = {"name": name, "content": content}
        if chosen_sub:
            item["subtype"] = chosen_sub
        # 保留 characters 字段（取并集）
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
```

#### 集成到 `_derive_volume_events`

**文件**: `app/services/kb_service.py` L918-927

在三路名称去重后，调用 `_consolidate_events`：

```python
    merged: list[dict] = []
    seen_names: set = set()
    for it in rom_evs + gro_evs + main_evs:
        name = (it.get("name") or "").strip().lower()
        if name and name in seen_names:
            continue
        if name:
            seen_names.add(name)
        merged.append(it)

    # LLM 重整合（新增）
    merged = await _consolidate_events(merged, volume_number, volume_title, semaphore)
    return merged
```

---

### 修改 5：跨卷角色去重增强

**问题**：`_cross_volume_dedup` 仅靠 embedding 距离 ≤ 0.15 判断，"鲁迪" vs "鲁迪乌斯" 的 embedding 距离可能超过阈值 → 不合并

**方案**：角色类增加精确名称匹配 + aliases 匹配的快速通道

#### 修改 `_cross_volume_dedup`

**文件**: `app/services/kb_service.py` L1150-1224

在 embedding 查询之前，对 character 类做精确名称 + aliases 匹配：

```python
async def _cross_volume_dedup(
    db: AsyncSession, kb_id: int, current_vol: int, new_entries: list[KnowledgeEntry]
) -> list[dict]:
    relations_added: list[dict] = []

    # 预加载已有角色条目的 title→entry 映射（含 aliases）
    existing_chars: dict[str, KnowledgeEntry] = {}
    char_alias_to_cano: dict[str, str] = {}
    if new_entries and any(e.category == "character" for e in new_entries):
        char_result = await db.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.kb_id == kb_id,
                KnowledgeEntry.category == "character",
                KnowledgeEntry.volume != current_vol,
            )
        )
        for ce in char_result.scalars().all():
            existing_chars[ce.title.lower()] = ce
            attrs = ce.attributes if isinstance(ce.attributes, dict) else {}
            for a in (attrs.get("aliases") or []):
                char_alias_to_cano[str(a).lower()] = ce.title.lower()

    for entry in list(new_entries):
        if entry.category in (KB_CATEGORY_CHAPTER_SUMMARY, KB_CATEGORY_VOLUME_EVENT):
            continue

        # 角色类：先做精确名称 + aliases 匹配（快速通道）
        if entry.category == "character":
            entry_title_lower = (entry.title or "").lower()
            matched_entry = None
            # 1. 标题精确匹配（忽略大小写）
            if entry_title_lower in existing_chars:
                matched_entry = existing_chars[entry_title_lower]
            # 2. 新条目标题是已有条目的别名
            elif entry_title_lower in char_alias_to_cano:
                cano_lower = char_alias_to_cano[entry_title_lower]
                matched_entry = existing_chars.get(cano_lower)
            # 3. 新条目的 aliases 包含已有条目标题
            else:
                entry_attrs = entry.attributes if isinstance(entry.attributes, dict) else {}
                entry_aliases = [str(a).lower() for a in (entry_attrs.get("aliases") or [])]
                for al in entry_aliases:
                    if al in existing_chars:
                        matched_entry = existing_chars[al]
                        break
                    if al in char_alias_to_cano:
                        matched_entry = existing_chars.get(char_alias_to_cano[al])
                        break

            if matched_entry:
                # 合并内容
                merged = await _llm_merge_entries(matched_entry, entry)
                if merged:
                    matched_entry.content = merged
                    # 合并 aliases
                    old_attrs = matched_entry.attributes if isinstance(matched_entry.attributes, dict) else {}
                    new_attrs = entry.attributes if isinstance(entry.attributes, dict) else {}
                    all_aliases = set(old_attrs.get("aliases") or [])
                    all_aliases.add(entry.title or "")
                    all_aliases.update(new_attrs.get("aliases") or [])
                    old_attrs["aliases"] = sorted(all_aliases)
                    matched_entry.attributes = old_attrs
                    old_doc = f"[{matched_entry.category}] {matched_entry.title}: {matched_entry.content}"
                    old_meta = {
                        "category": matched_entry.category,
                        "title": matched_entry.title,
                        "source": matched_entry.source,
                        "volume_number": matched_entry.volume,
                    }
                    try:
                        await update_in_kb(
                            kb_id,
                            [f"kb_{kb_id}_entry_{matched_entry.id}"],
                            [old_doc], [old_meta],
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
                relations_added.append({
                    "from_volume": matched_entry.volume,
                    "to_volume": current_vol,
                    "description": f"角色《{matched_entry.title}》跨卷合并（含别名识别）",
                    "title": matched_entry.title,
                })
                continue

        # 其他类（含未匹配的角色）：走 embedding 路径（现有逻辑不变）
        doc = f"[{entry.category}] {entry.title}: {entry.content}"
        try:
            res = await query_kb(kb_id, doc, n_results=3)
        except Exception:
            continue
        # ... 后续 embedding 逻辑完全不变 ...
```

---

## 修改文件汇总

| 文件 | 修改内容 | 涉及行号 |
|------|----------|----------|
| `app/services/kb_service.py` | `get_kb_overview` 加 volume 参数 | L190-233 |
| `app/services/kb_service.py` | 新增 `_normalize_character_names` | L722 后新增 |
| `app/services/kb_service.py` | 新增 `_load_existing_character_aliases` | L722 后新增 |
| `app/services/kb_service.py` | `_derive_key_characters` 加 canonical_map + aliases | L814-873 |
| `app/services/kb_service.py` | `_derive_volume_events` 调用 `_consolidate_events` | L918-927 |
| `app/services/kb_service.py` | 新增 `_consolidate_events` | L928 后新增 |
| `app/services/kb_service.py` | `_derive_volume_all` 加 canonical_map 参数 | L1078-1103 |
| `app/services/kb_service.py` | `_cross_volume_dedup` 增加角色精确匹配 | L1150-1224 |
| `app/services/kb_service.py` | 导入流程插入标准化步骤 + canonical_map 传递 + aliases 存储 | L1442, L1482, L1489-1495 |
| `app/api/knowledge_bases.py` | overview 端点加 volume 参数 | L110-115 |
| `static/js/knowledge-base.js` | `kbSelectVolume` 重新获取 overview | L329-343 |

## 验证步骤

1. **时间线显示**：导入一卷后，切换到该卷，确认时间线条目正常显示（不再"标题16内容空"）
2. **角色去重**：导入含"鲁迪"/"鲁迪乌斯"的多卷后，确认角色类无重复条目，aliases 字段含别名
3. **角色名一致性**：第一卷角色名确定后，后续卷沿用相同标准名
4. **别名识别**：检查"女仆"是否映射到"莉莉雅"，且不重复记录
5. **事件整合**：导入一卷后检查事件类，确认无明显重复散乱条目
6. **运行检查**：`python -c "import app.services.kb_service"` 确认无语法错误

## 假设与决策

- 用户已确认：重新提取该卷（删除已有数据重新导入）
- 用户已确认：时间线症状是"标题显示16但内容为空"
- 用户已确认：事件整合用 LLM 重整合方式
- `_normalize_character_names` 用 temperature=0.2 保证命名一致性
- `_consolidate_events` 用 temperature=0.2 + max_tokens=4096 保证整合质量
- 跨卷角色去重优先用精确名称+别名匹配，embedding 作为兜底
