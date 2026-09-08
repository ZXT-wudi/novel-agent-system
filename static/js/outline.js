let currentOutline = [];
let currentFullOutline = {};
let fullOutlineConfirmed = false;
let outlineConfirmed = false;
let outlineGenerating = false;
let outlineAbortController = null;

function updateFullOutlineLengthTag() {
    const input = document.getElementById("full-outline-target-word-count");
    const tag = document.getElementById("full-outline-length-tag");
    if (!input || !tag) return;
    const val = parseInt(input.value) || 0;
    const isLong = val >= 500000;
    tag.textContent = isLong ? "长篇" : "短篇";
    tag.style.color = isLong ? "#e8a838" : "var(--text-secondary)";
}

document.getElementById("full-outline-target-word-count")?.addEventListener("input", updateFullOutlineLengthTag);

async function generateFullOutline() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    if (outlineGenerating) {
        if (confirm("大纲正在生成中，是否取消当前生成？")) {
            if (outlineAbortController) {
                outlineAbortController.abort();
                outlineAbortController = null;
            }
            outlineGenerating = false;
            setWritingStatus("done", "已取消");
        }
        return;
    }

    const novel = appState.novels.find(n => n.id === novelId);
    const description = novel ? novel.description || "" : "";
    const genre = novel ? novel.genre || "" : "";
    const twcInput = document.getElementById("full-outline-target-word-count");
    const targetWordCount = twcInput ? (parseInt(twcInput.value) || 0) : (novel ? novel.target_word_count || 0 : 0);
    const lengthType = targetWordCount >= 500000 ? "long" : "short";
    const useWebResearch = document.getElementById("use-web-research-full")?.checked || false;

    outlineGenerating = true;
    outlineAbortController = new AbortController();
    setWritingStatus("writing", "正在生成全文大纲...");
    updateStatusBar("AI正在生成全文大纲，请耐心等待...");

    const container = document.getElementById("full-outline-container");
    container.innerHTML = '<div class="outline-empty" id="full-outline-stream-text" style="text-align:left;white-space:pre-wrap;font-size:12px;color:var(--text-secondary);max-height:300px;overflow-y:auto;"></div>';

    const streamText = document.getElementById("full-outline-stream-text");
    let fullText = "";
    let lastPhase = "";

    try {
        const pending = appState.pendingOutlineSettings || null;
        const body = { description, genre, length_type: lengthType, target_word_count: targetWordCount, use_web_research: useWebResearch };
        if (pending && pending.world_settings) body.world_settings = pending.world_settings;
        if (pending && pending.characters) body.characters = pending.characters;
        appState.pendingOutlineSettings = null;
        const response = await fetch(`/api/novels/${novelId}/outline/generate-full`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: outlineAbortController.signal,
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
                    } else if (data.type === "status") {
                        const phase = data.phase || "";
                        const msg = data.message || "";
                        const isKeepalive = (phase === lastPhase);
                        lastPhase = phase;
                        if (phase === "web_researching") {
                            updateStatusBar("正在联网搜索参考资料（Tavily）...");
                            if (!isKeepalive) streamText.textContent = "🔍 联网取材中...\n";
                        } else if (phase === "web_research_done") {
                            updateStatusBar("联网取材完成，开始生成全文大纲...");
                            streamText.textContent = "✅ 联网取材完成\n";
                        } else if (phase === "web_research_skipped") {
                            updateStatusBar("联网取材跳过：" + msg + "，开始生成全文大纲...");
                            streamText.textContent = "⚠ 联网取材跳过：" + msg + "\n";
                        } else if (phase === "kb_saving") {
                            updateStatusBar("💾 正在将联网取材保存到知识库...");
                            if (!isKeepalive) streamText.textContent += "💾 正在保存到知识库...\n";
                        } else if (phase === "kb_saved") {
                            const r = data.data || {};
                            const saved = r.saved || 0;
                            const skipped = r.skipped || 0;
                            updateStatusBar(`💾 已保存 ${saved} 条到知识库（跳过 ${skipped} 条矛盾内容）`);
                            streamText.textContent += `✅ 知识库已保存 ${saved} 条（跳过 ${skipped} 条矛盾内容）\n`;
                        } else if (phase === "kb_save_failed") {
                            updateStatusBar("⚠️ 知识库保存失败，但不影响大纲生成");
                            streamText.textContent += "⚠ 知识库保存失败：" + msg + "（不影响大纲生成）\n";
                        } else if (phase === "kb_loading") {
                            updateStatusBar("📚 正在加载知识库内容...");
                            if (!isKeepalive) streamText.textContent += "📚 正在加载知识库内容...\n";
                        } else if (phase === "generating_full_outline") {
                            updateStatusBar("正在生成全文大纲...");
                            if (!isKeepalive) streamText.textContent += "⏳ 正在生成全文大纲...\n";
                        }
                    } else if (data.type === "complete") {
                        const fullOutline = data.data && data.data.full_outline ? data.data.full_outline : null;
                        if (fullOutline && fullOutline.volumes) {
                            currentFullOutline = fullOutline;
                            fullOutlineConfirmed = false;
                            renderFullOutline(fullOutline);
                        }
                        const novelEntry = appState.novels.find(n => n.id === novelId);
                        if (novelEntry) {
                            novelEntry.target_word_count = parseInt(document.getElementById("full-outline-target-word-count")?.value) || novelEntry.target_word_count || 0;
                            novelEntry.length_type = novelEntry.target_word_count >= 500000 ? "long" : "short";
                        }
                        setWritingStatus("done", "全文大纲已生成");
                        updateStatusBar("全文大纲生成完成，请查看并确认");
                    } else if (data.type === "error") {
                        throw new Error(data.error || "生成失败");
                    }
                } catch (e) {
                    if (e.message && !e.message.includes("JSON")) throw e;
                }
            }
        }

        if (!currentFullOutline || !currentFullOutline.volumes || currentFullOutline.volumes.length === 0) {
            container.innerHTML = '<div class="outline-empty">全文大纲生成失败，请重试</div>';
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            setWritingStatus("done", "已取消");
            updateStatusBar("全文大纲生成已取消");
        } else {
            setWritingStatus("done", "全文大纲生成失败");
            container.innerHTML = `<div class="outline-empty" style="color:var(--danger);">生成失败: ${escapeHtml(error.message)}<br>请稍后重试</div>`;
        }
    } finally {
        outlineGenerating = false;
        outlineAbortController = null;
    }
}

