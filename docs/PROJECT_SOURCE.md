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

現行productionはpre-event predictionを中心とし、T-60分を主要実装基準とする。これは現在の `config/PREDICTION_TIMING_POLICY.json` と canonical production/pre-event workflow に一致する。

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

⸻

28. CALIBRATION

Calibrationはaccuracyと別軸で評価する。

評価:

* ECE
* reliability curve
* calibration slope
* calibration intercept
* Brier
* LogLoss
* subgroup calibration
* temporal calibration drift

Calibrationはvalidation-onlyで選択し、frozen holdoutへ再調整を持ち込まない。

⸻

29. BASELINES

各sport/competitionに適切なbaselineを維持する。

候補:

* class frequency
* persistence
* Elo
* simple logistic
* simple rating
* naive probability
* competition-level prior

complex modelがbaselineを継続的に上回らない場合、complexityを正当化しない。

⸻

30. MODEL ECOLOGY

単一championだけでなく、

* generalist
* sport expert
* competition expert
* regime expert
* recent-data expert
* long-memory expert
* calibration expert
* uncertainty expert
* selective expert
* fallback expert

を競争させる。

RouterはOOSで選択。

⸻

31. ROUTING

Routing candidate:

sport
→ competition
→ level
→ regime
→ recentness
→ uncertainty
→ data completeness
→ event type

ただし過分割を禁止。

小sampleでは上位scopeへfallbackする。

Hierarchical fallback:

specific
→ competition
→ sport
→ global

scope minimum data requirementsを明示する。

⸻

32. FEATURE LINEAGE

各featureは、

feature_id
source
source_available_at
transformation
cutoff
version
quality
missingness
revision behavior

を追跡可能にする。

Feature valueだけを保存してlineageを失わない。

⸻

33. MISSING DATA

missing ≠ zero。

分類:

* unavailable
* not applicable
* unknown
* delayed
* malformed
* source failed
* not yet public
* structurally absent

critical feature missing時は、

* fallback
* abstain
* deferred
* fail-closed

のいずれか。

silent zero禁止。

⸻

34. FAILURE TAXONOMY

失敗をaggregate errorだけで終わらせない。

分類:

* data missing
* PIT violation
* timestamp issue
* identity mismatch
* stale prediction
* source failure
* feature failure
* model failure
* calibration failure
* regime failure
* OOD failure
* disagreement failure
* uncertainty underestimation
* scope failure
* recovery failure
* automation failure
* reporting failure

各failureはFailure Memoryへ保存する。

⸻

35. EXPERIENCE MEMORY

成熟outcomeが得られたeventについて、canonical recordを生成する。

同一eventで複数snapshotがある場合も、

経験学習に同一eventを無制限に重複計上しない。

canonicalization policy:

* stable event_id
* latest valid pre-cutoff prediction per defined policy
* outcome
* prediction state
* prediction horizon
* model
* calibration
* error type
* regime
* data status
* source status

を保存する。

⸻

36. FAILURE ANALYSIS

各失敗について、

What happened?
When?
What information was available?
What information was missing?
What did models disagree on?
Was the event predictable?
Was confidence miscalibrated?
Was the source stale?
Was there regime change?
Was there OOD?
Was a better model family available?
Would additional information have helped?
Would abstention have helped?
Would fallback have helped?

を調査する。

⸻

37. COUNTERFACTUAL FAILURE ANALYSIS

Failure caseごとに、

* better data
* better timing
* better model
* better calibration
* better routing
* additional source
* abstention
* fallback
* different competition scope

のどれが改善余地だったかを評価する。

Counterfactual conclusionsは実測と仮説を分離する。

⸻

38. RESEARCH ROUTER

研究内容を以下へ分類する。

DIRECT_SEARCH
METHOD_SEARCH
FAILURE_SEARCH
COUNTEREXAMPLE_SEARCH
IMPLEMENTATION_SEARCH
BENCHMARK_SEARCH
NEGATIVE_EVIDENCE
FRONTIER_SEARCH
CROSS_DOMAIN_TRANSFER
UNKNOWN_UNKNOWN_SEARCH

