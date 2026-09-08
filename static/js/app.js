const appState = {
    novels: [],
    currentNovelId: null,
    currentChapter: null,
};

function getSelectedNovelId() {
    const select = document.getElementById("novel-select");
    return parseInt(select.value) || null;
}

function setWritingStatus(type, text) {
    const dot = document.querySelector(".status-dot");
    const textEl = document.getElementById("status-text");
    dot.className = `status-dot ${type}`;
    textEl.textContent = text;
}

function updateStatusBar(text, detail = "") {
    document.getElementById("status-bar-text").textContent = text;
    document.getElementById("status-bar-detail").textContent = detail;
}

function showModal() {
    document.getElementById("modal-overlay").style.display = "flex";
}

function closeModal() {
    document.getElementById("modal-overlay").style.display = "none";
}

document.getElementById("modal-overlay").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeModal();
});

function showCreateNovelModal() {
    const modal = document.getElementById("modal-content");
    modal.innerHTML = `
        <h2>创建新小说</h2>
        <div class="form-group">
            <label>小说标题 *</label>
            <input type="text" id="create-novel-title" placeholder="输入小说标题">
        </div>
        <div class="form-group">
            <label>小说类型</label>
            <select id="create-novel-genre">
                <option value="玄幻">玄幻</option>
                <option value="都市">都市</option>
                <option value="科幻">科幻</option>
                <option value="历史">历史</option>
                <option value="武侠">武侠</option>
                <option value="言情">言情</option>
                <option value="悬疑">悬疑</option>
                <option value="恐怖">恐怖</option>
                <option value="其他">其他</option>
            </select>
        </div>
        <div class="form-group">
            <label>篇幅类型</label>
            <div class="length-type-selector">
                <label class="length-option">
                    <input type="radio" name="length-type" value="long">
                    <span class="length-option-card">
                        <strong>长篇</strong>
                        <small>80万字以上，约200-300章</small>
                    </span>
                </label>
                <label class="length-option">
                    <input type="radio" name="length-type" value="short" checked>
                    <span class="length-option-card">
                        <strong>短篇</strong>
                        <small>20万字左右，约50-70章</small>
                    </span>
                </label>
            </div>
        </div>
        <div class="form-group">
            <label>小说简介</label>
            <textarea id="create-novel-description" placeholder="描述你想要写的小说..."></textarea>
        </div>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">取消</button>
            <button class="btn btn-primary" onclick="createNovel()">创建</button>
        </div>
    `;
    showModal();
}

async function createNovel() {
    const title = document.getElementById("create-novel-title").value.trim();
    if (!title) { alert("请输入小说标题"); return; }

    const genre = document.getElementById("create-novel-genre").value;
    const description = document.getElementById("create-novel-description").value.trim();
    const lengthType = document.querySelector('input[name="length-type"]:checked').value;
    const targetWordCount = lengthType === "long" ? 800000 : 200000;

    try {
        const novel = await apiPost("/api/novels", { title, genre, description, length_type: lengthType, target_word_count: targetWordCount });
        closeModal();
        await loadNovelList();
        document.getElementById("novel-select").value = novel.id;
        appState.currentNovelId = novel.id;
        await onNovelSelected(novel.id);
        updateStatusBar("小说创建成功");
    } catch (e) {
        alert("创建失败: " + e.message);
    }
}

async function loadNovelList() {
    try {
        const novels = await apiGet("/api/novels");
        appState.novels = novels;
        const select = document.getElementById("novel-select");
        select.innerHTML = '<option value="">选择小说...</option>';
        novels.forEach(n => {
            const option = document.createElement("option");
            option.value = n.id;
            const lengthTag = (n.target_word_count >= 500000 || n.length_type === "long") ? "长篇" : "短篇";
            option.textContent = `${n.title} (${lengthTag}, ${n.chapter_count}章) [${getStatusText(n.status)}]`;
            select.appendChild(option);
        });
    } catch (e) {
        console.error("加载小说列表失败:", e);
    }
}

