"""Live CI smoke test for the public WTA schedule endpoint.

This verifies the external source path and response shape only. It does not
mark historical source availability as PIT-safe.
"""
from datetime import datetime, timezone
import requests

BASE = "https://api.wtatennis.com/tennis"
YEAR = datetime.now(timezone.utc).year

def get_json(url):
    r = requests.get(
        url,
        headers={"User-Agent": "SevenSportResearchEngine/4.5.10"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise AssertionError(f"unexpected JSON root: {type(data).__name__}")
    return data

def main():
    rows = []
    page_count = 0
    for page in range(8):
        data = get_json(f"{BASE}/tournaments?page={page}&pageSize=100")
        page_rows = data.get("content")
        assert isinstance(page_rows, list), "WTA tournament response missing content[]"
        if not page_rows:
            break
        rows.extend(page_rows)
        page_count += 1
        page_info = data.get("pageInfo")
        num_pages = page_info.get("numPages") if isinstance(page_info, dict) else None
        if isinstance(num_pages, int) and page + 1 >= num_pages:
            break

    assert rows, "WTA tournament response is empty"

    current = []
    for t in rows:
        if not isinstance(t, dict):
            continue
        tg = t.get("tournamentGroup") or {}
        gid = tg.get("id") or t.get("tournamentGroupId") or t.get("groupId")
        year = t.get("year") or t.get("seasonYear")
        if gid and str(year) == str(YEAR):
            current.append((str(gid), str(year)))

    assert current, f"no current-year tournaments found in first {page_count} pages; year={YEAR}"

    gid, year = current[0]
    match_data = get_json(f"{BASE}/tournaments/{gid}/{year}/matches")
    matches = match_data.get("matches")
    if not isinstance(matches, list):
        matches = match_data.get("content")
    assert isinstance(matches, list), "WTA tournament match response missing matches/content[]"

    print({
        "status": "PASS",
        "year": YEAR,
        "tournament_rows_scanned": len(rows),
        "tournament_pages_scanned": page_count,
        "current_year_tournaments_scanned": len(current),
        "probe_group_id": gid,
        "probe_match_rows": len(matches),
        "pit_policy": "UNVERIFIABLE_for_historical_publication_timing",
    })

if __name__ == "__main__":
    main()
