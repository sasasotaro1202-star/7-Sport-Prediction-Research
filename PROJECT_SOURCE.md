7-Sport-Prediction-Research — Project Source

TARGET:
https://github.com/sasasotaro1202-star/7-Sport-Prediction-Research

ROLE:
本Sourceは7スポーツ予測研究プロジェクトの長期的・技術的な正本仕様である。
Project Instructionsより詳細な実装・研究・検証・運用ルールを保持する。
現行GitHub、コード、設定、テスト、Workflow、Artifact、実測結果が本Sourceや過去会話と矛盾する場合、現行GitHubを優先する。ただし過去結果を改変して整合させてはならない。

0. SYSTEM MISSION

最終目的は、平均的な過去精度だけではなく、未知の将来イベントに対するFuture Generalization、case-level correctness、状況認識、予測可能性、失敗耐性、校正、適切な棄権、情報取得判断、自己改善能力を最大化することである。

Prediction Systemは単一モデルではなく、

Data
→ Identity
→ Coverage
→ PIT
→ Feature
→ Candidate Model
→ Ensemble/Routing
→ Calibration
→ Uncertainty
→ Predictability
→ Matchday Intelligence
→ Selective Prediction
→ OOS
→ Robustness
→ Frozen Holdout
→ Production
→ Monitoring
→ Failure Analysis
→ Research
→ Adoption/Rollback

の閉ループとして扱う。

Accuracyだけを最大化する行為を禁止し、LogLoss、Brier、Calibration、Case-level error、Regime robustness、Recovery、安全性、再現性を同時に評価する。

⸻

1. CANONICAL CURRENT SCOPE

現在のリポジトリで明確にproduction/researchとして存在するスポーツは以下。

Current Production / Validated Scope

* VALORANT
* Basketball
* Volleyball
* UFC
* RIZIN

Research / Deferred / Expansion Scope

* Tennis
* F1
* Rugby
* Boxing

現在のScopeは固定的な「5スポーツ」ではない。
Registry、PIT検証、データ可用性、OOS、robustness、holdout、production gateにより段階的に拡張・縮退する。

⸻

2. EXISTING REPOSITORY INTEGRATION

既存実装を破棄せず、まず再利用・監査・改善する。

主要Workflowとして少なくとも以下の系統を統合対象とする。

* 24h autonomous research
* watchdog
* all-sport research
* autonomous research sweep
* bootstrap full history
* PIT history expansion
* cache/PIT health
* pre-event prediction
* matchday horizon research
* scope audit / expansion / boundary guard
* production invariants
* production runtime health
* production safety audit
* production failure recovery
* research/OOS smoke
* upset uncertainty research
* conformal aggregation/research
* retrieval local conformal research
* RIZIN validation
* deferred-sport research
* ultimate end-to-end research

既存Workflowの存在自体を成功条件にしない。
各Workflowが実際に正しいデータ、正しいPIT、正しい評価、artifact保存、失敗処理を実行しているかを検証する。

⸻

3. SPORT REGISTRY

各sportは以下のメタデータをRegistryで管理する。

必須:

* sport_id
* canonical_name
* status
* production_status
* target_definition
* event_definition
* event_time_field
* prediction_cutoff_policy
* available_at_policy
* identity_policy
* competition_registry
* source_registry
* model_registry
* calibration_registry
* holdout_status
* last_valid_oos
* last_robustness
* latest_failure
* coverage_status
* PIT_status
* release_status

statusは以下を使用。

DISCOVERED
METADATA_CHECKED
DATA_FEASIBLE
PIT_VALIDATED
SHADOW
OOS
ROBUSTNESS
LIMITED_PRODUCTION
STABLE_PRODUCTION
SCALE_UP
DEFERRED
HOLD
REJECTED
BLOCKED
FAILED
ROLLED_BACK

⸻

4. COMPETITION MASTER REGISTRY

競技単位ではなくcompetition/event structureまで正規化する。

各competitionは、

* competition_id
* sport_id
* canonical_name
* country/region
* level/tier
* season
* phase
* event_type
* event_time
* venue
* source
* source_event_id
* publication/availability metadata
* quality_status
* PIT_status
* production_status

を持つ。

同一大会の別名称、別source表記、翻訳名、略称をcanonical competitionへ正規化する。

未知competitionを既存competitionへ勝手にmapしない。

⸻

5. STAGED COMPETITION EXPANSION

Basketball

優先候補:

* NBA
* WNBA
* EuroLeague
* EuroCup
* FIBA World Cup
* Olympics
* B.League
* NCAA
* 主要国内リーグ
* 主要大陸大会

competitionごとにPIT・データ粒度・ルール・ロスター・season structureを別評価する。

Volleyball

候補:

* VNL
* World Championship
* Olympics
* Volleyball World events
* SV.LEAGUE
* Italy Serie A1
* Poland PlusLiga
* 主要国内リーグ
* 主要大陸大会

VALORANT

候補:

* VCT Champions
* Masters
* Americas
* EMEA
* Pacific
* China
* Challengers
* Ascension
* Game Changers

大会形式、Bo1/Bo3/Bo5、map構造、ロスター変更を保持する。

UFC / MMA

UFCを独立competition familyとして管理。
他MMA団体を自動統合せず、団体・ルール・データ品質ごとに別評価する。

RIZIN

RIZINは独立競技event familyとして扱う。
公式resultが存在することだけでhistorical PIT production-readyとはみなさない。