function getStatusText(status) {
    const map = { planning: "规划中", writing: "写作中", completed: "已完成" };
    return map[status] || status;
}

async function onNovelSelected(novelId) {
    if (!novelId) {
        document.getElementById("btn-delete-novel").style.display = "none";
        return;
    }
    appState.currentNovelId = novelId;
    appState.currentChapter = null;

    document.getElementById("btn-delete-novel").style.display = "";

    await loadNovelInfo(novelId);
    await loadOutline(novelId);
    await loadChapterList(novelId);
    await loadRagData(novelId);

    document.getElementById("welcome-screen").style.display = "flex";
    document.getElementById("chapter-text").style.display = "none";
    document.getElementById("chapter-header").style.display = "none";
    document.getElementById("review-panel").style.display = "none";
    hideChapterProgress();

    const novel = appState.novels.find(n => n.id === novelId);
    if (novel && novel.status !== "planning") {
        document.getElementById("btn-start-writing").disabled = false;
    } else {
        document.getElementById("btn-start-writing").disabled = false;
    }
}

async function deleteNovel() {
    const novelId = appState.currentNovelId;
    if (!novelId) {
        alert("请先选择要删除的小说");
        return;
    }
    const novel = appState.novels.find(n => n.id === novelId);
    const title = novel ? novel.title : "";
    if (!confirm(`确定删除小说《${title}》吗？\n所有章节、大纲、知识库关联将被永久删除，此操作不可撤销。`)) {
        return;
    }
    try {
        await apiDelete(`/api/novels/${novelId}`);
        appState.currentNovelId = null;
        appState.currentChapter = null;
        document.getElementById("btn-delete-novel").style.display = "none";
        document.getElementById("novel-select").value = "";
        await loadNovelList();
        updateStatusBar("小说已删除");
        location.reload();
    } catch (e) {
        alert("删除失败: " + e.message);
    }
}

async function loadNovelInfo(novelId) {
    try {
        const novel = await apiGet(`/api/novels/${novelId}`);
        const existing = appState.novels.find(n => n.id === novelId);
        if (existing) {
            Object.assign(existing, novel);
        } else {
            appState.novels.push(novel);
        }

        outlineConfirmed = novel.status !== "planning";

        const fullOutlinePanel = document.getElementById("full-outline-panel");
        if (novel.full_outline && novel.full_outline.volumes && novel.full_outline.volumes.length > 0) {
            if (typeof fullOutlineConfirmed !== 'undefined') {
                fullOutlineConfirmed = novel.status !== "planning";
            }
            if (typeof currentFullOutline !== 'undefined') {
                currentFullOutline = novel.full_outline;
            }
            if (typeof renderFullOutline === 'function') {
                renderFullOutline(novel.full_outline);
            }
        } else {
            if (typeof fullOutlineConfirmed !== 'undefined') {
                fullOutlineConfirmed = false;
            }
            document.getElementById("full-outline-container").innerHTML = '<div class="outline-empty">请生成全文大纲</div>';
        }

        if (novel.status === "planning") {
            document.getElementById("btn-confirm-outline").style.display = "inline-flex";
        } else {
            document.getElementById("btn-confirm-outline").style.display = "none";
        }

        updateBatchButton(novel);
    } catch (e) {
        console.error("加载小说信息失败:", e);
    }
}

function updateBatchButton(novel) {
    const btn = document.getElementById("btn-next-batch");
    const btnWrite = document.getElementById("btn-start-writing");

    if (!novel || novel.status !== "writing") {
        btn.style.display = "none";
        return;
    }

    const outline = novel.outline || [];
    const maxOutlineChapter = outline.length > 0 ? Math.max(...outline.map(o => o.chapter_number)) : 0;

    const chaptersWritten = novel.chapter_count || 0;

    if (chaptersWritten >= maxOutlineChapter && maxOutlineChapter > 0) {
        btn.style.display = "inline-flex";
        btnWrite.style.display = "none";
    } else {
        btn.style.display = "none";
        btnWrite.style.display = "inline-flex";
    }
}

