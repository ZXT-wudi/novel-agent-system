from app.llm.siliconflow import LLMError, get_client

llm_client = get_client("author")
from app.rag.retriever import query_collection, filter_by_distance
from app.agents.state import NovelState
from typing import AsyncGenerator, Optional
import json
import logging

logger = logging.getLogger(__name__)


OUTLINE_SYSTEM_PROMPT = """你是一位资深小说架构师，擅长设计引人入胜、结构完整的故事大纲。

【架构准则】
- 主线清晰、起承转合完整：开篇钩子、发展推进、转折高潮、收束呼应缺一不可；
- 角色设计：主角有清晰的核心动机与成长弧线，配角功能明确不冗余，避免工具人；
- 冲突设计：核心矛盾层层递进，每章有推进或转折，避免流水账式平铺；
- 节奏设计：张弛有度，铺垫章与高潮章交替，信息密度分配合理；
- 伏笔与呼应：埋设自然不生硬，回收有惊喜，前后章节相互照应；
- 章节钩子：每章结尾尽量留有牵引力，让读者愿意读下一章。

你的职责：
1. 根据用户的需求描述，设计完整的小说大纲
2. 大纲需要包含每个章节的标题、情节摘要、关键事件、涉及人物、环境地点和备注
3. 确保整体故事线有起承转合，节奏合理
4. 注意伏笔和前后呼应的设计

输出格式要求（严格JSON数组）：
[
  {
    "chapter_number": 1,
    "title": "章节标题",
    "plot_summary": "本章情节摘要，100-200字",
    "key_events": ["关键事件1", "关键事件2"],
    "characters": ["涉及人物1", "涉及人物2"],
    "location": "本章环境地点与场景，含场景切换，50字以内",
    "chapter_hook": "章末钩子（悬念/转折/未决），30字以内",
    "notes": "备注说明"
  }
]

只输出JSON数组，不要输出其他内容。"""


