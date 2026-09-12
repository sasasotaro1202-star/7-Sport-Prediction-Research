from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')


def utc(): return datetime.now(timezone.utc).isoformat()


def main():
    import argparse
    ap=argparse.ArgumentParser(description='Generate an auditable inventory of prediction eligibility.')
    ap.add_argument('--sport',choices=SPORTS)
    a=ap.parse_args()
    con=sqlite3.connect(DB)
    sports=(a.sport,) if a.sport else SPORTS
    out=[]
    for sport in sports:
        events=con.execute("""SELECT e.event_id,e.event_time_utc,e.status,epc.n
                             FROM event e
                             LEFT JOIN (SELECT event_id,COUNT(DISTINCT participant_id) n FROM event_participant WHERE participant_id IS NOT NULL GROUP BY event_id) epc
                             ON epc.event_id=e.event_id
                             WHERE e.sport=? AND e.event_time_utc IS NOT NULL
                             ORDER BY e.event_time_utc""",(sport,)).fetchall()
        eligible=0
        reasons={}
        for eid,et,status,n in events:
            outcome=con.execute("SELECT outcome_status FROM event_outcome WHERE event_id=?",(eid,)).fetchone()
            # Future prediction eligibility does not require an outcome, but does require a timestamp,
            # exactly two sides/participants, and at least one accepted model state.
            model=con.execute("SELECT 1 FROM model_state_snapshot WHERE sport=? AND market='winner' AND quality_status LIKE 'ACCEPTED%' LIMIT 1",(sport,)).fetchone()
            if int(n or 0)!=2:
                reason='not_exactly_two_participants'
            elif not model:
                reason='no_accepted_model'
            else:
                reason='ELIGIBLE'
                eligible+=1
            reasons[reason]=reasons.get(reason,0)+1
        out.append({'sport':sport,'events':len(events),'eligible_future_events':eligible,'reasons':reasons})
    report={'timestamp_utc':utc(),'policy':'prediction-eligibility-v1','sports':out}
    path=ROOT/'results/prediction_eligibility.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