function renderFullOutline(fullOutline) {
    const container = document.getElementById("full-outline-container");
    const confirmBtn = document.getElementById("btn-confirm-full-outline");
    if (!fullOutline || !fullOutline.volumes || fullOutline.volumes.length === 0) {
        container.innerHTML = '<div class="outline-empty">请生成全文大纲</div>';
        if (confirmBtn) confirmBtn.style.display = "none";
        return;
    }

    let html = `<div class="full-outline-info">
        <div class="full-outline-theme">主题：${escapeHtml(fullOutline.theme || '')}</div>
        <div class="full-outline-conflict">核心冲突：${escapeHtml(fullOutline.core_conflict || '')}</div>
        <div class="full-outline-total">预计总章节数：${fullOutline.total_chapters || '未定'}</div>
    </div>`;

    const foreshadowing = fullOutline.foreshadowing || [];
    if (foreshadowing.length) {
        const fsRows = foreshadowing.map(f => {
            const payoff = f.payoff_in_volume ? `第${f.payoff_in_volume}卷` : '未回收';
            return `<div class="fs-row"><span class="fs-id">${escapeHtml(f.id || '')}</span><span class="fs-desc">${escapeHtml(f.description || '')}</span><span class="fs-meta">埋于第${f.planted_in_volume || '?'}卷 · ${payoff} · ${escapeHtml(f.status || '')}</span></div>`;
        }).join('');
        html += `<div class="full-outline-foreshadowing"><div class="fs-title">伏笔总览</div>${fsRows}</div>`;
    }

    fullOutline.volumes.forEach(vol => {
        const dynamics = (vol.character_dynamics || []).map(d =>
            `<div class="dyn-item"><strong>${escapeHtml(d.character || '')}</strong>：情感[${escapeHtml(d.emotion_state || '')}]，事件[${escapeHtml(d.key_event || '')}]，变化[${escapeHtml(d.emotion_change || '')}]</div>`
        ).join('');
        const abilities = (vol.protagonist_abilities || []).map(a =>
            `<div class="abi-item"><strong>${escapeHtml(a.ability || '')}</strong>（${escapeHtml(a.state || '')}）：${escapeHtml(a.change || '')}，触发[${escapeHtml(a.trigger_event || '')}]</div>`
        ).join('');
        const fsIds = (vol.foreshadowing_ids || []).join(', ');
        html += `
            <div class="volume-item">
                <div class="volume-header" onclick="this.parentElement.classList.toggle('collapsed')">
                    <span class="volume-number">第${vol.volume_number}卷</span>
                    <span class="volume-title">${escapeHtml(vol.title || '')}</span>
                    <span class="volume-range">第${vol.chapter_range ? vol.chapter_range[0] : '?'}-${vol.chapter_range ? vol.chapter_range[1] : '?'}章</span>
                    <span class="volume-toggle">▼</span>
                </div>
                <div class="volume-body">
                    <div class="volume-summary">${escapeHtml(vol.summary || '')}</div>
                    <div class="volume-meta">
                        <span>核心角色：${escapeHtml((vol.key_characters || []).join(', '))}</span>
                        <span>重大事件：${escapeHtml((vol.major_events || []).join(', '))}</span>
                        <span>基调：${escapeHtml(vol.tone || '')}</span>
                        ${(vol.source_volumes && vol.source_volumes.length) ? `<span class="volume-source">关联知识库卷：${escapeHtml(vol.source_volumes.join('、'))}</span>` : ''}
                    </div>
                    ${dynamics ? `<div class="volume-section"><div class="volume-section-title">角色情感动态</div>${dynamics}</div>` : ''}
                    ${abilities ? `<div class="volume-section"><div class="volume-section-title">主角能力进阶</div>${abilities}</div>` : ''}
                    ${fsIds ? `<div class="volume-section"><div class="volume-section-title">本卷伏笔</div>${fsIds}</div>` : ''}
                </div>
            </div>
        `;
    });

    if (typeof fullOutlineConfirmed !== 'undefined' && !fullOutlineConfirmed) {
        if (confirmBtn) confirmBtn.style.display = "inline-flex";
        html += `<div class="full-outline-actions">
            <span class="badge" style="background:var(--warning);color:#fff;">未确认</span>
            <button class="btn btn-sm btn-outline" onclick="editFullOutlineModal()">编辑</button>
            <button class="btn btn-sm btn-outline" onclick="aiReviseFullOutline()">AI修改</button>
        </div>`;
    } else if (typeof fullOutlineConfirmed !== 'undefined') {
        if (confirmBtn) confirmBtn.style.display = "none";
        html += `<div class="full-outline-actions">
            <span class="badge" style="background:var(--success);color:#fff;">已确认</span>
            <button class="btn btn-sm btn-outline" onclick="editFullOutlineModal()">编辑</button>
            <button class="btn btn-sm btn-outline" onclick="aiReviseFullOutline()">AI修改</button>
        </div>`;
    }

    container.innerHTML = html;
}

