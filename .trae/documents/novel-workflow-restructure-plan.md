# 小说写作系统流程重构计划

## 一、需求摘要

用户希望重构小说创作流程，核心变更如下：

1. **两层大纲结构**：先确定主题 → 生成全文大纲（总体框架/分卷概述） → 基于全文大纲生成前10章详细大纲 → 用户查看编辑 → 写作 → 写完10章后点击"继续生成后续章节" → AI根据全文大纲+已写内容生成下10章详细大纲 → 循环
2. **篇幅选择**：创建小说时选择长篇（80万字+，约200-300章）或短篇（20万字，约50-70章），影响全文大纲的规模和情节密度
3. **章节知识数据库**：存储每章的主要内容、出现的角色、角色设定、世界观信息
4. **知识图谱可视化**：点击按钮以关系网络图形式展示角色关系、章节关联、世界观信息，供用户浏览和作者智能体读取

## 二、当前状态分析

### 现有流程
```
创建小说(title/genre/description) → 生成章节大纲(一次性生成N章) → 确认大纲 → 逐章写作
```

### 问题
- 只有一层大纲，没有"全文框架"和"章节细化"的分层
- 一次性生成所有章节大纲，无法分批生成
- 没有篇幅选择，大纲生成不区分长篇/短篇
- ChapterSemantic表已存在但只存摘要/关键词，缺少角色和世界观结构化数据
- 没有知识图谱可视化功能

### 可复用部分
- `Novel` 模型的 `outline` (JSON) 字段可改为存全文大纲
- `ChapterSemantic` 模型可扩展为知识数据库的核心
- `outline_agent.py` 的 `_safe_rag_query` 和 `_parse_outline_response` 可复用
- RAG系统（ChromaDB + embedder + retriever）完全可复用
- Writer Agent 和 Reader Agents 核心逻辑不变，只需调整上下文注入

## 三、详细设计

### 3.1 数据库模型变更

#### 3.1.1 Novel 模型扩展 (`app/models/novel.py`)

新增字段：
- `length_type`: String(20) — 篇幅类型，"long"（长篇）或 "short"（短篇）
- `full_outline`: JSON — 全文大纲（总体框架/分卷概述），与 `outline`（详细章节大纲）分离

`outline` 字段改为只存当前已生成的详细章节大纲（已确认的批次累积），`full_outline` 存总体框架。

全文大纲 JSON 结构：
```json
{
  "theme": "主题",
  "core_conflict": "核心冲突",
  "volumes": [
    {
      "volume_number": 1,
      "title": "卷标题",
      "summary": "本卷概述，300-500字",
      "chapter_range": [1, 50],
      "key_characters": ["角色1", "角色2"],
      "major_events": ["事件1", "事件2"],
      "tone": "基调描述"
    }
  ],
  "total_chapters": 200,
  "story_arc": "整体故事弧线描述"
}
```

#### 3.1.2 新建 StoryKnowledge 模型 (`app/models/story_knowledge.py`)

这是章节知识数据库的核心模型，替代原来 ChapterSemantic 的部分功能（ChapterSemantic 保留用于 RAG 向量检索，StoryKnowledge 用于结构化存储和图谱展示）：

```python
class StoryKnowledge(Base):
    __tablename__ = "story_knowledge"

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)  # 关联章节，0表示全局

    # 角色信息
    characters = Column(JSON, default=list)
    # 格式: [{"name": "林风", "role": "主角", "description": "...", "first_appear": 1, "status": "active"}]

    # 角色关系
    character_relations = Column(JSON, default=list)
    # 格式: [{"from": "林风", "to": "苏晴", "type": "师徒", "description": "..."}]

    # 世界观信息
    world_elements = Column(JSON, default=list)
    # 格式: [{"category": "功法", "name": "天罡诀", "description": "...", "related_characters": ["林风"]}]

    # 章节主要内容
    chapter_summary = Column(Text, default="")

    # 情节要点
    plot_points = Column(JSON, default=list)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    novel = relationship("Novel", back_populates="story_knowledge")

    __table_args__ = (UniqueConstraint("novel_id", "chapter_number", name="uq_novel_knowledge"),)
```

