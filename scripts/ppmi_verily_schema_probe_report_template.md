# PPMI / Verily Schema-Probe Report Template

Status: post-approval scratch template. Do not use before data-owner approval. Do not commit a filled copy. Store any filled local notes only under ignored local access/probe working space.

Use after:

- PPMI / Verily access has been approved.
- Non-protected approval metadata has been recorded with `scripts/record_access_approval.py`.
- `audit_access_lifecycle_state_handoff.py` reports `run_read_only_schema_probe`.
- `scripts/ppmi_verily_schema_probe_checklist.md` has been reviewed.

## Safe Metadata To Collect

Record only aggregate or schema-level facts:

- sections present from `file_inventory`, `subject_linkage`, `visit_or_session_linkage`, `sensor_metadata`, `target_metadata`, `missingness_policy`, `grouping_policy`, `hard_stops`;
- grouping keys found, including `sid` and `visit_id`;
- target columns found, including `updrs3`;
- sensor modalities found, including `wrist_accelerometer`;
- valid matched PD subject or subject-visit count as an integer count;
- explicit X4 V3-GSP eligibility fields: whether comparable multi-node anatomical sensors exist, whether the branch is formula-eligible before formula SHA freeze, and that external label selection remains disallowed;
- hard-stop reasons as non-row-level notes.

Do not record protected row data, raw samples, target or label values, feature matrices, credentials, access tokens, approval filenames, local protected paths, preregistrations, model runs, downloads, cache extractions, or canonical T1/T3 claim updates.

## Fill Locally After Approval

Keep this as local scratch content only. Replace placeholders locally; do not commit the filled values.

```text
sections_present=file_inventory,subject_linkage,visit_or_session_linkage,sensor_metadata,target_metadata,missingness_policy,grouping_policy,hard_stops
grouping_keys_found=sid,visit_id,<additional_non_protected_grouping_keys_if_needed>
target_columns_found=updrs3,<additional_non_protected_target_column_names_if_needed>
sensor_modalities_found=wrist_accelerometer,<additional_non_protected_sensor_modalities_if_needed>
valid_subject_count=<integer_count_at_least_20>
ppmi_x4_multinode_anatomical_sensors_present=false
ppmi_x4_v3_gsp_formula_eligible=false
ppmi_x4_external_label_selection_allowed=false
hard_stops=<non_row_level_stop_reasons_or_none>
```

## Recorder Command

Validate the local scratch report before recording metadata:

```bash
uv run python scripts/validate_ppmi_verily_schema_probe_report.py \
  --report "<local_completed_schema_probe_report_path>"
```

Run only after approval metadata exists. The recorder writes to `.schema_probes/` by default.

```bash
uv run python scripts/record_schema_probe_report.py \
  --route-id ppmi_verily \
  --sections-present "file_inventory,subject_linkage,visit_or_session_linkage,sensor_metadata,target_metadata,missingness_policy,grouping_policy,hard_stops" \
  --grouping-keys-found "sid,visit_id,<additional_non_protected_grouping_keys_if_needed>" \
  --target-columns-found "updrs3,<additional_non_protected_target_column_names_if_needed>" \
  --sensor-modalities-found "wrist_accelerometer,<additional_non_protected_sensor_modalities_if_needed>" \
  --valid-subject-count "<integer_count_at_least_20>" \
  --ppmi-x4-multinode-anatomical-sensors-present "<true_or_false>" \
  --ppmi-x4-v3-gsp-formula-eligible "<true_or_false>" \
  --ppmi-x4-external-label-selection-allowed "false"
```

## Post-Record Checks

- Run `uv run python audit_access_lifecycle_state_handoff.py`.
- Run `uv run python audit_schema_probe_artifact_gate.py` before any preregistration discussion.
- After schema metadata is recorded and before zero-shot scoring, prepare a
  target-free feature manifest from
  `scripts/ppmi_verily_target_free_manifest_template.json` and validate it with
  `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest "<local_completed_target_free_manifest_path>"`.
- Do not download data, extract caches, write a preregistration, start a remote job, run a model, or update claims until later gates explicitly allow that step.