async function generateNextBatch() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    const novel = appState.novels.find(n => n.id === novelId);
    const outline = novel ? novel.outline || [] : [];
    const maxOutlineChapter = outline.length > 0 ? Math.max(...outline.map(o => o.chapter_number)) : 0;
    const startChapter = maxOutlineChapter + 1;

    const fullOutline = novel ? novel.full_outline || {} : {};
    const totalChapters = fullOutline.total_chapters || 0;

    if (totalChapters > 0 && startChapter > totalChapters) {
        alert("已达到预计总章节数，无需继续生成");
        return;
    }

    setWritingStatus("writing", "正在生成后续章节大纲...");
    updateStatusBar("AI正在生成第" + startChapter + "章开始的详细大纲...");

    const container = document.getElementById("outline-container");
    container.innerHTML += '<div class="outline-empty" id="outline-stream-text" style="text-align:left;white-space:pre-wrap;font-size:12px;color:var(--text-secondary);max-height:300px;overflow-y:auto;"></div>';

    const streamText = document.getElementById("outline-stream-text");
    let fullText = "";

    try {
        const response = await fetch(`/api/novels/${novelId}/outline/generate-chapters`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ batch_size: 10, start_chapter: startChapter }),
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
                        fullText += data.text;
                        streamText.textContent += data.text;
                        streamText.scrollTop = streamText.scrollHeight;
                    } else if (data.type === "complete") {
                        const outline = data.data && data.data.outline ? data.data.outline : null;
                        if (outline && outline.length > 0) {
                            currentOutline = outline;
                        }
                        outlineConfirmed = false;
                        renderOutline();
                        setWritingStatus("done", "后续章节大纲已生成");
                        updateStatusBar("后续章节大纲生成完成，请查看并编辑");
                    } else if (data.type === "error") {
                        throw new Error(data.error || "生成失败");
                    }
                } catch (e) {
                    if (e.message && !e.message.includes("JSON")) throw e;
                }
            }
        }
    } catch (error) {
        setWritingStatus("done", "生成失败");
        alert("生成后续章节大纲失败: " + error.message);
    }

    await loadNovelInfo(novelId);
}

document.getElementById("novel-select").addEventListener("change", (e) => {
    const novelId = parseInt(e.target.value);
    if (novelId) {
        onNovelSelected(novelId);
    }
});

document.getElementById("chapter-select").addEventListener("change", async (e) => {
    const chapterNum = parseInt(e.target.value);
    if (!chapterNum) return;
    const prevChapter = appState.currentChapter;
    const success = await loadChapter(chapterNum);
    if (!success) {
        e.target.value = prevChapter || "";
        return;
    }
    e.target.value = appState.currentChapter;
    renderOutline();
});

let currentRagTab = "preferences";

