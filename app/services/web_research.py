"""联网取材服务：基于 Tavily 搜索 + LLM 摘要，为全文大纲提供外部参考资料。

工作流程：
1. 根据小说标题/类型/描述构造多条搜索 query（世界观/同类作品/文化背景）
2. 调用 Tavily advanced 搜索，去重收集结果片段
3. 用 author LLM 把原始材料摘要成结构化参考资料（去广告/导航，提炼可借鉴设定）
4. 返回摘要文本；未配置 TAVILY_API_KEY 或全部失败时返回空串（不阻断流程）
"""

from typing import Optional
import asyncio
import httpx

from app.config import settings


def _build_search_queries(title: str, genre: str, description: str) -> list[str]:
    """根据标题/类型/描述构造多条搜索 query，覆盖世界观、同类作品、文化背景。"""
    base = f"{title} {genre}".strip()
    queries = []
    if description:
        seed = description[:80].replace("\n", " ").strip()
        queries.append(f"{base} 小说 设定 世界观 {seed}")
    else:
        queries.append(f"{base} 小说 设定 世界观 主题")
    queries.append(f"{base} 经典作品 推荐 设定参考")
    queries.append(f"{base} 历史背景 文化 资料设定")
    return queries


async def _tavily_search(query: str, max_results: int = 4) -> list[dict]:
    """调用 Tavily REST API 进行 advanced 搜索，返回 results 列表。

    直接使用 httpx 请求 https://api.tavily.com/search，不依赖 tavily-python 包，
    避免因运行环境未安装该包而失败。
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.TAVILY_API_KEY}",
    }
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "topic": "general",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search", json=payload, headers=headers
            )
    except httpx.TimeoutException:
        raise asyncio.TimeoutError()
    except httpx.ConnectError as e:
        raise RuntimeError(f"连接 Tavily 失败: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(
            f"Tavily API 返回 {resp.status_code}: {resp.text[:200]}"
        )

    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"解析 Tavily 响应失败: {e}") from e

    return data.get("results", []) or []


async def _summarize_with_llm(raw_text: str, title: str, genre: str, description: str) -> str:
    """用 author LLM 把原始搜索结果摘要成结构化参考资料。"""
    from app.llm.siliconflow import get_client

    client = get_client("author")
    system = (
        "你是一位小说创作研究员。根据提供的联网搜索原始材料，提炼出对创作小说有帮助的参考资料，"
        "包括：1）真实历史/文化/地理背景要点；2）同类经典作品的设定亮点与可借鉴手法；"
        "3）主题与冲突的常见范式。要求：只保留与创作相关的信息，去除广告/导航/无关内容；"
        "用简洁的中文要点输出，分条列出，总字数控制在 800 字以内。"
        "不要照搬原作人名地名，只提炼可借鉴的设定与方法。"
    )
    user = (
        f"小说标题：{title}\n"
        f"小说类型：{genre}\n"
        f"小说描述：{description}\n\n"
        f"联网搜索原始材料：\n{raw_text}\n\n"
        f"请提炼出参考资料（分条要点）："
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return await asyncio.wait_for(
        client.chat(messages, temperature=0.3, max_tokens=2048),
        timeout=120.0,
    )


async def research_for_outline(
    title: str,
    genre: str,
    description: str,
    max_results_per_query: int = 4,
    max_snippets: int = 8,
) -> str:
    """主入口：按标题/类型/描述联网取材，返回摘要后的参考资料文本。

    未配置 TAVILY_API_KEY 或全部失败时返回空串，不阻断后续大纲生成流程。
    """
    if not settings.TAVILY_API_KEY:
        return ""

    queries = _build_search_queries(title, genre, description)
    all_snippets: list[str] = []
    seen_urls: set[str] = set()
    search_errors: list[str] = []

    for q in queries:
        try:
            results = await _tavily_search(q, max_results=max_results_per_query)
        except asyncio.TimeoutError:
            search_errors.append(f"查询超时(30s): {q[:40]}")
            continue
        except Exception as e:
            search_errors.append(f"{type(e).__name__}: {str(e)[:120]}")
            continue
        for r in results:
            url = r.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title_r = r.get("title", "")
            content = r.get("content", "")
            if content:
                snippet = f"【{title_r}】({url})\n{content[:1500]}"
                all_snippets.append(snippet)
            if len(all_snippets) >= max_snippets:
                break
        if len(all_snippets) >= max_snippets:
            break

    if not all_snippets:
        if search_errors:
            raise RuntimeError(
                f"全部{len(queries)}个搜索查询均失败 — {'; '.join(search_errors)}"
            )
        return ""

    raw_text = "\n\n---\n\n".join(all_snippets)
    if len(raw_text) > 9000:
        raw_text = raw_text[:9000]

    print(f"[WEB-RESEARCH] research_for_outline: {len(all_snippets)} snippets collected, raw_text_len={len(raw_text)}")

    try:
        summary = await _summarize_with_llm(raw_text, title, genre, description)
        result = summary.strip()
        print(f"[WEB-RESEARCH] research_for_outline: summary_len={len(result)}, preview={result[:200]}")
        return result
    except Exception as e:
        print(f"[WEB-RESEARCH] research_for_outline: LLM summary failed ({e}), returning raw text")
        return raw_text[:2000]


async def research_for_outline_safe(
    title: str, genre: str, description: str
) -> tuple[str, Optional[str]]:
    """带错误信息的包装：返回 (参考资料文本, 错误信息或None)。

    未配置 key 时返回 ('', '未配置 TAVILY_API_KEY')，便于 API 层给前端明确提示。
    """
    if not settings.TAVILY_API_KEY:
        return "", "未配置 TAVILY_API_KEY，跳过联网取材"
    try:
        result = await research_for_outline(title, genre, description)
        if not result:
            return "", "联网取材搜索成功但未获取到有效内容（可能是搜索结果均为空或无正文）"
        return result, None
    except RuntimeError as e:
        return "", str(e)
    except Exception as e:
        return "", f"联网取材失败：{e}"


_STRUCTURE_SYSTEM_PROMPT = """你是知识库管理员。将以下参考资料结构化为知识库条目。

