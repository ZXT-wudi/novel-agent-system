# 增强全文大纲：角色情感/事件、主角能力进阶、跨卷伏笔、深度知识库提取

## 一、背景与目标

用户反馈：全文大纲生成内容太有限，缺少
1. 每卷主角与其他角色的**情感**、**事件**、以及**情感随事件变化**；
2. 主角**能力**在各卷的**变化**，以及能力因**什么事件**而变化；
3. 每卷的**伏笔**，且需要**跨卷追踪**（埋下卷↔回收卷配对）；
4. 全文大纲生成时**没有充分读取高级知识库**，需大量提取角色/事件/世界观，保证同人准确性。

用户已确认的偏好（来自上一会话澄清）：
- 知识库提取深度：**大幅提高上限**
- 新增字段形式：**结构化数组**
- 伏笔：**跨卷追踪**（埋下卷 ↔ 回收卷配对）
- 章节级大纲：**同步增强**，引用这些新字段

成功标准：
- 全文大纲 JSON 输出新增：顶层 `foreshadowing[]`、`characters[].ability_baseline`；每卷新增 `character_dynamics[]`、`protagonist_abilities[]`、`foreshadowing_ids[]`。
- 同人场景下，知识库中角色/事件/世界观被大量注入到大纲生成的 system/user 上下文，并在 prompt 中硬约束 LLM 严格沿用。
- 章节大纲输出新增 `emotion_beat`、`ability_state`、`foreshadowing_action`，并在构建章节消息时把每卷的 dynamics/abilities/foreshadowing 传入。
- 全文大纲保存后，新字段被索引进 RAG（world_knowledge），写作时可检索。
- 前端卡片视图展示新字段；全屏编辑器与弹窗编辑器可编辑新字段并回存。
- 语法校验通过：`py_compile` + `node --check`。

## 二、当前状态分析（基于 Phase 1 实读代码）

### 数据结构现状
- `Novel.full_outline` 为 JSON 列（dict），结构宽松，**加字段无需迁移**。
- `_parse_full_outline_response`（outline_agent.py L339-352）只判断 `"volumes" in result`，加新字段不会破坏解析。

### 全文大纲 prompt 现状（outline_agent.py）
- `FULL_OUTLINE_SYSTEM_PROMPT`（L43-111）：每卷六要素 = setting/opening/development/climax/ending + key_characters/major_events/tone。**缺少**：角色情感、角色事件、情感变化、主角能力进阶、能力变化触发、伏笔。
- `_build_full_outline_messages`（L204-245）：`kb_section` 仅一行标签 `=== 原作知识库参考（同人创作必须严格遵循） ===` + kb_context，未显式要求 LLM 提取全部角色/事件/世界观。
- `CHAPTER_OUTLINE_SYSTEM_PROMPT`（L114-143）：已有 `character_changes`、`notes` 字段，但未引用全文大纲新增字段。
- `_build_chapter_outline_messages`（L248-320）：`volume_summary` 只用 title/summary/chapter_range/key_characters/major_events/tone 六项，未含新字段；无顶层伏笔区段。
- `generate_full_outline_stream`（L385-409）：`max_tokens=8192`。新增字段 + 更深 KB 会使输出 JSON 变大，需提高。

### 知识库注入现状（kb_service.py）
- `KB_INJECT_PER_CATEGORY_FULL`（L214-221）：worldview=12, character=30, event=25, timeline=12, faction=15, setting=15。
- `build_kb_context_for_agent`（L224-308）：`comprehensive=True` 用上述上限；`other_limit=12`；向量补充 `n_results=12`、distance≤0.6、补充上限 `supplement[:5]`。
- `outlines.py` `generate_full_outline`（L74-76）确以 `comprehensive=True` 调用，**调高上限即生效**。

### RAG 索引现状（knowledge_service.py）
- `index_full_outline_to_rag`（L220-268）：索引 worldview、characters（name/role/profile/motivation/relationships/arc）、每卷 setting/opening/development/climax/ending。**未索引**：character_dynamics、protagonist_abilities、顶层 foreshadowing、ability_baseline。

