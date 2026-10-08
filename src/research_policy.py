from __future__ import annotations

"""Immutable lightweight sport/stat policy for PIT and research components.

This module deliberately has no ML/runtime dependencies. It is safe to import
from PIT replay builders that run before candidate-model environments exist.
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
        "points", "rebounds", "assists", "steals", "blocks", "turnovers",
        "fieldGoalPct", "threePointPct", "freeThrowPct",
    ),
    "volleyball": ("attack", "serve", "receive", "block", "error", "sideout"),
    "tennis": (
        "ace", "double_fault", "first_serve", "first_serve_points_won",
        "break_points_saved", "break_points_won",
    ),
    "ufc": ("sig_str", "takedown", "td_pct", "sub_attempts", "control_time"),
    "rizin": ("sig_str", "takedown", "td_pct", "sub_attempts", "control_time"),
    "f1": (),
    "rugby": (),
    "boxing": (),
}
