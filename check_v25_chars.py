import asyncio
from app.database import async_session
from sqlalchemy import text
import json


async def main():
    async with async_session() as db:
        for vol in (25, 26):
            r = await db.execute(text(
                "SELECT title, attributes FROM knowledge_entries "
                "WHERE kb_id=2 AND volume=:vol AND category='character' ORDER BY id"
            ), {"vol": vol})
            rows = r.fetchall()
            total = len(rows)
            empty_alias = 0
            names = []
            sample_alias = None
            sample_name = None
            for title, attrs in rows:
                aliases = []
                if attrs:
                    if isinstance(attrs, str):
                        d = json.loads(attrs)
                    elif isinstance(attrs, dict):
                        d = attrs
                    else:
                        d = {}
                    aliases = d.get("aliases", [])
                if not aliases:
                    empty_alias += 1
                names.append((title or "").strip())
                if sample_alias is None and aliases:
                    sample_alias = aliases
                    sample_name = (title or "").strip()
            seen = {}
            dups = {}
            for n in names:
                if n in seen:
                    dups[n] = dups.get(n, 0) + 1
                else:
                    seen[n] = 1
            dup_list = {k: v for k, v in dups.items() if v > 0}
            print(f"\n=== 第{vol}卷 角色 ===")
            print(f"角色总数: {total}")
            print(f"空别名数: {empty_alias}")
            print(f"重复角色: {dup_list if dup_list else '无'}")
            if names:
                print(f"前8个角色: {names[:8]}")
            if sample_alias:
                print(f"示例'{sample_name}'别名({len(sample_alias)}条): {sample_alias[:8]}")


asyncio.run(main())
