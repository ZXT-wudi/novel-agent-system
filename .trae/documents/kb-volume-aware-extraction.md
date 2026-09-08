# 高级知识库——分卷提取 / 卷间关联 / 查重整合 / 卷级检索 改造方案

## 一、Summary（目标与范围）

把"高级知识库（KB）"从"按 8000 字符机械切块提取"改造为"按卷提取 + 卷间关联 + 卷内/跨卷查重整合 + 卷级检索"，并让卷结构贯穿小说创作全流程：

1. 上传 txt → 识别卷结构（显式卷标记 / 章·话标记合成卷 / 整篇兜底）→ 按卷逐卷提取六类知识，每卷提取完即落库（增量持久化 + 断点续传 + 进度可见）。
2. 全卷提取完成后，生成"每卷摘要"与"卷间显式关联"。
3. 跨卷查重：cosine≤0.15 的近重复表述合并；同名但有演变的实体保留分卷条目并建立关联。
4. 检索侧：生成"全文大纲"时按源卷组织喂入；生成"章节大纲"/写章节时按 `full_outline.volumes[].chapter_range` 推导出当前卷号，只检索该卷的 KB 条目。

成功标准：
- 同一 txt 重新提取时已完成的卷不重复处理（resume）。
- 前端/后台能看到"第 N 卷提取中 / 已完成"的进度。
- 章节大纲生成时，注入的 KB 上下文仅来自当前章节所属卷（而非全库杂乱注入）。
- 跨卷近重复条目数明显下降，同名演变实体可追溯。

---

## 二、Current State Analysis（现状与问题）

### 现状关键代码（均已通读确认）

- `app/services/kb_service.py`
  - L13-16：`CHUNK_SIZE=8000`、`CHUNK_OVERLAP=400` —— 按字符切块，**无视卷边界**，导致"杂乱没有连续性"。
  - L92-121 `add_entry`：写 DB + 向量，元数据仅 `{category, title, source}`，**无 volume**。
  - L224-308 `build_kb_context_for_agent`：全库按类别限量加载 + 向量补充（0.75 阈值），**全库无差别注入**，被大纲/章节/写作/扩写 4 处共用。
  - L311-328 `_split_text_into_chunks`：纯字符切块，换行偏好。
  - L331-343 `_dedup_entries`：仅按 `name` 大小写去重，**无语义查重、无跨卷处理**。
  - L346-401 `_extract_from_chunk`：LLM 提取六类（worldview/character/event/timeline/faction/setting），**无卷上下文**。
  - L404-543 `import_file_to_kb`：主入口，含预提取守卫、批处理；**一次性处理、无进度、无断点续传、崩溃全丢**。

- `app/rag/retriever.py`
  - L33-49 `query_collection`：支持 `where` 但 KB 侧不用。
  - L113-125 `query_kb`：**不支持 `where`**（无法按卷过滤向量）。

- `app/models/knowledge_base.py`
  - `KnowledgeBase`：id/name/genre/.../entries；**无卷结构字段**。
  - `KnowledgeEntry`：id/kb_id/category/title/content/attributes(JSON)/source/created_at；**无 volume 字段**。

- `app/agents/outline_agent.py`
  - L104-146：`full_outline.volumes[]` JSON 已含 `volume_number/title/chapter_range/六要素`——**卷标记能力已存在**，缺的是"把 KB 按源卷喂进去"。
  - L343-347 `_build_chapter_outline_messages`：已按 `chapter_range` 重叠算 `relevant_volumes`——**这正是"按全文大纲标明的卷检索"的钩子**，但 KB 上下文未据此过滤。

- `app/services/outline_service.py`
  - L57 `generate_full_novel_outline`、L90 `generate_chapter_outline_batch`：都调 `build_kb_context_for_agent`，**未传任何卷信息**。

- `app/services/chapter_service.py` L99-104：写作前构建 `kb_context`，同样**未传卷信息**。

- `app/services/novel_service.py` L240-266 `expand_novel_from_qa`：小说创建扩写时调 `build_kb_context_for_agent`（无卷）。

- `app/services/knowledge_service.py` L220-317 `index_full_outline_to_rag`：把 `full_outline.volumes[]` 六要素索引进 `world_knowledge`，文本前缀 `[卷N-...]` 但**元数据无 volume_number**。

