from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    competition_type: str
    confidence: str
    rule: str


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def classify_competition(sport: str, name: str | None, stage: str | None = None) -> dict:
    """Conservatively classify an explicitly named competition/event.

    This is a discovery aid, not a PIT decision. Unknown/ambiguous names remain
    OTHER_EXPLICIT_COMPETITION or UNRESOLVED rather than being silently pooled.
    """
    s = _norm(sport)
    text = _norm(" ".join(x for x in (name, stage) if x))

    def c(kind: str, confidence: str, rule: str) -> dict:
        return {
            "competition_type": kind,
            "confidence": confidence,
            "rule": rule,
        }

    # Hard event-format rules first.
    if re.search(r"\bfriendly\b|international friendly|club friendly|friendly match|pre-season|preseason|exhibition", text):
        return c("friendly", "HIGH", "friendly/exhibition/preseason marker")
    if re.search(r"\bqualif(?:ier|ying)\b|preliminary round|play-in", text):
        return c("qualifier", "HIGH", "qualifier/preliminary/play-in marker")
    if re.search(r"showmatch|show match|all-star|all star|exhibition", text):
        return c("showmatch_or_exhibition", "HIGH", "showmatch/all-star/exhibition marker")

    if s in {"ufc", "rizin"}:
        if re.search(r"\bgrand prix\b|\bgp\b", text):
            return c("tournament_or_series", "HIGH", "Grand Prix/GP marker")
        if re.search(r"fight night|\bufc fn\b", text):
            return c("fight_night_event", "HIGH", "Fight Night marker")
        if s == "ufc" and re.search(r"\bufc\s*\d+\b", text):
            return c("numbered_event", "HIGH", "numbered UFC event marker")
        if s == "rizin" and re.search(r"rizin\s*\d+|\bnumbered\b", text):
            return c("numbered_event", "MEDIUM", "numbered RIZIN event marker")
        if re.search(r"special|super arena|landmark|year end|new year|summer", text):
            return c("special_event", "MEDIUM", "special-event naming marker")
        return c("other_explicit_event", "LOW", "named combat-sports event without reliable subtype marker")

    if s == "valorant":
        if re.search(r"\bchampions\b", text):
            return c("champions", "HIGH", "Champions marker")
        if re.search(r"\bmasters?\b", text):
            return c("masters", "HIGH", "Masters marker")
        if re.search(r"\bchallengers?\b", text):
            return c("challengers", "HIGH", "Challengers marker")
        if re.search(r"game changers|gamechangers", text):
            return c("game_changers", "HIGH", "Game Changers marker")
        if re.search(r"showmatch|show match|exhibition", text):
            return c("showmatch_or_exhibition", "HIGH", "showmatch/exhibition marker")
        if re.search(r"\b(cup|copa)\b", text):
            return c("regional_cup", "MEDIUM", "cup/copa marker")
        if re.search(r"\b(league|vct|regional|series)\b", text):
            return c("regional_league", "MEDIUM", "league/regional/VCT/series marker")
        if re.search(r"\binternational\b|global", text):
            return c("international_event", "MEDIUM", "international/global marker")
        return c("other_explicit_competition", "LOW", "named VALORANT competition without reliable subtype marker")

    # Team sports: distinguish known competition families before generic league/cup.
    if re.search(r"\b(olympic|asian games|commonwealth games|pan american games)\b", text):
        return c("major_tournament", "HIGH", "multi-sport major-games marker")
    if re.search(r"world cup|world championship|\bworlds\b", text):
        return c("world_national_team", "MEDIUM", "world-event marker")
    if re.search(r"eurobasket|fiba asia cup|asia cup|afrobasket|americup|eurovolley|volleyball nations league|vnl|world league", text):
        return c("continental_national_team", "HIGH", "continental/national-team marker")
    if re.search(r"euroleague|basketball champions league|bcl|eurocup|champions league|cev champions league|cev cup|club world championship", text):
        return c("continental_club", "HIGH", "continental club marker")
    if re.search(r"\b(cup|copa|trophy|super cup|league cup)\b", text):
        return c("domestic_cup", "MEDIUM", "cup/trophy marker")
    if re.search(r"\bleague\b", text):
        return c("domestic_league", "MEDIUM", "league marker")
    if re.search(r"championship|championships|tournament", text):
        return c("major_tournament", "LOW", "generic championship/tournament marker")

    return c("other_explicit_competition", "LOW", "no conservative subtype rule matched")