Tennis

* ATP
* WTA
* Grand Slam
* tournament
* surface
* round

を階層化する。
surface、round、best-of、retirement、walkoverを正規化する。

F1

* Grand Prix
* Sprint
* Qualifying
* Championship

を別event typeとして保持する。
race finishing positionとqualifying semanticsを混同しない。

Rugby

Rugby union competitionを対象。
リーグ、代表戦、World Cup等をcompetition-specificに管理する。

Boxing

event → bout → weight class → fighterの階層を保持する。
勝敗、draw、NC、technical decision等の結果意味を固定する。

⸻

6. SCOPE LADDER

Scope expansionは必ず以下を通過する。

DISCOVERED
→ METADATA_CHECKED
→ DATA_FEASIBLE
→ PIT_VALIDATED
→ SHADOW
→ OOS/ROBUSTNESS
→ LIMITED_PRODUCTION
→ STABLE_PRODUCTION
→ SCALE_UP

未通過状態をproduction相当として扱わない。

⸻

7. COMPETITION ADMISSION GATES

新competitionのproduction昇格には最低限、

1. Identity integrity
2. Schedule/event integrity
3. Outcome semantics verification
4. Source provenance
5. PIT proof
6. Coverage validation
7. Missingness audit
8. Chronological OOS
9. Calibration
10. Robustness
11. Frozen holdout
12. Reproducibility
13. Recovery test
14. Production artifact validation
15. Monitoring readiness

を要求する。

明確なPIT証拠がない場合はPRODUCTIONではなくDEFERRED/HOLD。

⸻

8. EVENT-TIME CONTRACT

Prediction must be tied to an event.

必須概念:

event_id
event_time
prediction_time
prediction_cutoff
source_available_at
retrieved_at
published_at
revision_time
outcome_time

基本条件:

* event_time must be after prediction cutoff
* source_available_at must be <= cutoff
* later information must not enter earlier prediction
* retrieval time alone does not establish PIT
* future fixture presence alone does not prove historical publication
* revised source must retain revision lineage

⸻

9. PREDICTION HORIZON

既存productionはpre-event predictionを中心とし、30分前予測を主要実装基準とする。

しかし30分を永続的な真理とはみなさない。

Research horizons:

* T-24h
* T-6h
* T-90m
* T-60m
* T-45m
* T-30m
* T-20m
* T-15m
* T-5m

などを研究可能とする。

non-default horizonはpaired chronological OOS、frozen holdout、bootstrap、PIT auditを通過するまでproductionへ入れない。

⸻

10. TEAM / ATHLETE / PLAYER IDENTITY

各participant/entityは最低限、

* stable_id
* canonical_name
* raw_source_name
* source_id
* source URL
* effective_at
* team/association
* role/position/class
* quality_status

を保持する。

Fuzzy matchingはcandidate生成にのみ使用可能。

silent merge禁止。

以下は原則として別entity:

* reserve
* youth
* academy
* national team
* club team
* women’s team
* men’s team
* different roster state
* differently scoped organization

Team change / roster change / name changeを履歴化する。

⸻

11. MATCHDAY INTELLIGENCE

Pre-event predictionではhistorical baselineだけでなく、cutoff時点で取得可能なmatchday intelligenceを研究対象とする。

候補:

* lineup/roster
* starter
* injuries/availability
* suspensions
* recent schedule load
* travel
* venue
* rest
* weather
* market context
* late information
* official updates
* event-level metadata
* source disagreement

ただし「当日情報がある」だけでは有効とはみなさない。

各information sourceについて、

available_at
prediction relevance
incremental value
PIT validity
revision risk
coverage
reliability

を測定する。

⸻

12. TIMING RESEARCH

同一eventに複数cutoffを設けた場合、単純な独立サンプルとして扱わない。

基本構造:

event
├─ T-24h snapshot
├─ T-6h snapshot
├─ T-90m snapshot
├─ T-60m snapshot
├─ T-30m snapshot
└─ T-15m snapshot

をevent clusterとして管理する。

改善が最も大きい時点だけを選ぶのではなく、

* accuracy gain
* LogLoss gain
* calibration
* stability
* information cost
* computation cost
* revision risk
* abstention rate

まで評価する。

⸻

13. DATA COVERAGE DIGITAL TWIN

単純なrow countだけではcoverageを評価しない。

Coverage dimensions:

* competitions
* seasons
* dates
* teams
* athletes
* events
* outcomes
* features
* sources
* timestamps
* publication metadata
* availability metadata
* revisions
* prediction horizons
* regimes
* edge cases

Coverage debtを数量化する。

Coverage gapがperformance gapの原因なのか、model gapなのか、PIT gapなのかを切り分ける。

⸻

14. SOURCE REGISTRY

各sourceはRegistryで管理する。

必須:

* source_id
* provider/owner
* endpoint
* data type
* domain
* upstream owner
* independence
* license
* cost
* coverage
* freshness
* available_at support
* published_at support
* revision behavior
* schema
* parser
* last success
* last failure
* failure rate
* incremental information value
* production status

source countではなくsource valueを評価する。

⸻

15. SOURCE INDEPENDENCE

同じupstream由来の、

* mirror
* wrapper
* scraper
* copied CSV
* republished dataset
* transformed dataset

は独立sourceとして加算しない。

ensemble diversificationにもsource independenceを反映する。

⸻

16. CURRENT DATA REALITY / KNOWN CAVEATS

Basketball

