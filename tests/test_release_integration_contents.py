"""Acceptance must not bless a candidate changed while its tests were running."""

import importlib.util
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from sb.effect_values import JsonObject


@runtime_checkable
class IntegrationModule(Protocol):
    def unchanged_candidates(self, release: Path, jarvis_root: Path, executable: Path | None = None) -> AbstractContextManager[JsonObject]: ...
    def candidate_harness_commit(self, repo: Path, manifest: JsonObject) -> str: ...


spec = importlib.util.spec_from_file_location("check-release-integration", Path(__file__).resolve().parents[1] / "deploy/check-release-integration.py")
assert spec is not None and spec.loader is not None
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)
assert isinstance(API, IntegrationModule)
unchanged_candidates = API.unchanged_candidates
candidate_harness_commit = API.candidate_harness_commit


@pytest.mark.parametrize("changed", [None, "provider", "jarvis"])
def test_acceptance_binds_both_candidates(tmp_path: Path, changed: str | None):
    roots: dict[str, Path] = {}
    for name in ("provider", "jarvis"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
        _ = (roots[name] / "entry").write_text("accepted")

    def acceptance():
        with unchanged_candidates(
            release=roots["provider"], jarvis_root=roots["jarvis"]
        ) as evidence:
            assert set(evidence) == {"provider", "jarvis"}
            for item in evidence.values():
                assert isinstance(item, dict)
                checksum = item["inventory_sha256"]
                assert isinstance(checksum, str)
                assert len(checksum) == 64
            if changed:
                _ = (roots[changed] / "entry").write_text("replaced")

    if changed:
        with pytest.raises(RuntimeError, match="ACCEPTANCE_CANDIDATE_CHANGED:" + changed):
            acceptance()
    else:
        acceptance()


def test_original_failure_preserved_when_candidates_unchanged(tmp_path: Path):
    with (
        pytest.raises(ValueError, match="transport failed"),
        unchanged_candidates(tmp_path, tmp_path),
    ):
        raise ValueError("transport failed")


def test_runtime_replacement_rejects_acceptance(tmp_path: Path):
    root = tmp_path / "candidate"
    root.mkdir()
    node = tmp_path / "node"
    _ = node.write_bytes(b"original executable")
    with (
        pytest.raises(RuntimeError, match="ACCEPTANCE_CANDIDATE_CHANGED:node_executable"),
        unchanged_candidates(root, root, node),
    ):
        _ = node.write_bytes(b"replacement executable")


def test_harness_uses_candidate_commit_even_when_head_advances(tmp_path: Path):
    import subprocess

    def git(*args: str) -> str:
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()

    _ = git('init', '-q')
    _ = git('config', 'user.email', 'test@example.invalid')
    _ = git('config', 'user.name', 'Test')
    _ = (tmp_path / 'fixture').write_text('candidate')
    _ = git('add', 'fixture')
    _ = git('commit', '-qm', 'candidate')
    commit, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    _ = (tmp_path / 'fixture').write_text('unrelated newer fixture')
    _ = git('commit', '-qam', 'newer')
    resolve = candidate_harness_commit
    assert resolve(tmp_path, {'source_commit': commit, 'source_tree': tree}) == commit
    with pytest.raises(ValueError, match='CANDIDATE_SOURCE_TREE_MISMATCH'):
        _ = resolve(tmp_path, {'source_commit': commit, 'source_tree': git('rev-parse', 'HEAD^{tree}')})
    for invalid in ['HEAD', '--help', None, '0' * 40]:
        with pytest.raises(ValueError, match='CANDIDATE_SOURCE_COMMIT_INVALID'):
            _ = resolve(tmp_path, {'source_commit': invalid, 'source_tree': tree})
