# Cache Consumer Guard Audit — 2026-05-08

This scans Python scripts for references to cache-like artifacts from `results/cache_manifest_audit_20260508.json` and classifies whether the consumer is guarded, diagnostic/historical, or non-model/cache-production code.

## Summary

- Python scripts with cache references: `89`
- `current_safe_consumer_guarded`: `4`
- `diagnostic_only_consumer_block_reportable_use`: `53`
- `non_model_or_cache_producer_reference`: `32`

## Guarded Current Consumers

- `compose_t1_iter14_fog.py` — `results/item11_multiscale.csv`
- `compose_t1_iter15_harnet.py` — `results/harnet_subj_embeddings.csv`
- `run_t3_iter23_clinical_ablation.py` — `results/clinical_extras.csv`
- `run_t3_iter24_stage2_forced.py` — `results/clinical_extras.csv`

## Diagnostic-Only Model Consumers

- `autoresearch_ccc_eval.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only), `results/velinc_features.csv` (missing_manifest_diagnostic_only), `results/velinc_gated_features.csv` (missing_manifest_diagnostic_only)
- `autoresearch_eval.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `compose_t1_iter17_unused_channels.py` — `results/unused_channels_features.csv` (partial_manifest_diagnostic_only)
- `compose_t1_iter18_indomain_ssl.py` — `results/indomain_ssl_embeddings.csv` (partial_manifest_diagnostic_only)
- `regenerate_fm.py` — `results/fm_embeddings.npz` (missing_manifest_diagnostic_only)
- `run_ablation_v3.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_baselines.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_calibration_ablation.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/fm_embeddings_recording_norm.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_calibration_v2.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_compression_ablation.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_event_features.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_fusion_methods.py` — `results/mahalanobis_hc_subj.csv` (missing_manifest_diagnostic_only)
- `run_inductive_ablation.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_interaction_screen.py` — `results/interaction_features_subj.csv` (missing_manifest_diagnostic_only), `results/v2_self_normalized.csv` (missing_manifest_diagnostic_only)
- `run_item14_deep.py` — `results/peritem_subj_features.csv` (missing_manifest_diagnostic_only)
- `run_joints_v2.py` — `results/joints_v2_subj.csv` (missing_manifest_diagnostic_only), `results/peritem_subj_features.csv` (missing_manifest_diagnostic_only)
- `run_memento_experiments.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_obs_bias_ablation.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_paper_supplements.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_pd_only_experiments.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_per_item_iter17_hypothesis.py` — `results/item_specific_features.csv` (partial_manifest_diagnostic_only)
- `run_per_item_ordinal_v3.py` — `results/nonlinear_dynamics_features.csv` (missing_manifest_diagnostic_only)
- `run_per_item_v2.py` — `results/hc_ssl_subj_embeddings.csv` (missing_manifest_diagnostic_only), `results/item11_multiscale.csv` (manifest_complete_clean_by_construction), `results/item9_event_moment.csv` (missing_manifest_diagnostic_only), `results/moment_subj_embeddings.csv` (missing_manifest_diagnostic_only), `results/peritem_subj_features.csv` (missing_manifest_diagnostic_only), `results/walkway_joint_subj.csv` (missing_manifest_diagnostic_only)
- `run_peritem_insole.py` — `results/insole_subj_features.csv` (missing_manifest_diagnostic_only), `results/peritem_subj_features.csv` (missing_manifest_diagnostic_only)
- `run_phase4_distill.py` — `results/velinc_features.csv` (missing_manifest_diagnostic_only)
- `run_phase5_fm_adapter.py` — `results/fm_embeddings.npz` (missing_manifest_diagnostic_only)
- `run_phase6_stack.py` — `results/velinc_features.csv` (missing_manifest_diagnostic_only)
- `run_reviewer_experiments.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_rocket_ablation.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/coordination_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_self_norm_cross.py` — `results/v2_self_normalized.csv` (missing_manifest_diagnostic_only)
- `run_sensor_span.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_step_function.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_stride_fusion.py` — `results/peritem_subj_features.csv` (missing_manifest_diagnostic_only), `results/stride_locked_subj.csv` (missing_manifest_diagnostic_only)
- `run_stride_fusion_lean.py` — `results/stride_locked_subj.csv` (missing_manifest_diagnostic_only)
- `run_subgroup_experiments.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/fm_embeddings.npz` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t1_ceiling_push_probeD_chainpool.py` — `results/phaselocked_item12_features.csv` (partial_manifest_diagnostic_only), `results/phaselocked_item9_features.csv` (partial_manifest_diagnostic_only)
- `run_t1_ceiling_push_slotC.py` — `results/phaselocked_item12_features.csv` (partial_manifest_diagnostic_only), `results/phaselocked_item9_features.csv` (partial_manifest_diagnostic_only)
- `run_t1_ceiling_push_slotD.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t1_iter4.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/lr_asymmetry_features.csv` (missing_manifest_diagnostic_only), `results/rest_state_features.csv` (missing_manifest_diagnostic_only), `results/tug_transition_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t1_iter7_axial.py` — `results/axial_orientation_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_boost_iter5.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v2_self_normalized.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter1.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter16_site_ipw.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter17_site_centered.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter2.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter21_nested.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/item_specific_features.csv` (partial_manifest_diagnostic_only), `results/peritem_subj_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter3.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only), `results/velinc_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter41_target_fix.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter49_cops.py` — `results/iter49_cops_features_full.csv` (partial_manifest_diagnostic_only), `results/iter49_cops_features_smoke.csv` (partial_manifest_diagnostic_only)
- `run_t3_iter5_clinical.py` — `results/ablation_v3_features.csv` (missing_manifest_diagnostic_only), `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `run_t3_iter6_imu.py` — `results/event_axial_features.csv` (missing_manifest_diagnostic_only), `results/unsigned_asymmetry_features.csv` (missing_manifest_diagnostic_only)
- `run_v3_experiments.py` — `results/v3_features.csv` (missing_manifest_diagnostic_only)
- `train_indomain_ssl.py` — `results/indomain_ssl_embeddings.csv` (partial_manifest_diagnostic_only)

## Verdict

Current known safe-cache consumers use the shared guard. Scripts that still reference missing/partial-manifest caches are diagnostic or historical unless their caches are regenerated/backfilled and the scripts add require_cache_manifest.

Machine-readable report: `results/cache_consumer_guard_audit_20260508.json`