async function aiReviseFullOutline() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    const modal = document.getElementById("modal-content");
    modal.innerHTML = `
        <h2>AI修改全文大纲</h2>
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px;">描述你希望对全文大纲做出的修改，AI将根据你的意见重新调整大纲</p>
        <div class="form-group">
            <label>修改意见</label>
            <textarea id="revise-full-outline-feedback" rows="5" placeholder="例如：&#10;- 第一卷的节奏太快，需要增加过渡章节&#10;- 核心冲突不够突出，需要加强&#10;- 第三卷的基调太压抑，调整为先抑后扬&#10;- 增加一条副线，关于主角的师门"></textarea>
        </div>
        <div class="form-group">
            <label>修改范围（可选）</label>
            <select id="revise-full-outline-scope">
                <option value="all">全部大纲</option>
                ${currentFullOutline.volumes ? currentFullOutline.volumes.map(v => `<option value="volume_${v.volume_number}">第${v.volume_number}卷「${escapeHtml(v.title || '')}」</option>`).join('') : ''}
            </select>
        </div>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">取消</button>
            <button class="btn btn-primary" onclick="doAiReviseFullOutline()">开始修改</button>
        </div>
    `;
    showModal();
}

async function doAiReviseFullOutline() {
    const novelId = getSelectedNovelId();
    const feedback = document.getElementById("revise-full-outline-feedback").value.trim();
    const scope = document.getElementById("revise-full-outline-scope").value;

    if (!feedback) { alert("请输入修改意见"); return; }

    let fullFeedback = feedback;
    if (scope !== "all") {
        const volNum = scope.replace("volume_", "");
        fullFeedback = `[仅修改第${volNum}卷] ${feedback}`;
    }

    closeModal();
    setWritingStatus("writing", "正在修改全文大纲...");
    updateStatusBar("AI正在根据你的意见修改全文大纲...");

    try {
        const result = await apiPost(`/api/novels/${novelId}/outline/revise-full`, {
            user_feedback: fullFeedback,
        });
        currentFullOutline = result.full_outline || {};
        fullOutlineConfirmed = false;
        renderFullOutline(currentFullOutline);
        setWritingStatus("done", "全文大纲已修改");
        updateStatusBar("全文大纲修改完成");
    } catch (e) {
        setWritingStatus("done", "全文大纲修改失败");
        alert("全文大纲修改失败: " + e.message);
    }
}

async function generateChapterOutline() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    if (!currentFullOutline || !currentFullOutline.volumes || currentFullOutline.volumes.length === 0) {
        alert("请先生成并确认全文大纲");
        return;
    }

    if (!fullOutlineConfirmed) {
        alert("请先确认全文大纲后再生成章节大纲");
        return;
    }

    if (outlineGenerating) {
        if (confirm("大纲正在生成中，是否取消当前生成？")) {
            if (outlineAbortController) {
                outlineAbortController.abort();
                outlineAbortController = null;
            }
            outlineGenerating = false;
            setWritingStatus("done", "已取消");
            renderOutline();
        }
        return;
    }

    const startChapter = currentOutline.length > 0 ? Math.max(...currentOutline.map(o => o.chapter_number)) + 1 : 1;

    outlineGenerating = true;
    outlineAbortController = new AbortController();
    setWritingStatus("writing", "正在生成章节大纲...");
    updateStatusBar("AI正在生成章节大纲，请耐心等待...");

    const container = document.getElementById("outline-container");
    container.innerHTML = '<div class="outline-empty" id="outline-stream-text" style="text-align:left;white-space:pre-wrap;font-size:12px;color:var(--text-secondary);max-height:300px;overflow-y:auto;"></div>';

    const streamText = document.getElementById("outline-stream-text");
    let fullText = "";

    try {
        const response = await fetch(`/api/novels/${novelId}/outline/generate-chapters`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ batch_size: 10, start_chapter: startChapter }),
            signal: outlineAbortController.signal,
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
                        } else {
                            currentOutline = parseOutlineFromText(fullText);
                        }
                        outlineConfirmed = false;
                        renderOutline();
                        setWritingStatus("done", "章节大纲已生成");
                        updateStatusBar("章节大纲生成完成，请查看并编辑");
                    } else if (data.type === "error") {
                        throw new Error(data.error || "生成失败");
                    }
                } catch (e) {
                    if (e.message && !e.message.includes("JSON")) throw e;
                }
            }
        }

        if (!currentOutline || currentOutline.length === 0) {
            currentOutline = parseOutlineFromText(fullText);
            if (currentOutline.length > 0) {
                outlineConfirmed = false;
                renderOutline();
                setWritingStatus("done", "章节大纲已生成");
                updateStatusBar("章节大纲生成完成");
            }
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            setWritingStatus("done", "已取消");
            updateStatusBar("章节大纲生成已取消");
        } else {
            setWritingStatus("done", "章节大纲生成失败");
            container.innerHTML = `<div class="outline-empty" style="color:var(--danger);">生成失败: ${escapeHtml(error.message)}<br>请稍后重试</div>`;
            alert("章节大纲生成失败: " + error.message);
        }
    } finally {
        outlineGenerating = false;
        outlineAbortController = null;
    }
}

function parseOutlineFromText(text) {
    try {
        let clean = text.trim();
        if (clean.startsWith("```")) {
            const lines = clean.split("\n");
            clean = lines.slice(1, -1).join("\n");
        }
        const parsed = JSON.parse(clean);
        if (Array.isArray(parsed) && parsed.length > 0) {
            return parsed;
        }
    } catch (e) {
        const start = text.indexOf("[");
        const end = text.lastIndexOf("]");
        if (start !== -1 && end !== -1 && end > start) {
            try {
                const parsed = JSON.parse(text.substring(start, end + 1));
                if (Array.isArray(parsed) && parsed.length > 0) {
                    return parsed;
                }
            } catch (e2) {
            }
        }
    }
    return [];
}

