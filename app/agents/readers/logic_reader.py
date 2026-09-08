from app.llm.siliconflow import llm_client
from app.rag.retriever import query_collection, filter_by_distance
from app.agents.state import NovelState
import json


LOGIC_READER_PROMPT = """你是一位资深小说编辑，专注于小说逻辑自洽性审查，擅长发现设定、因果、时空与信息层面的硬伤。

【审查准则】
- 只报告真实的逻辑硬伤，不苛求小说的现实可行性——小说允许艺术夸张与虚构，审查的是作品"内在自洽"而非"符合现实"；
- 区分硬伤与可接受的虚构：力量体系、世界规则内的设定矛盾是硬伤；为叙事服务的合理虚构不是问题；
- 每条意见必须指出具体矛盾点（哪一处与哪一处冲突），suggestion 给出可执行的修正方向；
- 不臆测未交代的信息，不因"作者没写"就判定为逻辑漏洞。

【审查维度】
1. 设定一致性：是否与已建立的世界观规则矛盾（力量体系与上限、社会规则、地理设定、种族特性等）；是否出现前后设定打架。
2. 因果逻辑：事件之间的因果关系是否成立，是否存在"因为剧情需要所以发生"的硬凑；关键转折是否有合理铺垫。
3. 时间线：时间顺序、时长是否矛盾（昼夜、季节、经过天数、角色年龄增长等）；倒叙插叙是否清晰可解。
4. 空间逻辑：地点转换是否合理，人物位移在给定时间与手段下是否可能；场景空间关系是否自洽。
5. 信息一致性：前后文信息是否矛盾，角色是否"知道不该知道的"或"忘记该知道的"，设定陈述前后是否一致。
6. 文笔与AI腔：对白与叙述是否出现以下问题——（a）破折号"——"符号（无论用于心理状态、解释说明、语气转折、补充动作还是任何用途都属违规）；（b）"不是……"析因/翻转句（含"不是……而是……""不是因为……"等用"不是"拆解因果的用法）；（c）排比堆砌、刻板过渡词等AI腔句式；（d）"像...""如同...""仿佛...""犹如...""好似..."等明喻句式——不得用"像"字做环境描写或心理描写，应直接写出事物状态和角色情绪；（e）无意义的修饰性句子——纯装饰、零信息量（如"月光洒落在地上，给大地披上一层银纱"这类仅为美化而存在、不推动剧情不揭示人物不传递信息的句子）；以上句式降低文本自然度，须标记并建议改写为直白、准确的表述。

【严重程度判定】
- high：设定体系矛盾、因果断裂导致情节不成立、时间线硬伤；
- medium：局部因果稍弱、空间转换略突兀；
- low：细节小矛盾，不影响理解。
- AI腔句式（破折号"——"符号、"不是……"析因/翻转句、排比堆砌、"像..."明喻句式、无意义修饰句等）统一记为 medium。

输出格式（严格JSON）：
{
  "reader_type": "logic",
  "comments": [
    {
      "comment_id": "logic_1",
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


async def review_logic(state: NovelState) -> dict:
    novel_id = state.get("novel_id", 0)
    chapter_draft = state.get("chapter_draft", "")
    chapter_number = state.get("current_chapter_number", 1)
    previous_semantics = state.get("previous_semantics", [])
    outline = state.get("outline", [])

    outline_item = {}
    for item in outline:
        if item.get("chapter_number") == chapter_number:
            outline_item = item
            break

    knowledge_results = await query_collection(
        novel_id=novel_id,
        collection_type="world_knowledge",
        query_text="世界观设定 规则 体系",
        n_results=5,
    )
    knowledge_docs = filter_by_distance(knowledge_results)
    knowledge_context = "\n".join(knowledge_docs) if knowledge_docs else ""

    previous_context = ""
    if previous_semantics:
        parts = []
        for sem in previous_semantics:
            parts.append(f"第{sem.get('chapter_number', '?')}章：{sem.get('summary', '')} 关键词：{', '.join(sem.get('keywords', []))}")
        previous_context = "前文语义摘要：\n" + "\n".join(parts)

    messages = [
        {"role": "system", "content": LOGIC_READER_PROMPT},
        {"role": "user", "content": f"""请审查第{chapter_number}章的逻辑自洽性。

章节内容：
{chapter_draft}

{"世界观设定参考：" + knowledge_context if knowledge_context else ""}
{previous_context if previous_context else ""}

请从逻辑角度给出审查意见。"""},
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
            "reader_type": "logic",
            "comments": [],
            "overall_score": 7,
            "overall_comment": "审查完成，但解析结果失败",
        }

    return result
