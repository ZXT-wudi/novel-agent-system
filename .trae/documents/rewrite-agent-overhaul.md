# AI重写功能大修方案

## 一、概述

将"写作台"的"AI重写"功能从当前简陋的实现，升级为与作者智能体（writer_agent）对齐的智能体范式：复用 WRITER_SYSTEM_PROMPT 的文风硬约束、复用 `_build_writing_context` 的富上下文构建，并增加"AI自动分析侧重 → 2版本并行流式输出 → 用户择优采纳"的多版本对比机制。

### 已确认的设计决策（来自用户问答）
| 维度 | 决策 |
|------|------|
| 智能体范式 | 对齐作者智能体（writer_agent）——复用其文风硬约束与上下文构建 |
| 输出方式 | 多版本并列对比——AI生成2个不同侧重版本，用户择优 |
| 重写粒度 | 两者兼顾——段落级（短文本）与整章级（长文本）均支持 |
| 版本数量 | 2个版本 |
| 侧重生成 | AI自动分析——根据原文+修改方向自动生成2个不同侧重标签 |
| 流式方式 | 并行流式——2版本同时流式输出，并列展示 |

---

## 二、现状分析

### 当前实现的问题

**`app/services/rewrite_service.py`**（132行）：
1. **提示词过于简陋**：仅6行系统提示词（"你是一位小说修订专家...要求：1.保持与上下文衔接 2.遵循修改方向 3.保持人物性格 4.保持文风统一 5.只输出重写后内容"），完全没有 writer_agent 的文风硬约束（禁破折号/禁明喻/禁析因句/禁AI腔等），重写结果容易带AI腔。
2. **上下文构建极其单薄**：仅用 `chapter_context[:2000]` + `outline_context[:1000]` + RAG（user_preferences/world_knowledge各n=3），完全缺失：前文完整正文、语义摘要、角色设定、世界观元素、角色心理推演、写作方式/人称元数据。
3. **无智能体范式**：没有模块级 SYSTEM_PROMPT 常量，没有 helper 函数拆分，只是 service 层的直写函数。
4. **单版本输出**：只生成一个结果，用户没有选择余地。
5. **参数偏低**：temp=0.7（writer_agent用0.8）、max_tokens=4096（writer_agent用16384），整章重写会被截断。
6. **无chapter_number关联**：前端发送的是 `chapter_context`（截取的片段）和 `outline_context`（JSON.stringify的大纲片段），后端无法构建完整的 NovelState。

### 目标范式（`app/agents/writer_agent.py`）
- `WRITER_SYSTEM_PROMPT`（L12-65）：~50行，7大节，尤其【文风硬约束】极为严格
- `_build_writing_context(state: NovelState)`（L113-222）：返回 `(context_text, outline_item, metadata_section)`，构建大纲全览、前文完整正文、语义摘要、RAG、知识库、用户偏好、角色设定、角色关系、世界观元素、角色心理推演、写作方式/人称元数据
- `write_chapter_stream(state)`（L266-300）：temp=0.8, max_tokens=16384

### 关键依赖确认
- `appState.currentChapter`（app.js L4）：前端已有当前章节号，可传给后端
- `_build_chapter_state(db, novel_id, chapter_number)`（chapter_service.py L22）：可从DB构建完整 NovelState
- `_build_writing_context(state)`（writer_agent.py L113）：可从 NovelState 构建富上下文
- `get_db`（rag.py L4）：已导入，endpoint 可直接添加 `db` 依赖

---

## 三、改动清单

### 3.1 新建 `app/agents/rewrite_agent.py`

重写智能体，对齐 writer_agent 范式，支持2版本并行流式输出。

