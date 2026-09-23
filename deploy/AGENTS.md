# deploy/ — release packaging and cutover gates

Score 7 (below the usual bar), created anyway: this is the only place that encodes what a
release *is* and what a gate is *not allowed* to do, and no parent file covers it. Getting
it wrong activates an unverified release on the operator's machine.

## OVERVIEW
Release scripts are standalone Python CLIs; `prepare-release.py` and
`check-release-compatibility.py` use the project's Pydantic dependency to parse release inputs.
Not a package — there is no
`__init__.py`; tests load these via `runpy.run_path` or
`importlib.util.spec_from_file_location`, and ops runs them as CLIs.

## WHERE TO LOOK
| Need | File |
|------|------|
| Build a release from committed HEAD | `prepare-release.py` → `<app-root>/releases/<release_id>/` |
| Bundle the Python runtime into a release | `bundle_python_runtime.py` — `bundle_runtime`, `runtime_digest`, `release_identity` |
| Byte-identity manifest | `check-release-contents.py` — `inventory`, `verify`, `file_digest` |
| Committed input and wheel compatibility | `check-release-compatibility.py` — `verify`; never activates |
| JARVIS pairing gate | `check-release-integration.py` — `unchanged_candidates` |
| Rollback safety | `check-rollback-compat.py` — `check_rollback`, `RollbackCompatError` |
| Unit drain audit (18 units, both naming schemes) | `check-transition-units.py` — `assess_unit` |
| DB/lease audits | `check-database-handles.py`, `check-jarvis-pending-state.py` (both export `inspect`) |
| Installed unit templates | `deploy/systemd/second-brain{,-web,-backup}.service`, `.timer` |

## CONVENTIONS
- `prepare-release.py` builds from `git archive` of **committed HEAD** and refuses a dirty
  worktree as a production candidate. Staging is `/var/tmp/sb-release-*` with
  `os.umask(0o077)`; release dirs land mode `0700`.
- Release identity schema `sb-release-inputs-v3` binds the wheel, the requirements export,
  the bundled runtime digest, and `preparation_recipe_sha256` — the hash of
  `prepare-release.py`, `bundle_python_runtime.py` and `check-release-contents.py`. Editing
  any of those three changes every future release id.
- `prepare-release.py` uses a sibling import (`from bundle_python_runtime import …`) because
  the script directory is on `sys.path`, not because `deploy` is importable.
- `bundle_python_runtime.py` rejects external symlinks and FIFOs; budgets are 20k files /
  1 GiB.
- Shipped units are hardened by default: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome=read-only`, `RestrictAddressFamilies=AF_UNIX`, `MemoryDenyWriteExecute=yes`,
  `UMask=0077`. The one documented exception is
  `systemd/user/jm-second-brain-refresh.service.d/20-llm-runtime.conf`.

## ANTI-PATTERNS
- **Gates never activate.** Every gate emits an explicit `activation_authorized: false`,
  `drain_authorized: false` or `production_activation_authorized: false`. A zero exit code
  is an observation, not permission to drain a database or flip the `current` symlink.
- `check-release-contents.py` never seals a release, and its inventory must be written
  outside the release root.
- `check-transition-units.py` never stops, masks or restarts a service, and is not a complete
  process gate.
- `check-database-handles.py` never emits process arguments; `check-jarvis-pending-state.py`
  never emits row payloads.
- Rollback and compile-key gates run on disposable fake data — never user data.
- **`deploy/systemd/` is not what production runs.** Production uses the repo's top-level
  `systemd/user/jm-second-brain-*` units (`requests.path`/`.service`, `maintenance.service`/
  `.timer`). `check-transition-units.py` audits both; do not assume they match.

## COMMANDS
```bash
./deploy/install-systemd-user.sh --dry-run      # needs an executable sb at $SB_BIN
uv run --no-sync python deploy/prepare-release.py --offline
python deploy/check-release-contents.py verify <release> <inventory.json> --expected-sha256 <sha>
TMPDIR=/var/tmp python deploy/check-release-integration.py <release> <jarvis-dist>
```
