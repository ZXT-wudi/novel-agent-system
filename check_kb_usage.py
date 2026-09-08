import asyncio
import json
from app.database import async_session
from sqlalchemy import text


async def main():
    async with async_session() as db:
        r = await db.execute(text(
            "SELECT id, title, genre, knowledge_base_id FROM novels ORDER BY id DESC LIMIT 5"
        ))
        print("=== 最近小说列表 ===")
        for row in r:
            print(f"novel_id={row[0]}, title={row[1][:30]}, genre={row[2]}, kb_id={row[3]}")

        r2 = await db.execute(text(
            "SELECT id, title, genre, knowledge_base_id, full_outline FROM novels WHERE id = 5"
        ))
        row2 = r2.fetchone()
        if row2:
            print(f"\n=== novel_id=5 详情 ===")
            print(f"title={row2[1]}, genre={row2[2]}, kb_id={row2[3]}")
            fo = row2[4]
            if isinstance(fo, str):
                fo = json.loads(fo)
            if fo and isinstance(fo, dict):
                vols = fo.get("volumes", [])
                print(f"full_outline volumes: {len(vols)}")
                for v in vols[:5]:
                    print(f"  卷{v.get('volume_number')}: title={v.get('title','')[:30]}, source_volumes={v.get('source_volumes')}")
                if len(vols) > 5:
                    print(f"  ... (共{len(vols)}卷)")
            else:
                print("full_outline: empty or None")


asyncio.run(main())