#### 文件结构
```python
from app.llm.siliconflow import get_client, LLMError
from app.agents.state import NovelState
from app.agents.writer_agent import _build_writing_context
import json
import asyncio
import logging

logger = logging.getLogger(__name__)
llm_client = get_client("author")

# 模块级常量
REWRITE_SYSTEM_PROMPT = """..."""   # 见下文设计
ANALYZE_FOCUS_PROMPT = """..."""    # 见下文设计

async def _generate_focus_labels(original_text: str, instruction: str) -> list[dict]:
    """调用LLM分析原文+修改方向，生成2个不同侧重标签"""

def _build_rewrite_user_content(state, original_text, instruction, focus, context_text, metadata_section) -> str:
    """构建单版本重写的user消息内容"""

async def _stream_single_version(state, original_text, instruction, focus, version_idx):
    """流式输出单个版本的重写内容"""

async def rewrite_multi_stream(state: NovelState, original_text: str, instruction: str):
    """编排2版本并行流式输出，交替yield NDJSON行"""
```

#### REWRITE_SYSTEM_PROMPT 设计

继承 WRITER_SYSTEM_PROMPT 的【文风硬约束】（逐字复用——这是最核心的约束），适配【角色与设定准则】【写作重点】【写作技巧】为重写场景，新增【重写准则】和调整【输出要求】：

```
你是一位擅长心理描写的小说修订专家，具备深厚的文学功底和敏锐的情感洞察力，能够根据用户的修改方向，在保持原文核心情节与人物设定的前提下重写一段内容。

【重写准则】
- 严格遵循用户的修改方向，但改写须自然落地，不得生硬堆砌修改痕迹；
- 保持原文的核心情节走向、关键事件和人物关系不变，只调整写法、氛围、节奏或细节；
- 严格忠于上下文中已提供的角色设定与世界观元素，不得凭空捏造未设定的关键背景事实（身世、关系、设定）；
- 揣摩角色的深层动机——核心恐惧、内心渴望、说话习惯、身体语言与思维模式，一切推断须与既定人设自洽；
- 重写后的内容须与前后文无缝衔接，语气、人称、时态与节奏自然过渡。

【写作重点 · 心理与动作为核心】
- 心理活动是每段必须项：角色在当前场景下的情绪反应（害怕、意外、陌生、愤怒、期待、困惑等）必须具体可感地写出来，不是概述"他感到害怕"，而是写出害怕的具体表现——身体反应、思维碎片、本能冲动；
- 动作描写与心理描写交替：打斗/冲突场景侧重动作节奏与紧张感，但穿插角色内心判断与情绪；日常/情感场景侧重心理与对话，动作作为辅助；
- 环境描写仅作背景：一两笔点明场景即可，不得大段铺陈环境，环境细节服务于角色内心而非独立成景；
- 对话推动情节：每个角色有独特说话风格，潜台词丰富，不写无效寒暄。

【文风硬约束 · 必须遵守】
- 正文严禁出现破折号"——"这个符号本身，无论想用它表示心理状态、解释说明、语气转折、补充动作、情绪延伸还是任何其他用途，一律不许出现"——"。该独立成句就独立成句，该用逗号/句号断开就用逗号/句号，不靠破折号挂尾巴或做文章；
- 严禁一切"不是……"析因/翻转式句式——包括"不是……而是……""不是因为……""不是……，而是……"等一切用"不是"去拆解因果、做分析腔陈述的用法，直接把人和事直白写出来；
- 严禁空洞华丽的比喻与通感堆砌——如"瞳孔像是淬了火的灰玻璃""目光疯狂闪烁""心跳成了一串失序的鼓点"这类故作高深、华而不实的生造意象，看不懂、读不顺，纯属炫技，一律不用；描写要直白可感，用准确的动词和名词落地，不靠生造意象制造"高级感"；
- 严禁"像...""如同...""仿佛...""好似...""犹如..."等一切明喻句式——不得用"像"字做环境描写或心理描写，直接写出事物本身的状态和角色的情绪，不用比喻绕弯；
- 严禁无意义的修饰性句子——每个句子必须推动剧情、揭示人物或传递信息，不得写"月光洒落在地上，给大地披上一层银纱"这类纯装饰、零信息量的句子；
- 行文简单明了，用准确的动词和名词直白落地，不靠比喻和修饰句制造"高级感"；
- 聚焦核心剧情与人物，减少不必要的环境铺垫和修饰性描写，读者要的是故事和人物，不是散文；
- 句子要短、要干脆，一个句子只说一件事，该断就断，不为造势而拖长；
- 严禁单句堆砌修辞——一句话只把一件事说清楚，不得在同一句里叠摞比喻、通感、拟人、排比等多种修辞手法；一个比喻用完就停，不要在尾巴上再挂一个；
- 严禁"前半句抛出某个东西、后半句解释这个东西"的解释式句式——如"他眼中闪过一丝光，那是一种前所未有的坚定""她嘴角微微上扬，那是一个只有她自己才懂的笑"这类套路写法，直接把意思写进前半句，不要拆成两句做注解；
- 严禁排比堆砌、为对仗而对仗的机械句式；
- 严禁"综上所述、由此可见、不难发现、值得一提的是"等AI过渡腔与套话；
- 写小说像人带着思考在写：行文非连续、可以跳跃，用直白描述落地，不要写成因果分明、层层推导的分析文章；
- 句子要自然落地，短句碎句皆是节奏，不为刻意造势而堆砌。

【写作技巧】
- 每段不超过80字，段落之间留白适当，保持阅读流畅；
- 用具体细节替代抽象描述，通过小动作展现大情绪；
- 环境细节服务于氛围营造，伏笔设置自然不突兀；
- 文笔流畅，描写生动，对话自然，长短句交错，让文字有呼吸感与节奏感。

【输出要求】
- 严格依据修改方向与本版本侧重重写原文，输出长度应与原文相当（段落重写约同等长度，整章重写4000-6000字）；
- 只输出重写后的正文内容，不要输出标题、大纲、解释或任何元信息。"""
```

