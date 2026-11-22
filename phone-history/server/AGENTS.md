> ENGINEERING-MAP-START: 작업을 시작하면 `/home/jm/orca/engineering-vault/index.json`에서 이 디렉터리의 프로젝트 기록을 읽고 relations와 depends_on을 따라간다. 측정하지 않은 배포는 unknown이다. 이 문장은 기존 규칙을 바꾸지 않는다.

# phone-history/server — ingest service

Score 10 (distinct domain: stdlib HTTP ingest, not the `sb` engine and not the iOS app). Numbered module rules, the route table, and the predevice gate live in `../AGENTS.md`. This file is the Python package map only.

## OVERVIEW
`phone_history` is a hatchling package rooted at `server/` (`phone-history/pyproject.toml`). `__init__.py` exports `__version__` (`0.1.0-predevice`) and nothing else. Entry is `phone_history.cli:main` (`python -m phone_history`).

## WHERE TO LOOK
| Need | Module |
|------|--------|
| Bind, token, master key, data dir | `config.py` — `Settings.from_environment` |
| Path dispatch | `api.py` — `PhoneHistoryHTTPServer` (`ThreadingHTTPServer`) |
| Batch parse | `models.py` — `parse_batch`, `PhoneEvent`, `EventBatch` |
| Dedup, tombstones, attachments | `repository.py` (856 lines) — `Repository` |
| Use cases | `service.py` — `PhoneHistoryService` |
| Inbox handoff | `sink.py` — `EventSink`, `DisabledSink`, `SecondBrainSink` |
| Envelope | `crypto.py` `SecretBox`; `transport.py` seal/open |
| Scrub | `redaction.py` — `redact_fields`, `redact_text` |
| Typed failures | `errors.py` |

## CONVENTIONS
- No web framework. `api.py` dispatches on `parsed.path`. `log_message` is a no-op so query strings are not logged.
- Secrets stay in the environment (`PHONE_HISTORY_API_TOKEN` ≥ 32 chars, `PHONE_HISTORY_MASTER_KEY_B64` → 32 bytes). `Settings` does not serialize them.
- Default bind `127.0.0.1:8787`. Data dir default `~/.local/share/phone-history`, mode `0700`. DB file `phone-history.sqlite3`.
- Auth is `Authorization: Bearer <token>` checked with `hmac.compare_digest`. Encrypted batches open through `open_transport_payload` before parse.
- The only `sb` imports are lazy, inside `SecondBrainSink` (`sb.uploads`, `sb.search`). Other modules stay on `phone_history.*`.
- Root `uv run pytest` does not collect `phone-history/tests`. Packaging and `pythonpath` are in `../AGENTS.md`.

## ANTI-PATTERNS
- Do not add a public barrel to `__init__.py`.
- Do not expose the bind on public HTTP; TLS belongs in front of the process.
- `repository.py`: original attachments are never pruned by time. The retention field is not a delete license.
- `SinkError` must leave the event pending. Do not treat export failure as delivered.
- Do not log `Authorization` or master-key material. `log_message` staying empty is the guard.

## COMMANDS
```bash
cd phone-history && python3 -m phone_history serve --help
python3 -m pytest -q tests/test_api.py tests/test_second_brain_sink.py
```
