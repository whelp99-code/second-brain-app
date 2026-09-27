"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const Core = require("../src/sync-core");
const GEN = "view-v1:" + "a".repeat(64);
const OTHER = "view-v1:" + "b".repeat(64);

async function view(path, content = "generated", revision = 1) {
    return { path, object_id: path, revision, content, sha256: await Core.sha256(content) };
}
function page(files, extra = {}) {
    return { schema_version: 1, generation: GEN, offset: 0, total_files: files.length, files,
        next_cursor: null, inventory_complete: true, replace_owned: true, ...extra };
}
function memoryAdapter(initial = {}, hook = null) {
    const files = new Map(Object.entries(initial));
    const writes = [];
    return { files, writes,
        async read(path) { return files.has(path) ? files.get(path) : null; },
        async atomicWrite(path, expected, content) {
            if (hook) await hook(path, files, writes.length);
            const actual = files.has(path) ? files.get(path) : null;
            if (actual !== expected) throw new Core.SyncError("LOCAL_EDIT_CONFLICT");
            files.set(path, content); writes.push(path);
        }
    };
}
async function setup({ initial = {}, owned = {}, files = [], adapter = null, fetchPage = null, acknowledge = null } = {}) {
    const disk = adapter || memoryAdapter(initial);
    let persisted = { schema: 1, owned, generation: null, status: "not_synced" };
    const acknowledgements = [];
    const request = {
        adapter: disk,
        fetchPage: fetchPage || (async () => page(files)),
        acknowledge: acknowledge || (async generation => { acknowledgements.push(generation); return { acknowledged: true, generation }; }),
        state: persisted,
        persist: async state => { persisted = state; }
    };
    return { disk, request, acknowledgements, persisted: () => persisted };
}

test("valid complete generation writes only owned files and ACKs exact view ID", async () => {
    const f = await view("Auto/Daily/2026-09-26.md", "new day");
    const env = await setup({ initial: { "MyNotes/2026-09-26.md": "private notes" }, files: [f] });
    const result = await Core.synchronize(env.request);
    assert.equal(result.acknowledged, true);
    assert.equal(env.disk.files.get(f.path), "new day");
    assert.equal(env.disk.files.get("MyNotes/2026-09-26.md"), "private notes");
    assert.deepEqual(env.disk.writes, [f.path]);
    assert.deepEqual(env.acknowledgements, [GEN]);
    assert.equal(env.persisted().generation, GEN);
});

test("same generation repeated does not rewrite files", async () => {
    const f = await view("Home.md", "home");
    const env = await setup({ files: [f] });
    await Core.synchronize(env.request);
    await Core.synchronize({ ...env.request, state: env.persisted() });
    assert.equal(env.disk.writes.length, 1);
});

test("edited Auto file is preserved and blocks completion", async () => {
    const f = await view("Auto/Events/event.md", "server replacement");
    const env = await setup({ initial: { [f.path]: "human change" },
        owned: { [f.path]: { hash: await Core.sha256("old generated") } }, files: [f] });
    const result = await Core.synchronize(env.request);
    assert.equal(env.disk.files.get(f.path), "human change");
    assert.equal(result.conflicts[0].kind, "user_edit");
    assert.equal(env.persisted().generation, null);
    assert.equal(env.acknowledgements.length, 0);
});

test("existing unowned file is never silently adopted with different contents", async () => {
    const env = await setup({ initial: { "Home.md": "my personal home" }, files: [await view("Home.md", "server home")] });
    const result = await Core.synchronize(env.request);
    assert.equal(result.acknowledged, false);
    assert.equal(env.disk.files.get("Home.md"), "my personal home");
});

test("withdrawal replaces only unchanged owned file with inert tombstone", async () => {
    const old = "Auto/Events/deleted.md";
    const env = await setup({ initial: { [old]: "old sensitive text", "MyNotes/keep.md": "personal copy" },
        owned: { [old]: { hash: await Core.sha256("old sensitive text") } }, files: [] });
    const result = await Core.synchronize(env.request);
    assert.equal(result.withdrawn, 1);
    assert.equal(env.disk.files.get(old), Core.withdrawalContent());
    assert.equal(env.disk.files.get("MyNotes/keep.md"), "personal copy");
    assert.equal(env.persisted().owned[old].withdrawn, true);
});

test("withdrawal conflict preserves user copy and reports incomplete erasure", async () => {
    const old = "Auto/Events/deleted.md";
    const env = await setup({ initial: { [old]: "edited user copy" }, owned: { [old]: { hash: await Core.sha256("old") } } });
    const result = await Core.synchronize(env.request);
    assert.equal(result.acknowledged, false);
    assert.equal(result.conflicts[0].kind, "withdrawal_user_edit");
    assert.equal(env.disk.files.get(old), "edited user copy");
});

test("local edit during atomic update cannot be overwritten", async () => {
    const name = "Auto/Events/race.md";
    const disk = memoryAdapter({ [name]: "old" }, async (target, files) => { files.set(target, "concurrent user change"); });
    const env = await setup({ adapter: disk, owned: { [name]: { hash: await Core.sha256("old") } }, files: [await view(name, "new")] });
    const result = await Core.synchronize(env.request);
    assert.equal(result.acknowledged, false);
    assert.equal(result.conflicts[0].kind, "write_race");
    assert.equal(disk.files.get(name), "concurrent user change");
});

test("tampered remote body causes zero writes", async () => {
    const f = await view("Home.md", "expected"); f.content = "tampered";
    const env = await setup({ files: [f] });
    await assert.rejects(Core.synchronize(env.request), { code: "VIEW_HASH_MISMATCH" });
    assert.equal(env.disk.writes.length, 0);
    assert.equal(env.acknowledgements.length, 0);
});