### 核心缺陷归纳
1. 切块无视卷 → 提取结果无连续性、跨卷混杂。
2. 无卷级元数据 → 检索无法按卷过滤，章节大纲/写作注入的是全库杂乱内容。
3. 去重仅同名 → 跨卷重复表述堆积，存储膨胀。
4. 一次性提取 → 无进度、崩溃全丢。
5. 卷间无关联 → 卷与卷割裂。

---

## 三、Proposed Changes（按文件，含 what/why/how）

### 3.1 数据模型 —— `app/models/knowledge_base.py`

**what**：给 `KnowledgeBase` 与 `KnowledgeEntry` 增加卷相关字段。

**why**：需要可查询的卷字段（SQL `where` 与向量 `where` 双侧过滤）+ 卷结构/关联/进度的持久化（断点续传依赖）。沿用代码库"JSON 列装结构化数据"的既有约定（参见 `Novel.full_outline`/`Novel.outline`/`Novel.world_settings` 均 JSON），不新增表，降低迁移成本。

**how**：
- `KnowledgeBase` 增加：
  - `volumes = Column(JSON, default=list)`：卷结构数组 `[{volume_number, title, char_range:[start,end], chapter_count, summary, status:"pending"|"extracted"|"failed", entry_count, extracted_at}]`
  - `volume_relations = Column(JSON, default=list)`：跨卷关联 `[{from_vol, to_vol, relation_type:"承接"|"伏笔回收"|"角色演变"|"设定演进"|"时间跳跃", description}]`
  - `import_status = Column(String(20), default="idle")`：`idle|running|completed|partial`
  - `import_progress = Column(JSON, default=dict)`：`{total_volumes, completed:[...], failed:[...], started_at, updated_at, current_volume}`
- `KnowledgeEntry` 增加：
  - `volume = Column(Integer, nullable=True)`：所属卷号；历史数据为 `NULL`（视为"全卷通用"）
  - `volume_title = Column(String(200), nullable=True)`
- 关系不变；`KnowledgeEntry` 仍 `cascade="all, delete-orphan"`。

**迁移**：新增列均 `nullable`，旧库自动兼容（`volume=NULL`、`volumes=[]`、`import_status="idle"`）。无需数据搬迁。

---

### 3.2 卷识别与切分 —— 新建 `app/services/volume_splitter.py`

**what**：独立模块负责"把 txt 切成卷"。

**why**：卷识别逻辑独立、可测、可被 `import_file_to_kb` 复用；正则与中文数字解析集中一处。

**how**：

```python
import re

_CN = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,"百":100,"千":1000,"零":0}

def _cn2int(s: str) -> int:
    # 阿拉伯数字直转；中文数字按位权累加（支持 十二/二十三/一百零五 等）
    ...

VOLUME_PATTERNS = [
    re.compile(r"第\s*([一二三四五六七八九十百千零\d]+)\s*[卷部册]"),   # 第X卷/部/册
    re.compile(r"^\s*卷\s*([一二三四五六七八九十百千零\d]+)"),            # 卷X（行首）
    re.compile(r"^\s*([上中下])\s*[篇部卷]"),                          # 上篇/中篇/下篇
]
CHAPTER_PATTERNS = [
    re.compile(r"第\s*([一二三四五六七八九十百千零\d]+)\s*[章话回]"),     # 第X章/话/回
]

def detect_volumes(text: str, synth_every: int = 20) -> list[dict]:
    """
    返回 [{volume_number, title, char_range:[start,end], source:"explicit"|"synthetic"|"whole"}]
    策略：
      1. 扫 VOLUME_PATTERNS，命中的位置切出显式卷（source=explicit）。
      2. 若无显式卷但命中 CHAPTER_PATTERNS：按章号排序，每 synth_every 章合成一卷（source=synthetic）。
      3. 若两者皆无：整篇作第 1 卷（source=whole）。
    章号→卷号映射：vol = floor((ch_num-1)/synth_every) + 1。
    """
```

- 显式卷标题：取该卷首行剩余文本（去标记）作 `title`，空则 `第N卷`。
- 合成卷标题：`第N卷（第a-b章）`。
- 边界：卷 i 的 `[start, end]` = 卷 i 起始位 → 卷 i+1 起始位前（末卷到文本尾）。

---

### 3.3 KB 提取主流程改造 —— `app/services/kb_service.py`

#### 3.3.1 `import_file_to_kb` 重构（L404-543）

**what**：改为"先切卷 → 逐卷提取 → 每卷即落库 → 全卷后建关联/摘要 → 断点续传"。

