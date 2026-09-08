# Tasks

- [x] Task 1: 数据模型与迁移（KnowledgeBase / KnowledgeEntry / Novel.knowledge_base_id）
  - [x] SubTask 1.1: 新建 `app/models/knowledge_base.py`：`KnowledgeBase`（id, name, genre, source_work, is_fanwork, description, created_at, updated_at）与 `KnowledgeEntry`（id, kb_id FK, category 枚举 worldview/character/event/timeline/faction/setting/other, title, content Text, attributes JSON, source 枚举 upload/ai_search/manual, created_at）
  - [x] SubTask 1.2: `app/models/novel.py` 新增 `knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)`
  - [x] SubTask 1.3: `app/models/__init__.py` 导入新模型；确认 `init_db` 的 create_all 能建表
  - [x] SubTask 1.4: 对现有 novels 表执行 ALTER TABLE 加 knowledge_base_id 列（保留现有数据，迁移脚本或手动）

- [x] Task 2: 知识库后端 CRUD 与向量检索集成
  - [x] SubTask 2.1: `app/rag/chroma_client.py` 新增 `get_kb_collection_name(kb_id) -> f"kb_{kb_id}"`；`app/rag/retriever.py` 新增 `add_to_kb(kb_id, documents, ids, metadatas)` 与 `query_kb(kb_id, query_text, n_results)`（按 kb collection 增删查，与 per-novel 隔离）
  - [x] SubTask 2.2: 新建 `app/services/kb_service.py`：`create_kb / get_kb / list_kbs / update_kb / delete_kb`（删除时同步删 chroma collection 与条目）；`add_entry`（写 DB + 向量库）、`list_entries`（按 kb_id 与可选 category 过滤）、`update_entry`、`delete_entry`
  - [x] SubTask 2.3: 新建 `app/api/knowledge_bases.py` 路由：`POST /api/knowledge-bases`、`GET /api/knowledge-bases`、`GET /api/knowledge-bases/{id}`、`PUT`、`DELETE`；`POST /{id}/entries`、`GET /{id}/entries`、`PUT /entries/{eid}`、`DELETE /entries/{eid}`；在 `app/main.py` 注册路由
  - [x] SubTask 2.4: 新增 schemas（`app/schemas/knowledge_base.py`）用于请求/响应

- [x] Task 3: 知识库内容导入（文件提取 + AI 联网批量写入）
  - [x] SubTask 3.1: `kb_service.py` 新增 `import_file_to_kb(kb_id, file_content, filename)`：复用 `document_parser.extract_text_from_file` + 现有 LLM 提取提示词，把结构化条目写入指定 KB（source=upload），同时入向量库
  - [x] SubTask 3.2: `kb_service.py` 新增 `bulk_add_entries(kb_id, entries: list[dict])`：批量写入结构化条目（供 AI 联网整理后调用），source=ai_search；每条含 category/title/content/attributes，自动入向量库
  - [x] SubTask 3.3: API 新增 `POST /api/knowledge-bases/glm_5.2_ark_toC/import-file`（上传文件）与 `POST /api/knowledge-bases/glm_5.2_ark_toC/bulk-entries`（批量写入，供对话辅助场景）
  - [x] SubTask 3.4: 可视化数据端点 `GET /api/knowledge-bases/glm_5.2_ark_toC/overview` 返回按分类聚合的条目统计与样例，供详情页分区展示

- [x] Task 4: 小说创建问答流程加题材与同人知识库环节
  - [x] SubTask 4.1: `app/schemas/novel.py` 的 NovelQARequest 加 `genre: str` 与 `knowledge_base_id: Optional[int]`；`app/services/novel_service.py` 的 `create_novel`/`expand_novel_from_qa` 持久化这两个字段
  - [x] SubTask 4.2: `static/js/novel-wizard.js` WIZARD_STEPS 在 title 之后新增 genre 步骤（选项：玄幻/都市/科幻/历史/同人/其他）；选"同人"时追问原作名（source_work），并进入"知识库准备"子步骤：选择已有知识库 / 上传文件 / 标记"请求 AI 联网补全"
  - [x] SubTask 4.3: 同人小说若未关联知识库，确认按钮禁用并提示"同人小说需先准备原作知识库"
  - [x] SubTask 4.4: 确认时携带 genre 与 knowledge_base_id 调 from-qa；同人场景下，AI 联网补全由助手在对话中用 WebSearch 查找原作资料、整理后调 bulk-entries 写入（此为对话辅助，非系统自动）

