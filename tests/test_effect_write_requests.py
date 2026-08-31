from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.effect_write_requests import EffectWriteIoError, accept_effect_request
from sb.effect_write_values import frozen_correction_vector, frozen_effect_vectors
from sb.request_store import ReplayConflict

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


def test_stable_v2_publish_and_exact_replay(tmp_path: Path) -> None:
    request = frozen_correction_vector()["request"]
    first = accept_effect_request(tmp_path, request, NOW)
    second = accept_effect_request(tmp_path, request, NOW)
    path = tmp_path / first.queue_locator
    assert first.replayed is False and second.replayed is True
    assert first.request_file_digest == second.request_file_digest
    assert first.accepted_at == second.accepted_at
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_nlink == 1
    assert path.read_bytes().endswith(b"\n")


def test_completed_semantic_alias_conflict_is_permanent(tmp_path: Path) -> None:
    request = frozen_correction_vector()["request"]
    _ = accept_effect_request(tmp_path, request, NOW)
    changed = deepcopy(request)
    assert isinstance(changed, dict)
    changed["envelope_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        _ = accept_effect_request(tmp_path, changed, NOW)
    assert len(tuple((tmp_path / "pending").glob("*.v2.json"))) == 1


def test_symlinked_request_root_fails_before_publication(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "requests"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises((EffectWriteIoError, OSError)):
        _ = accept_effect_request(root, frozen_correction_vector()["request"], NOW)
    assert tuple(outside.iterdir()) == ()


def test_unused_revoked_delegation_fails_before_publication(tmp_path: Path) -> None:
    forget = frozen_effect_vectors()["forget"]
    assert isinstance(forget, dict)
    request = forget["request"]
    delegation_id = forget["delegation_id"]
    assert isinstance(delegation_id, str)
    with pytest.raises(ValueError, match="EFFECT_DELEGATION_INVALID"):
        _ = accept_effect_request(tmp_path, request, NOW, revoked_delegations={delegation_id})
    assert not (tmp_path / "pending").exists() or tuple((tmp_path / "pending").iterdir()) == ()


def test_changed_global_alias_rejected_from_journal(tmp_path: Path) -> None:
    request = frozen_correction_vector()["request"]
    first = accept_effect_request(tmp_path, request, NOW)
    path = tmp_path / first.queue_locator
    path.unlink()
    changed = deepcopy(request)
    assert isinstance(changed, dict)
    changed["request_id"] = "memeff:req:v2:" + "f" * 64
    with pytest.raises((ReplayConflict, ValueError)):
        _ = accept_effect_request(tmp_path, changed, NOW)
    assert not os.path.lexists(path)
