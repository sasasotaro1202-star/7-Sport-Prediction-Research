# Complete 9-Sport Target Audit — 2026-09-18

Repository audited: `sasasotaro1202-star/7-Sport-Prediction-Research`.

This audit treats each sport independently. A different URL/API over the same underlying dataset is not counted as an independent source. No new source is production-adopted from discovery alone.

## Cross-cutting finding

The repository's storage layer already supports source URL, retrieval time, source-availability time, event time, parser version, content hash, provenance, effective time, PIT replay and audit records. The key weakness is that several collectors still write `UNVERIFIABLE` source availability, which means their detailed statistics cannot safely enter strict historical PIT features. The strict research engine therefore often falls back to generic strength/history/rest features. This is preferable to leakage, but it limits feature diversity.

The canonical production workflow currently runs **7 sports** in its main matrix. Rugby has a separate coverage workflow/database and is not yet in the canonical model/release pipeline.

## 1. Basketball — independently audited

**Current provider / endpoint / dataset**
- ESPN scoreboard API: `site.api.espn.com/apis/site/v2/sports/basketball/{league}/scoreboard` for current discovery.
- Historical recovery uses SportsDataverse hoopR NBA/WNBA files and a FIBA 2019 CSV.
- hoopR's own README identifies ESPN as the source of its NBA/WNBA data, so those files are not independent from ESPN.
- FIBA 2019 is a different underlying dataset but narrow.

**Features / PIT / historical-live / fallback / license**
- Current strict model artifact has 9 features: Elo/history count/rest-day features and their A-B differences. The 9-feature count is consistent with no six-stat family surviving strict PIT filtering in the persisted research result.
- Collector statistics exist in the schema, but the collector marks source availability `UNVERIFIABLE`; strict feature construction requires `EXACT` source availability <= cutoff.
- Live/current: ESPN. Historical: hoopR/FIBA recovery. Fallback is explicit, but not all fallback sources are independent.
- License/terms: ESPN/NBA/FIBA terms must be checked before redistribution; the repo currently does not contain a machine-readable license registry. Do not assume a commercial reuse right.

**OOS evidence**
- Training 25,686, frozen holdout 7,246.
- Selection OOS n=8,991; holdout LogLoss 0.688742, Brier 0.247783, Accuracy 0.555755, ECE 0.029859.
- `hist_gb` selected; holdout excluded from production fit.

**New independent candidates**
- NBA Stats / stats.nba.com: richer player/team/game/PBP/shot information. Candidate; PIT availability and terms must be captured.
- WNBA Stats: official richer player/match statistics. Candidate; PIT availability must be proven.
- FIBA official data: international competition context. Candidate; current FIBA CSV is only narrow historical coverage.
- B.League official: Japan-specific team/player context. Candidate; machine-readable PIT access is unproven.
- SportsDataIO: injuries/confirmed lineups/odds/rosters, but commercial. Candidate only with timestamped historical snapshots and acceptable license/cost.

**Adoption**: No new candidate adopted yet. Priority is to make one genuinely independent source PIT-exact and then run candidate-vs-incumbent walk-forward/holdout tests.

**Risk**: current model is heavily dependent on generic Elo/history/rest because detailed stats are not PIT-verified.

## 2. Volleyball — independently audited

**Current**
- FIVB VIS endpoint `https://www.fivb.org/Vis2009/XmlRequest.asmx`, `GetVolleyMatchList`.
- ESPN scoreboard discovery also exists.
- Historical FIVB VIS collection is 2016-current in code; source snapshots are currently `UNVERIFIABLE`.

**Features/PIT/model**
- Current strict model: 9 generic Elo/history/rest features, `hist_gb` selected.
- Training 15,122; frozen holdout 4,266; selection OOS n=5,293.
- Holdout LogLoss 0.685229, Brier 0.246046, Accuracy 0.564932, ECE 0.016205.
- Detailed volleyball stat policy exists (`attack`, `serve`, `receive`, `block`, `error`, `sideout`) but those features cannot safely enter strict PIT unless exact availability metadata exists.

**Candidates**
- Volleyball World/FIVB official statistics; FIVB ranking snapshots; SV.LEAGUE official; commercial feeds such as Sportradar, Data Sports Group, Broadage, LSports and Highlightly.
- Aggregators are not automatically independent because upstream lineage is unclear.

**Adoption**: none yet. The highest-value research target is exact-timestamp team/player match statistics and ranking snapshots for major international and Japanese competitions.

**Risk**: coverage exists, but detailed pre-match information is not PIT-proven; women/youth/club coverage should remain separately typed rather than pooled blindly.

## 3. UFC — independently audited

