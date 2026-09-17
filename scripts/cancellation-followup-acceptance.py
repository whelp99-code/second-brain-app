"""Real provider seq1 cancellation settlement -> independent seq2 correction.
JARVIS validates the second wire request; its dispatch/settlement is not simulated.
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives import serialization

from sb.effect_values import canonical_bytes, format_instant
from sb.effect_write_requests import accept_effect_request
from sb.mcp_contract import write_fixture_request
from sb.request_executor import RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from tests.task30_effect_factory import effect_request
from tests.test_correction_cancellation import HISTORICAL
from tests.test_request_executor import _config

build = str(Path(sys.argv[1]).resolve())
run = subprocess.run([sys.executable, str(ROOT/'scripts/cancellation-submit-acceptance.py'), build, '--settle-result'],
    capture_output=True, text=True, timeout=120, env={**os.environ, 'TMPDIR':'/var/tmp'}, check=False)
if run.returncode:
    raise SystemExit(run.stderr)
prior_path = Path(run.stdout.splitlines()[0])
prior = json.loads(prior_path.read_text())
assert prior['cursor']['accepted_through_sequence'] == 1
work = prior_path.parent
executor = RequestExecutor(_config(work))
def hashed(domain, value):
    return 'sha256:' + hashlib.sha256(domain + canonical_bytes(value)).hexdigest()
try:
    assert executor.store.tombstone_high_water()[0] == 1
    now = datetime.now(UTC)
    seed = write_fixture_request()
    for key in ('request_id','request_digest'): seed.pop(key)
    for key,prefix in [('candidate_id','memcand:pos:v1:'),('candidate_digest','sha256:'),('classification_digest','sha256:')]:
        seed[key] = seed['receipt'][key] = prefix + '9'*64
    seed['receipt']['receipt_id'] = 'receipt:memory:'+'9'*64
    seed['subject'] = 'wiki/followup-beta'
    seed['payload'] = {'content':'IndependentBeta 후속기억'}
    seed['created_at'] = seed['receipt']['issued_at'] = format_instant(now)
    seed['expires_at'] = seed['receipt']['expires_at'] = format_instant(now+timedelta(minutes=10))
    identity = {k:seed[k] for k in ('candidate_id','candidate_digest','classification_digest','operation')}
    seed['idempotency_key'] = 'memidem:pos:v1:' + hashed(b'orca-jarvis/memory-write-idempotency/v1\0', identity)[7:]
    seed['receipt_digest'] = hashed(b'orca-jarvis/memory-write-receipt/v1\0',seed['receipt'])
    seed['request_digest'] = hashed(b'orca-jarvis/memory-write-request/v1\0',seed)
    seed['request_id'] = 'memreq:pos:v1:'+seed['request_digest'][7:]
    accept_stable_v1_request(executor.config.request_root, seed, now)
    assert executor.apply_once(now=now).state == 'proved'
    active = executor.generations.active()
    pages = [p for p in (active.root/'wiki').glob('*.md') if 'IndependentBeta 후속기억' in p.read_text()]
    assert len(pages) == 1
    request = effect_request(active, 'correct', 'IndependentBeta 후속기억', now,
        executor.store.tombstone_high_water(), HISTORICAL, '2', correction_content='IndependentBeta corrected 최신기억', page_id=pages[0].relative_to(active.root).with_suffix('').as_posix(),
        source_identity_full=hashlib.sha256(seed['candidate_id'].encode()).hexdigest())
    assert len(request['tombstone_chain_delta']) == 1
    assert request['tombstone_chain_delta'][0]['sequence'] == 2
    assert request['tombstone_chain_delta'][0]['previous_root'] == prior['local_recovery']['settlement']['tombstone_set_root']
    public = HISTORICAL.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    validated = subprocess.run(['node', str(ROOT/'scripts/cancellation-followup-validate.mjs')], input=json.dumps({
        'build':build,'request':request,'now':format_instant(now),'public_key':public}), capture_output=True,text=True,timeout=30, check=False)
    assert validated.returncode == 0, validated.stderr
    accepted = accept_effect_request(executor.config.request_root,request,now,
        public_keys=executor.config.jarvis_public_keys, provider_instance_id=executor.config.provider_instance_id)
    applied = executor.apply_once(now=now)
    assert applied.state == 'proved', applied
    assert applied.request_id == accepted.request_id
    assert executor.store.tombstone_high_water()[0] == 2
    assert executor.apply_once(now=now).state == 'idle'
    result_generation = executor.generations.active()
    files = subprocess.check_output(['git','-C',str(result_generation.root),'ls-tree','-r','--name-only','HEAD','wiki'], text=True).splitlines()
    committed = '\n'.join(subprocess.check_output(['git','-C',str(result_generation.root),'show',f'HEAD:{name}'], text=True) for name in files)
    assert 'IndependentBeta corrected 최신기억' in committed
    assert 'IndependentBeta 후속기억' not in committed
    assert 'ExampleAlpha 예시기록' not in committed
    assert executor.store.tombstone_high_water()[1] == request['tombstone_high_water']['set_root']
    report = {'prior_settlement_evidence':str(prior_path),'python_pid':os.getpid(),
        'jarvis_wire_validation':json.loads(validated.stdout),'provider_state':applied.state,
        'provider_tombstone_sequence':2,'request_id':accepted.request_id,
        'result_generation':result_generation.generation_id,'committed_replacement_found':True,
        'old_and_cancelled_records_absent_from_committed_wiki':True,'repeat_executor_state':'idle',
        'jarvis_dispatch_cursor':1,'scope':'real provider seq2 execution and both wire validators; JARVIS seq2 dispatch/completion not exercised'}
    destination = work/'followup-result.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(destination); print(json.dumps(report,ensure_ascii=False))
finally:
    executor.close()