async function aiReviseOutline() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    const modal = document.getElementById("modal-content");
    modal.innerHTML = `
        <h2>AI修改章节大纲</h2>
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px;">描述你希望对章节大纲做出的修改，AI将根据你的意见重新调整</p>
        <div class="form-group">
            <label>修改意见</label>
            <textarea id="revise-outline-feedback" rows="5" placeholder="例如：&#10;- 第3章的情节太平淡，需要增加冲突&#10;- 第5-7章节奏太慢，需要压缩&#10;- 主角在第8章的行为不符合人设&#10;- 增加一条关于配角的伏笔"></textarea>
        </div>
        <div class="form-group">
            <label>修改范围（可选）</label>
            <select id="revise-outline-scope">
                <option value="all">全部章节大纲</option>
                ${currentOutline.map(o => `<option value="chapter_${o.chapter_number}">第${o.chapter_number}章「${escapeHtml(o.title || '')}」</option>`).join('')}
            </select>
        </div>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">取消</button>
            <button class="btn btn-primary" onclick="doAiReviseOutline()">开始修改</button>
        </div>
    `;
    showModal();
}

async function doAiReviseOutline() {
    const novelId = getSelectedNovelId();
    const feedback = document.getElementById("revise-outline-feedback").value.trim();
    const scope = document.getElementById("revise-outline-scope").value;

    if (!feedback) { alert("请输入修改意见"); return; }

    let fullFeedback = feedback;
    if (scope !== "all") {
        const chNum = scope.replace("chapter_", "");
        fullFeedback = `[重点关注第${chNum}章] ${feedback}`;
    }

    closeModal();
    setWritingStatus("writing", "正在修改章节大纲...");
    updateStatusBar("AI正在根据你的意见修改章节大纲...");

    try {
        const result = await apiPost(`/api/novels/${novelId}/outline/revise`, {
            user_feedback: fullFeedback,
        });
        currentOutline = result.outline || [];
        outlineConfirmed = false;
        renderOutline();
        setWritingStatus("done", "章节大纲已修改");
        updateStatusBar("章节大纲修改完成");
    } catch (e) {
        setWritingStatus("done", "章节大纲修改失败");
        alert("章节大纲修改失败: " + e.message);
    }
}

async function confirmOutline() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    if (!currentOutline || currentOutline.length === 0) {
        alert("请先生成章节大纲");
        return;
    }

    if (!confirm("确认章节大纲？确认后大纲将保存到数据库，智能体将根据此大纲写作。")) return;

    try {
        await apiPut(`/api/novels/${novelId}/outline`, { outline: currentOutline });
        await apiPut(`/api/novels/${novelId}/outline/confirm`, { confirmed: true });
        outlineConfirmed = true;
        renderOutline();
        updateStatusBar("章节大纲已确认并保存，可以开始写作");
        await loadNovelInfo(novelId);
    } catch (e) {
        alert("确认失败: " + e.message);
    }
}

async function saveOutline() {
    const novelId = getSelectedNovelId();
    if (!novelId) return;

    try {
        await apiPut(`/api/novels/${novelId}/outline`, { outline: currentOutline });
        updateStatusBar("大纲已保存");
    } catch (e) {
        alert("保存失败: " + e.message);
    }
}

function renderOutline() {
    const container = document.getElementById("outline-container");
    const confirmBtn = document.getElementById("btn-confirm-outline");
    if (!currentOutline || currentOutline.length === 0) {
        container.innerHTML = '<div class="outline-empty">请生成章节大纲</div>';
        if (confirmBtn) confirmBtn.style.display = "none";
        return;
    }

    if (!outlineConfirmed) {
        if (confirmBtn) confirmBtn.style.display = "inline-flex";
    } else {
        if (confirmBtn) confirmBtn.style.display = "none";
    }

    let html = "";
    if (!outlineConfirmed) {
        html += `<div class="outline-status-bar">
            <span class="badge" style="background:var(--warning);color:#fff;">未确认</span>
            <span style="font-size:11px;color:var(--text-muted);">修改后请点击"确认大纲"</span>
        </div>`;
    } else {
        html += `<div class="outline-status-bar">
            <span class="badge" style="background:var(--success);color:#fff;">已确认</span>
        </div>`;
    }

    currentOutline.forEach((item, index) => {
        const isActive = item.chapter_number === appState.currentChapter;
        html += `
            <div class="outline-item ${isActive ? 'active' : ''}">
                <div class="outline-item-number" onclick="selectOutlineChapter(${item.chapter_number})">${item.chapter_number}</div>
                <div class="outline-item-content" onclick="selectOutlineChapter(${item.chapter_number})">
                    <div class="outline-item-title" contenteditable="true" 
                         onblur="updateOutlineTitle(${index}, this.textContent)"
                         onclick="event.stopPropagation()">${escapeHtml(item.title || '未命名')}</div>
                    <div class="outline-item-summary">${escapeHtml(item.plot_summary || '暂无摘要')}</div>
                </div>
                <div class="outline-item-actions">
                    <button class="outline-action-btn" onclick="event.stopPropagation();showOutlineEditModal(${index})" title="编辑">✎</button>
                    <button class="outline-action-btn delete" onclick="event.stopPropagation();deleteOutlineChapter(${index})" title="删除">✕</button>
                </div>
            </div>
        `;
    });

    html += `<div style="text-align:center;padding:8px;">
        <button class="btn btn-sm btn-outline" onclick="addOutlineChapter()">+ AI生成后续10章</button>
    </div>`;

    container.innerHTML = html;
}

function updateOutlineTitle(index, newTitle) {
    if (currentOutline[index]) {
        currentOutline[index].title = newTitle.trim();
        outlineConfirmed = false;
        renderOutline();
        saveOutline();
    }
}

function deleteOutlineChapter(index) {
    if (!currentOutline[index]) return;
    const item = currentOutline[index];
    if (!confirm(`确定删除第${item.chapter_number}章「${item.title || '未命名'}」？`)) return;
    currentOutline.splice(index, 1);
    outlineConfirmed = false;
    renderOutline();
    saveOutline();
}

