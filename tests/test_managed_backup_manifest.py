import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from sb.managed_backup_manifest import validate_managed_backups
from sb.managed_file_inspection import ManagedInspectionError
from sb.ops import create_backup, restore_backup
from tests.test_managed_copy_disposal import apply, prepare_copies
from tests.test_ops import _seed_vault


def test_unrelated_canonical_backup_survives_correction_and_restores(tmp_path: Path):
    executor, identity, old_archive, _export = prepare_copies(tmp_path / "provider", "correct")
    vault, _ = _seed_vault(tmp_path / "independent")
    retained = executor.config.backup_root / "retained.tar.gz"
    created = create_backup(vault, retained)
    try:
        result = apply(executor, "correct", identity)
        assert result["state"] == "proved", result
        assert not old_archive.exists() and retained.exists()
        restored = restore_backup(retained, tmp_path / "restored")
        assert restored.files == created.files
    finally:
        executor.close()


def make_archive(root, alteration):
    payload = b"unrelated memory"
    entry = {
        "path": "wiki/page.md",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "mode": 0o600,
    }
    manifest = {
        "format": "second-brain-backup-v1",
        "origin": "provider:fixture",
        "created_at": "2026-09-08T00:00:00+00:00",
        "app_version": "0.1",
        "schema_version": 1,
        "git_head": "",
        "files": [entry],
    }
    members = [("vault/wiki/page.md", payload)]
    if alteration == "unicode_origin":
        manifest["origin"] = "vault:/remember/e\u0301"
    if alteration == "hash":
        entry["sha256"] = "0" * 64
    elif alteration == "size":
        assert isinstance(entry["size"], int)
        entry["size"] += 1
    elif alteration == "mode":
        entry["mode"] = 0o400
    elif alteration == "missing":
        members = []
    elif alteration == "extra":
        members.append(("vault/extra", b"not in manifest"))
    elif alteration == "duplicate_member":
        members *= 2
    elif alteration == "duplicate_entry":
        manifest["files"] = [entry, entry]
    elif alteration == "unsafe_path":
        entry["path"] = "../page.md"
    elif alteration == "dot_path":
        entry["path"] = "."
    archive = root / "copy.tar.gz"
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if alteration == "spaced_json":
        encoded = json.dumps(manifest, indent=2).encode()
    if alteration == "duplicate_json_key":
        encoded = encoded.replace(b'"origin":', b'"origin":"first","origin":')
    with tarfile.open(archive, "w:gz") as bundle:
        for name, data in [("manifest.json", encoded), *members]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            bundle.addfile(info, io.BytesIO(data))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    if alteration == "checksum":
        checksum = "0" * 64
    archive.with_name(archive.name + ".sha256").write_text(f"{checksum}  {archive.name}\n")
    return archive


@pytest.mark.parametrize(
    "alteration",
    [
        "hash",
        "size",
        "mode",
        "missing",
        "extra",
        "duplicate_member",
        "duplicate_entry",
        "unsafe_path",
        "dot_path",
        "checksum",
    ],
)
def test_forged_or_incomplete_manifest_is_rejected_without_mutation(tmp_path: Path, alteration):
    archive = make_archive(tmp_path, alteration)
    before = archive.read_bytes()
    code = ("BACKUP_CHECKSUM_MISMATCH" if alteration == "checksum" else
        "BACKUP_MANIFEST_INVALID" if alteration in {"duplicate_entry", "unsafe_path", "dot_path"} else
        "BACKUP_MANIFEST_MISMATCH")
    with pytest.raises(ManagedInspectionError, match=code):
        validate_managed_backups(tmp_path)
    assert archive.read_bytes() == before


@pytest.mark.parametrize("variant", ["valid", "unicode_origin", "spaced_json"])
def test_canonical_manifest_and_optional_receipt_are_read_only(tmp_path: Path, variant):
    archive = make_archive(tmp_path, variant)
    receipt = archive.with_name(archive.name + ".verified.json")
    receipt.write_text('{"historic_receipt":true}')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    validate_managed_backups(tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_duplicate_json_key_is_rejected(tmp_path: Path):
    make_archive(tmp_path, "duplicate_json_key")
    with pytest.raises(ManagedInspectionError, match="BACKUP_MANIFEST_INVALID"):
        validate_managed_backups(tmp_path)


def test_orphan_sidecar_cannot_represent_a_backup(tmp_path: Path):
    (tmp_path / "missing.tar.gz.sha256").write_text("orphan")
    with pytest.raises(ManagedInspectionError, match="UNMANIFESTED_BACKUP"):
        validate_managed_backups(tmp_path)


def test_bad_retained_manifest_prevents_pointer_switch(tmp_path: Path):
    executor, identity, _old, _export = prepare_copies(tmp_path / "provider", "correct")
    base = executor.generations.active()
    archive = make_archive(executor.config.backup_root, "hash")
    try:
        result = apply(executor, "correct", identity)
        assert result == {"state": "failed", "code": "BACKUP_MANIFEST_MISMATCH"}
        assert executor.generations.active().generation_id == base.generation_id
        assert archive.exists()
        assert executor.store.db.execute("SELECT count(*) FROM managed_copy_disposals").fetchone()[0] == 0
    finally:
        executor.close()


@pytest.mark.parametrize("kind", ["missing", "invalid"])
def test_legacy_manifest_errors_do_not_expose_paths(tmp_path: Path, kind):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    if kind == "invalid":
        (legacy / "manifest.json").write_text("invalid JSON")
    with pytest.raises(ManagedInspectionError) as failure:
        validate_managed_backups(tmp_path)
    assert str(failure.value) == "UNMANIFESTED_BACKUP"


def test_legacy_manifest_directory_remains_supported(tmp_path: Path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "manifest.json").write_text('{"schema_version":1}')
    validate_managed_backups(tmp_path)


def test_enumeration_errors_do_not_expose_paths(tmp_path: Path, monkeypatch):
    def denied(_path):
        raise PermissionError(str(tmp_path))
    with monkeypatch.context() as context:
        context.setattr(Path, "iterdir", denied)
        with pytest.raises(ManagedInspectionError) as failure:
            validate_managed_backups(tmp_path)
    assert str(failure.value) == "UNMANIFESTED_BACKUP"
