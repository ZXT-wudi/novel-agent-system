from app.llm.siliconflow import LLMError, get_client

llm_client = get_client("author")
from app.agents.state import NovelState
from app.agents.character_agent import curate_relevant_settings
import json
import logging

logger = logging.getLogger(__name__)


WRITER_SYSTEM_PROMPT = """你是一位擅长心理描写的小说家，具备深厚的文学功底和敏锐的情感洞察力，擅长根据大纲与上下文撰写引人入胜的章节。

【角色与设定准则】
- 严格忠于上下文中已提供的角色设定、角色关系与世界观元素，不得凭空捏造未设定的关键背景事实（身世、关系、设定）；
- 揣摩角色的深层动机——核心恐惧、内心渴望、说话习惯、身体语言与思维模式，一切推断须与既定人设自洽；
- 涉及的重要配角同样需把握其行为特征与和主角的关系动态；
- 所有行为必须符合角色性格，冲突源于性格差异，避免为情节强行改变人设；角色成长轨迹要有逻辑性；
- 注意人物发展弧线与前后章节的衔接呼应。

【情绪节拍】
- 依据本章大纲的情节走向，先确定一个目标情绪（如悬疑紧张、温暖感动、愤怒不甘、好奇期待、忧伤惆怅）与强度（1-10级）；
- 规划情绪强度曲线：起→中→落，标注各级大致强度，并在合适位置安排一次情绪转折；
- 场景氛围与节奏快慢均服务于这条情绪曲线，张弛有度。

【叙事节奏 · 激情与平淡的交替】
- 全书和每卷都需要"激情点"与"平淡点"的交替，不能从头到尾都高潮，也不能一直平淡；
- "激情点"：高强度冲突、战斗、对峙、情感爆发、真相揭露等，节奏快、句子短、情绪烈；
- "平淡点"：日常过渡、内心反思、环境铺垫、人物互动的温情时刻等，节奏慢、句子长、情绪缓；
- 依据本章大纲的情节走向判断本章是"激情章"还是"平淡章"，或两者兼有（前平后激/前激后平）；
- 相邻章节之间也要注意节奏交替——前一章高潮后，本章可适当放缓做喘息；前一章铺垫后，本章可推向高潮；
- 参考上下文中"章节大纲全览"里前后章节的情节摘要，预判节奏走向，确保整卷有起伏、有呼吸感。

【写作重点 · 心理与动作为核心】
- 心理活动是每章必须项：主角在当前场景下的情绪反应（害怕、意外、陌生、愤怒、期待、困惑等）必须具体可感地写出来，不是概述"他感到害怕"，而是写出害怕的具体表现——身体反应、思维碎片、本能冲动；
- 动作描写与心理描写交替：打斗/冲突场景侧重动作节奏与紧张感，但穿插主角内心判断与情绪；日常/情感场景侧重心理与对话，动作作为辅助；
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
- 严格按照大纲的情节摘要和关键事件写作；
- 每章字数控制在4000-6000字，低于4000字不合格，篇幅与目标总字数相匹配；
- 直接输出章节正文内容，不要输出标题、大纲或其他任何元信息。"""


