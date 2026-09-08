# 强化写作文风约束：作者智能体 / 审查员 / AI润色师

## Summary

用户反馈：虽已给作者智能体提示词加入写作约束，但生成的正文仍大量出现破折号"——"作补充说明、"不是……而是……"翻转句，读起来不自然；审查员修订时未注意到这些约束（审查员提示词中根本没有文笔/AI腔约束）；AI润色师的去AI化清单也漏了这两项。

本计划在四个层面同时收紧文风约束，并新增专职"文笔审查员"形成双保险，确保从生成→审查→修订→润色全链路一致执行。

## Current State Analysis

| 角色 | 文件:行 | 约束现状 | 问题 |
|---|---|---|---|
| 作者智能体 | `app/agents/writer_agent.py:37` (`WRITER_SYSTEM_PROMPT`) | 有，措辞"**克制使用**"排比堆叠、破折号——、"不是…而是…" | "克制"=少用而非禁用，LLM 仍大量产出；埋在【写作技巧】里不够突出。`revise_chapter`（L383）复用此提示词，故加强后修订环节同步受益 |
| 逻辑审查员 | `app/agents/readers/logic_reader.py:7-43` (`LOGIC_READER_PROMPT`) | **无**任何文笔约束，只审逻辑自洽 | 不会标记破折号/不是而是，修订链路无反馈 |
| 角色审查员 | `app/agents/readers/character_reader.py:7-43` (`CHARACTER_READER_PROMPT`) | **无**任何文笔约束，只审人物塑造 | 同上 |
| AI润色师 | `app/agents/readers/polish_reader.py:16-23` (`POLISH_READER_PROMPT`) | 去AI化清单详尽（刻板过渡词/排比堆砌/同质化句式/欧化翻译腔/机械升华） | **唯独未显式列出"破折号——补充说明"和"不是…而是翻转句"**这两项用户最反感的模式 |
| 裁决提示词 | `app/agents/writer_agent.py:45-69` (`EVALUATE_SYSTEM_PROMPT`) | 区分"真问题"应接受、"风格偏好"可拒绝 | AI腔句式可能被判为"风格偏好"而遭拒绝，需澄清属质量问题 |

**编排链路**：
- 非流式：`graph.py:24-27` `asyncio.gather(review_character, review_logic)` → `evaluate_reviews` → `revise_chapter`(用 `WRITER_SYSTEM_PROMPT`) → `polish_chapter`
- 流式：`chapter_service.py:340-360` 串行 character→logic → evaluate → revise → polish
- 前端：`static/js/review.js:114` `getReaderTypeName` 映射 `{character:"人物", logic:"逻辑"}`，新审查员需补映射

## Proposed Changes

### 改动 1：强化作者智能体文风约束为硬约束
**文件**：`app/agents/writer_agent.py`
**对象**：`WRITER_SYSTEM_PROMPT`（L12-42）
**做法**：
- 删除 L37 的弱措辞行（"克制使用排比堆叠、破折号……"）
- 在【写作重点】（L30 结束）与【写作技巧】（L32 开始）之间，插入独立的 `【文风硬约束 · 必须遵守】` 区块，措辞改为"严禁"，并放至突出位置：
  ```
  【文风硬约束 · 必须遵守】
  - 严禁使用破折号"——"作补充说明或解释（如"他走了——带着不甘"），需要补充信息时改用独立短句或逗号分句；
  - 严禁"不是……而是……"翻转句式，直接陈述，让信息自然流出；
  - 严禁排比堆砌、为对仗而对仗的机械句式；
  - 严禁"综上所述、由此可见、不难发现、值得一提的是"等AI过渡腔与套话；
  - 句子要自然落地，短句碎句皆是节奏，不为刻意造势而堆砌。
  ```
- 【写作技巧】保留其余条目（每段80字、具体细节、环境细节、文笔流畅），仅移除原 AI 腔那行以避免重复
- **收益**：`write_chapter`、`write_chapter_stream`、`revise_chapter` 三处均复用此提示词，一处加强全链路生效

### 改动 2：逻辑审查员新增"文笔与AI腔"审查维度
**文件**：`app/agents/readers/logic_reader.py`
**对象**：`LOGIC_READER_PROMPT`
**做法**：在【审查维度】第 5 条（信息一致性）后新增第 6 条：
```
6. 文笔与AI腔：是否滥用破折号"——"作补充说明、"不是……而是……"翻转句、排比堆砌、刻板过渡词等AI腔句式；这类句式降低文本自然度，须标记并建议改写。
```
并在【严重程度判定】补充：`AI腔句式滥用统一记为 medium。`

### 改动 3：角色审查员新增"文笔与AI腔"审查维度
**文件**：`app/agents/readers/character_reader.py`
**对象**：`CHARACTER_READER_PROMPT`
**做法**：在【审查维度】第 5 条（人物关系）后新增第 6 条（同上措辞，可侧重对白与叙述文笔），并在严重程度补充同款 medium 规则。

