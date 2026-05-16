# Pro-Results Prompt-to-Artifact Audit - 2026-05-15

Objective: Break the T1 + T3 CCC glass ceiling by following /tmp/pro-results.txt.
Prompt source: `/tmp/pro-results.txt` (sha256 `a07d0311eebb35108ba3c364d9892f76cb8a7ec78bafe2597494bb79f020b135`, 492 lines)

## Success Criteria

- T1: Reportable full-cohort T1 CCC must beat iter34 hygiene-corrected 0.7170 under current gates.
- T3: Reportable full-cohort T3 CCC must beat iter47 corrected-target 0.3784 under current gates.
- Secondary: Retained-coverage/deployable improvements do not complete the full-cohort objective.

## Numbered Checklist

| Rank | Status | Requirement | Evidence | Key result |
|---:|---|---|---|---|
| 1 | `covered_failed` | Sum-aware multi-task Bayesian residual composer over PH/MFDFA item heads | `results/screen_t1_S1_sumaware_bayesian_20260515T105106Z.json` | ccc=0.7062; delta=-0.0108; verdict=SCREEN_FAIL_NO_LOOCV |
| 2 | `covered_failed` | Target-free TopoFractal-8 PH/MFDFA compression | `results/screen_t1_topofractal8_sumaware_20260515T103452Z.json` | ccc=0.7163; delta=-0.0006999999999999229; frac=0.0195; verdict=SCREEN_FAIL_NO_LOOCV |
| 3 | `covered_failed_class_sparsity` | Ordinal bounded item-distribution composer | `results/screen_t1_S3_ordinal_composer_20260515T104904Z.json` | ccc=0.7052; delta=-0.0118; verdict=SCREEN_FAIL_CLASS_N_NO_LOOCV |
| 4 | `blocked_external_access_required` | PPMI/Verily topology-first external transport after access approval | `scripts/ppmi_verily_tier3_request_packet.md` | compute_ready=0 |
| 5 | `covered_failed_or_sub_mcid` | Fixed PH/MFDFA micro-batch correction for items 10/13/14 | `results/lockbox_t1_S5_microbatch_item13only_audit_20260515T104934Z.json` | item13_delta=0.007542; joint_delta=0.008788 |
| 6 | `covered_descriptiveness_null` | Stability-constrained sparse biomechanical score discovery | `results/lockbox_t1_S6_stability_sparse_score_20260515T104957Z.json` | verdict=DESCRIPTIVENESS_RECORDED |
| 7 | `covered_failed_deployable_secondary` | Y-free item-level selective prediction from topology disagreement | `results/lockbox_t1_S7_multiitem_topology_abstention_20260515T104937Z.json` | cov70=0.705; cov50=0.7512 |
| 8 | `covered_failed` | TUG phase-specific PH/MFDFA microfeatures | `results/screen_t1_rank8_tug_phase_ph_mfdfa_20260515T111648Z.json` | ccc=0.718994; delta=0.001956; frac=0.681; verdict=SCREEN_FAIL_NO_LOOCV |
| 9 | `covered_failed` | Fold-local sparse prototype regression over TopoFractal state | `results/screen_t1_S9_topofractal_prototype_20260515T105343Z.json` | ccc=0.7077; delta=-0.0093; frac=0.005; verdict=SCREEN_FAIL_NO_LOOCV |
| 10 | `blocked_for_external_replication_internal_checks_negative` | Canonical Stage-1 + K=250 sklearn Gradient Boosting tail model | `results/lockbox_t3_S10_k250_hgb_fresh_replication_20260515T111626Z.json` | frac=0.4274; verdict=FAIL; fresh_ccc=0.3711; delta=-0.007300000000000029 |
| 11 | `covered_failed` | Latent observable-T3 decomposition with non-gait nuisance prior | `results/screen_t3_S11_observable_decomposition_20260515T110455Z.json` | ccc=0.3282; delta=-0.0556; frac=0.03; verdict=SCREEN_FAIL_NO_LOOCV_NO_LOSO |
| 12 | `covered_failed_deployable_secondary` | T3 unobservability-risk abstention from decomposition disagreement | `results/screen_t3_S12_unobservability_abstention_20260515T112653Z.json` | verdict=SCREEN_FAIL_NO_DEPLOYABLE_UPDATE; cov70=0.4104; cov50=0.3896 |

## Completion-Audit Coverage

