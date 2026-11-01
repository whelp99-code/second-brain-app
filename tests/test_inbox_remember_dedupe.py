from threading import Barrier, Thread
from pathlib import Path

from sb.inbox import write_inbox


def test_same_title_and_body_returns_the_existing_card(tmp_path: Path) -> None:
    first = write_inbox(tmp_path, "같은 본문", "같은 제목")
    second = write_inbox(tmp_path, "같은 본문", "같은 제목")
    cards = list((tmp_path / "inbox").glob("*.md"))
    assert second == first
    assert len(cards) == 1


def test_different_body_creates_a_second_card(tmp_path: Path) -> None:
    first = write_inbox(tmp_path, "같은 본문", "같은 제목")
    second = write_inbox(tmp_path, "다른 본문", "같은 제목")
    cards = list((tmp_path / "inbox").glob("*.md"))
    assert second != first
    assert len(cards) == 2

def test_concurrent_same_remember_creates_one_card(tmp_path: Path) -> None:
    barrier = Barrier(2)
    found: list[Path] = []

    def once() -> None:
        barrier.wait()
        found.append(write_inbox(tmp_path, "같은 본문", "같은 제목"))

    threads = [Thread(target=once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    cards = list((tmp_path / "inbox").glob("*.md"))
    assert found[0] == found[1]
    assert len(cards) == 1
def test_after_scan_same_body_returns_the_ingested_card(tmp_path: Path) -> None:
    from sb.config import Config
    from sb.pipeline import run_compile, run_ingest
    from sb.vault import init_vault

    root = init_vault(tmp_path / "vault").root
    config = Config(raw={
        "vault_root": str(root),
        "sources": [{"id": "inbox", "adapter": "inbox-documents", "llm_policy": "deny"}],
        "llm": {"prompt_version": "v1", "model_id": "fake"},
    })
    first = write_inbox(root, "같은 원문", "같은 제목")
    assert run_ingest(config, ("inbox",)).exit_code == 0
    assert not (root / first).is_file()
    second = write_inbox(root, "같은 원문", "같은 제목")
    assert second == Path("inbox") / ".done" / first.name
    assert list((root / "inbox").glob("*.md")) == []
    assert run_compile(config, llm_mode="fake").exit_code == 0
    third = write_inbox(root, "같은 원문", "같은 제목")
    assert third.parts[0] == "wiki"
    assert (root / third).is_file()
    assert list((root / "inbox").glob("*.md")) == []


def test_after_scan_different_body_creates_a_new_card(tmp_path: Path) -> None:
    from sb.config import Config
    from sb.pipeline import run_ingest
    from sb.vault import init_vault

    root = init_vault(tmp_path / "vault").root
    config = Config(raw={
        "vault_root": str(root),
        "sources": [{"id": "inbox", "adapter": "inbox-documents", "llm_policy": "deny"}],
    })
    _ = write_inbox(root, "같은 원문", "같은 제목")
    assert run_ingest(config, ("inbox",)).exit_code == 0
    second = write_inbox(root, "다른 원문", "같은 제목")
    assert second.parts[0] == "inbox"
    assert (root / second).is_file()
    titled = write_inbox(root, "같은 원문", "다른 제목")
    assert titled != second
    assert (root / titled).is_file()
