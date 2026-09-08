from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user_preference import UserPreference, ModificationRecord
from app.rag.retriever import add_to_collection, delete_from_collection, query_collection
from app.schemas.preference import PreferenceCreate, KnowledgeCreate


async def add_preference(db: AsyncSession, novel_id: int, data: PreferenceCreate) -> UserPreference:
    pref = UserPreference(
        novel_id=novel_id,
        preference_type=data.preference_type,
        preference_key=data.preference_key,
        preference_value=data.preference_value,
        source=data.source,
        weight=data.weight,
    )
    db.add(pref)
    await db.commit()
    await db.refresh(pref)

    await add_to_collection(
        novel_id=novel_id,
        collection_type="user_preferences",
        documents=[f"{data.preference_type}: {data.preference_key} - {data.preference_value}"],
        ids=[f"pref_{pref.id}"],
        metadatas=[{"type": data.preference_type, "key": data.preference_key}],
    )

    return pref


async def get_preferences(db: AsyncSession, novel_id: int) -> list[UserPreference]:
    result = await db.execute(
        select(UserPreference).where(UserPreference.novel_id == novel_id).order_by(UserPreference.created_at.desc())
    )
    return result.scalars().all()


async def delete_preference(db: AsyncSession, novel_id: int, pref_id: int) -> bool:
    result = await db.execute(select(UserPreference).where(UserPreference.id == pref_id, UserPreference.novel_id == novel_id))
    pref = result.scalar_one_or_none()
    if not pref:
        return False

    await delete_from_collection(novel_id, "user_preferences", [f"pref_{pref.id}"])
    await db.delete(pref)
    await db.commit()
    return True


async def add_knowledge(novel_id: int, data: KnowledgeCreate) -> dict:
    doc_text = f"{data.category} - {data.name}: {data.content}"
    doc_id = f"knowledge_{data.category}_{data.name}"

    await add_to_collection(
        novel_id=novel_id,
        collection_type="world_knowledge",
        documents=[doc_text],
        ids=[doc_id],
        metadatas=[{
            "category": data.category,
            "name": data.name,
            "related_characters": data.related_characters,
        }],
    )

    return {"id": doc_id, "category": data.category, "name": data.name, "content": data.content, "related_characters": data.related_characters}


async def get_knowledge(novel_id: int) -> list[dict]:
    from app.rag.chroma_client import chroma_client, get_novel_collection_name

    collection_name = get_novel_collection_name(novel_id, "world_knowledge")
    try:
        collection = chroma_client.get_collection(collection_name)
        result = collection.get(include=["metadatas", "documents"])
        items = []
        for i, doc_id in enumerate(result["ids"]):
            items.append({
                "id": doc_id,
                "category": result["metadatas"][i].get("category", ""),
                "name": result["metadatas"][i].get("name", ""),
                "content": result["documents"][i] if result["documents"] else "",
                "related_characters": result["metadatas"][i].get("related_characters", []),
            })
        return items
    except Exception:
        return []


async def get_modification_records(db: AsyncSession, novel_id: int, limit: int = 20) -> list[ModificationRecord]:
    result = await db.execute(
        select(ModificationRecord)
        .where(ModificationRecord.novel_id == novel_id)
        .order_by(ModificationRecord.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def learn_from_modifications(db: AsyncSession, novel_id: int):
    records = await get_modification_records(db, novel_id, limit=50)
    if not records:
        return

    style_patterns = {}
    for record in records:
        mod_type = record.modification_type or "general"
        if mod_type not in style_patterns:
            style_patterns[mod_type] = []
        style_patterns[mod_type].append({
            "original": record.original_text[:200],
            "modified": record.modified_text[:200],
            "decision": record.user_decision,
        })

    for mod_type, patterns in style_patterns.items():
        summary = f"用户在{mod_type}方面的修改偏好："
        for p in patterns[:5]:
            summary += f"\n原文倾向：{p['original']}... → 修改倾向：{p['modified']}... (决策：{p['decision']})"

        pref = UserPreference(
            novel_id=novel_id,
            preference_type="learned_style",
            preference_key=f"learned_{mod_type}",
            preference_value=summary,
            source="inferred",
            weight=0.5,
        )
        db.add(pref)

        await add_to_collection(
            novel_id=novel_id,
            collection_type="user_preferences",
            documents=[summary],
            ids=[f"learned_{mod_type}_{novel_id}"],
            metadatas=[{"type": "learned_style", "key": f"learned_{mod_type}"}],
        )

    await db.commit()
