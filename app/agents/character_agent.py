from app.llm.siliconflow import LLMError, get_client
from app.agents.state import NovelState
import logging

logger = logging.getLogger(__name__)

llm_client = get_client("author")

PSYCHOLOGY_SYSTEM_PROMPT = """你是一位资深角色心理分析师。根据本章情节、角色近况与角色设定，推演相关角色在本章场景中的心理状态，为小说作者提供落笔素材。

主角与配角推演深度有别：
- 主角：作为叙事焦点，须深入推演其内心——情绪层次更复杂、内在矛盾更深、动机与本章抉择的挣扎须充分展开，篇幅更长更细腻；
- 配角：围绕其与主角的互动和本章功能展开，心理推演简明有力，突出其对情节或主角的作用，不喧宾夺主。

通用要求：
- 推演须具体、可落地，给出具体情绪词与触因，禁止空泛套话；
- 紧扣本章冲突与角色既有人设，心理变化须有因果；
- 区分不同角色的差异心理，不千篇一律；
- 只输出推演结果，不要复述输入，不要输出与心理无关的设定。"""

_CORE_WORLD_CATEGORIES = ("世界观", "世界规则", "时代背景", "力量体系", "世界设定", "核心")


def _current_outline_item(state: NovelState) -> dict:
    chapter_number = state.get("current_chapter_number", 1)
    for item in (state.get("outline") or []):
        if item.get("chapter_number") == chapter_number:
            return item
    return {}


def _chapter_relevance_text(outline_item: dict) -> str:
    return " ".join(filter(None, [
        outline_item.get("plot_summary", ""),
        " ".join(outline_item.get("key_events", []) or []),
        outline_item.get("location", ""),
        outline_item.get("conflict", ""),
        outline_item.get("chapter_hook", ""),
    ]))


def _name_in_set(name: str, name_set) -> bool:
    if not name:
        return False
    for n in name_set:
        if not n:
            continue
        if n in name or name in n:
            return True
    return False


def curate_relevant_settings(state: NovelState) -> dict:
    """按本章相关性过滤角色/关系/世界观，纯确定性，不调用LLM。"""
    outline_item = _current_outline_item(state)
    chapter_chars = set(outline_item.get("characters", []) or [])
    rel_text = _chapter_relevance_text(outline_item)

    sk = state.get("story_knowledge") or {}
    all_chars = sk.get("characters") or []
    all_rels = sk.get("character_relations") or []
    all_elems = sk.get("world_elements") or []

    relevant_chars = []
    seen = set()
    for c in all_chars:
        name = c.get("name", "")
        role = c.get("role", "") or ""
        is_protagonist = "主角" in role
        chapter_hit = bool(chapter_chars) and _name_in_set(name, chapter_chars)
        keep = chapter_hit or is_protagonist or (not chapter_chars and len(relevant_chars) < 6)
        if keep and name and name not in seen:
            seen.add(name)
            relevant_chars.append(c)

    rel_names = {c.get("name", "") for c in relevant_chars}
    relevant_rels = [
        r for r in all_rels
        if _name_in_set(r.get("from", ""), rel_names) or _name_in_set(r.get("to", ""), rel_names)
    ]

    relevant_elems = []
    for e in all_elems:
        name = e.get("name", "")
        cat = e.get("category", "") or ""
        is_core = any(core in cat for core in _CORE_WORLD_CATEGORIES) if cat else False
        name_hit = bool(name) and name in rel_text
        cat_hit = bool(cat) and cat in rel_text
        if is_core or name_hit or cat_hit:
            relevant_elems.append(e)

    return {"characters": relevant_chars, "relations": relevant_rels, "world_elements": relevant_elems}


def _build_character_arc(name: str, prev_sems: list) -> str:
    arc_parts = []
    for s in prev_sems:
        involved = s.get("characters_involved") or []
        summary = s.get("summary", "") or ""
        if _name_in_set(name, set(involved)) or name in summary:
            arc_parts.append(f"第{s.get('chapter_number', '?')}章:{summary[:80]}")
    return "；".join(arc_parts[-3:]) if arc_parts else "无前情记录"


def _format_character_brief(c: dict, prev_sems: list) -> str:
    name = c.get("name", "") or ""
    role = c.get("role", "") or ""
    is_protagonist = "主角" in role
    tag = "主角" if is_protagonist else "配角"

    setting_parts = []
    desc = c.get("description") or c.get("profile") or ""
    if desc:
        setting_parts.append(f"人设：{desc}")
    personality = c.get("personality", "") or ""
    if personality:
        setting_parts.append(f"性格：{personality}")
    motivation = c.get("motivation", "") or c.get("goal", "") or ""
    if motivation:
        setting_parts.append(f"动机：{motivation}")
    background = c.get("background", "") or ""
    if background:
        setting_parts.append(f"背景：{background}")
    status = c.get("status", "") or ""
    if status:
        setting_parts.append(f"当前状态：{status}")
    arc = _build_character_arc(name, prev_sems)
    setting_parts.append(f"前情弧线：{arc}")

    return f"- {name}（{role}，{tag}）：{'；'.join(setting_parts)}"


async def curate_character_psychology(state: NovelState) -> NovelState:
    """推演本章相关角色心理，写入 state['character_psychology']。失败置空串，不阻断写作。"""
    rel = curate_relevant_settings(state)
    relevant_chars = rel["characters"]
    if not relevant_chars:
        state["character_psychology"] = ""
        return state

    outline_item = _current_outline_item(state)
    prev_sems = state.get("previous_semantics") or []

    char_briefs = [_format_character_brief(c, prev_sems) for c in relevant_chars]

    user_msg = f"""本章信息：
标题：{outline_item.get('title', '')}
情节摘要：{outline_item.get('plot_summary', '')}
关键事件：{', '.join(outline_item.get('key_events', []) or [])}
场景：{outline_item.get('location', '')}
冲突：{outline_item.get('conflict', '')}

相关角色（标注主角/配角，附完整设定）：
{chr(10).join(char_briefs)}

请为以上每个角色推演在本章场景中的心理，每个角色输出：
1. 此刻情绪（具体情绪词+触因）
2. 内心渴望/动机
3. 内心矛盾或恐惧
4. 行为与语言倾向（供作者落笔）

要求：主角推演须深入细腻、矛盾层次更丰富；配角推演简明有力、突出其与主角的互动或本章功能；禁止空泛套话；每个角色一段；总长不超过800字。"""

    messages = [
        {"role": "system", "content": PSYCHOLOGY_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    try:
        result = await llm_client.chat(messages, temperature=0.6, max_tokens=1500)
        state["character_psychology"] = result.strip()
    except LLMError:
        logger.warning("角色心理推演LLM失败，跳过")
        state["character_psychology"] = ""
    except Exception:
        logger.exception("角色心理推演异常，跳过")
        state["character_psychology"] = ""
    return state