### 前端现状
- `renderFullOutline`（app.js L252-305）：卡片只展示 theme/core_conflict/total_chapters + 每卷 volume_number/title/chapter_range/summary/key_characters/major_events/tone。**不展示**六要素文本，也不展示任何新字段。
- `editFullOutlineModal`/`saveFullOutlineEdit`（outline.js L736-834）：弹窗编辑 theme/core_conflict/story_arc/total_chapters + 每卷 title/summary/key_characters/major_events/chapter_range/tone。
- `renderFullOutlineFullscreen`/`saveFullOutlineFullscreen`（outline.js L880-964、L970+）：全屏编辑同上字段。两处编辑器均**不含新字段**。

## 三、数据结构设计

### 顶层新增/扩展
```
full_outline.foreshadowing: [
  {
    "id": "F1",                       // 伏笔编号，全大纲唯一
    "description": "伏笔内容描述",
    "planted_in_volume": 1,           // 埋下卷号
    "payoff_in_volume": 3,            // 回收卷号（未回收可为 null）
    "status": "planted"               // planted | ongoing | payoff
  }
]
full_outline.characters[i].ability_baseline  // 该角色（尤为主角）的核心能力/力量体系基线，40字以内
```

### 每卷新增
```
volume.character_dynamics: [
  {
    "character": "角色名",
    "emotion_state": "本卷该角色情感状态",          // 40字以内
    "key_event": "触发情感变化的关键事件",           // 40字以内
    "emotion_change": "情感如何变化"                 // 40字以内
  }
]
volume.protagonist_abilities: [
  {
    "ability": "能力名称",
    "state": "初现|成长|突破|受限|丧失",
    "change": "能力如何变化",                        // 40字以内
    "trigger_event": "触发变化的事件"                 // 40字以内
  }
]
volume.foreshadowing_ids: ["F1", "F3"]   // 本卷埋下或回收的顶层伏笔 id 引用
```

### 章节级新增（CHAPTER_OUTLINE 输出）
```
chapter.emotion_beat       // 本章关键情感节拍（角色情感状态/变化），40字以内
chapter.ability_state      // 本章主角能力状态/微小变化，40字以内
chapter.foreshadowing_action  // 本章对伏笔的动作（埋下/推进/回收）+引用id，40字以内
```

## 四、文件修改清单与具体改动

### 文件1：`app/agents/outline_agent.py`

**改动 A — `FULL_OUTLINE_SYSTEM_PROMPT`（L43-111）**
- 在【设计方法论】新增三节：
  - 「人物情感弧线」：每卷须列出主角与核心角色的情感状态、触发情感变化的关键事件、情感变化方向；情感随事件演进，避免突兀。
  - 「主角能力进阶」：在 characters 设定 `ability_baseline` 作为能力基线；每卷须列出主角能力的状态（初现/成长/突破/受限/丧失）、变化描述、触发变化的事件；能力变化须与情节事件因果绑定。
  - 「伏笔布局（跨卷追踪）」：顶层 `foreshadowing[]` 记录每个伏笔的 id、描述、埋下卷号、回收卷号、状态；每卷用 `foreshadowing_ids` 引用本卷埋下或回收的伏笔；埋下与回收须跨卷配对，不得孤立。
- 新增【同人创作硬约束】段：明确下方【原作知识库参考】中的角色姓名、身份、能力体系、世界观规则、重大事件必须严格沿用，不得原创冲突角色或推翻既有设定；若知识库提供了角色，须在 characters 中忠实纳入。
- 输出 JSON 扩展：
  - 顶层增加 `foreshadowing` 数组（结构如上）。
  - `characters[]` 每项增加 `ability_baseline` 字段。
  - 每卷增加 `character_dynamics`、`protagonist_abilities`、`foreshadowing_ids` 三个数组。
