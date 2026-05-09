# Current Headline Influence Audit

- Created: `2026-05-09T03:40:53+00:00`
- Scope: diagnostic only; no model selection, no filtering rule, no LOOCV rerun.

## Baseline And Jackknife Summary

| Model | N | CCC | MAE | leave-one CCC min | leave-one CCC max | CCC jackknife SE | top1 abs dCCC | top5 share | Gini | red flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `t1_iter12_honest_floor` | 94 | 0.6550 | 1.5614 | 0.6196 | 0.6732 | 0.0629 | 0.0354 | 0.3086 | 0.6263 | gini_abs_delta_ccc_gt_0_40 |
| `t1_iter34_hybrid_candidate` | 93 | 0.7366 | 1.7310 | 0.6997 | 0.7476 | 0.0546 | 0.0369 | 0.3016 | 0.5662 | gini_abs_delta_ccc_gt_0_40 |
| `t3_iter47_validrange_current` | 95 | 0.3784 | 7.5280 | 0.3402 | 0.4056 | 0.0861 | 0.0381 | 0.2840 | 0.6009 | gini_abs_delta_ccc_gt_0_40 |

## Influence Correlations

| Model | target vs delta CCC | abs(target-median) vs abs(delta CCC) | abs(target-median) vs abs(error) | abs(error) vs abs(delta CCC) |
|---|---:|---:|---:|---:|
| `t1_iter12_honest_floor` | -0.3262 | 0.7121 | 0.5496 | 0.4666 |
| `t1_iter34_hybrid_candidate` | -0.3819 | 0.6840 | 0.1527 | 0.3281 |
| `t3_iter47_validrange_current` | -0.4087 | 0.6779 | 0.5486 | 0.4200 |

## T3 Top Influence Subjects

| SID | site | y | pred | residual | CCC without | delta CCC | missing raw | target delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `NLS196` | NLS | 52.0 | 40.20 | -11.80 | 0.3402 | -0.0381 | 0 | 0.0 |
| `NLS179` | NLS | 43.0 | 41.99 | -1.01 | 0.3477 | -0.0307 | 0 | 0.0 |
| `NLS124` | NLS | 41.0 | 42.85 | 1.85 | 0.3499 | -0.0285 | 0 | 0.0 |
| `NLS141` | NLS | 17.0 | 40.04 | 23.04 | 0.4056 | 0.0272 | 0 | 0.0 |
| `NLS201` | NLS | 59.0 | 35.45 | -23.55 | 0.3580 | -0.0204 | 0 | 0.0 |
| `NLS121` | NLS | 11.0 | 31.06 | 20.06 | 0.3984 | 0.0201 | 0 | 0.0 |
| `NLS140` | NLS | 40.0 | 37.60 | -2.40 | 0.3598 | -0.0185 | 0 | 0.0 |
| `NLS135` | NLS | 43.0 | 34.87 | -8.13 | 0.3626 | -0.0157 | 0 | 0.0 |
| `NLS173` | NLS | 38.0 | 20.60 | -17.40 | 0.3924 | 0.0140 | 0 | 0.0 |
| `NLS102` | NLS | 14.0 | 13.25 | -0.75 | 0.3661 | -0.0123 | 0 | 0.0 |

## T1 Candidate Delta Robustness

- Matched N: `93`
- iter12 matched CCC: `0.6554`
- iter34 matched CCC: `0.7366`
- Base delta: `+0.0812`
- Leave-one minimum delta: `+0.0629`
- Sign flip under leave-one deletion: `False`

## Decision

No single-subject influence pattern justifies a model update. T3 max |leave-one CCC delta| is 0.0381; T1 iter34-minus-iter12 matched delta stays positive under all leave-one deletions (minimum 0.0629). Influence is still severity-tail concentrated, so this is a claim-fragility caveat rather than a filtering rule.

Manual review candidates are high-influence rows only; they are not a filtering rule.

Machine-readable report: `results/current_headline_influence_audit_20260509.json`
