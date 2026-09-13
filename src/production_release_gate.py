from __future__ import annotations
import json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/db/sports_v45.sqlite';OUT=ROOT/'results/release_gate.json';SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')
def main():
 r={'status':'BLOCKED','publish':False,'fatal':[],'coverage':{},'policy':'source outages may degrade a run, but never publish an unverified model'}
 if not DB.exists():r['fatal'].append('database_missing')
 else:
  c=sqlite3.connect(DB);counts=dict(c.execute('select sport,count(*) from event group by sport').fetchall());models=dict(c.execute("select sport,count(*) from model_state_snapshot where quality_status like 'ACCEPTED%' group by sport").fetchall());r['coverage']={s:{'events':int(counts.get(s,0)),'accepted_models':int(models.get(s,0))} for s in SPORTS};bad=c.execute("select count(*) from pit_replay where leakage_status not in ('PASS','UNKNOWN','CLEAN')").fetchone()[0];exact_missing=c.execute("select count(*) from source_snapshot where availability_status='EXACT' and source_available_at_utc is null").fetchone()[0];c.close();
  if bad:r['fatal'].append('pit_leakage_detected')
  if exact_missing:r['fatal'].append('exact_source_missing_availability_time')
 if not r['fatal']:
  ready=all(v['events']>0 and v['accepted_models']>0 for v in r['coverage'].values());r['status']='READY' if ready else 'DEGRADED_BLOCKED';r['publish']=ready
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())