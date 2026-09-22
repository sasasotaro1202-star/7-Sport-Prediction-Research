# 9-Sport Target Source Registry — independent audit baseline

This registry is deliberately sport-specific. A mirror, wrapper, republisher, or alternate API over the same underlying dataset is **not** an independent source. `EXACT` PIT requires an auditable source-availability timestamp; retrieval time alone is not historical availability.

## Status vocabulary
- `CURRENT`: currently used by repository collection/model paths.
- `CANDIDATE`: researched as potentially useful; not production-adopted.
- `NON_INDEPENDENT`: same underlying dataset as an existing source; do not count as diversification.
- `PIT_UNPROVEN`: useful data but historical availability before cutoff is not demonstrated.
- `DEFERRED`: deliberately not used until PIT/OOS evidence exists.

## Basketball

### Current
- **ESPN** — endpoint family `site.api.espn.com/apis/site/v2/sports/basketball/{league}/scoreboard`; underlying ESPN scoreboard/event dataset; current/live discovery and event/team/score fields. PIT: `UNVERIFIABLE` in the current collector; historical features therefore require PIT replay evidence. Fallback/backfill currently includes SportsDataverse `hoopR-data` NBA/WNBA files plus a FIBA 2019 CSV, but hoopR's NBA and WNBA repositories identify ESPN as their source, so those NBA/WNBA files are `NON_INDEPENDENT` relative to ESPN. The FIBA file is a genuinely different underlying dataset.
- **SportsDataverse hoopR-data** — NBA/WNBA historical files; source README explicitly identifies ESPN as the NBA/WNBA data source. `NON_INDEPENDENT` for diversification, although useful as a schema/recovery path. https://github.com/sportsdataverse/hoopR-data
- **FIBA World Cup 2019 dataset** — current historical recovery source in `hardened_public_history.py`; independent of ESPN, but narrow competition coverage and PIT publication timing is not proven. `DEFERRED` for feature use until replay passes.

### Candidates
- **NBA Stats / stats.nba.com** — player/team/game/shot/PBP/advanced tracking-style statistics. Independent information from ESPN at the underlying-provider level, but access stability, historical publication timestamps and terms must be validated before adoption. https://stats.nba.com/
- **WNBA Stats** — official WNBA player/match/advanced statistics. Potentially independent of ESPN; PIT availability must be established before historical use. https://stats.wnba.com/
- **FIBA official competition/statistics** — official international competition data; potentially adds international/team/player competition context not represented by the current ESPN recovery path. https://www.fiba.basketball/
- **B.League official** — Japan-specific competition/team/player data. Candidate for Japan coverage; PIT and machine-readable access must be verified before adoption. https://www.bleague.jp/
- **SportsDataIO NBA** — broad pre-match data including rosters, injuries, confirmed lineups and odds, but commercial/paid after trial. Candidate only if historical PIT snapshots are contractually and technically available. https://sportsdata.io/nba-api

## Volleyball

### Current
- **FIVB VIS** — `https://www.fivb.org/Vis2009/XmlRequest.asmx`, `GetVolleyMatchList`; underlying FIVB VIS match-list data; historical 2016–current collection path with team/tournament/result fields. Current implementation stores source availability as `UNVERIFIABLE`, so historical feature use is deferred until PIT replay proves availability.
- **ESPN** — generic live/scoreboard discovery path in the shared collector where a volleyball league is configured. Underlying ESPN dataset; current/live utility, but PIT historical availability is not established by retrieval time.

### Candidates
- **Volleyball World / FIVB official statistics** — official competition pages and statistics; can add player-level and competition-specific information. PIT must be proven for historical use. https://en.volleyballworld.com/
- **FIVB official rankings** — ranking history can add team strength/context, but rankings must be snapshotted with publication/effective timestamps. https://www.fivb.com/volleyball/rankings
- **Japan V.League / SV.LEAGUE official** — Japan competition context; candidate for league-specific team/player information, with PIT and machine-readable access to be validated. https://www.svleague.jp/
- **Highlightly / Data Sports Group / Broadage / LSports** — broad commercial/aggregated coverage. Treat as republished/aggregated unless underlying provider lineage is independently demonstrated; no automatic diversification credit.

## UFC

