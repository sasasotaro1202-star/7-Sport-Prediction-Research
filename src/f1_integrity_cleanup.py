from __future__ import annotations
import argparse
import json
from src.storage.db_v45 import connect


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--vacuum', action='store_true')
    args = ap.parse_args()
    con = connect()
    before = {table: con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
              for table in ('event_participant', 'match_stats', 'participant')}

    # F1 event_participant is strictly a driver-entry relation. Results, qualifying,
    # pitstops and any other observation roles belong in match_stats, never here.
    removed_non_driver = con.execute("""
        DELETE FROM event_participant
        WHERE event_id IN (SELECT event_id FROM event WHERE sport='f1')
          AND LOWER(COALESCE(role,'')) <> 'driver'
    """).rowcount

    # Remove blank/unmappable F1 participants that have no surviving driver relation.
    bad_pids = [r[0] for r in con.execute("""
        SELECT p.participant_id
        FROM participant p
        WHERE p.sport='f1'
          AND TRIM(COALESCE(p.canonical_name,''))=''
          AND NOT EXISTS (
              SELECT 1 FROM event_participant ep
              WHERE ep.participant_id=p.participant_id
                AND ep.role='driver'
          )
    """).fetchall()]
    removed_stats = 0
    removed_participants = 0
    if bad_pids:
        marks = ','.join('?' for _ in bad_pids)
        removed_stats = con.execute(
            f'DELETE FROM match_stats WHERE participant_id IN ({marks}) AND sport=\'f1\'',
            bad_pids,
        ).rowcount
        removed_participants = con.execute(
            f'DELETE FROM participant WHERE participant_id IN ({marks})',
            bad_pids,
        ).rowcount

    con.commit()
    if args.vacuum:
        con.execute('VACUUM')

    after = {table: con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
             for table in ('event_participant', 'match_stats', 'participant')}
    report = {
        'status': 'OK',
        'removed_non_driver_f1_event_participants': removed_non_driver,
        'removed_unmappable_f1_stats': removed_stats,
        'removed_unmappable_f1_participants': removed_participants,
        'before': before,
        'after': after,
    }
    print(json.dumps(report, ensure_ascii=False))
    con.close()


if __name__ == '__main__':
    main()
