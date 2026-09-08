import httpx
import json
import os
import asyncio
import logging
from typing import AsyncGenerator
from app.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class SiliconFlowClient:
    def __init__(self):
        self.base_url = settings.SILICONFLOW_BASE_URL
        self.api_key = settings.SILICONFLOW_API_KEY
        self.model = settings.SILICONFLOW_MODEL
        self.embedding_model = settings.SILICONFLOW_EMBEDDING_MODEL
        self._purpose_providers: dict[str, dict] = {}
        self.max_retries = 3
        self.retry_delay = 3.0
        self.chat_timeout = 480.0
        self.stream_timeout = 600.0
        self.embed_timeout = 120.0

    def reconfigure(self, base_url: str, api_key: str, chat_model: str, embedding_model: str | None = None):
        self.base_url = base_url
        self.api_key = api_key
        self.model = chat_model
        if embedding_model:
            self.embedding_model = embedding_model
        print(f"[LLM] 已切换供应商: base_url={base_url}, model={chat_model}, embedding={embedding_model}", flush=True)

    def set_purpose_provider(self, purpose: str, base_url: str, api_key: str, chat_model: str, embedding_model: str | None = None):
        self._purpose_providers[purpose] = {
            "base_url": base_url,
            "api_key": api_key,
            "chat_model": chat_model,
            "embedding_model": embedding_model,
        }

    def clear_purpose_providers(self):
        self._purpose_providers = {}

    def _resolve(self, purpose: str | None) -> dict | None:
        if purpose and self._purpose_providers.get(purpose):
            return self._purpose_providers[purpose]
        if self._purpose_providers.get("common"):
            return self._purpose_providers["common"]
        return None

    def _headers(self, api_key: str | None = None):
        return {
            "Authorization": f"Bearer {api_key or self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096, purpose: str = "common") -> str:
        cfg = self._resolve(purpose)
        payload = {
            "model": cfg["chat_model"] if cfg else self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        base_url = cfg["base_url"] if cfg else self.base_url
        headers = self._headers(cfg["api_key"] if cfg else None)
        last_error = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.chat_timeout) as client:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    if resp.status_code == 429:
                        wait = self.retry_delay * (attempt + 1) * 2
                        await asyncio.sleep(wait)
                        continue
                    if resp.status_code >= 500:
                        wait = self.retry_delay * (attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                last_error = LLMError(f"API请求失败 (HTTP {e.response.status_code}): {e.response.text[:200]}", e.response.status_code)
                if e.response.status_code >= 500 or e.response.status_code == 429:
                    wait = self.retry_delay * (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                raise last_error
            except httpx.TimeoutException:
                last_error = LLMError("API请求超时，模型生成时间较长，请稍后重试")
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue
            except httpx.ConnectError:
                last_error = LLMError("无法连接到API服务，请检查网络")
                await asyncio.sleep(self.retry_delay)
                continue
            except Exception as e:
                last_error = LLMError(f"API调用异常: {str(e)}")
                break
        if last_error:
            raise last_error
        raise LLMError("API调用失败，已达最大重试次数")

    async def chat_stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096, purpose: str = "common") -> AsyncGenerator[str, None]:
        cfg = self._resolve(purpose)
        payload = {
            "model": cfg["chat_model"] if cfg else self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        base_url = cfg["base_url"] if cfg else self.base_url
        headers = self._headers(cfg["api_key"] if cfg else None)
        last_error = None
        for attempt in range(self.max_retries):
            try:
                yielded_any = False
                async with httpx.AsyncClient(timeout=self.stream_timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as resp:
                        if resp.status_code >= 400:
                            error_body = await resp.aread()
                            err_msg = f"API流式请求失败 (HTTP {resp.status_code}): {error_body.decode()[:200]}"
                            last_error = LLMError(err_msg, resp.status_code)
                            if resp.status_code == 429 or resp.status_code >= 500:
                                wait = self.retry_delay * (attempt + 1)
                                if resp.status_code == 429:
                                    wait *= 2
                                logger.warning("流式请求返回 %d，第%d次重试（等待%.0fs）", resp.status_code, attempt + 1, wait)
                                await asyncio.sleep(wait)
                                continue
                            raise last_error
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yielded_any = True
                                    yield content
                            except json.JSONDecodeError:
                                continue
                return
            except LLMError:
                raise
            except httpx.TimeoutException:
                if yielded_any:
                    raise LLMError("API流式请求在输出途中超时，无法重试")
                last_error = LLMError("API流式请求超时，请稍后重试")
                logger.warning("流式请求超时，第%d次重试", attempt + 1)
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue
            except httpx.ConnectError:
                if yielded_any:
                    raise LLMError("无法连接到API服务（输出途中断开）")
                last_error = LLMError("无法连接到API服务，请检查网络")
                logger.warning("流式连接失败，第%d次重试", attempt + 1)
                await asyncio.sleep(self.retry_delay)
                continue
            except Exception as e:
                raise LLMError(f"API流式调用异常: {str(e)}")
        if last_error:
            raise last_error
        raise LLMError("API流式调用失败，已达最大重试次数")

    async def generate_image(self, prompt: str, image_size: str = "1024x1024", purpose: str = "image") -> str:
        cfg = self._resolve(purpose)
        base_url = cfg["base_url"] if cfg else self.base_url
        headers = self._headers(cfg["api_key"] if cfg else None)
        image_model = (
            cfg.get("chat_model")
            if cfg and cfg.get("chat_model")
            else os.getenv("IMAGE_MODEL", "Tongyi-MAI/Z-Image-Turbo")
        )
        payload = {
            "model": image_model,
            "prompt": prompt,
            "image_size": image_size,
        }
        last_error = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        f"{base_url}/images/generations",
                        headers=headers,
                        json=payload,
                    )
                    if resp.status_code == 429:
                        wait = self.retry_delay * (attempt + 1) * 2
                        await asyncio.sleep(wait)
                        continue
                    if resp.status_code >= 500:
                        wait = self.retry_delay * (attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    images = data.get("images", [])
                    if not images or not images[0].get("url"):
                        raise LLMError("图片生成响应中未找到图片URL")
                    return images[0]["url"]
            except httpx.HTTPStatusError as e:
                last_error = LLMError(f"图片生成失败 (HTTP {e.response.status_code}): {e.response.text[:200]}", e.response.status_code)
                if e.response.status_code >= 500 or e.response.status_code == 429:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise last_error
            except httpx.TimeoutException:
                last_error = LLMError("图片生成请求超时，请稍后重试")
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue
            except httpx.ConnectError:
                last_error = LLMError("无法连接到图片生成服务，请检查网络")
                await asyncio.sleep(self.retry_delay)
                continue
            except LLMError:
                raise
            except Exception as e:
                last_error = LLMError(f"图片生成异常: {str(e)}")
                break
        if last_error:
            raise last_error
        raise LLMError("图片生成失败，已达最大重试次数")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cfg = self._resolve("common")
        payload = {
            "model": cfg["embedding_model"] if cfg and cfg.get("embedding_model") else self.embedding_model,
            "input": texts,
            "encoding_format": "float",
        }
        base_url = cfg["base_url"] if cfg else self.base_url
        headers = self._headers(cfg["api_key"] if cfg else None)
        last_error = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.embed_timeout) as client:
                    resp = await client.post(
                        f"{base_url}/embeddings",
                        headers=headers,
                        json=payload,
                    )
                    if resp.status_code >= 500 or resp.status_code == 429:
                        wait = self.retry_delay * (attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    return [item["embedding"] for item in data["data"]]
            except httpx.HTTPStatusError as e:
                last_error = LLMError(f"Embedding API失败 (HTTP {e.response.status_code})")
                if e.response.status_code >= 500 or e.response.status_code == 429:
                    await asyncio.sleep(self.retry_delay)
                    continue
                raise last_error
            except Exception as e:
                last_error = LLMError(f"Embedding异常: {str(e)}")
                break
        if last_error:
            raise last_error
        raise LLMError("Embedding API调用失败")


llm_client = SiliconFlowClient()


class _PurposeProxy:
    def __init__(self, purpose: str):
        self._purpose = purpose

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        return await llm_client.chat(messages, temperature=temperature, max_tokens=max_tokens, purpose=self._purpose)

    def chat_stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> AsyncGenerator[str, None]:
        return llm_client.chat_stream(messages, temperature=temperature, max_tokens=max_tokens, purpose=self._purpose)


def get_client(purpose: str) -> _PurposeProxy:
    return _PurposeProxy(purpose)


async def reconfigure_llm_client():
    from app.database import async_session
    from app.models.llm_provider import LlmProvider
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(LlmProvider).where(LlmProvider.is_active == True))
        actives = result.scalars().all()
    llm_client.clear_purpose_providers()
    if not actives:
        llm_client.reconfigure(
            base_url=settings.SILICONFLOW_BASE_URL,
            api_key=settings.SILICONFLOW_API_KEY,
            chat_model=settings.SILICONFLOW_MODEL,
            embedding_model=settings.SILICONFLOW_EMBEDDING_MODEL,
        )
        return
    for p in actives:
        purpose = getattr(p, "purpose", None) or "common"
        llm_client.set_purpose_provider(
            purpose=purpose,
            base_url=p.base_url,
            api_key=p.api_key,
            chat_model=p.chat_model,
            embedding_model=p.embedding_model,
        )
    summary = ", ".join(
        f"{purpose}={cfg['chat_model']}" for purpose, cfg in llm_client._purpose_providers.items()
    )
    print(f"[LLM] 已按用途加载激活供应商: {summary}", flush=True)
