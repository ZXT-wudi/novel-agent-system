# 修复联网取材 fallback 与重构全文大纲设定传递链路

## Summary

用户报告两个问题：

1. **联网取材只保存 1 条到知识库**：`_summarize_with_llm` 的 `asyncio.wait_for(timeout=30.0)` 太短，`asyncio.TimeoutError` 的 `str()` 为空字符串，导致 `LLM summary failed ()`；fallback 把 9000 字原始片段截断为 2000 字，`_structure_to_entries` 只能从中提取出 1 条。
2. **扩充出来的设定（world_settings / characters）没有体现在全文大纲中**：经核查，流式生成路径（outlines.py → outline_agent.py）确实会把 `novel.world_settings`/`novel.characters` 拼进 prompt，但**链路不可靠**——`FullOutlineGenerateRequest` 根本不携带 `world_settings`/`characters`，大纲生成端只能从 DB 读取；而 DB 的值又会被 PUT 端点用 `collectEditedSettings()` 的结果覆盖（PUT 只跳过 `None`，不跳过空 dict/list 或全空字符串的 dict）。一旦确认页输入未被正确预填，PUT 就会把扩充阶段写入 DB 的正确设定覆盖成空值，大纲 prompt 的设定段就消失了。

用户选择：Issue 1「两者都做（最稳健）」；Issue 2「重构设定传递链路」——让大纲生成直接接收前端确认过的设定，不再依赖 DB/PUT 这一跳。

## Current State Analysis

### Issue 1 — 联网取材链路（web_research.py）
- `_summarize_with_llm` (L70-96)：`asyncio.wait_for(client.chat(..., max_tokens=2048), timeout=30.0)`。30s 远小于内部 httpx 的 300s，模型稍慢或 429 重试即超时。`asyncio.TimeoutError` 无参数，`str()` 为空 → `LLM summary failed ()`。
- `research_for_outline` fallback (L160-162)：`return raw_text[:2000]` —— 把最多 9000 字截断到 2000 字，丢掉绝大部分搜索结果。
- `_structure_to_entries` (L199-219)：`asyncio.wait_for(..., timeout=40.0)`，`max_tokens=4096`。当输入变大（失败时传完整原文），40s 偏紧。
- `save_web_research_to_kb` (L309-)：调用 `_structure_to_entries`，已有 `text_len`/`text_preview` 调试打印。

### Issue 2 — 设定传递链路
当前链路（不可靠）：
1. `POST /novels/from-qa` → `expand_novel_from_qa` → `_parse_expand_response` 返回含 `world_settings`/`characters` 的 dict → `create_novel` 写入 DB（JSON 列，`models/novel.py` L21-22 确认是 `Column(JSON)`）。
2. 前端 `renderWizardConfirmation(settings)` 用 `wizardState.settings` 预填确认页输入。
3. 用户点「确认」→ `confirmNovelWizard()` → `collectEditedSettings()` 读输入 → `PUT /api/novels/{id}`。
4. PUT 端点（novels.py L113-121）：遍历字段，只跳 `None`、跳 `title` 空串、跳 `target_word_count==0`，**不跳空 dict/list**。若确认页输入为空，会把 DB 正确设定覆盖成空值。
5. `generateFullOutline()`（outline.js L57-62）：POST body 仅 `{ description, genre, length_type, target_word_count, use_web_research }`，**不带 world_settings/characters**。
6. 大纲端点（outlines.py L180-196）：`state.outline_item` 用 `novel.world_settings or {}` / `novel.characters or []`（来自 DB，可能已被 PUT 覆盖）。
7. `_build_full_outline_messages`（outline_agent.py L295-307）：`if isinstance(ws, dict) and ws:` 判空——若 DB 已被覆盖成空 dict，则 `novel_settings_section` 为空，设定段不进 prompt。

**根因**：设定从扩充→大纲要走 DB/PUT 这一跳，而 PUT 不可靠 + 大纲请求不显式携带设定。重构后让大纲请求直接携带前端确认过的设定，绕开 DB/PUT 覆盖风险。

## Proposed Changes

