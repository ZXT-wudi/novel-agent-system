import asyncio
from app.rag.chroma_client import chroma_client, get_novel_collection_name, get_kb_collection_name
from app.rag.embedder import embed_single, embed_texts
import logging

logger = logging.getLogger(__name__)


async def add_to_collection(novel_id: int, collection_type: str, documents: list[str], ids: list[str], metadatas: list[dict] | None = None):
    collection_name = get_novel_collection_name(novel_id, collection_type)
    collection = await asyncio.to_thread(chroma_client.get_or_create_collection, collection_name)
    embeddings = await embed_texts(documents)
    await asyncio.to_thread(
        collection.add,
        documents=documents,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas or [{}] * len(documents),
    )


async def upsert_to_collection(novel_id: int, collection_type: str, documents: list[str], ids: list[str], metadatas: list[dict] | None = None):
    collection_name = get_novel_collection_name(novel_id, collection_type)
    collection = await asyncio.to_thread(chroma_client.get_or_create_collection, collection_name)
    embeddings = await embed_texts(documents)
    await asyncio.to_thread(
        collection.upsert,
        documents=documents,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas or [{}] * len(documents),
    )


async def query_collection(novel_id: int, collection_type: str, query_text: str, n_results: int = 5, where: dict | None = None) -> dict:
    collection_name = get_novel_collection_name(novel_id, collection_type)
    try:
        collection = await asyncio.to_thread(chroma_client.get_collection, collection_name)
    except Exception:
        logger.debug("RAG集合不存在或不可用: %s", collection_name, exc_info=True)
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    query_embedding = await embed_single(query_text)
    if not query_embedding:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
    }
    if where:
        kwargs["where"] = where
    return await asyncio.to_thread(collection.query, **kwargs)


async def delete_from_collection(novel_id: int, collection_type: str, ids: list[str]):
    collection_name = get_novel_collection_name(novel_id, collection_type)
    try:
        collection = await asyncio.to_thread(chroma_client.get_collection, collection_name)
        await asyncio.to_thread(collection.delete, ids=ids)
    except Exception:
        logger.warning("从集合删除失败: %s ids=%s", collection_name, ids, exc_info=True)


async def update_in_collection(novel_id: int, collection_type: str, ids: list[str], documents: list[str], metadatas: list[dict] | None = None):
    collection_name = get_novel_collection_name(novel_id, collection_type)
    try:
        collection = await asyncio.to_thread(chroma_client.get_collection, collection_name)
        embeddings = await embed_texts(documents)
        kwargs = {
            "ids": ids,
            "documents": documents,
            "embeddings": embeddings,
        }
        if metadatas:
            kwargs["metadatas"] = metadatas
        await asyncio.to_thread(collection.update, **kwargs)
    except Exception:
        logger.warning("更新集合失败: %s ids=%s", collection_name, ids, exc_info=True)


async def delete_novel_collections(novel_id: int):
    for collection_type in ["user_preferences", "chapter_semantics", "world_knowledge"]:
        collection_name = get_novel_collection_name(novel_id, collection_type)
        try:
            await asyncio.to_thread(chroma_client.delete_collection, collection_name)
        except Exception:
            logger.warning("删除小说集合失败: %s", collection_name, exc_info=True)


def filter_by_distance(result: dict, threshold: float = 0.6) -> list[str]:
    if not result:
        return []
    docs = result.get("documents", [[]])[0] or []
    dists = result.get("distances", [[]])[0] or []
    if not docs:
        return []
    if len(dists) != len(docs):
        return docs
    paired = list(zip(docs, dists))
    kept = [d for d, dist in paired if dist <= threshold]
    if not kept:
        paired.sort(key=lambda x: x[1])
        kept = [paired[0][0]]
    return kept


async def add_to_kb(kb_id: int, documents: list[str], ids: list[str], metadatas: list[dict] | None = None, embeddings: list[list[float]] | None = None):
    collection_name = get_kb_collection_name(kb_id)
    collection = await asyncio.to_thread(chroma_client.get_or_create_collection, collection_name)
    if embeddings is None:
        embeddings = await embed_texts(documents)
    await asyncio.to_thread(
        collection.add,
        documents=documents,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas or [{}] * len(documents),
    )


async def query_kb(kb_id: int, query_text: str, n_results: int = 5, where: dict | None = None) -> dict:
    collection_name = get_kb_collection_name(kb_id)
    try:
        collection = await asyncio.to_thread(chroma_client.get_collection, collection_name)
    except Exception:
        logger.debug("KB集合不存在或不可用: %s", collection_name, exc_info=True)
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    query_embedding = await embed_single(query_text)
    if not query_embedding:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
    }
    if where:
        kwargs["where"] = where
    return await asyncio.to_thread(collection.query, **kwargs)


async def delete_from_kb(kb_id: int, ids: list[str]):
    collection_name = get_kb_collection_name(kb_id)
    try:
        collection = await asyncio.to_thread(chroma_client.get_collection, collection_name)
        await asyncio.to_thread(collection.delete, ids=ids)
    except Exception:
        logger.warning("从KB集合删除失败: %s ids=%s", collection_name, ids, exc_info=True)


async def update_in_kb(kb_id: int, ids: list[str], documents: list[str], metadatas: list[dict] | None = None):
    collection_name = get_kb_collection_name(kb_id)
    try:
        collection = await asyncio.to_thread(chroma_client.get_collection, collection_name)
        embeddings = await embed_texts(documents)
        kwargs = {
            "ids": ids,
            "documents": documents,
            "embeddings": embeddings,
        }
        if metadatas:
            kwargs["metadatas"] = metadatas
        await asyncio.to_thread(collection.update, **kwargs)
    except Exception:
        logger.warning("更新KB集合失败: %s ids=%s", collection_name, ids, exc_info=True)


async def delete_kb_collection(kb_id: int):
    collection_name = get_kb_collection_name(kb_id)
    try:
        await asyncio.to_thread(chroma_client.delete_collection, collection_name)
    except Exception:
        logger.warning("删除KB集合失败: %s", collection_name, exc_info=True)
