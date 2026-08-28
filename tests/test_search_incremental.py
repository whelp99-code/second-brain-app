"""Commit-aware incremental search, conflict coverage, and metadata filters."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from sb.contracts import PageSpec, SourceCite
from sb.search import SearchIndex
from sb.store.cas import ContentAddressedStore
from sb.vault import Vault, init_vault

TERM = "공통검색키워드"
NEW_TERM = "증분추가키워드"


class _NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _put(root: Path, payload: bytes) -> str:
    return ContentAddressedStore(root).put(payload)


def _page(root: Path, page_id: str, status: str, term: str) -> PageSpec:
    digest = _put(root, f"source:{page_id}".encode())
    sid = digest[:8]
    return PageSpec(
        page_id,
        page_id,
        f"# section\n{term}.[^{sid}]",
        [SourceCite(sid, f"notes:{page_id}.md", digest)],
        status,
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=second-brain-test",
            "-c",
            "user.email=sb-test@local",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    vault = init_vault(root)
    pages = [
        _page(root, "wiki/일반-지식", "active", TERM),
        _page(root, "daily/2026-08-28", "active", TERM),
        _page(root, "conflicts/open-1", "conflicted", TERM),
    ]
    result = vault.write_pages(pages, "seed-search", _NoPreviousHash())
    assert result.commit is not None
    return root


def _meta(root: Path, key: str) -> str:
    with sqlite3.connect(root / ".sb" / "search.db") as conn:
        row = cast(
            tuple[object] | None,
            conn.execute("SELECT value FROM search_meta WHERE key=?", (key,)).fetchone(),
        )
    assert row is not None
    return str(row[0])


def test_same_head_reuses_index_and_new_commit_updates_without_full_rebuild(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = _seed(tmp_path)
    index = SearchIndex(root)
    first = index.search(TERM)
    first_head = _meta(root, "git_head")
    assert len(first) == 3

    def fail_full_rebuild(conn: sqlite3.Connection, vault_root: Path) -> None:
        del conn, vault_root
        raise AssertionError("same-head or ordinary incremental refresh used a full rebuild")

    monkeypatch.setattr("sb.search._full_rebuild", fail_full_rebuild)
    assert index.search(TERM) == first
    assert _meta(root, "git_head") == first_head

    vault = Vault(root)
    result = vault.write_pages(
        [_page(root, "wiki/새-지식", "active", NEW_TERM)],
        "incremental-add",
        _NoPreviousHash(),
    )
    assert result.commit is not None
    hits = index.search(NEW_TERM)
    assert any(hit.page_id == "wiki/새-지식" for hit in hits)
    assert _meta(root, "git_head") != first_head


def test_incremental_refresh_removes_deleted_committed_page(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    index = SearchIndex(root)
    assert any(hit.page_id == "wiki/일반-지식" for hit in index.search(TERM))

    removed = _git(root, "rm", "--", "wiki/일반-지식.md")
    assert removed.returncode == 0, removed.stderr
    committed = _git(root, "commit", "-m", "test: remove indexed page")
    assert committed.returncode == 0, committed.stderr

    hits = index.search(TERM)
    assert all(hit.page_id != "wiki/일반-지식" for hit in hits)
    assert {hit.page_id.split("/", 1)[0] for hit in hits} == {"daily", "conflicts"}


def test_search_indexes_conflicts_and_applies_kind_status_date_filters(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    index = SearchIndex(root)
    today = datetime.now(UTC).date().isoformat()

    conflict_hits = index.search(
        TERM,
        kinds=("conflicts",),
        status="conflicted",
        updated_from=today,
        updated_to=today,
    )
    assert [hit.page_id for hit in conflict_hits] == ["conflicts/open-1"]

    wiki_hits = index.search(TERM, kinds=("wiki",), status="active")
    assert [hit.page_id for hit in wiki_hits] == ["wiki/일반-지식"]
    assert index.search(TERM, updated_to="2000-01-01") == ()
