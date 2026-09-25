from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def publication_time(html):
    """Extract only a full explicit publication timestamp from the official page.
    Date-only publication values are not sufficient for the strict PIT clock.
    Retrieval time and dateModified are intentionally not accepted as PIT evidence.
    """
    patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        m = re.search(pattern, html or "", re.I)
        if m:
            raw = m.group(1)
            if not re.search(r"(?:T|\s)\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?", raw):
                continue
            value = iso(raw)
            if value:
                return value
    return None


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


def _rizin_archive_urls(base, max_archive_pages):
    """Return a bounded official result-archive page set."""
    cap = max(1, int(max_archive_pages))
    return [base if page == 1 else f"{base}?p={page}" for page in range(1, cap + 1)]


def _rizin_result_urls(html, base_url):
    """Discover canonical result pages first, then keep a de-duplicated fallback."""
    prioritized = []
    fallback = []
    anchor_re = re.compile(
        r'<a\b[^>]+(?:href|data-href)=["\']([^"\']*/_ct/\d+)["\'][^>]*>(.*?)</a>',
        re.I | re.S,
    )
    for href, inner in anchor_re.findall(html or ""):
        url = urljoin(base_url, href)
        label = clean(html_text(inner))
        (prioritized if "試合結果一覧" in label else fallback).append(url)

    candidates = prioritized + fallback
    candidates.extend(re.findall(r"https?://jp\.rizinff\.com/_ct/\d+", html or ""))
    candidates.extend(re.findall(r"(/_ct/\d+)", html or ""))
    out = []
    seen = set()
    for raw_url in candidates:
        url = urljoin(base_url, raw_url)
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _rizin_is_event_result_page(raw):
    """Accept only pages whose primary H1 is the event-level result list.
    
    Individual fight reports also contain a breadcrumb link to 「試合結果一覧」,
    so searching the whole text is insufficient and can duplicate every bout.
    """
    headings = re.findall(r"<h1\\b[^>]*>(.*?)</h1>", raw or "", re.I | re.S)
    for heading in headings:
        title = clean(re.sub(r"<[^>]+>", " ", heading))
        if "試合結果一覧" in title:
            return True
    return False


def _rizin_event_date(plain):
    """Parse the event/article date without accepting template/future footer dates."""
    text = clean(plain)
    candidates = []
    patterns = (
        r"(20\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})",
        r"(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})",
    )
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            try:
                year, month, day = map(int, m.groups())
                if year < 2010 or year > datetime.now(timezone.utc).year + 1:
                    continue
                dt = datetime(year, month, day, tzinfo=timezone.utc)
                if dt.date().isoformat() == "2000-01-01":
                    continue
                candidates.append(dt)
            except ValueError:
                continue
    if not candidates:
        return None
    return candidates[0].isoformat()

def _rizin_detail_fetch(hurl):
    try:
        raw, retrieved = http(hurl)
        plain = html_text(raw)
        if "（WIN）" not in plain and "(WIN)" not in plain and "WIN" not in plain:
            m_id = re.search(r"/_ct/(\d+)", hurl)
            if m_id:
                amp_url = f"https://jp.rizinff.com/_amp/_ct/{m_id.group(1)}"
                try:
                    amp_raw, amp_retrieved = http(amp_url)
                    amp_plain = html_text(amp_raw)
                    if len(amp_plain) > len(plain) and ("（WIN）" in amp_plain or "(WIN)" in amp_plain or "WIN" in amp_plain):
                        raw, retrieved, plain = amp_raw, amp_retrieved, amp_plain
                        hurl = amp_url
                except Exception:
                    pass
        return hurl, raw, retrieved, plain
    except Exception:
        return None


