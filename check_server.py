import httpx

BASE = "http://localhost:8011/api/knowledge-bases/2"
try:
    r = httpx.get(f"{BASE}", timeout=5.0)
    print(f"状态码: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"KB名称: {data.get('name', '?')}")
        print(f"import_status: {data.get('import_status', '?')}")
        vols = data.get("volumes", [])
        v21_plus = [v for v in vols if v.get("volume_number", 0) >= 21]
        print(f"V21+卷数: {len(v21_plus)}")
        for v in v21_plus:
            print(f"  V{v.get('volume_number')}: {v.get('title','')[:20]} status={v.get('status','?')}")
    else:
        print(f"响应: {r.text[:200]}")
except httpx.ConnectError:
    print("服务器未运行 (Connection refused)")
except Exception as e:
    print(f"错误: {e}")