**Current**
- Aristotle UFC API `https://ufcapi.aristotle.me/api/events` for current event/fight-card collection.
- TidyTuesday `ufc_fights.csv` is fallback; it is UFCStats-derived historical data.
- UFCStats is the primary public statistics surface and is not currently the direct collector.

**Features/PIT**
- Current policy: `sig_str`, `takedown`, `td_pct`, `sub_attempts`, `control_time`.
- Same-fight statistics are explicitly effective at fight time and excluded from that fight's pre-event features.
- Strict model result: Random Forest, training 7,293, holdout 2,058, selection OOS n=2,553; holdout LogLoss 0.689333, Brier 0.248065, Accuracy 0.556851, ECE 0.036011.

**Candidates**
- UFC official/Meta UFC Rankings for pre-fight strength snapshots.
- UFC official fighter/event pages for participant/identity and event context.
- Cito API for round-level stats, but independence is unproven because it likely aggregates public sources.

**Adoption**: no new source yet. Ranking snapshots are the most promising genuinely new feature family if historical publication timestamps can be proven.

**Risk**: current fallback dataset is excellent for historical fight labels/stats but publication-time PIT is unverified.

## 4. RIZIN — independently audited

**Current**
- Official `jp.rizinff.com` result pages; hardened parser extracts event date, fighter pair and WIN/LOSE.
- ESPN FightCenter is secondary corroboration, not independent diversification by default.

**Features/PIT**
- Current strict policy mirrors UFC fight-stat families but no current persisted RIZIN research result was present in `results/research` at audit time.
- Official historical labels are marked `PIT_REQUIRES_REPLAY`; source availability is not proven.

**Candidates**
- RIZIN.TV official event/fighter context.
- FightOdds.io pre-fight market data, only if historical pre-fight snapshots and terms are verifiable.
- MMAJunkie independent editorial reporting for reconciliation, not automatically a quantitative feature source.

**Adoption**: none. First requirement is a clean multi-year PIT-safe event/outcome history; then candidate features can be tested with walk-forward OOS.

**Risk**: no verified current RIZIN production model artifact in the audited research-results directory; do not treat RIZIN coverage as model readiness.

## 5. Tennis — independently audited

**Current**
- Jeff Sackmann ATP/WTA archives via `Aneeshers/tennis-sackmann-archive` mirror.
- Current collector explicitly uses retrieval time as the conservative availability time and refuses to pretend archive retrieval time equals historical publication time.

**Features/PIT**
- Policy includes ace, double fault, first-serve and break-point families.
- Historical outcome/stat data exists, but exact historical publication availability is not proven; strict PIT replay must therefore gate feature use.
- No persisted `results/research/tennis.json` was present in the audited directory.

**Candidates**
- ATP/WTA official stats and ranking snapshots.
- LiveTennisAPI captured point-by-point states with real UTC observations; historical archive from 2025 onward, licensing/access to verify.
- The Odds API historical tennis odds; paid plans and timestamped pre-match snapshots can provide genuinely new market information.
- Tennis Abstract and other Sackmann-derived repositories are not independent for diversification unless raw upstream lineage differs.

**Adoption**: none yet. The strongest candidates are official ranking snapshots and independent timestamped market data, provided historical PIT can be proven.

**Risk**: mirror dependence and publication-time uncertainty.

## 6. F1 — independently audited

**Current**
- Jolpica/Ergast-compatible endpoint `https://api.jolpi.ca/ergast/f1` for historical results/qualifying/pit-stop data.
- OpenF1 `https://api.openf1.org/v1` for session/timing data from 2023 onward.
- FastF1 is a wrapper/access layer and therefore not an independent underlying dataset.

**PIT/model**
- OpenF1 collector writes `UNVERIFIABLE` source availability.
- Strict research explicitly returns `DEFERRED_PIT` because historical availability before the 60-minute cutoff is not proven.
- No F1 winner binary model is incorrectly forced into production; multi-entrant finishing-position semantics remain a separate problem.

**Candidates**
- Official F1 timing/data surfaces for grid, tire, weather, sector and session information.
- FastF1 only as a technical access wrapper, not source diversification.
- Timestamped market/odds data as a potential independent signal.

**Adoption**: none. First fix PIT provenance; then model F1 as multi-entrant outcomes (e.g. finish position/top-N) rather than shoehorning into binary A/B.

**Risk**: current F1 is coverage/enrichment, not verified PIT model readiness.

## 7. VALORANT — independently audited

**Current**
- VLR.gg match/event/detail pages.
- Public VLR-derived CSV from `rush2pranav/valorant-pro-scene-tracker` for historical recovery. This is not independent from VLR.

