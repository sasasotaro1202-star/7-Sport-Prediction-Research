# Complete Competition Master — 8 Sports

Updated: 2026-09-19
Repository: sasasotaro1202-star/7-Sport-Prediction-Research

## Purpose and status semantics

This is the canonical competition/scope master for the eight-sport project. It separates configured/current collection scope, identified candidate scope, and production adoption. It does not claim that every competition in the world is currently machine-readable or production-ready.

- **Current / configured** = explicitly present in the current repository collector or production workflow.
- **Coverage / identified** = named in the repository's source registry, audit, or dedicated collector as a target/candidate, but not necessarily active in the canonical model.
- **PIT proven** = historical information availability before the prediction cutoff is evidenced sufficiently for strict PIT use.
- **PIT unproven** = data exists, but historical publication/availability timing is not proven.
- **Production adopted** = passed the project's OOS, calibration, frozen-holdout, challenger, PIT/leakage, quality and release requirements.
- **DEFERRED** = deliberately excluded until the blocking evidence is resolved.
- **Gate pending** = the current canonical production run has not yet completed its final release gate.

## Master table

| Sport | Competition / league | Country / region | Gender | Category | Era / coverage target | Currently retrievable | PIT provable | Production adoption | Current role / notes |
|---|---|---|---|---|---|---|---|---|---|
| Basketball | NBA | USA / North America | Men | Professional | Historical + current | Yes | Unproven for detailed historical ESPN features | Gate pending | Configured current collector |
| Basketball | WNBA | USA / North America | Women | Professional | Historical + current | Yes | Unproven for detailed historical ESPN features | Gate pending | Configured current collector |
| Basketball | NCAA Men's Basketball | USA | Men | College | Historical + current | Yes | Unproven | Gate pending | Configured current collector |
| Basketball | FIBA Basketball World Cup | International | Men | National teams | Historical; current recovery narrow | Partial | Unproven | Deferred | Independent FIBA 2019 recovery exists |
| Basketball | FIBA Women's Basketball World Cup | International | Women | National teams | Historical/current candidate | Candidate | Unproven | Deferred | Official FIBA source candidate |
| Basketball | Olympics Basketball | International | Men/Women | National teams | Historical/current candidate | Candidate | Unproven | Deferred | Official FIBA/Olympic candidate |
| Basketball | EuroLeague | Europe | Men | Club | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Basketball | EuroCup | Europe | Men | Club | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Basketball | Liga ACB | Spain | Men | Professional | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Basketball | B.League | Japan | Men | Professional | Historical/current candidate | Candidate | Unproven | Deferred | Official B.League candidate |
| Basketball | WJBL / Japan women's basketball | Japan | Women | Professional | Historical/current candidate | Candidate | Unproven | Deferred | Official machine-readable PIT not established |
| Volleyball | Volleyball World / FIVB competitions | International | Men/Women | National teams / international | 2016-current collection path | Yes | Unproven | Deferred / gate pending | Configured generic collector |
| Volleyball | Volleyball Nations League (VNL) | International | Men/Women | National teams | Historical/current candidate | Candidate/partial | Unproven | Deferred | FIVB/Volleyball World |
| Volleyball | Volleyball World Championship | International | Men/Women | National teams | Historical/current candidate | Candidate | Unproven | Deferred | FIVB/Volleyball World |
| Volleyball | Olympics Volleyball | International | Men/Women | National teams | Historical/current candidate | Candidate | Unproven | Deferred | FIVB/Olympic candidate |
| Volleyball | FIVB World Cup / World Cup-era competitions | International | Men/Women | National teams | Historical/current candidate | Candidate | Unproven | Deferred | FIVB history |
| Volleyball | SV.LEAGUE / Japan V.League | Japan | Men/Women | Professional | Historical/current candidate | Candidate | Unproven | Deferred | Official Japan candidate |
| UFC | UFC numbered events | International | Men/Women | MMA | Historical + current | Yes | Historical source availability unproven | Gate pending | UFC event/fight history |
| UFC | UFC Fight Night | International | Men/Women | MMA | Historical + current | Yes | Historical source availability unproven | Gate pending | Same UFC production family |
| UFC | UFC PPV / major event cards | International | Men/Women | MMA | Historical + current | Yes | Unproven | Gate pending | Same UFC production family |
| UFC | UFC rankings | International | Men/Women | Ranking context | Historical snapshots/current candidate | Candidate | Unproven | Deferred | Potential pre-fight feature if timestamped |
| RIZIN | RIZIN numbered events | Japan / International | Men/Women | MMA | Historical + current | Yes | Unproven | Deferred | Official RIZIN; PIT replay required |
| RIZIN | RIZIN Landmark | Japan / International | Men/Women | MMA | Historical + current | Yes | Unproven | Deferred | Official event coverage |
| RIZIN | RIZIN Grand Prix | Japan / International | Men/Women | Tournament MMA | Historical/current | Partial | Unproven | Deferred | Event coverage candidate |
| RIZIN | RIZIN women's divisions | Japan / International | Women | MMA | Historical/current | Partial | Unproven | Deferred | Gender/category kept separate |
| Tennis | ATP Tour | International | Men | Professional | Historical + current | Yes | Archive PIT unproven | Gate pending | Configured current collector |
| Tennis | WTA Tour | International | Women | Professional | Historical + current | Yes | Archive PIT unproven | Gate pending | Configured current collector |
| Tennis | Australian Open | Australia / International | Men/Women | Grand Slam | Historical + current | Candidate/yes | Unproven | Deferred | Official/independent candidate |
| Tennis | Roland-Garros | France / International | Men/Women | Grand Slam | Historical + current | Candidate/yes | Unproven | Deferred | Official/independent candidate |
| Tennis | Wimbledon | UK / International | Men/Women | Grand Slam | Historical + current | Candidate/yes | Unproven | Deferred | Official/independent candidate |
| Tennis | US Open | USA / International | Men/Women | Grand Slam | Historical + current | Candidate/yes | Unproven | Deferred | Official/independent candidate |
| Tennis | ATP Masters / ATP 1000 | International | Men | Masters | Historical + current | Candidate | Unproven | Deferred | ATP subset |
| Tennis | WTA 1000 | International | Women | WTA 1000 | Historical + current | Candidate | Unproven | Deferred | WTA subset |
| Tennis | ATP 500 | International | Men | ATP 500 | Historical + current | Candidate | Unproven | Deferred | ATP subset |
| Tennis | ATP 250 | International | Men | ATP 250 | Historical + current | Candidate | Unproven | Deferred | ATP subset |
| Tennis | WTA 500 | International | Women | WTA 500 | Historical + current | Candidate | Unproven | Deferred | WTA subset |
| Tennis | WTA 250 | International | Women | WTA 250 | Historical + current | Candidate | Unproven | Deferred | WTA subset |
| Tennis | ATP Challenger | International | Men | Challenger | Historical + current | Candidate | Unproven | Deferred | Archive coverage candidate |
| Tennis | ITF World Tennis Tour | International | Men/Women | ITF | Historical/current candidate | Candidate | Unproven | Deferred | Not currently production wired |
| Tennis | Davis Cup | International | Men | National teams | Historical/current candidate | Candidate | Unproven | Deferred | Team competition |
| Tennis | Billie Jean King Cup | International | Women | National teams | Historical/current candidate | Candidate | Unproven | Deferred | Team competition |
| Tennis | Olympic Tennis | International | Men/Women | Olympic | Historical/current candidate | Candidate | Unproven | Deferred | Olympic context |
| F1 | FIA Formula One World Championship | International | Mixed | Single-seater motorsport | Historical + current | Yes | Unproven for OpenF1 historical availability | Deferred | Jolpica/Ergast + OpenF1 |
| F1 | F1 Grand Prix races | International | Mixed | Race | Historical + current | Yes | Unproven | Deferred | Core F1 event layer |
| F1 | F1 Qualifying | International | Mixed | Qualifying | Historical + current | Yes | Unproven | Deferred | Separate session semantics |
| F1 | F1 Sprint | International | Mixed | Sprint | Modern era | Yes where available | Unproven | Deferred | Separate from Grand Prix |
| F1 | F1 Practice | International | Mixed | Practice | Modern era/source dependent | Yes where available | Unproven | Deferred | Only after PIT proof |
| F1 | F2 | International | Mixed | Formula 2 | Candidate | Candidate | Unproven | Deferred | Not canonical eight-sport scope |
| F1 | F3 | International | Mixed | Formula 3 | Candidate | Candidate | Unproven | Deferred | Not canonical eight-sport scope |
| VALORANT | VCT Champions | International | Open / mixed | Premier esports | Historical/current | Yes via VLR | Unproven | Gate pending / source-limited | VLR current source |
| VALORANT | VCT Masters | International | Open / mixed | Premier esports | Historical/current | Yes via VLR | Unproven | Gate pending / source-limited | VLR |
| VALORANT | VCT Americas | Americas | Open / mixed | Regional league | Historical/current | Yes via VLR | Unproven | Gate pending / source-limited | VLR |
| VALORANT | VCT EMEA | Europe/Middle East/Africa | Open / mixed | Regional league | Historical/current | Yes via VLR | Unproven | Gate pending / source-limited | VLR |
| VALORANT | VCT Pacific | Asia-Pacific | Open / mixed | Regional league | Historical/current | Yes via VLR | Unproven | Gate pending / source-limited | VLR |
| VALORANT | VCT China | China | Open / mixed | Regional league | Historical/current | Yes via VLR | Unproven | Gate pending / source-limited | VLR |
| VALORANT | Challengers | Regional/global | Open / mixed | Developmental esports | Historical/current | Yes where indexed | Unproven | Deferred | VLR |
| VALORANT | Ascension | Regional | Open / mixed | Promotion tournament | Historical/current | Yes where indexed | Unproven | Deferred | VLR |
| VALORANT | Game Changers | Regional/global | Women / women-focused | Esports | Historical/current | Yes where indexed | Unproven | Deferred | Keep category separate |
| VALORANT | Riot Esports Data / GRID competitions | Global | Open / mixed | Official esports data | Candidate | Candidate | Unproven | Deferred | Independent upstream candidate |
| Rugby | Men's Six Nations | Europe | Men | National teams | Current seed 2026 | Yes / crawl target | Unproven | Coverage-only / deferred | World Rugby seed |
| Rugby | Women's Six Nations | Europe | Women | National teams | Current seed 2026 | Yes / crawl target | Unproven | Coverage-only / deferred | World Rugby seed |
| Rugby | U20 Six Nations | Europe | Men | U20 national teams | Current | Yes / crawl target | Unproven | Coverage-only / deferred | World Rugby seed |
| Rugby | World Rugby U20 Championship | International | Men | U20 national teams | Current | Yes / crawl target | Unproven | Coverage-only / deferred | World Rugby seed |
| Rugby | World Rugby Nations Cup | International | Men/Women as applicable | National teams | Current | Yes / crawl target | Unproven | Coverage-only / deferred | World Rugby seed |
| Rugby | Rugby World Cup | International | Men | National teams | Historical/current candidate | Candidate | Unproven | Deferred | World Rugby candidate |
| Rugby | Women's Rugby World Cup | International | Women | National teams | Historical/current candidate | Candidate | Unproven | Deferred | World Rugby candidate |
| Rugby | Rugby Championship | Southern Hemisphere | Men | National teams | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Rugby | Super Rugby | Southern Hemisphere | Men | Club/franchise | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Rugby | Premiership Rugby | England | Men | Club | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Rugby | United Rugby Championship (URC) | Europe/Ireland/UK | Men | Club | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Rugby | Top 14 | France | Men | Club | Historical/current candidate | Candidate | Unproven | Deferred | Candidate |
| Rugby | Japan Rugby League One | Japan | Men | Club | Historical/current candidate | Candidate | Unproven | Deferred | Official Japan candidate |

## Current production-state summary

| Sport | Status |
|---|---|
| Basketball | Active collector/model path; detailed stat PIT limited; final release gate required |
| Volleyball | Active collection path; detailed stat PIT limited; final release gate required |
| UFC | Active historical fight path; same-fight statistics excluded from pre-fight features; final gate required |
| RIZIN | Explicitly deferred until historical PIT availability is proven |
| Tennis | ATP/WTA collection path exists; archive PIT remains conservative/unproven |
| F1 | Explicitly deferred for strict PIT and separate multi-entrant outcome design |
| VALORANT | Active VLR collection path; detailed player/round-stat PIT limited; final gate required |
| Rugby | Coverage workflow exists; no production model adoption until rugby-specific PIT/OOS/release evidence is complete |

## Promotion rule

Competition expansion does not automatically expand model training. The required sequence is:

discover → collect → provenance/QC → PIT proof → leakage audit → chronological OOS → ablation → calibration → multi-period replication → frozen holdout → challenger gate → production release

A competition/source that fails PIT or cannot be independently verified remains deferred even if it appears predictive.
