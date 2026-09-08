"""Compare compiled JARVIS and provider V4 codecs; no authority or writes granted."""
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sb.scoped_write_request import parse_scoped_write_request


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def reseal(value):
    base = {key: item for key, item in value.items() if key not in {"request_id", "request_digest"}}
    checksum = hashlib.sha256(b"orca-jarvis/memory-scoped-write-request/v4\0" + canonical(base).encode()).hexdigest()
    value.update(request_id="memreq:scoped:v4:" + checksum, request_digest="sha256:" + checksum)
    return value


def main():
    build = Path(sys.argv[1]).resolve()
    fixture = json.loads(Path("tests/fixtures/scoped_write_request_v4.json").read_text())
    now = datetime.fromisoformat(fixture["created_at"])
    cases = [{"name": "valid", "request": fixture, "expected": True}]
    changes = [
        ("wrong_provider", ["provider_instance_id"], "provider:other"),
        ("writer_lf", ["writer", "agent_id"], "agent:bad\n"),
        ("writer_cr", ["writer", "agent_id"], "agent:bad\r"),
        ("writer_owner", ["writer", "principal_id"], "principal:other"),
        ("scope_changed", ["preparation", "binding", "identity", "projects"], ["project:other"]),
        ("candidate_changed", ["preparation", "binding", "identity", "candidate_digest"], "sha256:" + "a" * 64),
        ("body_changed", ["preparation", "payload", "content"], "changed"),
        ("authority_label", ["preparation", "writes_authorized"], True),
        ("unknown_key", ["preparation", "extra"], "unexpected"),
        ("expired", ["expires_at"], fixture["created_at"]),
        ("extended", ["expires_at"], "2099-01-01T00:00:00.000Z"),
        ("idempotency_changed", ["idempotency_key"], "memidem:scoped:v4:" + "a" * 64),
    ]
    for name, path, value in changes:
        request = copy.deepcopy(fixture)
        target = request
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        cases.append({"name": name, "request": reseal(request), "expected": False})
    javascript = '''
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
const {parseMemoryScopedWriteRequestJson} = await import(pathToFileURL(process.argv[1] + '/src/memory-scoped-write-codec.js'));
const {canonicalize} = await import(pathToFileURL(process.argv[1] + '/src/canonical.js'));
const cases = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(cases.map(c => {
  try { const value = parseMemoryScopedWriteRequestJson(canonicalize(c.request), 'provider:fixture', new Date(cases[0].request.created_at));
    return {name:c.name, accepted:true, canonical:canonicalize(value)};
  } catch { return {name:c.name, accepted:false}; }
})));
'''
    node = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", javascript, str(build)],
        input=canonical(cases), text=True, timeout=30))
    results = []
    for case, observed in zip(cases, node, strict=True):
        try:
            decoded = parse_scoped_write_request(case["request"], now=now, expected_provider="provider:fixture")
            accepted = True
        except ValueError:
            accepted = False
        assert observed["name"] == case["name"]
        assert accepted == observed["accepted"] == case["expected"], (case["name"], observed, accepted)
        if accepted:
            assert decoded.canonical.decode() == observed["canonical"]
        results.append({"case": case["name"], "jarvis_accepted": observed["accepted"], "provider_accepted": accepted})
    print(json.dumps({"fixture_authority": True, "provider_calls": 0, "approval_consumed": False,
        "cases": results, "accepted": 1, "rejected": len(results) - 1, "canonical_bytes_match": True}, indent=2))


if __name__ == "__main__":
    main()
