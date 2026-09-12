from __future__ import annotations
import hashlib, json, re, sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
CACHE=ROOT/'data/raw/http_cache'

def utc(): return datetime.now(timezone.utc).isoformat()
def sid(*x): return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]

def cache_text(url):
    p=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding='utf-8')).get('text')
    except Exception: return None

def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS event_outcome(
      event_id TEXT PRIMARY KEY, sport TEXT NOT NULL, side_a_participant_id TEXT, side_b_participant_id TEXT,
      outcome TEXT, score_a REAL, score_b REAL, outcome_status TEXT NOT NULL, source TEXT, source_url TEXT,
      observed_at_utc TEXT NOT NULL, quality_status TEXT NOT NULL, reason TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_outcome_sport ON event_outcome(sport,outcome_status)')
    c.commit()

def participants(c,eid):
    return c.execute('SELECT participant_id,side FROM event_participant WHERE event_id=? ORDER BY CASE side WHEN "A" THEN 0 WHEN "B" THEN 1 ELSE 2 END',(eid,)).fetchall()

def main():
    c=sqlite3.connect(DB); init(c)
    rows=c.execute("SELECT event_id,sport,event_time_utc,source_count FROM event WHERE status IN ('COMPLETED','FINISHED','POST')").fetchall()
    verified=0; deferred=0
    for eid,sport,et,_ in rows:
        ps=participants(c,eid)
        if len(ps)<2: deferred+=1; continue
        a,b=ps[0][0],ps[1][0]
        outcome=sa=sb=None; source=url=reason=None
        # ESPN scoreboard JSON is retained in the source cache. Use the competitor winner flag and score only.
        if sport in ('basketball','tennis'):
            u=c.execute('SELECT source_url FROM source_snapshot WHERE source="espn" AND source_url IS NOT NULL ORDER BY retrieved_at_utc DESC').fetchall()
            for (url0,) in u:
                txt=cache_text(url0)
                if not txt: continue
                try: data=json.loads(txt)
                except Exception: continue
                for ev in data.get('events',[]):
                    name=str(ev.get('name') or ev.get('shortName') or ev.get('id') or '')
                    if not name: continue
                    # Match by stable event construction inputs rather than display-name substring alone.
                    comps=(ev.get('competitions') or [{}])[0].get('competitors') or []
                    if len(comps)<2: continue
                    names=[str((x.get('team') or {}).get('displayName') or x.get('displayName') or '') for x in comps[:2]]
                    epnames=[r[0] for r in c.execute('SELECT p.canonical_name FROM event_participant ep JOIN participant p ON p.participant_id=ep.participant_id WHERE ep.event_id=? ORDER BY ep.side',(eid,)).fetchall()]
                    if len(epnames)<2 or names[0]!=epnames[0] or names[1]!=epnames[1]: continue
                    vals=[]
                    for x in comps[:2]:
                        try: vals.append(float(x.get('score')))
                        except Exception: vals.append(None)
                    if any(v is None for v in vals): continue
                    if comps[0].get('winner') is True: outcome='A'
                    elif comps[1].get('winner') is True: outcome='B'
                    elif vals[0]>vals[1]: outcome='A'
                    elif vals[1]>vals[0]: outcome='B'
                    else: outcome='DRAW'
                    sa,sb=vals; source='espn'; url=url0; break
                if outcome: break
        elif sport=='f1':
            vals=c.execute("SELECT ep.participant_id,ms.value_num FROM event_participant ep JOIN match_stats ms ON ms.event_id=ep.event_id AND ms.participant_id=ep.participant_id WHERE ep.event_id=? AND ms.stat_name='results.position' AND ms.value_num IS NOT NULL ORDER BY ms.value_num ASC",(eid,)).fetchall()
            if vals:
                winner=vals[0][0]; outcome='A' if winner==a else 'B' if winner==b else None
                if outcome: source='jolpica'; url=c.execute('SELECT source_url FROM event WHERE event_id=?',(eid,)).fetchone()[0]
        if outcome:
            c.execute('INSERT OR REPLACE INTO event_outcome VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(eid,sport,a,b,outcome,sa,sb,'VERIFIED',source,url,utc(),'PIT_REQUIRES_REPLAY','Derived only from source-backed result data'))
            verified+=1
        else:
            deferred+=1
    c.commit(); print(json.dumps({'verified':verified,'deferred':deferred,'total_completed_events':len(rows)},ensure_ascii=False))
    c.close()
if __name__=='__main__': main()
