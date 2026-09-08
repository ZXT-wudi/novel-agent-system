let wizardState = null;

const WIZARD_STEPS = [
    {
        key: "title",
        question: "你好！我们来一起创建一部新小说吧 ✨\n首先，请告诉我这部小说的标题是什么？",
        placeholder: "输入小说标题...",
        chips: [{ label: "还没想好，先用「未命名小说」", value: "未命名小说" }],
        validate: (v) => (v && v.trim() ? null : "请输入小说标题"),
    },
    {
        key: "genre",
        question: "这部小说的题材是什么？如果是同人小说，需要准备原作知识库。",
        placeholder: "选择题材...",
        chips: [
            { label: "玄幻", value: "玄幻" },
            { label: "都市", value: "都市" },
            { label: "科幻", value: "科幻" },
            { label: "历史", value: "历史" },
            { label: "同人", value: "同人" },
            { label: "其他", value: "其他" },
        ],
        validate: (v) => (v && v.trim() ? null : "请选择题材"),
    },
    {
        key: "fanwork_kb",
        question: "同人小说需要原作知识库。请填写原作名，并选择或准备知识库。",
        inputType: "fanwork_kb",
        validate: (v) => (v && v.source_work && v.source_work.trim() && v.knowledge_base_id ? null : "请填写原作名并选择或创建知识库"),
    },
    {
        key: "content",
        question: "不错！接下来简单描述一下小说的大致内容吧——主要情节、世界观雏形或你想讲的故事都可以。",
        placeholder: "描述小说的大致内容、主要情节或核心看点...",
        inputType: "textarea",
        chips: [{ label: "我只有模糊想法，交给 AI 发挥", value: "我只有一个模糊的灵感，请帮我发散扩展成一个完整有趣的故事。" }],
        validate: (v) => (v && v.trim() ? null : "请描述小说的大致内容"),
    },
    {
        key: "writing_style",
        question: "你希望用怎样的写作风格？可以说明叙事人称、文风与节奏。",
        placeholder: "例如：第三人称、史诗宏大、节奏紧凑...",
        chips: [
            { label: "第三人称 · 史诗宏大", value: "第三人称，史诗宏大，节奏稳健，注重世界观与场面感" },
            { label: "第一人称 · 轻松幽默", value: "第一人称，轻松幽默，节奏明快，注重心理与口语化表达" },
            { label: "第三人称 · 细腻暗黑", value: "第三人称，细腻暗黑，氛围压抑，注重人物心理与悬念" },
            { label: "第二人称 · 沉浸式", value: "第二人称，沉浸式，代入感强，注重环境与感官描写" },
        ],
        validate: (v) => (v && v.trim() ? null : "请选择或输入写作风格"),
    },
    {
        key: "target",
        question: "最后，你计划写多长？选择一个篇幅，或自定义目标字数。",
        inputType: "length",
        chips: [
            { label: "短篇 · 约 20 万字", value: "200000" },
            { label: "长篇 · 约 80 万字", value: "800000" },
            { label: "长篇 · 约 150 万字", value: "1500000" },
        ],
        validate: (v) => (v && v.count > 0 ? null : "请选择或输入目标字数"),
    },
];

function startNovelWizard() {
    wizardState = {
        step: 0,
        answers: { title: "", content: "", writing_style: "", target_word_count: 0, length_type: "short" },
        novelId: null,
        settings: null,
        busy: false,
    };
    buildWizardDom();
    renderWizardStep();
}

function buildWizardDom() {
    const existing = document.getElementById("novel-wizard-overlay");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.className = "wizard-overlay";
    overlay.id = "novel-wizard-overlay";
    overlay.innerHTML = `
        <div class="wizard-modal">
            <div class="wizard-header">
                <h2>✨ 智能创建小说</h2>
                <button class="wizard-close" id="wizard-close-btn" title="关闭">✕</button>
            </div>
            <div class="wizard-progress">
                <div class="wizard-progress-bar" id="wizard-progress-bar"></div>
            </div>
            <div class="wizard-chat" id="wizard-chat"></div>
            <div class="wizard-input-area" id="wizard-input-area"></div>
        </div>
    `;
    document.body.appendChild(overlay);

    overlay.addEventListener("click", (e) => {
        if (e.target !== overlay) return;
        if (!wizardState || wizardState.busy) return;
        if (wizardState.novelId) return;
        closeNovelWizard();
    });

    document.getElementById("wizard-close-btn").addEventListener("click", () => {
        if (!wizardState || wizardState.busy) return;
        if (wizardState.novelId) {
            cancelNovelWizard();
        } else {
            closeNovelWizard();
        }
    });
}

