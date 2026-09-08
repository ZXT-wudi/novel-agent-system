from app.llm.siliconflow import llm_client
from app.rag.retriever import query_collection, filter_by_distance
from app.agents.state import NovelState
import json


CHARACTER_READER_PROMPT = """你是一位资深小说编辑，专注于人物塑造质量审查，对角色的真实感、一致性与立体感有敏锐判断。

【审查准则】
- 只报告真实存在的人物塑造问题，不为凑数而提意见，不苛求每个角色都"复杂深刻"；
- 尊重作者既定的人设与创作意图，审查的是"是否自洽、是否落地"，不是"是否符合某种理想人物模板"；
- 每条意见必须具体到章节中的位置或语句，suggestion 要给出可执行的改法，而非"建议加强"这类空话；
- 意见聚焦本章可见的问题，不臆测未发生章节的隐患。

【审查维度】
1. 性格一致性：人物行为是否符合其既定性格设定，尤其在压力、冲突、抉择等关键时刻的反应是否贴合人设；是否出现"为推动情节而强行OOC"的情况。
2. 人物发展：人物若在本章发生变化，是否有前文铺垫与合理逻辑，转变是否突兀；若本章为铺垫章，铺垫是否扎实。
3. 对话质量：每个角色是否有可辨识的说话风格（口吻、用词、语气），对话是否推动情节或揭示性格，是否存在无效寒暄与信息重复，对白是否像该角色会说的话。
4. 行为动机：关键行为是否有充分且可信的动机，是否存在"工具人"式行为（仅为情节服务而行动），动机是否在前文有所铺垫。
5. 人物关系：角色间互动是否符合既定关系设定，关系变化（亲近、疏远、对立）是否有迹可循，群戏中各人是否各司其职。
6. 文笔与AI腔：对白与叙述是否出现以下问题——（a）破折号"——"符号（无论用于心理状态、解释说明、语气转折、补充动作还是任何用途都属违规）；（b）"不是……"析因/翻转句（含"不是……而是……""不是因为……"等用"不是"拆解因果的用法）；（c）排比堆砌、刻板过渡词等AI腔句式；（d）"像...""如同...""仿佛...""犹如...""好似..."等明喻句式——不得用"像"字做环境描写或心理描写，应直接写出事物状态和角色情绪；（e）无意义的修饰性句子——纯装饰、零信息量（如"月光洒落在地上，给大地披上一层银纱"这类仅为美化而存在、不推动剧情不揭示人物不传递信息的句子）；以上句式降低文本自然度，须标记并建议改写为直白、准确的表述。

【严重程度判定】
- high：人设崩塌/OOC、动机缺失导致情节断裂、关系设定前后矛盾；
- medium：局部违和、对话失真、动机稍弱但仍可接受；
- low：可优化的小瑕疵，不影响整体。
- AI腔句式（破折号"——"符号、"不是……"析因/翻转句、排比堆砌、"像..."明喻句式、无意义修饰句等）统一记为 medium。

输出格式（严格JSON）：
{
  "reader_type": "character",
  "comments": [
    {
      "comment_id": "char_1",
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


async def review_character(state: NovelState) -> dict:
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
        query_text="人物设定 " + " ".join(outline_item.get("characters", [])),
        n_results=3,
    )
    knowledge_docs = filter_by_distance(knowledge_results)
    knowledge_context = "\n".join(knowledge_docs) if knowledge_docs else ""

    messages = [
        {"role": "system", "content": CHARACTER_READER_PROMPT},
        {"role": "user", "content": f"""请审查第{chapter_number}章的人物塑造。

本章涉及人物：{', '.join(outline_item.get('characters', []))}

章节内容：
{chapter_draft}

{"人物设定参考：" + knowledge_context if knowledge_context else ""}

请从人物角度给出审查意见。"""},
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
            "reader_type": "character",
            "comments": [],
            "overall_score": 7,
            "overall_comment": "审查完成，但解析结果失败",
        }

    return result
