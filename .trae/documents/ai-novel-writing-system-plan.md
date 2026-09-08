# AI多智能体小说写作系统 - 实施计划

## 1. 项目概述

构建一个基于多智能体协作的AI小说写作系统，包含作者智能体（大纲规划师、章节写手）和读者智能体（情节审查员、人物审查员、逻辑审查员），支持人机协作写作流程，具备RAG知识检索、用户偏好学习、章节语义关联等能力。

## 2. 技术栈决策

| 组件 | 选择 | 理由 |
|------|------|------|
| 多智能体框架 | LangGraph | 状态机模型天然适配写-审-改循环 |
| LLM | DeepSeek-V4-Pro (硅基流动API) | 用户指定 |
| 后端 | FastAPI | 异步高性能，WebSocket+SSE支持 |
| 前端 | 原生HTML/JS | 用户指定，无需构建工具 |
| 关系数据库 | PostgreSQL | JSONB、全文搜索、成熟生态 |
| ORM | SQLAlchemy 2.0 async | 与FastAPI配合最佳 |
| 向量数据库 | ChromaDB | 零配置嵌入式，LangChain生态集成 |
| 迁移工具 | Alembic | SQLAlchemy标准迁移工具 |

## 3. 系统架构

```
┌─────────────────────────────────────────────────┐
│          前端 (原生 HTML/JS + CSS)                │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ 大纲编辑 │  │ 章节阅读 │  │ 修改意见面板 │  │
│  │ 面板     │  │ 编辑面板 │  │ 用户决策面板 │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
└─────────────────────┬───────────────────────────┘
                      │ HTTP + WebSocket + SSE
┌─────────────────────┼───────────────────────────┐
│               FastAPI 后端                        │
│                      │                            │
│  ┌───────────────────┼──────────────────┐        │
│  │        API 路由层                     │        │
│  │  /novels /chapters /outline /agents  │        │
│  └───────────────────┼──────────────────┘        │
│                      │                            │
│  ┌───────────────────┼──────────────────┐        │
│  │     LangGraph 多智能体引擎            │        │
│  │                                      │        │
│  │  ┌──────────┐   ┌──────────┐        │        │
│  │  │ 大纲规划 │   │ 章节写手 │        │        │
│  │  │ Agent    │   │ Agent    │        │        │
│  │  └──────────┘   └──────────┘        │        │
│  │  ┌──────────┐   ┌──────────┐        │        │
│  │  │ 情节审查 │   │ 人物审查 │        │        │
│  │  │ Reader   │   │ Reader   │        │        │
│  │  └──────────┘   └──────────┘        │        │
│  │  ┌──────────┐                       │        │
│  │  │ 逻辑审查 │                       │        │
│  │  │ Reader   │                       │        │
│  │  └──────────┘                       │        │
│  └───────────────────┼──────────────────┘        │
│                      │                            │
│  ┌───────────────────┼──────────────────┐        │
│  │          RAG 检索层                   │        │
│  │  ┌──────────────────────────┐        │        │
│  │  │ ChromaDB 向量数据库       │        │        │
│  │  │ - 用户喜好文章            │        │        │
│  │  │ - 章节语义信息            │        │        │
│  │  │ - 世界观知识              │        │        │
│  │  └──────────────────────────┘        │        │
│  └──────────────────────────────────────┘        │
│                                                   │
│  ┌──────────────────────────────────────┐        │
│  │     PostgreSQL (4个核心数据表)        │        │
│  │  - novels (小说+大纲)                 │        │
│  │  - chapters (章节全文)                │        │
│  │  - chapter_semantics (章节语义摘要)   │        │
│  │  - user_preferences (用户偏好)        │        │
│  └──────────────────────────────────────┘        │
└───────────────────────────────────────────────────┘
```

## 4. 数据库设计

### 4.1 小说及大纲表 (novels)