function closeNovelWizard() {
    const overlay = document.getElementById("novel-wizard-overlay");
    if (overlay) overlay.remove();
    wizardState = null;
}

function updateWizardProgress() {
    const bar = document.getElementById("wizard-progress-bar");
    if (!bar) return;
    const isFanwork = wizardState.answers.genre === "同人";
    const total = WIZARD_STEPS.length - (isFanwork ? 0 : 1);
    const pct = Math.round((wizardState.step / total) * 100);
    bar.style.width = Math.min(pct, 100) + "%";
}

function escapeWizardHtml(str) {
    return String(str == null ? "" : str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function appendWizardBubble(role, text) {
    const chat = document.getElementById("wizard-chat");
    if (!chat) return null;
    const bubble = document.createElement("div");
    bubble.className = `wizard-bubble wizard-bubble-${role}`;
    bubble.innerHTML = escapeWizardHtml(text).replace(/\n/g, "<br>");
    chat.appendChild(bubble);
    chat.scrollTop = chat.scrollHeight;
    return bubble;
}

function renderWizardStep() {
    updateWizardProgress();
    const step = WIZARD_STEPS[wizardState.step];
    if (!step) return;
    // Skip fanwork_kb step if genre is not 同人
    if (step.key === "fanwork_kb" && wizardState.answers.genre !== "同人") {
        wizardState.step += 1;
        renderWizardStep();
        return;
    }
    appendWizardBubble("ai", step.question);
    renderWizardInput(step);
}

function renderWizardInput(step) {
    const area = document.getElementById("wizard-input-area");
    const inputType = step.inputType || "text";

    let inputHtml = "";
    if (inputType === "textarea") {
        inputHtml = `<textarea class="wizard-input" id="wizard-input" placeholder="${escapeWizardHtml(step.placeholder || "")}" rows="3"></textarea>`;
    } else if (inputType === "length") {
        inputHtml = `
            <div class="wizard-length-row">
                <input type="number" class="wizard-input" id="wizard-input" placeholder="自定义目标字数，如 300000" min="10000" step="10000">
                <span class="wizard-length-hint">字</span>
            </div>
        `;
    } else if (inputType === "fanwork_kb") {
        inputHtml = `
            <input type="text" class="wizard-input" id="wizard-source-work" placeholder="原作名称，如：无职转生" value="${escapeWizardHtml(wizardState.answers.source_work || "")}">
            <div class="wizard-kb-section">
                <div class="wizard-kb-section-label">选择已有知识库或新建：</div>
                <div class="wizard-kb-list" id="wizard-kb-list">
                    <div class="wizard-kb-loading">正在加载知识库...</div>
                </div>
                <button class="btn btn-outline wizard-kb-create-btn" id="wizard-create-kb-btn" type="button">➕ 为此原作新建知识库</button>
            </div>
        `;
    } else {
        inputHtml = `<input type="text" class="wizard-input" id="wizard-input" placeholder="${escapeWizardHtml(step.placeholder || "")}">`;
    }

    const chipsHtml = (step.chips || [])
        .map((c, i) => `<button class="wizard-chip" data-chip-idx="${i}">${escapeWizardHtml(c.label)}</button>`)
        .join("");

    const sendLabel = wizardState.step >= WIZARD_STEPS.length - 1 ? "开始扩写设定" : "下一步";

    area.innerHTML = `
        <div class="wizard-chips">${chipsHtml}</div>
        ${inputHtml}
        <div class="wizard-input-actions">
            <span class="wizard-error" id="wizard-error"></span>
            <button class="btn btn-primary" id="wizard-send-btn">${sendLabel}</button>
        </div>
    `;

    const input = document.getElementById("wizard-input");
    if (input) {
        input.focus();
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && (inputType !== "textarea" || (e.ctrlKey || e.metaKey))) {
                e.preventDefault();
                submitWizardAnswer();
            }
        });
    }

    const sourceInput = document.getElementById("wizard-source-work");
    if (sourceInput) {
        sourceInput.focus();
        sourceInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                submitWizardAnswer();
            }
        });
    }

    area.querySelectorAll(".wizard-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            const idx = parseInt(chip.dataset.chipIdx);
            applyWizardChip(step, step.chips[idx]);
        });
    });

    if (inputType === "fanwork_kb") {
        loadWizardKBList();
        const createBtn = document.getElementById("wizard-create-kb-btn");
        if (createBtn) {
            createBtn.addEventListener("click", createWizardKB);
        }
    }

    document.getElementById("wizard-send-btn").addEventListener("click", submitWizardAnswer);
}

