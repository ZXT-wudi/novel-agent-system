import asyncio
from app.database import async_session
from sqlalchemy import text
from app.llm.siliconflow import llm_client
import httpx


async def main():
    async with async_session() as db:
        r = await db.execute(text("SELECT purpose, base_url, chat_model, is_active FROM llm_providers"))
        rows = r.fetchall()
        if rows:
            print("DB LLM providers:")
            for row in rows:
                print(f"  {row}")
        else:
            print("DB LLM providers: (none, using .env defaults)")
    print(f"\nllm_client base_url: {llm_client.base_url}")
    print(f"llm_client model: {llm_client.model}")
    print(f"llm_client providers: {llm_client._purpose_providers}")
    print(f"chat_timeout: {llm_client.chat_timeout}s, max_retries: {llm_client.max_retries}")

    print("\n=== Testing quick LLM call (1 msg) ===")
    try:
        resp = await llm_client.chat(
            [{"role": "user", "content": "回复OK"}],
            temperature=0.1,
            max_tokens=10,
        )
        print(f"LLM response: {resp[:100]}")
        print("LLM API is responsive!")
    except Exception as e:
        print(f"LLM API error: {e}")


asyncio.run(main())
