"""Select verified state only for byte-identical sanitized restore pages."""
import hashlib

from sb.bound_knowledge import BoundKnowledge
from sb.restore_inventory import RestoreInventoryResult, RestoreMetadataScanner
from sb.tombstone_snapshot import TombstoneSnapshot


def matching_restore_knowledge(states: tuple[BoundKnowledge, ...],
                               inventory: RestoreInventoryResult,
                               snapshot: TombstoneSnapshot) -> tuple[BoundKnowledge, ...]:
    files = {item.relative.as_posix(): item.payload for item in inventory.files}
    if len(files) != len(inventory.files):
        raise ValueError('RESTORE_DUPLICATE_PATH')
    scanner = RestoreMetadataScanner(snapshot)
    return tuple(state for state in states
        if (body := files.get(state.page_id + '.md')) is not None
        and 'sha256:' + hashlib.sha256(body).hexdigest() == state.content_digest
        and scanner.is_clean(f"{state.page_id}\0{state.content_digest}\0{state.knowledge_status}\0{state.approval_status}".encode()))
