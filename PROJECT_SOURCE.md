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
