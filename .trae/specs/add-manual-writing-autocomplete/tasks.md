# Tasks

- [x] Task 1: 后端重构与补全函数（消除 write_chapter / write_chapter_stream 上下文构建冗余，新增续写补全函数）
  - [x] SubTask 1.1: 在 `app/agents/writer_agent.py` 抽取公共函数 `_build_writing_context(state) -> str`，将前文章节、语义摘要、RAG、用户偏好、故事知识、写作元数据的拼接逻辑统一到此函数（消除 `write_chapter` 与 `write_chapter_stream` 的重复块）
  - [x] SubTask 1.2: `write_chapter` 与 `write_chapter_stream` 改为调用 `_build_writing_context`，行为保持不变
  - [x] SubTask 1.3: 新增 `async def suggest_continuation(state: NovelState, current_text: str) -> str`：基于公共上下文 + 用户当前正文尾部（约 2000 字），构造续写提示词，调 `llm_client.chat(temperature=0.7, max_tokens=500)` 返回一段续写（约 100-300 字）；提示词强调"仅输出续写片段、不重复已有内容、遵循章节大纲与写作方式/人称"

- [x] Task 2: 后端补全建议端点
  - [x] SubTask 2.1: 在 `app/api/chapters.py` 新增 `POST /{novel_id}/chapters/{chapter_num}/suggest`，请求体 `{ "current_text": str }`
  - [x] SubTask 2.2: 端点内调 `chapter_service._build_chapter_state` 构建上下文，再调 `suggest_continuation(state, current_text)`；对 LLM 失败返回 `{"suggestion": ""}` 不抛 500
  - [x] SubTask 2.3: 验证端点返回 `{"suggestion": "..."}` 且不改动任何数据库状态

- [x] Task 3: 前端写作模式选择入口
  - [x] SubTask 3.1: 在 `static/js/chapter.js` 将现有 `startWriting` 改为先弹出模式选择（复用 `showModal` 或轻量弹层），提供"AI 自动写作""手动写作（AI 辅助补全）"两项
  - [x] SubTask 3.2: 选择"AI 自动写作"调用原 AI 生成流程（可重命名为 `startAiWriting`，行为不变）；选择"手动写作"调用新增 `startManualWriting()`
  - [x] SubTask 3.3: `startManualWriting()`：初始化手动写作状态（`chapterWriting` 标志、新章号、版本徽章置"写作中"），显示编辑器、聚焦、启用保存按钮

- [x] Task 4: 前端手动写作编辑器与 AI 补全交互
  - [x] SubTask 4.1: 在 `static/index.html` / `static/js/chapter.js` 实现手动写作编辑区，支持显示灰色幽灵文本建议（推荐 overlay 叠加在 textarea 之上或 contenteditable 方案，保证滚动同步）
  - [x] SubTask 4.2: 实现防抖触发（约 1 秒停顿 + 自上次建议后足量新内容）请求 `/suggest`；输入恢复时用 `AbortController` 中止在途请求
  - [x] SubTask 4.3: Tab 键接受建议（追加到正文、清除幽灵文本、可继续触发下一轮）；Esc 键清除当前建议
  - [x] SubTask 4.4: 用户继续输入时旧建议立即清除；保存时以编辑器全文作为章节内容
  - [x] SubTask 4.5: 在 `static/css/style.css` 新增幽灵文本/手动模式编辑器样式

- [x] Task 5: 联调与验证
  - [x] SubTask 5.1: 验证手动写作保存后走 `/save` 链路：章节持久化、知识抽取、语义分析、向量入库正常，知识图谱可更新
  - [x] SubTask 5.2: 验证 AI 自动写作模式行为与改造前一致
  - [x] SubTask 5.3: 启动服务器，端到端验证：模式选择 -> 手动写作 + Tab 补全 -> 保存 -> 下游更新

# Task Dependencies
- Task 2 依赖 Task 1（补全端点调用 suggest_continuation）
- Task 4 依赖 Task 2（前端调用 suggest 端点）与 Task 3（手动写作入口）
- Task 1 与 Task 3 相互独立，可并行
- Task 5 依赖所有前置任务