Novel 模型新增关系：`story_knowledge = relationship("StoryKnowledge", back_populates="novel", cascade="all, delete-orphan")`

### 3.2 创建小说流程变更

#### 3.2.1 前端 `showCreateNovelModal()` 变更

在创建小说弹窗中增加：
- **篇幅选择**：下拉框或单选按钮，选项为"长篇（80万字以上）"和"短篇（20万字左右）"
- 创建时传入 `length_type` 字段

#### 3.2.2 后端 novels API 变更

- `POST /api/novels` 接受 `length_type` 参数
- Novel 模型新增 `length_type` 字段

### 3.3 两层大纲生成流程

#### 3.3.1 步骤一：生成全文大纲

**触发**：用户创建小说后，点击"生成全文大纲"按钮（替换原"AI生成"按钮）

**流程**：
1. 前端发送 `POST /api/novels/{id}/outline/generate-full`，传入 `{description, genre, length_type}`
2. 后端 `outline_agent.py` 新增 `generate_full_outline()` 函数
3. AI 根据篇幅类型生成全文大纲：
   - 长篇：生成多卷结构，总章节数 200-300
   - 短篇：生成较少卷，总章节数 50-70
4. 全文大纲存入 `novel.full_outline`
5. 前端展示全文大纲（分卷展示，可编辑）

**全文大纲 Prompt 设计**：
```
你是一位资深小说架构师，需要设计完整的小说总体框架。

篇幅类型：{length_type}
长篇要求：80万字以上，约200-300章，需要设计3-5个大卷，每卷有完整的起承转合
短篇要求：20万字左右，约50-70章，需要设计2-3个卷

输出格式（严格JSON）：
{
  "theme": "作品主题",
  "core_conflict": "核心冲突",
  "story_arc": "整体故事弧线描述，500字以上",
  "total_chapters": 预计总章数,
  "volumes": [
    {
      "volume_number": 1,
      "title": "卷标题",
      "summary": "本卷详细概述，300-500字，包含主要情节走向、角色发展、冲突变化",
      "chapter_range": [1, 50],
      "key_characters": ["核心角色列表"],
      "major_events": ["关键转折点1", "关键转折点2"],
      "tone": "本卷基调"
    }
  ]
}
```

#### 3.3.2 步骤二：生成前10章详细大纲

**触发**：用户确认全文大纲后，点击"生成章节大纲"按钮

**流程**：
1. 前端发送 `POST /api/novels/{id}/outline/generate-chapters`，传入 `{batch_size: 10, start_chapter: 1}`
2. 后端 `outline_agent.py` 新增 `generate_chapter_outline()` 函数
3. AI 根据全文大纲 + RAG知识 + 第一卷概述，生成前10章详细大纲
4. 详细大纲追加到 `novel.outline` 数组
5. 前端展示详细大纲，用户可编辑每章的标题、摘要、事件、人物
6. 用户确认后进入写作阶段

**章节大纲 Prompt 设计**：
```
你是一位资深小说架构师，需要根据全文框架生成详细章节大纲。

全文框架：
{full_outline}

当前需要生成第{start}章到第{end}章的详细大纲。

相关卷概述：
{relevant_volume_summary}

已有章节大纲（供参考衔接）：
{existing_outline}

输出格式（严格JSON数组）：
[
  {
    "chapter_number": 1,
    "title": "章节标题",
    "plot_summary": "本章情节摘要，200-300字",
    "key_events": ["关键事件1", "关键事件2"],
    "characters": ["涉及人物1", "涉及人物2"],
    "notes": "备注说明"
  }
]
```

#### 3.3.3 步骤三：写完10章后继续生成

