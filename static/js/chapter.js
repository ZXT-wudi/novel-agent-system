let isEditMode = false;
let currentChapterContent = "";
let writingContent = "";
let currentChapterState = null;
let chapterWriting = false;
let chapterAbortController = null;
let manualWriting = false;
let suggestDebounceTimer = null;
let autoSaveTimer = null;
let suggestAbortController = null;
let currentSuggestion = "";
let suggestionPending = false;
let ghostMutationInProgress = false;
let contentModified = false;

function hasUnsavedContent() {
    if (chapterWriting) return true;
    if (contentModified) return true;
    return false;
}

function clearChapterState() {
    writingContent = "";
    currentChapterContent = "";
    currentChapterState = null;
    isEditMode = false;
    contentModified = false;
    if (typeof currentPolishedDraft !== "undefined") currentPolishedDraft = "";
    const mount = document.getElementById("polish-compare-mount");
    if (mount) { mount.innerHTML = ""; mount.style.display = "none"; }
    const chapterText = document.getElementById("chapter-text");
    if (chapterText) chapterText.style.display = "block";
    const editorEl = document.getElementById("chapter-editor");
    if (editorEl) editorEl.style.display = "none";
    const manualEl = document.getElementById("manual-editor");
    if (manualEl) manualEl.style.display = "none";
    const btnEdit = document.getElementById("btn-edit");
    if (btnEdit) btnEdit.textContent = "编辑";
    const draftBtn = document.getElementById("btn-save-draft");
    if (draftBtn) draftBtn.style.display = "none";
}

function getChapterTitleFromOutline(chapterNum) {
    if (typeof currentOutline !== "undefined" && currentOutline) {
        const item = currentOutline.find(o => o.chapter_number === chapterNum);
        if (item && item.title) return item.title;
    }
    return `第${chapterNum}章`;
}

async function startWriting() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    const novel = appState.novels.find(n => n.id === novelId);
    if (novel && novel.status === "planning") {
        alert("请先确认大纲后再开始写作");
        return;
    }

    if (chapterWriting) {
        if (confirm("章节正在写作中，是否取消当前写作？")) {
            if (chapterAbortController) {
                chapterAbortController.abort();
                chapterAbortController = null;
            }
            chapterWriting = false;
            setWritingStatus("done", "已取消");
        }
        return;
    }

    const modal = document.getElementById("modal-content");
    modal.innerHTML = `
        <h2>选择写作模式</h2>
        <div style="display:flex;flex-direction:column;gap:12px;margin:16px 0;">
            <button type="button" style="display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:16px;width:100%;border:1px solid var(--border);border-radius:8px;background:transparent;cursor:pointer;text-align:left;" onclick="closeModal(); startAiWriting();">
                <strong>AI 自动写作</strong>
                <small style="color:var(--text-muted);">AI 根据大纲自动生成整章，生成后可修改</small>
            </button>
            <button type="button" style="display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:16px;width:100%;border:1px solid var(--border);border-radius:8px;background:transparent;cursor:pointer;text-align:left;" onclick="closeModal(); startManualWriting();">
                <strong>手动写作（AI 辅助补全）</strong>
                <small style="color:var(--text-muted);">亲自撰写，AI 实时续写建议，按 Tab 补全</small>
            </button>
        </div>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">取消</button>
        </div>
    `;
    showModal();
}

