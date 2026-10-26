"""Production-shaped backups and owner receipt recovery through shipped surfaces."""
from __future__ import annotations

import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from sb.cli import main
from sb.effect_values import is_json_object, strict_loads
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.ops import create_backup
from sb.owner_effects import OwnerEffect
from sb.request_store import RequestStore
from sb.store.cas import ContentAddressedStore
from tests.test_ops import _seed_vault
from tests.test_web import request, running
from tests.test_web_effect_recovery import payload_for
from tests.test_web_lifecycle import URL, ready


def _commit(root: Path, *args: str) -> None:
    _ = subprocess.run(
        [
            "git", "-C", str(root),
            "-c", "user.name=second-brain-test",
            "-c", "user.email=sb-test@local",
            *args,
        ],
        check=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "second-brain-test",
            "GIT_AUTHOR_EMAIL": "sb-test@local",
            "GIT_COMMITTER_NAME": "second-brain-test",
            "GIT_COMMITTER_EMAIL": "sb-test@local",
        },
    )

def test_backup_v1_with_packed_history_is_inspected(tmp_path: Path) -> None:
    root, _ = _seed_vault(tmp_path)
    needle = b"M13PACKEDHISTORY"
    page = root / "wiki" / "historical.md"
    _ = page.write_bytes(needle)
    _commit(root, "add", "wiki/historical.md")
    _commit(root, "commit", "-qm", "historical")
    page.unlink()
    _commit(root, "add", "-u")
    _commit(root, "commit", "-qm", "removed")
    _ = subprocess.run(["git", "-C", str(root), "gc", "--prune=now"], check=True)
    archive = tmp_path / "production-format.tar.gz"
    _ = create_backup(root, archive)
    with tarfile.open(archive) as bundle:
        assert any(member.name.endswith(".pack") for member in bundle)
    assert inspect_managed_file(archive, (needle,)).matches > 0
    assert inspect_managed_file(archive, (b"absent-sentinel",)).matches == 0


def test_backup_v1_with_raw_office_zip_is_inspected(tmp_path: Path) -> None:
    root, _ = _seed_vault(tmp_path)
    document = tmp_path / "input.docx"
    with zipfile.ZipFile(document, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("word/document.xml", b"M13OFFICEPACK")
    _ = ContentAddressedStore(root).put(document.read_bytes())
    archive = tmp_path / "raw-office.tar.gz"
    _ = create_backup(root, archive)
    assert inspect_managed_file(archive, (b"M13OFFICEPACK",)).matches > 0
    assert inspect_managed_file(archive, (b"absent-sentinel",)).matches == 0


@pytest.mark.parametrize("failure", ["before_apply", "inspection", "after_activation"])
def test_maintenance_replays_interrupted_owner_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    config, root = ready(tmp_path)
    replacement = "M13SPLIT replacement"
    with running(config) as base:
        _, page = request(base + URL)
        payload = payload_for(page, replacement)
        with monkeypatch.context() as context:
            if failure == "before_apply":
                def fail_apply(*_args: object, **_kwargs: object) -> None:
                    raise RuntimeError("injected apply failure")
                context.setattr("sb.erasure.ErasureEngine.apply_owner", fail_apply)
            elif failure == "inspection":
                def fail_inspection(*_args: object, **_kwargs: object) -> None:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
                context.setattr("sb.owner_effects.prepare_copy_disposal", fail_inspection)
            else:
                from sb import owner_effects
                original_save = owner_effects.save
                def fail_save(path: Path, effect: OwnerEffect) -> None:
                    if effect.result is not None:
                        raise RuntimeError("injected lost response")
                    original_save(path, effect)
                context.setattr(owner_effects, "_save", fail_save)
            assert request(base + URL + "/correct", method="POST", payload=payload)[0] == 500
        _, current = request(base + URL)
        assert request(base + URL + "/correct", method="POST",
                        payload=payload_for(current, "different correction")) == (
            409, {"error": "OWNER_EFFECT_RECOVERY_REQUIRED"})
    monkeypatch.setattr("sb.cli.load_config", lambda: config)
    assert main(["maintain", "--once"]) == 0
    store = RequestStore(Path(config.request_root))
    try:
        loaded = strict_loads((root / "generation.json").read_text(), 1_000_000)
        assert is_json_object(loaded)
        assert store.tombstone_high_water() == (
            loaded["tombstone_sequence"], loaded["tombstone_set_root"])
        assert loaded["tombstone_sequence"] == 1
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
    def fail_inspection(*_args: object, **_kwargs: object) -> None:
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    monkeypatch.setattr("sb.owner_effects.prepare_copy_disposal", fail_inspection)
    with running(config) as base:
        _, page = request(base + URL)
        assert request(base + URL + "/correct", method="POST",
                        payload=payload_for(page, "replacement")) == (
            500, {"error": "MANAGED_ARCHIVE_UNSUPPORTED"})