**触发**：写完当前批次的10章后，"开始写下一章"按钮变为"继续生成后续章节"

**流程**：
1. 用户点击"继续生成后续章节"
2. 前端发送 `POST /api/novels/{id}/outline/generate-chapters`，传入 `{batch_size: 10, start_chapter: 上次结束+1}`
3. AI 根据全文大纲 + 已有详细大纲 + 已写章节的 StoryKnowledge 数据，生成下10章详细大纲
4. 用户可编辑 → 确认 → 继续写作

### 3.4 章节知识自动提取

#### 3.4.1 提取时机

每章写作完成（定稿）时，自动调用知识提取服务。

#### 3.4.2 新建知识提取服务 (`app/services/knowledge_extractor.py`)

```python
async def extract_chapter_knowledge(novel_id: int, chapter_number: int, chapter_content: str, outline_item: dict) -> dict:
    """从章节内容中提取结构化知识"""
    # 调用 LLM 提取：
    # 1. 出现的角色（名称、身份、描述、状态变化）
    # 2. 角色关系（新出现的关系、关系变化）
    # 3. 世界观元素（新出现的设定、功法、地点等）
    # 4. 章节摘要
    # 5. 情节要点
```

**提取 Prompt**：
```
你是一位小说分析专家，需要从章节内容中提取结构化信息。

章节大纲：
{outline_item}

章节内容：
{chapter_content}

请提取以下信息，输出严格JSON：
{
  "characters": [
    {"name": "角色名", "role": "主角/配角/龙套", "description": "角色描述和本章表现", "status": "active/departed/dead"}
  ],
  "character_relations": [
    {"from": "角色A", "to": "角色B", "type": "师徒/敌对/盟友/恋人/亲属/同门", "description": "关系描述"}
  ],
  "world_elements": [
    {"category": "功法/地点/物品/势力/规则", "name": "名称", "description": "描述", "related_characters": ["相关角色"]}
  ],
  "chapter_summary": "本章摘要，200字以内",
  "plot_points": ["关键情节点1", "关键情节点2"]
}
```

#### 3.4.3 知识累积与更新

- 提取后，将结果存入 `StoryKnowledge` 表
- 对于已存在的角色，合并描述信息（新描述追加，不覆盖）
- 对于角色关系，检查是否已存在相同 from+to 的关系，如存在则更新
- 世界观元素同理，已存在则更新描述

#### 3.4.4 StoryKnowledge API (`app/api/knowledge.py`)

```
GET    /api/novels/{id}/knowledge              — 获取全部知识数据
GET    /api/novels/{id}/knowledge/chapters      — 按章节获取知识
GET    /api/novels/{id}/knowledge/characters    — 获取所有角色（合并后）
GET    /api/novels/{id}/knowledge/relations     — 获取所有角色关系
GET    /api/novels/{id}/knowledge/world         — 获取所有世界观元素
PUT    /api/novels/{id}/knowledge/chapters/{num} — 手动编辑某章知识
POST   /api/novels/{id}/knowledge/extract/{num}  — 手动触发某章知识提取
GET    /api/novels/{id}/knowledge/graph          — 获取图谱数据（节点+边）
```

### 3.5 知识图谱可视化

#### 3.5.1 技术方案

使用 **D3.js** (v7) 实现力导向关系网络图。D3 是成熟的可视化库，无需构建工具，可直接通过 CDN 引入。

#### 3.5.2 图谱数据结构

后端 `GET /api/novels/{id}/knowledge/graph` 返回：

