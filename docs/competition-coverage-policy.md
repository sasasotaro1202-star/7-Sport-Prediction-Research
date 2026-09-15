# Seven-Sport Competition Coverage Policy

## Objective

The production system must seek PIT-safe historical and current coverage across all seven sports, not only the main professional competitions. Coverage expansion must improve generalization without contaminating training or evaluation.

## Competition taxonomy

Every event should be classified when the source supports it:

- `competition_scope`: `club`, `national_team`, `individual`, `mixed`
- `competition_level`: `professional`, `international`, `regional`, `developmental`, `university`, `high_school`, `amateur`, `other`
- `age_category`: `senior`, `u23`, `u20`, `u18`, `junior`, `youth`, `student`, `unknown`
- `gender`: `men`, `women`, `mixed`, `unknown`
- `region`: continent/country/region where authoritative
- `season_or_year`
- `stage`: qualification/group/knockout/final/etc. when available

Do not infer a category from a team name alone. Preserve `unknown` when evidence is insufficient.

## Target coverage

For each of the seven sports, the collector/research layer should discover and evaluate available sources for:

1. Major professional leagues/tours/promotions.
2. National-team competitions and international matches.
3. World championships and world-level events.
4. Asian Games and other continental/multi-sport events where the sport is contested.
5. U18/U20/U23 and other youth/developmental competitions where reliable historical data exists.
6. University/college competitions where reliable data exists.
7. Japanese high-school competitions, including Interhigh, where reliable structured or source-backed data exists.
8. Other materially relevant regional or international competitions.

## Seven-sport handling

- Basketball: professional, national-team, FIBA/world events, Asian Games, youth/student/high-school where data quality permits.
- Volleyball: professional, national-team, world/continental events, Asian Games, youth/student/high-school where data quality permits.
- UFC: UFC plus eligible international combat-sport context only where the competition is genuinely UFC data; do not merge unrelated promotions into UFC labels.
- RIZIN: RIZIN-specific event/card history; other promotions remain separately identified unless continuity and rule compatibility are authoritative.
- Tennis: tour-level, Grand Slam, national/continental/team events, youth/junior and student events where reliable data exists.
- F1: F1 World Championship plus historically comparable official FIA/F1 competition data; do not silently merge junior formula categories into F1.
- Valorant: VCT/international/regional events, qualifying and developmental circuits, with patch/roster/tournament-stage timing preserved.

## Modeling policy

Professional, national-team, youth, university, and high-school data must not be blindly pooled. The modeling layer should use explicit competition/age/context features or separate strata/models when OOS evidence supports that choice. A broader dataset is not automatically a better dataset.

## PIT requirements

For every feature used for prediction, retain or reconstruct an evidence-backed `available_at`/publication timestamp. Historical current-state pages must not be treated as historical truth. If a source cannot establish when information became available, it may remain useful for outcome/history coverage but must not silently become a pre-event feature.

## Quality gates

Coverage expansion must not weaken release gates. New sources require schema, duplicate, timestamp, provenance, outcome, and PIT checks. Missing or ambiguous competition classification is recorded rather than guessed. Unsupported or unverified data is excluded from model features and logged with a reason.

## Efficiency

Use source registries, cache-first retrieval, incremental updates, deduplication, and source-level freshness checks. Do not repeatedly download unchanged historical datasets. Prefer authoritative structured sources, then independent cross-checks.

## Completion criterion

A competition category is considered covered only when the repository has evidence of source discovery, parsing/ingestion, classification, PIT treatment, and validation. A policy document or search hit alone is not evidence of populated production data.
