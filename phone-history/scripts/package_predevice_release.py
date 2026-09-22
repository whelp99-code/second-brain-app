#!/usr/bin/env python3
"""Create and verify a deterministic Phone History pre-device source archive."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MANIFEST = ROOT / "evidence" / "release-manifest.json"
SELECTED_EVIDENCE = (
    "evidence/PREDEVICE_PASS",
    "evidence/predevice-gate-result.json",
    "evidence/predevice-static-report.json",
    "evidence/pytest-junit.xml",
    "evidence/release-manifest.json",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tar_info(name: str, data: bytes, executable: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mode = 0o755 if executable else 0o644
    return info


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = manifest["version"]
    prefix = f"phone-history-{version}"
    entries: list[tuple[str, bytes, bool]] = []
    for item in manifest["files"]:
        relative = item["path"]
        path = ROOT / relative
        data = path.read_bytes()
        if digest(data) != item["sha256"]:
            raise SystemExit(f"manifest mismatch before packaging: {relative}")
        entries.append((relative, data, path.stat().st_mode & 0o111 != 0))
    for relative in SELECTED_EVIDENCE:
        path = ROOT / relative
        if path.is_file() and all(existing[0] != relative for existing in entries):
            entries.append((relative, path.read_bytes(), False))
    entries.sort(key=lambda entry: entry[0])

    sums = "".join(f"{digest(data)}  {relative}\n" for relative, data, _ in entries).encode()
    entries.append(("SHA256SUMS", sums, False))

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for relative, data, executable in entries:
            name = f"{prefix}/{relative}"
            archive.addfile(tar_info(name, data, executable), io.BytesIO(data))

    DIST.mkdir(parents=True, exist_ok=True)
    archive_path = DIST / f"{prefix}.tar.gz"
    with archive_path.open("wb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            compressed.write(tar_buffer.getvalue())
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{archive_hash}  {archive_path.name}\n", encoding="utf-8")

    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        sums_member = members[f"{prefix}/SHA256SUMS"]
        sums_text = archive.extractfile(sums_member).read().decode("utf-8")  # type: ignore[union-attr]
        for line in sums_text.splitlines():
            expected, relative = line.split("  ", 1)
            member = members[f"{prefix}/{relative}"]
            payload = archive.extractfile(member).read()  # type: ignore[union-attr]
            if digest(payload) != expected:
                raise SystemExit(f"internal archive checksum mismatch: {relative}")

    result = {
        "result": "PASS",
        "archive": str(archive_path),
        "checksum": str(checksum_path),
        "sha256": archive_hash,
        "source_tree_sha256": manifest["source_tree_sha256"],
        "entry_count": len(entries),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
