# 知识库分类与整合优化方案

## 问题概述

用户在提取第一卷后发现 3 个分类质量问题：

| # | 问题 | 当前根因 |
|---|------|----------|
| 1 | "剑神流""水神流""北神流"出现在"势力"类 | `_derive_factions` prompt 太宽泛，将剑术流派当作势力提取 |
| 2 | "设定"类太杂乱（"治疗魔术""魔术分类""魔力来源"散乱） | `_derive_settings` 只提取不整合，无合并步骤 |
| 3 | "时间线"类太杂 | `_derive_timeline` 独立从章摘要提取，无法利用已提取的事件来浓缩 |

## 当前架构（已确认）

### 派生调用顺序（`_derive_volume_all` L1274-1300）

```
Phase 1 (asyncio.gather, 5路并行):
  ├─ _derive_key_characters()
  ├─ _derive_volume_events()   → events (含 _consolidate_events)
  ├─ _derive_timeline()         ← 独立提取，无法使用 events
  ├─ _derive_factions()         ← prompt 太宽泛
  └─ _derive_settings()         ← 只提取不整合

Phase 2 (sequential):
  └─ _derive_worldview_with_dedup()
```

**关键瓶颈**：timeline 和 events 在 Phase 1 并行执行，timeline 无法引用 events 结果。

### 当前 Prompt 分析

- **faction prompt**（L1159）：`"请提取该卷出现的势力/组织/阵营及其立场、成员、与主线冲突"` — 范围太宽，剑术流派被当作"流派/阵营"提取
- **worldview prompt**（L1219）：`"请提取该卷展现的世界观要素（地理/世界规则/体系/格局/风俗等）"` — 提到"体系"但不够明确
- **settings prompt**（L1187）：`"请提取与主线相关的设定（功法/地理/规则/道具/种族等）"` — 只提取不整合
- **timeline prompt**（L1131）：`"请据此梳理该卷时间线：按情节先后输出关键时间节点"` — 只用章摘要，不用事件

---

## 修改方案

### 修改 1：势力 prompt 收窄 + 世界观 prompt 扩展

**目标**：将剑术流派/技能体系从"势力"迁移到"世界观"

#### 修改 `_derive_factions` prompt

**文件**: `app/services/kb_service.py` L1159

```python
    prompt = f"""以下是第 {volume_number}卷《{volume_title}》各章摘要（含关键事件）。请提取该卷出现的势力/组织/阵营（有成员、有目标、有立场的团体，如国家、商会、骑士团、暗杀组织等）。
不要提取单纯的剑术流派/技能体系/魔法分类/武功招式——这些属于世界观设定，不是组织势力。
输出严格JSON（只输出JSON）：[{{"name":"势力/组织名称","content":"势力描述、成员、目的、立场"}}]
没有则输出 []。content 用平实陈述，不编造。

各章摘要：
{blob}"""
```

#### 修改 `_derive_worldview_with_dedup` prompt

**文件**: `app/services/kb_service.py` L1219

```python
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
```

### 修改 2：设定 LLM 整合

**目标**：将散乱的设定条目整合为有逻辑的分类条目

#### 新增函数：`_consolidate_settings`

**文件**: `app/services/kb_service.py`（新增，位于 `_derive_settings` 之后，约 L1210）

```python
async def _consolidate_settings(
    settings: list[dict], volume_number: int, volume_title: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    """LLM 整合散乱设定，将相关条目归并到统一分类条目。"""
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
```

#### 集成到 `_derive_settings`

**文件**: `app/services/kb_service.py` L1207（`return _dedup_entries(out)` 之前）

```python
    out = _dedup_entries(out)
    out = await _consolidate_settings(out, volume_number, volume_title, semaphore)
    return out
```

### 修改 3：时间线从章摘要+事件浓缩

**目标**：时间线利用已提取的事件来浓缩，只记录重要时间节点

#### 架构调整：`_derive_volume_all` 改为两阶段

**文件**: `app/services/kb_service.py` L1274-1300