現行監査済み構成ではESPNが主要source。

歴史データにはhoopR系のESPN-derived dataが含まれるため、それを独立vendorとして扱わない。

FIBA系historical coverageは限定的な場合がある。

strict modelは主にgeneric Elo/history/rest系9特徴を軸にする。

現行監査値の一例:

train: 25,686
holdout: 7,246
OOS: 8,991

holdout:

LogLoss ≈ 0.688742
Brier ≈ 0.247783
Accuracy ≈ 0.555755
ECE ≈ 0.029859

これらはhistorical benchmarkであり、将来成績を保証しない。

Volleyball

主要source:

* FIVB VIS
* ESPN

strict generic feature familyを中心とする。

現行監査値の一例:

train: 15,122
holdout: 4,266
OOS: 5,293

holdout:

LogLoss ≈ 0.685229
Brier ≈ 0.246046
Accuracy ≈ 0.564932
ECE ≈ 0.016205

Detailed statisticsはhistorical availabilityが弱い場合があるため、利用可能性をcompetition別に監査する。

UFC

主要source:

* Aristotle API
* UFCStats
* TidyTuesday UFC data系fallback

same-fight post-fight statisticsをpre-fight predictionへ利用してはならない。

strict candidate examples:

* significant strikes
* takedown
* takedown percentage
* submission attempts
* control time

ただしhistorical availability and cutoff must be proven.

現行監査値の一例:

train: 7,293
holdout: 2,058
OOS: 2,553

holdout:

LogLoss ≈ 0.689333
Brier ≈ 0.248065
Accuracy ≈ 0.556851
ECE ≈ 0.036011

RIZIN

公式結果ページを主要referenceとして扱う。

ただし公式historical resultが存在することと、prediction-time availabilityが証明されることは別。

historical PITが未証明ならDEFERRED_PIT。

Tennis

Sackmann ATP/WTA系datasetなどをresearch sourceとする。

mirrorである場合は独立sourceとしない。

historical retrieval timeだけではpublication timeを保証しない。
PIT証明が不十分な歴史データはproduction評価へ使用不可。

F1

候補:

* Jolpica / Ergast-compatible
* OpenF1

source availability timingを検証する。
qualifying、sprint、raceの意味を分離する。

finish positionをwin probabilityへ無条件変換しない。

VALORANT

主要research source:

* VLR
* VLR-derived CSV

VLR-derived CSVはVLRと独立ではない。

strict feature familyは現行実装を基準にする。

現行監査値の一例:

train: 7,265
holdout: 2,050
OOS: 2,543

holdout:

LogLoss ≈ 0.680527
Brier ≈ 0.243716
Accuracy ≈ 0.579512
ECE ≈ 0.006162

Riot / GRID等はdistinct candidate sourceとして調査可能だが、cost、license、availability、PITを必ず確認する。

Rugby

World Rugby official coverage系をreferenceとする。

coverage-onlyの状態ではmodel productionを行わない。

historical availabilityがUNVERIFIABLEならPIT未確立。

Boxing

free/public source candidatesを研究する。

PIT guardを最優先し、PIT未確立eventをproductionへ入れない。

⸻

17. SPORT-SPECIFIC TARGET SEMANTICS

予測targetはsportごとに明文化し、共通binary modelへ無理に統合しない。

必要に応じて、

* win/loss
* draw
* moneyline-like result
* map win
* set win
* bout result
* finishing position
* round/result type

を別targetとして扱う。

Outcome semanticsが曖昧なeventは評価対象外にする。

⸻

18. PREDICTION STATE ECOLOGY

Prediction state:

FRESH
AGING
STALE
UNKNOWN
SHOCKED
REQUIRES_RECALC
ABSTAIN
FALLBACK
INVALIDATED

stateは単純時間経過だけで決定しない。

consider:

* new lineup
* injury
* roster change
* event change
* source update
* market shift
* regime transition
* unexpected information
* disagreement spike
* model degradation
* source failure

⸻

19. UNCERTAINTY

uncertaintyを一種類に統合しない。

最低限、

* aleatoric uncertainty
* epistemic/model uncertainty
* data uncertainty
* source uncertainty
* temporal uncertainty
* regime uncertainty
* OOD uncertainty
* disagreement uncertainty
* outcome ambiguity

を区別する。

各予測にはconfidenceだけでなくuncertainty decompositionを可能な範囲で保持する。

⸻

20. UPSET / TAIL-RISK INTELLIGENCE

低確率側の結果を単純に無視しない。

UPSET riskを、

* prior imbalance
* model disagreement
* recent regime shift
* lineup/roster changes
* source conflict
* unusual schedule
* high variance
* sparse history
* OOD
* calibration instability

から研究する。

upset scoreは「upsetが起きる」と断言するためのものではなく、通常のconfidence過信を検出するrisk layerとして扱う。

⸻

21. PREDICTABILITY

各eventで、

Predictability

どの程度、現在情報から将来outcomeが識別可能か

を推定する。

候補信号:

* model disagreement
* historical entropy
* data completeness
* OOD distance
* regime ambiguity
* recent volatility
* lineup uncertainty
* source conflict
* target stochasticity

Predictability lowの場合は、

* abstain
* wider uncertainty
* safer fallback
* additional information acquisition

を検討する。

⸻

22. CONFORMAL / SELECTIVE PREDICTION

Research対象:

* conformal prediction
* adaptive conformal
* local conformal
* online conformal
* selective prediction
* abstention
* risk-controlling prediction sets

