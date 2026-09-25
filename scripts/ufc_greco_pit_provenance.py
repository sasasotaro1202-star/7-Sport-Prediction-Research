from __future__ import annotations

import csv
import io
import json
import subprocess
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


RESULTS_FILE = "ufc_fight_results.csv"
EVENTS_FILE = "ufc_event_details.csv"
OUT = Path("results/ufc_greco_pit_provenance.json")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def parse_csv_at(commit: str, path: str) -> list[dict[str, str]]:
    raw = git("show", f"{commit}:{path}")
    return list(csv.DictReader(io.StringIO(raw)))


def parse_commit_time(commit: str) -> datetime:
    raw = git("show", "-s", "--format=%cI", commit).strip()
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_event_date(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def first_seen_index(commits: list[str]) -> tuple[dict[str, datetime], dict[str, datetime]]:
    first_bout: dict[str, datetime] = {}
    first_event: dict[str, datetime] = {}
    for commit in commits:
        ts = parse_commit_time(commit)
        results = parse_csv_at(commit, RESULTS_FILE)
        for row in results:
            event = (row.get("EVENT") or "").strip()
            bout = (row.get("BOUT") or "").strip()
            if not event or not bout:
                continue
            key = event + "\t" + bout
            first_bout.setdefault(key, ts)
        events = parse_csv_at(commit, EVENTS_FILE)
        for row in events:
            event = (row.get("EVENT") or "").strip()
            if event:
                first_event.setdefault(event, ts)
    return first_bout, first_event


def main() -> int:
    commits = git("log", "--reverse", "--format=%H", "--follow", "--", RESULTS_FILE).splitlines()
    if not commits:
        raise SystemExit("no historical commits found")
    first_bout, first_event = first_seen_index(commits)

    current_events = parse_csv_at("HEAD", EVENTS_FILE)
    event_date = {
        (r.get("EVENT") or "").strip(): parse_event_date(r.get("DATE", ""))
        for r in current_events
        if (r.get("EVENT") or "").strip()
    }

    total = with_event_date = before_event = at_or_after_event = unknown = 0
    examples = []
    for key, seen_at in first_bout.items():
        total += 1
        event, _bout = key.split("\t", 1)
        when = event_date.get(event)
        if when is None:
            unknown += 1
            continue
        with_event_date += 1
        if seen_at < when:
            before_event += 1
        else:
            at_or_after_event += 1
        if len(examples) < 10 and not seen_at < when:
            examples.append({
                "event": event,
                "bout": _bout,
                "first_seen_at_utc": seen_at.isoformat(),
                "event_date_utc": when.isoformat(),
            })

    report = OrderedDict([
        ("schema_version", 1),
        ("source_repository", "Greco1899/scrape_ufc_stats"),
        ("source_head", git("rev-parse", "HEAD").strip()),
        ("history_commits_examined", len(commits)),
        ("history_start_commit", commits[0]),
        ("history_end_commit", commits[-1]),
        ("unique_bouts_first_seen", total),
        ("bouts_with_parseable_event_date", with_event_date),
        ("first_seen_before_event_date", before_event),
        ("first_seen_at_or_after_event_date", at_or_after_event),
        ("event_date_unknown", unknown),
        ("before_event_date_rate", (before_event / with_event_date) if with_event_date else None),
        ("non_pit_evidence_rate_upper_bound", (at_or_after_event / with_event_date) if with_event_date else None),
        ("pit_policy", "research_only; first Git appearance is a conservative upper bound on source availability"),
        ("prediction_cutoff_policy", "event_date_utc_minus_60_minutes; comparison is conservative because source exposes date but not fight start time"),
        ("unknown_is_fail_closed", True),
        ("examples_after_event_date", examples),
    ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