**why**：满足"按卷提取、进度可见、提取一卷保存一卷、崩溃续传"。

**how**（新流程）：
1. 解析文本（`extract_text_from_file`，复用现有）。
2. 调 `volume_splitter.detect_volumes(text)` 得卷结构。
3. 写入 `kb.volumes`（`status="pending"`）+ `kb.import_status="running"` + `import_progress`，`db.commit()`。
4. 遍历卷：
   - 若 `volumes[i].status == "extracted"`：跳过（**断点续传**）。
   - 否则：取该卷文本切片（仍用 `_split_text_into_chunks` 在**卷内**切块，`CHUNK_SIZE` 不变但边界不跨卷）。
   - 逐块调 `_extract_from_volume(...)`（见 3.3.2）→ 卷内 `_dedup_entries` 去重 → `add_entry`（带 `volume`/`volume_title`）→ 写 DB + 向量（元数据加 `volume_number`）。
   - 每卷完成后：`volumes[i].status="extracted"`、`entry_count`、`extracted_at=now`；`import_progress.completed.append(i)`；`db.commit()`（**一卷一落库**）。
   - 进度产出：`yield {"type":"volume_done","volume":i,"title":...,"entry_count":...}`（供 API 流式回传）。
5. 全卷完成 → 调 `_build_volume_relations_and_summaries`（见 3.3.3）→ 写 `kb.volume_relations` + `volumes[].summary` → `import_status="completed"`，`db.commit()`。
6. 失败卷：`status="failed"`，`import_status="partial"`；下次重传跳过 extracted、重试 failed。

**预提取守卫**：保留现有"已有结构化条目则跳过"逻辑，但改为"按卷判断 `status`"。

#### 3.3.2 `_extract_from_chunk` → `_extract_from_volume`

**what**：提取函数感知卷上下文。

**how**：函数签名增加 `volume_number: int, volume_title: str`；prompt 顶部注入 `【当前提取范围：第{volume_number}卷《{volume_title}》】`，并要求"仅提取本卷范围内明确出现的信息，不跨卷补脑"。输出 JSON 结构不变（六类），但每条隐式归属当前卷（由调用方在 `add_entry` 时打 `volume` 标）。

#### 3.3.3 `_build_volume_relations_and_summaries`（新增）

**what**：全卷提取后生成每卷摘要 + 卷间关联。

**how**：
- 输入：各卷的 `entry` 列表（按 category 聚合）+ 卷文本前 1000 字采样。
- LLM prompt（低温 0.3）输出严格 JSON：
  ```json
  {
    "summaries": [{"volume_number":1,"summary":"本卷设定/人物/事件概述，100-200字"}],
    "relations": [{"from_vol":1,"to_vol":2,"relation_type":"承接","description":"卷一结局事件在卷二发酵"}]
  }
  ```
- 写入 `kb.volumes[v].summary` 与 `kb.volume_relations`。
- 容错：JSON 解析失败则摘要置空、关联置空，不阻断主流程。

#### 3.3.4 跨卷语义查重 —— 新增 `_cross_volume_dedup`

**what**：跨卷仅合并近重复（cosine≤0.15），同名演变保留并建关联。

**why**：用户选定"按卷保留+仅合并近重复"——兼顾连续性与减存储。

**how**（在每卷新条目入库后、关联生成前增量执行）：
- 对当前卷每条新 `entry`：
  - `embed_single(entry.title + ":" + entry.content[:200])` 得向量。
  - `query_kb(kb_id, query_text, n_results=5, where={"category":entry.category, "volume_number":{"$ne": current_vol}})` 取其它卷同类条目。
  - 记 `kb_service` 已有 `query_kb` 需扩 `where`（见 3.4）。
  - 若最佳 cosine ≤ 0.15（**近重复表述**）：`_llm_merge_entries(old, new)` 合并 content（LLM 融合，保留更全信息）→ `update_in_kb` 更新向量 + DB content → 删除新条目（`delete_from_kb` + DB delete）→ 计 `merged_count`。
  - 否则若 `name` 同名（大小写不敏感）但 cosine>0.15（**演变**）：保留两条，追加 `volume_relations` 一条 `{from_vol:other, to_vol:current, relation_type:"角色演变"/"设定演进", description:"<name>在第X→Y卷的变化"}`。
  - 否则：保留，无关联。
- 阈值 `0.15` 设为模块常量 `CROSS_VOLUME_MERGE_THRESHOLD=0.15`，便于调参。

