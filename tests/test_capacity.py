"""Medium-scale committed Vault, search, retention, backup, and restore regression."""

from __future__ import annotations

from pathlib import Path

from sb.contracts import PageSpec, SourceCite
from sb.governance import retention_report
from sb.ops import create_backup, restore_backup
from sb.search import SearchIndex
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

PAGE_COUNT = 1000
TERM = "용량검증공통키워드"


class _NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def test_one_thousand_committed_pages_search_backup_and_restore(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    vault = init_vault(root)
    digest = ContentAddressedStore(root).put(b"shared capacity source")
    sid = digest[:8]
    pages = [
        PageSpec(
            page_id=f"wiki/scale-{index:04d}",
            title=f"Scale {index:04d}",
            body_md=f"# 항목 {index:04d}\n{TERM} 번호 {index:04d}.[^{sid}]",
            sources=[SourceCite(sid, "capacity:shared.md", digest)],
            status="active",
        )
        for index in range(PAGE_COUNT)
    ]

    written = vault.write_pages(pages, "capacity-1000", _NoPreviousHash())

    assert written.commit is not None
    assert written.pages == PAGE_COUNT
    hits = SearchIndex(root).search(TERM, 25, kinds=("wiki",), status="active")
    assert len(hits) == 25
    assert all(hit.page_id.startswith("wiki/scale-") for hit in hits)
    report = retention_report(root)
    assert report.raw_blobs == 1
    assert report.protected_blobs == 1
    assert report.orphan_blobs == ()

    archive = tmp_path / "capacity-backup.tar.gz"
    backup = create_backup(root, archive)
    assert backup.files >= PAGE_COUNT
    restored = tmp_path / "restored"
    result = restore_backup(archive, restored)
    assert result.files == backup.files
    restored_hits = SearchIndex(restored).search(TERM, 25, kinds=("wiki",), status="active")
    assert [hit.page_id for hit in restored_hits] == [hit.page_id for hit in hits]
