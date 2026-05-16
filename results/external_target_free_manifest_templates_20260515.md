# External Target-Free Manifest Templates - 2026-05-15

These are blank, content-free templates for post-schema, pre-scoring feature-manifest preflight. They are not completed manifests, schema probes, protected-data artifacts, preregistrations, model runs, or T1/T3 claim updates.

- Decision: `external_target_free_manifest_templates_ready`
- Goal complete: `False`
- Template directory: `results/external_target_free_manifest_templates_20260515`
- Route count: `6`

## Routes

### PPMI / Verily Study Watch (`ppmi_verily`)

- Template: `results/external_target_free_manifest_templates_20260515/ppmi_verily_target_free_manifest_template.json`
- Grouping keys: `sid, visit_id`
- Reserved target columns: `updrs3`
- Sensor modalities: `wrist_accelerometer`
- Validator: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`

Post-schema workflow sequence:

1. `validate_target_free_manifest` - `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
2. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
3. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

### Personalized Parkinson Project / PD-VME (`ppp_pd_vme`)

- Template: `results/external_target_free_manifest_templates_20260515/ppp_pd_vme_target_free_manifest_template.json`
- Grouping keys: `sid, visit_id`
- Reserved target columns: `updrs3`
- Sensor modalities: `study_watch_accelerometer`
- Validator: `uv run python scripts/validate_target_free_manifest.py --route-id ppp_pd_vme --manifest <completed_target_free_manifest_path_outside_git>`

Post-schema workflow sequence:

1. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id ppp_pd_vme --manifest <completed_target_free_manifest_path_outside_git>`
2. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id ppp_pd_vme --record <completed_formula_sha_record_path_outside_git>`
3. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`

### WATCH-PD (`watchpd`)

- Template: `results/external_target_free_manifest_templates_20260515/watchpd_target_free_manifest_template.json`
- Grouping keys: `sid, visit_id`
- Reserved target columns: `updrs3`
- Sensor modalities: `apdm_imu`
- Validator: `uv run python scripts/validate_target_free_manifest.py --route-id watchpd --manifest <completed_target_free_manifest_path_outside_git>`

Post-schema workflow sequence:

1. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id watchpd --manifest <completed_target_free_manifest_path_outside_git>`
2. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id watchpd --record <completed_formula_sha_record_path_outside_git>`
3. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`

### CNS Portugal / Lobo AX3 gait (`cns_portugal_lobo`)

- Template: `results/external_target_free_manifest_templates_20260515/cns_portugal_lobo_target_free_manifest_template.json`
- Grouping keys: `sid, session_id`
- Reserved target columns: `updrs3`
- Sensor modalities: `ax3_imu`
- Validator: `uv run python scripts/validate_target_free_manifest.py --route-id cns_portugal_lobo --manifest <completed_target_free_manifest_path_outside_git>`

Post-schema workflow sequence:

1. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id cns_portugal_lobo --manifest <completed_target_free_manifest_path_outside_git>`
2. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id cns_portugal_lobo --record <completed_formula_sha_record_path_outside_git>`
3. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`

### Hssayeni / MJFF Levodopa Response (`hssayeni_mjff`)

- Template: `results/external_target_free_manifest_templates_20260515/hssayeni_mjff_target_free_manifest_template.json`
- Grouping keys: `sid, visit_id`
- Reserved target columns: `updrs3`
- Sensor modalities: `geneactiv_wrist_accelerometer`
- Validator: `uv run python scripts/validate_target_free_manifest.py --route-id hssayeni_mjff --manifest <completed_target_free_manifest_path_outside_git>`

Post-schema workflow sequence:

1. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id hssayeni_mjff --manifest <completed_target_free_manifest_path_outside_git>`
2. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id hssayeni_mjff --record <completed_formula_sha_record_path_outside_git>`
3. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`

### ICICLE-PD / ICICLE-GAIT (`icicle_gait`)

- Template: `results/external_target_free_manifest_templates_20260515/icicle_gait_target_free_manifest_template.json`
- Grouping keys: `sid, visit_id`
- Reserved target columns: `updrs3`
- Sensor modalities: `lower_back_ax3`
- Validator: `uv run python scripts/validate_target_free_manifest.py --route-id icicle_gait --manifest <completed_target_free_manifest_path_outside_git>`

Post-schema workflow sequence:

1. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id icicle_gait --manifest <completed_target_free_manifest_path_outside_git>`
2. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id icicle_gait --record <completed_formula_sha_record_path_outside_git>`
3. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`

## PPMI/Verily Support

- Existing route-specific template: `scripts/ppmi_verily_target_free_manifest_template.json`
- Existing route-specific validator: `scripts/validate_ppmi_verily_target_free_manifest.py`
- Existing route-specific validator command: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- Existing route-specific audit: `results/ppmi_verily_target_free_manifest_validator_audit_20260515.json`

## Boundary

Complete these templates only after route approval and schema-probe metadata recording. Keep completed manifests outside git unless a future audit explicitly allows a scrubbed artifact. Do not include protected rows, target values, feature matrices, credentials, local paths, model predictions, or approval records. Completed records must also omit path-like values inside otherwise allowed fields: local scratch paths, completed-file extensions, download/file-path strings, and subject/visit identifier value dumps. Validators fail closed on those markers.
