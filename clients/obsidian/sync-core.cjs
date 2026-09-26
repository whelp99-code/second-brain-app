/** Pure, testable synchronization engine. Host supplies CAS-style file operations.
 * It never accesses a filesystem directly, stores tokens, or owns MyNotes.
 */
'use strict';
const encoder = new TextEncoder();
const HASH = /^[a-f0-9]{64}$/;
const PATH = /^Auto\/(?:(?:Home|History|Questions|Relations|Predictions)\.md|(?:Daily|People|Companies|Projects|Places|Events|Decisions|Questions|Evidence|System|Predictions)\/[A-Za-z0-9_-]+\.md)$/;

function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}

async function digest(content) {
  const bytes = await globalThis.crypto.subtle.digest('SHA-256', encoder.encode(content));
  return Array.from(new Uint8Array(bytes), x => x.toString(16).padStart(2, '0')).join('');
}
function validatePath(path) {
  if (typeof path !== 'string' || !PATH.test(path)) throw new Error('UNSAFE_VIEW_PATH');
  return path;
}
function validContent(content) {
  if (typeof content !== 'string' || encoder.encode(content).length > 1048576)
    throw new Error('VIEW_CONTENT_TOO_LARGE');
  if (/<\s*(script|iframe|img|object|embed|style|link)\b/i.test(content)
      || /!\[/.test(content) || /\]\(\s*(javascript|data|file):/i.test(content))
    throw new Error('UNSAFE_VIEW_CONTENT');
}
async function validateManifest(manifest) {
  if (!manifest || manifest.schema_version !== 1 || typeof manifest.complete !== 'boolean'
      || !HASH.test(manifest.generation) || manifest.cursor !== manifest.generation
      || manifest.managed_prefix !== 'Auto/' || !Array.isArray(manifest.files)
      || manifest.files.length > 20000) throw new Error('INVALID_MANIFEST');
  let size = 0;
  const seen = new Set();
  for (const row of manifest.files) {
    validatePath(row.path); validContent(row.content);
    if (seen.has(row.path) || !HASH.test(row.sha256)) throw new Error('INVALID_MANIFEST');
    seen.add(row.path);
    size += encoder.encode(row.content).length;
    if (size > 8 * 1024 * 1024) throw new Error('VIEW_BATCH_TOO_LARGE');
    if (await digest(row.content) !== row.sha256) throw new Error('VIEW_HASH_MISMATCH');
  }
  if (await digest(canonical(manifest.files)) !== manifest.generation)
    throw new Error('VIEW_GENERATION_MISMATCH');
}
function emptyState() {
  return {version: 1, generation: null, cursor: null, owned: {}, intents: {}, conflicts: [], status: 'new'};
}
const WITHDRAWN = '# 기록 철회\n\n서버에서 이 기록의 제공이 중단되었습니다. 최신 원문은 열 수 없습니다.\n';

async function applyManifest(host, manifest, originalState = emptyState()) {
  await validateManifest(manifest); // validate ALL entries before modifying anything
  const state = structuredClone(originalState);
  if (state.version !== 1 || !state.owned || !state.intents) throw new Error('INVALID_SYNC_STATE');
  for (const path of [...Object.keys(state.owned), ...Object.keys(state.intents)]) validatePath(path);
  state.status = 'applying'; state.conflicts = [];
  await host.save(structuredClone(state));
  const incoming = new Map(manifest.files.map(row => [row.path, row]));
  // Withdraw previously-owned revoked entries before installing new content.
  const removals = manifest.complete ? Object.keys(state.owned).filter(p => !incoming.has(p)) : [];
  const jobs = [...await Promise.all(removals.map(async path => ({path, content: WITHDRAWN,
                 sha256: await digest(WITHDRAWN), withdrawn: true}))), ...manifest.files];
  for (const row of jobs) {
    const path = row.path;
    const current = await host.read(path); // null means absent; errors are not absence
    const currentHash = current === null ? null : await digest(current);
    const previous = state.owned[path];
    const pending = state.intents[path];
    if (pending && pending.next === row.sha256 && currentHash === row.sha256) {
      // Recovery of an operation whose intent was durably recorded before writing.
      state.owned[path] = row.sha256; delete state.intents[path];
      await host.save(structuredClone(state)); continue;
    }
    if (current !== null && (!previous || currentHash !== previous)) {
      state.conflicts.push(path); continue; // never adopt or overwrite unowned/user-edited files
    }
    if (currentHash === row.sha256 && previous === row.sha256) continue;
    state.intents[path] = {previous: currentHash, next: row.sha256};
    await host.save(structuredClone(state)); // write-ahead ownership intent
    await host.compareAndWrite(path, current, row.content);
    const after = await host.read(path);
    if (after === null || await digest(after) !== row.sha256) throw new Error('VIEW_WRITE_NOT_CONFIRMED');
    state.owned[path] = row.sha256;
    delete state.intents[path];
    await host.save(structuredClone(state));
  }
  state.status = state.conflicts.length ? 'conflict' : manifest.complete ? 'complete' : 'partial';
  if (state.status === 'complete') {
    state.generation = manifest.generation;
    state.cursor = manifest.cursor;
  }
  await host.save(structuredClone(state));
  return state;
}
async function collectManifest(fetchPage, options = {}) {
  const pageSize = options.pageSize || 100;
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 500) throw new Error('INVALID_PAGE_SIZE');
  let next = null, first = null, totalBytes = 0;
  const files = [], seen = new Set(), cursors = new Set();
  for (let count = 0; count < 400; count++) {
    const query = new URLSearchParams({page_size: String(pageSize)});
    if (options.day) query.set('day', options.day);
    if (options.timezone) query.set('timezone', options.timezone);
    if (next !== null) query.set('cursor', next);
    const response = await fetchPage('views/obsidian/manifest?' + query.toString());
    if (!response || !Array.isArray(response.files) || response.page_offset !== files.length ||
        !Number.isInteger(response.total_files) || response.total_files < 0 || response.total_files > 20000 ||
        typeof response.snapshot_complete !== 'boolean' || !HASH.test(response.generation) ||
        response.cursor !== response.generation || response.managed_prefix !== 'Auto/')
      throw new Error('INVALID_MANIFEST_PAGE');
    if (!first) first = response;
    if (response.generation !== first.generation || response.total_files !== first.total_files ||
        response.snapshot_complete !== first.snapshot_complete || response.day !== first.day ||
        response.timezone !== first.timezone) throw new Error('VIEW_GENERATION_CHANGED_RETRY');
    for (const row of response.files) {
      validatePath(row.path); validContent(row.content);
      if (seen.has(row.path) || !HASH.test(row.sha256)) throw new Error('INVALID_MANIFEST_PAGE');
      seen.add(row.path);
      totalBytes += encoder.encode(row.content).length;
      if (totalBytes > 8 * 1024 * 1024) throw new Error('VIEW_BATCH_TOO_LARGE');
      if (await digest(row.content) !== row.sha256) throw new Error('VIEW_HASH_MISMATCH');
      files.push(row);
    }
    if (files.length > first.total_files) throw new Error('INVALID_MANIFEST_PAGE');
    next = response.next_cursor;
    if (next === null) {
      if (files.length !== first.total_files || response.page_complete !== true)
        throw new Error('INCOMPLETE_MANIFEST');
      const complete = {...first, files, complete:first.snapshot_complete, next_cursor:null,
                        page_offset:0, page_complete:true};
      await validateManifest(complete);
      return complete;
    }
    if (typeof next !== 'string' || !next || next.length > 1000 || cursors.has(next) || !response.files.length)
      throw new Error('INVALID_MANIFEST_CURSOR');
    cursors.add(next);
  }
  throw new Error('MANIFEST_PAGE_LIMIT');
}

module.exports = {digest, canonical, validatePath, validateManifest, emptyState, applyManifest, collectManifest, WITHDRAWN};
