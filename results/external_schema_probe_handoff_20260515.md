# External Schema-Probe Handoff - 2026-05-15

This is a content-free post-approval handoff. It is not an access approval, completed schema probe, target-free feature manifest, preregistration, model run, protected-data artifact, or T1/T3 claim update.

- Decision: `external_schema_probe_handoff_ready`
- Goal complete: `False`
- Route count: `6`
- Schema contract: `pd_imu.datasets.external_schema_probe_specs`

## Routes

### 1. PPMI / Verily Study Watch (`ppmi_verily`)

- Protected access required: `True`
- Required sections: `file_inventory, subject_linkage, visit_or_session_linkage, sensor_metadata, target_metadata, missingness_policy, grouping_policy, hard_stops`
- Required grouping keys: `sid, visit_id`
- Required target columns: `updrs3`
- Required sensor modalities: `wrist_accelerometer`
- Minimum valid subjects: `20`

Post-approval workflow sequence:

1. `validate_schema_probe_report` - `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
2. `record_schema_probe_metadata` - `uv run python scripts/record_schema_probe_report.py --route-id ppmi_verily --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
3. `validate_target_free_manifest` - `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
4. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
5. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-approval commands:

- Validate local schema report: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- Record scrubbed schema metadata after validation: `uv run python scripts/record_schema_probe_report.py --route-id ppmi_verily --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
- Validate target-free manifest: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- Validate formula-SHA record before extraction or scoring: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- Validate aggregate external result record after scoring: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

Still blocked until approval and schema/manifest gates pass:

- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

PPMI/Verily-specific support:

- Checklist: `scripts/ppmi_verily_schema_probe_checklist.md`
- Report template: `scripts/ppmi_verily_schema_probe_report_template.md`
- Checklist audit: `results/ppmi_verily_schema_probe_checklist_audit_20260515.json`
- Report-template audit: `results/ppmi_verily_schema_probe_report_template_audit_20260515.json`
- Route-specific validator: `scripts/validate_ppmi_verily_schema_probe_report.py`
- Route-specific validator command: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest template: `scripts/ppmi_verily_target_free_manifest_template.json`
- Target-free manifest validator: `scripts/validate_ppmi_verily_target_free_manifest.py`
- Target-free manifest validator command: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`

### 2. Personalized Parkinson Project / PD-VME (`ppp_pd_vme`)

- Protected access required: `True`
- Required sections: `file_inventory, subject_linkage, visit_or_session_linkage, sensor_metadata, target_metadata, missingness_policy, grouping_policy, hard_stops`
- Required grouping keys: `sid, visit_id`
- Required target columns: `updrs3`
- Required sensor modalities: `study_watch_accelerometer`
- Minimum valid subjects: `20`

Post-approval workflow sequence:

1. `validate_schema_probe_report` - `uv run python scripts/validate_schema_probe_report.py --route-id ppp_pd_vme --report <completed_schema_probe_report_path_outside_git>`
2. `record_schema_probe_metadata` - `uv run python scripts/record_schema_probe_report.py --route-id ppp_pd_vme --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
3. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id ppp_pd_vme --manifest <completed_target_free_manifest_path_outside_git>`
4. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id ppp_pd_vme --record <completed_formula_sha_record_path_outside_git>`
5. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-approval commands:

- Validate local schema report: `uv run python scripts/validate_schema_probe_report.py --route-id ppp_pd_vme --report <completed_schema_probe_report_path_outside_git>`
- Record scrubbed schema metadata after validation: `uv run python scripts/record_schema_probe_report.py --route-id ppp_pd_vme --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
- Validate target-free manifest: `uv run python scripts/validate_target_free_manifest.py --route-id ppp_pd_vme --manifest <completed_target_free_manifest_path_outside_git>`
- Validate formula-SHA record before extraction or scoring: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppp_pd_vme --record <completed_formula_sha_record_path_outside_git>`
- Validate aggregate external result record after scoring: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`

Still blocked until approval and schema/manifest gates pass:

- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

### 3. WATCH-PD (`watchpd`)

- Protected access required: `True`
- Required sections: `file_inventory, subject_linkage, visit_or_session_linkage, sensor_metadata, target_metadata, missingness_policy, grouping_policy, hard_stops`
- Required grouping keys: `sid, visit_id`
- Required target columns: `updrs3`
- Required sensor modalities: `apdm_imu`
- Minimum valid subjects: `20`

Post-approval workflow sequence:

1. `validate_schema_probe_report` - `uv run python scripts/validate_schema_probe_report.py --route-id watchpd --report <completed_schema_probe_report_path_outside_git>`
2. `record_schema_probe_metadata` - `uv run python scripts/record_schema_probe_report.py --route-id watchpd --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
3. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id watchpd --manifest <completed_target_free_manifest_path_outside_git>`
4. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id watchpd --record <completed_formula_sha_record_path_outside_git>`
5. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-approval commands:

- Validate local schema report: `uv run python scripts/validate_schema_probe_report.py --route-id watchpd --report <completed_schema_probe_report_path_outside_git>`
- Record scrubbed schema metadata after validation: `uv run python scripts/record_schema_probe_report.py --route-id watchpd --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
- Validate target-free manifest: `uv run python scripts/validate_target_free_manifest.py --route-id watchpd --manifest <completed_target_free_manifest_path_outside_git>`
- Validate formula-SHA record before extraction or scoring: `uv run python scripts/validate_external_formula_sha_record.py --route-id watchpd --record <completed_formula_sha_record_path_outside_git>`
- Validate aggregate external result record after scoring: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`

Still blocked until approval and schema/manifest gates pass:

- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

### 4. CNS Portugal / Lobo AX3 gait (`cns_portugal_lobo`)

