"""Fixed local TPM command adapter; no provisioning or software fallback."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Literal

from pydantic import Field

from sb.company_freshness_anchor import (
    NV_HANDLE,
    AnchorRejected,
    parse_nvreadpublic,
    require_trusted_file,
    tpm_nvextend_argv,
    tpm_nvread_argv,
    tpm_nvreadpublic_argv,
)
from sb.effect_values import parse_instant
from sb.effect_write_models import ClosedModel

TPM_OWNER_AUTH: Final = Path("/run/sb-company-processor/credentials/tpm-owner.auth")
TPM_PROVISIONING: Final = Path("/etc/second-brain-company/tpm-provisioning.json")


class ProvisioningEvidence(ClosedModel):
    schema_version: Literal[1]
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    public_name_hex: str = Field(pattern=r"^000b[0-9a-f]{64}$")
    measured_at: str
    deletion_policy_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    owner_auth_outside_restore_set: Literal[True]
    platform_clear_physical_policy: Literal[True]
    operator_evidence_retained_outside_restore_set: Literal[True]


class TpmNvExtendAnchor:
    """Use a pre-provisioned protected NV index, never define/reset one."""

    def identity(self) -> str:
        require_trusted_file(TPM_PROVISIONING, mode=0o644)
        if str(TPM_PROVISIONING).startswith("/etc/") and TPM_PROVISIONING.stat().st_uid != 0:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        proof = ProvisioningEvidence.model_validate_json(TPM_PROVISIONING.read_bytes(), strict=True)
        _ = parse_instant(proof.measured_at)
        properties = _command(["tpm2_getcap", "properties-variable"]).decode("ascii")
        flags = {
            key.strip(): value.strip()
            for line in properties.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        if any(flags.get(key) != "1" for key in ("ownerAuthSet", "lockoutAuthSet", "disableClear")):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        with TemporaryDirectory(prefix="sb-company-identity-") as folder:
            output = Path(folder) / "identity.public"
            _ = _command(["tpm2_readpublic", "-c", "0x81010001", "-f", "tss", "-o", str(output)])
            if output.is_symlink() or not 1 <= output.stat().st_size <= 16_384:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            identity = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
        try:
            metadata = parse_nvreadpublic(_command(tpm_nvreadpublic_argv()).decode("ascii"))
        except (UnicodeError, ValueError) as exc:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED") from exc
        if (
            identity != proof.identity
            or metadata["name"] != proof.public_name_hex
            or metadata["authorization_policy"]
            != proof.deletion_policy_digest.removeprefix("sha256:")
        ):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        return identity

    def public_name(self) -> bytes:
        try:
            metadata = parse_nvreadpublic(_command(tpm_nvreadpublic_argv()).decode("ascii"))
            name = bytes.fromhex(metadata["name"])
        except (UnicodeError, ValueError) as exc:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED") from exc
        if len(name) != 34 or name[:2] != b"\x00\x0b":
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        return name

    def read_value(self) -> bytes:
        with TemporaryDirectory(prefix="sb-company-nv-") as folder:
            output = Path(folder) / "nv.bin"
            _ = _command(tpm_nvread_argv(NV_HANDLE, output), authenticated=True)
            try:
                if output.stat().st_size != 32:
                    raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                return output.read_bytes()
            except OSError as exc:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED") from exc

    def extend(self, record_digest_raw: bytes) -> bytes:
        if len(record_digest_raw) != 32:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        _ = _command(
            tpm_nvextend_argv(NV_HANDLE),
            record_digest_raw,
            authenticated=True,
        )
        return self.read_value()


def _command(
    arguments: list[str],
    payload: bytes | None = None,
    *,
    authenticated: bool = False,
) -> bytes:
    allowed = {
        "tpm2_nvreadpublic",
        "tpm2_nvread",
        "tpm2_nvextend",
        "tpm2_readpublic",
        "tpm2_getcap",
    }
    if not arguments or arguments[0] not in allowed:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    argv = ["/usr/bin/" + arguments[0], *arguments[1:], "-T", "device:/dev/tpmrm0"]
    if authenticated:
        require_trusted_file(TPM_OWNER_AUTH, mode=0o600)
        if not 0 < TPM_OWNER_AUTH.stat().st_size <= 1024:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        argv.extend(("-P", "file:" + str(TPM_OWNER_AUTH)))
    try:
        result = subprocess.run(
            argv,
            input=payload,
            capture_output=True,
            timeout=5,
            check=False,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED") from exc
    if result.returncode != 0 or len(result.stdout) > 1_048_576:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    return result.stdout
