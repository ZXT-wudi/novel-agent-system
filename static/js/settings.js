let currentEditId = null;
let providerListCache = [];

const PROVIDER_PRESETS = {
    siliconflow: { label: "SiliconFlow", base_url: "https://api.siliconflow.cn/v1", chat_model: "Qwen/Qwen2.5-72B-Instruct", embedding_model: "BAAI/bge-m3" },
    openai: { label: "OpenAI", base_url: "https://api.openai.com/v1", chat_model: "gpt-4o", embedding_model: "text-embedding-3-small" },
    deepseek: { label: "DeepSeek", base_url: "https://api.deepseek.com/v1", chat_model: "deepseek-chat", embedding_model: "" },
    zhipu: { label: "智谱GLM", base_url: "https://open.bigmodel.cn/api/paas/v4", chat_model: "glm-4-plus", embedding_model: "embedding-3" },
    custom: { label: "自定义", base_url: "", chat_model: "", embedding_model: "" },
};

const PROVIDER_PURPOSES = {
    author: { label: "✍️ 作者智能体", short: "作者", desc: "大纲生成、章节写作、续写改写", fallback: "未单独配置时使用「通用」的配置" },
    image: { label: "🎨 图像生成智能体", short: "图像", desc: "世界地图、区域插画、角色形象", fallback: "未单独配置时使用「通用」的配置" },
    polish: { label: "🪄 AI润色师", short: "润色", desc: "章节 AI 润色", fallback: "未单独配置时使用「通用」的配置" },
    common: { label: "⚙️ 通用智能体", short: "通用", desc: "知识抽取、审读、知识库问答、向量嵌入，并作为其他用途的兜底配置", fallback: "所有未单独配置的调用都会使用此配置" },
};

const PURPOSE_ORDER = ["author", "image", "polish", "common"];

function providerLabel(type) {
    const p = PROVIDER_PRESETS[type];
    return p ? p.label : type;
}

function purposeLabel(purpose) {
    const p = PROVIDER_PURPOSES[purpose];
    return p ? p.short : "通用";
}

async function loadProviders() {
    const container = document.getElementById("settings-providers-container");
    if (!container) {
        await loadActiveModel();
        return;
    }
    container.innerHTML = '<div class="outline-empty">加载中...</div>';
    try {
        const providers = await apiGet("/api/llm-providers");
        providerListCache = Array.isArray(providers) ? providers : [];
        renderProviderList(providerListCache);
    } catch (e) {
        providerListCache = [];
        container.innerHTML = `<div class="outline-empty">加载失败：${escapeHtml(e.message)}</div>`;
    }
    await loadActiveModel();
}

function renderProviderList(providers) {
    const container = document.getElementById("settings-providers-container");
    if (!container) return;
    const normalized = providers.map(p => ({ ...p, purpose: p.purpose || "common" }));
    let html = "";
    PURPOSE_ORDER.forEach(purpose => {
        const meta = PROVIDER_PURPOSES[purpose];
        const items = normalized.filter(p => p.purpose === purpose);
        const activeOne = items.find(p => p.is_active);
        const statusText = activeOne
            ? `当前：${escapeHtml(activeOne.chat_model || "-")}`
            : escapeHtml(meta.fallback);
        const statusColor = activeOne ? "var(--success)" : "var(--text-muted)";
        html += `
            <div style="margin-bottom:22px;">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:4px;padding:10px 12px;background:var(--bg-secondary);border-radius:8px;">
                    <div style="display:flex;flex-direction:column;gap:3px;min-width:0;">
                        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                            <span style="font-weight:600;color:var(--text-primary);font-size:14px;">${meta.label}</span>
                            <span class="badge" style="background:var(--bg-tertiary);color:var(--text-secondary);font-size:11px;">${items.length} 条配置</span>
                        </div>
                        <div style="font-size:12px;color:var(--text-secondary);">${meta.desc}</div>
                        <div style="font-size:11px;color:${statusColor};">● ${statusText}</div>
                    </div>
                    <button class="btn btn-sm btn-primary" style="flex-shrink:0;" onclick="openProviderForm(null, '${purpose}')">+ 新增</button>
                </div>
                <div>${items.map(providerCardHtml).join("")}</div>
            </div>
        `;
    });
    container.innerHTML = html;
}

