import re
from typing import List, Dict

SYNTH_VOLUME_EVERY = 20

_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "零": 0}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_UPPER_VOL = {"上": 1, "中": 2, "下": 3}

_VOLUME_PATTERNS = [
    re.compile(r"第\s*([一二三四五六七八九十百千零\d]+)\s*[卷部册]"),
    re.compile(r"^\s*卷\s*([一二三四五六七八九十百千零\d]+)", re.MULTILINE),
    re.compile(r"^\s*([上中下])\s*[篇部卷]", re.MULTILINE),
]
_CHAPTER_PATTERNS = [
    re.compile(r"第\s*([一二三四五六七八九十百千零\d]+)\s*[章话回]"),
]


def _cn2int(s: str) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return 0
    total = 0
    section = 0
    num = 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            u = _CN_UNITS[ch]
            if ch == "十" and num == 0:
                num = 1
            if u >= 10000:
                total = (total + section + num) * u
                section = 0
                num = 0
            else:
                section += num * u
                num = 0
    return total + section + num


def _clean_title(line: str, fallback: str) -> str:
    line = (line or "").strip()
    line = re.sub(r"第\s*[一二三四五六七八九十百千零\d]+\s*[卷部册]\s*", "", line)
    line = re.sub(r"^\s*卷\s*[一二三四五六七八九十百千零\d]+\s*", "", line)
    line = re.sub(r"^\s*[上中下]\s*[篇部卷]\s*", "", line)
    cut = re.search(r"第\s*[一二三四五六七八九十百千零\d]+\s*[章话回]", line)
    if cut:
        line = line[:cut.start()]
    line = line.strip(" \t:：.。-—\u3000")
    return line or fallback