async function startAiWriting() {
    if (manualWriting) {
        manualWriting = false;
        clearSuggestionState();
        const manualEl = document.getElementById("manual-editor");
        if (manualEl) manualEl.style.display = "none";
    }
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
    const draftBtn = document.getElementById("btn-save-draft");
    if (draftBtn) draftBtn.style.display = "none";
    const novelId = getSelectedNovelId();
    const nextChapter = getNextChapterNumber();
    appState.currentChapter = nextChapter;

    chapterWriting = true;
    chapterAbortController = new AbortController();
    currentChapterContent = "";
    writingContent = "";
    contentModified = true;
    setWritingStatus("writing", `正在写第${nextChapter}章...`);
    showChapterProgress();
    updateStatusBar(`正在生成第${nextChapter}章...`);

    document.getElementById("welcome-screen").style.display = "none";
    const polishMount = document.getElementById("polish-compare-mount");
    if (polishMount) { polishMount.innerHTML = ""; polishMount.style.display = "none"; }
    if (typeof currentPolishedDraft !== "undefined") currentPolishedDraft = "";
    document.getElementById("chapter-text").style.display = "block";
    document.getElementById("chapter-header").style.display = "flex";
    document.getElementById("chapter-title-display").textContent = getChapterTitleFromOutline(nextChapter);
    document.getElementById("chapter-text").textContent = "";
    updateChapterStatusBadge("writing");
    const versionEl = document.getElementById("chapter-version");
    if (versionEl) versionEl.textContent = "v0";

    const select = document.getElementById("chapter-select");
    if (select && !Array.from(select.options).some(o => parseInt(o.value) === nextChapter)) {
        const opt = document.createElement("option");
        opt.value = nextChapter;
        opt.textContent = `第${nextChapter}章: 生成中...`;
        select.appendChild(opt);
    }
    if (select) select.value = nextChapter;

    try {
        const response = await fetch(`/api/novels/${novelId}/chapters/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chapter_number: nextChapter, stream: true }),
            signal: chapterAbortController.signal,
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({ detail: `请求失败 (HTTP ${response.status})` }));
            throw new Error(errData.detail || `请求失败`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);
                    if (data.type === "content") {
                        writingContent += data.text;
                        currentChapterContent = writingContent;
                        const textEl = document.getElementById("chapter-text");
                        textEl.textContent = currentChapterContent;
                        textEl.scrollTop = textEl.scrollHeight;
                    } else if (data.type === "status") {
                        const msg = data.message || "";
                        if (data.phase === "writing") {
                            setWritingStatus("writing", msg || "正在写作...");
                        } else if (data.phase === "reviewing") {
                            setWritingStatus("reviewing", msg || "正在审查...");
                            updateStatusBar(msg || "读者智能体正在审查...");
                        } else if (data.phase === "evaluating") {
                            setWritingStatus("reviewing", msg || "正在评估...");
                            updateStatusBar(msg || "写手智能体正在评估...");
                        } else if (data.phase === "revising") {
                            setWritingStatus("writing", msg || "正在修订...");
                            updateStatusBar(msg || "写手智能体正在修订...");
                        } else if (data.phase === "polishing") {
                            setWritingStatus("reviewing", msg || "正在润色...");
                            updateStatusBar(msg || "AI 文章润色师正在润色...");
                        } else if (data.phase === "curating_psychology") {
                            setWritingStatus("writing", msg || "正在推演角色心理...");
                            updateStatusBar(msg || "角色心理分析师正在推演...");
                        }
                    } else if (data.type === "polish_content") {
                        appendPolishChunk(data.text || "");
                    } else if (data.type === "complete") {
                        const result = data.data || {};
                        currentChapterState = result;
                        hideChapterProgress();
                        document.getElementById("btn-save-chapter").disabled = false;

                        const hasPending = result.pending_user_decisions && result.pending_user_decisions.length > 0;
                        const hasPolish = result.polished_draft;
                        if (!hasPending && !hasPolish) {
                            const mount = document.getElementById("polish-compare-mount");
                            if (mount) { mount.innerHTML = ""; mount.style.display = "none"; }
                            const textEl = document.getElementById("chapter-text");
                            if (textEl) textEl.style.display = "block";
                        }

                        if (hasPending) {
                            setWritingStatus("waiting", "等待您的决策");
                            showReviewPanel(result);
                            updateStatusBar("有审查意见需要您决策");
                        } else if (hasPolish) {
                            setWritingStatus("waiting", "AI 润色完成，请审阅");
                            showReviewPanel(result);
                            updateStatusBar("AI 文章润色师已完成润色，请审阅采纳");
                        } else if (result.is_final) {
                            setWritingStatus("done", "章节已完成");
                            updateStatusBar(`第${nextChapter}章写作完成`);
                            saveCurrentChapter();
                        } else {
                            setWritingStatus("done", "章节草稿完成");
                            updateStatusBar(`第${nextChapter}章草稿完成`);
                        }

                        if (result.chapter_draft) {
                            writingContent = result.chapter_draft;
                            currentChapterContent = writingContent;
                            document.getElementById("chapter-text").textContent = currentChapterContent;
                        }

                        updateChapterStatusBadge(result.current_phase || "draft");
                        renderOutline();
                    } else if (data.type === "error") {
                        throw new Error(data.error || "生成失败");
                    }
                } catch (e) {
                    if (e.message && !e.message.includes("JSON")) throw e;
                }
            }
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            setWritingStatus("done", "已取消");
            updateStatusBar("写作已取消");
        } else {
            setWritingStatus("done", "写作失败");
            hideChapterProgress();
            document.getElementById("btn-save-chapter").disabled = !currentChapterContent;
            if (!currentChapterContent) {
                document.getElementById("chapter-text").textContent = "写作失败，请重试";
            }
            alert("写作失败: " + (error.message || "未知错误"));
        }
    } finally {
        chapterWriting = false;
        chapterAbortController = null;
    }
}

function startManualWriting() {
    const nextChapter = getNextChapterNumber();
    appState.currentChapter = nextChapter;

    chapterWriting = true;
    chapterAbortController = new AbortController();
    currentChapterContent = "";
    writingContent = "";
    manualWriting = true;
    contentModified = true;
    document.getElementById("welcome-screen").style.display = "none";
    document.getElementById("chapter-text").style.display = "none";
    document.getElementById("chapter-header").style.display = "flex";
    document.getElementById("chapter-title-display").textContent = getChapterTitleFromOutline(nextChapter);

    setWritingStatus("writing", "手动写作中...");
    updateStatusBar("手动写作第" + nextChapter + "章，输入内容，AI 将提供续写建议");
    updateChapterStatusBadge("writing");
    const versionEl = document.getElementById("chapter-version");
    if (versionEl) versionEl.textContent = "v0";

    const select = document.getElementById("chapter-select");
    if (select && !Array.from(select.options).some(o => parseInt(o.value) === nextChapter)) {
        const opt = document.createElement("option");
        opt.value = nextChapter;
        opt.textContent = `第${nextChapter}章: 手动写作中...`;
        select.appendChild(opt);
    }
    if (select) select.value = nextChapter;

    const textEl = document.getElementById("chapter-text");
    const textareaEl = document.getElementById("chapter-editor");
    const editorEl = document.getElementById("manual-editor");
    textEl.style.display = "none";
    if (textareaEl) textareaEl.style.display = "none";
    editorEl.style.display = "block";
    isEditMode = true;
    editorEl.innerHTML = "";
    document.getElementById("btn-save-chapter").disabled = true;
    const draftBtn = document.getElementById("btn-save-draft");
    if (draftBtn) draftBtn.style.display = "inline-flex";
    clearSuggestionState();

    editorEl.removeEventListener("input", handleManualInput);
    editorEl.removeEventListener("keydown", handleManualKeydown);
    editorEl.addEventListener("input", handleManualInput);
    editorEl.addEventListener("keydown", handleManualKeydown);

    setTimeout(() => editorEl.focus(), 0);
}

function handleManualInput() {
    if (!manualWriting || ghostMutationInProgress) return;
    const editorEl = document.getElementById("manual-editor");
    contentModified = true;
    currentSuggestion = "";
    hideGhostText();
    if (suggestAbortController) {
        suggestAbortController.abort();
        suggestAbortController = null;
    }

    document.getElementById("btn-save-chapter").disabled = !editorEl.innerText;

    clearTimeout(suggestDebounceTimer);
    suggestDebounceTimer = setTimeout(() => requestSuggestion(), 1000);

    clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(saveDraft, 30000);
}

async function requestSuggestion() {
    if (!manualWriting) return;
    const novelId = getSelectedNovelId();
    const chapterNum = appState.currentChapter;
    if (!novelId || !chapterNum) return;

    const editorEl = document.getElementById("manual-editor");
    const text = editorEl ? editorEl.innerText : "";
    if (!text || text.trim().length < 5) {
        currentSuggestion = "";
        hideGhostText();
        return;
    }

    if (suggestAbortController) {
        suggestAbortController.abort();
    }
    suggestAbortController = new AbortController();
    const localController = suggestAbortController;
    const signal = localController.signal;
    suggestionPending = true;

    try {
        const resp = await fetch(`/api/novels/${novelId}/chapters/${chapterNum}/suggest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ current_text: text }),
            signal: signal,
        });
        if (signal.aborted) return;
        if (!resp.ok) {
            currentSuggestion = "";
            hideGhostText();
            return;
        }
        const data = await resp.json();
        if (signal.aborted) return;
        const suggestion = data.suggestion || "";
        if (suggestion && manualWriting && !signal.aborted) {
            currentSuggestion = suggestion;
            showGhostText(suggestion);
        } else {
            currentSuggestion = "";
            hideGhostText();
        }
    } catch (e) {
        if (e.name !== "AbortError") {
            currentSuggestion = "";
            hideGhostText();
        }
    } finally {
        if (suggestAbortController === localController) {
            suggestAbortController = null;
        }
        suggestionPending = false;
    }
}

