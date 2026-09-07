from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from sb.request_store import RequestIdentity, RequestStore

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _claim(root: str) -> tuple[str, int] | None:
    store = RequestStore(Path(root))
    try:
        lease = store.claim(f"worker:{os.getpid()}", NOW)
        return None if lease is None else (lease.request_id, lease.fence)
    finally:
        store.close()


def test_two_real_processes_claim_one_logical_request_once(tmp_path: Path) -> None:
    identity = RequestIdentity(
        2, "request:1", "sha256:" + "1" * 64, "sha256:" + "2" * 64,
        "idem:" + "3" * 64, "lane:" + "4" * 64, "correct", "sha256:" + "5" * 64,
        "sha256:" + "6" * 64, "sha256:" + "7" * 64, None, None, None, 0,
        "sha256:" + "0" * 64,
    )
    store = RequestStore(tmp_path)
    _ = store.accept(identity, {"state": "pending"}, NOW)
    store.close()
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_claim, (str(tmp_path), str(tmp_path))))
    assert sum(result is not None for result in results) == 1
