from __future__ import annotations

"""PIT-safe participant/entity context features.

The feature builder is sport-agnostic. It consumes only participant_history rows
whose effective time and independently-proven source availability are both at or
before the prediction cutoff. It intentionally prefers missing values over any
guess, carry-forward from an unproven source, or silent identity merge.
"""

import re
import sqlite3
from bisect import bisect_right
from datetime import datetime, timezone
from typing import Dict, Iterable, Mapping, MutableMapping, Sequence


NUMERIC_ALIASES = {
    "age_years": (
        "age", "age_years", "athlete.age", "player.age", "fighter.age"
    ),
    "height_cm": (
        "height_cm", "height", "athlete.height", "player.height",
        "fighter.height"
    ),
    "weight_kg": (
        "weight_kg", "weight", "athlete.weight", "player.weight",
        "fighter.weight"
    ),
    "reach_cm": (
        "reach_cm", "reach", "athlete.reach", "player.reach",
        "fighter.reach"
    ),
    "ranking": (
        "rank", "ranking", "world_rank", "athlete.rank", "player.rank",
        "fighter.rank"
    ),
    "ranking_points": (
        "ranking_points", "rank_points", "ranking.point", "rank.point",
        "points_ranking", "player.ranking_points"
    ),
    "seed": (
        "seed", "seeding", "athlete.seed", "player.seed", "fighter.seed"
    ),
    "career_wins": (
        "career_wins", "record_wins", "wins", "fighter.career_wins",
        "player.career_wins"
    ),
    "career_losses": (
        "career_losses", "record_losses", "losses", "fighter.career_losses",
        "player.career_losses"
    ),
    "career_draws": (
        "career_draws", "record_draws", "draws", "fighter.career_draws",
        "player.career_draws"
    ),
    "rating_external": (
        "external_rating", "rating_external", "player.rating",
        "athlete.rating"
    ),
}

DOB_ALIASES = (
    "dob", "birth_date", "birthdate", "date_of_birth",
    "fighter.dob", "athlete.dob", "player.dob"
)

STANCE_ALIASES = ("stance", "fighter.stance", "athlete.stance", "player.stance")
HANDEDNESS_ALIASES = (
    "handedness", "hand", "fighter.handedness", "athlete.handedness",
    "player.handedness"
)

OUTPUT_NUMERIC = tuple(NUMERIC_ALIASES)
PROFILE_FEATURE_PREFIX = "profile"

_STATIC_NORMALIZERS = {
    "age_years": "age_years",
    "height_cm": "height_cm",
    "weight_kg": "weight_kg",
    "reach_cm": "reach_cm",
    "ranking": "ranking",
    "ranking_points": "ranking_points",
    "seed": "seed",
    "career_wins": "career_wins",
    "career_losses": "career_losses",
    "career_draws": "career_draws",
    "rating_external": "rating_external",
}


def _dt(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        x = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9_.]+", "_", str(value or "").strip().lower()).strip("_")


def _find_alias(attribute: object, aliases: Mapping[str, Sequence[str]]) -> str | None:
    n = _norm(attribute)
    for canonical, values in aliases.items():
        normalized = {_norm(v) for v in values}
        if n in normalized:
            return canonical
    return None


def _coerce_numeric(canonical: str, value_num: object, value_text: object) -> float | None:
    if value_num is not None:
        try:
            v = float(value_num)
            return v if v == v and abs(v) != float("inf") else None
        except (TypeError, ValueError):
            pass
    raw = str(value_text or "").strip()
    if not raw:
        return None

    # UFCStats-style dimensions are normalized here; other sports can already
    # persist metric values in value_num.
    if canonical == "height_cm":
        m = re.search(r"(\d+)\s*['’]\s*(\d+(?:\.\d+)?)?\s*(?:\"|in)?", raw)
        if m:
            feet = float(m.group(1))
            inches = float(m.group(2) or 0.0)
            return feet * 30.48 + inches * 2.54
    if canonical in ("weight_kg",):
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:lb|lbs|pounds)?", raw, re.I)
        if m:
            v = float(m.group(1))
            return v * 0.45359237 if re.search(r"lb|pound", raw, re.I) else v
    if canonical == "reach_cm":
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:\"|in|inch|inches)?", raw, re.I)
        if m:
            v = float(m.group(1))
            return v * 2.54 if re.search(r"\"|in|inch", raw, re.I) else v
    m = re.search(r"-?\d+(?:\.\d+)?", raw.replace(",", ""))
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


def _birth_year(value: object) -> int | None:
    raw = str(value or "")
    m = re.search(r"(19|20)\d{2}", raw)
    return int(m.group()) if m else None


def _age_from_dob(value: object, cutoff: datetime) -> float | None:
    raw = str(value or "").strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dob = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            years = (cutoff - dob).total_seconds() / (365.2425 * 86400.0)
            return round(max(0.0, years), 4)
        except ValueError:
            continue
    year = _birth_year(raw)
    if year is not None:
        return round(max(0.0, cutoff.year - year), 4)
    return None