async function addOutlineChapter() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    if (!currentFullOutline || !currentFullOutline.volumes || currentFullOutline.volumes.length === 0) {
        alert("请先生成并确认全文大纲后再添加章节");
        return;
    }

    if (!fullOutlineConfirmed) {
        alert("请先确认全文大纲后再添加章节");
        return;
    }

    if (outlineGenerating) {
        if (confirm("大纲正在生成中，是否取消当前生成？")) {
            if (outlineAbortController) {
                outlineAbortController.abort();
                outlineAbortController = null;
            }
            outlineGenerating = false;
            setWritingStatus("done", "已取消");
            renderOutline();
        }
        return;
    }

    const startChapter = currentOutline.length > 0 ? Math.max(...currentOutline.map(o => o.chapter_number)) + 1 : 1;

    outlineGenerating = true;
    outlineAbortController = new AbortController();
    setWritingStatus("writing", "正在生成后续章节大纲...");
    updateStatusBar(`AI正在读取全文大纲、已有章节和知识库，生成第${startChapter}章开始的10章大纲...`);

    const container = document.getElementById("outline-container");
    const streamDiv = document.createElement("div");
    streamDiv.id = "outline-stream-text";
    streamDiv.style.cssText = "text-align:left;white-space:pre-wrap;font-size:12px;color:var(--text-secondary);max-height:300px;overflow-y:auto;padding:8px;";
    container.appendChild(streamDiv);

    let fullText = "";

    try {
        const response = await fetch(`/api/novels/${novelId}/outline/generate-chapters`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ batch_size: 10, start_chapter: startChapter }),
            signal: outlineAbortController.signal,
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
                        streamDiv.textContent += data.text;
                        streamDiv.scrollTop = streamDiv.scrollHeight;
                    } else if (data.type === "complete") {
                        const outline = data.data && data.data.outline ? data.data.outline : null;
                        if (outline && outline.length > 0) {
                            currentOutline = outline;
                        } else {
                            const parsed = parseOutlineFromText(fullText);
                            if (parsed.length > 0) {
                                currentOutline = currentOutline.concat(parsed);
                            }
                        }
                        outlineConfirmed = false;
                        renderOutline();
                        setWritingStatus("done", "后续章节大纲已生成");
                        updateStatusBar("后续章节大纲生成完成，请查看并重新确认大纲");
                    } else if (data.type === "error") {
                        throw new Error(data.error || "生成失败");
                    }
                } catch (e) {
                    if (e.message && !e.message.includes("JSON")) throw e;
                }
            }
        }

        if (currentOutline.length === 0) {
            const parsed = parseOutlineFromText(fullText);
            if (parsed.length > 0) {
                currentOutline = currentOutline.concat(parsed);
                outlineConfirmed = false;
                renderOutline();
                setWritingStatus("done", "后续章节大纲已生成");
                updateStatusBar("后续章节大纲生成完成，请重新确认大纲");
            }
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            setWritingStatus("done", "已取消");
            updateStatusBar("生成已取消");
        } else {
            setWritingStatus("done", "生成失败");
            alert("生成后续章节大纲失败: " + error.message);
        }
    } finally {
        outlineGenerating = false;
        outlineAbortController = null;
    }
}

async function selectOutlineChapter(chapterNumber) {
    const success = await loadChapter(chapterNumber);
    if (!success) return;
    renderOutline();
    const select = document.getElementById("chapter-select");
    if (select) select.value = chapterNumber;
}

async function loadOutline(novelId) {
    const novel = appState.novels.find(n => n.id === novelId);
    const isConfirmed = novel && novel.status !== "planning";

    const twcInput = document.getElementById("full-outline-target-word-count");
    if (twcInput && novel) {
        twcInput.value = novel.target_word_count || 0;
        updateFullOutlineLengthTag();
    }

    try {
        const result = await apiGet(`/api/novels/${novelId}/outline`);
        currentOutline = result.outline || [];
        outlineConfirmed = isConfirmed;
        renderOutline();
    } catch (e) {
        console.error("加载大纲失败:", e);
    }

    try {
        const foResult = await apiGet(`/api/novels/${novelId}/outline/full`);
        if (foResult.full_outline && foResult.full_outline.volumes && foResult.full_outline.volumes.length > 0) {
            currentFullOutline = foResult.full_outline;
            fullOutlineConfirmed = isConfirmed;
            renderFullOutline(foResult.full_outline);
        } else {
            currentFullOutline = {};
            fullOutlineConfirmed = false;
            const confirmBtn = document.getElementById("btn-confirm-full-outline");
            if (confirmBtn) confirmBtn.style.display = "none";
        }
    } catch (e) {
        console.error("加载全文大纲失败:", e);
    }
}

function showOutlineEditModal(index) {
    const item = currentOutline[index];
    if (!item) return;

    const modal = document.getElementById("modal-content");
    modal.innerHTML = `
        <h2>编辑第${item.chapter_number}章大纲</h2>
        <div class="form-group">
            <label>章节标题</label>
            <input type="text" id="edit-outline-title" value="${escapeHtml(item.title || '')}">
        </div>
        <div class="form-group">
            <label>情节摘要</label>
            <textarea id="edit-outline-summary">${escapeHtml(item.plot_summary || '')}</textarea>
        </div>
        <div class="form-group">
            <label>关键事件（每行一个）</label>
            <textarea id="edit-outline-events">${escapeHtml((item.key_events || []).join('\n'))}</textarea>
        </div>
        <div class="form-group">
            <label>涉及人物（每行一个）</label>
            <textarea id="edit-outline-characters">${escapeHtml((item.characters || []).join('\n'))}</textarea>
        </div>
        <div class="form-group">
            <label>备注</label>
            <textarea id="edit-outline-notes">${escapeHtml(item.notes || '')}</textarea>
        </div>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">取消</button>
            <button class="btn btn-primary" onclick="saveOutlineEdit(${index})">保存</button>
        </div>
    `;
    showModal();
}

function saveOutlineEdit(index) {
    const item = currentOutline[index];
    if (!item) return;

    item.title = document.getElementById("edit-outline-title").value;
    item.plot_summary = document.getElementById("edit-outline-summary").value;
    item.key_events = document.getElementById("edit-outline-events").value.split("\n").filter(s => s.trim());
    item.characters = document.getElementById("edit-outline-characters").value.split("\n").filter(s => s.trim());
    item.notes = document.getElementById("edit-outline-notes").value;

    outlineConfirmed = false;
    renderOutline();
    saveOutline();
    closeModal();
    updateStatusBar("章节大纲已修改，请重新确认大纲");
}

