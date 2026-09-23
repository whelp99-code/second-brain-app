"""T04: installed conflict judgment, held budget, and explicit retry."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Literal, Protocol, TypedDict

from pydantic import TypeAdapter


class Artifact(Protocol):
    interpreter: Path
    fixture_root: Path


class CaseFailure(RuntimeError):
    """An installed conflict assertion failed."""


class ProbeResult(TypedDict):
    code: str
    calls_after_hold: int
    key: str
    error: str
    source: list[str]


_PROBE = '''
import json
import sys
from pathlib import Path
from sb.config import Config
from sb.conflict import check
from sb.contracts import Unit
from sb.llm import LLMUnavailable
from sb.ops import retry_failed
from sb.readiness import readiness
from sb.store.ledger import Ledger
from sb.vault import init_vault

root = Path(sys.argv[1])
raw = sys.argv[2]
scenario = sys.argv[3]
init_vault(root)
config = Config(raw={'vault_root': str(root), 'caps': {'max_derivation_attempts': 1},
                     'llm': {'model_id': 'fake', 'prompt_version': 'v1'}})
units = [Unit(unit_id='left', content_hash='a'*64, span='0-1', text='동일한 기억 사실', origin='me-wiki:left'),
         Unit(unit_id='right', content_hash='b'*64, span='0-1', text='동일한 기억 사실', origin='me-wiki:right')]
class Model:
    def __init__(self, response):
        self.response = response
        self.calls = 0
    def generate(self, prompt, **kwargs):
        self.calls += 1
        if self.response == 'TIMEOUT':
            raise LLMUnavailable(attempts=2, reason='timeout after 120s')
        return self.response

model = Model(raw)
with Ledger(root) as ledger:
    first = check(units, [], ledger, model, config)
    failed = list(ledger.list_derivations(status='failed', stage='conflict'))
    assert len(failed) == 1, failed
    key = failed[0].deriv_key
    second = check(units, [], ledger, model, config)
    assert model.calls == 1 and second[0].failure == 'DERIVATIONS_HELD'
    assert ledger.get_derivation(key).attempts == 1
    error = failed[0].error
    code = first[0].failure
    assert error is not None
    if raw != 'TIMEOUT':
        assert raw not in error
    assert 'hash=' in error and 'length=' in error
    assert 'DERIVATIONS_HELD' in readiness(config)['reasons']
if scenario == 'happy':
    assert retry_failed(root, stage='conflict') == 1
    with Ledger(root) as ledger:
        corrected = Model('{"relation":"supports","confidence":0.9,"rationale":"valid","cites":[]}')
        result = check(units, [], ledger, corrected, config)
        assert corrected.calls == 1 and result[0].route == 'note'
        assert ledger.get_derivation(key).status == 'done'
        assert 'DERIVATIONS_HELD' not in readiness(config)['reasons']
print(json.dumps({'code': code, 'calls_after_hold': model.calls, 'key': key,
                  'error': error, 'source': [item.unit_id for item in units]}))
'''


def run(artifacts: Artifact, scenario: Literal["happy", "failure"]) -> list[str]:
    """Exercise installed wheel judgment and readiness with isolated per-case vaults."""
    cases = (
        ("enum", '{"relation":"invented","confidence":0.9,"rationale":"x"}', "CONFLICT_ENUM_INVALID"),
        ("nan", '{"relation":"supports","confidence":NaN,"rationale":"x"}', "CONFLICT_CONFIDENCE_INVALID"),
        ("cites", '{"relation":"supports","confidence":0.9,"rationale":"x","cites":["forged"]}', "CONFLICT_CITATION_INVALID"),
        ("duplicate", '{"relation":"supports","relation":"unrelated","confidence":0.9,"rationale":"x"}', "CONFLICT_DUPLICATE_KEY"),
        ("timeout", "TIMEOUT", "CONFLICT_TIMEOUT"),
    )
    selected = cases if scenario == "failure" else cases[:1]
    fixture = artifacts.fixture_root / "T04" / scenario
    fixture.mkdir(parents=True, exist_ok=True)
    assertions: list[str] = []
    for name, raw, code in selected:
        root = fixture / name
        result = subprocess.run([str(artifacts.interpreter), "-c", _PROBE, str(root), raw, scenario],
                                cwd=fixture, env={key: value for key, value in os.environ.items()
                                                  if key != "PYTHONPATH"},
                                text=True, capture_output=True, timeout=30, check=False)
        if result.returncode != 0:
            raise CaseFailure(f"{name} installed probe failed: {result.stderr[-500:]}")
        report = TypeAdapter(ProbeResult).validate_json(result.stdout)
        _ = (fixture / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")
        if report["code"] != code or report["calls_after_hold"] != 1:
            raise CaseFailure(f"{name}: expected {code} and one invocation, got {report}")
        assertions.append(f"{name}: {code}, held without another LLM call")
    if scenario == "failure":
        raise CaseFailure("DERIVATIONS_HELD: " + "; ".join(assertions))
    return assertions + ["explicit retry processed corrected verdict for same source"]
