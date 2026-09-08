import asyncio
from app.database import async_session
from sqlalchemy import text


async def main():
    async with async_session() as db:
        r = await db.execute(text(
            "SELECT volume, COUNT(*) FROM knowledge_entries "
            "WHERE kb_id=2 AND volume>=20 GROUP BY volume ORDER BY volume"
        ))
        rows = r.fetchall()
        if rows:
            print("V20+ entries by volume:")
            total = 0
            for vol, cnt in rows:
                print(f"  V{vol}: {cnt} entries")
                total += cnt
            print(f"  Total V20+: {total}")
        else:
            print("V20+ entries: 0 (still extracting)")


asyncio.run(main())