- Protected access required: `True`
- Required sections: `file_inventory, subject_linkage, visit_or_session_linkage, sensor_metadata, target_metadata, missingness_policy, grouping_policy, hard_stops`
- Required grouping keys: `sid, session_id`
- Required target columns: `updrs3`
- Required sensor modalities: `ax3_imu`
- Minimum valid subjects: `20`

Post-approval workflow sequence:

1. `validate_schema_probe_report` - `uv run python scripts/validate_schema_probe_report.py --route-id cns_portugal_lobo --report <completed_schema_probe_report_path_outside_git>`
2. `record_schema_probe_metadata` - `uv run python scripts/record_schema_probe_report.py --route-id cns_portugal_lobo --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
3. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id cns_portugal_lobo --manifest <completed_target_free_manifest_path_outside_git>`
4. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id cns_portugal_lobo --record <completed_formula_sha_record_path_outside_git>`
5. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-approval commands:

- Validate local schema report: `uv run python scripts/validate_schema_probe_report.py --route-id cns_portugal_lobo --report <completed_schema_probe_report_path_outside_git>`
- Record scrubbed schema metadata after validation: `uv run python scripts/record_schema_probe_report.py --route-id cns_portugal_lobo --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
- Validate target-free manifest: `uv run python scripts/validate_target_free_manifest.py --route-id cns_portugal_lobo --manifest <completed_target_free_manifest_path_outside_git>`
- Validate formula-SHA record before extraction or scoring: `uv run python scripts/validate_external_formula_sha_record.py --route-id cns_portugal_lobo --record <completed_formula_sha_record_path_outside_git>`
- Validate aggregate external result record after scoring: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`

Still blocked until approval and schema/manifest gates pass:

- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

### 5. Hssayeni / MJFF Levodopa Response (`hssayeni_mjff`)

- Protected access required: `True`
- Required sections: `file_inventory, subject_linkage, visit_or_session_linkage, sensor_metadata, target_metadata, missingness_policy, grouping_policy, hard_stops`
- Required grouping keys: `sid, visit_id`
- Required target columns: `updrs3`
- Required sensor modalities: `geneactiv_wrist_accelerometer`
- Minimum valid subjects: `20`

Post-approval workflow sequence:

1. `validate_schema_probe_report` - `uv run python scripts/validate_schema_probe_report.py --route-id hssayeni_mjff --report <completed_schema_probe_report_path_outside_git>`
2. `record_schema_probe_metadata` - `uv run python scripts/record_schema_probe_report.py --route-id hssayeni_mjff --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
3. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id hssayeni_mjff --manifest <completed_target_free_manifest_path_outside_git>`
4. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id hssayeni_mjff --record <completed_formula_sha_record_path_outside_git>`
5. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-approval commands:

- Validate local schema report: `uv run python scripts/validate_schema_probe_report.py --route-id hssayeni_mjff --report <completed_schema_probe_report_path_outside_git>`
- Record scrubbed schema metadata after validation: `uv run python scripts/record_schema_probe_report.py --route-id hssayeni_mjff --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
- Validate target-free manifest: `uv run python scripts/validate_target_free_manifest.py --route-id hssayeni_mjff --manifest <completed_target_free_manifest_path_outside_git>`
- Validate formula-SHA record before extraction or scoring: `uv run python scripts/validate_external_formula_sha_record.py --route-id hssayeni_mjff --record <completed_formula_sha_record_path_outside_git>`
- Validate aggregate external result record after scoring: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`

Still blocked until approval and schema/manifest gates pass:

- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

### 6. ICICLE-PD / ICICLE-GAIT (`icicle_gait`)

- Protected access required: `True`
- Required sections: `file_inventory, subject_linkage, visit_or_session_linkage, sensor_metadata, target_metadata, missingness_policy, grouping_policy, hard_stops`
- Required grouping keys: `sid, visit_id`
- Required target columns: `updrs3`
- Required sensor modalities: `lower_back_ax3`
- Minimum valid subjects: `20`

Post-approval workflow sequence:

1. `validate_schema_probe_report` - `uv run python scripts/validate_schema_probe_report.py --route-id icicle_gait --report <completed_schema_probe_report_path_outside_git>`
2. `record_schema_probe_metadata` - `uv run python scripts/record_schema_probe_report.py --route-id icicle_gait --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
3. `validate_target_free_manifest` - `uv run python scripts/validate_target_free_manifest.py --route-id icicle_gait --manifest <completed_target_free_manifest_path_outside_git>`
4. `validate_formula_sha_record` - `uv run python scripts/validate_external_formula_sha_record.py --route-id icicle_gait --record <completed_formula_sha_record_path_outside_git>`
5. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-approval commands:

- Validate local schema report: `uv run python scripts/validate_schema_probe_report.py --route-id icicle_gait --report <completed_schema_probe_report_path_outside_git>`
- Record scrubbed schema metadata after validation: `uv run python scripts/record_schema_probe_report.py --route-id icicle_gait --sections-present <csv> --grouping-keys-found <csv> --target-columns-found <csv> --sensor-modalities-found <csv> --valid-subject-count <n>`
- Validate target-free manifest: `uv run python scripts/validate_target_free_manifest.py --route-id icicle_gait --manifest <completed_target_free_manifest_path_outside_git>`
- Validate formula-SHA record before extraction or scoring: `uv run python scripts/validate_external_formula_sha_record.py --route-id icicle_gait --record <completed_formula_sha_record_path_outside_git>`
- Validate aggregate external result record after scoring: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`

Still blocked until approval and schema/manifest gates pass:

- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

## Boundary

Do not add completed packets, approval evidence, credentials, local data paths, protected rows, target values, schema-probe outputs, completed manifests, formula records, row-level predictions, downloads, caches, preregistrations, model runs, or canonical claim updates to this repo from this handoff.