#### ANALYZE_FOCUS_PROMPT 设计

```
你是小说改写策略分析专家。用户会给你一段原文和修改方向，你需要分析原文特征与修改方向，给出2个不同侧重的改写策略。

【分析准则】
- 两个版本的侧重必须明显不同，从不同维度切入改写；
- 侧重维度可以是：节奏快慢、情绪浓淡、动作与心理比例、对话与描写比例、氛围基调、视角聚焦等；
- 每个版本给出一个简短标签（2-6字）和一段具体策略描述（20-50字）；
- 策略描述要具体可执行，不要空泛。

输出格式（严格JSON数组）：
[
  {
    "label": "版本标签",
    "approach": "具体策略描述"
  },
  {
    "label": "版本标签",
    "approach": "具体策略描述"
  }
]

只输出JSON数组，不要输出其他内容。"""
```

#### `_generate_focus_labels` 实现逻辑
```python
async def _generate_focus_labels(original_text, instruction):
    messages = [
        {"role": "system", "content": ANALYZE_FOCUS_PROMPT},
        {"role": "user", "content": f"""【原文（前200字）】
{original_text[:200]}

【修改方向】
{instruction}

请分析原文与修改方向，给出2个不同侧重版本的改写策略。"""},
    ]
    response = await llm_client.chat(messages, temperature=0.7, max_tokens=512)
    try:
        result = json.loads(response)
        if isinstance(result, list) and len(result) >= 2:
            valid = []
            for item in result[:2]:
                if isinstance(item, dict) and "label" in item and "approach" in item:
                    valid.append(item)
            if len(valid) >= 2:
                return valid[:2]
    except (json.JSONDecodeError, TypeError):
        pass
    # 兜底：2个通用侧重
    return [
        {"label": "稳健版", "approach": "忠实原文风格，适度调整细节与节奏"},
        {"label": "大胆版", "approach": "更大胆地改写，强化情绪张力与冲突感"},
    ]
```

