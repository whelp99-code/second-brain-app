"""Missing compiled markers must not divert compiled pages to _proposed."""
from __future__ import annotations

from pathlib import Path

from sb.config import Config
from sb.pipeline import StageReport, _Compiled, run_compile
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import Vault, _commit_if_changed
from tests.vault_test_support import CAS_SID, CitedPageFixture, MemoryLedger, cited_page, ready

PAGE = "daily/2026-09-10"
STAMP = ("sb/1.0.0|v1|test", "2026-09-10")


def _page(body: str):
    return cited_page(CitedPageFixture(page_id=PAGE, body_md=f"{body}[^{CAS_SID}]"))


def test_correction_writes_page_when_compiled_marker_is_missing(tmp_path: Path) -> None:
    root = ready(tmp_path)
    dest = tmp_path / "daily" / "2026-09-10.md"
    proposed = tmp_path / "wiki" / "_proposed" / "daily-2026-09-10.md"
    first = root.write_pages([_page("first")], "run-1", MemoryLedger())
    assert first.pages == 1
    assert first.proposals == 0
    assert dest.is_file()
    second = root.write_pages([_page("corrected")], "run-2", MemoryLedger())
    assert second.proposals == 0
    assert second.pages == 1
    assert not proposed.exists()
    assert "corrected" in dest.read_text(encoding="utf-8")


def test_human_page_without_frontmatter_still_goes_to_proposed(tmp_path: Path) -> None:
    root = ready(tmp_path)
    dest = tmp_path / "daily" / "2026-09-10.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("hand-edited note\n", encoding="utf-8")
    result = root.write_pages([_page("compiled")], "run-1", MemoryLedger())
    assert result.proposals == 1
    assert result.pages == 0
    assert dest.read_text(encoding="utf-8") == "hand-edited note\n"
    assert (tmp_path / "wiki" / "_proposed" / "daily-2026-09-10.md").is_file()


def test_human_edit_of_compiled_page_without_marker_goes_to_proposed(tmp_path: Path) -> None:
    root = ready(tmp_path)
    dest = tmp_path / "daily" / "2026-09-10.md"
    first = root.write_pages([_page("first")], "run-1", MemoryLedger())
    assert first.pages == 1
    original = dest.read_text(encoding="utf-8")
    dest.write_text(original.replace("first", "first USER_EDIT", 1), encoding="utf-8")
    result = root.write_pages([_page("corrected")], "run-2", MemoryLedger())
    assert result.proposals == 1
    assert result.pages == 0
    assert "USER_EDIT" in dest.read_text(encoding="utf-8")
    assert "corrected" not in dest.read_text(encoding="utf-8")


def test_managed_compile_corrects_unmodified_compiled_page(tmp_path: Path) -> None:
    active = tmp_path / "share" / "vault"
    vault = ready(active)
    config = Config(raw={
        "vault_root": str(active),
        "share_root": str(tmp_path / "share"),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "provider_instance_id": "provider:review",
        "provider_release_sha": "a" * 40,
    })
    first = vault.write_pages([_page("Original")], "seed", MemoryLedger())
    assert first.pages == 1
    dest = active / f"{PAGE}.md"

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger
        compiled = _Compiled(vault.root, ContentAddressedStore(vault.root))
        written = vault.write_pages([_page("Corrected")], run_id, compiled)
        return StageReport((), written.pages, written.conflicts, 0, False)

    outcome = run_compile(config, compiler=stage)
    assert outcome.exit_code == 0
    assert "Corrected" in dest.read_text(encoding="utf-8")
    assert not tuple((dest.parent.parent / "wiki" / "_proposed").glob("*.md"))


def test_managed_compile_keeps_committed_human_edit(tmp_path: Path) -> None:
    active = tmp_path / "share" / "vault"
    vault = ready(active)
    config = Config(raw={
        "vault_root": str(active),
        "share_root": str(tmp_path / "share"),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "provider_instance_id": "provider:review",
        "provider_release_sha": "a" * 40,
    })
    first = vault.write_pages([_page("Original")], "seed", MemoryLedger())
    assert first.pages == 1
    dest = active / f"{PAGE}.md"
    dest.write_text(dest.read_text(encoding="utf-8") + "\nUSER_EDIT_COMMITTED\n", encoding="utf-8")
    assert _commit_if_changed(active, "human-edit", [dest]) is not None

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger
        compiled = _Compiled(vault.root, ContentAddressedStore(vault.root))
        written = vault.write_pages([_page("Corrected")], run_id, compiled)
        return StageReport((), written.pages, written.conflicts, 0, False)

    outcome = run_compile(config, compiler=stage)
    assert outcome.exit_code == 0
    assert "USER_EDIT_COMMITTED" in dest.read_text(encoding="utf-8")
    assert "Corrected" not in dest.read_text(encoding="utf-8")


def test_managed_compile_keeps_committed_human_only_page(tmp_path: Path) -> None:
    active = tmp_path / "share" / "vault"
    vault = ready(active)
    config = Config(raw={
        "vault_root": str(active),
        "share_root": str(tmp_path / "share"),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "provider_instance_id": "provider:review",
        "provider_release_sha": "a" * 40,
    })
    first = vault.write_pages([_page("Original")], "seed", MemoryLedger())
    assert first.pages == 1
    dest = active / f"{PAGE}.md"
    dest.write_text("# notes\nhuman-only page\n", encoding="utf-8")
    assert _commit_if_changed(active, "human-page", [dest]) is not None

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger
        compiled = _Compiled(vault.root, ContentAddressedStore(vault.root))
        written = vault.write_pages([_page("Corrected")], run_id, compiled)
        return StageReport((), written.pages, written.conflicts, 0, False)

    outcome = run_compile(config, compiler=stage)
    assert outcome.exit_code == 0
    assert "human-only page" in dest.read_text(encoding="utf-8")
    assert "Corrected" not in dest.read_text(encoding="utf-8")


def test_managed_compile_keeps_uncommitted_human_edit(tmp_path: Path) -> None:
    active = tmp_path / "share" / "vault"
    vault = ready(active)
    config = Config(raw={
        "vault_root": str(active),
        "share_root": str(tmp_path / "share"),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "provider_instance_id": "provider:review",
        "provider_release_sha": "a" * 40,
    })
    first = vault.write_pages([_page("Original")], "seed", MemoryLedger())
    assert first.pages == 1
    dest = active / f"{PAGE}.md"
    dest.write_text(dest.read_text(encoding="utf-8") + "\nUSER_EDIT_KEEP_THIS\n", encoding="utf-8")

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger
        compiled = _Compiled(vault.root, ContentAddressedStore(vault.root))
        written = vault.write_pages([_page("Corrected")], run_id, compiled)
        return StageReport((), written.pages, written.conflicts, 0, False)

    outcome = run_compile(config, compiler=stage)
    assert outcome.exit_code == 0
    assert "USER_EDIT_KEEP_THIS" in dest.read_text(encoding="utf-8")
    assert "Corrected" not in dest.read_text(encoding="utf-8")


def test_marked_human_edit_still_goes_to_proposed(tmp_path: Path) -> None:
    root = ready(tmp_path)
    dest = tmp_path / "daily" / "2026-09-10.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("hand-edited compiled page\n", encoding="utf-8")
    result = root.write_pages(
        [_page("second")],
        "run-1",
        MemoryLedger({PAGE: "deadbeef"}),
    )
    assert result.proposals == 1
    assert dest.read_text(encoding="utf-8") == "hand-edited compiled page\n"
