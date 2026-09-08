# 计划：修复小说删除 + 增强智能创建 + 联网取材存入知识库

## 概要

三个独立但相关的改动：
1. **修复小说删除**：后端 async ORM 级联 `MissingGreenlet` 崩溃 + 前端无删除按钮 + 角色图片路径双重前缀
2. **增强智能创建**：扩写提示词加结构维度+约束、扩写时读知识库、扩写结果全字段可编辑+重新生成
3. **联网取材→知识库**：LLM 结构化搜索结果→LLM 逐条查矛盾→自动保存不矛盾条目→前端通知

---

## 一、当前状态分析

### 1.1 小说删除（Issue 1）

**后端** `app/services/novel_service.py:71-107` `delete_novel()`：
- 只显式删除 `NovelImage` 和 `CharacterImage` 行
- 未显式删除 `Chapter`、`ChapterVersion`、`ChapterSemantic`、`StoryKnowledge`、`UserPreference`、`ModificationRecord`
- `Novel` 模型所有关系有 `cascade="all, delete-orphan"` 但**没有 `passive_deletes=True`**
- async SQLAlchemy 中 `db.delete(novel)` → ORM 尝试 lazy-load 子关系 → `MissingGreenlet` → HTTP 500
- 角色图片路径 bug：`CharacterImage.image_path` 存为 `/static/character_images/{filename}`，删除时又拼 `os.path.join("static","character_images", path)` → 路径不存在 → 文件残留

**前端** `static/js/app.js:110-126` `loadNovelList()`：
- 小说列表只是一个 `<select>` 下拉框，**没有任何删除按钮**
- 唯一调用 `apiDelete("/api/novels/{id}")` 的是 `cancelNovelWizard`（仅向导取消时）

**API** `app/api/novels.py:98-103`：无 try/except，异常直接 500

### 1.2 智能创建+扩写（Issue 2）

**扩写函数** `app/services/novel_service.py:199-216` `expand_novel_from_qa()`：
- 签名：`(title, content, writing_style, target_word_count, length_type, genre="")` — **无 `db`/`knowledge_base_id` 参数**
- 不调用 `build_kb_context_for_agent` → 同人扩写完全没读知识库
- 提示词 `EXPAND_QA_SYSTEM_PROMPT`（L120-163）偏简单，缺力量体系/社会结构/核心冲突等维度

**API** `app/api/novels.py:30-62` `create_novel_from_qa()`：
- 接收 `data.knowledge_base_id` 但只传给 `NovelCreate`，**不传给 `expand_novel_from_qa`**

**前端** `static/js/novel-wizard.js:415-475` `renderWizardConfirmation()`：
- 所有字段用 `<span>` 只读展示，**不可编辑**
- `confirmNovelWizard()`（L477-504）直接关闭向导调 `generateFullOutline()`，**不保存编辑**

**无 PUT 端点**：novels API 只有 POST/GET/DELETE，无更新接口

### 1.3 联网取材→知识库（Issue 3）

**web_research.py**：`research_for_outline_safe()` 返回 `(str, Optional[str])` — 纯文本摘要，非结构化条目

**知识库系统**：
- `kb_service.add_entry()`（L92-121）：直接插入，**零去重、零矛盾检查**
- `bulk_add_entries()`（L546-560）：循环调 `add_entry`，同样无检查
- 唯一去重：`import_file_to_kb` 中的 `(category, title.lower())` 精确匹配
- `KnowledgeEntry` 模型：`id, kb_id, category, title, content, attributes, source, created_at`

---

## 二、具体改动

### 改动 1：修复小说删除

#### 1a. `app/models/novel.py` — 给现有 5 个 cascade 关系加 `passive_deletes=True`

Novel 模型当前有 5 个 cascade 关系（均无 `passive_deletes`）：`chapters`、`semantics`、`preferences`、`modifications`、`story_knowledge`。注意实际属性名是 `semantics`（不是 `chapter_semantics`），且模型**没有** `novel_images`/`character_images` 关系（图片表由 service 层显式删除处理）。给这 5 个关系各加 `passive_deletes=True`，保留原有 `order_by`：

```python
chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True, order_by="Chapter.chapter_number")
semantics = relationship("ChapterSemantic", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True, order_by="ChapterSemantic.chapter_number")
preferences = relationship("UserPreference", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True)
modifications = relationship("ModificationRecord", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True)
story_knowledge = relationship("StoryKnowledge", back_populates="novel", cascade="all, delete-orphan", passive_deletes=True, order_by="StoryKnowledge.chapter_number")
```

