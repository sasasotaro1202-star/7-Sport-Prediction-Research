from __future__ import annotations
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'

CONTEXT_STATS = (
    'ctx_international_flag',
    'ctx_global_tier',
    'ctx_stage_pressure',
    'ctx_recent_int_30d',
)

GLOBAL_PATTERNS = re.compile(r'(world cup|world championship|worlds|olympic|olympics|olympic qualifying|world qualifier|world qualifiers|masters|champions|grand slam|davis cup|billie jean king cup|united cup|vnl|nations league|fivb|fiba|avc|cev|norcesca|continental|afrobasket|americup|asia cup|eurobasket|pan american|sudamericano|rizin|ufc)', re.I)
CONTINENTAL_PATTERNS = re.compile(r'(euro|european|asia|asian|africa|african|americas|american|oceania|nor🇨🇦|avc|cev|norcesca|afrobasket|americup|asia cup)', re.I)
GLOBAL_TIER_PATTERNS = re.compile(r'(world cup|world championship|olympic|olympics|champions|grand slam|masters|worlds)', re.I)
QUALIFIER_PATTERNS = re.compile(r'(qualif|pre-qualif|play-in|lcq|last chance)', re.I)
FINAL_PATTERNS = re.compile(r'(final|championship match|gold medal|title)', re.I)
SEMI_PATTERNS = re.compile(r'(semi[- ]?final)', re.I)
QF_PATTERNS = re.compile(r'(quarter[- ]?final)', re.I)
PLAYOFF_PATTERNS = re.compile(r'(playoff|knockout|elimination)', re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


def sid(*xs):
    return hashlib.sha256('|'.join('' if x is None else str(x) for x in xs).encode()).hexdigest()[:32]


def dt(v):
    if not v:
        return None
    try:
        x = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        if x.tzinfo is None:
            x = x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc)
    except Exception:
        return None


def classify(competition, stage, round_):
    text = ' '.join(str(x or '') for x in (competition, stage, round_))
    international = bool(GLOBAL_PATTERNS.search(text))
    tier = 0.0
    if GLOBAL_TIER_PATTERNS.search(text):
        tier = 3.0
    elif CONTINENTAL_PATTERNS.search(text):
        tier = 2.0
    elif international:
        tier = 1.0
    if FINAL_PATTERNS.search(text):
        pressure = 1.0
    elif SEMI_PATTERNS.search(text):
        pressure = 0.85
    elif QF_PATTERNS.search(text):
        pressure = 0.70
    elif PLAYOFF_PATTERNS.search(text):
        pressure = 0.55
    elif QUALIFIER_PATTERNS.search(text):
        pressure = 0.45
    elif international:
        pressure = 0.25
    else:
        pressure = 0.0
    return int(international), tier, pressure


def source_gate(c, event_id, cutoff):
    rows = c.execute('''SELECT ep.source,ep.source_url,ss.availability_status,ss.source_available_at_utc
                        FROM event_participant ep
                        LEFT JOIN source_snapshot ss ON ss.source=ep.source AND ss.source_url=ep.source_url
                        WHERE ep.event_id=? AND ep.source_url IS NOT NULL
                        ORDER BY CASE WHEN ss.availability_status='EXACT' THEN 0 ELSE 1 END''', (event_id,)).fetchall()
    for r in rows:
        if r[2] == 'EXACT' and r[3]:
            a = dt(r[3])
            if a and a <= cutoff:
                return r[0], r[1], True
    return (rows[0][0], rows[0][1], False) if rows else ('international-context', None, False)


def rebuild():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    events = c.execute('''SELECT event_id,sport,competition_id,stage,round,event_time_utc
                          FROM event WHERE event_time_utc IS NOT NULL ORDER BY event_time_utc,event_id''').fetchall()
    history = {}
    written = 0
    exact = 0
    for e in events:
        et = dt(e['event_time_utc'])
        if not et:
            continue
        cutoff = et - timedelta(minutes=60)
        intl, tier, pressure = classify(e['competition_id'], e['stage'], e['round'])
        ps = c.execute('''SELECT participant_id,side FROM event_participant
                          WHERE event_id=? AND side IN ('A','B') AND participant_id IS NOT NULL''', (e['event_id'],)).fetchall()
        if not ps:
            continue
        src, url, exact_source = source_gate(c, e['event_id'], cutoff)
        for p in ps:
            pid = p['participant_id']
            recent = history.get(pid, [])
            recent_int = sum(1 for x in recent if x[0] and et - x[1] <= timedelta(days=30))
            values = {
                'ctx_international_flag': float(intl),
                'ctx_global_tier': tier,
                'ctx_stage_pressure': pressure,
                'ctx_recent_int_30d': float(recent_int),
            }
            for name, value in values.items():
                sidv = sid('international-context-v1', e['event_id'], pid, name)
                quality = 'EXACT' if exact_source else 'UNVERIFIABLE'
                effective = cutoff.isoformat() if exact_source else None
                c.execute('''INSERT OR REPLACE INTO match_stats
                    (stat_id,event_id,participant_id,team_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,value_text,unit,source,source_url,quality_status,confidence)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (sidv,e['event_id'],pid,pid,e['sport'],now(),effective,name,value,str(value),'context',src,url,quality,1.0 if exact_source else 0.0))
                written += 1
                if exact_source:
                    exact += 1
        history.setdefault(ps[0]['participant_id'], []).append((bool(intl), et))
        for p in ps[1:]:
            history.setdefault(p['participant_id'], []).append((bool(intl), et))
    c.commit()
    c.close()
    return {'events': len(events), 'context_rows': written, 'exact_rows': exact}


def main():
    if not DB.exists():
        raise SystemExit('database missing')
    print(json.dumps(rebuild(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
