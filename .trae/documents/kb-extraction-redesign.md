# 知识库提取重构方案：按卷·章摘要派生式提取

## 一、Summary

当前知识库提取以**"按 8000 字块独立抽 6 类"**为主干（[_extract_volume_entries](file:///d:/xiaoshuo/app/services/kb_service.py#L653) → [_extract_from_volume](file:///d:/xiaoshuo/app/services/kb_service.py#L586)），带来三个问题：

1. **量虚高且杂乱**：每卷切成最多 80 块、每块独立抽 6 类（max_tokens=4096），块间 400 字重叠 + 仅按 name 精确去重（[_dedup_entries](file:///d:/xiaoshuo/app/services/kb_service.py#L571)）→ 同一实体跨块多次留存，条目膨胀到几百条冗余。
2. **卷总结覆盖不全**：[_extract_volume_event_summary](file:///d:/xiaoshuo/app/services/kb_service.py#L692) 只读 `vtext[:8000]`，4 万字的卷只看到头 1/5，与逐章摘要（覆盖整卷）口径不一致。
3. **时间/事件对不上**：6 类从任意字符块抽取，没有"卷内章序"约束，时间线与事件脱钩。

本方案将架构重构为**以"章摘要"为脊柱的按卷派生式提取**：

- **Pass A（每卷，脊柱，关键路径）**：先抽每卷章摘要（summary+characters+key_events）→ 反向聚合章摘要得卷总结（map-reduce，覆盖整卷）。
- **Pass B（每卷，派生 6 类）**：6 类全部从"本卷章摘要 + 卷总结"派生，丢弃块级 6 类。每类规则：
  - **世界观**：跨卷 embedding 余弦去重（前几卷相似则后续不重复记录）
  - **角色**：跟着章摘要，只记重点角色（跨章出场频次 + 关键事件提及）
  - **事件**：跟着章摘要，记录主线 + 主角/其他角色感情戏 + 角色成长，跳过与主线无关的内容
  - **时间线**：从事件按本卷章序派生（时间事件天然对齐）
  - **势力/阵营**：从事件 + 章摘要派生
  - **设定**：从事件 + 章摘要派生
- **大纲衔接**：全文大纲用卷内容（卷总结）生成，卷号已由 [full_outline.volumes[].chapter_range](file:///d:/xiaoshuo/app/agents/outline_agent.py#L104-L135) 记录；章节大纲通过 [volumes_for_chapter_range](file:///d:/xiaoshuo/app/services/volume_splitter.py#L231) + Task E 的 `build_kb_context_for_agent(volume=, chapter_numbers=)` 取"对应卷内六类 + 章节内容"。**大纲侧无需新管道、无需改大纲 schema**。

### 与上一版方案（kb-volume-chapter-hierarchy.md，已完成）的关系

上一版补齐了"章节级索引 + 层级检索 + 前端卷筛选"（KnowledgeEntry 加 chapter_number、新增 volume_event/chapter_summary 分类、build_kb_context_for_agent 加 chapter_numbers）。本方案**复用**这些基础设施，只重构**提取内容的生产方式**（从块级 6 类 → 章摘要派生 6 类），不改 KB schema、不改大纲 schema、不改检索接口。

## 二、Current State Analysis

### 已有（本方案复用，无需改动）
- [volume_splitter.detect_volumes](file:///d:/xiaoshuo/app/services/volume_splitter.py)：卷识别（已修复卷数爆炸）✅
- [volume_splitter.detect_chapters_in_volume](file:///d:/xiaoshuo/app/services/volume_splitter.py)：卷内章/话切分（含"本卷全文"fallback）✅
- [_extract_chapter_summary](file:///d:/xiaoshuo/app/services/kb_service.py#L710)：单章摘要（summary+characters+key_events，chapter_text[:8000]）✅ 作为脊柱保留
- [_extract_chapter_summaries_batch](file:///d:/xiaoshuo/app/services/kb_service.py#L761)：批量并发章摘要 ✅ 作为脊柱保留
- `KnowledgeEntry`：已有 volume/volume_title/chapter_number/chapter_title（上一版加的）✅ 无需迁移
- `KB_CATEGORY_LABELS`（[L229-241](file:///d:/xiaoshuo/app/services/kb_service.py#L229-L241)）：8 个分类值不变 ✅
- `build_kb_context_for_agent`：已有 volume + chapter_numbers 参数（上一版加的）✅
- [_build_comprehensive_volume_context](file:///d:/xiaoshuo/app/services/kb_service.py)：comprehensive 模式已含每卷 volume_event + chapter_summary ✅
- [embed_single/embed_texts](file:///d:/xiaoshuo/app/rag/embedder.py#L17-L38)：BAAI/bge-large-zh-v1.5，1024 维 ✅
- [query_kb](file:///d:/xiaoshuo/app/rag/retriever.py#L113)：ChromaDB 相似检索 ✅
- [full_outline.volumes[].chapter_range](file:///d:/xiaoshuo/app/agents/outline_agent.py#L104-L135) + [volumes_for_chapter_range](file:///d:/xiaoshuo/app/services/volume_splitter.py#L231)：章→卷动态映射 ✅

### 待重构（本方案替换）
- [_extract_volume_entries](file:///d:/xiaoshuo/app/services/kb_service.py#L653)：块级 6 类 → **删除**，由派生函数取代
- [_extract_from_volume](file:///d:/xiaoshuo/app/services/kb_service.py#L586)：单块 6 类 prompt → **删除**
- [_split_text_into_chunks](file:///d:/xiaoshuo/app/services/kb_service.py#L551)：块切分 → **变为无人调用**（章摘要用截断不用切块），可删
- `MAX_LLM_CHUNKS`、`CHUNK_OVERLAP` 常量：→ **变为无人引用**，可删（`CHUNK_SIZE` 保留，章摘要截断仍用）
- [_extract_volume_event_summary](file:///d:/xiaoshuo/app/services/kb_service.py#L692)：输入 `vtext[:8000]` → **改为吃章摘要**（map-reduce）
- 导入循环 [L1090-1219](file:///d:/xiaoshuo/app/services/kb_service.py#L1090)：per-volume 顺序与条目创建 → **重构**

## 三、Proposed Changes

### Step 1: 新增 7 个派生提取函数（per-volume，从章摘要派生 6 类 + 卷总结）

**文件**: `app/services/kb_service.py`（在 [_extract_chapter_summaries_batch](file:///d:/xiaoshuo/app/services/kb_service.py#L761) 之后新增）

所有派生函数的公共输入：`chapters_data: list[dict]`（每项含 `chapter_number, chapter_title, summary, characters[], key_events[]`）、`volume_number`、`volume_title`。除世界观去重外，均不读写 DB。

**1a. `_build_volume_summary_from_chapters(chapters_data, vn, vol_title) -> str`**（替换 _extract_volume_event_summary 的输入来源）
- 拼接各章 `summary` + `characters` + `key_events` 为一段结构化文本
- LLM prompt："以下是第N卷各章摘要与出场角色/关键事件，请综合成该卷主要事件走向与重要角色弧光总结，300-600字，按情节先后组织，突出因果与转折"
- `temperature=0.3, max_tokens=2048`，失败返回空串
- 覆盖整卷（不再只看前 8000 字）

**1b. `_derive_key_characters(chapters_data, vn, vol_title) -> list[dict]`**
- 聚合所有章 `characters[]` + `key_events[]` 中出现的角色名 → 按跨章出场次数 + 在 key_events 中被提及次数 排序
- 只保留重点角色：出场章数 ≥ `KEY_CHAR_MIN_CHAPTERS`（建议 2）或 在 key_events 中被提及 ≥ `KEY_CHAR_MIN_EVENTS`（建议 2）
- 对每个重点角色：拼接其出场的章节摘要 → 一次 LLM 合并成单条 `{name, content}`（身份/能力/关系/本卷内成长弧光）
- 输出 `[{name, content}]`，一条角色一条记录（彻底解决块间重复）

**1c. `_derive_volume_events(chapters_data, vn, vol_title) -> list[dict]`**
- 主线事件：聚合各章 `key_events[]`（带 chapter_number 出处）→ LLM 整合成 `{name, content, characters}`，prompt 明确"跳过与主线无关的日常/插曲，只保留推动主线或角色弧光的事件"
- 感情戏子抽取：LLM over 章摘要："提取该卷主角及主要角色之间的感情线发展关键节点"→ 事件条目，`attributes={"subtype":"romance"}`
- 角色成长子抽取：LLM over 章摘要："提取该卷主要角色的成长/转变节点"→ 事件条目，`attributes={"subtype":"growth"}`
- 合并三类事件 → `[{name, content, characters, attributes}]`
- `temperature=0.3, max_tokens=3072`

**1d. `_derive_timeline(events, vn, vol_title) -> list[dict]`**
- 输入 1c 的 events（含 chapter_number 出处）→ 按 chapter_number 排序
- LLM 轻量整理成 `[{name: 时间节点, content: 时间描述与对应事件}]`，`temperature=0.2, max_tokens=1536`
- 时间线天然跟随卷内章序 → 解决"时间事件对不上"

**1e. `_derive_factions(chapters_data, events, vn, vol_title) -> list[dict]`**
- LLM over 章摘要 + events："提取该卷出现的势力/组织/阵营及其立场、成员、与主线冲突"
- 输出 `[{name, content}]`，`max_tokens=2048`

**1f. `_derive_settings(chapters_data, events, vn, vol_title) -> list[dict]`**
- LLM over 章摘要 + events："提取与主线相关的设定（功法/地理/规则/道具/种族等），跳过与主线无关的"
- 输出 `[{name, content}]`，`max_tokens=2048`

**1g. `_derive_worldview_with_dedup(chapters_data, vn, vol_title, kb_id, cached_embs) -> list[dict]`**
- LLM over 章摘要："提取该卷展现的世界观要素（地理/世界规则/体系/格局/风俗）"→ 候选 `[{name, content}]`
- 对每个候选：`emb = await embed_single(name + content)` → 与 `cached_embs`（已存 worldview 条目向量列表）算余弦 → 若 max 余弦 ≥ `WORLDVIEW_DEDUP_THRESHOLD`（0.85）→ 跳过；否则加入候选集并 `cached_embs.append((title, emb))`
- 输出新增的 worldview 条目 `[{name, content}]`
- `cached_embs` 在导入开始时一次性从 ChromaDB 取回本 KB 已有 worldview 条目向量（见 Step 4），随每卷新增追加 → 兼容续传

### Step 2: 改造 _extract_volume_event_summary 为 map-reduce

**文件**: `app/services/kb_service.py` — [_extract_volume_event_summary](file:///d:/xiaoshuo/app/services/kb_service.py#L692)

- 保留函数名（导入循环调用点不改），改签名：`_extract_volume_event_summary(chapters_data, vn, vol_title)`（入参由 `vtext` 改为 `chapters_data`）
- 内部委托 `_build_volume_summary_from_chapters`（Step 1a）
- 删除 `vtext[:CHUNK_SIZE]` 截断逻辑（L693）

### Step 3: 重构导入循环（per-volume 顺序调整 + 派生 6 类替换块级 6 类）

**文件**: `app/services/kb_service.py` — `import_file_to_kb_stream` 卷循环 [L1110-1216](file:///d:/xiaoshuo/app/services/kb_service.py#L1110)

当前 per-volume 顺序：reset → vtext → **块级 6 类** → 建 6 类条目 → 卷总结(vtext[:8000]) → 建卷总结条目 → 章摘要批 → 建章摘要条目 → 向量 → 跨卷查重 → commit。

新 per-volume 顺序：

```
1. _reset_volume(db, kb_id, vn)                                    # 不变
2. vtext = text[vstart:vend]; 若空 continue                         # 不变
3. chapters_data = await _extract_chapter_summaries_batch(vtext, vn, vol["title"])   # 脊柱，最先
4. 建 chapter_summary 条目（遍历 chapters_data，复用现 L1160-1176 逻辑）            # 不变
5. vol_event_text = await _extract_volume_event_summary(chapters_data, vn, vol["title"])  # 改：吃 chapters_data
6. 建 volume_event 条目（复用现 L1146-1157 逻辑）                                     # 不变
7. derived = await _derive_volume_all(chapters_data, vol_event_text, vn, vol["title"], kb_id, cached_embs)
   # 内部并发跑 1b/1c/1e/1f/1g，1d 串在 1c 后；返回 {character,event,timeline,faction,setting,worldview}
8. 建 6 类条目（遍历 derived 各类，category 对应，volume=vn，chapter_number=None，event 带 attributes）
9. vol["chapters"] = [...]                                          # 不变
10. await db.flush() → 向量索引（复用现 L1183-1200）→ 跨卷查重（L1203，保留）→ commit   # 不变
```

- 删除 L1118 `_extract_volume_entries(vtext, vn, vol["title"])` 调用
- 删除 L1121-1142 的块级 6 类条目创建循环
- 新增第 7-8 步派生 + 建条目

**派生并发编排**：建议封装一个 `_derive_volume_all(...)` 协程，内部用 `asyncio.Semaphore(MAX_CONCURRENT_LLM)` + `BATCH=4`（复用现有并发模式）并发跑 1b/1c/1e/1f/1g，1d 等 1c 完成后跑，1g（世界观去重）单独跑（需 cached_embs 互斥追加，用 `asyncio.Lock` 保护 append）。

### Step 4: 世界观 embedding 去重缓存初始化

**文件**: `app/services/kb_service.py` — `import_file_to_kb_stream` 开头（volumes 循环之前）

- 初始化 `cached_embs: list[tuple[str, list[float]]] = []`
- 导入开始时一次性取回本 KB 已有 worldview 条目向量：
  ```python
  from app.rag.chroma_client import chroma_client, get_kb_collection_name
  coll = chroma_client.get_or_create_collection(get_kb_collection_name(kb_id))
  existing = coll.get(where={"category": "worldview"}, include=["embeddings", "metadatas"])
  cached_embs = [(m.get("title",""), e) for m, e in zip(existing.get("metadatas",[]), existing.get("embeddings",[]))]
  ```
  （兼容续传：上一会话已存的 worldview 不会丢；本会话新增的随每卷 append）
- 常量 `WORLDVIEW_DEDUP_THRESHOLD = 0.85`、`KEY_CHAR_MIN_CHAPTERS = 2`、`KEY_CHAR_MIN_EVENTS = 2` 加到顶部常量区

**余弦计算**：自行用 `embed_single` 取候选向量 + Python 算余弦，**不依赖 Chroma collection 的 distance metric**（避免 L2/cosine 不一致）。

### Step 5: 废弃/清理块级 6 类代码

**文件**: `app/services/kb_service.py`
- 删除 [_extract_from_volume](file:///d:/xiaoshuo/app/services/kb_service.py#L586)（L586-650）
- 删除 [_extract_volume_entries](file:///d:/xiaoshuo/app/services/kb_service.py#L653)（L653-689）
- 删除 [_split_text_into_chunks](file:///d:/xiaoshuo/app/services/kb_service.py#L551)（L551-568，删除前确认无其他调用方）
- 删除常量 `MAX_LLM_CHUNKS`、`CHUNK_OVERLAP`（删除前确认无引用）；`CHUNK_SIZE`、`MAX_CONCURRENT_LLM` 保留
- [_dedup_entries](file:///d:/xiaoshuo/app/services/kb_service.py#L571) 保留（派生函数内部仍可复用做卷内 name 去重）

### Step 6: 大纲集成验证（复用 Task E 管道，无新代码）

本方案**不改大纲侧代码**，仅验证现有管道正确消费重构后的数据：

- **全文大纲**：`comprehensive=True` → [_build_comprehensive_volume_context](file:///d:/xiaoshuo/app/services/kb_service.py) 已按卷注入 volume_event + chapter_summary + 各卷 6 类。重构后 volume_event 覆盖整卷、6 类为按卷派生，全文大纲自动得到更准数据。"记录对应卷"已由 [full_outline.volumes[].chapter_range](file:///d:/xiaoshuo/app/agents/outline_agent.py#L104-L135) 承担，无需新增字段。
- **章节大纲**：[volumes_for_chapter_range](file:///d:/xiaoshuo/app/services/volume_splitter.py#L231) 推算 batch 章节所在卷 → `build_kb_context_for_agent(volume=目标卷, chapter_numbers=该卷章节范围)` → 取到"对应卷内六类（chapter_number=None，or_(...is_(None)) 始终纳入）+ 章节摘要"。Task E 已接好，验证即可。
- **决策**：[OutlineChapterItem](file:///d:/xiaoshuo/app/schemas/outline.py#L5-L11) **不加** volume 字段，章→卷继续用 `chapter_range` 动态推算（避免冗余存储与不一致）。

## 四、Assumptions & Decisions

### 关键决策（用户已确认）
1. **按卷派生，不做全书聚合**：角色/事件/时间线/势力/设定/世界观均 per-volume 派生（volume=vn，chapter_number=None），跨卷连贯性交给全文大纲用卷总结缝合。理由：把状态钉在卷内时间线，避免跨卷时间/事件错位。
2. **丢弃块级 6 类**：[_extract_volume_entries](file:///d:/xiaoshuo/app/services/kb_service.py#L653)/[_extract_from_volume](file:///d:/xiaoshuo/app/services/kb_service.py#L586) 整体删除，6 类改由章摘要派生。（早期"6 类不改"的想法被后续"6 类全部按规则派生"的详细需求取代。）
3. **卷总结改 map-reduce**：[_extract_volume_event_summary](file:///d:/xiaoshuo/app/services/kb_service.py#L692) 输入由 `vtext[:8000]` 改为 `chapters_data`，覆盖整卷。
4. **世界观去重用 embedding**：BAAI/bge-large-zh-v1.5（1024 维）余弦 ≥0.85 判重，自行算余弦不依赖 Chroma metric。
5. **角色只记重点**：跨章出场 ≥2 章或 key_events 提及 ≥2 次。
6. **事件含感情戏 + 角色成长**：作为事件子类型（attributes.subtype）记录，跳过与主线无关内容。
7. **大纲 schema 不改**：volume provenance 复用 full_outline.volumes[].chapter_range，章→卷用 volumes_for_chapter_range 动态推算。

### 边界处理
- **卷内无章/话标记**：[detect_chapters_in_volume](file:///d:/xiaoshuo/app/services/volume_splitter.py) fallback 返回整卷为 1 章"本卷全文" → 章摘要只取前 8000 字 → 卷总结退化为同当前覆盖。不退步、不报错。
- **章文本超 8000 字**：[_extract_chapter_summary](file:///d:/xiaoshuo/app/services/kb_service.py#L710) 仍截断前 8000 字（摘要不需全文，保持不变）。
- **世界观候选 embedding 失败**：embed_single 返回零向量 → 余弦为 0 → 视为"无相似"→ 正常加入（宁多勿漏）。
- **续传兼容**：旧 KB 的 volume status="extracted" 但条目是块级 6 类 → 续传跳过该卷。要得到新派生结构需清空重导。旧 KB 检索不受影响。
- **旧 KB 条目**：chapter_number=NULL 的条目在 chapter_numbers 过滤时始终纳入（`or_(...is_(None))`，上一版已保证）。
- **并发**：派生函数复用 `BATCH=4` + `asyncio.Semaphore(MAX_CONCURRENT_LLM)`；世界观 cached_embs 追加用 `asyncio.Lock`。
- **跨卷查重 [_cross_volume_dedup](file:///d:/xiaoshuo/app/services/kb_service.py#L1203) 保留**：与世界观 embedding 去重并存（前者面向通用条目，后者专门做 worldview）。

### LLM 成本对比
- 当前：每卷最多 80 块 × 4096 token（6 类）+ 1 卷总结 + N 章摘要。
- 重构后：每卷 N 章摘要 + 1 卷总结(map-reduce) + ~6 派生调用（角色/事件/感情/成长/势力/设定/世界观，多为单次）。
- 净效果：**删除昂贵的块级 6 类，派生调用数远少于块数**，总 token 与调用数下降，条目数从几百冗余降到几十精炼。

### 不做的事
- 不改 KB schema（上一版已齐）
- 不改大纲 schema（OutlineChapterItem 不加 volume 字段）
- 不改 build_kb_context_for_agent / _build_comprehensive_volume_context 接口
- 不改前端（卷筛选器上一版已完成）
- 不改 [volume_splitter](file:///d:/xiaoshuo/app/services/volume_splitter.py)（卷识别+章切分已稳定）
- 不改 [detect_chapters_in_volume](file:///d:/xiaoshuo/app/services/volume_splitter.py) fallback

## 五、Rollout 顺序（7 步）

1. 新增 7 个派生提取函数（Step 1a-1g）
2. 改造 _extract_volume_event_summary 为 map-reduce（Step 2）
3. 重构导入循环 per-volume 顺序 + 派生 6 类建条目（Step 3）
4. 世界观 embedding 去重缓存初始化 + 常量（Step 4）
5. 废弃/清理块级 6 类代码（Step 5）
6. 大纲集成验证（Step 6，无新代码，跑通验证）
7. 验证：py_compile + import 检查 + 模拟多卷文件运行时测试 + 回归旧 KB（Step 7）

## 六、Verification

### 语法/导入
- `py_compile` 所有修改的 .py 文件
- `python -c "from app.services import kb_service, volume_splitter"` 导入检查
- 确认 _extract_volume_entries/_extract_from_volume/_split_text_into_chunks 删除后无残留引用（grep）

### 运行时测试（模拟"每话前缀卷名"的多卷文件）
- 构造 3 卷 × 5 章/卷 文本，每卷世界观前两章相似、后续卷世界观与首卷相似
- 导入后验证：
  - chapter_summary 条目数 ≈ 15（3×5）
  - volume_event 条目数 = 3，每条覆盖整卷（非仅前 8000 字，可用字数/事件数粗校）
  - 6 类条目均为 per-volume（volume=vn, chapter_number=None）
  - 角色条目只含重点角色（出场 ≥2 章），无跨章重复
  - 事件条目含主线 + 感情戏 + 成长子类型
  - 时间线条目按章序
  - **世界观条目数 < 3 卷×候选数**（去重生效：相似卷被跳过）

### 大纲集成验证
- 全文大纲生成 → kb_context 含各卷 volume_event（整卷覆盖）+ 章摘要 + 派生 6 类
- 章节大纲生成（指定某卷章节范围）→ kb_context 含该卷 6 类 + 该卷章摘要，不含其他卷

### 回归旧 KB
- 旧 KB（块级 6 类条目，chapter_number=NULL）→ 检索仍正常（comprehensive/章级过滤 `or_(...is_(None))` 始终纳入）
- 旧 KB 重新生成大纲不受影响
- 要获取新派生结构需清空重导（提示用户）