**为什么**：async SQLAlchemy 中，无 `passive_deletes` 的 cascade 会触发 lazy-load → `MissingGreenlet` 崩溃。已核实所有子表 FK 均为 `ondelete="CASCADE"`（chapter/chapter_semantic/story_knowledge/user_preference/modification_record/novel_image/character_image 及 chapter_versions），故 `passive_deletes=True` 后 ORM 不加载子对象，直接靠 DB `ON DELETE CASCADE` 删除子行。`Chapter.versions` 关系同理存在潜在 MissingGreenlet 风险，但显式删子表时已先删 ChapterVersion，故此处不改 chapter.py。

#### 1b. `app/services/novel_service.py` `delete_novel()` — 显式删子表 + 修图片路径

当前文件只导入了 `Chapter`、`NovelImage`、`CharacterImage`。需在文件顶部追加导入（按实际模块路径）：

```python
from app.models.chapter_semantic import ChapterSemantic
from app.models.story_knowledge import StoryKnowledge
from app.models.user_preference import UserPreference, ModificationRecord
from app.models.chapter import ChapterVersion
```

在 `db.delete(novel)` 之前，显式删除所有子表行（belt-and-suspenders，即使 `passive_deletes` 万一不生效也能工作；`ChapterVersion` 通过 `chapter_id` 关联，需用子查询先删）：

```python
from sqlalchemy import delete
# 显式删子表（按依赖顺序，先删依赖再删被依赖）
await db.execute(delete(ModificationRecord).where(ModificationRecord.novel_id == novel_id))
await db.execute(delete(UserPreference).where(UserPreference.novel_id == novel_id))
await db.execute(delete(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id))
await db.execute(delete(ChapterSemantic).where(ChapterSemantic.novel_id == novel_id))
await db.execute(delete(ChapterVersion).where(ChapterVersion.chapter_id.in_(
    select(Chapter.id).where(Chapter.novel_id == novel_id)
)))  # ChapterVersion 通过 chapter_id 关联，需先删
await db.execute(delete(Chapter).where(Chapter.novel_id == novel_id))
await db.execute(delete(NovelImage).where(NovelImage.novel_id == novel_id))
await db.execute(delete(CharacterImage).where(CharacterImage.novel_id == novel_id))
await db.delete(novel)
await db.commit()
```

角色图片路径修复——`image_path` 格式为 `/static/character_images/{filename}`，需提取纯文件名：

```python
for path in character_images:
    # path 格式: /static/character_images/3_0_师父.png
    filename = path.replace("/static/character_images/", "").replace("static/character_images/", "").lstrip("/")
    full = os.path.join("static", "character_images", filename)
    if filename and os.path.exists(full):
        try:
            os.remove(full)
        except OSError:
            pass
```

#### 1c. `app/api/novels.py` — 给删除端点加 try/except

```python
@router.delete("/{novel_id}")
async def delete_novel(novel_id: int, db: AsyncSession = Depends(get_db)):
    try:
        success = await novel_service.delete_novel(db, novel_id)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    if not success:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"message": "删除成功"}
```

#### 1d. `static/js/app.js` — 添加删除按钮

在 `loadNovelList()` 中，给 `novel-select` 旁边动态添加删除按钮（或直接在 `index.html` 的 nav 中加固定按钮）。推荐在 `index.html` nav 中加固定按钮 + `app.js` 中加 `deleteNovel()` 函数：

**index.html** nav-center 区域加：
```html
<button class="btn btn-danger btn-sm" id="btn-delete-novel" onclick="deleteNovel()" title="删除当前选中的小说" style="display:none;">🗑️ 删除</button>
```

**app.js** 添加：
```javascript
async function deleteNovel() {
    const novelId = appState.currentNovelId;
    if (!novelId) { alert("请先选择要删除的小说"); return; }
    const novel = appState.novels.find(n => n.id === novelId);
    const title = novel ? novel.title : "该小说";
    if (!confirm(`确定要删除「${title}」吗？\n\n所有章节、大纲、知识库索引、图片都将被永久删除，此操作不可撤销。`)) return;
    try {
        await apiDelete(`/api/novels/${novelId}`);
        appState.currentNovelId = null;
        await loadNovelList();
        document.getElementById("welcome-screen").style.display = "flex";
        document.getElementById("btn-delete-novel").style.display = "none";
        updateStatusBar(`已删除「${title}」`);
    } catch (e) {
        alert("删除失败: " + (e.message || e));
    }
}
```

在 `onNovelSelected` 中显示删除按钮，在切换/清空时隐藏。

### 改动 2：增强智能创建