def backfill_rizin(c, max_pages=150):
    # Crawl the official paginated result archive before fetching detail articles.
    index, _ = http(RIZIN_TAG)
    archive_cap = min(24, max(6, (int(max_pages) + 7) // 8))
    archive_urls = _rizin_archive_urls(RIZIN_TAG, archive_cap)
    archive_html = {RIZIN_TAG: index}
    for page_url in archive_urls[1:]:
        try:
            html, _ = http(page_url)
            if "/_ct/" not in html:
                break
            archive_html[page_url] = html
        except Exception:
            break

    urls = []
    seen_urls = set()
    for page_url, html in archive_html.items():
        for url in _rizin_result_urls(html, page_url):
            if url not in seen_urls:
                seen_urls.add(url)
                urls.append(url)
    detail_urls = urls[:max(1, int(max_pages))]

    added = 0
    labeled = 0
    exact_snapshots = 0
    workers = max(1, min(6, int(__import__("os").getenv("RIZIN_DETAIL_WORKERS", "6"))))
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_rizin_detail_fetch, u) for u in detail_urls]
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    for url, raw, retrieved, plain in results:
        # Individual fight-report pages also contain WIN/LOSE patterns and event
        # footer dates. They are not the canonical event result-list source and
        # must never be reinterpreted as an event-level result feed.
        if not _rizin_is_event_result_page(raw):
            continue
        dm = re.search(r"(20\d{2})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})", plain)
        et = iso("-".join(dm.groups())) if dm else None
        tm = re.search(r"([^\n]{2,100})試合結果(?:一覧)?", plain)
        title = clean(tm.group(1)) if tm else url
        matches = list(re.finditer(r"(?:\(WIN\)|（WIN）|WIN)\s+(.{1,80}?)\s+vs\.?\s+(.{1,80}?)\s+(?:\(LOSE\)|（LOSE）|LOSE)", plain, re.I))
        matches += list(re.finditer(r"(?:\(LOSE\)|（LOSE）|LOSE)\s+(.{1,80}?)\s+vs\.?\s+(.{1,80}?)\s+(?:\(WIN\)|（WIN）|WIN)", plain, re.I))
        seen = set()
        for m in matches:
            left_marker = "WIN" if re.match(r"(?:\(WIN\)|（WIN）|WIN)\s+", m.group(0), re.I) else "LOSE"
            a, b = clean(m.group(1)), clean(m.group(2))
            if not a or not b or a == b or len(a) > 80 or len(b) > 80:
                continue
            key = (a, b, et, url)
            if key in seen:
                continue
            seen.add(key)
            eid = upsert_event(c, "rizin", f"{a} vs {b}", et, "jp.rizinff.com", url, "COMPLETED",
                               competition=title, season=str(et)[:4] if et else None)
            p1 = upsert_participant(c, "rizin", a, "fighter")
            p2 = upsert_participant(c, "rizin", b, "fighter")
            upsert_ep(c, eid, p1, p1, "A", "fight", "jp.rizinff.com", url)
            upsert_ep(c, eid, p2, p2, "B", "fight", "jp.rizinff.com", url)
            side = "A" if "WIN" in left_marker.upper() else "B"
            add_outcome(c, "rizin", eid, p1, p2, side, url)
            labeled += 1
            added += 1
        if matches:
            payload_hash = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
            add_snapshot(c, "rizin", "jp.rizinff.com", url, retrieved, et, payload_hash, "UNVERIFIABLE")
            published_at = publication_time(raw)
            if published_at and et:
                published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(timezone.utc)
                event_dt = datetime.fromisoformat(et.replace("Z", "+00:00")).astimezone(timezone.utc)
                if published_dt <= event_dt - __import__("datetime").timedelta(minutes=60):
                    snapshot_id = sid("rizin", "jp.rizinff.com", url, payload_hash)
                    c.execute(
                        """UPDATE source_snapshot
                           SET source_available_at_utc=?, availability_status='EXACT', provenance_json=?
                           WHERE snapshot_id=?""",
                        (published_at, json.dumps({
                            "sport": "rizin",
                            "parser": "v4.5.17-rizin-archive-pit",
                            "evidence": "official_page_datePublished",
                            "publication_time_utc": published_at,
                            "pit_rule": "publication_at_or_before_event_minus_60m",
                        }, ensure_ascii=False), snapshot_id),
                    )
                    exact_snapshots += 1

    # Persisted-shape diagnostics: distinguish collection volume from researchable
    # fight rows. These counts are observational only and do not relax PIT gates.
    persisted_events = c.execute(
        "SELECT COUNT(*) FROM event WHERE sport='rizin'"
    ).fetchone()[0]
    paired_events = c.execute(
        """SELECT COUNT(*)
             FROM event e
             JOIN event_participant a ON a.event_id=e.event_id AND a.side='A'
             JOIN event_participant b ON b.event_id=e.event_id AND b.side='B'
            WHERE e.sport='rizin'"""
    ).fetchone()[0]
    verified_outcome_events = c.execute(
        """SELECT COUNT(*)
             FROM event_outcome o
            WHERE o.sport='rizin' AND o.outcome_status='VERIFIED'
              AND o.outcome IN ('A','B')"""
    ).fetchone()[0]
    paired_verified_events = c.execute(
        """SELECT COUNT(*)
             FROM event e
             JOIN event_participant a ON a.event_id=e.event_id AND a.side='A'
             JOIN event_participant b ON b.event_id=e.event_id AND b.side='B'
             JOIN event_outcome o ON o.event_id=e.event_id
            WHERE e.sport='rizin' AND o.outcome_status='VERIFIED'
              AND o.outcome IN ('A','B')"""
    ).fetchone()[0]
    unique_event_dates = c.execute(
        "SELECT COUNT(DISTINCT substr(event_time_utc,1,10)) FROM event WHERE sport='rizin' AND event_time_utc IS NOT NULL"
    ).fetchone()[0]
    date_rows = c.execute(
        """SELECT substr(event_time_utc,1,10) AS event_date, COUNT(*) AS n
             FROM event
            WHERE sport='rizin' AND event_time_utc IS NOT NULL
            GROUP BY substr(event_time_utc,1,10)
            ORDER BY event_date ASC"""
    ).fetchall()
    name_rows = c.execute(
        """SELECT name, substr(event_time_utc,1,10) AS event_date, COUNT(*) AS n
             FROM event
            WHERE sport='rizin' AND event_time_utc IS NOT NULL
            GROUP BY name, substr(event_time_utc,1,10)
            ORDER BY event_date ASC, name ASC
            LIMIT 20"""
    ).fetchall()
    coverage = {
        "status": "PASS" if added > 0 else "DEFERRED",

        "sport": "rizin",
        "archive_pages_scanned": len(archive_html),
        "result_article_urls": len(detail_urls),
        "events_added": added,
        "labeled_bouts": labeled,
        "exact_pit_snapshots": exact_snapshots,
        "persisted_events": int(persisted_events),
        "paired_events": int(paired_events),
        "verified_outcome_events": int(verified_outcome_events),
        "paired_verified_events": int(paired_verified_events),
        "unique_event_dates": int(unique_event_dates),
        "event_date_counts": [{"date": str(d), "events": int(n)} for d, n in date_rows],
        "sample_event_names": [{"name": str(nm), "date": str(d), "events": int(n)} for nm, d, n in name_rows],
        "reason": None if added > 0 else "official_rizin_result_archive_returned_no_parseable_result_records",
    }
    out = ROOT / "results" / "v45" / "rizin_coverage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    return added, labeled, len(detail_urls)


def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--sport",choices=("basketball","rizin"),required=True); a=ap.parse_args()
    c=connect(); report={"version":"v4.5.17-rizin-archive-pit","sport":a.sport,"timestamp_utc":utcnow(),"added":{},"warnings":[]}
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
