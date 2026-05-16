# External Zero-Shot Result Record Templates - 2026-05-15

These are blank, content-free templates for aggregate external zero-shot result reporting. They are not completed result records, schema probes, feature manifests, preregistrations, model runs, or T1/T3 claim updates.

- Decision: `external_zeroshot_result_templates_ready`
- Goal complete: `False`
- Template directory: `results/external_zeroshot_result_templates_20260515`
- Route count: `6`

## Routes

### PPMI / Verily Study Watch (`ppmi_verily`)

- Template: `results/external_zeroshot_result_templates_20260515/ppmi_verily_zeroshot_result_record_template.json`
- Target columns: `updrs3`
- Sensor modalities: `wrist_accelerometer`
- Validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-score reporting workflow sequence:

1. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling` - `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence` - `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state` - `uv run python verify_current_goal_state.py`

Route-specific result contract:

- Blueprint record ID: `ppmi_verily_zeroshot_blueprint_20260515`
- Blueprint SHA256: `4540fbc00a3bb92b6bedca34e954bb0e8ae00cbee30ee6f9651c56229591e13f`
- Formula validator gate: `ppmi_route_specific_formula_contract`
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
- Fixed T3 branch model: `sklearn.ensemble.GradientBoostingRegressor`
- Fixed T3 branch selector/K: `univariate_corr_top_K` / `250`

### Personalized Parkinson Project / PD-VME (`ppp_pd_vme`)

- Template: `results/external_zeroshot_result_templates_20260515/ppp_pd_vme_zeroshot_result_record_template.json`
- Target columns: `updrs3`
- Sensor modalities: `study_watch_accelerometer`
- Validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-score reporting workflow sequence:

1. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling` - `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence` - `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state` - `uv run python verify_current_goal_state.py`

### WATCH-PD (`watchpd`)

- Template: `results/external_zeroshot_result_templates_20260515/watchpd_zeroshot_result_record_template.json`
- Target columns: `updrs3`
- Sensor modalities: `apdm_imu`
- Validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-score reporting workflow sequence:

1. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling` - `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence` - `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state` - `uv run python verify_current_goal_state.py`

### CNS Portugal / Lobo AX3 gait (`cns_portugal_lobo`)

- Template: `results/external_zeroshot_result_templates_20260515/cns_portugal_lobo_zeroshot_result_record_template.json`
- Target columns: `updrs3`
- Sensor modalities: `ax3_imu`
- Validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-score reporting workflow sequence:

1. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling` - `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence` - `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state` - `uv run python verify_current_goal_state.py`

### Hssayeni / MJFF Levodopa Response (`hssayeni_mjff`)

- Template: `results/external_zeroshot_result_templates_20260515/hssayeni_mjff_zeroshot_result_record_template.json`
- Target columns: `updrs3`
- Sensor modalities: `geneactiv_wrist_accelerometer`
- Validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-score reporting workflow sequence:

1. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling` - `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence` - `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state` - `uv run python verify_current_goal_state.py`

### ICICLE-PD / ICICLE-GAIT (`icicle_gait`)

- Template: `results/external_zeroshot_result_templates_20260515/icicle_gait_zeroshot_result_record_template.json`
- Target columns: `updrs3`
- Sensor modalities: `lower_back_ax3`
- Validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`

Post-score reporting workflow sequence:

1. `validate_zeroshot_result_record` - `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling` - `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence` - `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state` - `uv run python verify_current_goal_state.py`

## Boundary

Complete these templates only after route approval, schema metadata, target-free manifest preflight, formula-SHA preflight, and external zero-shot scoring. Keep completed aggregate result records outside git unless a future audit explicitly allows a scrubbed artifact. Do not include protected rows, target values, row predictions, feature matrices, credentials, local paths, or internal canonical update claims. Completed records must also omit path-like values inside otherwise allowed fields: local scratch paths, completed-file extensions, download/file-path strings, and subject/visit identifier value dumps. Validators fail closed on those markers.
