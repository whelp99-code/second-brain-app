"""Regenerate the small document fixtures; oversize bytes stay generated on demand."""

from __future__ import annotations

import runpy
import sys
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent


def oversize_bytes(limit: int) -> bytes:
    return b"x" * (limit + 1)


def main() -> None:
    cases = runpy.run_path(str(ROOT / "test_parsers.py"))
    for suffix, factory in cases["SUPPORTED"]:
        (FIXTURES / ("sample" + suffix)).write_bytes(factory())
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", b"<s>" + b"x" * 1_000_000 + b"</s>")
    (FIXTURES / "zip-bomb.hwpx").write_bytes(payload.getvalue())
    (FIXTURES / "truncated.pdf").write_bytes(cases["_payload_pdf"]()[:32])
    if len(sys.argv) > 1 and sys.argv[1] == "--oversize":
        (FIXTURES / "oversize.bin").write_bytes(oversize_bytes(10 * 1024 * 1024))


if __name__ == "__main__":
    main()