既知手法の追加だけでresearchを埋めない。

⸻

39. RESEARCH PORTFOLIO

研究Budgetを、

* Exploit
* Adjacent
* Frontier
* Replication
* Ablation
* Adversarial
* Recovery
* Meta-research

へ配分する。

単一アイデアへの過剰集中を防ぐ。

⸻

40. RESEARCH INGESTION

External researchは、

DISCOVERED
→ SOURCE_VERIFIED
→ METHOD_ABSTRACTED
→ RELEVANCE_CHECKED
→ COST_CHECKED
→ PIT_CHECKED
→ LOCAL_EXPERIMENT
→ LOCAL_REPRODUCTION
→ OOS
→ ROBUSTNESS
→ ACCEPT/HOLD/REJECT

の順序を基本とする。

「論文に書いてある」「他repositoryで高精度」はproduction evidenceではない。

⸻

41. KNOWLEDGE EVIDENCE LEVEL

Evidence level:

E0 = idea only
E1 = external claim
E2 = external implementation
E3 = local reproduction
E4 = local OOS evidence
E5 = robustness evidence
E6 = frozen holdout evidence
E7 = production evidence

Evidence levelを過大評価しない。

⸻

42. NEGATIVE KNOWLEDGE

失敗した研究も永続化する。

保存:

* rejected method
* failure reason
* dataset
* cutoff
* metric delta
* computational cost
* PIT issue
* robustness failure
* conditions where it failed

同じ失敗を繰り返さない。

⸻

43. FRONTIER SCANS

定期的に以下を走査する。

Data Frontier
Research Frontier
Failure Frontier
Coverage Frontier
Unknown Frontier
Source Frontier
Method Frontier

目的はscopeを無限拡張することではなく、現在systemの限界を発見することである。

⸻

44. COVERAGE DEBT

Coverage debtを、

* missing competitions
* missing seasons
* missing historical snapshots
* missing lineup data
* missing availability metadata
* missing athlete/team identity
* missing source provenance
* missing outcome detail

などに分解する。

Coverage debtが高いときにmodel complexityだけを増やさない。

⸻

45. SOURCE VALUE / INFORMATION VALUE

sourceの追加価値はsource数ではなくincremental informationで測る。

評価対象:

* accuracy gain
* LogLoss gain
* calibration gain
* uncertainty reduction
* OOD detection
* failure avoidance
* prediction timing gain
* compute cost
* reliability
* coverage
* revision risk

⸻

46. INFORMATION ACQUISITION POLICY

Prediction時に常に「さらに情報を取る」ことを正解としない。

Action候補:

PREDICT_NOW
ACQUIRE_MORE
WAIT
RECOMPUTE
FALLBACK
ABSTAIN

判断要素:

* expected information value
* latency
* source reliability
* cost
* event proximity
* disagreement
* stale risk
* uncertainty

⸻

47. FORECAST LIFETIME

Predictionにはfreshness/lifetimeを持たせる。

新情報到着、lineup変更、source revision、regime changeなどでlifetimeを短縮する。

STALE予測をproduction artifactとして永続利用しない。

⸻

48. ADAPTIVE COMPUTE

Compute budgetを固定的に大量投入しない。

高uncertainty/high-value eventには追加compute。
low-value/low-information eventでは軽量route。

cache →
incremental →
deduplicate →
vectorize →
parallel I/O →
selective recomputation →
training optimization →
algorithm optimization

の順に効率化する。

⸻

49. CROSS-PROJECT TRANSFER

他prediction projectから知見を転用するときは、

DISCOVER
→ ABSTRACT_MECHANISM
→ COMPATIBILITY
→ ADAPT
→ LOCAL_PIT
→ LOCAL_OOS
→ LOCAL_HOLDOUT
→ SHADOW
→ PROMOTE

を必須とする。

他domainの結果をそのままproductionへコピーしない。

⸻

50. EXTERNAL INTELLIGENCE TRANSLATION

外部AI、GitHub、論文、OSS、公開API等はそのままproduction dependencyにしない。

