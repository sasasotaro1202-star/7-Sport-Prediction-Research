from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REQUIRED = {
    'source_snapshot', 'event', 'event_participant', 'participant_history',
    'team_history', 'match_stats', 'availability', 'event_outcome',
    'pit_replay', 'pit_feature_snapshot', 'model_state_snapshot',
    'replay_audit', 'collection_state'
}


def inspect(db: Path) -> dict:
    if not db.exists() or db.stat().st_size == 0:
        return {'status': 'MISSING', 'db': str(db), 'size_bytes': 0}
    try:
        con = sqlite3.connect(db, timeout=5)
        con.row_factory = sqlite3.Row
        integrity = con.execute('PRAGMA quick_check').fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(REQUIRED - tables)
        events = int(con.execute('SELECT COUNT(*) FROM event').fetchone()[0]) if 'event' in tables else 0
        snapshots = int(con.execute('SELECT COUNT(*) FROM source_snapshot').fetchone()[0]) if 'source_snapshot' in tables else 0
        con.close()
        if integrity != 'ok':
            return {'status': 'CORRUPT', 'db': str(db), 'integrity': integrity}
        if missing:
            return {'status': 'INCOMPLETE_SCHEMA', 'db': str(db), 'missing_tables': missing}
        return {'status': 'OK', 'db': str(db), 'size_bytes': db.stat().st_size,
                'event_rows': events, 'source_snapshot_rows': snapshots}
    except Exception as exc:
        return {'status': 'UNREADABLE', 'db': str(db), 'error': repr(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/db/sports_v45.sqlite')
    ap.add_argument('--sport', default=None)
    ap.add_argument('--repair', action='store_true')
    args = ap.parse_args()
    db = Path(args.db)
    result = inspect(db)
    result['sport'] = args.sport
    result['repair_attempted'] = False
    if args.repair and result['status'] in {'CORRUPT', 'INCOMPLETE_SCHEMA', 'UNREADABLE'}:
        result['repair_attempted'] = True
        try:
            db.unlink(missing_ok=True)
            result['status_after_repair'] = 'REMOVED_FOR_REBUILD'
        except Exception as exc:
            result['status_after_repair'] = 'REPAIR_FAILED'
            result['repair_error'] = repr(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Missing is acceptable before first collection; corruption/schema failures are repaired
    # by removing the cache so the next initialization starts from a clean database.
    return 0 if result['status'] in {'OK', 'MISSING'} or result.get('status_after_repair') == 'REMOVED_FOR_REBUILD' else 1


if __name__ == '__main__':
    raise SystemExit(main())