| Check | Passed | Evidence |
|---|---:|---|
| `prompt_file_loaded` | `True` | /tmp/pro-results.txt |
| `all_12_numbered_recommendations_present_in_prompt` | `True` | /tmp/pro-results.txt |
| `prompt_gate_terms_are_explicit` | `True` | /tmp/pro-results.txt |
| `rank1_to_rank3_internal_t1_screens_failed_below_promotion_gate` | `True` | 1, 2, 3 |
| `rank4_ppmi_verily_external_route_is_access_blocked_but_packeted` | `True` | scripts/ppmi_verily_tier3_request_packet.md |
| `queued_external_access_packets_have_generic_content_free_preflight` | `True` | content_boundary, external_queue_status, external_queue_status_audit, external_queue_status_decision, generic_packet_validator, generic_packet_validator_audit |
| `queued_external_access_requests_have_generic_fill_checklist` | `True` | external_queue_status, external_queue_status_audit, external_queue_status_decision, generic_fill_checklist, generic_fill_checklist_audit, generic_fill_checklist_decision |
| `queued_external_access_requests_have_stable_submission_index` | `True` | external_queue_status, external_queue_status_audit, external_queue_status_decision, external_submission_index, external_submission_index_audit, external_submission_index_decision |
| `queued_external_access_requests_have_all_route_lifecycle_status` | `True` | external_lifecycle_status, external_lifecycle_status_audit, external_lifecycle_status_decision, external_lifecycle_status_workflow_by_route, external_queue_status, external_queue_status_audit |
| `queued_external_schema_probe_handoff_is_generic_and_content_free` | `True` | external_queue_status, external_queue_status_audit, external_queue_status_decision, external_schema_probe_handoff, external_schema_probe_handoff_audit, external_schema_probe_handoff_decision |
| `queued_external_schema_probe_reports_have_generic_content_free_preflight` | `True` | external_queue_status, external_queue_status_audit, external_queue_status_decision, generic_schema_probe_report_validator, generic_schema_probe_report_validator_audit, generic_schema_probe_report_validator_decision |
| `queued_external_target_free_manifests_have_generic_content_free_preflight` | `True` | external_queue_status, external_queue_status_audit, external_queue_status_decision, generic_target_free_manifest_validator, generic_target_free_manifest_validator_audit, generic_target_free_manifest_validator_decision |
| `queued_external_target_free_manifest_templates_are_generic_and_content_free` | `True` | external_queue_status, external_queue_status_audit, external_queue_status_decision, external_target_free_manifest_templates, external_target_free_manifest_templates_audit, external_target_free_manifest_templates_decision |
| `queued_external_zeroshot_blueprint_handoff_is_generic_and_content_free` | `True` | external_queue_status, external_queue_status_audit, external_queue_status_decision, external_zeroshot_blueprint_handoff, external_zeroshot_blueprint_handoff_audit, external_zeroshot_blueprint_handoff_decision |
| `queued_external_formula_sha_templates_are_generic_and_content_free` | `True` | external_formula_sha_ppmi_bad_contract_hard_failures, external_formula_sha_ppmi_contract_negative_failed, external_formula_sha_ppmi_contract_present, external_formula_sha_record_validator, external_formula_sha_templates, external_formula_sha_templates_audit |
| `queued_external_zeroshot_result_templates_are_generic_and_content_free` | `True` | external_queue_ppmi_result_x4_policy, external_queue_status, external_queue_status_audit, external_queue_status_decision, external_zeroshot_result_ppmi_bad_contract_hard_failures, external_zeroshot_result_ppmi_contract_negative_failed |
| `current_verified_next_action_is_ppmi_submission_not_compute` | `True` | access_lifecycle_current_action, current_state, next_action, pre_submission_handoff |
| `current_submission_handoff_is_content_free_and_actionable` | `True` | results/ppmi_verily_current_submission_handoff_20260515.json |
| `rank5_microbatch_and_joint_followup_are_sub_mcid` | `True` | best_followup_joint_item12_13, item13_microbatch |
| `rank6_stability_descriptor_has_no_stable_columns` | `True` | results/lockbox_t1_S6_stability_sparse_score_20260515T104957Z.json |
| `rank7_t1_selective_prediction_failed_existing_slotD_secondary_references` | `True` | results/lockbox_t1_S7_multiitem_topology_abstention_20260515T104937Z.json |
| `rank8_tug_phase_cache_manifest_exists_and_screen_fails_gate` | `True` | results/screen_t1_rank8_tug_phase_ph_mfdfa_20260515T111648Z.json |
| `rank9_sparse_prototype_screen_failed_below_promotion_gate` | `True` | results/screen_t1_S9_topofractal_prototype_20260515T105343Z.json |
| `rank10_k250_internal_replication_negative_and_external_branch_blocked` | `True` | delta_vs_iter47, external_access, external_blueprint, frac_positive, fresh_internal_ccc, fresh_internal_replication |
| `rank11_t3_observable_decomposition_failed_full_cohort_gate` | `True` | results/screen_t3_S11_observable_decomposition_20260515T110455Z.json |
| `rank12_t3_unobservability_abstention_failed_slotF_secondary_references` | `True` | results/screen_t3_S12_unobservability_abstention_20260515T112653Z.json |
| `s13_s15_t3_transfer_extension_failed_and_not_promoted` | `True` | exists, fivefold_promotion, fivefold_screen_JOINT_mean, fivefold_screen_JOINT_std, joint_delta, joint_frac_positive |
| `slotF_t3_deployable_replication_boundary_lift_not_promoted` | `True` | bootstrap_seed, claim, coverage_rows, created_at_utc, decision, gates |
| `no_numbered_item_is_missing_or_unverified` | `True` | 1, 10, 11, 12, 2, 3 |

## Explicit Prompt Directives

