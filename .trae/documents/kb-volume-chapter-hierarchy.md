# 知识库卷→章层级索引与提取增强方案

## 一、Summary

当前知识库提取只到**卷级**：每卷提取 6 类扁平条目（世界观/角色/事件/时间线/势力/设定），没有卷主要事件总结、没有角色-事件关联、没有章节级内容索引。检索时 `build_kb_context_for_agent` 只支持卷级过滤/分组，无法下钻到章/话级别。

本方案在现有卷级架构上增加**章节级索引**，实现：
1. **提取增强**：每卷增加"卷主要事件总结"(`volume_event`)；每章/话增加 LLM 生成的"章节摘要"(`chapter_summary`，含出场角色+关键事件)；event 条目增加 `characters` 角色字段
2. **层级检索**：`build_kb_context_for_agent` 增加 `chapter_numbers` 参数，支持"先卷后章"分级下钻；全文大纲/新建小说→卷级；章节大纲/正文写作→章级
3. **前端卷筛选器**：详情页顶部加卷列表 Tab，可点击切换查看某卷条目

## 二、Current State Analysis

### 已有（无需改动）
- `volume_splitter.detect_volumes`：卷识别（正则+合成）✅
- `volume_splitter._CHAPTER_PATTERNS`：章/话正则已定义（L15-17），但仅用于无卷时合成卷计数
- `KnowledgeEntry.volume` / `volume_title`：卷级字段已有 ✅
- `import_file_to_kb_stream`：流式导入+续传（每卷 commit）✅
- `build_kb_context_for_agent`：3 模式（comprehensive/volume_numbers/默认）✅
- `_build_comprehensive_volume_context`：按卷分组+跨卷关联+各卷摘要 ✅
- 前端 `renderKBDetail`：按分类分组展示 ✅（需加卷 Tab）
- 前端 `kbUploadFile`：流式进度渲染 ✅

### 缺失（本方案补齐）
- `KnowledgeEntry` 无 `chapter_number` / `chapter_title` 字段
- `volume_splitter` 无卷内章节切分函数
- `_extract_from_volume` prompt 的 event 条目无 `characters` 字段
- 无卷主要事件总结提取（`volume_event`）
- 无章节摘要提取（`chapter_summary`）
- `build_kb_context_for_agent` 无 `chapter_numbers` 参数
- `_build_comprehensive_volume_context` 不含卷事件总结/章节摘要
- entries API 无 `volume` 过滤参数
- 前端无卷 Tab 筛选

## 三、Proposed Changes

### Step 1: 数据模型 + 迁移 + 分类常量

**文件**: `app/models/knowledge_base.py`
- `KnowledgeEntry` 增加 `chapter_number = Column(Integer, nullable=True)` 和 `chapter_title = Column(String(200), nullable=True)`（在 `volume_title` 之后）

**文件**: `app/database.py`
- `_check_and_migrate` 增加 2 个 ALTER TABLE 块：
  ```python
  cols = [c["name"] for c in inspector.get_columns("knowledge_entries")]
  if "chapter_number" not in cols:
      await session.execute(text("ALTER TABLE knowledge_entries ADD COLUMN chapter_number INTEGER"))
  if "chapter_title" not in cols:
      await session.execute(text("ALTER TABLE knowledge_entries ADD COLUMN chapter_title VARCHAR(200)"))
  ```

**文件**: `app/services/kb_service.py`（顶部常量区）
- 增加 `KB_CATEGORY_VOLUME_EVENT = "volume_event"` 和 `KB_CATEGORY_CHAPTER_SUMMARY = "chapter_summary"`
- `KB_CATEGORY_LABELS` 增加 `"volume_event": "卷事件总结"`、`"chapter_summary": "章节摘要"`

### Step 2: volume_splitter — 卷内章节切分

**文件**: `app/services/volume_splitter.py`
- 新增函数 `detect_chapters_in_volume(vol_text: str) -> List[Dict]`
  - 用 `_CHAPTER_PATTERNS`（已有，第N章/话/回）在卷文本内 finditer
  - 去重（同 line_start 只保留一个）、按 start 排序
  - 返回 `[{chapter_number, chapter_title, char_range:[start,end], text}]`，char_range 的 end 为下一章 line_start 或 len(text)
  - chapter_title 从标题行提取（去掉"第N章/话/回"前缀后的文本，复用 `_clean_title` 逻辑但需适配章标题——新写 `_clean_chapter_title`）
  - **fallback**：若卷内无任何章/话标记，返回 `[{chapter_number: 1, chapter_title: "本卷全文", char_range: [0, len(vol_text)], text: vol_text}]`

