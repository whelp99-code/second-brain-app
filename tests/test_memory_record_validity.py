from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.generations import GenerationStore
from sb.memory_records import MemoryRecordError, MemoryRecordV1, records_for_page, target_for_record
from sb.targets import GenerationIdentityV1
from tests.test_generations import build_generation


def _seed(root: Path, metadata: str) -> GenerationIdentityV1:
    (root / "wiki").mkdir()
    _ = (root / "wiki/example.md").write_text(
        f"---\n{metadata}---\nRemember this decision.[^aaaaaaaa]\n\n[^aaaaaaaa]: source:example\n"
    )

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    _ = git("init", "-q")
    _ = git("config", "user.name", "Test")
    _ = git("config", "user.email", "test@example.invalid")
    _ = git("add", "wiki/example.md")
    _ = git("commit", "-qm", "seed")
    return GenerationIdentityV1(
        "provider:test", "sbgen:v1:" + "1" * 64, "sha256:" + "2" * 64,
        git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}"),
    )


def test_undated_and_historical_records_have_stable_identity(tmp_path: Path) -> None:
    for name, metadata in (("undated", ""), ("historical", "updated: 2020-01-01\n")):
        root = tmp_path / name
        root.mkdir()
        generation = _seed(root, metadata)
        first = records_for_page(root, "wiki/example", generation, datetime(2026, 9, 7, tzinfo=UTC))
        later = records_for_page(root, "wiki/example", generation, datetime(2027, 1, 1, tzinfo=UTC))
        assert first == later and len(first) == 1
        assert first[0].valid_until == "9999-12-31T23:59:59.000Z"
        if name == "historical":
            assert first[0].valid_from == "2020-01-01T00:00:00.000Z"
        else:
            assert first[0].valid_from == "0001-01-01T00:00:00.000Z"


def test_explicit_validity_is_preserved_and_target_receipt_stays_short(tmp_path: Path) -> None:
    generation = _seed(tmp_path, "updated: 2020-01-01\nvalid_from: 2026-09-01T00:00:00.000Z\n"
                       + "valid_until: 2026-10-01T00:00:00.000Z\n")
    record = records_for_page(tmp_path, "wiki/example", generation)[0]
    now = datetime(2026, 9, 7, tzinfo=UTC)
    target = target_for_record(tmp_path, generation, ("wiki/example", record, now))
    assert record.valid_from == target.valid_from == "2026-09-01T00:00:00.000Z"
    assert record.valid_until == target.valid_until == "2026-10-01T00:00:00.000Z"
    assert target.expires_at == "2026-09-07T00:05:00.000Z"


def test_unknown_start_is_not_the_synthetic_sealed_commit_date(tmp_path: Path) -> None:
    store = GenerationStore(tmp_path / "state", tmp_path / "share",
                            provider_instance_id="provider:test", provider_release_sha="a" * 40)
    text = "Undated assertion.[^aaaaaaaa]\n\n[^aaaaaaaa]: source:example\n"
    try:
        first = build_generation(store, text=text)
        second = build_generation(store, first, text=text)
        assert first.generation_id != second.generation_id
        records: list[tuple[MemoryRecordV1, ...]] = []
        for generation in (first, second):
            manifest = generation.manifest
            identity = GenerationIdentityV1(
                manifest.provider_instance_id, generation.generation_id,
                manifest.generation_digest, manifest.head, manifest.tree,
            )
            records.append(records_for_page(generation.root, "wiki/value", identity))
        assert records[0] == records[1]
        assert records[0][0].valid_from == "0001-01-01T00:00:00.000Z"
    finally:
        store.close()


@pytest.mark.parametrize("metadata", [
    "updated: 2026-02-30\n",
    "valid_from: 2026-09-07T00:00:00Z\n",
    "valid_from: 2026-09-07T00:00:00.000Z\nvalid_until: 2026-09-07T00:00:00.000Z\n",
    "valid_from: 2026-09-07T00:00:00.000Z\nvalid_until: 2026-09-06T00:00:00.000Z\n",
    "valid_until: not-an-instant\n",
])
def test_invalid_intervals_are_not_replaced_by_defaults(tmp_path: Path, metadata: str) -> None:
    generation = _seed(tmp_path, metadata)
    with pytest.raises(MemoryRecordError, match="EFFECT_TARGET_INVALID"):
        _ = records_for_page(tmp_path, "wiki/example", generation)
