const ROLE_COLORS = {
    "主角": "#f1c40f",
    "配角": "#3498db",
    "龙套": "#95a5a6"
};

const CATEGORY_COLORS = {
    "地点": "#e74c3c",
    "组织": "#9b59b6",
    "物品": "#1abc9c",
    "概念": "#34495e",
    "历史": "#e67e22"
};

const RELATION_COLORS = {
    "师徒": "#9b59b6",
    "敌对": "#e74c3c",
    "盟友": "#27ae60",
    "亲属": "#e67e22",
    "恋人": "#e91e63",
    "主仆": "#34495e",
    "朋友": "#2ecc71",
    "上下级": "#f39c12"
};

let currentView = "stage";
let currentStageIndex = 0;
let graphSimulation = null;
let graphSvg = null;
let graphContainer = null;
let graphData = null;
let hiddenRelationTypes = new Set();
let showChapterNodes = false;
let worldMapMode = "";

const WORLD_CATEGORY_STYLES = {
    location: { color: "#3b82f6", emoji: "📍" },
    power: { color: "#8b5cf6", emoji: "🏛" },
    skill: { color: "#f59e0b", emoji: "📜" },
    item: { color: "#10b981", emoji: "💎" },
    other: { color: "#64748b", emoji: "🗺" }
};

function isRelationLink(l) {
    return l.type !== "appears_in" && l.type !== "related";
}

function svgIdPrefix(prefix, name) {
    return prefix + "-" + encodeURIComponent(name);
}

function nodeVisualRadius(n) {
    if (n.type === "character") return (n.role === "主角" ? 22 : (n.role === "配角" ? 16 : 11)) + 2;
    if (n.type === "chapter") return 17;
    return 19;
}

function relationCurvePoints(d) {
    const sx0 = d.source.x, sy0 = d.source.y;
    const tx0 = d.target.x, ty0 = d.target.y;
    const dx = tx0 - sx0, dy = ty0 - sy0;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    const rs = nodeVisualRadius(d.source) + 2;
    const rt = nodeVisualRadius(d.target) + 6;
    const sx = sx0 + ux * rs, sy = sy0 + uy * rs;
    const tx = tx0 - ux * rt, ty = ty0 - uy * rt;
    const mx = (sx + tx) / 2, my = (sy + ty) / 2;
    const cx = mx - uy * 40, cy = my + ux * 40;
    return { sx, sy, tx, ty, cx, cy };
}

function relationCurvePath(d) {
    const p = relationCurvePoints(d);
    return `M${p.sx},${p.sy} Q${p.cx},${p.cy} ${p.tx},${p.ty}`;
}

function relationCurveMid(d) {
    const p = relationCurvePoints(d);
    return {
        x: (p.sx + 2 * p.cx + p.tx) / 4,
        y: (p.sy + 2 * p.cy + p.ty) / 4
    };
}

function classifyWorldCategory(category) {
    const c = (category || "").trim();
    if (!c || c === "地点" || c === "区域") return "location";
    if (c === "势力" || c === "组织" || c === "门派") return "power";
    if (c.includes("功法") || c.includes("技能") || c.includes("武学")) return "skill";
    if (c.includes("物品") || c.includes("宝物") || c.includes("法宝") || c.includes("兵器")) return "item";
    return "other";
}

function hashStringSeed(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
        h ^= str.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return h >>> 0;
}

