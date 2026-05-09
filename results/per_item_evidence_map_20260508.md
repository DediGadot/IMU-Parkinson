# Per-Item Evidence Map - 2026-05-08

Per-item CCCs must be reported with their current claim scope. Items 9-14 are components of the canonical iter12 T1 floor, items 15 and 18 are supplementary iter17 per-item wins, items 4-8/16/17 are historical iter8 lockbox context, and items 1-3 remain backfill-only for this current map. The T3 per-item sum is a historical dead route, not a current T3 headline.

- Passed: `True`
- Status counts: `{'missing_or_backfill_only_unobservable': 3, 'historical_iter8_per_item_lockbox_supplementary': 7, 'current_t1_iter12_component': 6, 'iter17_reportable_per_item_win': 2}`
- Missing source artifacts: `0`

## Composite Context

| Composite | Status | CCC | MAE | N | Items |
|---|---|---:|---:|---:|---|
| T1 iter12 sum | current_canonical_floor | 0.6550 | 1.561 | 94 | [9, 10, 11, 12, 13, 14] |
| T3 per-item sum | historical_dead_route_not_current_t3 | 0.2646 | 7.482 | 94 | 1-18 |

## Item Map

| Item | Status | Variant | CCC | Std | MAE | N | Claim scope |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | missing_or_backfill_only_unobservable | v2_baseline | n/a | n/a | n/a | n/a | no_current_reportable_loocv_per_item_lockbox |
| 2 | missing_or_backfill_only_unobservable | v2_baseline | n/a | n/a | n/a | n/a | no_current_reportable_loocv_per_item_lockbox |
| 3 | missing_or_backfill_only_unobservable | v2_baseline | n/a | n/a | n/a | n/a | no_current_reportable_loocv_per_item_lockbox |
| 4 | historical_iter8_per_item_lockbox_supplementary | v2_baseline | 0.0916 | 0.0379 | 1.254 | 94 | historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route |
| 5 | historical_iter8_per_item_lockbox_supplementary | v2_baseline | 0.0814 | 0.0317 | 1.412 | 94 | historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route |
| 6 | historical_iter8_per_item_lockbox_supplementary | lr_multitask | -0.0661 | 0.0315 | 1.438 | 94 | historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route |
| 7 | historical_iter8_per_item_lockbox_supplementary | item_plus_v2 | 0.2711 | 0.0165 | 0.629 | 94 | historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route |
| 8 | historical_iter8_per_item_lockbox_supplementary | item_plus_v2 | 0.1696 | 0.0263 | 0.796 | 94 | historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route |
| 9 | current_t1_iter12_component | hy_residual_item | 0.4437 | 0.0139 | 0.342 | 94 | component_of_canonical_t1_iter12_floor_not_standalone_headline |
| 10 | current_t1_iter12_component | item_plus_v2 | 0.4755 | 0.0204 | 0.509 | 94 | component_of_canonical_t1_iter12_floor_not_standalone_headline |
| 11 | current_t1_iter12_component | item_dedicated | 0.3794 | 0.0185 | 0.363 | 94 | component_of_canonical_t1_iter12_floor_not_standalone_headline |
| 12 | current_t1_iter12_component | item_plus_v2 | 0.5928 | 0.0084 | 0.523 | 94 | component_of_canonical_t1_iter12_floor_not_standalone_headline |
| 13 | current_t1_iter12_component | item_plus_v2 | 0.1169 | 0.0017 | 0.621 | 94 | component_of_canonical_t1_iter12_floor_not_standalone_headline |
| 14 | current_t1_iter12_component | item_plus_v2 | 0.3788 | 0.0135 | 0.524 | 94 | component_of_canonical_t1_iter12_floor_not_standalone_headline |
| 15 | iter17_reportable_per_item_win | item_only | 0.1099 | 0.0065 | 1.088 | 94 | supplementary_per_item_lockbox_win_not_t1_t3_composite_update |
| 16 | historical_iter8_per_item_lockbox_supplementary | lr_multitask | 0.1469 | 0.0122 | 0.900 | 94 | historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route |
| 17 | historical_iter8_per_item_lockbox_supplementary | v2_baseline | 0.1774 | 0.0176 | 1.316 | 93 | historical_per_item_lockbox_supplementary_not_current_t1_or_t3_route |
| 18 | iter17_reportable_per_item_win | hy_residual_item_v2 | 0.4858 | 0.0204 | 0.887 | 93 | supplementary_per_item_lockbox_win_not_t1_t3_composite_update |

## Key Checks

| Check | Passed |
|---|---:|
| eighteen_item_rows_present | `True` |
| status_counts_match_current_claim_scope | `True` |
| t1_component_item9_metric_matches_iter8_batch | `True` |
| t1_component_item12_metric_matches_iter8_batch | `True` |
| iter17_item15_metric_matches_lockbox | `True` |
| iter17_item18_metric_matches_lockbox | `True` |
| canonical_t1_sum_is_current_composite | `True` |
| t3_per_item_sum_is_historical_dead_route | `True` |
| all_source_artifacts_exist | `True` |

Next action: Do not launch another WearGait-only per-item composite. Use this map for manuscript and handoff evidence; new composite claims require new data or a genuinely new target representation.