#### `_stream_single_version` 实现逻辑
```python
async def _stream_single_version(state, original_text, instruction, focus):
    context_text, outline_item, metadata_section = _build_writing_context(state)

    user_content = f"""请重写以下内容。

【原文】
{original_text}

【修改方向】
{instruction}

【本版本侧重】
{focus.get("label", "")}：{focus.get("approach", "")}
{metadata_section}

前文上下文：
{context_text}

请严格遵循上述写作方式与叙事人称行文，依据修改方向与本版本侧重进行重写。
输出长度应与原文相当，只输出重写后的内容。"""

    messages = [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    async for chunk in llm_client.chat_stream(messages, temperature=0.8, max_tokens=16384):
        yield chunk
```

#### `rewrite_multi_stream` 并行编排逻辑
```python
async def rewrite_multi_stream(state, original_text, instruction):
    # 步骤1：生成2个侧重标签
    try:
        focus_labels = await _generate_focus_labels(original_text, instruction)
    except Exception as e:
        logger.warning(f"侧重分析失败，使用兜底标签: {e}")
        focus_labels = [
            {"label": "稳健版", "approach": "忠实原文风格，适度调整"},
            {"label": "大胆版", "approach": "更大胆改写，强化情绪张力"},
        ]

    # 先yield所有侧重标签
    for i, fl in enumerate(focus_labels):
        yield {"type": "focus", "version": i, "label": fl.get("label", ""), "approach": fl.get("approach", "")}

    # 步骤2：用asyncio.Queue做并行流式交错
    queue = asyncio.Queue()
    num_versions = len(focus_labels)

    async def producer(version_idx, focus):
        try:
            async for chunk in _stream_single_version(state, original_text, instruction, focus):
                await queue.put({"type": "content", "version": version_idx, "text": chunk})
            await queue.put({"type": "version_done", "version": version_idx})
        except Exception as e:
            await queue.put({"type": "version_error", "version": version_idx, "error": str(e)})
        finally:
            await queue.put(None)  # 哨兵

    tasks = [
        asyncio.create_task(producer(i, focus_labels[i]))
        for i in range(num_versions)
    ]

    done_sentinels = 0
    while done_sentinels < num_versions:
        item = await queue.get()
        if item is None:
            done_sentinels += 1
            continue
        yield item

    yield {"type": "complete"}
    await asyncio.gather(*tasks, return_exceptions=True)
```

### 3.2 修改 `app/api/rag.py`

**当前**（L67-101）：`rewrite_content` endpoint 无 `db` 依赖，调用 `rewrite_section_stream`。

**改动**：
1. 修改 import（L8）：`from app.services.rewrite_service import rewrite_section, rewrite_section_stream` → `from app.agents.rewrite_agent import rewrite_multi_stream` + `from app.services.chapter_service import _build_chapter_state`
2. endpoint 签名添加 `db: AsyncSession = Depends(get_db)`
3. 从 request data 中提取 `chapter_number`
4. 调用 `_build_chapter_state(db, novel_id, chapter_number)` 构建 NovelState
5. 调用 `rewrite_multi_stream(state, original_text, instruction)` 获取多版本流
6. stream_generator 中将 dict yield 为 NDJSON 行

```python
@router.post("/{novel_id}/rewrite")
async def rewrite_content(novel_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    original_text = data.get("original_text", "")
    instruction = data.get("instruction", "")
    chapter_number = data.get("chapter_number")

    if not original_text:
        raise HTTPException(status_code=400, detail="请提供需要重写的原文")
    if not instruction:
        raise HTTPException(status_code=400, detail="请提供修改方向")

    # 构建完整NovelState（与作者智能体相同的上下文）
    state = {}
    if chapter_number:
        try:
            state = await _build_chapter_state(db, novel_id, int(chapter_number))
        except Exception as e:
            logger.warning(f"构建章节状态失败: {e}")

    async def stream_generator():
        try:
            async for item in rewrite_multi_stream(state, original_text, instruction):
                yield json.dumps(item, ensure_ascii=False) + "\n"
        except LLMError as e:
            yield json.dumps({"type": "error", "error": f"AI服务错误: {e.message}"}, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"重写失败: {str(e)}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
```