FULL_OUTLINE_SYSTEM_PROMPT = """你是一位资深小说架构师，需要设计完整、宏大而连贯的总体框架。

【设计方法论——先设定，后情节】
一、世界观与背景（worldview）：时代背景、世界规则或力量体系、社会结构、主要场景地域，须自洽并能支撑全部情节；
二、人物设定（characters）：主角、核心配角、重要配角、主要反派逐一设定（不少于8人，须覆盖原作/知识库中的全部主要角色）：
   - 每人明确：身份背景与年龄外貌、核心动机与性格、与主角的关系（师徒/家人/恋人/敌对/盟友等）、随情节的变化轨迹；
   - 每位角色必须写明与主角的具体关系定位及其情感基调，不得遗漏；
   - 人物关联要成网：谁与谁对立、谁与谁牵绊、谁推动谁的变化；
   - 变化轨迹写清：随情节推进将受到什么冲击、发生什么转变、得到什么（精神的/物质的）；
三、每卷情节按六要素设计：
   1. 环境地点（setting）：本卷情节主要发生在什么环境、什么地方？有无场景切换？先在脑海中想象这些场景，用简短词句写下来；
   2. 故事开端（opening）：事件如何引发？发现了问题还是遇到了困难？从哪个人开始？注意伏笔和悬念的埋设；写清主角的动力来源（引起好奇主动探索，还是被动卷入不得不走下去）；
   3. 发展与阻力（development）：为实现目标需要做什么、达成哪些条件？遇到什么阻力（冲突）？主角做了什么去解决？和哪些人产生联系、打了交道？反派出来了没？
   4. 故事高潮（climax）：最大的阻力是什么？反派是谁、有多厉害？用什么方式解决才最爽快？各个人物遭受什么冲击？主角给他人带来什么震撼或其他情绪？
   5. 结尾与新开端（ending）：情节结束后主角发生了什么变化、有什么收获（精神的/物质的）？其他人物如何了、有何改变（要做对比）？是否又引出另外一个悬念、开启下一卷？一环扣一环，让读者欲罢不能；
四、卷间衔接：核心矛盾逐卷升级，小冲突服务大冲突，避免各卷割裂；跨卷伏笔在合适卷回收，长线期待与短线满足交替。
五、人物情感弧线（character_dynamics）：每卷须为该卷涉及的每位核心角色与主角之间逐一列出一条情感动态——包含情感状态、触发情感变化的关键事件、以及情感如何变化（由X到Y）；至少3条/卷，须覆盖本卷出场的全部主要角色；情感须随事件演进、有因有果，避免突兀跳变；不同卷之间同一角色的情感关系要形成连贯脉络。
六、主角能力进阶（protagonist_abilities 与 ability_baseline）：在 characters 中为主角（及关键力量持有者）设定 ability_baseline 作为能力/力量体系基线；每卷须列出主角能力的状态（初现/成长/突破/受限/丧失）、能力如何变化、以及触发变化的事件；能力变化须与情节事件因果绑定，不得无端觉醒或消失。
七、伏笔布局（跨卷追踪，foreshadowing 与 foreshadowing_ids）：在顶层 foreshadowing[] 中登记每个伏笔的 id（形如 F1、F2）、描述、埋下卷号 planted_in_volume、回收卷号 payoff_in_volume（未回收为 null）、状态 status（planted/ongoing/payoff）；每卷用 foreshadowing_ids 引用本卷埋下或回收的伏笔 id；埋下与回收须跨卷配对，不得出现无回收的孤立伏笔（除非有意留作长线）。

【架构准则】
- 整体弧线：核心主题与核心冲突贯穿始终，起承转合在卷与卷之间形成完整脉络；
- 节奏与密度：每卷情节密度与目标总字数推导的章节规模相匹配，不灌水、不仓促。

篇幅要求：
- 长篇（80万字以上）：约200-300章，设计3-5个大卷，每卷50-80章，情节线丰富，多线并行
- 短篇（20万字左右）：约50-70章，设计2-3个卷，每卷20-30章，情节紧凑，主线集中

写作元数据驱动的篇幅推导（当用户消息中提供【写作元数据】时，以本节规则为准）：
- 根据「目标总字数」推算 total_chapters：每章约3000-5000字（均值约4000字），total_chapters ≈ 目标总字数 / 4000，并钳制在 10-400 的合理区间内。
- 根据 total_chapters 推算卷数：长篇每卷约40-80章（均值约60章），短篇每卷约20-30章；volumes 数量 ≈ total_chapters / 60（长篇）或 total_chapters / 25（短篇），至少1卷，最多5卷。
- 大纲规模必须与目标总字数严格匹配：total_chapters 必须等于上述推算值（±10%以内），各卷 chapter_range 的上限之和必须等于 total_chapters，不得显著偏离。例如80万字→约200章3-4卷，20万字→约50章2卷。
- 写作方式（writing_style）应指导 story_arc 与各卷 summary 的行文基调与风格；叙事人称（narrative_pov）应指导 story_arc 与各卷叙述视角（如第一人称、第三人称限知、第三人称全知等）。
- 若用户消息未提供【写作元数据】，则沿用上方「篇幅要求」。
- 若用户消息提供了【小说设定】，其中的世界观与人物设定是基线，必须严格沿用并深化，不得推翻：characters 数组中的每个角色必须原样纳入输出（姓名、角色定位、性格、背景、动机须一致），不得改名、删减属性或另造角色；world_settings 的全部字段须沿用并可在其基础上深化扩展。

【同人创作硬约束】
- 若下方提供【原作知识库参考】，其中出现的角色姓名、身份、能力体系、世界观规则、重大事件等必须严格沿用，不得原创与之冲突的角色或推翻既有设定。
- 知识库中提供的全部主要角色（主角、核心配角、重要配角、主要反派）须在 characters 中忠实纳入并沿用其设定，不得遗漏主要角色；本卷新增的 character_dynamics、protagonist_abilities 须与原作角色设定自洽。
- 知识库中的全部事件、世界观、时间线、势力设定须在卷概述、伏笔等处逐一覆盖，不得遗漏。
- 每卷须在 source_volumes 中标注本卷引用的原作源卷号列表（如本卷主要取材自原作第1-2卷则填 [1, 2]）；此字段供后续章节大纲按源卷过滤知识库上下文使用。
- 时间线门控（最高优先级）：source_volumes 须随同人卷序号单调递增——早期同人卷只能引用早期源卷，严禁后期源卷的事件、人物或设定出现在前期同人卷的时间线上。

输出格式要求（严格JSON对象，所有字段必须完整出现、内容充实，不得省略或留空）：
{
  "theme": "作品核心主题",
  "core_conflict": "核心冲突描述",
  "story_arc": "整体故事弧线描述，600-1000字，须包含：核心主题阐释、主线冲突的起承转合（起因→发展→转折→高潮→结局逐段展开）、各卷如何推进核心冲突、主角成长弧线的阶段性变化、关键转折点说明",
  "worldview": "世界观与背景设定，200-400字：时代背景、世界规则或力量体系、社会结构、主要场景地域",
  "characters": [
    {
      "name": "人物姓名",
      "role": "主角/核心配角/反派",
      "profile": "身份背景、年龄外貌，60字以内",
      "motivation": "核心动机与性格特点，60字以内",
      "relationships": "与主角的关系定位（师徒/家人/恋人/敌对/盟友等）及情感基调，50字以内",
      "arc": "变化轨迹：将受到的冲击、转变与收获，40字以内",
      "ability_baseline": "该角色（尤为主角）的核心能力/力量体系基线，60字以内，无则写'无'"
    }
  ],
  "total_chapters": 预计总章节数,
  "volumes": [
    {
      "volume_number": 1,
      "title": "卷标题",
      "summary": "本卷情节概述，200-350字",
      "chapter_range": [1, 50],
      "source_volumes": [1, 2],
      "setting": "本卷环境地点：主要环境、在什么地方、场景如何、有无切换，60字以内",
      "opening": "开端：事件如何引发、从谁开始、伏笔悬念、主角动力（主动探索/被动卷入），70字以内",
      "development": "发展与阻力：目标条件、阻力冲突、主角的解决、打交道的人物、反派动向，80字以内",
      "climax": "高潮：最大阻力与反派、解决方式（要爽快）、各人物冲击、主角的震撼，80字以内",
      "ending": "结尾与新开端：主角变化收获、他人改变对比、引出的新悬念，50字以内",
      "key_characters": ["核心角色1", "核心角色2"],
      "major_events": ["关键转折点1", "关键转折点2"],
      "tone": "本卷基调",
      "character_dynamics": [
        {
          "character": "本条涉及的角色（写角色名，如 艾莉丝），每条只写一位角色与主角的关系",
          "emotion_state": "本卷该关系的情感状态，如 信任渐生/暗中防备",
          "key_event": "触发情感变化的关键事件",
          "emotion_change": "情感如何变化（由X到Y，有因有果）"
        }
      ],
      "protagonist_abilities": [
        {
          "ability": "能力名称或类别",
          "state": "初现/成长/突破/受限/丧失",
          "change": "能力如何变化",
          "trigger_event": "触发能力变化的事件"
        }
      ],
      "foreshadowing_ids": ["F1", "F2"]
    }
  ],
  "foreshadowing": [
    {
      "id": "F1",
      "description": "伏笔内容描述",
      "planted_in_volume": 1,
      "payoff_in_volume": 2,
      "status": "planted"
    }
  ]
}

字段说明：
- 每卷 character_dynamics 至少3条，须为本卷出场的每位核心角色与主角之间逐一写一条情感动态（角色×主角），覆盖本卷全部主要角色；每条须有具体触发事件与因果变化，不得空泛；不同卷之间同一角色的情感关系要形成连贯脉络。
- 每卷 protagonist_abilities：主角在该卷有能力状态变化时必须列出（至少1条），确无变化时可为空数组；能力变化须与情节事件因果绑定，不得无端觉醒或消失。
- 每卷 foreshadowing_ids 引用本卷埋下或回收的伏笔 id，须对应顶层 foreshadowing 中已登记的 id。
- 每卷 source_volumes：标注本卷引用的原作源卷号列表；须随卷序号单调递增，早期同人卷对应早期源卷，不得让后期源卷内容出现在前期时间线。
- 顶层 foreshadowing 登记全部伏笔：埋下与回收须跨卷配对，不得出现无回收的孤立伏笔（除非有意留作长线，此时 payoff_in_volume 填 null、status 为 ongoing）。

内容纪律：story_arc、worldview、各卷 summary 与六要素须充实饱满地展开，按上述上限充分书写，不得刻意从简导致信息稀薄；新增的 character_dynamics、protagonist_abilities、foreshadowing 须写出具体事件与因果脉络，禁止用空泛标签敷衍。
输出完整性（最高优先级）：总输出必须以完整的JSON对象闭合——最末一个`}`不可缺失。为此，各字段在保证信息充实的前提下尽量精炼、避免重复啰嗦；若卷数或章节数较多，优先压缩各卷 summary 与六要素的字数（取下限而非上限），确保JSON结构完整闭合。宁可单字段略短，也不可因冗长导致输出在中间被截断。
只输出JSON对象，不要输出其他内容。"""