```json
{
  "nodes": [
    {"id": "char_林风", "type": "character", "name": "林风", "role": "主角", "description": "...", "chapters": [1,2,3]},
    {"id": "char_苏晴", "type": "character", "name": "苏晴", "role": "配角", "description": "...", "chapters": [1,2]},
    {"id": "chapter_1", "type": "chapter", "name": "第1章 初入江湖", "number": 1},
    {"id": "world_天罡诀", "type": "world", "name": "天罡诀", "category": "功法", "description": "..."}
  ],
  "links": [
    {"source": "char_林风", "target": "char_苏晴", "type": "师徒", "label": "师徒"},
    {"source": "char_林风", "target": "chapter_1", "type": "appears_in"},
    {"source": "char_林风", "target": "world_天罡诀", "type": "uses"},
    {"source": "chapter_1", "target": "world_天罡诀", "type": "introduces"}
  ]
}
```

#### 3.5.3 图谱前端实现

新建 `static/js/knowledge-graph.js`：

- **节点类型**：角色（圆形，大小按出场频率）、章节（方形）、世界观元素（菱形）
- **节点颜色**：主角=金色、配角=蓝色、龙套=灰色、章节=绿色、世界观按 category 分色
- **关系线**：师徒=紫色、敌对=红色、盟友=蓝色、恋人=粉色、亲属=橙色、同门=青色
- **交互**：
  - 拖拽节点调整布局
  - 滚轮缩放
  - 点击节点显示详情面板（右侧浮动）
  - 点击角色节点高亮其所有关系和出场章节
  - 点击章节节点高亮该章角色和世界观
  - 筛选按钮：全部/仅角色/仅章节/仅世界观
- **触发**：侧边栏知识库面板中的"知识图谱"按钮

### 3.6 作者智能体读取知识

#### 3.6.1 写作时注入知识

在 `writer_agent.py` 的 `write_chapter()` / `write_chapter_stream()` 中，新增知识注入：

```python
# 在构建上下文时，查询 StoryKnowledge 获取：
# 1. 当前章节涉及角色的详细设定
# 2. 角色之间的关系（确保对话和互动符合关系）
# 3. 相关世界观元素（确保使用设定一致）
```

#### 3.6.2 大纲生成时注入知识

在 `outline_agent.py` 生成新批次章节大纲时，注入已写章节的知识数据：

```python
# 生成下10章大纲时，提供：
# 1. 所有角色的当前状态
# 2. 活跃的角色关系
# 3. 已引入的世界观元素
```

### 3.7 前端 UI 变更

#### 3.7.1 创建小说弹窗

增加篇幅选择：
```html
<div class="form-group">
    <label>篇幅类型</label>
    <div class="length-type-selector">
        <label class="length-option">
            <input type="radio" name="length-type" value="long">
            <span class="length-option-card">
                <strong>长篇</strong>
                <small>80万字以上，约200-300章</small>
            </span>
        </label>
        <label class="length-option">
            <input type="radio" name="length-type" value="short" checked>
            <span class="length-option-card">
                <strong>短篇</strong>
                <small>20万字左右，约50-70章</small>
            </span>
        </label>
    </div>
</div>
```

#### 3.7.2 大纲面板重构

- "AI生成"按钮拆分为两步：
  1. "生成全文大纲" — 生成总体框架（仅 planning 阶段可用）
  2. "生成章节大纲" — 生成详细章节大纲（全文大纲确认后可用）
- 全文大纲展示区：在详细大纲上方，折叠式展示各卷概述
- "继续生成后续章节"按钮：写完当前批次所有章节后出现

#### 3.7.3 知识图谱入口

- 侧边栏知识库面板增加"知识图谱"按钮
- 点击后以全屏遮罩层或右侧大面板展示图谱

#### 3.7.4 欢迎页步骤更新

```
1. 创建小说 → 2. 生成全文大纲 → 3. 生成章节大纲 → 4. 确认大纲 → 5. 开始写作
```

## 四、文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `app/models/story_knowledge.py` | 章节知识数据模型 |
| `app/services/knowledge_extractor.py` | AI知识提取服务 |
| `app/api/knowledge.py` | 知识数据库API路由 |
| `app/schemas/knowledge.py` | 知识相关Pydantic模型 |
| `static/js/knowledge-graph.js` | D3.js知识图谱可视化 |

