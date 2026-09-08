# 手动写作与 AI 补全 Spec

## Why
当前系统只能由 AI 整章生成后再供用户修改。用户希望也能亲自撰写章节，并在写作时获得类似代码补全的 AI 实时续写提示（按 Tab 接受），降低纯手写的负担同时保留完全的创作主导权。现有 `write_chapter` 与 `write_chapter_stream` 上下文构建逻辑高度重复，需顺势抽取公共函数消除冗余。

## What Changes
- 新增**写作模式选择**：点击"开始写下一章"时，让用户选择"AI 自动写作"或"手动写作（AI 辅助补全）"
- 新增**手动写作模式**：用户在编辑器中直接撰写；AI 基于已输入文本 + 章节大纲 + 全文大纲 + RAG（前文章节/语义/世界观/偏好）+ 故事知识 + 写作元数据，生成一段续写建议
- 新增**补全交互**：建议以灰色幽灵文本显示在光标后方；**Tab 接受**追加到正文、**Esc 取消**；用户继续输入则旧建议清除并在停顿后重新请求
- 新增后端 `POST /api/novels/{novel_id}/chapters/{chapter_num}/suggest` 端点，返回续写建议片段
- **重构**：抽取 `writer_agent` 中重复的上下文构建逻辑为公共函数，写作与补全共用，消除冗余
- **复用**：手动模式完成后点击"保存章节"走与 AI 模式完全相同的保存链路（章节持久化 + 版本管理 + 知识抽取 + 语义分析 + 向量入库）

## Impact
- Affected code:
  - 后端：`app/agents/writer_agent.py`（重构 + 新增补全函数）、`app/api/chapters.py`（新增 suggest 端点）、`app/services/chapter_service.py`（复用 `_build_chapter_state`）
  - 前端：`static/js/chapter.js`（模式选择、手动写作、补全交互）、`static/index.html`（编辑器结构/按钮）、`static/css/style.css`（幽灵文本样式）
- 不改动：保存链路 `/save`、知识抽取、语义分析、向量入库（手动模式直接复用）

## ADDED Requirements

### Requirement: 写作模式选择
系统 SHALL 在用户点击"开始写下一章"时提供写作模式选择，至少包含"AI 自动写作"与"手动写作（AI 辅助补全）"两个选项。

#### Scenario: 选择 AI 自动写作
- **WHEN** 用户点击"开始写下一章"并选择"AI 自动写作"
- **THEN** 执行现有 AI 流式生成流程（行为与改造前一致）

#### Scenario: 选择手动写作
- **WHEN** 用户选择"手动写作（AI 辅助补全）"
- **THEN** 进入手动写作编辑器，光标聚焦可立即输入，AI 补全就绪

### Requirement: AI 续写补全
系统 SHALL 在手动写作模式下，基于用户已输入内容与小说上下文生成续写建议片段。

#### Scenario: 停顿触发建议
- **WHEN** 用户在手动写作中停止输入达到防抖阈值（约 1 秒）且自上次建议后有足量新内容
- **THEN** 后端依据"当前正文尾部 + 章节大纲 + 全文大纲 + RAG 上下文 + 故事知识 + 写作元数据"生成一段续写建议（约 100-300 字，一个段落或一个场景节拍）
- **AND** 建议以灰色幽灵文本显示在光标后方

#### Scenario: Tab 接受建议
- **WHEN** 存在待接受建议且用户按下 Tab 键
- **THEN** 建议文本追加到正文末尾，幽灵文本清除，可在新内容基础上继续触发下一轮建议

#### Scenario: 继续输入忽略建议
- **WHEN** 存在待接受建议但用户继续键入新字符
- **THEN** 旧建议立即清除；当用户再次停顿时，依据更新后的正文重新请求新建议

#### Scenario: Esc 取消建议
- **WHEN** 用户按下 Esc 键
- **THEN** 当前建议清除且在再次停顿前不再请求

#### Scenario: 请求中止
- **WHEN** 用户在建议请求未返回时继续输入
- **THEN** 中止在途请求，避免过期建议覆盖新输入

### Requirement: 手动写作保存复用
系统 SHALL 在手动写作完成后，通过既有"保存章节"按钮走与 AI 模式相同的保存链路。

#### Scenario: 保存手动章节
- **WHEN** 用户在手动模式下完成整章并点击"保存章节"
- **THEN** 触发 `POST /api/novels/{id}/chapters/{num}/save`，执行章节持久化（status=final）、版本管理、故事知识抽取、语义分析与向量入库
- **AND** 知识图谱等下游视图随之更新

## MODIFIED Requirements

### Requirement: 写作上下文构建（去冗余）
`writer_agent` 中 `write_chapter` 与 `write_chapter_stream` 的上下文拼接逻辑 SHALL 抽取为单一公共函数，写作（流式/非流式）与补全建议共用，不再各自重复实现。

### Requirement: 章节生成入口
"开始写下一章"按钮 SHALL 先弹出模式选择，而非直接进入 AI 生成；原 AI 生成逻辑作为"AI 自动写作"选项的行为保留。

## REMOVED Requirements
无（纯新增与重构，不删除既有能力）。
