from app.llm.siliconflow import llm_client
from app.rag.retriever import query_collection, filter_by_distance
from app.agents.state import NovelState
import json


STYLE_READER_PROMPT = """你是一位资深小说编辑，专注于文笔自然度与AI腔审查，对文本的句式、节奏、表达惯性有敏锐判断。

【审查准则】
- 只报告真实存在的文笔与AI腔问题，不为凑数而提意见，不苛求文采华丽；
- 每条意见必须具体到章节中的位置或语句，suggestion 给出可直接替换的改写示例，而非"建议优化"这类空话；
- 聚焦本章可见的句式与表达问题，不臆测未发生章节；
- 破折号"——"是绝对禁止符号，正文出现即算问题，不存在"可接受"的破折号；排比须区分有意的修辞与无意识的AI腔，机械堆砌与套路化才是问题。

【审查维度】
1. 破折号符号：正文是否出现"——"符号本身（无论用于心理状态、解释说明、语气转折、补充动作还是任何用途都属违规）；出现即须标记并建议改写为独立短句或逗号/句号分句；
2. 析因/翻转句式：是否滥用一切"不是……"析因/翻转句（含"不是……而是……""不是因为……"等用"不是"拆解因果、做分析腔陈述的用法），是否可改为直接陈述；
3. 排比堆砌与机械对仗：是否为对仗而对仗、为排比而排比、堆砌形容词的华丽空转、无信息增量的总结句；
4. 空洞华丽修辞：是否使用故作高深、华而不实的生造比喻与通感——如"瞳孔像是淬了火的灰玻璃""目光疯狂闪烁""心跳成了一串失序的鼓点"等看不懂、读不顺的炫技式描写；此类修辞无叙事价值，须建议改为直白可感的朴素表达，suggestion 给出具体改写示例；
5. 单句堆砌修辞：是否在同一句里叠摞比喻、通感、拟人、排比等多种修辞手法，造成句子臃肿、华而不实；一个比喻用完即止，不应在尾巴上再挂一个，须建议拆分或精简；
6. 解释式句式：是否出现"前半句抛出某个东西、后半句解释这个东西"的套路——如"他眼中闪过一丝光，那是一种前所未有的坚定""她嘴角微微上扬，那是一个只有她自己才懂的笑"；此类写法须建议直接把意思写进前半句，不拆成两句做注解，suggestion 给出合并改写示例；
7. 刻板过渡词与套话：是否出现"综上所述、由此可见、不难发现、值得一提的是、不言而喻、众所周知、与此同时"等AI过渡腔；
8. 欧化长难句与翻译腔：是否把口语能说清的事绕成从句套从句的长难句；
9. 章末机械升华收束：是否出现"这一夜，注定不平静""命运的齿轮悄然转动""谁也没有想到，这一切只是开始"等套式收束。
10. 明喻句式全面禁用：是否使用"像...""如同...""仿佛...""犹如...""好似..."等明喻句式做环境描写或心理描写——不得用"像"字绕弯，应直接写出事物状态和角色情绪；suggestion 给出删除比喻后的直白改写示例；
11. 无意义修饰句：是否出现纯装饰、零信息量的修饰性句子（如"月光洒落在地上，给大地披上一层银纱"这类仅为美化而存在、不推动剧情不揭示人物不传递信息的句子）；suggestion 给出删除该句后的效果或改写为有信息量的句子；

【严重程度判定】
- high：整章句式机械化、AI腔密集到影响可读性；
- medium：出现破折号"——"符号、"不是……"析因/翻转句、排比堆砌、空洞华丽修辞、单句堆砌修辞、解释式句式等，须改写；
- low：个别句式稍显套路，不影响整体阅读。
- AI腔句式（出现破折号"——"符号、"不是……"析因/翻转句、排比堆砌、空洞华丽修辞、单句堆砌修辞、解释式句式、"像..."明喻句式、无意义修饰句等）统一记为 medium 起步。

输出格式（严格JSON）：
{
  "reader_type": "style",
  "comments": [
    {
      "comment_id": "style_1",
      "aspect": "审查维度",
      "comment": "具体问题描述（附原文片段）",
      "suggestion": "改写示例",
      "severity": "high/medium/low"
    }
  ],
  "overall_score": 8,
  "overall_comment": "总体评价"
}

只输出JSON，不要输出其他内容。"""


async def review_style(state: NovelState) -> dict:
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
        query_text="写作风格 文笔 句式",
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
        {"role": "system", "content": STYLE_READER_PROMPT},
        {"role": "user", "content": f"""请审查第{chapter_number}章的文笔自然度与AI腔。

章节内容：
{chapter_draft}

{"世界观设定参考：" + knowledge_context if knowledge_context else ""}
{previous_context if previous_context else ""}

请从文笔与AI腔角度给出审查意见。"""},
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
            "reader_type": "style",
            "comments": [],
            "overall_score": 7,
            "overall_comment": "审查完成，但解析结果失败",
        }

    return result