CHAPTER_OUTLINE_SYSTEM_PROMPT = """你是一位资深小说架构师，需要根据全文框架生成详细、连贯的章节大纲。

【章节设计准则--六要素齐备】
- 环境地点（location）：本章情节主要发生的环境是如何的？在什么地方？有场景切换吗？在脑海中想象一下这些场景，用简单的词句写下来；
- 涉及人物（characters 与 character_changes）：本章的主要参与者有哪些？人物言行须与人物设定一致；随情节推进，这些人物发生了什么变化？受到什么冲击？得到什么好处？写入 character_changes；
- 开端与动力：本章事件如何引发？发现了问题？遇到了困难？从哪个人开始？注意伏笔和悬念的描写，这是吸引读者继续看下去的技巧；本章是主角主动探索，还是被动卷入不得不走下去；
- 发展与阻力（conflict）：为实现目标需要做什么、达到哪些条件？遇到了什么阻力（冲突）？主角做了什么事情去解决？和哪些人产生了联系、打了交道？反派出来了没？写进 conflict 与 plot_summary；
- 高潮章（卷末关键章）：最大的阻力是什么？反派有多厉害？用什么方式解决才最爽快？各个人物遭受了什么样的冲击？主角给他人产生了什么样的震撼或其他情绪？
- 章末钩子（chapter_hook）：每章结尾留有牵引力（悬念、转折、未决冲突），让读者愿意读下一章；本章结束时主角有何收获？是否又引起另外一个悬念？一环扣一环；
- 衔接连贯：与前文及已有章节大纲自然衔接，时间线、地点、人物状态保持一致；
- 一致性：严格遵循已写章节的知识数据与人物设定，不与之矛盾；
- 情感节拍（emotion_beat）：本章角色情感状态/变化须与所在卷的 character_dynamics 一致并推进；写出本章关键情感节拍。
- 能力状态（ability_state）：本章主角能力状态须与所在卷 protagonist_abilities 一致，可有微小变化，写入 ability_state。
- 伏笔动作（foreshadowing_action）：本章可埋下/推进/回收伏笔；动作须引用顶层 foreshadowing 的 id（如 F1），并标注动作类型（埋下/推进/回收），写入 foreshadowing_action。

输出格式要求（严格JSON数组）：
[
  {
    "chapter_number": 1,
    "title": "章节标题",
    "plot_summary": "本章情节摘要，150-250字，按开端引发->发展阻力->推进/高潮的骨架叙述",
    "key_events": ["关键事件1", "关键事件2"],
    "characters": ["涉及人物1", "涉及人物2"],
    "location": "本章环境地点与场景，含场景切换，50字以内",
    "conflict": "本章核心阻力或冲突，30字以内",
    "character_changes": "涉及人物在本章的变化、受到的冲击或得到的好处，50字以内，无则写'无'",
    "chapter_hook": "章末钩子（悬念/转折/未决），30字以内",
    "notes": "伏笔、呼应等备注",
    "emotion_beat": "本章关键情感节拍（角色情感状态/变化），40字以内，无则写'无'",
    "ability_state": "本章主角能力状态/微小变化，40字以内，无则写'无'",
    "foreshadowing_action": "本章对伏笔的动作（埋下/推进/回收）+引用id，40字以内，无则写'无'"
  }
]

字数纪律：新增字段务必从简表达，确保输出为完整JSON、绝不截断。
只输出JSON数组，不要输出其他内容。"""