### Current
- **Aristotle UFC API** — `https://ufcapi.aristotle.me/api/events`; current API event/fight-card source. Historical availability is not proven as PIT; collector therefore treats it as a collection source, not automatically as historical PIT evidence.
- **TidyTuesday 2026-07-07 `ufc_fights.csv`** — fallback dataset; underlying UFCStats-derived historical fight/stat dataset. The repository explicitly records historical publication time as `UNVERIFIABLE`; fight statistics become effective at fight time, so they are excluded from the same fight's pre-event features. https://github.com/rfordatascience/tidytuesday/tree/main/data/2026/2026-07-07
- **UFCStats** — official statistics site used as the conceptual primary statistics source for UFC results/fight statistics. It is not currently wired as the repository's direct collector. http://ufcstats.com/

### Candidates
- **UFC official rankings / Meta UFC Rankings** — official rankings can add a distinct strength prior, but historical ranking snapshots and publication timestamps must be preserved. https://www.ufc.com/rankings
- **UFC official event/fighter pages** — official event, participant and profile information; useful for identity/participant confirmation, but PIT publication history must be captured.
- **Cito UFC API** — detailed event/bout/round data and a free tier, but likely aggregates/repackages underlying public sources; do not count as independent until lineage is demonstrated. https://docs.citoapi.com/ufc-stats-api

## RIZIN

### Current
- **RIZIN official** — `jp.rizinff.com` result pages/tags; current hardened parser extracts event date, fighter pair and WIN/LOSE result. Historical publication timestamps are not yet proven, so results are `PIT_REQUIRES_REPLAY` rather than automatically usable features. https://jp.rizinff.com/
- **ESPN FightCenter** — secondary event/fight result pages can provide historical corroboration. It is not considered independent from an underlying RIZIN result merely because the URL is different; use only for reconciliation unless lineage differs.

### Candidates
- **RIZIN.TV** — official streaming/event/fighter context. Potentially useful for participant/event metadata; historical availability and machine-readable extraction need proof. https://www.rizin.tv/
- **FightOdds.io** — independent market/odds surface for RIZIN fights; useful only as a market feature after timestamped pre-fight odds snapshots and licensing are verified. https://fightodds.io/
- **MMAJunkie** — independent editorial result reporting; useful for cross-checking outcomes/metadata, not automatically a quantitative feature source. https://mmajunkie.usatoday.com/

## Tennis

### Current
- **Jeff Sackmann archive mirror (`Aneeshers/tennis-sackmann-archive`)** — ATP/WTA match archives, rankings/match-stat style fields; current repository source name `JeffSackmannArchive`. The code deliberately treats archive retrieval time as the conservative availability timestamp and does not pretend the archive was available at historical match time. Thus it is not automatically PIT-EXACT for historical feature replay. https://github.com/Aneeshers/tennis-sackmann-archive
- **ATP/WTA official sites** — current official statistics/rankings surfaces used as research candidates rather than direct PIT training evidence. https://www.atptour.com/en/stats ; https://www.wtatennis.com/stats

### Candidates
- **Live Tennis API data** — captured live point-by-point states with real UTC observation times; potentially valuable for live/PIT research, but its historical archive starts in 2025 and licensing/access terms must be checked. https://github.com/livetennisapi/livetennisapi-data
- **The Odds API tennis** — historical pre-match odds available on paid plans, including Grand Slam history from 2020. Market information is genuinely new relative to Sackmann match stats, but must be timestamped at the exact prediction cutoff. https://the-odds-api.com/sports/tennis-odds.html
- **Tennis Abstract** — derived tennis analysis/rankings. Treat as a derivative unless a distinct raw underlying source is demonstrated; useful for exploratory comparison, not automatic diversification. https://www.tennisabstract.com/
- **ATP/WTA official stats/rankings** — potentially distinct official data, especially ranking snapshots and richer serving/returning statistics. Historical PIT availability is the blocking requirement.

## F1

### Current
- **Jolpica-F1 / Ergast-compatible** — `https://api.jolpi.ca/ergast/f1`, historical race/results/qualifying/pit-stop style data. Ergast was succeeded by Jolpica; therefore FastF1/Jolpica wrappers are not independent datasets. Historical publication timing is not automatically PIT-EXACT.
- **OpenF1** — `https://api.openf1.org/v1`, historical session/timing data from 2023 onward; current collector uses `/sessions` and `/session_result`. Source availability timestamp is currently not proven, so strict research marks F1 `DEFERRED_PIT` rather than using leakage-prone telemetry as historical pre-race evidence. https://openf1.org/docs

### Candidates
- **FastF1** — useful access/analysis wrapper for F1 timing/telemetry but it is a wrapper over official F1 API/Jolpica-related sources; `NON_INDEPENDENT` for source diversification. https://docs.fastf1.dev/
- **Official F1 timing/data surfaces** — potentially the most direct source for qualifying, grid, tire, weather and timing data; historical availability and terms need explicit PIT snapshot capture. https://www.formula1.com/
- **F1 market/odds provider** — potentially valuable pre-event market signal, but only adopt after timestamped historical odds and licensing are verified.

