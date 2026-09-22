# tests/ — suite conventions

Score 10 (distinct domain: 216 files / 30.4k LOC with a cross-import fixture web that no
other tree uses). Commands and "no sleeps" are in the repo-root `AGENTS.md`; this file is
about how the suite is wired.

## OVERVIEW
Flat package imported as `tests.<module>`. There is no `tests/__init__.py` and no per-
directory conftest — `tests/conftest.py` is the single plugin for `tests/`,
`tests/integration/` and `tests/fixtures/` alike.

## WHERE TO LOOK
| Need | Location |
|------|----------|
| Global isolation | `conftest.py` autouse `secure_test_umask`: umask `0o077`, `SB_CONFIG` → an absent file under `tmp_path`, `XDG_DATA_HOME` → tmp, `SB_MCP_CONTRACT_PROFILE="task30-schema3"` restored after each test |
| Vault/page helpers | `knowledge.py` (`stamp_knowledge`, `commit_page`, `register_page`), `vault_test_support.py` (`CitedPageFixture`, `MemoryLedger`, `git`) |
| MCP client wrapper | `mcp_test_support.py` — `call(server, name, arguments)` wraps `anyio.run` + MCP `Client` |
| Task-30 chain | `task30_clock.py` (`FrozenTask30DateTime`), `task30_effect_factory.py`, `task30_process_harness.py` (`executor_config`, the widest-fan-in helper in the repo), `task30_restore_factory.py` |
| Real-process end-to-end | `integration/` — `subprocess.run([sys.executable, "-m", "sb.cli", …])`, spawn `Process`, MCP stdio; gate file `integration/test_walking_skeleton.py` |
| Corpora and eval vectors | `fixtures/` — mirrored `second-brain/` vs `wiki-spike/` trees, `korean_*_v1.json`, `scoped_write_request_v4.json` |
| Subprocess workers | `restore_kill_worker.py`, `restore_stdio_server.py`, `fixtures/task30_provider_worker.py`, `fixtures/generation_compile_worker.py` |

## CONVENTIONS
- Test modules double as fixture libraries. Importing an underscored helper across files
  (`test_web._ready/_request`, `test_request_executor._config`, `test_ops._seed_vault`) is
  normal here and is not a smell. `test_web` has the highest inbound import count.
- Clocks are frozen constants, never `datetime.now()`: `NOW = 2026-08-31T00:00:01Z` in the
  task-30 helpers, `TODAY = date(2026, 8, 26)` in CLI tests.
- Temp vaults get an isolated git identity: `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` =
  `os.devnull`, `user.name=second-brain-test`, `commit.gpgsign=false`.
- Synchronization uses pipes, `Event`s and Unix barrier sockets. There is zero `sleep(` in
  `tests/` — a timing wait is a defect, not a fallback.
- Fixture Python is dual-mode: importable *and* a CLI (`python -m tests.fixtures.
  jarvis_memory_provider {init,serve,apply,seed} <root>`), and refuses to run unless the
  target root is empty and carries a `.jarvis-memory-probe` marker.
- Optional/gated: `test_embeddings.py` needs the `embeddings` extra; sqlite-vec tests use
  module-level `pytestmark = skipif`; live smokes need `SB_LIVE_EMB`/`SB_LIVE_DB`/`SB_LIVE_LLM`;
  `/proc`-based tests are Linux-only.
- Connector tests follow `test_connectors_<name>.py` and cover parse, skip, and
  unchanged-cursor resume.

## ANTI-PATTERNS
- Secret-shaped fixture rows use `FORBIDDEN_*` tokens, never live credentials. Connectors
  must skip them; a test that ingests one is asserting the wrong thing.
- Korean eval sets are `dataset_origin: "synthetic"` — they are not real user questions and
  not a substitute for live quality acceptance.
- `test_effect_knowledge_sigkill.py`: do not reuse an `Event` lock after killing its waiting
  process.
- `restore_kill_worker.py` monkeypatches `_extract`/`materialize` then `SIGKILL`s a child —
  fault hooks stay in the worker, never in production code.
