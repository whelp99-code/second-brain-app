"""CAS raw store: sha256 placement, 0444 mode, idempotent put/get/exists."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from sb.store.cas import CasBlobMissing, ContentAddressedStore

_PAYLOAD: bytes = b"second-brain cas fixture v1"
_DIGEST: str = hashlib.sha256(_PAYLOAD).hexdigest()


def test_put_returns_sha256_hex_of_bytes(tmp_path: Path) -> None:
    """Given a vault, when bytes are put, then the sha256 hex of those bytes is returned."""
    cas = ContentAddressedStore(tmp_path)

    digest = cas.put(_PAYLOAD)

    assert digest == _DIGEST


def test_put_writes_blob_under_hash_prefix_path(tmp_path: Path) -> None:
    """Given a vault, when bytes are put, then the blob lives at raw/<h[:2]>/<h>."""
    cas = ContentAddressedStore(tmp_path)

    digest = cas.put(_PAYLOAD)

    blob = tmp_path / "raw" / digest[:2] / digest
    assert blob.is_file()
    assert blob.read_bytes() == _PAYLOAD


def test_put_sets_blob_mode_0444(tmp_path: Path) -> None:
    """Given a vault, when a blob is stored, then the file mode is 0444."""
    cas = ContentAddressedStore(tmp_path)

    digest = cas.put(_PAYLOAD)

    mode = stat.S_IMODE((tmp_path / "raw" / digest[:2] / digest).stat().st_mode)
    assert mode == 0o444


def test_put_is_idempotent_same_bytes_one_file(tmp_path: Path) -> None:
    """Given stored bytes, when the same bytes are put again, then hash and file count stay 1."""
    cas = ContentAddressedStore(tmp_path)

    first = cas.put(_PAYLOAD)
    second = cas.put(_PAYLOAD)

    files = [path for path in (tmp_path / "raw").rglob("*") if path.is_file()]
    assert first == second == _DIGEST
    assert len(files) == 1


def test_get_returns_original_bytes_when_blob_exists(tmp_path: Path) -> None:
    """Given a stored blob, when get is called with its hash, then the original bytes return."""
    cas = ContentAddressedStore(tmp_path)
    digest = cas.put(_PAYLOAD)

    data = cas.get(digest)

    assert data == _PAYLOAD


def test_get_raises_cas_blob_missing_when_absent(tmp_path: Path) -> None:
    """Given an empty store, when get is called with an unknown hash, then CasBlobMissing raises."""
    cas = ContentAddressedStore(tmp_path)

    with pytest.raises(CasBlobMissing):
        _ = cas.get(_DIGEST)


def test_exists_is_true_only_for_stored_hash(tmp_path: Path) -> None:
    """Given one stored blob, when exists is queried, then only that hash is present."""
    cas = ContentAddressedStore(tmp_path)
    _ = cas.put(_PAYLOAD)

    assert cas.exists(_DIGEST) is True
    assert cas.exists("0" * 64) is False
