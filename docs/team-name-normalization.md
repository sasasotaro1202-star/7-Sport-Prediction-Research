# Team-name normalization and identity policy

## Purpose

Team names must be human-readable in predictions while preserving the source value for auditability. A spelling variation must never create a false new team, and two different teams must never be merged merely because their names look similar.

## Required representation

Every team-facing prediction record should preserve:

- `team_id`: stable internal identity
- `canonical_name`: the display name used in predictions
- `raw_name`: exact source-provided name
- `source` / `source_url`: provenance
- `effective_at_utc`: when the identity/name was valid
- `quality_status`: identity confidence/state

The existing database already separates stable `team_id` from `team.canonical_name` and stores team history separately. Do not replace this with a single free-text team name.

## Normalization rules

1. Normalize Unicode, whitespace, punctuation, and harmless casing differences before matching.
2. Remove only source-specific presentation noise (for example unnecessary separators or duplicated whitespace).
3. Maintain an explicit alias map for verified abbreviations, historical names, sponsor-name variants, and source-specific spellings.
4. Never merge teams using fuzzy similarity alone.
5. A fuzzy match may create a `REVIEW_REQUIRED` candidate, but must not silently change identity.
6. Team relocations, franchise changes, mergers, reserve/academy squads, national teams, youth teams, and similarly named organizations must remain distinct unless authoritative evidence proves continuity.
7. Do not infer identity from a current website page when reconstructing historical data; identity resolution must respect the historical observation time.
8. Keep raw source names unchanged for audit/debugging.

## Prediction display

The user-facing prediction should show the canonical team name, not an opaque ID or raw source abbreviation. When useful, show the source alias in a secondary field, never as the primary prediction label.

Example:

`Los Angeles Lakers` — canonical display name
`LAL` — source alias
`team_id=...` — internal identity

## Quality gates

Team identity processing should fail closed when:

- one source name could map to multiple plausible teams;
- a historical rename has no reliable effective date;
- an academy/youth/reserve/national team could be confused with the senior club;
- two sources disagree on identity and the conflict cannot be resolved;
- a newly observed name has no safe mapping.

Such events should remain collectable as raw evidence but be marked `IDENTITY_UNRESOLVED` / excluded from model features until resolved. Never manufacture a team identity just to increase coverage.

## Sport-specific caution

The same display string can represent different entities across sports or competitions. Identity keys must therefore be scoped by sport and must not globally equate names across the seven sports.

For Valorant in particular, roster/organization changes and historical team-name changes must not cause a new roster or organization to inherit historical strength automatically. Preserve the entity timeline and model roster continuity explicitly.

## Acceptance criteria

A production prediction is acceptable only when the displayed team names are canonical, the underlying `team_id` values are stable, source names remain auditable, and unresolved identity conflicts cannot silently enter training or prediction features.