**Features/PIT/model**
- Policy includes rating, ACS, ADR, KAST, K/D and FK/FD, but strict persisted result has 9 generic features because detailed stats do not pass exact PIT source-availability requirements.
- Training 7,265; holdout 2,050; selection OOS n=2,543.
- Random Forest selected; holdout LogLoss 0.680527, Brier 0.243716, Accuracy 0.579512, ECE 0.006162.

**Candidates**
- Riot Esports Data / GRID is the clearest distinct upstream candidate and provides official VALORANT esports data.
- Riot official VALORANT Esports event/roster context is useful for identity and competition metadata.
- Kaggle/VLR scrapes are not independent unless upstream lineage differs.

**Adoption**: none yet. Official Riot/GRID data is a candidate for a challenger feature layer, but licensing/cost and historical PIT must be established before use.

**Risk**: VLR dependence and limited exact PIT for detailed round/player stats.

## 8. Rugby — independently audited

**Current**
- World Rugby official source is collected by `src/rugby_production.py` into a dedicated `data/db/rugby_v45.sqlite`.
- Seed scope includes Men's/Women's Six Nations, U20 Six Nations, World Rugby U20 Championship and Nations Cup.
- Rugby has its own scheduled workflow `rugby_production.yml`, but the main canonical production workflow matrix remains 7 sports.

**PIT/model**
- Current rugby source snapshots are `UNVERIFIABLE`.
- No rugby strict research model/result artifact exists in the canonical `results/research` directory.
- Therefore Rugby is **coverage-only**, not production prediction-ready.

**Candidates**
- ESPN Rugby for broad scoreboard/lineups/match/odds coverage.
- Japan Rugby League One official for Japan-specific competition context.
- World Rugby rankings/statistics for official ranking snapshots.
- Rugby Database for independent historical context if provenance/PIT is proven.
- `nrlR` is a scraper package, not independent if it merely republishes upstream web data.
- Sportradar/Highlightly can add breadth but are commercial/aggregated and require lineage/license checks.

**Adoption**: none. First build rugby-specific outcome semantics and PIT-safe feature history; do not add Rugby into the canonical model matrix until that is complete.

**Risk**: current workflow validates coverage but not model/OOS/PIT readiness.

## 9. Boxing — explicitly deferred

**Current**
- Boxing is now a formal target sport with a dedicated PIT-source guard workflow.
- Free/open candidates include Boxing Undefeated's open-boxing-data, BoxingScene, and BoxRec-compatible public tooling.

**PIT/model**
- No candidate currently proves historical `source_available_at_utc <= prediction_cutoff` for the required 60-minute pre-event cutoff.
- The repository therefore marks Boxing `DEFERRED_PIT`; no Boxing features, model artifact, or future prediction is promoted.
- Candidate feature families are limited to documented pre-fight attributes such as fighter history, strength, rest/inactivity and weight-class context until provenance is proven.

**Operational guard**
- `.github/workflows/boxing_pit_guard.yml` runs every six hours and on demand. It records source reachability without treating retrieval time as historical availability.

## Actions audit

- Latest verified `Production Invariants` run: **#79**, run ID `35252678367`, head `1cff3ef44563f50cb4f94f3581a5299826b87fbe`, completed `success`; the invariants job and its steps succeeded.
- Canonical production workflow has five active sport collectors, parallelized with `fail-fast: false`, transient-network retry, persistent cache, collection guard, PIT replay, independent leakage audit, frozen-holdout research, quality gate, release gate and invariants; four additional target sports are explicit DEFERRED lanes.
- Rugby has a separate scheduled coverage workflow, while Boxing has a lightweight six-hour PIT source guard. The expected `results/v45/rugby_coverage.json` was not present on `main` at audit time, despite the workflow requiring it. This is a concrete reproducibility/operability risk and must be repaired rather than treated as success; the Boxing guard is intentionally non-publishing and uses the same fail-closed provenance rule.
- `production_release_gate.py` currently writes `BLOCKED`/`publish=false` but returns exit code 0. This means a blocked release can appear green in Actions. This conflicts with the requirement that failures must not be treated as success. This should be changed so `BLOCKED` returns non-zero while still never publishing unsafe models.

## Final adoption policy

No newly discovered source is promoted by source count, field count, or apparent predictive correlation. The required sequence is:

`candidate source → independent lineage check → source-availability/PIT proof → schema/QC → new-feature layer → chronological walk-forward OOS → multi-period/multi-competition replication → frozen holdout → calibration/drift checks → incumbent comparison → gated adoption`.

A candidate that fails PIT or cannot be independently verified remains `DEFERRED` even if it appears predictive. This audit therefore intentionally recommends **fewer, higher-value sources**, not equal source counts across sports.
