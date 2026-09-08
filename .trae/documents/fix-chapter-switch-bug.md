# 修复章节切换内容丢失 + 下拉标题重复

## 问题概述

### Bug 1: 切换章节时未保存内容跑到另一章节 + 回切报错

**现象**: 创作完一章未点"保存章节"就切换到另一章，内容跑到另一章下方；再切回原章报错。

**根因**: [chapter.js#L450-L509 `loadChapter()`](file:///d:/xiaoshuo/static/js/chapter.js#L450-L509) 切换时：
1. **不检查未保存内容** — 无警告直接切换
2. **不中止 AI 写作流** — `chapterWriting=true` 且切到别的章时，流仍在后台跑，`complete` 事件会把内容写到 `appState.currentChapter`（已是新章号）→ 内容存进错误的章节
3. **不清空状态变量** — `writingContent`/`currentChapterContent`/`currentChapterState`/`isEditMode` 残留旧值，后端拉取失败时显示脏数据

### Bug 2: 下拉框显示"第一章：第一章"

**根因**: 保存时 title 写死为 `第N章`，下拉渲染又加 `第N章:` 前缀 → 双重叠加。

- [chapter.js#L528 `saveDraft`](file:///d:/xiaoshuo/static/js/chapter.js#L528): `title: \`第${appState.currentChapter}章\``
- [chapter.js#L561 `saveCurrentChapter`](file:///d:/xiaoshuo/static/js/chapter.js#L561): `title: chapter-title-display.textContent`（该元素在 L84/L228 被设为 `第${nextChapter}章`）
- [chapter.js#L613 `loadChapterList`](file:///d:/xiaoshuo/static/js/chapter.js#L613): `第${ch.chapter_number}章: ${ch.title}` → 前缀+已存储的 `第N章` = 重复
- [chapters.py#L103](file:///d:/xiaoshuo/app/api/chapters.py#L103): 后端兜底也是 `f"第{chapter_num}章"`

大纲数据 `currentOutline`（[outline.js#L1](file:///d:/xiaoshuo/static/js/outline.js#L1)）里存了 AI 生成的真实标题（如"风云起"），但保存章节时没有用它。

---

## 修改方案

### 改动 1: 新增 `hasUnsavedContent()` 辅助函数 — chapter.js

**位置**: [chapter.js](file:///d:/xiaoshuo/static/js/chapter.js) 全局函数区（~L13 后新增）

**逻辑**:
```javascript
function hasUnsavedContent() {
    // AI 写作进行中
    if (chapterWriting) return true;
    // 手动写作模式有内容
    if (manualWriting) {
        const el = document.getElementById("manual-editor");
        if (el && el.innerText.trim()) return true;
    }
    // 编辑模式有内容
    if (isEditMode) {
        const editorEl = document.getElementById("chapter-editor");
        if (editorEl && editorEl.value.trim()) return true;
    }
    // 有章节状态但未保存（currentChapterState 存在且 polished_draft 非空或有审查结果）
    if (currentChapterState && (currentChapterState.polished_draft || currentChapterState.chapter_draft)) {
        return true;
    }
    // 有内容但不在编辑模式（草稿态）
    if (!isEditMode && currentChapterContent && currentChapterContent.trim()) {
        return true;
    }
    return false;
}
```

**目的**: 统一判断"当前章是否有未落盘的内容"

---

### 改动 2: 新增 `clearChapterState()` 辅助函数 — chapter.js

**位置**: [chapter.js](file:///d:/xiaoshuo/static/js/chapter.js) 全局函数区

**逻辑**:
```javascript
function clearChapterState() {
    writingContent = "";
    currentChapterContent = "";
    currentChapterState = null;
    isEditMode = false;
    if (typeof currentPolishedDraft !== "undefined") currentPolishedDraft = "";
    // 隐藏润色对比面板
    const mount = document.getElementById("polish-compare-mount");
    if (mount) { mount.innerHTML = ""; mount.style.display = "none"; }
    // 恢复章节文本区显示
    const chapterText = document.getElementById("chapter-text");
    if (chapterText) chapterText.style.display = "block";
    const editorEl = document.getElementById("chapter-editor");
    if (editorEl) editorEl.style.display = "none";
    const manualEl = document.getElementById("manual-editor");
    if (manualEl) manualEl.style.display = "none";
    // 恢复编辑按钮文字
    const btnEdit = document.getElementById("btn-edit");
    if (btnEdit) btnEdit.textContent = "编辑";
    const draftBtn = document.getElementById("btn-save-draft");
    if (draftBtn) draftBtn.style.display = "none";
}
```

**目的**: 切换前彻底清空内存状态 + UI 面板，杜绝脏数据残留

---

### 改动 3: 改造 `loadChapter()` — chapter.js L450-509

**改前**:
```javascript
async function loadChapter(chapterNumber) {
    if (manualWriting) { ... }
    clearTimeout(autoSaveTimer); autoSaveTimer = null;
    // 直接加载，不检查未保存内容
    ...
}
```

**改后**:
```javascript
async function loadChapter(chapterNumber) {
    const prevChapter = appState.currentChapter;
    const isSameChapter = chapterNumber === prevChapter;

    // 同一章 + AI写作中 → 复用内存
    if (isSameChapter && chapterWriting) {
        // ... 保持原 L462-470 逻辑
        return true;
    }

    // 不同章 + 有未保存内容 → 弹窗三选一
    if (!isSameChapter && hasUnsavedContent()) {
        const choice = confirm("当前章节有未保存的内容。\n点击「确定」保存后切换，点击「取消」丢弃内容直接切换。");
        if (choice) {
            // 用户选"确定" → 先保存
            if (chapterWriting && chapterAbortController) {
                chapterAbortController.abort();
                chapterAbortController = null;
                chapterWriting = false;
            }
            await saveCurrentChapter();
        } else {
            // 用户选"取消" → 丢弃
            if (chapterWriting && chapterAbortController) {
                chapterAbortController.abort();
                chapterAbortController = null;
                chapterWriting = false;
            }
        }
    }

    // 中止 AI 写作（切到别的章时）
    if (chapterWriting && !isSameChapter) {
        if (chapterAbortController) {
            chapterAbortController.abort();
            chapterAbortController = null;
        }
        chapterWriting = false;
    }

    // 清理手动写作
    if (manualWriting) {
        manualWriting = false;
        clearSuggestionState();
        const manualEl = document.getElementById("manual-editor");
        if (manualEl) manualEl.style.display = "none";
    }
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;

    // 彻底清空状态
    clearChapterState();

    const novelId = getSelectedNovelId();
    if (!novelId) return false;

    appState.currentChapter = chapterNumber;

    // 加载新章
    try {
        const chapter = await apiGet(`/api/novels/${novelId}/chapters/${chapterNumber}`);
        if (chapter) {
            currentChapterContent = chapter.content || "";
            // ... 保持原 L476-504 渲染逻辑
        }
        return true;
    } catch (e) {
        document.getElementById("chapter-text").textContent = "该章节尚未创建";
        return true;  // 切换本身成功了（即使该章不存在）
    }
}
```

**关键变化**:
1. 返回 `true/false`（是否切换成功 / 是否取消）
2. 切换前检查未保存内容 → `confirm()` 三选一
3. 中止 AI 写作流
4. 调用 `clearChapterState()` 彻底清空

**注意**: 使用浏览器原生 `confirm()` 而非自定义弹窗，因为 `confirm()` 是同步阻塞的，在 `change` 事件中能自然工作。文案为"确定=保存后切换 / 取消=丢弃切换"。这比三按钮弹窗更简洁。

---

### 改动 4: 改造章节下拉 change 事件 — app.js L418-425

**改前**:
```javascript
document.getElementById("chapter-select").addEventListener("change", (e) => {
    const chapterNum = parseInt(e.target.value);
    if (chapterNum) {
        appState.currentChapter = chapterNum;
        loadChapter(chapterNum);
        renderOutline();
    }
});
```

**改后**:
```javascript
document.getElementById("chapter-select").addEventListener("change", async (e) => {
    const chapterNum = parseInt(e.target.value);
    if (!chapterNum) return;
    const prevChapter = appState.currentChapter;
    const success = await loadChapter(chapterNum);
    if (!success) {
        e.target.value = prevChapter || "";  // 用户取消 → 回退下拉选中项
        return;
    }
    renderOutline();
});
```

**关键变化**:
1. `async` 化
2. `appState.currentChapter` 的更新移入 `loadChapter` 内部（改动 3），避免提前赋值导致取消时状态不一致
3. 用户取消 → 回退下拉 value

---

### 改动 5: 改造 `selectOutlineChapter()` — outline.js L661-665

**改前**:
```javascript
function selectOutlineChapter(chapterNumber) {
    appState.currentChapter = chapterNumber;
    loadChapter(chapterNumber);
    renderOutline();
}
```

**改后**:
```javascript
async function selectOutlineChapter(chapterNumber) {
    const success = await loadChapter(chapterNumber);
    if (!success) return;
    renderOutline();
    // 同步下拉选中
    const select = document.getElementById("chapter-select");
    if (select) select.value = chapterNumber;
}
```

---

### 改动 6: 新增 `getChapterTitleFromOutline()` 辅助 — chapter.js

**位置**: [chapter.js](file:///d:/xiaoshuo/static/js/chapter.js) 全局函数区

```javascript
function getChapterTitleFromOutline(chapterNum) {
    if (typeof currentOutline !== "undefined" && currentOutline) {
        const item = currentOutline.find(o => o.chapter_number === chapterNum);
        if (item && item.title) return item.title;
    }
    return `第${chapterNum}章`;  // fallback
}
```

**目的**: 从大纲获取真实章节标题，而非写死"第N章"

---

### 改动 7: 修复 `startAiWriting()` 中标题显示 — chapter.js L84

**改前**: `document.getElementById("chapter-title-display").textContent = \`第${nextChapter}章\`;`

**改后**: `document.getElementById("chapter-title-display").textContent = getChapterTitleFromOutline(nextChapter);`

---

### 改动 8: 修复 `startManualWriting()` 中标题显示 — chapter.js L228

同改动 7，将 `第${nextChapter}章` 改为 `getChapterTitleFromOutline(nextChapter)`

---

### 改动 9: 修复 `loadChapter()` 中标题显示 — chapter.js L466, L479

- L466 (AI写作中复用): 改为 `getChapterTitleFromOutline(chapterNumber)`
- L479 (后端加载): 保持 `chapter.title || getChapterTitleFromOutline(chapterNumber)` — 优先用 DB 存的 title

---

### 改动 10: 修复 `saveDraft()` 中 title — chapter.js L528

**改前**: `title: \`第${appState.currentChapter}章\``

**改后**: `title: getChapterTitleFromOutline(appState.currentChapter)`

---

### 改动 11: 修复 `saveCurrentChapter()` 中 title — chapter.js L561

**改前**: `title: document.getElementById("chapter-title-display").textContent`

**改后**: `title: getChapterTitleFromOutline(appState.currentChapter)`

**理由**: `chapter-title-display` 的内容在改动 7/8/9 后已是真实标题，但直接用 helper 更可靠（避免 display 元素被意外修改）

---

### 改动 12: 修复下拉渲染格式 — chapter.js L613

**改前**: `option.textContent = \`第${ch.chapter_number}章: ${ch.title || '未命名'} (${getStatusText(ch.status)})\`;`

**改后**:
```javascript
const chapterTitle = ch.title && !ch.title.match(/^第\d+章$/) ? ch.title : getChapterTitleFromOutline(ch.chapter_number);
option.textContent = `第${ch.chapter_number}章「${chapterTitle || '未命名'}」(${getStatusText(ch.status)})`;
```

**逻辑**: 如果 DB 里的 title 是 "第N章" 模式（旧数据），则从大纲取真实标题替换；否则用 DB 的 title。格式改为 `第N章「标题」（状态）`，与大纲页风格一致。

---

### 改动 13: 后端兜底 title 保持不变 — chapters.py L103

**现状**: `title = data.get("title", f"第{chapter_num}章")`

**不改**: 前端改动 10/11 后已传入真实标题，后端兜底仅在前端未传时触发，是合理的最后防线。

---

## 假设与决策

1. **使用浏览器原生 `confirm()` 而非自定义弹窗**: `confirm()` 同步阻塞，在 `change` 事件中能自然工作；自定义弹窗需要 Promise + 事件循环，在 `change` 回调中处理下拉回退更复杂。
2. **"确定=保存后切换，取消=丢弃切换"**: 比三按钮弹窗更简洁，覆盖 90% 场景。用户想保存就点确定，想丢弃就点取消。
3. **`currentOutline` 全局可访问**: outline.js L1 `let currentOutline = []` 是全局变量，chapter.js 可直接访问。
4. **旧数据兼容**: 下拉渲染时检测 title 是否为 "第N章" 模式，是则从大纲取真实标题，避免已有数据仍显示重复。
5. **`loadChapter` 返回 boolean**: `true` = 已切换（含目标章不存在的情况），`false` = 用户取消。调用方据此决定是否回退下拉。

---

## 验证步骤

### Bug 1 验证（内容丢失 + 回切报错）

1. **AI写作进行中切换**:
   - 启动 AI 写第 1 章，写作进行中切到第 2 章
   - 预期: 弹出 confirm → 点取消 → 丢弃内容，切到第 2 章，第 1 章不会被写入错误内容
   - 预期: 弹出 confirm → 点确定 → 先保存第 1 章再切到第 2 章

2. **AI写作完成后未保存切换**:
   - AI 写完第 1 章（complete 事件到达，草稿模式）不点保存，切到第 2 章
   - 预期: 弹出 confirm → 选保存/丢弃
   - 切回第 1 章: 正常加载已保存的内容或"尚未创建"（如果丢弃了）

3. **手动写作未保存切换**:
   - 手动写第 1 章输入一些内容，切到第 2 章
   - 预期: 弹出 confirm
   - 切回: 内容正确（保存了）或空（丢弃了）

4. **切回原章不报错**:
   - 任何切换场景后切回原章，不应出现 JS 错误或状态混乱

### Bug 2 验证（标题重复）

5. **新保存的章节**:
   - AI 写第 3 章并保存 → 下拉显示 `第3章「真实大纲标题」（草稿）`，不重复

6. **已有旧数据**:
   - DB 中 title 为 "第1章" 的旧章节 → 下拉显示 `第1章「大纲里的真实标题」（已定稿）`，从大纲取标题替换

7. **大纲未确认时**:
   - `currentOutline` 为空 → `getChapterTitleFromOutline` 回退到 `第N章`，下拉显示 `第N章「第N章」`，可接受（边缘场景）