### 改动 4：新建专职"文笔审查员"
**文件**：`app/agents/readers/style_reader.py`（新建）
**内容**：
- `STYLE_READER_PROMPT`：专职审查文笔自然度与AI腔，审查维度聚焦：① 破折号"——"补充说明滥用；② "不是…而是…"翻转句；③ 排比堆砌/机械对仗；④ 刻板过渡词与套话；⑤ 欧化长难句/翻译腔；⑥ 章末机械升华收束。每条意见须给出具体位置 + 改写建议，severity 统一 medium 起步。
- `review_style(state)` 函数：结构镜像 `review_character`/`review_logic`（取 chapter_draft、outline_item、可选 knowledge 检索），`reader_type` 返回 `"style"`，输出严格 JSON（同 comments/overall_score/overall_comment 结构）。
- 使用默认 `llm_client`（与 logic/character 一致）。

### 改动 5：将文笔审查员接入并行审查编排
**文件**：`app/agents/graph.py`
**对象**：`review_parallel`（L21-38）
**做法**：
- 顶部 import 增加 `from app.agents.readers.style_reader import review_style`
- `asyncio.gather` 内追加 `review_style(state)`（与 character、logic 并行）

### 改动 6：将文笔审查员接入流式编排
**文件**：`app/services/chapter_service.py`
**对象**：`generate_chapter_with_stream`（L319-360）
**做法**：
- L320-322 import 块追加 `from app.agents.readers.style_reader import review_style`
- 在 logic 审查（L346-350）之后、收集 comments（L352）之前，插入一段：发送 `{"type":"status","phase":"reviewing","message":"文笔审查员正在审查...","reviewer":"style"}` 事件，`try: style_result = await review_style(state) except LLMError: style_result = {...}`
- `[char_result, logic_result]` 列表改为 `[char_result, logic_result, style_result]`

### 改动 7：AI润色师去AI化清单补全两项
**文件**：`app/agents/readers/polish_reader.py`
**对象**：`POLISH_READER_PROMPT`（L16-23 "二、彻底去AI化"清单）
**做法**：在现有 bullet 列表（L18-23）中追加两条：
```
• 破折号补充说明滥用：滥用"——"作解释/补充（如"他笑了——带着苦涩"），一律改为独立短句或逗号分句；
• 翻转句式：滥用"不是……而是……"句式，一律改为直接陈述。
```
（同步在 L51 `Constraints` 第 2 条"去AI化核心要求"末尾追加这两项，保持两处一致。）

### 改动 8：裁决提示词澄清AI腔属质量问题
**文件**：`app/agents/writer_agent.py`
**对象**：`EVALUATE_SYSTEM_PROMPT`（L45-69）
**做法**：在【裁决准则】"区分真问题与风格偏好"那条后补一句：
```
- 破折号"——"补充说明、"不是…而是…"翻转句、排比堆砌等AI腔句式属于文本质量问题（非个人风格偏好），审查员指出后应予接受并改写。
```

### 改动 9：前端审查员类型映射补全
**文件**：`static/js/review.js`
**对象**：`getReaderTypeName`（L113-116）
**做法**：`const map = { character: "人物", logic: "逻辑", style: "文笔" };`

## Assumptions & Decisions

1. **"严禁"而非"克制"**：用户明确反馈"克制使用"无效，故作者提示词改为硬禁止措辞，并提升为独立区块增强注意力权重。
2. **双保险策略**：用户选择"两者都做"——既给现有两个审查员加文笔维度，又新建专职文笔审查员并行运行。现有审查员加维度覆盖面广（即使只跑 character 也能抓到），专职审查员聚焦深度。两者 comment 都进 `review_comments`，经 evaluate→revise 链路统一处理。
3. **severity 定为 medium**：AI腔句式不影响情节理解，定为 low 易被裁决器以"风格偏好"拒绝；定为 medium 确保被接受进入修订。不设 high 以免与逻辑硬伤混淆。
4. **review_style 用默认 llm_client**：与 logic/character 一致（均用 `common` purpose 的 `llm_client`），不额外引入模型配置依赖。
5. **不修改 plot_reader.py**：该文件存在但 `review_plot` 全局未被调用，属遗留代码，不在本次范围。
6. **不修改知识提取类提示词**：`knowledge_service.py`/`kb_service.py`/`chapter_service.py:_SEMANTIC_SYSTEM_PROMPT` 已有"避免"措辞且用于摘要而非正文，用户未提及，保持不动。

## Verification

1. **语法验证**：`d:\xiaoshuo\venv\Scripts\python.exe -m py_compile app\agents\writer_agent.py app\agents\readers\logic_reader.py app\agents\readers\character_reader.py app\agents\readers\style_reader.py app\agents\graph.py app\services\chapter_service.py app\agents\readers\polish_reader.py` 全部 exit 0。
2. **提示词一致性自检**：grep 确认 "破折号" 和 "不是……而是" 关键词在 writer_agent.py、logic_reader.py、character_reader.py、style_reader.py、polish_reader.py 五处提示词中均出现。
3. **链路连通自检**：grep 确认 `review_style` 在 style_reader.py 定义、graph.py 和 chapter_service.py 均有 import 与调用。
4. **前端映射自检**：grep 确认 review.js 的 map 含 `style` 键。
5. **运行验证（用户侧）**：生成一章正文，检查输出是否仍大量出现"——"补充说明与"不是…而是…"句式；审查面板是否出现"文笔"类型意见。