> **注**：需在 rag.py 顶部添加 `import logging; logger = logging.getLogger(__name__)`（当前无 logger）。

### 3.3 修改 `static/js/app.js`（L689-842）

#### 全局状态变更
```javascript
let rewritePanelOpen = false;
let rewriteResults = ["", ""];      // 2个版本的结果文本
let rewriteLabels = ["", ""];       // 2个版本的侧重标签
```

#### `showRewriteModal()` 变更
- 初始化 `rewriteResults = ["", ""]`、`rewriteLabels = ["", ""]`
- 结果区域改为2列容器结构：

```html
<div id="rewrite-result-area" style="display:none;margin-top:12px;">
    <div class="rewrite-versions">
        <div class="rewrite-version-card" id="rewrite-version-0">
            <div class="rewrite-version-label" id="rewrite-label-0">版本A</div>
            <div class="rewrite-result" id="rewrite-result-0"></div>
            <div class="rewrite-actions">
                <button class="btn btn-success" onclick="acceptRewrite(0)">采纳</button>
            </div>
        </div>
        <div class="rewrite-version-card" id="rewrite-version-1">
            <div class="rewrite-version-label" id="rewrite-label-1">版本B</div>
            <div class="rewrite-result" id="rewrite-result-1"></div>
            <div class="rewrite-actions">
                <button class="btn btn-success" onclick="acceptRewrite(1)">采纳</button>
            </div>
        </div>
    </div>
    <div style="margin-top:8px;">
        <button class="btn btn-outline" onclick="retryRewrite()">重新生成</button>
        <button class="btn btn-danger" onclick="discardRewrite()">放弃</button>
    </div>
</div>
```

#### `doRewrite()` 变更
- 发送请求中添加 `chapter_number: appState.currentChapter`
- 删除 `chapter_context` 和 `outline_context`（后端从 NovelState 构建）
- NDJSON 解析逻辑改为多版本：

```javascript
async function doRewrite() {
    const novelId = getSelectedNovelId();
    const originalText = document.getElementById("rewrite-original").value.trim();
    const instruction = document.getElementById("rewrite-instruction").value.trim();

    if (!originalText) { alert("请输入需要重写的内容"); return; }
    if (!instruction) { alert("请输入修改方向"); return; }

    const btn = document.getElementById("btn-do-rewrite");
    btn.disabled = true;
    btn.textContent = "正在重写...";

    const resultArea = document.getElementById("rewrite-result-area");
    resultArea.style.display = "block";
    rewriteResults = ["", ""];
    rewriteLabels = ["", ""];

    // 清空2个结果区
    for (let i = 0; i < 2; i++) {
        const el = document.getElementById(`rewrite-result-${i}`);
        if (el) { el.textContent = ""; el.style.borderColor = "var(--accent)"; }
        const labelEl = document.getElementById(`rewrite-label-${i}`);
        if (labelEl) labelEl.textContent = `版本${i === 0 ? "A" : "B"}`;
    }

    try {
        const response = await fetch(`/api/novels/${novelId}/rewrite`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                original_text: originalText,
                instruction: instruction,
                chapter_number: appState.currentChapter,
                stream: true,
            }),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: "请求失败" }));
            throw new Error(err.detail || "请求失败");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);
                    if (data.type === "focus") {
                        rewriteLabels[data.version] = data.label;
                        const labelEl = document.getElementById(`rewrite-label-${data.version}`);
                        if (labelEl) labelEl.textContent = `${data.label}：${data.approach}`;
                    } else if (data.type === "content") {
                        rewriteResults[data.version] += data.text;
                        const el = document.getElementById(`rewrite-result-${data.version}`);
                        if (el) {
                            el.textContent = rewriteResults[data.version];
                            el.scrollTop = el.scrollHeight;
                        }
                    } else if (data.type === "version_done") {
                        const el = document.getElementById(`rewrite-result-${data.version}`);
                        if (el) el.style.borderColor = "var(--success)";
                    } else if (data.type === "version_error") {
                        const el = document.getElementById(`rewrite-result-${data.version}`);
                        if (el) {
                            el.textContent = "生成失败: " + data.error;
                            el.style.borderColor = "var(--danger)";
                        }
                    } else if (data.type === "error") {
                        throw new Error(data.error);
                    }
                } catch (e) {
                    if (e.message && !e.message.includes("JSON")) throw e;
                }
            }
        }
    } catch (e) {
        alert("重写失败: " + e.message);
    }

    btn.disabled = false;
    btn.textContent = "开始重写";
}
```

