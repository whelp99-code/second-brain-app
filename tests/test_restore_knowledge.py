import hashlib
from pathlib import Path

import pytest

from sb.bound_knowledge import BoundKnowledge
from sb.restore_inventory import RestoreInventoryResult, SanitizedRestoreFile
from sb.restore_knowledge import matching_restore_knowledge
from sb.tombstone_snapshot import BlockedTargetIdentity, TombstoneSnapshot

EMPTY = TombstoneSnapshot(0, "unused", "unused", (), ())


@pytest.mark.parametrize('body', [b'original', b'changed', None])
def test_only_exact_sanitized_body_retains_state(body):
    state = BoundKnowledge('wiki/page', 'sha256:' + hashlib.sha256(b'original').hexdigest(), 'ACTIVE', 'APPROVED')
    inventory = RestoreInventoryResult(() if body is None else (SanitizedRestoreFile(Path('wiki/page.md'), body),), '', 0, 0)
    assert matching_restore_knowledge((state,), inventory, EMPTY) == ((state,) if body == b'original' else ())


def test_duplicate_sanitized_paths_rejected():
    file = SanitizedRestoreFile(Path('wiki/page.md'), b'original')
    with pytest.raises(ValueError, match='RESTORE_DUPLICATE_PATH'):
        matching_restore_knowledge((), RestoreInventoryResult((file, file), '', 0, 0), EMPTY)


@pytest.mark.parametrize("blocked", ["비밀", "APPROVED", "ACTIVE"])
def test_blocked_metadata_never_reenters_ledger(blocked):
    body = b"surviving content"
    state = BoundKnowledge("wiki/비밀", "sha256:" + hashlib.sha256(body).hexdigest(), "ACTIVE", "APPROVED")
    inventory = RestoreInventoryResult((SanitizedRestoreFile(Path("wiki/비밀.md"), body),), "", 0, 0)
    payload = blocked.encode("utf-8")
    target = BlockedTargetIdentity(1, "unused", "unused", hashlib.sha256(payload).hexdigest(),
                                   "unused", "unused", "unused", "unused", 0, len(payload))
    snapshot = TombstoneSnapshot(1, "unused", "unused", (), (target,))
    assert matching_restore_knowledge((state,), inventory, snapshot) == ()
