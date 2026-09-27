"""A page deletion erases all original spans, not shifted successor offsets."""
from pathlib import Path

from sb.erasure import ErasureEngine, ReingressGate
from tests.test_erasure import NOW, erasure_request


def test_multiple_records_on_one_page_are_erased_from_original_bytes(tmp_path: Path) -> None:
    page = tmp_path / "wiki/example-alpha.md"
    page.parent.mkdir()
    _ = page.write_text("first old record\nsecond old record\n")
    first = erasure_request(tmp_path, "first old record")
    second = erasure_request(tmp_path, "second old record")
    request = first.model_copy(update={"targets": [first.targets[0], second.targets[0]]})
    gate = ReingressGate(tmp_path / "state/reingress.db")
    try:
        _ = ErasureEngine(gate).apply(tmp_path, request, NOW)
        assert page.read_text() == "Corrected fixture value.\n\n"
    finally:
        gate.close()