function showGhostText(text) {
    const editor = document.getElementById("manual-editor");
    if (!editor) return;
    hideGhostText();

    ghostMutationInProgress = true;
    try {
        const span = document.createElement("span");
        span.className = "ghost-text";
        span.id = "current-ghost";
        span.textContent = text;
        editor.appendChild(span);

        const sel = window.getSelection();
        const range = document.createRange();
        range.setStartAfter(span);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
        editor.focus();
    } finally {
        ghostMutationInProgress = false;
    }
}

function hideGhostText() {
    const ghost = document.getElementById("current-ghost");
    if (ghost && ghost.parentNode) {
        ghost.parentNode.removeChild(ghost);
    }
}

function clearSuggestionState() {
    currentSuggestion = "";
    suggestionPending = false;
    clearTimeout(suggestDebounceTimer);
    suggestDebounceTimer = null;
    if (suggestAbortController) {
        suggestAbortController.abort();
        suggestAbortController = null;
    }
    hideGhostText();
}

function acceptSuggestion() {
    if (!manualWriting || !currentSuggestion) return;
    const editor = document.getElementById("manual-editor");
    if (!editor) return;
    const text = currentSuggestion;
    const ghost = document.getElementById("current-ghost");

    ghostMutationInProgress = true;
    try {
        let textNode;
        if (ghost && ghost.parentNode) {
            textNode = document.createTextNode(text);
            ghost.parentNode.replaceChild(textNode, ghost);
        } else {
            textNode = document.createTextNode(text);
            editor.appendChild(textNode);
        }

        const sel = window.getSelection();
        const range = document.createRange();
        range.setStartAfter(textNode);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
    } finally {
        ghostMutationInProgress = false;
    }

    document.getElementById("btn-save-chapter").disabled = !editor.innerText;
    currentSuggestion = "";
    hideGhostText();
    if (suggestAbortController) {
        suggestAbortController.abort();
        suggestAbortController = null;
    }
    clearTimeout(suggestDebounceTimer);
    suggestDebounceTimer = setTimeout(() => requestSuggestion(), 800);
    editor.focus();
}