async def _safe_rag_query(novel_id: int, collection_type: str, query_text: str, n_results: int = 5) -> str:
    try:
        results = await query_collection(
            novel_id=novel_id,
            collection_type=collection_type,
            query_text=query_text,
            n_results=n_results,
        )
        docs = filter_by_distance(results)
        return "\n".join(docs) if docs else ""
    except LLMError:
        return ""
    except Exception:
        logger.debug("RAG query failed for %s", collection_type, exc_info=True)
        return ""


def _build_outline_messages(user_input: dict, preference_context: str, knowledge_context: str, kb_context: str = "") -> list[dict]:
    preference_section = f"\n用户偏好参考：\n{preference_context}" if preference_context else ""
    knowledge_section = f"\n世界观设定参考：\n{knowledge_context}" if knowledge_context else ""
    kb_section = f"\n=== 原作知识库参考（同人创作最高优先级，必须完整覆盖：以下知识库条目必须逐一体现到大纲中。须提取全部角色、事件、世界观、时间线、势力设定并忠实沿用，不得遗漏任何条目，不得原创冲突角色或推翻既有设定。若知识库中有N个角色，大纲中必须体现这N个角色及其关系） ===\n{kb_context}" if kb_context else ""
    return [
        {"role": "system", "content": OUTLINE_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请根据以下需求设计小说大纲：

小说标题：{user_input.get('title', '未命名')}
小说类型：{user_input.get('genre', '未指定')}
小说描述：{user_input.get('description', '无描述')}
目标章节数：{user_input.get('target_chapters', '10')}
{preference_section}
{knowledge_section}
{kb_section}

请设计完整的大纲。"""},
    ]


def _format_novel_settings(world_settings: Optional[dict], characters: Optional[list]) -> str:
    setting_lines = []
    ws = world_settings if isinstance(world_settings, dict) else {}
    if ws.get("era"):
        setting_lines.append(f"时代背景：{ws['era']}")
    if ws.get("location"):
        setting_lines.append(f"主要地点：{ws['location']}")
    if ws.get("rules"):
        setting_lines.append(f"世界规则：{ws['rules']}")
    if ws.get("key_elements"):
        setting_lines.append(f"关键元素：{', '.join(str(x) for x in ws['key_elements'])}")
    if ws.get("power_system"):
        setting_lines.append(f"力量体系：{ws['power_system']}")
    if ws.get("social_structure"):
        setting_lines.append(f"社会结构：{ws['social_structure']}")
    if ws.get("core_conflict"):
        setting_lines.append(f"核心冲突：{ws['core_conflict']}")
    if ws.get("theme"):
        setting_lines.append(f"主题思想：{ws['theme']}")
    for c in (characters or []):
        if isinstance(c, dict) and c.get("name"):
            setting_lines.append(
                f"- 人物 {c.get('name', '')}（{c.get('role', '')}）："
                f"{c.get('personality', '')}；{c.get('background', '')}；动机：{c.get('motivation', '')}"
            )
    if not setting_lines:
        return ""
    return "\n【小说设定（基线，必须沿用并深化）】\n" + "\n".join(setting_lines)


def _build_full_outline_messages(
    user_input: dict,
    preference_context: str,
    knowledge_context: str,
    writing_style: Optional[str] = None,
    target_word_count: Optional[int] = None,
    narrative_pov: Optional[str] = None,
    kb_context: str = "",
    web_research_context: str = "",
) -> list[dict]:
    length_type = user_input.get("length_type", "short")
    twc = target_word_count if target_word_count else user_input.get("target_word_count") or 0
    try:
        twc = int(twc)
    except (TypeError, ValueError):
        twc = 0
    if twc > 0:
        length_type = "long" if twc >= 500000 else "short"
    length_desc = "长篇（80万字以上，约200-300章，3-5个大卷）" if length_type == "long" else "短篇（20万字左右，约50-70章，2-3个卷）"
    preference_section = f"\n用户偏好参考：\n{preference_context}" if preference_context else ""
    knowledge_section = f"\n世界观设定参考：\n{knowledge_context}" if knowledge_context else ""
    kb_section = f"\n=== 原作知识库参考（同人创作最高优先级，按源卷组织：以下知识库已按源卷分段呈现，标注【源卷N《title》】，另含【卷N主要事件总结】、【卷N章节摘要】、【跨卷关联】与【各卷摘要】。生成全文大纲时，请将每个源卷的设定/人物/事件映射到本小说对应卷，并依据各卷主要事件走向与章节内容安排本小说对应卷的承接与节奏，参考跨卷关联保证连贯。全部角色、事件、世界观、时间线、势力设定须忠实沿用，不得遗漏，不得原创冲突角色或推翻既有设定） ===\n{kb_context}" if kb_context else ""
    web_research_section = f"\n=== 联网取材参考（真实资料/同类作品/文化背景，可借鉴但需与原创设定融合，不可直接照搬人名地名） ===\n{web_research_context}" if web_research_context else ""

    metadata_lines = []
    if target_word_count:
        metadata_lines.append(f"目标总字数：{target_word_count} 字")
    if writing_style:
        metadata_lines.append(f"写作方式：{writing_style}")
    if narrative_pov:
        metadata_lines.append(f"叙事人称：{narrative_pov}")
    metadata_section = ("\n【写作元数据】\n" + "\n".join(metadata_lines)) if metadata_lines else ""
    ws = user_input.get("world_settings")
    chars = user_input.get("characters")
    novel_settings_json = {}
    if isinstance(ws, dict) and ws:
        novel_settings_json["world_settings"] = ws
    if isinstance(chars, list) and chars:
        novel_settings_json["characters"] = chars
    novel_settings_section = ""
    if novel_settings_json:
        novel_settings_section = (
            "\n【小说设定（基线，必须严格沿用并深化，不得推翻：以下角色必须原样纳入 characters，姓名/性格/背景/动机须一致，不得改名、删改或另造角色；世界观须沿用并深化）】\n"
            + json.dumps(novel_settings_json, ensure_ascii=False, indent=2)
        )

    logger.debug("[OUTLINE-MSG] world_settings present=%s, characters present=%s, novel_settings_section_len=%s",
                 bool(ws), bool(chars), len(novel_settings_section))
    if novel_settings_section:
        logger.debug("[OUTLINE-MSG] settings preview: %s", novel_settings_section[:300])

    return [
        {"role": "system", "content": FULL_OUTLINE_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请根据以下需求设计小说总体框架：

小说标题：{user_input.get('title', '未命名')}
小说类型：{user_input.get('genre', '未指定')}
小说描述：{user_input.get('description', '无描述')}
篇幅类型：{length_desc}{metadata_section}{novel_settings_section}
{preference_section}
{knowledge_section}
{kb_section}
{web_research_section}

请设计完整的总体框架。"""},
    ]