function seededRandom(seed) {
    let s = seed >>> 0;
    return function () {
        s = (s + 0x6D2B79F5) >>> 0;
        let t = Math.imul(s ^ (s >>> 15), 1 | s);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function buildRegionBlobPath(name, baseRadius) {
    const rand = seededRandom(hashStringSeed(name));
    const segments = 8;
    const pts = [];
    for (let i = 0; i < segments; i++) {
        const angle = (i / segments) * Math.PI * 2;
        const r = baseRadius * (1.4 + rand() * 0.4);
        pts.push({ x: Math.cos(angle) * r, y: Math.sin(angle) * r });
    }
    let d = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
    for (let i = 0; i < segments; i++) {
        const p0 = pts[(i - 1 + segments) % segments];
        const p1 = pts[i];
        const p2 = pts[(i + 1) % segments];
        const p3 = pts[(i + 2) % segments];
        const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
        const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
        d += `C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
    }
    return d + "Z";
}

function openKnowledgeGraph() {
    const existing = document.getElementById("graph-overlay");
    if (existing) existing.remove();
    if (graphSimulation) { graphSimulation.stop(); graphSimulation = null; }

    const overlay = document.createElement("div");
    overlay.id = "graph-overlay";
    overlay.className = "graph-overlay";
    overlay.innerHTML = `
        <div class="graph-panel">
            <div class="graph-header">
                <h3>知识图谱</h3>
                <div class="graph-view-switcher">
                    <button class="graph-view-btn active" data-view="stage" onclick="setGraphView('stage')">角色演化</button>
                    <button class="graph-view-btn" data-view="graph" onclick="setGraphView('graph')">关系网络</button>
                    <button class="graph-view-btn" data-view="map" onclick="setGraphView('map')">世界观地图</button>
                </div>
                <button class="btn btn-sm btn-outline" onclick="closeKnowledgeGraph()">关闭</button>
            </div>
            <div class="graph-body" id="graph-body"><div class="graph-loading">加载中...</div></div>
            <div class="graph-detail" id="graph-detail" style="display:none;"></div>
        </div>
    `;
    document.body.appendChild(overlay);
    setTimeout(() => overlay.classList.add("visible"), 10);
    graphContainer = document.getElementById("graph-body");
    const novelId = appState.currentNovelId || getSelectedNovelId();
    if (novelId) loadGraphData(novelId);
    else document.getElementById("graph-body").innerHTML = '<div class="graph-empty">请先选择小说</div>';
}

function closeKnowledgeGraph() {
    if (graphSimulation) { graphSimulation.stop(); graphSimulation = null; }
    const overlay = document.getElementById("graph-overlay");
    if (overlay) {
        overlay.classList.remove("visible");
        setTimeout(() => { if (overlay) overlay.remove(); }, 200);
    }
    graphSvg = null;
    graphContainer = null;
    graphData = null;
    currentView = "stage";
    currentStageIndex = 0;
    hiddenRelationTypes = new Set();
    showChapterNodes = false;
    worldMapMode = "";
    volumeFilter = "";
}

function setActiveViewButton(view) {
    currentView = view;
    document.querySelectorAll(".graph-view-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.view === view);
    });
}

function setGraphView(view) {
    if (!graphData) return;
    const detail = document.getElementById("graph-detail");
    if (detail) detail.style.display = "none";
    if (view === "stage") {
        setActiveViewButton("stage");
        renderCharacterStageView(graphData);
    } else if (view === "graph") {
        setActiveViewButton("graph");
        if (graphData.nodes && graphData.nodes.length > 0) renderGraph(graphData);
        else document.getElementById("graph-body").innerHTML = '<div class="graph-empty">暂无关系数据</div>';
    } else if (view === "map") {
        setActiveViewButton("map");
        renderWorldMap(graphData);
    }
}

async function loadGraphData(novelId) {
    const body = document.getElementById("graph-body");
    try {
        const data = await apiGet(`/api/novels/${novelId}/knowledge/graph`);
        graphData = data;
        currentStageIndex = 0;
        const stages = data.stages || [];
        if (stages.length > 0) {
            setActiveViewButton("stage");
            renderCharacterStageView(data);
            return;
        }
        if (data.nodes && data.nodes.length > 0) {
            setActiveViewButton("graph");
            renderGraph(data);
            return;
        }
        if (data.regions && data.regions.length > 0) {
            setActiveViewButton("map");
            renderWorldMap(data);
            return;
        }
        body.innerHTML = '<div class="graph-empty">暂无知识数据，请先写章节或手动添加知识</div>';
    } catch (e) {
        body.innerHTML = '<div class="graph-empty">加载失败: ' + e.message + "</div>";
    }
}

function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

function shadeColor(hex, percent) {
    const n = parseInt((hex || "#888888").replace("#", ""), 16);
    let r = (n >> 16) & 0xff, g = (n >> 8) & 0xff, b = n & 0xff;
    const f = percent < 0 ? 0 : 255, p = Math.abs(percent) / 100;
    r = Math.round((f - r) * p + r);
    g = Math.round((f - g) * p + g);
    b = Math.round((f - b) * p + b);
    return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

function renderCharacterStageView(data) {
    if (graphSimulation) { graphSimulation.stop(); graphSimulation = null; }
    graphSvg = null;
    setActiveViewButton("stage");
    const body = document.getElementById("graph-body");
    const detail = document.getElementById("graph-detail");
    if (detail) detail.style.display = "none";

    const stages = (data && data.stages) || [];
    if (stages.length === 0) {
        body.innerHTML = '<div class="graph-empty">暂无阶段数据，请先生成全文大纲或写章节</div>';
        return;
    }
    if (currentStageIndex >= stages.length) currentStageIndex = 0;

    body.innerHTML = `
        <div class="stage-view">
            <div class="stage-arc-bar"></div>
            <div class="stage-selector" id="stage-selector"></div>
            <div class="stage-content fade-in" id="stage-content"></div>
        </div>
    `;

    const selector = document.getElementById("stage-selector");
    stages.forEach((stage, i) => {
        const pill = document.createElement("button");
        pill.className = "stage-pill" + (i === currentStageIndex ? " active" : "");
        pill.innerHTML =
            `<span class="stage-pill-index">${String(i + 1).padStart(2, "0")}</span>` +
            `<span class="stage-pill-name">${escapeHtml(stage.name)}</span>` +
            `<span class="stage-pill-range">第${stage.chapter_range[0]}-${stage.chapter_range[1]}章</span>`;
        pill.onclick = () => selectStage(i);
        selector.appendChild(pill);
    });

    renderStageCharacters(stages[currentStageIndex]);
}

function selectStage(index) {
    if (!graphData || !graphData.stages) return;
    if (index === currentStageIndex) return;
    currentStageIndex = index;
    document.querySelectorAll(".stage-pill").forEach((p, i) => {
        p.classList.toggle("active", i === index);
    });
    const content = document.getElementById("stage-content");
    if (content) {
        content.classList.remove("fade-in");
        void content.offsetWidth;
        content.classList.add("fade-in");
    }
    renderStageCharacters(graphData.stages[index]);
}

function renderStageCharacters(stage) {
    const content = document.getElementById("stage-content");
    if (!content || !stage) return;

    const characters = stage.characters || [];
    const rangeText = `第${stage.chapter_range[0]}-${stage.chapter_range[1]}章`;

    if (characters.length === 0) {
        content.innerHTML =
            `<div class="stage-empty-state">` +
                `<div class="stage-empty-icon">✦</div>` +
                `<div class="stage-empty-title">本阶段暂无角色数据</div>` +
                `<div class="stage-empty-desc">写一些属于「${escapeHtml(stage.name)} · ${rangeText}」的章节后，角色会在此处登场</div>` +
            `</div>`;
        return;
    }

    const proCount = characters.filter(c => c.is_protagonist || c.role === "主角").length;
    let html = `<div class="stage-meta">共 <strong>${characters.length}</strong> 位角色 · ${rangeText} · 主角 ${proCount} 位</div>`;
    html += `<div class="character-grid">`;
    characters.forEach((char, idx) => {
        html += buildCharacterCard(char, idx);
    });
    html += `</div>`;
    content.innerHTML = html;

    content.querySelectorAll(".character-card").forEach(card => {
        const idx = parseInt(card.dataset.index, 10);
        card.onclick = () => showCharacterStageDetail(characters[idx], stage);
    });
}

function buildCharacterCard(char, idx) {
    const isPro = char.is_protagonist || char.role === "主角";
    const role = char.role || "配角";
    const roleColor = ROLE_COLORS[role] || ROLE_COLORS["龙套"];
    const initial = (char.name || "?").charAt(0);

    const rels = char.relations || [];
    const relChips = rels.slice(0, 4).map(r => {
        const rc = RELATION_COLORS[r.type] || "#95a5a6";
        return `<span class="rel-chip" style="border-color:${rc}55;">` +
            `<span class="rel-chip-type" style="background:${rc}22;color:${rc};">${escapeHtml(r.type)}</span>` +
            `<span class="rel-chip-target">${escapeHtml(r.target)}</span>` +
            `</span>`;
    }).join("");
    const relExtra = rels.length > 4 ? `<span class="rel-chip rel-chip-more">+${rels.length - 4}</span>` : "";

    const chapters = char.appeared_chapters || [];
    let chText = "";
    if (chapters.length > 0) {
        chText = chapters.length > 8
            ? `出场：第${chapters[0]}-${chapters[chapters.length - 1]}章（共 ${chapters.length} 章）`
            : `出场：第${chapters.join("、")}章`;
    }

    const desc = char.description || "暂无描述";
    const shortDesc = desc.length > 90 ? desc.substring(0, 90) + "…" : desc;

    return `<div class="character-card${isPro ? " character-card-protagonist" : ""}" data-index="${idx}" style="--role-color:${roleColor};animation-delay:${Math.min(idx, 8) * 0.04}s;">` +
        `<div class="character-card-glow"></div>` +
        (isPro ? `<div class="protagonist-badge">主角</div>` : "") +
        `<div class="character-card-header">` +
            `<div class="character-avatar" style="background:linear-gradient(135deg,${roleColor},${shadeColor(roleColor, -30)});">${escapeHtml(initial)}</div>` +
            `<div class="character-card-titles">` +
                `<div class="character-card-name">${escapeHtml(char.name)}</div>` +
                `<span class="character-role-badge" style="background:${roleColor}22;color:${roleColor};">${escapeHtml(role)}</span>` +
            `</div>` +
        `</div>` +
        `<div class="character-card-desc">${escapeHtml(shortDesc)}</div>` +
        (rels.length > 0 ? `<div class="character-card-rels">${relChips}${relExtra}</div>` : "") +
        (chText ? `<div class="character-card-chapters">📖 ${escapeHtml(chText)}</div>` : "") +
        `</div>`;
}

function showCharacterStageDetail(char, stage) {
    const detail = document.getElementById("graph-detail");
    if (!detail || !char) return;

    const isPro = char.is_protagonist || char.role === "主角";
    const role = char.role || "配角";
    const roleColor = ROLE_COLORS[role] || ROLE_COLORS["龙套"];
    const initial = (char.name || "?").charAt(0);

    let html = `<div class="graph-detail-header" style="border-bottom:2px solid ${roleColor};">` +
        `<div style="display:flex;align-items:center;gap:12px;">` +
            `<div class="character-avatar character-avatar-lg" style="background:linear-gradient(135deg,${roleColor},${shadeColor(roleColor, -30)});">${escapeHtml(initial)}</div>` +
            `<div style="min-width:0;">` +
                `<div style="font-size:16px;font-weight:600;color:var(--text-primary);display:flex;align-items:center;gap:8px;">${escapeHtml(char.name)}` +
                    (isPro ? `<span class="protagonist-badge" style="position:static;">主角</span>` : "") +
                `</div>` +
                `<div style="font-size:11px;color:${roleColor};margin-top:4px;font-weight:600;">${escapeHtml(role)} · ${escapeHtml(stage.name)}</div>` +
            `</div>` +
        `</div></div>`;

    html += `<div class="detail-section">` +
        `<div class="detail-section-title">🖼️ 角色形象</div>`;
    if (char.image_url) {
        html += `<img src="${escapeHtml(char.image_url)}" class="character-portrait" alt="${escapeHtml(char.name)} 角色形象" loading="lazy">` +
            `<div style="margin-top:8px;display:flex;gap:8px;">` +
            `<button class="btn btn-sm btn-outline portrait-regenerate-btn" data-char-name="${escapeHtml(char.name)}" data-stage-index="${currentStageIndex}">🔄 重新生成形象</button>` +
            `</div>`;
    } else {
        html += `<div class="character-portrait-placeholder">` +
            `<div class="character-portrait-placeholder-icon">🎨</div>` +
            `<div class="character-portrait-placeholder-text">暂无角色形象，点击下方按钮生成</div>` +
            `<button class="btn btn-sm btn-primary portrait-generate-btn" data-char-name="${escapeHtml(char.name)}" data-stage-index="${currentStageIndex}">🎨 生成角色形象</button>` +
            `</div>`;
    }
    html += `</div>`;

    if (char.description) {
        html += `<div class="detail-section">` +
            `<div class="detail-section-title">📝 角色状态（${escapeHtml(stage.name)}）</div>` +
            `<div class="detail-desc" style="border-left:3px solid ${roleColor};">${escapeHtml(char.description)}</div>` +
            `</div>`;
    }

    const rels = char.relations || [];
    if (rels.length > 0) {
        html += `<div class="detail-section"><div class="detail-section-title">🔗 人物关系 (${rels.length})</div>`;
        rels.forEach(r => {
            const rc = RELATION_COLORS[r.type] || "#95a5a6";
            html += `<div class="detail-rel-row" style="background:${rc}0d;border-left:2px solid ${rc};">` +
                `<span style="color:var(--text-primary);font-weight:500;font-size:12px;">${escapeHtml(r.target)}</span>` +
                `<span class="detail-rel-type" style="background:${rc}22;color:${rc};">${escapeHtml(r.type)}</span>` +
                `</div>`;
        });
        html += `</div>`;
    }

    const chapters = char.appeared_chapters || [];
    if (chapters.length > 0) {
        const chText = chapters.length > 12
            ? chapters.slice(0, 12).join("、") + ` …等 ${chapters.length} 章`
            : chapters.join("、");
        html += `<div class="detail-section"><div class="detail-section-title">📖 出场章节 (${chapters.length})</div>` +
            `<div class="detail-chapters">${escapeHtml(chText)}</div></div>`;
    }

    if (graphData && graphData.stages) {
        const otherStages = graphData.stages
            .map((s, i) => ({ s, i }))
            .filter(({ s, i }) => i !== currentStageIndex && (s.characters || []).some(c => c.name === char.name));
        if (otherStages.length > 0) {
            html += `<div class="detail-section"><div class="detail-section-title">⏱ 跨阶段登场 (${otherStages.length})</div>`;
            otherStages.forEach(({ s }) => {
                const otherChar = (s.characters || []).find(c => c.name === char.name);
                const evHint = otherChar && otherChar.description ? escapeHtml(otherChar.description.substring(0, 40)) + "…" : "";
                html += `<div class="detail-stage-row">` +
                    `<span class="detail-stage-name">${escapeHtml(s.name)}</span>` +
                    `<span class="detail-stage-range">第${s.chapter_range[0]}-${s.chapter_range[1]}章</span>` +
                    (evHint ? `<span class="detail-stage-ev">${evHint}</span>` : "") +
                    `</div>`;
            });
            html += `</div>`;
        }
    }

    html += `<button class="btn btn-sm btn-outline" onclick="document.getElementById('graph-detail').style.display='none'" style="margin-top:14px;width:100%;">关闭</button>`;
    detail.innerHTML = html;
    detail.style.display = "block";

    const genBtn = detail.querySelector(".portrait-generate-btn, .portrait-regenerate-btn");
    if (genBtn) {
        const force = genBtn.classList.contains("portrait-regenerate-btn");
        genBtn.onclick = () => generateCharacterPortrait(genBtn.dataset.charName, parseInt(genBtn.dataset.stageIndex, 10), force);
    }
}

async function generateCharacterPortrait(characterName, stageIndex, force) {
    const novelId = (typeof appState !== "undefined" && appState.currentNovelId) || (typeof getSelectedNovelId === "function" && getSelectedNovelId());
    if (!novelId) {
        alert("未找到当前小说，无法生成");
        return;
    }

    const stage = graphData && graphData.stages ? graphData.stages[stageIndex] : null;
    const char = stage && stage.characters ? stage.characters.find(c => c.name === characterName) : null;
    if (!char) return;

    const detail = document.getElementById("graph-detail");
    const btn = detail ? detail.querySelector(".portrait-generate-btn, .portrait-regenerate-btn") : null;
    const placeholder = detail ? detail.querySelector(".character-portrait-placeholder") : null;
    const originalText = btn ? btn.textContent : "";

    if (btn) {
        btn.disabled = true;
        btn.textContent = force ? "重新生成中... 请稍候" : "生成中... 请稍候";
    }

    try {
        const result = await apiPost(`/api/novels/${novelId}/knowledge/character-image`, {
            stage_index: stageIndex,
            character_name: characterName,
            description: char.description || "",
            role: char.role || "",
            force: !!force,
        });

        char.image_url = result.image_url || "";

        const stage2 = graphData.stages[stageIndex];
        const char2 = stage2.characters.find(c => c.name === characterName);
        if (char2) char2.image_url = char.image_url;
        if (graphData.character_images) graphData.character_images[characterName] = char.image_url;

        showCharacterStageDetail(char, stage);
    } catch (e) {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText || "🎨 生成角色形象";
        }
        if (placeholder) {
            const errEl = placeholder.querySelector(".portrait-error");
            if (errEl) {
                errEl.textContent = "生成失败：" + (e.message || "请稍后重试");
            } else {
                const d = document.createElement("div");
                d.className = "portrait-error";
                d.textContent = "生成失败：" + (e.message || "请稍后重试");
                placeholder.appendChild(d);
            }
        }
    }
}

function renderGraph(data) {
    setActiveViewButton("graph");
    const body = document.getElementById("graph-body");
    body.innerHTML = "";
    const detail = document.getElementById("graph-detail");
    if (detail) detail.style.display = "none";

    const characterImages = data.character_images || {};

    const toolbar = document.createElement("div");
    toolbar.className = "graph-toolbar";

    const volumes = data.volumes || [];
    if (volumes.length > 0) {
        const volWrap = document.createElement("div");
        volWrap.style.cssText = "display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary);";
        const volLabel = document.createElement("span");
        volLabel.textContent = "分卷:";
        const volSelect = document.createElement("select");
        volSelect.style.cssText = "background:var(--bg-tertiary);color:var(--text-primary);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:12px;max-width:220px;cursor:pointer;";
        let volOpts = '<option value="">全部卷</option>';
        volumes.forEach(v => {
            if (!v.range || v.range.length < 2) return;
            const sel = v.name === volumeFilter ? " selected" : "";
            volOpts += `<option value="${escapeHtml(v.name)}"${sel}>${escapeHtml(v.name)}（第${v.range[0]}-${v.range[1]}章）</option>`;
        });
        volSelect.innerHTML = volOpts;
        volSelect.onchange = () => {
            volumeFilter = volSelect.value;
            if (graphSimulation) { graphSimulation.stop(); graphSimulation = null; }
            renderGraph(graphData);
        };
        volWrap.appendChild(volLabel);
        volWrap.appendChild(volSelect);
        toolbar.appendChild(volWrap);
    }

    const chapterBtn = document.createElement("button");
    chapterBtn.className = "btn btn-sm btn-outline";
    chapterBtn.textContent = `章节节点：${showChapterNodes ? "显示" : "隐藏"}`;
    chapterBtn.onclick = () => {
        showChapterNodes = !showChapterNodes;
        if (graphSimulation) { graphSimulation.stop(); graphSimulation = null; }
        renderGraph(graphData);
    };
    toolbar.appendChild(chapterBtn);
    body.appendChild(toolbar);

    const width = body.clientWidth || 800;
    const height = body.clientHeight || 600;

    const rawNodes = data.nodes.map(n => ({ ...n }));
    const nodeMap = {};
    rawNodes.forEach(n => { nodeMap[n.id] = n; });
    let nodes = rawNodes;
    let links = data.links.map(l => ({ ...l })).filter(l => nodeMap[l.source] && nodeMap[l.target]);

    let volDef = null;
    if (volumeFilter) {
        volDef = (volumes || []).find(v => v.name === volumeFilter) || null;
        if (volDef && volDef.range && volDef.range.length >= 2) {
            const [lo, hi] = volDef.range;
            const chInVol = new Set(rawNodes.filter(n => n.type === "chapter" && n.number >= lo && n.number <= hi).map(n => n.id));
            const charsInVol = new Set(links.filter(l => l.type === "appears_in" && chInVol.has(l.target)).map(l => l.source));
            const worldsInVol = new Set(links.filter(l => l.type === "related" && charsInVol.has(l.source)).map(l => l.target));
            nodes = rawNodes.filter(n =>
                (n.type === "chapter" && chInVol.has(n.id)) ||
                (n.type === "character" && charsInVol.has(n.id)) ||
                (n.type === "world" && worldsInVol.has(n.id))
            );
            const idSetV = new Set(nodes.map(n => n.id));
            links = links.filter(l => idSetV.has(l.source) && idSetV.has(l.target));
        } else {
            volumeFilter = "";
            volDef = null;
        }
    }

    if (!showChapterNodes) {
        nodes = nodes.filter(n => n.type !== "chapter");
        const idSet = new Set(nodes.map(n => n.id));
        links = links.filter(l => l.type !== "appears_in" && idSet.has(l.source) && idSet.has(l.target));
        const degree = {};
        links.forEach(l => {
            degree[l.source] = (degree[l.source] || 0) + 1;
            degree[l.target] = (degree[l.target] || 0) + 1;
        });
        nodes = nodes.filter(n => (degree[n.id] || 0) > 0);
        const idSet2 = new Set(nodes.map(n => n.id));
        links = links.filter(l => idSet2.has(l.source) && idSet2.has(l.target));
    }
    const relLinks = links.filter(isRelationLink);
    const weakLinks = links.filter(l => !isRelationLink(l));
    const relationTypes = [...new Set(relLinks.map(l => l.type))];

    graphSvg = d3.select(body).append("svg")
        .attr("width", width)
        .attr("height", height)
        .attr("class", "graph-svg");

    const defs = graphSvg.append("defs");
    const bgGrad = defs.append("radialGradient").attr("id", "graph-bg-grad")
        .attr("cx", "50%").attr("cy", "45%").attr("r", "75%");
    bgGrad.append("stop").attr("offset", "0%").attr("stop-color", "#1a2342");
    bgGrad.append("stop").attr("offset", "60%").attr("stop-color", "#101728");
    bgGrad.append("stop").attr("offset", "100%").attr("stop-color", "#0a0e17");
    graphSvg.append("rect").attr("width", width).attr("height", height).attr("fill", "url(#graph-bg-grad)");

    const glow = defs.append("filter").attr("id", "node-glow")
        .attr("x", "-60%").attr("y", "-60%").attr("width", "220%").attr("height", "220%");
    glow.append("feGaussianBlur").attr("stdDeviation", "3.5").attr("result", "blur");
    const merge = glow.append("feMerge");
    merge.append("feMergeNode").attr("in", "blur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    relationTypes.forEach(t => {
        const color = RELATION_COLORS[t] || "#4a5568";
        defs.append("marker")
            .attr("id", svgIdPrefix("arrow", t))
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 9).attr("refY", 0)
            .attr("markerWidth", 6).attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", color);
    });

    graphSvg.append("text").attr("x", 20).attr("y", 32)
        .attr("fill", "var(--text-secondary)").attr("font-size", "13px")
        .attr("font-weight", "600").attr("letter-spacing", "1.5px")
        .text(volumeFilter ? `关系网络 · ${volumeFilter}` : "关系网络 · 力导向图");
    const charCount = nodes.filter(n => n.type === "character").length;
    graphSvg.append("text").attr("x", 20).attr("y", 50)
        .attr("fill", "var(--text-muted)").attr("font-size", "10px")
        .attr("letter-spacing", "0.5px").text(`节点 ${nodes.length} · 角色 ${charCount} · 关系 ${relLinks.length}`);

    const legendData = [
        { label: "主角", color: ROLE_COLORS["主角"] },
        { label: "配角", color: ROLE_COLORS["配角"] },
        { label: "龙套", color: ROLE_COLORS["龙套"] },
        { label: "章节", color: "#2ecc71" },
        { label: "世界观", color: "#9b59b6" }
    ];
    const legend = graphSvg.append("g").attr("transform", `translate(${width - 120}, 22)`);
    legendData.forEach((d, i) => {
        const ly = i * 18;
        legend.append("circle").attr("cx", 6).attr("cy", ly).attr("r", 5).attr("fill", d.color).attr("opacity", 0.9);
        legend.append("text").attr("x", 18).attr("y", ly + 3).attr("fill", "var(--text-muted)").attr("font-size", "10px").text(d.label);
    });
    if (relationTypes.length > 0) {
        const relStart = legendData.length * 18 + 18;
        legend.append("text")
            .attr("x", 0).attr("y", relStart)
            .attr("fill", "var(--text-muted)").attr("font-size", "9px").attr("letter-spacing", "1px")
            .text("关系类型 · 点击显隐");
        const relLegend = legend.selectAll("g.legend-item").data(relationTypes).enter().append("g")
            .attr("class", d => "legend-item" + (hiddenRelationTypes.has(d) ? " off" : ""))
            .attr("transform", (d, i) => `translate(0, ${relStart + 18 + i * 18})`)
            .on("click", function (event, d) {
                if (hiddenRelationTypes.has(d)) hiddenRelationTypes.delete(d);
                else hiddenRelationTypes.add(d);
                d3.select(this).classed("off", hiddenRelationTypes.has(d));
                curveElements.attr("visibility", l => hiddenRelationTypes.has(l.type) ? "hidden" : "visible");
                linkLabels.attr("visibility", l => hiddenRelationTypes.has(l.type) ? "hidden" : "visible");
            });
        relLegend.append("circle").attr("cx", 6).attr("cy", 0).attr("r", 5)
            .attr("fill", d => RELATION_COLORS[d] || "#95a5a6").attr("opacity", 0.9);
        relLegend.append("text").attr("x", 18).attr("y", 3)
            .attr("fill", "var(--text-muted)").attr("font-size", "10px").text(d => d);
    }

    const g = graphSvg.append("g");
    graphSvg.call(d3.zoom().scaleExtent([0.3, 5]).on("zoom", (event) => { g.attr("transform", event.transform); }));

    const linkGroup = g.append("g").attr("class", "graph-links");
    const nodeGroup = g.append("g").attr("class", "graph-nodes");

    graphSimulation = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id(d => d.id).distance(d => d.type === "appears_in" ? 55 : 95))
        .force("charge", d3.forceManyBody().strength(-280))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collision", d3.forceCollide().radius(d => {
            if (d.type === "character") return d.role === "主角" ? 36 : (d.role === "配角" ? 28 : 22);
            return 24;
        }));

    const lineElements = linkGroup.selectAll("line.graph-link").data(weakLinks).enter().append("line")
        .attr("class", "graph-link")
        .attr("stroke", d => RELATION_COLORS[d.type] || "#4a5568")
        .attr("stroke-width", d => d.type === "appears_in" ? 1 : 2.2)
        .attr("stroke-opacity", d => d.type === "appears_in" ? 0.22 : 0.65)
        .attr("stroke-dasharray", d => d.type === "appears_in" ? "3,4" : "none");

    const curveElements = linkGroup.selectAll("path.graph-link").data(relLinks).enter().append("path")
        .attr("class", "graph-link graph-link-curve")
        .attr("fill", "none")
        .attr("stroke", d => RELATION_COLORS[d.type] || "#4a5568")
        .attr("stroke-width", 2.2)
        .attr("stroke-opacity", 0.65)
        .attr("marker-end", d => `url(#${svgIdPrefix("arrow", d.type)})`);

    const linkElements = lineElements.merge(curveElements);

    const linkLabels = linkGroup.selectAll("text.graph-link-label").data(relLinks).enter().append("text")
        .attr("class", "graph-link-label")
        .attr("text-anchor", "middle")
        .attr("fill", d => RELATION_COLORS[d.type] || "#999")
        .attr("font-size", "9px")
        .attr("font-weight", "600")
        .text(d => d.label || d.type);

    curveElements.attr("visibility", d => hiddenRelationTypes.has(d.type) ? "hidden" : "visible");
    linkLabels.attr("visibility", d => hiddenRelationTypes.has(d.type) ? "hidden" : "visible");

    const nodeElements = nodeGroup.selectAll("g").data(nodes).enter().append("g")
        .attr("class", "graph-node")
        .call(d3.drag().on("start", dragStarted).on("drag", dragged).on("end", dragEnded))
        .on("click", (event, d) => { event.stopPropagation(); showNodeDetail(d); })
        .on("mouseenter", function (event, d) {
            d3.select(this).select("circle, rect, polygon").attr("filter", "url(#node-glow)");
            linkElements.attr("stroke-opacity", l => {
                const s = typeof l.source === "object" ? l.source : nodeMap[l.source];
                const t = typeof l.target === "object" ? l.target : nodeMap[l.target];
                return (s === d || t === d) ? 0.95 : 0.08;
            });
            linkLabels.attr("opacity", l => {
                const s = typeof l.source === "object" ? l.source : nodeMap[l.source];
                const t = typeof l.target === "object" ? l.target : nodeMap[l.target];
                return (s === d || t === d) ? 1 : 0.2;
            });
        })
        .on("mouseleave", function (event, d) {
            d3.select(this).select("circle, rect, polygon").attr("filter", null);
            linkElements.attr("stroke-opacity", l => l.type === "appears_in" ? 0.22 : 0.65);
            linkLabels.attr("opacity", 1);
        });

    nodeElements.each(function (d) {
        const el = d3.select(this);
        if (d.type === "character") {
            const radius = d.role === "主角" ? 22 : (d.role === "配角" ? 16 : 11);
            const color = ROLE_COLORS[d.role] || ROLE_COLORS["龙套"];
            el.append("circle").attr("r", radius + 3).attr("fill", color).attr("opacity", 0.18);
            const portrait = characterImages[d.name];
            if (portrait) {
                const clipId = svgIdPrefix("clip", d.id);
                defs.append("clipPath").attr("id", clipId).append("circle").attr("r", radius);
                el.append("circle").attr("r", radius).attr("fill", "#0a0e17");
                el.append("image")
                    .attr("href", portrait)
                    .attr("width", radius * 2).attr("height", radius * 2)
                    .attr("x", -radius).attr("y", -radius)
                    .attr("preserveAspectRatio", "xMidYMid slice")
                    .attr("clip-path", `url(#${clipId})`);
                el.append("circle").attr("r", radius).attr("fill", "none").attr("stroke", color).attr("stroke-width", 2);
            } else {
                el.append("circle").attr("r", radius)
                    .attr("fill", color)
                    .attr("stroke", "#0a0e17").attr("stroke-width", 2);
                el.append("circle").attr("r", radius - 5).attr("fill", shadeColor(color, 25)).attr("opacity", 0.5);
                el.append("text")
                    .attr("text-anchor", "middle")
                    .attr("dy", 0)
                    .attr("dominant-baseline", "central")
                    .attr("font-weight", "bold")
                    .attr("font-size", "16px")
                    .attr("fill", d.type === "character" ? "#e2e8f0" : "#94a3b8")
                    .attr("pointer-events", "none")
                    .text(d.name ? d.name[0] : "?");
            }
        } else if (d.type === "chapter") {
            el.append("rect").attr("width", 30).attr("height", 30).attr("x", -15).attr("y", -15).attr("rx", 7)
                .attr("fill", "#2ecc71").attr("stroke", "#0a0e17").attr("stroke-width", 2).attr("opacity", 0.92);
        } else if (d.type === "world") {
            el.append("polygon").attr("points", "0,-17 17,0 0,17 -17,0")
                .attr("fill", CATEGORY_COLORS[d.category] || "#95a5a6")
                .attr("stroke", "#0a0e17").attr("stroke-width", 2).attr("opacity", 0.92);
        }
        el.append("text")
            .attr("dy", d.type === "character" ? (d.role === "主角" ? 38 : 30) : 34)
            .attr("text-anchor", "middle")
            .attr("fill", "var(--text-secondary)")
            .attr("font-size", "10px")
            .attr("font-weight", d.type === "character" && d.role === "主角" ? "600" : "400")
            .text(d.name.length > 6 ? d.name.substring(0, 6) + "…" : d.name);
    });

    graphSimulation.on("tick", () => {
        lineElements.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        curveElements.attr("d", relationCurvePath);
        linkLabels.attr("x", d => relationCurveMid(d).x)
            .attr("y", d => relationCurveMid(d).y - 5);
        nodeElements.attr("transform", d => `translate(${d.x},${d.y})`);
    });
}

function dragStarted(event, d) {
    if (!event.active) graphSimulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
}
function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
function dragEnded(event, d) {
    if (!event.active) graphSimulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
}

function findCharStageIndex(name) {
    if (!graphData || !graphData.stages) return -1;
    let idx = -1;
    graphData.stages.forEach((s, i) => {
        if ((s.characters || []).some(c => c.name === name)) idx = i;
    });
    return idx;
}

function showNodeDetail(node) {
    const detail = document.getElementById("graph-detail");
    if (!detail || !node) return;
    let html = `<div class="graph-detail-header"><strong>${escapeHtml(node.name)}</strong>` +
        `<button class="btn btn-sm btn-outline" onclick="document.getElementById('graph-detail').style.display='none'" style="margin-left:auto;padding:2px 8px;font-size:11px;">✕</button></div>`;

    if (node.type === "character") {
        const portrait = graphData && graphData.character_images ? graphData.character_images[node.name] : null;
        if (portrait) html += `<img class="node-portrait" src="${escapeHtml(portrait)}" alt="${escapeHtml(node.name)} 头像">`;
        const color = ROLE_COLORS[node.role] || "#95a5a6";
        html += `<div style="margin-bottom:8px;"><span class="character-role-badge" style="background:${color}22;color:${color};">${escapeHtml(node.role || "配角")}</span></div>`;
        if (node.description) html += `<div style="color:var(--text-secondary);font-size:12px;line-height:1.7;margin-bottom:10px;">${escapeHtml(node.description)}</div>`;
        if (node.status) html += `<div style="color:var(--text-muted);font-size:11px;">状态: ${escapeHtml(node.status)}</div>`;
        const sIdx = findCharStageIndex(node.name);
        if (sIdx >= 0) {
            html += `<button class="btn btn-sm btn-outline node-portrait-btn" style="margin-top:10px;width:100%;" data-char-name="${escapeHtml(node.name)}" data-stage-index="${sIdx}">` +
                (portrait ? "🔄 重新生成角色形象" : "🎨 生成角色形象") + `</button>`;
        }
    } else if (node.type === "chapter") {
        html += `<div style="color:var(--text-muted);font-size:12px;margin-bottom:8px;">第 ${escapeHtml(node.chapter || "?")} 章</div>`;
        if (node.summary) html += `<div style="color:var(--text-secondary);font-size:12px;line-height:1.7;">${escapeHtml(node.summary)}</div>`;
    } else if (node.type === "world") {
        const color = CATEGORY_COLORS[node.category] || "#95a5a6";
        html += `<div style="margin-bottom:8px;"><span class="character-role-badge" style="background:${color}22;color:${color};">${escapeHtml(node.category || "其他")}</span></div>`;
        if (node.description) html += `<div style="color:var(--text-secondary);font-size:12px;line-height:1.7;">${escapeHtml(node.description)}</div>`;
    }
    detail.innerHTML = html;
    detail.style.display = "block";

    const nodeBtn = detail.querySelector(".node-portrait-btn");
    if (nodeBtn) {
        const name = nodeBtn.dataset.charName;
        const sIdx = parseInt(nodeBtn.dataset.stageIndex, 10);
        const hasPortrait = !!(graphData.character_images && graphData.character_images[name]);
        nodeBtn.onclick = async () => {
            const ok = await generatePortraitFromNode(name, sIdx, nodeBtn, hasPortrait);
        };
    }
}

async function generatePortraitFromNode(characterName, stageIndex, btn, force) {
    const novelId = (typeof appState !== "undefined" && appState.currentNovelId) || (typeof getSelectedNovelId === "function" && getSelectedNovelId());
    if (!novelId) {
        alert("未找到当前小说，无法生成");
        return false;
    }
    const stage = graphData && graphData.stages ? graphData.stages[stageIndex] : null;
    const char = stage && stage.characters ? stage.characters.find(c => c.name === characterName) : null;
    if (!char) return false;

    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = force ? "重新生成中... 请稍候" : "生成中... 请稍候";
    try {
        const result = await apiPost(`/api/novels/${novelId}/knowledge/character-image`, {
            stage_index: stageIndex,
            character_name: characterName,
            description: char.description || "",
            role: char.role || "",
            force: !!force,
        });
        const url = result.image_url || "";
        char.image_url = url;
        if (graphData.character_images) graphData.character_images[characterName] = url;
        const node = (graphData.nodes || []).find(n => n.type === "character" && n.name === characterName);
        showNodeDetail(node || { type: "character", name: characterName, role: char.role, description: char.description });
        if (currentView === "graph" && graphSimulation) {
            graphSimulation.stop();
            graphSimulation = null;
            renderGraph(graphData);
        }
        return true;
    } catch (e) {
        btn.disabled = false;
        btn.textContent = original;
        alert("生成失败：" + (e.message || "请稍后重试"));
        return false;
    }
}

function showCharacterInGraph(name, role, description) {
    if (!graphData) return;
    const node = (graphData.nodes || []).find(n => n.name === name && n.type === "character");
    if (node) showNodeDetail(node);
}

function showRegionDetail(region) {
    const detail = document.getElementById("graph-detail");
    if (!detail || !region) return;
    const color = CATEGORY_COLORS[region.category] || "#95a5a6";
    let html = `<div class="graph-detail-header" style="border-bottom:2px solid ${color};">` +
        `<strong>${escapeHtml(region.name)}</strong>` +
        `<button class="btn btn-sm btn-outline" onclick="document.getElementById('graph-detail').style.display='none'" style="margin-left:auto;padding:2px 8px;font-size:11px;">✕</button></div>`;
    html += `<div style="margin-bottom:8px;"><span class="character-role-badge" style="background:${color}22;color:${color};">${escapeHtml(region.category || "其他")}</span></div>`;
    if (region.importance) {
        html += `<div style="color:var(--text-muted);font-size:11px;margin-bottom:8px;text-transform:capitalize;">重要度 · ${escapeHtml(String(region.importance))}</div>`;
    }
    if (region.description) {
        html += `<div class="detail-desc" style="border-left:3px solid ${color};">${escapeHtml(region.description)}</div>`;
    }
    const chars = region.characters || [];
    if (chars.length > 0) {
        html += `<div class="detail-section"><div class="detail-section-title">👥 关联角色 (${chars.length})</div>`;
        chars.forEach(name => {
            html += `<div class="detail-rel-row region-char-link" style="border-left:2px solid ${color};" data-char-name="${escapeHtml(name)}">` +
                `<span style="color:var(--text-primary);font-size:12px;">👤 ${escapeHtml(name)}</span>` +
                `</div>`;
        });
        html += `</div>`;
    }
    html += `<div class="detail-section"><div class="detail-section-title">🖼️ 区域插画</div>` +
        `<div class="region-illustration" id="region-illustration"></div></div>`;
    detail.innerHTML = html;
    detail.style.display = "block";
    renderRegionIllustration(region);
    detail.querySelectorAll(".region-char-link").forEach(el => {
        el.onclick = () => {
            const n = el.dataset.charName;
            const node = (graphData.nodes || []).find(x => x.name === n && x.type === "character");
            if (node) showNodeDetail(node);
        };
    });
}

function renderRegionIllustration(region) {
    const box = document.getElementById("region-illustration");
    if (!box || !region) return;
    const url = graphData && graphData.images && graphData.images.regions ? graphData.images.regions[region.name] : null;
    const prompt = graphData && graphData.images && graphData.images.region_prompts ? graphData.images.region_prompts[region.name] : null;
    if (url) {
        box.innerHTML = `<img src="${escapeHtml(url)}" alt="${escapeHtml(region.name)} 区域插画">` +
            `<button type="button" class="btn btn-sm btn-outline" id="region-gen-btn" style="margin-top:8px;">🔄 重新生成插画</button>` +
            (prompt ? `<details class="prompt-details"><summary>查看生成提示词</summary><div class="prompt-text">${escapeHtml(prompt)}</div></details>` : "") +
            `<div class="region-illustration-error"></div>`;
        const btn = document.getElementById("region-gen-btn");
        if (btn) btn.onclick = () => generateRegionIllustration(region, true);
        return;
    }
    box.innerHTML = `<button type="button" class="btn btn-sm btn-primary" id="region-gen-btn">🎨 生成区域插画</button>` +
        `<div class="region-illustration-error"></div>`;
    const btn = document.getElementById("region-gen-btn");
    if (btn) btn.onclick = () => generateRegionIllustration(region, false);
}

async function generateRegionIllustration(region, force) {
    const novelId = (typeof appState !== "undefined" && appState.currentNovelId) || (typeof getSelectedNovelId === "function" && getSelectedNovelId());
    if (!novelId) {
        alert("未找到当前小说，无法生成");
        return;
    }
    const btn = document.getElementById("region-gen-btn");
    const errBox = document.querySelector(".region-illustration-error");
    const originalText = btn ? btn.textContent : "";
    if (btn) {
        btn.disabled = true;
        btn.textContent = force ? "重新生成中…" : "生成中…";
    }
    try {
        const result = await apiPost(`/api/novels/${novelId}/knowledge/region-image`, {
            region_name: region.name,
            description: region.description || "",
            force: !!force
        });
        if (graphData) {
            if (!graphData.images) graphData.images = {};
            if (!graphData.images.regions) graphData.images.regions = {};
            graphData.images.regions[region.name] = result.image_url || null;
            if (!graphData.images.region_prompts) graphData.images.region_prompts = {};
            graphData.images.region_prompts[region.name] = result.prompt || null;
        }
        renderRegionIllustration(region);
    } catch (e) {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText || "🎨 生成区域插画";
        }
        if (errBox) errBox.textContent = `生成失败：${e.message || "请稍后重试"}`;
    }
}

async function generateWorldMapImage(btn, force) {
    const novelId = (typeof appState !== "undefined" && appState.currentNovelId) || (typeof getSelectedNovelId === "function" && getSelectedNovelId());
    if (!novelId) {
        alert("未找到当前小说，无法生成");
        return;
    }
    const errBox = document.querySelector(".map-generate-error");
    const originalText = btn ? btn.textContent : "";
    if (btn) {
        btn.disabled = true;
        btn.textContent = force ? "重新生成中…" : "生成中…";
    }
    try {
        const result = await apiPost(`/api/novels/${novelId}/knowledge/world-image`, { force: !!force });
        if (graphData) {
            if (!graphData.images) graphData.images = {};
            graphData.images.world_map = result.image_url || null;
            graphData.images.world_map_prompt = result.prompt || null;
        }
        worldMapMode = "illustration";
        renderWorldMap(graphData);
    } catch (e) {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText || "生成插画";
        }
        if (errBox) errBox.textContent = `生成失败：${e.message || "请稍后重试"}`;
    }
}

function renderWorldMap(data) {
    setActiveViewButton("map");
    const body = document.getElementById("graph-body");
    body.innerHTML = "";
    const detail = document.getElementById("graph-detail");
    if (detail) detail.style.display = "none";

    const regions = data.regions || [];
    if (regions.length === 0) {
        body.innerHTML = '<div class="graph-empty">暂无世界观数据</div>';
        return;
    }
    if (!data.images) data.images = {};
    if (!data.images.regions) data.images.regions = {};
    if (!worldMapMode) worldMapMode = data.images.world_map ? "illustration" : "schematic";

    const modeSwitch = document.createElement("div");
    modeSwitch.className = "map-mode-switch";
    modeSwitch.innerHTML =
        `<button type="button" data-mode="illustration"${worldMapMode === "illustration" ? ' class="active"' : ""}>插画模式</button>` +
        `<button type="button" data-mode="schematic"${worldMapMode === "schematic" ? ' class="active"' : ""}>示意模式</button>`;
    modeSwitch.querySelectorAll("button[data-mode]").forEach(b => {
        b.onclick = () => {
            if (worldMapMode === b.dataset.mode) return;
            worldMapMode = b.dataset.mode;
            renderWorldMap(graphData);
        };
    });
    if (data.images.world_map) {
        const regenBtn = document.createElement("button");
        regenBtn.type = "button";
        regenBtn.className = "map-regen-btn";
        regenBtn.textContent = "🔄 重新生成插画";
        regenBtn.title = "依据当前世界观设定重新生成地图插画";
        regenBtn.onclick = () => generateWorldMapImage(regenBtn, true);
        modeSwitch.appendChild(regenBtn);
        if (worldMapMode === "illustration" && data.images.world_map_prompt) {
            const promptBtn = document.createElement("button");
            promptBtn.type = "button";
            promptBtn.className = "map-regen-btn";
            promptBtn.textContent = "📜 提示词";
            promptBtn.title = "查看本次插画实际使用的生成提示词";
            promptBtn.onclick = () => {
                const panel = document.getElementById("map-prompt-panel");
                if (panel) panel.style.display = panel.style.display === "none" ? "block" : "none";
            };
            modeSwitch.appendChild(promptBtn);
        }
    }
    body.appendChild(modeSwitch);

    const wrap = document.createElement("div");
    wrap.className = "world-map-wrap";
    body.appendChild(wrap);

    const width = body.clientWidth || 800;
    const height = body.clientHeight || 600;
    const centerX = width / 2;
    const centerY = height / 2 + 30;

    const worldCategories = {};
    (data.nodes || []).forEach(n => {
        if (n.type === "world") worldCategories[n.name] = n.category;
    });

    const regionsData = regions.map((region, i) => {
        const angle = (i / regions.length) * 2 * Math.PI - Math.PI / 2;
        const radius = Math.min(width, height) * 0.32;
        const category = region.category || worldCategories[region.name] || "地点";
        const style = WORLD_CATEGORY_STYLES[classifyWorldCategory(category)];
        const baseRadius = Math.max(16, Math.min(26, 15 + (region.characters || []).length));
        return {
            ...region,
            category,
            style,
            baseRadius,
            x: centerX + radius * Math.cos(angle) * (0.85 + Math.random() * 0.3),
            y: centerY + radius * Math.sin(angle) * (0.85 + Math.random() * 0.3)
        };
    });

    if (worldMapMode === "illustration" && !data.images.world_map) {
        wrap.innerHTML =
            `<div class="map-generate-card">` +
                `<div class="map-generate-icon">🗺️</div>` +
                `<div class="map-generate-title">生成世界地图插画</div>` +
                `<div class="map-generate-desc">依据小说世界观设定生成一张艺术风地图插画</div>` +
                `<button type="button" class="btn btn-primary" id="world-map-gen-btn">生成插画</button>` +
                `<div class="map-generate-error"></div>` +
            `</div>`;
        const genBtn = document.getElementById("world-map-gen-btn");
        if (genBtn) genBtn.onclick = () => generateWorldMapImage(genBtn);
        return;
    }

    if (worldMapMode === "illustration") {
        const bg = document.createElement("img");
        bg.className = "world-map-bg";
        bg.src = data.images.world_map;
        bg.alt = "世界地图插画";
        wrap.appendChild(bg);

        if (data.images.world_map_prompt) {
            const panel = document.createElement("div");
            panel.className = "map-prompt-panel";
            panel.id = "map-prompt-panel";
            panel.style.display = "none";
            panel.innerHTML = '<div class="map-prompt-title">本次插画生成提示词（存于生成时刻）</div>' +
                '<div class="map-prompt-text">' + escapeHtml(data.images.world_map_prompt) + '</div>';
            wrap.appendChild(panel);
        }
    }

    graphSvg = d3.select(wrap).append("svg")
        .attr("width", width).attr("height", height).attr("class", "world-map-svg");

    if (worldMapMode === "schematic") {
        const defs = graphSvg.append("defs");
        const bgGrad = defs.append("radialGradient").attr("id", "map-bg-grad")
            .attr("cx", "50%").attr("cy", "50%").attr("r", "70%");
        bgGrad.append("stop").attr("offset", "0%").attr("stop-color", "#0e1a2e");
        bgGrad.append("stop").attr("offset", "100%").attr("stop-color", "#06090f");
        graphSvg.append("rect").attr("width", width).attr("height", height).attr("fill", "url(#map-bg-grad)");

        const glow = defs.append("filter").attr("id", "map-region-glow").attr("x", "-50%").attr("y", "-50%").attr("width", "200%").attr("height", "200%");
        glow.append("feGaussianBlur").attr("stdDeviation", "4").attr("result", "blur");
        const merge = glow.append("feMerge");
        merge.append("feMergeNode").attr("in", "blur");
        merge.append("feMergeNode").attr("in", "SourceGraphic");

        for (let i = 0; i < 120; i++) {
            graphSvg.append("circle")
                .attr("cx", Math.random() * width).attr("cy", Math.random() * height)
                .attr("r", Math.random() * 1.3 + 0.3)
                .attr("fill", "#fff").attr("opacity", Math.random() * 0.5 + 0.1);
        }

        graphSvg.append("text").attr("x", width / 2).attr("y", 38).attr("text-anchor", "middle")
            .attr("fill", "var(--text-secondary)").attr("font-size", "16px").attr("font-weight", "600")
            .attr("letter-spacing", "3px").text("世界观地图 · " + escapeHtml(data.novel_title || ""));
        graphSvg.append("text").attr("x", width / 2).attr("y", 58).attr("text-anchor", "middle")
            .attr("fill", "var(--text-muted)").attr("font-size", "10px").attr("letter-spacing", "1px")
            .text(`共 ${regions.length} 个区域`);

        const idName = (id, prefix) => {
            const s = typeof id === "object" && id !== null ? id.id : id;
            return typeof s === "string" && s.startsWith(prefix) ? s.slice(prefix.length) : null;
        };
        const regionChars = new Map(regionsData.map(r => [r.name, new Set()]));
        (data.links || []).forEach(l => {
            if (l.type !== "related") return;
            const src = typeof l.source === "object" && l.source !== null ? l.source.id : l.source;
            const tgt = typeof l.target === "object" && l.target !== null ? l.target.id : l.target;
            const charName = idName(src, "char_") || idName(tgt, "char_");
            const worldName = idName(src, "world_") || idName(tgt, "world_");
            if (!charName || !worldName) return;
            const set = regionChars.get(worldName);
            if (set) set.add(charName);
        });
        const linkGroup = graphSvg.append("g");
        for (let i = 0; i < regionsData.length; i++) {
            for (let j = i + 1; j < regionsData.length; j++) {
                const a = regionsData[i];
                const b = regionsData[j];
                let shared = 0;
                regionChars.get(a.name).forEach(c => { if (regionChars.get(b.name).has(c)) shared++; });
                if (!shared) continue;
                linkGroup.append("line")
                    .attr("x1", a.x).attr("y1", a.y)
                    .attr("x2", b.x).attr("y2", b.y)
                    .attr("stroke", "#64748b")
                    .attr("stroke-width", Math.min(1.5 + shared * 0.8, 4))
                    .attr("stroke-opacity", 0.5);
            }
        }

        const regionGroup = graphSvg.append("g").attr("class", "map-regions");
        const regionElements = regionGroup.selectAll("g").data(regionsData).enter().append("g")
            .attr("transform", d => `translate(${d.x},${d.y})`)
            .style("cursor", "pointer")
            .on("mouseenter", function () {
                d3.select(this).transition().duration(150)
                    .attr("transform", d => `translate(${d.x},${d.y}) scale(1.08)`);
            })
            .on("mouseleave", function () {
                d3.select(this).transition().duration(150)
                    .attr("transform", d => `translate(${d.x},${d.y}) scale(1)`);
            })
            .on("click", function (event, d) { event.stopPropagation(); showRegionDetail(d); });

        regionElements.append("path")
            .attr("d", d => buildRegionBlobPath(d.name, d.baseRadius))
            .attr("fill", d => d.style.color)
            .attr("fill-opacity", 0.3)
            .attr("stroke", d => d.style.color)
            .attr("stroke-width", 1.5)
            .attr("stroke-opacity", 0.7)
            .style("opacity", 0)
            .transition().duration(600).delay((d, i) => i * 60).style("opacity", 1);

        regionElements.append("circle").attr("r", 3)
            .attr("fill", "rgba(255,255,255,0.85)").attr("opacity", 0)
            .transition().duration(500).delay((d, i) => i * 60 + 100).attr("opacity", 1);

        regionElements.append("text")
            .attr("x", d => -d.baseRadius * 1.1)
            .attr("y", d => -d.baseRadius * 1.1)
            .attr("text-anchor", "middle")
            .attr("dominant-baseline", "middle")
            .attr("font-size", "16px")
            .style("opacity", 0)
            .text(d => d.style.emoji)
            .transition().duration(400).delay((d, i) => i * 60 + 150).style("opacity", 1);

        regionElements.each(function (d) {
            const g = d3.select(this);
            const label = d.name.length > 8 ? d.name.substring(0, 8) + "…" : d.name;
            const w = label.length * 11 + 14;
            const by = d.baseRadius * 1.8 + 12;
            g.append("rect")
                .attr("x", -w / 2).attr("y", by).attr("width", w).attr("height", 17).attr("rx", 8)
                .attr("fill", "rgba(255,255,255,0.92)")
                .style("opacity", 0)
                .transition().duration(400).delay((d2, i) => i * 60 + 200).style("opacity", 1);
            g.append("text")
                .attr("x", 0).attr("y", by + 12.5)
                .attr("text-anchor", "middle")
                .attr("fill", "#1f2937").attr("font-size", "11px").attr("font-weight", "600")
                .style("opacity", 0)
                .text(label)
                .transition().duration(400).delay((d2, i) => i * 60 + 200).style("opacity", 1);
            g.append("text")
                .attr("x", 0).attr("y", by + 32)
                .attr("text-anchor", "middle")
                .attr("fill", "var(--text-muted)").attr("font-size", "9px")
                .style("opacity", 0)
                .text(`${(d.characters || []).length} 角色`)
                .transition().duration(400).delay((d2, i) => i * 60 + 280).style("opacity", 1);
        });

        graphSvg.append("text").attr("x", 20).attr("y", height - 20)
            .attr("fill", "var(--text-muted)").attr("font-size", "10px").attr("opacity", 0.6)
            .text("点击区域查看详情");
    } else {
        const hotspotGroup = graphSvg.append("g");
        const hotspots = hotspotGroup.selectAll("g").data(regionsData).enter().append("g")
            .attr("transform", d => `translate(${d.x},${d.y})`);

        hotspots.append("circle")
            .attr("class", "map-hotzone")
            .attr("r", d => Math.max(20, d.baseRadius + 6))
            .each(function (d) { d3.select(this).append("title").text(d.name); })
            .on("click", function (event, d) { event.stopPropagation(); showRegionDetail(d); });

        hotspots.append("circle")
            .attr("r", 3)
            .attr("fill", "rgba(255,255,255,0.9)")
            .style("pointer-events", "none");

        hotspots.append("text")
            .attr("y", d => Math.max(20, d.baseRadius + 6) + 14)
            .attr("text-anchor", "middle")
            .attr("fill", "#fff").attr("font-size", "10px").attr("font-weight", "600")
            .attr("paint-order", "stroke")
            .attr("stroke", "rgba(0,0,0,0.7)").attr("stroke-width", "2.5px")
            .style("pointer-events", "none")
            .text(d => d.name.length > 8 ? d.name.substring(0, 8) + "…" : d.name);

        graphSvg.append("text").attr("x", 20).attr("y", height - 20)
            .attr("fill", "rgba(255,255,255,0.65)").attr("font-size", "10px")
            .style("pointer-events", "none")
            .text("点击高亮热区查看区域详情");
    }
}
