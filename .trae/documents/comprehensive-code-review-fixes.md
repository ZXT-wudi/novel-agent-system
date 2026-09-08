# 综合代码审查修复计划

## 摘要

整个项目是一步一步迭代开发的，积累了大量技术债务。本次审查通过5个并行探索代理 + 逐文件验证，确认了约80+个问题，覆盖关键Bug(4)、高严重度(5)、中等(若干)、低(若干)四个等级。用户选择"全部修复"，按严重度分组执行，ChromaDB用run_in_executor包装，_active_states加TTL清理，DB/向量一致性用向量优先策略，evaluate_reviews发完整草稿，print()转logging+控制台输出。

## 当前状态分析

### 技术栈
- 后端：FastAPI + SQLAlchemy(async) + SQLite + ChromaDB + SiliconFlow LLM
- 前端：原生JS + D3.js
- 多智能体写作管线：writer_agent + 5 readers + evaluate_reviews + revise_chapter
- SSE流式传输贯穿全流程

### 已确认的关键问题清单

**关键Bug (4个)**
1. `apply_user_decision`双重处理 — graph.py:54-88 处理user_decisions后不清空，revise_chapter再次处理
2. ChromaDB同步阻塞 — retriever.py全文件 async函数直接调用同步API
3. DB/向量无事务一致性 — chapter_service.py:585-594 先commit DB再写向量
4. _active_states内存泄漏 — reviews.py:11 全局dict无TTL无清理

**高严重度 (5个)**
5. review_parallel无异常隔离 — graph.py:25-29 asyncio.gather无return_exceptions
6. evaluate_reviews只发3000字 — writer_agent.py:348 chapter_draft[:3000]
7. revise_full_outline token不匹配 — outline_agent.py:802 max_tokens=8192 vs 生成32768
8. generate_chapter_outline非流/流不匹配 — outline_agent.py:674(8192) vs 714(16384)
9. write_chapter max_tokens不足 — writer_agent.py:254,296 max_tokens=8192 对4000-6000字章节勉强够

**中等 (若干)**
10. list.index(ch)代替enumerate — outline_agent.py:678
11. print()调试代替logging — outline_agent.py:314-316, chapter_service.py:106-112, novel_service.py:225,247
12. 裸except:pass静默吞异常 — retriever.py:57-58,74-75
13. _filter_by_distance重复定义 — retriever.py:84-98 + chapter_service.py:67-81
14. 前端XSS — app.js/outline.js/review.js/chapter.js 无escapeHtml，96处innerHTML
15. MAX_REVISION_ROUNDS未在auto-revise路径检查 — graph.py
16. process_user_decisions/finalize_chapter保存chapter_draft而非polished_draft — review_service.py:59,63,79,83
17. delete_novel先删文件再删DB — novel_service.py:87-114
18. get_novels N+1查询 — novel_service.py:52-72
19. 硬编码向量维度1024 — embedder.py:32

**低 (若干)**
20. 死代码/未使用导入
21. 不一致的错误处理模式
22. 重复代码片段

## 修复计划（按严重度分组执行）

---

### 第一组：关键Bug (4个)

#### 修复1: apply_user_decision双重处理

**文件**: `app/agents/graph.py`
**位置**: L54-88 (`apply_user_decision`函数)
**问题**: `apply_user_decision`读取`user_decisions`，构建`accepted_from_user`并追加到`writer_decisions`，然后调用`revise_chapter`。但`revise_chapter`(writer_agent.py:406-452)会再次读取`user_decisions`并处理。用户决策被重复应用。

**修改**: 在`apply_user_decision`中，构建`accepted_from_user`后、调用`revise_chapter`前，清空`user_decisions`：
```python
# L80之后，L83之前添加：
state["user_decisions"] = []
```

**验证**: 检查revise_chapter的`all_revisions`列表不会包含重复的用户决策条目。

---

#### 修复2: ChromaDB同步阻塞事件循环

**文件**: `app/rag/retriever.py`
**位置**: 全文件所有async函数
**问题**: `add_to_collection`、`upsert_to_collection`、`query_collection`、`delete_from_collection`、`update_in_collection`、`add_to_kb`、`query_kb`、`delete_from_kb`、`update_in_kb`、`delete_novel_collections` — 所有函数直接调用同步ChromaDB API（collection.add/upsert/query/delete/update），阻塞asyncio事件循环。