### A. Issue 1 — 联网取材（`app/services/web_research.py`）

**A1. `_summarize_with_llm` 超时 30s → 120s（L93-96）**
- 把 `timeout=30.0` 改为 `timeout=120.0`，给慢模型/429 重试足够时间。

**A2. `research_for_outline` fallback 改为返回完整原文 + 区分 TimeoutError（L155-162）**
```python
try:
    summary = await _summarize_with_llm(raw_text, title, genre, description)
    result = summary.strip()
    print(f"[WEB-RESEARCH] research_for_outline: summary_len={len(result)}, preview={result[:200]}")
    return result
except asyncio.TimeoutError:
    print(f"[WEB-RESEARCH] research_for_outline: LLM summary timed out (120s), passing full raw snippets to structurer (len={len(raw_text)})")
    return raw_text
except Exception as e:
    print(f"[WEB-RESEARCH] research_for_outline: LLM summary failed ({type(e).__name__}: {e}), passing full raw snippets (len={len(raw_text)})")
    return raw_text
```
- 不再 `[:2000]` 截断，把完整原文（最多 9000 字）交给 `_structure_to_entries`，让结构化步骤从全部片段提取多条。
- `asyncio.TimeoutError` 单独捕获并打印明确信息（不再出现空括号）。

**A3. `_structure_to_entries` 超时 40s → 90s（L216-219）**
- 输入可能从 800 字摘要变成 9000 字原文，40s 偏紧，提到 90s。`max_tokens=4096` 保持不变（足够输出多条结构化条目）。

### B. Issue 2 — 重构设定传递链路

**B1. 请求 schema 增字段（`app/schemas/outline.py` L20-25）**
```python
class FullOutlineGenerateRequest(BaseModel):
    description: Optional[str] = None
    genre: Optional[str] = None
    length_type: Optional[str] = "short"
    target_word_count: Optional[int] = None
    use_web_research: bool = False
    world_settings: Optional[dict] = None
    characters: Optional[list] = None
```

**B2. 大纲端点优先用请求里的设定（`app/api/outlines.py` L180-196）**
```python
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
```
- 请求显式带设定时优先用请求的；否则回退 DB（兼容大纲页面直接生成的场景）。
- 调试打印标明设定来源（request/db）、world_settings 的 keys、characters 数量，便于核验链路。

**B3. PUT 端点对空 dict/list 跳过（`app/api/novels.py` L113-121，防御性）**
```python
for field in ["title", "genre", "description", "length_type", "writing_style", "target_word_count", "narrative_pov", "world_settings", "characters"]:
    val = getattr(data, field, None)
    if val is None:
        continue
    if field == "title" and isinstance(val, str) and not val.strip():
        continue
    if field == "target_word_count" and val == 0:
        continue
    if field in ("world_settings", "characters") and not val:
        continue
    setattr(novel, field, val)
```
- 防御：`{}`/`[]` 不覆盖 DB（与 target_word_count==0 同思路）。注意：全空字符串的 dict 仍会被写入，所以 B2 的请求直传才是根本修复；此处仅兜底真正的空容器。

**B4. 前端：确认页设定暂存到 appState（`static/js/novel-wizard.js` `confirmNovelWizard` L557-559）**
```javascript
try {
    const edited = collectEditedSettings();
    appState.pendingOutlineSettings = edited;   // 暂存给大纲请求直传
    await apiPut(`/api/novels/${novelId}`, edited);
} catch (e) {
    wizardState.busy = false;
    appState.pendingOutlineSettings = null;
    alert("保存设定失败: " + e.message);
    renderWizardConfirmation(wizardState.settings || {});
    return;
}
```
- PUT 仍执行（保持 DB 同步），但同时把确认过的设定暂存 `appState.pendingOutlineSettings`，供紧接着的 `generateFullOutline()` 直传给大纲端点。
- 失败分支清空暂存，避免脏数据。

