"""Bind a prior-content absence check to the immutable successor before removing its source."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

from sb.managed_copy_disposal import copy_inventory


class CancellationAbsenceError(RuntimeError):
    pass


def record_cancellation_absence(db: sqlite3.Connection, intent_id: str, generation_id: str,
    generation_digest: str, root: Path, needles: tuple[bytes, ...] | None,
) -> str:
    if needles is None:
        return require_cancellation_absence(db,intent_id,generation_id,generation_digest,root)
    if not needles or any(not needle for needle in needles):
        raise CancellationAbsenceError('CANCELLATION_ABSENCE_UNPROVED')
    inventory=copy_inventory((root,),needles)
    _=db.execute('''INSERT INTO correction_cancellation_absence VALUES(?,?,?,?)
        ON CONFLICT(intent_id) DO UPDATE SET generation_id=excluded.generation_id,
        generation_digest=excluded.generation_digest,inventory_digest=excluded.inventory_digest''',
        (intent_id,generation_id,generation_digest,inventory))
    return inventory


def require_cancellation_absence(db: sqlite3.Connection, intent_id: str, generation_id: str,
    generation_digest: str, root: Path,
) -> str:
    row=cast(sqlite3.Row|None,db.execute('SELECT generation_id,generation_digest,inventory_digest FROM correction_cancellation_absence WHERE intent_id=?',
        (intent_id,)).fetchone())
    if row is None or tuple(row) != (generation_id,generation_digest,copy_inventory((root,))):
        raise CancellationAbsenceError('CANCELLATION_ABSENCE_UNPROVED')
    value=cast(object,row[2])
    if not isinstance(value,str):
        raise CancellationAbsenceError('CANCELLATION_ABSENCE_UNPROVED')
    return value