**修改**:
1. 文件顶部添加 `import asyncio`
2. 将所有同步ChromaDB调用用 `await asyncio.to_thread(...)` 包装

具体包装列表：
- L13 `collection.add(...)` → `await asyncio.to_thread(collection.add, documents=documents, embeddings=embeddings, ids=ids, metadatas=metadatas or [{}] * len(documents))`
- L25 `collection.upsert(...)` → 同理用to_thread包装
- L36 `chroma_client.get_collection(...)` → `await asyncio.to_thread(chroma_client.get_collection, collection_name)`
- L49 `collection.query(**kwargs)` → `await asyncio.to_thread(collection.query, **kwargs)`
- L55-56 `collection.delete(ids=ids)` → `await asyncio.to_thread(collection.delete, ids=ids)`
- L65-66 `collection.update(**kwargs)` → `await asyncio.to_thread(collection.update, **kwargs)`
- L78-81 `delete_novel_collections` — 改为async + to_thread
- L103 `collection.add(...)` (add_to_kb) → to_thread
- L117 `chroma_client.get_collection(...)` → to_thread
- L129 `collection.query(**kwargs)` → to_thread
- L135-136 `collection.delete(ids=ids)` → to_thread
- L145 `collection.update(**kwargs)` → to_thread
- L159-160 `delete_kb_collection` — 改为async + to_thread

**注意**: `delete_novel_collections`和`delete_kb_collection`当前是同步函数，需要改为async。调用方（novel_service.py:118, kb_service.py等）需要相应加await。

**验证**: `python -c "import py_compile; py_compile.compile('app/rag/retriever.py')"` 语法检查。

---

#### 修复3: DB/向量库事务一致性（向量优先策略）

**文件**: `app/services/chapter_service.py`
**位置**: L548-594 (`save_chapter_semantic`函数)
**问题**: L585先`await db.commit()`，L588再`await upsert_to_collection(...)`。如果upsert失败，DB有记录但向量库没有，导致RAG检索不到该章节。

**修改**: 调整顺序 — 先写向量库，成功后再commit DB：
```python
# 1. 先准备DB操作（add/update semantic记录），但不commit
# 2. 先写向量库
await upsert_to_collection(
    novel_id=novel_id,
    collection_type="chapter_semantics",
    documents=[doc_text],
    ids=[vector_id],
    metadatas=[{"chapter_number": chapter_number, "novel_id": novel_id}],
)
# 3. 向量写成功后再commit DB
await db.commit()
await db.refresh(semantic)
```

如果向量写失败（抛异常），不commit DB，调用方会看到异常并处理。

**同时检查其他类似模式**:
- `save_chapter`(L419-465): L448先commit，L453-463后extract_chapter_knowledge。这里knowledge提取是LLM调用不是向量写，可以保留顺序但加try/except。
- `knowledge_extractor.py`中如果有类似的先commit后写向量模式，同样调整。
- `kb_service.py`中如果有类似模式，同样调整。

**验证**: 语法检查 + 确认向量写失败时DB不会commit。

---

#### 修复4: _active_states内存泄漏（TTL自动清理）

**文件**: `app/api/reviews.py`
**位置**: L11 (`_active_states`定义)
**问题**: `_active_states: dict[str, NovelState] = {}` 是内存全局dict，只在finalize/decide时删除。用户放弃操作时条目永不清理，导致内存泄漏。且重启后状态全丢。

**修改**:
1. 改为带时间戳的字典：`_active_states: dict[str, tuple[float, NovelState]] = {}`
2. 添加TTL清理函数：
```python
import time
_ACTIVE_STATE_TTL = 1800  # 30分钟

def _cleanup_stale_states():
    now = time.time()
    expired = [k for k, (ts, _) in _active_states.items() if now - ts > _ACTIVE_STATE_TTL]
    for k in expired:
        del _active_states[k]

def _set_active_state(key: str, state: NovelState):
    _cleanup_stale_states()
    _active_states[key] = (time.time(), state)

def _get_active_state(key: str) -> NovelState | None:
    _cleanup_stale_states()
    entry = _active_states.get(key)
    return entry[1] if entry else None

def _del_active_state(key: str):
    _active_states.pop(key, None)
```
3. 所有 `_active_states[key] = state` → `_set_active_state(key, state)`
4. 所有 `_active_states.get(key)` → `_get_active_state(key)`
5. 所有 `del _active_states[key]` → `_del_active_state(key)`

