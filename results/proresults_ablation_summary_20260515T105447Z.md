# Pro-results ablation closure — 20260515T105447Z

**Overall verdict**: `NEGATIVE_ABLATION_CLOSURE_OF_PRORESULTS_IDEAS`

**Iter34 baseline T1 LOOCV CCC** = 0.717 (N=92)

## Headline T1 CCC slots (FWER n=5, gate=0.99, MCID=+0.025)

| Slot | Δ CCC vs iter34 | frac>0 | 5-fold Δ̄ | seed std | N1 scrambled-y CCC | N2 SID-shuffle CCC | Verdict |
|---|---|---|---|---|---|---|---|
| S1_sumaware_bayesian | -0.0075 | 0.0035 | -0.0117 | 0.0043 | 0.7045 | 0.7127 | NEGATIVE_DELTA |
| S2_topofractal8 | -0.0245 | 0.013 | -0.027 | 0.0031 | 0.71 | 0.7147 | NEGATIVE_DELTA |
| S3_ordinal_composer | None | None | None | None | None | None | FAIL |
| S5_microbatch_item13only_audit | None | None | None | None | None | None | FAIL |

## Descriptiveness slot S6 (no CCC headline)
- Stable PH cols on item 13: 0
- Stable PH cols on item 14: 0
- Stable MFDFA cols on item 10: 0
- Verdict: DESCRIPTIVENESS_RECORDED

## Deployable secondary S7 (lifetime FWER n=10, gate=0.995)

| Coverage | slotD baseline | S7 retained CCC | Δ vs slotD | frac>0 | Verdict |
|---|---|---|---|---|---|
| cov_70 | 0.7876 | None | None | None | FAIL |
| cov_50 | 0.8338 | None | None | None | FAIL |