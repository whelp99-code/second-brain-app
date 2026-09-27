"use strict";

// Platform-neutral core. No Node APIs, filesystem paths outside the View Vault,
// credential persistence, dynamic script execution, or background workers.
const MAX_FILES = 20000;
const MAX_BYTES = 20 * 1024 * 1024;
const GENERATION = /^view-v1:[a-f0-9]{64}$/;
const HASH = /^[a-f0-9]{64}$/;
const PATH = /^Auto\/(Daily|People|Companies|Projects|Places|Events|Decisions|Questions|Evidence|System)\/[A-Za-z0-9_-]{1,180}\.md$/;

class SyncError extends Error {
    constructor(code) { super(code); this.name = "SyncError"; this.code = code; }
}
function fail(code) { throw new SyncError(code); }
function safePath(path) {
    if (typeof path !== "string" || (path !== "Home.md" && !PATH.test(path))) fail("UNSAFE_VIEW_PATH");
    return path;
}
function validGeneration(value) {
    if (typeof value !== "string" || !GENERATION.test(value)) fail("INVALID_VIEW_GENERATION");
    return value;
}
function endpoint(value) {
    let parsed;
    try { parsed = new URL(value); } catch (_) { fail("INVALID_SERVER_URL"); }
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
    if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && local)) fail("HTTPS_REQUIRED");
    if (parsed.username || parsed.password || parsed.search || parsed.hash) fail("INVALID_SERVER_URL");
    return parsed.href.replace(/\/$/, "");
}
async function sha256(text) {
    if (typeof text !== "string" || !globalThis.crypto?.subtle) fail("CRYPTO_UNAVAILABLE");
    const bytes = new TextEncoder().encode(text);
    const result = await globalThis.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(result), b => b.toString(16).padStart(2, "0")).join("");
}
function initialState(raw) {
    const state = { schema: 1, owned: {}, generation: null, status: "not_synced" };
    if (raw == null) return state;
    if (raw.schema !== 1 || !raw.owned || typeof raw.owned !== "object" || Array.isArray(raw.owned)) fail("INVALID_SYNC_STATE");
    if (Object.keys(raw.owned).length > MAX_FILES) fail("INVALID_SYNC_STATE");
    for (const [path, item] of Object.entries(raw.owned)) {
        safePath(path);
        if (!item || typeof item.hash !== "string" || !HASH.test(item.hash)) fail("INVALID_SYNC_STATE");
        state.owned[path] = { hash: item.hash, withdrawn: item.withdrawn === true };
    }
    if (raw.generation != null) state.generation = validGeneration(raw.generation);
    state.status = ["complete", "not_synced", "applying", "conflict", "ack_pending"].includes(raw.status) ? raw.status : "not_synced";
    return state;
}
function copyState(state) { return JSON.parse(JSON.stringify(state)); }
async function loadSnapshot(fetchPage, onProgress = () => {}) {
    let cursor = null, generation = null, total = null, offset = 0, byteCount = 0;
    const files = [], paths = new Set(), cursors = new Set();
    do {
        if (cursor !== null) {
            if (typeof cursor !== "string" || cursor.length > 512 || cursors.has(cursor)) fail("INVALID_VIEW_CURSOR");
            cursors.add(cursor);
        }
        const page = await fetchPage(cursor);
        if (!page || page.schema_version !== 1 || !Array.isArray(page.files) || page.replace_owned !== true) fail("INVALID_MANIFEST");
        const current = validGeneration(page.generation);
        if (generation !== null && current !== generation) fail("VIEW_CHANGED_DURING_FETCH");
        generation = current;
        if (!Number.isSafeInteger(page.total_files) || page.total_files < 0 || page.total_files > MAX_FILES) fail("VIEW_TOO_LARGE");
        if (total !== null && total !== page.total_files) fail("INVALID_MANIFEST_TOTAL");
        total = page.total_files;
        if (page.offset !== offset || page.files.length > 100) fail("INVALID_MANIFEST_OFFSET");
        for (const file of page.files) {
            safePath(file?.path);
            if (paths.has(file.path)) fail("DUPLICATE_VIEW_PATH");
            if (!Number.isSafeInteger(file.revision) || file.revision < 1 || typeof file.object_id !== "string" || file.object_id.length > 512) fail("INVALID_VIEW_OBJECT");
            if (typeof file.content !== "string" || typeof file.sha256 !== "string" || !HASH.test(file.sha256)) fail("INVALID_VIEW_CONTENT");
            const bytes = new TextEncoder().encode(file.content).length;
            byteCount += bytes;
            if (bytes > 1024 * 1024 || byteCount > MAX_BYTES) fail("VIEW_TOO_LARGE");
            if (await sha256(file.content) !== file.sha256) fail("VIEW_HASH_MISMATCH");
            paths.add(file.path);
            files.push({ path: file.path, objectId: file.object_id, revision: file.revision, hash: file.sha256, content: file.content });
        }
        offset += page.files.length;
        if (offset > total) fail("INVALID_MANIFEST_TOTAL");
        cursor = page.next_cursor;
        if (cursor === null) {
            if (page.inventory_complete !== true || offset !== total) fail("INCOMPLETE_VIEW_INVENTORY");
        } else if (page.inventory_complete !== false || !page.files.length) fail("INVALID_MANIFEST_CURSOR");
        onProgress({ state: "fetching", received: offset, total });
    } while (cursor !== null);
    return { generation, files, paths };
}
function withdrawalContent() {
    return "---\nsb_managed: true\nsb_withdrawn: true\n---\n\n# 사용할 수 없는 기록\n\n원본이 삭제·철회되었거나 현재 허용된 뷰에서 제외되었습니다. 이전 내용을 현재 기억으로 사용하지 않습니다.\n";
}
async function synchronize({ adapter, fetchPage, acknowledge, state: rawState, persist, onProgress = () => {} }) {
    const state = initialState(rawState);
    // Download and validate the entire inventory before changing any files.
    const snapshot = await loadSnapshot(fetchPage, onProgress);
    state.status = "applying";
    const save = async () => persist(copyState(state));
    await save();
    const conflicts = [];
    let written = 0, withdrawn = 0;
    // Withdrawal precedes newly displayed content. Never physically unlink a file
    // after a non-atomic read check: replace with an inert tombstone atomically.
    for (const path of Object.keys(state.owned).sort()) {
        if (snapshot.paths.has(path)) continue;
        const current = await adapter.read(safePath(path));
        if (current === null) { delete state.owned[path]; await save(); continue; }
        if (await sha256(current) !== state.owned[path].hash) { conflicts.push({ path, kind: "withdrawal_user_edit" }); continue; }
        const replacement = withdrawalContent();
        try {
            if (current !== replacement) await adapter.atomicWrite(path, current, replacement);
        } catch (error) {
            if (error?.code === "LOCAL_EDIT_CONFLICT") { conflicts.push({ path, kind: "withdrawal_race" }); continue; }
            throw error;
        }
        state.owned[path] = { hash: await sha256(replacement), withdrawn: true };
        withdrawn++;
        await save();
    }
    for (const file of snapshot.files) {
        const current = await adapter.read(file.path);
        const currentHash = current === null ? null : await sha256(current);
        const tracked = state.owned[file.path];
        if (currentHash !== file.hash && current !== null && (!tracked || currentHash !== tracked.hash)) {
            conflicts.push({ path: file.path, kind: "user_edit" }); continue;
        }
        try {
            if (currentHash !== file.hash) {
                await adapter.atomicWrite(file.path, current, file.content);
                written++;
            }
        } catch (error) {
            if (error?.code === "LOCAL_EDIT_CONFLICT") { conflicts.push({ path: file.path, kind: "write_race" }); continue; }
            throw error;
        }
        state.owned[file.path] = { hash: file.hash, withdrawn: false };
        await save();
        onProgress({ state: "applying", written, withdrawn, conflicts: conflicts.length });
    }
    if (conflicts.length) {
        state.status = "conflict";
        await save();
        return { state, written, withdrawn, conflicts, acknowledged: false };
    }
    state.status = "ack_pending";
    await save();
    const result = await acknowledge(snapshot.generation);
    if (!result || result.acknowledged !== true || result.generation !== snapshot.generation) fail("VIEW_ACK_REJECTED");
    state.generation = snapshot.generation;
    state.status = "complete";
    await save();
    return { state, written, withdrawn, conflicts: [], acknowledged: true };
}

module.exports = { SyncError, safePath, validGeneration, endpoint, sha256, initialState, loadSnapshot, synchronize, withdrawalContent };