async function confirmFullOutline() {
    const novelId = getSelectedNovelId();
    if (!novelId) { alert("请先选择小说"); return; }

    if (!currentFullOutline || !currentFullOutline.volumes || currentFullOutline.volumes.length === 0) {
        alert("请先生成全文大纲");
        return;
    }

    if (!confirm("确认全文大纲？确认后大纲将保存到数据库，智能体将根据此大纲生成章节。")) return;

    try {
        await apiPut(`/api/novels/${novelId}/outline/full`, { full_outline: currentFullOutline });
        fullOutlineConfirmed = true;
        renderFullOutline(currentFullOutline);
        updateStatusBar("全文大纲已确认并保存，可以生成章节大纲");
    } catch (e) {
        alert("确认失败: " + e.message);
    }
}

function editFullOutlineModal() {
    const modal = document.getElementById("modal-content");
    const fo = currentFullOutline;

    let volumesHtml = '';
    (fo.volumes || []).forEach((vol, i) => {
        const dynTxt = (vol.character_dynamics || []).map(d => `${d.character || ''}|${d.emotion_state || ''}|${d.key_event || ''}|${d.emotion_change || ''}`).join('\n');
        const abiTxt = (vol.protagonist_abilities || []).map(a => `${a.ability || ''}|${a.state || ''}|${a.change || ''}|${a.trigger_event || ''}`).join('\n');
        const fsIds = (vol.foreshadowing_ids || []).join(', ');
        volumesHtml += `
            <div class="form-group" style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;margin-bottom:8px;">
                <label style="font-weight:600;">第${vol.volume_number}卷</label>
                <div class="form-group">
                    <label>卷标题</label>
                    <input type="text" id="edit-fo-vol-title-${i}" value="${escapeHtml(vol.title || '')}">
                </div>
                <div class="form-group">
                    <label>卷概述</label>
                    <textarea id="edit-fo-vol-summary-${i}" rows="3">${escapeHtml(vol.summary || '')}</textarea>
                </div>
                <div class="form-group">
                    <label>核心角色（逗号分隔）</label>
                    <input type="text" id="edit-fo-vol-chars-${i}" value="${escapeHtml((vol.key_characters || []).join(', '))}">
                </div>
                <div class="form-group">
                    <label>重大事件（逗号分隔）</label>
                    <input type="text" id="edit-fo-vol-events-${i}" value="${escapeHtml((vol.major_events || []).join(', '))}">
                </div>
                <div class="form-group">
                    <label>章节范围</label>
                    <div style="display:flex;gap:8px;">
                        <input type="number" id="edit-fo-vol-start-${i}" value="${escapeHtml(vol.chapter_range ? vol.chapter_range[0] : '')}" placeholder="起始章" style="width:80px;">
                        <span style="line-height:36px;">~</span>
                        <input type="number" id="edit-fo-vol-end-${i}" value="${escapeHtml(vol.chapter_range ? vol.chapter_range[1] : '')}" placeholder="结束章" style="width:80px;">
                    </div>
                </div>
                <div class="form-group">
                    <label>基调</label>
                    <input type="text" id="edit-fo-vol-tone-${i}" value="${escapeHtml(vol.tone || '')}">
                </div>
                ${(vol.source_volumes && vol.source_volumes.length) ? `<div class="form-group"><label>关联知识库卷（自动生成）</label><div class="outline-readonly-field">第 ${vol.source_volumes.map(v => v + '卷').join('、')}</div></div>` : ''}
                <div class="form-group">
                    <label>角色情感动态（每行：角色|情感状态|关键事件|情感变化）</label>
                    <textarea id="edit-fo-vol-dynamics-${i}" rows="3" placeholder="主角|信任|结盟|由戒备转为信任">${escapeHtml(dynTxt)}</textarea>
                </div>
                <div class="form-group">
                    <label>主角能力进阶（每行：能力|状态|变化|触发事件）</label>
                    <textarea id="edit-fo-vol-abilities-${i}" rows="3" placeholder="剑术|觉醒|熟练度提升|生死之战">${escapeHtml(abiTxt)}</textarea>
                </div>
                <div class="form-group">
                    <label>本卷伏笔ID（逗号分隔，如 F1,F2）</label>
                    <input type="text" id="edit-fo-vol-fsids-${i}" value="${escapeHtml(fsIds)}">
                </div>
            </div>
        `;
    });

    const foreshadowingTxt = (fo.foreshadowing || []).map(f => `${f.id || ''}|${f.description || ''}|${f.planted_in_volume || ''}|${f.payoff_in_volume || ''}|${f.status || ''}`).join('\n');

    modal.innerHTML = `
        <h2>编辑全文大纲</h2>
        <div class="form-group">
            <label>主题</label>
            <input type="text" id="edit-fo-theme" value="${escapeHtml(fo.theme || '')}">
        </div>
        <div class="form-group">
            <label>核心冲突</label>
            <textarea id="edit-fo-conflict" rows="2">${escapeHtml(fo.core_conflict || '')}</textarea>
        </div>
        <div class="form-group">
            <label>故事弧线</label>
            <textarea id="edit-fo-arc" rows="3">${escapeHtml(fo.story_arc || '')}</textarea>
        </div>
        <div class="form-group">
            <label>预计总章节数</label>
            <input type="number" id="edit-fo-total" value="${escapeHtml(fo.total_chapters || '')}">
        </div>
        <div class="form-group">
            <label>伏笔总览（每行：ID|描述|埋下卷|回收卷|状态）</label>
            <textarea id="edit-fo-foreshadowing" rows="4" placeholder="F1|主角身世之谜|1|5|planted">${escapeHtml(foreshadowingTxt)}</textarea>
        </div>
        <h3 style="margin:12px 0 8px;font-size:14px;">分卷详情</h3>
        ${volumesHtml}
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">取消</button>
            <button class="btn btn-primary" onclick="saveFullOutlineEdit()">保存</button>
        </div>
    `;
    showModal();
}

