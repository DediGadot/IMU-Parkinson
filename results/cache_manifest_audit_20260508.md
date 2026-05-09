# Cache Manifest Audit — 2026-05-08

Policy: per `AGENTS.md`, reusable cache artifacts feeding inductive headlines need sidecar manifests with script, command, git SHA, data hash, label-use, fold scope, cohort-statistics scope, normalization scope, leakage status, and leakage rationale. Missing or partial manifests are diagnostic-only.

## Summary

- Cache-like artifacts audited: `45`
- `manifest_complete_clean_by_construction`: `4`
- `missing_manifest_diagnostic_only`: `33`
- `partial_manifest_diagnostic_only`: `8`

## Headline-Safe Artifacts

- `results/clinical_extras.csv` — manifest `results/clinical_extras.csv.manifest.json`
- `results/harnet_subj_embeddings.csv` — manifest `results/harnet_subj_embeddings.csv.manifest.json`
- `results/item11_multiscale.csv` — manifest `results/item11_multiscale.csv.manifest.json`
- `results/item11_multiscale_recordings.csv` — manifest `results/item11_multiscale_recordings.csv.manifest.json`

## Diagnostic-Only Artifacts Requiring Backfill

- `results/ablation_v3_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/axial_orientation_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/coordination_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/event_axial_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/fm_embeddings.npz` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/fm_embeddings_all_13.npz` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/fm_embeddings_lower_back_1.npz` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/fm_embeddings_minimal_5.npz` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/fm_embeddings_recording_norm.npz` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/fm_embeddings_wrists_2.npz` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/fm_embeddings_wrists_back_3.npz` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/hc_ssl_subj_embeddings.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/indomain_ssl_embeddings.csv` — `partial_manifest_diagnostic_only` (missing/null fields: script, git_sha, command, created_at_utc, fold_scope, cohort_statistics_used, normalization_scope, leakage_rationale)
- `results/insole_recording_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/insole_subj_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/interaction_features_subj.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/item9_event_moment.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/item_specific_features.csv` — `partial_manifest_diagnostic_only` (missing/null fields: script, command, created_at_utc, fold_scope, cohort_statistics_used, normalization_scope, leakage_rationale, git_sha)
- `results/iter49_cops_features_full.csv` — `partial_manifest_diagnostic_only` (missing/null fields: git_sha, command, data_sha256, fold_scope, cohort_statistics_used, normalization_scope, leakage_rationale)
- `results/iter49_cops_features_smoke.csv` — `partial_manifest_diagnostic_only` (missing/null fields: git_sha, command, data_sha256, fold_scope, cohort_statistics_used, normalization_scope, leakage_rationale)
- `results/iter51_tlvmc_defog_features.csv` — `partial_manifest_diagnostic_only` (missing/null fields: git_sha, command, data_sha256, fold_scope, cohort_statistics_used, normalization_scope, leakage_rationale)
- `results/joints_v2_strides.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/joints_v2_subj.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/lr_asymmetry_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/mahalanobis_hc_subj.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/moment_subj_embeddings.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/nonlinear_dynamics_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/peritem_rec_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/peritem_subj_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/phaselocked_item12_features.csv` — `partial_manifest_diagnostic_only` (missing/null fields: script, created_at_utc, cohort_statistics_used, normalization_scope, leakage_rationale, git_sha)
- `results/phaselocked_item9_features.csv` — `partial_manifest_diagnostic_only` (missing/null fields: script, created_at_utc, cohort_statistics_used, normalization_scope, leakage_rationale, git_sha)
- `results/rest_state_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/stride_locked_subj.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/tug_transition_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/unsigned_asymmetry_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/unused_channels_features.csv` — `partial_manifest_diagnostic_only` (missing/null fields: script, command, created_at_utc, fold_scope, cohort_statistics_used, normalization_scope, leakage_rationale, git_sha)
- `results/v2_self_normalized.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/v3_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/velinc_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/velinc_gated_features.csv` — `missing_manifest_diagnostic_only` (missing manifest)
- `results/walkway_joint_subj.csv` — `missing_manifest_diagnostic_only` (missing manifest)

## Backfill Discipline

No manifests were synthesized in this audit. Backfill should be done only when the producing script, command, git SHA, data hash, and leakage rationale can be reconstructed from real evidence. Otherwise the artifact remains diagnostic-only.

Machine-readable report: `results/cache_manifest_audit_20260508.json`