#### 2a. `app/services/novel_service.py` — 增强 `EXPAND_QA_SYSTEM_PROMPT`

在现有提示词基础上增加：

**结构维度**（JSON 输出新增字段）：
- `power_system`：力量体系（修炼等级/能力分类/力量来源/上限约束）
- `social_structure`：社会结构（主要势力/阶层划分/权力格局）
- `core_conflict`：核心冲突（主角vs谁/表层冲突/深层主题冲突）
- `theme`：主题思想（故事想探讨什么命题）
- `key_items`：关键道具/意象列表

**创作约束**（准则新增）：
- 同人还原：同人题材必须还原原作核心设定与角色关系，不得OOC
- 设定自洽：力量体系/社会规则/角色背景之间不得矛盾
- 禁忌雷区：避免烂俗套路（如无脑后宫/过度金手指/无逻辑升级）
- 角色动机：每个角色必须有清晰的行动动机，避免工具人

更新 JSON 输出格式模板加入新字段。

#### 2b. `app/services/novel_service.py` — `expand_novel_from_qa` 读知识库

签名改为：
```python
async def expand_novel_from_qa(
    db: AsyncSession,
    title: str,
    content: str,
    writing_style: str,
    target_word_count: int,
    length_type: str,
    genre: str = "",
    knowledge_base_id: int = 0,
) -> dict:
```

函数体新增：
```python
kb_context = ""
if knowledge_base_id:
    try:
        from app.services.kb_service import build_kb_context_for_agent
        kb_context = await build_kb_context_for_agent(db, knowledge_base_id, content)
    except Exception as e:
        print(f"[KB] 扩写时知识库读取失败: {e}")

kb_section = f"\n=== 原作知识库参考（同人创作必须严格遵循原作设定） ===\n{kb_context}" if kb_context else ""
```

user prompt 中追加 `{kb_section}`。

#### 2c. `app/api/novels.py` — 传 db + knowledge_base_id 给扩写函数

```python
expanded = await novel_service.expand_novel_from_qa(
    db=db,
    title=data.title,
    content=data.content,
    writing_style=data.writing_style,
    target_word_count=data.target_word_count,
    length_type=data.length_type,
    genre=data.genre,
    knowledge_base_id=data.knowledge_base_id or 0,
)
```

#### 2d. `app/api/novels.py` — 添加 PUT 端点更新小说

参考现有 `get_novel` 端点的章节计数模式（L70-95），PUT 端点更新后返回完整 NovelResponse：

```python
@router.put("/{novel_id}", response_model=NovelResponse)
async def update_novel(novel_id: int, data: NovelUpdate, db: AsyncSession = Depends(get_db)):
    novel = await novel_service.get_novel(db, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    for field in ["title","genre","description","length_type","world_settings","characters","writing_style","target_word_count","narrative_pov"]:
        val = getattr(data, field, None)
        if val is not None:
            setattr(novel, field, val)
    await db.commit()
    await db.refresh(novel)
    from sqlalchemy import select, func
    from app.models.chapter import Chapter
    ch_count = await db.execute(select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id))
    chapter_count = ch_count.scalar() or 0
    return NovelResponse(
        id=novel.id, title=novel.title, genre=novel.genre, description=novel.description,
        length_type=novel.length_type or "short", full_outline=novel.full_outline or {},
        outline=novel.outline or [], world_settings=novel.world_settings or {},
        characters=novel.characters or [], status=novel.status, writing_style=novel.writing_style,
        target_word_count=novel.target_word_count, narrative_pov=novel.narrative_pov,
        created_at=novel.created_at, updated_at=novel.updated_at, chapter_count=chapter_count,
    )
```

需在 `app/schemas/novel.py` 添加 `NovelUpdate` schema（所有字段 Optional，字段集与 NovelCreate 一致，但 title 也设 Optional 以允许部分更新）。

#### 2e. `static/js/novel-wizard.js` — 扩写结果全字段可编辑

`renderWizardConfirmation()` 改为渲染 `<input>`/`<textarea>` 而非 `<span>`：
- 标题 → `<input type="text" id="confirm-title">`
- 简介 → `<textarea id="confirm-description">`
- 类型 → `<select id="confirm-genre">`（含已有类型选项）
- 人称 → `<select id="confirm-narrative-pov">`（第一/第三/第二人称）
- 世界观4项 → 各自 `<input>`/`<textarea>`
- 每个角色卡片 → name/role/personality/background 各自 `<input>`/`<textarea>`
- 新增"🔄 重新扩写"按钮，点击后调 `proceedToExpand()` 重新走扩写流程
- "确认"按钮改为调 `confirmNovelWizard()`，该函数收集所有编辑值 → PUT 更新小说 → 再走大纲生成