#### `acceptRewrite(version)` 变更
```javascript
function acceptRewrite(version) {
    const text = rewriteResults[version];
    if (!text) return;

    if (isEditMode) {
        const editor = document.getElementById("chapter-editor");
        const original = document.getElementById("rewrite-original").value.trim();
        editor.value = editor.value.replace(original, text);
        currentChapterContent = editor.value;
        editor.dispatchEvent(new Event("input"));
    } else {
        const original = document.getElementById("rewrite-original").value.trim();
        currentChapterContent = currentChapterContent.replace(original, text);
        const textEl = document.getElementById("chapter-text");
        textEl.textContent = currentChapterContent;
    }

    contentModified = true;
    closeRewritePanel();
    updateStatusBar(`已采纳「${rewriteLabels[version] || "版本" + (version + 1)}」的重写内容`);
}
```

#### `retryRewrite()` / `discardRewrite()` 保持简单
```javascript
function retryRewrite() {
    document.getElementById("rewrite-result-area").style.display = "none";
    doRewrite();
}

function discardRewrite() {
    document.getElementById("rewrite-result-area").style.display = "none";
    rewriteResults = ["", ""];
    rewriteLabels = ["", ""];
}
```

### 3.4 修改 `static/css/style.css`（L1028-1097）

- `.rewrite-panel` width: `420px` → `760px`（容纳2列）
- 新增 `.rewrite-versions`：flex 2列布局
- 新增 `.rewrite-version-card`：单列卡片
- 新增 `.rewrite-version-label`：标签头部
- `.rewrite-result` 的 `max-height` 增加到 `400px`（整章重写需要更大空间）

```css
.rewrite-panel {
    /* ...其他不变... */
    width: 760px;
}

.rewrite-versions {
    display: flex;
    gap: 12px;
    margin-top: 8px;
}

.rewrite-version-card {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.rewrite-version-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
    padding: 4px 8px;
    background: var(--bg-card);
    border-radius: var(--radius-sm);
    border-left: 3px solid var(--accent);
}

.rewrite-result {
    /* ...其他不变... */
    max-height: 400px;
}
```

### 3.5 修改 `static/index.html`（L174）

- app.js 版本号 `?v=20260825a` → `?v=20260826a`（强制刷新缓存）

### 3.6 废弃 `app/services/rewrite_service.py`

- 不再被任何模块 import（rag.py 改为从 rewrite_agent 导入）
- 文件保留但不再使用（避免删除引起潜在 git 冲突，后续可清理）

---

## 四、多版本 NDJSON 流式协议

### 时序
```
1. {"type": "focus", "version": 0, "label": "动作流", "approach": "加快节奏..."}
2. {"type": "focus", "version": 1, "label": "心理流", "approach": "强化内心压迫感..."}
3. {"type": "content", "version": 0, "text": "他猛地转身"}          ← 版本0 chunk
4. {"type": "content", "version": 1, "text": "手心的汗"}            ← 版本1 chunk
5. {"type": "content", "version": 0, "text": ",拳头攥紧"}
6. ...（交错yield，取决于哪个流先产出）
7. {"type": "version_done", "version": 0}
8. {"type": "version_done", "version": 1}
9. {"type": "complete"}
```

