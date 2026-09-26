'use strict';
const {Plugin, PluginSettingTab, Setting, Modal, Notice, TFile, requestUrl, Platform} = require('obsidian');
// syncCore is statically bundled by build.cjs, with no runtime dependency.
const {applyManifest, emptyState, validatePath} = syncCore;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function baseUrl(value) {
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash ||
      (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname))))
    throw new Error('HTTPS_OR_LOOPBACK_REQUIRED');
  return url.origin;
}
class FormModal extends Modal {
  constructor(app, title, fields, submit) { super(app); this.heading=title; this.fields=fields; this.submit=submit; }
  onOpen() {
    this.contentEl.createEl('h2', {text:this.heading});
    const values = {};
    for (const field of this.fields) {
      this.contentEl.createEl('label', {text:field.label});
      const input = this.contentEl.createEl(field.multiline ? 'textarea' : 'input');
      if (field.secret) input.type='password';
      input.value=field.value || ''; values[field.key]=input.value;
      input.addEventListener('input', () => { values[field.key]=input.value; });
      input.style.width='100%'; if (field.multiline) input.rows=8;
    }
    const button = this.contentEl.createEl('button', {text:'확인'});
    button.addEventListener('click', async () => {
      button.disabled=true;
      try { await this.submit(values); this.close(); }
      catch (error) { new Notice('Second Brain: '+String(error.message || '요청 실패')); button.disabled=false; }
    });
  }
  onClose() { this.contentEl.empty(); }
}
class TextModal extends Modal {
  constructor(app, title, text) { super(app); this.heading=title; this.text=text; }
  onOpen() {
    this.contentEl.createEl('h2', {text:this.heading});
    // Never render remote evidence as HTML/Markdown: no scripts or tracking images.
    const pre=this.contentEl.createEl('pre'); pre.textContent=this.text; pre.style.whiteSpace='pre-wrap';
  }
  onClose() { this.contentEl.empty(); }
}
class LifeSettings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin=plugin; }
  display() {
    const {containerEl}=this; containerEl.empty();
    containerEl.createEl('h2', {text:'Second Brain Memory Browser'});
    containerEl.createEl('p', {text:'전용 View Vault를 사용하세요. Auto/에는 다른 동기화 도구를 함께 적용하지 마세요. MyNotes는 자동 수정하지 않습니다.'});
    new Setting(containerEl).setName('서버 주소').setDesc('HTTPS 주소. 서버 변경 시 전용 Vault를 새로 사용하세요.')
      .addText(input => input.setValue(this.plugin.options.base).onChange(async value => {
        try {
          const next=baseUrl(value);
          if (this.plugin.state.server && this.plugin.state.server !== next && Object.keys(this.plugin.state.owned).length)
            throw new Error('NEW_SERVER_REQUIRES_NEW_VIEW_VAULT');
          this.plugin.options.base=next; this.plugin.token=''; await this.plugin.persist();
        } catch { /* Save only complete validated URLs, not partially typed addresses. */ }
      }));
    new Setting(containerEl).setName('허용된 입력 출처 ID').setDesc('서버의 life.sources에 별도로 허용한 출처만 사용합니다.')
      .addText(input => input.setValue(this.plugin.options.source).onChange(async value => {
        this.plugin.options.source=value.trim(); await this.plugin.persist();
      }));
    new Setting(containerEl).setName('세션 로그인').setDesc('생활기록 전용 토큰만 사용합니다. 토큰은 디스크에 저장하지 않습니다.')
      .addButton(button => button.setButtonText('토큰 입력').onClick(() => this.plugin.login()));
    new Setting(containerEl).setName('연결 해제').addButton(button => button.setButtonText('로그아웃').onClick(() => {
      this.plugin.token=''; new Notice('토큰을 메모리에서 제거했습니다.');
    }));
  }
}
module.exports = class SecondBrainMemoryBrowser extends Plugin {
  async onload() {
    const saved=await this.loadData() || {};
    this.options={base:typeof saved.base === 'string' ? saved.base : '', source:typeof saved.source === 'string' ? saved.source : ''};
    this.state=saved.sync && saved.sync.version===1 ? saved.sync : emptyState();
    this.token=''; this.syncing=false;
    this.addSettingTab(new LifeSettings(this.app, this));
    this.status=this.addStatusBarItem(); this.status.setText('SB: 로그인 필요');
    this.addCommand({id:'session-login', name:'생활기록 세션 로그인', callback:()=>this.login()});
    this.addCommand({id:'sync-memory-view', name:'기억 뷰 새로고침', callback:()=>this.sync()});
    this.addCommand({id:'open-memory-home', name:'기억 홈 열기', callback:()=>this.app.workspace.openLinkText('Auto/Home','',false)});
    this.addCommand({id:'save-memory-note', name:'메모를 기억에 저장', callback:()=>this.capture()});
    this.addCommand({id:'show-sync-state', name:'동기화 상태 확인', callback:()=>new TextModal(this.app,'동기화 상태',JSON.stringify(this.state,null,2)).open()});
    this.registerObsidianProtocolHandler('sb-life-evidence', async params => {
      try {
        if (!UUID.test(params.event || '')) throw new Error('INVALID_EVENT');
        const evidence=await this.api('evidence/'+params.event);
        new TextModal(this.app,'원문 근거',evidence.content).open();
      } catch(error) { new Notice('Second Brain: '+String(error.message)); }
    });
    this.registerObsidianProtocolHandler('sb-life-correct', async params => {
      try {
        if (!UUID.test(params.event || '')) throw new Error('INVALID_EVENT');
        const event=await this.api('events/'+params.event);
        const key=globalThis.crypto.randomUUID();
        new FormModal(this.app,'잘못된 기억 정정',[
          {key:'replacement',label:'정정할 본문',value:event.body,multiline:true},
          {key:'reason',label:'정정 이유'},
        ],async values => {
          await this.api('corrections','POST',{event_id:event.event_id,expected_revision:event.revision,
            replacement:values.replacement,reason:values.reason,idempotency_key:key});
          new Notice('정정을 서버에 반영했습니다.'); await this.sync();
        }).open();
      } catch(error) { new Notice('Second Brain: '+String(error.message)); }
    });
    this.registerDomEvent(document,'visibilitychange',()=> {
      if (document.visibilityState==='visible' && this.token) void this.sync();
    });
  }
  onunload() { this.token=''; }
  async persist() {
    // Explicit allowlist: never serialize token, evidence content, or credentials.
    await this.saveData({base:this.options.base,source:this.options.source,sync:this.state});
  }
  login() {
    new FormModal(this.app,'생활기록 전용 세션 토큰',[
      {key:'token',label:'전용 토큰 (현재 세션 메모리에만 보관)',secret:true},
    ],async values => {
      if (values.token.length<32) throw new Error('TOKEN_TOO_SHORT');
      this.token=values.token;
      try {
        const health=await this.api('health');
        if (health.credential_kind!=='life_client') throw new Error('USE_LIFE_ONLY_TOKEN_NOT_ADMIN');
        await this.sync();
      }
      catch(error) { this.token=''; throw error; }
    }).open();
  }
  async api(route, method='GET', data=null) {
    if (!this.token) throw new Error('SESSION_LOGIN_REQUIRED');
    const base=baseUrl(this.options.base);
    if (this.state.server && this.state.server !== base && Object.keys(this.state.owned).length)
      throw new Error('SERVER_IDENTITY_CHANGED');
    const response=await requestUrl({url:base+'/api/life/v1/'+route,method,
      headers:{Authorization:'Bearer '+this.token,'Content-Type':'application/json'},
      ...(data===null?{}:{body:JSON.stringify(data)}),throw:false});
    if (response.status<200 || response.status>=300) {
      if (response.status===401) this.token='';
      const code=response.json && typeof response.json.error==='string' ? response.json.error : 'HTTP_'+response.status;
      throw new Error(/^[A-Z0-9_]+$/.test(code) ? code : 'REQUEST_FAILED');
    }
    return response.json;
  }
  assertDesktopPath(path) {
    validatePath(path);
    // On mobile, use only Obsidian's sandboxed Vault interface (no Node filesystem).
    if (Platform.isDesktopApp && typeof this.app.vault.adapter.getBasePath==='function') {
      const fs=require('fs'), nodePath=require('path');
      let cursor=this.app.vault.adapter.getBasePath();
      for (const part of path.split('/')) {
        cursor=nodePath.join(cursor,part);
        if (fs.existsSync(cursor) && fs.lstatSync(cursor).isSymbolicLink()) throw new Error('VIEW_SYMLINK_REJECTED');
      }
    }
  }
  async sync() {
    if (this.syncing) return;
    this.syncing=true; this.status.setText('SB: 동기화 중');
    try {
      const manifest=await this.api('views/obsidian/manifest');
      this.state.server=baseUrl(this.options.base);
      const vault=this.app.vault;
      const host={
        read:async path => {
          this.assertDesktopPath(path);
          const file=vault.getAbstractFileByPath(path);
          if (!file) return null;
          if (!(file instanceof TFile)) throw new Error('VIEW_PATH_NOT_FILE');
          return vault.read(file);
        },
        compareAndWrite:async (path,expected,content) => {
          this.assertDesktopPath(path);
          if (expected===null) {
            let folder='';
            for (const segment of path.split('/').slice(0,-1)) {
              folder=folder ? folder+'/'+segment : segment;
              if (!vault.getAbstractFileByPath(folder)) await vault.createFolder(folder);
            }
            this.assertDesktopPath(path);
            await vault.create(path,content); // refuses an existing path
          } else {
            const file=vault.getAbstractFileByPath(path);
            if (!(file instanceof TFile)) throw new Error('VIEW_CHANGED_DURING_APPLY');
            let conflict=false;
            await vault.process(file,current => {
              if (current!==expected) { conflict=true; return current; }
              return content;
            });
            if (conflict) throw new Error('VIEW_CHANGED_DURING_APPLY');
          }
        },
        save:async state => {this.state=state; await this.persist();},
      };
      this.state=await applyManifest(host,manifest,this.state);
      this.status.setText('SB: '+this.state.status);
      if(this.state.conflicts.length) new Notice('수정본을 보존했습니다. 동기화 상태에서 충돌 파일을 확인하세요.');
    } catch(error) {
      this.status.setText('SB: 확인 필요');
      new Notice('Second Brain: '+String(error.message || '동기화 실패'));
    } finally { this.syncing=false; }
  }
  capture() {
    const key=globalThis.crypto.randomUUID();
    const capturedAt=new Date().toISOString();
    new FormModal(this.app,'새 기억 저장',[
      {key:'title',label:'제목'}, {key:'body',label:'기록할 내용',multiline:true},
    ],async values => {
      if(!this.options.source) throw new Error('SOURCE_REQUIRED');
      await this.api('events:batch','POST',{source_id:this.options.source,items:[{
        idempotency_key:key,payload:{source_item_id:key,source_version:'1',event_type:'note_saved',
          title:values.title,body:values.body,event_status:'occurred',evidence_level:'user_asserted',
          observed_at:capturedAt,occurred_start:capturedAt,
          timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,time_precision:'exact'},
      }]});
      new Notice('서버에 기록을 반영했습니다.'); await this.sync();
    }).open();
  }
};
