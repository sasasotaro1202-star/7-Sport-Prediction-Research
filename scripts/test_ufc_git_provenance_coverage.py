from __future__ import annotations

from src.ufc_git_provenance_coverage import _added_event_names, _norm_event, _parse_timestamp


def test_event_normalization_is_stable():
    assert _norm_event("  UFC 331: Van   vs. Pantoja 2 ") == "ufc 331: van vs. pantoja 2"


def test_added_event_names_reads_only_added_csv_rows():
    diff = """diff --git a/ufc_fight_stats.csv b/ufc_fight_stats.csv
--- a/ufc_fight_stats.csv
+++ b/ufc_fight_stats.csv
@@ -1,2 +1,4 @@
 EVENT,BOUT,ROUND,FIGHTER
+UFC A,A vs B,Round 1,A
+UFC A,A vs B,Round 1,B
-UFC OLD,X vs Y,Round 1,X
diff --git a/ufc_fighter_details.csv b/ufc_fighter_details.csv
--- a/ufc_fighter_details.csv
+++ b/ufc_fighter_details.csv
@@ -1 +1,2 @@
+SHOULD NOT COUNT,foo
 """
    assert _added_event_names(diff) == {"UFC A"}


def test_timestamp_without_zone_is_treated_as_utc():
    dt = _parse_timestamp("2026-09-24T18:03:28")
    assert dt.isoformat() == "2026-09-24T18:03:28+00:00"


if __name__ == "__main__":
    test_event_normalization_is_stable()
    test_added_event_names_reads_only_added_csv_rows()
    test_timestamp_without_zone_is_treated_as_utc()