| Directive | Passed | Evidence |
|---|---:|---|
| `objective_success_criteria_are_concrete_and_unmet` | `True` | prompt_mentions_current_t1_ceiling, prompt_mentions_current_t3_ceiling, t1_ceiling, t3_ceiling |
| `best_immediate_rank1_algorithm_executed_as_screen` | `True` | results/screen_t1_S1_sumaware_bayesian_20260515T105106Z.json |
| `rank1_algorithm_steps_1_to_4_are_implemented` | `True` | s1_script, topofractal_result, topofractal_script |
| `rank1_screen_gate_prevented_loocv` | `True` | results/screen_t1_S1_sumaware_bayesian_20260515T105106Z.json |
| `rank1_null_and_no_headline_boundary_respected` | `True` | results/screen_t1_S1_sumaware_bayesian_20260515T105106Z.json |
| `topofractal_screen_nulls_and_canary_respected` | `True` | results/screen_t1_topofractal8_sumaware_20260515T103452Z.json |
| `best_one_month_ppmi_algorithm_is_packeted_access_first` | `True` | scripts/ppmi_verily_setup.md |
| `k250_external_branch_fixed_no_search` | `True` | delta_vs_iter47, external_access, external_blueprint, frac_positive, fresh_internal_ccc, fresh_internal_replication |
| `user_side_submission_sequence_is_available_without_protected_content` | `True` | results/ppmi_verily_submission_bundle_20260515.json |
| `no_remaining_local_weargait_model_action` | `True` | results/remaining_blocker_action_audit_20260509.json |

## Rejected-Temptation Guard

| Rule | Passed | Evidence |
|---|---:|---|
| `no_y_test_dependent_abstention` | `True` | CLAUDE.md::oracle metric; CLAUDE.md::y-free retention rule |
| `no_post_hoc_cohort_surgery` | `True` | findings.md::post-hoc cohort surgery; AGENTS.md::do not run a post-hoc N=92 lockbox |
| `no_broad_952_feature_omnibuses` | `True` | findings.md::Omnibus 952-feature stack; findings.md::catastrophic overfit |
| `no_v2_pdcor_selection_model_rule` | `True` | findings.md::V2 pdCor-selection on T1; progress.md::pdCor is a DESCRIPTIVENESS metric |
| `no_global_target_derived_selectors_or_rankers` | `True` | AGENTS.md::Never pre-compute XGBRanker ranks; CLAUDE.md::No global imputers |
| `no_unlabeled_encoder_reruns_without_new_data` | `True` | AGENTS.md::Frozen healthy-population-pretrained encoders are dead; CLAUDE.md::frozen MOMENT/HC-SSL/HARNet |
| `no_healthy_control_anchors_as_deployable_signal` | `True` | AGENTS.md::Healthy controls are diagnostic-only; CLAUDE.md::HC anchors HURT |
| `no_old_retracted_number_claims` | `True` | AGENTS.md::Retracted numbers; CLAUDE.md::Superseded/caveated values |
| `no_t3_clinical_label_oracle_features` | `True` | AGENTS.md::Privileged oracles are large; AGENTS.md::not a deployable model |
| `no_internal_t3_hyperparameter_fishing` | `True` | findings.md::K=250 GB finding is retracted; findings.md::seed-shopping artifact |
| `no_per_item_cherry_picking_after_loocv` | `True` | AGENTS.md::Composite-level cherry-picking ban; CLAUDE.md::No composite-level cherry-picking |
| `no_loocv_reruns_after_multiple_variants` | `True` | CLAUDE.md::Never re-run LOOCV across variants; AGENTS.md::pre-register exactly one winner |

## Ceiling Break Evidence

- T1 best attempt: `X4 equal-weight 2-bag V2+V3-GSP`; CCC `0.7345218263626917`, delta `0.017483986061199164`, frac>0 `0.91`.
- T3 best attempt: `S11 direct 5-fold screen / S10 fresh replication`; fresh K250 CCC `0.3711`, S11 direct screen CCC `0.3838`.
- S13/S15 T3 transfer extension: S13 JOINT delta `4.8e-05`, S15 @70% frac>full `0.9176`, S15 @50% frac>full `0.944`.

## Decision

- All numbered items covered or access-blocked: `True`
- Completion-audit checklist passed: `True`
- Explicit prompt-directive checklist passed: `True`
- Rejected-temptation guard passed: `True`
- Goal complete: `False`
- Hard gaps: `2`
  - No T1 full-cohort candidate beats iter34 by the promotion/MCID gate.
  - No T3 full-cohort candidate beats iter47 by the promotion/MCID gate.

## Current Verified Next Action

- Source: `results/current_goal_state_verification_20260508.json`
- Action: `submit_ppmi_verily_access_request`
- Safe to execute code now: `False`
- Fill checklist: `scripts/ppmi_verily_user_fill_checklist.md`
- Packet fields to fill: `13`
- Email fields to fill: `12`
- Completed package validator: `scripts/validate_ppmi_verily_submission_package.py`
- Record submission command template: `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval command template: `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`

Next allowed action: No local WearGait-only model run is justified by this checklist. The next ceiling-break action is external access approval/submission for PPMI/Verily or another queued route, then a read-only schema probe.