### Step 3: 提取 prompt 增强 + 新提取函数

**文件**: `app/services/kb_service.py`

**3a. 修改 `_extract_from_volume`（L449-512）的 prompt**
- event 数组的元素从 `{"name", "content"}` 改为 `{"name", "content", "characters": ["角色名"]}`
- prompt 说明改为："事件经过、起因、结果、涉及人物（characters 数组填入参与该事件的角色名，没有就空数组）"
- `_extract_volume_entries` 的 `merged` dict 不变（6 类），但 event 条目会多一个 `characters` 字段
- 导入流程（L877-894）创建 event KnowledgeEntry 时，把 `it.get("characters", [])` 写入 `attributes={"characters": [...]}`

**3b. 新增 `_extract_volume_event_summary(vtext, vn, vol_title) -> str`**
- 输入：卷全文（若超 8000 字则取前 8000 字截断）
- LLM prompt：总结该卷主要事件、关键情节走向、重要角色弧光，输出 300-600 字
- 返回摘要文本（失败返回空串）
- 用现有 `llm_client.chat`，`temperature=0.3, max_tokens=2048`

**3c. 新增 `_extract_chapter_summary(chapter_text, ch_num, ch_title, vn, vol_title) -> dict`**
- 输入：单章文本（若超 8000 字截断）、章号、章标题、卷号、卷标题
- LLM prompt：生成该章 200-500 字内容摘要，并列出出场角色、关键事件
- 输出 `{"summary": "...", "characters": [...], "key_events": [...]}`
- 失败返回 `{"summary": "", "characters": [], "key_events": []}`

**3d. 新增 `_extract_chapter_summaries_batch(vtext, vn, vol_title) -> list[dict]`**
- 调用 `detect_chapters_in_volume(vtext)` 得到章节列表
- 用 `asyncio.Semaphore(MAX_CONCURRENT_LLM)` + `BATCH=4` 并发调用 `_extract_chapter_summary`（复用 `_extract_volume_entries` 的并发模式）
- 返回 `[{chapter_number, chapter_title, summary, characters, key_events}]`

### Step 4: 导入流程集成

**文件**: `app/services/kb_service.py` — `import_file_to_kb_stream`（L844-938 的卷循环内）

在现有 `_extract_volume_entries(vtext, vn, vol["title"])`（L874）之后、创建条目循环（L877）之前/并行：

1. **提取卷事件总结**：`vol_event_text = await _extract_volume_event_summary(vtext[:8000], vn, vol["title"])`
   - 若非空，创建 `KnowledgeEntry(category="volume_event", title=f"第{vn}卷《{vol['title']}》主要事件总结", content=vol_event_text, volume=vn, volume_title=vol["title"], source="upload")`，加入 `new_objs`

2. **提取章节摘要**：`chapters_data = await _extract_chapter_summaries_batch(vtext, vn, vol["title"])`
   - 对每个 chapter_data：创建 `KnowledgeEntry(category="chapter_summary", title=f"第{ch['chapter_number']}章《{ch['chapter_title']}》摘要", content=ch["summary"], attributes={"characters": ch["characters"], "key_events": ch["key_events"]}, volume=vn, volume_title=vol["title"], chapter_number=ch["chapter_number"], chapter_title=ch["chapter_title"], source="upload")`，加入 `new_objs`

3. **event 条目补 characters**：在 L877-894 的条目创建循环中，对 `category == "event"` 的条目，`attributes={"characters": it.get("characters", [])}`（其他类别 attributes={}）

4. **向量索引 metadata 补 chapter_number**：L900-903 的 metas 构建，增加 `if obj.chapter_number is not None: meta["chapter_number"] = obj.chapter_number`

5. **kb.volumes 存章节列表**：在 L924 的 `kb.volumes = [dict(v) for v in volumes]` 之前，给当前 vol dict 加 `vol["chapters"] = [{"chapter_number": ch["chapter_number"], "chapter_title": ch["chapter_title"]} for ch in chapters_data]`

6. **进度事件**：L929-938 的 progress 事件增加 `"chapters_extracted": len(chapters_data)` 字段

### Step 5: 检索层级增强

**文件**: `app/services/kb_service.py`

**5a. `build_kb_context_for_agent`（L253）增加 `chapter_numbers` 参数**
- 签名：`async def build_kb_context_for_agent(db, kb_id, query_text="", comprehensive=False, volume_numbers=None, chapter_numbers=None)`
- SQL 过滤（L267-274）：当 `chapter_numbers` 非空时，增加 `.where(or_(KnowledgeEntry.chapter_number.in_(chapter_numbers), KnowledgeEntry.chapter_number.is_(None)))`（无章归属的条目始终纳入，保证卷级设定不丢）
- 向量检索过滤（L336-340）：当 `chapter_numbers` 非空时，metadata 过滤增加 `m.get("chapter_number") in chapter_numbers or m.get("chapter_number") is None`

