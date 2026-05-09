# Cache Backfill Decisions - 2026-05-08

This report records why remaining manual backfill candidates were left partial.
It does not modify manifests.

## Summary

- `leave_partial_no_patch`: `2`

## Decisions

- `results/item_specific_features.csv` - `leave_partial_no_patch`; script `cache_item_specific_features.py`; git script match `4d0cc13`; blocking fields=['cohort_statistics_used', 'command', 'created_at_utc', 'fold_scope', 'git_sha', 'leakage_rationale', 'normalization_scope', 'script']. Committed script-hash evidence is insufficient to promote this older-schema manifest because exact command/runtime schema fields are missing. Do not infer them from narrative docs.
- `results/unused_channels_features.csv` - `leave_partial_no_patch`; script `cache_unused_channels.py`; git script match `d281a0e`; blocking fields=['cohort_statistics_used', 'command', 'created_at_utc', 'fold_scope', 'git_sha', 'leakage_rationale', 'normalization_scope', 'script']. Committed script-hash evidence is insufficient to promote this older-schema manifest because exact command/runtime schema fields are missing. Do not infer them from narrative docs.

Machine-readable report: `results/cache_backfill_decisions_20260508.json`
