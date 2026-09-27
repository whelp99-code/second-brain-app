"use strict";
const { Plugin, PluginSettingTab, Setting, Modal, Notice, TFile, requestUrl } = require("obsidian");
const Core = require("./sync-core");

function code(error) { return /^[A-Z0-9_]+$/.test(error?.code || "") ? error.code : "REQUEST_FAILED"; }
function el(parent, tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    parent.appendChild(item);
    return item;
}
function button(parent, title, callback) {
    const item = el(parent, "button", title);
    item.addEventListener("click", () => Promise.resolve().then(callback).catch(error => new Notice(`Second Brain: ${code(error)}`)));
    return item;
}
class TextDialog extends Modal {
    constructor(plugin, title, text) { super(plugin.app); this.title = title; this.text = text; }
    onOpen() { this.contentEl.replaceChildren(); el(this.contentEl, "h2", this.title); el(this.contentEl, "pre", this.text, "sb-memory-evidence"); }
    onClose() { this.contentEl.replaceChildren(); }
}
class ConnectDialog extends Modal {
    constructor(plugin) { super(plugin.app); this.plugin = plugin; }
    onOpen() {
        const root = this.contentEl; root.replaceChildren();
        el(root, "h2", "Second Brain 연결");
        el(root, "p", "전용 MemoryView Vault에서 사용하세요. 토큰은 이번 앱 세션의 메모리에만 보관하며 data.json에 저장하지 않습니다.");
        el(root, "label", "서버 주소 (HTTPS, 로컬 시험은 loopback HTTP)");
        const server = el(root, "input"); server.type = "url"; server.value = this.plugin.settings.server;
        server.placeholder = "https://your-private-server";
        el(root, "label", "기기 범위가 제한된 토큰");
        const token = el(root, "input"); token.type = "password"; token.autocomplete = "off";
        const status = el(root, "p", "관리자 토큰은 사용하지 않습니다.");
        button(root, "연결", async () => {
            const target = Core.endpoint(server.value);
            const old = this.plugin.settings.server;
            if (old && Core.endpoint(old) !== target && Object.keys(this.plugin.syncState.owned).length) throw new Core.SyncError("NEW_SERVER_REQUIRES_NEW_VIEW_VAULT");
            this.plugin.settings.server = target;
            this.plugin.sessionToken = token.value; token.value = "";
            status.textContent = "인증 확인 중";
            try {
                const health = await this.plugin.api("/health");
                if (health.client_id === "local-owner") throw new Core.SyncError("DEVICE_TOKEN_REQUIRED");
                this.plugin.health = health;
                const permitted = health.sources_configured?.filter(s => s.enabled) || [];
                if (!this.plugin.settings.sourceId && permitted.length === 1) this.plugin.settings.sourceId = permitted[0].source_id;
                await this.plugin.saveSettings();
                this.plugin.status("연결됨 · 새로고침 가능");
                this.close();
                await this.plugin.sync();
            } catch (error) {
                this.plugin.sessionToken = ""; status.textContent = code(error); throw error;
            }
        });
    }
    onClose() { this.contentEl.replaceChildren(); }
}
class CorrectionDialog extends Modal {
    constructor(plugin, event) { super(plugin.app); this.plugin = plugin; this.event = event; this.key = `obsidian-correct:${crypto.randomUUID()}`; }
    onOpen() {
        const root = this.contentEl; root.replaceChildren();
        el(root, "h2", "기록 정정");
        el(root, "p", `기준 개정 ${this.event.revision} · 원본을 덮어쓰지 않고 새 개정으로 남깁니다.`);
        const title = el(root, "input"); title.value = this.event.title;
        const body = el(root, "textarea"); body.value = this.event.body; body.rows = 12;
        const state = el(root, "select");
        for (const [value, label] of Object.entries({ planned: "예정", occurred: "발생 기록", cancelled: "취소", unknown: "미확인" })) {
            const item = el(state, "option", label); item.value = value;
        }
        state.value = this.event.event_status;
        const reason = el(root, "input"); reason.placeholder = "정정 이유";
        const status = el(root, "p", "");
        let pending = null;
        button(root, "정정 요청", async () => {
            if (!reason.value.trim()) throw new Core.SyncError("CORRECTION_REASON_REQUIRED");
            const request = { idempotency_key: this.key, event_id: this.event.event_id, expected_revision: this.event.revision,
                reason: reason.value, changes: { title: title.value, body: body.value, event_status: state.value } };
            if (pending && JSON.stringify(pending) !== JSON.stringify(request)) throw new Core.SyncError("RETRY_PAYLOAD_CHANGED");
            pending = request; status.textContent = "정정 요청 중";
            const result = await this.plugin.api("/corrections", "POST", pending);
            status.textContent = `접수 ${result.receipt_id}`;
            this.close(); await this.plugin.sync();
        });
    }
    onClose() { this.contentEl.replaceChildren(); }
}
class QuestionsDialog extends Modal {
    constructor(plugin, questions) { super(plugin.app); this.plugin = plugin; this.questions = questions; }
    onOpen() {
        const root = this.contentEl; root.replaceChildren(); el(root, "h2", "중요한 빈칸");
        if (!this.questions.length) el(root, "p", "현재 확인할 질문이 없습니다.");
        for (const question of this.questions) {
            const section = el(root, "section", undefined, "sb-memory-question");
            el(section, "p", question.prompt);
            const answer = el(section, "textarea"); answer.rows = 3;
            const state = el(section, "select");
            for (const [value, label] of Object.entries({ "": "진행 상태는 바꾸지 않음", occurred: "진행됨", cancelled: "취소됨", unknown: "모르겠음" })) {
                const item = el(state, "option", label); item.value = value;
            }
            const status = el(section, "p", "");
            const keys = {};
            for (const [action, label] of Object.entries({ answer: "답변", skip: "건너뛰기", mute: "다시 묻지 않기" })) {
                button(section, label, async () => {
                    if (action === "answer" && !answer.value.trim()) throw new Core.SyncError("ANSWER_REQUIRED");
                    keys[action] ||= `obsidian-answer:${crypto.randomUUID()}`;
                    const body = { action, idempotency_key: keys[action], expected_revision: question.event_revision };
                    if (action === "answer") { body.answer = answer.value; if (state.value) body.event_status = state.value; }
                    const result = await this.plugin.api(`/questions/${encodeURIComponent(question.question_id)}/response`, "POST", body);
                    status.textContent = `접수 ${result.receipt_id}`;
                    section.querySelectorAll("button").forEach(item => { item.disabled = true; });
                    await this.plugin.sync();
                });
            }
        }
    }
    onClose() { this.contentEl.replaceChildren(); }
}
class RelationsDialog extends Modal {
    constructor(plugin, data) { super(plugin.app); this.plugin = plugin; this.data = data; }
    onOpen() {
        const root = this.contentEl; root.replaceChildren(); el(root, "h2", "근거로 연결된 기억");
        el(root, "p", this.data.note || "관계는 원출처의 연결 정보입니다.");
        const filter = el(root, "select");
        for (const value of ["all", "person", "company", "project", "place", "decision"]) {
            const option = el(filter, "option", value); option.value = value;
        }
        const list = el(root, "div");
        const render = () => {
            list.replaceChildren();
            const nodes = new Map(this.data.nodes.map(n => [n.id, n]));
            let shown = 0;
            for (const edge of this.data.edges) {
                const target = nodes.get(edge.to), source = nodes.get(edge.from);
                if (!target || !source || (filter.value !== "all" && target.kind !== filter.value)) continue;
                if (shown++ >= 500) { el(list, "p", "표시 한도 500개. 필터로 범위를 좁혀주세요."); break; }
                const row = el(list, "p");
                row.textContent = `${source.name} → ${target.name} · ${edge.relation} · ${edge.evidence_level}`;
            }
            if (!shown) el(list, "p", "이 범위의 관계가 없습니다.");
        };
        filter.addEventListener("change", render); render();
    }
    onClose() { this.contentEl.replaceChildren(); }
}
class MemorySettings extends PluginSettingTab {
    constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
    display() {
        this.containerEl.replaceChildren();
        new Setting(this.containerEl).setName("Second Brain MemoryView").setDesc("Auto/는 서버 뷰, MyNotes/는 사용자 원본입니다. 같은 Auto 영역에 다른 동기화 작성자를 연결하지 마세요.");
        new Setting(this.containerEl).setName("연결").setDesc(this.plugin.settings.server || "연결되지 않음").addButton(b => b.setButtonText("연결 / 토큰 입력").onClick(() => new ConnectDialog(this.plugin).open()));
        new Setting(this.containerEl).setName("기억에 저장할 출처 ID").setDesc("서버에서 허용한 출처 ID만 사용합니다. 예: phone").addText(t => t.setValue(this.plugin.settings.sourceId).onChange(async value => {
            if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(value)) return;
            this.plugin.settings.sourceId = value; await this.plugin.saveSettings();
        }));
        new Setting(this.containerEl).setName("동기화 상태").setDesc(this.plugin.syncState.status).addButton(b => b.setButtonText("새로고침").onClick(() => this.plugin.sync().catch(e => new Notice(code(e)))));
        new Setting(this.containerEl).setName("연결 해제").setDesc("세션 토큰만 지웁니다. MyNotes와 기존 오프라인 뷰는 삭제하지 않습니다.").addButton(b => b.setButtonText("연결 해제").onClick(() => {
            this.plugin.sessionToken = ""; this.plugin.status("연결 해제 · 오프라인 뷰");
        }));
    }
}
class SecondBrainMemoryView extends Plugin {
    async onload() {
        this.disposed = false; this.sessionToken = ""; this.syncing = false; this.capturing = false;
        const raw = await this.loadData() || {};
        this.settings = { server: typeof raw.server === "string" ? raw.server : "", sourceId: typeof raw.sourceId === "string" ? raw.sourceId : "",
            deviceId: /^[a-f0-9-]{36}$/.test(raw.deviceId || "") ? raw.deviceId : crypto.randomUUID() };
        this.syncState = Core.initialState(raw.syncState);
        this.captureIntents = raw.captureIntents && typeof raw.captureIntents === "object" && !Array.isArray(raw.captureIntents) ? raw.captureIntents : {};
        this.statusEl = this.addStatusBarItem(); this.status("연결 필요");
        this.addRibbonIcon("book-open", "Second Brain 기억 새로고침", () => this.sync().catch(e => new Notice(code(e))));
        this.addCommand({ id: "connect-memory", name: "서버 연결 / 세션 토큰 입력", callback: () => new ConnectDialog(this).open() });
        this.addCommand({ id: "sync-memory", name: "기억 뷰 새로고침", callback: () => this.sync().catch(e => new Notice(code(e))) });
        this.addCommand({ id: "capture-current-note", name: "현재 MyNotes 메모를 기억에 저장", callback: () => this.captureCurrent().catch(e => new Notice(code(e))) });
        this.addCommand({ id: "process-captured-memory", name: "접수한 기록 처리", callback: () => this.processCaptured().catch(e => new Notice(code(e))) });
        this.addCommand({ id: "correct-current-event", name: "현재 사건 정정", callback: () => this.correctCurrent().catch(e => new Notice(code(e))) });
        this.addCommand({ id: "answer-memory-questions", name: "중요한 빈칸 확인", callback: () => this.showQuestions().catch(e => new Notice(code(e))) });
        this.addCommand({ id: "show-memory-relations", name: "관계 패널", callback: () => this.showRelations().catch(e => new Notice(code(e))) });
        this.addSettingTab(new MemorySettings(this.app, this));
        this.registerObsidianProtocolHandler("sb-memory", params => this.openEvidence(params).catch(e => new Notice(code(e))));
        this.registerDomEvent(document, "visibilitychange", () => {
            if (document.visibilityState === "visible" && this.sessionToken) this.sync(false).catch(e => this.status(code(e)));
        });
        this.app.workspace.onLayoutReady(() => { if (this.sessionToken) this.sync(false).catch(e => this.status(code(e))); });
    }
    onunload() { this.disposed = true; this.sessionToken = ""; }
    status(message) { if (!this.disposed && this.statusEl) this.statusEl.textContent = `SB · ${message}`; }
    async saveSettings() {
        if (this.disposed) throw new Core.SyncError("PLUGIN_UNLOADED");
        // Deliberate whitelist: sessionToken, raw source text and HTTP headers never persist.
        await this.saveData({ server: this.settings.server, sourceId: this.settings.sourceId, deviceId: this.settings.deviceId,
            syncState: Core.initialState(this.syncState), captureIntents: this.captureIntents });
    }
    async api(path, method = "GET", body = undefined) {
        if (this.disposed) throw new Core.SyncError("PLUGIN_UNLOADED");
        if (!this.sessionToken) throw new Core.SyncError("SESSION_TOKEN_REQUIRED");
        if (!path.startsWith("/") || path.includes("..") || path.startsWith("//")) throw new Core.SyncError("INVALID_API_PATH");
        let response;
        try {
            response = await requestUrl({ url: Core.endpoint(this.settings.server) + "/api/life/v1" + path, method,
                headers: { Authorization: `Bearer ${this.sessionToken}`, "Content-Type": "application/json" },
                body: body === undefined ? undefined : JSON.stringify(body), throw: false });
        } catch (_) { throw new Core.SyncError("SERVER_UNAVAILABLE"); }
        if (this.disposed) throw new Core.SyncError("PLUGIN_UNLOADED");
        let result;
        try { result = response.json; } catch (_) { throw new Core.SyncError("INVALID_SERVER_RESPONSE"); }
        if (response.status >= 400) {
            if (response.status === 401) this.sessionToken = "";
            const error = new Core.SyncError(/^[A-Z0-9_]+$/.test(result?.error || "") ? result.error : `HTTP_${response.status}`);
            error.httpStatus = response.status; throw error;
        }
        return result;
    }
    adapter() {
        return {
            read: async path => {
                Core.safePath(path);
                if (this.disposed) throw new Core.SyncError("PLUGIN_UNLOADED");
                const file = this.app.vault.getAbstractFileByPath(path);
                if (!file) return null;
                if (!(file instanceof TFile)) throw new Core.SyncError("LOCAL_PATH_IS_NOT_FILE");
                return this.app.vault.read(file);
            },
            atomicWrite: async (path, expected, content) => {
                Core.safePath(path);
                if (this.disposed) throw new Core.SyncError("PLUGIN_UNLOADED");
                const file = this.app.vault.getAbstractFileByPath(path);
                if (expected === null) {
                    if (file) throw new Core.SyncError("LOCAL_EDIT_CONFLICT");
                    const parts = path.split("/"); parts.pop();
                    let folder = "";
                    for (const part of parts) {
                        folder = folder ? `${folder}/${part}` : part;
                        if (!this.app.vault.getAbstractFileByPath(folder)) await this.app.vault.createFolder(folder);
                    }
                    if (this.disposed || this.app.vault.getAbstractFileByPath(path)) throw new Core.SyncError("LOCAL_EDIT_CONFLICT");
                    await this.app.vault.create(path, content);
                } else {
                    if (!(file instanceof TFile) || file.path !== path) throw new Core.SyncError("LOCAL_EDIT_CONFLICT");
                    await this.app.vault.process(file, current => {
                        if (this.disposed || file.path !== path || current !== expected) throw new Core.SyncError("LOCAL_EDIT_CONFLICT");
                        return content;
                    });
                }
            }
        };
    }
    async sync(interactive = true) {
        if (this.syncing || this.disposed) return;
        if (!this.sessionToken) { if (interactive) new ConnectDialog(this).open(); return; }
        this.syncing = true; this.status("검증·동기화 중");
        try {
            const result = await Core.synchronize({ adapter: this.adapter(), state: this.syncState,
                fetchPage: cursor => this.api("/views/obsidian/manifest" + (cursor ? `?cursor=${encodeURIComponent(cursor)}` : "")),
                acknowledge: generation => this.api("/views/obsidian/ack", "POST", { generation }),
                persist: async state => { this.syncState = state; await this.saveSettings(); },
                onProgress: progress => this.status(progress.state === "fetching" ? `수신 ${progress.received}/${progress.total}` : "파일 적용 중") });
            this.status(result.acknowledged ? `완료 · 갱신 ${result.written}` : `사용자 편집 충돌 ${result.conflicts.length}`);
            if (result.conflicts.length && interactive) new TextDialog(this, "보존한 사용자 수정본", result.conflicts.map(c => `${c.path}: ${c.kind}`).join("\n") + "\n\n내용을 MyNotes에 보존하거나 정정 요청한 뒤 관리형 파일을 별도 확인하세요. 자동 덮어쓰기는 하지 않았습니다.").open();
        } catch (error) { this.status(code(error)); throw error; }
        finally { this.syncing = false; }
    }
    async processCaptured() {
        const result = await this.api("/run", "POST", {});
        new Notice(`기록 ${result.processed}개 처리 · 알림 전달은 별도입니다.`);
        await this.sync();
    }
    async captureCurrent() {
        if (this.capturing) throw new Core.SyncError("CAPTURE_ALREADY_RUNNING");
        const file = this.app.workspace.getActiveFile();
        if (!(file instanceof TFile) || !file.path.startsWith("MyNotes/") || file.extension !== "md") throw new Core.SyncError("SELECT_MYNOTES_MARKDOWN");
        if (!this.settings.sourceId) throw new Core.SyncError("CAPTURE_SOURCE_REQUIRED");
        this.capturing = true;
        try {
            const body = await this.app.vault.read(file);
            const hash = await Core.sha256(body);
            const itemId = `obsidian:${this.settings.deviceId}:${await Core.sha256(file.path)}`;
            const intentKey = await Core.sha256(itemId + "\0" + hash);
            let intent = this.captureIntents[intentKey];
            if (!intent) {
                let previous = null;
                try { previous = await this.api(`/event-lookup?source_id=${encodeURIComponent(this.settings.sourceId)}&source_item_id=${encodeURIComponent(itemId)}`); }
                catch (error) { if (error.code !== "LIFE_EVENT_NOT_FOUND") throw error; }
                intent = { sourceId: this.settings.sourceId, itemId, sourceVersion: hash, title: file.basename,
                    issuedAt: new Date().toISOString(), key: `obsidian:${intentKey}`, expected: previous ? { [previous.event_id]: previous.revision } : {} };
                this.captureIntents[intentKey] = intent; await this.saveSettings();
            }
            if (intent.sourceId !== this.settings.sourceId || intent.sourceVersion !== hash) throw new Core.SyncError("CAPTURE_INTENT_CHANGED");
            const result = await this.api("/events:batch", "POST", { idempotency_key: intent.key, expected_revisions: intent.expected,
                events: [{ source_id: intent.sourceId, source_item_id: intent.itemId, source_version: hash,
                    title: intent.title, body, event_type: "note_saved", event_status: "occurred", evidence_level: "user_asserted",
                    occurred_start: intent.issuedAt, observed_at: intent.issuedAt, timezone: "Asia/Seoul", time_precision: "exact" }] });
            const receipt = await this.api(`/receipts/${encodeURIComponent(result.receipt_id)}`);
            intent.receiptId = receipt.receipt_id; await this.saveSettings();
            new Notice("영속 접수 완료. ‘접수한 기록 처리’ 명령으로 검색 반영을 확인하세요.");
        } finally { this.capturing = false; }
    }
    async correctCurrent() {
        const file = this.app.workspace.getActiveFile();
        if (!(file instanceof TFile)) throw new Core.SyncError("SELECT_EVENT_NOTE");
        const metadata = this.app.metadataCache.getFileCache(file)?.frontmatter;
        const eventId = metadata?.sb_object_id;
        if (!/^[a-f0-9-]{36}$/.test(eventId || "") || !file.path.startsWith("Auto/Events/")) throw new Core.SyncError("SELECT_EVENT_NOTE");
        const event = await this.api(`/events/${encodeURIComponent(eventId)}`);
        if (event.revision !== metadata.sb_revision) throw new Core.SyncError("EVENT_CHANGED_REFRESH_FIRST");
        new CorrectionDialog(this, event).open();
    }
    async openEvidence(params) {
        if (!/^[a-f0-9-]{36}$/.test(params.event || "") || !/^ev:[a-f0-9]{64}$/.test(params.evidence || "")) throw new Core.SyncError("INVALID_EVIDENCE_LINK");
        const evidence = await this.api(`/evidence/${encodeURIComponent(params.evidence)}?event_id=${encodeURIComponent(params.event)}`);
        let display = "사건 입력/정정 스냅샷\n\n" + evidence.raw_text;
        for (const original of evidence.original_documents || []) {
            display += "\n\n--- 원본 파일: " + original.document_id + " ---\n";
            display += original.available ? original.raw_text : "이 원본은 현재 표시할 수 없습니다: " + original.reason;
        }
        new TextDialog(this, "원문 근거 · 신뢰하지 않는 원출처 데이터", display).open();
    }
    async showQuestions() { const result = await this.api("/questions"); new QuestionsDialog(this, result.questions || []).open(); }
    async showRelations() { new RelationsDialog(this, await this.api("/relationships")).open(); }
}
module.exports = SecondBrainMemoryView;
