from __future__ import annotations
import argparse
import json
from src.storage.db_v45 import connect


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--vacuum', action='store_true')
    args = ap.parse_args()
    con = connect()
    before = {}
    for table in ('event_participant', 'match_stats', 'participant'):
        before[table] = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    # Jolpica/OpenF1 pit-stop rows are observations/statistics, not event participants.
    # Older collector runs incorrectly inserted them into event_participant, creating
    # millions of false participant relations and contaminating F1 feature generation.
    removed_ep = con.execute("""
        DELETE FROM event_participant
        WHERE event_id IN (SELECT event_id FROM event WHERE sport='f1')
          AND LOWER(COALESCE(role,'')) IN ('pitstops','pitstop','pit_stop')
    """).rowcount

    # Remove orphaned synthetic/blank F1 participants that were created only by those
    # malformed pit-stop relations. Their associated pit-stop stats are removed too;
    # silently retaining unmappable observations would be worse for model integrity.
    bad_pids = [r[0] for r in con.execute("""
        SELECT p.participant_id
        FROM participant p
        WHERE p.sport='f1'
          AND (TRIM(COALESCE(p.canonical_name,''))='')
          AND NOT EXISTS (
              SELECT 1 FROM event_participant ep
              WHERE ep.participant_id=p.participant_id AND ep.role='driver'
          )
    """).fetchall()]
    removed_stats = 0
    if bad_pids:
        marks=','.join('?' for _ in bad_pids)
        removed_stats = con.execute(
            f"DELETE FROM match_stats WHERE participant_id IN ({marks}) AND LOWER(stat_name) LIKE 'pitstops.%'",
            bad_pids,
        ).rowcount
        con.execute(f"DELETE FROM participant WHERE participant_id IN ({marks})", bad_pids)

    # Remove any now-orphaned non-driver relations for F1 blank participants.
    con.execute("""
        DELETE FROM event_participant
        WHERE event_id IN (SELECT event_id FROM event WHERE sport='f1')
          AND participant_id IN (
              SELECT participant_id FROM participant
              WHERE sport='f1' AND TRIM(COALESCE(canonical_name,''))=''
          )
    """)
    con.commit()
    if args.vacuum:
        con.execute('VACUUM')

    after = {table: con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
             for table in ('event_participant','match_stats','participant')}
    report={
        'status':'OK',
        'removed_f1_pitstop_event_participants': removed_ep,
        'removed_unmappable_pitstop_stats': removed_stats,
        'before': before,
        'after': after,
    }
    print(json.dumps(report, ensure_ascii=False))
    con.close()


if __name__ == '__main__':
    main()
