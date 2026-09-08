import httpx
import sys

BASE = "http://localhost:8011/api/knowledge-bases/2"
start_vol = int(sys.argv[1]) if len(sys.argv) > 1 else 22

r = httpx.delete(f"{BASE}/volumes-from/{start_vol}", timeout=60.0)
print(f"DELETE from V{start_vol}: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"删除条目: {data.get('deleted_entries', '?')}")
else:
    print(f"响应: {r.text[:300]}")
