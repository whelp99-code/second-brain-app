from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sb.vault import (
    GenerationAuthorityRequiredError,
    GitCommandError,
    PathEscapeError,
    VaultLintError,
    init_vault,
)
from tests.vault_test_support import (
    DEAD_SID,
    CitedPageFixture,
    MemoryLedger,
    cited_page,
    git,
    ready,
)


def test_rollback_requires_generation_authority_and_changes_zero_bytes(tmp_path: Path) -> None:
    vault = ready(tmp_path)
    written = vault.write_pages([cited_page()], "run-rb", MemoryLedger())
    destination = tmp_path / "wiki" / "identity-profile.md"
    before = git(tmp_path, "rev-parse", "HEAD")
    assert written.commit is not None and destination.is_file()
    with pytest.raises(
        GenerationAuthorityRequiredError,
        match="ROLLBACK_REQUIRES_GENERATION_AUTHORITY",
    ):
        vault.rollback("run-rb")
    assert destination.is_file() and git(tmp_path, "rev-parse", "HEAD") == before


def test_append_log_writes_line_when_called(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    vault.append_log("hello from test")
    assert "hello from test" in (tmp_path / "log.md").read_text(encoding="utf-8")


def test_write_pages_commits_log_line_with_page_when_content_changes(tmp_path: Path) -> None:
    result = ready(tmp_path).write_pages(
        [cited_page()], "run-log", MemoryLedger(), log_line="status run-log pages=1"
    )
    assert result.commit is not None
    names = git(tmp_path, "show", "--name-only", "--format=", "HEAD")
    assert "wiki/identity-profile.md" in names and "log.md" in names
    assert "run-log" in git(tmp_path, "show", "HEAD:log.md")
    assert git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_skips_log_and_commit_when_page_unchanged(tmp_path: Path) -> None:
    vault, page, ledger = ready(tmp_path), cited_page(), MemoryLedger()
    first = vault.write_pages([page], "run-a", ledger, log_line="status run-a pages=1")
    destination = tmp_path / "wiki" / "identity-profile.md"
    ledger.hashes[page.page_id] = hashlib.sha256(destination.read_bytes()).hexdigest()
    before = (tmp_path / "log.md").read_bytes()
    count = int(git(tmp_path, "rev-list", "--count", "HEAD").strip())
    second = vault.write_pages([page], "run-b", ledger, log_line="status run-b pages=1")
    assert first.commit is not None and second.commit is None
    assert (tmp_path / "log.md").read_bytes() == before
    assert "run-b" not in (tmp_path / "log.md").read_text(encoding="utf-8")
    assert int(git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count
    assert git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_restores_log_when_lint_or_path_fails(tmp_path: Path) -> None:
    vault = ready(tmp_path)
    before = (tmp_path / "log.md").read_bytes()
    with pytest.raises(VaultLintError) as linted:
        unexpected = vault.write_pages(
            [cited_page(CitedPageFixture(body_md=f"Poison.[^{DEAD_SID}]"))],
            "run-lint",
            MemoryLedger(),
            log_line="status run-lint",
        )
        assert unexpected.commit is None
    assert any("unresolved" in reason for reason in linted.value.reasons)
    with pytest.raises(PathEscapeError) as path_error:
        unexpected = vault.write_pages(
            [cited_page(CitedPageFixture(page_id="../outside"))],
            "run-path",
            MemoryLedger(),
            log_line="status run-path",
        )
        assert unexpected.commit is None
    assert "outside" in str(path_error.value)
    assert (tmp_path / "log.md").read_bytes() == before
    assert git(tmp_path, "status", "--porcelain") == ""
    assert git(tmp_path, "diff", "--cached", "--name-only") == ""


def test_write_pages_restores_page_log_index_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = ready(tmp_path)
    before = (tmp_path / "log.md").read_bytes()
    destination = tmp_path / "wiki" / "identity-profile.md"

    def fail_commit(root: Path, message: str, paths: list[Path] | None = None) -> str | None:
        del message
        if paths:
            relative = [str(path.resolve().relative_to(root.resolve())) for path in paths]
            assert git(root, "add", "--", *relative) == ""
        raise GitCommandError(argv=("commit",), stderr="simulated")

    monkeypatch.setattr("sb.vault._commit_if_changed", fail_commit)
    with pytest.raises(GitCommandError) as raised:
        unexpected = vault.write_pages(
            [cited_page()], "run-fail", MemoryLedger(), log_line="status run-fail"
        )
        assert unexpected.commit is None
    assert "simulated" in str(raised.value)
    assert (tmp_path / "log.md").read_bytes() == before
    assert not destination.exists()
    assert git(tmp_path, "status", "--porcelain") == ""
    assert git(tmp_path, "diff", "--cached", "--name-only") == ""
