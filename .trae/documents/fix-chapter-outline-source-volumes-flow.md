# 修复章节大纲生成流程:source_volumes 映射缺失

## 概述

全文大纲 → 章节大纲的流程中,章节大纲流式端点未使用 `resolve_source_volumes` 映射同人卷号→源卷号,导致知识库上下文按错误的卷号过滤、走错误的代码路径(comprehensive=False)。同时,全文大纲生成后无服务端校验 `source_volumes` 是否已填写,LLM 漏填时回退注入全部卷。

## 现状分析

### 流程梳理

| 步骤 | 位置 | 现状 | 是否正确 |
|------|------|------|----------|
| 全文大纲生成 | outlines.py:140-141 | `build_kb_context_for_agent(comprehensive=True, toc_mode=True)` 注入全部卷 | ✅ 用户确认保持 |
| 全文大纲 prompt | outline_agent.py:85,112,155 | 要求 LLM 每卷填写 `source_volumes` | ✅ prompt 正确 |
| source_volumes 校验 | 无 | 无服务端校验,LLM 漏填则 resolve_source_volumes 返回 None → 注入全部卷 | ❌ 缺失 |
| 章节大纲(流式端点) | outlines.py:284-294 | 用同人卷号直接当 KB volume_numbers,comprehensive=False,不调 resolve_source_volumes | ❌ 核心BUG |
| 章节大纲(服务函数) | outline_service.py:88-108 | 正确调用 resolve_source_volumes + comprehensive=True + toc_mode=False | ✅ 但从未被调用 |
| 章节写作(正文) | chapter_service.py:103-106 | 正确调用 resolve_source_volumes + comprehensive=True + toc_mode=False | ✅ |

### 核心 BUG 详解(outlines.py:284-294)

```python
# 当前(错误):
chapter_vol_nums = volumes_for_chapter_range(...)  # 同人卷号,如 [1]
kb_context = await build_kb_context_for_agent(
    db, novel.knowledge_base_id, ...,
    volume_numbers=chapter_vol_nums,  # ← 用同人卷号当源卷号过滤!如果同人卷号=1,只查源卷1
    chapter_numbers=list(range(start, end)),  # ← 用同人章节号当KB章节号过滤!
    # comprehensive=False(默认)→ 走 _build_chapter_level_context 或 by_category 路径
    # 不是 _build_comprehensive_volume_context(卷→章层级)
)
```

而 prompt(outline_agent.py:386)告诉 LLM:
> "原作知识库参考(同人创作最高优先级,**已按【卷→章】层级组织**:含该卷主要事件总结、本章摘要、本章角色与事件)"

实际 KB context 因 comprehensive=False 根本不是按卷→章层级组织的 → **prompt 与实际数据不一致**。

### 正确参照实现(outline_service.py:88-108)

```python
if novel.genre == "同人" and novel.full_outline:
    source_volumes = resolve_source_volumes(novel.full_outline, chapter_vol_nums)
    kb_context = await build_kb_context_for_agent(
        db, novel.knowledge_base_id, ...,
        comprehensive=True,           # → 走 _build_comprehensive_volume_context
        volume_numbers=source_volumes, # ← 源卷号,如 [1, 2, 3]
        chapter_numbers=None,         # ← 不按章节过滤(卷级注入)
        toc_mode=False,               # ← 完整章节摘要
    )
else:
    kb_context = await build_kb_context_for_agent(
        db, novel.knowledge_base_id, ...,
        volume_numbers=chapter_vol_nums,
        chapter_numbers=list(range(start, end)),
    )
```

此函数逻辑正确但**从未被调用**(全项目 grep 仅 1 处定义,0 处调用)。

## 修改方案

### 修改 1:修复章节大纲流式端点(outlines.py)

**文件**: `app/api/outlines.py`

**1a. 更新导入(L281)**

```python
# 原:
from app.services.volume_splitter import volumes_for_chapter_range
# 改:
from app.services.volume_splitter import volumes_for_chapter_range, resolve_source_volumes
```

**1b. 重写 KB 上下文构建(L284-294)**