async function saveFullOutlineEdit() {
    const fo = currentFullOutline;
    fo.theme = document.getElementById("edit-fo-theme").value;
    fo.core_conflict = document.getElementById("edit-fo-conflict").value;
    fo.story_arc = document.getElementById("edit-fo-arc").value;
    fo.total_chapters = parseInt(document.getElementById("edit-fo-total").value) || fo.total_chapters;

    (fo.volumes || []).forEach((vol, i) => {
        vol.title = document.getElementById(`edit-fo-vol-title-${i}`).value;
        vol.summary = document.getElementById(`edit-fo-vol-summary-${i}`).value;
        vol.key_characters = document.getElementById(`edit-fo-vol-chars-${i}`).value.split(',').map(s => s.trim()).filter(s => s);
        vol.major_events = document.getElementById(`edit-fo-vol-events-${i}`).value.split(',').map(s => s.trim()).filter(s => s);
        const start = parseInt(document.getElementById(`edit-fo-vol-start-${i}`).value) || 0;
        const end = parseInt(document.getElementById(`edit-fo-vol-end-${i}`).value) || 0;
        vol.chapter_range = [start, end];
        vol.tone = document.getElementById(`edit-fo-vol-tone-${i}`).value;
        vol.character_dynamics = (document.getElementById(`edit-fo-vol-dynamics-${i}`).value || '').split('\n').map(line => {
            const p = line.split('|').map(s => s.trim());
            if (!p[0]) return null;
            return { character: p[0] || '', emotion_state: p[1] || '', key_event: p[2] || '', emotion_change: p[3] || '' };
        }).filter(Boolean);
        vol.protagonist_abilities = (document.getElementById(`edit-fo-vol-abilities-${i}`).value || '').split('\n').map(line => {
            const p = line.split('|').map(s => s.trim());
            if (!p[0]) return null;
            return { ability: p[0] || '', state: p[1] || '', change: p[2] || '', trigger_event: p[3] || '' };
        }).filter(Boolean);
        vol.foreshadowing_ids = (document.getElementById(`edit-fo-vol-fsids-${i}`).value || '').split(',').map(s => s.trim()).filter(s => s);
    });

    fo.foreshadowing = (document.getElementById("edit-fo-foreshadowing").value || '').split('\n').map(line => {
        const p = line.split('|').map(s => s.trim());
        if (!p[0]) return null;
        const pv = p[2] ? parseInt(p[2]) : null;
        const payv = p[3] ? parseInt(p[3]) : null;
        return { id: p[0] || '', description: p[1] || '', planted_in_volume: pv, payoff_in_volume: payv, status: p[4] || '' };
    }).filter(Boolean);

    const novelId = getSelectedNovelId();
    try {
        await apiPut(`/api/novels/${novelId}/outline/full`, { full_outline: fo });
        currentFullOutline = fo;
        fullOutlineConfirmed = false;
        renderFullOutline(fo);
        closeModal();
        updateStatusBar("全文大纲已修改，请重新确认大纲以使智能体读取最新版本");
    } catch (e) {
        alert("保存失败: " + e.message);
    }
}

let outlineFullscreenPriorState = null;

function enterOutlineFullscreen() {
    const ch = document.getElementById("chapter-header");
    const rp = document.getElementById("review-panel");
    if (!outlineFullscreenPriorState) {
        outlineFullscreenPriorState = {
            chapterContent: document.getElementById("chapter-content").style.display,
            welcomeScreen: document.getElementById("welcome-screen").style.display,
            chapterHeader: ch ? ch.style.display : "none",
            reviewPanel: rp ? rp.style.display : "none",
        };
    }
    document.getElementById("chapter-content").style.display = "none";
    document.getElementById("welcome-screen").style.display = "none";
    if (ch) ch.style.display = "none";
    if (rp) rp.style.display = "none";
    document.getElementById("full-outline-fullscreen").style.display = "none";
    document.getElementById("outline-fullscreen").style.display = "none";
}

function exitOutlineFullscreen() {
    document.getElementById("full-outline-fullscreen").style.display = "none";
    document.getElementById("outline-fullscreen").style.display = "none";
    const s = outlineFullscreenPriorState;
    if (s) {
        document.getElementById("chapter-content").style.display = s.chapterContent;
        document.getElementById("welcome-screen").style.display = s.welcomeScreen;
        const ch = document.getElementById("chapter-header"); if (ch) ch.style.display = s.chapterHeader;
        const rp = document.getElementById("review-panel"); if (rp) rp.style.display = s.reviewPanel;
    } else {
        document.getElementById("chapter-content").style.display = "";
        document.getElementById("welcome-screen").style.display = "flex";
    }
    outlineFullscreenPriorState = null;
}

function openFullOutlineFullscreen() {
    if (!currentFullOutline) currentFullOutline = {};
    if (!currentFullOutline.volumes) currentFullOutline.volumes = [];
    enterOutlineFullscreen();
    renderFullOutlineFullscreen();
}

