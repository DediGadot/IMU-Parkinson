# Transitive Cache Dependency Audit — 2026-05-08

`audit_cache_consumer_guards.py` scans direct cache references. This audit walks local Python imports from current headline/reportable entrypoints and records cache-like artifacts referenced anywhere in the import closure.

Static import reachability is conservative: an imported helper may reference a cache path that the entrypoint never executes. Treat these findings as provenance boundaries, not automatic invalidation.

## Summary

- Entry points audited: `12`
- `entrypoint_direct_diagnostic_cache_reference`: `5`
- `import_closure_contains_diagnostic_cache_reference`: `7`

## Entry Points

### `compose_t1_iter12_honest.py`
- Role: `canonical_t1_current_floor`
- Classification: `entrypoint_direct_diagnostic_cache_reference`
- Import-closure files: `4`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: The entrypoint source directly references missing/partial-manifest cache-like artifacts; reportable reuse needs regeneration/backfill or a stronger diagnostic-only caveat.

### `run_t1_iter34_hybrid_8item_multibase.py`
- Role: `strongest_t1_candidate_caveated`
- Classification: `import_closure_contains_diagnostic_cache_reference`
- Import-closure files: `9`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/lr_asymmetry_features.csv`, `results/rest_state_features.csv`, `results/tug_transition_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.

### `run_t1_iter46_et_robust.py`
- Role: `t1_diagnostic_robustification`
- Classification: `import_closure_contains_diagnostic_cache_reference`
- Import-closure files: `10`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/lr_asymmetry_features.csv`, `results/rest_state_features.csv`, `results/tug_transition_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.

### `run_t3_iter47_invalid_code_fix.py`
- Role: `canonical_t3_validrange_audit_truth`
- Classification: `import_closure_contains_diagnostic_cache_reference`
- Import-closure files: `7`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.

### `run_t3_iter41_target_fix.py`
- Role: `superseded_t3_corrected_target_audit`
- Classification: `entrypoint_direct_diagnostic_cache_reference`
- Import-closure files: `6`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: The entrypoint source directly references missing/partial-manifest cache-like artifacts; reportable reuse needs regeneration/backfill or a stronger diagnostic-only caveat.

### `run_t3_iter5_clinical.py`
- Role: `historical_t3_target_contaminated`
- Classification: `entrypoint_direct_diagnostic_cache_reference`
- Import-closure files: `5`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: The entrypoint source directly references missing/partial-manifest cache-like artifacts; reportable reuse needs regeneration/backfill or a stronger diagnostic-only caveat.

### `run_t3_iter16_site_ipw.py`
- Role: `historical_t3_target_contaminated_loso`
- Classification: `entrypoint_direct_diagnostic_cache_reference`
- Import-closure files: `5`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: The entrypoint source directly references missing/partial-manifest cache-like artifacts; reportable reuse needs regeneration/backfill or a stronger diagnostic-only caveat.

### `compose_t1_iter14_fog.py`
- Role: `guarded_safe_cache_null_screen`
- Classification: `import_closure_contains_diagnostic_cache_reference`
- Import-closure files: `7`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/hc_ssl_subj_embeddings.csv`, `results/item9_event_moment.csv`, `results/lr_asymmetry_features.csv`, `results/moment_subj_embeddings.csv`, `results/peritem_subj_features.csv`, `results/rest_state_features.csv`, `results/tug_transition_features.csv`, ... +1 more
- Clean-manifest artifacts in closure: `results/item11_multiscale.csv`
- Interpretation: Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.

### `compose_t1_iter15_harnet.py`
- Role: `guarded_safe_cache_null_screen`
- Classification: `import_closure_contains_diagnostic_cache_reference`
- Import-closure files: `7`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/hc_ssl_subj_embeddings.csv`, `results/item9_event_moment.csv`, `results/lr_asymmetry_features.csv`, `results/moment_subj_embeddings.csv`, `results/peritem_subj_features.csv`, `results/rest_state_features.csv`, `results/tug_transition_features.csv`, ... +1 more
- Clean-manifest artifacts in closure: `results/harnet_subj_embeddings.csv`, `results/item11_multiscale.csv`
- Interpretation: Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.

### `run_t3_iter23_clinical_ablation.py`
- Role: `guarded_safe_cache_null_screen`
- Classification: `import_closure_contains_diagnostic_cache_reference`
- Import-closure files: `7`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: `results/clinical_extras.csv`
- Interpretation: Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.

### `run_t3_iter24_stage2_forced.py`
- Role: `guarded_safe_cache_null_screen`
- Classification: `import_closure_contains_diagnostic_cache_reference`
- Import-closure files: `7`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: `results/clinical_extras.csv`
- Interpretation: Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.

### `run_t3_iter49_cops.py`
- Role: `external_zero_shot_diagnostic`
- Classification: `entrypoint_direct_diagnostic_cache_reference`
- Import-closure files: `8`
- Diagnostic/partial artifacts in closure: `results/ablation_v3_features.csv`, `results/iter49_cops_features_full.csv`, `results/iter49_cops_features_smoke.csv`, `results/velinc_features.csv`
- Clean-manifest artifacts in closure: none
- Interpretation: The entrypoint source directly references missing/partial-manifest cache-like artifacts; reportable reuse needs regeneration/backfill or a stronger diagnostic-only caveat.

## Verdict

Direct cache-consumer guard status is not enough for provenance claims. Current headline/candidate entrypoints have import closures that can reach diagnostic-only cache paths through historical helper modules; this should be disclosed as conservative static reachability and resolved by cache backfill, regeneration, or narrower helper extraction before claiming cache-manifest-clean future headlines.

Machine-readable report: `results/transitive_cache_dependency_audit_20260508.json`
