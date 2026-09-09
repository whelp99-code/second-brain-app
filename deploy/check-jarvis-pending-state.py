"""Read only aggregate JARVIS pending-state evidence; never authorize a drain."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

STATES = (
    ('memory_outbox', 'state'), ('memory_outbox_attempts', 'outcome'),
    ('memory_candidate_dispatch_publications', 'state'), ('collaboration_bridge_outbox', 'state'),
    ('pre_gjc_report_outbox', 'state'), ('outbox', 'outcome'),
)
COUNTS = {
    'cursor_rows': 'SELECT count(*) FROM memory_effect_dispatch_cursor',
    'active_cursor_rows': 'SELECT count(*) FROM memory_effect_dispatch_cursor WHERE active_lane_id IS NOT NULL',
    'gjc_lease_rows': 'SELECT count(*) FROM gjc_runtime_leases',
    'microloop_lease_rows': 'SELECT count(*) FROM microloop_leases',
}


def inspect(database: Path) -> dict[str, object]:
    path = database.resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        states = {table: conn.execute(f'SELECT {column},count(*) FROM "{table}" '
                                     f'GROUP BY {column}').fetchall() for table, column in STATES}
        counts = {name: conn.execute(query).fetchone()[0] for name, query in COUNTS.items()}
        return {'database': str(path), 'states': states, 'counts': counts,
                'scope': 'single read transaction; named queues only; lease rows are not liveness proof',
                'drain_authorized': False}
    finally:
        conn.rollback()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.database), indent=2))