外部情報
→ mechanism
→ local implementation
→ local tests
→ PIT validation
→ OOS
→ robustness
→ release gate

へ変換する。

ChatGPT-only / proprietary connector-only capabilityは、GitHub Actionsで再利用可能なAPI/CLI/OSS/local implementationへ翻訳できない限りresearch/advisory only。

⸻

51. COST FIREWALL

優先順位:

1. Verified free
2. Free quota
3. OSS/local
4. Cached snapshot
5. lightweight computation

paid-only
billing risk
unknown cost
trial auto-renewal
quota overage

は自動production利用禁止。

cost不明 = HOLD / UNCONFIRMED。

⸻

52. AUTOMATION RELIABILITY

Long-running GitHub Actionsは以下を実装する。

* checkpoint
* resume
* idempotency
* retry
* exponential backoff
* watchdog
* heartbeat
* stale-run detection
* bounded execution
* artifact preservation
* deterministic writes
* concurrency control
* recovery
* rollback

同じjobの重複実行による計算 wasteを防ぐ。

⸻

53. SINGLE-WRITER POLICY

Critical state:

* production registry
* promotion state
* rollback state
* canonical experiment registry
* canonical experience ledger
* source registry
* scope registry

にはsingle-writer semanticsを優先する。

並列researchは可能だがcritical state mergeはdeterministicに行う。

⸻

54. CACHE / REPRODUCIBILITY

同一snapshot、同一config、同一code、同一experiment fingerprintなら再利用可能なartifactを再計算しない。

Experiment fingerprint候補:

* git commit
* dataset hash
* source snapshot
* feature version
* model config
* calibration config
* seed
* code version
* environment
* cutoff policy

⸻

55. DETERMINISTIC REPLAY

保存artifactだけで可能な限り、

input snapshot
→ feature
→ model
→ probability
→ calibration
→ decision

を再現可能にする。

再現不能なproduction resultはProduction Evidenceとして格下げする。

⸻

56. ADVERSARIAL VALIDATION

最低限、

* PIT attack
* leakage attack
* future timestamp injection
* source removal
* feature deletion
* time shift
* distribution shift
* regime shift
* missingness
* outlier
* rare event
* new competition
* unseen participant
* stale source

を定期検査する。

⸻

57. ROBUSTNESS

Candidate modelが平均OOSで良くても、

* latest holdout
* recent periods
* high volatility
* upset-heavy events
* new competition
* sparse data
* missing feature state
* source outage
* distribution shift

で破綻するなら無条件採用しない。

⸻

58. ADOPTION GATES

Candidate採用では少なくとも、

* same OOS observations
* chronological integrity
* PIT=valid
* leakage audit clean
* reproducibility
* robustness
* calibration not degraded materially
* newest holdout not worsened
* sufficient sample size
* statistical uncertainty considered
* computation cost acceptable
* operational safety

を確認する。

参考benchmarkは、

* primary OOS relative improvement ≥3%
* auxiliary improvement ≥1%
* ≥70% evaluation periods without worsening
* newest holdout no worsening
* calibration no material degradation or meaningful improvement
* PIT violations = 0

をcandidate thresholdとして利用可能。

ただしsample size、variance、confidence interval、event dependence、rare-event structure、economic/operational costを必ず併記し、thresholdだけで自動採用しない。

⸻

59. FROZEN HOLDOUT FIREWALL

Frozen holdoutはmodel selectionに使用しない。

holdoutを繰り返し見て、

* feature tuning
* model tuning
* threshold tuning
* calibration tuning
* scope tuning

を行ってはならない。

holdout accessはrelease-stageに限定し、config freeze後に評価する。

⸻

60. PRODUCTION BUNDLE

Production releaseは少なくとも、

* model artifact
* feature version
* calibration artifact
* source registry state
* PIT policy
* target specification
* config
* git commit
* dataset/snapshot hash
* experiment lineage
* validation result
* robustness result
* holdout result
* release decision
* rollback pointer

を含む。

⸻

61. PRODUCTION SAFETY

production predictionはfail-closedを基本とする。

