from app.llm.siliconflow import LLMError, get_client

llm_client = get_client("author")
from app.rag.retriever import query_collection
import json


async def rewrite_section(
    novel_id: int,
    original_text: str,
    instruction: str,
    chapter_context: str = "",
    outline_context: str = "",
) -> dict:
    rag_context = ""
    try:
        pref_results = await query_collection(novel_id, "user_preferences", instruction, n_results=3)
        pref_docs = pref_results.get("documents", [[]])[0]
        knowledge_results = await query_collection(novel_id, "world_knowledge", instruction, n_results=3)
        knowledge_docs = knowledge_results.get("documents", [[]])[0]
        parts = []
        if pref_docs:
            parts.append("用户写作偏好：\n" + "\n".join(pref_docs))
        if knowledge_docs:
            parts.append("世界观参考：\n" + "\n".join(knowledge_docs))
        rag_context = "\n\n".join(parts)
    except Exception:
        pass

    context_section = ""
    if chapter_context:
        context_section += f"\n章节上下文（前后文）：\n{chapter_context[:2000]}"
    if outline_context:
        context_section += f"\n大纲参考：\n{outline_context[:1000]}"
    if rag_context:
        context_section += f"\n{rag_context}"

    messages = [
        {
            "role": "system",
            "content": """你是一位小说修订专家。用户会给你一段原文和修改方向，你需要根据修改方向重写这段内容。

要求：
1. 保持与上下文的衔接和连贯性
2. 遵循用户的修改方向，但可以适度发挥
3. 保持人物性格一致性
4. 保持文风统一
5. 只输出重写后的内容，不要解释或加标注""",
        },
        {
            "role": "user",
            "content": f"""请重写以下内容：

【原文】
{original_text}

【修改方向】
{instruction}
{context_section}

请输出重写后的内容：""",
        },
    ]

    rewritten = await llm_client.chat(messages, temperature=0.7, max_tokens=4096)

    return {
        "original_text": original_text,
        "rewritten_text": rewritten,
        "instruction": instruction,
    }


async def rewrite_section_stream(
    novel_id: int,
    original_text: str,
    instruction: str,
    chapter_context: str = "",
    outline_context: str = "",
):
    rag_context = ""
    try:
        pref_results = await query_collection(novel_id, "user_preferences", instruction, n_results=3)
        pref_docs = pref_results.get("documents", [[]])[0]
        knowledge_results = await query_collection(novel_id, "world_knowledge", instruction, n_results=3)
        knowledge_docs = knowledge_results.get("documents", [[]])[0]
        parts = []
        if pref_docs:
            parts.append("用户写作偏好：\n" + "\n".join(pref_docs))
        if knowledge_docs:
            parts.append("世界观参考：\n" + "\n".join(knowledge_docs))
        rag_context = "\n\n".join(parts)
    except Exception:
        pass

    context_section = ""
    if chapter_context:
        context_section += f"\n章节上下文（前后文）：\n{chapter_context[:2000]}"
    if outline_context:
        context_section += f"\n大纲参考：\n{outline_context[:1000]}"
    if rag_context:
        context_section += f"\n{rag_context}"

    messages = [
        {
            "role": "system",
            "content": """你是一位小说修订专家。用户会给你一段原文和修改方向，你需要根据修改方向重写这段内容。

要求：
1. 保持与上下文的衔接和连贯性
2. 遵循用户的修改方向，但可以适度发挥
3. 保持人物性格一致性
4. 保持文风统一
5. 只输出重写后的内容，不要解释或加标注""",
        },
        {
            "role": "user",
            "content": f"""请重写以下内容：

【原文】
{original_text}

【修改方向】
{instruction}
{context_section}

请输出重写后的内容：""",
        },
    ]

    async for chunk in llm_client.chat_stream(messages, temperature=0.7, max_tokens=4096):
        yield chunk
