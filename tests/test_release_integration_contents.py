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


def test_harness_uses_candidate_commit_even_when_head_advances(tmp_path):
    import subprocess

    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()

    git('init', '-q')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Test')
    (tmp_path / 'fixture').write_text('candidate')
    git('add', 'fixture')
    git('commit', '-qm', 'candidate')
    commit, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    (tmp_path / 'fixture').write_text('unrelated newer fixture')
    git('commit', '-qam', 'newer')
    resolve = API['candidate_harness_commit']
    assert resolve(tmp_path, {'source_commit': commit, 'source_tree': tree}) == commit
    with pytest.raises(ValueError, match='CANDIDATE_SOURCE_TREE_MISMATCH'):
        resolve(tmp_path, {'source_commit': commit, 'source_tree': git('rev-parse', 'HEAD^{tree}')})
    for invalid in ['HEAD', '--help', None, '0' * 40]:
        with pytest.raises(ValueError, match='CANDIDATE_SOURCE_COMMIT_INVALID'):
            resolve(tmp_path, {'source_commit': invalid, 'source_tree': tree})
