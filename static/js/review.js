let reviewDecisions = {};
let currentPolishedDraft = "";

function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

function appendPolishChunk(text) {
    const polishMount = document.getElementById("polish-compare-mount");
    if (!polishMount) return;

    if (!document.getElementById("polish-polished")) {
        const chapterDraft = (typeof writingContent !== "undefined" && writingContent) || (typeof currentChapterContent !== "undefined" && currentChapterContent) || "";
        polishMount.innerHTML = `
            <div class="polish-compare-card" id="polish-compare-card">
                <div class="polish-compare-header">
                    <span class="polish-badge">AI 文章润色师</span>
                    <span class="polish-subtitle">正在润色，请稍候...</span>
                </div>
                <div class="polish-panes">
                    <div class="polish-pane">
                        <div class="polish-pane-title">原文</div>
                        <div class="polish-pane-body" id="polish-original"></div>
                    </div>
                    <div class="polish-pane polish-pane-accent">
                        <div class="polish-pane-title">润色文</div>
                        <div class="polish-pane-body" id="polish-polished"></div>
                    </div>
                </div>
            </div>`;
        polishMount.style.display = "block";
        const origEl = document.getElementById("polish-original");
        if (origEl) origEl.textContent = chapterDraft;
        const chapterText = document.getElementById("chapter-text");
        if (chapterText) chapterText.style.display = "none";
    }

    const polEl = document.getElementById("polish-polished");
    if (polEl) {
        polEl.textContent += text;
        polEl.scrollTop = polEl.scrollHeight;
    }
}

function showReviewPanel(state) {
    const panel = document.getElementById("review-panel");
    const body = document.getElementById("review-body");
    const summary = document.getElementById("review-summary");
    const actions = document.getElementById("review-actions");
    const polishMount = document.getElementById("polish-compare-mount");
    const chapterText = document.getElementById("chapter-text");

    reviewDecisions = {};

    const comments = state.review_comments || [];
    const writerDecisions = state.writer_decisions || [];
    const pendingDecisions = state.pending_user_decisions || [];
    const chapterDraft = state.chapter_draft || "";
    const polishedDraft = state.polished_draft || "";

    if (polishMount) {
        if (polishedDraft && chapterDraft && polishedDraft !== chapterDraft) {
            currentPolishedDraft = polishedDraft;
            polishMount.innerHTML = `
                <div class="polish-compare-card" id="polish-compare-card">
                    <div class="polish-compare-header">
                        <span class="polish-badge">AI 文章润色师</span>
                        <span class="polish-subtitle">已完成整章润色，请对比审阅后决定是否采纳</span>
                    </div>
                    <div class="polish-panes">
                        <div class="polish-pane">
                            <div class="polish-pane-title">原文</div>
                            <div class="polish-pane-body" id="polish-original"></div>
                        </div>
                        <div class="polish-pane polish-pane-accent">
                            <div class="polish-pane-title">润色文</div>
                            <div class="polish-pane-body" id="polish-polished"></div>
                        </div>
                    </div>
                    <div class="polish-actions">
                        <button class="btn btn-primary" onclick="acceptPolish()">一键采纳润色版</button>
                        <button class="btn btn-outline" onclick="dismissPolish()">暂不采纳</button>
                    </div>
                </div>`;
            polishMount.style.display = "block";
            const origEl = document.getElementById("polish-original");
            const polEl = document.getElementById("polish-polished");
            if (origEl) origEl.textContent = chapterDraft;
            if (polEl) polEl.textContent = polishedDraft;
            if (chapterText) chapterText.style.display = "none";
        } else {
            currentPolishedDraft = "";
            polishMount.innerHTML = "";
            polishMount.style.display = "none";
            if (chapterText) chapterText.style.display = "block";
        }
    }

    const hasComments = writerDecisions.length > 0 || pendingDecisions.length > 0;
    if (hasComments) {
        panel.style.display = "block";
        summary.textContent = `共${comments.length}条意见 | 写手已采纳${writerDecisions.length}条 | 待您决策${pendingDecisions.length}条`;

        let html = "";

        writerDecisions.forEach((d, i) => {
            const comment = d.original_comment || {};
            html += `
                <div class="review-card accepted">
                    <div class="review-card-header">
                        <span class="review-reader-type ${comment.reader_type || 'general'}">${getReaderTypeName(comment.reader_type)}</span>
                        <span class="writer-decision">写手已采纳</span>
                    </div>
                    <div class="review-comment">${escapeHtml(comment.comment || '')}</div>
                    <div class="review-suggestion">修改方案：${escapeHtml(d.revision_plan || comment.suggestion || '')}</div>
                </div>
            `;
        });

        pendingDecisions.forEach((d, i) => {
            const comment = d.original_comment || {};
            const id = d.comment_id || `pending_${i}`;
            reviewDecisions[id] = "pending";

            html += `
                <div class="review-card" id="review-card-${id}">
                    <div class="review-card-header">
                        <span class="review-reader-type ${comment.reader_type || 'general'}">${getReaderTypeName(comment.reader_type)}</span>
                        <span class="review-severity ${comment.severity || 'medium'}">${getSeverityName(comment.severity)}</span>
                    </div>
                    <div class="review-comment">${escapeHtml(comment.comment || d.reason || '')}</div>
                    <div class="review-suggestion">建议：${escapeHtml(comment.suggestion || '')}</div>
                    <div class="review-decision">
                        <button class="btn btn-sm btn-success" onclick="decideReview('${id}', 'accept_suggestion')">采纳建议</button>
                        <button class="btn btn-sm btn-danger" onclick="decideReview('${id}', 'reject')">拒绝</button>
                        <button class="btn btn-sm btn-warning" onclick="showCustomInput('${id}')">自定义修改</button>
                    </div>
                    <div class="custom-input" id="custom-input-${id}">
                        <textarea id="custom-text-${id}" placeholder="输入您的修改内容..."></textarea>
                        <button class="btn btn-sm btn-primary" onclick="submitCustomDecision('${id}')">确认</button>
                    </div>
                </div>
            `;
        });

        body.innerHTML = html;
        actions.style.display = pendingDecisions.length > 0 ? "flex" : "none";
    } else {
        panel.style.display = "none";
        body.innerHTML = "";
        actions.style.display = "none";
    }
}