- [x] Task 5: 大纲与写作上下文注入关联知识库
  - [x] SubTask 5.1: `app/agents/outline_agent.py` 新增 `_safe_kb_query(novel_id, query_text, n_results)`：依据 novel.knowledge_base_id 检索关联 KB 向量集合；在全文/章节大纲生成处合并注入（与现有 preference/knowledge 上下文并列）
  - [x] SubTask 5.2: `app/agents/writer_agent.py` 的 `_build_writing_context` 扩展：新增关联 KB 检索段（依据 novel.knowledge_base_id），命中条目以 `=== 原作知识库参考 ===` 注入
  - [x] SubTask 5.3: `app/services/chapter_service.py` 的 `_build_chapter_state` 读取 novel.knowledge_base_id 放入 state，供 writer_agent 使用
  - [x] SubTask 5.4: 同人小说校验：`app/api/outlines.py` 生成全文大纲端点若 novel.is_fanwork 且无 knowledge_base_id，返回 400 提示需先准备知识库

- [x] Task 6: 知识库前端（列表页 + 分类详情页可视化）
  - [x] SubTask 6.1: `static/index.html` 主导航新增"知识库"入口；新增列表容器与详情容器（或独立 overlay）
  - [x] SubTask 6.2: 新建 `static/js/knowledge-base.js`：列表页渲染卡片（名称/题材/原作/条目数），支持新建/删除；详情页按分类分区展示条目，支持编辑/删除/手动添加
  - [x] SubTask 6.3: 详情页支持上传文件导入（调 import-file）与"批量写入"（供 AI 联网补全场景粘贴整理好的结构化知识）
  - [x] SubTask 6.4: `static/css/style.css` 新增知识库卡片、分类分区、条目卡片样式，与现有深色主题一致
  - [x] SubTask 6.5: `novel-wizard.js` 的知识库准备子步骤复用列表数据（拉取已有知识库供选择）

- [x] Task 7: 联调与端到端验证

- [x] Task 8: 修复验证发现的阻断性 bug
  - [x] SubTask 8.1: 修复 KB 路由 prefix（main.py 改为 /api/knowledge-bases）
  - [x] SubTask 8.2: 修复 novel-wizard.js fanwork_kb 步骤：renderWizardInput 处理 fanwork_kb 类型（原作名输入+知识库选择 UI）、validate 类型匹配、仅同人时展示
  - [x] SubTask 8.3: 修复 proceedToExpand payload 携带 genre 与 knowledge_base_id
  - [x] SubTask 8.4: 重新验证 checklist 项 10/13/14/24
  - [x] SubTask 7.1: 验证独立知识库 CRUD + 向量检索与 per-novel RAG 隔离
  - [x] SubTask 7.2: 验证同人小说强制知识库流程（未关联被拦截、关联后放行）
  - [x] SubTask 7.3: 验证大纲/章节生成注入关联 KB 内容（同人内容不偏离原作）
  - [x] SubTask 7.4: 验证文件上传提取与 AI 联网批量写入均入库且可检索
  - [x] SubTask 7.5: 启动服务器，端到端验证：建知识库 -> 上传/联网补全 -> 同人小说关联 -> 生成大纲 -> 章节写作注入 -> 可视化浏览

# Task Dependencies
- Task 2 / Task 3 / Task 5 依赖 Task 1
- Task 4 依赖 Task 2（知识库 API）
- Task 6 依赖 Task 2 / Task 3（API 端点）
- Task 1 与 Task 6 的前端骨架可并行
- Task 7 依赖所有前置任务