function handleManualKeydown(e) {
    if (!manualWriting) return;

    if (e.key === "Tab") {
        e.preventDefault();
        if (currentSuggestion) {
            acceptSuggestion();
        }
    } else if (e.key === "Escape") {
        if (currentSuggestion) {
            e.preventDefault();
            currentSuggestion = "";
            hideGhostText();
            clearTimeout(suggestDebounceTimer);
            if (suggestAbortController) {
                suggestAbortController.abort();
                suggestAbortController = null;
            }
        }
    }
}

async function loadChapter(chapterNumber) {
    const prevChapter = appState.currentChapter;
    const isSameChapter = chapterNumber === prevChapter;

    if (isSameChapter && chapterWriting) {
        document.getElementById("welcome-screen").style.display = "none";
        document.getElementById("chapter-text").style.display = "block";
        document.getElementById("chapter-header").style.display = "flex";
        document.getElementById("chapter-title-display").textContent = getChapterTitleFromOutline(chapterNumber);
        document.getElementById("chapter-text").textContent = writingContent;
        updateChapterStatusBadge("writing");
        return true;
    }

    if (isSameChapter) {
        return true;
    }

    if (!isSameChapter && hasUnsavedContent()) {
        const choice = confirm("当前章节有未保存的内容。\n点击「确定」保存后切换，点击「取消」丢弃内容直接切换。");
        if (choice) {
            if (chapterWriting && chapterAbortController) {
                chapterAbortController.abort();
                chapterAbortController = null;
                chapterWriting = false;
            }
            if (writingContent && !currentChapterContent) {
                currentChapterContent = writingContent;
            }
            await saveCurrentChapter();
        } else {
            if (chapterWriting && chapterAbortController) {
                chapterAbortController.abort();
                chapterAbortController = null;
                chapterWriting = false;
            }
        }
    }

    if (chapterWriting && !isSameChapter) {
        if (chapterAbortController) {
            chapterAbortController.abort();
            chapterAbortController = null;
        }
        chapterWriting = false;
    }

    if (manualWriting) {
        manualWriting = false;
        clearSuggestionState();
        const manualEl = document.getElementById("manual-editor");
        if (manualEl) manualEl.style.display = "none";
    }
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;

    clearChapterState();

    const novelId = getSelectedNovelId();
    if (!novelId) return false;

    appState.currentChapter = chapterNumber;

    try {
        const chapter = await apiGet(`/api/novels/${novelId}/chapters/${chapterNumber}`);
        if (chapter) {
            currentChapterContent = chapter.content || "";
            document.getElementById("welcome-screen").style.display = "none";
            document.getElementById("chapter-text").style.display = "block";
            document.getElementById("chapter-header").style.display = "flex";
            document.getElementById("chapter-title-display").textContent = chapter.title || getChapterTitleFromOutline(chapterNumber);
            document.getElementById("chapter-text").textContent = currentChapterContent;
            document.getElementById("chapter-status-badge").textContent = getStatusText(chapter.status);
            document.getElementById("chapter-status-badge").className = `badge badge-${chapter.status}`;
            document.getElementById("chapter-version").textContent = `v${chapter.version}`;
            document.getElementById("btn-save-chapter").disabled = false;
            updateChapterStatusBadge(chapter.status);

            const draftBtn = document.getElementById("btn-save-draft");
            if (chapter.status === "draft") {
                updateStatusBar("这是草稿，可继续编辑");
                isEditMode = true;
                const textEl = document.getElementById("chapter-text");
                const editorEl = document.getElementById("chapter-editor");
                textEl.style.display = "none";
                if (editorEl) {
                    editorEl.style.display = "block";
                    editorEl.value = currentChapterContent;
                    editorEl.oninput = () => { contentModified = true; };
                }
                const btnEdit = document.getElementById("btn-edit");
                if (btnEdit) btnEdit.textContent = "预览";
                if (draftBtn) draftBtn.style.display = "inline-flex";
                document.getElementById("btn-save-chapter").disabled = false;
            } else {
                if (draftBtn) draftBtn.style.display = "none";
            }
        }
        return true;
    } catch (e) {
        document.getElementById("chapter-text").textContent = "该章节尚未创建";
        return true;
    }
}

