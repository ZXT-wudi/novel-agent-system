let kbManagerOpen = false;
let kbCurrentId = null;
let kbCurrentVolume = null;
let kbDetailCache = null;
let kbEntriesByCat = {};
let kbEditingEntryId = null;
let kbEditingEntryCat = null;

const KB_CATEGORIES = [
    { key: "worldview", label: "世界观", icon: "🌍" },
    { key: "character", label: "角色", icon: "👤" },
    { key: "event", label: "事件", icon: "⚡" },
    { key: "timeline", label: "时间线", icon: "⏱" },
    { key: "faction", label: "势力 / 阵营", icon: "⚔️" },
    { key: "setting", label: "设定", icon: "📖" },
    { key: "volume_event", label: "卷事件总结", icon: "📜" },
    { key: "chapter_summary", label: "章节摘要", icon: "📑" },
    { key: "other", label: "其他", icon: "📦" },
];

const KB_GENRES = ["玄幻", "都市", "科幻", "历史", "同人", "其他"];

function kbEscape(s) {
    if (typeof escapeHtml === "function") return escapeHtml(s);
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

function openKnowledgeBaseManager() {
    const existing = document.getElementById("kb-overlay");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "kb-overlay";
    overlay.className = "kb-overlay";
    overlay.innerHTML = `
        <div class="kb-panel">
            <div class="kb-header">
                <h3 id="kb-title">📚 知识库管理</h3>
                <div class="kb-header-actions" id="kb-header-actions"></div>
                <button class="btn btn-sm btn-outline" onclick="closeKnowledgeBaseManager()">关闭</button>
            </div>
            <div class="kb-body" id="kb-body">
                <div class="kb-loading">加载中...</div>
            </div>
            <div class="kb-modal" id="kb-modal" style="display:none;"></div>
        </div>
    `;
    document.body.appendChild(overlay);
    setTimeout(() => overlay.classList.add("visible"), 10);
    kbManagerOpen = true;
    kbShowListView();
}

function closeKnowledgeBaseManager() {
    const overlay = document.getElementById("kb-overlay");
    if (overlay) {
        overlay.classList.remove("visible");
        setTimeout(() => { if (overlay) overlay.remove(); }, 200);
    }
    kbManagerOpen = false;
    kbCurrentId = null;
    kbDetailCache = null;
}

function kbSetHeaderActions(html) {
    const el = document.getElementById("kb-header-actions");
    if (el) el.innerHTML = html;
}

function kbSetTitle(text) {
    const el = document.getElementById("kb-title");
    if (el) el.textContent = text;
}

function kbSetBody(html) {
    const el = document.getElementById("kb-body");
    if (el) el.innerHTML = html;
}

/* ===================== 列表视图 ===================== */

function kbShowListView() {
    kbCurrentId = null;
    kbDetailCache = null;
    kbSetTitle("📚 知识库管理");
    kbSetHeaderActions(`<button class="btn btn-sm btn-primary" onclick="kbShowCreateForm()">+ 新建知识库</button>`);
    kbSetBody(`
        <div class="kb-toolbar">
            <input type="text" class="kb-search" id="kb-search" placeholder="搜索知识库名称 / 原作..." oninput="filterKBList()">
            <span class="kb-count" id="kb-count"></span>
        </div>
        <div class="kb-list" id="kb-list"><div class="kb-loading">加载中...</div></div>
    `);
    loadKBList();
}

let kbListData = [];

async function loadKBList() {
    const listEl = document.getElementById("kb-list");
    if (!listEl) return;
    listEl.innerHTML = '<div class="kb-loading">加载中...</div>';
    try {
        const items = await apiGet("/api/knowledge-bases");
        kbListData = Array.isArray(items) ? items : [];
        renderKBList();
    } catch (e) {
        listEl.innerHTML = `<div class="kb-empty">加载失败：${kbEscape(e.message)}</div>`;
    }
}

function filterKBList() {
    renderKBList();
}

function renderKBList() {
    const listEl = document.getElementById("kb-list");
    if (!listEl) return;
    const searchEl = document.getElementById("kb-search");
    const kw = (searchEl && searchEl.value || "").trim().toLowerCase();
    let items = kbListData;
    if (kw) {
        items = items.filter(it =>
            (it.name || "").toLowerCase().includes(kw) ||
            (it.source_work || "").toLowerCase().includes(kw) ||
            (it.genre || "").toLowerCase().includes(kw)
        );
    }

    const countEl = document.getElementById("kb-count");
    if (countEl) countEl.textContent = `共 ${items.length} 个知识库`;

    if (items.length === 0) {
        listEl.innerHTML = '<div class="kb-empty">暂无知识库，点击右上角“新建知识库”创建</div>';
        return;
    }

    listEl.innerHTML = `<div class="kb-grid">` + items.map(it => {
        const fanBadge = it.is_fanwork ? `<span class="kb-tag kb-tag-fan">同人</span>` : "";
        const genreBadge = it.genre ? `<span class="kb-tag">${kbEscape(it.genre)}</span>` : "";
        let importBadge = "";
        if (it.import_status === "running") {
            const p = it.import_progress || {};
            const ev = (p.extracted_volumes || []).length;
            const tv = p.total_volumes || 0;
            importBadge = `<span class="kb-tag" style="background:#fef3c7;color:#b45309">⏳ 提取中 ${ev}/${tv}卷</span>`;
        } else if (it.import_status === "completed") {
            importBadge = `<span class="kb-tag" style="background:#dcfce7;color:#15803d">✓ 已提取</span>`;
        }
        const sourceLine = it.is_fanwork && it.source_work
            ? `<div class="kb-card-source">原作：${kbEscape(it.source_work)}</div>` : "";
        const desc = it.description ? `<div class="kb-card-desc">${kbEscape(it.description.length > 80 ? it.description.slice(0, 80) + "…" : it.description)}</div>` : "";
        return `
            <div class="kb-card" onclick="loadKBDetail(${it.id})">
                <div class="kb-card-head">
                    <div class="kb-card-name">${kbEscape(it.name)}</div>
                    <div class="kb-card-badges">${genreBadge}${fanBadge}${importBadge}</div>
                </div>
                ${sourceLine}
                ${desc}
                <div class="kb-card-foot">
                    <span class="kb-card-count">📝 ${it.entry_count || 0} 条目</span>
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); kbDelete(${it.id}, '${kbEscape(it.name).replace(/'/g, "\\'")}')">删除</button>
                </div>
            </div>
        `;
    }).join("") + `</div>`;
}

async function kbDelete(kbId, name) {
    if (!confirm(`确定删除知识库「${name}」及其所有条目？此操作不可恢复。`)) return;
    try {
        await apiDelete(`/api/knowledge-bases/${kbId}`);
        await loadKBList();
    } catch (e) {
        alert("删除失败：" + e.message);
    }
}

/* ===================== 新建知识库表单 ===================== */

function kbShowCreateForm() {
    const genreOpts = KB_GENRES.map(g => `<option value="${g}">${g}</option>`).join("");
    kbOpenModal("新建知识库", `
        <div class="kb-form">
            <div class="kb-form-row">
                <label>名称 *</label>
                <input type="text" id="kb-new-name" placeholder="如：无职转生知识库">
            </div>
            <div class="kb-form-row">
                <label>题材</label>
                <select id="kb-new-genre" onchange="kbOnGenreChange()">${genreOpts}</select>
            </div>
            <div class="kb-form-row kb-form-row-inline">
                <label class="kb-checkbox-label">
                    <input type="checkbox" id="kb-new-fanwork" onchange="kbOnFanworkChange()"> 同人作品
                </label>
            </div>
            <div class="kb-form-row" id="kb-new-source-row" style="display:none;">
                <label>原作</label>
                <input type="text" id="kb-new-source" placeholder="如：无职转生～到了异世界就认真活下去～">
            </div>
            <div class="kb-form-row">
                <label>描述</label>
                <textarea id="kb-new-desc" rows="3" placeholder="可选，知识库用途说明"></textarea>
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="kb-new-error"></span>
                <button class="btn btn-outline" onclick="kbCloseModal()">取消</button>
                <button class="btn btn-primary" onclick="kbSubmitCreate()">创建</button>
            </div>
        </div>
    `);
}

function kbOnGenreChange() {
    const genre = document.getElementById("kb-new-genre").value;
    const fanChk = document.getElementById("kb-new-fanwork");
    if (genre === "同人" && fanChk) fanChk.checked = true;
    kbOnFanworkChange();
}

function kbOnFanworkChange() {
    const isFan = document.getElementById("kb-new-fanwork").checked;
    const row = document.getElementById("kb-new-source-row");
    if (row) row.style.display = isFan ? "" : "none";
}

async function kbSubmitCreate() {
    const name = document.getElementById("kb-new-name").value.trim();
    const errEl = document.getElementById("kb-new-error");
    if (errEl) errEl.textContent = "";
    if (!name) { if (errEl) errEl.textContent = "请填写名称"; return; }
    const genre = document.getElementById("kb-new-genre").value;
    const isFanwork = document.getElementById("kb-new-fanwork").checked;
    const sourceWork = document.getElementById("kb-new-source").value.trim();
    const desc = document.getElementById("kb-new-desc").value.trim();
    try {
        await apiPost("/api/knowledge-bases", {
            name, genre, source_work: isFanwork ? sourceWork : "", is_fanwork: isFanwork, description: desc
        });
        kbCloseModal();
        await loadKBList();
    } catch (e) {
        if (errEl) errEl.textContent = "创建失败：" + e.message;
    }
}

/* ===================== 详情视图 ===================== */

async function loadKBDetail(kbId) {
    kbCurrentId = kbId;
    kbCurrentVolume = null;
    kbSetHeaderActions(`<button class="btn btn-sm btn-outline" onclick="kbShowListView()">← 返回列表</button>`);
    kbSetTitle("加载中...");
    kbSetBody('<div class="kb-loading">加载中...</div>');
    try {
        const [kb, overview] = await Promise.all([
            apiGet(`/api/knowledge-bases/${kbId}`),
            apiGet(`/api/knowledge-bases/${kbId}/overview`),
        ]);
        kbDetailCache = { kb, overview };
        renderKBDetail(kb, overview);
    } catch (e) {
        kbSetTitle("知识库详情");
        kbSetBody(`<div class="kb-empty">加载失败：${kbEscape(e.message)}</div>`);
    }
}

function renderKBDetail(kb, overview) {
    const genreBadge = kb.genre ? `<span class="kb-tag">${kbEscape(kb.genre)}</span>` : "";
    const fanBadge = kb.is_fanwork ? `<span class="kb-tag kb-tag-fan">同人</span>` : "";
    const sourceLine = (kb.is_fanwork && kb.source_work) ? `<span class="kb-detail-source">原作：${kbEscape(kb.source_work)}</span>` : "";
    const total = (overview && overview.total != null) ? overview.total : (overview && overview.total_entries) || 0;

    kbSetTitle(kb.name || "知识库详情");
    kbSetHeaderActions(`
        <button class="btn btn-sm btn-outline" onclick="kbShowListView()">← 返回列表</button>
        <button class="btn btn-sm btn-success" onclick="kbShowAddEntryForm()">+ 添加条目</button>
        <button class="btn btn-sm btn-primary" onclick="kbShowUploadFile()">📤 上传文件</button>
        <button class="btn btn-sm btn-warning" onclick="kbShowBulkWrite()">✍ 批量写入</button>
    `);

    const cats = (overview && overview.categories) || {};
    kbEntriesByCat = {};
    const knownKeys = KB_CATEGORIES.map(c => c.key);
    const extraKeys = Object.keys(cats).filter(k => !knownKeys.includes(k));

    const sections = KB_CATEGORIES.map(c => {
        const info = cats[c.key];
        const count = info ? info.count : 0;
        return kbSectionHtml(c, count, count > 0);
    }).join("") + extraKeys.map(k => {
        const c = { key: k, label: k, icon: "📁" };
        const info = cats[k];
        return kbSectionHtml(c, info ? info.count : 0, true);
    }).join("");

    const volumes = kb.volumes || [];
    const volTabs = volumes.length
        ? `<div class="kb-vol-tabs"><button class="kb-vol-tab${kbCurrentVolume == null ? " active" : ""}" data-vol="all" onclick="kbSelectVolume(null)">全部</button>${volumes.map(v => `<button class="kb-vol-tab${v.volume_number === kbCurrentVolume ? " active" : ""}" data-vol="${v.volume_number}" onclick="kbSelectVolume(${v.volume_number})">第${v.volume_number}卷${v.title ? "·" + kbEscape(v.title) : ""}</button>`).join("")}</div>`
        : "";

    kbSetBody(`
        <div class="kb-detail">
            <div class="kb-detail-header">
                <div class="kb-detail-title">${kbEscape(kb.name || "")}</div>
                <div class="kb-detail-meta">
                    ${genreBadge}${fanBadge}${sourceLine}
                    <span class="kb-detail-total">共 ${total} 条目</span>
                </div>
                ${kb.description ? `<div class="kb-detail-desc">${kbEscape(kb.description)}</div>` : ""}
            </div>
            ${volTabs}
            <div class="kb-sections" id="kb-sections">${sections}</div>
        </div>
    `);

    KB_CATEGORIES.forEach(c => {
        const info = cats[c.key];
        if (info && info.count > 0) loadKBSectionEntries(kbCurrentId, c.key);
    });
    extraKeys.forEach(k => loadKBSectionEntries(kbCurrentId, k));
}

async function kbSelectVolume(volNum) {
    kbCurrentVolume = volNum;
    document.querySelectorAll(".kb-vol-tab").forEach(btn => {
        const v = btn.dataset.vol;
        const isActive = (v === "all") ? (kbCurrentVolume == null) : (Number(v) === kbCurrentVolume);
        btn.classList.toggle("active", isActive);
    });
    try {
        const overview = await apiGet(
            `/api/knowledge-bases/${kbCurrentId}/overview${kbCurrentVolume != null ? `?volume=${kbCurrentVolume}` : ""}`
        );
        kbDetailCache = { ...kbDetailCache, overview };
        renderKBDetail(kbDetailCache.kb, overview);
    } catch (e) {
        const cats = (kbDetailCache && kbDetailCache.overview) ? (kbDetailCache.overview.categories || {}) : {};
        const knownKeys = KB_CATEGORIES.map(c => c.key);
        KB_CATEGORIES.forEach(c => {
            const info = cats[c.key];
            if (info && info.count > 0) loadKBSectionEntries(kbCurrentId, c.key);
        });
        Object.keys(cats).filter(k => !knownKeys.includes(k)).forEach(k => loadKBSectionEntries(kbCurrentId, k));
    }
}

function kbSectionHtml(cat, count, hasData) {
    return `
        <div class="kb-detail-section" id="kb-section-${cat.key}">
            <div class="kb-section-header">
                <div class="kb-section-title">${cat.icon} ${kbEscape(cat.label)} <span class="kb-section-count">${count}</span></div>
                <button class="btn btn-sm btn-outline" onclick="kbShowAddEntryForm('${cat.key}')">+ 添加</button>
            </div>
            <div class="kb-section-body" id="kb-section-body-${cat.key}">
                ${hasData ? '<div class="kb-loading kb-loading-sm">加载条目...</div>' : '<div class="kb-empty-sm">暂无条目</div>'}
            </div>
        </div>
    `;
}

async function loadKBSectionEntries(kbId, category) {
    const bodyEl = document.getElementById(`kb-section-body-${category}`);
    if (!bodyEl) return;
    try {
        const entries = await apiGet(`/api/knowledge-bases/${kbId}/entries?category=${encodeURIComponent(category)}${kbCurrentVolume != null ? `&volume=${kbCurrentVolume}` : ""}`);
        renderKBSectionEntries(category, Array.isArray(entries) ? entries : []);
    } catch (e) {
        bodyEl.innerHTML = `<div class="kb-empty-sm">加载失败：${kbEscape(e.message)}</div>`;
    }
}

function renderKBSectionEntries(category, entries) {
    const bodyEl = document.getElementById(`kb-section-body-${category}`);
    if (!bodyEl) return;
    kbEntriesByCat[category] = Array.isArray(entries) ? entries : [];
    if (entries.length === 0) {
        bodyEl.innerHTML = '<div class="kb-empty-sm">暂无条目</div>';
        return;
    }
    bodyEl.innerHTML = entries.map(e => kbEntryCardHtml(e)).join("");
    bodyEl.querySelectorAll("[data-entry-toggle]").forEach(btn => {
        btn.onclick = () => {
            const card = btn.closest(".kb-entry-card");
            const content = card.querySelector(".kb-entry-content");
            if (!content) return;
            const collapsed = content.classList.toggle("collapsed");
            btn.textContent = collapsed ? "展开" : "收起";
        };
    });
}

function kbFindEntry(eid) {
    for (const cat of Object.keys(kbEntriesByCat)) {
        const found = kbEntriesByCat[cat].find(e => String(e.id) === String(eid));
        if (found) return found;
    }
    return null;
}

function kbEntryCardHtml(e) {
    const content = e.content || "";
    const isLong = content.length > 120 || content.indexOf("\n") >= 0;
    const sourceTag = e.source ? `<span class="kb-entry-source">${kbEscape(e.source)}</span>` : "";
    const volTag = e.volume ? `<span class="kb-entry-source">第${e.volume}卷</span>` : "";
    const chTag = e.chapter_number ? `<span class="kb-entry-source">第${e.chapter_number}章</span>` : "";
    const attrStr = e.attributes && Object.keys(e.attributes).length
        ? `<div class="kb-entry-attr">${kbEscape(JSON.stringify(e.attributes))}</div>` : "";
    return `
        <div class="kb-entry-card">
            <div class="kb-entry-head">
                <div class="kb-entry-title">${kbEscape(e.title || "(无标题)")}</div>
                <div class="kb-entry-actions">
                    ${volTag}${chTag}${sourceTag}
                    <button class="btn btn-sm btn-outline" onclick="kbShowEditEntryForm(${e.id}, '${kbEscape(e.category)}')">编辑</button>
                    <button class="btn btn-sm btn-danger" onclick="kbDeleteEntry(${e.id}, '${kbEscape(e.title).replace(/'/g, "\\'")}')">删除</button>
                </div>
            </div>
            <div class="kb-entry-content collapsed">${kbEscape(content) || "<span class='kb-muted'>（无内容）</span>"}</div>
            ${isLong ? `<button class="kb-entry-toggle" data-entry-toggle>展开</button>` : ""}
            ${attrStr}
        </div>
    `;
}

/* ===================== 条目：添加 / 编辑 / 删除 ===================== */

function kbCategoryOptions(selected) {
    const known = KB_CATEGORIES.map(c => `<option value="${c.key}" ${c.key === selected ? "selected" : ""}>${c.label}</option>`).join("");
    return known;
}

function kbShowAddEntryForm(presetCategory) {
    const cat = presetCategory || "worldview";
    kbOpenModal("添加条目", `
        <div class="kb-form">
            <div class="kb-form-row">
                <label>分类</label>
                <select id="kb-entry-cat">${kbCategoryOptions(cat)}</select>
            </div>
            <div class="kb-form-row">
                <label>标题 *</label>
                <input type="text" id="kb-entry-title" placeholder="条目标题">
            </div>
            <div class="kb-form-row">
                <label>内容</label>
                <textarea id="kb-entry-content" rows="6" placeholder="条目正文..."></textarea>
            </div>
            <div class="kb-form-row">
                <label>属性 (可选，JSON)</label>
                <textarea id="kb-entry-attr" rows="3" placeholder='如：{"别名":"鲁迪"} 或留空'></textarea>
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="kb-entry-error"></span>
                <button class="btn btn-outline" onclick="kbCloseModal()">取消</button>
                <button class="btn btn-primary" onclick="kbSubmitEntry()">添加</button>
            </div>
        </div>
    `);
}

async function kbSubmitEntry() {
    const errEl = document.getElementById("kb-entry-error");
    if (errEl) errEl.textContent = "";
    const category = document.getElementById("kb-entry-cat").value;
    const title = document.getElementById("kb-entry-title").value.trim();
    const content = document.getElementById("kb-entry-content").value;
    const attrText = document.getElementById("kb-entry-attr").value.trim();
    if (!title) { if (errEl) errEl.textContent = "请填写标题"; return; }
    let attributes = null;
    if (attrText) {
        try { attributes = JSON.parse(attrText); }
        catch (err) { if (errEl) errEl.textContent = "属性 JSON 解析失败"; return; }
    }
    try {
        await apiPost(`/api/knowledge-bases/${kbCurrentId}/entries`, { category, title, content, attributes, source: "manual" });
        kbCloseModal();
        await loadKBDetail(kbCurrentId);
    } catch (e) {
        if (errEl) errEl.textContent = "添加失败：" + e.message;
    }
}

function kbShowEditEntryForm(eid, category) {
    kbEditingEntryId = eid;
    kbEditingEntryCat = category;
    const entry = kbFindEntry(eid) || {};
    const attrText = entry.attributes && Object.keys(entry.attributes).length
        ? JSON.stringify(entry.attributes, null, 2) : "";

    kbOpenModal("编辑条目", `
        <div class="kb-form">
            <div class="kb-form-row">
                <label>分类</label>
                <select id="kb-edit-cat">${kbCategoryOptions(category)}</select>
            </div>
            <div class="kb-form-row">
                <label>标题 *</label>
                <input type="text" id="kb-edit-title" value="${kbEscape(entry.title || "")}">
            </div>
            <div class="kb-form-row">
                <label>内容</label>
                <textarea id="kb-edit-content" rows="6">${kbEscape(entry.content || "")}</textarea>
            </div>
            <div class="kb-form-row">
                <label>属性 (可选，JSON)</label>
                <textarea id="kb-edit-attr" rows="3" placeholder='留空保持原值'>${kbEscape(attrText)}</textarea>
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="kb-edit-error"></span>
                <button class="btn btn-outline" onclick="kbCloseModal()">取消</button>
                <button class="btn btn-primary" onclick="kbSubmitEditEntry()">保存</button>
            </div>
        </div>
    `);
}

async function kbSubmitEditEntry() {
    const errEl = document.getElementById("kb-edit-error");
    if (errEl) errEl.textContent = "";
    const category = document.getElementById("kb-edit-cat").value;
    const title = document.getElementById("kb-edit-title").value.trim();
    const content = document.getElementById("kb-edit-content").value;
    const attrText = document.getElementById("kb-edit-attr").value.trim();
    if (!title) { if (errEl) errEl.textContent = "请填写标题"; return; }
    const payload = { category, title, content };
    if (attrText) {
        try { payload.attributes = JSON.parse(attrText); }
        catch (err) { if (errEl) errEl.textContent = "属性 JSON 解析失败"; return; }
    }
    try {
        await apiPut(`/api/knowledge-bases/${kbCurrentId}/entries/${kbEditingEntryId}`, payload);
        kbCloseModal();
        await loadKBDetail(kbCurrentId);
    } catch (e) {
        if (errEl) errEl.textContent = "保存失败：" + e.message;
    }
}

async function kbDeleteEntry(eid, title) {
    if (!confirm(`确定删除条目「${title}」？`)) return;
    try {
        await apiDelete(`/api/knowledge-bases/${kbCurrentId}/entries/${eid}`);
        await loadKBDetail(kbCurrentId);
    } catch (e) {
        alert("删除失败：" + e.message);
    }
}

/* ===================== 上传文件 ===================== */

function kbShowUploadFile() {
    kbOpenModal("上传文件到知识库", `
        <div class="kb-form">
            <div class="kb-form-note">支持 txt / md / docx / pdf 等文档，上传后由 AI 分块提取知识点并写入对应分类。</div>
            <div class="kb-form-note kb-form-warn">⚠ 大文件（如整本小说）会分块处理全文，可能需要数分钟，请耐心等待。</div>
            <div class="kb-form-row">
                <label>选择文件</label>
                <input type="file" id="kb-upload-file">
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="kb-upload-error"></span>
                <span class="kb-upload-status" id="kb-upload-status"></span>
                <button class="btn btn-outline" onclick="kbCloseModal()">取消</button>
                <button class="btn btn-primary" id="kb-upload-btn" onclick="kbUploadFile()">上传</button>
            </div>
        </div>
    `);
}

async function kbUploadFile() {
    const errEl = document.getElementById("kb-upload-error");
    const statusEl = document.getElementById("kb-upload-status");
    const btn = document.getElementById("kb-upload-btn");
    if (errEl) errEl.textContent = "";
    if (statusEl) statusEl.innerHTML = "";
    const fileInput = document.getElementById("kb-upload-file");
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
        const response = await fetch(`/api/knowledge-bases/${kbCurrentId}/import-file`, {
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
        let totalVolumes = 0;

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
                    totalVolumes = data.total_volumes || 0;
                    const volList = (data.volumes || []).map(v => `第${v.volume_number}卷《${kbEscape(v.title || "")}》`).join("、");
                    setProgress(0, `📊 识别到 <b>${totalVolumes}</b> 卷，开始按卷提取…<br><span style="font-size:11px;color:#9ca3af">${volList}</span>`);
                } else if (data.type === "progress" && data.phase === "extracting") {
                    const idx = (data.index || 0) + 1;
                    const t = data.total || totalVolumes;
                    const pct = t > 0 ? Math.round(idx / t * 100) : 0;
                    if (data.skipped) {
                        setProgress(pct, `⏭ 跳过已提取的 第${data.volume_number}卷《${kbEscape(data.volume_title || "")}》（累计 ${data.cumulative_entries || 0} 条）`);
                    } else {
                        setProgress(pct, `✅ 第${data.volume_number}卷《${kbEscape(data.volume_title || "")}》提取完成，新增 ${data.entries_added || 0} 条，累计 ${data.cumulative_entries || 0} 条（${idx}/${t}）`);
                    }
                } else if (data.type === "progress" && data.phase === "relations") {
                    setProgress(100, `🔗 ${kbEscape(data.message || "正在生成卷摘要与跨卷关联…")}`);
                } else if (data.type === "complete") {
                    if (data.skipped) {
                        if (statusEl) statusEl.textContent = `ℹ️ ${data.message || "已提取完成，跳过"}`;
                        if (btn) { btn.disabled = false; btn.textContent = "上传"; }
                        setTimeout(() => { kbCloseModal(); loadKBDetail(kbCurrentId); }, 2000);
                    } else {
                        const warn = (data.warnings && data.warnings.length) ? `<br><span style="color:#b45309">⚠ ${data.warnings.length} 条警告：${kbEscape(data.warnings.join("；"))}</span>` : "";
                        if (statusEl) statusEl.innerHTML = `✅ 完成：导入 ${data.imported_count || 0} 条，文本 ${data.text_length || 0} 字，共 ${data.total_volumes || 0} 卷${warn}`;
                        setTimeout(() => { kbCloseModal(); loadKBDetail(kbCurrentId); }, 2500);
                    }
                } else if (data.type === "error") {
                    throw new Error(data.error || "提取失败");
                }
            }
        }
    } catch (e) {
        if (errEl) errEl.textContent = "上传失败：" + e.message;
        if (btn) { btn.disabled = false; btn.textContent = "上传"; }
    }
}