要求：
1. 只提取有价值的、可用于小说创作的设定信息
2. 每个条目必须包含 category、title、content 三个字段
3. category 只能是以下之一：worldview（世界观）、character（角色）、event（事件）、timeline（时间线）、faction（势力）、setting（其他设定）
4. title 简洁概括条目主题（不超过20字）
5. content 详细描述该设定（50-300字）
6. 一段参考资料可拆分为多个条目，但不要重复
7. 无价值的内容（广告、导航、无关信息）不要提取

输出格式：严格JSON数组，不要输出任何其他内容，不要使用markdown代码块：
[{"category": "worldview", "title": "条目标题", "content": "条目内容"}, ...]"""


async def _structure_to_entries(web_research_text: str, title: str, genre: str) -> list[dict]:
    """用 LLM 把联网取材摘要文本结构化为知识库条目列表。"""
    import json
    from app.llm.siliconflow import get_client

    client = get_client("author")
    user = (
        f"小说标题：{title}\n"
        f"小说类型：{genre}\n\n"
        f"参考资料：\n{web_research_text}\n\n"
        f"请结构化为知识库条目JSON数组："
    )
    messages = [
        {"role": "system", "content": _STRUCTURE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    import asyncio
    response = await asyncio.wait_for(
        client.chat(messages, temperature=0.3, max_tokens=4096),
        timeout=90.0,
    )

    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        entries = json.loads(text)
    except json.JSONDecodeError:
        first_bracket = text.find("[")
        last_bracket = text.rfind("]")
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            try:
                entries = json.loads(text[first_bracket:last_bracket + 1])
            except json.JSONDecodeError:
                print(f"[WEB-RESEARCH] _structure_to_entries JSON parse failed. Raw response (first 500 chars): {text[:500]}")
                return []
        else:
            print(f"[WEB-RESEARCH] _structure_to_entries no JSON array found. Raw response (first 500 chars): {text[:500]}")
            return []
    if not isinstance(entries, list):
        print(f"[WEB-RESEARCH] _structure_to_entries: LLM returned non-list type: {type(entries).__name__}")
        return []

    valid_categories = {"worldview", "character", "event", "timeline", "faction", "setting"}
    result = []
    rejected = 0
    for e in entries:
        if not isinstance(e, dict):
            rejected += 1
            continue
        cat = e.get("category", "")
        t = e.get("title", "")
        c = e.get("content", "")
        if cat in valid_categories and t and c:
            result.append({"category": cat, "title": t, "content": c})
        else:
            rejected += 1
    print(f"[WEB-RESEARCH] _structure_to_entries: parsed {len(entries)} entries, accepted {len(result)}, rejected {rejected}")
    return result


_CONTRADICTION_SYSTEM_PROMPT = """你是设定一致性审查员。判断新条目是否与已有条目存在事实矛盾。

