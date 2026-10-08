from __future__ import annotations

"""Lightweight canonical research policy shared by PIT/OOS components.

This module intentionally contains only immutable sport/stat policy so PIT replay
builders do not need to import the full ML training stack merely to resolve the
feature policy.
"""

SPORTS = (
    "valorant",
    "basketball",
    "volleyball",
    "tennis",
    "ufc",
    "rizin",
    "f1",
    "rugby",
    "boxing",
)

POLICY = {
    "valorant": ("rating", "acs", "adr", "kast", "k_d", "fk_fd"),
    "basketball": (
        "points",
        "rebounds",
        "assists",
        "steals",
        "blocks",
        "turnovers",
        "fieldGoalPct",
        "threePointPct",
        "freeThrowPct",
    ),
    "volleyball": ("attack", "serve", "receive", "block", "error", "sideout"),
    "tennis": (
        "ace",
        "double_fault",
        "first_serve",
        "first_serve_points_won",
        "break_points_saved",
        "break_points_won",
    ),
    "ufc": ("sig_str", "takedown", "td_pct", "sub_attempts", "control_time"),
    "rizin": ("sig_str", "takedown", "td_pct", "sub_attempts", "control_time"),
    "f1": (),
    "rugby": (),
    "boxing": (),
}
