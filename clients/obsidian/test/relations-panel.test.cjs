'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('path');
const vm = require('node:vm');
const core = require('../sync-core.cjs');

function pluginRuntime(desktop = false) {
  class Modal { constructor(app){ this.app = app; } open(){} }
  class Plugin {
    constructor(){ this.commands = []; this.protocols = {}; this.views = {}; this.app = {workspace:{on:()=>({}),getActiveFile:()=>null},vault:{}}; }
    async loadData(){ return null; }
    async saveData(value){ this.saved = value; }
    addStatusBarItem(){ return {setText(){}}; }
    addSettingTab(){}
    addCommand(value){ this.commands.push(value); }
    registerObsidianProtocolHandler(name, handler){ this.protocols[name] = handler; }
    registerView(type, factory){ this.views[type] = factory; }
    registerDomEvent(){}
    registerEvent(){}
  }
  class ItemView { constructor(leaf){ this.leaf = leaf; this.containerEl = {empty(){}, createEl(){ return this; }}; } }
  const obsidian = {
    Plugin, Modal, ItemView, PluginSettingTab: class {}, Setting: class {}, Notice: class {},
    TFile: class {}, TFolder: class {}, Platform: {isDesktopApp: desktop}, requestUrl: async () => ({status: 200, json: {}}),
  };
  const code = 'const syncCore = injectedCore;\n' + fs.readFileSync(path.join(__dirname, '..', 'main.src.cjs'), 'utf8');
  const context = {
    module: {exports: {}}, require: name => { assert.equal(name, 'obsidian'); return obsidian; },
    injectedCore: core, TextEncoder, URL, URLSearchParams, Intl, Date, Number, JSON, Map, Set,
    globalThis, document: {visibilityState: 'visible'}, window: {}, setTimeout,
  };
  vm.runInNewContext(code, context, {filename: 'main.src.cjs'});
  return {Plugin: context.module.exports};
}

function fakeEl() {
  const node = {
    tag: 'div', attrs: {}, children: [], text: '', type: '', checked: false, listeners: {},
    empty(){ this.children = []; },
    createEl(tag, options){
      const child = fakeEl();
      child.tag = tag;
      child.text = options && options.text || '';
      child.attrs = options && options.attr || {};
      this.children.push(child);
      return child;
    },
    addEventListener(name, fn){ this.listeners[name] = fn; },
  };
  return node;
}

function sections(root) {
  return root.children.filter(child => child.tag === 'section');
}

const rows = [
  {body: {relation_kind: 'knows', from_id: 'a', to_id: 'b', state: 'asserted', valid_from: '2026-09-01T00:00:00Z', valid_until: null}, evidence: [{event_id: 'e1', revision: 1}]},
  {body: {relation_kind: 'works_at', from_id: 'a', to_id: 'c', state: 'asserted', valid_from: null, valid_until: '2026-10-01T00:00:00Z'}, evidence: [{event_id: 'e2', revision: 2}]},
  {body: {relation_kind: 'knows', from_id: 'ghost', to_id: 'b', state: 'candidate', valid_from: null, valid_until: null}, evidence: []},
];

test('relation panel renders one section per kind and persists filter in plugin data', async () => {
  const runtime = pluginRuntime(false);
  const plugin = new runtime.Plugin();
  await plugin.onload();
  const root = fakeEl();
  plugin.renderRelationPanel(root, rows);
  const kinds = sections(root).map(section => section.attrs['data-kind']);
  assert.deepEqual(kinds, ['knows', 'works_at']);
  const knows = sections(root).find(section => section.attrs['data-kind'] === 'knows');
  const toggle = knows.children.find(child => child.tag === 'input');
  toggle.checked = false;
  await toggle.listeners.change();
  assert.equal(plugin.saved.relationFilter.kinds.knows, false);
  assert.equal(plugin.relationFilter.kinds.knows, false);
  const again = fakeEl();
  plugin.renderRelationPanel(again, rows);
  const hidden = sections(again).find(section => section.attrs['data-kind'] === 'knows');
  assert.equal(hidden.children.some(child => child.attrs['data-edge'] === '1'), false);
  assert.equal(sections(again).some(section => section.attrs['data-kind'] === 'works_at'), true);
});

test('panel never adds edges without evidence rows', async () => {
  const runtime = pluginRuntime(true);
  const plugin = new runtime.Plugin();
  await plugin.onload();
  const root = fakeEl();
  plugin.renderRelationPanel(root, rows);
  const edges = sections(root).flatMap(section => section.children.filter(child => child.attrs['data-edge'] === '1'));
  assert.equal(edges.length, 2);
  assert.equal(JSON.stringify(root).includes('ghost'), false);
});

test('mobile registers panel view without login token persistence', async () => {
  const runtime = pluginRuntime(false);
  const plugin = new runtime.Plugin();
  await plugin.onload();
  assert.equal(typeof plugin.views['sb-relation-panel'], 'function');
  const view = plugin.views['sb-relation-panel']({id: 'leaf'});
  assert.equal(view.getViewType(), 'sb-relation-panel');
  plugin.token = 'session-token-should-not-be-saved-123456';
  await plugin.persist();
  const saved = JSON.stringify(plugin.saved);
  assert.equal(saved.includes('session-token-should-not-be-saved'), false);
  assert.equal(JSON.stringify(plugin.saved.relationFilter), '{"kinds":{}}');
});
