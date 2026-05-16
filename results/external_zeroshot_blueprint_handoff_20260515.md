# External Zero-Shot Blueprint Handoff - 2026-05-15

This is a content-free zero-shot analysis-order handoff for queued gated external routes. It is not an access approval, schema probe, completed feature manifest, preregistration, model run, protected-data artifact, or T1/T3 claim update.

- Decision: `external_zeroshot_blueprint_handoff_ready`
- Goal complete: `False`
- Route count: `6`

## Shared Analysis Order

- `approval_metadata_record`
- `read_only_schema_probe`
- `schema_probe_report_preflight`
- `schema_probe_metadata_record`
- `target_free_manifest_preflight`
- `formula_sha256_after_manifest_before_extraction_or_scoring`
- `zero_shot_external_validation`
- `aggregate_result_record_preflight_after_external_scoring`
- `route_only_grouped_sanity_if_zero_shot_fails_or_for_context`
- `fresh_augmentation_preregistration_only_after_zero_shot`

## Routes

### PPMI / Verily Study Watch (`ppmi_verily`)

- Grouping keys: `sid, visit_id`
- Target columns: `updrs3`
- Sensor modalities: `wrist_accelerometer`
- Minimum linked subjects: `20`
- Schema handoff: `results/external_schema_probe_handoff_20260515.md`
- Schema validator: `scripts/validate_ppmi_verily_schema_probe_report.py`
- Schema validator command: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest template: `results/external_target_free_manifest_templates_20260515/ppmi_verily_target_free_manifest_template.json`
- Target-free manifest validator: `scripts/validate_ppmi_verily_target_free_manifest.py`
- Target-free manifest validator command: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- Formula-SHA template: `results/external_formula_sha_templates_20260515/ppmi_verily_formula_sha_record_template.json`
- Formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Formula-SHA validator command: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- Aggregate result template: `results/external_zeroshot_result_templates_20260515/ppmi_verily_zeroshot_result_record_template.json`
- Aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`
- Aggregate result validator command: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

Tracks:

- Track A: `weargait_trained_sensor_zeroshot` - external-validity or transportability evidence only; no internal WearGait-PD headline update
- Track B: `weargait_trained_clinical_plus_sensor_zeroshot` - external comparator only; not a new internal canonical
- Track C: `ppmi_verily_only_grouped_sanity` - route-internal sanity only; not WearGait deployment performance and not an internal headline update
- Track D: `augmentation_screen_after_zero_shot_only` - cannot update canonical WearGait-PD T1/T3 without promotion gate, null gates, and a full-cohort internal result

Route-specific locked blueprint:

- Blueprint: `results/ppmi_verily_zeroshot_blueprint_20260515.json`
- Blueprint audit: `results/ppmi_verily_zeroshot_blueprint_audit_20260515.json`
- Must use for exact track definitions: `True`
- Required locked formula components:
  - small fixed TopoFractal PH/MFDFA branch
  - canonical comparator
  - separate fixed K=250 sklearn-GB branch for T3 only
  - no omnibus feature expansion
  - no cross-branch adaptive stacking before zero-shot results
- Route-specific track names:
  - Track A: `weargait_trained_wrist_topofractal_zeroshot`
  - Track B: `weargait_trained_clinical_plus_wrist_zeroshot`
  - Track C: `ppmi_only_subject_grouped_sanity`
  - Track D: `augmentation_screen_after_zero_shot_only`

Locked no-search rules:

- no scaffold before approved schema probe
- no cache extraction before schema-probe metadata recorded
- no external labels for zero-shot feature selection
- no PH/MFDFA column search on the external route
- no TopoFractal component-count search on the external route
- no K-search on the external route
- no adaptive stacking before zero-shot results
- no endpoint switching after external outcomes
- no canonical WearGait-PD T1/T3 update from external-only metrics

### Personalized Parkinson Project / PD-VME (`ppp_pd_vme`)

- Grouping keys: `sid, visit_id`
- Target columns: `updrs3`
- Sensor modalities: `study_watch_accelerometer`
- Minimum linked subjects: `20`
- Schema handoff: `results/external_schema_probe_handoff_20260515.md`
- Schema validator: `scripts/validate_schema_probe_report.py`
- Schema validator command: `uv run python scripts/validate_schema_probe_report.py --route-id ppp_pd_vme --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest template: `results/external_target_free_manifest_templates_20260515/ppp_pd_vme_target_free_manifest_template.json`
- Target-free manifest validator: `scripts/validate_target_free_manifest.py`
- Target-free manifest validator command: `uv run python scripts/validate_target_free_manifest.py --route-id ppp_pd_vme --manifest <completed_target_free_manifest_path_outside_git>`
- Formula-SHA template: `results/external_formula_sha_templates_20260515/ppp_pd_vme_formula_sha_record_template.json`
- Formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Formula-SHA validator command: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppp_pd_vme --record <completed_formula_sha_record_path_outside_git>`
- Aggregate result template: `results/external_zeroshot_result_templates_20260515/ppp_pd_vme_zeroshot_result_record_template.json`
- Aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`
- Aggregate result validator command: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`

Tracks:

- Track A: `weargait_trained_sensor_zeroshot` - external-validity or transportability evidence only; no internal WearGait-PD headline update
- Track B: `weargait_trained_clinical_plus_sensor_zeroshot` - external comparator only; not a new internal canonical
- Track C: `ppp_pd_vme_only_grouped_sanity` - route-internal sanity only; not WearGait deployment performance and not an internal headline update
- Track D: `augmentation_screen_after_zero_shot_only` - cannot update canonical WearGait-PD T1/T3 without promotion gate, null gates, and a full-cohort internal result

Locked no-search rules:

- no scaffold before approved schema probe
- no cache extraction before schema-probe metadata recorded
- no external labels for zero-shot feature selection
- no PH/MFDFA column search on the external route
- no TopoFractal component-count search on the external route
- no K-search on the external route
- no adaptive stacking before zero-shot results
- no endpoint switching after external outcomes
- no canonical WearGait-PD T1/T3 update from external-only metrics

### WATCH-PD (`watchpd`)

- Grouping keys: `sid, visit_id`
- Target columns: `updrs3`
- Sensor modalities: `apdm_imu`
- Minimum linked subjects: `20`
- Schema handoff: `results/external_schema_probe_handoff_20260515.md`
- Schema validator: `scripts/validate_schema_probe_report.py`
- Schema validator command: `uv run python scripts/validate_schema_probe_report.py --route-id watchpd --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest template: `results/external_target_free_manifest_templates_20260515/watchpd_target_free_manifest_template.json`
- Target-free manifest validator: `scripts/validate_target_free_manifest.py`
- Target-free manifest validator command: `uv run python scripts/validate_target_free_manifest.py --route-id watchpd --manifest <completed_target_free_manifest_path_outside_git>`
- Formula-SHA template: `results/external_formula_sha_templates_20260515/watchpd_formula_sha_record_template.json`
- Formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Formula-SHA validator command: `uv run python scripts/validate_external_formula_sha_record.py --route-id watchpd --record <completed_formula_sha_record_path_outside_git>`
- Aggregate result template: `results/external_zeroshot_result_templates_20260515/watchpd_zeroshot_result_record_template.json`
- Aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`
- Aggregate result validator command: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`

