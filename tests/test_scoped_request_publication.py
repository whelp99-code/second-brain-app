import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sb.scoped_request_publication import publish_scoped_pending
from sb.task30_barriers import BarrierEvent


def material():
    value = json.loads((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    return value, datetime.fromisoformat(value["created_at"])


class FailAfterPublish:
    def reach(self, event: BarrierEvent):
        if event.barrier_id.value == "pending_publish_fsync":
            raise RuntimeError("injected after publication")


def test_published_orphan_is_adopted_with_original_bytes_and_timestamp(tmp_path):
    value, now = material()
    tmp_path.chmod(0o700)
    with pytest.raises(RuntimeError, match="injected"):
        publish_scoped_pending(tmp_path, value, now=now, expected_provider="provider:fixture", barrier_sink=FailAfterPublish())
    path = next(tmp_path.glob("*.v4.json"))
    original = path.read_bytes()
    recovered = publish_scoped_pending(tmp_path, value, now=now + timedelta(milliseconds=1), expected_provider="provider:fixture")
    assert recovered.canonical == original == path.read_bytes()
    assert recovered.accepted_at == value["created_at"]
    assert len(list(tmp_path.iterdir())) == 1
    assert path.stat().st_mode & 0o777 == 0o600
    repeated = publish_scoped_pending(tmp_path, value, now=now + timedelta(milliseconds=2), expected_provider="provider:fixture")
    assert repeated == recovered


def test_unsafe_or_changed_existing_file_is_not_overwritten(tmp_path):
    value, now = material()
    published = publish_scoped_pending(tmp_path, value, now=now, expected_provider="provider:fixture")
    published.path.write_bytes(b"{}\n")
    with pytest.raises(ValueError):
        publish_scoped_pending(tmp_path, value, now=now, expected_provider="provider:fixture")
    assert published.path.read_bytes() == b"{}\n"
    published.path.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    published.path.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        publish_scoped_pending(tmp_path, value, now=now, expected_provider="provider:fixture")
    assert outside.read_bytes() == b"unchanged"


def test_public_directory_is_rejected_before_writing(tmp_path):
    value, now = material()
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="WRITE_REQUEST_INBOX_UNSAFE"):
        publish_scoped_pending(tmp_path, value, now=now, expected_provider="provider:fixture")
    assert not list(tmp_path.iterdir())
