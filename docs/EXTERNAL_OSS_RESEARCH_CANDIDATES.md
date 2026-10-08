# External OSS Research Candidates

This document is a research registry, not a production dependency list.

## Tier A

### 1. mattpocock/skills

Status: PROMOTION_CANDIDATE for research/engineering use only.

Use it to encode repeatable research procedures such as PIT audit, OOS review, calibration review, robustness review, and failure analysis as reusable Agent Skills.

Do not use skill output as prediction evidence and do not make the production predictor depend on the skill repository.

### 2. Fission-AI/OpenSpec

Status: PROMOTION_CANDIDATE for research/engineering use only.

Use it to prototype a structured research specification flow:

Hypothesis -> Spec -> Design -> Tasks -> Implementation -> Verification.

The repository's current 2026-10-06 main commit contains an explicit residual security-advisory treatment for the `braces` dependency. That is a review item, not a reason to silently bypass security checks.

### 3. Graphify-Labs/graphify

Status: PROMOTION_CANDIDATE for research/engineering use only.

Use it to build a local code/config/document relationship graph and investigate component lineage, duplication, and disconnected research artifacts.

Do not feed graph-derived claims into production prediction logic without local validation.

## Tier B

- `Panniantong/Agent-Reach`: research candidate for web/source discovery and information acquisition.
- `obra/superpowers`: research candidate for engineering methodology.
- `firecrawl/firecrawl`: HOLD; consider only as a retrieval fallback after license/security/operational review.

## Adoption gates

Every candidate remains subject to the project's normal external-research contract:

DISCOVER
-> SOURCE_VERIFIED
-> RELEVANCE_CHECKED
-> COST_CHECKED
-> SECURITY_CHECKED
-> LOCAL_IMPLEMENTATION
-> LOCAL_REPRODUCTION
-> OOS
-> ROBUSTNESS
-> FROZEN_HOLDOUT
-> SHADOW
-> DECISION

No candidate in this document is ADOPTED or PRODUCTION.

## Current implementation rule

The registry itself must not add an import or runtime dependency to `requirements.txt`, Production workflows, prediction artifacts, model registry, or active sport scope.
