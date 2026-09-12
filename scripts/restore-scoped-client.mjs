// Consume a restored classified page using JARVIS's issuer and scoped client.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';

export async function checkRestoredScope({load,database,config,root,launcher,pageId,clientId='restore',coordinate,needle='KeepBeta',projects=['project:a'],policyRevision='policy:1',profile='scoped-record-read-v3'}) {
  const {createProductionMemoryAccessClaim} = await load('src/memory-access-claim-production.js');
  const {createFileMemoryAccessScopeResolver} = await load('src/memory-access-policy.js');
  const {createMemoryScopedClient} = await load('src/memory-scoped-client.js');
  const {createSecondBrainTransport} = await load('src/second-brain-transport.js');
  const now = new Date();
  const expires = new Date(now.getTime()+300000).toISOString();
  const session = {principal_id:'principal:owner',agent_id:`agent:${clientId}`,session_id:`session:${clientId}`,expires_at:expires};
  const policy = {schema_version:1,provider_instance_id:config.provider_instance_id,
    principal_id:session.principal_id,policy_revision:policyRevision,valid_from:now.toISOString(),valid_until:expires,
    sessions:[{agent_id:session.agent_id,session_id:session.session_id,projects,methods:['sb_read_page','sb_search']}]};
  const policyPath = join(root,`${clientId}-policy.json`);
  writeFileSync(policyPath,JSON.stringify(policy),{mode:0o600});
  const scopedConfig = join(root,`${clientId}-scoped.toml`);
  writeFileSync(scopedConfig,readFileSync(join(root,'config.toml'),'utf8')+`\n[mcp_scoped_read]\nprincipal = "principal:owner"\nagent = "${session.agent_id}"\nsession = "${session.session_id}"\npolicy_revision = "${policyRevision}"\n`,{mode:0o600});
  const resolve = createFileMemoryAccessScopeResolver(policyPath,config.provider_instance_id,()=>session);
  const issue = createProductionMemoryAccessClaim(database.authority,config,resolve);
  const errLog = join(root,`${clientId}-mcp.err`);
  const wrappedLauncher = join(root,`${clientId}-mcp-wrap`);
  writeFileSync(wrappedLauncher,`${readFileSync(launcher,'utf8').trim()} 2>>${JSON.stringify(errLog)}
`,{mode:0o700});
  const transport = createSecondBrainTransport({contractProfile:profile,launcherPath:wrappedLauncher,configPath:scopedConfig});
  let withdrawAfterResponse = false;
  let intercepted = 0;
  const monitored = {
    call: async (...args) => {
      const response = await transport.call(...args);
      if (response.kind !== 'data') {
        throw new Error(JSON.stringify({pageId, args: args[0], response}));
      }
      if (withdrawAfterResponse) {
        assert.equal(response.kind,'data');
        assert(JSON.stringify(response.value).includes(needle));
        intercepted++;
        writeFileSync(policyPath,JSON.stringify({...policy,sessions:[]}));
      }
      return response;
    },
    restart:()=>transport.restart(), close:()=>transport.close(), diagnostics:()=>transport.diagnostics(),
  };
  const client = createMemoryScopedClient({issue,profile,transport:monitored,now:()=>new Date(),
    budgets:{max_hits:50,max_excerpt_bytes:8192,max_total_bytes:1000000,max_page_bytes:100000},
    max_age_ms:86400000,expiry_ms:172800000});
  try {
    let allowed;
    try {
      allowed = await client.readPage(pageId);
    } catch (error) {
      throw new Error(`${pageId} ${String(error)} ${JSON.stringify(transport.diagnostics())}`);
    }
    assert.equal(allowed.pages.length,1);
    assert(JSON.stringify(allowed).includes(needle));
    if (coordinate) await coordinate(clientId, {
      read:()=>client.readPage(pageId),
      revoke:()=>writeFileSync(policyPath,JSON.stringify({...policy,sessions:[]})),
      restore:()=>writeFileSync(policyPath,JSON.stringify(policy)),
    });
    const searched = await client.search(needle,2);
    assert.equal(searched.pages.length,1);
    for (const action of [()=>client.readPage(pageId),()=>client.search(needle,2)]) {
      withdrawAfterResponse = true;
      await assert.rejects(action, error=>error.code==='MEMORY_ACCESS_SCOPE_UNAVAILABLE');
      withdrawAfterResponse = false;
      writeFileSync(policyPath,JSON.stringify(policy));
      assert.equal((await action()).pages.length,1);
    }
    assert.equal(intercepted,2);
    writeFileSync(policyPath,JSON.stringify({...policy,sessions:[{...policy.sessions[0],projects:['project:b']}]}));
    await assert.rejects(()=>client.readPage(pageId));
    const restricted = await client.search(needle,2);
    assert.equal(restricted.pages.length,0);
    writeFileSync(policyPath,JSON.stringify({...policy,sessions:[]}));
    await assert.rejects(()=>client.readPage(pageId), error=>error.code==='MEMORY_ACCESS_SCOPE_UNAVAILABLE');
    return {agent:session.agent_id,session:session.session_id,generation:allowed.generation,
      page_content_digest:allowed.pages[0].content_digest,profile:'scoped-record-read-v3',allowed_pages:1,restricted_pages:0,withdrawal_denied:true,post_response_withdrawal_denied:true,intercepted_response_count:intercepted,restored_policy_resumes:true};
  } finally {await transport.close();}
}
