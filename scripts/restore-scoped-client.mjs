// Consume a restored classified page using JARVIS's issuer and scoped client.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';

export async function checkRestoredScope({load,database,config,root,launcher,pageId}) {
  const {createProductionMemoryAccessClaim} = await load('src/memory-access-claim-production.js');
  const {createFileMemoryAccessScopeResolver} = await load('src/memory-access-policy.js');
  const {createMemoryScopedClient} = await load('src/memory-scoped-client.js');
  const {createSecondBrainTransport} = await load('src/second-brain-transport.js');
  const now = new Date();
  const expires = new Date(now.getTime()+300000).toISOString();
  const session = {principal_id:'principal:owner',agent_id:'agent:restore',session_id:'session:restore',expires_at:expires};
  const policy = {schema_version:1,provider_instance_id:config.provider_instance_id,
    principal_id:session.principal_id,policy_revision:'policy:1',valid_from:now.toISOString(),valid_until:expires,
    sessions:[{agent_id:session.agent_id,session_id:session.session_id,projects:['project:a'],methods:['sb_read_page','sb_search']}]};
  const policyPath = join(root,'restore-policy.json');
  writeFileSync(policyPath,JSON.stringify(policy),{mode:0o600});
  const scopedConfig = join(root,'restore-scoped.toml');
  writeFileSync(scopedConfig,readFileSync(join(root,'config.toml'),'utf8')+`\n[mcp_scoped_read]\nprincipal = "principal:owner"\nagent = "agent:restore"\nsession = "session:restore"\npolicy_revision = "policy:1"\n`,{mode:0o600});
  const resolve = createFileMemoryAccessScopeResolver(policyPath,config.provider_instance_id,()=>session);
  const issue = createProductionMemoryAccessClaim(database.authority,config,resolve);
  const transport = createSecondBrainTransport({contractProfile:'scoped-record-read-v3',launcherPath:launcher,configPath:scopedConfig});
  const client = createMemoryScopedClient({issue,profile:'scoped-record-read-v3',transport,now:()=>new Date(),
    budgets:{max_hits:50,max_excerpt_bytes:8192,max_total_bytes:1000000,max_page_bytes:100000},
    max_age_ms:86400000,expiry_ms:172800000});
  try {
    const allowed = await client.readPage(pageId);
    assert.equal(allowed.pages.length,1);
    assert(JSON.stringify(allowed).includes('KeepBeta'));
    const searched = await client.search('KeepBeta',2);
    assert.equal(searched.pages.length,1);
    writeFileSync(policyPath,JSON.stringify({...policy,sessions:[{...policy.sessions[0],projects:['project:b']}]}));
    await assert.rejects(()=>client.readPage(pageId));
    const restricted = await client.search('KeepBeta',2);
    assert.equal(restricted.pages.length,0);
    writeFileSync(policyPath,JSON.stringify({...policy,sessions:[]}));
    await assert.rejects(()=>client.readPage(pageId), error=>error.code==='MEMORY_ACCESS_SCOPE_UNAVAILABLE');
    return {profile:'scoped-record-read-v3',allowed_pages:1,restricted_pages:0,withdrawal_denied:true};
  } finally {await transport.close();}
}
