from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.models.novel import Novel
from app.models.chapter import Chapter, ChapterVersion
from app.models.chapter_semantic import ChapterSemantic
from app.models.story_knowledge import StoryKnowledge
from app.models.user_preference import UserPreference, ModificationRecord
from app.models.novel_image import NovelImage
from app.models.character_image import CharacterImage
from app.schemas.novel import NovelCreate, NovelListResponse
from app.rag.chroma_client import chroma_client, get_novel_collection_name
from app.rag.retriever import delete_novel_collections
import json
import os
import asyncio
import logging
from app.llm.siliconflow import LLMError, get_client

logger = logging.getLogger(__name__)
llm_client = get_client("author")

_LENGTH_THRESHOLD = 500000


def derive_length_type(target_word_count, stored=None) -> str:
    twc = target_word_count or 0
    if twc > 0:
        return "long" if twc >= _LENGTH_THRESHOLD else "short"
    return stored or "short"


async def create_novel(db: AsyncSession, data: NovelCreate) -> Novel:
    novel = Novel(
        title=data.title,
        genre=data.genre,
        description=data.description,
        length_type=data.length_type or "short",
        writing_style=data.writing_style or "直白、紧凑、重心理与动作",
        target_word_count=data.target_word_count,
        narrative_pov=data.narrative_pov or "第三人称",
        knowledge_base_id=data.knowledge_base_id,
        ordinary_knowledge_base_id=data.ordinary_knowledge_base_id,
        world_settings=data.world_settings or {},
        characters=data.characters or [],
        outline=[],
        full_outline={},
        status="planning",
    )
    db.add(novel)
    await db.commit()
    await db.refresh(novel)

    for collection_type in ["user_preferences", "chapter_semantics", "world_knowledge"]:
        collection_name = get_novel_collection_name(novel.id, collection_type)
        await asyncio.to_thread(chroma_client.get_or_create_collection, collection_name)

    return novel


async def get_novel(db: AsyncSession, novel_id: int) -> Novel | None:
    result = await db.execute(select(Novel).where(Novel.id == novel_id))
    return result.scalar_one_or_none()


async def get_novels(db: AsyncSession) -> list[NovelListResponse]:
    chapter_count_subq = (
        select(Chapter.novel_id, func.count(Chapter.id).label("chapter_count"))
        .group_by(Chapter.novel_id)
        .subquery()
    )
    result = await db.execute(
        select(
            Novel,
            func.coalesce(chapter_count_subq.c.chapter_count, 0).label("chapter_count"),
        )
        .outerjoin(chapter_count_subq, Novel.id == chapter_count_subq.c.novel_id)
        .order_by(Novel.created_at.desc())
    )
    responses = []
    for novel, chapter_count in result.all():
        responses.append(NovelListResponse(
            id=novel.id,
            title=novel.title,
            genre=novel.genre,
            length_type=derive_length_type(novel.target_word_count, novel.length_type),
            target_word_count=novel.target_word_count,
            status=novel.status,
            chapter_count=chapter_count,
            created_at=novel.created_at,
        ))
    return responses


async def delete_novel(db: AsyncSession, novel_id: int) -> bool:
    novel = await get_novel(db, novel_id)
    if not novel:
        return False

    novel_images = (await db.execute(
        select(NovelImage.image_path).where(NovelImage.novel_id == novel_id)
    )).scalars().all()
    character_images = (await db.execute(
        select(CharacterImage.image_path).where(CharacterImage.novel_id == novel_id)
    )).scalars().all()

    await db.execute(delete(ModificationRecord).where(ModificationRecord.novel_id == novel_id))
    await db.execute(delete(UserPreference).where(UserPreference.novel_id == novel_id))
    await db.execute(delete(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id))
    await db.execute(delete(ChapterSemantic).where(ChapterSemantic.novel_id == novel_id))
    await db.execute(delete(ChapterVersion).where(ChapterVersion.chapter_id.in_(
        select(Chapter.id).where(Chapter.novel_id == novel_id)
    )))
    await db.execute(delete(Chapter).where(Chapter.novel_id == novel_id))
    await db.execute(delete(NovelImage).where(NovelImage.novel_id == novel_id))
    await db.execute(delete(CharacterImage).where(CharacterImage.novel_id == novel_id))
    await db.delete(novel)
    await db.commit()

    await delete_novel_collections(novel_id)

    for path in novel_images:
        full = os.path.join("static", "novel_images", path or "")
        if path and os.path.exists(full):
            try:
                os.remove(full)
            except OSError:
                logger.warning("删除小说图片失败: %s", full, exc_info=True)
    for path in character_images:
        filename = (path or "").replace("/static/character_images/", "").replace("static/character_images/", "").lstrip("/")
        full = os.path.join("static", "character_images", filename)
        if filename and os.path.exists(full):
            try:
                os.remove(full)
            except OSError:
                logger.warning("删除角色图片失败: %s", full, exc_info=True)

    return True


