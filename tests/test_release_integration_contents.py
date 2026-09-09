"""Acceptance must not bless a candidate changed while its tests were running."""

import runpy
from pathlib import Path

import pytest

API = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "deploy/check-release-integration.py")
)


@pytest.mark.parametrize("changed", [None, "provider", "jarvis"])
def test_acceptance_binds_both_candidates(tmp_path, changed):
    roots = {}
    for name in ("provider", "jarvis"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
        (roots[name] / "entry").write_text("accepted")

    def acceptance():
        with API["unchanged_candidates"](
            release=roots["provider"], jarvis_root=roots["jarvis"]
        ) as evidence:
            assert set(evidence) == {"provider", "jarvis"}
            assert all(len(item["inventory_sha256"]) == 64 for item in evidence.values())
            if changed:
                (roots[changed] / "entry").write_text("replaced")

    if changed:
        with pytest.raises(RuntimeError, match="ACCEPTANCE_CANDIDATE_CHANGED:" + changed):
            acceptance()
    else:
        acceptance()


def test_original_failure_preserved_when_candidates_unchanged(tmp_path):
    with (
        pytest.raises(ValueError, match="transport failed"),
        API["unchanged_candidates"](tmp_path, tmp_path),
    ):
        raise ValueError("transport failed")


def test_runtime_replacement_rejects_acceptance(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    node = tmp_path / "node"
    node.write_bytes(b"original executable")
    with (
        pytest.raises(RuntimeError, match="ACCEPTANCE_CANDIDATE_CHANGED:node_executable"),
        API["unchanged_candidates"](root, root, node),
    ):
        node.write_bytes(b"replacement executable")