function applyWizardChip(step, chip) {
    const input = document.getElementById("wizard-input");
    if (!input || !chip) return;
    if (step.key === "target") {
        input.value = chip.value;
    } else {
        input.value = chip.value;
    }
    input.focus();
}

async function loadWizardKBList() {
    const container = document.getElementById("wizard-kb-list");
    if (!container) return;
    try {
        const kbs = await apiGet("/api/knowledge-bases");
        const list = Array.isArray(kbs) ? kbs : [];
        if (list.length === 0) {
            container.innerHTML = `<div class="wizard-kb-empty">暂无知识库，请新建或稍后在知识库管理中准备</div>`;
            return;
        }
        const selectedKbId = wizardState.answers.knowledge_base_id;
        container.innerHTML = list.map(kb => `
            <label class="wizard-kb-option">
                <input type="radio" name="wizard-kb-select" value="${kb.id}" ${selectedKbId === kb.id ? "checked" : ""}>
                <div class="wizard-kb-info">
                    <div class="wizard-kb-name">${escapeWizardHtml(kb.name)}</div>
                    <div class="wizard-kb-meta">${escapeWizardHtml(kb.source_work || "未指定原作")} · ${kb.entry_count || 0} 条</div>
                </div>
            </label>
        `).join("");
    } catch (e) {
        container.innerHTML = `<div class="wizard-kb-error">加载失败：${escapeWizardHtml(e.message)}</div>`;
    }
}

async function createWizardKB() {
    const sourceInput = document.getElementById("wizard-source-work");
    const sourceWork = sourceInput ? sourceInput.value.trim() : "";
    const errorEl = document.getElementById("wizard-error");
    if (!sourceWork) {
        if (errorEl) errorEl.textContent = "请先输入原作名";
        return;
    }
    const btn = document.getElementById("wizard-create-kb-btn");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "创建中...";
    }
    try {
        const kb = await apiPost("/api/knowledge-bases", {
            name: `${sourceWork} 知识库`,
            genre: "同人",
            source_work: sourceWork,
            is_fanwork: true,
            description: `为《${sourceWork}》同人小说准备的知识库`
        });
        wizardState.answers.source_work = sourceWork;
        wizardState.answers.knowledge_base_id = kb.id;
        await loadWizardKBList();
        const radio = document.querySelector(`input[name="wizard-kb-select"][value="${kb.id}"]`);
        if (radio) radio.checked = true;
        if (errorEl) errorEl.textContent = "";
    } catch (e) {
        if (errorEl) errorEl.textContent = `创建失败：${e.message}`;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "➕ 为此原作新建知识库";
        }
    }
}

