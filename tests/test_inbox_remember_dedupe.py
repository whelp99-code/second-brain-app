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