Prediction set coverageだけを最大化しない。

同時に、

* coverage
* set size
* selective risk
* utility
* calibration
* stability
* regime robustness

を評価する。

⸻

23. MATCHDAY DRIFT / CALIBRATION

Matchday-specific dataを追加するcandidateは、

historical base expert
+
matchday expert
+
uncertainty/VOI router
+
temporal recalibration

として研究する。

Candidate calibrators:

* none
* temperature / beta-style
* isotonic
* sigmoid

validationはchronological。

同一event複数snapshotについてevent-cluster dependencyを考慮する。

⸻

24. EVENT-CLUSTER BOOTSTRAP

同一eventの複数prediction snapshotを独立rowとしてbootstrapしてはならない。

bootstrap unitは原則event cluster。

例:

event A
├─ T-60
├─ T-30
└─ T-15

を1clusterとして扱う。

同一eventに由来するcorrelationを無視しない。

⸻

25. OOS STANDARD

Production-quality evaluationはchronological only。

禁止:

* random split
* random K-fold
* future informationのbackfill
* outcome後に生成されたfeatureの使用
* holdoutへのmodel selection
* holdoutへのrepeated tuning
* future source revisionのhistorical insertion

基本:

Train
→ Validation
→ OOS
→ Robustness
→ Frozen Holdout

の時系列を守る。

⸻

26. OOS REQUIREMENTS

各evaluation resultには、

* event_id
* event_time
* prediction_cutoff
* source snapshot
* PIT status
* feature snapshot
* model version
* calibration version
* probabilities
* actual
* metrics
* uncertainty
* prediction state
* error class
* regime
* competition
* data quality status

を保存する。

⸻

27. METRICS

Primary:

* LogLoss

Secondary:

* Accuracy
* Brier
* ECE
* class-wise LogLoss
* class-wise recall/precision
* selective risk
* abstention rate
* top-k metrics
* calibration slope/intercept
* robustness metrics

aggregateだけでなく、

* sport
* competition
* season
* phase
* team tier
* event type
* regime
* confidence bucket
* uncertainty bucket
* horizon
* data completeness
* source combination

単位で分解する。


=== AUTONOMOUS GITHUB EXECUTION CONTROL — V2 ===

目的:
GitHub Actions上でMONITOR→DETECT→TRIAGE→RESEARCH→VERIFY→RECONCILEを自動継続し、手動dispatchを原則不要にする。

制御Plane:
.github/workflows/autonomous_control_plane.yml
src/autonomous_control_plane.py

制御Planeは各3時間で実行され、先にGitHub Actionsの実行状態をsnapshotする。
対象:
* source_feasibility_audit.yml
* scope_autofill.yml
* production_runtime_health.yml
* production_safety_audit.yml
* nine_sport_lane_audit.yml
* autonomous_research_sweep.yml
* 24h_autonomous_research.yml
* pre_event_prediction.yml

Actions状態は、
* MISSING
* IN_PROGRESS
* HEALTHY
* STALE
* FAILED
を区別する。
存在だけを成功証拠とはしない。

自動dispatch対象:
* SOURCE_FEASIBILITY
* SCOPE_AUTOFILL
* RUNTIME_HEALTH
* SAFETY_AUDIT
* LANE_AUDIT
* RESEARCH_HEALTH
* DEEP_RESEARCH

各dispatchには個別cooldownを設定し、active runとの重複を禁止する。
allowlist外Workflowは自動起動しない。

ownership boundary:
* pre-event production heartbeatはproduction watchdogが所有
* PIT History Expansionは00:47/09:47/18:47 UTCの固定9時間cadenceが所有
* Production Failure Recoveryはworkflow_run failure recoveryが所有
* model promotionはproduction release gateだけが所有

control planeは上記boundaryを迂回しない。

Memory:
* results/research/research_queue.jsonl
* results/research/autonomous_action_log.jsonl
* results/research/autonomous_control_plane.json
* results/research/automation_health.json

をGitHub-native memoryとして保持する。

missing-as-zero禁止:
accepted_models、PIT exact evidence、experience、route state等の欠損はUNKNOWN/UNVERIFIABLEとして扱い、0へ変換しない。

promotion safety:
* automatic model promotion = false
* frozen holdout tuning = forbidden
* PIT bypass = forbidden
* scope implicit activation = forbidden

mutable write safety:
自動commit前後でcurrent main SHAを再確認し、concurrent updateがあればfail closedする。

完成状態:
control planeのGREENはreconciliation/automation safetyの成功だけを意味し、
PERFORMANCE_VERIFIED、ADOPTED、PRODUCTION、STABLEを意味しない。
OOS、PIT、calibration、robustness、frozen holdout、release gateは既存契約を維持する。


=== PIT EVIDENCE AUTOMATION HARDENING — 2026-10-04 ===

目的:
GitHub ActionsだけでPIT証拠の不足・外部source制約を明示的に処理し、手動介入を減らしながらPIT fail-closedを維持する。

B.LEAGUE exact PIT bridge:
* 固定PIT History Expansion内で、先に既存のGit provenanceを記録した後に実行する。
* 対象は既登録のRESEARCH_EVIDENCE_ONLY証拠に限定する。
* games_summary_202021.csvのrevision SHA、games_202021.csvの同一revision、canonical event ID、participant解決を同時に検証する。
* source_available_at_utcは登録済みの保守的publication boundだけを使用し、retrieval timeをPIT証拠にしない。
* canonical eventが不足、participantが曖昧、exact rowが0件の場合はAPPLIED扱いにせず失敗する。
* materialization成功はPIT evidenceの局所改善であり、OOS、robustness、frozen holdout、production promotionを意味しない。