### 修改文件

| 文件 | 变更内容 |
|------|----------|
| `app/models/novel.py` | 新增 `length_type`、`full_outline` 字段，新增 `story_knowledge` 关系 |
| `app/models/__init__.py` | 导入 StoryKnowledge |
| `app/database.py` | 确保新表被创建 |
| `app/agents/outline_agent.py` | 新增 `generate_full_outline()`、`generate_chapter_outline()` 函数 |
| `app/agents/writer_agent.py` | 写作时注入 StoryKnowledge 数据 |
| `app/agents/state.py` | NovelState 新增 `full_outline`、`story_knowledge` 字段 |
| `app/services/outline_service.py` | 新增全文大纲和分批章节大纲的 service 函数 |
| `app/services/chapter_service.py` | 定稿时调用知识提取 |
| `app/api/outlines.py` | 新增 `generate-full-outline`、`generate-chapters` 端点 |
| `app/api/novels.py` | 创建小说时接受 `length_type` |
| `app/main.py` | 注册 knowledge 路由 |
| `app/schemas/outline.py` | 新增 FullOutlineGenerateRequest、ChapterOutlineGenerateRequest |
| `app/schemas/novel.py` | 新增 length_type 字段 |
| `static/index.html` | D3.js CDN引入、知识图谱容器、UI结构调整 |
| `static/js/app.js` | 创建小说弹窗增加篇幅选择、知识图谱按钮 |
| `static/js/outline.js` | 两层大纲生成/展示逻辑、继续生成按钮 |
| `static/js/chapter.js` | 写完批次后显示"继续生成"按钮 |
| `static/css/style.css` | 篇幅选择器样式、知识图谱样式、全文大纲样式 |

## 五、实施顺序

### Phase 1: 数据层（后端基础）
1. 扩展 Novel 模型（length_type, full_outline, story_knowledge 关系）
2. 创建 StoryKnowledge 模型
3. 更新 database.py 确保新表创建
4. 更新 schemas（novel, outline, knowledge）

### Phase 2: 全文大纲生成
5. outline_agent.py 新增 generate_full_outline() 和 generate_full_outline_stream()
6. outline_service.py 新增全文大纲相关函数
7. outlines.py 新增 generate-full-outline 端点
8. 前端 outline.js 实现全文大纲生成和展示

### Phase 3: 分批章节大纲
9. outline_agent.py 新增 generate_chapter_outline() 和流式版本
10. outline_service.py 新增分批章节大纲函数
11. outlines.py 新增 generate-chapters 端点
12. 前端实现"继续生成后续章节"按钮逻辑

### Phase 4: 知识提取与存储
13. 创建 knowledge_extractor.py
14. 创建 knowledge.py API 路由
15. chapter_service.py 定稿时调用知识提取
16. writer_agent.py 注入知识数据

### Phase 5: 知识图谱可视化
17. 引入 D3.js CDN
18. 创建 knowledge-graph.js
19. 前端添加图谱按钮和容器
20. CSS 样式

### Phase 6: 创建小说流程改造
21. 前端创建弹窗增加篇幅选择
22. 后端 novels API 接受 length_type
23. 欢迎页步骤更新

## 六、验证步骤

1. 创建小说时选择长篇/短篇，验证 length_type 存储正确
2. 生成全文大纲，验证 JSON 结构完整，长篇多卷/短篇少卷
3. 生成前10章详细大纲，验证与全文大纲一致
4. 编辑大纲后确认，进入写作
5. 写完10章后，验证"继续生成后续章节"按钮出现
6. 点击继续，验证下10章大纲基于已写内容生成
7. 验证每章定稿后 StoryKnowledge 自动提取
8. 手动编辑知识数据，验证保存正确
9. 打开知识图谱，验证节点和关系线正确渲染
10. 验证作者智能体在写作时读取了知识数据
