# Runtime Cache Dependency Audit — 2026-05-08

This installs a Python `sys.addaudithook('open')` hook, then runs lightweight data-load/recompute paths for current headline/candidate scripts. It distinguishes executed cache reads from static import-only reachability for these paths.

Runtime tracing is diagnostic only. It does not prove unexercised branches are safe and does not replace static import cleanup or concrete cache manifests.

## Summary

- Diagnostic/partial cache-like artifacts opened: `results/ablation_v3_features.csv`

## Targets

### `t1_iter12_recompute`
- Status: `ok`
- Result: `{'n': 94, 'n_sids': 94, 'ccc': 0.655, 'mae': 1.5614}`
- Opened cache-like artifacts: `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only, events=1)

### `t1_iter34_loader`
- Status: `ok`
- Result: `{'n': 92, 'x_cols': 1751, 'stage1_cols': 9, 'stage1_names': ['hy_0', 'hy_1', 'hy_2', 'hy_3', 'hy_4', 'hy_5', 'cv_yrs', 'cv_sex', 'cv_dbs'], 'available_aux': [15, 18], 't1_mean': 4.0326, 'item_keys': [9, 10, 11, 12, 13, 14, 15, 18]}`
- Opened cache-like artifacts: `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only, events=2)

### `t3_iter47_filter_minimal`
- Status: `ok`
- Result: `{'n': 95, 'x_cols': 1752, 'excluded_sids': ['NLS188', 'WPD013', 'NLS151'], 'target_changed_sids': ['NLS036']}`
- Opened cache-like artifacts: `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only, events=1)

## Verdict

The narrowed T1 iter12 recompute executes only the V2 SID-order cache among cache-like artifacts, eliminating the previous executed per-item/MOMENT/HC-SSL/walkway cache reads. T1 iter34's current fail-closed loader now produces N=92 after the auxiliary valid-range fix, so it is not a reproduction path for the historical N=93 lockbox; it still executes ablation_v3_features.csv. T3 iter47 also executes ablation_v3_features.csv. Static velinc reachability did not execute in these lightweight paths. Runtime tracing is diagnostic and does not make missing manifests headline-safe.

Machine-readable report: `results/runtime_cache_dependency_audit_20260508.json`
