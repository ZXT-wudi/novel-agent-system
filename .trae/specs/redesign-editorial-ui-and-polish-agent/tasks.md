# Tasks

- [x] Task 1: 墨韵编辑风 CSS 设计系统全面重构
  - [x] SubTask 1.1: 在 `static/index.html` 引入 Noto Serif SC + Noto Sans SC 字体（Google Fonts `<link>`，含中文回退栈 Songti/STSong/serif）
  - [x] SubTask 1.2: 在 `static/css/style.css` `:root` 重构设计令牌：字体变量（`--font-serif`/`--font-sans`）、墨色文本（`--ink #2b2620` / `--ink-soft #5c5044` / `--ink-muted #8a7d6b`）、朱砂印章红（`--seal #b04a3f` / `--seal-hover #9a3d33`）、保留纸张色（`--paper #faf6ef`/`--paper-raised #fffdf8`/`--paper-recessed #f3ece0`）、发丝细线（`--rule #e0d4be`）、强化阴影（`--shadow`/`--shadow-lift`）、保留 `--amber #c8893f` 作次级点缀；将原 `--text-primary/--accent/--border` 等引用改为新令牌或别名兼容
  - [x] SubTask 1.3: 新增纸张纹理（`body::before` 细微噪点 data-uri SVG，~4% 不透明度，`position:fixed`，`pointer-events:none`，不挡交互）
  - [x] SubTask 1.4: 全组件编辑风精修——品牌与视图标题（衬线 + 朱砂下划线细线）、活动栏（衬线标签 + 朱砂激活态左条）、章节头（杂志卡：衬线"第N章" + 元信息行 + 发丝细线 + 柔阴影）、章节正文（阅读宽度 ~720px、行高 1.85、段首缩进 2em、首段首字下沉 `::first-letter` 朱砂衬线）、按钮（渐变 + 发丝边 + 柔影）、面板/卡片（发丝边 + 柔影 + 圆角 10px）、引用/批注（朱砂左竖线）、分隔符（居中◆）、徽章/状态药丸、审查卡片（衬线读者类型 + 朱砂采纳强调）
  - [x] SubTask 1.5: grep 确认全站无 `#1a1a2e`/`#16213e`/`#6c63ff`/`#5a52d5` 等冷蓝黑 hex

- [x] Task 2: 后端 AI 文章润色师智能体
  - [x] SubTask 2.1: 新建 `app/agents/readers/polish_reader.py`，定义 `POLISH_READER_PROMPT`（采用用户提供的完整 Profile，并追加输出约束：仅输出整章润色后全文，保留段落结构与换行，不得输出 JSON/markdown 围栏/前言后语/润色说明）
  - [x] SubTask 2.2: 实现 `async def polish_chapter(state) -> dict`：构造 messages（`system`=POLISH_READER_PROMPT，`user`=原文 `chapter_draft` + 文体/受众上下文），调用 `llm_client.chat(messages, temperature=0.5, max_tokens=8192)`，返回 `{"reader_type": "polish", "polished_draft": <润色全文>}`；参照 `logic_reader.py` 的 `knowledge_collection` 查询与异常处理写法
  - [x] SubTask 2.3: 静态核对 prompt 已含核心信息保真/去AI化/语言规范/语气适配约束

- [x] Task 3: 后端图与流程接入润色师
  - [x] SubTask 3.1: `app/agents/state.py` 新增 `polished_draft: Optional[str] = None` 字段
  - [x] SubTask 3.2: `app/agents/graph.py` `review_parallel`：将 `review_plot` 替换为 `polish_chapter`；gather 结果按 `reader_type` 分流——`polish` → `state["polished_draft"] = result["polished_draft"]`，其余并入 `review_comments`（保留 character+logic 评论）
  - [x] SubTask 3.3: `app/services/chapter_service.py` 流式 `generate_chapter_with_stream`：将 `review_plot` 调用块替换为 `polish_chapter` 块，状态事件文案改为"AI 文章润色师正在润色全章..."，`all_comments` 聚合跳过 polish 结果（仅 character+logic）
  - [x] SubTask 3.4: `chapter_service.py` 非流式 `generate_chapter`（经 `review_parallel`）自动兼容；核对无误
  - [x] SubTask 3.5: `chapter_service.py` `_state_to_response` 新增 `polished_draft` 字段（`state.get("polished_draft", "")`）

- [x] Task 4: 前端润色对比与采纳 UI
  - [x] SubTask 4.1: `static/js/review.js` `showReviewPanel`：当 `state.polished_draft` 存在时，在评论卡片之上渲染"AI 润色对比"卡——双栏（原文 `chapter_draft` / 润色文 `polished_draft`）可滚动，底部"一键采纳润色版" + "暂不采纳"两按钮
  - [x] SubTask 4.2: 新增 `acceptPolish()`：客户端将 `currentChapterContent` 设为 `polished_draft`，更新 `#chapter-text` 显示，隐藏润色卡，启用保存按钮（经现有 `saveCurrentChapter` 持久化）
  - [x] SubTask 4.3: 新增 `dismissPolish()`：隐藏润色卡，保留原文，不影响评论流程
  - [x] SubTask 4.4: `getReaderTypeName` 移除 `plot: "情节"` 映射（评论不再含 plot）；核对 `chapter.js` 状态文案由后端 `data.message` 驱动即可

- [x] Task 5: 整体自检与验证
  - [x] SubTask 5.1: 静态核对所有改动文件语法/导入无误（py_compile 受本机 PowerShell 策略限制，以静态核对为准）
  - [x] SubTask 5.2: grep 确认 CSS 无冷蓝黑残留、衬线字体已加载、首字下沉/朱砂点缀已就位
  - [x] SubTask 5.3: 静态核对流程链路：generate → polish_chapter(替换plot) → state.polished_draft → _state_to_response → showReviewPanel 对比 → acceptPolish → 保存

# Task Dependencies
- Task 1 与 Task 2 互相独立，可并行
- Task 3 依赖 Task 2（使用 `polish_chapter`）
- Task 4 依赖 Task 3（依赖 `polished_draft` 下发）
- Task 5 依赖 Task 1–4