F1 OpenF1 deferred-PIT classification:
* historical backfillのHTTP 401/403を明示記録する。
* total=0、skipped=0、failedが全て401/403の場合のみDEFERRED_PITとする。
* 500系、network error、unknown status、partial success、skipありはDEFERRED_PITにせずfail-closedする。
* 毎回results/f1_openf1_backfill.jsonへ状態を保存し、失敗を隠さない。

安全条件:
* automatic model promotion = false
* frozen holdout tuning = forbidden
* PIT bypass = forbidden
* missing = zero conversion = forbidden
* materialization/report status != performance verification


=== AUTONOMOUS DISPATCH ORDERING SAFETY ===

control planeの安全順序は、
RECONCILE
→ PERSIST CURRENT CONTROL STATE
→ CAPTURE RESULTING MAIN SHA
→ RECHECK REMOTE MAIN
→ DISPATCH ALLOWLISTED WORKFLOW
とする。

状態commitをdispatch後に置いてはならない。dispatch先Workflowが旧main SHAで開始されるraceを防ぐ。

persist前後またはdispatch直前にmainが変化した場合はFAIL CLOSEDとし、次回のcontrol cycleで再評価する。dispatch eligibilityとcooldown判定は、control-plane invocation時のgithub.shaではなく、reconciled current main SHAを基準とする。

このordering safetyはautomation integrityのためのものであり、performance verification、OOS、PIT validation、holdout、production approvalを意味しない。


=== CURRENT-MAIN ACTIONS EVIDENCE GATE ===

Actions health evidence is valid only when the latest observed run `headSha` matches the current control-plane `GITHUB_SHA` (the reconciled main SHA used for the cycle). A successful run on an older commit is classified STALE, not HEALTHY, so autonomous dispatch never relies on stale success evidence.

SHA mismatch is separate from workflow failure. The health payload records both `head_sha` and `current_main_sha`, plus an explicit `sha_match` field when both are verifiable.

=== FAILURE-MEMORY-AWARE CONTROL PLANE ===

Failure Memoryは単なる保存先ではなく、次researchのevidence inputとして扱う。

control planeは毎cycle、append-only failure_memory.jsonlを読み、
* recent_24h
* recent_7d
* failure_class
* latest failure
を監査する。

recent failureが存在する場合、観測済みfailureをroot-cause researchへ変換するRESEARCH_HEALTH candidateをpriorityへ追加する。これはproduction retryやpromotionではない。

Failure Recoveryのownershipは変更しない。Production Failure Recoveryはworkflow_runとしてretry/fresh-current-main recoveryを担当し、control planeはその結果を研究priorityへ反映するだけとする。

=== PUSH-TRIGGERED CURRENT-MAIN RECONCILIATION ===

When `autonomous_control_plane.yml` is invoked by a `push` to `main`, the triggering commit is accepted for reconciliation only when it is the current remote `main` SHA or a verified ancestor of the current remote `main` SHA. The workflow resolves and checks out the latest remote `main` before inspection, and compares the push SHA against the resolved main. A diverged or unverifiable push is fail-closed. Scheduled and manual invocations retain strict exact-SHA matching.

Deterministic control-plane persistence is gated on successful current-main resolution. A failed or stale resolution therefore cannot run persistence against an unset current-main SHA and create a secondary error that obscures the primary provenance failure.


=== EVENT-TRIGGERED CURRENT-MAIN RECONCILIATION ===

workflow_run failure event受信時も、まずremote main SHAを解決し、そのcurrent mainをcheckoutしてからcontrol planeを評価する。

event_head_sha == current_main
または
event_head_shaがcurrent mainのverified ancestor
の場合のみevent failureをRESEARCH_HEALTH signalとして扱う。

ancestor判定はGitHub compare APIのaheadを利用し、diverged/behind/unknownはfail-closed。
scheduled/manual runは従来どおりgithub.sha == current mainを要求する。

Failure Memoryが先にmainを進めた場合でも、triggering failure eventを失わず、current main上で安全にresearchへ接続する。
automatic model promotion、PIT bypass、holdout tuningは変更しない。


Failure Memoryは単なる保存先ではなく、次researchのevidence inputとして扱う。

control planeは毎cycle、append-only failure_memory.jsonlを読み、
* recent_24h
* recent_7d
* failure_class
* latest failure
を監査する。

recent failureが存在する場合、観測済みfailureをroot-cause researchへ変換するRESEARCH_HEALTH candidateをpriorityへ追加する。これはproduction retryやpromotionではない。

Failure Recoveryのownershipは変更しない。Production Failure Recoveryはworkflow_runとしてretry/fresh-current-main recoveryを担当し、control planeはその結果を研究priorityへ反映するだけとする。

Actions evidenceはdispatch allowlistとmonitor-only workflowを分離する。production、PIT History Expansion、Production Failure Recovery、Production Watchdog、Production Invariants、Lightweight Regressionは監視対象だが、自動dispatch許可対象ではない。

JSONL破損、timestamp不正、memory欠損はUNKNOWN/DEGRADEDとして記録し、failure件数を0に偽装しない。


=== EVENT-DRIVEN FAILURE TRIAGE ===

