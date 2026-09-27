from __future__ import annotations

from src.competition_scope_classifier import classify_competition


def main() -> int:
    cases = [
        ("basketball", "B.League", "domestic_league", "MEDIUM"),
        ("basketball", "Emperor's Cup", "domestic_cup", "MEDIUM"),
        ("basketball", "EuroLeague", "continental_club", "HIGH"),
        ("basketball", "FIBA Asia Cup Qualifiers", "qualifier", "HIGH"),
        ("basketball", "Asian Games", "major_tournament", "HIGH"),
        ("basketball", "Japan vs Korea Friendly", "friendly", "HIGH"),
        ("volleyball", "VNL", "continental_national_team", "HIGH"),
        ("volleyball", "CEV Champions League", "continental_club", "HIGH"),
        ("ufc", "UFC 322", "numbered_event", "HIGH"),
        ("ufc", "UFC Fight Night", "fight_night_event", "HIGH"),
        ("rizin", "RIZIN Landmark 12", "special_event", "MEDIUM"),
        ("rizin", "RIZIN Grand Prix", "tournament_or_series", "HIGH"),
        ("valorant", "VCT Masters Toronto", "masters", "HIGH"),
        ("valorant", "VCT Champions", "champions", "HIGH"),
        ("valorant", "Game Changers Pacific", "game_changers", "HIGH"),
        ("valorant", "Regional Cup", "regional_cup", "MEDIUM"),
        ("basketball", "Unknown Invitational", "other_explicit_competition", "LOW"),
    ]
    for sport, name, expected_type, expected_conf in cases:
        got = classify_competition(sport, name)
        assert got["competition_type"] == expected_type, (sport, name, got)
        assert got["confidence"] == expected_conf, (sport, name, got)

    # Stage text can expose the qualifier even when the competition name itself
    # is generic.
    got = classify_competition("basketball", "FIBA Asia Cup", "Qualifying")
    assert got["competition_type"] == "qualifier"

    print("COMPETITION_CLASSIFIER=PASS")
    print("COMPETITION_CLASSIFIER_CONSERVATIVE_FALLBACK=PASS")
    print("COMPETITION_CLASSIFIER_STAGE_RULE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