```sql
CREATE TABLE novels (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    genre VARCHAR(50),
    description TEXT,                    -- 小说简介
    outline JSONB NOT NULL DEFAULT '[]', -- 大纲数据，结构如下：
    -- outline 结构: [
    --   {
    --     "chapter_number": 1,
    --     "title": "章节标题",
    --     "plot_summary": "情节摘要",
    --     "key_events": ["事件1", "事件2"],
    --     "characters": ["人物1", "人物2"],
    --     "notes": "备注"
    --   }
    -- ]
    world_settings JSONB DEFAULT '{}',   -- 世界观设定
    characters JSONB DEFAULT '[]',       -- 人物卡片
    status VARCHAR(20) DEFAULT 'planning', -- planning/writing/completed
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 4.2 章节全文表 (chapters)

```sql
CREATE TABLE chapters (
    id SERIAL PRIMARY KEY,
    novel_id INTEGER REFERENCES novels(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title VARCHAR(200),
    content TEXT NOT NULL,               -- 章节正文全文
    version INTEGER DEFAULT 1,           -- 当前版本号
    status VARCHAR(20) DEFAULT 'draft',  -- draft/reviewing/revised/final
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(novel_id, chapter_number)
);

-- 章节版本历史
CREATE TABLE chapter_versions (
    id SERIAL PRIMARY KEY,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR(50),                  -- "writer_agent" / "reader_suggestion" / "user_edit"
    review_comments JSONB,               -- 读者智能体意见
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(chapter_id, version)
);
```

### 4.3 章节语义摘要表 (chapter_semantics)

```sql
CREATE TABLE chapter_semantics (
    id SERIAL PRIMARY KEY,
    novel_id INTEGER REFERENCES novels(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    summary TEXT NOT NULL,               -- 章节主要内容摘要
    keywords TEXT[] NOT NULL,            -- 关键词列表
    characters_involved TEXT[],          -- 涉及人物
    plot_points TEXT[],                  -- 关键情节点
    emotional_arc VARCHAR(50),           -- 情感走向 (紧张/温馨/悲伤/激昂...)
    timeline_position TEXT,              -- 时间线位置
    vector_id VARCHAR(200),             -- ChromaDB中的向量ID
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(novel_id, chapter_number)
);
```

### 4.4 用户偏好表 (user_preferences)

```sql
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    novel_id INTEGER REFERENCES novels(id) ON DELETE CASCADE,
    preference_type VARCHAR(50) NOT NULL, -- "style" / "plot" / "character" / "pacing"
    preference_key VARCHAR(100) NOT NULL,
    preference_value TEXT NOT NULL,
    source VARCHAR(50),                  -- "user_explicit" / "user_modification" / "inferred"
    weight FLOAT DEFAULT 1.0,           -- 权重，用户明确指定的权重更高
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 修改记录表（学习用户写作偏好的核心数据）
CREATE TABLE modification_records (
    id SERIAL PRIMARY KEY,
    novel_id INTEGER REFERENCES novels(id) ON DELETE CASCADE,
    chapter_number INTEGER,
    original_text TEXT NOT NULL,          -- 原始AI生成文本
    modified_text TEXT NOT NULL,          -- 用户修改后文本
    modification_type VARCHAR(50),        -- "style" / "plot" / "character" / "detail"
    reader_suggestion TEXT,               -- 读者智能体的建议（如果有）
    user_decision VARCHAR(20),            -- "accepted" / "rejected" / "modified"
    user_note TEXT,                       -- 用户备注
    created_at TIMESTAMP DEFAULT NOW()
);
```

## 5. LangGraph 多智能体设计

### 5.1 智能体角色定义

| 智能体 | 类型 | 职责 | LLM |
|--------|------|------|-----|
| outline_agent | 作者 | 根据用户需求生成/修改大纲 | DeepSeek-V4-Pro |
| writer_agent | 作者 | 根据大纲+上下文撰写章节 | DeepSeek-V4-Pro |
| plot_reader | 读者 | 审查情节合理性、节奏、伏笔 | DeepSeek-V4-Pro |
| character_reader | 读者 | 审查人物行为一致性、性格发展 | DeepSeek-V4-Pro |
| logic_reader | 读者 | 审查逻辑自洽性、设定一致性 | DeepSeek-V4-Pro |

### 5.2 核心状态定义

```python
class NovelState(TypedDict):
    novel_id: int
    current_phase: str                    # "outline" / "writing" / "reviewing" / "revising" / "user_decision"
    outline: list[dict]                   # 大纲数据
    current_chapter_number: int
    chapter_draft: str                    # 当前章节草稿
    chapter_title: str                    # 当前章节标题
    previous_chapters_full: list[str]     # 前2章全文
    previous_semantics: list[dict]        # 更早章节的语义摘要
    review_comments: list[dict]           # 读者智能体审查意见
    writer_decisions: list[dict]          # 写手智能体对意见的决策
    pending_user_decisions: list[dict]    # 需要用户决策的修改意见
    user_decisions: list[dict]            # 用户最终决策
    revision_count: int                   # 修订次数
    is_final: bool                        # 章节是否最终定稿
    rag_context: str                      # RAG检索到的相关上下文
```

### 5.3 大纲生成流程图

```
用户输入小说需求
       │
       ▼
┌──────────────┐
│ outline_agent│ ← 调用RAG检索用户喜好
│ 生成大纲     │
└──────┬───────┘
       │
       ▼
  返回大纲给用户 ──→ 用户修改大纲 ──→ 更新数据库
       │                                    │
       │ 用户确认大纲                        │ 循环修改
       ▼                                    │
  大纲定稿，存入数据库 ←─────────────────────┘
```

### 5.4 章节写作流程图 (LangGraph核心)

```
                    开始写第N章
                        │
                        ▼
              ┌──────────────────┐
              │  加载上下文       │
              │  - 前2章全文      │
              │  - 语义摘要(RAG)  │
              │  - 大纲第N章      │
              │  - 用户偏好       │
              └────────┬─────────┘
                        │
                        ▼
              ┌──────────────────┐
              │  writer_agent    │
              │  撰写章节草稿    │
              └────────┬─────────┘
                        │
            ┌───────────┼───────────┐
            │           │           │
            ▼           ▼           ▼
    ┌────────────┐ ┌────────────┐ ┌────────────┐
    │plot_reader │ │char_reader │ │logic_reader│
    │ 情节审查   │ │ 人物审查   │ │ 逻辑审查   │
    └──────┬─────┘ └──────┬─────┘ └──────┬─────┘
           │               │               │
           └───────────────┼───────────────┘
                           │
                           ▼
              ┌──────────────────┐
              │  writer_agent    │
              │  判断是否接受意见 │
              │  接受→自动修改    │
              │  拒绝→标记待确认  │
              └────────┬─────────┘
                        │
              ┌─────────┴─────────┐
              │                   │
         有待确认意见         全部接受
              │                   │
              ▼                   │
     ┌────────────────┐           │
     │ 等待用户决策    │           │
     │ - 接受原版     │           │
     │ - 采纳建议     │           │
     │ - 自己修改     │           │
     └────────┬───────┘           │
              │                   │
              └─────────┬─────────┘
                        │
                        ▼
              ┌──────────────────┐
              │  修订次数 < 3 ?  │
              └────────┬─────────┘
                  是   │    否
              ┌────────┘    └──────┐
              ▼                     ▼
     回到 writer_agent       章节定稿
     重新修订                         │
                                      ▼
                            ┌──────────────────┐
                            │  存储到数据库      │
                            │  - 章节全文       │
                            │  - 语义摘要+关键词 │
                            │  - 用户偏好记录   │
                            │  - 更新ChromaDB   │
                            └──────────────────┘
                                      │
                                      ▼
                            等待用户触发写下一章
```

### 5.5 LangGraph 状态图实现结构

```python
# 图节点
nodes = {
    "load_context",        # 加载上下文（前2章全文+语义摘要+大纲+偏好+RAG）
    "write_chapter",       # writer_agent写章节
    "review_parallel",     # 3个reader_agent并行审查
    "evaluate_reviews",    # writer_agent判断是否接受意见
    "auto_revise",         # 自动修订（接受的意见）
    "user_decision",       # 等待用户决策（拒绝的意见）
    "apply_user_decision", # 应用用户决策
    "check_revision",      # 检查是否需要继续修订
    "finalize",            # 章节定稿，存储数据
}

# 边
edges = {
    "load_context"    → "write_chapter",
    "write_chapter"   → "review_parallel",
    "review_parallel" → "evaluate_reviews",
    "evaluate_reviews" → conditional:
        - "all_accepted"  → "finalize"
        - "has_rejected"  → "user_decision"
        - "all_accepted_with_revisions" → "auto_revise"
    "auto_revise"     → "check_revision",
    "user_decision"   → "apply_user_decision",
    "apply_user_decision" → "check_revision",
    "check_revision"  → conditional:
        - "need_more" → "write_chapter"  (revision_count < 3)
        - "done"      → "finalize"
}
```

## 6. RAG系统设计

### 6.1 ChromaDB Collection设计

| Collection名 | 内容 | 用途 |
|-------------|------|------|
| user_preferences | 用户喜好的文章片段、风格描述 | 大纲生成和写作时参考用户偏好 |
| chapter_semantics | 章节摘要+关键词的向量 | 写新章节时检索相关前文语义 |
| world_knowledge | 世界观设定、人物卡片、时间线 | 写作时保持设定一致性 |

### 6.2 RAG调用时机

| 触发场景 | 检索Collection | 检索Query | 返回内容 |
|----------|---------------|-----------|---------|
| 大纲规划师生成大纲 | user_preferences + world_knowledge | 用户小说需求描述 | 喜好风格+世界观参考 |
| 用户修改大纲 | user_preferences | 大纲相关描述 | 偏好参考 |
| 写手写新章节 | chapter_semantics + world_knowledge + user_preferences | 当前章节大纲+关键词 | 前2章外章节的相关语义+设定+偏好 |
| 读者审查章节 | world_knowledge | 审查涉及的人物/设定 | 设定参考 |

### 6.3 向量化策略

- 使用硅基流动API的embedding模型进行文本向量化
- 章节语义：将摘要+关键词拼接后向量化
- 世界观知识：每个设定条目单独向量化，附带元数据（类型、关联人物等）
- 用户偏好：每个偏好条目单独向量化

## 7. 前端页面设计

### 7.1 页面结构

```
┌─────────────────────────────────────────────────────────────┐
│  导航栏：小说标题 | 章节列表(下拉) | 创建新小说              │
├──────────────────────┬──────────────────────────────────────┤
│                      │                                      │
│   左侧面板           │         右侧主区域                    │
│   ┌──────────────┐   │   ┌──────────────────────────────┐   │
│   │ 大纲面板      │   │   │                              │   │
│   │ (可编辑)      │   │   │     章节内容阅读/编辑区域     │   │
│   │              │   │   │                              │   │
│   │ 第1章: xxx   │   │   │     支持Markdown渲染          │   │
│   │ 第2章: xxx   │   │   │     支持用户直接编辑           │   │
│   │ 第3章: xxx   │   │   │                              │   │
│   │ ...          │   │   │                              │   │
│   │              │   │   │                              │   │
│   │ [+添加章节]  │   │   │                              │   │
│   └──────────────┘   │   └──────────────────────────────┘   │
│   ┌──────────────┐   │   ┌──────────────────────────────┐   │
│   │ 写作控制面板  │   │   │     修改意见/决策面板         │   │
│   │              │   │   │   (AI审查意见+用户决策)       │   │
│   │ [生成大纲]   │   │   │                              │   │
│   │ [写下一章]   │   │   │   读者意见1: [接受][拒绝][修改]│   │
│   │ [暂停写作]   │   │   │   读者意见2: [接受][拒绝][修改]│   │
│   │              │   │   │   读者意见3: [接受][拒绝][修改]│   │
│   │ 写作状态:    │   │   │                              │   │
│   │ 🔄 正在写作  │   │   │   写手判断: 已自动采纳2条     │   │
│   └──────────────┘   │   │   需要您决定: 1条             │   │
│                      │   └──────────────────────────────┘   │
├──────────────────────┴──────────────────────────────────────┤
│  底部状态栏：当前进度 | Token消耗 | 章节状态                  │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 交互流程

1. **创建小说** → 输入小说名称、类型、描述 → 触发大纲规划师生成大纲
2. **大纲编辑** → 左侧面板显示大纲，可直接点击编辑 → 保存即更新数据库
3. **开始写作** → 点击"写第N章" → 进入写作流程
4. **写作过程** → SSE实时推送AI生成内容 → 右侧主区域流式显示
5. **审查反馈** → 3个读者智能体并行审查 → 修改意见面板显示
6. **用户决策** → 对每条意见选择接受/拒绝/自定义修改
7. **章节完成** → 用户确认 → 存入数据库 → 等待用户触发下一章

### 7.3 前端技术要点

- **SSE (Server-Sent Events)**：AI生成内容时使用SSE流式推送
- **WebSocket**：用于实时状态更新（写作进度、审查状态等）
- **原生JS**：无框架依赖，使用fetch API + EventSource
- **CSS**：使用CSS Grid/Flexbox布局，响应式设计

## 8. API设计

### 8.1 小说管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/novels | 创建新小说 |
| GET | /api/novels | 获取小说列表 |
| GET | /api/novels/{novel_id} | 获取小说详情 |
| DELETE | /api/novels/{novel_id} | 删除小说 |

### 8.2 大纲管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/novels/{novel_id}/outline/generate | AI生成大纲 |
| GET | /api/novels/{novel_id}/outline | 获取大纲 |
| PUT | /api/novels/{novel_id}/outline | 更新大纲 |
| PUT | /api/novels/{novel_id}/outline/confirm | 确认大纲定稿 |

### 8.3 章节管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/novels/{novel_id}/chapters/generate | 开始写新章节(SSE) |
| GET | /api/novels/{novel_id}/chapters | 获取章节列表 |
| GET | /api/novels/{novel_id}/chapters/{chapter_num} | 获取章节内容 |
| PUT | /api/novels/{novel_id}/chapters/{chapter_num} | 用户编辑章节 |
| GET | /api/novels/{novel_id}/chapters/{chapter_num}/versions | 获取版本历史 |

### 8.4 审查与决策

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/novels/{novel_id}/chapters/{chapter_num}/review | 触发读者审查 |
| GET | /api/novels/{novel_id}/chapters/{chapter_num}/reviews | 获取审查意见 |
| POST | /api/novels/{novel_id}/chapters/{chapter_num}/decide | 用户决策 |

### 8.5 RAG管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/novels/{novel_id}/rag/preferences | 添加用户喜好内容 |
| GET | /api/novels/{novel_id}/rag/preferences | 获取用户喜好列表 |
| DELETE | /api/novels/{novel_id}/rag/preferences/{id} | 删除喜好条目 |
| POST | /api/novels/{novel_id}/rag/knowledge | 添加世界观知识 |
| GET | /api/novels/{novel_id}/rag/knowledge | 获取知识列表 |

### 8.6 WebSocket

| 路径 | 说明 |
|------|------|
| /ws/novels/{novel_id}/status | 实时写作状态推送 |

## 9. 项目目录结构

```
d:\xiaoshuo\
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI应用入口
│   ├── config.py                   # 配置管理
│   ├── database.py                 # 数据库连接与会话
│   ├── models/                     # SQLAlchemy数据模型
│   │   ├── __init__.py
│   │   ├── novel.py                # 小说+大纲模型
│   │   ├── chapter.py              # 章节模型
│   │   ├── chapter_semantic.py     # 章节语义模型
│   │   └── user_preference.py      # 用户偏好+修改记录模型
│   ├── schemas/                    # Pydantic请求/响应模型
│   │   ├── __init__.py
│   │   ├── novel.py
│   │   ├── chapter.py
│   │   ├── outline.py
│   │   ├── review.py
│   │   └── preference.py
│   ├── api/                        # API路由
│   │   ├── __init__.py
│   │   ├── novels.py
│   │   ├── outlines.py
│   │   ├── chapters.py
│   │   ├── reviews.py
│   │   └── rag.py
│   ├── agents/                     # LangGraph智能体
│   │   ├── __init__.py
│   │   ├── state.py                # 共享状态定义
│   │   ├── outline_agent.py        # 大纲规划师
│   │   ├── writer_agent.py         # 章节写手
│   │   ├── readers/                # 读者智能体
│   │   │   ├── __init__.py
│   │   │   ├── plot_reader.py      # 情节审查
│   │   │   ├── character_reader.py # 人物审查
│   │   │   └── logic_reader.py     # 逻辑审查
│   │   └── graph.py                # LangGraph状态图定义
│   ├── services/                   # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── novel_service.py
│   │   ├── chapter_service.py
│   │   ├── outline_service.py
│   │   ├── review_service.py
│   │   └── preference_service.py
│   ├── rag/                        # RAG相关
│   │   ├── __init__.py
│   │   ├── chroma_client.py        # ChromaDB客户端
│   │   ├── embedder.py             # 向量化服务
│   │   └── retriever.py            # 检索服务
│   └── llm/                        # LLM调用
│       ├── __init__.py
│       └── siliconflow.py          # 硅基流动API封装
├── static/                         # 前端静态文件
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   ├── app.js                  # 主应用逻辑
│   │   ├── outline.js              # 大纲编辑逻辑
│   │   ├── chapter.js              # 章节阅读/编辑逻辑
│   │   ├── review.js               # 审查意见逻辑
│   │   └── sse.js                  # SSE/WebSocket通信
│   └── index.html                  # 主页面
├── alembic/                        # 数据库迁移
│   ├── env.py
│   └── versions/
├── alembic.ini
├── requirements.txt
├── .env                            # 环境变量(API Key等)
└── README.md
```

## 10. 实施步骤

### 阶段1: 基础设施 (预计文件: 8个)

1. 创建项目结构和依赖配置
2. 配置FastAPI应用入口和配置管理
3. 设置PostgreSQL数据库连接
4. 创建所有SQLAlchemy数据模型
5. 配置Alembic数据库迁移
6. 封装硅基流动API调用
7. 配置ChromaDB客户端
8. 实现向量化服务

### 阶段2: LangGraph智能体 (预计文件: 7个)

1. 定义共享状态(NovelState)
2. 实现大纲规划师智能体(outline_agent)
3. 实现章节写手智能体(writer_agent)
4. 实现情节审查读者(plot_reader)
5. 实现人物审查读者(character_reader)
6. 实现逻辑审查读者(logic_reader)
7. 构建LangGraph状态图(graph.py)

### 阶段3: RAG系统 (预计文件: 3个)

1. 实现ChromaDB集合管理
2. 实现RAG检索服务
3. 实现章节语义提取和向量化

### 阶段4: 业务逻辑层 (预计文件: 5个)

1. 实现小说管理服务
2. 实现大纲管理服务
3. 实现章节管理服务
4. 实现审查决策服务
5. 实现用户偏好学习服务

### 阶段5: API路由层 (预计文件: 5个)

1. 实现小说管理API
2. 实现大纲管理API（含SSE流式生成）
3. 实现章节管理API（含SSE流式写作）
4. 实现审查决策API
5. 实现RAG管理API

### 阶段6: 前端界面 (预计文件: 6个)

1. 实现主页面HTML结构
2. 实现CSS样式（含布局和主题）
3. 实现大纲编辑面板JS
4. 实现章节阅读/编辑JS
5. 实现审查意见决策JS
6. 实现SSE/WebSocket通信JS

### 阶段7: 集成测试与优化

1. 端到端流程测试
2. 上下文窗口优化
3. API调用成本优化
4. 用户体验优化

## 11. 核心依赖

```
fastapi>=0.115.0
uvicorn>=0.34.0
sqlalchemy[asyncio]>=2.0
asyncpg>=0.30.0
alembic>=1.14.0
pydantic>=2.0
langgraph>=0.4.0
langchain>=0.3.0
langchain-community>=0.3.0
chromadb>=0.5.0
httpx>=0.28.0
python-dotenv>=1.0.0
jinja2>=3.1.0
python-multipart>=0.0.18
websockets>=14.0
```

## 12. 关键设计决策记录

| 决策 | 选择 | 替代方案 | 选择理由 |
|------|------|---------|---------|
| 前端方案 | FastAPI + 原生HTML/JS | React/Vue/Streamlit | 用户指定 |
| 智能体框架 | LangGraph | CrewAI/AutoGen | 状态机适配写-审-改循环 |
| 数据库 | PostgreSQL | SQLite | JSONB、全文搜索 |
| LLM | DeepSeek-V4-Pro(硅基流动) | OpenAI/Ollama | 用户指定 |
| 读者智能体 | 3个专业读者 | 1个综合读者 | 审查更全面 |
| 上下文策略 | 前2章全文+语义摘要 | 全部全文/仅1章 | 平衡效果与token |
| 向量数据库 | ChromaDB | FAISS/Pinecone | 零配置嵌入式，开发便捷 |
| RAG内容 | 喜好+语义+世界观 | 仅喜好 | 全面支撑写作质量 |

## 13. 假设与约束

1. **API Key管理**：硅基流动API Key通过.env文件配置，不硬编码
2. **并发控制**：同一小说同一时间只允许一个章节写作流程运行
3. **修订上限**：每章节最多3轮修订循环，避免无限循环
4. **Token限制**：DeepSeek-V4-Pro的上下文窗口需要合理控制输入长度
5. **编码**：所有文件UTF-8编码，确保中文正确处理
6. **部署**：开发阶段单机运行，生产部署方案后续规划