function submitWizardAnswer() {
    const step = WIZARD_STEPS[wizardState.step];
    const input = document.getElementById("wizard-input");
    const errorEl = document.getElementById("wizard-error");
    if (errorEl) errorEl.textContent = "";

    if (step.key === "target") {
        const count = parseInt(input.value);
        const err = step.validate({ count });
        if (err) {
            if (errorEl) errorEl.textContent = err;
            return;
        }
        const ltype = count >= 500000 ? "long" : "short";
        wizardState.answers.target_word_count = count;
        wizardState.answers.length_type = ltype;
        appendWizardBubble("user", `${count} 字（${ltype === "long" ? "长篇" : "短篇"}）`);
    } else if (step.key === "fanwork_kb") {
        const sourceInput = document.getElementById("wizard-source-work");
        const sourceWork = sourceInput ? sourceInput.value.trim() : "";
        const selected = document.querySelector('input[name="wizard-kb-select"]:checked');
        const kbId = selected && selected.value ? parseInt(selected.value) : null;
        const err = step.validate({ source_work: sourceWork, knowledge_base_id: kbId });
        if (err) {
            if (errorEl) errorEl.textContent = err;
            return;
        }
        wizardState.answers.source_work = sourceWork;
        wizardState.answers.knowledge_base_id = kbId;
        const kbText = kbId ? `已关联知识库 #${kbId}` : "暂未关联";
        appendWizardBubble("user", `原作：${sourceWork} | ${kbText}`);
    } else {
        const val = input.value;
        const err = step.validate(val);
        if (err) {
            if (errorEl) errorEl.textContent = err;
            return;
        }
        wizardState.answers[step.key] = val.trim();
        appendWizardBubble("user", val.trim());
    }

    wizardState.step += 1;
    if (wizardState.step >= WIZARD_STEPS.length) {
        proceedToExpand();
    } else {
        renderWizardStep();
    }
}

async function proceedToExpand() {
    updateWizardProgress();
    appendWizardBubble("ai", "好的，我正在根据你的回答扩写完整的小说设定，请稍候...");

    const area = document.getElementById("wizard-input-area");
    area.innerHTML = `<div class="wizard-loading"><span class="wizard-spinner"></span>AI 正在扩写小说设定...</div>`;

    wizardState.busy = true;
    try {
        const payload = {
            title: wizardState.answers.title,
            content: wizardState.answers.content,
            writing_style: wizardState.answers.writing_style,
            target_word_count: wizardState.answers.target_word_count,
            length_type: wizardState.answers.length_type,
            genre: wizardState.answers.genre || "",
            knowledge_base_id: wizardState.answers.knowledge_base_id || null,
        };
        const res = await apiPost("/api/novels/from-qa", payload);
        wizardState.novelId = res.novel_id;
        wizardState.settings = res.settings || {};
        appendWizardBubble("ai", "✅ 扩写完成！请查看下方设定摘要并确认。");
        renderWizardConfirmation(wizardState.settings);
    } catch (e) {
        appendWizardBubble("ai", `扩写失败：${e.message}。可以重试或取消。`);
        area.innerHTML = `
            <div class="wizard-input-actions">
                <button class="btn btn-outline" id="wizard-retry-btn">重试扩写</button>
                <button class="btn btn-danger" id="wizard-cancel-btn">取消</button>
            </div>
        `;
        document.getElementById("wizard-retry-btn").addEventListener("click", proceedToExpand);
        document.getElementById("wizard-cancel-btn").addEventListener("click", () => {
            if (wizardState && wizardState.novelId) {
                cancelNovelWizard();
            } else {
                closeNovelWizard();
            }
        });
    } finally {
        wizardState.busy = false;
    }
}

