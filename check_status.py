import httpx
import json

c = httpx.Client(timeout=30)
r = c.get("http://localhost:8011/api/knowledge-bases/2")
d = r.json()
print("import_status:", d.get("import_status"))
print("import_progress:", json.dumps(d.get("import_progress", {}), ensure_ascii=False)[:800])
vols = [v for v in d.get("volumes", []) if v.get("volume_number", 0) >= 20]
print("V20+ 卷状态:")
for v in vols:
    vn = v.get("volume_number")
    title = v.get("title", "")
    status = v.get("status", "")
    print(f"  V{vn} {title} -> {status}")
