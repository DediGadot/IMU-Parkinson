# T3 Iter47 Domain Residual Audit

- Created: `2026-05-09T03:58:32+00:00`
- Scope: diagnostic only; uses true clinical domain labels; no model promotion, no filtering, no LOOCV rerun.
- Parsed valid-range total max absolute difference vs iter47 target: `0.000000`

## Baseline

- Current iter47 CCC: `0.3784`
- Current iter47 MAE: `7.5280`
- N: `95`

## Domain Residual Associations

| Domain | Items | residual r | true r | pred r | abs-error r | oracle CCC | dCCC | dMAE | deployable proxy |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `unobservable_non_gait` | 1,2,3,4,5,6,15,16,17,18 | -0.8004 | 0.8904 | 0.2118 | -0.0233 | 0.8500 | 0.4716 | -2.9976 | no |
| `upper_limb_brady_4_6` | 4,5,6 | -0.6224 | 0.7643 | 0.2753 | 0.0009 | 0.7156 | 0.3372 | -1.3769 | no |
| `appendicular_brady_4_8_14` | 4,5,6,7,8,14 | -0.6156 | 0.8341 | 0.3925 | 0.0283 | 0.7226 | 0.3442 | -1.5154 | no |
| `rigidity_3` | 3 | -0.4504 | 0.5347 | 0.1708 | 0.0600 | 0.5665 | 0.1882 | -0.7634 | no |
| `gait_balance_7_14` | 7,8,9,10,11,12,13,14 | -0.4135 | 0.7389 | 0.5382 | 0.0818 | 0.5867 | 0.2083 | -0.7024 | yes |
| `lower_limb_brady_7_8` | 7,8 | -0.4085 | 0.6453 | 0.4017 | 0.0646 | 0.5691 | 0.1908 | -0.6390 | yes |
| `tremor_15_18` | 15,16,17,18 | -0.4068 | 0.2957 | -0.1336 | -0.1257 | 0.4914 | 0.1130 | -0.5798 | no |
| `speech_face_1_2` | 1,2 | -0.3369 | 0.5069 | 0.2923 | 0.0655 | 0.5030 | 0.1247 | -0.2631 | no |
| `t1_items_9_14` | 9,10,11,12,13,14 | -0.3223 | 0.6560 | 0.5426 | 0.0791 | 0.5211 | 0.1427 | -0.3286 | yes |
| `pigdf_like_9_13` | 9,10,11,12,13 | -0.2978 | 0.6334 | 0.5435 | 0.0949 | 0.5060 | 0.1277 | -0.2183 | yes |

## Privileged Multidomain Oracle

- Ridge alpha: `10.0`
- CCC: `0.8533`
- MAE: `4.4870`
- Delta CCC vs current: `+0.4749`
- Delta MAE vs current: `-3.0410`

## Decision

Current iter47 T3 residuals are most associated with unobservable_non_gait (r=-0.8004). The best single-domain privileged oracle is unobservable_non_gait (delta CCC +0.4716); the best gait-observable proxy is gait_balance_7_14 (delta CCC +0.2083). Because these corrections use true clinical domain labels, they are explanation only.

These oracle corrections are non-deployable because they require true Part III domain labels at test time. Use this only to explain residual anatomy and to decide whether a future target representation needs external data.

Machine-readable report: `results/t3_iter47_domain_residual_audit_20260509.json`
