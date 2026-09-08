import asyncio
from app.database import async_session
from sqlalchemy import text
import json


async def main():
    async with async_session() as db:
        print("=== V22 character entries (first 8) ===")
        r = await db.execute(text(
            "SELECT title, attributes FROM knowledge_entries "
            "WHERE kb_id=2 AND volume=22 AND category='character' ORDER BY id LIMIT 8"
        ))
        rows = r.fetchall()
        for title, attrs in rows:
            a = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
            aliases = a.get("aliases", [])
            print(f"  {title}  aliases({len(aliases)})={aliases[:5]}...")

        print("\n=== V22 entries by category ===")
        r2 = await db.execute(text(
            "SELECT category, COUNT(*) FROM knowledge_entries WHERE kb_id=2 AND volume=22 GROUP BY category"
        ))
        for cat, cnt in r2.fetchall():
            print(f"  {cat}: {cnt}")

        r3 = await db.execute(text(
            "SELECT COUNT(*) FROM knowledge_entries WHERE kb_id=2 AND volume=22 AND category='character'"
        ))
        print(f"\nV22 character count: {r3.scalar()}")
        r4 = await db.execute(text(
            "SELECT COUNT(*) FROM knowledge_entries WHERE kb_id=2 AND volume=22 AND category='character' AND attributes LIKE '%[]%'"
        ))
        print(f"V22 characters with empty aliases: {r4.scalar()}")


asyncio.run(main())
