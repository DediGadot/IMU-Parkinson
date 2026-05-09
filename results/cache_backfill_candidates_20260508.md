# Cache Backfill Candidate Audit - 2026-05-08

This report classifies partial cache manifests by recoverable provenance evidence. It does not modify manifests and does not make any artifact headline-safe.

## Summary

- `do_not_backfill_for_internal_headline`: `4`
- `manual_backfill_candidate`: `2`
- `needs_commit_before_backfill`: `2`

## Artifacts

- `results/indomain_ssl_embeddings.csv` - `do_not_backfill_for_internal_headline`; script `train_indomain_ssl.py`; git script match `d281a0e`; missing=['script', 'git_sha', 'command', 'created_at_utc', 'fold_scope', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=[]. Manifest describes labels used or non-clean leakage status; this cache is external/diagnostic even if metadata is completed.
- `results/item_specific_features.csv` - `manual_backfill_candidate`; script `cache_item_specific_features.py`; git script match `4d0cc13`; missing=['script', 'command', 'created_at_utc', 'fold_scope', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=['git_sha']. Manifest script_sha256 matches committed script code. Backfill may be defensible if command/runtime evidence is also accepted.
- `results/iter49_cops_features_full.csv` - `do_not_backfill_for_internal_headline`; script `run_t3_iter49_cops.py`; git script match `none`; missing=['git_sha', 'command', 'data_sha256', 'fold_scope', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=[]. Manifest describes labels used or non-clean leakage status; this cache is external/diagnostic even if metadata is completed.
- `results/iter49_cops_features_smoke.csv` - `do_not_backfill_for_internal_headline`; script `run_t3_iter49_cops.py`; git script match `none`; missing=['git_sha', 'command', 'data_sha256', 'fold_scope', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=[]. Manifest describes labels used or non-clean leakage status; this cache is external/diagnostic even if metadata is completed.
- `results/iter51_tlvmc_defog_features.csv` - `do_not_backfill_for_internal_headline`; script `run_t3_iter51_tlvmc_defog.py`; git script match `none`; missing=['git_sha', 'command', 'data_sha256', 'fold_scope', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=[]. Manifest describes labels used or non-clean leakage status; this cache is external/diagnostic even if metadata is completed.
- `results/phaselocked_item12_features.csv` - `needs_commit_before_backfill`; script `cache_phaselocked_item12.py`; git script match `none`; missing=['script', 'created_at_utc', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=['git_sha']. Manifest script_sha256 matches the working-tree script, but no committed git SHA contains that exact file.
- `results/phaselocked_item9_features.csv` - `needs_commit_before_backfill`; script `cache_phaselocked_item9.py`; git script match `none`; missing=['script', 'created_at_utc', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=['git_sha']. Manifest script_sha256 matches the working-tree script, but no committed git SHA contains that exact file.
- `results/unused_channels_features.csv` - `manual_backfill_candidate`; script `cache_unused_channels.py`; git script match `d281a0e`; missing=['script', 'command', 'created_at_utc', 'fold_scope', 'cohort_statistics_used', 'normalization_scope', 'leakage_rationale']; nullish=['git_sha']. Manifest script_sha256 matches committed script code. Backfill may be defensible if command/runtime evidence is also accepted.

Machine-readable report: `results/cache_backfill_candidates_20260508.json`