Tracks:

- Track A: `weargait_trained_sensor_zeroshot` - external-validity or transportability evidence only; no internal WearGait-PD headline update
- Track B: `weargait_trained_clinical_plus_sensor_zeroshot` - external comparator only; not a new internal canonical
- Track C: `watchpd_only_grouped_sanity` - route-internal sanity only; not WearGait deployment performance and not an internal headline update
- Track D: `augmentation_screen_after_zero_shot_only` - cannot update canonical WearGait-PD T1/T3 without promotion gate, null gates, and a full-cohort internal result

Locked no-search rules:

- no scaffold before approved schema probe
- no cache extraction before schema-probe metadata recorded
- no external labels for zero-shot feature selection
- no PH/MFDFA column search on the external route
- no TopoFractal component-count search on the external route
- no K-search on the external route
- no adaptive stacking before zero-shot results
- no endpoint switching after external outcomes
- no canonical WearGait-PD T1/T3 update from external-only metrics

### CNS Portugal / Lobo AX3 gait (`cns_portugal_lobo`)

- Grouping keys: `sid, session_id`
- Target columns: `updrs3`
- Sensor modalities: `ax3_imu`
- Minimum linked subjects: `20`
- Schema handoff: `results/external_schema_probe_handoff_20260515.md`
- Schema validator: `scripts/validate_schema_probe_report.py`
- Schema validator command: `uv run python scripts/validate_schema_probe_report.py --route-id cns_portugal_lobo --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest template: `results/external_target_free_manifest_templates_20260515/cns_portugal_lobo_target_free_manifest_template.json`
- Target-free manifest validator: `scripts/validate_target_free_manifest.py`
- Target-free manifest validator command: `uv run python scripts/validate_target_free_manifest.py --route-id cns_portugal_lobo --manifest <completed_target_free_manifest_path_outside_git>`
- Formula-SHA template: `results/external_formula_sha_templates_20260515/cns_portugal_lobo_formula_sha_record_template.json`
- Formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Formula-SHA validator command: `uv run python scripts/validate_external_formula_sha_record.py --route-id cns_portugal_lobo --record <completed_formula_sha_record_path_outside_git>`
- Aggregate result template: `results/external_zeroshot_result_templates_20260515/cns_portugal_lobo_zeroshot_result_record_template.json`
- Aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`
- Aggregate result validator command: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`

Tracks:

- Track A: `weargait_trained_sensor_zeroshot` - external-validity or transportability evidence only; no internal WearGait-PD headline update
- Track B: `weargait_trained_clinical_plus_sensor_zeroshot` - external comparator only; not a new internal canonical
- Track C: `cns_portugal_lobo_only_grouped_sanity` - route-internal sanity only; not WearGait deployment performance and not an internal headline update
- Track D: `augmentation_screen_after_zero_shot_only` - cannot update canonical WearGait-PD T1/T3 without promotion gate, null gates, and a full-cohort internal result

Locked no-search rules:

- no scaffold before approved schema probe
- no cache extraction before schema-probe metadata recorded
- no external labels for zero-shot feature selection
- no PH/MFDFA column search on the external route
- no TopoFractal component-count search on the external route
- no K-search on the external route
- no adaptive stacking before zero-shot results
- no endpoint switching after external outcomes
- no canonical WearGait-PD T1/T3 update from external-only metrics

### Hssayeni / MJFF Levodopa Response (`hssayeni_mjff`)

- Grouping keys: `sid, visit_id`
- Target columns: `updrs3`
- Sensor modalities: `geneactiv_wrist_accelerometer`
- Minimum linked subjects: `20`
- Schema handoff: `results/external_schema_probe_handoff_20260515.md`
- Schema validator: `scripts/validate_schema_probe_report.py`
- Schema validator command: `uv run python scripts/validate_schema_probe_report.py --route-id hssayeni_mjff --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest template: `results/external_target_free_manifest_templates_20260515/hssayeni_mjff_target_free_manifest_template.json`
- Target-free manifest validator: `scripts/validate_target_free_manifest.py`
- Target-free manifest validator command: `uv run python scripts/validate_target_free_manifest.py --route-id hssayeni_mjff --manifest <completed_target_free_manifest_path_outside_git>`
- Formula-SHA template: `results/external_formula_sha_templates_20260515/hssayeni_mjff_formula_sha_record_template.json`
- Formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Formula-SHA validator command: `uv run python scripts/validate_external_formula_sha_record.py --route-id hssayeni_mjff --record <completed_formula_sha_record_path_outside_git>`
- Aggregate result template: `results/external_zeroshot_result_templates_20260515/hssayeni_mjff_zeroshot_result_record_template.json`
- Aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`
- Aggregate result validator command: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`

