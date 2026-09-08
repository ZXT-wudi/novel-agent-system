import os
import re
import time
import asyncio
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.character_image import CharacterImage
from app.models.novel import Novel
from app.models.novel_image import NovelImage
from app.models.story_knowledge import StoryKnowledge
from app.llm.siliconflow import llm_client, LLMError

IMAGE_DIR = os.path.join("static", "character_images")
NOVEL_IMAGE_DIR = os.path.join("static", "novel_images")
os.makedirs(NOVEL_IMAGE_DIR, exist_ok=True)


def _sanitize_filename(name: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return safe[:50] if safe else "character"


def _build_image_prompt(character_name: str, description: str, role: str, world_style: str) -> str:
    desc = re.sub(r"\s+", " ", (description or "").strip())
    desc = desc[:300] if desc else "作品中的重要角色"
    role_text = (role or "").strip() or "主要角色"
    style_hint = world_style or "东方玄幻小说插画风格"
    en_core = (
        "High-quality half-body character portrait illustration, face and upper body in focus, "
        "cinematic lighting, clean solid background, highly detailed, no text, no watermark"
    )
    return (
        f"{en_core}. "
        f"为小说角色「{character_name}」（{role_text}）绘制半身肖像，"
        f"年龄、性别、发型发色、五官样貌、体型、服饰与气质必须与设定完全一致，禁止添加设定之外的元素。"
        f"角色设定：{desc}。画面风格：{style_hint}。画面中不出现任何文字。"
    )


async def _download_and_save(url: str, filepath: str):
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content

    def _write():
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(data)

    await asyncio.to_thread(_write)


async def generate_and_save_character_image(
    db: AsyncSession,
    novel_id: int,
    stage_index: int,
    character_name: str,
    description: str,
    role: str = "",
    world_style: str = "",
    force: bool = False,
) -> dict:
    existing = await db.execute(
        select(CharacterImage).where(
            CharacterImage.novel_id == novel_id,
            CharacterImage.stage_index == stage_index,
            CharacterImage.character_name == character_name,
        )
    )
    existing_record = existing.scalars().first()
    if existing_record and not force:
        return {"image_url": existing_record.image_path, "cached": True}

    prompt = _build_image_prompt(character_name, description, role, world_style)
    image_url = await llm_client.generate_image(prompt, image_size="1024x1024")

    safe_name = _sanitize_filename(character_name)
    filename = f"{novel_id}_{stage_index}_{safe_name}_{int(time.time())}.png"
    filepath = os.path.join(IMAGE_DIR, filename)
    relative_path = f"/static/character_images/{filename}"

    await _download_and_save(image_url, filepath)

    if existing_record:
        old_path = existing_record.image_path or ""
        if old_path.startswith("/static/"):
            try:
                os.remove(os.path.join("static", old_path[len("/static/"):]))
            except OSError:
                pass
        existing_record.image_path = relative_path
        existing_record.prompt = prompt
        await db.commit()
        return {"image_url": relative_path, "cached": False}

    record = CharacterImage(
        novel_id=novel_id,
        stage_index=stage_index,
        character_name=character_name,
        image_path=relative_path,
        prompt=prompt,
    )
    db.add(record)
    await db.commit()

    return {"image_url": relative_path, "cached": False}


async def get_character_image(db: AsyncSession, novel_id: int, stage_index: int, character_name: str) -> str | None:
    result = await db.execute(
        select(CharacterImage).where(
            CharacterImage.novel_id == novel_id,
            CharacterImage.stage_index == stage_index,
            CharacterImage.character_name == character_name,
        )
    )
    record = result.scalars().first()
    return record.image_path if record else None


def _genre_style(genre: str) -> str:
    g = genre or ""
    if any(k in g for k in ("仙侠", "玄幻", "修真")):
        return "东方玄幻古风"
    if "科幻" in g:
        return "科幻概念地图"
    if "都市" in g:
        return "现代都市"
    if "历史" in g:
        return "古风历史"
    return "史诗幻想"


async def _collect_world_text(db: AsyncSession, novel_id: int) -> str:
    result = await db.execute(
        select(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id)
    )
    parts = []
    for k in result.scalars().all():
        for elem in (k.world_elements or []):
            if not isinstance(elem, dict):
                continue
            name = elem.get("name", "")
            if name:
                parts.append(f"{name}：{elem.get('description', '')}")
    return "；".join(parts)[:900]


async def _collect_region_characters(db: AsyncSession, novel_id: int, region_name: str, limit: int = 5) -> list[str]:
    result = await db.execute(
        select(StoryKnowledge).where(StoryKnowledge.novel_id == novel_id)
    )
    matched = []
    for k in result.scalars().all():
        for char in (k.characters or []):
            if not isinstance(char, dict):
                continue
            name = char.get("name", "")
            if not name or name in matched:
                continue
            blob = f"{name}{char.get('traits', '')}{char.get('description', '')}"
            if region_name in blob:
                matched.append(name)
                if len(matched) >= limit:
                    return matched
    return matched


async def generate_and_save_world_map(db: AsyncSession, novel_id: int, force: bool = False) -> dict | None:
    existing = await db.execute(
        select(NovelImage).where(
            NovelImage.novel_id == novel_id,
            NovelImage.image_type == "world_map",
        )
    )
    existing_record = existing.scalars().first()
    if existing_record and not force:
        return {
            "image_url": f"/static/novel_images/{existing_record.image_path}",
            "prompt": existing_record.prompt or None,
        }

    novel_result = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_result.scalar_one_or_none()
    if not novel:
        return None

    title = (novel.title or "")[:100]
    genre = (novel.genre or "")[:50]
    outline = novel.full_outline or {}
    theme = str(outline.get("theme") or "")[:150]
    world_text = await _collect_world_text(db, novel_id)
    style = _genre_style(novel.genre)

    en_core = (
        "Epic fantasy world map illustration, hand-drawn ancient atlas style, "
        "aerial top-down view of a complete continent, mountains, rivers, coastlines, "
        "dense forests, deserts, volcanic wastelands, mystical realms and cities "
        "scattered naturally across the terrain, cinematic epic atmosphere, "
        "intricate details, high resolution, no text, no watermark, no labels"
    )
    cn_parts = [f"{style}风格的世界地图插画，俯瞰视角"]
    if title:
        cn_parts.append(f"《{title}》的世界全貌")
    if genre:
        cn_parts.append(f"题材：{genre}")
    if theme:
        cn_parts.append(f"主题：{theme}")
    if world_text:
        cn_parts.append(
            "地图中每一处地形、城池、秘境都必须来自以下世界观设定并与之一一对应"
            f"（设定为雪山则画雪山，设定为火山则画熔岩），禁止出现设定之外的地点：{world_text[:450]}"
        )
    cn_parts.append("画面中不出现任何文字")
    prompt = en_core + ". " + "。".join(cn_parts)

    image_url = await llm_client.generate_image(prompt, image_size="1344x768")

    filename = f"world_map_{novel_id}_{int(time.time())}.png"
    filepath = os.path.join(NOVEL_IMAGE_DIR, filename)
    await _download_and_save(image_url, filepath)

    if existing_record:
        existing_record.image_path = filename
        existing_record.prompt = prompt
    else:
        db.add(NovelImage(
            novel_id=novel_id,
            image_type="world_map",
            image_key="",
            image_path=filename,
            prompt=prompt,
        ))
    await db.commit()

    return {"image_url": f"/static/novel_images/{filename}", "prompt": prompt}


async def generate_and_save_region_image(
    db: AsyncSession,
    novel_id: int,
    region_name: str,
    description: str = "",
    force: bool = False,
) -> dict | None:
    region_name = (region_name or "").strip()
    existing = await db.execute(
        select(NovelImage).where(
            NovelImage.novel_id == novel_id,
            NovelImage.image_type == "region",
            NovelImage.image_key == region_name,
        )
    )
    existing_record = existing.scalars().first()
    if existing_record and not force:
        return {
            "image_url": f"/static/novel_images/{existing_record.image_path}",
            "prompt": existing_record.prompt or None,
        }

    novel_result = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_result.scalar_one_or_none()
    if not novel:
        return None

    related_chars = await _collect_region_characters(db, novel_id, region_name)
    world_text = await _collect_world_text(db, novel_id)
    style = _genre_style(novel.genre)

    en_core = (
        "Stunning fantasy landscape scene illustration, cinematic wide composition, "
        "environment and atmosphere consistent with the lore below, dramatic lighting, "
        "highly detailed, no text, no watermark"
    )
    cn_parts = [f"{style}风格区域场景插画，区域名称：{region_name}"]
    if description:
        cn_parts.append(
            "场景的地形、建筑、色彩与氛围必须与该描述严格一致，禁止偏离设定："
            f"{description[:250]}"
        )
    if world_text:
        cn_parts.append(f"世界观背景：{world_text[:250]}")
    if related_chars:
        cn_parts.append(f"可出现关联角色：{'、'.join(related_chars)}")
    cn_parts.append("画面中不出现任何文字")
    prompt = en_core + ". " + "。".join(cn_parts)

    image_url = await llm_client.generate_image(prompt, image_size="1024x1024")

    filename = f"region_{novel_id}_{int(time.time())}.png"
    filepath = os.path.join(NOVEL_IMAGE_DIR, filename)
    await _download_and_save(image_url, filepath)

    if existing_record:
        existing_record.image_path = filename
        existing_record.prompt = prompt
    else:
        db.add(NovelImage(
            novel_id=novel_id,
            image_type="region",
            image_key=region_name,
            image_path=filename,
            prompt=prompt,
        ))
    await db.commit()

    return {"image_url": f"/static/novel_images/{filename}", "prompt": prompt}


async def get_novel_image_maps(db: AsyncSession, novel_id: int) -> dict:
    result = await db.execute(
        select(NovelImage).where(NovelImage.novel_id == novel_id)
    )
    world_map = None
    world_map_prompt = None
    regions = {}
    region_prompts = {}
    for r in result.scalars().all():
        url = f"/static/novel_images/{r.image_path}"
        if r.image_type == "world_map":
            world_map = url
            world_map_prompt = r.prompt or None
        elif r.image_type == "region":
            regions[r.image_key] = url
            region_prompts[r.image_key] = r.prompt or None
    return {
        "world_map": world_map,
        "world_map_prompt": world_map_prompt,
        "regions": regions,
        "region_prompts": region_prompts,
    }