function getReaderTypeName(type) {
    const map = { character: "人物", logic: "逻辑", style: "文笔" };
    return map[type] || type || "综合";
}

function getSeverityName(severity) {
    const map = { high: "重要", medium: "中等", low: "轻微" };
    return map[severity] || severity || "中等";
}

function decideReview(id, action) {
    reviewDecisions[id] = action;
    const card = document.getElementById(`review-card-${id}`);
    if (card) {
        if (action === "accept_suggestion") {
            card.classList.add("accepted");
            card.querySelector(".review-decision").innerHTML = '<span class="writer-decision" style="color:var(--success)">已采纳</span>';
        } else if (action === "reject") {
            card.classList.add("rejected");
            card.querySelector(".review-decision").innerHTML = '<span class="writer-decision" style="color:var(--danger)">已拒绝</span>';
        }
    }
}

function showCustomInput(id) {
    const input = document.getElementById(`custom-input-${id}`);
    if (input) input.style.display = "block";
}

function submitCustomDecision(id) {
    const text = document.getElementById(`custom-text-${id}`).value.trim();
    if (!text) { alert("请输入修改内容"); return; }
    reviewDecisions[id] = "custom";
    reviewDecisions[`${id}_text`] = text;

    const card = document.getElementById(`review-card-${id}`);
    if (card) {
        card.classList.add("accepted");
        card.querySelector(".review-decision").innerHTML = `<span class="writer-decision" style="color:var(--warning)">自定义修改</span>`;
    }
}

