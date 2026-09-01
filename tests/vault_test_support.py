from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sb.contracts import PageSpec, SourceCite
from sb.vault import Vault, init_vault

CAS_HASH = "ab" + ("cd" * 31)
CAS_SID = CAS_HASH[:8]
DEAD_SID = "dead1234"


@dataclass(frozen=True, slots=True)
class MemoryLedger:
    hashes: dict[str, str] = field(default_factory=dict)

    def last_compiled_hash(self, page_id: str) -> str | None:
        return self.hashes.get(page_id)


def git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=env
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def seed_cas(root: Path, digest: str = CAS_HASH, data: bytes = b"blob") -> None:
    destination = root / "raw" / digest[:2] / digest
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = destination.write_bytes(data)
    assert written == len(data)


@dataclass(frozen=True, slots=True)
class CitedPageFixture:
    page_id: str = "identity-profile"
    body_md: str | None = None
    sid: str = CAS_SID
    digest: str = CAS_HASH


def cited_page(fixture: CitedPageFixture | None = None) -> PageSpec:
    selected = CitedPageFixture() if fixture is None else fixture
    text = (
        f"A cited fact.[^{selected.sid}]"
        if selected.body_md is None
        else selected.body_md
    )
    cite = SourceCite(
        sid=selected.sid,
        origin="me-wiki:identity/profile.md",
        hash=selected.digest,
        spans=["0-12"],
    )
    return PageSpec(
        page_id=selected.page_id,
        title="Profile",
        body_md=text,
        sources=[cite],
        status="active",
    )


def frontmatter_field(block: str, key: str) -> str:
    prefix = f"{key}:"
    for line in block.splitlines():
        stripped = line.strip().removeprefix("- ")
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip().strip("'\"")
    pytest.fail(f"missing frontmatter key {key}")


def ready(root: Path) -> Vault:
    vault = init_vault(root)
    seed_cas(root)
    return vault