function renderWizardConfirmation(s) {
    const area = document.getElementById("wizard-input-area");
    const ws = s.world_settings || {};
    const chars = Array.isArray(s.characters) ? s.characters : [];
    const genreVal = wizardState.answers.genre || s.genre || "原创";

    const genreOptions = ["原创","同人","玄幻","都市","科幻","历史","悬疑","言情","其他"]
        .map(g => `<option value="${g}" ${g===genreVal?"selected":""}>${g}</option>`).join("");

    const povVal = s.narrative_pov || "第三人称";
    const povOptions = ["第一人称","第三人称","第二人称"]
        .map(p => `<option value="${p}" ${p===povVal?"selected":""}>${p}</option>`).join("");

    const lengthVal = s.length_type || "short";
    const lengthOptions = `<option value="short" ${lengthVal==="short"?"selected":""}>短篇</option><option value="long" ${lengthVal==="long"?"selected":""}>长篇</option>`;

    const worldHtml = `
        <div class="wizard-edit-row"><label>时代背景</label><input type="text" id="ws-era" value="${escapeWizardHtml(ws.era || "")}"></div>
        <div class="wizard-edit-row"><label>主要地点</label><input type="text" id="ws-location" value="${escapeWizardHtml(ws.location || "")}"></div>
        <div class="wizard-edit-row"><label>世界规则</label><textarea id="ws-rules" rows="2">${escapeWizardHtml(ws.rules || "")}</textarea></div>
        <div class="wizard-edit-row"><label>关键元素</label><input type="text" id="ws-key_elements" value="${escapeWizardHtml((ws.key_elements || []).join("、"))}"></div>
        <div class="wizard-edit-row"><label>力量体系</label><textarea id="ws-power_system" rows="2">${escapeWizardHtml(ws.power_system || "")}</textarea></div>
        <div class="wizard-edit-row"><label>社会结构</label><textarea id="ws-social_structure" rows="2">${escapeWizardHtml(ws.social_structure || "")}</textarea></div>
        <div class="wizard-edit-row"><label>核心冲突</label><textarea id="ws-core_conflict" rows="2">${escapeWizardHtml(ws.core_conflict || "")}</textarea></div>
        <div class="wizard-edit-row"><label>主题思想</label><input type="text" id="ws-theme" value="${escapeWizardHtml(ws.theme || "")}"></div>
    `;

    const charsHtml = chars
        .map((c, i) => `
            <div class="wizard-char-card" data-idx="${i}">
                <div class="wizard-char-head">
                    <input type="text" class="char-name" value="${escapeWizardHtml(c.name || "")}" placeholder="角色名">
                    <input type="text" class="char-role" value="${escapeWizardHtml(c.role || "")}" placeholder="角色定位">
                </div>
                <div class="wizard-char-line"><label>性格</label><textarea class="char-personality" rows="2">${escapeWizardHtml(c.personality || "")}</textarea></div>
                <div class="wizard-char-line"><label>背景</label><textarea class="char-background" rows="3">${escapeWizardHtml(c.background || "")}</textarea></div>
                <div class="wizard-char-line"><label>动机</label><textarea class="char-motivation" rows="3">${escapeWizardHtml(c.motivation || "")}</textarea></div>
            </div>
        `)
        .join("");

    area.innerHTML = `
        <div class="wizard-confirm-card">
            <div class="wizard-confirm-section">
                <div class="wizard-edit-row"><label>标题</label><input type="text" id="confirm-title" value="${escapeWizardHtml(s.title || "")}"></div>
                <div class="wizard-edit-row"><label>类型</label><select id="confirm-genre">${genreOptions}</select></div>
                ${genreVal === "同人" ? `
<div class="wizard-edit-row"><label>原作</label><input type="text" value="${escapeWizardHtml(wizardState.answers.source_work || "")}" disabled></div>
<div class="wizard-edit-row"><label>知识库</label><input type="text" value="${wizardState.answers.knowledge_base_id ? "已关联 #" + wizardState.answers.knowledge_base_id : "未关联"}" disabled></div>
` : ""}
                <div class="wizard-edit-row"><label>篇幅</label><select id="confirm-length_type">${lengthOptions}</select></div>
                <div class="wizard-edit-row"><label>目标字数</label><input type="number" id="confirm-target_word_count" value="${s.target_word_count || 0}"></div>
                <div class="wizard-edit-row"><label>叙事人称</label><select id="confirm-narrative_pov">${povOptions}</select></div>
                <div class="wizard-edit-row"><label>写作风格</label><input type="text" id="confirm-writing_style" value="${escapeWizardHtml(s.writing_style || "")}"></div>
            </div>
            <div class="wizard-confirm-section">
                <div class="wizard-confirm-section-title">简介</div>
                <textarea id="confirm-description" class="wizard-edit-desc" rows="4">${escapeWizardHtml(s.description || "")}</textarea>
            </div>
            <div class="wizard-confirm-section">
                <div class="wizard-confirm-section-title">世界观</div>
                ${worldHtml}
            </div>
            <div class="wizard-confirm-section">
                <div class="wizard-confirm-section-title">主要角色</div>
                <div class="wizard-char-list">${charsHtml || '<span class="wizard-confirm-muted">暂无</span>'}</div>
            </div>
        </div>
        <div class="wizard-input-actions">
            <button class="btn btn-danger" id="wizard-cancel-btn">取消（删除此次创建）</button>
            <button class="btn btn-outline" id="wizard-reexpand-btn">🔄 重新扩写</button>
            <button class="btn btn-success" id="wizard-confirm-btn">确认，开始生成全文大纲</button>
        </div>
    `;

    document.getElementById("wizard-confirm-btn").addEventListener("click", confirmNovelWizard);
    document.getElementById("wizard-cancel-btn").addEventListener("click", cancelNovelWizard);
    document.getElementById("wizard-reexpand-btn").addEventListener("click", reExpandNovel);
}

