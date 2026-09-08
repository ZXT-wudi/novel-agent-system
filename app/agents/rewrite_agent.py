from app.llm.siliconflow import get_client, LLMError
from app.agents.state import NovelState
from app.agents.writer_agent import _build_writing_context
import json
import asyncio
import logging

logger = logging.getLogger(__name__)
llm_client = get_client("author")


REWRITE_SYSTEM_PROMPT = """你是一位擅长心理描写的小说修订专家，具备深厚的文学功底和敏锐的情感洞察力，能够根据用户的修改方向，在保持原文核心情节与人物设定的前提下重写一段内容。

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


ANALYZE_FOCUS_PROMPT = """你是小说改写策略分析专家。用户会给你一段原文和修改方向，你需要分析原文特征与修改方向，给出2个不同侧重的改写策略。

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

FALLBACK_FOCUS = [
    {"label": "稳健版", "approach": "忠实原文风格，适度调整细节与节奏"},
    {"label": "大胆版", "approach": "更大胆地改写，强化情绪张力与冲突感"},
]


async def _generate_focus_labels(original_text: str, instruction: str) -> list[dict]:
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
                    valid.append({"label": str(item["label"]), "approach": str(item["approach"])})
            if len(valid) >= 2:
                return valid[:2]
    except (json.JSONDecodeError, TypeError):
        pass

    return FALLBACK_FOCUS[:]


async def _stream_single_version(state: NovelState, original_text: str, instruction: str, focus: dict):
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


async def rewrite_multi_stream(state: NovelState, original_text: str, instruction: str):
    try:
        focus_labels = await _generate_focus_labels(original_text, instruction)
    except Exception as e:
        logger.warning(f"侧重分析失败，使用兜底标签: {e}")
        focus_labels = FALLBACK_FOCUS[:]

    for i, fl in enumerate(focus_labels):
        yield {"type": "focus", "version": i, "label": fl.get("label", ""), "approach": fl.get("approach", "")}

    queue: asyncio.Queue = asyncio.Queue()
    num_versions = len(focus_labels)

    async def producer(version_idx: int, focus: dict):
        try:
            async for chunk in _stream_single_version(state, original_text, instruction, focus):
                await queue.put({"type": "content", "version": version_idx, "text": chunk})
            await queue.put({"type": "version_done", "version": version_idx})
        except Exception as e:
            await queue.put({"type": "version_error", "version": version_idx, "error": str(e)})
        finally:
            await queue.put(None)

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
