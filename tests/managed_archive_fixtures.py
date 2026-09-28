"""Synthetic archive representations shared by regression and manual QA."""

from __future__ import annotations

import io
import struct
import subprocess
import zipfile
from pathlib import Path
from typing import Final

from sb.ops import create_backup

SENTINEL: Final = b"task30-nested-archive-sentinel-6ce1a52f" * 8
OTHER: Final = b"unrelated-synthetic-document-c371f914" * 8


def document(payload: bytes, *, bad_offset: bool = False) -> bytes:
    """Build a deterministic OOXML-shaped ZIP; optionally damage only the EOCD offset."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, body in (("[Content_Types].xml", b"<Types/>"),
                           ("word/document.xml", b"<document>" + payload + b"</document>")):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, body)
    result = bytearray(output.getvalue())
    if bad_offset:
        end = len(result) - 22
        original = int.from_bytes(result[end + 16:end + 20], "little")
        struct.pack_into("<I", result, end + 16, original + 7)
    return bytes(result)


def zipped(name: str, payload: bytes, *, extra: bytes = b"") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.extra = extra
        bundle.writestr(info, payload)
    return output.getvalue()


def packed_repository(root: Path, payload: bytes) -> Path:
    """Create an actual Git pack/index pair, with no loose copy of the payload."""
    repository = root / ".git"
    _ = subprocess.run(["git", "init", "-q", "--bare", str(repository)],
                       check=True, capture_output=True)
    written = subprocess.run(["git", f"--git-dir={repository}", "hash-object", "-w", "--stdin"],
                             input=payload, check=True, capture_output=True)
    _ = subprocess.run(["git", f"--git-dir={repository}", "update-ref", "refs/tags/retained",
                        written.stdout.decode().strip()], check=True, capture_output=True)
    _ = subprocess.run(["git", "-c", "pack.writeReverseIndex=false", f"--git-dir={repository}",
                        "repack", "-ad", "--no-write-bitmap-index"],
                       check=True, capture_output=True)
    _ = subprocess.run(["git", f"--git-dir={repository}", "prune-packed"],
                       check=True, capture_output=True)
    return repository


def archived(root: Path, payload: bytes, *, packed: bool = False) -> Path:
    vault = root / "source"
    vault.mkdir(parents=True)
    if packed:
        _ = packed_repository(vault, payload)
    else:
        raw = vault / "raw"
        raw.mkdir()
        _ = (raw / "document.docx").write_bytes(payload)
    archive = root / "backups" / "synthetic.tar.gz"
    _ = create_backup(vault, archive, origin="task30-synthetic")
    return archive
