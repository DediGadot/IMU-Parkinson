# Headline Metric Recompute Audit - 2026-05-08

Recompute headline/candidate metrics from stored per-subject prediction artifacts where available; LOSO is recomputed from per-seed rows.

- Passed: `True`
- Tolerance: `0.0005`
- Checks: `9`

## Checks

### t1_iter12_honest_floor

- Passed: `True`
- Source: `results/t1_iter12_honest_composite.json`
- Method: full_metrics(per_subject.y_true, per_subject.y_pred)
- `n` recomputed `94` vs claimed `94` -> `True`
- `ccc` recomputed `0.655` vs claimed `0.655` -> `True`
- `mae` recomputed `1.5614` vs claimed `1.5614` -> `True`
- `r` recomputed `0.7012` vs claimed `0.7012` -> `True`
- `cal_slope` recomputed `0.4827` vs claimed `0.4827` -> `True`

### t1_iter34_hybrid_candidate

- Passed: `True`
- Source: `results/lockbox_t1_iter34_hybrid_20260506_141720.json`
- Method: full_metrics(per_subject.y_true, per_subject.y_pred)
- `n` recomputed `93` vs claimed `93` -> `True`
- `ccc` recomputed `0.7366` vs claimed `0.7366` -> `True`
- `mae` recomputed `1.731` vs claimed `1.731` -> `True`
- `r` recomputed `0.7406` vs claimed `0.7406` -> `True`
- `cal_slope` recomputed `0.8215` vs claimed `0.8215` -> `True`

### t3_iter47_validrange_current

- Passed: `True`
- Source: `results/iter47_invalidcode_subject_preds_20260508_194605.csv`
- Summary source: `results/iter47_invalidcode_20260508_194605.json`
- Method: full_metrics(subject_predictions.y_true_validrange, subject_predictions.y_pred)
- `n` recomputed `95` vs claimed `95` -> `True`
- `ccc` recomputed `0.3784` vs claimed `0.3784` -> `True`
- `mae` recomputed `7.528` vs claimed `7.528` -> `True`
- `r` recomputed `0.4141` vs claimed `0.4141` -> `True`
- `cal_slope` recomputed `0.2692` vs claimed `0.2692` -> `True`

### t3_iter47_validrange_no_cv

- Passed: `True`
- Source: `results/iter47_invalidcode_subject_preds_20260508_194605.csv`
- Summary source: `results/iter47_invalidcode_20260508_194605.json`
- Method: full_metrics(subject_predictions.y_true_validrange, subject_predictions.y_pred)
- `n` recomputed `95` vs claimed `95` -> `True`
- `ccc` recomputed `0.3771` vs claimed `0.3771` -> `True`
- `mae` recomputed `7.6798` vs claimed `7.6798` -> `True`
- `r` recomputed `0.4067` vs claimed `0.4067` -> `True`
- `cal_slope` recomputed `0.2745` vs claimed `0.2745` -> `True`

### t3_iter47_complete33_current_sensitivity

- Passed: `True`
- Source: `results/iter47_invalidcode_subject_preds_20260508_194605.csv`
- Summary source: `results/iter47_invalidcode_20260508_194605.json`
- Method: full_metrics(subject_predictions.y_true_validrange, subject_predictions.y_pred)
- `n` recomputed `88` vs claimed `88` -> `True`
- `ccc` recomputed `0.4281` vs claimed `0.4281` -> `True`
- `mae` recomputed `7.3131` vs claimed `7.3131` -> `True`
- `r` recomputed `0.4713` vs claimed `0.4713` -> `True`
- `cal_slope` recomputed `0.3019` vs claimed `0.3019` -> `True`

### dst_audit_stage2_current

- Passed: `True`
- Source: `results/dst_walkway_leakage_audit_subject_rows_20260508_multiseed.csv`
- Summary source: `results/dst_walkway_leakage_audit_20260508_multiseed.json`
- Method: full_metrics(dst_subject_rows.y_true, dst_subject_rows.y_pred)
- `n` recomputed `95` vs claimed `95` -> `True`
- `ccc` recomputed `0.3784` vs claimed `0.3784` -> `True`
- `mae` recomputed `7.528` vs claimed `7.528` -> `True`
- `r` recomputed `0.4141` vs claimed `0.4141` -> `True`
- `cal_slope` recomputed `0.2692` vs claimed `0.2692` -> `True`

### dst_audit_stage2_no_dst

- Passed: `True`
- Source: `results/dst_walkway_leakage_audit_subject_rows_20260508_multiseed.csv`
- Summary source: `results/dst_walkway_leakage_audit_20260508_multiseed.json`
- Method: full_metrics(dst_subject_rows.y_true, dst_subject_rows.y_pred)
- `n` recomputed `95` vs claimed `95` -> `True`
- `ccc` recomputed `0.3766` vs claimed `0.3766` -> `True`
- `mae` recomputed `7.5795` vs claimed `7.5795` -> `True`
- `r` recomputed `0.41` vs claimed `0.41` -> `True`
- `cal_slope` recomputed `0.2708` vs claimed `0.2708` -> `True`

### t3_iter47_loso_drop_allmissing_validrange_stage2_current

- Passed: `True`
- Source: `results/iter47_invalidcode_loso_rows_20260508_195424.csv`
- Summary source: `results/iter47_invalidcode_loso_20260508_195424.json`
- Method: mean per-seed CCC by LOSO direction from rows CSV, then two-way mean
- `NLS_to_WPD_mean_ccc` recomputed `0.1937` vs claimed `0.19369999999999998` -> `True`
- `WPD_to_NLS_mean_ccc` recomputed `0.1059` vs claimed `0.1059` -> `True`
- `two_way_mean_ccc` recomputed `0.1498` vs claimed `0.1498` -> `True`

### t3_iter47_loso_drop_allmissing_validrange_stage2_no_cv

- Passed: `True`
- Source: `results/iter47_invalidcode_loso_rows_20260508_195424.csv`
- Summary source: `results/iter47_invalidcode_loso_20260508_195424.json`
- Method: mean per-seed CCC by LOSO direction from rows CSV, then two-way mean
- `NLS_to_WPD_mean_ccc` recomputed `0.2125` vs claimed `0.21246666666666666` -> `True`
- `WPD_to_NLS_mean_ccc` recomputed `0.1138` vs claimed `0.1138` -> `True`
- `two_way_mean_ccc` recomputed `0.1631` vs claimed `0.16313333333333332` -> `True`


Machine-readable report: `results/headline_metric_recompute_audit_20260508.json`
