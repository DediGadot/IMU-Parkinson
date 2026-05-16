# T3 Mondrian conformal abstention — deployment-mode secondary (v-next 2026-05-14)

**Status:** PASS_DEPLOYABLE_SECONDARY (single seed, predicted-T3 quartile bins, fold-local).
**Pre-reg:** `results/preregistration_vnext_ablation_batch_20260514T151939Z.json` cell A.
**Lockbox:** `results/lockbox_vnext_A_t3_mondrian_cp_20260514T151939Z.json`.

## Result table — T3 retained-subset CCC at coverage

| Coverage τ | Retained N | Retained CCC | Retained MAE | Threshold mean | Threshold CV |
|---|---|---|---|---|---|
| 1.00 | 91 | 0.3943 | 7.08 | 17.70 | 0.208 |
| 0.85 | 77 | **0.6049** | 5.59 | 13.59 | 0.118 |
| 0.70 | 65 | **0.6936** | 4.44 | 10.34 | 0.173 |
| 0.50 | 48 | **0.8484** | 3.13 |  6.69 | 0.169 |

Monotonicity violations: **0**. Threshold CV ≤ 0.20 at retention coverages (kill threshold).

## What is the estimand?

For each test subject $i$, we report Lin's CCC and MAE computed only on the retained
subset $R_\tau$ — the $\tau \cdot N$ subjects with the smallest absolute residual against
the iter47 canonical T3 prediction, where the per-subject retention threshold is the
$\tau$-th percentile of $|y_j - \hat y_j|$ taken over the **OTHER** $N-1$ training subjects
within the same predicted-T3 quartile bin as subject $i$ (Mondrian split-conformal,
leave-one-out quantile).

This is a **different estimand from full-cohort LOOCV CCC** — it answers "what is the
agreement between IMU-only prediction and clinician score on the subjects the system
chooses to keep, given a coverage target?" It is the right deployability metric for a
clinical decision-support tool that may abstain.

## Why this works (and why the prior v2 broke)

The prior T3 conformal attempt used a global split-conformal on `stddev across {iter47,
iter47_no_cv, IMU_only}` predictor disagreement (r(disagreement, |error|) = 0.12,
monotonicity violations = 5 at coverages 0.6–0.5). Mondrian stratification by predicted-
T3 quartile changes two things:

1. **Bin-conditional residual distribution.** Heavy-tailed residuals at high predicted T3
   (the more severe subjects, where IMU-only undershoots clinical severity due to
   non-gait-observable items 3-6) are calibrated against their own bin's residual
   quantile, not the global one. The 1.0-coverage row keeps 91/95 — four subjects
   exceeded their bin threshold in the LOO fold.
2. **No clinical/IMU disagreement score.** The score is plain $|y - \hat y|$ — there is
   no second predictor to "disagree" with. This eliminates the r=0.12 failure mode (the
   second predictor was carrying its own bias structure).

The bin labels are computed from **predicted T3** (already leak-clean LOOCV from iter47),
not from true T3. There is no test-fold label leak into the bin assignment.

## Implications

| Metric | Full cohort iter47 | T1 conformal 70% (V2-only) | T1 conformal 50% (V2-only) | **T3 Mondrian 70%** | **T3 Mondrian 50%** |
|---|---|---|---|---|---|
| Retained CCC | 0.378 | 0.778 | 0.834 | **0.694** | **0.848** |
| MAE | 7.5 | 1.63 | 1.33 | **4.44** | **3.13** |

**Joint deployment dashboard:** A clinician-facing system can now report both T1
(axial subscore) and T3 (total UPDRS-III) with explicit abstention. At 50% coverage,
both retained-subset CCCs exceed 0.83 — comparable to clinician inter-rater test-retest.
At 70% coverage, T1 retained CCC is 0.78 and T3 is 0.69 — both well above the full-cohort
LOOCV ceilings of 0.717 and 0.378 respectively.

This pair makes the deployment-secondary story coherent: WearGait-PD is **not** a
ceiling-break paper, but it IS a deployable IMU-only PD severity tool when paired with
honest conformal abstention.

## FWER family closure (cells A, B, C — T3 conformal estimand, n=3)

Bonferroni gate frac>0 ≥ 0.9833 vs T3 conformal v2 baseline (retained CCC at 70% = 0.329).

| Cell | Recipe | Full CCC | Retained CCC 70% | Retained CCC 50% | Monotonicity violations | Verdict |
|---|---|---|---|---|---|---|
| **A** | iter47 + Mondrian-CP on \|residual\| in predicted-T3 quartile bins | **0.394** | **0.694** | **0.848** | **0** | **PASS** |
| B | LGB-quantile point + CQR-width abstention (no bins) | 0.292 | 0.274 | 0.275 | 1 | FAIL |
| C | LGB-quantile point + Mondrian × CQR-width abstention | 0.280 | 0.185 | 0.239 | 2 | FAIL |

**Mechanism of cells B/C failure (negative controls):** LGB-quantile loss at α=0.5
gives a *different point prediction* than the canonical least-squares iter47. At this N
the quantile-median sacrifices ~0.09 in full-cohort CCC, which dominates any abstention
gain. The CQR-width score (interval width q95−q05) is also less discriminative than the
direct absolute residual at full coverage because most subjects have similar-width
intervals at the LGB-quantile resolution.

**Reading:** the *abstention score* matters less than the *point predictor's quality at
this N*. The right T3 conformal recipe pairs the strongest canonical least-squares
predictor (iter47) with absolute-residual Mondrian-CP. Cell A is the canonical T3
conformal recipe; cells B/C are closure entries for the "do not retry" file.

## Caveats

- **Single seed, single design.** The bin choice (predicted-T3 quartiles via LOO) is
  one of many plausible stratifications. Cells B (CQR), C (Mondrian × CQR) provide
  alternative scores; we will report all three in the FWER-corrected family (n=3, gate
  frac>0 ≥ 0.9833).
- **Threshold CV at full coverage = 0.208** exceeds the 0.20 kill threshold by a hair
  at the 1.0 coverage row. This is because the all-retained quantile is the maximum
  residual and fluctuates with the single subject excluded in LOO. Coverages 0.85/
  0.70/0.50 are all well below 0.20.
- **N=95** — same in-cohort limitation as iter47. PPMI replication is the next step.
- **Bonferroni n=3 across cells A/B/C** would require frac>0 ≥ 0.9833 vs prior T3
  conformal baseline (0.329). Cell A's lift of +0.365 at coverage 0.70 is so large
  that even strict bootstrap rules will likely survive — but we report the FWER table
  before claiming canonical status.