#### 2f. `static/js/novel-wizard.js` — `confirmNovelWizard` 收集编辑值

```javascript
async function confirmNovelWizard() {
    if (!wizardState || wizardState.busy) return;
    const novelId = wizardState.novelId;
    if (!novelId) { closeNovelWizard(); return; }

    // 收集编辑后的值
    const edited = collectEditedSettings();
    wizardState.busy = true;
    // PUT 更新小说
    await apiPut(`/api/novels/${novelId}`, edited);
    // ... 后续流程不变
}
```

### 改动 3：联网取材存入知识库

#### 3a. `app/services/web_research.py` — 新增结构化+矛盾检查+保存函数

新增三个函数：

**`_structure_to_entries(web_research_text, title, genre)`**：
- LLM 把摘要文本结构化为 `[{"category","title","content"}]` JSON 数组
- System prompt: "你是知识库管理员。将以下参考资料结构化为知识库条目..."
- 输出 JSON 数组，category 限定为 worldview/character/event/timeline/faction/setting

**`_check_contradiction(new_entry, existing_entries)`**：
- LLM 判断新条目是否与同类别已有条目矛盾
- System prompt: "你是设定一致性审查员。判断新条目是否与已有条目存在事实矛盾..."
- 返回 `True`（矛盾，跳过）或 `False`（不矛盾，可保存）

**`save_web_research_to_kb(db, kb_id, web_research_text, title, genre)`**：
- 主流程：
  1. 调 `_structure_to_entries` 得到候选条目列表
  2. 查现有 KB 条目（`list_entries(db, kb_id)`），按 category 分组
  3. 对每条候选：调 `_check_contradiction` 与同类别已有条目比对
  4. 不矛盾的调 `add_entry(db, kb_id, ..., source="web_research")` 保存
  5. 返回 `{"saved": N, "skipped": M, "skipped_titles": [...]}`
- 无 kb_id 或无 web_research_text 时安全返回 `{"saved":0, "skipped":0, "reason":"..."}`

#### 3b. `app/api/outlines.py` — 全文大纲端点接入 KB 保存

在 `generate_full_outline` 的 `stream_generator` 中，web research 之后、构建 state 之前，插入 KB 保存步骤，并**调整执行顺序**：先 web research → 存 KB → 再 build kb_context（使 KB context 包含新存条目）：

```python
# 1. 先做联网取材
web_research_context = ""
if data.use_web_research:
    yield json.dumps({"type": "status", "phase": "web_researching"}, ensure_ascii=False) + "\n"
    try:
        from app.services.web_research import research_for_outline_safe
        web_research_context, wr_err = await research_for_outline_safe(
            novel.title, data.genre or novel.genre or "", description
        )
        if wr_err:
            yield json.dumps({"type": "status", "phase": "web_research_skipped", "message": wr_err}, ensure_ascii=False) + "\n"
        else:
            yield json.dumps({"type": "status", "phase": "web_research_done"}, ensure_ascii=False) + "\n"
    except Exception as e:
        print(f"[WebResearch] 联网取材失败: {e}")

# 2. 联网结果存入知识库（如果有 KB 且有结果）
kb_save_result = None
if web_research_context and novel.knowledge_base_id:
    yield json.dumps({"type": "status", "phase": "kb_saving"}, ensure_ascii=False) + "\n"
    try:
        from app.services.web_research import save_web_research_to_kb
        kb_save_result = await save_web_research_to_kb(
            db, novel.knowledge_base_id, web_research_context,
            novel.title, data.genre or novel.genre or "",
        )
        yield json.dumps({"type": "status", "phase": "kb_saved", "data": kb_save_result}, ensure_ascii=False) + "\n"
    except Exception as e:
        print(f"[KB] 联网取材存知识库失败: {e}")
        yield json.dumps({"type": "status", "phase": "kb_save_failed", "message": str(e)}, ensure_ascii=False) + "\n"

# 3. 构建 KB context（此时包含新存条目）
kb_context = ""
if novel.knowledge_base_id:
    try:
        kb_context = await build_kb_context_for_agent(db, novel.knowledge_base_id, description, comprehensive=True)
    except Exception as e:
        print(f"[KB] 全文大纲知识库读取失败: {e}")

# 4. 构建 state
state: NovelState = {
    "novel_id": novel_id,
    "knowledge_base_id": novel.knowledge_base_id,
    "kb_context": kb_context,
    "web_research_context": web_research_context,
    "outline_item": { ... },  # 原有字段不变
}
```