EVALUATE_SYSTEM_PROMPT = """你是一位资深小说作者，需要理性、公允地判断读者审查意见是否合理，并决定是否采纳修改。

【裁决准则】
- 以作品质量为唯一准绳，不盲目迎合审查者，也不固执己见；
- 区分"真问题"与"个人风格偏好"：人设崩塌、逻辑硬伤、情节断裂、动机缺失等真问题应接受；纯属风格偏好且原文无硬伤的，可拒绝；
- 正文出现破折号"——"符号、一切"不是……"析因/翻转句（含"不是……而是……""不是因为……"等）、排比堆砌、空洞华丽的修辞堆砌（如"瞳孔像是淬了火的灰玻璃"等故作高深的生造意象）、单句叠摞多种修辞、"前半句抛出东西后半句补解释"的解释式句式、"像...""如同...""仿佛..."等明喻句式、无意义的修饰性句子（纯装饰零信息量）等AI腔句式属于文本质量问题（非个人风格偏好），审查员指出后应予接受并改写；
- 接受的意见必须给出具体可执行的修改计划（改哪里、怎么改），而非空泛同意；
- 拒绝的意见必须说明正当理由，让用户能判断是否仍要强制修改；
- 避免为省事全部接受或全部拒绝，逐条独立判断。

对于每条审查意见，你需要：
1. 评估意见的合理性（合理/部分合理/不合理）
2. 如果合理或部分合理，给出具体修改计划
3. 如果不合理，说明拒绝理由

输出格式（严格JSON数组）：
[
  {
    "comment_id": "意见编号",
    "decision": "accept/reject",
    "reason": "判断理由",
    "revision_plan": "修改计划（如果接受）"
  }
]

只输出JSON数组，不要输出其他内容。"""


SUGGEST_SYSTEM_PROMPT = """你是小说续写助手，根据用户已写正文与大纲上下文，顺势续写一句简短的文字。

【续写准则】
- 严格承接用户结尾的语气、人称、时态与节奏，读起来像同一位作者顺手写下的下一句；
- 续写内容选最自然的一种——动作、神态、对白、心理、环境均可，哪种最能顺势接上就续哪种；
- 避免"综上所述""由此可见""不难发现"等AI过渡腔，续写即正文本身；
- 不替作者决定情节走向，只顺势续一句，把后续决定权留给作者；
- 不重复用户已写内容，不输出引号。

续写要求：
1. 约 15-25 字，只是一个短句或一个动作描写，不要整段
2. 自然衔接用户结尾，保持上下文连贯
3. 遵循本章大纲的情节走向与写作方式、叙事人称
4. 不要重复用户已写内容
5. 只输出续写的短句本身，不要输出标题、大纲、引号或任何解释"""