critical failure時:

INVALIDATED
→ FALLBACK / ABSTAIN / DEFERRED

とし、

missing data
source failure
unknown PIT
identity mismatch
stale artifact
missing model registry

を適当に補完してpredictionを出さない。

⸻

62. SAFE DEGRADATION

主モデル停止時に備え、

Champion
→ Specialist
→ Generalist
→ Baseline
→ Abstain

のfallback chainを明示する。

fallback利用事実をprediction event logに保存する。

⸻

63. MONITORING

productionでは、

* data freshness
* source health
* coverage
* missingness
* prediction frequency
* uncertainty
* disagreement
* calibration drift
* regime drift
* OOD rate
* abstention rate
* fallback rate
* error rate
* recovery rate

を監視する。

⸻

64. POLICY REGRET

次のregretを測定する。

* Model Regret
* Timing Regret
* Information Regret
* Scope Regret
* Policy Regret
* Research Regret

例:
「30分前に取得した情報が有効だったか」
「追加取得をしなかったことで性能低下したか」
「specialistではなくgeneralistを使うべきだったか」
などを後から検証する。

⸻

65. RESEARCH STOPPING

研究は無限に実行しない。

停止条件候補:

* no meaningful incremental value
* repeated negative result
* compute cost too high
* insufficient data
* unresolved PIT
* robustness failure
* duplicated mechanism
* frontier saturated

ただし停止状態でも将来source/data/method変化で再開可能にする。

⸻

66. SELF-EVOLUTION

Project Source自体を進化対象とする。

detect:

* missing rule
* contradiction
* obsolete assumption
* recurring failure
* ineffective workflow
* unnecessary computation
* new validated mechanism

↓

propose change
→ consistency check
→ historical impact analysis
→ implementation
→ test
→ OOS validation
→ holdout/release validation
→ adopt/reject

過去の成績を改善して見せるためにhistorical recordを改変してはならない。

⸻

67. RESULT PRESENTATION CONTRACT

作業報告では、performance変化があった場合、明示的な指示がなくても自動表示する。

最低限:

Current Champion
Prior Champion
New Candidate
OOS ΔLogLoss
OOS ΔBrier
OOS ΔAccuracy
ECE/calibration Δ
Latest Holdout Δ
Robustness Δ
PIT status
Failure status
Production status

を可能な範囲で表示する。

「改善した」という文章だけで終わらせず、比較対象、評価期間、sample sizeを示す。

⸻

68. STATUS TAXONOMY

必ず明確に区別する。

IMPLEMENTED
EXECUTED
VERIFIED
PERFORMANCE_VERIFIED
PROMOTION_CANDIDATE
ADOPTED
PRODUCTION
STABLE
HOLD
REJECTED
FAILED
BLOCKED
DEFERRED
ROLLED_BACK
UNKNOWN
UNVERIFIABLE
SUPERSEDED
RETIRED

codeが存在するだけでADOPTEDとは書かない。
green CIだけでPERFORMANCE_VERIFIEDとは書かない。

⸻

69. NO-FAKE-SUCCESS POLICY

禁止:

* fabricated metrics
* missing value → zero
* hidden exception
* silent partial success
* || trueによる失敗隠蔽
* skipped testをpassedとして表示
* unavailable PITをvalidとして表示
* incomplete datasetをcompleteとして表示
* failed recoveryをrecoveredとして表示

Partial completionはpartial completionとして報告する。

⸻

70. RECOVERY PROTOCOL

失敗時:

1. Preserve logs/artifacts
2. Detect failure class
3. Reuse checkpoint
4. Retry deterministic-safe stage
5. Avoid duplicate computation
6. Verify outputs
7. Update failure ledger
8. Resume downstream only after gate passes

不可逆な破損が疑われる場合はrollbackする。

⸻

71. RESEARCH MEMORY

GitHub-native memoryとして以下を永続保持する。

* source registry
* competition registry
* experiment registry
* model registry
* calibration registry
* failure memory
* negative knowledge
* experience ledger
* promotion/rejection ledger
* scope frontier
* research queue
* automation health
* performance history
* PIT audit history
* holdout history
* rollback history

