# Per-Item OOF Companion Scope Audit - 2026-05-08

Per-item OOF companions are scope/integrity checked as finite one-dimensional arrays whose length matches either the JSON-reported evaluation N or the current 94-slot T1 cohort. Per-item JSON row-level equality cannot be checked because the JSON artifacts do not contain per_subject.y_pred. For current T1 items 9-14, the companion arrays must sum exactly to the canonical iter12 T1 OOF vector.

- Passed: `True`
- OOF-backed rows: `15`
- Row-level JSON comparison available count: `0`
- Warnings: `1`

## Key Checks

| Check | Passed |
|---|---:|
| per_item_map_source_passed | `True` |
| all_15_oof_backed_rows_have_finite_expected_slot_arrays | `True` |
| row_level_json_prediction_comparison_unavailable_for_per_item_artifacts | `True` |
| t1_iter12_item_oofs_sum_to_canonical_oof | `True` |
| item18_valid_n_mismatch_recorded_as_warning_not_failure | `True` |

## T1 Iter12 Companion Summation

- Max abs diff vs canonical T1 OOF: `0.0000000000`
- Recomputed CCC from summed item OOFs: `0.6550`
- Recomputed MAE from summed item OOFs: `1.561`

| Item | Valid target N | OOF companion CCC | Map summary CCC | Relation |
|---:|---:|---:|---:|---|
| 9 | 94 | 0.4486 | 0.4437 | OOF companion metric is not expected to equal map summary metric because the per-item JSON stores seed-summary metrics, not row-level ensemble predictions. |
| 10 | 94 | 0.4822 | 0.4755 | OOF companion metric is not expected to equal map summary metric because the per-item JSON stores seed-summary metrics, not row-level ensemble predictions. |
| 11 | 94 | 0.3826 | 0.3794 | OOF companion metric is not expected to equal map summary metric because the per-item JSON stores seed-summary metrics, not row-level ensemble predictions. |
| 12 | 94 | 0.5975 | 0.5928 | OOF companion metric is not expected to equal map summary metric because the per-item JSON stores seed-summary metrics, not row-level ensemble predictions. |
| 13 | 94 | 0.1197 | 0.1169 | OOF companion metric is not expected to equal map summary metric because the per-item JSON stores seed-summary metrics, not row-level ensemble predictions. |
| 14 | 94 | 0.3857 | 0.3788 | OOF companion metric is not expected to equal map summary metric because the per-item JSON stores seed-summary metrics, not row-level ensemble predictions. |

## OOF-Backed Rows

| Item | Status | JSON N | OOF shape | Finite | Row-level JSON comparison | Passed |
|---:|---|---:|---|---:|---:|---:|
| 4 | historical_iter8_per_item_lockbox_supplementary | 94 | [94] | `True` | `False` | `True` |
| 5 | historical_iter8_per_item_lockbox_supplementary | 94 | [94] | `True` | `False` | `True` |
| 6 | historical_iter8_per_item_lockbox_supplementary | 94 | [94] | `True` | `False` | `True` |
| 7 | historical_iter8_per_item_lockbox_supplementary | 94 | [94] | `True` | `False` | `True` |
| 8 | historical_iter8_per_item_lockbox_supplementary | 94 | [94] | `True` | `False` | `True` |
| 9 | current_t1_iter12_component | 94 | [94] | `True` | `False` | `True` |
| 10 | current_t1_iter12_component | 94 | [94] | `True` | `False` | `True` |
| 11 | current_t1_iter12_component | 94 | [94] | `True` | `False` | `True` |
| 12 | current_t1_iter12_component | 94 | [94] | `True` | `False` | `True` |
| 13 | current_t1_iter12_component | 94 | [94] | `True` | `False` | `True` |
| 14 | current_t1_iter12_component | 94 | [94] | `True` | `False` | `True` |
| 15 | iter17_reportable_per_item_win | 94 | [94] | `True` | `False` | `True` |
| 16 | historical_iter8_per_item_lockbox_supplementary | 94 | [94] | `True` | `False` | `True` |
| 17 | historical_iter8_per_item_lockbox_supplementary | 93 | [93] | `True` | `False` | `True` |
| 18 | iter17_reportable_per_item_win | 93 | [94] | `True` | `False` | `True` |

## Warnings

- item 18: `json_reported_valid_n_differs_from_oof_slot_len` ({'item': 18, 'warning': 'json_reported_valid_n_differs_from_oof_slot_len', 'artifact': 'results/lockbox_peritem_18_iter17hyp_hy_residual_item_v2_20260503_221544.json', 'json_reported_n': 93, 'oof_slot_len': 94, 'interpretation': 'companion array has full 94-slot cohort shape; JSON reports valid target/evaluation count.'})

Machine-readable report: `results/per_item_oof_companion_scope_audit_20260508.json`