- 字数纪律段补充：新增字段按上限从简，确保输出为完整 JSON、绝不截断。

**改动 B — `_build_full_outline_messages`（L204-245，L218 kb_section）**
- 强化 kb_section 文案，显式要求提取并忠实沿用：
  `kb_section = f"\n=== 原作知识库参考（同人创作必须严格遵循：须从中提取全部角色、事件、世界观设定并忠实沿用，不得原创冲突角色或推翻既有设定） ===\n{kb_context}" if kb_context else ""`

**改动 C — `CHAPTER_OUTLINE_SYSTEM_PROMPT`（L114-143）**
- 在【章节设计准则】新增：
  - 「情感节拍」：本章角色情感状态/变化须与所在卷的 character_dynamics 一致并推进。
  - 「能力状态」：本章主角能力状态须与所在卷 protagonist_abilities 一致，微小变化可写入。
  - 「伏笔动作」：本章可埋下/推进/回收伏笔，动作须引用顶层 foreshadowing 的 id，并标记动作类型。
- 输出 JSON 数组每项新增 `emotion_beat`、`ability_state`、`foreshadowing_action`。

**改动 D — `_build_chapter_outline_messages`（L248-320，L265-272 volume_summary）**
- 扩展 volume_summary：在原有六项后追加每卷的 character_dynamics、protagonist_abilities、foreshadowing_ids（序列化为简短文本）。
- 在 user 消息中新增「顶层伏笔清单」区段：把 `full_outline.foreshadowing` 序列化注入，供章节大纲引用 id。

**改动 E — `generate_full_outline_stream`（L385-409，L408）**
- `max_tokens` 由 8192 提升到 16384，容纳更大 JSON。

**改动 F — `_parse_full_outline_response`（L339-352）**
- 无需改动（仅判断 `volumes`），仅记录验证：新字段不破坏解析。

### 文件2：`app/services/kb_service.py`

**改动 J — `KB_INJECT_PER_CATEGORY_FULL`（L214-221）**
- worldview 12→30，character 30→60，event 25→50，timeline 12→25，faction 15→30，setting 15→30。

**改动 K — `build_kb_context_for_agent`（L224-308）**
- L231 `other_limit` 12→20。
- L284 向量 `n_results` 12→20。
- L291 distance 阈值 0.6→0.65。
- L304 补充上限 `supplement[:5]`→`supplement[:15]`。

### 文件3：`app/services/knowledge_service.py`

**改动 L — `index_full_outline_to_rag`（L220-268）**
- characters 索引段：增加 `ability_baseline`（若有）。
- 顶层新增 foreshadowing 索引：遍历 `full_outline.foreshadowing`，每个生成一条 `[伏笔] Fid：描述（埋于第X卷，回收于第Y卷，状态）` 文档。
- 每卷新增索引：遍历 `character_dynamics`、`protagonist_abilities`，分别生成 `[卷N-角色情感]`、`[卷N-主角能力]` 文档，id 形如 `outline_volN_char_dynamics`、`outline_volN_protag_abilities`。

### 文件4：`static/js/app.js`

**改动 M — `renderFullOutline`（L252-305）**
- 在 `full-outline-info` 之后、volumes 循环之前，新增「伏笔总览」块：遍历 `fullOutline.foreshadowing`，展示 id/description/埋下卷/回收卷/状态。
- 在每卷 `volume-body` 内，`volume-meta` 之后新增：
  - 角色情感动态：遍历 `vol.character_dynamics` 展示 角色→情感状态→关键事件→情感变化。
  - 主角能力进阶：遍历 `vol.protagonist_abilities` 展示 能力→状态→变化→触发事件。
  - 本卷伏笔：展示 `vol.foreshadowing_ids`（逗号拼接，缺省提示“无”）。
- 缺字段时优雅降级（`|| []`）。

### 文件5：`static/js/outline.js`