def detect_volumes(text: str, synth_every: int = SYNTH_VOLUME_EVERY) -> List[Dict]:
    """返回 [{volume_number, title, char_range:[start,end], source}]，char_range 的 end 为切片右界（exclusive）。"""
    if not text or not text.strip():
        return [{"volume_number": 1, "title": "第1卷", "char_range": [0, 0], "source": "whole"}]

    vol_matches = []
    for pi, pat in enumerate(_VOLUME_PATTERNS):
        for m in pat.finditer(text):
            num_str = m.group(1)
            if pi == 2:
                num = _UPPER_VOL.get(num_str, 1)
            else:
                num = _cn2int(num_str)
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            if line_end == -1:
                line_end = len(text)
            if text[line_start:m.start()].strip():
                continue
            vol_matches.append({
                "num": num,
                "start": m.start(),
                "line_start": line_start,
                "line": text[line_start:line_end],
            })

    if vol_matches:
        vol_matches.sort(key=lambda x: x["start"])
        seen_starts = set()
        deduped = []
        for vm in vol_matches:
            if vm["line_start"] in seen_starts:
                continue
            seen_starts.add(vm["line_start"])
            deduped.append(vm)
        seen_nums = set()
        by_num = []
        for vm in deduped:
            if vm["num"] in seen_nums:
                continue
            seen_nums.add(vm["num"])
            by_num.append(vm)
        deduped = by_num

        n = len(deduped)
        volumes = []
        for i, vm in enumerate(deduped):
            start = 0 if i == 0 else vm["line_start"]
            end = len(text) if i == n - 1 else deduped[i + 1]["line_start"]
            title = _clean_title(vm["line"], f"第{i + 1}卷")
            volumes.append({
                "volume_number": i + 1,
                "title": title,
                "char_range": [start, end],
                "source": "explicit",
            })
        return volumes

    ch_matches = []
    for pat in _CHAPTER_PATTERNS:
        for m in pat.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            ch_matches.append({
                "ch_num": _cn2int(m.group(1)),
                "start": m.start(),
                "line_start": line_start,
            })

    if ch_matches:
        ch_matches.sort(key=lambda x: x["start"])
        seen = set()
        ordered = []
        for cm in ch_matches:
            if cm["line_start"] in seen:
                continue
            seen.add(cm["line_start"])
            ordered.append(cm)
        ch_matches = ordered

        total = len(ch_matches)
        vol_count = max(1, (total + synth_every - 1) // synth_every)
        volumes = []
        for k in range(vol_count):
            seg = ch_matches[k * synth_every:(k + 1) * synth_every]
            if not seg:
                continue
            start = 0 if k == 0 else seg[0]["line_start"]
            end = len(text)
            next_idx = (k + 1) * synth_every
            if next_idx < len(ch_matches):
                end = ch_matches[next_idx]["line_start"]
            a, b = seg[0]["ch_num"], seg[-1]["ch_num"]
            title = f"第{k + 1}卷（第{a}-{b}章）" if a != b else f"第{k + 1}卷（第{a}章）"
            volumes.append({
                "volume_number": k + 1,
                "title": title,
                "char_range": [start, end],
                "source": "synthetic",
            })
        if volumes:
            return volumes

    return [{
        "volume_number": 1,
        "title": "第1卷",
        "char_range": [0, len(text)],
        "source": "whole",
    }]


def _clean_chapter_title(line: str, fallback: str) -> str:
    line = (line or "").strip()
    line = re.sub(r"第\s*[一二三四五六七八九十百千零\d]+\s*[章话回]\s*", "", line)
    line = line.strip(" \t:：.。-—\u3000")
    return line or fallback


def detect_chapters_in_volume(vol_text: str) -> List[Dict]:
    """返回 [{chapter_number, chapter_title, char_range:[start,end], text}]，char_range 的 end 为切片右界（exclusive）。"""
    if not vol_text or not vol_text.strip():
        return [{"chapter_number": 1, "chapter_title": "本卷全文", "char_range": [0, 0], "text": ""}]

    ch_matches = []
    for pat in _CHAPTER_PATTERNS:
        for m in pat.finditer(vol_text):
            line_start = vol_text.rfind("\n", 0, m.start()) + 1
            line_end = vol_text.find("\n", m.end())
            if line_end == -1:
                line_end = len(vol_text)
            ch_matches.append({
                "ch_num": _cn2int(m.group(1)),
                "start": m.start(),
                "line_start": line_start,
                "line": vol_text[line_start:line_end],
            })

    if ch_matches:
        ch_matches.sort(key=lambda x: x["start"])
        seen = set()
        ordered = []
        for cm in ch_matches:
            if cm["line_start"] in seen:
                continue
            seen.add(cm["line_start"])
            ordered.append(cm)
        ch_matches = ordered

        n = len(ch_matches)
        chapters = []
        for i, cm in enumerate(ch_matches):
            start = cm["line_start"]
            end = len(vol_text) if i == n - 1 else ch_matches[i + 1]["line_start"]
            ch_num = cm["ch_num"] or (i + 1)
            title = _clean_chapter_title(cm["line"], f"第{ch_num}章")
            chapters.append({
                "chapter_number": ch_num,
                "chapter_title": title,
                "char_range": [start, end],
                "text": vol_text[start:end],
            })
        return chapters

    return [{
        "chapter_number": 1,
        "chapter_title": "本卷全文",
        "char_range": [0, len(vol_text)],
        "text": vol_text,
    }]


def volumes_for_chapter_range(full_outline: dict, start_ch: int, end_ch: int) -> List[int]:
    if not isinstance(full_outline, dict):
        return []
    volumes = full_outline.get("volumes") or []
    result: list[int] = []
    for v in volumes:
        if not isinstance(v, dict):
            continue
        cr = v.get("chapter_range")
        if not (isinstance(cr, list) and len(cr) == 2):
            continue
        try:
            vstart = int(cr[0])
            vend = int(cr[1])
        except (TypeError, ValueError):
            continue
        if vstart <= end_ch and vend >= start_ch:
            vn = v.get("volume_number")
            if vn is not None and vn not in result:
                result.append(vn)
    return result


def resolve_source_volumes(full_outline: dict, fanwork_vol_nums: List[int]) -> List[int] | None:
    """根据全文大纲的 source_volumes 映射，解析指定同人卷对应的源知识库卷号列表。

    全文大纲每卷可记录 source_volumes（该同人卷引用的原作源卷号），
    用于同人创作时按源卷过滤知识库上下文，确保时间线一致。
    无映射时返回 None（调用方应回退为注入全部源卷）。
    """
    if not fanwork_vol_nums or not isinstance(full_outline, dict):
        return None
    sv: set[int] = set()
    for vol in (full_outline.get("volumes") or []):
        if not isinstance(vol, dict):
            continue
        if vol.get("volume_number") in fanwork_vol_nums:
            svs = vol.get("source_volumes")
            if isinstance(svs, list):
                sv.update(x for x in svs if isinstance(x, int))
    return sorted(sv) if sv else None


def validate_and_backfill_source_volumes(full_outline: dict) -> dict:
    """校验全文大纲每卷的 source_volumes。若缺失则按时间线门控自动补全为 [1..volume_number]。

    时间线门控规则：source_volumes 须随同人卷序号单调递增，
    早期同人卷只能引用早期源卷。因此缺失时默认补全为 [1, 2, ..., volume_number]。
    """
    if not isinstance(full_outline, dict):
        return full_outline
    volumes = full_outline.get("volumes") or []
    for vol in volumes:
        if not isinstance(vol, dict):
            continue
        vn = vol.get("volume_number")
        sv = vol.get("source_volumes")
        if not isinstance(sv, list) or not sv:
            backfill = list(range(1, (vn or 1) + 1))
            vol["source_volumes"] = backfill
            print(f"[OUTLINE] 卷{vn} 缺少 source_volumes，已自动补全为 {backfill}")
    full_outline["volumes"] = volumes
    return full_outline