**同时修改**: `chapter_service.py` L322, L399 — 这两处直接写入`_reviews_mod._active_states`，改为调用`_set_active_state`。

**验证**: 语法检查 + 确认超过30分钟的条目会被自动清理。

---

### 第二组：高严重度 (5个)

#### 修复5: review_parallel异常隔离

**文件**: `app/agents/graph.py`
**位置**: L22-40 (`review_parallel`函数)
**问题**: L25-29 `asyncio.gather`没有`return_exceptions=True`，任一reader崩溃会导致全部失败。

**修改**: 参照chapter_service.py:352-367流式路径的模式，给每个reader加try/except：
```python
async def review_parallel(state: NovelState) -> NovelState:
    state["current_phase"] = "reviewing"

    results = []
    for reader_func, reader_type in [
        (review_character, "character"),
        (review_logic, "logic"),
        (review_style, "style"),
    ]:
        try:
            result = await reader_func(state)
            results.append(result)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("审查员 %s 失败: %s", reader_type, e)
            results.append({"reader_type": reader_type, "comments": [], "overall_score": 0, "overall_comment": f"审查失败: {e}"})

    all_comments = []
    for result in results:
        comments = result.get("comments", [])
        for c in comments:
            c["reader_type"] = result.get("reader_type", "unknown")
        all_comments.extend(comments)

    state["review_comments"] = all_comments
    state["current_phase"] = "reviewed"
    return state
```

**验证**: 语法检查 + 模拟一个reader抛异常确认其他reader不受影响。

---

#### 修复6: evaluate_reviews发送完整草稿

**文件**: `app/agents/writer_agent.py`
**位置**: L348 (`evaluate_reviews`函数)
**问题**: `chapter_draft[:3000]` 只发送前3000字，后半部分的问题无法被评估。

**修改**:
1. L348: `{chapter_draft[:3000]}` → `{chapter_draft}`
2. L356: `max_tokens=4096` → `max_tokens=8192`（容纳更完整的裁决输出）

**验证**: 语法检查 + 确认evaluate_reviews收到完整草稿。

---

#### 修复7: revise_full_outline token对齐

**文件**: `app/agents/outline_agent.py`
**位置**: L802 (`revise_full_outline`函数)
**问题**: `max_tokens=8192`，但`generate_full_outline`(L620)和`generate_full_outline_stream`(L651)用的是32768。修订时8192不够会导致JSON截断。

**修改**: L802 `max_tokens=8192` → `max_tokens=32768`

**验证**: 语法检查。

---

#### 修复8: generate_chapter_outline非流/流token对齐

**文件**: `app/agents/outline_agent.py`
**位置**: L674 (非流) vs L714 (流)
**问题**: 非流`max_tokens=8192`，流`max_tokens=16384`，不一致。

**修改**: L674 `max_tokens=8192` → `max_tokens=16384`

**验证**: 语法检查。

---

#### 修复9: write_chapter max_tokens提升

**文件**: `app/agents/writer_agent.py`
**位置**: L254 (`write_chapter`) 和 L296 (`write_chapter_stream`)
**问题**: `max_tokens=8192`。4000-6000中文字 ≈ 5200-7800 tokens，8192勉强够，但加上JSON/标点/格式有截断风险。

**修改**:
- L254: `max_tokens=8192` → `max_tokens=16384`
- L296: `max_tokens=8192` → `max_tokens=16384`

**验证**: 语法检查。

---

### 第三组：中等 (若干)

#### 修复10: list.index(ch) → enumerate

**文件**: `app/agents/outline_agent.py`
**位置**: L677-678
**问题**: `ch["chapter_number"] = start_chapter + new_chapters.index(ch)` — O(n²)且如果有重复dict会出错。

**修改**:
```python
for i, ch in enumerate(new_chapters):
    ch["chapter_number"] = start_chapter + i
```

**验证**: 语法检查。

---

#### 修复11: print() → logging + 控制台输出

**文件**: `app/main.py`, `app/agents/outline_agent.py`, `app/services/chapter_service.py`, `app/services/novel_service.py`

**修改**:

