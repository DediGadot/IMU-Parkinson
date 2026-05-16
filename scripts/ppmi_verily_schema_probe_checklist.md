# PPMI / Verily Post-Approval Schema-Probe Checklist

Status: post-approval operator checklist. Do not use before data-owner approval, and do not fill this file with protected PPMI metadata, row dumps, credentials, local approval filenames, or schema-probe output.

Use this checklist only after:

- The PPMI access workflow and Verily Raw Device Data Tier-3 request are approved.
- Non-protected approval metadata has been recorded with `scripts/record_access_approval.py`.
- The current access lifecycle action is `run_read_only_schema_probe`.

## Boundary

The first code action after approval is a read-only schema probe. It may record table names, column names, linkage keys, modality names, counts, missingness summaries, and policy decisions. It must not record protected row data, raw samples, label values, feature matrices, credentials, preregistrations, model runs, remote jobs, downloads, cache extractions, or canonical T1/T3 claim updates.

## Required Schema Sections

The probe record must cover all typed sections expected by `pd_imu.datasets.schema_probe_spec_for_route("ppmi_verily")`:

- `file_inventory`
- `subject_linkage`
- `visit_or_session_linkage`
- `sensor_metadata`
- `target_metadata`
- `missingness_policy`
- `grouping_policy`
- `hard_stops`

## Minimum PPMI / Verily Fields To Inspect

- Accessible table names and download endpoints, without row dumps.
- Subject identifiers present in both Verily sensor metadata and clinical tables.
- Visit identifiers and any session identifiers needed for subject-level grouping.
- Visit dates, clinical assessment dates, wearable collection timestamps, and candidate matching windows.
- Verily Study Watch wrist laterality, accelerometer availability, sampling rate, units, axis frame, and timestamp format.
- Whether the approved schema exposes a WearGait-compatible 13-node anatomical IMU graph; if not, the X4 V2+V3-GSP branch remains excluded from PPMI Track A/B formulas.
- Total recording duration and missingness per subject or subject-visit, reported only as counts or aggregate summaries.
- MDS-UPDRS Part III item columns, total columns, valid value ranges, and invalid-code handling.
- Hoehn & Yahr availability.
- Demographics and cohort metadata needed for non-protected cohort summaries.
- Medication state and dose-timing fields, if available.
- Any hard stop that prevents subject-level matching, target construction, or wrist-feature extraction.

## Recorder Command Shape

After the read-only inspection, record only scrubbed metadata. Use `scripts/ppmi_verily_schema_probe_report_template.md` as a local scratch template if helpful. Replace the angle-bracket values locally; do not commit filled template copies, local approval paths, or protected table details. In short: do not commit local approval paths.

```bash
uv run python scripts/record_schema_probe_report.py \
  --route-id ppmi_verily \
  --sections-present "file_inventory,subject_linkage,visit_or_session_linkage,sensor_metadata,target_metadata,missingness_policy,grouping_policy,hard_stops" \
  --grouping-keys-found "<comma_separated_grouping_keys_including_sid_and_visit_id>" \
  --target-columns-found "<comma_separated_target_columns_including_updrs3>" \
  --sensor-modalities-found "<comma_separated_sensor_modalities_including_wrist_accelerometer>" \
  --valid-subject-count "<matched_pd_subject_or_subject_visit_count>" \
  --ppmi-x4-multinode-anatomical-sensors-present "<true_or_false>" \
  --ppmi-x4-v3-gsp-formula-eligible "<true_or_false>" \
  --ppmi-x4-external-label-selection-allowed "false"
```

Expected minimum recorder values for a valid PPMI / Verily probe:

- grouping keys include `sid` and `visit_id`;
- target columns include `updrs3`;
- sensor modalities include `wrist_accelerometer`;
- valid subject count is at least `20`;
- `ppmi_x4_multinode_anatomical_sensors_present` is explicitly `true` or `false`;
- `ppmi_x4_v3_gsp_formula_eligible` is `true` only if the schema proves a comparable multi-node anatomical layout before formula freeze;
- `ppmi_x4_external_label_selection_allowed` is `false`;
- `protected_row_dump_included`, `preregistration_written`, and `model_run_started` remain false.

## After Recording

- Run `uv run python audit_access_lifecycle_state_handoff.py`.
- Review schema-probe gates only. A clean schema-probe artifact can unlock preregistration review, but it is not itself a model result.
- Before zero-shot scoring, validate the target-free feature manifest with
  `scripts/validate_ppmi_verily_target_free_manifest.py` using
  `scripts/ppmi_verily_target_free_manifest_template.json` as local scratch
  guidance.
- After the target-free manifest passes and before extraction or scoring,
  freeze the content-free zero-shot formula using the PPMI route row in
  `results/external_formula_sha_templates_20260515.md`, then validate the
  local formula-SHA record with
  `scripts/validate_external_formula_sha_record.py --route-id ppmi_verily`.
- After scoring, validate only aggregate external zero-shot result metadata
  with `scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily`
  before reporting a transportability or within-route sanity row.
- Do not write a preregistration or experiment script until the schema-probe artifact passes the typed `SchemaProbeArtifactEvidence` checks and the route-specific stop conditions are resolved.