**B5. 前端：大纲请求携带暂存设定（`static/js/outline.js` `generateFullOutline` L57-62）**
```javascript
const pending = appState.pendingOutlineSettings || null;
const body = { description, genre, length_type: lengthType, target_word_count: targetWordCount, use_web_research: useWebResearch };
if (pending && pending.world_settings) body.world_settings = pending.world_settings;
if (pending && pending.characters) body.characters = pending.characters;
appState.pendingOutlineSettings = null;   // 用完即清，避免泄漏到下次大纲页直接生成
const response = await fetch(`/api/novels/${novelId}/outline/generate-full`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: outlineAbortController.signal,
});
```
- 大纲页面直接生成时 `pending` 为 null，body 不带设定，端点回退 DB——完全向后兼容。

**B6. 大纲 agent 增设定段调试打印（`app/agents/outline_agent.py` `_build_full_outline_messages` 返回前，约 L308 后）**
```python
ws = user_input.get("world_settings")
chars = user_input.get("characters")
# ... 现有 novel_settings_json 构建逻辑 ...
print(f"[OUTLINE-MSG] world_settings present={bool(ws)}, characters present={bool(chars)}, novel_settings_section_len={len(novel_settings_section)}")
if novel_settings_section:
    print(f"[OUTLINE-MSG] settings preview: {novel_settings_section[:300]}")
return [ ... ]
```
- 确认设定确实拼进 prompt，定位「数据没到 prompt」vs「LLM 忽略设定」。

## Assumptions & Decisions

1. **Issue 1 选「两者都做」**：超时 30→120s、失败时返回完整原文（不截断）、区分 TimeoutError 报错；并顺手把 `_structure_to_entries` 超时 40→90s 以承接更大输入。
2. **Issue 2 选「重构链路」**：让 `FullOutlineGenerateRequest` 显式携带 `world_settings`/`characters`，大纲端点优先用请求值；前端确认后暂存 `appState.pendingOutlineSettings` 直传。PUT 仍保留（DB 同步），但加空容器跳过兜底。
3. **`appState` 共享**：`app.js` L1 定义为全局，novel-wizard.js 与 outline.js 均已使用，`pendingOutlineSettings` 可跨文件访问，无需新增全局。
4. **JSON 列**：`models/novel.py` L21-22 确认 `world_settings`/`characters` 为 `Column(JSON)`，SQLAlchemy 自动序列化，DB 读写无类型问题。
5. **向后兼容**：大纲页面直接生成（非向导流程）不带设定，端点回退 DB，行为不变。
6. **死代码 shadow 函数 `outline_service.generate_full_novel_outline`（L49-77）**：无调用方，本次不动（不在用户诉求范围内），但 B6 的调试打印覆盖了真正在用的流式路径。

## Verification Steps

1. **语法检查**：`python -m py_compile app/services/web_research.py app/schemas/outline.py app/api/outlines.py app/api/novels.py app/agents/outline_agent.py`。
2. **Issue 1 验证**：起服务，对一本同人类小说开「联网取材」生成全文大纲，观察日志：
   - 正常：`summary_len=...`，`_structure_to_entries: parsed N entries, accepted M`，`知识库已保存 M 条`，M 应 >1。
   - 摘要超时：看到 `LLM summary timed out (120s), passing full raw snippets (len=9000)`，随后 `_structure_to_entries` 仍能提取多条，`知识库已保存 M 条` M 应 >1（不再只有 1 条）。
3. **Issue 2 验证**：新建小说走向导→确认→自动生成全文大纲，观察日志：
   - `[OUTLINE] settings source: world_settings from=request (keys=[era, location, rules, key_elements, power_system, social_structure, core_conflict, theme]), characters from=request (n=...)` —— 来源是 request，设定齐全。
   - `[OUTLINE-MSG] world_settings present=True, characters present=True, novel_settings_section_len>0` —— 设定段进了 prompt。
   - 生成的全文大纲角色/世界观与扩充一致。
4. **回归**：在大纲页面（非向导）直接点「生成全文大纲」，日志应显示 `from=db`，行为与重构前一致。
5. **PUT 兜底**：若手动构造空 `{}` 提交，DB 设定不被覆盖（`[NOVEL-UPDATE]` 后查询 world_settings 仍非空）。
