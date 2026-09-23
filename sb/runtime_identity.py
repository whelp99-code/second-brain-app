"""Read-only installed artifact identity, without serializing configuration values."""
from __future__ import annotations

import hashlib
import os
import re
import sys
import zipfile
from importlib import metadata
from pathlib import Path
from typing import ClassVar, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sb.config import Config
from sb.contract_digest import TASK32_CONTRACT_DIGEST


class ReleaseManifest(BaseModel):
    """Whitelist of attestable, non-secret release fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_profile: Literal["task32-schema4"]
    contract_profile_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    working_tree_modified: bool | None = None


class IdentityReport(TypedDict):
    status: Literal["ok", "degraded"]
    reasons: list[str]
    source_commit: str | None
    wheel_sha: str | None
    installed_metadata: dict[str, str]
    process_entrypoint: str
    contract_profile: str | None
    contract_profile_digest: str | None
    configured_provider_identity: str
    active_generation: str | None
    working_tree_modified: bool | None


def runtime_identity(config: Config, *, manifest_path: Path | None = None) -> IdentityReport:
    """Bind the current imported package to a release manifest and wheel."""
    path = manifest_path or Path(os.environ.get("SB_RELEASE_MANIFEST", str(Path(sys.prefix).parent / "release-manifest.json")))
    distribution = metadata.distribution("second-brain")
    package = Path(__file__).resolve().parent
    report: IdentityReport = {
        "status": "degraded", "reasons": [], "source_commit": None, "wheel_sha": None,
        "installed_metadata": {"name": distribution.metadata["Name"], "version": distribution.version},
        "process_entrypoint": Path(sys.argv[0]).name,
        "contract_profile": None, "contract_profile_digest": TASK32_CONTRACT_DIGEST,
        "configured_provider_identity": hashlib.sha256(config.provider_instance_id.encode()).hexdigest(),
        "active_generation": None, "working_tree_modified": None,
    }
    generation = Path(config.vault_root).resolve().name
    if re.fullmatch(r"gen-[0-9a-f]{12,64}", generation):
        report["active_generation"] = generation
    try:
        manifest = ReleaseManifest.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        report["reasons"].append("RELEASE_MANIFEST_MISSING")
        return report
    except (OSError, ValueError, ValidationError):
        report["reasons"].append("RELEASE_MANIFEST_INVALID")
        return report
    report["source_commit"] = manifest.source_commit
    report["wheel_sha"] = manifest.wheel_sha256
    report["contract_profile"] = manifest.contract_profile
    report["working_tree_modified"] = manifest.working_tree_modified
    if manifest.contract_profile_digest is not None and manifest.contract_profile_digest != TASK32_CONTRACT_DIGEST:
        report["reasons"].append("CONTRACT_PROFILE_DIGEST_MISMATCH")
    wheels = sorted(path.parent.glob("second_brain-*.whl"))
    if len(wheels) != 1:
        report["reasons"].append("RELEASE_WHEEL_MISSING")
        return report
    wheel = wheels[0]
    try:
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != manifest.wheel_sha256:
            report["reasons"].append("WHEEL_SHA_MISMATCH")
        with zipfile.ZipFile(wheel) as archive:
            entries = [name for name in archive.namelist() if name.startswith("sb/") and name.endswith(".py")]
            if not entries or any((package.parent / name).read_bytes() != archive.read(name) for name in entries):
                report["reasons"].append("INSTALLED_SOURCE_MISMATCH")
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1 or distribution.read_text("METADATA") != archive.read(metadata_names[0]).decode():
                report["reasons"].append("INSTALLED_METADATA_MISMATCH")
    except (OSError, KeyError, zipfile.BadZipFile):
        report["reasons"].append("RELEASE_WHEEL_INVALID")
    if not report["reasons"]:
        report["status"] = "ok"
    return report