function switchRagTab(tab) {
    currentRagTab = tab;
    document.querySelectorAll(".rag-tab").forEach(t => t.classList.remove("active"));
    event.target.classList.add("active");
    loadRagData(getSelectedNovelId());
}

async function loadRagData(novelId) {
    if (!novelId) return;
    const container = document.getElementById("rag-content");

    try {
        if (currentRagTab === "preferences") {
            const prefs = await apiGet(`/api/novels/${novelId}/rag/preferences`);
            if (prefs.length === 0) {
                container.innerHTML = '<div class="rag-empty">暂无偏好数据，点击添加</div>';
                return;
            }
            container.innerHTML = prefs.map(p => `
                <div class="rag-item">
                    <span class="rag-item-type ${escapeHtml(p.preference_type)}">${escapeHtml(p.preference_type)}</span>
                    <span class="rag-item-text">${escapeHtml(p.preference_key)}: ${escapeHtml(p.preference_value)}</span>
                    <span class="rag-item-delete" onclick="deletePreference(${p.id})">×</span>
                </div>
            `).join("");
        } else {
            const knowledge = await apiGet(`/api/novels/${novelId}/rag/knowledge`);
            if (knowledge.length === 0) {
                container.innerHTML = '<div class="rag-empty">暂无世界观数据，点击添加</div>';
                return;
            }
            container.innerHTML = knowledge.map(k => `
                <div class="rag-item">
                    <span class="rag-item-type world">${escapeHtml(k.category)}</span>
                    <span class="rag-item-text">${escapeHtml(k.name)}: ${escapeHtml(k.content)}</span>
                </div>
            `).join("");
        }
    } catch (e) {
        container.innerHTML = '<div class="rag-empty">加载失败</div>';
    }
}

function showAddKnowledgeModal() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    const modal = document.getElementById("modal-content");
    if (currentRagTab === "preferences") {
        modal.innerHTML = `
            <h2>添加用户偏好</h2>
            <div class="form-group">
                <label>偏好类型</label>
                <select id="pref-type">
                    <option value="style">写作风格</option>
                    <option value="plot">情节偏好</option>
                    <option value="character">人物偏好</option>
                    <option value="pacing">节奏偏好</option>
                </select>
            </div>
            <div class="form-group">
                <label>偏好名称</label>
                <input type="text" id="pref-key" placeholder="如：对话风格">
            </div>
            <div class="form-group">
                <label>偏好内容</label>
                <textarea id="pref-value" placeholder="描述你的偏好..."></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn btn-outline" onclick="closeModal()">取消</button>
                <button class="btn btn-primary" onclick="addPreference()">添加</button>
            </div>
        `;
    } else {
        modal.innerHTML = `
            <h2>添加世界观知识</h2>
            <div class="form-group">
                <label>类别</label>
                <select id="knowledge-category">
                    <option value="setting">世界设定</option>
                    <option value="power_system">力量体系</option>
                    <option value="character">人物设定</option>
                    <option value="location">地点设定</option>
                    <option value="history">历史背景</option>
                    <option value="rule">规则法则</option>
                </select>
            </div>
            <div class="form-group">
                <label>名称</label>
                <input type="text" id="knowledge-name" placeholder="如：修炼体系">
            </div>
            <div class="form-group">
                <label>内容</label>
                <textarea id="knowledge-content" placeholder="详细描述..."></textarea>
            </div>
            <div class="form-group">
                <label>关联人物（每行一个）</label>
                <textarea id="knowledge-characters" placeholder="可选"></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn btn-outline" onclick="closeModal()">取消</button>
                <button class="btn btn-primary" onclick="addKnowledge()">添加</button>
            </div>
        `;
    }
    showModal();
}

