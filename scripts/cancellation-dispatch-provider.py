"""Isolated acceptance seed and executor; no authority or accepted response fabrication."""
import base64
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_values import canonical_bytes, format_instant
from sb.mcp_contract import write_fixture_request
from sb.request_executor import RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from tests.test_request_executor import _config

work = Path(sys.argv[1])
key = Ed25519PrivateKey.from_private_bytes(bytes(range(32,64)))
proof_key = Ed25519PrivateKey.from_private_bytes(bytes(range(64,96)))
config_base = _config(work)
executor = RequestExecutor(replace(config_base, provider_signing_key_id="provider:followup", provider_signing_key=proof_key, jarvis_public_keys={**config_base.jarvis_public_keys, "jarvis:followup":key.public_key()}))
now = datetime.now(UTC)
def hashed(domain, value):
    return 'sha256:' + hashlib.sha256(domain + canonical_bytes(value)).hexdigest()
try:
    if sys.argv[2] == 'prepare':
        seed = write_fixture_request()
        for key in ('request_id', 'request_digest'): seed.pop(key)
        for key, prefix in [('candidate_id','memcand:pos:v1:'),('candidate_digest','sha256:'),('classification_digest','sha256:')]:
            seed[key] = seed['receipt'][key] = prefix + '9'*64
        seed['receipt']['receipt_id'] = 'receipt:memory:'+'9'*64
        seed['subject'] = 'wiki/followup-beta'
        seed['payload'] = {'content': 'IndependentBeta 후속기억'}
        seed['created_at'] = seed['receipt']['issued_at'] = format_instant(now)
        seed['expires_at'] = seed['receipt']['expires_at'] = format_instant(now+timedelta(minutes=10))
        identity = {k:seed[k] for k in ('candidate_id','candidate_digest','classification_digest','operation')}
        seed['idempotency_key'] = 'memidem:pos:v1:' + hashed(b'orca-jarvis/memory-write-idempotency/v1\0', identity)[7:]
        seed['receipt_digest'] = hashed(b'orca-jarvis/memory-write-receipt/v1\0', seed['receipt'])
        seed['request_digest'] = hashed(b'orca-jarvis/memory-write-request/v1\0', seed)
        seed['request_id'] = 'memreq:pos:v1:'+seed['request_digest'][7:]
        accept_stable_v1_request(executor.config.request_root, seed, now)
        assert executor.apply_once(now=now).state == 'proved'
        active = executor.generations.active()
        pages = [p for p in (active.root/'wiki').glob('*.md') if 'IndependentBeta 후속기억' in p.read_text()]
        assert len(pages) == 1
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(32,64)))
        public = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode().rstrip('=')
        config = work/'followup-config.toml'
        config.write_text((work/'config.toml').read_text().replace('[jarvis_public_keys]', '[jarvis_public_keys]\n"jarvis:followup" = "'+public+'"'))
        launcher = work/'followup-mcp'
        launcher.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom sb.mcp import main\nmain()\n')
        launcher.chmod(0o700)
        print(json.dumps({'proof_public_key':proof_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), 'config':str(config),'launcher':str(launcher), 'selector': {
            'page_id':pages[0].relative_to(active.root).with_suffix('').as_posix(),
            'exact_record':'IndependentBeta 후속기억', 'source_identity_full':hashlib.sha256(seed['candidate_id'].encode()).hexdigest()}}))
    elif sys.argv[2] == 'apply':
        result = executor.apply_once(now=now)
        assert result.state == 'proved', result
        assert executor.store.tombstone_high_water()[0] == 2
        assert executor.apply_once(now=now).state == 'idle'
        active = executor.generations.active()
        files = subprocess.check_output(['git','-C',str(active.root),'ls-tree','-r','--name-only','HEAD','wiki'],text=True).splitlines()
        committed = '\n'.join(subprocess.check_output(['git','-C',str(active.root),'show',f'HEAD:{name}'],text=True) for name in files)
        assert 'IndependentBeta corrected 최신기억' in committed
        assert 'IndependentBeta 후속기억' not in committed
        assert 'ExampleAlpha 예시기록' not in committed
        print(json.dumps({'request_id': result.request_id, 'state':result.state,
            'generation_id': active.generation_id,'tombstone_sequence':2,
            'tombstone_set_root':executor.store.tombstone_high_water()[1],
            'committed_replacement_found':True,'old_and_cancelled_absent':True,'repeat_state':'idle'}))
    else: raise ValueError('unknown acceptance mode')
finally:
    executor.close()
