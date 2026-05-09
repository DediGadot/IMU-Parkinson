# OOF Artifact Integrity Audit - 2026-05-08

Verify selected current/historical lockbox .oof.npy files are byte-level prediction companions to their JSON per_subject.y_pred arrays.

- Passed: `True`
- Checks: `4`

## Checks

### t1_iter12_honest_floor

- Status: `current_t1_canonical_floor`
- Passed: `True`
- JSON: `results/t1_iter12_honest_composite.json`
- OOF: `results/t1_iter12_honest_composite.oof.npy`
- JSON N: `94`
- OOF shape: `[94]`
- Max abs diff: `0.0`

### t1_iter34_hybrid_candidate

- Status: `current_t1_strongest_candidate`
- Passed: `True`
- JSON: `results/lockbox_t1_iter34_hybrid_20260506_141720.json`
- OOF: `results/lockbox_t1_iter34_hybrid_20260506_141720.oof.npy`
- JSON N: `93`
- OOF shape: `[93]`
- Max abs diff: `0.0`

### t1_iter46_etrobust_diagnostic

- Status: `negative_diagnostic`
- Passed: `True`
- JSON: `results/lockbox_t1_iter46_etrobust_20260508_162825.json`
- OOF: `results/lockbox_t1_iter46_etrobust_20260508_162825.oof.npy`
- JSON N: `93`
- OOF shape: `[93]`
- Max abs diff: `0.0`

### t3_iter5_historical_target_contaminated

- Status: `historical_target_contaminated`
- Passed: `True`
- JSON: `results/lockbox_t3_iter5_A3_tier1_20260502_171604.json`
- OOF: `results/lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy`
- JSON N: `98`
- OOF shape: `[98]`
- Max abs diff: `0.0`


Machine-readable report: `results/oof_artifact_integrity_audit_20260508.json`