def _build_chapter_outline_messages(
    full_outline: dict,
    start_chapter: int,
    end_chapter: int,
    existing_outline: list[dict],
    knowledge_context: str,
    writing_style: Optional[str] = None,
    target_word_count: Optional[int] = None,
    narrative_pov: Optional[str] = None,
    kb_context: str = "",
    world_settings: Optional[dict] = None,
    characters: Optional[list] = None,
) -> list[dict]:
    relevant_volumes = []
    for vol in full_outline.get("volumes", []):
        ch_range = vol.get("chapter_range", [0, 0])
        if ch_range[1] >= start_chapter and ch_range[0] <= end_chapter:
            relevant_volumes.append(vol)

    vol_blocks = []
    for v in relevant_volumes:
        dyn_lines = []
        for d in (v.get("character_dynamics") or []):
            if isinstance(d, dict):
                dyn_lines.append(
                    f"    - {d.get('character', '')}：情感[{d.get('emotion_state', '')}]，事件[{d.get('key_event', '')}]，变化[{d.get('emotion_change', '')}]"
                )
        ab_lines = []
        for a in (v.get("protagonist_abilities") or []):
            if isinstance(a, dict):
                ab_lines.append(
                    f"    - {a.get('ability', '')}（{a.get('state', '')}）：{a.get('change', '')}，触发[{a.get('trigger_event', '')}]"
                )
        fs_ids = v.get("foreshadowing_ids") or []
        vol_blocks.append(
            f"第{v.get('volume_number', '?')}卷「{v.get('title', '')}」：{v.get('summary', '')}\n"
            f"章节范围：第{v.get('chapter_range', [0,0])[0]}章-第{v.get('chapter_range', [0,0])[1]}章\n"
            f"核心角色：{', '.join(v.get('key_characters', []))}\n"
            f"重大事件：{', '.join(v.get('major_events', []))}\n"
            f"基调：{v.get('tone', '')}\n"
            "角色情感动态：\n" + ("\n".join(dyn_lines) if dyn_lines else "    无") + "\n"
            "主角能力进阶：\n" + ("\n".join(ab_lines) if ab_lines else "    无") + "\n"
            f"本卷伏笔：{', '.join(fs_ids) if fs_ids else '无'}"
        )
    volume_summary = "\n\n".join(vol_blocks)

    existing_section = ""
    if existing_outline:
        last_few = existing_outline[-5:] if len(existing_outline) > 5 else existing_outline
        existing_section = f"\n已有章节大纲（最近几章，供参考衔接）：\n{json.dumps(last_few, ensure_ascii=False, indent=2)}"

    knowledge_section = f"\n已写章节知识数据（角色状态、世界观等）：\n{knowledge_context}" if knowledge_context else ""
    kb_section = f"\n=== 原作知识库参考（同人创作最高优先级，已按【卷→章】层级组织：含该卷主要事件总结、本章摘要、本章角色与事件。须忠实沿用本章涉及的角色/事件/设定，不得原创冲突角色或推翻既有设定） ===\n{kb_context}" if kb_context else ""

    metadata_lines = []
    if writing_style:
        metadata_lines.append(f"写作方式：{writing_style}")
    if narrative_pov:
        metadata_lines.append(f"叙事人称：{narrative_pov}")
    if target_word_count:
        metadata_lines.append(f"目标总字数：{target_word_count} 字")
    metadata_section = ("\n【写作元数据】\n" + "\n".join(metadata_lines)) if metadata_lines else ""

    worldview = (full_outline or {}).get("worldview", "")
    fo_char_lines = []
    for c in ((full_outline or {}).get("characters") or []):
        if isinstance(c, dict) and c.get("name"):
            fo_char_lines.append(
                f"- {c['name']}（{c.get('role', '')}）：{c.get('profile', '')}；"
                f"动机：{c.get('motivation', '')}；关联：{c.get('relationships', '')}"
            )
    fo_chars_section = ("\n人物设定（章节中人物言行须与之一致）：\n" + "\n".join(fo_char_lines)) if fo_char_lines else ""

    db_settings_section = ""
    if world_settings:
        db_settings_section = "\n【原始世界设定兜底（补充全文大纲可能遗漏的世界观，须忠实沿用，不得与之矛盾）】\n" + json.dumps(world_settings, ensure_ascii=False, indent=2)

    db_chars_section = ""
    if characters:
        db_char_lines = []
        for c in characters:
            if isinstance(c, dict) and c.get("name"):
                db_char_lines.append(
                    f"- {c['name']}（{c.get('role', '')}）：{c.get('profile', '') or c.get('description', '')}；"
                    f"动机：{c.get('motivation', '')}；关联：{c.get('relationships', '')}"
                )
        if db_char_lines:
            db_chars_section = "\n【原始人物设定兜底（补充全文大纲可能遗漏的角色，人物言行须与之不矛盾）】\n" + "\n".join(db_char_lines)

    relevant_fs_ids = set()
    for v in relevant_volumes:
        for fid in (v.get("foreshadowing_ids") or []):
            relevant_fs_ids.add(fid)
    fs_lines = []
    for f in ((full_outline or {}).get("foreshadowing") or []):
        if isinstance(f, dict):
            fid = f.get("id", "")
            if fid not in relevant_fs_ids:
                continue
            payoff = f.get("payoff_in_volume")
            fs_lines.append(
                f"- {fid}（状态：{f.get('status', '')}）：{f.get('description', '')}；"
                f"埋下卷：{f.get('planted_in_volume', '')}，回收卷：{payoff if payoff else '未回收'}"
            )
    foreshadowing_section = ("\n伏笔追踪（本章可埋下/推进/回收，须引用顶层 foreshadowing 的 id，不得遗漏已埋未回收的伏笔）：\n" + "\n".join(fs_lines)) if fs_lines else ""

    return [
        {"role": "system", "content": CHAPTER_OUTLINE_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请生成第{start_chapter}章到第{end_chapter}章的详细大纲。

全文框架：
主题：{full_outline.get('theme', '')}
核心冲突：{full_outline.get('core_conflict', '')}
故事弧线：{full_outline.get('story_arc', '')}
世界观背景：{worldview}{fo_chars_section}{db_settings_section}{db_chars_section}
预计总章节数：{full_outline.get('total_chapters', '')}
{metadata_section}

相关卷概述：
{volume_summary}
{existing_section}
{knowledge_section}
{kb_section}
{foreshadowing_section}

请生成第{start_chapter}章到第{end_chapter}章的详细大纲。本章大纲的情节密度与篇幅应与目标总字数推导的章节规模相匹配，行文基调遵循上述写作方式与叙事人称。"""},
    ]


def _parse_outline_response(response: str, fallback_outline: list | None = None) -> list:
    try:
        response_clean = response.strip()
        if response_clean.startswith("```"):
            lines = response_clean.split("\n")
            response_clean = "\n".join(lines[1:-1])
        outline = json.loads(response_clean)
        if isinstance(outline, list) and len(outline) > 0:
            return outline
    except json.JSONDecodeError:
        pass
    if fallback_outline is not None:
        return fallback_outline
    return [{"chapter_number": 1, "title": "待编辑", "plot_summary": response[:500], "key_events": [], "characters": [], "notes": ""}]


def _repair_truncated_json(text: str) -> dict | None:
    """Attempt to repair truncated JSON by auto-closing unclosed strings and brackets."""

    def _scan(t: str) -> tuple[list[str], bool]:
        in_str = False
        esc = False
        stk: list[str] = []
        for ch in t:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                stk.append("}")
            elif ch == "[":
                stk.append("]")
            elif ch in "}]":
                if stk and stk[-1] == ch:
                    stk.pop()
        return stk, in_str

    def _close(t: str, stk: list[str], in_str: bool) -> str:
        r = t.rstrip()
        while r and r[-1] in ", \n\r\t":
            r = r[:-1]
        if in_str:
            r += '"'
        for c in reversed(stk):
            r += c
        return r

    stk, in_str = _scan(text)
    if not stk and not in_str:
        return None

    try:
        result = json.loads(_close(text, stk, in_str))
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    last_pos = -1
    s = False
    e = False
    for i, ch in enumerate(text):
        if e:
            e = False
            continue
        if ch == "\\":
            e = True
            continue
        if ch == '"':
            s = not s
            continue
        if s:
            continue
        if ch in "}]":
            last_pos = i

    if last_pos > 0:
        cut = text[: last_pos + 1]
        stk2, in_str2 = _scan(cut)
        if stk2 or in_str2:
            try:
                result = json.loads(_close(cut, stk2, in_str2))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    return None


def _parse_full_outline_response(response: str, fallback: dict | None = None) -> dict:
    response_clean = response.strip()
    if response_clean.startswith("```"):
        lines = response_clean.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response_clean = "\n".join(lines).strip()

    try:
        result = json.loads(response_clean)
        if isinstance(result, dict) and "volumes" in result:
            return result
    except json.JSONDecodeError:
        pass

    repaired = _repair_truncated_json(response_clean)
    if repaired is not None and isinstance(repaired, dict) and "volumes" in repaired:
        logger.warning(
            "全文大纲JSON疑似被截断，已尝试自动修复。响应长度=%d字符，卷数=%d，末尾100字符: %s",
            len(response_clean),
            len(repaired.get("volumes", [])),
            response_clean[-100:],
        )
        return repaired

    logger.error(
        "全文大纲JSON解析失败（疑似截断且无法修复）。响应长度=%d字符，末尾200字符: %s",
        len(response_clean),
        response_clean[-200:],
    )

    if fallback is not None:
        return fallback
    return {"theme": "", "core_conflict": "", "story_arc": "", "total_chapters": 0, "volumes": []}


async def generate_full_outline(state: NovelState) -> NovelState:
    novel_id = state.get("novel_id", 0)
    user_input = state.get("outline_item", {})
    description = user_input.get("description", "")

    preference_context = await _safe_rag_query(novel_id, "user_preferences", description, n_results=5)
    world_knowledge_context = await _safe_rag_query(novel_id, "world_knowledge", description, n_results=8)
    chapter_semantic_context = await _safe_rag_query(novel_id, "chapter_semantics", description, n_results=8)
    knowledge_context = "\n".join([p for p in [world_knowledge_context, chapter_semantic_context] if p])
    kb_context = state.get("kb_context", "")
    web_research_context = state.get("web_research_context", "")

    messages = _build_full_outline_messages(
        user_input,
        preference_context,
        knowledge_context,
        writing_style=user_input.get("writing_style"),
        target_word_count=user_input.get("target_word_count"),
        narrative_pov=user_input.get("narrative_pov"),
        kb_context=kb_context,
        web_research_context=web_research_context,
    )
    response = await llm_client.chat(messages, temperature=0.8, max_tokens=32768)
    full_outline = _parse_full_outline_response(response)

    state["full_outline"] = full_outline
    state["current_phase"] = "full_outline_generated"
    return state


async def generate_full_outline_stream(state: NovelState) -> AsyncGenerator[str, None]:
    novel_id = state.get("novel_id", 0)
    user_input = state.get("outline_item", {})
    description = user_input.get("description", "")

    preference_context = await _safe_rag_query(novel_id, "user_preferences", description, n_results=5)
    world_knowledge_context = await _safe_rag_query(novel_id, "world_knowledge", description, n_results=8)
    chapter_semantic_context = await _safe_rag_query(novel_id, "chapter_semantics", description, n_results=8)
    knowledge_context = "\n".join([p for p in [world_knowledge_context, chapter_semantic_context] if p])
    kb_context = state.get("kb_context", "")
    web_research_context = state.get("web_research_context", "")

    messages = _build_full_outline_messages(
        user_input,
        preference_context,
        knowledge_context,
        writing_style=user_input.get("writing_style"),
        target_word_count=user_input.get("target_word_count"),
        narrative_pov=user_input.get("narrative_pov"),
        kb_context=kb_context,
        web_research_context=web_research_context,
    )

    async for chunk in llm_client.chat_stream(messages, temperature=0.8, max_tokens=32768):
        yield chunk


async def generate_chapter_outline(state: NovelState) -> NovelState:
    novel_id = state.get("novel_id", 0)
    full_outline = state.get("full_outline", {})
    existing_outline = state.get("outline", [])
    outline_item = state.get("outline_item", {})
    start_chapter = outline_item.get("start_chapter", 1)
    batch_size = outline_item.get("batch_size", 10)
    end_chapter = start_chapter + batch_size - 1
    writing_style = outline_item.get("writing_style")
    target_word_count = outline_item.get("target_word_count")
    narrative_pov = outline_item.get("narrative_pov")

    knowledge_context = state.get("story_knowledge_summary", "")
    if not knowledge_context:
        knowledge_context = await _safe_rag_query(novel_id, "world_knowledge", f"第{start_chapter}章到第{end_chapter}章", 5)

    kb_context = state.get("kb_context", "")

    messages = _build_chapter_outline_messages(full_outline, start_chapter, end_chapter, existing_outline, knowledge_context, writing_style=writing_style, target_word_count=target_word_count, narrative_pov=narrative_pov, kb_context=kb_context)
    response = await llm_client.chat(messages, temperature=0.8, max_tokens=16384)
    new_chapters = _parse_outline_response(response)

    for i, ch in enumerate(new_chapters):
        ch["chapter_number"] = start_chapter + i

    merged = list(existing_outline)
    existing_nums = {item.get("chapter_number") for item in merged}
    for ch in new_chapters:
        if ch.get("chapter_number") not in existing_nums:
            merged.append(ch)
    merged.sort(key=lambda x: x.get("chapter_number", 0))

    state["outline"] = merged
    state["current_phase"] = "chapter_outline_generated"
    return state


async def generate_chapter_outline_stream(state: NovelState) -> AsyncGenerator[str, None]:
    novel_id = state.get("novel_id", 0)
    full_outline = state.get("full_outline", {})
    existing_outline = state.get("outline", [])
    outline_item = state.get("outline_item", {})
    start_chapter = outline_item.get("start_chapter", 1)
    batch_size = outline_item.get("batch_size", 10)
    end_chapter = start_chapter + batch_size - 1
    writing_style = outline_item.get("writing_style")
    target_word_count = outline_item.get("target_word_count")
    narrative_pov = outline_item.get("narrative_pov")
    world_settings = outline_item.get("world_settings") or {}
    characters = outline_item.get("characters") or []

    knowledge_context = state.get("story_knowledge_summary", "")
    if not knowledge_context:
        knowledge_context = await _safe_rag_query(novel_id, "world_knowledge", f"第{start_chapter}章到第{end_chapter}章", 5)

    kb_context = state.get("kb_context", "")

    messages = _build_chapter_outline_messages(full_outline, start_chapter, end_chapter, existing_outline, knowledge_context, writing_style=writing_style, target_word_count=target_word_count, narrative_pov=narrative_pov, kb_context=kb_context, world_settings=world_settings, characters=characters)

    async for chunk in llm_client.chat_stream(messages, temperature=0.8, max_tokens=16384):
        yield chunk


async def generate_outline(state: NovelState) -> NovelState:
    novel_id = state.get("novel_id", 0)
    user_input = state.get("outline_item", {})
    description = user_input.get("description", "")

    preference_context = await _safe_rag_query(novel_id, "user_preferences", description, 5)
    knowledge_context = await _safe_rag_query(novel_id, "world_knowledge", description, 5)
    kb_context = state.get("kb_context", "")

    messages = _build_outline_messages(user_input, preference_context, knowledge_context, kb_context=kb_context)
    response = await llm_client.chat(messages, temperature=0.8, max_tokens=8192)
    outline = _parse_outline_response(response)

    state["outline"] = outline
    state["current_phase"] = "outline_generated"
    return state


async def generate_outline_stream(state: NovelState) -> AsyncGenerator[str, None]:
    novel_id = state.get("novel_id", 0)
    user_input = state.get("outline_item", {})
    description = user_input.get("description", "")

    preference_context = await _safe_rag_query(novel_id, "user_preferences", description, 5)
    knowledge_context = await _safe_rag_query(novel_id, "world_knowledge", description, 5)
    kb_context = state.get("kb_context", "")

    messages = _build_outline_messages(user_input, preference_context, knowledge_context, kb_context=kb_context)

    async for chunk in llm_client.chat_stream(messages, temperature=0.8, max_tokens=8192):
        yield chunk


async def revise_outline(state: NovelState) -> NovelState:
    novel_id = state.get("novel_id", 0)
    current_outline = state.get("outline", [])
    user_feedback = state.get("outline_item", {}).get("user_feedback", "")

    preference_context = await _safe_rag_query(novel_id, "user_preferences", user_feedback, 3)
    preference_section = f"\n用户偏好参考：\n{preference_context}" if preference_context else ""

    messages = [
        {"role": "system", "content": OUTLINE_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请根据用户反馈修改以下大纲：

当前大纲：
{json.dumps(current_outline, ensure_ascii=False, indent=2)}

用户反馈：
{user_feedback}
{preference_section}

请输出修改后的完整大纲。"""},
    ]

    response = await llm_client.chat(messages, temperature=0.7, max_tokens=8192)
    outline = _parse_outline_response(response, current_outline)

    state["outline"] = outline
    return state


async def revise_full_outline(state: NovelState) -> NovelState:
    novel_id = state.get("novel_id", 0)
    current_full_outline = state.get("full_outline", {})
    user_feedback = state.get("outline_item", {}).get("user_feedback", "")

    preference_context = await _safe_rag_query(novel_id, "user_preferences", user_feedback, 3)
    preference_section = f"\n用户偏好参考：\n{preference_context}" if preference_context else ""

    messages = [
        {"role": "system", "content": FULL_OUTLINE_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请根据用户反馈修改以下小说总体框架：

当前总体框架：
{json.dumps(current_full_outline, ensure_ascii=False, indent=2)}

用户反馈：
{user_feedback}
{preference_section}

请输出修改后的完整总体框架。"""},
    ]

    response = await llm_client.chat(messages, temperature=0.7, max_tokens=32768)
    full_outline = _parse_full_outline_response(response, current_full_outline)

    state["full_outline"] = full_outline
    return state
