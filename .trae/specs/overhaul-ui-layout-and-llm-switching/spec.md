# 温暖纸张风界面重塑与大模型切换 Spec

## Why
当前所有功能（全文大纲、章节大纲、写作控制、知识库、知识图谱）全部挤在一个 320px 侧栏的单页里，主内容区被压缩，界面拥挤难看；配色为冷调蓝黑（`#1a1a2e` / `#16213e` / `#6c63ff`），与小说写作的手稿气质不符。同时大模型硬编码为 SiliconFlow 单一供应商，配置只能通过 `.env` 修改，无法在运行时切换不同厂商的大模型与 API Key。

## What Changes
- **采用温暖纸张浅色配色**：弃用冷调蓝黑，改为米色/暖灰背景 + 暖琥珀/赭石点缀的浅色主题，贴合写作手稿气质、护眼舒适。
- **左侧图标导航栏 + 分视图**：新增窄图标活动栏，切换 写作台 / 大纲 / 知识库 / 设置 四个视图，每个视图只承载对应功能，主内容区更宽敞。
  - 写作台：章节选择 / 内容展示 / 编辑 / AI 重写 / 写作控制
  - 大纲：全文大纲 + 章节大纲（含展开全屏编辑入口）
  - 知识库：偏好/世界观 + 知识库管理 + 知识图谱
  - 设置：大模型供应商管理 + 激活切换
- **BREAKING** 重构 `static/index.html` 为「图标栏 + 分视图容器」结构，旧的单侧栏布局被替换；功能入口从顶部栏迁移到对应视图。
- **新增大模型供应商管理**：DB 表存储多供应商配置（厂商类型 / 名称 / base_url / api_key / 对话模型 / 嵌入模型 / 是否激活），API 增删改查 + 激活切换；设置视图提供管理 UI（含厂商预设：SiliconFlow / OpenAI / DeepSeek / 智谱 / 自定义）。
- **LLM 客户端按激活供应商动态配置**：保留现有共享单例 `llm_client`（已被 7 个 service + embedder 引用），新增 `reconfigure` 能力；切换激活供应商时即时重载 base_url/api_key/对话模型/嵌入模型；启动时从 DB 载入激活供应商，无则回退 `.env` 默认。此举使所有现有调用点无需改动即可生效。

## Impact
- Affected specs: 与已完成的 `redesign-ui-and-novel-creation-flow`（大纲展开/知识图谱分阶段/问答创建）兼容——本 spec 复用其大纲全屏编辑与知识图谱视图，仅重新组织其所在的视图容器与配色。
- Affected code:
  - `static/index.html`（重写为 图标栏 + 四个分视图容器，顶部栏精简）
  - `static/css/style.css`（新温暖纸张配色变量、图标活动栏、分视图布局、设置/供应商卡片样式）
  - `static/js/app.js`（视图切换 `switchView`、写作台/控制迁移、供应商管理调用、顶部激活模型指示）
  - `static/js/outline.js` / `knowledge-base.js` / `knowledge-graph.js`（迁入对应视图，入口调整）
  - 新增 `static/js/settings.js`（设置视图 + 大模型供应商管理 UI）
  - 新增 `app/models/llm_provider.py`（供应商模型）
  - 新增 `app/schemas/llm_provider.py`（Create/Update/Response，Response 中 api_key 脱敏）
  - 新增 `app/api/llm_providers.py`（CRUD + 激活端点）
  - `app/llm/siliconflow.py`（增加 `reconfigure` 方法 + `reconfigure_llm_client(db)` 工厂）
  - `app/main.py`（注册新路由 + startup 载入激活供应商）
  - `app/database.py`（init 建新表）

## ADDED Requirements

### Requirement: 温暖纸张浅色主题
系统 SHALL 采用温暖纸张风格的浅色配色（米色/暖灰背景 + 暖琥珀/赭石点缀 + 暖深棕文字），弃用原冷调蓝黑。

#### Scenario: 全局换肤
- **WHEN** 用户打开任意界面
- **THEN** 背景为暖米/暖灰，文字为暖深棕，主操作色为暖琥珀/赭石，全站不再出现 `#1a1a2e` / `#16213e` / `#6c63ff` 等冷蓝黑配色

### Requirement: 左侧图标导航栏与分视图
系统 SHALL 提供左侧窄图标活动栏，在 写作台 / 大纲 / 知识库 / 设置 四个视图间切换，每个视图只承载对应功能。

#### Scenario: 用户切换视图
- **WHEN** 用户点击图标栏某图标
- **THEN** 主内容区切换为对应视图，其余视图隐藏，被点击图标高亮为当前视图

### Requirement: 大纲视图集中承载大纲
系统 SHALL 在「大纲」视图集中展示全文大纲与章节大纲（含展开全屏编辑入口）。

### Requirement: 知识库视图集中承载知识
系统 SHALL 在「知识库」视图集中展示偏好/世界观、知识库管理与知识图谱。

### Requirement: 写作台视图集中承载写作
系统 SHALL 在「写作台」视图集中展示章节选择、内容展示/编辑、AI 重写与写作控制。

### Requirement: 大模型供应商管理
系统 SHALL 支持新增/编辑/删除多个大模型供应商配置（厂商类型、名称、base_url、api_key、对话模型、嵌入模型），并指定其中之一为激活。

#### Scenario: 用户新增供应商
- **WHEN** 用户在设置视图填写厂商/名称/base_url/api_key/对话模型并保存
- **THEN** 配置存入数据库并出现在供应商列表，api_key 在列表中脱敏显示（仅显示末 4 位）

#### Scenario: 用户切换激活供应商
- **WHEN** 用户将某供应商设为激活
- **THEN** 系统将该供应商标记为激活（其余取消激活），并即时重新配置共享 LLM 客户端的 base_url/api_key/对话模型/嵌入模型，后续生成即使用新供应商

#### Scenario: 厂商预设可选
- **WHEN** 用户新增供应商时选择厂商预设
- **THEN** 自动填入该厂商的默认 base_url 与推荐模型名（SiliconFlow / OpenAI / DeepSeek / 智谱 / 自定义）

### Requirement: LLM 客户端按激活配置动态载入
系统 SHALL 在启动时从数据库载入激活供应商配置 LLM 客户端；若无激活供应商则回退 `.env` 默认配置。

#### Scenario: 启动载入激活供应商
- **WHEN** 服务启动
- **THEN** 读取 DB 激活供应商，配置共享 LLM 客户端的 base_url/api_key/对话模型/嵌入模型；无激活记录则使用 `.env` 的 SiliconFlow 配置

#### Scenario: 切换后即时生效
- **WHEN** 激活供应商被切换
- **THEN** 不重启服务，下一次 chat/chat_stream/embed/generate_image 调用即使用新供应商配置

## MODIFIED Requirements

### Requirement: 顶部导航栏
顶部栏精简为 品牌 + 小说选择器 + 新建小说 + 当前激活模型指示，不再承载章节选择/知识库/写作控制等入口（这些迁入对应视图）。小说选择与新建小说仍保留在顶部以便跨视图使用。

## REMOVED Requirements
（无功能移除，仅视图与配色重组）