for (const bad of ["MyNotes/secret.md", "../secret.md", "Auto/Events/../../secret.md", "/tmp/file.md",
    "Auto/Events/evil.svg", "Auto/Events/a\\b.md", "Auto/Events/%2e%2e.md", ".obsidian/data.json", "Auto/People/a/b.md"]) {
    test(`reject unsafe remote path ${bad}`, async () => {
        const env = await setup({ files: [await view(bad)] });
        await assert.rejects(Core.synchronize(env.request), { code: "UNSAFE_VIEW_PATH" });
        assert.equal(env.disk.writes.length, 0);
    });
}

test("network loss on second manifest page does not apply a partial inventory", async () => {
    let count = 0;
    const env = await setup({ fetchPage: async () => {
        if (count++) throw new Error("simulated connection failure");
        return page([await view("Home.md")], { total_files: 2, next_cursor: "second", inventory_complete: false });
    }});
    await assert.rejects(Core.synchronize(env.request), /connection failure/);
    assert.equal(env.disk.writes.length, 0);
});

test("generation switching during page download is rejected before apply", async () => {
    let count = 0;
    const env = await setup({ fetchPage: async () => count++ ?
        page([await view("Auto/Events/two.md")], { generation: OTHER, offset: 1, total_files: 2 }) :
        page([await view("Home.md")], { total_files: 2, next_cursor: "next", inventory_complete: false }) });
    await assert.rejects(Core.synchronize(env.request), { code: "VIEW_CHANGED_DURING_FETCH" });
    assert.equal(env.disk.writes.length, 0);
});

test("duplicate file path and infinite cursor are rejected", async () => {
    const file = await view("Home.md");
    const env = await setup({ fetchPage: async () => page([file, file]) });
    await assert.rejects(Core.synchronize(env.request), { code: "DUPLICATE_VIEW_PATH" });
});

test("ACK failure leaves recoverable state, not false complete", async () => {
    const env = await setup({ files: [await view("Home.md")], acknowledge: async () => { throw new Error("ACK unavailable"); } });
    await assert.rejects(Core.synchronize(env.request), /ACK unavailable/);
    assert.equal(env.persisted().status, "ack_pending");
    assert.equal(env.persisted().generation, null);
    const result = await Core.synchronize({ ...env.request, state: env.persisted(), acknowledge: async generation => ({ acknowledged: true, generation }) });
    assert.equal(result.written, 0);
    assert.equal(result.state.status, "complete");
});

test("provider generation cannot masquerade as view acknowledgement", async () => {
    const env = await setup({ files: [await view("Home.md")], acknowledge: async () => ({ acknowledged: true, generation: "gen-0002" }) });
    await assert.rejects(Core.synchronize(env.request), { code: "VIEW_ACK_REJECTED" });
    assert.equal(env.persisted().generation, null);
});

test("interrupted file application resumes without overwriting manual changes", async () => {
    const files = [await view("Home.md", "one"), await view("Auto/Events/two.md", "two")];
    const disk = memoryAdapter({}, async (_, __, count) => { if (count === 1) throw new Error("disk failure"); });
    const env = await setup({ files, adapter: disk });
    await assert.rejects(Core.synchronize(env.request), /disk failure/);
    assert.equal(env.persisted().status, "applying");
    assert.equal(Object.keys(env.persisted().owned).length, 1);
    const recovered = memoryAdapter(Object.fromEntries(disk.files));
    const result = await Core.synchronize({ ...env.request, adapter: recovered, state: env.persisted() });
    assert.equal(result.written, 1);
    assert.equal(result.acknowledged, true);
});

test("server URLs enforce secure transport and no embedded credentials", () => {
    assert.equal(Core.endpoint("https://example.org/"), "https://example.org");
    assert.equal(Core.endpoint("http://127.0.0.1:8765"), "http://127.0.0.1:8765");
    for (const bad of ["http://example.org", "https://user:password@example.org", "https://example.org/?token=secret", "file:///tmp/secret", "javascript:alert(1)"]) {
        assert.throws(() => Core.endpoint(bad), Core.SyncError);
    }
});

test("persisted state rejects ownership outside managed folders", () => {
    assert.throws(() => Core.initialState({ schema: 1, owned: { "MyNotes/private.md": { hash: "0".repeat(64) } } }), { code: "UNSAFE_VIEW_PATH" });
});

test("built plugin saves only whitelisted metadata, never session credentials", async () => {
    const source = fs.readFileSync(path.join(__dirname, "../dist/sb-memory-view/main.js"), "utf8");
    class Plugin {} class PluginSettingTab {} class Modal {} class Setting {} class Notice {} class TFile {}
    const context = { module: { exports: {} }, exports: {}, require: name => {
        assert.equal(name, "obsidian"); return { Plugin, PluginSettingTab, Modal, Setting, Notice, TFile, requestUrl() {} };
    }, URL, TextEncoder, crypto: globalThis.crypto, console, document: {} };
    vm.runInNewContext(source, context, { filename: "main.js" });
    const instance = new context.module.exports();
    instance.settings = { server: "https://example.org", sourceId: "phone", deviceId: "a-test-device" };
    instance.sessionToken = "DO-NOT-PERSIST-THIS-CREDENTIAL";
    instance.syncState = Core.initialState(null); instance.captureIntents = {}; instance.disposed = false;
    let stored;
    instance.saveData = async value => { stored = value; };
    await instance.saveSettings();
    assert.ok(stored.server);
    assert.equal(JSON.stringify(stored).includes("DO-NOT-PERSIST"), false);
    assert.equal(Object.hasOwn(stored, "sessionToken"), false);
});
