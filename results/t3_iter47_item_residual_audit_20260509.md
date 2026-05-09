# T3 Iter47 Item-Level Residual Audit

Diagnostic-only audit of saved corrected-target OOF predictions. No model was fit, no preregistration was written, and no LOOCV was run.

## Base

- N: 95
- CCC: `0.3784`
- MAE: `7.528`
- residual-vs-true r: `-0.7771`
- target reconstruction max abs diff: `0.000000`

## Top Items By Residual Correlation

| item | name | observable | r(item,residual) | r(item,pred) | oracle dCCC | oracle dMAE |
|---:|---|---:|---:|---:|---:|---:|
| 6 | pronation_supination | no | `-0.571` | `0.151` | `0.282` | `-1.183` |
| 4 | finger_tapping | no | `-0.528` | `0.215` | `0.256` | `-0.779` |
| 5 | hand_movements | no | `-0.469` | `0.319` | `0.226` | `-0.850` |
| 3 | rigidity | no | `-0.460` | `0.168` | `0.195` | `-0.837` |
| 2 | facial_expression | no | `-0.383` | `0.149` | `0.139` | `-0.459` |
| 16 | kinetic_tremor | no | `-0.372` | `-0.125` | `0.090` | `-0.546` |
| 8 | leg_agility | yes | `-0.359` | `0.345` | `0.148` | `-0.421` |
| 7 | toe_tapping | yes | `-0.330` | `0.335` | `0.125` | `-0.349` |
| 18 | rest_tremor_constancy | no | `-0.323` | `-0.095` | `0.068` | `-0.144` |
| 14 | global_spontaneity | yes | `-0.270` | `0.262` | `0.075` | `0.005` |

## Top Privileged Oracles

| item | name | observable | oracle dCCC | oracle CCC | r(item,residual) |
|---:|---|---:|---:|---:|---:|
| 6 | pronation_supination | no | `0.282` | `0.660` | `-0.571` |
| 4 | finger_tapping | no | `0.256` | `0.635` | `-0.528` |
| 5 | hand_movements | no | `0.226` | `0.605` | `-0.469` |
| 3 | rigidity | no | `0.195` | `0.573` | `-0.460` |
| 8 | leg_agility | yes | `0.148` | `0.527` | `-0.359` |
| 2 | facial_expression | no | `0.139` | `0.518` | `-0.383` |
| 7 | toe_tapping | yes | `0.125` | `0.504` | `-0.330` |
| 10 | gait | yes | `0.091` | `0.470` | `-0.247` |
| 16 | kinetic_tremor | no | `0.090` | `0.468` | `-0.372` |
| 14 | global_spontaneity | yes | `0.075` | `0.454` | `-0.270` |

## Observable Split

- Mean |r(item,residual)| for gait/balance-observable items 7-14: `0.247`
- Mean |r(item,residual)| for non-observable items: `0.371`
- Best observable privileged dCCC: `0.148`
- Best non-observable privileged dCCC: `0.282`

## Interpretation

- Parsed item totals exactly reconstruct the iter47 valid-range T3 target.
- Residual-item dependence is stronger for non-WearGait-observable clinical items than for gait/balance-observable items.
- Top residual-correlated item is 6 (pronation_supination), r=-0.571.
- Top privileged single-item oracle is item 6 (pronation_supination), delta CCC=0.282; this is non-deployable because it uses the true clinical item at prediction time.

## Decision

- No model promotion.
- No new LOOCV.
- Use this as stop-rule evidence against another WearGait-only T3 scalar-feature or calibration screen.
