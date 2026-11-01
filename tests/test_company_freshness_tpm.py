"""Exercise real adapter argv at the subprocess boundary, never the host TPM."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

import sb.company_freshness_tpm as tpm
from sb.company_freshness_anchor import AnchorRejected
from sb.effect_values import canonical_bytes


@pytest.mark.parametrize("policy", ["cd" * 32, "ef" * 32, "", "xyz"])
def test_adapter_reads_live_public_and_extends_raw_digest_without_secret_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
) -> None:
    # Given: only the OS command boundary is replaced with a TPM-shaped device.
    credential = tmp_path / "owner.auth"
    _ = credential.write_bytes(b"synthetic-owner-auth")
    credential.chmod(0o600)
    monkeypatch.setattr(tpm, "TPM_OWNER_AUTH", credential)
    name = "000b" + "ab" * 32
    identity_bytes = b"isolated-pinned-tpm-identity-public"
    identity = "sha256:" + hashlib.sha256(identity_bytes).hexdigest()
    proof = tmp_path / "provisioning.json"
    _ = proof.write_bytes(
        canonical_bytes(
            {
                "schema_version": 1,
                "identity": identity,
                "public_name_hex": name,
                "measured_at": "2026-10-16T00:00:00.000Z",
                "deletion_policy_digest": "sha256:" + "cd" * 32,
                "owner_auth_outside_restore_set": True,
                "platform_clear_physical_policy": True,
                "operator_evidence_retained_outside_restore_set": True,
            }
        )
    )
    proof.chmod(0o644)
    monkeypatch.setattr(tpm, "TPM_PROVISIONING", proof)
    public = (
        "0x01804F43:\n  name: "
        + name
        + "\n  hash algorithm:\n    friendly: sha256\n"
        + "  attributes:\n    friendly: nt=extend|policydelete|written|ownerread|ownerwrite\n"
        + "  size: 32\n"
        + ("  authorization policy: " + policy + "\n" if policy else "")
    ).encode()
    live = b"\x11" * 32
    commands: list[list[str]] = []
    outputs: list[Path] = []

    def command(
        argv: list[str],
        *,
        input: bytes | None,
        capture_output: bool,
        timeout: int,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal live
        assert capture_output and timeout == 5 and not check
        assert env == {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
        assert argv[-2:] == ["-P", "file:" + str(credential)] or "-P" not in argv
        assert "device:/dev/tpmrm0" in argv
        assert "synthetic-owner-auth" not in " ".join(argv)
        commands.append(argv)
        match argv[0]:
            case "/usr/bin/tpm2_nvreadpublic":
                return subprocess.CompletedProcess(argv, 0, public, b"")
            case "/usr/bin/tpm2_nvread":
                output = Path(argv[argv.index("-o") + 1])
                outputs.append(output)
                _ = output.write_bytes(live)
            case "/usr/bin/tpm2_nvextend":
                assert input is not None and len(input) == 32
                live = hashlib.sha256(live + input).digest()
            case "/usr/bin/tpm2_getcap":
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    b"ownerAuthSet: 1\nlockoutAuthSet: 1\ndisableClear: 1\n",
                    b"",
                )
            case "/usr/bin/tpm2_readpublic":
                assert argv[argv.index("-c") + 1] == "0x81010001"
                output = Path(argv[argv.index("-o") + 1])
                outputs.append(output)
                _ = output.write_bytes(identity_bytes)
            case _:
                raise AssertionError("unexpected executable")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("sb.company_freshness_tpm.subprocess.run", command)
    anchor = tpm.TpmNvExtendAnchor()
    if policy != "cd" * 32:
        with pytest.raises(AnchorRejected, match="COMPANY_FRESHNESS_REQUIRED"):
            anchor.identity()
        assert not any(argv[0].endswith("/tpm2_nvextend") for argv in commands)
        return
    assert anchor.identity() == identity
    assert anchor.public_name() == bytes.fromhex(name)
    assert anchor.read_value() == b"\x11" * 32

    # When: the production adapter extends one raw SHA256 digest.
    result = anchor.extend(b"\x22" * 32)

    # Then: a fresh device read, not echoed input, supplies the result.
    assert result == hashlib.sha256(b"\x11" * 32 + b"\x22" * 32).digest()
    assert sum(argv[0].endswith("/tpm2_nvextend") for argv in commands) == 1
    assert outputs and all(not output.parent.exists() for output in outputs)


def test_adapter_rejects_malformed_digest_before_command() -> None:
    with pytest.raises(AnchorRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = tpm.TpmNvExtendAnchor().extend(b"not-32-bytes")


def test_missing_provisioning_proof_never_probes_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tpm, "TPM_PROVISIONING", tmp_path / "missing-proof.json")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("No TPM command is allowed without retained provisioning proof")

    monkeypatch.setattr("sb.company_freshness_tpm.subprocess.run", forbidden)
    with pytest.raises((AnchorRejected, OSError)):
        _ = tpm.TpmNvExtendAnchor().identity()
