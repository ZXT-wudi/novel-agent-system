import httpx
import sys

BASE = "http://localhost:8011/api/knowledge-bases/2"
NEW_FILE = r"D:\课件\无职转生-～到了异世界就拿出真本事～-完全收录版.txt"

start_volume = int(sys.argv[1]) if len(sys.argv) > 1 else 20
body_count = int(sys.argv[2]) if len(sys.argv) > 2 else 6
skip_volumes = int(sys.argv[3]) if len(sys.argv) > 3 else 0

print("=== 续接导入开始 ===", flush=True)
print(f"文件: {NEW_FILE}", flush=True)
print(f"start_volume={start_volume}, body_count={body_count}, skip_volumes={skip_volumes}", flush=True)

with open(NEW_FILE, "rb") as f:
    file_content = f.read()

files = {"file": ("upload.txt", file_content, "text/plain")}
data = {
    "start_volume": str(start_volume),
    "body_count": str(body_count),
    "skip_volumes": str(skip_volumes),
}

try:
    with httpx.Client(timeout=None) as c:
        with c.stream("POST", f"{BASE}/append-continuation",
                      files=files, data=data) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    print(line, flush=True)
except Exception as e:
    print(f"=== 错误: {e} ===", flush=True)
    sys.exit(1)

print("=== 脚本结束 ===", flush=True)