1. **main.py** 顶部添加logging配置（在现有import之后）：
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
```

2. **outline_agent.py**:
   - L314-316: `print(f"[OUTLINE-MSG]...")` → `logger.info(...)` (logger已在L10定义)
   - 确认所有print都替换

3. **chapter_service.py**:
   - L106-112: `print(f"[CH-WRITE]...")` → `logger.info(...)` (logger已在L18定义)

4. **novel_service.py**:
   - L225: `print(f"[PARSE-EXPAND]...")` → 添加logger + `logger.info(...)`
   - L247: `print(f"[KB]...")` → `logger.info(...)` 或 `logger.warning(...)`
   - 需在文件顶部添加 `import logging; logger = logging.getLogger(__name__)`

**验证**: 语法检查 + 启动服务确认日志输出到控制台。

---

#### 修复12: 裸except:pass → 带日志的错误处理

**文件**: `app/rag/retriever.py`
**位置**: L57-58, L74-75 (以及修复2中所有try/except块)
**问题**: `except Exception: pass` 静默吞掉所有错误，调试困难。

**修改**:
- L57-58: `except Exception: pass` → `except Exception: logger.warning("从集合删除失败: %s", collection_name, exc_info=True)`
- L74-75: `except Exception: pass` → `except Exception: logger.warning("更新集合失败: %s", collection_name, exc_info=True)`
- L137-138: `except Exception: pass` → 同理
- L153-154: `except Exception: pass` → 同理

**验证**: 语法检查。

---

#### 修复13: 消除重复的_filter_by_distance

**文件**: `app/services/chapter_service.py`, `app/rag/retriever.py`
**位置**: chapter_service.py L67-81, retriever.py L84-98
**问题**: 同一函数在两处定义。

**修改**:
1. chapter_service.py: 删除L67-81的`_filter_by_distance`内部函数
2. chapter_service.py: 已有 `from app.rag.retriever import query_collection` (L10)，添加 `filter_by_distance` 到导入
3. chapter_service.py L86,88,90: `_filter_by_distance(...)` → `filter_by_distance(...)`

**验证**: 语法检查 + 确认调用正常。

---

#### 修复14: 前端XSS修复

**文件**: `static/js/app.js`, `static/js/outline.js`, `static/js/review.js`, `static/js/chapter.js`
**问题**: 这4个文件没有escapeHtml函数，96处innerHTML中很多直接插入API返回数据。

**修改**:
1. 在`app.js`、`outline.js`、`review.js`、`chapter.js`各文件顶部添加escapeHtml函数：
```javascript
function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
```
2. 检查所有innerHTML中的动态数据，用escapeHtml包裹
   - 重点：API返回的title、summary、content、error.message、comment等用户可控内容
   - 静态HTML标签不需转义
   - 已有escape的文件（knowledge-graph.js, novel-wizard.js, knowledge-base.js, settings.js）确认使用一致

**注意**: 这是一个较大的改动，需要逐文件检查每个innerHTML。由于这是个人工具，优先处理直接插入API数据的innerHTML，静态HTML模板可不改。

**验证**: 浏览器中测试各页面，确认无HTML注入。

---

#### 修复15: MAX_REVISION_ROUNDS检查

**文件**: `app/agents/graph.py`
**位置**: `auto_revise`函数 (L43-46)
**问题**: `auto_revise`直接调用`revise_chapter`，不检查`revision_count`是否已达上限。`check_revision`有检查但在某些路径可能被跳过。

**修改**: 在`auto_revise`中添加上限检查：
```python
async def auto_revise(state: NovelState) -> NovelState:
    state["current_phase"] = "auto_revising"
    revision_count = state.get("revision_count", 0)
    if revision_count >= settings.MAX_REVISION_ROUNDS:
        state["is_final"] = True
        state["current_phase"] = "finalized"
        return state
    state = await revise_chapter(state)
    return state
