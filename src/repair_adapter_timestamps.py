from __future__ import annotations
import json,re,sqlite3
from datetime import datetime,timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/db/sports_v45.sqlite'
UA='SevenSportResearchEngine/4.5.10-timestamp-repair'
def iso_human(s):
    s=re.sub(r'\s+',' ',str(s or '')).strip()
    for fmt in ('%B %d, %Y','%b %d, %Y','%Y-%m-%d'):
        try:return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:pass
    return None

def main():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    cols={row['name'] for row in c.execute('PRAGMA table_info(event)').fetchall()}
    if 'event_id' not in cols or 'sport' not in cols or 'event_time_utc' not in cols:
        print(json.dumps({'scanned':0,'fixed':0,'skipped':True,'reason':'event schema missing required columns'},ensure_ascii=False));c.close();return
    # Older/canonical schemas may not retain a source URL. In that case this repair is
    # intentionally a no-op: eligibility remains controlled by the PIT quality gates.
    if 'source_url' not in cols:
        print(json.dumps({'scanned':0,'fixed':0,'skipped':True,'reason':'source_url not present; PIT gate remains authoritative'},ensure_ascii=False));c.close();return
    rows=c.execute("SELECT event_id,sport,event_time_utc,source_url FROM event WHERE event_time_utc IS NULL AND sport IN ('ufc','rizin','volleyball','valorant') AND source_url IS NOT NULL AND source_url != ''").fetchall();fixed=0
    sess=requests.Session();sess.headers.update({'User-Agent':UA})
    for r in rows:
        try:
            h=sess.get(r['source_url'],timeout=20).text;s=BeautifulSoup(h,'lxml');dt=None
            if r['sport']=='ufc':
                for node in s.select('.b-list__box-list-item'):
                    t=' '.join(node.stripped_strings)
                    if 'Date:' in t:dt=iso_human(t.split('Date:',1)[1]);break
            else:
                for z in s.select('script[type="application/ld+json"]'):
                    try:
                        x=json.loads(z.string or z.get_text());items=x if isinstance(x,list) else [x]
                        for q in items:
                            if isinstance(q,dict):
                                for k in ('startDate','datePublished','dateCreated'):
                                    if q.get(k):
                                        try:
                                            v=str(q[k]).replace('Z','+00:00');d=datetime.fromisoformat(v);dt=d.astimezone(timezone.utc).isoformat() if d.tzinfo else d.replace(tzinfo=timezone.utc).isoformat();break
                                        except Exception:pass
                            if dt:break
                    except Exception:pass
                    if dt:break
            if dt:
                c.execute('UPDATE event SET event_time_utc=?,updated_at=? WHERE event_id=?',(dt,datetime.now(timezone.utc).isoformat(),r['event_id']));fixed+=1
        except Exception:pass
    c.commit();print(json.dumps({'scanned':len(rows),'fixed':fixed},ensure_ascii=False));c.close()
if __name__=='__main__':main()
