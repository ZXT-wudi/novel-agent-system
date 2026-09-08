import sys
sys.path.insert(0, r"d:\xiaoshuo")
from app.services.volume_splitter import detect_volumes, detect_chapters_in_volume

FILE = r"D:\课件\无职转生-～到了异世界就拿出真本事～-完全收录版.txt"
SKIP = 5

with open(FILE, encoding="utf-8") as f:
    text = f.read()

print(f"文件总长度: {len(text)} 字符", flush=True)

detected = detect_volumes(text)
print(f"检测到 {len(detected)} 卷:", flush=True)
for i, v in enumerate(detected):
    s, e = v["char_range"]
    print(f"  [{i}] V{v['volume_number']} {v['title']}  source={v['source']}  chars={e-s}", flush=True)

if SKIP >= len(detected):
    print(f"skip_volumes={SKIP} 越界", flush=True)
    sys.exit(1)

sliced = detected[SKIP:]
print(f"\nskip_volumes={SKIP} 后剩 {len(sliced)} 卷:", flush=True)

for vi, vol in enumerate(sliced):
    vn = SKIP + vi + 1
    s, e = vol["char_range"]
    vol_text = text[s:e]
    print(f"\n===== V{vn} '{vol['title']}'  正文 {len(vol_text)} 字符 =====", flush=True)
    chapters = detect_chapters_in_volume(vol_text)
    print(f"  章节数: {len(chapters)}", flush=True)
    sizes = []
    for ch in chapters:
        cl = len(ch["text"])
        sizes.append(cl)
        flag = " <-- 超长!" if cl > 20000 else (" <-- 长" if cl > 10000 else "")
        print(f"    Ch{ch['chapter_number']} '{ch['chapter_title']}' {cl}字符{flag}", flush=True)
    if sizes:
        print(f"  总计 {sum(sizes)} 字符, 平均 {sum(sizes)//len(sizes)} 字符, 最长 {max(sizes)} 字符", flush=True)
