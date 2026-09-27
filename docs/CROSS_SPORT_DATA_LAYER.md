# Nine-Sport Cross-Sport Data Layer

## Status

Research-only. No production model or production prediction artifact is changed by this layer.

## Newly discovered sources

### TheSportsDB
Free JSON API with broad sports metadata. Current public pages show the nine target sports: basketball, volleyball, UFC, RIZIN FF, Valorant Champions Tour, tennis, Formula 1, rugby and boxing. The strongest use is cross-sport event, participant, league, venue and schedule/standings enrichment; it should not be assumed to have Opta-depth event statistics.

### ESPN public API surface
A current public GitHub implementation documents ESPN public endpoints across 17 sports, including basketball, racing, tennis, MMA, rugby and volleyball. Useful endpoint families include scores/schedules, teams/rosters, athletes, injuries, transactions, news and statistics. Treat the API surface as public/undocumented and reconstruct historical availability conservatively.

### Odds-API.io
The provider currently advertises a free tier of 100 requests/hour and 500/day across 34 sports. Direct current pages confirm basketball, tennis, MMA including Rizin, boxing, rugby and Valorant/esports coverage. Odds are a useful market-state feature, but bookmaker publication/capture time must be retained for PIT.

### Specialist open datasets
Live Tennis API publishes a 2023-2026 point-by-point research dataset with an observed layer carrying real UTC capture timestamps; access to the full dataset is restricted to non-commercial academic research. UFC-DataLab provides a maintained UFC historical corpus with fight stats and scorecards. An open boxing punch-recognition dataset supports future video-derived feature research. rugby.db provides a public-domain historical rugby corpus with limited tournament scope. VLR.gg unofficial API projects expose match, team and player statistics.

## PIT rule

- available_at <= prediction_time is eligible.
- available_at > prediction_time is a PIT failure.
- missing/unparseable available_at is UNKNOWN_FAIL_CLOSED.
- retrieval time is never substituted for historical availability evidence.
- market odds must retain bookmaker/source observation time.
- candidate-source data cannot auto-promote a production model.

## Current boundary

Existing sport-specific collectors remain the primary research/production data path. The cross-sport sources are discovery/enrichment candidates until PIT, quality, licensing and chronological OOS evidence are established.
## Cross-sport context sources

These are not Opta replacements, but they can add information available across multiple sports:

- GDELT: public news/event information for information shocks and external context. The GDELT project states its database is free and open; current GDELT Cloud also exposes structured stories/events with explicit coverage/provenance metadata.
- Open-Meteo: free weather/historical forecast data without an API key for non-commercial use. Archived forecast runs are particularly useful for PIT-safe weather features because the forecast run time can be preserved.
- OpenStreetMap Overpass: free public geospatial data for venue coordinates, travel distance and venue context.
- Wikidata: free SPARQL access for entity resolution and stable biographical/geographic metadata.

These context sources should be joined after event identity is established and before prediction features are materialized. Each source keeps its own observation/snapshot timestamp and PIT status.