/* ===================== 批量写入 ===================== */

function kbShowBulkWrite() {
    const sample = JSON.stringify([
        { category: "character", title: "示例角色", content: "主角简介...", attributes: {} }
    ], null, 2);
    kbOpenModal("批量写入条目", `
        <div class="kb-form">
            <div class="kb-form-note">粘贴 JSON 数组，每项含 category / title / content / attributes(可选)。</div>
            <div class="kb-form-row">
                <label>条目数组 (JSON)</label>
                <textarea id="kb-bulk-text" rows="10" placeholder='${kbEscape(sample)}'></textarea>
            </div>
            <div class="kb-form-actions">
                <span class="kb-error" id="kb-bulk-error"></span>
                <span class="kb-bulk-status" id="kb-bulk-status"></span>
                <button class="btn btn-outline" onclick="kbCloseModal()">取消</button>
                <button class="btn btn-primary" onclick="kbSubmitBulk()">写入</button>
            </div>
        </div>
    `);
}

async function kbSubmitBulk() {
    const errEl = document.getElementById("kb-bulk-error");
    const statusEl = document.getElementById("kb-bulk-status");
    if (errEl) errEl.textContent = "";
    if (statusEl) statusEl.textContent = "";
    const text = document.getElementById("kb-bulk-text").value.trim();
    if (!text) { if (errEl) errEl.textContent = "请粘贴 JSON"; return; }
    let entries;
    try {
        entries = JSON.parse(text);
    } catch (err) {
        if (errEl) errEl.textContent = "JSON 解析失败：" + err.message;
        return;
    }
    if (!Array.isArray(entries)) {
        if (errEl) errEl.textContent = "内容必须是 JSON 数组";
        return;
    }
    if (statusEl) statusEl.textContent = `正在写入 ${entries.length} 条...`;
    try {
        const result = await apiPost(`/api/knowledge-bases/${kbCurrentId}/bulk-entries`, { entries });
        if (statusEl) statusEl.textContent = `✅ 完成：成功写入 ${result.added_count || 0} 条`;
        setTimeout(() => { kbCloseModal(); loadKBDetail(kbCurrentId); }, 1200);
    } catch (e) {
        if (errEl) errEl.textContent = "写入失败：" + e.message;
        if (statusEl) statusEl.textContent = "";
    }
}

/* ===================== 模态框 ===================== */

function kbOpenModal(title, innerHtml) {
    const modal = document.getElementById("kb-modal");
    if (!modal) return;
    modal.innerHTML = `
        <div class="kb-modal-card">
            <div class="kb-modal-header">
                <h4>${kbEscape(title)}</h4>
                <button class="kb-modal-close" onclick="kbCloseModal()">✕</button>
            </div>
            <div class="kb-modal-body">${innerHtml}</div>
        </div>
    `;
    modal.style.display = "flex";
}

function kbCloseModal() {
    const modal = document.getElementById("kb-modal");
    if (modal) { modal.style.display = "none"; modal.innerHTML = ""; }
    kbEditingEntryId = null;
    kbEditingEntryCat = null;
}