def build_index(con: sqlite3.Connection, sport: str) -> MutableMapping[str, list]:
    """Build an immutable-in-run history index with independent PIT evidence."""
    index: MutableMapping[str, list] = {}
    try:
        rows = con.execute(
            """
            SELECT
                ph.participant_id,
                ph.attribute,
                ph.value_num,
                ph.value_text,
                ph.effective_at_utc,
                MIN(ss.source_available_at_utc) AS source_available_at_utc
              FROM participant_history ph
              JOIN source_snapshot ss
                ON ss.source=ph.source
               AND ss.source_url=ph.source_url
               AND ss.availability_status='EXACT'
               AND ss.source_available_at_utc IS NOT NULL
             WHERE ph.sport=?
               AND ph.quality_status='EXACT'
               AND ph.effective_at_utc IS NOT NULL
             GROUP BY
                ph.history_id, ph.participant_id, ph.attribute,
                ph.value_num, ph.value_text, ph.effective_at_utc
             ORDER BY ph.participant_id, ph.effective_at_utc
            """,
            (sport,),
        ).fetchall()
    except sqlite3.DatabaseError:
        return index

    for pid, attribute, value_num, value_text, effective_at, available_at in rows:
        et = _dt(effective_at)
        at = _dt(available_at)
        if not pid or et is None or at is None:
            continue
        canonical = (
            _find_alias(attribute, NUMERIC_ALIASES)
            or ("dob" if _norm(attribute) in {_norm(x) for x in DOB_ALIASES} else None)
            or ("stance" if _norm(attribute) in {_norm(x) for x in STANCE_ALIASES} else None)
            or ("handedness" if _norm(attribute) in {_norm(x) for x in HANDEDNESS_ALIASES} else None)
        )
        if canonical is None:
            continue
        index.setdefault(str(pid), []).append(
            (et.timestamp(), at.timestamp(), canonical, value_num, value_text)
        )
    return index


def features_for(
    index: Mapping[str, Sequence[tuple]],
    participant_id: str | None,
    cutoff: datetime,
) -> Dict[str, float]:
    """Return only observations fully evidenced by the supplied cutoff."""
    if not participant_id:
        return {}
    rows = index.get(str(participant_id), ())
    if not rows:
        return {}
    cutoff_ts = cutoff.timestamp()
    selected: Dict[str, tuple] = {}
    for item in rows:
        if len(item) != 5:
            continue
        effective_ts, available_ts, canonical, value_num, value_text = item
        if effective_ts <= cutoff_ts and available_ts <= cutoff_ts:
            prev = selected.get(canonical)
            if prev is None or effective_ts > prev[0] or (
                effective_ts == prev[0] and available_ts > prev[1]
            ):
                selected[canonical] = item

    out: Dict[str, float] = {}
    age = None
    for canonical, item in selected.items():
        _, _, _, value_num, value_text = item
        if canonical == "dob":
            age = _age_from_dob(value_text if value_text else value_num, cutoff)
            continue
        if canonical in _STATIC_NORMALIZERS:
            value = _coerce_numeric(canonical, value_num, value_text)
            if value is not None:
                out[f"{PROFILE_FEATURE_PREFIX}__{canonical}"] = value
        elif canonical in ("stance", "handedness"):
            raw = _norm(value_text)
            if canonical == "stance":
                out[f"{PROFILE_FEATURE_PREFIX}__stance_orthodox"] = float(raw == "orthodox")
                out[f"{PROFILE_FEATURE_PREFIX}__stance_southpaw"] = float(
                    raw in ("southpaw", "lefty")
                )
                out[f"{PROFILE_FEATURE_PREFIX}__stance_switch"] = float(
                    raw in ("switch", "switchstance")
                )
            else:
                out[f"{PROFILE_FEATURE_PREFIX}__hand_left"] = float(
                    raw in ("left", "left_handed", "southpaw")
                )
                out[f"{PROFILE_FEATURE_PREFIX}__hand_right"] = float(
                    raw in ("right", "right_handed", "orthodox")
                )
    if age is not None:
        out[f"{PROFILE_FEATURE_PREFIX}__age_years"] = float(age)
    return out


def difference_features(a: Mapping[str, float], b: Mapping[str, float]) -> Dict[str, float]:
    """Create A-B numeric differences without fabricating missing values."""
    out: Dict[str, float] = {}
    keys = sorted(set(a) | set(b))
    for key in keys:
        av = a.get(key)
        bv = b.get(key)
        if av is None or bv is None:
            continue
        try:
            out["D__" + key] = float(av) - float(bv)
        except (TypeError, ValueError):
            continue
    return out


def event_participant_features(
    con: sqlite3.Connection,
    event_id: str,
    cutoff: datetime,
) -> Dict[str, Dict[str, float]]:
    """Read exact event-level seed/role-state features when independently evidenced."""
    result: Dict[str, Dict[str, float]] = {"A": {}, "B": {}}
    try:
        rows = con.execute(
            """
            SELECT ep.side, ep.seed, ep.lineup_status, ep.effective_at_utc
              FROM event_participant ep
             WHERE ep.event_id=?
               AND ep.side IN ('A','B')
               AND ep.quality_status='EXACT'
            """,
            (event_id,),
        ).fetchall()
    except sqlite3.DatabaseError:
        return result
    cutoff_ts = cutoff.timestamp()
    for side, seed, lineup_status, effective_at in rows:
        et = _dt(effective_at)
        if et is not None and et.timestamp() > cutoff_ts:
            continue
        if seed is not None:
            try:
                result[side]["event__seed"] = float(seed)
            except (TypeError, ValueError):
                pass
        status = _norm(lineup_status)
        if status:
            result[side]["event__lineup_confirmed"] = float(
                status in ("confirmed", "starting", "starter", "active")
            )
            result[side]["event__lineup_out"] = float(
                status in ("out", "unavailable", "withdrawn")
            )
    return result
