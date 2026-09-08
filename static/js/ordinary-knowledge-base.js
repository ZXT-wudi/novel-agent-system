let okbManagerOpen = false;
let okbCurrentId = null;
let okbDetailCache = null;

const ORDINARY_DIMENSIONS = [
    { key: "theme", label: "主题的挖掘与立意", icon: "🎯" },
    { key: "character_arc", label: "人物弧光", icon: "👤" },
    { key: "plot_structure", label: "情节结构与节奏控制", icon: "📐" },
    { key: "narrative_pov", label: "叙事视角与叙述声音", icon: "👁" },
    { key: "language_style", label: "语言风格与细节描写", icon: "✍" },
    { key: "worldbuilding", label: "世界观与规则自洽", icon: "🌍" },
    { key: "emotional_resonance", label: "情感共鸣与余味", icon: "💫" },
];

function okbEscape(s) {
    if (typeof escapeHtml === "function") return escapeHtml(s);
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

function openOrdinaryKBManager() {
    const existing = document.getElementById("okb-overlay");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "okb-overlay";
    overlay.className = "kb-overlay";
    overlay.innerHTML = `
        <div class="kb-panel">
            <div class="kb-header">
                <h3 id="okb-title">📖 普通知识库管理</h3>
                <div class="kb-header-actions" id="okb-header-actions"></div>
                <button class="btn btn-sm btn-outline" onclick="closeOrdinaryKBManager()">关闭</button>
            </div>
            <div class="kb-body" id="okb-body">
                <div class="kb-loading">加载中...</div>
            </div>
            <div class="kb-modal" id="okb-modal" style="display:none;"></div>
        </div>
    `;
    document.body.appendChild(overlay);
    setTimeout(() => overlay.classList.add("visible"), 10);
    okbManagerOpen = true;
    okbShowListView();
}

function closeOrdinaryKBManager() {
    const overlay = document.getElementById("okb-overlay");
    if (overlay) {
        overlay.classList.remove("visible");
        setTimeout(() => { if (overlay) overlay.remove(); }, 200);
    }
    okbManagerOpen = false;
    okbCurrentId = null;
    okbDetailCache = null;
}

function okbSetHeaderActions(html) {
    const el = document.getElementById("okb-header-actions");
    if (el) el.innerHTML = html;
}

function okbSetTitle(text) {
    const el = document.getElementById("okb-title");
    if (el) el.textContent = text;
}

function okbSetBody(html) {
    const el = document.getElementById("okb-body");
    if (el) el.innerHTML = html;
}

/* ===================== 列表视图 ===================== */

let okbListData = [];

function okbShowListView() {
    okbCurrentId = null;
    okbDetailCache = null;
    okbSetTitle("📖 普通知识库管理");
    okbSetHeaderActions(`<button class="btn btn-sm btn-primary" onclick="okbShowCreateForm()">+ 新建知识库</button>`);
    okbSetBody(`
        <div class="kb-toolbar">
            <input type="text" class="kb-search" id="okb-search" placeholder="搜索知识库名称 / 参考作品..." oninput="okbRenderList()">
            <span class="kb-count" id="okb-count"></span>
        </div>
        <div class="kb-list" id="okb-list"><div class="kb-loading">加载中...</div></div>
    `);
    okbLoadList();
}

async function okbLoadList() {
    const listEl = document.getElementById("okb-list");
    if (!listEl) return;
    listEl.innerHTML = '<div class="kb-loading">加载中...</div>';
    try {
        const items = await apiGet("/api/ordinary-knowledge-bases");
        okbListData = Array.isArray(items) ? items : [];
        okbRenderList();
    } catch (e) {
        listEl.innerHTML = `<div class="kb-empty">加载失败：${okbEscape(e.message)}</div>`;
    }
}

function okbRenderList() {
    const listEl = document.getElementById("okb-list");
    if (!listEl) return;
    const searchEl = document.getElementById("okb-search");
    const kw = (searchEl && searchEl.value || "").trim().toLowerCase();
    let items = okbListData;
    if (kw) {
        items = items.filter(it =>
            (it.name || "").toLowerCase().includes(kw) ||
            (it.source_work || "").toLowerCase().includes(kw) ||
            (it.genre || "").toLowerCase().includes(kw)
        );
    }

    const countEl = document.getElementById("okb-count");
    if (countEl) countEl.textContent = `共 ${items.length} 个知识库`;

    if (items.length === 0) {
        listEl.innerHTML = '<div class="kb-empty">暂无知识库，点击右上角"新建知识库"创建</div>';
        return;
    }

    listEl.innerHTML = `<div class="kb-grid">` + items.map(it => {
        const genreBadge = it.genre ? `<span class="kb-tag">${okbEscape(it.genre)}</span>` : "";
        let importBadge = "";
        if (it.import_status === "processing") {
            const p = it.import_progress || {};
            const dc = (p.done_chunks || []).length;
            const tc = p.total_chunks || 0;
            importBadge = `<span class="kb-tag" style="background:#fef3c7;color:#b45309">⏳ 提取中 ${dc}/${tc}块</span>`;
        } else if (it.import_status === "completed") {
            importBadge = `<span class="kb-tag" style="background:#dcfce7;color:#15803d">✓ 已提取</span>`;
        } else if (it.import_status === "partial") {
            importBadge = `<span class="kb-tag" style="background:#fee2e2;color:#b91c1c">⚠ 部分完成</span>`;
        }
        const sourceLine = it.source_work
            ? `<div class="kb-card-source">参考：${okbEscape(it.source_work)}</div>` : "";
        const desc = it.description ? `<div class="kb-card-desc">${okbEscape(it.description.length > 80 ? it.description.slice(0, 80) + "…" : it.description)}</div>` : "";
        return `
            <div class="kb-card" onclick="okbLoadDetail(${it.id})">
                <div class="kb-card-head">
                    <div class="kb-card-name">${okbEscape(it.name)}</div>
                    <div class="kb-card-badges">${genreBadge}${importBadge}</div>
                </div>
                ${sourceLine}
                ${desc}
                <div class="kb-card-foot">
                    <span class="kb-card-count">📝 ${it.entry_count || 0} 条目</span>
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); okbDelete(${it.id}, '${okbEscape(it.name).replace(/'/g, "\\'")}')">删除</button>
                </div>
            </div>
        `;
    }).join("") + `</div>`;
}

async function okbDelete(kbId, name) {
    if (!confirm(`确定删除知识库「${name}」及其所有条目？此操作不可恢复。`)) return;
    try {
        await apiDelete(`/api/ordinary-knowledge-bases/${kbId}`);
        await okbLoadList();
    } catch (e) {
        alert("删除失败：" + e.message);
    }
}

/* ===================== 新建知识库表单 ===================== */

function okbShowCreateForm() {
    const genreOpts = (typeof KB_GENRES !== "undefined" ? KB_GENRES : ["玄幻","都市","科幻","历史","同人","其他"])
        .map(g => `<option value="${g}">${g}</option>`).join("");
    okbOpenModal("新建普通知识库", `
        <div class="kb-form">
            <div class="kb-form-row">
                <label>名称 *</label>
                <input type="text" id="okb-new-name" placeholder="如：斗破苍穹·写作技法库">
            </div>
            <div class="kb-form-row">
                <label>题材</label>
                <select id="okb-new-genre">${genreOpts}</select>
            </div>
            <div class="kb-form-row">
                <label>参考作品</label>
                <input type="text" id="okb-new-source" placeholder="如：斗破苍穹（可选）">
            </div>
            <div class="kb-form-row">
                <label>描述</label>
                <textarea id="okb-new-desc" rows="3" placeholder="可选，知识库用途说明"></textarea>
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="okb-new-error"></span>
                <button class="btn btn-outline" onclick="okbCloseModal()">取消</button>
                <button class="btn btn-primary" onclick="okbSubmitCreate()">创建</button>
            </div>
        </div>
    `);
}

async function okbSubmitCreate() {
    const name = document.getElementById("okb-new-name").value.trim();
    const errEl = document.getElementById("okb-new-error");
    if (errEl) errEl.textContent = "";
    if (!name) { if (errEl) errEl.textContent = "请填写名称"; return; }
    const genre = document.getElementById("okb-new-genre").value;
    const sourceWork = document.getElementById("okb-new-source").value.trim();
    const desc = document.getElementById("okb-new-desc").value.trim();
    try {
        await apiPost("/api/ordinary-knowledge-bases", {
            name, genre, source_work: sourceWork, description: desc
        });
        okbCloseModal();
        await okbLoadList();
    } catch (e) {
        if (errEl) errEl.textContent = "创建失败：" + e.message;
    }
}

/* ===================== 详情视图 ===================== */

async function okbLoadDetail(kbId) {
    okbCurrentId = kbId;
    okbSetHeaderActions(`<button class="btn btn-sm btn-outline" onclick="okbShowListView()">← 返回列表</button>`);
    okbSetTitle("加载中...");
    okbSetBody('<div class="kb-loading">加载中...</div>');
    try {
        const detail = await apiGet(`/api/ordinary-knowledge-bases/${kbId}`);
        okbDetailCache = detail;
        okbRenderDetail(detail);
    } catch (e) {
        okbSetTitle("知识库详情");
        okbSetBody(`<div class="kb-empty">加载失败：${okbEscape(e.message)}</div>`);
    }
}

function okbRenderDetail(detail) {
    const genreBadge = detail.genre ? `<span class="kb-tag">${okbEscape(detail.genre)}</span>` : "";
    const sourceLine = detail.source_work ? `<span class="kb-detail-source">参考：${okbEscape(detail.source_work)}</span>` : "";

    okbSetTitle(detail.name || "知识库详情");
    okbSetHeaderActions(`
        <button class="btn btn-sm btn-outline" onclick="okbShowListView()">← 返回列表</button>
        <button class="btn btn-sm btn-primary" onclick="okbShowUploadFile()">📤 上传文件</button>
    `);

    let importStatusBadge = "";
    if (detail.import_status === "processing") {
        const p = detail.import_progress || {};
        const dc = (p.done_chunks || []).length;
        const tc = p.total_chunks || 0;
        importStatusBadge = `<span class="kb-tag" style="background:#fef3c7;color:#b45309">⏳ 提取中 ${dc}/${tc}块</span>`;
    } else if (detail.import_status === "completed") {
        importStatusBadge = `<span class="kb-tag" style="background:#dcfce7;color:#15803d">✓ 已提取</span>`;
    } else if (detail.import_status === "partial") {
        importStatusBadge = `<span class="kb-tag" style="background:#fee2e2;color:#b91c1c">⚠ 部分完成</span>`;
    }

    const entries = detail.entries || [];
    const entryMap = {};
    entries.forEach(e => { entryMap[e.dimension] = e; });

    const sections = ORDINARY_DIMENSIONS.map(dim => {
        const entry = entryMap[dim.key];
        const hasData = !!entry;
        return okbSectionHtml(dim, hasData, entry);
    }).join("");

    okbSetBody(`
        <div class="kb-detail">
            <div class="kb-detail-header">
                <div class="kb-detail-title">${okbEscape(detail.name || "")}</div>
                <div class="kb-detail-meta">
                    ${genreBadge}${importStatusBadge}${sourceLine}
                    <span class="kb-detail-total">共 ${entries.length}/7 维度</span>
                </div>
                ${detail.description ? `<div class="kb-detail-desc">${okbEscape(detail.description)}</div>` : ""}
            </div>
            <div class="kb-sections" id="okb-sections">${sections}</div>
        </div>
    `);
}

function okbSectionHtml(dim, hasData, entry) {
    const content = (entry && entry.content) || "";
    const isLong = content.length > 200 || content.indexOf("\n") >= 0;
    const contentHtml = hasData
        ? `<div class="kb-entry-content collapsed">${okbEscape(content)}</div>`
        : '<div class="kb-empty-sm">暂未提取</div>';
    const toggleBtn = (hasData && isLong) ? `<button class="kb-entry-toggle" data-okb-toggle="${dim.key}">展开</button>` : "";
    const editBtn = hasData
        ? `<button class="btn btn-sm btn-outline" onclick="okbShowEditEntryForm(${entry.id}, '${dim.key}')">编辑</button>`
        : "";
    return `
        <div class="kb-detail-section" id="okb-section-${dim.key}">
            <div class="kb-section-header">
                <div class="kb-section-title">${dim.icon} ${okbEscape(dim.label)}</div>
                ${editBtn}
            </div>
            <div class="kb-section-body" id="okb-section-body-${dim.key}">
                ${contentHtml}
            </div>
            ${toggleBtn}
        </div>
    `;
}

async function okbShowEditEntryForm(eid, dimKey) {
    const dim = ORDINARY_DIMENSIONS.find(d => d.key === dimKey) || { label: dimKey };
    const detail = okbDetailCache;
    const entry = (detail && detail.entries || []).find(e => String(e.id) === String(eid)) || {};

    okbOpenModal(`编辑 · ${dim.label}`, `
        <div class="kb-form">
            <div class="kb-form-row">
                <label>维度</label>
                <div style="color:#6b7280;font-size:14px">${dim.icon} ${okbEscape(dim.label)}</div>
            </div>
            <div class="kb-form-row">
                <label>内容</label>
                <textarea id="okb-edit-content" rows="12" style="font-size:13px;line-height:1.6">${okbEscape(entry.content || "")}</textarea>
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="okb-edit-error"></span>
                <button class="btn btn-outline" onclick="okbCloseModal()">取消</button>
                <button class="btn btn-primary" onclick="okbSubmitEditEntry(${eid}, '${dimKey}')">保存</button>
            </div>
        </div>
    `);
}

async function okbSubmitEditEntry(eid, dimKey) {
    const errEl = document.getElementById("okb-edit-error");
    if (errEl) errEl.textContent = "";
    const content = document.getElementById("okb-edit-content").value;
    try {
        await apiPut(`/api/ordinary-knowledge-bases/${okbCurrentId}/entries/${eid}`, { content });
        okbCloseModal();
        await okbLoadDetail(okbCurrentId);
    } catch (e) {
        if (errEl) errEl.textContent = "保存失败：" + e.message;
    }
}

/* ===================== 上传文件 ===================== */

function okbShowUploadFile() {
    okbOpenModal("上传文件到普通知识库", `
        <div class="kb-form">
            <div class="kb-form-note">上传参考作品（txt / pdf / docx 等），系统将自动分块提取 7 个维度的写作技法。</div>
            <div class="kb-form-note kb-form-warn">⚠ 几百万字的大文件会分块并行提取并逐级合并，可能需要数分钟，请耐心等待。支持断点续传。</div>
            <div class="kb-form-row">
                <label>选择文件</label>
                <input type="file" id="okb-upload-file" accept=".txt,.md,.pdf,.docx,.doc">
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="okb-upload-error"></span>
                <span class="kb-upload-status" id="okb-upload-status"></span>
                <button class="btn btn-outline" onclick="okbCloseModal()">取消</button>
                <button class="btn btn-primary" id="okb-upload-btn" onclick="okbUploadFile()">上传并提取</button>
            </div>
        </div>
    `);
}

async function okbUploadFile() {
    const errEl = document.getElementById("okb-upload-error");
    const statusEl = document.getElementById("okb-upload-status");
    const btn = document.getElementById("okb-upload-btn");
    if (errEl) errEl.textContent = "";
    if (statusEl) statusEl.innerHTML = "";
    const fileInput = document.getElementById("okb-upload-file");
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        if (errEl) errEl.textContent = "请选择文件";
        return;
    }
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);
    if (btn) { btn.disabled = true; btn.textContent = "提取中..."; }

    function setProgress(pct, textHtml) {
        if (!statusEl) return;
        statusEl.innerHTML = `<div style="margin-top:6px">
            <div style="height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden">
                <div style="height:100%;width:${pct}%;background:#3b82f6;transition:width .3s"></div>
            </div>
            <div style="margin-top:5px;font-size:12px;color:#6b7280;line-height:1.5">${textHtml}</div>
        </div>`;
    }

    try {
        const response = await fetch(`/api/ordinary-knowledge-bases/${okbCurrentId}/import-file`, {
            method: "POST",
            body: formData,
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `请求失败 (HTTP ${response.status})`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let totalChunks = 0;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";
            for (const line of lines) {
                if (!line.trim()) continue;
                let data;
                try { data = JSON.parse(line); } catch (e) { continue; }
                if (data.type === "start") {
                    totalChunks = data.total_chunks || 0;
                    const resumeNote = data.resume ? `<br><span style="color:#b45309">⟳ 检测到上次未完成，正在断点续传（跳过 ${data.done_chunks || 0} 块）</span>` : "";
                    const failedNote = (data.failed_prev && data.failed_prev.length)
                        ? `<br><span style="color:#b91c1c">⚠ 上次失败 ${data.failed_prev.length} 块将重试</span>` : "";
                    setProgress(0, `📊 识别到 <b>${totalChunks}</b> 个文本块，开始分块提取 7 维写作技法…${resumeNote}${failedNote}`);
                } else if (data.type === "progress" && data.level === "map") {
                    const pct = data.percent || 0;
                    setProgress(pct, `📝 分块提取中：${data.done}/${data.total} 块完成（${pct}%）`);
                } else if (data.type === "progress" && data.level === "reduce") {
                    const pct = data.percent || 0;
                    setProgress(pct, `🔗 合并阶段：${data.done}/${data.total} 批完成（${pct}%）`);
                } else if (data.type === "complete") {
                    const dimCount = data.dimensions ? Object.keys(data.dimensions).length : 7;
                    const failedNote = (data.failed_chunks && data.failed_chunks.length)
                        ? `<br><span style="color:#b91c1c">⚠ ${data.failed_chunks.length} 块提取失败，结果基于已成功块合并</span>` : "";
                    if (statusEl) statusEl.innerHTML = `✅ 提取完成：${dimCount} 个维度已生成${failedNote}`;
                    setTimeout(() => { okbCloseModal(); okbLoadDetail(okbCurrentId); }, 2500);
                } else if (data.type === "error") {
                    throw new Error(data.message || "提取失败");
                }
            }
        }
    } catch (e) {
        if (errEl) errEl.textContent = "上传失败：" + e.message;
        if (btn) { btn.disabled = false; btn.textContent = "上传并提取"; }
    }
}

/* ===================== 模态框 ===================== */

function okbOpenModal(title, innerHtml) {
    const modal = document.getElementById("okb-modal");
    if (!modal) return;
    modal.innerHTML = `
        <div class="kb-modal-card">
            <div class="kb-modal-header">
                <h4>${okbEscape(title)}</h4>
                <button class="kb-modal-close" onclick="okbCloseModal()">✕</button>
            </div>
            <div class="kb-modal-body">${innerHtml}</div>
        </div>
    `;
    modal.style.display = "flex";
}

function okbCloseModal() {
    const modal = document.getElementById("okb-modal");
    if (modal) { modal.style.display = "none"; modal.innerHTML = ""; }
}

document.addEventListener("click", function(e) {
    const toggle = e.target.closest("[data-okb-toggle]");
    if (!toggle) return;
    const section = toggle.closest(".kb-detail-section");
    if (!section) return;
    const content = section.querySelector(".kb-entry-content");
    if (!content) return;
    const collapsed = content.classList.toggle("collapsed");
    toggle.textContent = collapsed ? "展开" : "收起";
});