function renderFullOutlineFullscreen() {
    document.getElementById("outline-fullscreen").style.display = "none";
    const fs = document.getElementById("full-outline-fullscreen");
    const fo = currentFullOutline || {};

    let volumesHtml = "";
    (fo.volumes || []).forEach((vol, i) => {
        const dynTxt = (vol.character_dynamics || []).map(d => `${d.character || ''}|${d.emotion_state || ''}|${d.key_event || ''}|${d.emotion_change || ''}`).join('\n');
        const abiTxt = (vol.protagonist_abilities || []).map(a => `${a.ability || ''}|${a.state || ''}|${a.change || ''}|${a.trigger_event || ''}`).join('\n');
        const fsIds = (vol.foreshadowing_ids || []).join(', ');
        volumesHtml += `
            <div class="outline-volume-card">
                <div class="outline-card-head">
                    <span class="outline-card-title">第 ${vol.volume_number || (i + 1)} 卷</span>
                </div>
                <div class="outline-edit-fields">
                    <div class="form-group">
                        <label>卷号</label>
                        <input type="number" class="outline-edit-input" id="fs-fo-vol-num-${i}" value="${escapeHtml(vol.volume_number || '')}">
                    </div>
                    <div class="form-group">
                        <label>卷标题</label>
                        <input type="text" class="outline-edit-input" id="fs-fo-vol-title-${i}" value="${escapeHtml(vol.title || '')}">
                    </div>
                    <div class="form-group">
                        <label>章节范围</label>
                        <div class="outline-range-row">
                            <input type="number" class="outline-edit-input outline-range-input" id="fs-fo-vol-start-${i}" value="${escapeHtml(vol.chapter_range ? vol.chapter_range[0] : '')}" placeholder="起始章">
                            <span class="outline-range-sep">~</span>
                            <input type="number" class="outline-edit-input outline-range-input" id="fs-fo-vol-end-${i}" value="${escapeHtml(vol.chapter_range ? vol.chapter_range[1] : '')}" placeholder="结束章">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>概要</label>
                        <textarea class="outline-edit-textarea" id="fs-fo-vol-summary-${i}" rows="3">${escapeHtml(vol.summary || '')}</textarea>
                    </div>
                    <div class="form-group">
                        <label>核心角色（逗号分隔）</label>
                        <input type="text" class="outline-edit-input" id="fs-fo-vol-chars-${i}" value="${escapeHtml((vol.key_characters || []).join(', '))}">
                    </div>
                    <div class="form-group">
                        <label>重大事件（逗号分隔）</label>
                        <input type="text" class="outline-edit-input" id="fs-fo-vol-events-${i}" value="${escapeHtml((vol.major_events || []).join(', '))}">
                    </div>
                    <div class="form-group">
                        <label>基调</label>
                        <input type="text" class="outline-edit-input" id="fs-fo-vol-tone-${i}" value="${escapeHtml(vol.tone || '')}">
                    </div>
                    ${(vol.source_volumes && vol.source_volumes.length) ? `<div class="form-group"><label>关联知识库卷（自动生成）</label><div class="outline-readonly-field">第 ${vol.source_volumes.map(v => v + '卷').join('、')}</div></div>` : ''}
                    <div class="form-group">
                        <label>角色情感动态（每行：角色|情感状态|关键事件|情感变化）</label>
                        <textarea class="outline-edit-textarea" id="fs-fo-vol-dynamics-${i}" rows="3" placeholder="主角|信任|结盟|由戒备转为信任">${escapeHtml(dynTxt)}</textarea>
                    </div>
                    <div class="form-group">
                        <label>主角能力进阶（每行：能力|状态|变化|触发事件）</label>
                        <textarea class="outline-edit-textarea" id="fs-fo-vol-abilities-${i}" rows="3" placeholder="剑术|觉醒|熟练度提升|生死之战">${escapeHtml(abiTxt)}</textarea>
                    </div>
                    <div class="form-group">
                        <label>本卷伏笔ID（逗号分隔，如 F1,F2）</label>
                        <input type="text" class="outline-edit-input" id="fs-fo-vol-fsids-${i}" value="${escapeHtml(fsIds)}">
                    </div>
                </div>
            </div>
        `;
    });

    const foreshadowingTxt = (fo.foreshadowing || []).map(f => `${f.id || ''}|${f.description || ''}|${f.planted_in_volume || ''}|${f.payoff_in_volume || ''}|${f.status || ''}`).join('\n');

    fs.innerHTML = `
        <div class="outline-fullscreen-header">
            <h2>全文大纲（展开编辑）</h2>
            <button class="btn btn-sm btn-outline" onclick="cancelFullOutlineFullscreen()">✕ 关闭</button>
        </div>
        <div class="outline-fullscreen-body">
            <div class="outline-edit-fields">
                <div class="form-group">
                    <label>主题</label>
                    <input type="text" class="outline-edit-input" id="fs-fo-theme" value="${escapeHtml(fo.theme || '')}">
                </div>
                <div class="form-group">
                    <label>核心冲突</label>
                    <textarea class="outline-edit-textarea" id="fs-fo-conflict" rows="2">${escapeHtml(fo.core_conflict || '')}</textarea>
                </div>
                <div class="form-group">
                    <label>故事弧线</label>
                    <textarea class="outline-edit-textarea" id="fs-fo-arc" rows="4">${escapeHtml(fo.story_arc || '')}</textarea>
                </div>
                <div class="form-group">
                    <label>预计总章节数</label>
                    <input type="number" class="outline-edit-input" id="fs-fo-total" value="${escapeHtml(fo.total_chapters || '')}">
                </div>
                <div class="form-group">
                    <label>伏笔总览（每行：ID|描述|埋下卷|回收卷|状态）</label>
                    <textarea class="outline-edit-textarea" id="fs-fo-foreshadowing" rows="4" placeholder="F1|主角身世之谜|1|5|planted">${escapeHtml(foreshadowingTxt)}</textarea>
                </div>
            </div>
            <h3 class="outline-fullscreen-section-title">分卷详情</h3>
            ${volumesHtml}
        </div>
        <div class="outline-fullscreen-actions">
            <button class="btn btn-outline" onclick="cancelFullOutlineFullscreen()">取消</button>
            <button class="btn btn-primary" onclick="saveFullOutlineFullscreen()">保存并返回</button>
        </div>
    `;
    fs.style.display = "flex";
    fs.scrollTop = 0;
}

function cancelFullOutlineFullscreen() {
    exitOutlineFullscreen();
}

