from __future__ import annotations
import hashlib, json, re, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data/db/sports_v45.sqlite'
CONTEXT_STATS=('ctx_international_flag','ctx_global_tier','ctx_stage_pressure','ctx_recent_int_30d')
GLOBAL_PATTERNS=re.compile(r'(world cup|world championship|worlds|olympic|olympics|olympic qualifying|world qualifier|world qualifiers|masters|champions|grand slam|davis cup|billie jean king cup|united cup|vnl|nations league|fivb|fiba|avc|cev|norcesca|continental|afrobasket|americup|asia cup|eurobasket|pan american|sudamericano|rizin|ufc)',re.I)
CONTINENTAL_PATTERNS=re.compile(r'(euro|european|asia|asian|africa|african|americas|american|oceania|avc|cev|norcesca|afrobasket|americup|asia cup)',re.I)
GLOBAL_TIER_PATTERNS=re.compile(r'(world cup|world championship|olympic|olympics|champions|grand slam|masters|worlds)',re.I)
QUALIFIER_PATTERNS=re.compile(r'(qualif|pre-qualif|play-in|lcq|last chance)',re.I)
FINAL_PATTERNS=re.compile(r'(final|championship match|gold medal|title)',re.I); SEMI_PATTERNS=re.compile(r'(semi[- ]?final)',re.I); QF_PATTERNS=re.compile(r'(quarter[- ]?final)',re.I); PLAYOFF_PATTERNS=re.compile(r'(playoff|knockout|elimination)',re.I)
def now(): return datetime.now(timezone.utc).isoformat()
def sid(*xs): return hashlib.sha256('|'.join('' if x is None else str(x) for x in xs).encode()).hexdigest()[:32]
def dt(v):
    if not v:return None
    try:
        x=datetime.fromisoformat(str(v).replace('Z','+00:00')); return (x if x.tzinfo else x.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except:return None
def classify(competition,stage,round_):
    text=' '.join(str(x or '') for x in (competition,stage,round_)); international=bool(GLOBAL_PATTERNS.search(text)); tier=3.0 if GLOBAL_TIER_PATTERNS.search(text) else 2.0 if CONTINENTAL_PATTERNS.search(text) else 1.0 if international else 0.0
    pressure=1.0 if FINAL_PATTERNS.search(text) else .85 if SEMI_PATTERNS.search(text) else .70 if QF_PATTERNS.search(text) else .55 if PLAYOFF_PATTERNS.search(text) else .45 if QUALIFIER_PATTERNS.search(text) else .25 if international else 0.0
    return int(international),tier,pressure
def source_gate(c,event_id,cutoff):
    rows=c.execute('''SELECT ep.source,ep.source_url,ss.availability_status,ss.source_available_at_utc FROM event_participant ep LEFT JOIN source_snapshot ss ON ss.source=ep.source AND ss.source_url=ep.source_url WHERE ep.event_id=? AND ep.source_url IS NOT NULL ORDER BY CASE WHEN ss.availability_status='EXACT' THEN 0 ELSE 1 END''',(event_id,)).fetchall()
    for r in rows:
        a=dt(r[3])
        if r[2]=='EXACT' and a and a<=cutoff:return r[0],r[1],True
    return (rows[0][0],rows[0][1],False) if rows else ('international-context',None,False)
def rebuild():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    events=c.execute('SELECT event_id,sport,competition_id,stage,round,event_time_utc FROM event WHERE event_time_utc IS NOT NULL ORDER BY event_time_utc,event_id').fetchall(); history={}; written=exact=0; verified_context={}
    # First establish which historical competition metadata was itself observable by its own cutoff.
    for e in events:
        et=dt(e['event_time_utc']);
        if not et: continue
        verified_context[e['event_id']]=source_gate(c,e['event_id'],et-timedelta(minutes=60))[2]
    for e in events:
        et=dt(e['event_time_utc']);
        if not et: continue
        cutoff=et-timedelta(minutes=60); intl,tier,pressure=classify(e['competition_id'],e['stage'],e['round']); ps=c.execute("SELECT participant_id,side FROM event_participant WHERE event_id=? AND side IN ('A','B') AND participant_id IS NOT NULL",(e['event_id'],)).fetchall()
        if not ps: continue
        src,url,exact_source=source_gate(c,e['event_id'],cutoff)
        for p in ps:
            pid=p['participant_id']; recent=history.get(pid,[]); recent_int=sum(1 for is_int,ts,ok in recent if is_int and ok and et-ts<=timedelta(days=30)); values={'ctx_international_flag':float(intl),'ctx_global_tier':tier,'ctx_stage_pressure':pressure,'ctx_recent_int_30d':float(recent_int)}
            for name,value in values.items():
                quality='EXACT' if exact_source else 'UNVERIFIABLE'; effective=cutoff.isoformat() if exact_source else None
                c.execute('''INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,team_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,value_text,unit,source,source_url,quality_status,confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(sid('international-context-v2',e['event_id'],pid,name),e['event_id'],pid,pid,e['sport'],now(),effective,name,value,str(value),'context',src,url,quality,1.0 if exact_source else 0.0)); written+=1; exact+=int(exact_source)
            history.setdefault(pid,[]).append((bool(intl),et,verified_context.get(e['event_id'],False)))
    c.commit(); c.close(); return {'events':len(events),'context_rows':written,'exact_rows':exact,'pit_policy':'historical context only counts when the context source was EXACT by that event cutoff'}
def main():
    if not DB.exists(): raise SystemExit('database missing')
    print(json.dumps(rebuild(),ensure_ascii=False,indent=2))
if __name__=='__main__': main()
