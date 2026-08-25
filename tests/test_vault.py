"""Tests for sb.vault: init, cited atomic writes, lint, human-edit, git, rollback."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sb.contracts import PageSpec, SourceCite
from sb.vault import VaultLintError, init_vault

CAS_HASH = "ab" + ("cd" * 31)
CAS_SID = CAS_HASH[:8]
DEAD_SID = "dead1234"


@dataclass(frozen=True, slots=True)
class MemoryLedger:
    """In-memory last-compiled-hash map. The dict payload is the mutable store."""

    hashes: dict[str, str] = field(default_factory=dict)

    def last_compiled_hash(self, page_id: str) -> str | None:
        return self.hashes.get(page_id)


def _git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _seed_cas(root: Path, digest: str = CAS_HASH, data: bytes = b"blob") -> None:
    dest = root / "raw" / digest[:2] / digest
    _ = dest.parent.mkdir(parents=True, exist_ok=True)
    written = dest.write_bytes(data)
    assert written == len(data)


def _cited_page(
    *,
    page_id: str = "identity-profile",
    body_md: str | None = None,
    sid: str = CAS_SID,
    digest: str = CAS_HASH,
) -> PageSpec:
    text = f"A cited fact.[^{sid}]" if body_md is None else body_md
    cite = SourceCite(sid=sid, origin="me-wiki:identity/profile.md", hash=digest, spans=["0-12"])
    return PageSpec(page_id=page_id, title="Profile", body_md=text, sources=[cite], status="active")


def _record_hash(ledger: MemoryLedger, page_id: str, path: Path) -> None:
    ledger.hashes[page_id] = hashlib.sha256(path.read_bytes()).hexdigest()


def _field(block: str, key: str) -> str:
    prefix = f"{key}:"
    for line in block.splitlines():
        stripped = line.strip().removeprefix("- ")
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip().strip("'\"")
    pytest.fail(f"missing frontmatter key {key}")


def _k1_block(text: str) -> str:
    assert text.startswith("---\n")
    parts = text.split("---", 2)
    assert len(parts) == 3
    return parts[1]


def test_init_vault_creates_layout_perms_and_gitignore_when_root_empty(
    tmp_path: Path,
) -> None:
    vault = init_vault(tmp_path)
    assert vault.root == tmp_path
    for rel in ("wiki", "daily", "conflicts", "inbox", "raw", ".sb", "wiki/_proposed"):
        assert (tmp_path / rel).is_dir(), rel
    assert (tmp_path / "log.md").is_file()
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "raw/" in gitignore
    assert ".sb/" in gitignore
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert (tmp_path / ".git").is_dir()
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert int(_git(tmp_path, "rev-list", "--count", "HEAD").strip()) >= 1


def test_write_pages_renders_k1_and_commits_when_lint_passes(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    result = vault.write_pages([_cited_page()], "run-cited", MemoryLedger())
    dest = tmp_path / "wiki" / "identity-profile.md"
    assert dest.is_file()
    text = dest.read_text(encoding="utf-8")
    block = _k1_block(text)
    assert _field(block, "id") == "identity-profile"
    assert _field(block, "title") == "Profile"
    assert _field(block, "status") == "active"
    assert _field(block, "updated")
    assert _field(block, "compiled_by").startswith("sb/")
    assert _field(block, "sid") == CAS_SID
    assert _field(block, "origin") == "me-wiki:identity/profile.md"
    assert _field(block, "hash") == CAS_HASH
    assert f"[^{CAS_SID}]: me-wiki:identity/profile.md" in text
    assert result.commit is not None
    assert result.pages == 1
    assert result.conflicts == 0
    assert result.proposals == 0
    assert _git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-cited (1 pages, 0 conflicts, 0 proposals)"
    )
    assert _git(tmp_path, "log", "-1", "--format=%an <%ae>").strip() == (
        "second-brain-bot <sb@local>"
    )
    assert list(tmp_path.rglob("*.tmp")) == []


def test_write_pages_counts_conflict_dest_in_commit_message_when_prefixed(
    tmp_path: Path,
) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page(page_id="conflicts/2026-08-25-identity-profile")
    result = vault.write_pages([page], "run-conflict", MemoryLedger())
    assert result.pages == 0
    assert result.conflicts == 1
    assert result.proposals == 0
    assert result.commit is not None
    assert (tmp_path / "conflicts" / "2026-08-25-identity-profile.md").is_file()
    assert _git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-conflict (0 pages, 1 conflicts, 0 proposals)"
    )


def test_write_pages_raises_and_keeps_tree_clean_when_footnote_unresolved(
    tmp_path: Path,
) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page(body_md=f"Poison.[^{DEAD_SID}]", sid=CAS_SID, digest=CAS_HASH)
    with pytest.raises(VaultLintError) as raised:
        unexpected = vault.write_pages([page], "run-dead", MemoryLedger())
        assert unexpected.commit is None
    assert any("unresolved" in reason for reason in raised.value.reasons)
    assert not (tmp_path / "wiki" / "identity-profile.md").exists()
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_raises_when_body_empty(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    with pytest.raises(VaultLintError) as raised:
        unexpected = vault.write_pages([_cited_page(body_md="   \n")], "run-empty", MemoryLedger())
        assert unexpected.commit is None
    assert any("empty body" in reason for reason in raised.value.reasons)
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_raises_when_cas_hash_missing(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    with pytest.raises(VaultLintError) as raised:
        unexpected = vault.write_pages([_cited_page()], "run-cas", MemoryLedger())
        assert unexpected.commit is None
    assert any("missing CAS" in reason for reason in raised.value.reasons)
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_routes_to_proposed_when_human_edited(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page()
    ledger = MemoryLedger()
    original_write = vault.write_pages([page], "run-orig", ledger)
    assert original_write.commit is not None
    assert original_write.pages == 1
    dest = tmp_path / "wiki" / "identity-profile.md"
    _record_hash(ledger, page.page_id, dest)
    original = dest.read_text(encoding="utf-8")
    human_text = original + "\nhuman note\n"
    written = dest.write_text(human_text, encoding="utf-8")
    assert written == len(human_text)
    add_out = _git(tmp_path, "-c", "user.name=human", "-c", "user.email=h@local", "add", "-A")
    assert add_out == ""
    human_git = ("-c", "user.name=human", "-c", "user.email=h@local")
    commit_out = _git(tmp_path, *human_git, "commit", "-m", "human edit")
    assert "human edit" in commit_out
    proposed_write = vault.write_pages([page], "run-proposed", ledger)
    assert proposed_write.pages == 0
    assert proposed_write.conflicts == 0
    assert proposed_write.proposals == 1
    assert proposed_write.commit is not None
    assert dest.read_text(encoding="utf-8") == human_text
    proposed = tmp_path / "wiki" / "_proposed" / "identity-profile.md"
    assert proposed.is_file()
    assert proposed.read_text(encoding="utf-8") != dest.read_text(encoding="utf-8")
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "identity-profile" in log
    assert "_proposed" in log
    assert _git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-proposed (0 pages, 0 conflicts, 1 proposals)"
    )


def test_write_pages_skips_commit_when_content_unchanged(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page()
    ledger = MemoryLedger()
    first = vault.write_pages([page], "run-a", ledger)
    dest = tmp_path / "wiki" / "identity-profile.md"
    _record_hash(ledger, page.page_id, dest)
    count_after_first = int(_git(tmp_path, "rev-list", "--count", "HEAD").strip())
    second = vault.write_pages([page], "run-b", ledger)
    assert first.commit is not None
    assert second.commit is None
    assert second.pages == 1
    assert int(_git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count_after_first
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_rollback_reverts_run_commit_when_run_id_exists(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    written = vault.write_pages([_cited_page()], "run-rb", MemoryLedger())
    assert written.commit is not None
    dest = tmp_path / "wiki" / "identity-profile.md"
    assert dest.is_file()
    vault.rollback("run-rb")
    assert not dest.exists()
    subject = _git(tmp_path, "log", "-1", "--format=%s").strip()
    assert "revert" in subject.lower() or "run-rb" in subject


def test_init_vault_does_not_commit_when_already_initialized(tmp_path: Path) -> None:
    first = init_vault(tmp_path)
    assert first.root == tmp_path
    count = int(_git(tmp_path, "rev-list", "--count", "HEAD").strip())
    stray_n = (tmp_path / "wiki" / "stray.md").write_text("stray\n", encoding="utf-8")
    assert stray_n == len("stray\n")
    second = init_vault(tmp_path)
    assert second.root == tmp_path
    assert int(_git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count
    assert "stray.md" not in _git(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")


def test_write_pages_does_not_stage_unrelated_dirty_files(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    stray_n = (tmp_path / "wiki" / "stray.md").write_text("stray\n", encoding="utf-8")
    assert stray_n == len("stray\n")
    result = vault.write_pages([_cited_page()], "run-scope", MemoryLedger())
    assert result.commit is not None
    assert result.pages == 1
    names = _git(tmp_path, "show", "--name-only", "--format=", "HEAD")
    assert "wiki/identity-profile.md" in names
    assert "stray.md" not in names
    assert "stray.md" in _git(tmp_path, "status", "--porcelain")


def test_append_log_writes_line_when_called(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    vault.append_log("hello from test")
    assert "hello from test" in (tmp_path / "log.md").read_text(encoding="utf-8")