async function addPreference() {
    const novelId = getSelectedNovelId();
    if (!novelId) return;

    const type = document.getElementById("pref-type").value;
    const key = document.getElementById("pref-key").value.trim();
    const value = document.getElementById("pref-value").value.trim();

    if (!key || !value) { alert("请填写完整"); return; }

    try {
        await apiPost(`/api/novels/${novelId}/rag/preferences`, {
            preference_type: type,
            preference_key: key,
            preference_value: value,
        });
        closeModal();
        await loadRagData(novelId);
        updateStatusBar("偏好已添加");
    } catch (e) {
        alert("添加失败: " + e.message);
    }
}

async function addKnowledge() {
    const novelId = getSelectedNovelId();
    if (!novelId) return;

    const category = document.getElementById("knowledge-category").value;
    const name = document.getElementById("knowledge-name").value.trim();
    const content = document.getElementById("knowledge-content").value.trim();
    const characters = document.getElementById("knowledge-characters").value.split("\n").filter(s => s.trim());

    if (!name || !content) { alert("请填写完整"); return; }

    try {
        await apiPost(`/api/novels/${novelId}/rag/knowledge`, {
            category,
            name,
            content,
            related_characters: characters,
        });
        closeModal();
        await loadRagData(novelId);
        updateStatusBar("世界观知识已添加");
    } catch (e) {
        alert("添加失败: " + e.message);
    }
}

async function deletePreference(prefId) {
    const novelId = getSelectedNovelId();
    if (!novelId) return;
    if (!confirm("确定删除此偏好？")) return;

    try {
        await apiDelete(`/api/novels/${novelId}/rag/preferences/${prefId}`);
        await loadRagData(novelId);
    } catch (e) {
        alert("删除失败: " + e.message);
    }
}

function showImportDocumentModal() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    const modal = document.getElementById("modal-content");
    modal.innerHTML = `
        <h2>导入文档到知识库</h2>
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px;">上传文档后，AI会自动提取世界观设定、人物、情节元素等信息存入知识库</p>
        <div class="upload-area" id="upload-area" onclick="document.getElementById('file-input').click()"
             ondragover="event.preventDefault();this.classList.add('dragover')"
             ondragleave="this.classList.remove('dragover')"
             ondrop="event.preventDefault();this.classList.remove('dragover');handleFileDrop(event)">
            <div class="upload-icon">📄</div>
            <div class="upload-text">点击选择文件或拖拽文件到此处</div>
            <div class="upload-formats">支持格式：.txt .md .docx .pdf</div>
        </div>
        <input type="file" id="file-input" style="display:none" accept=".txt,.md,.docx,.pdf" onchange="handleFileSelect(event)">
        <div class="form-group">
            <label>文档类别</label>
            <select id="import-category">
                <option value="imported">通用导入</option>
                <option value="reference_work">参考作品</option>
                <option value="world_setting">世界设定资料</option>
                <option value="style_reference">风格参考</option>
                <option value="character_reference">人物参考</option>
            </select>
        </div>
        <div id="upload-progress" style="display:none;" class="upload-progress"></div>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">关闭</button>
        </div>
    `;
    showModal();
}

async function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) await uploadDocument(file);
}

async function handleFileDrop(event) {
    const file = event.dataTransfer.files[0];
    if (file) await uploadDocument(file);
}

async function uploadDocument(file) {
    const novelId = getSelectedNovelId();
    if (!novelId) return;

    const category = document.getElementById("import-category").value;
    const progressEl = document.getElementById("upload-progress");
    progressEl.style.display = "block";
    progressEl.innerHTML = `正在上传 <b>${file.name}</b> 并提取知识...<br><span style="color:var(--text-muted);font-size:11px;">这可能需要1-2分钟，请耐心等待</span>`;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("category", category);

    try {
        const response = await fetch(`/api/novels/${novelId}/rag/import-document`, {
            method: "POST",
            body: formData,
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: "上传失败" }));
            throw new Error(err.detail || "上传失败");
        }
        const result = await response.json();

        if (result.error) {
            progressEl.innerHTML = `<span style="color:var(--danger);">提取失败: ${escapeHtml(result.error)}</span>`;
        } else {
            let html = `<span style="color:var(--success);">导入成功！</span><br>`;
            html += `文件: ${escapeHtml(result.filename)}<br>`;
            html += `文本长度: ${result.text_length} 字<br>`;
            html += `导入条数: <span class="upload-result-count">${result.imported_count}</span> 条<br>`;
            html += `提取分类: ${result.extracted_categories.join(", ")}`;
            progressEl.innerHTML = html;
            await loadRagData(novelId);
        }
    } catch (e) {
        progressEl.innerHTML = `<span style="color:var(--danger);">导入失败: ${escapeHtml(e.message)}</span>`;
    }
}