Tracks:

- Track A: `weargait_trained_sensor_zeroshot` - external-validity or transportability evidence only; no internal WearGait-PD headline update
- Track B: `weargait_trained_clinical_plus_sensor_zeroshot` - external comparator only; not a new internal canonical
- Track C: `hssayeni_mjff_only_grouped_sanity` - route-internal sanity only; not WearGait deployment performance and not an internal headline update
- Track D: `augmentation_screen_after_zero_shot_only` - cannot update canonical WearGait-PD T1/T3 without promotion gate, null gates, and a full-cohort internal result

Locked no-search rules:

- no scaffold before approved schema probe
- no cache extraction before schema-probe metadata recorded
- no external labels for zero-shot feature selection
- no PH/MFDFA column search on the external route
- no TopoFractal component-count search on the external route
- no K-search on the external route
- no adaptive stacking before zero-shot results
- no endpoint switching after external outcomes
- no canonical WearGait-PD T1/T3 update from external-only metrics

### ICICLE-PD / ICICLE-GAIT (`icicle_gait`)

- Grouping keys: `sid, visit_id`
- Target columns: `updrs3`
- Sensor modalities: `lower_back_ax3`
- Minimum linked subjects: `20`
- Schema handoff: `results/external_schema_probe_handoff_20260515.md`
- Schema validator: `scripts/validate_schema_probe_report.py`
- Schema validator command: `uv run python scripts/validate_schema_probe_report.py --route-id icicle_gait --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest template: `results/external_target_free_manifest_templates_20260515/icicle_gait_target_free_manifest_template.json`
- Target-free manifest validator: `scripts/validate_target_free_manifest.py`
- Target-free manifest validator command: `uv run python scripts/validate_target_free_manifest.py --route-id icicle_gait --manifest <completed_target_free_manifest_path_outside_git>`
- Formula-SHA template: `results/external_formula_sha_templates_20260515/icicle_gait_formula_sha_record_template.json`
- Formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Formula-SHA validator command: `uv run python scripts/validate_external_formula_sha_record.py --route-id icicle_gait --record <completed_formula_sha_record_path_outside_git>`
- Aggregate result template: `results/external_zeroshot_result_templates_20260515/icicle_gait_zeroshot_result_record_template.json`
- Aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`
- Aggregate result validator command: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`

Tracks:

- Track A: `weargait_trained_sensor_zeroshot` - external-validity or transportability evidence only; no internal WearGait-PD headline update
- Track B: `weargait_trained_clinical_plus_sensor_zeroshot` - external comparator only; not a new internal canonical
- Track C: `icicle_gait_only_grouped_sanity` - route-internal sanity only; not WearGait deployment performance and not an internal headline update
- Track D: `augmentation_screen_after_zero_shot_only` - cannot update canonical WearGait-PD T1/T3 without promotion gate, null gates, and a full-cohort internal result

Locked no-search rules:

- no scaffold before approved schema probe
- no cache extraction before schema-probe metadata recorded
- no external labels for zero-shot feature selection
- no PH/MFDFA column search on the external route
- no TopoFractal component-count search on the external route
- no K-search on the external route
- no adaptive stacking before zero-shot results
- no endpoint switching after external outcomes
- no canonical WearGait-PD T1/T3 update from external-only metrics

## PPMI/Verily Support

- Route-specific blueprint: `results/ppmi_verily_zeroshot_blueprint_20260515.json`
- Route-specific blueprint audit: `results/ppmi_verily_zeroshot_blueprint_audit_20260515.json`

## Boundary

Do not add completed packets, approval evidence, credentials, local data paths, protected rows, target values, schema-probe outputs, completed manifests, formula records, row-level predictions, downloads, caches, preregistrations, model runs, or canonical claim updates to this repo from this handoff.