async def update_novel_status(db: AsyncSession, novel_id: int, status: str) -> Novel | None:
    novel = await get_novel(db, novel_id)
    if not novel:
        return None
    novel.status = status
    await db.commit()
    await db.refresh(novel)
    return novel


EXPAND_QA_SYSTEM_PROMPT = """你是一位资深小说设定架构师，擅长根据用户的简单问答信息，扩写出丰富、完整且自洽的小说设定。

【设定扩写准则】
- 忠于用户输入：用户的问答信息是设定基线，扩写是丰富而非推翻；
- 内在自洽：世界观、力量体系、社会规则、角色背景之间须互不矛盾，能自圆其说；
- 题材保真：若用户已指定题材（玄幻/都市/科幻/历史/同人等），必须保留；同人类题材须在世界观与角色设定中体现原作的基础设定与角色关系；
- 简介吸引力：扩写后的简介要能勾起阅读兴趣，点明核心冲突或悬念，避免平铺直叙；
- 角色立体：主角设定有动机、有性格、有背景，避免扁平标签化；
- 风格与人称：从用户的写作风格描述中准确推断叙事人称，保留用户指定的风格、字数、篇幅类型。

【创作约束（必须遵守）】
- 目标字数与篇幅类型以用户输入为准：target_word_count 必须等于用户给出的目标字数，length_type 须根据目标字数判定（≥500000为long，否则short），不得擅自更改或自行臆造；
- 同人还原：同人类题材必须严格还原原作核心设定、力量体系与角色关系，角色不得OOC（out of character），不得擅自改变原作已确立的事实；
- 设定自洽：力量体系/社会规则/角色背景/时代背景之间不得出现逻辑矛盾，每一项设定都需能互相印证；
- 禁忌雷区：避免烂俗套路——拒绝无脑后宫、过度金手指、无逻辑升级、降智反派、工具人配角等网文通病；
- 角色动机：每个角色（含配角）必须有清晰的行动动机与性格逻辑，角色行为需符合其性格设定，避免为推动剧情而强行OOC；
- 冲突层次：核心冲突需有表层（具体事件/对手）与深层（价值观/主题命题）两个层次，避免单一扁平的打怪升级模式。

你的职责：
1. 根据用户提供的问答信息和标题，扩写出丰富、引人入胜的简介（200-400字），点明核心冲突或悬念
2. 构建完整世界观，包含时代背景、主要地点、世界规则、关键元素
3. 设计力量体系：修炼等级/能力分类/力量来源/上限约束（玄幻科幻类必备，都市言情类可弱化但需有内在逻辑）
4. 设计社会结构：主要势力组织、阶层划分、权力格局（体现世界的社会运作方式）
5. 明确核心冲突：主角与谁对抗、表层冲突是什么、深层主题冲突是什么
6. 点明主题思想：这个故事想探讨什么命题（如成长、自由、正义、人性等）
7. 设计至少一位主角的设定，包含姓名、角色定位、性格特点、背景故事、行动动机
8. 从用户的写作风格描述中推断叙事人称（第一人称/第三人称/第二人称）
9. 保留用户指定的写作风格、目标字数、篇幅类型
10. 若用户已指定题材类型（如玄幻/都市/科幻/历史/同人等），必须保留该题材，不要更改；同人类题材应在世界观与角色设定中体现原作的基础设定与角色关系

输出格式要求（严格JSON对象，不要输出任何其他内容，不要使用markdown代码块）：
{
  "title": "精炼后的标题（可保留原标题）",
  "genre": "推断的小说类型，如 玄幻/都市/科幻/历史/言情",
  "description": "扩写后的丰富简介，200-400字，点明核心冲突或悬念",
  "world_settings": {
    "era": "时代背景",
    "location": "主要地点",
    "rules": "世界规则或基本法则",
    "key_elements": ["关键元素1", "关键元素2"],
    "power_system": "力量体系：修炼等级/能力分类/力量来源/上限约束（如无力量体系则描述该世界的核心规则体系）",
    "social_structure": "社会结构：主要势力/阶层划分/权力格局",
    "core_conflict": "核心冲突：主角vs谁、表层冲突、深层主题冲突",
    "theme": "主题思想：故事想探讨的命题"
  },
  "characters": [
    {
      "name": "主角姓名",
      "role": "主角",
      "personality": "性格特点",
      "background": "背景故事",
      "motivation": "行动动机与核心目标"
    }
  ],
  "writing_style": "写作风格",
  "target_word_count": 800000,
  "narrative_pov": "第三人称",
  "length_type": "long"
}

只输出JSON对象，不要输出其他内容。"""


