from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.delegations import (
    DelegationRejected,
    create_read_fence,
    verify_delegation,
    verify_read_fence,
)
from sb.effect_write_values import frozen_correction_vector

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


def test_frozen_delegation_verifies_with_pinned_ed25519_key() -> None:
    request = frozen_correction_vector()["request"]
    assert isinstance(request, dict)
    delegation = request["delegation"]
    assert isinstance(delegation, dict)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32))).public_key()
    parsed = verify_delegation(delegation, {"jarvis:fixture": key}, "provider:fixture", NOW)
    assert parsed.max_uses == 1
    assert parsed.operation == "correct"


def test_forged_delegation_has_zero_authority() -> None:
    request = frozen_correction_vector()["request"]
    assert isinstance(request, dict)
    delegation = deepcopy(request["delegation"])
    assert isinstance(delegation, dict)
    delegation["signature"] = "A" * 86
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32))).public_key()
    with pytest.raises(DelegationRejected, match="DELEGATION_SIGNATURE_INVALID"):
        _ = verify_delegation(delegation, {"jarvis:fixture": key}, "provider:fixture", NOW)


def test_frozen_cross_process_read_fence_identity() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    fence = create_read_fence(
        provider_instance_id="provider:fixture",
        purpose="memory_read",
        operation="read",
        sequence=2,
        set_root="sha256:908cd03d8a17024d3aae83927dc2053492a605ee16b02e1987d8aee7c8b76dfd",
        issued_at="2026-08-31T00:00:01.000Z",
        not_before="2026-08-31T00:00:01.000Z",
        expires_at="2026-08-31T00:01:01.000Z",
        nonce="memfence-nonce:" + "a" * 64,
        signing_key_id="jarvis:fixture",
        private_key=private,
    )
    assert fence.fence_digest == "sha256:0f9d63c623a72abe72f1c717bf9136f04fc2a41ba1be44f8c2c395d0e8c70fea"
    assert fence.fence_id == "memfence:v1:0f9d63c623a72abe72f1c717bf9136f04fc2a41ba1be44f8c2c395d0e8c70fea"
    assert fence.signature == "sQbb--0cXjA20TfC0_GeZVaeL7gkBVHPcAdgDb2m_5xe2M0gY8H33WiUVf2rXklWkz4ktqn4T-64BGisIhk7Bw"


def test_read_fence_binds_high_water_and_rejects_stale_root() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    root = "sha256:" + "1" * 64
    fence = create_read_fence(
        provider_instance_id="provider:fixture",
        purpose="memory_read",
        operation="read",
        sequence=3,
        set_root=root,
        issued_at="2026-08-31T00:00:00.000Z",
        not_before="2026-08-31T00:00:00.000Z",
        expires_at="2026-08-31T00:05:00.000Z",
        nonce="nonce:" + "2" * 64,
        signing_key_id="jarvis:fixture",
        private_key=private,
    )
    verified = verify_read_fence(
        fence.model_dump(mode="json"),
        {"jarvis:fixture": private.public_key()},
        "provider:fixture",
        NOW,
        3,
        root,
    )
    assert verified.fence_id == fence.fence_id
    mismatched = fence.model_copy(update={"purpose": "memory_status"})
    with pytest.raises(DelegationRejected, match="TOMBSTONE_FENCE_REQUIRED"):
        _ = verify_read_fence(
            mismatched.model_dump(mode="json"),
            {"jarvis:fixture": private.public_key()},
            "provider:fixture",
            NOW,
            3,
            root,
        )
    with pytest.raises(DelegationRejected, match="TOMBSTONE_SET_STALE"):
        _ = verify_read_fence(
            fence.model_dump(mode="json"),
            {"jarvis:fixture": private.public_key()},
            "provider:fixture",
            NOW,
            4,
            "sha256:" + "3" * 64,
        )