```python
async def _derive_volume_all(
    chapters_data: list[dict],
    volume_number: int,
    volume_title: str,
    cached_embs: list,
    emb_lock: asyncio.Lock,
    canonical_map: dict[str, list[str]],
) -> dict:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
    # Phase 1: 4 路并行（不含 timeline）
    chars, events, factions, settings = await asyncio.gather(
        _derive_key_characters(chapters_data, volume_number, volume_title, semaphore, canonical_map),
        _derive_volume_events(chapters_data, volume_number, volume_title, semaphore),
        _derive_factions(chapters_data, volume_number, volume_title, semaphore),
        _derive_settings(chapters_data, volume_number, volume_title, semaphore),
    )
    # Phase 2: timeline（使用 events 结果）+ worldview 并行
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
```

#### 修改 `_derive_timeline` 签名 + prompt

**文件**: `app/services/kb_service.py` L1127-1152

```python
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
        events_text = "\n\n已提取的关键事件：\n" + "\n".join(event_lines)

    prompt = f"""以下是第 {volume_number}卷《{volume_title}》按章序排列的各章摘要{events_text and "及已提取的关键事件" or ""}。
请据此梳理该卷时间线：按情节先后输出**重要**时间节点（只记录推动情节发展的关键转折点，跳过琐碎细节）。
每个节点简要描述该时间发生的关键事件及其影响。
输出严格JSON（只输出JSON）：[{{"name":"时间节点/阶段","content":"关键事件与影响简述"}}]
没有则输出 []。不编造。各章已按章序，时间线应跟随章序。

各章摘要：
{blob}{events_text}"""
    messages = [
        {"role": "system", "content": "你是一位文学分析专家，擅长梳理小说时间线，注重简洁和重点。"},
        {"role": "user", "content": prompt},
    ]
    async with semaphore:
        try:
            resp = await llm_client.chat(messages, temperature=0.2, max_tokens=1536)
        except Exception:
            return []
    data = _parse_json_response(resp)
    out: list[dict] = []
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                out.append(it)
    return _dedup_entries(out)
```

---

## 修改文件汇总

| 文件 | 修改内容 | 涉及位置 |
|------|----------|----------|
| `app/services/kb_service.py` | `_derive_factions` prompt 收窄（排除剑术流派） | L1159 |
| `app/services/kb_service.py` | `_derive_worldview_with_dedup` prompt 扩展（明确含体系设定+整合指令） | L1219 |
| `app/services/kb_service.py` | 新增 `_consolidate_settings` 函数 | L1210 后新增 |
| `app/services/kb_service.py` | `_derive_settings` 调用 `_consolidate_settings` | L1207 |
| `app/services/kb_service.py` | `_derive_timeline` 签名增加 `events` 参数 + prompt 改为章摘要+事件浓缩 | L1127-1152 |
| `app/services/kb_service.py` | `_derive_volume_all` 改为两阶段：Phase1 提取 events→Phase2 timeline 用 events | L1274-1300 |

## 验证步骤

1. **势力→世界观迁移**：重新提取一卷后，检查"势力"类不再出现"剑神流""水神流"等流派，"世界观"类出现整合的体系条目
2. **设定整合**：检查"设定"类条目数量减少、条目名称为体系概括名（如"魔术体系"），content 含分子项描述
3. **时间线浓缩**：检查"时间线"类条目数量减少、每条为重要节点而非琐碎事件
4. **运行检查**：`python -m py_compile app/services/kb_service.py` + `import` 检查无语法错误

## 假设与决策

- 势力→世界观通过 prompt 调整实现，无需代码迁移逻辑（LLM 在提取阶段自然分类）
- 世界观 prompt 增加整合指令，将同一体系下的流派整合为一条
- 设定整合采用 LLM 后处理（`_consolidate_settings`），与 `_consolidate_events` 模式一致
- 时间线架构调整：Phase1 提取 events → Phase2 timeline 引用 events 结果，总阶段数不变（仍为 2 阶段），timeline 和 worldview 在 Phase2 并行
- 所有修改只需重新提取该卷即可生效，无需修改前端
