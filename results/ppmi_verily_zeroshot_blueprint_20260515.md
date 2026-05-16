# PPMI / Verily Zero-Shot Blueprint - 2026-05-15

This is a content-free pre-access design blueprint. It is not a model result, access approval, schema probe, or preregistration.

- Route: `ppmi_verily`
- Status: `pre_access_design_blueprint_not_preregistration`
- Blueprint SHA256: `4540fbc00a3bb92b6bedca34e954bb0e8ae00cbee30ee6f9651c56229591e13f`
- Goal complete: `False`

## Analysis Order

- `read_only_schema_probe`
- `schema_probe_report_preflight`
- `schema_probe_metadata_record`
- `target_free_manifest_before_scoring`
- `formula_sha256_after_manifest_before_extraction_or_scoring`
- `zero_shot_external_validation`
- `aggregate_result_record_preflight_after_external_scoring`
- `ppmi_only_sanity_if_zero_shot_fails_or_for_context`
- `fresh_augmentation_preregistration_only_after_zero_shot`

## Tracks

- Track A: `weargait_trained_wrist_topofractal_zeroshot` - external-validity evidence only; no internal WearGait-PD headline update
- Track B: `weargait_trained_clinical_plus_wrist_zeroshot` - external comparator only; not a new internal T3 canonical
- Track C: `ppmi_only_subject_grouped_sanity` - PPMI-internal sanity only; not WearGait deployment performance and not an internal headline update
- Track D: `augmentation_screen_after_zero_shot_only` - cannot update canonical WearGait-PD T1/T3 without promotion gate and null gates

## Source Prompt Trace

- Source audit: `results/proresults_prompt_to_artifact_audit_20260515.json`
- Prompt path: `/tmp/pro-results.txt`
- Prompt SHA256: `a07d0311eebb35108ba3c364d9892f76cb8a7ec78bafe2597494bb79f020b135`
- Prompt rank: `4` - PPMI/Verily topology-first external transport after access approval
- Source goal complete: `False`

## No-Search Rules

- no scaffold before approved schema probe
- no cache extraction before schema-probe metadata recorded
- no PPMI labels for zero-shot feature selection
- no PH/MFDFA column search on PPMI
- no TopoFractal component-count search on PPMI
- no K-search around K=250
- no cross-branch adaptive stacking before zero-shot results
- no X4 13-sensor V2+V3-GSP transfer on wrist-only PPMI unless approved schema proves comparable multi-node sensors before formula freeze
- no endpoint switching after PPMI outcomes
- no canonical WearGait-PD T1/T3 update from external-only metrics

## Claim Boundary

External-only metrics cannot update the internal WearGait-PD T1/T3 canonical claims. Any augmentation attempt needs a fresh formula_sha256 preregistration after zero-shot evidence.

Machine-readable report: `results/ppmi_verily_zeroshot_blueprint_20260515.json`