control planeは3時間cronだけを待たず、Production、Pre-Event Adaptive Timing Prediction、PIT History Expansion、Production Failure Recovery、Autonomous Research Sweep、Autonomous Control Plane Regressionのcompleted failure eventを直接受ける。

failure / timed_out / startup_failure / cancelled:
→ current-main SHA確認
→ workflow_run payloadをfirst-class evidenceとして保持
→ Failure Memory未記録でもbounded RESEARCH_HEALTHへ変換
→ Production Failure Recoveryのretry ownershipは変更しない。

event head SHAがcurrent mainと一致しない場合はFAIL CLOSEDとし、fresh current-main regressionとして扱わない。success eventはfailure triageを起動しない。automatic model promotion、PIT bypass、frozen holdout tuningは引き続き禁止。


=== CONTROL-PLANE NO-CHURN PERSISTENCE ===

制御Planeのstate fingerprintは「観測されたworkflow runの実体」と「選択されたdecision」を表し、invocation/current-main SHA、wall-clock由来のage_hours、そこから導出されるstale/status/sha_match/current_main_shaはfingerprintから除外する。

stable evidence:
* run_status
* workflow run head_sha
* conclusion
* run_id
* release / quality / future / experience / route / timing / failure-memory
* selected decision

同一evidenceでcontrol plane自身がmainを1 commit進めた場合でも、次cycleにself-commitを連鎖させない。action logもstable fingerprintの変化時だけappendする。

ただし、current-main SHAの検証、persist直前のremote main再確認、dispatch直前のremote main再確認は引き続き必須。no-churnは安全gateを弱めるものではない。

=== TEMPORAL TRAJECTORY INTELLIGENCE — RESEARCH ONLY ===

AUTOMATION:
`.github/workflows/autonomous_temporal_trajectory_loop.yml` runs on a recurring schedule and after successful canonical production/pre-event runs. Five active sports are collected in parallel from restored GitHub Actions database caches. A single merge writer reconciles against the newest main, deduplicates snapshot/outcome ledgers, reruns chronological OOS, and commits only when persistent evidence changes.
Cache boundary:
* The canonical production collector cache is a seed for later collection and is not treated as trajectory evidence merely because `event` rows exist.
* The trajectory loop restores `trajectory-ready-db-v1-*` first. This cache is produced only after the production merge reaches the post-`Outcomes`/post-`Strict PIT replay` stage and has verified completed events, numeric match statistics, and exact source availability metadata.
* Verified final outcome is not required merely to preserve an in-event snapshot. Snapshot coverage and outcome coverage are separate debts: PIT-valid snapshots may be accumulated before final outcome verification, while OOS remains BLOCKED until a canonical VERIFIED A/B outcome is attached.
* The pre-merge active-scope cache is publication-gated by collection-guard status and non-empty event coverage so an explicitly deferred lane does not poison the next seed.

The loop uses sport-specific horizons rather than a universal forecast horizon: VALORANT 60/180/300/600s, Basketball 120/300/600/1200s, Volleyball 60/180/300/600s, UFC 60/120/300/600s, RIZIN 60/120/300/600s. This is a research policy, not a production release decision.

Experience single-writer continuity:
* `.github/workflows/pre_event_prediction.yml` uploads each sport lane's prediction/settlement archive as an artifact, then a dedicated `persist_experience` job becomes the only writer for `results/experience/**` and the derived research-memory artifacts.
* The writer restores the newest `main`, merges all current-run sport artifacts deterministically, rejects conflicting IDs/malformed records, and retries up to three times when `main` advances concurrently. It never treats a stale push as success.
* GitHub Artifact path flattening is handled explicitly, so both `results/experience/predictions/**` and flattened `predictions/**` layouts are accepted.
* The durable archive is append-only by `prediction_id`; same IDs with different content are fail-closed. This prevents per-sport matrix jobs from racing on shared state and allows Experience memory to accumulate every successful prediction cycle rather than waiting for the six-hour research sweep.
* No Experience persistence changes production models or bypasses PIT/OOS/holdout/promotion gates.

Autonomous research-memory continuity:
* `src/experience_learning.py` recomputes settlement-derived memory every research sweep but preserves the prior artifact when the substantive knowledge state is unchanged, so wall-clock generation timestamps do not create false progress or commit churn.
* `src/experience_research_bridge.py` applies the same idempotent persistence rule to prospective research candidates.
* `.github/workflows/autonomous_research_sweep.yml` may persist these two research artifacts to `main` only when their substantive state changes and must re-check the current `main` SHA immediately before push.
* `.github/workflows/autonomous_control_plane.yml` listens for research-sweep failures so an observed failure can enter bounded failure triage without waiting for the next scheduled control cycle.
* This persistence is research-memory only; it never changes production models, bypasses PIT/OOS gates, or grants automatic promotion.

Control Plane integration:
`TRAJECTORY_RESEARCH` is a bounded recovery action. Missing/stale/failed trajectory evidence can be re-dispatched by the autonomous control plane. Failure events remain fail-closed and never grant model promotion or frozen-holdout access.


目的:
最終勝敗だけを予測するのではなく、prediction cutoff時点の状態から、その後の状態軌跡・複数horizon・複数未来scenarioを予測し、最終outcome predictionへ接続する。

実装:
* src/trajectory_intelligence_oos.py
* scripts/trajectory_research_runner.py
* tests/test_trajectory_intelligence_oos.py
* config/TEMPORAL_TRAJECTORY_POLICY.json
* .github/workflows/autonomous_temporal_trajectory_loop.yml