def _build_writing_context(state: NovelState) -> tuple[str, dict, str]:
    """返回 (context_text, outline_item, metadata_section)"""
    chapter_number = state.get("current_chapter_number", 1)
    outline = state.get("outline", [])
    previous_full = state.get("previous_chapters_full", [])
    previous_semantics = state.get("previous_semantics", [])
    rag_context = state.get("rag_context", "")
    user_preference = state.get("user_preference_summary", "")
    novel_genre = state.get("novel_genre", "")

    outline_item = {}
    for item in outline:
        if item.get("chapter_number") == chapter_number:
            outline_item = item
            break

    context_parts = []

    if outline:
        overview_lines = []
        for item in outline:
            num = item.get("chapter_number", "?")
            title = item.get("title", "")
            summary = item.get("plot_summary", "")
            marker = "▶" if num == chapter_number else " "
            overview_lines.append(f"{marker} 第{num}章「{title}」：{summary}")
        context_parts.append("=== 章节大纲全览（▶为当前章，参考前后章节确保连贯）===\n" + "\n".join(overview_lines))

    if previous_full:
        for i, ch_content in enumerate(previous_full):
            ch_num = chapter_number - len(previous_full) + i
            context_parts.append(f"=== 第{ch_num}章完整正文 ===\n{ch_content}")

    if previous_semantics:
        context_parts.append("=== 更早章节语义摘要 ===")
        for sem in previous_semantics:
            context_parts.append(f"第{sem.get('chapter_number', '?')}章摘要：{sem.get('summary', '')}")
            if sem.get("keywords"):
                context_parts.append(f"关键词：{', '.join(sem.get('keywords', []))}")

    if rag_context:
        context_parts.append(f"=== RAG检索参考 ===\n{rag_context}")

    kb_context = state.get("kb_context", "")
    if kb_context:
        kb_label = "原作知识库参考（同人创作必须严格遵循原作设定）" if novel_genre == "同人" else "知识库参考"
        context_parts.append(f"=== {kb_label} ===\n{kb_context}")

    ordinary_kb_context = state.get("ordinary_kb_context", "")
    if ordinary_kb_context:
        context_parts.append("=== 写作技法参考（可借鉴，非硬性设定） ===\n" + ordinary_kb_context)

    if user_preference:
        context_parts.append(f"=== 用户写作偏好 ===\n{user_preference}")

    story_knowledge = state.get("story_knowledge", {})
    if story_knowledge:
        rel = curate_relevant_settings(state)
        if rel["characters"]:
            char_text = "\n".join([f"- {c.get('name', '')}({c.get('role', '')}): {c.get('description', '')}" for c in rel["characters"]])
            context_parts.append(f"=== 本章相关角色设定 ===\n{char_text}")
        if rel["relations"]:
            rel_text = "\n".join([f"- {r.get('from', '')} -> {r.get('to', '')}({r.get('type', '')}): {r.get('description', '')}" for r in rel["relations"]])
            context_parts.append(f"=== 本章相关角色关系 ===\n{rel_text}")
        if rel["world_elements"]:
            elem_text = "\n".join([f"- [{e.get('category', '')}] {e.get('name', '')}: {e.get('description', '')}" for e in rel["world_elements"]])
            context_parts.append(f"=== 本章相关世界观元素 ===\n{elem_text}")

    character_psychology = state.get("character_psychology", "")
    if character_psychology:
        context_parts.append(f"=== 本章角色心理推演 ===\n{character_psychology}")

    if not (story_knowledge or {}).get("characters"):
        char_lines = []
        for c in ((state.get("full_outline") or {}).get("characters") or []):
            if isinstance(c, dict) and c.get("name"):
                char_lines.append(f"- {c.get('name', '')}({c.get('role', '')}): {c.get('profile', '')} 动机:{c.get('motivation', '')}")
        for c in (state.get("novel_characters") or []):
            if isinstance(c, dict) and c.get("name"):
                char_lines.append(f"- {c.get('name', '')}({c.get('role', '')}): {c.get('personality', '')} {c.get('background', '')}")
        if char_lines:
            context_parts.append("=== 角色设定 ===\n" + "\n".join(char_lines))

    if not (story_knowledge or {}).get("world_elements"):
        ws_lines = []
        wv = (state.get("full_outline") or {}).get("worldview", "")
        if wv:
            ws_lines.append(f"- [世界观] {wv}")
        nws = state.get("novel_world_settings") or {}
        if nws.get("era"):
            ws_lines.append(f"- [时代背景] {nws['era']}")
        if nws.get("location"):
            ws_lines.append(f"- [主要地点] {nws['location']}")
        if nws.get("rules"):
            ws_lines.append(f"- [世界规则] {nws['rules']}")
        if nws.get("key_elements"):
            ws_lines.append(f"- [关键元素] {', '.join(str(x) for x in nws['key_elements'])}")
        if ws_lines:
            context_parts.append("=== 世界观元素 ===\n" + "\n".join(ws_lines))

    context_text = "\n\n".join(context_parts) if context_parts else "这是第一章，没有前文上下文。"

    writing_style = state.get("writing_style", "") or "直白、紧凑、重心理与动作"
    narrative_pov = state.get("narrative_pov", "") or "第三人称"
    target_word_count = state.get("target_word_count", 0)
    metadata_lines = []
    metadata_lines.append(f"写作方式：{writing_style}")
    metadata_lines.append(f"叙事人称：{narrative_pov}")
    if target_word_count:
        metadata_lines.append(f"目标总字数：{target_word_count} 字")
    metadata_lines.append("本章目标字数：4000-6000字")
    metadata_section = "\n【写作元数据】\n" + "\n".join(metadata_lines)

    return context_text, outline_item, metadata_section


