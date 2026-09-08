// Isolated synthetic UI/HTTP acceptance; no operational provider or model call.
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const build=process.argv[2]; assert(build?.startsWith('/'), 'absolute isolated build required'); process.umask(0o077); const load=p=>import(pathToFileURL(join(build,p)));
// Dashboard composition resolves its policy relative to cwd; use the isolated build config.
process.chdir(build);
const {chromium}=await load('node_modules/playwright/index.mjs');
const {AuthorityDb}=await load('src/db.js');
const {createDashboardServer}=await load('src/dashboard/server.js');
const {Task32ReadAdapter,task32Evidence}=await load('tests/fixtures/task32-memory-test-support.js');
const {externalAnchors,bindExternal}=await load('tests/helpers.js');
const root=mkdtempSync('/var/tmp/jarvis-view-browser-');
const db=new AuthorityDb(join(root,'authority.sqlite')); const anchors=externalAnchors();
await db.initialize({decision:{keyId:'decision-test',principal:'principal:owner',publicKeyPath:anchors.decisionPublic},verifier:{keyId:'verifier-test',principal:'independent-verifier',publicKeyPath:anchors.verifierPublic}});bindExternal(db,anchors);
const adapter=new Task32ReadAdapter();let current=new Date('2026-09-01T00:00:00Z');
const server=createDashboardServer({db,staticRoot:join(build,'dashboard'),host:'127.0.0.1',port:0,clock:()=>current,memoryAdapter:adapter,memoryProjectionKey:Buffer.alloc(32,7)});
const origin=`http://${server.address.host}:${server.address.port}`;
const browser=await chromium.launch({headless:true});const pages=[];
try {
for(const width of [1440,1024]){
const page=await browser.newPage({viewport:{width,height:1000}});pages.push(page);await page.clock.install({time:current});
const errors=[];page.on('pageerror',e=>errors.push(e.message)); page.on('console',m=>{if(['error','warning'].includes(m.type()))errors.push(m.text())});
await page.goto(origin+'/memory');await page.getByRole('heading',{name:'Memory',exact:true}).waitFor();
await page.getByLabel('Memory query').fill('fixture');await page.getByRole('button',{name:'Search memory',exact:true}).click();
await page.getByRole('button',{name:/Synthetic Task 32 record/}).click();await page.getByLabel('Replacement').fill('Private draft fixture');await page.getByRole('checkbox').check();
await page.screenshot({path:join(root,`selected-${width}.png`)});
db.db.prepare('UPDATE memory_surface_authority SET privacy_epoch=privacy_epoch+1 WHERE singleton_id=1').run();server.publish(['memory.privacy.v1']);
await page.getByLabel('Replacement').waitFor({state:'detached'});await page.getByText('Select a current record.').waitFor();
assert(!await page.getByText('Synthetic Task 32 record',{exact:true}).count());
assert.equal(await page.getByLabel('Memory query').inputValue(),'');
await page.screenshot({path:join(root,`cleared-${width}.png`)});
assert.deepEqual(errors,[]);assert(!await page.locator('vite-error-overlay').count());
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
writeFileSync(join(root,`viewport-${width}.json`),JSON.stringify({url:page.url(),title:await page.title(),width,errors,global_disconnected_badge:await page.getByText("끊김",{exact:true}).count()>0,selected_then_privacy_clear:true,not_blank:true,no_overlay:true,no_overflow:true}));await page.close();
}
// Actual HTTP request: change policy inside the provider response boundary, expect no record bytes.
adapter.search=async()=>{db.db.prepare('UPDATE memory_surface_authority SET privacy_epoch=privacy_epoch+1 WHERE singleton_id=1').run();return {kind:'current',checked_at:current.toISOString(),evidence:[task32Evidence()]};};
const session=await (await fetch(origin+'/api/v1/session')).json();
const response=await fetch(origin+'/api/v1/memory/search',{method:'POST',headers:{'content-type':'application/json','origin':origin,'x-jarvis-csrf':session.csrf_token},body:JSON.stringify({schema_version:1,query:'fixture',limit:20})});const body=await response.json();assert.equal(response.status,409);assert.equal(body.error.code,'MEMORY_SURFACE_READ_CHANGED');assert(!JSON.stringify(body).includes('Synthetic Task 32 record'));
const result={root,origin,viewports:[1440,1024],browser:'Chromium Playwright; Browser plugin not available',privacy_clear_passed:true,http_race_status:response.status,native_model_calls:0,provider:'deterministic adapter fixture',query_input_cleared:true,full_native_integration:false,global_connection_readiness:'not certified by this memory-flow acceptance'};writeFileSync(join(root,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();server.close();db.close();}
