# 墨韵编辑风 UI 精修 + AI 文章润色师 Spec

## Why
当前温暖纸张扁平界面虽已分视图，但整体观感"太简陋"：缺乏排版层级、无编辑气质、章节区平铺无设计感。同时三个审查智能体（情节/人物/逻辑）中，用户希望用"AI 文章润色师"替换其中"情节审查员"，让审查环节多一条"整章润色 + 一键采纳"的人性化路径，消除 AI 机械感。

## What Changes
- **UI**：在保留温暖纸张浅色基底的前提下，整体升级为"墨韵编辑风"——引入衬线标题（Noto Serif SC）、首字下沉、杂志感章节卡片、纸张纹理、朱砂印章红点缀、发丝细线、统一编辑级排版层级与留白。**不使用冷蓝黑**（朱砂/墨色为暖系红与暖近黑，非冷蓝黑）。
- **智能体**：新增 `app/agents/readers/polish_reader.py`（AI 文章润色师），其系统提示词采用用户提供的完整 Profile；产出为**整章润色后全文**（`polished_draft`），不再产出评论卡片。
- **流程**：用润色师**替换** `review_plot`（情节审查员）的位置（总数仍为三：润色 + 人物 + 逻辑）。润色师与人物/逻辑并行运行，但其结果走独立分支（写入 `state["polished_draft"]`，不并入 `review_comments`）。
- **前端**：审查面板新增"AI 润色对比"区——原文 / 润色文双栏对比 + "一键采纳润色版" / "暂不采纳"。采纳为客户端替换 `chapter_draft` 并经现有保存流程持久化（鲁棒、不依赖 `_active_states`）。
- **状态下发**：`_state_to_response` 新增 `polished_draft` 字段，随流式 `complete` 事件下发。
- **状态文案**：流式状态文案由"情节审查员正在审查"改为"AI 文章润色师正在润色全章"。

## Impact
- Affected code:
  - `static/css/style.css`（设计令牌、字体、纸张纹理、全组件编辑风精修）
  - `static/index.html`（引入 Noto Serif SC 字体）
  - `app/agents/readers/polish_reader.py`（新增）
  - `app/agents/state.py`（新增 `polished_draft` 字段）
  - `app/agents/graph.py`（`review_parallel` 替换 `review_plot`→`polish_chapter`，分支处理）
  - `app/services/chapter_service.py`（流式 + 非流式接入润色师、状态文案、`_state_to_response` 暴露 `polished_draft`）
  - `static/js/review.js`（润色对比面板 + `acceptPolish` + `dismissPolish`）
  - `static/js/chapter.js`（状态文案适配核对）
- 既有评论审查流程（人物/逻辑 → `/decide`）保持不变；润色师走独立采纳路径，互不干扰。

## ADDED Requirements

### Requirement: 墨韵编辑风设计系统
系统 SHALL 在温暖纸张浅色基底上提供编辑级排版层级：衬线标题、首字下沉、杂志感章节卡片、纸张纹理、朱砂印章红点缀、发丝细线，且不得出现冷蓝黑色调。

#### Scenario: 首屏呈现编辑风
- **WHEN** 用户打开写作台
- **THEN** 章节标题为衬线字体，正文首段首字下沉为朱砂色衬线大字，章节卡带发丝细线与柔阴影，背景有细微纸张纹理

#### Scenario: 全站无冷蓝黑
- **WHEN** 全局检索 CSS 色值
- **THEN** 不存在 `#1a1a2e` / `#16213e` / `#6c63ff` / `#5a52d5` 等冷蓝黑 hex

### Requirement: AI 文章润色师智能体
系统 SHALL 提供 `polish_chapter` 智能体，其系统提示词为用户提供的"AI 文章润色师"完整 Profile；输入为章节原文，输出为**整章润色后全文**（保留段落结构与核心信息，无额外说明/无 JSON/无 markdown 围栏）。

#### Scenario: 润色产出全文
- **WHEN** 章节生成流程进入审查环节
- **THEN** 润色师与人物/逻辑审查并行运行，产出 `polished_draft`（整章润色全文），并存入 `state["polished_draft"]`

### Requirement: 润色对比与一键采纳
系统 SHALL 在审查面板提供原文 / 润色文双栏对比，并提供"一键采纳润色版"与"暂不采纳"。

#### Scenario: 采纳润色版
- **WHEN** 用户点击"一键采纳润色版"
- **THEN** 章节正文被替换为润色全文，润色卡片关闭，保存按钮可用；经现有保存流程持久化

#### Scenario: 暂不采纳
- **WHEN** 用户点击"暂不采纳"
- **THEN** 保留原文，润色卡片关闭，原审查评论流程不受影响

## MODIFIED Requirements

### Requirement: 审查并行环节
`review_parallel` 现并行运行 `polish_chapter` + `review_character` + `review_logic`；对结果按 `reader_type` 分流：`polish` → 写入 `state["polished_draft"]`；其余 → 并入 `review_comments`。流式生成流程同步替换 `review_plot` 调用为 `polish_chapter`，状态文案改为润色师。

## REMOVED Requirements

### Requirement: 情节审查员（plot_reader）接入流程
**Reason**: 用户指定用 AI 文章润色师替换情节审查员。
**Migration**: `plot_reader` 不再被 `review_parallel` / 流式流程调用（文件可保留备查）；`getReaderTypeName` 中 `plot: "情节"` 映射移除（评论中不再出现 plot 类型）。
