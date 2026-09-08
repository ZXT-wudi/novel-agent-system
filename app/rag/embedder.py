from app.llm.siliconflow import llm_client, LLMError
from app.config import settings
import asyncio

EMBED_MAX_CHARS = 700


def _truncate_for_embed(text: str, max_chars: int = EMBED_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_period = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"), cut.rfind("\n"))
    if last_period > max_chars // 2:
        return cut[: last_period + 1]
    return cut


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    truncated = [_truncate_for_embed(t) for t in texts]
    batch_size = 20
    all_embeddings: list[list[float]] = []
    for i in range(0, len(truncated), batch_size):
        batch = truncated[i : i + batch_size]
        for attempt in range(3):
            try:
                embeddings = await llm_client.embed(batch)
                all_embeddings.extend(embeddings)
                break
            except LLMError:
                if attempt == 2:
                    all_embeddings.extend([[0.0] * settings.EMBEDDING_DIMENSION for _ in batch])
                else:
                    await asyncio.sleep(2 * (attempt + 1))
    return all_embeddings


async def embed_single(text: str) -> list[float]:
    embeddings = await embed_texts([text])
    return embeddings[0] if embeddings else []