async function saveDraft() {
    if (chapterWriting && !manualWriting) return;

    const novelId = getSelectedNovelId();
    if (!novelId || !appState.currentChapter) return;

    const content = isEditMode
        ? (manualWriting
            ? document.getElementById("manual-editor").innerText
            : document.getElementById("chapter-editor").value)
        : currentChapterContent;

    if (!content || content.trim().length < 1) return;

    try {
        await apiPost(`/api/novels/${novelId}/chapters/${appState.currentChapter}/save`, {
            content: content,
            title: getChapterTitleFromOutline(appState.currentChapter),
            status: 'draft'
        });
        setWritingStatus("done", "草稿已保存");
        updateStatusBar("草稿已自动保存");
        contentModified = false;
    } catch (e) {
        console.error("草稿自动保存失败:", e);
    }
}

async function saveCurrentChapter() {
    const novelId = getSelectedNovelId();
    if (!novelId || !appState.currentChapter) {
        updateStatusBar("请先选择要保存的章节");
        return;
    }

    const content = isEditMode
        ? (manualWriting
            ? document.getElementById("manual-editor").innerText
            : document.getElementById("chapter-editor").value)
        : currentChapterContent;

    const saveBtn = document.getElementById("btn-save-chapter");
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中...";
    setWritingStatus("reviewing", "正在保存");
    updateStatusBar("正在保存章节，AI 正在同步知识库与知识图谱，可能需要约半分钟，请稍候...");

    try {
        await apiPost(`/api/novels/${novelId}/chapters/${appState.currentChapter}/save`, {
            content: content,
            title: getChapterTitleFromOutline(appState.currentChapter),
        });
        updateStatusBar("章节已保存，知识库与知识图谱已同步");
        setWritingStatus("done", "已保存");
        await loadChapterList(novelId);
        manualWriting = false;
        contentModified = false;
        clearSuggestionState();
    } catch (e) {
        alert("保存失败: " + e.message);
        saveBtn.disabled = false;
    } finally {
        saveBtn.textContent = originalText;
    }
}

