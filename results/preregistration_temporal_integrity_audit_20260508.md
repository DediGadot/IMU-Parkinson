# Pre-Registration Temporal Integrity Audit - 2026-05-08

Use embedded timestamps or filename timestamps, not pulled-file mtimes, to verify pre-registration precedes result generation; compare formula hashes when both sides record them.

- Passed: `True`
- Checks: `9`
- Warnings: `11`
- Hard failures: `0`

## Checks

### t1_iter12_honest_floor

- Status: `current_t1_canonical_floor`
- Passed: `True`
- Prereg: `results/preregistration_t1_iter12_honest_20260503_053105.json`
- Result: `results/t1_iter12_honest_composite.json`
- Prereg time: `2026-05-03T05:31:05.289387+00:00` via `iso_datetime`
- Result time: `None` via `None`
- Temporal ok: `None`
- Reference ok: `True`
- Formula status: `not_recorded_legacy_or_no_formula`
- Warnings: `['not_recorded_legacy_or_no_formula', 'embedded_or_filename_result_time_missing']`
- Hard failures: `[]`

### t1_iter34_hybrid_candidate

- Status: `current_t1_strongest_candidate`
- Passed: `True`
- Prereg: `results/preregistration_t1_iter34_hybrid_20260506_135932.json`
- Result: `results/lockbox_t1_iter34_hybrid_20260506_141720.json`
- Prereg time: `2026-05-06T13:59:32.531124+00:00` via `iso_datetime`
- Result time: `2026-05-06T14:17:20+00:00` via `filename`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `prereg_only_result_lacks_formula_link`
- Warnings: `['prereg_only_result_lacks_formula_link']`
- Hard failures: `[]`

### t1_iter46_etrobust_diagnostic

- Status: `negative_diagnostic`
- Passed: `True`
- Prereg: `results/preregistration_t1_iter46_etrobust_20260508_160501.json`
- Result: `results/lockbox_t1_iter46_etrobust_20260508_162825.json`
- Prereg time: `2026-05-08T16:05:01+00:00` via `created_at_utc`
- Result time: `2026-05-08T16:28:25.330115+00:00` via `timestamp_utc`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `match`
- Warnings: `['prereg_git_sha_unknown']`
- Hard failures: `[]`

### t3_iter47_validrange_current

- Status: `current_t3_audit_truth`
- Passed: `True`
- Prereg: `results/preregistration_t3_iter47_invalidcode_20260508_194605.json`
- Result: `results/iter47_invalidcode_20260508_194605.json`
- Prereg time: `2026-05-08T16:46:05+00:00` via `created_at_utc`
- Result time: `2026-05-08T16:54:15+00:00` via `created_at_utc`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `match`
- Warnings: `['prereg_git_sha_unknown', 'filesystem_mtime_not_temporal_order_authority']`
- Hard failures: `[]`

### t3_iter47_validrange_loso

- Status: `current_t3_loso_audit_truth`
- Passed: `True`
- Prereg: `results/preregistration_t3_iter47_invalidcode_loso_20260508_195424.json`
- Result: `results/iter47_invalidcode_loso_20260508_195424.json`
- Prereg time: `2026-05-08T16:54:24+00:00` via `created_at_utc`
- Result time: `2026-05-08T16:54:30+00:00` via `created_at_utc`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `match`
- Warnings: `['prereg_git_sha_unknown', 'filesystem_mtime_not_temporal_order_authority']`
- Hard failures: `[]`

### t3_iter39_fogstar_zeroshot

- Status: `external_validity_partial`
- Passed: `True`
- Prereg: `results/preregistration_t3_iter39_fogstar_zeroshot_20260508_143717.json`
- Result: `results/iter39_fogstar_zeroshot_20260508_143717.json`
- Prereg time: `2026-05-08T11:37:17+00:00` via `created_at_utc`
- Result time: `2026-05-08T11:38:50+00:00` via `created_at_utc`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `prereg_only_result_lacks_formula_link`
- Warnings: `['prereg_git_sha_unknown', 'prereg_only_result_lacks_formula_link']`
- Hard failures: `[]`

### t3_iter49_cops_zeroshot

- Status: `external_validity_partial`
- Passed: `True`
- Prereg: `results/preregistration_t3_iter49_cops.json`
- Result: `results/iter49_cops_zeroshot.json`
- Prereg time: `2026-05-08T17:34:52+00:00` via `created_at_utc`
- Result time: `2026-05-08T18:52:26+00:00` via `created_at_utc`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `match`
- Warnings: `[]`
- Hard failures: `[]`

### t3_iter51_tlvmc_defog_zeroshot

- Status: `external_validity_partial`
- Passed: `True`
- Prereg: `results/preregistration_t3_iter51_tlvmc_defog_zeroshot.json`
- Result: `results/iter51_tlvmc_defog_zeroshot.json`
- Prereg time: `2026-05-09T01:04:08+00:00` via `created_at_utc`
- Result time: `2026-05-09T01:33:57+00:00` via `created_at_utc`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `match`
- Warnings: `[]`
- Hard failures: `[]`

### t3_iter5_historical

- Status: `historical_target_contaminated`
- Passed: `True`
- Prereg: `results/preregistration_t3_iter5_20260502_171604.json`
- Result: `results/lockbox_t3_iter5_A3_tier1_20260502_171604.json`
- Prereg time: `2026-05-02T17:16:04.210186+00:00` via `iso_datetime`
- Result time: `2026-05-02T17:16:04+00:00` via `filename`
- Temporal ok: `True`
- Reference ok: `True`
- Formula status: `not_recorded_legacy_or_no_formula`
- Warnings: `['not_recorded_legacy_or_no_formula']`
- Hard failures: `[]`


Machine-readable report: `results/preregistration_temporal_integrity_audit_20260508.json`