function providerCardHtml(p) {
    const label = providerLabel(p.provider_type);
    const keyText = p.api_key ? escapeHtml(p.api_key) : "未设置";
    const activeBadge = p.is_active
        ? `<span class="badge" style="background:var(--success);color:#fff;">使用中</span>`
        : `<button class="btn btn-sm btn-outline" onclick="activateProvider(${p.id})">启用</button>`;
    return `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;padding:12px 12px;border-bottom:1px solid var(--border);">
            <div style="display:flex;flex-direction:column;gap:6px;min-width:0;flex:1;">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    <span style="font-weight:600;color:var(--text-primary);">${escapeHtml(p.name)}</span>
                    <span class="badge" style="background:var(--accent);color:#fff;">${escapeHtml(label)}</span>
                    ${activeBadge}
                </div>
                <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);">
                    <span>模型：<b style="color:var(--text-primary);">${escapeHtml(p.chat_model || "-")}</b></span>
                    <span>密钥：${keyText}</span>
                </div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-shrink:0;">
                <button class="btn btn-sm btn-outline" onclick="openProviderForm(${p.id})">编辑</button>
                <button class="btn btn-sm btn-danger" onclick="deleteProvider(${p.id})">删除</button>
            </div>
        </div>
    `;
}

async function loadActiveModel() {
    try {
        const active = await apiGet("/api/llm-providers/active");
        if (!active || typeof active !== "object") {
            updateActiveModelIndicator("未配置（使用 .env 默认）");
            return;
        }
        const parts = PURPOSE_ORDER
            .filter(k => active[k])
            .map(k => `${purposeLabel(k)}:${active[k].chat_model || active[k].name}`);
        updateActiveModelIndicator(parts.length ? parts.join(" · ") : "未配置（使用 .env 默认）");
    } catch (e) {
        updateActiveModelIndicator("未配置");
    }
}

function openProviderForm(existing, purpose) {
    let p = null;
    if (existing != null) {
        if (typeof existing === "object") {
            p = existing;
        } else {
            p = providerListCache.find(x => String(x.id) === String(existing));
        }
        currentEditId = p ? p.id : null;
    } else {
        currentEditId = null;
    }
    renderProviderForm(p, purpose);
}

function renderProviderForm(existing, presetPurpose) {
    const container = document.getElementById("settings-providers-container");
    if (!container) return;
    const editing = !!existing;
    const type = existing ? existing.provider_type : "siliconflow";
    const purpose = existing ? (existing.purpose || "common") : (presetPurpose || "common");
    const preset = PROVIDER_PRESETS[type] || PROVIDER_PRESETS.custom;
    const isImage = purpose === "image";
    const options = Object.keys(PROVIDER_PRESETS)
        .map(k => `<option value="${k}"${k === type ? " selected" : ""}>${escapeHtml(PROVIDER_PRESETS[k].label)}</option>`)
        .join("");
    const purposeOptions = PURPOSE_ORDER
        .map(k => `<option value="${k}"${k === purpose ? " selected" : ""}>${escapeHtml(PROVIDER_PURPOSES[k].label)}</option>`)
        .join("");
    const apiKeyPlaceholder = editing ? "留空则不修改" : "输入 API Key";
    const baseUrlVal = editing ? existing.base_url : preset.base_url;
    const chatVal = editing ? existing.chat_model : (isImage ? "Tongyi-MAI/Z-Image-Turbo" : preset.chat_model);
    const embedVal = editing ? (existing.embedding_model || "") : preset.embedding_model;
    const modelLabel = isImage ? "图像模型" : "对话模型";
    const modelPlaceholder = isImage ? "如：Tongyi-MAI/Z-Image-Turbo" : "如：gpt-4o";

    container.innerHTML = `
        <div class="kb-form">
            <h4 style="margin:0;font-size:16px;color:var(--text-primary);">${editing ? "编辑供应商" : "新增供应商"}</h4>
            <div class="kb-form-row">
                <label>用途 *</label>
                <select id="pf-purpose" onchange="onProviderPurposeChange()">${purposeOptions}</select>
                <div style="font-size:11px;color:var(--text-muted);" id="pf-purpose-hint">${escapeHtml(PROVIDER_PURPOSES[purpose].desc)}。${escapeHtml(PROVIDER_PURPOSES[purpose].fallback)}。</div>
            </div>
            <div class="kb-form-row">
                <label>类型</label>
                <select id="pf-type" onchange="onProviderTypeChange()">${options}</select>
            </div>
            <div class="kb-form-row">
                <label>名称（备注名）</label>
                <input type="text" id="pf-name" value="${escapeHtml(existing ? existing.name : "")}" placeholder="如：我的 SiliconFlow 账号">
                <div style="font-size:11px;color:var(--text-muted);">仅用于在列表中区分多条配置，不影响任何调用</div>
            </div>
            <div class="kb-form-row">
                <label>Base URL</label>
                <input type="text" id="pf-base-url" value="${escapeHtml(baseUrlVal)}" placeholder="https://api.example.com/v1">
            </div>
            <div class="kb-form-row">
                <label>API Key</label>
                <input type="password" id="pf-api-key" placeholder="${apiKeyPlaceholder}">
            </div>
            <div class="kb-form-row">
                <label id="pf-chat-model-label">${modelLabel}</label>
                <input type="text" id="pf-chat-model" value="${escapeHtml(chatVal)}" placeholder="${modelPlaceholder}">
            </div>
            <div class="kb-form-row" id="pf-embedding-row">
                <label>嵌入模型（可选）</label>
                <input type="text" id="pf-embedding-model" value="${escapeHtml(embedVal)}" placeholder="如：text-embedding-3-small">
            </div>
            <div class="modal-actions">
                <button class="btn btn-outline" onclick="loadProviders()">取消</button>
                <button class="btn btn-primary" onclick="saveProvider()">保存</button>
            </div>
        </div>
    `;
    toggleEmbeddingRow(isImage);
}

