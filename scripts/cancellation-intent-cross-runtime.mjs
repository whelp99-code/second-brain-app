// Real Node/Python library interop; no provider mutation or production state.
import assert from 'node:assert/strict';
import {createHash, createPrivateKey, createPublicKey, sign} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const [buildArgument] = process.argv.slice(2);
assert(buildArgument?.startsWith('/')); const build = resolve(buildArgument); const sb = process.cwd();
process.umask(0o077); const root = mkdtempSync('/var/tmp/cancellation-intent-cross-runtime-');
const load = name=>import(pathToFileURL(join(build,'dist/src',name)));
const {createCorrectionCancellationIntent, requireCorrectionCancellationIntent, CORRECTION_CANCELLATION_INTENT_DOMAIN:domain} =
  await load('memory-correction-cancellation-intent.js');
const {canonicalize} = await load('canonical.js');
const key = start=>createPrivateKey({key:Buffer.concat([Buffer.from('302e020100300506032b657004220420','hex'),
  Buffer.from(Array.from({length:32},(_,i)=>start+i))]),format:'der',type:'pkcs8'});
const historical=key(0); const current=key(32); const stamp='2026-09-08T00:00:00.000Z';
const options={provider_instance_id:'provider:fixture',now:new Date(stamp),
  historical_delegation_keys:new Map([['jarvis:fixture',createPublicKey(historical)]]),
  current_cancellation_keys:new Map([['jarvis:current',createPublicKey(current)]])};
const original=JSON.parse(readFileSync(join(build,'contracts/second-brain-mcp-v1.json'),'utf8')).vectors.correction.request;
const base=createCorrectionCancellationIntent(original,{candidate_id:'memcand:pos:v1:'+'a'.repeat(64),
  suppression_event_digest:'sha256:'+'b'.repeat(64),dispatch_fence:0,attempt_count:0,active_cursor:false},
{issued_at:stamp,expires_at:'2026-09-08T00:05:00.000Z',nonce:'정정-취소',signing_key_id:'jarvis:current'},current,options);
function resign(value) {
  const {intent_id,intent_digest,signature,...body}=value; void intent_id;void intent_digest;void signature;
  const observed='sha256:'+createHash('sha256').update(domain).update(canonicalize(body)).digest('hex');
  const unsigned={...body,intent_id:'memcancel:intent:v1:'+observed.slice(7),intent_digest:observed};
  return {...unsigned,signature:sign(null,Buffer.from(domain+canonicalize(unsigned)),current).toString('base64url')};
}
const changes=[['valid',null],['plaintext',v=>{v.payload={content:'must not be sent'};}],
  ['target',v=>{v.target.page_id='wiki/other';}],['scope',v=>{v.scope.max_records=64;}],
  ['chain',v=>{v.tombstone.sequence=2;}],['attempt',v=>{v.unsent_evidence.attempt_count=1;}],
  ['cursor',v=>{v.unsent_evidence.active_cursor=true;}],['boolean',v=>{v.schema_version=true;}],
  ['bool-fence',v=>{v.unsent_evidence.dispatch_fence=false;}],['float',v=>{v.tombstone.sequence=1.5;}],
  ['ttl',v=>{v.expires_at='2026-09-08T00:05:00.001Z';}],['future',v=>{v.not_before='2026-09-08T00:00:00.001Z';}],
  ['signature',v=>{v.original_delegation.signature='a'.repeat(86);}],['purge',v=>{v.disposition='managed_erasure';}],
  ['historical-key',v=>{v.original_delegation.signing_key_id='unknown';}],['current-key',v=>{v.signing_key_id='unknown';}]];
const cases=changes.map(([name,change])=>{const value=structuredClone(base);if(change)change(value);
  // Fractional JSON is outside the canonical integer contract and must fail before re-signing.
  const wire=name==='float'?value:resign(value);let accepted=false;
  try{requireCorrectionCancellationIntent(wire,options);accepted=true;}catch{}
  assert.equal(accepted,name==='valid',name);return{name,value:wire,node_accepted:accepted};});
writeFileSync(join(root,'node-cases.json'),JSON.stringify(cases));
const script=String.raw`
import json,sys,os
from pathlib import Path
from tests.test_correction_cancellation import cancellation_fixture,validate
from sb.effect_write_values import EffectRequestRejected
root=Path(sys.argv[1]); cases=json.loads((root/'node-cases.json').read_text()); results=[]
for case in cases:
    try:
        parsed=validate(case['value']); accepted=True
    except EffectRequestRejected:
        accepted=False
    assert accepted==case['node_accepted'],case['name']
    results.append({'name':case['name'],'node_accepted':case['node_accepted'],'python_accepted':accepted})
(root/'python-vector.json').write_text(json.dumps(cancellation_fixture(),ensure_ascii=False))
print(json.dumps({'pid':os.getpid(),'cases':results}))
`;
const python=spawnSync(join(sb,'.venv/bin/python'),['-c',script,root],{cwd:sb,encoding:'utf8',timeout:30000});
assert.equal(python.status,0,python.stderr);
const generated=JSON.parse(readFileSync(join(root,'python-vector.json'),'utf8'));
assert.deepEqual(requireCorrectionCancellationIntent(generated,options),base);
assert.equal(JSON.stringify(base).includes(original.payload.content),false);
const pythonResult=JSON.parse(python.stdout);
const manifest=JSON.parse(readFileSync(join(build,'dist/build-metadata.json'),'utf8'));
const result={status:'passed',root,build,node_pid:process.pid,python_pid:pythonResult.pid,cases:pythonResult.cases,
  build_artifact_digest:manifest.artifact.digest,bidirectional_identical:true,
  intent_digest:base.intent_digest,canonical_bytes:Buffer.byteLength(canonicalize(base)),plaintext_present:false,
  provider_mutations:0,operational_data_used:false,automatic_recovery_complete:false};
writeFileSync(join(root,'result.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