**5b. `_build_comprehensive_volume_context`（L355-411）增强**
- 在每卷的 `【源卷N《title》】` 区块（L377-384）之前，插入该卷的 `volume_event` 条目内容作为 `【卷N主要事件总结】`
- 在每卷区块之后，插入该卷的 `chapter_summary` 条目列表作为 `【卷N章节摘要】`（格式：`- 第X章《title》：summary[:150]`）
- 这让全文大纲/新建小说的 comprehensive 模式自动包含卷事件总结+章节摘要

**5c. 新增章节级上下文构建（chapter_numbers 非空时）**
- 在 `build_kb_context_for_agent` 中，当 `chapter_numbers` 非空且非 comprehensive 时，走新的章节级构建逻辑：
  - 先拉对应卷的 `volume_event` + `chapter_summary` 条目（按 chapter_number 过滤）
  - 再拉该章相关的人物/事件/设定条目（chapter_number 过滤 + volume 过滤）
  - 组装为 `【卷N主要事件总结】` + `【第X章摘要】` + `【本章角色】` + `【本章事件】` + `【本章设定】` 区块
- 这条路径用于章节大纲/正文写作

### Step 6: 智能体/服务集成

**文件**: `app/services/outline_service.py`
- `generate_chapter_outline_batch`（L88-98）：在现有 `volume_numbers=chapter_vol_nums` 基础上，增加 `chapter_numbers=[chapter_range_start, chapter_range_end]`（从 batch 的章节号范围推导）
- `generate_novel_outline` / `generate_full_novel_outline`：保持 `comprehensive=True`（自动含卷事件总结+章节摘要，由 Step 5b 保证）

**文件**: `app/services/chapter_service.py`
- `_build_chapter_state`（L100-106）：在现有 `volume_numbers=chapter_vol_nums` 基础上，增加 `chapter_numbers=[chapter_number]`

**文件**: `app/services/novel_service.py`
- `expand_novel_from_qa`（L245）：保持 `comprehensive=True`

**文件**: `app/agents/outline_agent.py`
- `_build_full_outline_messages` 的 `kb_section`（L284）：文案增加"另含【卷N主要事件总结】与【卷N章节摘要】，请依据各卷事件走向与章节内容安排本小说对应卷的承接与节奏"
- `_build_chapter_outline_messages` 的 `kb_section`（L381）：文案改为"同人创作最高优先级，已按【卷→章】层级组织：含该卷主要事件总结、本章摘要、本章角色与事件。须忠实沿用本章涉及的角色/事件/设定"

### Step 7: 前端卷筛选器

**文件**: `app/api/knowledge_bases.py`
- `list_entries` 端点（L79-85）：增加 `volume: int | None = Query(default=None)` 参数，传给 service

**文件**: `app/services/kb_service.py`
- `list_entries`（L135-141）：增加 `volume: int | None = None` 参数，`if volume is not None: stmt = stmt.where(or_(KnowledgeEntry.volume == volume, KnowledgeEntry.volume.is_(None)))`（无卷归属的条目始终显示）

**文件**: `static/js/knowledge-base.js`
- `renderKBDetail`（L269-317）：
  - 在 `kb-detail-header`（L300-307）之后、`kb-sections`（L308）之前，插入卷 Tab 栏：
    ```javascript
    const volTabs = (kb.volumes || []).map(v =>
        `<button class="kb-vol-tab${v.volume_number === kbCurrentVolume ? ' active' : ''}" onclick="kbSelectVolume(${v.volume_number})">第${v.volume_number}卷</button>`
    ).join("");
    ```
  - 全局变量 `kbCurrentVolume = null`（null=全部）
  - `kbSelectVolume(volNum)`：设 `kbCurrentVolume`，重新渲染 sections（调 `loadKBSectionEntries` 时带 volume 参数）
- `loadKBSectionEntries`（L333-342）：URL 改为 `/entries?category=${category}${kbCurrentVolume ? '&volume=' + kbCurrentVolume : ''}`
- `kbEntryCardHtml`（L372-393）：增加卷/章标签显示：
  ```javascript
  const volTag = e.volume ? `<span class="kb-entry-source">第${e.volume}卷</span>` : "";
  const chTag = e.chapter_number ? `<span class="kb-entry-source">第${e.chapter_number}章</span>` : "";
  ```
  插入到 `kb-entry-actions` 的 `sourceTag` 旁

### Step 8: Schemas