**改动 N — `renderFullOutlineFullscreen`（L880-964）**
- 顶部编辑区新增「伏笔总览」可编辑区：遍历 `fo.foreshadowing`，每项生成 id/description/planted_in_volume/payoff_in_volume/status 输入框；并提供“新增伏笔”按钮。
- 每卷 `outline-edit-fields` 内新增：
  - 角色情感动态（可编辑文本，逗号或换行分隔；为降复杂度用多行 textarea，每行一条 `角色|情感状态|关键事件|情感变化`）。
  - 主角能力进阶（同上，每行 `能力|状态|变化|触发事件`）。
  - 本卷伏笔 id（逗号分隔 input）。

**改动 O — `saveFullOutlineFullscreen`（L970+）**
- 回收顶层 `foreshadowing`（含动态新增项）。
- 每卷回收 `character_dynamics`、`protagonist_abilities`（按行解析为结构化数组）、`foreshadowing_ids`（逗号分隔）。
- 缺省/空行过滤。

**改动 P — `editFullOutlineModal`（L736-803）与 `saveFullOutlineEdit`（L805-834）**
- 与全屏编辑器保持一致：弹窗也新增伏笔总览 + 每卷新字段输入；保存时回收。保证两条编辑路径都能修改新字段。

## 五、假设与决策

1. **不新建迁移**：`Novel.full_outline` 为 JSON dict，新增字段无需 DB 迁移；旧数据缺新字段时前端与 prompt 均优雅降级。
2. **max_tokens 提至 16384**：工程默认值；若实际模型窗口更小或仍截断，后续再调整。KB 注入上限提高会增大输入 token，但典型上下文窗口（32K+）可承载，暂不做硬截断，先验证效果。
3. **伏笔 id 由 LLM 生成**：prompt 指定形如 F1/F2…；前端编辑器允许用户增改，保存时原样回存。
4. **结构化数组编辑交互**：为降低复杂度，全屏/弹窗对 `character_dynamics`、`protagonist_abilities` 采用“每行一条、竖线分隔字段”的 textarea 形式保存时解析；伏笔总览用逐字段输入框。
5. **范围限定**：本次仅增强全文大纲 + 章节大纲 + KB 注入 + RAG 索引 + 全文大纲前端展示/编辑；不涉及“智能创建小说（扩写）”链路（上一会话已完成并验证）。
6. **章节大纲生成不改流式签名**：`generate_chapter_outline` 与其 SSE 调用不变，仅 prompt 与消息构建变化。

## 六、验证步骤

1. 语法校验：
   - `python -m py_compile app/agents/outline_agent.py app/services/kb_service.py app/services/knowledge_service.py`
   - `node --check static/js/app.js` 与 `node --check static/js/outline.js`
2. 烟雾测试（grep 确认关键符号落位）：
   - outline_agent.py：`character_dynamics`、`protagonist_abilities`、`foreshadowing`、`ability_baseline`、`emotion_beat`、`ability_state`、`foreshadowing_action`、`max_tokens=16384`。
   - kb_service.py：worldview=30、character=60、event=50、`supplement[:15]`。
   - knowledge_service.py：`foreshadowing`、`character_dynamics`、`protagonist_abilities` 索引分支。
   - app.js：`renderFullOutline` 含伏笔总览与每卷新字段。
   - outline.js：`renderFullOutlineFullscreen`/`saveFullOutlineFullscreen`/`editFullOutlineModal`/`saveFullOutlineEdit` 含新字段。
3. 端到端手工验证（用户侧）：
   - 选一本同人小说 → 生成全文大纲 → 确认输出含每卷 character_dynamics/protagonist_abilities/foreshadowing_ids 与顶层 foreshadowing。
   - 卡片视图展示新字段；全屏/弹窗编辑器可改新字段并保存。
   - 生成章节大纲 → 确认章节含 emotion_beat/ability_state/foreshadowing_action。
   - 确认同人知识库中角色/事件/世界观被大量注入（日志或返回长度可观察）。