async function submitDecisions() {
    const novelId = getSelectedNovelId();
    if (!novelId || !appState.currentChapter) return;

    const decisions = [];
    for (const [id, action] of Object.entries(reviewDecisions)) {
        if (id.endsWith("_text")) continue;
        if (action === "pending") continue;

        const decision = { comment_id: id, action: action };
        if (action === "custom") {
            decision.custom_text = reviewDecisions[`${id}_text`] || "";
        }

        const pendingItem = (currentChapterState?.pending_user_decisions || []).find(
            d => d.comment_id === id || `pending_${(currentChapterState?.pending_user_decisions || []).indexOf(d)}` === id
        );
        if (pendingItem) {
            decision.original_text = pendingItem.original_comment?.comment || "";
            decision.suggestion = pendingItem.original_comment?.suggestion || "";
            decision.modification_type = pendingItem.original_comment?.aspect || "style";
        }

        decisions.push(decision);
    }

    if (decisions.length === 0) {
        alert("请至少对一条意见做出决策");
        return;
    }

    setWritingStatus("writing", "正在应用决策并润色...");
    updateStatusBar("正在应用决策并润色，可能需要一些时间，请稍候...");
    try {
        const result = await apiPost(
            `/api/novels/${novelId}/chapters/${appState.currentChapter}/decide`,
            { decisions: decisions }
        );

        if (result.is_final) {
            if (result.polished_draft && result.polished_draft !== result.chapter_draft) {
                currentChapterState = result;
                currentChapterContent = result.chapter_draft || currentChapterContent;
                showReviewPanel(result);
                setWritingStatus("waiting", "AI 润色完成，请审阅");
                updateStatusBar("AI 文章润色师已完成润色，请审阅采纳");
                document.getElementById("btn-save-chapter").disabled = false;
            } else {
                currentChapterContent = result.polished_draft || result.chapter_draft || currentChapterContent;
                document.getElementById("chapter-text").textContent = currentChapterContent;
                hideReviewPanel();
                setWritingStatus("done", "章节已完成");
                updateStatusBar("章节写作完成");
                document.getElementById("btn-save-chapter").disabled = true;
            }
        } else if (result.chapter_draft) {
            currentChapterContent = result.chapter_draft;
            document.getElementById("chapter-text").textContent = currentChapterContent;
            if (result.pending_user_decisions && result.pending_user_decisions.length > 0) {
                currentChapterState = result;
                showReviewPanel(result);
                setWritingStatus("waiting", "仍有待决策意见");
            } else {
                hideReviewPanel();
                setWritingStatus("done", "修订完成");
            }
        }
    } catch (e) {
        alert("提交决策失败: " + e.message);
        setWritingStatus("waiting", "提交失败");
    }
}

function acceptAllSuggestions() {
    for (const [id, action] of Object.entries(reviewDecisions)) {
        if (id.endsWith("_text")) continue;
        if (action === "pending") {
            decideReview(id, "accept_suggestion");
        }
    }
}

function rejectAllSuggestions() {
    for (const [id, action] of Object.entries(reviewDecisions)) {
        if (id.endsWith("_text")) continue;
        if (action === "pending") {
            decideReview(id, "reject");
        }
    }
}

function hideReviewPanel() {
    document.getElementById("review-panel").style.display = "none";
}

function acceptPolish() {
    const polished = currentPolishedDraft;
    if (!polished) return;
    currentChapterContent = polished;
    if (currentChapterState) currentChapterState.chapter_draft = polished;
    isEditMode = true;
    contentModified = true;
    const textEl = document.getElementById("chapter-text");
    if (textEl) textEl.style.display = "none";
    const editorEl = document.getElementById("chapter-editor");
    if (editorEl) {
        editorEl.style.display = "block";
        editorEl.value = currentChapterContent;
        editorEl.oninput = () => { contentModified = true; };
    }
    const btnEdit = document.getElementById("btn-edit");
    if (btnEdit) btnEdit.textContent = "预览";
    const mount = document.getElementById("polish-compare-mount");
    if (mount) { mount.innerHTML = ""; mount.style.display = "none"; }
    currentPolishedDraft = "";
    document.getElementById("btn-save-chapter").disabled = false;
    setWritingStatus("done", "已采纳润色版");
    updateStatusBar("已采纳 AI 润色版，可继续修改，点击「保存章节」后生效并更新知识库");
    if (document.querySelectorAll("#review-body .review-card").length === 0) {
        hideReviewPanel();
    }
}

function dismissPolish() {
    const mount = document.getElementById("polish-compare-mount");
    if (mount) { mount.innerHTML = ""; mount.style.display = "none"; }
    currentPolishedDraft = "";
    const textEl = document.getElementById("chapter-text");
    if (textEl && currentChapterContent) {
        textEl.style.display = "block";
        textEl.textContent = currentChapterContent;
    }
    contentModified = true;
    document.getElementById("btn-save-chapter").disabled = false;
    if (document.querySelectorAll("#review-body .review-card").length === 0) {
        hideReviewPanel();
        setWritingStatus("done", "已保留原文");
        updateStatusBar("已保留原文，点击「保存章节」后生效");
    }
}