let rewritePanelOpen = false;
let rewriteResults = ["", ""];
let rewriteLabels = ["", ""];

function showRewriteModal() {
    if (rewritePanelOpen) {
        closeRewritePanel();
        return;
    }

    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }
    if (!currentChapterContent) { alert("当前没有章节内容"); return; }
    if (!appState.currentChapter) { alert("请先选择一个章节"); return; }

    rewritePanelOpen = true;
    rewriteResults = ["", ""];
    rewriteLabels = ["", ""];

    const panel = document.createElement("div");
    panel.className = "rewrite-panel";
    panel.id = "rewrite-panel";
    panel.innerHTML = `
        <div class="rewrite-panel-header">
            <h3>AI重写助手</h3>
            <button class="btn btn-sm btn-outline" onclick="closeRewritePanel()">关闭</button>
        </div>
        <div class="rewrite-panel-body">
            <div class="form-group">
                <label>选中需要重写的内容</label>
                <textarea id="rewrite-original" rows="6" placeholder="在这里粘贴或输入需要重写的段落..." style="width:100%;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);padding:8px;font-size:13px;font-family:inherit;resize:vertical;"></textarea>
            </div>
            <div class="form-group">
                <label>修改方向</label>
                <textarea id="rewrite-instruction" rows="3" placeholder="如：换一种更紧张的氛围写这段 / 增加对话减少描写 / 用第一人称重写..." style="width:100%;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);padding:8px;font-size:13px;font-family:inherit;resize:vertical;"></textarea>
            </div>
            <button class="btn btn-primary" onclick="doRewrite()" id="btn-do-rewrite" style="width:100%;">开始重写</button>
            <div id="rewrite-result-area" style="display:none;margin-top:12px;">
                <div class="rewrite-versions">
                    <div class="rewrite-version-card" id="rewrite-version-0">
                        <div class="rewrite-version-label" id="rewrite-label-0">版本A</div>
                        <div class="rewrite-result" id="rewrite-result-0"></div>
                        <div class="rewrite-actions">
                            <button class="btn btn-success" onclick="acceptRewrite(0)">采纳</button>
                        </div>
                    </div>
                    <div class="rewrite-version-card" id="rewrite-version-1">
                        <div class="rewrite-version-label" id="rewrite-label-1">版本B</div>
                        <div class="rewrite-result" id="rewrite-result-1"></div>
                        <div class="rewrite-actions">
                            <button class="btn btn-success" onclick="acceptRewrite(1)">采纳</button>
                        </div>
                    </div>
                </div>
                <div style="display:flex;gap:8px;margin-top:8px;">
                    <button class="btn btn-outline" onclick="retryRewrite()">重新生成</button>
                    <button class="btn btn-danger" onclick="discardRewrite()">放弃</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(panel);
}

function closeRewritePanel() {
    rewritePanelOpen = false;
    const panel = document.getElementById("rewrite-panel");
    if (panel) panel.remove();
}

async function doRewrite() {
    const novelId = getSelectedNovelId();
    const originalText = document.getElementById("rewrite-original").value.trim();
    const instruction = document.getElementById("rewrite-instruction").value.trim();

    if (!originalText) { alert("请输入需要重写的内容"); return; }
    if (!instruction) { alert("请输入修改方向"); return; }

    const btn = document.getElementById("btn-do-rewrite");
    btn.disabled = true;
    btn.textContent = "正在重写...";

    const resultArea = document.getElementById("rewrite-result-area");
    resultArea.style.display = "block";
    rewriteResults = ["", ""];
    rewriteLabels = ["", ""];

    for (let i = 0; i < 2; i++) {
        const el = document.getElementById(`rewrite-result-${i}`);
        if (el) { el.textContent = ""; el.style.borderColor = "var(--accent)"; }
        const labelEl = document.getElementById(`rewrite-label-${i}`);
        if (labelEl) labelEl.textContent = `版本${i === 0 ? "A" : "B"}`;
    }

    try {
        const response = await fetch(`/api/novels/${novelId}/rewrite`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                original_text: originalText,
                instruction: instruction,
                chapter_number: appState.currentChapter,
                stream: true,
            }),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: "请求失败" }));
            throw new Error(err.detail || "请求失败");
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
                    if (data.type === "focus") {
                        rewriteLabels[data.version] = data.label;
                        const labelEl = document.getElementById(`rewrite-label-${data.version}`);
                        if (labelEl) labelEl.textContent = `${data.label}：${data.approach}`;
                    } else if (data.type === "content") {
                        rewriteResults[data.version] += data.text;
                        const el = document.getElementById(`rewrite-result-${data.version}`);
                        if (el) {
                            el.textContent = rewriteResults[data.version];
                            el.scrollTop = el.scrollHeight;
                        }
                    } else if (data.type === "version_done") {
                        const el = document.getElementById(`rewrite-result-${data.version}`);
                        if (el) el.style.borderColor = "var(--success)";
                    } else if (data.type === "version_error") {
                        const el = document.getElementById(`rewrite-result-${data.version}`);
                        if (el) {
                            el.textContent = "生成失败: " + data.error;
                            el.style.borderColor = "var(--danger)";
                        }
                    } else if (data.type === "error") {
                        throw new Error(data.error);
                    }
                } catch (e) {
                    if (e.message && !e.message.includes("JSON")) throw e;
                }
            }
        }
    } catch (e) {
        alert("重写失败: " + e.message);
    }

    btn.disabled = false;
    btn.textContent = "开始重写";
}

function acceptRewrite(version) {
    const text = rewriteResults[version];
    if (!text) return;

    if (isEditMode) {
        const editor = document.getElementById("chapter-editor");
        const original = document.getElementById("rewrite-original").value.trim();
        editor.value = editor.value.replace(original, text);
        currentChapterContent = editor.value;
        editor.dispatchEvent(new Event("input"));
    } else {
        const original = document.getElementById("rewrite-original").value.trim();
        currentChapterContent = currentChapterContent.replace(original, text);
        const textEl = document.getElementById("chapter-text");
        textEl.textContent = currentChapterContent;
    }

    contentModified = true;
    closeRewritePanel();
    updateStatusBar(`已采纳「${rewriteLabels[version] || "版本" + (version + 1)}」的重写内容`);
}

function retryRewrite() {
    document.getElementById("rewrite-result-area").style.display = "none";
    doRewrite();
}

function discardRewrite() {
    document.getElementById("rewrite-result-area").style.display = "none";
    rewriteResults = ["", ""];
    rewriteLabels = ["", ""];
}

function switchView(name) {
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.querySelectorAll(".activity-item").forEach(b => b.classList.remove("active"));
    const view = document.getElementById("view-" + name);
    if (view) view.classList.add("active");
    const btn = document.querySelector(`.activity-item[data-view="${name}"]`);
    if (btn) btn.classList.add("active");
    if (name === "settings" && typeof loadProviders === "function") loadProviders();
    if (name === "settings" && typeof loadNovelKBBinding === "function") loadNovelKBBinding();
}

function updateActiveModelIndicator(text) {
    document.getElementById("active-model-indicator").textContent = "模型: " + (text || "未配置");
}

async function init() {
    await loadNovelList();
    switchView("writing");
    updateStatusBar("就绪");
}

init();