即把原 `generate_full_outline`（outlines.py L29-113）中 L42-64 的"先建 kb_context 再 web research"改为"先 web research → 存 KB → 再建 kb_context"。

#### 3c. `static/js/outline.js` — 处理新的 KB 保存状态事件

在 SSE 事件处理中新增对 `kb_saving` / `kb_saved` / `kb_save_failed` phase 的处理：
- `kb_saving` → 状态栏显示 "💾 正在将联网取材保存到知识库..."
- `kb_saved` → 显示 "💾 已保存 N 条到知识库（跳过 M 条矛盾内容）"
- `kb_save_failed` → 显示 "⚠️ 知识库保存失败，但不影响大纲生成"

---

## 三、假设与决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 删除确认方式 | `confirm()` 对话框 | 足够简单，避免引入新 modal 组件 |
| `passive_deletes` + 显式删子表 | 两者都做 | belt-and-suspenders，模型层和 service 层双重保险 |
| 扩写可编辑范围 | 全部字段 | 用户明确要求"全部可编辑+重新扩写" |
| KB 保存触发时机 | 全文大纲生成时（web research 之后） | 此时已有 KB id 和搜索结果，时机最自然 |
| 矛盾检查方法 | LLM 逐条比对同类目 | embedding 无法检测语义矛盾（高相似度≠不矛盾）；LLM 逐条是质量与成本的平衡 |
| KB 保存后是否重建 kb_context | 是，调整执行顺序 | 确保新存条目能被大纲生成时读到 |
| `source` 字段值 | `"web_research"` | 区分来源，便于后续管理 |

---

## 四、验证步骤

### 4.1 语法验证
```bash
.\venv\Scripts\python.exe -m py_compile app\models\novel.py app\services\novel_service.py app\api\novels.py app\services\web_research.py app\api\outlines.py app\schemas\novel.py
node --check static\js\app.js
node --check static\js\novel-wizard.js
node --check static\js\outline.js
```

### 4.2 运行时冒烟测试
- 导入 `delete_novel`、`expand_novel_from_qa`（新签名）、`save_web_research_to_kb`、`_structure_to_entries`、`_check_contradiction` 无 ImportError
- `delete_novel` 源码包含显式 `delete(Chapter)` 等
- `expand_novel_from_qa` 签名包含 `db` 和 `knowledge_base_id`
- `save_web_research_to_kb` 可调用且无 kb_id 时安全返回
- `renderWizardConfirmation` 源码包含 `<input` 和 `重新` 按钮
- `loadNovelList` 或 `index.html` 包含删除按钮

### 4.3 功能验证（手动）
- 创建一个小说 → 在列表选中 → 点删除按钮 → 确认 → 小说从列表消失、chromadb collections 被清理
- 智能创建同人小说 → 扩写结果页面所有字段可编辑 → 改几个值 → 确认 → 大纲生成使用编辑后的值
- 全文大纲勾选"联网取材" → 前端显示"正在保存到知识库"→"已保存N条"状态 → 知识库中出现 source=web_research 的新条目

---

## 五、文件清单

| 文件 | 改动类型 | 内容 |
|---|---|---|
| `app/models/novel.py` | 编辑 | 所有关系加 `passive_deletes=True` |
| `app/services/novel_service.py` | 编辑 | `delete_novel` 显式删子表+修图片路径；`EXPAND_QA_SYSTEM_PROMPT` 增强；`expand_novel_from_qa` 加 db/kb_id 参数+读 KB |
| `app/api/novels.py` | 编辑 | 删除端点加 try/except；`create_novel_from_qa` 传 db/kb_id；新增 PUT `/{novel_id}` 端点 |
| `app/schemas/novel.py` | 编辑 | 新增 `NovelUpdate` schema |
| `app/services/web_research.py` | 编辑 | 新增 `_structure_to_entries`、`_check_contradiction`、`save_web_research_to_kb` |
| `app/api/outlines.py` | 编辑 | 全文大纲端点：web research 后存 KB + 调整 kb_context 构建顺序 + 新状态事件 |
| `static/index.html` | 编辑 | nav 加删除按钮 + 缓存号 |
| `static/js/app.js` | 编辑 | `deleteNovel()` 函数 + 删除按钮显隐 |
| `static/js/novel-wizard.js` | 编辑 | `renderWizardConfirmation` 全字段可编辑 + "重新扩写"按钮 + `confirmNovelWizard` 收集编辑值 PUT 更新 |
| `static/js/outline.js` | 编辑 | 处理 `kb_saving`/`kb_saved`/`kb_save_failed` 状态事件 |
