"""The shipping plan's recorded source hashes must match the documents on disk.

A stale ``sources[].sha256`` makes the shipping harness reject the plan as source
drift, so the mismatch is caught here instead of at proposal time.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests.json_fixtures import parse_object

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "shipping-plan.json"


def _drift(plan: Path, root: Path) -> list[str]:
    sources = parse_object(plan.read_text(encoding="utf-8"))["sources"]
    assert isinstance(sources, list)
    drift: list[str] = []
    for source in sources:
        assert isinstance(source, dict)
        recorded = source["sha256"]
        source_path = source["path"]
        assert isinstance(source_path, str)
        target = root / source_path
        if not target.is_file():
            drift.append(f"{source['path']}: expected {recorded}, file missing")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != recorded:
            drift.append(f"{source['path']}: expected {recorded}, actual {actual}")
    return drift


def test_plan_source_hashes_match_the_documents() -> None:
    drift = _drift(PLAN, ROOT)
    assert not drift, "\n".join(["docs/shipping-plan.json sources drift:", *drift])