## VALORANT

### Current
- **VLR.gg** — match pages, results, event/tournament context, team names and match-level details; current collector and public-history path use VLR-derived data. PIT publication timestamps are not automatically equivalent to retrieval timestamps.
- **Public VLR-derived CSV (`rush2pranav/valorant-pro-scene-tracker`)** — historical result recovery. It is `NON_INDEPENDENT` from VLR for diversification because it is explicitly a VLR-derived dataset.

### Candidates
- **Riot Esports Data / GRID** — official VALORANT esports data partnership, with live/source-direct esports data. This is the clearest genuinely different upstream source candidate, but access is commercial/partner-oriented and licensing must be confirmed. https://riotesportsdata.com/valorant
- **Riot official VALORANT Esports** — tournament/roster/event context. Use for identity and official event metadata where historical publication timestamps can be captured. https://valorantesports.com/
- **Kaggle VCT datasets** — useful exploratory material but generally VLR-scraped/derived; do not count as independent without upstream lineage proof.

## Rugby

### Current
- **World Rugby official** — `src/rugby_production.py` crawls `world.rugby` seeds for Men's/Women's Six Nations, U20 competitions and Nations Cup, storing event/participant snapshots in a dedicated `rugby_v45.sqlite`. Current implementation labels source availability `UNVERIFIABLE` and has no rugby model/OOS path, so this is coverage-only, not production prediction evidence. https://www.world.rugby/
- **Rugby League One official** — Japan-specific official competition surface identified as a useful candidate, but not currently wired into the repository. https://league-one.jp/en

### Candidates
- **ESPN Rugby** — broad international/club scoreboard, lineups, match and odds surfaces; potentially useful for coverage/reconciliation, but underlying dataset lineage and historical PIT availability must be verified. https://www.espn.com/rugby/scoreboard
- **World Rugby rankings/statistics** — official ranking and team/player competition context; historical snapshot availability is the gating requirement.
- **nrlR** — R package scraping NRL/Super League/etc.; `NON_INDEPENDENT` if it only republishes upstream scraped pages, and not suitable as a diversification source without distinct lineage. https://cran.r-project.org/package=nrlR
- **Rugby Database** — community-maintained broad historical rugby database; potentially independent, but provenance/coverage/PIT publication timing need verification. https://rugbydatabase.co.uk/
- **Sportradar / Highlightly / other commercial feeds** — broad coverage and live statistics, but cost and upstream lineage need validation; no automatic adoption.

## Boxing

### Current
- **Boxing Undefeated / open-boxing-data**
- **mavese/machineLearningBoxingMatches** — public historical Boxing CSV candidate; the dataset was added to that repository on 2018-06-21, but the CSV exposed there does not provide an event-date field, so commit timing alone cannot establish row-level PIT availability for a specific bout. It remains `PIT_UNPROVEN`. — free/open boxing-data candidate monitored by the repository's boxing_production.py guard. It does not currently prove historical source availability at the prediction cutoff, so it remains `PIT_UNPROVEN`/`DEFERRED` rather than a production feature source. https://github.com/boxingundefeated/open-boxing-data
- **BoxingScene** — public schedule/results candidate. Retrieval time is not treated as historical publication availability; `PIT_UNPROVEN`.
- **BoxRec** — broad boxing record/schedule surface and public tooling ecosystem. Access/terms and historical publication timing require separate verification; `PIT_UNPROVEN` and not production-adopted.

### Candidate feature families
- Fighter age, height/reach, stance, weight class, recent win rate, opponent-strength history, inactivity/rest, weight-class-specific Elo, and prior result-method mix.
- These are design candidates only. No Boxing feature is enabled until source observations and historical availability are proven.

### Adoption status
- **DEFERRED_PIT** — no Boxing model is trained or published. The dedicated guard checks public-source reachability but never converts retrieval time into PIT evidence.

## Adoption rule

No candidate in this registry is production-adopted merely because it has more fields. Adoption requires: (1) independent underlying data, (2) PIT/available_at evidence, (3) data-quality checks, (4) demonstrably new information, (5) chronological walk-forward OOS improvement across multiple periods/competitions, (6) frozen holdout replication, (7) acceptable cost/licensing, and (8) operational continuity. A failed or unproven criterion leaves the source `DEFERRED`/`REJECTED` rather than silently using it.