async def write_chapter(state: NovelState) -> NovelState:
    chapter_number = state.get("current_chapter_number", 1)

    context_text, outline_item, metadata_section = _build_writing_context(state)

    messages = [
        {"role": "system", "content": WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请撰写第{chapter_number}章。

本章大纲：
标题：{outline_item.get('title', '')}
情节摘要：{outline_item.get('plot_summary', '')}
关键事件：{', '.join(outline_item.get('key_events', []))}
涉及人物：{', '.join(outline_item.get('characters', []))}
场景地点：{outline_item.get('location', '')}
本章冲突：{outline_item.get('conflict', '')}
人物变化：{outline_item.get('character_changes', '')}
章末钩子：{outline_item.get('chapter_hook', '')}
备注：{outline_item.get('notes', '')}
{metadata_section}

前文上下文：
{context_text}

请严格遵循上述写作方式与叙事人称行文。

【字数硬约束】本章目标字数4000-6000字，低于4000字不合格。
【视角硬约束】从主角视角出发，必须描绘主角在当前场景下的心理活动与情绪反应（害怕、意外、陌生、愤怒、期待等），写出情绪的具体表现而非概述。
【文风硬约束】严禁"像...""如同...""仿佛..."等明喻句式，严禁无意义修饰句，行文简单明了，聚焦核心剧情与人物，减少不必要的环境描写。

请开始写作。"""},
    ]

    draft = await llm_client.chat(messages, temperature=0.8, max_tokens=16384)

    state["chapter_draft"] = draft
    state["chapter_title"] = outline_item.get("title", f"第{chapter_number}章")
    state["current_phase"] = "chapter_written"
    return state


async def write_chapter_stream(state: NovelState):
    chapter_number = state.get("current_chapter_number", 1)

    context_text, outline_item, metadata_section = _build_writing_context(state)

    messages = [
        {"role": "system", "content": WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请撰写第{chapter_number}章。

本章大纲：
标题：{outline_item.get('title', '')}
情节摘要：{outline_item.get('plot_summary', '')}
关键事件：{', '.join(outline_item.get('key_events', []))}
涉及人物：{', '.join(outline_item.get('characters', []))}
场景地点：{outline_item.get('location', '')}
本章冲突：{outline_item.get('conflict', '')}
人物变化：{outline_item.get('character_changes', '')}
章末钩子：{outline_item.get('chapter_hook', '')}
备注：{outline_item.get('notes', '')}
{metadata_section}

前文上下文：
{context_text}

请严格遵循上述写作方式与叙事人称行文。

【字数硬约束】本章目标字数4000-6000字，低于4000字不合格。
【视角硬约束】从主角视角出发，必须描绘主角在当前场景下的心理活动与情绪反应（害怕、意外、陌生、愤怒、期待等），写出情绪的具体表现而非概述。
【文风硬约束】严禁"像...""如同...""仿佛..."等明喻句式，严禁无意义修饰句，行文简单明了，聚焦核心剧情与人物，减少不必要的环境描写。

请开始写作。"""},
    ]

    async for chunk in llm_client.chat_stream(messages, temperature=0.8, max_tokens=16384):
        yield chunk


