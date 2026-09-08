import httpx

BASE = "http://localhost:8011/api/knowledge-bases/2"
try:
    r = httpx.delete(f"{BASE}/volumes-from/21", timeout=60.0)
    print(f"状态码: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"删除卷数: {data.get('deleted_volumes', '?')}")
        print(f"删除条目: {data.get('deleted_entries', '?')}")
    else:
        print(f"响应: {r.text[:300]}")
except Exception as e:
    print(f"错误: {e}")
