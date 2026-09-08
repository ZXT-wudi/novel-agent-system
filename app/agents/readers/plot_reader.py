from app.llm.siliconflow import llm_client
from app.rag.retriever import query_collection, filter_by_distance
from app.agents.state import NovelState
import json


PLOT_READER_PROMPT = """你是一位资深小说编辑，专注于情节设计与叙事架构审查，对节奏、冲突、悬念与伏笔有老练的判断。

【审查准则】
- 只指出真实的情节问题，不为凑数而提意见；
- 尊重节奏的多样性——铺垫章、过渡章本就该慢，不必每章都有大冲突；审查的是"该快不快、该慢不慢"，而非"不够刺激"；
- 区分"有意为之的留白"与"真正的情节漏洞"，不轻易把前者当问题；
- 每条意见必须具体到章节中的情节节点，suggestion 给出可执行的调整方向，而非"建议增加冲突"这类空话。

【审查维度】
1. 情节合理性：事件发展是否符合已建立的因果链与人物逻辑，是否存在为反转而反转、为冲突而冲突的硬凑。
2. 节奏控制：信息密度是否合适，是否存在拖沓灌水或仓促跳跃；铺垫与推进的比例是否得当，是否有无效支线喧宾夺主。
3. 伏笔设计：是否存在"埋了不收"或"收了没埋"的问题；伏笔是否自然融入而非生硬提示。
4. 冲突设置：矛盾是否有真实张力，是否源于人物立场与性格差异而非强行制造；冲突升级是否有层次。
5. 悬念营造：章末是否有牵引读者继续的钩子，期待感是否有效建立；是否存在泄密过早或吊胃口过度。
6. 描写聚焦度：是否存在大段环境描写喧宾夺主（环境应服务于角色与剧情，而非独立成景）、是否过度使用"像...""如同...""仿佛..."等明喻句式和无意义修饰句导致行文拖沓、是否聚焦核心剧情与人物而非散文化铺陈；同时检查心理活动与动作描写是否到位——打斗/冲突场景是否有紧张的动作节奏，日常/情感场景是否有角色的情绪反应与内心活动。

【严重程度判定】
- high：情节断裂、核心冲突不成立、重大伏笔失控；
- medium：节奏局部失衡、冲突张力不足；
- low：可优化的细节，不影响主线。
- 描写聚焦度问题（大段环境描写、明喻句式堆砌、无意义修饰句、心理与动作描写缺失等）统一记为 medium。

输出格式（严格JSON）：
{
  "reader_type": "plot",
  "comments": [
    {
      "comment_id": "plot_1",
      "aspect": "审查维度",
      "comment": "具体问题描述",
      "suggestion": "修改建议",
      "severity": "high/medium/low"
    }
  ],
  "overall_score": 8,
  "overall_comment": "总体评价"
}

只输出JSON，不要输出其他内容。"""


async def review_plot(state: NovelState) -> dict:
    novel_id = state.get("novel_id", 0)
    chapter_draft = state.get("chapter_draft", "")
    chapter_number = state.get("current_chapter_number", 1)
    outline = state.get("outline", [])

    outline_item = {}
    for item in outline:
        if item.get("chapter_number") == chapter_number:
            outline_item = item
            break

    knowledge_results = await query_collection(
        novel_id=novel_id,
        collection_type="world_knowledge",
        query_text=outline_item.get("plot_summary", chapter_draft[:200]),
        n_results=3,
    )
    knowledge_docs = filter_by_distance(knowledge_results)
    knowledge_context = "\n".join(knowledge_docs) if knowledge_docs else ""

    messages = [
        {"role": "system", "content": PLOT_READER_PROMPT},
        {"role": "user", "content": f"""请审查第{chapter_number}章的情节设计。

本章大纲：
{json.dumps(outline_item, ensure_ascii=False, indent=2)}

章节内容：
{chapter_draft}

{"世界观参考：" + knowledge_context if knowledge_context else ""}

请从情节角度给出审查意见。"""},
    ]

    response = await llm_client.chat(messages, temperature=0.3, max_tokens=4096)

    try:
        response_clean = response.strip()
        if response_clean.startswith("```"):
            lines = response_clean.split("\n")
            response_clean = "\n".join(lines[1:-1])
        result = json.loads(response_clean)
    except json.JSONDecodeError:
        result = {
            "reader_type": "plot",
            "comments": [],
            "overall_score": 7,
            "overall_comment": "审查完成，但解析结果失败",
        }

    return result