def _parse_expand_response(response: str, title: str, writing_style: str, target_word_count: int, length_type: str) -> dict:
    response_clean = response.strip()
    if response_clean.startswith("```"):
        lines = response_clean.split("\n")
        response_clean = "\n".join(lines[1:-1])
    try:
        result = json.loads(response_clean)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM返回内容无法解析为JSON: {str(e)}")

    if not isinstance(result, dict):
        raise LLMError("LLM返回内容不是有效的JSON对象")

    pov = result.get("narrative_pov")
    if not pov and writing_style:
        for keyword, pov_value in [("第一人称", "第一人称"), ("第一视角", "第一人称"), ("第二人称", "第二人称"), ("第三人称", "第三人称"), ("第三视角", "第三人称")]:
            if keyword in writing_style:
                pov = pov_value
                break

    raw_title = result.get("title")
    parsed_title = raw_title.strip() if isinstance(raw_title, str) else raw_title

    final_twc = target_word_count if target_word_count else result.get("target_word_count") or 0
    try:
        final_twc = int(final_twc)
    except (TypeError, ValueError):
        final_twc = target_word_count or 0
    derived_length = "long" if final_twc >= 500000 else "short"
    logger.debug("[PARSE-EXPAND] target_word_count param=%s, LLM result.get=%s, final_twc=%s, derived_length=%s",
                 target_word_count, result.get("target_word_count"), final_twc, derived_length)

    return {
        "title": parsed_title or title,
        "genre": result.get("genre") or "",
        "description": result.get("description") or "",
        "world_settings": result.get("world_settings") or {},
        "characters": result.get("characters") or [],
        "writing_style": result.get("writing_style") or writing_style,
        "target_word_count": final_twc,
        "narrative_pov": pov or "第三人称",
        "length_type": derived_length,
    }


async def expand_novel_from_qa(db: AsyncSession, title: str, content: str, writing_style: str, target_word_count: int, length_type: str, genre: str = "", knowledge_base_id: int = 0) -> dict:
    kb_context = ""
    if knowledge_base_id:
        try:
            from app.services.kb_service import build_kb_context_for_agent
            kb_context = await build_kb_context_for_agent(db, knowledge_base_id, content, comprehensive=True, toc_mode=True)
        except Exception as e:
            logger.warning("[KB] 扩写时知识库读取失败: %s", e, exc_info=True)

    kb_section = f"\n\n=== 原作知识库参考（同人创作必须严格遵循原作设定，不得违背） ===\n{kb_context}" if kb_context else ""

    messages = [
        {"role": "system", "content": EXPAND_QA_SYSTEM_PROMPT},
        {"role": "user", "content": f"""请根据以下问答信息扩写小说设定：

小说标题：{title}
题材类型：{genre or "未指定，请根据内容推断"}
写作风格：{writing_style}
目标字数：{target_word_count}
篇幅类型：{length_type}

用户问答信息：
{content}{kb_section}

请扩写出完整的小说设定JSON。"""},
    ]
    response = await llm_client.chat(messages, temperature=0.8, max_tokens=8192)
    return _parse_expand_response(response, title, writing_style, target_word_count, length_type)
