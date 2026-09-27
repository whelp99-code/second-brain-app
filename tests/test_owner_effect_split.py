"""Production-shaped backups and owner receipt recovery through shipped surfaces."""
from __future__ import annotations

import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from sb.cli import main
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.ops import create_backup
from sb.request_store import RequestStore
from sb.store.cas import ContentAddressedStore
from tests.test_ops import _seed_vault
from tests.test_web import _request, _running
from tests.test_web_effect_recovery import payload_for
from tests.test_web_lifecycle import URL, ready


def test_backup_v1_with_packed_history_is_inspected(tmp_path: Path) -> None:
    root, _ = _seed_vault(tmp_path)
    needle = b"M13PACKEDHISTORY"
    page = root / "wiki" / "historical.md"
    page.write_bytes(needle)
    for args in (("add", "wiki/historical.md"), ("commit", "-qm", "historical")):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    page.unlink()
    for args in (("add", "-u"), ("commit", "-qm", "removed"), ("gc", "--prune=now")):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    archive = tmp_path / "production-format.tar.gz"
    create_backup(root, archive)
    with tarfile.open(archive) as bundle:
        assert any(member.name.endswith(".pack") for member in bundle)
    assert inspect_managed_file(archive, (needle,)).matches > 0
    assert inspect_managed_file(archive, (b"absent-sentinel",)).matches == 0


def test_backup_v1_with_raw_office_zip_is_inspected(tmp_path: Path) -> None:
    root, _ = _seed_vault(tmp_path)
    document = tmp_path / "input.docx"
    with zipfile.ZipFile(document, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("word/document.xml", b"M13OFFICEPACK")
    ContentAddressedStore(root).put(document.read_bytes())
    archive = tmp_path / "raw-office.tar.gz"
    create_backup(root, archive)
    assert inspect_managed_file(archive, (b"M13OFFICEPACK",)).matches > 0
    assert inspect_managed_file(archive, (b"absent-sentinel",)).matches == 0


@pytest.mark.parametrize("failure", ["before_apply", "inspection", "after_activation"])
def test_maintenance_replays_interrupted_owner_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    config, root = ready(tmp_path)
    replacement = "M13SPLIT replacement"
    with _running(config) as base:
        _, page = _request(base + URL)
        payload = payload_for(page, replacement)
        with monkeypatch.context() as context:
            if failure == "before_apply":
                def fail(*_args, **_kwargs):
                    raise RuntimeError("injected apply failure")
                context.setattr("sb.erasure.ErasureEngine.apply_owner", fail)
            elif failure == "inspection":
                def fail(*_args, **_kwargs):
                    raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
                context.setattr("sb.owner_effects.prepare_copy_disposal", fail)
            else:
                from sb import owner_effects
                save = owner_effects._save
                def fail(path, effect):
                    if effect.result is not None:
                        raise RuntimeError("injected lost response")
                    save(path, effect)
                context.setattr(owner_effects, "_save", fail)
            assert _request(base + URL + "/correct", method="POST", payload=payload)[0] == 500
        _, current = _request(base + URL)
        assert _request(base + URL + "/correct", method="POST",
                        payload=payload_for(current, "different correction")) == (
            409, {"error": "OWNER_EFFECT_RECOVERY_REQUIRED"})
    monkeypatch.setattr("sb.cli.load_config", lambda: config)
    assert main(["maintain", "--once"]) == 0
    store = RequestStore(Path(config.request_root))
    try:
        manifest = json.loads((root / "generation.json").read_text())
        assert store.tombstone_high_water() == (
            manifest["tombstone_sequence"], manifest["tombstone_set_root"])
        assert manifest["tombstone_sequence"] == 1
    finally:
        store.close()
    effects = [json.loads(path.read_text()) for path in
               (Path(config.state_root) / "owner-effects").glob("*.json")]
    assert len(effects) == 1 and effects[0]["result"] is not None
    assert effects[0]["replacement"] is None
    assert main(["maintain", "--once"]) == 0


def test_web_managed_inspection_failure_exposes_stable_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = ready(tmp_path)
    def fail(*_args, **_kwargs):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    monkeypatch.setattr("sb.owner_effects.prepare_copy_disposal", fail)
    with _running(config) as base:
        _, page = _request(base + URL)
        assert _request(base + URL + "/correct", method="POST",
                        payload=payload_for(page, "replacement")) == (
            500, {"error": "MANAGED_ARCHIVE_UNSUPPORTED"})
