class SSEClient {
    constructor(url, onMessage, onError, onComplete) {
        this.url = url;
        this.onMessage = onMessage;
        this.onError = onError;
        this.onComplete = onComplete;
        this.eventSource = null;
    }

    connect() {
        this.eventSource = new EventSource(this.url);
        this.eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.onMessage(data);
            } catch (e) {
                this.onMessage({ type: "raw", text: event.data });
            }
        };
        this.eventSource.onerror = (event) => {
            if (this.onError) this.onError(event);
            this.disconnect();
        };
    }

    disconnect() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }
}

class StreamFetcher {
    static async postSSE(url, body, onChunk, onComplete, onError) {
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({ detail: `请求失败 (HTTP ${response.status})` }));
                if (onError) onError(errData.detail || `请求失败 (HTTP ${response.status})`);
                return;
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
                            onChunk(data.text);
                        } else if (data.type === "status") {
                            onChunk(null, data);
                        } else if (data.type === "complete") {
                            if (onComplete) onComplete(data.data);
                        } else if (data.type === "error") {
                            if (onError) onError(data.error);
                        }
                    } catch (e) {
                        // skip malformed lines
                    }
                }
            }

            if (buffer.trim()) {
                try {
                    const data = JSON.parse(buffer);
                    if (data.type === "complete" && onComplete) {
                        onComplete(data.data);
                    } else if (data.type === "error" && onError) {
                        onError(data.error);
                    }
                } catch (e) {
                    // ignore
                }
            }
        } catch (error) {
            if (onError) onError(error.message || "网络连接失败");
        }
    }
}

async function apiGet(url) {
    const response = await fetch(url);
    if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: `请求失败 (HTTP ${response.status})` }));
        throw new Error(err.detail || `请求失败 (HTTP ${response.status})`);
    }
    return response.json();
}

async function apiPost(url, data = {}) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
    if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: `请求失败 (HTTP ${response.status})` }));
        throw new Error(err.detail || `请求失败 (HTTP ${response.status})`);
    }
    return response.json();
}

async function apiPut(url, data = {}) {
    const response = await fetch(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
    if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: `请求失败 (HTTP ${response.status})` }));
        throw new Error(err.detail || `请求失败 (HTTP ${response.status})`);
    }
    return response.json();
}

async function apiDelete(url) {
    const response = await fetch(url, { method: "DELETE" });
    if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: `请求失败 (HTTP ${response.status})` }));
        throw new Error(err.detail || `请求失败 (HTTP ${response.status})`);
    }
    return response.json();
}