function toggleEmbeddingRow(isImage) {
    const row = document.getElementById("pf-embedding-row");
    if (row) row.style.display = isImage ? "none" : "";
}

function onProviderPurposeChange() {
    const purpose = document.getElementById("pf-purpose").value;
    const isImage = purpose === "image";
    const hint = document.getElementById("pf-purpose-hint");
    if (hint) hint.textContent = `${PROVIDER_PURPOSES[purpose].desc}。${PROVIDER_PURPOSES[purpose].fallback}。`;
    const label = document.getElementById("pf-chat-model-label");
    if (label) label.textContent = isImage ? "图像模型" : "对话模型";
    const modelInput = document.getElementById("pf-chat-model");
    if (modelInput && !modelInput.dataset.dirty) {
        modelInput.value = isImage ? "Tongyi-MAI/Z-Image-Turbo" : "";
        modelInput.placeholder = isImage ? "如：Tongyi-MAI/Z-Image-Turbo" : "如：gpt-4o";
    }
    toggleEmbeddingRow(isImage);
}

function onProviderTypeChange() {
    const type = document.getElementById("pf-type").value;
    const fieldIds = ["pf-base-url", "pf-chat-model", "pf-embedding-model"];
    if (type === "custom") {
        fieldIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = "";
        });
        return;
    }
    const preset = PROVIDER_PRESETS[type] || PROVIDER_PRESETS.custom;
    const keyMap = { "pf-base-url": "base_url", "pf-chat-model": "chat_model", "pf-embedding-model": "embedding_model" };
    const purpose = document.getElementById("pf-purpose") ? document.getElementById("pf-purpose").value : "common";
    fieldIds.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (id === "pf-chat-model" && purpose === "image") return;
        const cur = el.value;
        const presetVal = preset[keyMap[id]];
        if (!cur || Object.values(PROVIDER_PRESETS).some(p => p[keyMap[id]] === cur)) {
            el.value = presetVal;
        }
    });
}

async function saveProvider() {
    const provider_type = document.getElementById("pf-type").value;
    const purpose = document.getElementById("pf-purpose").value;
    const name = document.getElementById("pf-name").value.trim();
    const base_url = document.getElementById("pf-base-url").value.trim();
    const apiKeyInput = document.getElementById("pf-api-key").value;
    const chat_model = document.getElementById("pf-chat-model").value.trim();
    const embedding_model = document.getElementById("pf-embedding-model").value.trim();

    if (!name) {
        alert("请填写名称（备注名，用于在列表中区分多条配置）");
        return;
    }

    try {
        if (currentEditId == null) {
            await apiPost("/api/llm-providers", {
                provider_type,
                purpose,
                name,
                base_url,
                api_key: apiKeyInput,
                chat_model,
                embedding_model,
            });
        } else {
            const payload = { provider_type, purpose, name, base_url, chat_model, embedding_model };
            if (apiKeyInput) payload.api_key = apiKeyInput;
            await apiPut(`/api/llm-providers/${currentEditId}`, payload);
        }
        await loadProviders();
    } catch (e) {
        alert("保存失败：" + e.message);
    }
}

