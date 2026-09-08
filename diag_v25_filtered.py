import sys
sys.path.insert(0, r"d:\xiaoshuo")
from app.services.volume_splitter import detect_volumes, detect_chapters_in_volume

FILE = r"D:\课件\无职转生-～到了异世界就拿出真本事～-完全收录版.txt"
SKIP = 5
_MIN_CHAPTER_CHARS = 200
_APPENDIX_KEYWORDS = ("附录", "设定草案", "人物设定", "返回的附录")

with open(FILE, encoding="utf-8") as f:
    text = f.read()

detected = detect_volumes(text)
sliced = detected[SKIP:]

for vi, vol in enumerate(sliced):
    vn = SKIP + vi + 1
    s, e = vol["char_range"]
    vol_text = text[s:e]
    chapters = detect_chapters_in_volume(vol_text)
    raw = len(chapters)

    filtered = [
        ch for ch in chapters
        if len((ch.get("text") or "").strip()) >= _MIN_CHAPTER_CHARS
        and not any(kw in (ch.get("chapter_title") or "") for kw in _APPENDIX_KEYWORDS)
    ]
    kept = len(filtered)
    removed_short = sum(1 for ch in chapters if len((ch.get("text") or "").strip()) < _MIN_CHAPTER_CHARS)
    removed_appendix = sum(1 for ch in chapters if len((ch.get("text") or "").strip()) >= _MIN_CHAPTER_CHARS and any(kw in (ch.get("chapter_title") or "") for kw in _APPENDIX_KEYWORDS))

    sizes = [len(ch["text"]) for ch in filtered]
    avg = sum(sizes) // len(sizes) if sizes else 0
    mx = max(sizes) if sizes else 0
    total = sum(sizes) if sizes else 0

    print(f"V{vn} '{vol['title']}': 原始{raw}章 → 过滤后{kept}章 (移除短章{removed_short}+附录章{removed_appendix})", flush=True)
    print(f"  保留: 总计{total}字, 平均{avg}字, 最长{mx}字", flush=True)
    if mx > 12000:
        print(f"  注意: 最长章节{mx}字将被截断至12000字", flush=True)
