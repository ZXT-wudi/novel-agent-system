# 修复章节写作三大严重问题

## 问题概述

用户报告了三个严重问题：
1. **"短篇"显示错误**：选择了80万字，但选择栏显示"短篇"
2. **章节字数过短**：生成约2000字，应为4000-6000字
3. **写作质量差**：无主角视角、无心理描写、比喻修辞过多（"像..."泛滥）、无意义修饰句堆砌

## 根因分析

### 问题1：显示"短篇"
- 数据库 novel ID=5 的 `length_type=long, target_word_count=800000` **是正确的**
- 但 `narrative_pov`、`writing_style`、`genre` **全部为空**
- 根因：小说通过旧快速创建表单（[app.js:95-98](file:///d:/xiaoshuo/static/js/app.js#L95-L98)）创建，该表单只发送 `title, genre, description, length_type`，不收集 `writing_style`、`narrative_pov`、`target_word_count`
- 旧表单 `length_type` 默认选中"短篇"radio（[index.html](file:///d:/xiaoshuo/static/index.html)），用户创建时看到"短篇"，后经大纲页面更新为"长篇"但初始状态已造成困扰
- 前端显示逻辑本身正确（[app.js:119](file:///d:/xiaoshuo/static/js/app.js#L119)）

### 问题2：章节字数过短
- [writer_agent.py:59](file:///d:/xiaoshuo/app/agents/writer_agent.py#L59) 系统提示词有"每章字数控制在3000-5000字"
- 但用户消息（[L241](file:///d:/xiaoshuo/app/agents/writer_agent.py#L241)）只说"控制每章篇幅与目标总字数相匹配"——太模糊，LLM不遵循
- `max_tokens=8192`（[L244](file:///d:/xiaoshuo/app/agents/writer_agent.py#L244)）足够生成4000-6000字，问题在提示词不够强

### 问题3：写作质量差
- **根因1**：[L35](file:///d:/xiaoshuo/app/agents/writer_agent.py#L35) 【写作重点】写"选择以下一个焦点做深度优化（不必三选全做）"——允许AI跳过心理描写，选择"环境描写"导致修辞堆砌
- **根因2**：`narrative_pov` 为空 → [L207-208](file:///d:/xiaoshuo/app/agents/writer_agent.py#L207-L208) 不注入"叙事人称" → [L241](file:///d:/xiaoshuo/app/agents/writer_agent.py#L241) "请严格遵循上述叙事人称行文"无内容可遵循
- **根因3**：现有反比喻规则（[L43](file:///d:/xiaoshuo/app/agents/writer_agent.py#L43)）未明确禁止"像..."明喻句式，LLM仍大量使用
- **根因4**：无"简单明了"、"聚焦核心剧情"、"减少不必要描写"原则
- **根因5**：无主角视角和心理描写的明确指令

## 修改方案

### 修改1：writer_agent.py — WRITER_SYSTEM_PROMPT 重构（核心修改）

**文件**：`d:\xiaoshuo\app\agents\writer_agent.py`
**位置**：L12-60 `WRITER_SYSTEM_PROMPT`

#### 1a. 重构【写作重点】（L34-38）
将"选择一个焦点（不必三选全做）"改为**心理描写为核心、根据情节类型调整**：

```
【写作重点 · 心理与动作为核心】
- 心理活动是每章必须项：主角在当前场景下的情绪反应（害怕、意外、陌生、愤怒、期待、困惑等）必须具体可感地写出来，不是概述"他感到害怕"，而是写出害怕的具体表现——身体反应、思维碎片、本能冲动；
- 动作描写与心理描写交替：打斗/冲突场景侧重动作节奏与紧张感，但穿插主角内心判断与情绪；日常/情感场景侧重心理与对话，动作作为辅助；
- 环境描写仅作背景：一两笔点明场景即可，不得大段铺陈环境，环境细节服务于角色内心而非独立成景；
- 对话推动情节：每个角色有独特说话风格，潜台词丰富，不写无效寒暄。
```

#### 1b. 强化【文风硬约束】（L40-49）
在现有规则基础上，新增针对"像..."明喻和修饰句的强约束：

```
- 严禁"像...""如同...""仿佛...""好似...""犹如..."等一切明喻句式——不得用"像"字做环境描写或心理描写，直接写出事物本身的状态和角色的情绪，不用比喻绕弯；
- 严禁无意义的修饰性句子——每个句子必须推动剧情、揭示人物或传递信息，不得写"月光洒落在地上，给大地披上一层银纱"这类纯装饰、零信息量的句子；
- 行文简单明了，用准确的动词和名词直白落地，不靠比喻和修饰句制造"高级感"；
- 聚焦核心剧情与人物，减少不必要的环境铺垫和修饰性描写，读者要的是故事和人物，不是散文；
- 句子要短、要干脆，一个句子只说一件事，该断就断，不为造势而拖长。
```

#### 1c. 修改字数要求（L59）
```
- 每章字数控制在4000-6000字，低于4000字不合格，篇幅与目标总字数相匹配；
```

---

### 修改2：writer_agent.py — _build_writing_context 默认值

**文件**：`d:\xiaoshuo\app\agents\writer_agent.py`
**位置**：L201-211 `_build_writing_context` 函数

当 `narrative_pov` 和 `writing_style` 为空时补默认值，确保LLM始终有POV指令：

```python
writing_style = state.get("writing_style", "") or "直白、紧凑、重心理与动作"
narrative_pov = state.get("narrative_pov", "") or "第三人称"
target_word_count = state.get("target_word_count", 0)
metadata_lines = []
metadata_lines.append(f"写作方式：{writing_style}")
metadata_lines.append(f"叙事人称：{narrative_pov}")
if target_word_count:
    metadata_lines.append(f"目标总字数：{target_word_count} 字")
metadata_lines.append(f"本章目标字数：4000-6000字")
metadata_section = "\n【写作元数据】\n" + "\n".join(metadata_lines)
```

注意：移除 `if writing_style:` 和 `if narrative_pov:` 的条件判断，确保始终注入。

---

### 修改3：writer_agent.py — write_chapter / write_chapter_stream 用户消息强化

**文件**：`d:\xiaoshuo\app\agents\writer_agent.py`
**位置**：L224-241（write_chapter）和 L260-277（write_chapter_stream）

将 L241/L277 的模糊指令：
```
请严格遵循上述写作方式与叙事人称行文，并控制每章篇幅与目标总字数相匹配。请开始写作。
```
改为明确的硬约束：
```
请严格遵循上述写作方式与叙事人称行文。

【字数硬约束】本章目标字数4000-6000字，低于4000字不合格。
【视角硬约束】从主角视角出发，必须描绘主角在当前场景下的心理活动与情绪反应（害怕、意外、陌生、愤怒、期待等），写出情绪的具体表现而非概述。
【文风硬约束】严禁"像...""如同...""仿佛..."等明喻句式，严禁无意义修饰句，行文简单明了，聚焦核心剧情与人物，减少不必要的环境描写。

请开始写作。
```

---

### 修改4：novel_service.py — create_novel 时补默认值

**文件**：`d:\xiaoshuo\app\services\novel_service.py`
**位置**：L20-44 `create_novel` 函数

在创建小说时，当 `narrative_pov` 和 `writing_style` 为空时补默认值，从源头杜绝空值：

```python
novel = Novel(
    title=data.title,
    genre=data.genre,
    description=data.description,
    length_type=data.length_type or "short",
    writing_style=data.writing_style or "直白、紧凑、重心理与动作",
    target_word_count=data.target_word_count,
    narrative_pov=data.narrative_pov or "第三人称",
    ...
)
```

---

### 修改5：reader 智能体 — 强化反比喻检查

#### 5a. character_reader.py（L21）
**文件**：`d:\xiaoshuo\app\agents\readers\character_reader.py`

在【审查维度】第6项"文笔与AI腔"中追加：
```
"像...""如同...""仿佛..."等明喻句式滥用（每个比喻都该标记，超过2处即为滥用）、无意义修饰句堆砌（纯装饰零信息量的句子）、过多环境描写喧宾夺主（环境描写篇幅超过剧情和人物描写）。
```

在【严重程度判定】中追加：
```
- "像..."明喻句式超过3处、或无意义修饰句超过3处，统一记为 medium。
```

#### 5b. polish_reader.py（L23-24, L60）
**文件**：`d:\xiaoshuo\app\agents\readers\polish_reader.py`

在 L23"空洞华丽修辞"条目后追加：
```
• "像..."明喻句式：严禁"像...""如同...""仿佛..."等一切明喻——无论用于环境、心理还是动作描写，一律改为直白陈述，不用比喻绕弯；
• 无意义修饰句：严禁纯装饰、零信息量的修饰性句子（如"月光洒落，给大地披上银纱"），每个句子必须推动剧情或揭示人物；
```

在 L60 Constraints 第2项中同步追加上述两条。

#### 5c. plot_reader.py — 新增节奏审查维度
**文件**：`d:\xiaoshuo\app\agents\readers\plot_reader.py`

在【审查维度】第2项"节奏控制"中追加：
```
是否存在过多环境描写、比喻修辞堆砌导致节奏拖沓、读者疲劳；是否偏离核心剧情做不必要的铺陈。
```

---

### 修改6（可选）：前端旧表单修复

**文件**：`d:\xiaoshuo\static\js\app.js` L95-98

旧快速创建表单不收集 `target_word_count`、`writing_style`、`narrative_pov`。两个方案：
- **方案A（推荐）**：在旧表单提交时补默认值（`target_word_count: 0, writing_style: "直白紧凑", narrative_pov: "第三人称"`），并在创建后提示用户通过向导完善设定
- **方案B**：移除旧表单，统一引导用户使用向导创建

此修改优先级较低，因为修改4已在后端补默认值。但前端补默认值可以避免 `target_word_count=0` 的情况。

---

## 假设与决策

1. **字数目标**：4000-6000字（用户确认），在系统提示词和用户消息中双重写入
2. **心理描写**：根据情节类型调整侧重，但每章都必须有（用户确认"根据情节类型决定"但额外说明"内容上要加上各种心理活动"）
3. **空字段处理**：写作时补默认值 + 创建时强制默认（用户确认"两者都做"）
4. **比喻限制**：基本禁止"像..."明喻句式，用户明确说"不要用比喻或者别的什么修饰语句"
5. **写作风格默认值**：`"直白、紧凑、重心理与动作"` — 体现用户"简单明了"的要求
6. **叙事人称默认值**：`"第三人称"` — 与现有 `_parse_expand_response` L235 的回退逻辑一致
7. **reader 智能体**：三个 reader 都需要更新，确保反比喻规则在审查和润色环节也生效

## 验证步骤

1. **语法检查**：对所有修改的 .py 文件运行 `d:\xiaoshuo\venv\Scripts\python.exe -m py_compile <file>`
2. **重启服务器**：确保 `--reload` 生效，或手动重启
3. **功能验证**：
   - 重新生成一章，检查字数是否在4000-6000范围内
   - 检查输出是否包含主角心理描写
   - 检查是否还有"像..."明喻句式
   - 检查是否还有无意义修饰句
4. **空字段验证**：对 novel ID=5（narrative_pov/writing_style 为空），确认写作上下文是否注入了默认值
