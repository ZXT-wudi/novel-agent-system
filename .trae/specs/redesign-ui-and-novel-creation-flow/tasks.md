# Tasks

- [x] Task 1: 后端数据模型与 schema 扩展——为小说问答采集的元数据新增字段
  - [x] SubTask 1.1: 在 `app/models/novel.py` 的 Novel 模型新增字段：`writing_style`（String，写作方式）、`target_word_count`（Integer，目标总字数）、`narrative_pov`（String，叙事人称）
  - [x] SubTask 1.2: 在 `app/schemas/novel.py` 的 `NovelCreate` schema 新增对应可选字段，并在 `NovelResponse` 中返回这些字段
  - [x] SubTask 1.3: 运行迁移/重建数据库表，验证字段持久化正常（已用 ALTER TABLE 保留数据）

- [x] Task 2: 后端问答扩写与自动衔接大纲生成 API
  - [x] SubTask 2.1: 在 `app/services/novel_service.py` 新增 `expand_novel_from_qa` 函数：接收问答采集的原始信息（标题/大致内容/写作方式/目标字数/篇幅类型），调用 LLM 扩写出丰富简介、Genre、世界设定雏形与主角建议，构造 NovelCreate 入参
  - [x] SubTask 2.2: 在 `app/api/novels.py` 新增 `POST /api/novels/from-qa` 端点，接收问答结果，调用扩写后创建小说并返回 novel_id
  - [x] SubTask 2.3: 验证创建的小说包含写作方式、目标字数等元数据

- [x] Task 3: 大纲 Agent 提示词注入写作元数据
  - [x] SubTask 3.1: 在 `app/agents/outline_agent.py` 的 `_build_full_outline_messages` 中注入 `writing_style`、`target_word_count`、`narrative_pov`，并调整 `FULL_OUTLINE_SYSTEM_PROMPT` 使其按目标字数推导合理卷数与章节量
  - [x] SubTask 3.2: 从 state 取 novel 详情时读取并传递这些新字段（确认 `generate_full_outline` / `generate_full_outline_stream` 能拿到 novel 的元数据）
  - [x] SubTask 3.3: 验证生成的大纲体积/卷数与目标字数一致

- [x] Task 4: 小说创建智能问答前端（novel-wizard.js）
  - [x] SubTask 4.1: 新建 `static/js/novel-wizard.js`，实现多轮引导式问答对话界面（AI 提问气泡 + 用户输入框 + 历史记录），依次收集标题、大致内容、写作方式、目标字数/篇幅
  - [x] SubTask 4.2: 收集完成后调用 `POST /api/novels/from-qa`，展示 AI 扩写后的设定摘要供用户确认
  - [x] SubTask 4.3: 用户点击"确认"后保存小说，并自动触发全文大纲生成（调用 `generateFullOutline` 流式生成），无需额外手动点击
  - [x] SubTask 4.4: 在 `index.html` 引入 `novel-wizard.js`，并将导航栏"新建小说"按钮改为调用问答流程入口 `startNovelWizard()`

- [x] Task 5: 大纲全屏展开查看与编辑（UI 重塑）
  - [x] SubTask 5.1: 在 `index.html` 侧栏全文大纲面板头部新增"展开查看"按钮；在章节大纲面板头部新增"展开查看"按钮
  - [x] SubTask 5.2: 在 `static/js/outline.js` 实现 `openFullOutlineFullscreen()` / `openOutlineFullscreen()`：将主内容区切换为全屏大纲视图（隐藏 chapter-content、welcome-screen，显示大纲编辑区），完整展示所有字段并使其可编辑
  - [x] SubTask 5.3: 全屏视图提供"保存并返回"与"取消"按钮；保存后更新 `currentFullOutline`/`currentOutline`，重置确认状态，调用后端 PUT 保存，返回侧栏视图
  - [x] SubTask 5.4: 在 `style.css` 新增全屏大纲视图样式（紧凑列表 + 可编辑卡片 + 滚动容器），保证 320px 侧栏摘要与全屏完整视图并存

- [x] Task 6: 知识图谱分阶段角色演化视图（重新设计）
  - [x] SubTask 6.1: 在 `knowledge-graph.js` 顶部筛选器新增视图切换：角色演化（默认）/ 关系网络 / 世界观地图，替换旧的全部/角色/章节/世界观筛选
  - [x] SubTask 6.2: 实现 `renderCharacterStageView(data)`：顶部阶段选择器（基于 `regions` 或 full_outline 的卷范围生成阶段列表），主区域显示该阶段内出场角色卡片，主角置顶突出，含姓名/类型/设定/关系/出场章节
  - [x] SubTask 6.3: 切换阶段时更新角色设定为该阶段最新状态（利用按章节号过滤 story_knowledge 中记录的 character 描述），呈现角色演化
  - [x] SubTask 6.4: 优化 `renderWorldMap` 与力导向图视觉精良度（配色、间距、卡片样式），统一与新角色视图的风格
  - [x] SubTask 6.5: 后端 `build_graph_data` 在已有 regions 基础上返回按阶段聚合的角色信息（`stages` 字段：每阶段含 name、chapter_range、characters 列表）

- [x] Task 7: 整体架构与流程自检
  - [x] SubTask 7.1: 检查小说创建 → 全文大纲 → 章节大纲 → 写作全链路状态衔接正确（确认按钮可用性、状态栏提示）
  - [x] SubTask 7.2: 检查提示词与 state 字段是否完整传递（写作方式、目标字数、前文知识），修复架构断层
  - [x] SubTask 7.3: 启动服务器并人工验证：问答创建小说 → 自动生成全文大纲 → 展开修改确认 → 生成章节大纲 → 知识图谱分阶段查看

# Task Dependencies
- Task 2 依赖 Task 1（需要新字段）
- Task 3 依赖 Task 1（Agent 读取新字段）
- Task 4 依赖 Task 2（前端调用问答扩写 API）
- Task 5 与 Task 6 相互独立，可并行
- Task 7 依赖所有前置任务