function collectEditedSettings() {
    const val = (id) => (document.getElementById(id) ? document.getElementById(id).value.trim() : "");
    const settings = {
        title: val("confirm-title") || (wizardState.settings && wizardState.settings.title) || "未命名小说",
        genre: val("confirm-genre"),
        description: val("confirm-description"),
        length_type: val("confirm-length_type"),
        target_word_count: parseInt(val("confirm-target_word_count"), 10) || 0,
        narrative_pov: val("confirm-narrative_pov"),
        writing_style: val("confirm-writing_style"),
        world_settings: {
            era: val("ws-era"),
            location: val("ws-location"),
            rules: val("ws-rules"),
            key_elements: val("ws-key_elements") ? val("ws-key_elements").split(/、|,/).map(s => s.trim()).filter(Boolean) : [],
            power_system: val("ws-power_system"),
            social_structure: val("ws-social_structure"),
            core_conflict: val("ws-core_conflict"),
            theme: val("ws-theme"),
        },
        characters: [],
    };
    document.querySelectorAll(".wizard-char-card").forEach(card => {
        settings.characters.push({
            name: card.querySelector(".char-name") ? card.querySelector(".char-name").value.trim() : "",
            role: card.querySelector(".char-role") ? card.querySelector(".char-role").value.trim() : "",
            personality: card.querySelector(".char-personality") ? card.querySelector(".char-personality").value.trim() : "",
            background: card.querySelector(".char-background") ? card.querySelector(".char-background").value.trim() : "",
            motivation: card.querySelector(".char-motivation") ? card.querySelector(".char-motivation").value.trim() : "",
        });
    });
    return settings;
}

async function reExpandNovel() {
    if (!wizardState || wizardState.busy) return;
    if (wizardState.novelId) {
        try {
            await apiDelete(`/api/novels/${wizardState.novelId}`);
        } catch (e) {
            console.error("清理旧小说失败:", e);
        }
        wizardState.novelId = null;
    }
    wizardState.settings = null;
    proceedToExpand();
}

async function confirmNovelWizard() {
    if (!wizardState || wizardState.busy) return;
    const novelId = wizardState.novelId;
    if (!novelId) {
        closeNovelWizard();
        return;
    }

    wizardState.busy = true;
    const area = document.getElementById("wizard-input-area");
    if (area) {
        area.innerHTML = `<div class="wizard-loading"><span class="wizard-spinner"></span>正在保存编辑后的设定...</div>`;
    }

    try {
        const edited = collectEditedSettings();
        appState.pendingOutlineSettings = edited;
        await apiPut(`/api/novels/${novelId}`, edited);
    } catch (e) {
        wizardState.busy = false;
        appState.pendingOutlineSettings = null;
        alert("保存设定失败: " + e.message);
        renderWizardConfirmation(wizardState.settings || {});
        return;
    }

    closeNovelWizard();

    try {
        await loadNovelList();
        const select = document.getElementById("novel-select");
        select.value = novelId;
        appState.currentNovelId = novelId;
        await onNovelSelected(novelId);
        updateStatusBar("小说创建成功，正在自动生成全文大纲...");
        await generateFullOutline();
    } catch (e) {
        console.error("确认小说创建失败:", e);
        updateStatusBar("小说创建后衔接失败: " + e.message);
    } finally {
        wizardState.busy = false;
    }
}

async function cancelNovelWizard() {
    if (!wizardState) return;
    const novelId = wizardState.novelId;

    if (novelId) {
        wizardState.busy = true;
        const area = document.getElementById("wizard-input-area");
        if (area) {
            area.innerHTML = `<div class="wizard-loading"><span class="wizard-spinner"></span>正在清理已创建的小说...</div>`;
        }
        try {
            await apiDelete(`/api/novels/${novelId}`);
            await loadNovelList();
            updateStatusBar("已取消小说创建");
        } catch (e) {
            console.error("清理小说失败:", e);
            updateStatusBar("取消失败: " + e.message);
        }
    }

    closeNovelWizard();
}
