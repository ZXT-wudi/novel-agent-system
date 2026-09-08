# 普通知识库（写作技法分析库）更新计划

## 摘要

新建一个**独立的「普通知识库」子系统**：用户上传参考作品后，用一套**全新的、粗略的 7 维度技法提取**（主题/人物弧光/情节结构/叙事视角/语言风格/世界观自洽/情感共鸣）把「可借鉴的写作技法」结构化保存；按题材分类、用户可选；一部小说可**同时绑定**普通知识库与高级知识库，写作时把技法参考与原作设定参考分别注入。

- 全新代码，**不复用** **`kb_service.py`** **任何逻辑**（仅复用共享的 `document_parser` 与 LLM client 基础设施）。

- 现有「每章一致性提取（StoryKnowledge）」与「高级知识库（13 段深度提取）」**完全不动**。

- 新表 + 新路由 + 新前端页面 + 新增小说绑定字段。

***

## 当前状态分析（基于实际探索）

### 现有两套知识库（均保持不动）

1. **StoryKnowledge**（[story\_knowledge.py](file:///d:/xiaoshuo/app/models/story_knowledge.py)）：按章自动提取 5 个一致性字段（characters/character\_relations/world\_elements/chapter\_summary/plot\_points），由 [knowledge\_extractor.py](file:///d:/xiaoshuo/app/services/knowledge_extractor.py) 生成，喂给写作一致性注入（[writer\_agent.py:164-175](file:///d:/xiaoshuo/app/agents/writer_agent.py#L164-L175)）、知识图谱、角色阶段、世界区域、角色图。**不可选、不按题材分类**。
2. **KnowledgeBase + KnowledgeEntry**（[knowledge\_base.py](file:///d:/xiaoshuo/app/models/knowledge_base.py)）：高级库，按题材分类、可选；13+ 段深度提取流水线在 [kb\_service.py](file:///d:/xiaoshuo/app/services/kb_service.py)（`import_file_to_kb_stream`）。

### 关键接入点

- 小说绑定高级库的唯一外键：`Novel.knowledge_base_id`（[novel.py:18](file:///d:/xiaoshuo/app/models/novel.py#L18)，`ondelete="SET NULL"`）。

- 高级库写作消费：`build_kb_context_for_agent`（kb\_service.py:292）→ `state["kb_context"]` → [writer\_agent.py:156-159](file:///d:/xiaoshuo/app/agents/writer_agent.py#L156-L159) 注入 `=== 知识库参考 ===`（同人时为 `=== 原作知识库参考（同人创作必须严格遵循原作设定）===`）。

- LLM 调用：`from app.llm.siliconflow import get_client` → `llm_client.chat(messages, temperature=..., max_tokens=...)`（[writer\_agent.py:1,258](file:///d:/xiaoshuo/app/agents/writer_agent.py#L1)）。

- 文档解析（共享工具，非高级库代码）：`extract_text_from_file(file_content, filename)`（[document\_parser.py:6](file:///d:/xiaoshuo/app/services/document_parser.py#L6)）。

- 建表/迁移：`init_db()`（[database.py:39-74](file:///d:/xiaoshuo/app/database.py#L39-L74)）先 `create_all` 建新表，再 `_check_and_migrate` 给现存表补列。

- 前端「知识库」页面：[index.html:136-140](file:///d:/xiaoshuo/static/index.html#L136-L140) 面板 + [knowledge-base.js](file:///d:/xiaoshuo/static/js/knowledge-base.js)；题材常量 `KB_GENRES = ["玄幻","都市","科幻","历史","同人","其他"]`（knowledge-base.js:21）。

- 小说创建向导：[novel-wizard.js](file:///d:/xiaoshuo/static/js/novel-wizard.js) 在 `fanwork_kb` 步骤选 `knowledge_base_id`，提交到 `/api/novels/from-qa`（L387）。

***

## 关键假设与决策（已与用户确认）

1. **普通知识库 = 全新独立子系统**，不复用 `kb_service.py` 代码；仅复用共享基础设施 `document_parser` 与 `app.llm.siliconflow`。
2. **StoryKnowledge（每章一致性）完全不动**——其提取提示词、图谱、阶段、区域、角色图均不变。
3. **高级知识库完全不动**——13 段流水线、CRUD、前端页面均不变。
4. **7 维度粗提取 + 超长文档鲁棒分块**：面向**几百万字**文档，采用**分层 map-reduce**（逐块提取 → 分批合并 → 递归归并 → 最终 7 维）。**全量分块、绝不截断**；按段落/句边界切块并加小重叠防边界丢技法；**编码鲁棒**（GBK/GB18030/Big5/UTF-8 txt 不乱码丢字）；**断点续传 + 逐块重试**，中断或单块失败不丢已提取内容。详见 §2。
5. **不入 ChromaDB/RAG**：最终 7 维技法分析篇幅小，写作时**全量注入 7 维**（中间逐块分析仅在提取期持久化用于续传，合并完成后可保留在 `import_progress` 供再合并）。
6. **新表 + 新路由 + 新前端页面**（用户选定「独立新表+独立页面」）。
7. 小说新增 `ordinary_knowledge_base_id` 外键，实现与高级库**同时绑定**。
8. 复用 `KB_GENRES` 题材列表做分类。
9. 注入定位为「**可借鉴、非硬性设定**」，与高级库（同人硬性设定）区分。

***

## 提议改动

### 1. 数据模型（新表 + 新外键）

**新建** **`app/models/ordinary_knowledge_base.py`**：

- `OrdinaryKnowledgeBase` 表 `ordinary_knowledge_bases`：`id`、`name`(String 200)、`genre`(String 50)、`source_work`(String 200)、`description`(Text)、`import_status`(String 20, default 'idle')、`import_progress`(JSON)、`created_at`、`updated_at`；`relationship("OrdinaryKnowledgeEntry", cascade="all, delete-orphan")`。

- `OrdinaryKnowledgeEntry` 表 `ordinary_knowledge_entries`：`id`、`base_id`(FK `ordinary_knowledge_bases.id` ondelete CASCADE)、`dimension`(String 32)、`content`(Text)、`attributes`(JSON)、`created_at`；`UniqueConstraint("base_id","dimension")`（每个库每个维度仅一条合并结果）。

**修改** **`app/models/novel.py`**：新增列

```python
ordinary_knowledge_base_id = Column(Integer, ForeignKey("ordinary_knowledge_bases.id", ondelete="SET NULL"), nullable=True)
```

**修改** **`app/database.py`** **的** **`_check_and_migrate`**：在 novels 分支补

```python
if "ordinary_knowledge_base_id" not in cols:
    sync_conn.execute(text("ALTER TABLE novels ADD COLUMN ordinary_knowledge_base_id INTEGER"))
```

（两张新表由 `create_all` 自动创建，前提是新模型在 `init_db` 前已被 import——通过新路由在 main.py 注册即满足。）

### 2. 提取服务（新文件，自包含）

**新建** **`app/services/ordinary_kb_service.py`**（仅 import `get_client`、`extract_text_from_file`、新模型、`async_session`；**不 import** **`kb_service`**）。txt/md 在本服务内做**编码鲁棒解码**；docx/pdf 复用 `extract_text_from_file`。

- `ORDINARY_DIMENSIONS`：7 维 key + 中文名 + 引导要点：

  - `theme` 主题的挖掘与立意

  - `character_arc` 人物（动机/缺陷/恐惧/渴望/弧光）

  - `plot_structure` 情节结构与节奏控制

  - `narrative_pov` 叙事视角与叙述声音

  - `language_style` 语言风格与细节描写

  - `worldbuilding` 世界观与规则自洽

  - `emotional_resonance` 情感共鸣与余味

#### 2a. 编码鲁棒解码（防 txt 乱码丢字）

`_decode_text_robust(filename, raw)`：`.txt/.md` 按 `utf-8-sig → utf-8 → charset_normalizer 检测 → gb18030 → big5 → utf-16 → errors="ignore"` 顺序尝试，取首个无替换符的解码；`.docx/.pdf` 走 `extract_text_from_file`。（共享 `document_parser` 对 txt 直接 `utf-8 errors="ignore"`，几百万字中文 GBK 小说会大面积丢字，故本服务自带解码。依赖 `charset-normalizer`，若未安装则加入 `requirements`。）

#### 2b. 无损分块（全量、不截断）

`_split_into_chunks(text, target=9000, overlap=400)`：按段落/句号边界切成 \~9000 字块，块间 \~400 字重叠防边界丢技法；**不设上限、不截断**，几百万字 → 数百块全部保留。

#### 2c. 分层 map-reduce（适配几百万字，不丢要点）

- **map**：`ORDINARY_EXTRACTION_PROMPT` 逐块提取，输出 JSON 7 字段，每字段限定 \~200-300 字「可借鉴的具体写法」（语言风格须摘原句+分析；情节结构须指转折/留白/加速点；人物须指弧光起止）。temp=0.4，max\_tokens=4096。并发 `MAX_CONCURRENT=6`，逐块失败重试 3 次。

- **reduce（递归）**：`ORDINARY_MERGE_PROMPT` 把多个块分析分批合并（`BATCH=25` 块/批，按上下文容量）成中间 7 维；若中间结果仍 >1，继续合并直至 1 份最终 7 维。temp=0.3。

- **最终**：upsert 7 条 `OrdinaryKnowledgeEntry`（base\_id+dimension 唯一），更新 `import_status='completed'`。

- 规模示例：300 万字 → \~340 块 → map 340 次 → reduce 约 14 批 → 最终 1 次，约 355 次 LLM 调用，一次性成本。

#### 2d. 断点续传 + 防丢失

- `import_progress`（JSON）持久化 `{total_chunks, done_chunks:[idx...], chunk_analyses:[{idx, dims...}], level, status, failed:[idx...]}`。

- 每块提取完成即 flush 进度；中断后重跑 `import-file` 时跳过 `done_chunks`、从断点继续，已提取内容不重算、不丢。

- 失败块记入 `failed` 并在流式进度上报，不静默跳过；最终若仍有失败块则 `import_status='partial'` 并提示用户重试该批。

- NDJSON 流式回传：`start{total}` → `progress{done,total,level,percent}` → `complete{dimensions}` / `error{msg}`。

#### 2e. 写作注入构建

`build_ordinary_kb_context(db, base_id)`：读 7 条 entry，拼成带维度标题的文本块（如 `【主题的挖掘与立意】\n...`），供 writer\_agent 注入。

### 3. API 路由（新文件）

**新建** **`app/api/ordinary_knowledge_bases.py`**（前缀 `/api/ordinary-knowledge-bases`）：

- `POST /` 创建；`GET /` 列表（带维度数）；`GET /{id}`；`PUT /{id}` 更新元信息；`DELETE /{id}` 删除。

- `GET /{id}/entries`（可按 `dimension` 过滤）；`POST /{id}/entries` 手动加；`PUT /{id}/entries/{eid}`；`DELETE /{id}/entries/{eid}`。

- `POST /{id}/import-file`：上传文件→调用 `extract_ordinary_kb_stream`，流式 NDJSON 响应；若该库 `import_progress` 显示 `processing/partial`，则**断点续传**（跳过已完成块，直接进入未完成块/合并）。

- `GET /{id}/import-status`：返回 `import_status` 与 `import_progress`（总块数/已完成/失败块/当前层级），供前端进度展示与续传判断。

- `GET /{id}/overview`：7 维度计数与状态。

**修改** **`app/main.py`**：在 [main.py:24,42](file:///d:/xiaoshuo/app/main.py#L24-L42) 旁新增

```python
from app.api.ordinary_knowledge_bases import router as ordinary_kb_router
...
app.include_router(ordinary_kb_router, prefix="/api/ordinary-knowledge-bases", tags=["普通知识库"])
```

**修改小说创建/更新 API**（`app/api/novels.py`，含 `from-qa` 与 update 端点）：请求体新增可选 `ordinary_knowledge_base_id` 字段并落库。

### 4. 写作注入（修改 writer\_agent + chapter\_service）

**修改** **`app/agents/writer_agent.py`** **`_build_writing_context`**（现有 kb\_context 块 [L156-159](file:///d:/xiaoshuo/app/agents/writer_agent.py#L156-L159) 之后）新增：

```python
ordinary_kb_context = state.get("ordinary_kb_context", "")
if ordinary_kb_context:
    context_parts.append("=== 写作技法参考（可借鉴，非硬性设定） ===\n" + ordinary_kb_context)
```

**修改** **`app/services/chapter_service.py`** **构建 state 处**（[L85-100, L276](file:///d:/xiaoshuo/app/services/chapter_service.py#L85-L100) 附近）：若 `novel.ordinary_knowledge_base_id`，调用 `build_ordinary_kb_context` 填入 `state["ordinary_knowledge_base_id"]`。

### 5. 前端（新页面 + 小说绑定）

**修改** **`static/index.html`**：在「知识库」面板（[L136-140](file:///d:/xiaoshuo/static/index.html#L136-L140)）「高级知识库」按钮旁加「普通知识库」按钮→`openOrdinaryKBManager()`；底部 script 引入 `ordinary-knowledge-base.js?v=20260905a`。

**新建** **`static/js/ordinary-knowledge-base.js`**（独立实现，不复用 knowledge-base.js 的函数；仅复用 `KB_GENRES` 常量）：

- 列表：卡片显示 名称/题材标签/原作/提取状态(⏳提取中/✓已提取)/维度数/删除。

- 创建表单：name、genre(`<select>` 复用 `KB_GENRES`)、source\_work、description。

- 详情：7 维度分区（用 `ORDINARY_DIMENSIONS` 中文名），每区折叠展示内容，支持手动增删改。

- 上传文件：流式解析 NDJSON，渲染进度条（镜像 rewrite\_agent 的 NDJSON 处理风格，但自包含）。

**修改** **`static/js/settings.js`（小说设置面板）**：新增「普通知识库」`<select>`（题材无关、可选「无」），调用 `PUT /api/novels/{id}` 更新 `ordinary_knowledge_base_id`；与现有高级库选择并列（若存在）。
（向导 `novel-wizard.js` 的可选绑定留作后续扩展，本期用设置面板满足「用户选择后使用」。）

### 6. 常量对齐

- 题材：复用 `KB_GENRES`。

- 维度：以后端 `ORDINARY_DIMENSIONS` 为准，前端用同名映射。

***

## 验证步骤

1. 启动服务 → `init_db` 自动建 `ordinary_knowledge_bases` / `ordinary_knowledge_entries` 表，并给 `novels` 表加 `ordinary_knowledge_base_id` 列（用 `PRAGMA table_info` 核对）。
2. 前端「普通知识库」→ 新建（题材=都市）→ 上传一个 **GBK 编码的几百万字 txt** 参考作品 → 验证：不乱码、分块覆盖全文（`import_progress.total_chunks` 与字数匹配）、流式进度推进、最终 7 维内容齐全；同样验证一个文本型 pdf 可正常解析提取。
   2b. 提取进行到中途关闭服务 → 重启后重跑 `import-file` → 从断点继续、已提取块不重算；模拟单块失败 → 该块重试 3 次后进 `failed`、状态为 `partial`，其余已提取内容不丢。
3. 创建/打开一部小说 → 设置面板绑定该普通库 → 写一章 → 后端提示词出现 `=== 写作技法参考（可借鉴，非硬性设定） ===` 且 7 维内容齐全。
4. 同时绑定普通库 + 高级库 → 写一章 → 两个 section 同时注入、互不覆盖。
5. 回归：高级库导入/详情/写作注入（`=== 知识库参考 ===`）正常；每章一致性（StoryKnowledge 图谱/阶段/区域）正常。
6. 删除普通库 → 对应小说的 `ordinary_knowledge_base_id` 被置空（SET NULL），写作不再注入技法段。

***

## 范围边界（不做）

- 不改 `knowledge_extractor.py` 的 StoryKnowledge 提取与相关图谱/角色阶段/世界区域。

- 不改 `kb_service.py` 的高级库 13 段流水线及其 CRUD/前端。

- 不接 `outline_agent`（本期仅章节写作注入；大纲注入可后续扩展）。

- 不做普通库的 ChromaDB 向量化（全量注入）。

- 不改 novel-wizard 的向导步骤流（用设置面板完成绑定）。