判断标准：
- "矛盾"指新条目与已有条目在事实、设定、规则上存在直接冲突（如一个说主角是男性，另一个说主角是女性）
- 互补信息（如不同角度的描述）不算矛盾
- 如果新条目与已有条目无直接冲突，返回不矛盾
- 只判断同类别（category）内的矛盾

输出格式：严格JSON对象，不要输出任何其他内容：
{"contradicts": true或false, "reason": "矛盾原因简述，无矛盾时为空"}"""


async def _check_contradiction(new_entry: dict, existing_entries: list) -> bool:
    """用 LLM 判断新条目是否与同类别已有条目矛盾。返回 True=矛盾(跳过)，False=不矛盾(可保存)。"""
    if not existing_entries:
        return False

    import json
    from app.llm.siliconflow import get_client

    client = get_client("author")
    existing_text = "\n\n".join(
        f"[已有] 标题：{getattr(e, 'title', '')}\n内容：{getattr(e, 'content', '')}" for e in existing_entries
    )
    user = (
        f"新条目：\n标题：{new_entry['title']}\n内容：{new_entry['content']}\n\n"
        f"已有条目：\n{existing_text}\n\n"
        f"请判断新条目是否与已有条目矛盾："
    )
    messages = [
        {"role": "system", "content": _CONTRADICTION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    try:
        response = await asyncio.wait_for(
            client.chat(messages, temperature=0.1, max_tokens=512),
            timeout=15.0,
        )
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        result = json.loads(text)
        return bool(result.get("contradicts", False))
    except Exception:
        return False


async def save_web_research_to_kb(
    db,
    kb_id: int,
    web_research_text: str,
    title: str,
    genre: str,
) -> dict:
    """将联网取材结果结构化后保存到知识库，跳过与已有内容矛盾的条目。

    返回 {"saved": N, "skipped": M, "skipped_titles": [...]}
    """
    if not kb_id or not web_research_text:
        return {"saved": 0, "skipped": 0, "skipped_titles": [], "reason": "无知识库或无取材结果"}

    print(f"[WEB-RESEARCH] save_web_research_to_kb: kb_id={kb_id}, text_len={len(web_research_text)}, text_preview={web_research_text[:200]}")

    from app.services.kb_service import add_entry, list_entries

    try:
        candidates = await _structure_to_entries(web_research_text, title, genre)
    except Exception as e:
        return {"saved": 0, "skipped": 0, "skipped_titles": [], "reason": f"结构化失败：{e}"}

    if not candidates:
        return {"saved": 0, "skipped": 0, "skipped_titles": [], "reason": "无可提取条目"}

    existing = await list_entries(db, kb_id)
    by_category: dict[str, list] = {}
    for e in existing:
        by_category.setdefault(e.category, []).append(e)

    saved = 0
    skipped = 0
    skipped_titles: list[str] = []
    for entry in candidates:
        cat = entry["category"]
        same_cat = by_category.get(cat, [])
        try:
            is_contradict = await _check_contradiction(entry, same_cat)
        except Exception:
            is_contradict = False
        if is_contradict:
            skipped += 1
            skipped_titles.append(entry["title"])
            continue
        try:
            added = await add_entry(
                db, kb_id, cat, entry["title"], entry["content"],
                attributes={"source_query": title}, source="web_research",
            )
            if added:
                saved += 1
                same_cat.append(added)
            else:
                skipped += 1
                skipped_titles.append(entry["title"])
        except Exception:
            skipped += 1
            skipped_titles.append(entry["title"])

    return {"saved": saved, "skipped": skipped, "skipped_titles": skipped_titles}
