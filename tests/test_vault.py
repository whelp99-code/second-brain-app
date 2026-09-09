from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest

from sb.contracts import PageSpec, SourceCite
from sb.vault import GitCommandError, PathEscapeError, Vault, VaultLintError, init_vault
from tests.vault_test_support import (
    CAS_HASH,
    CAS_SID,
    DEAD_SID,
    CitedPageFixture,
    MemoryLedger,
    cited_page,
    frontmatter_field,
    git,
    ready,
)


def _git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=env
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


def _field(block: str, key: str) -> str:
    prefix = f"{key}:"
    for line in block.splitlines():
        stripped = line.strip().removeprefix("- ")
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip().strip("'\"")
    pytest.fail(f"missing frontmatter key {key}")


def _ready(tmp_path: Path) -> Vault:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path)
    return vault


def test_init_vault_creates_layout_perms_and_gitignore_when_root_empty(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    assert vault.root == tmp_path
    for relative in ("wiki", "daily", "conflicts", "inbox", "raw", ".sb", "wiki/_proposed"):
        assert (tmp_path / relative).is_dir(), relative
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert (tmp_path / "log.md").is_file() and (tmp_path / ".git").is_dir()
    assert "raw/" in gitignore and ".sb/" in gitignore
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert git(tmp_path, "status", "--porcelain") == ""
    assert int(git(tmp_path, "rev-list", "--count", "HEAD").strip()) >= 1


def test_write_pages_renders_k1_and_commits_when_lint_passes(tmp_path: Path) -> None:
    result = ready(tmp_path).write_pages([cited_page()], "run-cited", MemoryLedger())
    destination = tmp_path / "wiki" / "identity-profile.md"
    assert destination.is_file()
    text = destination.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    parts = text.split("---", 2)
    assert len(parts) == 3
    block = parts[1]
    assert frontmatter_field(block, "id") == "identity-profile"
    assert frontmatter_field(block, "title") == "Profile"
    assert frontmatter_field(block, "status") == "active"
    assert frontmatter_field(block, "updated")
    assert frontmatter_field(block, "compiled_by").startswith("sb/")
    assert frontmatter_field(block, "sid") == CAS_SID
    assert frontmatter_field(block, "origin") == "me-wiki:identity/profile.md"
    assert frontmatter_field(block, "hash") == CAS_HASH
    assert f"[^{CAS_SID}]: me-wiki:identity/profile.md" in text
    assert result.commit is not None
    assert (result.pages, result.conflicts, result.proposals) == (1, 0, 0)
    assert git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-cited (1 pages, 0 conflicts, 0 proposals)"
    )
    assert (
        _git(tmp_path, "log", "-1", "--format=%an <%ae>").strip() == "second-brain-bot <sb@local>"
    )
    assert list(tmp_path.rglob("*.tmp")) == []


def test_write_pages_counts_conflict_dest_in_commit_message_when_prefixed(tmp_path: Path) -> None:
    page = cited_page(CitedPageFixture(page_id="conflicts/2026-08-25-identity-profile"))
    result = ready(tmp_path).write_pages([page], "run-conflict", MemoryLedger())
    assert (result.pages, result.conflicts, result.proposals) == (0, 1, 0)
    assert result.commit is not None
    assert (tmp_path / "conflicts" / "2026-08-25-identity-profile.md").is_file()
    assert git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-conflict (0 pages, 1 conflicts, 0 proposals)"
    )


