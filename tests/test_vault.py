"""Tests for sb.vault: init, cited atomic writes, lint, human-edit, git, rollback."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

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
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _cited_page(
    *,
    page_id: str = "identity-profile",
    body_md: str | None = None,
    sid: str = CAS_SID,
    digest: str = CAS_HASH,
) -> PageSpec:
    text = f"A cited fact.[^{sid}]" if body_md is None else body_md
    return PageSpec(
        page_id=page_id,
        title="Profile",
        body_md=text,
        sources=[
            SourceCite(
                sid=sid,
                origin="me-wiki:identity/profile.md",
                hash=digest,
                spans=["0-12"],
            )
        ],
        status="active",
    )


def _record_hash(ledger: MemoryLedger, page_id: str, path: Path) -> None:
    ledger.hashes[page_id] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_init_vault_creates_layout_perms_and_gitignore_when_root_empty(
    tmp_path: Path,
) -> None:
    # Given an empty directory
    # When init_vault runs
    vault = init_vault(tmp_path)

    # Then the K1 vault layout, 0700 root, gitignore, and an init commit exist
    assert vault.root == tmp_path
    for rel in (
        "wiki",
        "daily",
        "conflicts",
        "inbox",
        "raw",
        ".sb",
        "wiki/_proposed",
    ):
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
    # Given an initialized vault with the source blob in CAS
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page()

    # When a cited page is written
    result = vault.write_pages([page], "run-cited", MemoryLedger())

    # Then the wiki file has K1 frontmatter, a resolving footnote, and one bot commit
    dest = tmp_path / "wiki" / "identity-profile.md"
    assert dest.is_file()
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1])
    assert meta["id"] == "identity-profile"
    assert meta["title"] == "Profile"
    assert meta["status"] == "active"
    assert meta["updated"]
    assert meta["compiled_by"].startswith("sb/")
    assert meta["sources"][0]["sid"] == CAS_SID
    assert meta["sources"][0]["origin"] == "me-wiki:identity/profile.md"
    assert meta["sources"][0]["hash"] == CAS_HASH
    assert f"[^{CAS_SID}]: me-wiki:identity/profile.md" in text
    assert result.commit is not None
    assert _git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-cited (1 pages, 0 conflicts, 0 proposals)"
    )
    assert _git(tmp_path, "log", "-1", "--format=%an <%ae>").strip() == (
        "second-brain-bot <sb@local>"
    )
    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == []


def test_write_pages_counts_conflict_dest_in_commit_message_when_prefixed(
    tmp_path: Path,
) -> None:
    # Given a conflict PageSpec
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page(page_id="conflicts/2026-08-25-identity-profile")

    # When it is written
    vault.write_pages([page], "run-conflict", MemoryLedger())

    # Then it lands under conflicts/ and the commit counts it as a conflict
    assert (tmp_path / "conflicts" / "2026-08-25-identity-profile.md").is_file()
    assert _git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-conflict (0 pages, 1 conflicts, 0 proposals)"
    )


def test_write_pages_raises_and_keeps_tree_clean_when_footnote_unresolved(
    tmp_path: Path,
) -> None:
    # Given a PageSpec whose body cites a sid that is not in sources
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page(body_md=f"Poison.[^{DEAD_SID}]", sid=CAS_SID, digest=CAS_HASH)

    # When write_pages lints
    with pytest.raises(VaultLintError):
        vault.write_pages([page], "run-dead", MemoryLedger())

    # Then nothing is written and git status stays clean
    assert not (tmp_path / "wiki" / "identity-profile.md").exists()
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_raises_when_body_empty(tmp_path: Path) -> None:
    # Given a cited source but an empty body
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page(body_md="   \n")

    # When write_pages lints
    with pytest.raises(VaultLintError):
        vault.write_pages([page], "run-empty", MemoryLedger())

    # Then the tree is unchanged
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_raises_when_cas_hash_missing(tmp_path: Path) -> None:
    # Given no CAS blob for the source hash
    vault = init_vault(tmp_path)
    page = _cited_page()

    # When write_pages lints
    with pytest.raises(VaultLintError):
        vault.write_pages([page], "run-cas", MemoryLedger())

    # Then no page is committed
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_routes_to_proposed_when_human_edited(tmp_path: Path) -> None:
    # Given a compiled page whose ledger hash matches the file
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page()
    ledger = MemoryLedger()
    vault.write_pages([page], "run-orig", ledger)
    dest = tmp_path / "wiki" / "identity-profile.md"
    _record_hash(ledger, page.page_id, dest)
    original = dest.read_text(encoding="utf-8")

    # When a human edits the page and compile writes again
    dest.write_text(original + "\nhuman note\n", encoding="utf-8")
    _git(tmp_path, "-c", "user.name=human", "-c", "user.email=h@local", "add", "-A")
    _git(
        tmp_path,
        "-c",
        "user.name=human",
        "-c",
        "user.email=h@local",
        "commit",
        "-m",
        "human edit",
    )
    vault.write_pages([page], "run-proposed", ledger)

    # Then the human file is kept and the bot write goes to _proposed
    assert dest.read_text(encoding="utf-8") == original + "\nhuman note\n"
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
    # Given a page already written and recorded in the ledger
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page()
    ledger = MemoryLedger()
    first = vault.write_pages([page], "run-a", ledger)
    dest = tmp_path / "wiki" / "identity-profile.md"
    _record_hash(ledger, page.page_id, dest)
    count_after_first = int(_git(tmp_path, "rev-list", "--count", "HEAD").strip())

    # When the same page is written again
    second = vault.write_pages([page], "run-b", ledger)

    # Then no new commit is created
    assert first.commit is not None
    assert second.commit is None
    assert int(_git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count_after_first
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_rollback_reverts_run_commit_when_run_id_exists(tmp_path: Path) -> None:
    # Given a cited write that produced a run commit
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    page = _cited_page()
    vault.write_pages([page], "run-rb", MemoryLedger())
    dest = tmp_path / "wiki" / "identity-profile.md"
    assert dest.is_file()

    # When rollback targets that run
    vault.rollback("run-rb")

    # Then the run's page is gone and HEAD is a revert
    assert not dest.exists()
    subject = _git(tmp_path, "log", "-1", "--format=%s").strip()
    assert "revert" in subject.lower() or "run-rb" in subject


def test_init_vault_does_not_commit_when_already_initialized(tmp_path: Path) -> None:
    # Given an initialized vault with an uncommitted stray file
    init_vault(tmp_path)
    count = int(_git(tmp_path, "rev-list", "--count", "HEAD").strip())
    (tmp_path / "wiki" / "stray.md").write_text("stray\n", encoding="utf-8")

    # When init_vault is invoked again
    init_vault(tmp_path)

    # Then no new commit is created and the stray file is not in HEAD
    assert int(_git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count
    tracked = _git(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")
    assert "stray.md" not in tracked


def test_write_pages_does_not_stage_unrelated_dirty_files(tmp_path: Path) -> None:
    # Given a stray uncommitted wiki file beside a cited write
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    (tmp_path / "wiki" / "stray.md").write_text("stray\n", encoding="utf-8")

    # When a cited page is written
    vault.write_pages([_cited_page()], "run-scope", MemoryLedger())

    # Then the bot commit contains only the page it wrote
    names = _git(tmp_path, "show", "--name-only", "--format=", "HEAD")
    assert "wiki/identity-profile.md" in names
    assert "stray.md" not in names
    assert "stray.md" in _git(tmp_path, "status", "--porcelain")


def test_append_log_writes_line_when_called(tmp_path: Path) -> None:
    # Given an initialized vault
    vault = init_vault(tmp_path)

    # When a log line is appended
    vault.append_log("hello from test")

    # Then log.md contains that line
    assert "hello from test" in (tmp_path / "log.md").read_text(encoding="utf-8")
