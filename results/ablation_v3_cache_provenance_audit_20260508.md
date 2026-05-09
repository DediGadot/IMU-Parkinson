# Ablation V3 Cache Provenance Audit - 2026-05-08

This is a non-mutating evidence report for `results/ablation_v3_features.csv`. It does not create or backfill a manifest sidecar.

## Summary

- Cache SHA256: `b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4`
- Shape: `178` rows x `1877` columns; `178` unique SIDs.
- Manifest validator status: `missing_manifest_diagnostic_only`.
- Current V2 filters select `1752` columns, including `31` `dst_*` and `6` `cv_*` columns.
- Runtime cache audit targets opening this cache: `3`.
- Decision: `do_not_synthesize_clean_manifest`.

## Proven Evidence

- Git tracks the cache: `True`; cache history: `94842a4 first commit`.
- Current producer script hashes: `run_ablation_v3.py`=`5a349664fab587e803ca5c2d26feffc5bc7318790d80acb7678ed5a981d9fd4d`, `run_ablation_v2.py`=`6b87041edf4ef569bda90574ad2dd4aa63baef1cae635344c0f3b66db3535704`
- Log SHA256: `3a8beb404e1d58b73bff57268ebd4d44d31da47a2fdf032e3a20e6b4b02b1ed1`.

Relevant log lines:

```text
Loaded split: 142 dev + 36 test subjects
V3 extraction: 1417 recordings, 11 cores...
  1417 done in 160s
  Walkway loaded: 135 subjects, 31 metrics
  Distilled 31 walkway cols for 178 subjects
Cached: 178 subjects x 1875 features -> /root/pd-imu/results/ablation_v3_features.csv

======================================================================
PHASE 0: FOUNDATION — 10-split stability + K sweep
======================================================================
  split1_lgb: MAE=8.63 r=0.627 PD-MAE=8.60 (K=150)
  split1_stk: MAE=8.53 r=0.610 PD-MAE=8.41 (K=150, 2 base)
```

## Prior Audits Linked

- `audit_runtime_cache_dependencies.py` found this is the only diagnostic/partial cache opened by lightweight iter12/iter34/iter47 paths.
  - `t1_iter12_recompute`: status `ok`, result `{'n': 94, 'n_sids': 94, 'ccc': 0.655, 'mae': 1.5614}`
  - `t1_iter34_loader`: status `ok`, result `{'n': 92, 'x_cols': 1751, 'stage1_cols': 9, 'stage1_names': ['hy_0', 'hy_1', 'hy_2', 'hy_3', 'hy_4', 'hy_5', 'cv_yrs', 'cv_sex', 'cv_dbs'], 'available_aux': [15, 18], 't1_mean': 4.0326, 'item_keys': [9, 10, 11, 12, 13, 14, 15, 18]}`
  - `t3_iter47_filter_minimal`: status `ok`, result `{'n': 95, 'x_cols': 1752, 'excluded_sids': ['NLS188', 'WPD013', 'NLS151'], 'target_changed_sids': ['NLS036']}`
- `audit_dst_walkway_leakage.py` measured the selected `dst_*` caveat on corrected T3.
  - current Stage 2 CCC `0.3784`, no-`dst_*` CCC `0.3766`.
  - bootstrap delta no-`dst` minus current `-0.00042923548816437636`.

## Decision

- No ablation_v3_features.csv.manifest.json sidecar exists.
- The available ablation_v3.log records split sizes, extraction, distillation, and cache path, but not an exact command, creation timestamp, raw-data hash, producing git SHA, or manifest schema fields.
- The cache contains compatibility target/clinical columns and the current V2 feature filter selects six cv_* columns; this is disclosed but not a clean label-free feature-cache sidecar.
- The cache also contains 31 selected dst_* pressure-walkway-distiller columns from a once-trained historical dev-split model; the no-dst sensitivity is non-material, but the distiller is not LOOCV fold-local.

Recommended use: Historical/current reports may cite pipelines that read this cache only with explicit provenance caveats and, for T3, the no-dst sensitivity. Future cache-manifest-clean headlines need a real regeneration/backfill or narrower reproduction artifacts.

Machine-readable report: `results/ablation_v3_cache_provenance_audit_20260508.json`
