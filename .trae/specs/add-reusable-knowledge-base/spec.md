# 可复用知识库与同人创作支持 Spec

## Why
当前系统的知识库（ChromaDB）按小说隔离、由写作过程中自动抽取积累，用户无法主动构建一份独立、可跨小说复用的参考资料库。尤其创作"同人小说"时，必须依赖原作的世界观、角色、时间线、事件等设定，否则内容会偏离原作。需要引入独立知识库实体，支持文件上传与 AI 联网补全，并在大纲/章节生成中强制注入，同时提供清晰的可视化浏览。

## What Changes
- 新增**独立知识库**实体（`KnowledgeBase`）与知识条目（`KnowledgeEntry`），可跨小说复用，建小说时关联
- 新增知识库**向量检索**能力（独立 ChromaDB collection `kb_{id}`），与现有 per-novel RAG 并存
- 小说创建问答流程新增**题材**问题；选"同人"时追问原作名并进入**知识库准备**环节（选已有 / 上传文件 / AI 联网补全）
- **同人小说强制关联知识库**才能继续生成全文大纲
- 大纲 Agent 与写作 Agent 的上下文构建**注入关联知识库**内容
- 知识库内容来源多样：用户上传文件提取（复用现有 `import_document_to_knowledge` 思路）、AI 联网查找整理后批量写入、手动添加；AI 整理时主动扩充原作完整设定（不止用户提到的点）
- 新增知识库**列表页 + 分类详情页**可视化（世界观/角色/事件/时间线/势力/设定分区浏览）

## Impact
- Affected specs: 继承 `redesign-ui-and-novel-creation-flow`（小说创建流程）、`add-manual-writing-autocomplete`（写作上下文）
- Affected code:
  - 后端模型：新建 `app/models/knowledge_base.py`；`app/models/novel.py` 新增 `knowledge_base_id`
  - 后端 RAG：`app/rag/retriever.py` 新增 KB 版 add/query；`app/rag/chroma_client.py` 新增 `get_kb_collection_name`
  - 后端服务：新建 `app/services/kb_service.py`（CRUD + 导入 + 联网补全写入）；`app/services/knowledge_service.py` 现有文件提取逻辑迁移为可写入指定 KB
  - 后端 Agent：`app/agents/outline_agent.py`、`app/agents/writer_agent.py` 的上下文构建注入关联 KB
  - 后端 API：新建 `app/api/knowledge_bases.py`（知识库 CRUD + 导入 + 批量写入 + 可视化数据）；`app/api/novels.py` 的 from-qa 端点接收题材与 kb_id
  - 前端：`static/js/novel-wizard.js` 加题材/同人/知识库步骤；新建 `static/js/knowledge-base.js`（列表+详情）；`static/index.html` 加导航入口；`static/css/style.css` 加样式

## ADDED Requirements

### Requirement: 独立可复用知识库
系统 SHALL 提供独立于小说的知识库实体，每个知识库含名称、题材、原作名（同人用）、描述，可被多篇小说关联复用。

#### Scenario: 创建知识库
- **WHEN** 用户创建知识库并填写名称、题材、（同人时）原作名
- **THEN** 知识库持久化，可在建小说时被选择关联

#### Scenario: 关联复用
- **WHEN** 用户为小说 A 与小说 B 都关联同一知识库
- **THEN** 两篇小说的大纲/章节生成均能检索到该知识库内容

### Requirement: 知识库内容多来源
系统 SHALL 支持三种方式向知识库添加内容：用户上传文件自动提取、AI 联网查找整理后批量写入、手动添加单条。AI 整理时主动扩充原作完整设定（世界观/角色/事件/时间线/势力/设定），不止局限于用户提到的点。

#### Scenario: 上传文件提取
- **WHEN** 用户向知识库上传文档
- **THEN** 系统提取结构化知识条目（按分类）并入库，同时写入向量库供检索

#### Scenario: AI 联网补全
- **WHEN** AI 助手在对话中用联网搜索查找原作资料并整理为结构化知识
- **THEN** 通过批量写入端点将知识条目写入指定知识库，来源标记为 ai_search
- **AND** 补充的内容覆盖原作完整设定而非仅用户提及部分

#### Scenario: 手动添加
- **WHEN** 用户手动填写一条知识（分类/标题/内容）
- **THEN** 写入知识库，来源标记为 manual

### Requirement: 同人小说知识库强制
系统 SHALL 在小说题材为"同人"时，强制关联一个知识库后才能生成全文大纲。

#### Scenario: 同人未关联知识库
- **WHEN** 用户选题材"同人"但未关联/准备知识库
- **THEN** 阻止生成全文大纲，提示需先准备原作知识库

#### Scenario: 同人已关联
- **WHEN** 同人小说已关联知识库
- **THEN** 允许生成全文大纲，且大纲/章节生成注入该知识库内容

### Requirement: 知识库注入创作链路
系统 SHALL 在大纲生成与章节写作时，若小说关联了知识库，将检索到的相关知识库内容注入提示词上下文。

#### Scenario: 大纲注入
- **WHEN** 生成全文/章节大纲且小说关联知识库
- **THEN** 依据大纲主题检索关联知识库，将命中条目注入大纲提示词

#### Scenario: 章节写作注入
- **WHEN** 生成/续写章节且小说关联知识库
- **THEN** 依据章节内容检索关联知识库，将命中条目注入写作上下文

### Requirement: 知识库可视化
系统 SHALL 提供知识库列表页（卡片展示名称/题材/原作/条目数）与详情页（按分类分区浏览条目）。

#### Scenario: 列表浏览
- **WHEN** 用户进入知识库列表
- **THEN** 以卡片展示所有知识库，含名称、题材、原作、条目数

#### Scenario: 分类详情
- **WHEN** 用户打开某知识库详情
- **THEN** 按世界观/角色/事件/时间线/势力/设定分类分区展示条目，可编辑/删除

## MODIFIED Requirements

### Requirement: 小说创建问答流程
小说创建问答 SHALL 新增题材问题（在标题之后）；当选"同人"时追问原作名，并进入知识库准备环节（选择已有知识库 / 上传文件 / 请求 AI 联网补全），同人强制关联知识库后方可确认并生成全文大纲。原问答其余步骤（内容/风格/字数）保留。

### Requirement: 大纲与写作上下文检索
`outline_agent` 与 `writer_agent` 的上下文构建 SHALL 在原有 per-novel world_knowledge 检索基础上，额外检索小说关联知识库的向量集合，合并注入。

## REMOVED Requirements
无（纯新增，不删除既有 per-novel RAG 与章节知识抽取能力，两者并存）。
