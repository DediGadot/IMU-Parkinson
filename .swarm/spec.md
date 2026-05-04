# Specification: Strict-Inductive T3 CCC Improvement

## Feature Description

The project needs a leakage-proof research-execution workflow to improve prediction of total Parkinson motor severity from wearable movement data. The work must prioritize scientifically plausible signal sources, use only existing project data or publicly available external data, and report whether any candidate meaningfully improves total-score concordance beyond the current honest deployment baseline.

The goal is not to recover previously inflated transductive results. The goal is to identify whether additional observable mobility signal, public-data pretraining signal, or target-structure signal can produce a credible, reproducible improvement in total-score prediction under strict subject-level inductive evaluation.

## User Scenarios

### Scenario 1: Leakage-proof candidate screening
Given the researcher has one or more candidate improvement ideas,
When the candidate is evaluated,
Then the reported screening result MUST be produced under subject-level inductive evaluation with no held-out-subject labels, ranks, target-derived statistics, or fitted transforms entering training.

### Scenario 2: Public-data-only external signal
Given a candidate uses data beyond the current cohort,
When external data is used for representation learning or transfer,
Then the data source MUST be publicly available or controlled-access public, MUST be documented, and MUST be verified as disjoint from the target evaluation cohort.

### Scenario 3: Significant T3 improvement decision
Given a candidate completes screening,
When its total-score concordance is compared against the current honest baseline,
Then the project MUST decide whether to continue, stop, or pre-register confirmation based on predefined improvement thresholds.

### Scenario 4: Confirmatory lockbox evaluation
Given a single candidate passes the screening threshold,
When confirmatory evaluation is run,
Then exactly one pre-registered confirmation run SHOULD be used for the headline result, and the result MUST be reported regardless of outcome.

### Scenario 5: Negative result handling
Given a candidate fails to improve total-score concordance,
When the result is reviewed,
Then the failure SHOULD be recorded as evidence against that signal source rather than repeatedly re-tuning the same idea.

## Functional Requirements

- FR-001: The workflow MUST preserve subject-level separation for every reported evaluation.
- FR-002: The workflow MUST fit every target-derived or distribution-derived operation using training subjects only within each evaluation fold.
- FR-003: The workflow MUST exclude held-out-subject labels, ranks, prototypes, anchors, fitted normalizers, fitted imputers, selected features, calibration parameters, and learned pooling weights from any training stage before the held-out subject is evaluated.
- FR-004: The workflow MUST use only the existing cohort data or publicly available external data sources.
- FR-005: The workflow MUST document the access status of every external data source as open public, controlled-access public, or unavailable.
- FR-006: The workflow MUST verify that any external data used for representation learning is disjoint from the target evaluation cohort.
- FR-007: The workflow MUST evaluate candidates against the current honest total-score baseline before any confirmatory run is selected.
- FR-008: The workflow MUST include null or sanity checks sufficient to detect label leakage, subject-identity leakage, cache-join leakage, and impossible test-only feature use.
- FR-009: The workflow MUST report total-score concordance, calibration slope, mean absolute error, Pearson correlation, prediction variance, and sample count for every candidate.
- FR-010: The workflow MUST preserve the lockbox discipline: screening results may select one candidate, but confirmatory results MUST NOT be repeatedly re-run to choose a better headline.
- FR-011: The workflow SHOULD prioritize candidates that add biologically plausible mobility signal not already exhausted by prior baseline, shallow aggregation, frozen representation, distillation, or stacking experiments.
- FR-012: The workflow SHOULD use available remote compute for heavy experiment execution and record whether the run completed successfully.
- FR-013: The workflow SHOULD fail fast on missing data, missing dependencies, failed leakage checks, or invalid evaluation setup rather than silently falling back to weaker behavior.
- FR-014: The workflow MUST NOT use clinical ground-truth severity variables as deployable input features; such variables MAY be used only as targets, validation labels, or explicitly labeled oracle ceilings.
- FR-015: The workflow MUST distinguish exploratory screening metrics from confirmatory headline metrics.

## Success Criteria

- SC-001: A candidate is considered screening-positive only if total-score concordance improves beyond the current honest baseline by a practically meaningful margin and no leakage or null-check failure is observed.
- SC-002: A candidate is considered strong enough for confirmation if screening total-score concordance reaches at least 0.35 or improves by at least 0.08 absolute concordance over the current honest baseline, with calibration slope and prediction variance moving in the correct direction.
- SC-003: A confirmatory result is considered a glass-ceiling break if total-score concordance reaches at least 0.40 under pre-registered strict inductive evaluation or mean absolute error improves below 6.5 without leakage.
- SC-004: A candidate is considered unsuccessful if it does not exceed the current honest baseline beyond expected noise or if any required leakage/sanity check fails.
- SC-005: The research loop should stop or change strategy after three consecutive candidates fail to improve total-score concordance by a meaningful margin.

## Key Entities

- Candidate experiment
- External public data source
- Evaluation fold
- Screening result
- Confirmatory result
- Leakage check
- Null check
- Pre-registration record
- Remote execution record

## Edge Cases and Failure Modes

- External data may be controlled-access rather than immediately downloadable.
- External data may use different sensors, sampling rates, body placements, or labels, creating transfer mismatch.
- Apparent improvement may arise from site, subject identity, cache joins, target leakage, or repeated confirmatory selection.
- Total-score prediction may remain limited because some clinical items are not directly observable from gait or movement sensors.
- Calibration may improve slope without increasing rank information; such changes alone should not be treated as a true ceiling break.
- Candidate models may collapse predictions toward the population mean, improving mean absolute error without improving concordance.
- Remote execution may fail because of missing raw data, missing dependencies, expired credentials, or insufficient disk space.