**文件**: `app/schemas/knowledge_base.py`
- `KnowledgeEntryResponse`：增加 `chapter_number: Optional[int] = None`、`chapter_title: Optional[str] = None`
- `KnowledgeEntryCreate`：增加 `chapter_number: Optional[int] = None`、`chapter_title: Optional[str] = None`
- `KnowledgeEntryUpdate`：同上

**文件**: `app/services/kb_service.py`
- `update_entry`（L149）的 `valid_fields`：增加 `"chapter_number", "chapter_title"`
- `update_entry` 向量 metadata（L158-161）：增加 `if entry.chapter_number is not None: metadata["chapter_number"] = entry.chapter_number`

### Step 9: knowledge_service 向量元数据

**文件**: `app/services/knowledge_service.py`
- `index_full_outline_to_rag`（L305 区域，Step 8 已改过）：无需再改（大纲向量不含 chapter_number，KB 条目向量在导入流程 L900-903 已含）

## 四、Assumptions & Decisions

### 关键决策（用户已确认）
1. **章节内容**：LLM 生成 200-500 字摘要 + 出场角色 + 关键事件（非全文存储、非纯要点）
2. **数据模型**：KnowledgeEntry 加 `chapter_number`/`chapter_title` + 新分类 `volume_event`/`chapter_summary`（非嵌套 JSON、非混合）
3. **角色-事件**：event 条目 `attributes.characters` 数组（事件→角色反向索引）
4. **检索层级**：按场景分级下钻（全文大纲→卷级、章节大纲→章级、正文写作→章级详细）

### 边界处理
- **卷内无章/话标记**：`detect_chapters_in_volume` fallback 返回整卷作为 1 个"章"，chapter_title="本卷全文"
- **章文本超 8000 字**：截断前 8000 字送 LLM 摘要（摘要不需全文）
- **续传兼容**：旧 KB 的 volume status="extracted" 但无 chapter_summary → 续传跳过该卷（不补提取章节摘要）。要获取章节级数据需清空重导。旧 KB 仍可正常工作（卷级检索不受影响）
- **旧 KB 条目**：chapter_number=NULL 的条目在 chapter_numbers 过滤时始终纳入（`or_(...is_(None))`），不丢卷级设定
- **并发**：章节摘要提取复用 `BATCH=4` + `asyncio.Semaphore(MAX_CONCURRENT_LLM)`，与现有 chunk 提取一致
- **LLM 成本**：几百章≈几百次 chapter_summary 调用 + ~10 次 volume_event 调用，用户已接受

### 不做的事
- 不改 `detect_volumes`（卷识别逻辑已稳定）
- 不改 `_build_volume_relations_and_summaries` 的一句话摘要（kb.volumes[].summary 保留用于列表/徽章展示，卷事件总结走 volume_event 条目）
- 不改前端 `kbUploadFile` 流式进度（已完成）
- 不改 `import_file_to_kb` 旧版兼容 wrapper

## 五、Rollout 顺序（10 步）

1. 数据模型 + 迁移 + 分类常量（Step 1）
2. volume_splitter 章节切分函数（Step 2）
3. 提取 prompt 增强 + 新提取函数（Step 3a/3b/3c/3d）
4. 导入流程集成（Step 4）
5. 检索层级增强 build_kb_context_for_agent + _build_comprehensive_volume_context（Step 5a/5b/5c）
6. 智能体/服务集成（Step 6）
7. 前端卷筛选器（Step 7）
8. Schemas（Step 8）
9. py_compile + import 检查 + node --check（验证）
10. 回归旧 KB + 向后兼容审查（验证）

## 六、Verification

### 语法/导入
- `py_compile` 所有修改的 .py 文件
- `python -c "from app.services import kb_service, volume_splitter; ..."` 导入检查
- `node --check static/js/knowledge-base.js`

### 回归旧 KB
- 旧 KB 条目 chapter_number=NULL → chapter_numbers 过滤时 `or_(...is_(None))` 始终纳入 ✅
- 旧 KB kb.volumes[] 无 chapters 字段 → 前端 `(kb.volumes || []).map()` 和 `(v.chapters || [])` 安全处理 ✅
- 迁移新列 nullable，默认 NULL → 旧行安全 ✅

### 功能验证（手动）
- 上传含"第N卷""第N章"的 txt → 检查：volume_event 条目存在、chapter_summary 条目存在、event 条目 attributes.characters 非空
- 详情页卷 Tab 切换 → 条目按卷过滤
- 全文大纲生成 → kb_context 含【卷N主要事件总结】+【卷N章节摘要】
- 章节大纲生成 → kb_context 含本章摘要+本章角色/事件
