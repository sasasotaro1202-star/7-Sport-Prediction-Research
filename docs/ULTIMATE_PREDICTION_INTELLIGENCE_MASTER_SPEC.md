# ULTIMATE PREDICTION INTELLIGENCE — MASTER SPECIFICATION

Version: 1.0  
Date: 2026-10-06  
Repository: \`sasasotaro1202-star/7-Sport-Prediction-Research\`  
Role: research/engineering master specification

> This document consolidates the Project Source, the existing repository architecture, and the deeper prediction-engine design developed during research. It is a design specification, not a claim that every component is already implemented or production-validated.
>
> The current GitHub registry, production gates, experiment artifacts, and executed evidence always take precedence over this document when describing actual repository state.

---

## 0. CORE DEFINITION

The system is not a single "winner classifier".

It is a time-aware, sport-specific, evidence-controlled Prediction Intelligence system whose objective is:

\[
\text{Future Generalization}
\times
\text{Case-Level Correctness}
\times
\text{Calibration}
\times
\text{Predictability Awareness}
\times
\text{Uncertainty Quality}
\times
\text{Robustness}
\times
\text{PIT Integrity}
\times
\text{Information Efficiency}
\times
\text{Recovery Reliability}
\times
\text{Reproducibility}
\times
\text{Operational Safety}
\]

The system must answer five questions simultaneously:

1. What is the current latent state of each participant?
2. How does that state interact with this particular opponent, competition, format and environment?
3. What outcomes are plausible from that state?
4. How much should the system trust the resulting probability?
5. What should the system do when information is missing, contradictory, stale or insufficient?

The final decision is therefore not only:

\[
P(\text{win})
\]

but:

\[
\{\text{probability distribution},\text{uncertainty},\text{predictability},\text{state},\text{reliability},\text{action}\}
\]

---

# 1. NON-NEGOTIABLE PRINCIPLES

## 1.1 Future first

Historical accuracy is evidence, not the objective.

A model that wins on an old aggregate but fails on the newest regime, unseen competition or sparse cases is not automatically superior.

## 1.2 PIT is a hard gate

For every feature:

\[
available\_at \le prediction\_cutoff
\]

must be provable.

Retrieval time alone is not sufficient.

Unknown PIT means:

\[
\text{FAIL\ CLOSED}
\]

The system must never silently convert unknown timing into valid timing.

## 1.3 Missing is not zero

Missing values must preserve semantic cause:

- unavailable
- not applicable
- unknown
- delayed
- malformed
- source failed
- not yet public
- structurally absent

A missing injury report is not "no injury".  
A missing statistic is not "0".  
A missing timestamp is not "available immediately".

## 1.4 Identity integrity precedes modeling

Canonical identity is part of the model.

No silent merge.

Fuzzy matching is candidate generation only. Final identity resolution requires a deterministic mapping with provenance.

## 1.5 Sport-specific modeling

Basketball, volleyball, VALORANT, UFC, RIZIN, tennis, F1, rugby and boxing are different stochastic systems.

They may share infrastructure and statistical primitives, but they must not be forced into one generic target semantics or one identical feature interpretation.

## 1.6 Probability is not confidence

A 65% prediction does not automatically mean "high confidence".

Probability describes the modeled outcome distribution.

Confidence describes trust in the probability estimate.

Predictability describes how identifiable the outcome is from the information available now.

These are separate axes.

## 1.7 No fake improvement

Never:

- fabricate metrics
- create synthetic training rows to reach a target
- use future information in historical evaluation
- change historical records to make a model look better
- call skipped tests "passed"
- call degraded recovery "recovered"
- call code presence "adopted"
- call green CI "performance verified"

---

# 2. COMPLETE SYSTEM PIPELINE

Canonical flow:

\[
\text{Discover}
\rightarrow
\text{Identity}
\rightarrow
\text{Coverage}
\rightarrow
\text{Provenance}
\rightarrow
\text{PIT}
\rightarrow
\text{Features}
\rightarrow
\text{Candidate Models}
\rightarrow
\text{Ensemble}
\rightarrow
\text{Routing}
\rightarrow
\text{Calibration}
\rightarrow
\text{Uncertainty}
\rightarrow
\text{Predictability}
\rightarrow
\text{Matchday Intelligence}
\rightarrow
\text{Simulation}
\rightarrow
\text{Selective Decision}
\rightarrow
\text{OOS}
\rightarrow
\text{Robustness}
\rightarrow
\text{Frozen Holdout}
\rightarrow
\text{Production}
\rightarrow
\text{Monitoring}
\rightarrow
\text{Failure Analysis}
\rightarrow
\text{Research}
\rightarrow
\text{Adoption/Rollback}
\]

Each arrow is a gate, not a cosmetic label.

---

# 3. THE THREE-WORLD MODEL

The system should conceptually separate three worlds.

## 3.1 Observed world

What has actually been observed:

- results
- scores
- player statistics
- lineups
- schedule
- venue
- weather
- roster changes
- source publications
- timestamps
- tactical indicators
- map/set/round information
- historical events

## 3.2 Latent world

What is believed to be true but not observed perfectly:

- true current team strength
- true player ability
- temporary form
- fatigue
- health
- tactical state
- chemistry
- coach strategy
- matchup suitability
- regime
- source reliability
- uncertainty in all of the above

Represent latent state as a probability distribution:

\[
Z_t \sim P(Z_t \mid X_{\le t})
\]

not just a point estimate.

## 3.3 Future world

What may happen after prediction cutoff:

\[
S_0
\rightarrow E_1
\rightarrow S_1
\rightarrow E_2
\rightarrow \dots
\rightarrow S_T
\rightarrow Y
\]

where:

- \(S_t\) = game state
- \(E_t\) = event
- \(Y\) = final target

The ultimate system is therefore a generative model of possible futures, not merely a classifier.

---

# 4. LATENT STATE MODEL

## 4.1 Dynamic state equation

A general state-space formulation:

\[
Z_t = f(Z_{t-1},U_t,\epsilon_t)
\]

\[
X_t = g(Z_t,V_t)
\]

where:

- \(Z_t\): latent true state
- \(U_t\): real state changes
- \(X_t\): observed features
- \(\epsilon_t,V_t\): process/measurement noise

This prevents the common error:

"last result = current ability"

because:

\[
Observed\ Result =
Ability + Opponent + Context + Randomness
\]

## 4.2 Multidimensional strength

Never force all strength into a single scalar.

Example basketball vector:

\[
\theta =
[
ORtg,
DRtg,
Transition,
HalfCourt,
3PT,
Rim,
Rebound,
TOV,
Bench,
Clutch,
Pace
]
\]

Example baseball-style internal vector:

\[
\theta =
[
Starter,
Bullpen,
Batting,
Defense,
Baserunning
]
\]

with further decomposition.

Example VALORANT vector:

\[
\theta =
[
Attack,
Defense,
MapPool,
Pistol,
Economy,
Retake,
Entry,
Utility,
Clutch,
PlayerAvailability
]
\]

The exact vector is sport-specific.

---

# 5. TIME DECAY AND SHRINKAGE

## 5.1 Time decay

Old evidence should generally receive lower weight:

\[
w_i = e^{-\lambda \Delta t_i}
\]

where:

- \(\Delta t_i\) = age of observation
- \(\lambda\) = decay rate

Decay should be adaptive.

A coach change, transfer, rule change or major roster rebuild can cause a regime break, increasing effective \(\lambda\).

## 5.2 Shrinkage

Small samples must not create extreme estimates.

A basic shrinkage form:

\[
\hat{\theta}
=
w\theta_{obs}
+
(1-w)\theta_{prior}
\]

with:

\[
w=\frac{n}{n+k}
\]

where:

- \(n\) = effective sample size
- \(k\) = prior-strength constant

This is especially important for:

- new players
- new teams
- new competitions
- rare tactical patterns
- sparse matchup histories
- recent role changes

## 5.3 Hierarchical partial pooling

When multiple competitions share a mechanism but differ in scale:

\[
\theta_{competition}
\sim
N(\mu_{sport},\sigma^2_{sport})
\]

Then:

- competition-specific data updates competition state
- sport-level information supplies prior strength
- global prior stabilizes sparse competitions

This gives structured information sharing without blindly pooling datasets.

---

# 6. TEAM / ATHLETE / PLAYER STATE

Each participant state should conceptually contain:

\[
State =
BaseSkill
+
RecentForm
+
Health
+
Role
+
Fit
+
Environment
\]

## 6.1 Base skill

Long-term ability adjusted for:

- opponent quality
- competition level
- age
- role
- rule set
- surface/map/venue where relevant

## 6.2 Recent form

Do not use only W/L.

Use underlying process metrics where available.

For a team:

\[
RecentState
=
\sum_i w_i \cdot ProcessMetric_i
\]

with time-decay and opponent adjustment.

## 6.3 Health

Health should not be a binary "injured/not injured" variable when better information exists.

Possible state:

\[
Health \in
\{
Available,
Questionable,
Limited,
Returning,
Unavailable
\}
\]

with probability:

\[
P(Health=s)
\]

when uncertainty exists.

## 6.4 Role

The same athlete can have different value under different roles.

Therefore:

\[
Value = f(Player,Role,Opponent,Strategy)
\]

not a single fixed player number.

## 6.5 Replacement effect

Player value should be measured relative to replacement:

\[
\Delta TeamStrength
=
Strength(Team)
-
Strength(Team\ without\ Player)
\]

and should include interaction effects.

Two players may individually look mediocre but jointly create a highly effective combination.

---

# 7. MATCHUP ENGINE

Generic strength:

\[
A > B
\]

is insufficient.

The actual prediction is:

\[
P(Y|A,B,X)
\]

where interaction matters:

\[
A \times B
\]

## 7.1 Matchup matrix

Conceptually:

\[
M_{A,B}
=
Strength(A)
-
Strength(B)
+
Interaction(A,B)
\]

The interaction term may represent:

- style collision
- handedness
- map pool
- pace
- serve/return interaction
- wrestling vs striking
- line vs scrum matchup
- tire strategy
- tactical response

## 7.2 Historical H2H

H2H is not a magic feature.

Its value depends on:

- recency
- roster continuity
- coach continuity
- tactical continuity
- venue
- competition format
- sample size

Therefore:

\[
w_{H2H}
=
f(recency,continuity,context,n)
\]

Old H2H with different rosters should approach zero influence.

---

# 8. SPORT-SPECIFIC PREDICTION ENGINES

## 8.1 Basketball

Target candidates:

- game win probability
- score distribution
- margin distribution
- overtime probability
- player output

Core structure:

\[
Possession
\rightarrow
Outcome
\rightarrow
NextPossession
\]

Key feature families:

- offensive efficiency
- defensive efficiency
- pace
- shooting efficiency
- 3P profile
- rim profile
- turnover rate
- offensive rebound
- defensive rebound
- free throw generation
- opponent-adjusted form
- lineup impact
- bench quality
- rest
- travel
- schedule density
- home/away
- injuries
- role changes

Generative model:

\[
N_{possessions}\sim P(N)
\]

\[
Outcome_j
\sim
P(TOV,Shot,FT,OR,DR|\ State_j)
\]

Aggregate simulated possession paths into:

- final score
- margin
- win probability

## 8.2 Volleyball

Natural hierarchy:

\[
Point
\rightarrow
Set
\rightarrow
Match
\]

Key dimensions:

- serve quality
- receive quality
- side-out efficiency
- attack efficiency
- block
- error rate
- rotation strength
- setter distribution
- matchup by rotation
- player availability
- recent workload

Do not treat match win probability as a generic classifier if point/set structure provides a better generative model.

## 8.3 VALORANT

Natural hierarchy:

\[
Round
\rightarrow
Map
\rightarrow
Series
\]

Model state may include:

- side
- economy
- buy state
- player survival
- utility
- map
- site preference
- pistol status
- anti-eco behavior
- timeout/tactical adaptation
- roster
- patch/rule context

For multi-map matches:

\[
P(Series)
=
\sum_{map\ paths}
P(Map_1)
P(Map_2|Map_1)
\cdots
\]

Map probabilities must respect the map veto and series format.

## 8.4 UFC / RIZIN

Bout-level structure:

\[
Fight
\rightarrow
Round
\rightarrow
Exchange
\rightarrow
Outcome
\]

Key dimensions:

- striking volume
- striking accuracy
- defensive rate
- takedown rate
- takedown defense
- submission attempts
- control
- pace
- stance matchup
- reach/size
- age
- durability
- finishing profile
- cardio
- recent layoff
- opponent quality
- weight class
- rule set

Important:

Post-fight statistics from the same fight are never valid pre-fight features.

Historical availability must be proven.

## 8.5 Tennis

Natural structure:

\[
Point
\rightarrow
Game
\rightarrow
Set
\rightarrow
Match
\]

Key features:

- serve points won
- first serve
- second serve
- return quality
- break creation/save
- hold rate
- surface-specific performance
- recent form
- fatigue
- tournament stage
- best-of format
- injury
- travel

Use surface-specific hierarchical models instead of assuming all surfaces are exchangeable.

## 8.6 F1

Hierarchy:

\[
Session
\rightarrow
Qualifying
\rightarrow
Race
\]

Important variables:

- qualifying pace
- long-run pace
- tire degradation
- tire compound
- track characteristics
- weather
- safety-car probability
- pit strategy
- grid position
- driver/team form
- reliability

Finishing position must not be naively converted into binary A/B probabilities.

## 8.7 Rugby

Hierarchy depends on competition, but core process features include:

- territory
- possession
- set piece
- scrum
- lineout
- tackle efficiency
- discipline
- kicking
- attacking phases
- defensive structure
- fatigue
- travel
- weather

Coverage integrity must precede model complexity.

## 8.8 Boxing

Bout hierarchy:

\[
Event
\rightarrow
Bout
\rightarrow
WeightClass
\rightarrow
Fighter
\]

Keep explicit outcome classes:

- win
- loss
- draw
- no contest
- technical decision
- other competition-specific outcome

Do not collapse ambiguous outcomes into win/loss without a documented semantic rule.

---

# 9. GAME-STATE MODEL

A strong predictor should model conditional event probabilities.

For state \(S_t\):

\[
P(E_{t+1}|S_t,X)
\]

After observing event \(E_{t+1}\):

\[
P(S_{t+1}|S_t,E_{t+1},X)
\]

This creates a sequential model.

Examples:

Basketball:
- score differential
- time remaining
- possession
- foul state
- lineup

Volleyball:
- set score
- rotation
- server
- side-out state

VALORANT:
- round
- economy
- alive players
- site
- utility

UFC:
- round
- time
- damage
- cardio proxy
- positional state

This is the foundation for true match simulation.

---

# 10. TACTICAL ADAPTATION AND GAME THEORY

Opponent behavior is not static.

A useful formulation is:

\[
P(Strategy=s | Opponent,State,Score,Time)
\]

The system should allow:

\[
Strategy_{t+1}
=
h(Strategy_t,Opponent,GameState)
\]

Substitutions and rotations are also actions:

\[
P(Lineup_{t+1}|State_t)
\]

This is particularly relevant in:

- basketball substitutions
- volleyball rotation/lineup behavior
- VALORANT tactical timeouts and adaptation
- MMA pacing/adaptation
- F1 pit strategy
- rugby tactical kicking

---

# 11. GENERATIVE MONTE CARLO ENGINE

The final prediction should ideally come from many plausible worlds.

For simulation \(b=1,\dots,B\):

1. sample latent team state
2. sample player/lineup state
3. sample fitness
4. sample tactical state
5. sample environment
6. simulate events
7. simulate adaptations
8. continue until terminal state
9. record outcome

Then:

\[
P(\text{win})
\approx
\frac{1}{B}
\sum_{b=1}^{B}
I(Y_b=\text{win})
\]

For a multiclass result:

\[
P(Y=k)
=
\frac{1}{B}
\sum_b I(Y_b=k)
\]

The simulation should also produce:

- score distribution
- margin distribution
- overtime probability
- upset probability
- scenario frequencies
- tail outcomes

## 11.1 Sources of randomness

Do not collapse all uncertainty into one random term.

At minimum distinguish:

### Parameter uncertainty
"I do not know the true parameter."

### State uncertainty
"I do not know the current true state."

### Event randomness
"Even knowing the state, the sport is stochastic."

### Data uncertainty
"The input data itself may be incomplete or noisy."

### Source uncertainty
"Sources disagree or provenance is weak."

### Regime uncertainty
"The underlying data-generating process may have changed."

---

# 12. SCENARIO ENGINE

Every prediction should have multiple paths.

Example classes:

- dominant favorite controls game
- low-scoring close game
- underdog early lead
- favorite comeback
- overtime
- map upset
- injury-driven collapse
- tactical adaptation swing

The system should separate:

\[
MostLikelyScenario
\neq
MostDangerousScenario
\]

The highest-probability scenario may be safe but a low-probability tail may explain most severe forecast errors.

---

# 13. MARGIN AND TAIL-RISK MODEL

Binary win/loss hides useful information.

Estimate:

\[
P(Margin=m)
\]

or a continuous distribution:

\[
F_{margin}(x)=P(Margin\le x)
\]

From this derive:

- win probability
- one-score probability
- blowout probability
- comeback probability
- upset tail probability

For sports where score or margin is naturally defined, margin modeling is often a better intermediate representation than direct classification.

---

# 14. ENSEMBLE ARCHITECTURE

Candidate model families may include:

- frequency baseline
- Elo
- Bayesian hierarchical rating
- logistic regression
- Poisson / negative-binomial
- state-space model
- gradient boosting
- random forest
- neural network
- temporal model
- graph model
- nearest-neighbor retrieval
- generative simulation

The system should not assume "deep learning = best".

## 14.1 OOF ensemble

Let base predictions be:

\[
p_1,\dots,p_K
\]

Then:

\[
p_{ens}
=
\sum_{k=1}^{K} w_kp_k
\]

subject to:

\[
w_k\ge0,\qquad \sum_k w_k=1
\]

Weights must be estimated from chronological out-of-fold evidence.

## 14.2 Adaptive weighting

A stronger system allows:

\[
w_k=f(context,regime,uncertainty,data\ quality)
\]

rather than fixed global weights.

However adaptive complexity is accepted only after OOS evidence.

---

# 15. DYNAMIC ROUTING

The system should select the appropriate model scope.

Routing hierarchy:

\[
Specific
\rightarrow
Competition
\rightarrow
Sport
\rightarrow
Global
\]

Inputs may include:

- sport
- competition
- tier
- event type
- regime
- recentness
- data completeness
- uncertainty
- model disagreement
- sample support
- OOD distance

Small samples must fallback upward.

Over-specialization is a failure mode.

---

# 16. TEMPORAL MEMORY / SIMILAR-EVENT RETRIEVAL

Historical analogues can help when used correctly.

For query \(x\), retrieve:

\[
\mathcal{N}_k(x)
\]

using standardized feature distance.

A generic distance:

\[
d(x_i,x_j)
=
\sqrt{
\frac{1}{D}
\sum_{d=1}^{D}
(x_{id}-x_{jd})^2
}
\]

Weight neighbors:

\[
w_i
\propto
e^{-d_i/\tau}
\]

Use retrieved cases for:

- expected trajectory
- scenario distribution
- support
- predictability

Never let future snapshots leak into anchor features.

Do not recursively feed the model's own future predictions back as if they were observations.

---

# 17. PREDICTABILITY ENGINE

Predictability is distinct from confidence.

Conceptually:

\[
Predictability
=
f(
DataCompleteness,
Agreement,
OOD,
RegimeClarity,
HistoricalEntropy,
LineupCertainty,
TargetStochasticity,
Support
)
\]

A low-predictability case may deserve:

- abstention
- wider uncertainty
- additional information
- specialist model
- generalist fallback

This prevents the system from being forced to produce overconfident predictions for intrinsically difficult events.

---

# 18. MODEL DISAGREEMENT

Given \(K\) model probabilities:

\[
Disagreement
=
Var(p_1,\dots,p_K)
\]

or a robust alternative such as median absolute deviation.

High disagreement may indicate:

- conflicting mechanisms
- regime change
- data corruption
- insufficient model coverage
- genuine ambiguity

Disagreement should feed both:

1. uncertainty
2. routing

---

# 19. OOD DETECTION

Estimate distance from training support:

\[
OODDistance=f(x,\mathcal{D}_{train})
\]

Possible methods:

- standardized Mahalanobis distance
- nearest-neighbor distance
- density estimate
- isolation methods
- embedding distance

OOD must not be interpreted as "bad event".

It means:

"The historical support for this case is weak."

The system should reduce confidence when OOD is high unless validated evidence shows otherwise.

---

# 20. REGIME DETECTION

Sports are nonstationary.

Potential change points:

- coach
- player transfer
- rule change
- patch
- lineup rebuild
- competition format
- tactical system
- equipment
- season transition

A generic regime model:

\[
R_t\in\{1,\dots,K\}
\]

with:

\[
P(R_t|X_{\le t})
\]

Prediction becomes:

\[
P(Y|X)
=
\sum_r
P(Y|X,R=r)P(R=r|X)
\]

---

# 21. MATCHDAY INTELLIGENCE

Historical baseline should be updated using only information legally and temporally available at cutoff.

Possible live inputs:

- lineup
- starter
- availability
- suspension
- travel
- rest
- venue
- weather
- official update
- roster change
- event metadata
- source conflict

Each source needs:

- available_at
- relevance
- incremental value
- PIT status
- revision risk
- coverage
- reliability

A source is not valuable merely because it exists.

---

# 22. VALUE OF INFORMATION

At prediction time, the action need not always be "predict now".

Candidate actions:

- PREDICT_NOW
- ACQUIRE_MORE
- WAIT
- RECOMPUTE
- FALLBACK
- ABSTAIN

A conceptual value function:

\[
VOI(source)
=
ExpectedRiskReduction
-
LatencyCost
-
ReliabilityPenalty
-
ComputeCost
\]

A better information source should be queried only when the expected reduction in decision uncertainty justifies the cost and delay.

---

# 23. FORECAST LIFETIME

A prediction becomes stale as the world changes.

Lifetime should shorten after:

- confirmed lineup change
- injury update
- roster change
- source revision
- regime change
- unexpected event
- disagreement spike

Prediction state:

- FRESH
- AGING
- STALE
- UNKNOWN
- SHOCKED
- REQUIRES_RECALC
- ABSTAIN
- FALLBACK
- INVALIDATED

---

# 24. CALIBRATION

Accuracy and calibration are different.

For predicted probability \(p\), calibration asks:

\[
P(Y=1|p\approx q)\approx q
\]

Track:

- LogLoss
- Brier
- ECE
- reliability curve
- calibration slope
- calibration intercept
- subgroup calibration
- temporal calibration drift

Calibration options:

- temperature-style scaling
- beta-style scaling
- isotonic regression
- sigmoid calibration

Calibration must be selected chronologically and never tuned against the frozen holdout.

---

# 25. SELECTIVE PREDICTION / ABSTENTION

The best action is not always "predict".

Let:

\[
coverage(\tau)
=
P(score\ge\tau)
\]

and selective risk:

\[
Risk(\tau)
=
E[Loss|score\ge\tau]
\]

Measure the trade-off between:

- coverage
- risk
- calibration
- utility
- stability

Abstention is a system behavior, not a model failure.

---

# 26. CONFORMAL RESEARCH

Possible research directions:

- conformal prediction
- adaptive conformal
- local conformal
- online conformal
- risk-controlling prediction
- set-valued prediction

But coverage alone is not enough.

Evaluate:

\[
Coverage,\ SetSize,\ SelectiveRisk,\ Utility,\ Stability,\ RegimeRobustness
\]

Event dependence must be respected.

---

# 27. EVENT-CLUSTER DEPENDENCY

If one event has:

- T-24h
- T-6h
- T-90m
- T-60m
- T-30m
- T-15m

these are correlated observations.

They are not six independent games.

Bootstrap at the event-cluster level:

\[
Cluster = \{all\ snapshots\ of\ one\ event\}
\]

Experience learning should also canonicalize one event according to a defined policy so repeated snapshots do not inflate the effective sample.

---

# 28. DATA MODEL

Every event should have a canonical identity.

### Event

- event_id
- sport_id
- competition_id
- season
- phase
- round
- event_type
- event_time
- venue
- participants
- source_event_ids
- status
- outcome_status

### Prediction

- prediction_id
- event_id
- prediction_time
- prediction_cutoff
- horizon
- model_version
- ensemble_version
- calibration_version
- probability distribution
- state
- confidence
- predictability
- disagreement
- OOD
- uncertainty decomposition
- source snapshot
- feature snapshot
- git SHA
- data hash

### Source snapshot

- source_id
- raw URI/endpoint
- published_at
- available_at
- retrieved_at
- revision_time
- snapshot_hash
- parser_version
- schema_version
- reliability_status

### Feature lineage

- feature_id
- feature_value
- source_id
- source_available_at
- transformation
- cutoff
- version
- quality
- missingness
- revision behavior

---

# 29. IDENTITY MODEL

Participant records:

- stable_id
- canonical_name
- raw_source_name
- source_id
- source URL
- effective_at
- team/association
- role/position/class
- quality status

Never merge by name alone.

Separate:

- club
- national team
- reserve
- youth
- academy
- women
- men
- different organizational scopes
- different roster states

History of team changes and name changes must be preserved.

---

# 30. COVERAGE DIGITAL TWIN

Coverage must be multi-dimensional:

- competitions
- seasons
- dates
- teams
- athletes
- events
- outcomes
- features
- sources
- timestamps
- publication metadata
- availability metadata
- revisions
- prediction horizons
- regimes
- edge cases

Define:

\[
CoverageDebt
=
f(missingness,\ depth,\ provenance,\ PIT,\ identity,\ regime)
\]

Do not answer a coverage problem by adding a more complex model.

---

# 31. SOURCE REGISTRY

Each source should record:

- source_id
- provider
- endpoint
- data type
- domain
- upstream owner
- independence
- license
- cost
- coverage
- freshness
- available_at support
- published_at support
- revision behavior
- schema
- parser
- last success
- last failure
- failure rate
- incremental information value
- production status

Source count is not source value.

---

# 32. SOURCE INDEPENDENCE

The following may all be the same information lineage:

- mirror
- wrapper
- scraper
- copied CSV
- republished dataset
- transformed dataset

Do not treat them as six independent experts.

Independence must be considered in:

- ensemble diversification
- source conflict
- evidence aggregation

---

# 33. FAILURE TAXONOMY

Every failure should be classified.

### Data
- missing data
- malformed data
- stale data
- source outage

### Temporal
- PIT violation
- timestamp issue
- unavailable history
- revision leakage

### Identity
- identity mismatch
- silent merge risk

### Model
- model failure
- calibration failure
- routing failure
- regime failure
- OOD failure

### Uncertainty
- disagreement failure
- underestimation
- false certainty

### Scope
- unsupported competition
- target semantic mismatch

### Operations
- automation failure
- timeout
- race condition
- recovery failure
- reporting failure

Failures are learning objects, not merely logs.

---

# 34. FAILURE MEMORY

For every important failure, store:

- event
- what happened
- when
- available information
- missing information
- model disagreement
- predictability
- calibration state
- source state
- regime
- OOD
- counterfactual alternatives
- error classification
- evidence level

Counterfactual questions:

- Would better data have helped?
- Would later timing have helped?
- Would a specialist have helped?
- Would a fallback have helped?
- Would abstention have helped?
- Would a different competition scope have helped?

Observed evidence and speculation must be separated.

---

# 35. EXPERIENCE MEMORY

When an event matures:

1. verify outcome
2. canonicalize event
3. select the defined canonical prediction
4. retain prediction lineage
5. score
6. classify error
7. update experience ledger

Repeated snapshots cannot be treated as independent experiences.

---

# 36. RESEARCH MEMORY

Persist:

- source registry
- competition registry
- experiment registry
- model registry
- calibration registry
- failure memory
- negative knowledge
- experience ledger
- promotion/rejection ledger
- scope frontier
- research queue
- automation health
- performance history
- PIT audit history
- holdout history
- rollback history

Research memory should be GitHub-native and reproducible.

---

# 37. NEGATIVE KNOWLEDGE

Rejected methods are valuable.

Store:

- method
- dataset
- cutoff
- OOS delta
- reason rejected
- cost
- PIT issue
- robustness failure
- failure conditions

This prevents rediscovering the same dead ends.

---

# 38. CROSS-DOMAIN TRANSFER

Nothing is copied into production simply because it worked elsewhere.

Required sequence:

\[
DISCOVER
\rightarrow
ABSTRACT\ MECHANISM
\rightarrow
COMPATIBILITY
\rightarrow
ADAPT
\rightarrow
LOCAL\ PIT
\rightarrow
LOCAL\ OOS
\rightarrow
LOCAL\ ROBUSTNESS
\rightarrow
LOCAL\ HOLDOUT
\rightarrow
SHADOW
\rightarrow
PROMOTE
\]

Only the mechanism transfers.

The evidence does not.

---

# 39. RESEARCH EVIDENCE LEVEL

Use:

- E0 = idea only
- E1 = external claim
- E2 = external implementation
- E3 = local reproduction
- E4 = local OOS evidence
- E5 = robustness evidence
- E6 = frozen holdout evidence
- E7 = production evidence

No upward inflation.

---

# 40. RESEARCH PRIORITIZATION

Prioritize approximately by:

\[
Priority
\propto
\frac{
ExpectedImpact
\times
EvidenceGap
\times
FailureRelevance
\times
GeneralizationPotential
\times
InformationValue
}{
Cost
}
\]

This is a research heuristic, not a claim of precise expected utility.

Research categories:

- Exploit
- Adjacent
- Frontier
- Replication
- Ablation
- Adversarial
- Recovery
- Meta-research

---

# 41. OOS / WALK-FORWARD

Production-grade evaluation is chronological.

Correct pattern:

\[
Train_1
\rightarrow
Validate_1
\rightarrow
OOS_1
\rightarrow
Train_2
\rightarrow
Validate_2
\rightarrow
OOS_2
\rightarrow
\dots
\]

Forbidden:

- random split
- random K-fold for temporal targets
- future feature backfill
- holdout-driven tuning
- repeated frozen-holdout optimization
- future source revisions inserted into historical rows

---

# 42. METRICS

Primary:

- LogLoss

Secondary:

- Brier
- Accuracy
- ECE
- class-wise loss
- recall/precision
- selective risk
- abstention rate
- calibration slope/intercept
- robustness
- subgroup metrics

Always slice by:

- sport
- competition
- season
- phase
- tier
- event type
- regime
- confidence
- uncertainty
- horizon
- data completeness
- source combination

A single aggregate number is insufficient.

---

# 43. STATISTICAL COMPARISON

For candidate \(C\) vs incumbent \(I\):

\[
\Delta LogLoss
=
LL_C-LL_I
\]

Lower is better.

Do not use point estimate alone.

Also report:

- sample size
- event dependence
- confidence interval / bootstrap interval
- newest fold
- worst fold
- recent period
- subgroup behavior
- practical effect size

A tiny average gain with unstable tails is not automatically an improvement.

---

# 44. ADOPTION GATE

Reference candidate benchmark:

- primary OOS relative improvement >= 3%
- auxiliary improvement >= 1%
- >=70% evaluation periods without worsening
- newest holdout not worse
- calibration not materially degraded or meaningfully improved
- PIT violations = 0

These are candidate thresholds, not automatic approval.

Also require:

- chronological integrity
- leakage audit clean
- reproducibility
- robustness
- enough data
- uncertainty considered
- operational safety
- acceptable cost

---

# 45. FROZEN HOLDOUT FIREWALL

Frozen holdout is never a tuning environment.

Do not use it to adjust:

- features
- model hyperparameters
- thresholds
- calibration
- scope
- routing

Access should happen only at release evaluation after configuration freeze.

---

# 46. REPRODUCIBILITY

Each experiment should have a fingerprint:

\[
Fingerprint=
Hash(
GitSHA,
DatasetHash,
SourceSnapshot,
FeatureVersion,
ModelConfig,
CalibrationConfig,
Seed,
Environment,
CutoffPolicy
)
\]

Same fingerprint should reuse existing artifacts.

Deterministic replay should reproduce:

\[
InputSnapshot
\rightarrow
Feature
\rightarrow
Model
\rightarrow
Probability
\rightarrow
Calibration
\rightarrow
Decision
\]

where feasible.

---

# 47. ADVERSARIAL VALIDATION

Regular attacks:

- PIT attack
- leakage attack
- future timestamp injection
- source removal
- feature deletion
- time shift
- distribution shift
- regime shift
- missingness
- outlier
- rare event
- unseen competition
- unseen participant
- stale source

A system that only passes normal data is not sufficiently tested.

---

# 48. ROBUSTNESS MATRIX

Evaluate candidates against:

- newest periods
- recent periods
- high variance
- upset-heavy cases
- sparse cases
- missing feature cases
- source outage
- distribution shift
- new competitions
- new participants
- regime changes

Promotion requires acceptable behavior beyond the average.

---

# 49. CONTROL PLANE

The automation system should continuously execute:

\[
MONITOR
\rightarrow
DETECT
\rightarrow
RESEARCH
\rightarrow
IMPLEMENT
\rightarrow
TEST
\rightarrow
PIT
\rightarrow
OOS
\rightarrow
ROBUSTNESS
\rightarrow
HOLDOUT
\rightarrow
ADOPT/HOLD/REJECT
\rightarrow
DEPLOY
\rightarrow
MONITOR
\]

## 49.1 Single-writer semantics

Critical state should have deterministic ownership:

- production registry
- promotion state
- rollback state
- experiment registry
- experience ledger
- source registry
- scope registry

Parallel research is allowed.

Concurrent mutation of critical state is not.

---

# 50. AUTOMATION RELIABILITY

Long-running GitHub Actions should use:

- checkpoint
- resume
- idempotency
- retries
- exponential backoff
- watchdog
- heartbeat
- stale-run detection
- bounded execution
- artifact preservation
- deterministic writes
- concurrency control
- recovery
- rollback

The goal is not merely "the job started".

The goal is:

\[
\text{system remains correct under interruption}
\]

---

# 51. SAFE DEGRADATION

Canonical fallback:

\[
Champion
\rightarrow
Specialist
\rightarrow
Generalist
\rightarrow
Baseline
\rightarrow
Abstain
\]

Every fallback event must be logged.

The system must never hide fallback usage.

---

# 52. COST FIREWALL

Preferred:

1. verified free
2. free quota
3. OSS/local
4. cached snapshot
5. lightweight computation

Automatically avoid:

- paid-only
- billing risk
- unknown cost
- auto-renewing trial
- uncontrolled quota overage

Unknown cost = HOLD / UNCONFIRMED.

---

# 53. PRODUCTION OUTPUT CONTRACT

Each prediction should expose, where available:

- Sport
- Competition
- Event
- Start time
- Prediction
- Probability
- State
- Reliability
- Model
- Agreement
- Predictability
- Upset risk
- OOD
- Data health
- PIT health
- Forecast lifetime
- Previous -> Current probability delta
- Change drivers
- source snapshot
- model version
- calibration version
- Git SHA

The result should clearly distinguish:

- Current
- History
- Research Candidate

---

# 54. FINAL DECISION OBJECT

Conceptually:

\[
Decision =
(
P(Y),
Confidence,
Predictability,
Uncertainty,
OOD,
Disagreement,
ForecastState,
Action,
ModelRoute,
EvidenceLevel
)
\]

Example action policy:

\[
Action=
\begin{cases}
PREDICT\_NOW & \text{strong evidence, acceptable uncertainty}\\
ACQUIRE\_MORE & \text{high VOI}\\
RECOMPUTE & \text{new critical information}\\
FALLBACK & \text{specialist/champion failure}\\
ABSTAIN & \text{unsafe or low predictability}\\
DEFERRED & \text{PIT/data not established}
\end{cases}
\]

---

# 55. IDEAL MATCH ANALYSIS

For a single event, the output should follow this order:

## A. Event validity

- canonical event
- competition
- format
- event time
- target semantics
- identity status

## B. Data/PIT health

- source health
- missingness
- PIT proof
- revision risk
- coverage

## C. Current state

- long-term ability
- recent state
- roster
- health
- role
- form

## D. Matchup

- stylistic advantages
- weaknesses
- opponent response
- interaction effects

## E. Environment

- venue
- rest
- travel
- weather
- schedule
- format

## F. Model ecology

- generalist
- specialist
- recent model
- long-memory model
- simulation
- disagreement

## G. Simulation

- most likely scenario
- alternate scenario
- upset scenario
- margin distribution

## H. Probability

\[
P_1,\dots,P_K
\]

with calibration information.

## I. Uncertainty

- data
- model
- state
- regime
- OOD
- source conflict
- outcome randomness

## J. Final

- most likely result
- predictability
- failure scenario
- current recommendation/action state

---

# 56. WHY A MODEL CAN LOSE EVEN WHEN IT IS GOOD

A correct probability can still lose.

If:

\[
P(A)=0.75
\]

then 25% failure remains.

The right question after a miss is not:

"Why was the prediction wrong?"

but:

"Was 25% uncertainty correctly represented?"

Then classify:

1. irreducible sports randomness
2. bad data
3. wrong latent-state estimate
4. wrong matchup model
5. wrong lineup state
6. regime shift
7. OOD
8. bad calibration
9. bad routing
10. stale forecast
11. source conflict
12. system failure

This turns misses into research.

---

# 57. SELF-IMPROVEMENT LOOP

Every mature event may produce new knowledge.

\[
Outcome
\rightarrow
ErrorAnalysis
\rightarrow
FailureClassification
\rightarrow
Hypothesis
\rightarrow
ResearchTask
\rightarrow
Experiment
\rightarrow
OOS
\rightarrow
Robustness
\rightarrow
Holdout
\rightarrow
Adopt/Reject
\]

The system should learn not only:

"which team won"

but also:

"under what conditions the forecast succeeds or fails."

---

# 58. META-LEARNING

A higher-level model can estimate:

\[
P(ModelFailure | CaseContext)
\]

Inputs:

- disagreement
- OOD
- regime change
- missingness
- source conflict
- uncertainty
- prediction age
- competition profile
- recent model degradation

Then the system can route or abstain before a severe failure.

This model itself must be evaluated chronologically and must not leak the future outcome into its inputs.

---

# 59. RESEARCH FRONTIERS

Research candidates:

### Representation
- temporal embeddings
- player/team embeddings
- style embeddings
- graph representations

### Models
- Bayesian state-space
- gradient boosting
- temporal neural models
- transformers
- graph neural networks

### Simulation
- event-level generative models
- tactical state transitions
- dynamic substitutions
- scenario-conditioned simulation

### Uncertainty
- conformal
- calibration
- selective prediction
- Bayesian model averaging

### Operations
- adaptive compute
- source routing
- information acquisition
- dynamic freshness

No frontier method enters production without local evidence.

---

# 60. ADAPTIVE COMPUTE

Compute should follow information value.

High-risk/high-value case:

\[
MoreModels
+
MoreSimulation
+
MoreChecks
\]

Low-information low-value case:

\[
LightRoute
+
Cache
+
Baseline
\]

Optimization order:

\[
Cache
\rightarrow
Incremental
\rightarrow
Deduplicate
\rightarrow
Vectorize
\rightarrow
ParallelI/O
\rightarrow
SelectiveRecompute
\rightarrow
TrainingOptimization
\rightarrow
AlgorithmOptimization
\]

Do not sacrifice research fidelity merely to reduce runtime.

---

# 61. UNKNOWN FRONTIER

Research queue should prioritize:

- high model disagreement
- low predictability
- unseen competitions
- new participants
- regime transitions
- source conflicts
- missing-data-heavy events
- extreme confidence failures
- unexplained performance changes
- novel failure patterns

Unknown is not a reason to ignore an event.

Unknown is a research signal.

---

# 62. COMPLETION CONTRACT

A task is not complete because:

- code exists
- workflow exists
- Actions is green
- a model file was created
- one metric improved

Completion requires runnable evidence of the intended stage:

- source/config integrated
- tests
- workflows
- checkpoint/recovery
- PIT audit
- leakage/meta-leakage audit
- chronological OOS/WFO
- calibration
- ablation
- robustness
- frozen holdout firewall
- artifact validation
- reproducibility
- failure handling
- report
- promotion decision

Every missing stage remains visibly incomplete.

---

# 63. STATUS TAXONOMY

Use exactly these semantic states when applicable:

- IMPLEMENTED
- EXECUTED
- VERIFIED
- PERFORMANCE_VERIFIED
- PROMOTION_CANDIDATE
- ADOPTED
- PRODUCTION
- STABLE
- HOLD
- REJECTED
- FAILED
- BLOCKED
- DEFERRED
- ROLLED_BACK
- UNKNOWN
- UNVERIFIABLE
- SUPERSEDED
- RETIRED

No synonym should silently collapse these distinctions.

---

# 64. CURRENT REPOSITORY INTEGRATION RULE

The research specification must integrate with the current repository rather than replace it blindly.

Current canonical scope is governed by:

\[
config/PROJECT\_SCOPE\_POLICY.json
\]

Current active prediction lanes are the five configured sports.

Research-only/deferred sports remain outside production inference until their own gates are passed.

Existing implementation areas such as:

- autonomous control plane
- production workflow
- pre-event prediction
- dynamic model routing
- temporal trajectory research
- conformal research
- experience learning
- failure memory
- source/collection guards

should be reused and audited rather than duplicated.

---

# 65. CURRENT PRODUCTION REALITY VS TARGET

The design target is broader than the evidence currently available.

Important distinction:

### Operational scope
A sport may be in the active prediction matrix.

### Accepted model scope
A model may actually be production-accepted for that sport.

### Research scope
A method may exist but remain experimental.

These are not the same.

Current release evidence must be interpreted literally.

For example, a release artifact can say that publication is allowed while individual sports remain deferred for strict PIT/model-safety reasons. That means the automation path is functioning, not that every sport has a validated champion.

---

# 66. CURRENT REPOSITORY CHECKPOINT

At the time this master specification was produced:

- default branch: \`main\`
- latest observed main commit: \`8950e01dbfb3d179850b3baaa2ce2ff52e23feab\`
- repository is public Python
- active production workflow exists
- the five-sport production matrix exists
- T-60 pre-event automation exists
- research-only sport lanes are guarded separately
- failure-memory and control-plane recovery are present
- dynamic model routing exists as a research challenger
- trajectory intelligence exists as research-only
- production evidence must still be distinguished from repository existence

Observed latest control-plane work includes hardening around:

- workflow-run event storms
- durable main advances
- outdated in-progress recovery
- stale queued recovery
- failure memory reconciliation
- continuous watchdog behavior

These observations demonstrate active automation engineering, not predictive-performance superiority.

---

# 67. CURRENT EVIDENCE INTERPRETATION

A current release report may simultaneously contain:

- \`publish=true\`
- \`READY_WITH_EXPLICIT_DEFERRED_SPORTS\`
- some accepted models
- some active lanes without accepted strict-PIT models
- pending coverage
- incomplete exact PIT replay

The correct interpretation is:

"the release/pipeline gate itself is operating under explicit partial/deferred safety, while model validation remains incomplete for some lanes."

Never flatten that into "all sports are production-ready."

---

# 68. IMPLEMENTATION ORDER

The highest-value implementation order is:

## Phase 1 — Integrity
1. canonical event IDs
2. canonical participant IDs
3. exact PIT fields
4. source lineage
5. missingness semantics
6. outcome semantics

## Phase 2 — Baselines
1. frequency baseline
2. Elo/rating
3. logistic
4. sport-specific structural baseline

## Phase 3 — State modeling
1. opponent-adjusted ability
2. time decay
3. shrinkage
4. player state
5. availability
6. regime detection

## Phase 4 — Matchup
1. interaction terms
2. style matchup
3. H2H with continuity
4. tactical context

## Phase 5 — Generative models
1. event process
2. score/margin distribution
3. state transitions
4. Monte Carlo

## Phase 6 — Intelligence
1. disagreement
2. OOD
3. predictability
4. uncertainty decomposition
5. forecast lifetime
6. VOI routing

## Phase 7 — Model ecology
1. ensemble
2. specialist/generalist
3. dynamic router
4. calibration

## Phase 8 — Selective prediction
1. abstention
2. conformal
3. risk control

## Phase 9 — Self-improvement
1. experience ledger
2. failure memory
3. research queue
4. negative knowledge
5. autonomous prioritization

## Phase 10 — Production hardening
1. watchdog
2. checkpoints
3. single writer
4. replay
5. rollback
6. artifact integrity

---

# 69. RECOMMENDED DATABASE RELATIONSHIP

Conceptual relational model:

\[
Sport
\rightarrow
Competition
\rightarrow
Season
\rightarrow
Event
\]

\[
Event
\rightarrow
Participant
\]

\[
Event
\rightarrow
SourceSnapshot
\]

\[
Prediction
\rightarrow
Event
\]

\[
Prediction
\rightarrow
FeatureSnapshot
\]

\[
Prediction
\rightarrow
ModelVersion
\]

\[
Prediction
\rightarrow
CalibrationVersion
\]

\[
Prediction
\rightarrow
Outcome
\]

\[
Outcome
\rightarrow
Experience
\]

\[
Experience
\rightarrow
FailureAnalysis
\]

\[
FailureAnalysis
\rightarrow
ResearchTask
\]

\[
ResearchTask
\rightarrow
Experiment
\]

\[
Experiment
\rightarrow
PromotionDecision
\]

This creates a closed research graph.

---

# 70. PSEUDOCODE — END-TO-END

\`\`\`text
for each candidate event:

    validate_event_identity()

    validate_target_semantics()

    cutoff = resolve_prediction_cutoff(event)

    sources = collect_sources_before(cutoff)

    if not sources_have_proven_PIT():
        state = DEFERRED / ABSTAIN
        log_failure_or_data_gap()
        continue

    features = build_features_as_of(cutoff)

    validate_feature_lineage(features)

    state_distribution = infer_latent_state(features)

    matchup_distribution = infer_matchup(
        team_state,
        opponent_state,
        interaction_features
    )

    context_distribution = infer_context(
        roster,
        venue,
        rest,
        travel,
        weather,
        regime
    )

    base_predictions = run_base_models(
        state_distribution,
        matchup_distribution,
        context_distribution
    )

    disagreement = measure_disagreement(base_predictions)

    ood = measure_ood(features)

    predictability = estimate_predictability(
        data_quality,
        disagreement,
        ood,
        regime,
        support
    )

    route = choose_model_route(
        sport,
        competition,
        regime,
        predictability,
        data_quality
    )

    simulation = run_conditional_monte_carlo(
        route,
        parameter_uncertainty,
        state_uncertainty,
        event_randomness
    )

    probabilities = aggregate(simulation)

    probabilities = calibrate(probabilities)

    uncertainty = decompose_uncertainty(...)

    action = choose_action(
        probabilities,
        uncertainty,
        predictability,
        stale_risk,
        VOI
    )

    persist_full_prediction_lineage()

    if action == ACQUIRE_MORE:
        collect_more_and_recompute()

    if action == ABSTAIN:
        persist_abstention_reason()

after outcome matures:

    settle_outcome()

    canonicalize_event_experience()

    score_prediction()

    classify_failure()

    update_experience_memory()

    generate_research_candidate()

    evaluate_candidate_chronologically()

    enforce_holdout_firewall()

    adopt_or_reject()

    monitor again
\`\`\`

---

# 71. RESEARCH EXPERIMENT TEMPLATE

Each experiment should answer:

### Hypothesis
What mechanism should improve?

### Mechanism
Why should it improve future generalization?

### Data
Which data and period?

### PIT
Why is every feature available by cutoff?

### Comparator
Which incumbent?

### OOS design
Which chronological folds?

### Primary metric
Usually LogLoss.

### Secondary
Brier, Accuracy, ECE, robustness.

### Segment checks
Sport, competition, regime, uncertainty, OOD.

### Ablation
What happens without the proposed component?

### Adversarial tests
Does it survive leakage/time-shift/data-removal checks?

### Cost
Compute and source burden.

### Decision
Accept / Hold / Reject.

---

# 72. MODEL EXPLANATION CONTRACT

Explanations should describe mechanisms and evidence, not invented causal certainty.

Preferred:

"Probability increased because the model's opponent-adjusted rating improved, the expected starting lineup became stronger, and disagreement between the specialist models fell."

Avoid:

"Team A will win because it has more momentum."

When explanation is a hypothesis:

label it as a hypothesis.

Prediction is not proof of causation.

---

# 73. CASE-LEVEL CORRECTNESS

Aggregate metrics can hide individual failure clusters.

For each event store:

- predicted class
- probability
- actual
- confidence
- predictability
- disagreement
- OOD
- data health
- key drivers
- failure path

Then search for:

\[
P(Error|Context)
\]

Examples:

- high-confidence losses
- low-predictability cases
- new competition
- roster uncertainty
- high disagreement
- OOD events
- regime transitions

The goal is to reduce catastrophic case-level errors without destroying calibration.

---

# 74. CONFIDENCE GOVERNANCE

High confidence is earned only when:

1. PIT is valid
2. identity is valid
3. data coverage is sufficient
4. models agree reasonably
5. OOD is acceptable
6. regime is known
7. calibration is good
8. history provides support
9. current state is sufficiently observed

If these fail, probability may still be emitted in research mode, but confidence must decrease.

---

# 75. SOURCE CONFLICT ENGINE

When sources disagree:

\[
Conflict = f(value\ difference,\ source\ reliability,\ independence,\ recency)
\]

Possible outcomes:

- reconcile
- prefer higher-reliability source
- retain both and widen uncertainty
- defer prediction
- trigger manual/research review

Never overwrite contradictory observations silently.

---

# 76. DATA RECONCILIATION

Before modeling, compare source representations:

\[
Source_A
\leftrightarrow
Source_B
\leftrightarrow
Canonical
\]

Check:

- event IDs
- teams
- dates
- scores
- participants
- status
- result type

A model should not be trusted on top of unresolved data conflicts.

---

# 77. FORECAST DELTA ENGINE

When a new snapshot arrives:

\[
\Delta p
=
p_{new}-p_{old}
\]

Explain change drivers.

Possible decomposition:

\[
\Delta p
=
\Delta lineup
+
\Delta injury
+
\Delta form
+
\Delta source
+
\Delta model
+
\Delta regime
\]

The decomposition is analytical attribution, not automatically causal attribution.

---

# 78. MODEL-FAILURE PREDICTOR

An additional meta-model can predict the probability that the current model will be wrong or materially degraded.

Input candidates:

- probability extremeness
- disagreement
- OOD
- predictability
- source conflict
- data completeness
- forecast age
- regime ambiguity
- recent model loss

Output:

\[
P(Failure|Context)
\]

This can trigger:

- specialist route
- additional data acquisition
- recomputation
- abstention

It must be trained only from past OOS outcomes.

---

# 79. TIME-TO-FAILURE RESEARCH

Beyond "will model fail?", estimate:

\[
P(T_{failure}\le t|CurrentState)
\]

This allows proactive maintenance.

Examples:

- source degradation
- calibration drift
- regime shift
- competition migration
- new patch
- roster instability

Useful output:

- stable
- watch
- imminent degradation
- degraded
- retrain required

---

# 80. PRODUCTION OBSERVABILITY

Monitor continuously:

- source freshness
- source error rate
- coverage
- missingness
- prediction frequency
- uncertainty
- disagreement
- OOD
- calibration drift
- regime drift
- abstention
- fallback
- error rate
- recovery rate
- artifact completeness

Operational observability and predictive observability are both required.

---

# 81. RECOVERY PROTOCOL

On failure:

1. preserve logs/artifacts
2. classify failure
3. reuse checkpoint
4. retry deterministic-safe stage
5. prevent duplicate computation
6. verify output
7. update failure ledger
8. resume only after downstream gate passes

Rollback when state corruption is plausible.

---

# 82. STOPPING RESEARCH

Stop a line of work when:

- no meaningful incremental value
- repeated negative result
- excessive cost
- insufficient data
- unresolved PIT
- robustness failure
- duplicated mechanism
- frontier saturation

But retain the record so it can be revisited after new evidence.

---

# 83. GOVERNANCE OF SCOPE

Expansion:

\[
DISCOVERED
\rightarrow
METADATA\_CHECKED
\rightarrow
DATA\_FEASIBLE
\rightarrow
PIT\_VALIDATED
\rightarrow
SHADOW
\rightarrow
OOS/ROBUSTNESS
\rightarrow
LIMITED\_PRODUCTION
\rightarrow
STABLE\_PRODUCTION
\rightarrow
SCALE\_UP
\]

Retraction is also valid:

\[
STABLE
\rightarrow
HOLD
\rightarrow
DEGRADED
\rightarrow
ROLLED\_BACK
\]

Growth is not always success.

A smaller trustworthy scope is better than a larger invalid scope.

---

# 84. THE ULTIMATE PREDICTION EQUATION

A useful conceptual form is:

\[
P(Y|X)
=
\int
P(
Y
|
GameState,
TeamState,
PlayerState,
Tactics,
Context
)
\]

\[
\cdot
P(
GameState
|
TeamState,
PlayerState,
Tactics,
Context
)
\]

\[
\cdot
P(
TeamState,
PlayerState,
Tactics
|
X
)
\,dState
\]

The complete future distribution can be expressed as:

\[
P(
Y,
S_{0:T},
E_{0:T},
Z_{0:T}
|
X_{cutoff}
)
\]

This is the closest mathematical summary of the full system.

---

# 85. WHAT "PERFECT" MEANS HERE

Perfect does not mean:

- 100% accuracy
- no losses
- one huge neural network
- maximum feature count
- maximum number of sports
- maximum compute
- always making a prediction

Perfect means the system is increasingly good at knowing:

- what it knows
- what it does not know
- when its information is valid
- when its model is appropriate
- when a result is inherently noisy
- when extra information is worth acquiring
- when it should abstain
- when it is drifting
- when it failed
- why it failed
- how to test the fix
- whether the fix truly generalizes
- when to promote it
- when to roll it back

---

# 86. FINAL OPERATING LAW

The system must continuously behave as follows:

\[
MONITOR
\rightarrow
DETECT
\rightarrow
DIAGNOSE
\rightarrow
RESEARCH
\rightarrow
IMPLEMENT
\rightarrow
TEST
\rightarrow
PIT\ CHECK
\rightarrow
OOS
\rightarrow
ROBUSTNESS
\rightarrow
FROZEN\ HOLDOUT
\rightarrow
DECIDE
\rightarrow
DEPLOY
\rightarrow
MONITOR
\rightarrow
LEARN
\rightarrow
REPEAT
\]

Never confuse:

\[
Action\ Green
\neq
Research\ Success
\neq
Production\ Approval
\]

Never confuse:

\[
Prediction
\neq
Certainty
\]

Never confuse:

\[
Historical\ Accuracy
\neq
Future\ Generalization
\]

Never confuse:

\[
Data\ Availability
\neq
PIT\ Validity
\]

Never confuse:

\[
Confidence
\neq
Predictability
\]

Never confuse:

\[
Code\ Exists
\neq
Evidence
\]

The final intelligence is the ability to produce a calibrated future distribution from correct, point-in-time information; choose the right model and timing; recognize uncertainty and tail risk; act conservatively when evidence is weak; and convert every matured result and failure into the next validated research cycle.

---

# APPENDIX A — CURRENT REPOSITORY ALIGNMENT

This specification is intentionally compatible with the current project architecture:

- canonical active scope via \`config/PROJECT_SCOPE_POLICY.json\`
- active production workflow
- 15-minute pre-event scheduler
- T-60 default automatic prediction
- manual arbitrary positive lead times
- source/collection guards
- PIT audit
- failure memory
- experience ledger
- dynamic model routing
- trajectory research
- conformal research
- watchdog/control-plane recovery
- explicit deferred sports
- fail-closed release behavior

The master specification expands the *target intelligence architecture* without silently changing the canonical scope.

---

# APPENDIX B — CURRENT RESEARCH PRIORITY RULE

Unless current evidence contradicts this, the default highest-value research ordering is:

1. strict PIT coverage for active lanes
2. exact event/participant identity
3. outcome completeness and semantics
4. current roster/availability integrity
5. chronological OOS quality
6. calibration and uncertainty
7. matchup/interactions
8. generative simulation
9. adaptive routing
10. selective prediction
11. frontier models

This order prevents "complexity before correctness."

---

# APPENDIX C — MINIMUM RELEASE CHECKLIST

Before any production promotion:

[ ] event semantics verified  
[ ] identity verified  
[ ] source provenance verified  
[ ] available_at proven  
[ ] no leakage  
[ ] no meta-leakage  
[ ] missingness audited  
[ ] chronological OOS  
[ ] calibration checked  
[ ] ablation completed  
[ ] robustness checked  
[ ] newest period checked  
[ ] frozen holdout protected  
[ ] reproducible fingerprint  
[ ] artifact present  
[ ] rollback pointer present  
[ ] recovery tested  
[ ] production gate passed  
[ ] status explicitly recorded

---

# APPENDIX D — ONE-SENTENCE DEFINITION

**Build a system that predicts the future not by pretending certainty, but by reconstructing the current state, simulating plausible futures, measuring what is unknown, selecting the appropriate model and information timing, refusing unsafe predictions, and continuously learning from verified outcomes without violating point-in-time integrity.**
