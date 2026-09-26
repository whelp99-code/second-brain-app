'use strict';
const {Plugin, PluginSettingTab, Setting, Modal, Notice, TFile, requestUrl, Platform} = require('obsidian');
// syncCore is statically bundled by build.cjs, with no runtime dependency.
const {applyManifest, emptyState, validatePath, collectManifest, digest, canonical} = syncCore;
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
      const input = this.contentEl.createEl(field.options ? 'select' : field.multiline ? 'textarea' : 'input');
      if (field.options) for (const [value, label] of field.options) input.createEl('option', {value, text:label});
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
    this.token=''; this.syncing=false; this.selectedDay=null;
    this.addSettingTab(new LifeSettings(this.app, this));
    this.status=Platform.isDesktopApp ? this.addStatusBarItem() : {setText:()=>{}};
    this.status.setText('SB: 로그인 필요');
    this.addCommand({id:'session-login', name:'생활기록 세션 로그인', callback:()=>this.login()});
    this.addCommand({id:'sync-memory-view', name:'기억 뷰 새로고침', callback:()=>this.sync()});
    this.addCommand({id:'open-memory-home', name:'기억 홈 열기', callback:()=>this.app.workspace.openLinkText('Auto/Home','',false)});
    this.addCommand({id:'save-memory-note', name:'메모를 기억에 저장', callback:()=>this.capture()});
    this.addCommand({id:'show-sync-state', name:'동기화 상태 확인', callback:()=>new TextModal(this.app,'동기화 상태',JSON.stringify(this.state,null,2)).open()});
    this.addCommand({id:'select-memory-day', name:'날짜별 하루 기록 보기', callback:()=>this.selectDay()});
    this.addCommand({id:'recall-memory', name:'과거·현재 기억에서 찾기', callback:()=>this.recall()});
    this.addCommand({id:'memory-questions', name:'필요한 확인 질문 보기', callback:()=>this.questions()});
    this.addCommand({id:'memory-relations', name:'근거 관계 필터 보기', callback:()=>this.relations()});
    this.addCommand({id:'memory-predictions', name:'예측·실제 결과 보기', callback:()=>this.predictions()});
    this.addCommand({id:'memory-health', name:'수집·전달·기기 상태 보기', callback:()=>this.health()});
    this.addCommand({id:'save-selected-personal-note', name:'현재 개인 메모를 명시적으로 기억에 저장', callback:()=>this.savePersonalNote()});
    this.registerObsidianProtocolHandler('sb-life-question', params=>void this.answerQuestion(params.id, Number(params.revision)));
    this.registerObsidianProtocolHandler('sb-life-evidence', async params => {
      try {
        if (!UUID.test(params.event || '')) throw new Error('INVALID_EVENT');
        const evidence=await this.api('evidence/'+params.event);
        let content=evidence.content;
        try {
          const original=JSON.parse(content);
          content=JSON.stringify({...original,attachments:(original.attachments||[]).map(a=>({
            name:a.name,mime:a.mime,sha256:a.sha256,content:'원본 바이너리는 별도 근거 API에서 확인'}))},null,2);
        } catch { /* Non-JSON original text is displayed literally. */ }
        new TextModal(this.app,'원문 근거',content).open();
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
    if (typeof route!=='string' || route.includes('..') || route.includes('\\') || route.startsWith('/') ||
        route.includes('#') || route.length>4096) throw new Error('INVALID_API_ROUTE');
    const sessionToken=this.token;
    const base=baseUrl(this.options.base);
    if (this.state.server && this.state.server !== base && Object.keys(this.state.owned).length)
      throw new Error('SERVER_IDENTITY_CHANGED');
    const response=await requestUrl({url:base+'/api/life/v1/'+route,method,
      headers:{Authorization:'Bearer '+this.token,'Content-Type':'application/json'},
      ...(data===null?{}:{body:JSON.stringify(data)}),throw:false});
    if (this.token!==sessionToken || baseUrl(this.options.base)!==base) throw new Error('SESSION_CHANGED_RETRY');
    if (typeof response.text==='string' && new TextEncoder().encode(response.text).length>20*1024*1024)
      throw new Error('API_RESPONSE_TOO_LARGE');
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
      const sessionToken=this.token;
      const server=baseUrl(this.options.base);
      const manifest=await collectManifest(route=>this.api(route), {
        day:this.selectedDay, timezone:'Asia/Seoul', pageSize:100,
      });
      const guard=()=> {
        if (!sessionToken || this.token!==sessionToken || baseUrl(this.options.base)!==server)
          throw new Error('SESSION_CHANGED_RETRY');
      };
      guard();
      this.state.server=baseUrl(this.options.base);
      const vault=this.app.vault;
      const host={
        read:async path => {
          guard();
          this.assertDesktopPath(path);
          const file=vault.getAbstractFileByPath(path);
          if (!file) return null;
          if (!(file instanceof TFile)) throw new Error('VIEW_PATH_NOT_FILE');
          return vault.read(file);
        },
        compareAndWrite:async (path,expected,content) => {
          guard();
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
      guard();
      if (this.state.status==='complete') {
        try {
          await this.api('views/obsidian/ack','POST',{generation:manifest.generation,day:manifest.day,timezone:manifest.timezone});
          this.state.serverAck=manifest.generation;
        } catch(error) {
          this.state.serverAck=null;
          this.state.ackError=String(error.message || 'ACK_FAILED');
        }
        await this.persist();
      }
      this.status.setText('SB: '+this.state.status);
      if(this.state.conflicts.length) new Notice('수정본을 보존했습니다. 동기화 상태에서 충돌 파일을 확인하세요.');
    } catch(error) {
      this.status.setText('SB: 확인 필요');
      new Notice('Second Brain: '+String(error.message || '동기화 실패'));
    } finally { this.syncing=false; }
  }
  selectDay() {
    new FormModal(this.app,'조회할 날짜',[
      {key:'day',label:'YYYY-MM-DD',value:this.selectedDay||new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul'}).format(new Date())},
    ],async value=> {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value.day) || !Number.isFinite(Date.parse(value.day))) throw new Error('INVALID_DAY');
      this.selectedDay=value.day;
      await this.sync();
      await this.app.workspace.openLinkText('Auto/Daily/'+value.day,'',false);
    }).open();
  }
  recall() {
    new FormModal(this.app,'근거로 기억 찾기',[
      {key:'query',label:'찾을 내용'},
      {key:'as_of',label:'당시 시점 (선택: ISO 시각, 예 2026-09-20T12:00:00+09:00)'},
    ],async value=> {
      const request={query:value.query,trigger:'explicit_question'};
      if (value.as_of.trim()) request.as_of=value.as_of.trim();
      const result=await this.api('recall','POST',request);
      const lines=[result.why_now||'',result.state==='no_data'?'일치하는 허용된 기록 없음':''];
      for (const hit of result.hits||[]) lines.push('\n'+hit.title+'\n'+hit.event_status+
        (hit.historical?' · 과거 시점':' · 현재')+(hit.changed_since?' · 이후 변경됨':'')+'\n'+hit.text+
        '\n근거 사건: '+hit.event_id+' / 개정 '+hit.revision);
      new TextModal(this.app,'기억 회상',lines.join('\n')).open();
    }).open();
  }
  async questions() {
    try {
      const result=await this.api('questions');
      const open=(result.items||[]).filter(row=>row.body.state==='open');
      if (!open.length) { new Notice('현재 필요한 확인 질문이 없습니다.'); return; }
      new FormModal(this.app,'확인할 기록 선택',[
        {key:'id',label:'질문',value:open[0].object_id,options:open.map(row=>[row.object_id,row.body.title+' · '+row.body.prompt])},
      ],async values=> {
        const selected=open.find(row=>row.object_id===values.id);
        if (!selected) throw new Error('INVALID_QUESTION');
        await this.answerQuestion(selected.object_id,selected.revision);
      }).open();
    } catch(error) { new Notice('Second Brain: '+String(error.message)); }
  }
  async answerQuestion(id, revision) {
    try {
      if (!/^question:[a-f0-9]{64}$/.test(id||'') || !Number.isSafeInteger(revision)||revision<1) throw new Error('INVALID_QUESTION');
      const result=await this.api('questions');
      const question=(result.items||[]).find(row=>row.object_id===id && row.revision===revision && row.body.state==='open');
      if (!question) throw new Error('STALE_QUESTION_REFRESH');
      const session=globalThis.crypto.randomUUID();
      new FormModal(this.app,question.body.prompt,[
        {key:'action',label:'처리',value:'answer',options:[['answer','답변'],['skip','건너뛰기'],['mute','다시 묻지 않기']]},
        {key:'answer',label:'기억할 내용',multiline:true},
        {key:'event_status',label:'진행 상태',value:'unchanged',options:[['unchanged','기존 상태 유지'],['occurred','진행됨'],['cancelled','취소됨'],['unknown','모름']]},
      ],async values=> {
        const request={action:values.action,expected_revision:revision};
        if(values.action==='answer') {
          request.answer=values.answer;
          if(values.event_status!=='unchanged') request.event_status=values.event_status;
        }
        request.idempotency_key=session+'-'+await digest(canonical(request));
        await this.api('questions/'+encodeURIComponent(id)+'/response','POST',request);
        new Notice('확인 내용을 저장했습니다.'); await this.sync();
      }).open();
    } catch(error) { new Notice('Second Brain: '+String(error.message)); }
  }
  async relations() {
    try {
      const result=await this.api('relations');
      const kinds=[...new Set((result.items||[]).map(row=>row.body.relation_kind))];
      new FormModal(this.app,'근거 관계 필터',[
        {key:'kind',label:'관계 종류',value:'all',options:[['all','전체'],...kinds.map(k=>[k,k])]},
        {key:'state',label:'확인 상태',value:'all',options:[['all','전체'],['asserted','사용자 명시'],['candidate','추정 후보']]},
      ],async values=> {
        const rows=(result.items||[]).filter(row=>(values.kind==='all'||row.body.relation_kind===values.kind)&&
          (values.state==='all'||row.body.state===values.state));
        const lines=rows.map(row=>row.body.from_id+' → '+row.body.to_id+'\n'+row.body.relation_kind+' · '+row.body.state+
          '\n효력: '+(row.body.valid_from||'미지정')+' ~ '+(row.body.valid_until||'미지정')+
          '\n근거: '+row.evidence.map(e=>e.event_id+'#'+e.revision).join(', '));
        new TextModal(this.app,'근거 관계',lines.join('\n\n')||'해당 관계 없음').open();
      }).open();
    } catch(error) { new Notice('Second Brain: '+String(error.message)); }
  }
  async predictions() {
    try {
      const forecasts=await this.api('predictions'), actual=await this.api('actuals');
      const results=new Map((actual.items||[]).map(row=>[row.body.prediction_id,row.body]));
      const lines=(forecasts.items||[]).map(row=> {
        const b=row.body,a=results.get(row.object_id);
        return b.target_id+'\n상태: '+b.state+' · 표본 '+b.sample_count+
          '\n예상 분: '+(b.estimate_minutes===null?'자료 부족':b.estimate_minutes)+
          '\n실제: '+(!a?'미채점':a.actual_minutes===null?'결측':a.actual_minutes)+
          '\n오차: '+(!a||a.absolute_error_minutes===null?'미채점':a.absolute_error_minutes);
      });
      new TextModal(this.app,'예측과 실제 결과',lines.join('\n\n')||'등록된 예측 없음').open();
    } catch(error) { new Notice('Second Brain: '+String(error.message)); }
  }
  async health() {
    try { new TextModal(this.app,'수집·전달 상태',JSON.stringify(await this.api('health'),null,2)).open(); }
    catch(error) { new Notice('Second Brain: '+String(error.message)); }
  }
  async savePersonalNote() {
    try {
      const file=this.app.workspace.getActiveFile();
      if (!(file instanceof TFile) || !file.path.startsWith('MyNotes/') || file.extension!=='md') throw new Error('SELECT_MYNOTES_MARKDOWN');
      const content=await this.app.vault.read(file);
      if (new TextEncoder().encode(content).length>100000) throw new Error('NOTE_TOO_LARGE');
      this.capture(file.basename,content);
    } catch(error) { new Notice('Second Brain: '+String(error.message)); }
  }
  capture(initialTitle='', initialBody='') {
    const key=globalThis.crypto.randomUUID();
    const capturedAt=new Date().toISOString();
    new FormModal(this.app,'새 기억 저장',[
      {key:'title',label:'제목',value:initialTitle}, {key:'body',label:'기록할 내용',value:initialBody,multiline:true},
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