function toggleEditMode() {
    isEditMode = !isEditMode;
    const textEl = document.getElementById("chapter-text");
    const editorEl = document.getElementById("chapter-editor");
    const btnEdit = document.getElementById("btn-edit");

    if (isEditMode) {
        textEl.style.display = "none";
        editorEl.style.display = "block";
        editorEl.value = currentChapterContent;
        editorEl.oninput = () => { contentModified = true; };
        btnEdit.textContent = "预览";
        document.getElementById("btn-save-chapter").disabled = false;
    } else {
        editorEl.style.display = "none";
        textEl.style.display = "block";
        currentChapterContent = editorEl.value;
        textEl.textContent = currentChapterContent;
        btnEdit.textContent = "编辑";
    }
}

function getNextChapterNumber() {
    const select = document.getElementById("chapter-select");
    const existing = Array.from(select.options)
        .filter(o => o.value)
        .map(o => parseInt(o.value));
    return existing.length > 0 ? Math.max(...existing) + 1 : 1;
}

async function loadChapterList(novelId) {
    try {
        const chapters = await apiGet(`/api/novels/${novelId}/chapters`);
        const select = document.getElementById("chapter-select");
        select.innerHTML = '<option value="">选择章节...</option>';
        chapters.forEach(ch => {
            const option = document.createElement("option");
            option.value = ch.chapter_number;
            const chapterTitle = ch.title && !ch.title.match(/^第\d+章$/) ? ch.title : getChapterTitleFromOutline(ch.chapter_number);
            option.textContent = `第${ch.chapter_number}章「${chapterTitle || '未命名'}」(${getStatusText(ch.status)})`;
            select.appendChild(option);
        });
    } catch (e) {
        console.error("加载章节列表失败:", e);
    }
}

function getStatusText(status) {
    const map = {
        draft: "草稿",
        reviewing: "审查中",
        revised: "已修订",
        final: "已定稿",
        planning: "规划中",
        writing: "写作中",
        completed: "已完成",
    };
    return map[status] || status;
}

function updateChapterStatusBadge(status) {
    const badge = document.getElementById("chapter-status-badge");
    badge.textContent = getStatusText(status);
    badge.className = `badge badge-${status === 'finalized' ? 'final' : status}`;
}

function showChapterProgress() {
    document.getElementById("chapter-progress").style.display = "block";
    document.getElementById("progress-fill").style.width = "0%";
    document.getElementById("progress-text").textContent = "0%";
}

function hideChapterProgress() {
    document.getElementById("chapter-progress").style.display = "none";
}

function updateProgress(percent) {
    document.getElementById("progress-fill").style.width = percent + "%";
    document.getElementById("progress-text").textContent = percent + "%";
}
