#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "results/research/bleague_public_availability_evidence.json"


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main() -> None:
    x = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    assert x["status"] == "RESEARCH_EVIDENCE_ONLY"
    assert x["strict_pit_usable"] is False
    assert x["revision_evidence"]["file"] == "inst/extdata/games_summary_202021.csv"

    rev = x["revision_evidence"]
    assert rev["revision_sha"] == "42c621a5437228a4d5a796f62116bee5cc44dce2"
    assert rev["revision_commit_timestamp_utc"] == "2021-04-13T23:29:05Z"
    assert rev["next_file_touch_sha"] == "64cba9d4693646b3365805da04ad9f8779e5233c"
    assert rev["next_file_touch_timestamp_utc"] == "2021-05-11T13:51:31Z"
    assert rev["no_intervening_file_touch_between_revision_and_independent_publication"] is True

    ev = x["evidence"][0]
    assert ev["source_url"] == "https://rnsr0371.boy.jp/2021/04/19/simulation_chiba202021/"
    assert ev["published_on"] == "2021-04-19"
    assert ev["referenced_files"] == [
        "inst/extdata/games_summary_202021.csv",
        "inst/extdata/teams.csv",
    ]

    bound = rev["public_availability_bound"]
    assert bound["precision"] == "DATE_ONLY"
    assert bound["latest_safe_utc"] == "2021-04-19T23:59:59Z"
    assert bound["semantics"] == "conservative_latest_possible_publication_time"
    assert ev["revision_evidence"]["exact_revision_sha"] == rev["revision_sha"]
    assert ev["revision_evidence"]["pit_status"] == "CANDIDATE_DATE_BOUND_NOT_YET_WIRED"

    # The provenance chain must be chronological and the safe bound may never
    # be earlier than either the exact revision commit or the publication date.
    assert parse_utc(rev["revision_commit_timestamp_utc"]) <= parse_utc(bound["latest_safe_utc"])
    assert parse_utc(rev["next_file_touch_timestamp_utc"]) > parse_utc(bound["latest_safe_utc"])

    print("BLEAGUER_PUBLIC_AVAILABILITY_EVIDENCE=PASS")


if __name__ == "__main__":
    main()
