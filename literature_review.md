# Literature Review

This review is aligned to `CONT.md` and the clean Paper 3 reruns. It is not a place to preserve pre-audit headline numbers.

## Comparison Rules

UPDRS regression papers are only loosely comparable unless they match on:

- cohort composition (`PD-only` vs `PD+HC`)
- split level (`subject-level` vs window-level leakage)
- evaluation design (`LOOCV` vs held-out test)
- task context (`free-living ADL` vs controlled clinical gait)

Small-cohort PD-only LOOCV papers may achieve lower MAE than a mixed-cohort held-out benchmark without being methodologically stronger.

## Verified External References

### Hssayeni et al. 2021

- 24 PD subjects
- wrist + ankle gyroscopes
- free-body ADL
- LOOCV
- reported `MAE 5.95`, `r 0.74`

Interpretation:
- important external reference
- not directly comparable to our clean mixed-cohort held-out benchmark
- smaller and easier protocol, but useful as a PD-only LOOCV target

### Shuqair et al. 2024

- same 24-subject PD-only setting as Hssayeni
- self-supervised CNN-LSTM style pipeline
- LOOCV
- reported strong correlation on a very small cohort

Interpretation:
- useful as a small-cohort PD-only reference
- not directly comparable to a 178-subject held-out benchmark

### Parera / IS22

- widely quoted low MAE
- methodology strongly suggests leakage-prone evaluation

Interpretation:
- should not be used as a clean performance target

### Sotirakis 2023

- larger cohort
- visit-level cross-validation structure

Interpretation:
- better than obvious window leakage, but still vulnerable to within-subject dependence if visits are split across folds

## Our Current Position

The clean audited WearGait-PD results are:

| Model | MAE | r | Status |
|------|-----|---|--------|
| LGB baseline | 9.47 | 0.605 | clean deployable reference |
| pre-specified stack | 9.68 | 0.579 | clean primary model |
| sensitivity stack | 9.40 | 0.605 | exploratory sensitivity only |
| H&Y ceiling | 8.22 | 0.705 | clinical upper bound |

These results are:

- stronger than the old contaminated manuscript claims in terms of methodological honesty
- weaker than the old touched-test numbers in absolute error
- not yet comparable to PD-only LOOCV papers unless the corrected nested LOOCV rerun is completed

## Claims We Can Make Relative to Literature

- We have an audited subject-level held-out benchmark on WearGait-PD.
- We should not claim cross-dataset SOTA based on the clean current results.
- We should not compare the clean held-out benchmark directly against leakage-prone or protocol-mismatched studies as if they were apples-to-apples.
- The most defensible literature comparison is protocol-aware: held-out mixed-cohort benchmark on one hand, corrected PD-only LOOCV on the other.

## Practical Literature Takeaway

The field still has three persistent problems:

- tiny PD-only cohorts
- leakage-prone or weakly controlled validation
- inconsistent problem definitions

That context makes evaluation hygiene more important than squeezing out another `0.1-0.2` MAE on a single split.
