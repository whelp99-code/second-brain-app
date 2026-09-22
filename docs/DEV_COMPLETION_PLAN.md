# second-brain-app completion plan

## Remaining work

1. Host `python3` is 3.14; collection aborted with 56 errors (3.27s). Use project-required Python (likely 3.12 via uv) and install extras.
2. `pytest` rc 0.
3. No push.

## Done definition

- pytest rc 0 on the version declared in pyproject.toml

## Evidence 2026-09-21

`python3 -m pytest -q --tb=no` rc 2, 56 collection errors.

## Evidence (CPython 3.12 .venv312)

pytest: **20 failed, 1888 passed, 50 skipped, 12 warnings, 532.88s**.
Failures include embeddings hybrid-search/rebuild tests.

Retest embeddings with clean TMPDIR: `EmbeddingUnavailable: sqlite-vec 1024-d store unavailable` (optional dep missing in .venv312).

sqlite-vec 0.1.9 installed. single embeddings test rc=0

`tests/test_embeddings.py` after sqlite-vec: **30 passed, 1 skipped, 1.49s**.