def test_write_pages_raises_and_keeps_tree_clean_when_footnote_unresolved(
    tmp_path: Path,
) -> None:
    vault = ready(tmp_path)
    page = cited_page(CitedPageFixture(
        body_md=f"Poison.[^{DEAD_SID}]",
        sid=CAS_SID,
        digest=CAS_HASH,
    ))
    with pytest.raises(VaultLintError) as raised:
        unexpected = vault.write_pages([page], "run-dead", MemoryLedger())
        assert unexpected.commit is None
    assert any("unresolved" in reason for reason in raised.value.reasons)
    assert not (tmp_path / "wiki" / "identity-profile.md").exists()
    assert git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_raises_when_body_empty(tmp_path: Path) -> None:
    vault = ready(tmp_path)
    with pytest.raises(VaultLintError) as raised:
        unexpected = vault.write_pages(
            [cited_page(CitedPageFixture(body_md="   \n"))],
            "run-empty",
            MemoryLedger(),
        )
        assert unexpected.commit is None
    assert any("empty body" in reason for reason in raised.value.reasons)
    assert git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_raises_when_cas_hash_missing(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    with pytest.raises(VaultLintError) as raised:
        unexpected = vault.write_pages([cited_page()], "run-cas", MemoryLedger())
        assert unexpected.commit is None
    assert any("missing CAS" in reason for reason in raised.value.reasons)
    assert git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_routes_to_proposed_when_human_edited(tmp_path: Path) -> None:
    vault, page, ledger = ready(tmp_path), cited_page(), MemoryLedger()
    original_write = vault.write_pages([page], "run-orig", ledger)
    assert original_write.commit is not None and original_write.pages == 1
    destination = tmp_path / "wiki" / "identity-profile.md"
    ledger.hashes[page.page_id] = hashlib.sha256(destination.read_bytes()).hexdigest()
    original = destination.read_text(encoding="utf-8")
    human_text = original + "\nhuman note\n"
    written = destination.write_text(human_text, encoding="utf-8")
    assert written == len(human_text)
    assert git(
        tmp_path, "-c", "user.name=human", "-c", "user.email=h@local", "add", "-A"
    ) == ""
    human_git = ("-c", "user.name=human", "-c", "user.email=h@local")
    assert "human edit" in git(tmp_path, *human_git, "commit", "-m", "human edit")
    proposed_write = vault.write_pages([page], "run-proposed", ledger)
    assert (proposed_write.pages, proposed_write.conflicts, proposed_write.proposals) == (0, 0, 1)
    assert proposed_write.commit is not None
    assert destination.read_text(encoding="utf-8") == human_text
    proposed = tmp_path / "wiki" / "_proposed" / "identity-profile.md"
    assert proposed.is_file() and proposed.read_text(encoding="utf-8") != destination.read_text(
        encoding="utf-8"
    )
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "identity-profile" in log and "_proposed" in log
    assert git(tmp_path, "log", "-1", "--format=%s").strip() == (
        "sb: run run-proposed (0 pages, 0 conflicts, 1 proposals)"
    )


def test_write_pages_skips_commit_when_content_unchanged(tmp_path: Path) -> None:
    vault, page, ledger = ready(tmp_path), cited_page(), MemoryLedger()
    first = vault.write_pages([page], "run-a", ledger)
    destination = tmp_path / "wiki" / "identity-profile.md"
    ledger.hashes[page.page_id] = hashlib.sha256(destination.read_bytes()).hexdigest()
    count_after_first = int(git(tmp_path, "rev-list", "--count", "HEAD").strip())
    second = vault.write_pages([page], "run-b", ledger)
    assert first.commit is not None and second.commit is None and second.pages == 1
    assert int(git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count_after_first
    assert git(tmp_path, "status", "--porcelain") == ""


def test_init_vault_does_not_commit_when_already_initialized(tmp_path: Path) -> None:
    first = init_vault(tmp_path)
    assert first.root == tmp_path
    count = int(git(tmp_path, "rev-list", "--count", "HEAD").strip())
    stray_count = (tmp_path / "wiki" / "stray.md").write_text("stray\n", encoding="utf-8")
    assert stray_count == len("stray\n")
    second = init_vault(tmp_path)
    assert second.root == tmp_path
    assert int(git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count
    assert "stray.md" not in git(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")


def test_write_pages_does_not_stage_unrelated_dirty_files(tmp_path: Path) -> None:
    vault = ready(tmp_path)
    stray_count = (tmp_path / "wiki" / "stray.md").write_text("stray\n", encoding="utf-8")
    assert stray_count == len("stray\n")
    result = vault.write_pages([cited_page()], "run-scope", MemoryLedger())
    assert result.commit is not None and result.pages == 1
    names = git(tmp_path, "show", "--name-only", "--format=", "HEAD")
    assert "wiki/identity-profile.md" in names
    assert "stray.md" not in names
    assert "stray.md" in _git(tmp_path, "status", "--porcelain")


def test_append_log_writes_line_when_called(tmp_path: Path) -> None:
    vault = init_vault(tmp_path)
    vault.append_log("hello from test")
    assert "hello from test" in (tmp_path / "log.md").read_text(encoding="utf-8")


def test_write_pages_commits_log_line_with_page_when_content_changes(tmp_path: Path) -> None:
    result = _ready(tmp_path).write_pages(
        [_cited_page()], "run-log", MemoryLedger(), log_line="status run-log pages=1"
    )
    assert result.commit is not None
    names = _git(tmp_path, "show", "--name-only", "--format=", "HEAD")
    assert "wiki/identity-profile.md" in names and "log.md" in names
    assert "run-log" in _git(tmp_path, "show", "HEAD:log.md")
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_skips_log_and_commit_when_page_unchanged(tmp_path: Path) -> None:
    vault, page, ledger = _ready(tmp_path), _cited_page(), MemoryLedger()
    first = vault.write_pages([page], "run-a", ledger, log_line="status run-a pages=1")
    dest = tmp_path / "wiki" / "identity-profile.md"
    ledger.hashes[page.page_id] = hashlib.sha256(dest.read_bytes()).hexdigest()
    before = (tmp_path / "log.md").read_bytes()
    count = int(_git(tmp_path, "rev-list", "--count", "HEAD").strip())
    second = vault.write_pages([page], "run-b", ledger, log_line="status run-b pages=1")
    assert first.commit is not None and second.commit is None
    assert (tmp_path / "log.md").read_bytes() == before
    assert "run-b" not in (tmp_path / "log.md").read_text(encoding="utf-8")
    assert int(_git(tmp_path, "rev-list", "--count", "HEAD").strip()) == count
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_write_pages_restores_log_when_lint_or_path_fails(tmp_path: Path) -> None:
    vault = _ready(tmp_path)
    before = (tmp_path / "log.md").read_bytes()
    with pytest.raises(VaultLintError) as linted:
        unexpected = vault.write_pages(
            [_cited_page(body_md=f"Poison.[^{DEAD_SID}]")],
            "run-lint",
            MemoryLedger(),
            log_line="status run-lint",
        )
        assert unexpected.commit is None
    assert any("unresolved" in reason for reason in linted.value.reasons)
    with pytest.raises(PathEscapeError) as path_err:
        unexpected = vault.write_pages(
            [_cited_page(page_id="../outside")],
            "run-path",
            MemoryLedger(),
            log_line="status run-path",
        )
        assert unexpected.commit is None
    assert "outside" in str(path_err.value)
    assert (tmp_path / "log.md").read_bytes() == before
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert _git(tmp_path, "diff", "--cached", "--name-only") == ""


def test_write_pages_restores_page_log_index_when_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _ready(tmp_path)
    before = (tmp_path / "log.md").read_bytes()
    dest = tmp_path / "wiki" / "identity-profile.md"

    def boom(root: Path, message: str, paths: list[Path] | None = None) -> str | None:
        del message
        if paths:
            assert (
                _git(
                    root,
                    "add",
                    "--",
                    *[str(p.resolve().relative_to(root.resolve())) for p in paths],
                )
                == ""
            )
        raise GitCommandError(argv=("commit",), stderr="simulated")

    monkeypatch.setattr("sb.vault._commit_if_changed", boom)
    with pytest.raises(GitCommandError) as raised:
        unexpected = vault.write_pages(
            [_cited_page()], "run-fail", MemoryLedger(), log_line="status run-fail"
        )
        assert unexpected.commit is None
    assert "simulated" in str(raised.value)
    assert (tmp_path / "log.md").read_bytes() == before
    assert not dest.exists()
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert _git(tmp_path, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize('fence', ['```', '~~~~'])
@pytest.mark.parametrize('span_first', [True, False])
def test_render_keeps_code_examples_and_one_source_definition(tmp_path: Path, fence: str, span_first: bool) -> None:
    from sb.vault import read_page_spec

    origin = 'me-wiki:identity/profile.md'
    definition = f'[^{CAS_SID}]: {origin}'
    definitions = [definition + ' span=0-12', definition]
    if not span_first:
        definitions.reverse()
    body = f'A fact.[^{CAS_SID}]\n\n{fence}\n{definition}\n{fence}\n\n' + '\n\n'.join(definitions)
    vault = _ready(tmp_path)
    vault.write_pages([_cited_page(body_md=body)], 'first', MemoryLedger())
    text = (tmp_path / 'wiki/identity-profile.md').read_text()
    assert text.count(definition) == 2  # code example and one real definition
    assert f'{fence}\n{definition}\n{fence}' in text
    assert f'{definition} span=0-12' in text
    page = read_page_spec(tmp_path, 'identity-profile')
    assert page is not None
    assert page.sources[0].spans == ['0-12']
    ledger = MemoryLedger()
    ledger.hashes[page.page_id] = hashlib.sha256(text.encode()).hexdigest()
    outcome = vault.write_pages([page], 'repeat', ledger)
    assert outcome.commit is None
    assert (tmp_path / 'wiki/identity-profile.md').read_text() == text


def test_code_example_does_not_replace_real_source_definition(tmp_path: Path) -> None:
    definition = f'[^{CAS_SID}]: me-wiki:identity/profile.md'
    body = f'A fact.[^{CAS_SID}]\n\n```markdown\n{definition}\n```'
    _ready(tmp_path).write_pages([_cited_page(body_md=body)], 'code', MemoryLedger())
    text = (tmp_path / 'wiki/identity-profile.md').read_text()
    assert text.count(definition) == 2


def test_different_span_annotations_are_not_silently_discarded(tmp_path: Path) -> None:
    definition = f"[^{CAS_SID}]: me-wiki:identity/profile.md"
    body = f"A fact.[^{CAS_SID}]\n\n{definition} span=0-12\n\n{definition} span=20-30"
    _ready(tmp_path).write_pages([_cited_page(body_md=body)], "spans", MemoryLedger())
    text = (tmp_path / "wiki/identity-profile.md").read_text()
    assert f"{definition} span=0-12" in text
    assert f"{definition} span=20-30" in text
    assert text.count(definition) == 2