```

**验证**: 语法检查。

---

#### 修复16: 保存polished_draft而非chapter_draft

**文件**: `app/services/review_service.py`
**位置**: L56-63 (`process_user_decisions`), L77-83 (`finalize_chapter`)
**问题**: 保存章节时用`state.get("chapter_draft", "")`，但如果有`polished_draft`应该保存润色后的版本。

**修改**:
1. `process_user_decisions` L59,63:
```python
content_to_save = state.get("polished_draft") or state.get("chapter_draft", "")
await save_chapter(db, novel_id, chapter_number, content_to_save, state.get("chapter_title", ""), "final")
await save_chapter_semantic(db, novel_id, chapter_number, content_to_save)
```
2. `finalize_chapter` L79,83: 同理

**验证**: 语法检查 + 确认保存的是润色版。

---

#### 修复17: delete_novel先删DB再删文件

**文件**: `app/services/novel_service.py`
**位置**: L75-120 (`delete_novel`函数)
**问题**: L87-101先删文件，L103-114后删DB记录并commit。如果commit失败，文件已删但DB记录还在。

**修改**: 调整顺序 — 先删DB记录并commit，再删文件：
```python
# 1. 先收集文件路径
novel_images = ...
character_images = ...
# 2. 删DB记录
await db.execute(delete(ModificationRecord)...)
...
await db.delete(novel)
await db.commit()
# 3. DB commit成功后删文件
for path in novel_images: ...
for path in character_images: ...
# 4. 删向量集合
for collection_type in ...: ...
```

**验证**: 语法检查。

---

#### 修复18: get_novels N+1查询优化

**文件**: `app/services/novel_service.py`
**位置**: L52-72 (`get_novels`函数)
**问题**: 每个novel都执行单独的count查询。

**修改**: 用子查询一次性获取：
```python
async def get_novels(db: AsyncSession) -> list[NovelListResponse]:
    from sqlalchemy import func, select
    chapter_count_subq = (
        select(Chapter.novel_id, func.count(Chapter.id).label("ch_count"))
        .group_by(Chapter.novel_id)
        .subquery()
    )
    result = await db.execute(
        select(Novel, func.coalesce(chapter_count_subq.c.ch_count, 0))
        .outerjoin(chapter_count_subq, Novel.id == chapter_count_subq.c.novel_id)
        .order_by(Novel.created_at.desc())
    )
    rows = result.all()
    return [
        NovelListResponse(
            id=novel.id, title=novel.title, genre=novel.genre,
            length_type=novel.length_type or "short",
            target_word_count=novel.target_word_count,
            status=novel.status, chapter_count=ch_count,
            created_at=novel.created_at,
        )
        for novel, ch_count in rows
    ]
```

**验证**: 语法检查 + 确认返回数据正确。

---

#### 修复19: 硬编码向量维度

**文件**: `app/rag/embedder.py`
**位置**: L32
**问题**: `[0.0] * 1024` 硬编码向量维度。如果换embedding模型维度不同会出错。

**修改**:
```python
# 从配置或常量获取维度
from app.config import settings
EMBEDDING_DIM = settings.EMBEDDING_DIM if hasattr(settings, 'EMBEDDING_DIM') else 1024
# L32:
all_embeddings.extend([[0.0] * EMBEDDING_DIM for _ in batch])
```

或者在config.py中添加 `EMBEDDING_DIM: int = 1024` 配置项。

**验证**: 语法检查。

---

### 第四组：低 (若干)

#### 修复20-22: 死代码、未使用导入、不一致错误处理

**文件**: 多个文件
**修改**:
1. 检查并删除未使用的import语句
2. 检查并删除已注释掉或永远不执行的代码
3. 统一try/except模式：要么全部用`except LLMError`，要么全部用`except Exception`

**验证**: 语法检查 + 启动服务确认无ImportError。

---

## 假设与决策

1. **ChromaDB修复**: 使用`asyncio.to_thread`包装同步调用，不改ChromaDB客户端本身
2. **DB/向量一致性**: 向量优先策略 — 先写向量，成功后再commit DB，向量写失败时不commit
3. **_active_states**: TTL 30分钟自动清理，不持久化到DB（个人使用场景够用）
4. **evaluate_reviews**: 发送完整草稿，max_tokens从4096提到8192
5. **write_chapter max_tokens**: 从8192提到16384（安全余量）
6. **print转logging**: 全部转，在main.py配置StreamHandler输出到控制台
7. **执行顺序**: 按严重度分组，每组修完后做语法检查
8. **前端XSS**: 4个无escapeHtml的文件各加一个，逐个innerHTML检查
9. **delete_novel**: 先删DB再删文件
10. **get_novels**: 用outerjoin+子查询消除N+1

## 验证步骤

每组修复完成后执行：
```bash
# 语法检查所有修改过的Python文件
d:\xiaoshuo\venv\Scripts\python.exe -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['app/agents/graph.py', 'app/agents/writer_agent.py', 'app/agents/outline_agent.py', 'app/rag/retriever.py', 'app/rag/embedder.py', 'app/services/chapter_service.py', 'app/services/review_service.py', 'app/services/novel_service.py', 'app/api/reviews.py', 'app/main.py']]"
```

全部修复完成后：
1. 重启服务确认无ImportError/启动错误
2. 生成一章测试写作流程正常
3. 确认控制台日志输出格式正确