⸻

72. RESEARCH PRIORITIZATION

次のresearch taskは、

Expected Impact
× Evidence Gap
× Failure Relevance
× Generalization Potential
× Information Value
÷ Cost

を基本思想として優先順位付けする。

単なる新規性だけではresearch priorityを上げない。

⸻

73. UNKNOWN FRONTIER

最重要未知領域:

* events with high disagreement
* events with low predictability
* unseen competitions
* new participants
* regime transitions
* source conflict
* missing-data heavy events
* extreme confidence failures
* unexplained performance changes
* previously unseen failure patterns

Unknownを無視せず研究queueへ送る。

⸻

74. COMPLETION DEFINITION

「24時間動いた」
「Actionsがgreen」
「モデルが生成された」
だけではcompleteとはしない。

Completion requires evidence of runnable GitHub state:

* source/config integrated
* tests
* workflows
* checkpoint/recovery
* PIT audit
* leakage/meta-leakage audit
* chronological OOS/WFO
* calibration
* ablation
* robustness
* frozen holdout firewall
* artifact validation
* reproducibility
* failure handling
* report
* production gate

未実施項目は未実施として残す。

⸻

⸻

75. FINAL OPERATING LOOP

常時、

MONITOR
→ DETECT DEGRADATION / NEW METHOD / NEW SOURCE / NEW FAILURE
→ RESEARCH
→ IMPLEMENT
→ TEST
→ PIT CHECK
→ OOS
→ ROBUSTNESS
→ HOLDOUT
→ ADOPT / HOLD / REJECT
→ DEPLOY
→ MONITOR
→ FAIL / LEARN
→ REPEAT

を実行する。

⸻

76. ULTIMATE PRINCIPLE

最適化対象は単純な過去Accuracyではない。

最終目的関数は、

Future Generalization
× Case-Level Correctness
× Calibration
× Predictability Awareness
× Uncertainty Quality
× Robustness
× PIT Integrity
× Information Efficiency
× Recovery Reliability
× Reproducibility
× Operational Safety

を総合的に最大化することである。

「より複雑なモデル」ではなく、
「将来未知のイベントで、いつ、何を、どの情報から、どのモデルで、どの程度確信して予測し、必要なら追加情報を取り、危険ならfallback/abstainし、失敗したら原因を特定して次の研究へ変換できるsystem」
を最終的なPrediction Intelligenceと定義する。


⸻

77. CROSS-SPORT FEATURE INTELLIGENCE AND PATTERN SEARCH

「データ量が多いほど全列を入れる」が本プロジェクトの方針ではない。
各active sportについて、利用可能な情報を意味的familyに分離し、単体値・A/B差分・相対値・トレンド・ローリング統計・鮮度・欠損状態・相互作用を候補として扱う。

必須family:

* identity_strength: Elo、opponent strength、H2H、historical participation
* form_load: recent result、streak、margin、rest、schedule load
* performance_history: prior team/player/athlete/fighter/map/match statistics
* entity_profile: age、height/reach、stance、position、role、class等
* team_roster_context: roster、starter、lineup、role、team composition
* competition_context: competition、season、phase、stage、round、event type、rules
* matchday_intelligence: availability、injury、weather、travel、late official information、market/news where legally and PIT-safely observed
* data_quality: source reliability、freshness、coverage、PIT/data state
* interaction: differences、ratios、relative values、cross-family interactions

競技別の優先順位は設けてよいが、固定レシピにしてはならない。

Basketball:
* team strength/Elo
* recent form and schedule load
* team season metrics
* player/roster/starter information
* venue/competition/phase
* available matchday information
* stat differentials and rate/efficiency interactions

Volleyball:
* team strength/Elo
* recent results and set performance
* scoring/attack/serve/receive/block history
* player roster/rotation/starter information when PIT-valid
* competition/phase/round
* rest/schedule load
* matchday availability and lineup changes
* rate/differential/trend interactions