```python
chapter_vol_nums = volumes_for_chapter_range(novel.full_outline or {}, data.start_chapter, data.start_chapter + data.batch_size - 1)

kb_context = ""
if novel.knowledge_base_id:
    try:
        if novel.genre == "同人" and novel.full_outline:
            source_volumes = resolve_source_volumes(novel.full_outline, chapter_vol_nums)
            kb_context = await build_kb_context_for_agent(
                db, novel.knowledge_base_id,
                f"第{data.start_chapter}章到第{data.start_chapter + data.batch_size - 1}章",
                comprehensive=True,
                volume_numbers=source_volumes,
                chapter_numbers=None,
                toc_mode=False,
            )
        else:
            kb_context = await build_kb_context_for_agent(
                db, novel.knowledge_base_id,
                f"第{data.start_chapter}章到第{data.start_chapter + data.batch_size - 1}章",
                volume_numbers=chapter_vol_nums,
                chapter_numbers=list(range(data.start_chapter, data.start_chapter + data.batch_size)),
            )
    except Exception as e:
        print(f"[KB] 章节大纲知识库读取失败: {e}")
```

**原因**: 同人创作需先通过 `resolve_source_volumes` 将同人卷号映射为源知识库卷号,再用 `comprehensive=True` 走卷→章层级上下文构建路径,与 chapter_service.py 和 outline_service.py 保持一致。

### 修改 2:新增 source_volumes 校验函数(volume_splitter.py)

**文件**: `app/services/volume_splitter.py`

在文件末尾(L271 后)新增:

```python
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
```

**原因**: 用户选择自动补全策略。按时间线门控规则,同人卷 N 缺失 source_volumes 时补全为 [1..N],保证早期卷只引用早期源卷,避免时间线错乱。

### 修改 3:在全文大纲各入口调用校验

**3a. 流式生成端点(outlines.py)**

在 L219 解析后、L221 保存前插入:

```python
full_outline = _parse_full_outline_response(full_text)
full_outline = validate_and_backfill_source_volumes(full_outline)  # ← 新增
```

同时在 L85 的 `stream_generator` 内部添加导入:

```python
from app.services.volume_splitter import validate_and_backfill_source_volumes
```

**3b. 服务生成函数(outline_service.py)**

在 L71 生成后、L73 保存前插入:

```python
full_outline = state.get("full_outline", {})
full_outline = validate_and_backfill_source_volumes(full_outline)  # ← 新增
```

在文件头部导入(L17 已有 volume_splitter 导入,追加):

```python
from app.services.volume_splitter import volumes_for_chapter_range, resolve_source_volumes, validate_and_backfill_source_volumes
```

**3c. 手动更新函数(outline_service.py L204-212)**

在 L209 保存前插入:

```python
full_outline = validate_and_backfill_source_volumes(full_outline)
novel.full_outline = full_outline
```

**3d. AI 修订函数(outline_service.py L247-265)**

在 L259 生成后、L261 保存前插入:

```python
full_outline = state.get("full_outline", {})
full_outline = validate_and_backfill_source_volumes(full_outline)  # ← 新增
```

## 不修改的部分

- **toc_mode=True(全文大纲)**: 用户确认保持目录格式,【各卷摘要】卷级摘要始终包含。
- **outline_service.py generate_chapter_outline_batch**: 逻辑已正确,虽未被调用但留作参考,不改动。
- **chapter_service.py**: 章节写作路径已正确,不改动。

## 假设与决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| toc_mode(全文大纲) | 保持 True | 用户确认;卷级摘要+章节目录足够,节省 token |
| source_volumes 缺失处理 | 自动补全 [1..N] | 用户选择;符合时间线门控规则 |
| 代码复用 | 不提取共享 helper | 流式端点内联修复即可,避免过度抽象;正确参照已有 outline_service.py:88-108 |

## 验证步骤

1. **编译检查**: `python -c "import app.api.outlines; import app.services.outline_service; import app.services.volume_splitter"` 确认无导入错误
2. **单元验证**: 调用 `validate_and_backfill_source_volumes({"volumes": [{"volume_number": 3}]})` 确认输出 `source_volumes=[1,2,3]`
3. **端到端验证**: 重启服务器后,对已有同人小说重新生成章节大纲,检查服务器日志是否出现 `resolve_source_volumes` 的输出或 KB 上下文按源卷过滤的日志
4. **回归检查**: 对原创小说(非同人)生成章节大纲,确认走 else 分支(comprehensive=False + chapter_numbers),行为不变