async def suggest_continuation(state: NovelState, current_text: str) -> str:
    context_text, outline_item, metadata_section = _build_writing_context(state)

    current_text_tail = current_text[-2000:] if current_text else ""

    user_content = f"""本章大纲：
标题：{outline_item.get('title', '')}
情节摘要：{outline_item.get('plot_summary', '')}
关键事件：{', '.join(outline_item.get('key_events', []))}
涉及人物：{', '.join(outline_item.get('characters', []))}
{metadata_section}

前文上下文：
{context_text}

【用户已写正文（尾部）】
{current_text_tail}

请续写下一句（约 15-25 字），仅输出续写内容。"""

    messages = [
        {"role": "system", "content": SUGGEST_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        result = await llm_client.chat(messages, temperature=0.7, max_tokens=60)
        return result.strip()
    except LLMError as e:
        logger.warning("续写建议失败: %s", e.message)
        return ""


async def evaluate_reviews(state: NovelState) -> NovelState:
    review_comments = state.get("review_comments", [])
    chapter_draft = state.get("chapter_draft", "")

    if not review_comments:
        state["writer_decisions"] = []
        state["pending_user_decisions"] = []
        state["current_phase"] = "all_accepted"
        return state

    comments_text = json.dumps(review_comments, ensure_ascii=False, indent=2)

    messages = [
        {"role": "system", "content": EVALUATE_SYSTEM_PROMPT},
        {"role": "user", "content": f"""当前章节内容：
{chapter_draft}

读者审查意见：
{comments_text}

请判断每条意见是否合理，决定是否接受。"""},
    ]

    response = await llm_client.chat(messages, temperature=0.3, max_tokens=8192)

    try:
        response_clean = response.strip()
        if response_clean.startswith("```"):
            lines = response_clean.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            response_clean = "\n".join(lines)
        parsed = json.loads(response_clean)
        if isinstance(parsed, dict):
            parsed = parsed.get("decisions") or parsed.get("results") or []
        if not isinstance(parsed, list):
            parsed = []
    except (json.JSONDecodeError, ValueError, TypeError):
        parsed = []

    decision_map = {}
    for d in parsed:
        if not isinstance(d, dict):
            continue
        cid = str(d.get("comment_id", ""))
        decision_map[cid] = d

    accepted = []
    pending = []
    for i, comment in enumerate(review_comments):
        cid = str(comment.get("comment_id", i))
        decision = decision_map.get(cid)
        if decision is None:
            decision = {
                "comment_id": cid,
                "decision": "reject",
                "reason": "AI未给出明确裁决，交由用户判断",
                "revision_plan": "",
            }
        entry = {**decision, "original_comment": comment}
        if decision.get("decision") == "accept":
            accepted.append(entry)
        else:
            pending.append(entry)

    state["writer_decisions"] = accepted
    state["pending_user_decisions"] = pending
    state["current_phase"] = "has_rejected" if pending else "all_accepted"
    return state


async def revise_chapter(state: NovelState) -> NovelState:
    chapter_draft = state.get("chapter_draft", "")
    accepted_decisions = state.get("writer_decisions", [])
    user_decisions = state.get("user_decisions", [])
    chapter_number = state.get("current_chapter_number", 1)

    all_revisions = []
    for d in accepted_decisions:
        all_revisions.append(f"意见：{d.get('original_comment', {}).get('comment', '')}\n修改计划：{d.get('revision_plan', '')}")
    for d in user_decisions:
        if d.get("action") == "accept_suggestion":
            all_revisions.append(f"用户采纳意见：{d.get('suggestion', '')}")
        elif d.get("action") == "custom":
            all_revisions.append(f"用户自定义修改：{d.get('custom_text', '')}")

    if not all_revisions:
        state["is_final"] = True
        state["current_phase"] = "finalized"
        return state

    revision_text = "\n\n".join([f"{i+1}. {r}" for i, r in enumerate(all_revisions)])

    messages = [
        {"role": "system", "content": WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请根据以下修改意见修订第{chapter_number}章：

当前章节内容：
{chapter_draft}

需要修改的内容：
{revision_text}

请输出修订后的完整章节内容。"""},
    ]

    parts: list[str] = []
    async for chunk in llm_client.chat_stream(messages, temperature=0.7, max_tokens=16384):
        parts.append(chunk)
    revised = "".join(parts).strip()
    if revised:
        state["chapter_draft"] = revised
    else:
        logger.warning("修订返回空内容 novel=%s chapter=%s revision=%d，保留原草稿",
                       state.get("novel_id"), chapter_number, state.get("revision_count", 0))
    state["revision_count"] = state.get("revision_count", 0) + 1
    state["current_phase"] = "revised"
    return state