VALORANT:
* team rating/form
* map-specific and series-specific history
* player/map statistics
* roster changes
* patch/map pool/Bo format
* event stage/round
* recent travel/rest and matchday status
* source disagreement and data coverage

UFC / RIZIN:
* fighter strength/history
* opponent-adjusted form
* prior fight statistics
* physical/profile attributes
* stance/weight class/rules
* inactivity/rest
* opponent/competition context
* official lineup/card changes and late information

Tennis:
* player strength and surface-specific history
* serve/return performance
* tournament/round/surface
* recent load/rest
* player availability
* match conditions

F1:
* driver/team strength
* circuit-specific history
* qualifying/race/sprint event type
* car/team state
* current roster
* weather/track conditions only when PIT-proven

Rugby:
* team strength/form
* scoring/concession and territory/set-piece style where available
* roster/selection
* competition/phase
* rest/travel
* weather/venue

Boxing:
* fighter strength/form
* age/physical profile
* weight class
* opponent strength
* inactivity
* result-method history
* bout/event context

78. FEATURE PATTERN SELECTION GATE

大量の候補を直接productionへ入れない。
FEATURE_PATTERN_POLICY と feature-pattern optimizerにより、pre-holdout training rowsだけで複数のfamily組合せをchronological walk-forward比較する。

候補は少なくとも、

* core
* core + performance
* core + form
* core + profile
* core + roster
* core + competition
* core + matchday
* core + data quality
* core + interaction
* 複数family combinations
* all available families

を含め、sport-specific priorityに基づき探索順序を変える。

評価は、

LogLoss
+ recent-period weighting
+ fold dispersion penalty
+ complexity tie-break

を基本とする。

同等性能なら特徴数の少ないpatternを優先する。
単一fold、random split、frozen holdout tuningによる選択は禁止する。

79. FEATURE FAMILY ABLATION

新情報を追加した場合は「追加後に少し良くなった」だけで採用しない。

minimum comparison:

BASE
BASE + family A
BASE + family B
BASE + family A + family B
BASE + profile/roster
BASE + matchday
BASE + interaction
selected composite
all available

利用できないfamilyを0で埋めて有効に見せてはならない。
family unavailable、PIT-unproven、identity-unresolvedを別状態で記録する。

80. PARTICIPANT / TEAM HISTORY FEATURE CONTRACT

participant_history と team_history に保存された属性は、

effective_at <= prediction_cutoff
AND exact source availability <= prediction_cutoff
AND entity identity resolved
AND event_timeより前

を満たす場合だけpredictive featureとして利用できる。

UFC等のprofileについては、age、height、weight、reach、stance、career summary等を候補化する。
Basketball/Volleyball/VALORANT等ではplayer/roster/team season informationを同じ契約で扱う。

profile/roster dataが存在すること自体は採用を意味しない。
historical PIT proofのないprofileはOOS trainingから除外し、future/current prospective observationではcutoff時点のevidenceとして扱う。

81. SPORT-WIDE DATA PATTERN OBJECTIVE

全active sportsで、「情報の多さ」ではなく「future generalizationに効く情報パターン」を探索する。

優先するのは、

data value
× PIT validity
× identity quality
× coverage
× robustness
× incremental OOS value
÷ complexity

である。

UFCだけ、Basketballだけ、Volleyballだけに閉じる実装は不十分であり、feature-pattern researchは5 active lanesすべてに適用する。
将来のdeferred sportsも同じ契約を満たした時点で自動的にこの探索枠へ入れる。

82. PROMOTION FIREWALL FOR NEW FEATURES

新しいfeature family/patternは、

DISCOVERED
→ DATA_FEASIBLE
→ PIT_VALIDATED
→ PATTERN_SCREENED
→ CHRONOLOGICAL_OOS
→ ROBUSTNESS
→ FROZEN_HOLDOUT
→ SHADOW
→ LIMITED_PRODUCTION
→ STABLE_PRODUCTION

の順に昇格する。

IMPLEMENTED、EXECUTED、VERIFIEDだけではfeature adoptionを意味しない。
performance evidenceがなければRESEARCH_ONLY/HOLDを維持する。