#### 3.3.5 `build_kb_context_for_agent` 增卷参数（L224-308）

**what**：新增 `volume_numbers: list[int] | None = None` 与 `comprehensive: bool=False`（已有）的组合语义。

**how**：
- `volume_numbers` 非空（章节大纲/写作场景）：
  - DB 侧：`select(KnowledgeEntry).where(kb_id==.., or_(volume.in_(volume_numbers), volume.is_(None)))` —— `NULL` 视为"全卷通用"，向后兼容历史数据。
  - 向量补充：`query_kb(kb_id, query_text, n_results=40, where={"$or":[{"volume_number":{"$in":volume_numbers}},{"volume_number":None}]})`（`query_kb` 需支持 `where`，见 3.4）。
  - 输出按 category 分段（现有格式），条目前可加 `[卷N]` 前缀。
- `volume_numbers` 空且 `comprehensive=True`（全文大纲场景）：
  - 按**源卷**分组输出：`【源卷一《标题》】\n- 角色：...\n【源卷二《标题》】\n...` + 末尾 `【跨卷关联】` 段（来自 `kb.volume_relations`）+ `【各卷摘要】` 段。
- `volume_numbers` 空且 `comprehensive=False`（扩写/默认）：维持现状（全库限量），最小改动。

#### 3.3.6 `_dedup_entries` 不变
卷内仍用同名去重（L331-343），跨卷交给 3.3.4。

---

### 3.4 检索侧 —— `app/rag/retriever.py`

**what**：`query_kb` 增加 `where` 与 `n_results` 已有，补 `where: dict | None = None`。

**how**（L113-125）：
```python
async def query_kb(kb_id, query_text, n_results=5, where=None) -> dict:
    ...
    kwargs = {"query_embeddings":[query_embedding], "n_results":n_results}
    if where:
        kwargs["where"] = where
    return collection.query(**kwargs)
```
与 `query_collection`（L33-49）的 `where` 用法对齐。

---

### 3.5 全文大纲生成 —— `app/agents/outline_agent.py` + `app/services/outline_service.py`

**what**：生成全文大纲时按源卷喂入 KB；大纲每卷已自带 `volume_number`（已有，无需改 prompt 结构）。

**how**：
- `outline_service.generate_full_novel_outline`（L57）改：
  ```python
  kb_context = await build_kb_context_for_agent(db, novel.knowledge_base_id, description or novel.description or "", comprehensive=True)
  ```
- `outline_agent._build_full_outline_messages`（L263-327）：`kb_section` 文案改为"按源卷组织，须将源卷设定映射到本小说对应卷"——`build_kb_context_for_agent(comprehensive=True)` 已产出按源卷分段的文本，直接注入即可。无需改 prompt JSON schema（`volume_number` 字段早已有）。

---

### 3.6 章节大纲生成 —— `app/services/outline_service.py` + `app/agents/outline_agent.py`

**what**：章节大纲按 `full_outline.volumes[].chapter_range` 推导当前卷号，只检索该卷 KB。

**how**：
- `outline_service.generate_chapter_outline_batch`（L80-110）改：
  ```python
  fo = novel.full_outline or {}
  vol_nums = [v.get("volume_number") for v in fo.get("volumes", [])
              if _vol_overlap(v.get("chapter_range",[0,0]), start_chapter, start_chapter+batch_size-1)]
  kb_context = await build_kb_context_for_agent(db, novel.knowledge_base_id,
              f"第{start_chapter}章到第{start_chapter+batch_size-1}章",
              volume_numbers=vol_nums or None)
  ```
  `_vol_overlap(rng, s, e): return rng[1]>=s and rng[0]<=e`（与 `outline_agent` L346 同口径，可抽公共函数）。
- `outline_agent._build_chapter_outline_messages`（L343-347）已算 `relevant_volumes` 用于注入卷概述，**保持不变**；KB 卷过滤在 service 层完成。

---

### 3.7 写章节 —— `app/services/chapter_service.py`

**what**：写作前构建 `kb_context` 时按章节号推卷。

**how**（L99-104）：
```python
if novel.knowledge_base_id:
    ch_num = chapter_number
    vol_nums = [v.get("volume_number") for v in (novel.full_outline or {}).get("volumes", [])
                if _rng_overlap(v.get("chapter_range",[0,0]), ch_num, ch_num)]
    kb_context = await build_kb_context_for_agent(db, novel.knowledge_base_id, query_text, volume_numbers=vol_nums or None)
```
`_rng_overlap` 同 3.6（可放 `app/services/_vol_util.py` 或并入 `kb_service`）。

