> ENGINEERING-MAP-START: 작업을 시작하면 `/home/jm/orca/engineering-vault/index.json`에서 이 디렉터리의 프로젝트 기록을 읽고 relations와 depends_on을 따라간다. 측정하지 않은 배포는 unknown이다. 이 문장은 기존 규칙을 바꾸지 않는다.

# Phone History module rules

Score 14 — a self-contained subproject inside this repo: its own `pyproject.toml`
(`phone-history`, hatchling, package `server/phone_history`), its own `Makefile`, its own
`VERSION`, and an iOS app. The repo-root `AGENTS.md` layer table and `uv run` gates describe
the `sb` engine and do **not** apply here.

These rules apply only under `phone-history/`.

1. `contracts/phone-event-v1.schema.json`, `contracts/fixtures/event-batch.json`, and `contracts/openapi.yaml` are the client/server contract source of truth.
2. Regenerate Swift contract files after contract changes; never hand-edit `Generated*.swift`.
3. Never write directly to Second Brain wiki/daily/canonical stores. Use the inbox sink only.
4. New candidates start `UNVERIFIED`, `UNREVIEWED`, and `canonical=false`.
5. Share Extension performs local encrypted queue writes only; no network calls.
6. Do not add global screen, keyboard, notification, VPN/DNS, or private app-database collection.
7. A-dot call classification must be user-declared and audio-validated.
8. Never delete a local queue event based only on HTTP 2xx; require an explicit event receipt.
9. Do not add secrets, real tokens, Apple Team IDs, provisioning profiles, or user recordings to git.
10. `scripts/run_predevice_gate.py` must pass before device handoff. Device closure also requires D1-D12 evidence.

## WHERE TO LOOK
| Need | Location |
|------|----------|
| Contract source of truth | `contracts/openapi.yaml`, `contracts/phone-event-v1.schema.json`, `contracts/fixtures/event-batch.json` |
| HTTP server (stdlib, path-dispatched) | `server/phone_history/api.py` — `/healthz`, `/v1/{capabilities,sync/status,timeline,episodes,candidates,events:batch,events:encrypted,maintenance}` |
| Storage, dedup, tombstones (839 LOC, largest file) | `server/phone_history/repository.py` |
| Second Brain handoff | `server/phone_history/sink.py` — `EventSink` protocol, `DisabledSink`, `SinkError`; inbox-only, one-way |
| PII/secret scrubbing | `server/phone_history/redaction.py` — `redact_fields` |
| Envelope crypto | `server/phone_history/crypto.py`; queue side is `ios/Core/SecureEventQueue.swift` |
| CLI entry | `phone-history = "phone_history.cli:main"` |
| iOS app | `ios/` (see `ios/AGENTS.md`) |
| Current verdict | `evidence/predevice-gate-result.json` — authoritative over prose in `README.md` |

## CONVENTIONS
- Python packaging here is hatchling + plain `python3 -m pytest`, not `uv`.
  `[tool.pytest.ini_options] pythonpath = ["server", ".."]` is what makes both
  `phone_history.*` and the parent repo importable from tests.
- Ruff config is local: `line-length = 100`, `select = ["E","F","I","B","UP","SIM","RUF"]`.
- `scripts/` uses snake_case module names; the two device-side gates are shell
  (`mac_predevice_gate.sh`, `physical_device_gate.sh`).
- The gate writes one log per step into `evidence/`, then runs `git diff --check` against
  `phone-history` from the repo root — so regenerated Swift must already be committed-clean.

## ANTI-PATTERNS
- `make verify` delegates to `scripts/run_predevice_gate.py`; set `PYTHON` when using an existing environment. Static PASS is not an Xcode build or device PASS.
- Do not hand-edit `ios/Core/Generated*.swift` (rule 2). `GeneratedAPIPaths.swift` pins
  `openAPISHA256` — changing `contracts/openapi.yaml` without regenerating breaks the gate.
- Do not treat an HTTP 2xx as delivery (rule 8): local queue deletion requires an explicit
  per-event receipt.

## COMMANDS
```bash
python3 scripts/run_predevice_gate.py     # canonical gate; writes evidence/*.log + result JSON
python3 -m pytest -q                      # from phone-history/
python3 -m ruff check server tests scripts
```