async function saveFullOutlineFullscreen() {
    const fo = currentFullOutline || {};
    fo.theme = document.getElementById("fs-fo-theme").value;
    fo.core_conflict = document.getElementById("fs-fo-conflict").value;
    fo.story_arc = document.getElementById("fs-fo-arc").value;
    fo.total_chapters = parseInt(document.getElementById("fs-fo-total").value) || fo.total_chapters;

    (fo.volumes || []).forEach((vol, i) => {
        vol.volume_number = parseInt(document.getElementById(`fs-fo-vol-num-${i}`).value) || vol.volume_number;
        vol.title = document.getElementById(`fs-fo-vol-title-${i}`).value;
        vol.summary = document.getElementById(`fs-fo-vol-summary-${i}`).value;
        vol.key_characters = document.getElementById(`fs-fo-vol-chars-${i}`).value.split(',').map(s => s.trim()).filter(s => s);
        vol.major_events = document.getElementById(`fs-fo-vol-events-${i}`).value.split(',').map(s => s.trim()).filter(s => s);
        const start = parseInt(document.getElementById(`fs-fo-vol-start-${i}`).value) || 0;
        const end = parseInt(document.getElementById(`fs-fo-vol-end-${i}`).value) || 0;
        vol.chapter_range = [start, end];
        vol.tone = document.getElementById(`fs-fo-vol-tone-${i}`).value;
        vol.character_dynamics = (document.getElementById(`fs-fo-vol-dynamics-${i}`).value || '').split('\n').map(line => {
            const p = line.split('|').map(s => s.trim());
            if (!p[0]) return null;
            return { character: p[0] || '', emotion_state: p[1] || '', key_event: p[2] || '', emotion_change: p[3] || '' };
        }).filter(Boolean);
        vol.protagonist_abilities = (document.getElementById(`fs-fo-vol-abilities-${i}`).value || '').split('\n').map(line => {
            const p = line.split('|').map(s => s.trim());
            if (!p[0]) return null;
            return { ability: p[0] || '', state: p[1] || '', change: p[2] || '', trigger_event: p[3] || '' };
        }).filter(Boolean);
        vol.foreshadowing_ids = (document.getElementById(`fs-fo-vol-fsids-${i}`).value || '').split(',').map(s => s.trim()).filter(s => s);
    });

    fo.foreshadowing = (document.getElementById("fs-fo-foreshadowing").value || '').split('\n').map(line => {
        const p = line.split('|').map(s => s.trim());
        if (!p[0]) return null;
        const pv = p[2] ? parseInt(p[2]) : null;
        const payv = p[3] ? parseInt(p[3]) : null;
        return { id: p[0] || '', description: p[1] || '', planted_in_volume: pv, payoff_in_volume: payv, status: p[4] || '' };
    }).filter(Boolean);

    const novelId = getSelectedNovelId();
    if (novelId) {
        try {
            await apiPut(`/api/novels/${novelId}/outline/full`, { full_outline: fo });
        } catch (e) {
            alert("保存失败: " + e.message);
            return;
        }
    }
    currentFullOutline = fo;
    fullOutlineConfirmed = false;
    renderFullOutline(fo);
    updateStatusBar("全文大纲已修改，请重新确认大纲以使智能体读取最新版本");
    exitOutlineFullscreen();
}

function openOutlineFullscreen() {
    enterOutlineFullscreen();
    renderOutlineFullscreen();
}

function renderOutlineFullscreen() {
    document.getElementById("full-outline-fullscreen").style.display = "none";
    const fs = document.getElementById("outline-fullscreen");
    const chapters = currentOutline || [];

    let cardsHtml = "";
    if (chapters.length === 0) {
        cardsHtml = '<div class="outline-empty">暂无章节大纲</div>';
    }
    chapters.forEach((item, idx) => {
        cardsHtml += `
            <div class="outline-chapter-card" data-index="${idx}">
                <div class="outline-card-head">
                    <span class="outline-card-title">第 ${item.chapter_number || (idx + 1)} 章</span>
                    <button class="btn btn-sm btn-danger" onclick="deleteOutlineChapterInFullscreen(${idx})">删除</button>
                </div>
                <div class="outline-edit-fields">
                    <div class="form-group">
                        <label>章号</label>
                        <input type="number" class="outline-edit-input fs-ch-num" value="${escapeHtml(item.chapter_number || '')}">
                    </div>
                    <div class="form-group">
                        <label>标题</label>
                        <input type="text" class="outline-edit-input fs-ch-title" value="${escapeHtml(item.title || '')}">
                    </div>
                    <div class="form-group">
                        <label>情节摘要</label>
                        <textarea class="outline-edit-textarea fs-ch-summary" rows="4">${escapeHtml(item.plot_summary || '')}</textarea>
                    </div>
                    <div class="form-group">
                        <label>关键事件（每行一个）</label>
                        <textarea class="outline-edit-textarea fs-ch-events" rows="3">${escapeHtml((item.key_events || []).join('\n'))}</textarea>
                    </div>
                    <div class="form-group">
                        <label>涉及人物（每行一个）</label>
                        <textarea class="outline-edit-textarea fs-ch-characters" rows="2">${escapeHtml((item.characters || []).join('\n'))}</textarea>
                    </div>
                    <div class="form-group">
                        <label>备注</label>
                        <textarea class="outline-edit-textarea fs-ch-notes" rows="2">${escapeHtml(item.notes || '')}</textarea>
                    </div>
                </div>
            </div>
        `;
    });

    fs.innerHTML = `
        <div class="outline-fullscreen-header">
            <h2>章节大纲（展开编辑）</h2>
            <button class="btn btn-sm btn-outline" onclick="cancelOutlineFullscreen()">✕ 关闭</button>
        </div>
        <div class="outline-fullscreen-body">
            ${cardsHtml}
        </div>
        <div class="outline-fullscreen-actions">
            <button class="btn btn-outline" onclick="cancelOutlineFullscreen()">取消</button>
            <button class="btn btn-primary" onclick="saveOutlineFullscreen()">保存并返回</button>
        </div>
    `;
    fs.style.display = "flex";
    fs.scrollTop = 0;
}

function cancelOutlineFullscreen() {
    exitOutlineFullscreen();
}

function syncOutlineFullscreenToCurrent() {
    const next = [];
    const cards = document.querySelectorAll("#outline-fullscreen .outline-chapter-card");
    cards.forEach(card => {
        next.push({
            chapter_number: parseInt(card.querySelector(".fs-ch-num").value) || (next.length + 1),
            title: card.querySelector(".fs-ch-title").value,
            plot_summary: card.querySelector(".fs-ch-summary").value,
            key_events: card.querySelector(".fs-ch-events").value.split("\n").filter(s => s.trim()),
            characters: card.querySelector(".fs-ch-characters").value.split("\n").filter(s => s.trim()),
            notes: card.querySelector(".fs-ch-notes").value,
        });
    });
    currentOutline = next;
}

function deleteOutlineChapterInFullscreen(idx) {
    syncOutlineFullscreenToCurrent();
    if (!currentOutline[idx]) return;
    const item = currentOutline[idx];
    if (!confirm(`确定删除第${item.chapter_number}章「${item.title || '未命名'}」？`)) return;
    currentOutline.splice(idx, 1);
    outlineConfirmed = false;
    renderOutlineFullscreen();
}

async function saveOutlineFullscreen() {
    syncOutlineFullscreenToCurrent();
    const novelId = getSelectedNovelId();
    if (novelId) {
        try {
            await apiPut(`/api/novels/${novelId}/outline`, { outline: currentOutline });
        } catch (e) {
            alert("保存失败: " + e.message);
            return;
        }
    }
    outlineConfirmed = false;
    renderOutline();
    updateStatusBar("章节大纲已修改，请重新确认大纲");
    exitOutlineFullscreen();
}
