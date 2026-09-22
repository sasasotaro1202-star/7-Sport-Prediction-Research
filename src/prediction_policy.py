from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1','rugby','boxing')

def utc(): return datetime.now(timezone.utc).isoformat()

def main():
    import argparse
    ap=argparse.ArgumentParser(description='Generate an auditable inventory of prediction eligibility.')
    ap.add_argument('--sport',choices=SPORTS)
    a=ap.parse_args(); con=sqlite3.connect(DB); sports=(a.sport,) if a.sport else SPORTS; out=[]
    for sport in sports:
        events=con.execute("""SELECT e.event_id,e.event_time_utc,e.status,COALESCE(epc.n,0)
                             FROM event e LEFT JOIN (SELECT event_id,COUNT(DISTINCT participant_id) n FROM event_participant WHERE participant_id IS NOT NULL GROUP BY event_id) epc
                             ON epc.event_id=e.event_id WHERE e.sport=? AND e.event_time_utc IS NOT NULL ORDER BY e.event_time_utc""",(sport,)).fetchall()
        eligible=0; reasons={}
        for eid,et,status,n in events:
            model=con.execute("SELECT 1 FROM model_state_snapshot WHERE sport=? AND market='winner' AND quality_status LIKE 'ACCEPTED%' LIMIT 1",(sport,)).fetchone()
            # Head-to-head sports require exactly two participants. F1 is inherently multiclass: a race has a field of >=2 drivers.
            participant_ok=(int(n or 0)==2) if sport!='f1' else (int(n or 0)>=2)
            if not participant_ok: reason='invalid_participant_count'
            elif not model: reason='no_accepted_model'
            else: reason='ELIGIBLE'; eligible+=1
            reasons[reason]=reasons.get(reason,0)+1
        out.append({'sport':sport,'events':len(events),'eligible_future_events':eligible,'reasons':reasons})
    report={'timestamp_utc':utc(),'policy':'prediction-eligibility-v2-multiclass-f1','sports':out}
    path=ROOT/'results/prediction_eligibility.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
