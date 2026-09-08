# 角色跨卷去重移除 + 时间线格式修正方案

## 问题概述

用户提取多卷后发现两个问题：

| # | 问题 | 根因 |
|---|------|------|
| 1 | "鲁迪"只在第一卷存在，后续卷无角色记录 | `_cross_volume_dedup` 对角色做跨卷去重：匹配到同名角色后，删除新卷条目、内容合并到旧条目、`volume_number` 保持旧值。按卷过滤时后续卷看不到该角色 |
| 2 | 前几卷时间线正常（如"成为家庭教师一个月后"），后面退化为"第1章：梦境与全白空间"按章罗列 | `_derive_timeline` prompt 约束不足：输入 blob 每段以 `[第X章《标题》]` 开头强引导按章；prompt 有"时间线应跟随章序"的误导语；无正面示例、无"禁止按章"的负面约束 |

---

## 修改 1：移除角色跨卷去重（每卷独立存储角色）

**目标**：每个卷独立存储自己的角色条目，不再跨卷合并删除。

### 当前代码（`_cross_volume_dedup` L1435-1589）

函数执行流程：
1. **L1443-1457**：加载其他卷已有角色到 `existing_chars` 字典 + `char_alias_to_cano` 别名映射
2. **L1459-1461**：跳过 chapter_summary 和 volume_event 类别
3. **L1463-1523**：character 类别 — 按名称/别名匹配已有角色，匹配成功后：
   - L1483：`_llm_merge_entries` 把新卷内容合并到旧条目
   - L1494-1508：更新旧条目向量（`volume_number` 保持旧值）
   - **L1509-1516：删除新卷条目（DB + 向量库）**
   - L1517-1522：记录跨卷关系
4. **L1525-1588**：非角色类别 — 向量相似度去重（阈值 0.15）

### 修改内容

**文件**: `app/services/kb_service.py`

**删除 L1443-1457**（existing_chars 加载块）— 不再需要加载已有角色。

**删除 L1463-1523**（character 匹配+合并+删除块）— 整块替换为一行 `continue`。

修改后的循环开头：

```python
    relations_added: list[dict] = []

    for entry in list(new_entries):
        if entry.category in (KB_CATEGORY_CHAPTER_SUMMARY, KB_CATEGORY_VOLUME_EVENT):
            continue
        if entry.category == "character":
            continue

        doc = f"[{entry.category}] {entry.title}: {entry.content}"
        # ... 非角色类别去重逻辑不变 ...
```

### 影响分析

- **角色存储**：每卷独立存储自己的角色条目，`volume_number` = 当前卷号。按卷过滤时每卷都能看到自己的角色。
- **名称归一化不受影响**：`_normalize_character_names` + `_load_existing_character_aliases` 仍在导入流程中运行（L1809-1811），确保跨卷角色名称一致（如"鲁迪"/"鲁迪乌斯"归一为同一标准名）。`_load_existing_character_aliases` 查询 `volume < current_vol` 的角色条目加载别名，多卷同名条目会覆盖但别名一致，无影响。
- **`_derive_key_characters` 不受影响**：每卷仍独立派生角色，阈值 `KEY_CHAR_MIN_CHAPTERS=2`/`KEY_CHAR_MIN_EVENTS=2` 不变。
- **`_llm_merge_entries` 仍用于**：非角色类别（event/faction/setting/worldview）的跨卷向量相似度去重（L1554），不受影响。
- **跨卷关系记录**：角色的"跨卷合并"关系不再记录，但同名跨卷关系仍由非角色去重块的 L1582-1588 记录。此为预期行为——角色每卷独立，不需要合并关系。
- **重新提取某卷**：`_reset_volume` 删除该卷所有条目后重新提取，新条目独立存储，不受其他卷影响。

---

## 修改 2：时间线 prompt 重写（禁止按章描述 + 事件前置）

**目标**：时间线使用故事内时间描述（如"成为家庭教师一个月后"），不以章节为单位。

### 当前 prompt 问题（L1141-1148）

1. **"各章已按章序，时间线应跟随章序"** — 误导 LLM 以章节为单位组织
2. **events_text 追加在 blob 末尾**（L1148 `{blob}{events_text}`）— 长篇 blob 后事件权重被稀释
3. **无正面示例** — `name` 只说"时间节点/阶段"，未给出"成为家庭教师一个月后"这类示例
4. **无负面约束** — 未禁止"第X章"或章标题作为 name

### 修改内容

**文件**: `app/services/kb_service.py` L1127-1164

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

### 关键改动

| 改动 | 说明 |
|------|------|
| events_text 前置 | 事件放在 blob 之前，标注"以关键事件为主要线索"，提升事件权重 |
| blob 标注为"补充背景" | 降低章节摘要的主导地位 |
| 删除"各章已按章序，时间线应跟随章序" | 消除按章组织的误导 |
| 新增"要求"段 | 4 条明确约束 |
| 正面示例 | "成为家庭教师一个月后""抵达王都当日""战斗后的第三天""修炼半年后" |
| 负面约束 | "禁止使用'第X章'或章标题作为时间节点名" |
| events_text 格式简化 | 去掉"已提取的关键事件："前缀（移到 prompt 正文中），只保留事件列表 |

---

## 修改文件汇总

| 文件 | 修改内容 | 涉及位置 |
|------|----------|----------|
| `app/services/kb_service.py` | 删除 `_cross_volume_dedup` 中角色加载块（L1443-1457）+ 角色匹配删除块（L1463-1523），替换为 `continue` | L1441-1524 |
| `app/services/kb_service.py` | `_derive_timeline` prompt 重写：事件前置 + 正面示例 + 负面约束 + 删误导语 | L1127-1164 |

## 验证步骤

1. **语法检查**：`d:\xiaoshuo\venv\Scripts\python.exe -m py_compile app/services/kb_service.py`
2. **导入检查**：`d:\xiaoshuo\venv\Scripts\python.exe -c "import app.services.kb_service; print('IMPORT_OK')"`
3. **角色验证**：重新提取一卷后，检查该卷角色条目独立存在（`volume_number` = 当前卷），"鲁迪"在每卷都有记录
4. **时间线验证**：重新提取退化的卷后，检查时间线条目 name 为故事内时间描述（如"成为家庭教师一个月后"），不再出现"第X章：..."格式

## 假设与决策

- 角色每卷独立存储是用户的明确意图（"每一卷主要角色都是在发生变化的所以都要有所记录"），移除跨卷去重后无需替代合并逻辑
- 名称归一化（`_normalize_character_names`）保留，确保跨卷角色名称一致
- 时间线不加格式过滤后处理——强 prompt 约束应足够；格式过滤有清空全部条目的风险（若 LLM 仍输出按章格式，过滤后为空），不如让 prompt 引导 LLM 正确输出
- 前两卷时间线已正常，无需重新提取；仅需重新提取退化的卷即可生效
- 非角色类别（event/faction/setting/worldview）的跨卷向量去重保持不变
