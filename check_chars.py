import asyncio
from app.database import async_session
from sqlalchemy import text
import json


async def main():
    async with async_session() as db:
        print("=== V20 vs V21 character entries ===")
        for vol in [20, 21]:
            r = await db.execute(text(
                "SELECT title, attributes FROM knowledge_entries "
                "WHERE kb_id=2 AND volume=:v AND category='character' ORDER BY id LIMIT 8"
            ), {"v": vol})
            rows = r.fetchall()
            print(f"\n--- V{vol} characters (first 8) ---")
            for title, attrs in rows:
                a = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
                aliases = a.get("aliases", [])
                print(f"  {title}  aliases={aliases}")

        print("\n=== V21 character count + duplicates ===")
        r2 = await db.execute(text(
            "SELECT COUNT(*) FROM knowledge_entries WHERE kb_id=2 AND volume=21 AND category='character'"
        ))
        print(f"V21 character entries: {r2.scalar()}")

        r3 = await db.execute(text(
            "SELECT COUNT(*) FROM knowledge_entries WHERE kb_id=2 AND volume=20 AND category='character'"
        ))
        print(f"V20 character entries: {r3.scalar()}")

        print("\n=== V21 entries by category ===")
        r4 = await db.execute(text(
            "SELECT category, COUNT(*) FROM knowledge_entries WHERE kb_id=2 AND volume=21 GROUP BY category"
        ))
        for cat, cnt in r4.fetchall():
            print(f"  {cat}: {cnt}")

        print("\n=== V21+ entries by volume ===")
        r5 = await db.execute(text(
            "SELECT volume, COUNT(*) FROM knowledge_entries WHERE kb_id=2 AND volume>=20 GROUP BY volume ORDER BY volume"
        ))
        for vol, cnt in r5.fetchall():
            print(f"  V{vol}: {cnt}")


asyncio.run(main())
