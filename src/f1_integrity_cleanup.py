from __future__ import annotations
import argparse
import json
from src.storage.db_v45 import connect


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--vacuum', action='store_true')
    args = ap.parse_args()
    con = connect()
    before = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
              for t in ('event_participant', 'match_stats', 'participant')}

    # F1 event_participant is the canonical participant relation. Only driver
    # relations belong there. Results/qualifying/pit-stop rows are statistics,
    # not additional participant relations. Keeping them here caused a huge
    # relation explosion and distorted downstream feature generation.
    removed_ep = con.execute("""
        DELETE FROM event_participant
        WHERE event_id IN (SELECT event_id FROM event WHERE sport='f1')
          AND LOWER(COALESCE(role,'')) <> 'driver'
    """).rowcount

    # Remove synthetic blank F1 participants that were created by malformed
    # pit-stop rows. Their unmappable pit-stop statistics are discarded rather
    # than silently treated as driver features.
    bad_pids = [r[0] for r in con.execute("""
        SELECT p.participant_id
        FROM participant p
        WHERE p.sport='f1'
          AND TRIM(COALESCE(p.canonical_name,''))=''
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

    con.commit()
    if args.vacuum:
        con.execute('VACUUM')

    after = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
             for t in ('event_participant','match_stats','participant')}
    report={
        'status':'OK',
        'removed_f1_non_driver_event_participants': removed_ep,
        'removed_unmappable_pitstop_stats': removed_stats,
        'before': before,
        'after': after,
    }
    print(json.dumps(report, ensure_ascii=False))
    con.close()


if __name__ == '__main__':
    main()