TemporalTrajectoryEngineはcomplete historical trajectory retrievalを使い、autoregressiveな自己予測連鎖をresearch baselineとする実装を避ける。過去eventのfuture-state pathを条件付きで再利用することで、horizon間の相関を保持する。

Snapshot contract:
* event_id
* event_time_utc
* prediction_time_utc
* source_available_at_utc
* feature_vector = prediction cutoff時点で利用可能な入力のみ
* observed_state_vector = 未来trajectoryの教師labelとしてのみ使用
* in_event modeではevent_end_time_utcを必須とする

PIT gate:
* source_available_at_utc <= prediction_time_utc
* pre_event modeではprediction_time_utc < event_time_utc
* in_event modeではevent_time_utc <= prediction_time_utc < event_end_time_utc
* missing/invalid/unknown PITはINVALID/FAIL CLOSED
* retrieval timeだけではPIT proofとしない

Trajectory case:
* 複数snapshotは同一event clusterとして保持する。
* 評価時はcanonical anchorを1event 1caseへ正規化する。
* future snapshot featureはanchor featureへ流用しない。
* future stateはlabelとしてのみ使用する。

Forecast output:
* horizon別expected state
* state P10/P90
* horizon別outcome probability
* scenario event IDs / weights
* nearest distance
* geometry/support由来のpredictability score

Evaluation:
* chronological event-cluster OOS
* random splitは禁止
* 同一event snapshotを独立sampleとして数えない
* state trajectory誤差をhorizon別MAEで評価
* outcomeはLogLoss/Brier/Accuracyで評価
* fold別改善と全体改善を分離して保存
* frozen holdoutはselector/trajectory tuningに使用しない

Production policy:
* 本層はRESEARCH_ONLY。
* production model / champion / frozen holdout / release gateを直接変更しない。
* automatic promotionはfalse。
* PIT trajectory dataが存在しない場合はBLOCKEDとし、精度を捏造しない。
* OOS、robustness、frozen holdout、production safetyを通過するまでproduction inferenceへ接続しない。

Coverage priority:
まずactive five sportsについて、competition/season/eventごとの複数cutoff snapshotをPIT付きで蓄積する。data coverageが不足する場合はmodel complexityを増やすのではなく、trajectory snapshot coverage debtを研究queueへ送る。

時間軸候補:
* T-24h / T-6h / T-90m / T-60m / T-45m / T-30m / T-20m / T-15m / T-5m
* event-triggered update
* in-event state snapshots（event_end_time_utcが証明できる場合のみ）

この層の成功条件は「時間ごとの予測を大量生成した」ではない。未知eventでのFuture Generalization、Case-Level Correctness、Calibration、Predictability Awareness、Uncertainty、Robustness、PIT Integrityが改善したことをchronological OOSとfrozen holdoutで証明することを要求する。


61. END-TO-END SPORT PREDICTION MODELING BLUEPRINT

本Projectは、単純なwinner classifierを最上位概念とせず、prediction cutoff時点の観測情報から潜在状態を推定し、その状態・相手・可用性・戦術から将来の試合状態と結果分布を生成する構造を研究上位設計として採用する。

中核概念:

P(Y|X) = ∫ P(Y|Z,X) P(Z|X) dZ

X = cutoff時点でPIT証明された情報、Z = 観測できない現在のteam/player/game state、Y = 将来event outcome。

推奨する研究分解:
Data → Identity/PIT → State Estimation → Player State → Availability/Lineup → Matchup/Interaction → Sport-specific Event Generator → Joint/Scenario Simulation → Calibration → Uncertainty/Predictability → Selective Decision → Outcome → Experience → Failure Analysis → Research.

Stateは単一Strengthではなくsport-specific vectorとして扱う。例えば攻撃/守備、先発/打撃/救援、half-court/transition/shooting、serve/return等に分解し、long-term priorとrecent evidenceをsample-size-aware shrinkageで統合する。

PlayerStateは概念上 BaseSkill + Form + Health + Role + Fit とし、怪我・疲労・復帰・加齢効果を必要に応じてcomponent別に扱う。欠場を一律固定ペナルティにしない。

Availability/Lineupは確率変数として扱い、複数lineup scenarioをsimulationへ伝播させる。Lineupが不確実なのに単一固定lineupを仮定しない。

MatchupはStrength_Aの絶対値ではなくStrength_A(B)のような相手依存の関数を優先し、ability × opponent weakness/strength、role compatibility、lineup chemistry等の相互作用を候補とする。

試合モデルはsport-specific state transition/generative processとして設計する。footballのscore/tactical state、baseballのinning/base-out state、basketballのpossession state、tennisのpoint→game→set state等を例とし、必要ならMarkov/semi-Markov/point-process/hazard等を比較する。Markov性は仮定ではなく検証対象とする。

期待値だけではなくvariance・tail・joint distributionを扱う。依存する出力をP(X)P(Y)へ機械的に分解せず、joint behaviorを必要に応じて階層モデル・latent factor・multivariate distribution・copula-like構造等で研究する。

Monte Carloはlineup、latent state、context、game-state transitionをまとめてsamplingし、勝率だけでなくscore distribution、first-event probability、tail scenario等を導出する。simulationは同じevent内の依存関係を維持する。

