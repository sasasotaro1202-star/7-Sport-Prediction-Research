from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import add_snapshot, add_stat, upsert_ep, upsert_event, upsert_participant

ROOT = Path(__file__).resolve().parents[1]
NBA_GAMES = "https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba/nba_games_in_data_repo.csv"
WNBA_GAMES = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_wnba_schedules/wnba_games_in_data_repo.csv"
FIBA_2019 = "https://raw.githubusercontent.com/gkaramanis/FIBA-Basketbal-World-Cup/master/data/FIBA-WBC19-results.csv"
RIZIN_TAG = "https://jp.rizinff.com/_tags/%E8%A9%A6%E5%90%88%E7%B5%90%E6%9E%9C"


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def iso(v):
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def sid(*values):
    return hashlib.sha256("|".join("" if v is None else str(v) for v in values).encode()).hexdigest()[:32]


def http(url, timeout=45):
    r = requests.get(url, headers={"User-Agent": "SevenSportResearchEngine/4.5.16"}, timeout=timeout)
    r.raise_for_status()
    return r.text, utcnow()


def first(keys, *names):
    for n in names:
        if clean(keys.get(n)):
            return clean(keys[n])
    return ""


def infer(keys, side, kind):
    # Schema drift guard: identify semantic columns instead of depending on one
    # provider spelling. Never use score/id columns as participant names.
    items = list(keys.items())
    if kind == "name":
        exact = first(keys,
            f"{side}_team_name", f"{side}_team_display_name", f"{side}_team",
            f"{side}_name", f"{side}_team_full_name", f"{side}_team_short_name",
            "home_team_name" if side == "home" else "away_team_name")
        if exact:
            return exact
        for k, v in items:
            lk = k.lower()
            if side in lk and any(t in lk for t in ("team_name", "teamname", "team_display", "team_full", "team_short")) and not any(t in lk for t in ("score", "id", "code")):
                if clean(v):
                    return clean(v)
    elif kind == "score":
        exact = first(keys, f"{side}_score", f"{side}_team_score", f"{side}_points", f"{side}_team_points")
        if exact:
            return exact
        for k, v in items:
            lk = k.lower()
            if side in lk and any(t in lk for t in ("score", "points", "pts")) and "id" not in lk:
                if clean(v):
                    return clean(v)
    return ""