---

### 3.8 小说创建扩写 —— `app/services/novel_service.py`

**what**：`expand_novel_from_qa`（L240-266）此时小说尚无 `full_outline`，无法推卷。

**how**：维持现状（默认全库限量注入），不改。仅注释说明"卷级检索在大纲/写作阶段生效"。符合用户范围（"只能创建小说"主要指创建后的大纲流程，扩写阶段无卷可推）。

---

### 3.9 API —— `app/api/knowledge_bases.py`

**what**：导入接口改为流式 + 进度 + 断点续传；新增进度查询端点。

**how**：
- `POST /{kb_id}/import-file`（L138-149）改为流式（NDJSON，仿 `chapter_service.generate_chapter_with_stream`）：
  - 解析上传文件 → 调改造后的 `import_file_to_kb`（改为 `AsyncGenerator`）。
  - 每卷完成 `yield {"type":"volume_done",...}`；结束 `yield {"type":"complete", summary}`。
  - 重传时跳过已 `extracted` 的卷（断点续传）。
- 新增 `GET /{kb_id}/import-status`：返回 `kb.import_status` + `kb.import_progress` + `kb.volumes[].status`，供前端重连后展示进度。
- 现有 CRUD/`vector-status` 等不变。

---

### 3.10 前端进度（最小改动）

**what**：导入弹窗展示逐卷进度。

**how**：`static/js/novel-wizard.js`（或对应 KB 管理页 JS）消费流式 NDJSON，渲染"第 N 卷《标题》提取中/完成"。非本次后端核心，列出但实现轻量。

---

### 3.11 既有 `index_full_outline_to_rag` 顺手补元数据（可选小改）

`app/services/knowledge_service.py` L258-281：给卷六要素向量条目元数据加 `{"source":"outline","type":"full_outline","volume_number":vol_num}`，使后续按卷过滤一致。低风险，纳入本次。

---

## 四、数据流（文本示意）

```
上传 txt
  ↓ volume_splitter.detect_volumes → kb.volumes(写) + import_status=running
  ↓ 逐卷（跳过 extracted）：
  ↓    卷内切块 → _extract_from_volume(带卷号) → 卷内 _dedup → add_entry(volume=N)
  ↓    _cross_volume_dedup(≤0.15合并 / 同名演变建关联) → 一卷落库 commit + yield 进度
  ↓ 全卷完 → _build_volume_relations_and_summaries → kb.volume_relations + volumes[].summary → completed

全文大纲：build_kb_context_for_agent(comprehensive=True) → 按源卷分段注入 → LLM 设计 novel.volumes（每卷 volume_number）
章节大纲：service 由 chapter_range 推 vol_nums → build_kb_context_for_agent(volume_nums) → 仅当前卷 KB 注入
写章节：service 由 chapter_number 推 vol → build_kb_context_for_agent(volume_nums=[vol]) → 仅当前卷 KB
```

---

## 五、Edge Cases / 失败模式

- **无卷标记且无章标记**：整篇作第 1 卷，`source="whole"`，仍走分卷流程（统一路径）。
- **卷标记错乱/缺号**：按出现顺序重新编号为 1..N，`title` 保留原文。
- **单卷过长**（>200k 字）：卷内仍按 `CHUNK_SIZE=8000` 切块，受 `MAX_LLM_CHUNKS=80` 保护（已有）。
- **LLM 提取单卷失败**：该卷 `status="failed"`，`import_status="partial"`，不阻断其它卷；重传只重试 failed/pending。
- **跨卷合并误判**（cosine≤0.15 实为不同实体）：阈值偏保守（0.15 很严格），且仅合并同 category；合并前 LLM 再判一次"是否同一实体"，双保险。
- **历史 KB（volume=NULL）**：卷级检索时 `NULL` 视为"全卷通用"一并召回，向后兼容。
- **同一 KB 多次重传不同 txt**：以最新 `import_status` 为准；若已 completed 再传，提示"将清空旧条目重新切卷"（或加 `?force=1`）。本方案默认：重传同 KB 触发"跳过已 extracted 卷"，若需全新提取先删条目再传。

---

## 六、Testing / Acceptance