Uncertaintyは少なくともdata uncertainty、model uncertainty、intrinsic sport randomnessへ分け、confidenceとは別にpredictability、model disagreement、OOD、source reliability、regime transition、upset risk、forecast ageを記録する。

Prediction Stabilityは入力perturbation/snapshot間のprobability変化として評価し、Adversarial/Monotonicity/Counterfactual testingを診断用途で行う。予測上のcounterfactual差分をcausal effectとして報告しない。

追加情報の取得自体もdecision problemとし、VOI / information gain、latency、source reliability、cost、event proximity、disagreement、stale riskから PREDICT_NOW / ACQUIRE_MORE / WAIT / RECOMPUTE / FALLBACK / ABSTAIN を選択する。

Live predictionではpre-event forecastをpriorとして扱い、P(theta|Data_1:t)を実観測stateに応じて逐次更新する。初期少sampleのlive noiseでpriorを過度に上書きしない。

EvaluationではLogLoss/Brier/Accuracy/ECEだけでなく、calibration、sharpness、selective risk、event-cluster dependency、latest period、regime、OOD、upset-heavy cases、data-quality strataまで分解する。Conceptual blueprintのどのcomponentも、PIT/OOS/robustness/frozen holdoutを通過しない限りproduction adoptionを意味しない。

実装順序は、PIT/identity/event contract → baseline → latent strength → availability/lineup → matchup → event simulation → calibration → uncertainty/predictability → sensitivity/counterfactual/VOI → live update → advanced neural/graph/vision を原則とする。complexityは測定されたFuture Generalization improvementによって正当化する。

詳細な再現可能設計は docs/PREDICTION_MODELING_BLUEPRINT.md をcanonical research-design referenceとして使用する。これは既存のproduction gate、PIT hard gate、scope registry、champion/challenger、frozen holdout firewall、automatic promotion禁止を置き換えない。

62. PROBABILISTIC STATE CORE

src/probabilistic_state_core.py は、全スポーツへ直接production接続するものではなく、sport-specific generative researchの共通数学層として扱う。

提供するprimitive:
* effective sample-size-aware shrinkage
* component-wise latent state blending
* matchup interaction diagnostics
* scenario-mixture probability propagation
* law-of-total-variance decomposition
* local probability sensitivity
* expected information gain
* immutable normalized scenario representation
* cluster-dependent effective sample size diagnostic
* decision expected-utility / abstention diagnostic
* information-action value after acquisition cost

この層の目的は、Current Strengthを単一勝敗率へ短絡させず、observed evidence → latent state → matchup → uncertain scenarios → outcome distributionという研究構造を共通化すること。

重要な境界:
* 本moduleのresearch-only出力はproduction model promotion evidenceではない。
* sport-specific callerはcanonical event identity/PIT validation後にのみ使用する。
* 単純blendは最終モデル形ではなくbaseline/diagnosticとして扱う。
* state-space, Bayesian, particle, neural, graph等の高度モデルはlocal OOS/robustnessで比較する。
* repeated snapshotsは情報量を水増しするためevent-cluster単位で評価する。
* uncertaintyはwithin-event randomnessとbetween-state/model uncertaintyを分離する。
* VOIは情報量の診断であり、source query actionそのものはreliability/latency/cost/utilityを含むdecision layerで別途決定する。

63. ADVANCED STATISTICAL VALIDATION

latent state candidateではfilteringとretrospective smoothingを区別する。prediction-time stateにはfuture observationを入れず、smoothingはhistorical diagnosticに限定する。

candidate比較では nominal rowsだけでなく unique events, event-cluster count, effective sample size, fold variance, confidence interval, effect size, replication statusを保存する。

大量candidateを並列評価するautonomous researchではmultiple-comparison riskを明示し、単一foldの改善や閾値到達だけを採用根拠にしない。

rare-event/upset/OOD/regime-transition/high-confidence failureのtail slicesを標準評価へ追加し、平均LogLossだけで見逃される破綻を監視する。

prediction utilityとforecast qualityを分離する。proper scoring rule上の改善がdecision utility改善を意味するとは限らないため、selective risk、abstention、regret等を必要な研究で追加評価する。

64. MODEL COMPLEXITY ORDER

実装優先順位は、PIT/identity/event contract → baseline → latent state → availability/lineup → matchup → event generator → calibration → uncertainty/predictability → sensitivity/counterfactual/VOI → live sequential update → advanced neural/graph/vision とする。

complexityは実装量ではなく、local chronological OOS、robustness、frozen holdout、operational reliabilityを伴うFuture Generalization改善によって正当化する。

65. STATUS BOUNDARY

現時点でprobabilistic_state_coreはIMPLEMENTED/RESEARCH_ONLYであり、production model, champion, challenger promotion stateを変更しない。CI testがPASSしてもPERFORMANCE_VERIFIEDやPRODUCTIONを意味しない。

77. AUTONOMOUS CONTROL-PLANE WATCHDOG

The control plane is not allowed to depend solely on a scheduled invocation. A dedicated GitHub Actions watchdog runs twice per hour and checks:

- current remote main SHA
- durable control-plane state presence and provenance
- control-plane state age
- active control-plane runs

If durable state is missing, provenance-stale, timestamp-invalid, or older than the recovery threshold, and no recent/active control-plane run can explain the state, the watchdog dispatches the control plane against the current main SHA.

The watchdog is recovery-only. It does not modify production models, bypass PIT, tune frozen holdout, or promote candidates. It re-checks the remote main immediately before dispatch and fails closed on SHA drift.