### 前端处理
- `focus` 事件 → 设置标签，渲染版本卡片头部
- `content` 事件 → 按 `version` 索引追加文本到对应结果区
- `version_done` 事件 → 该版本边框变绿，表示完成
- `version_error` 事件 → 该版本显示错误
- `complete` 事件 → 全部完成

---

## 五、边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 侧重分析LLM调用失败 | catch后用兜底标签（"稳健版"/"大胆版"），不中断流程 |
| 侧重分析返回非JSON/格式不对 | try-except，用兜底标签 |
| 某个版本流式生成失败 | producer catch后 put `version_error`，另一个版本继续 |
| 无 chapter_number（前端未传） | state为空dict，`_build_writing_context` 返回空上下文，LLM仅凭原文+修改方向重写（降级模式） |
| Novel构建失败（novel_id不存在） | catch后 state={}，同上降级 |
| original_text 极长（整章5000+字） | max_tokens=16384，LLM自然停止 |
| original_text 极短（段落200字） | max_tokens=16384（不截断，LLM按prompt中"输出长度应与原文相当"约束自然停止） |
| LLMError（API限流/宕机） | stream_generator catch后 yield error事件 |
| 前端用户未选章节 | showRewriteModal 中 `appState.currentChapter` 为null → alert提示 |

---

## 六、验证步骤

### 后端验证
1. 语法检查：`d:\xiaoshuo\venv\Scripts\python.exe -m py_compile app\agents\rewrite_agent.py`
2. 语法检查：`d:\xiaoshuo\venv\Scripts\python.exe -m py_compile app\api\rag.py`
3. 导入测试：确认 `from app.agents.rewrite_agent import rewrite_multi_stream` 无报错
4. 启动服务器后，用 curl 测试 NDJSON 输出格式：
   ```bash
   curl -N -X POST http://localhost:8011/api/novels/{novel_id}/rewrite \
     -H "Content-Type: application/json" \
     -d '{"original_text":"测试段落","instruction":"增加紧张感","chapter_number":1,"stream":true}'
   ```
   预期输出：先2行 `focus` 事件，然后交错 `content` 事件，最后 `version_done` × 2 + `complete`

### 前端验证
1. `node --check static/js/app.js` 语法检查
2. 浏览器硬刷新（Ctrl+Shift+R），打开AI重写面板
3. 输入原文+修改方向，点击"开始重写"
4. 验证：2列结果卡片同时流式输出，各有侧重标签
5. 验证：点击某个版本的"采纳"，原文被替换为该版本内容
6. 验证：`contentModified = true` 后切换章节会提示未保存

---

## 七、假设与决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 复用 writer_agent 的 `_build_writing_context` 而非重写 | DRY原则，保证重写与生成使用完全相同的上下文构建逻辑 |
| 2 | 从 chapter_service 导入 `_build_chapter_state`（私有函数） | 代码库已有跨模块私有导入先例（chapter_service 导入 writer_agent 的私有函数）；避免重复400+行状态构建代码 |
| 3 | API层构建 NovelState 传给 agent | agent 不直接依赖 DB/Service 层，职责清晰 |
| 4 | max_tokens=16384 对所有场景 | 简化逻辑，LLM按prompt约束自然停止；段落级不会浪费太多token |
| 5 | asyncio.Queue 做并行交错 | Python原生asyncio方案，无额外依赖；2个producer task各自put chunk，main consumer交替yield |
| 6 | 兜底侧重标签 | 侧重分析是LLM调用，可能失败/格式错，必须有降级保证 |
| 7 | 废弃而非删除 rewrite_service.py | 避免git冲突，后续可统一清理 |
| 8 | 前端始终传 chapter_number | `appState.currentChapter` 始终可用，让后端能构建完整上下文 |