- **单元**：`volume_splitter`
  - 显式卷：`第X卷`/`卷X`/`上中下篇` 各一例 → 卷数/标题/char_range 正确。
  - 合成卷：仅 `第X章`/`第X话` 的 txt → 每 20 章一卷。
  - 兜底：纯文本无任何标记 → 1 卷。
  - `_cn2int`：`十二`/`二十三`/`一百零五`/`99` 正确。
- **集成**（手动）：
  - 上传一个 3 卷 txt → `kb.volumes` 3 条、`import_status=completed`、各卷 `entry_count>0`。
  - 中途 Ctrl+C → `import_status=partial`；重传 → 跳过已提取卷，`completed`。
  - 跨卷同名角色（如"萧炎"在卷一/卷三）→ 保留两条 + `volume_relations` 含"角色演变"。
  - 跨卷近重复世界观表述 → 合并为 1 条。
  - 生成全文大纲 → 日志/响应中 `kb_context` 含"【源卷一】...【源卷二】...【跨卷关联】"。
  - 生成章节大纲（第 25-30 章，属卷二）→ 注入的 KB 条目仅来自卷二（`volume=2`）+ NULL 通用条目。
- **回归**：旧 KB（无 volume）仍能被大纲/写作正常注入（NULL 召回）。

---

## 七、Migration / 兼容

- 新增列均 `nullable`，Alembic 自动 `ALTER TABLE`；旧数据 `volume=NULL`/`volumes=[]`/`import_status="idle"`。
- 旧 KB 检索：`volume_numbers` 过滤时 `OR volume IS NULL`，行为不退化。
- 不删除/不重写既有 `_split_text_into_chunks`/`_dedup_entries`/`add_entry`/`query_kb` 旧签名，仅扩展参数（向后兼容）。

---

## 八、Assumptions & Decisions

1. **数据模型**：`KnowledgeBase.volumes/volume_relations/import_status/import_progress`（JSON）+ `KnowledgeEntry.volume/volume_title`（列）。沿用代码库 JSON 列约定，不新增表。✓（基于 `Novel.full_outline` 等既有模式）
2. **卷识别**：混合策略——显式卷标记优先；无卷但有章/话标记则每 20 章合成一卷；皆无则整篇为卷 1。✓（用户 Q1 定制答案）
3. **跨卷查重**：cosine≤0.15 近重复合并；同名演变保留并建关联。✓（用户 Q2 选"按卷保留+仅合并近重复"）
4. **进度/续传**：流式 NDJSON + `volumes[].status` + `import_status` + `GET /import-status`；重传跳过 extracted。✓（用户附加要求）
5. **检索分场景**：全文大纲 `comprehensive=True`（按源卷分组）；章节大纲/写作按 `chapter_range` 推 `volume_numbers` 过滤；扩写维持默认。✓（用户 Q4：全文大纲输入每卷、章节大纲按卷检索）
6. **阈值常量**：`CROSS_VOLUME_MERGE_THRESHOLD=0.15`、`SYNTH_VOLUME_EVERY=20`，模块级可调。
7. **不改**：`outline_agent` prompt 的 JSON schema（`volume_number` 早已有）；`expand_novel_from_qa`（无卷可推）；readers（不直查 KB）。
8. **范围确认**：用户要求"只能创建小说/全文大纲/章节大纲/各智能体调库处都要改"——本方案覆盖 `novel_service.expand`（评估不改）、`outline_service`（全文/章节大纲）、`chapter_service`（写作）、`outline_agent`（prompt 文案）、`kb_service`/`retriever`（底层），即全部"调库处"的统一 chokepoint `build_kb_context_for_agent`。

---

## 九、Rollout 顺序（实施步骤）

1. 模型加字段 + 迁移。
2. `volume_splitter.py` + 单测。
3. `retriever.query_kb` 加 `where`。
4. `kb_service`：`_extract_from_volume`、`import_file_to_kb` 重构（流式 + 续传）、`_cross_volume_dedup`、`_build_volume_relations_and_summaries`、`build_kb_context_for_agent` 增参。
5. `outline_service` / `chapter_service`：推卷号并传参。
6. `outline_agent._build_full_outline_messages`：`kb_section` 文案。
7. `knowledge_bases.py`：流式导入 + 进度端点。
8. `knowledge_service.index_full_outline_to_rag`：补 `volume_number` 元数据。
9. 前端进度渲染（轻量）。
10. 手动集成测试 + 回归旧 KB。