async function activateProvider(id) {
    try {
        await apiPost("/api/llm-providers/" + id + "/activate");
        await loadProviders();
    } catch (e) {
        alert("启用失败：" + e.message);
    }
}

async function deleteProvider(id) {
    if (!confirm("确定删除此供应商？")) return;
    try {
        await apiDelete("/api/llm-providers/" + id);
        await loadProviders();
    } catch (e) {
        alert("删除失败：" + e.message);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadActiveModel();
});

async function loadNovelKBBinding() {
    const container = document.getElementById("settings-novel-kb-container");
    if (!container) return;
    const novelId = (typeof appState !== "undefined" && appState.currentNovelId) || null;
    if (!novelId) {
        container.innerHTML = '<div class="outline-empty">请先在左侧选择一部小说</div>';
        return;
    }
    container.innerHTML = '<div class="outline-empty">加载中...</div>';
    try {
        const [novel, advancedKBs, ordinaryKBs] = await Promise.all([
            apiGet(`/api/novels/${novelId}`),
            apiGet("/api/knowledge-bases").catch(() => []),
            apiGet("/api/ordinary-knowledge-bases").catch(() => []),
        ]);
        renderNovelKBBinding(novel, advancedKBs, ordinaryKBs);
    } catch (e) {
        container.innerHTML = `<div class="outline-empty">加载失败：${escapeHtml(e.message)}</div>`;
    }
}

function renderNovelKBBinding(novel, advancedKBs, ordinaryKBs) {
    const container = document.getElementById("settings-novel-kb-container");
    if (!container) return;

    const advId = novel.knowledge_base_id || 0;
    const ordId = novel.ordinary_knowledge_base_id || 0;

    const advOpts = `<option value="0">不绑定</option>` +
        (Array.isArray(advancedKBs) ? advancedKBs : []).map(kb =>
            `<option value="${kb.id}" ${kb.id === advId ? "selected" : ""}>${escapeHtml(kb.name)}${kb.genre ? "（" + escapeHtml(kb.genre) + "）" : ""}</option>`
        ).join("");

    const ordOpts = `<option value="0">不绑定</option>` +
        (Array.isArray(ordinaryKBs) ? ordinaryKBs : []).map(kb => {
            const status = kb.import_status === "completed" ? " ✓" : (kb.import_status === "processing" ? " ⏳" : (kb.import_status === "partial" ? " ⚠" : ""));
            return `<option value="${kb.id}" ${kb.id === ordId ? "selected" : ""}>${escapeHtml(kb.name)}${kb.genre ? "（" + escapeHtml(kb.genre) + "）" : ""}${status}</option>`;
        }).join("");

    container.innerHTML = `
        <div style="margin-bottom:16px;">
            <div style="font-weight:600;color:var(--text-primary);margin-bottom:6px;">📖 高级知识库（原作设定参考，同人硬性遵循）</div>
            <select id="novel-adv-kb-select" onchange="saveNovelKBBinding('advanced', this.value)" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-primary);color:var(--text-primary);">${advOpts}</select>
        </div>
        <div style="margin-bottom:8px;">
            <div style="font-weight:600;color:var(--text-primary);margin-bottom:6px;">📝 普通知识库（写作技法参考，可借鉴非硬性）</div>
            <select id="novel-ord-kb-select" onchange="saveNovelKBBinding('ordinary', this.value)" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-primary);color:var(--text-primary);">${ordOpts}</select>
        </div>
        <div style="font-size:11px;color:var(--text-muted);">可同时绑定两个知识库，写作时分别注入。普通知识库需先在知识库页面上传参考作品并完成提取。</div>
    `;
}

async function saveNovelKBBinding(kbType, value) {
    const novelId = (typeof appState !== "undefined" && appState.currentNovelId) || null;
    if (!novelId) return;
    const payload = kbType === "advanced"
        ? { knowledge_base_id: Number(value) }
        : { ordinary_knowledge_base_id: Number(value) };
    try {
        await apiPut(`/api/novels/${novelId}`, payload);
        if (typeof updateStatusBar === "function") updateStatusBar("知识库绑定已更新");
    } catch (e) {
        alert("绑定失败：" + e.message);
        await loadNovelKBBinding();
    }
}
