"""Runtime identity characterization and regression coverage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sb.config import Config
from sb.readiness import readiness


def test_ready_shape_when_identity_is_not_yet_separated(tmp_path: Path) -> None:
    # Given an isolated, uninitialized vault; When readiness is inspected;
    # Then the legacy payload has only provider release, not artifact identities.
    report = readiness(Config(raw={"vault_root": str(tmp_path / "vault"),
                                   "backup_root": str(tmp_path / "backup")}))
    assert report["status"] == "degraded"
    assert "provider_release" in report
    assert "source_commit" not in report
    assert "wheel_sha" not in report
    assert "process_entrypoint" not in report


def test_profile_digest_mismatch_when_manifest_disagrees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a manifest with a forged profile digest and a secret in config;
    # When identity is checked; Then the specific mismatch is reported without leakage.
    manifest = tmp_path / "release-manifest.json"
    _ = manifest.write_text(json.dumps({"source_commit": "a" * 40,
        "wheel_sha256": "b" * 64, "contract_profile": "task32-schema4",
        "contract_profile_digest": "c" * 64}))
    monkeypatch.setenv("SB_RELEASE_MANIFEST", str(manifest))
    from sb.runtime_identity import runtime_identity

    result = runtime_identity(Config(raw={"provider_instance_id": "fixture",
        "api_key": "super-secret-value"}))
    assert result["status"] == "degraded"
    assert "CONTRACT_PROFILE_DIGEST_MISMATCH" in result["reasons"]
    assert "super-secret-value" not in json.dumps(result)


@pytest.mark.parametrize("payload", ["{", '{"source_commit": "a"}'])
def test_invalid_manifest_when_malformed_or_missing_fields(tmp_path: Path, payload: str) -> None:
    # Given malformed release metadata; When parsed; Then it fails with a stable code.
    from sb.runtime_identity import runtime_identity

    manifest = tmp_path / "release-manifest.json"
    _ = manifest.write_text(payload)
    result = runtime_identity(Config(raw={}), manifest_path=manifest)
    assert result["status"] == "degraded"
    assert result["reasons"] == ["RELEASE_MANIFEST_INVALID"]


def test_stale_wheel_when_manifest_digest_disagrees(tmp_path: Path) -> None:
    # Given a wheel with stale manifest digest; When inspected; Then no ok leaks out.
    from sb.runtime_identity import runtime_identity

    manifest = tmp_path / "release-manifest.json"
    _ = manifest.write_text(json.dumps({"source_commit": "a" * 40,
        "wheel_sha256": "b" * 64, "contract_profile": "task32-schema4"}))
    _ = (tmp_path / "second_brain-1.0.7-py3-none-any.whl").write_bytes(b"wheel")
    result = runtime_identity(Config(raw={}), manifest_path=manifest)
    assert result["status"] == "degraded"
    assert "WHEEL_SHA_MISMATCH" in result["reasons"]