def add_outcome(c, sport, eid, p1, p2, side, url):
    c.execute("""INSERT OR REPLACE INTO event_outcome
        (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,
         outcome_status,source,source_url,observed_at_utc,quality_status,reason)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, sport, p1, p2, side, None, None, "VERIFIED", "hardened_public_history", url,
         utcnow(), "PIT_REQUIRES_REPLAY", "Historical label; excluded from pre-event features until PIT replay passes."))


def backfill_csv(c, url, competition):
    raw, retrieved = http(url)
    rows = list(csv.DictReader(io.StringIO(raw)))
    added = 0
    for row in rows:
        keys = {str(k).strip().lower(): v for k, v in row.items()}
        home = infer(keys, "home", "name")
        away = infer(keys, "away", "name") or infer(keys, "visitor", "name")
        if not home or not away or home == away:
            continue
        date = first(keys, "game_date", "date", "start_date", "start_time", "game_datetime", "game_et", "game_time")
        if not date:
            for k, v in keys.items():
                if any(t in k for t in ("game_date", "start_date", "game_time", "start_time")) and clean(v):
                    date = clean(v); break
        et = iso(date)
        eid = upsert_event(c, "basketball", f"{home} vs {away}", et, "hardened-public-dataset", url, "COMPLETED", competition=competition, season=str(et)[:4] if et else None)
        p1 = upsert_participant(c, "basketball", home, "team")
        p2 = upsert_participant(c, "basketball", away, "team")
        upsert_ep(c, eid, p1, p1, "A", "match", "hardened-public-dataset", url)
        upsert_ep(c, eid, p2, p2, "B", "match", "hardened-public-dataset", url)
        hs, aws = infer(keys, "home", "score"), infer(keys, "away", "score") or infer(keys, "visitor", "score")
        try:
            hscore, ascore = float(hs), float(aws)
        except Exception:
            hscore = ascore = None
        if hscore is not None and ascore is not None:
            side = "A" if hscore > ascore else "B" if ascore > hscore else "DRAW"
            add_outcome(c, "basketball", eid, p1, p2, side, url)
            add_stat(c, eid, p1, p1, "basketball", "score.final", hscore, str(hscore), "hardened-public-dataset", url)
            add_stat(c, eid, p2, p2, "basketball", "score.final", ascore, str(ascore), "hardened-public-dataset", url)
        added += 1
    add_snapshot(c, "basketball", "hardened-public-dataset", url, retrieved, None,
                 hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest(), "UNVERIFIABLE")
    return added, len(rows)


def html_text(raw):
    # RIZIN result pages may expose the result list primarily through
    # OpenGraph/meta descriptions while the visible body is client-rendered.
    # Preserve those semantic metadata fields before stripping HTML.
    meta_parts = []
    for m in re.finditer(
        r"<meta\b[^>]+(?:name|property)=[\"\'](?:description|og:description)[\"\'][^>]*>",
        raw, flags=re.I | re.S,
    ):
        tag = m.group(0)
        cm = re.search(r"content=[\"\'](.*?)[\"\']", tag, flags=re.I | re.S)
        if cm:
            meta_parts.append(cm.group(1))
    raw_body = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw_body = re.sub(r"<style[^>]*>.*?</style>", " ", raw_body, flags=re.I | re.S)
    raw_body = re.sub(r"<[^>]+>", " ", raw_body)
    raw_body = raw_body.replace("&nbsp;", " ").replace("&amp;", "&")
    return clean(" ".join(meta_parts) + " " + raw_body)


def backfill_rizin(c, max_pages=150):
    index, _ = http(RIZIN_TAG)
    urls = set(re.findall(r"https?://jp\.rizinff\.com/_ct/\d+", index))
    urls.update(urljoin(RIZIN_TAG, x) for x in re.findall(r"(?:href|data-href)=[\"']([^\"']*/_ct/\d+)[\"']", index, re.I))
    urls.update(urljoin(RIZIN_TAG, x) for x in re.findall(r"(/_ct/\d+)", index))
    added = 0; labeled = 0
    for url in sorted(urls)[:max_pages]:
        try:
            raw, retrieved = http(url)
        except Exception:
            continue
        plain = html_text(raw)
        dm = re.search(r"(20\d{2})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})", plain)
        et = iso("-".join(dm.groups())) if dm else None
        tm = re.search(r"([^\n]{2,100})試合結果(?:一覧)?", plain)
        title = clean(tm.group(1)) if tm else url
        # This matches the actual official page representation, including the
        # HTML-stripped '(WIN) A vs B (LOSE)' form observed on RIZIN result pages.
        matches = list(re.finditer(r"(\(WIN\)|WIN)\s+(.{1,80}?)\s+vs\.?\s+(.{1,80}?)\s+(\(LOSE\)|LOSE)", plain, re.I))
        matches += list(re.finditer(r"(\(LOSE\)|LOSE)\s+(.{1,80}?)\s+vs\.?\s+(.{1,80}?)\s+(\(WIN\)|WIN)", plain, re.I))
        seen = set()
        for m in matches:
            left_marker, a, b, right_marker = m.group(1), clean(m.group(2)), clean(m.group(3)), m.group(4)
            a = re.sub(r"\s+", " ", a); b = re.sub(r"\s+", " ", b)
            if not a or not b or a == b or len(a) > 80 or len(b) > 80: continue
            key=(a,b,et,url)
            if key in seen: continue
            seen.add(key)
            eid=upsert_event(c,"rizin",f"{a} vs {b}",et,"jp.rizinff.com",url,"COMPLETED",competition=title,season=str(et)[:4] if et else None)
            p1=upsert_participant(c,"rizin",a,"fighter"); p2=upsert_participant(c,"rizin",b,"fighter")
            upsert_ep(c,eid,p1,p1,"A","fight","jp.rizinff.com",url); upsert_ep(c,eid,p2,p2,"B","fight","jp.rizinff.com",url)
            side="A" if "WIN" in left_marker.upper() else "B"
            add_outcome(c,"rizin",eid,p1,p2,side,url); labeled += 1; added += 1
        if matches:
            add_snapshot(c,"rizin","jp.rizinff.com",url,retrieved,et,hashlib.sha256(raw.encode("utf-8","ignore")).hexdigest(),"UNVERIFIABLE")
    return added, labeled, len(urls)


def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--sport",choices=("basketball","rizin"),required=True); a=ap.parse_args()
    c=connect(); report={"version":"v4.5.16-hardened","sport":a.sport,"timestamp_utc":utcnow(),"added":{},"warnings":[]}
    try:
        if a.sport=="basketball":
            for name,url in (("nba",NBA_GAMES),("wnba",WNBA_GAMES),("fiba_2019",FIBA_2019)):
                try: report["added"][name]=backfill_csv(c,url,name.upper())
                except Exception as e: report["warnings"].append({"source":name,"error":repr(e)})
        else:
            try: report["added"]["rizin"]=backfill_rizin(c)
            except Exception as e: report["warnings"].append({"source":"rizin","error":repr(e)})
        c.commit()
    finally: c.close()
    out=ROOT/"results"/f"hardened_public_history_{a.sport}.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
