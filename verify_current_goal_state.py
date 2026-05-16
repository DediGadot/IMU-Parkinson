#!/usr/bin/env python3
"""Verify the current evidence state for the active WearGait-PD research goal.

This is not a success marker for the research objective. It validates that the
repo's handoff artifacts agree on the current state and explicitly reports
whether the objective is complete.
"""

from __future__ import annotations

import json
import html as html_lib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cache_provenance import validate_cache_manifest


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT = RESULTS / "current_goal_state_verification_20260508.json"
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}
EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT = 19
EXPECTED_PPMI_PACKET_FIELD_COUNT = 13
EXPECTED_PPMI_EMAIL_FIELD_COUNT = 12
EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT = 4
EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE = [
    {
        "step_id": "validate_completed_packet",
        "command": (
            "uv run python scripts/validate_ppmi_verily_completed_packet.py "
            "--packet <completed_packet_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_completed_email",
        "command": (
            "uv run python scripts/validate_ppmi_verily_submission_email.py "
            "--email <completed_email_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_completed_package",
        "command": (
            "uv run python scripts/validate_ppmi_verily_submission_package.py "
            "--packet <completed_packet_path_outside_git> "
            "--email <completed_email_path_outside_git>"
        ),
    },
    {
        "step_id": "record_submission_metadata",
        "command": (
            "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
            "--submitted-at-utc <ISO8601_UTC> "
            "--submission-channel <non_protected_channel> "
            "--submitted-by <non_protected_submitter> "
            "--confirmation-reference <non_protected_receipt> "
            "--pre-submission-preflight-passed"
        ),
    },
    {
        "step_id": "record_approval_metadata",
        "command": (
            "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
            "--approved-at-utc <ISO8601_UTC> "
            "--source <non_protected_approval_source>"
        ),
    },
    {
        "step_id": "validate_schema_probe_report",
        "command": (
            "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_target_free_manifest",
        "command": (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_formula_sha_record",
        "command": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            "--route-id ppmi_verily "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_zeroshot_result_record",
        "command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            "--route-id ppmi_verily "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    },
]
EXPECTED_SCHEMA_POST_APPROVAL_WORKFLOW_STEP_IDS = [
    "validate_schema_probe_report",
    "record_schema_probe_metadata",
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
]
EXPECTED_TARGET_FREE_POST_SCHEMA_WORKFLOW_STEP_IDS = [
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
]
EXPECTED_FORMULA_POST_FORMULA_WORKFLOW_STEP_IDS = [
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
]
EXPECTED_ZEROSHOT_RESULT_POST_SCORE_WORKFLOW_STEP_IDS = [
    "validate_zeroshot_result_record",
    "audit_external_result_claim_labeling",
    "audit_prompt_objective_evidence",
    "verify_current_goal_state",
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def approx_equal(value: Any, expected: float, tol: float = 5e-4) -> bool:
    try:
        return abs(float(value) - expected) <= tol
    except (TypeError, ValueError):
        return False


class Verifier:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, passed: bool, evidence: Any, required: bool = True) -> None:
        self.checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "required": bool(required),
                "evidence": evidence,
            }
        )

    @property
    def hard_failures(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if c["required"] and not c["passed"]]


def main() -> None:
    v = Verifier()

    required_files = [
        "CLAUDE.md",
        "findings.md",
        "progress.md",
        "task_plan.md",
        "gpu.sh",
        "cache_provenance.py",
        "compose_t1_iter14_fog.py",
        "compose_t1_iter15_harnet.py",
        "compose_t1_iter12_honest.py",
        "audit_t1_iter12_batch_integrity.py",
        "run_t1_iter34_hybrid_8item_multibase.py",
        "audit_t1_iter34_n93_gap.py",
        "audit_t1_iter48_aux_validrange.py",
        "audit_t1_iter34_aux_order.py",
        "audit_t1_iter34_p2_robustness.py",
        "audit_t1_iter34_base_item_decomp.py",
        "run_t1_iter46_et_robust.py",
        "run_t1_iter37_harnet_finetune.py",
        "run_t1_X4_equal_weight_2bag.py",
        "audit_t1_x4_equal_weight_2bag_status.py",
        "run_t3_iter5_clinical.py",
        "run_t3_iter23_clinical_ablation.py",
        "run_t3_iter24_stage2_forced.py",
        "run_t3_iter16_site_ipw.py",
        "run_t3_iter26_hssayeni.py",
        "scripts/ppmi_verily_setup.md",
        "scripts/ppmi_verily_tier3_request_packet.md",
        "scripts/export_ppmi_verily_packet_docx.py",
        "scripts/ppmi_verily_submission_email_template.md",
        "scripts/ppmi_verily_user_fill_checklist.md",
        "scripts/ppmi_verily_schema_probe_checklist.md",
        "scripts/ppmi_verily_schema_probe_report_template.md",
        "scripts/ppmi_verily_target_free_manifest_template.json",
        "scripts/validate_ppmi_verily_completed_packet.py",
        "scripts/validate_ppmi_verily_submission_email.py",
        "scripts/validate_ppmi_verily_submission_package.py",
        "scripts/validate_access_request_packet.py",
        "scripts/validate_ppmi_verily_schema_probe_report.py",
        "scripts/validate_schema_probe_report.py",
        "scripts/validate_ppmi_verily_target_free_manifest.py",
        "scripts/validate_target_free_manifest.py",
        "scripts/show_ppmi_verily_next_action.py",
        "scripts/show_external_access_queue.py",
        "scripts/show_access_request_fill_checklist.py",
        "scripts/write_external_access_submission_index.py",
        "scripts/show_external_access_lifecycle.py",
        "scripts/write_external_schema_probe_handoff.py",
        "scripts/write_external_target_free_manifest_templates.py",
        "scripts/write_external_zeroshot_blueprint_handoff.py",
        "scripts/write_external_formula_sha_templates.py",
        "scripts/validate_external_formula_sha_record.py",
        "scripts/write_external_zeroshot_result_templates.py",
        "scripts/validate_external_zeroshot_result_record.py",
        "scripts/record_access_submission.py",
        "scripts/record_access_approval.py",
        "scripts/record_schema_probe_report.py",
        "scripts/ppp_pd_vme_request_setup.md",
        "scripts/watchpd_request_setup.md",
        "scripts/icicle_request_setup.md",
        "scripts/cns_portugal_request_setup.md",
        "scripts/synapse_hssayeni_setup.md",
        "scripts/weargait_raw_data_recovery_runbook.md",
        "scripts/probe_tlvmc_fog_route.py",
        "scripts/write_tlvmc_defog_prereg.py",
        "run_t3_iter38_fogstar_stage1.py",
        "run_t3_iter39_fogstar_zeroshot.py",
        "run_t3_iter40_local_residual.py",
        "run_t3_iter50_lowdf_convex.py",
        "run_t3_iter49_cops.py",
        "run_t3_iter52_pdfe_turning.py",
        "run_current_conformal_abstention.py",
        "audit_t3_target_stage2_covariates.py",
        "run_t3_iter41_target_fix.py",
        "run_t3_iter42_target_prorate.py",
        "run_t3_iter47_invalid_code_fix.py",
        "audit_t3_iter47_target_integrity.py",
        "audit_t3_complete33_claim_labeling.py",
        "audit_external_result_claim_labeling.py",
        "audit_remaining_blocker_actions.py",
        "audit_external_access_readiness.py",
        "audit_ppmi_verily_request_packet.py",
        "audit_ppmi_verily_submit_format.py",
        "audit_ppmi_verily_submission_email_template.py",
        "audit_ppmi_verily_submission_email_validator.py",
        "audit_ppmi_verily_submission_package_validator.py",
        "audit_access_request_packet_validator.py",
        "audit_access_request_fill_checklist.py",
        "audit_external_access_submission_index.py",
        "audit_external_access_lifecycle_status.py",
        "audit_external_schema_probe_handoff.py",
        "audit_external_target_free_manifest_templates.py",
        "audit_external_zeroshot_blueprint_handoff.py",
        "audit_external_formula_sha_templates.py",
        "audit_external_zeroshot_result_templates.py",
        "audit_ppmi_verily_user_fill_checklist.py",
        "audit_ppmi_verily_schema_probe_checklist.py",
        "audit_ppmi_verily_schema_probe_report_template.py",
        "audit_ppmi_verily_schema_probe_report_validator.py",
        "audit_external_schema_probe_report_validator.py",
        "audit_ppmi_verily_target_free_manifest_validator.py",
        "audit_external_target_free_manifest_validator.py",
        "audit_ppmi_verily_completed_packet_validator.py",
        "audit_ppmi_verily_submission_bundle.py",
        "scripts/write_ppmi_verily_zeroshot_blueprint.py",
        "audit_ppmi_verily_zeroshot_blueprint.py",
        "audit_access_submission_tracker.py",
        "audit_access_submission_recorder.py",
        "audit_access_approval_recorder.py",
        "audit_schema_probe_recorder.py",
        "audit_current_next_action_handoff.py",
        "audit_access_lifecycle_state_handoff.py",
        "audit_ppmi_verily_next_action_status.py",
        "audit_external_access_queue_status.py",
        "audit_ppmi_verily_current_submission_handoff.py",
        "audit_proresults_prompt_to_artifact.py",
        "audit_t3_slotF_replication.py",
        "audit_weargait_raw_data_recovery_runbook.py",
        "audit_task_plan_current_scope.py",
        "audit_paper_generator_routing.py",
        "audit_readme_claim_routing.py",
        "audit_legacy_manuscript_surfaces.py",
        "audit_historical_archive_surfaces.py",
        "audit_secret_hygiene.py",
        "audit_t3_iter47_residual_anatomy.py",
        "audit_t3_iter47_ccc_rescale_sanity.py",
        "audit_current_headline_influence.py",
        "audit_t3_iter47_domain_residuals.py",
        "audit_t3_iter47_item_residuals.py",
        "audit_t3_clinical_dependency.py",
        "visualize_t3_iter5.py",
        "visualize_fogstar_iter39.py",
        "visualize_current_best_pipeline.py",
        "render_current_paper.py",
        "audit_prompt_objective_evidence.py",
        "audit_cache_manifests.py",
        "audit_missing_cache_manifest_origins.py",
        "audit_manual_cache_backfill_evidence.py",
        "audit_cache_backfill_candidates.py",
        "audit_cache_backfill_decisions.py",
        "audit_cache_consumer_guards.py",
        "audit_transitive_cache_dependencies.py",
        "audit_runtime_cache_dependencies.py",
        "audit_dst_walkway_leakage.py",
        "audit_ablation_v3_cache_provenance.py",
        "audit_ablation_v3_regeneration.py",
        "scripts/download_weargait_missing_synapse.py",
        "audit_canonical_claim_consistency.py",
        "audit_headline_metric_recompute.py",
        "audit_ccc_metric_integrity.py",
        "audit_oof_artifact_integrity.py",
        "audit_preregistration_temporal_integrity.py",
        "audit_pre_audit_claim_labeling.py",
        "audit_historical_subdomain_claim_labeling.py",
        "audit_t1_candidate_claim_labeling.py",
        "audit_reportable_artifact_flags.py",
        "audit_per_item_evidence_map.py",
        "audit_per_item_oof_companion_scope.py",
        "tests/test_cache_provenance.py",
        "tests/test_run_t1_iter4_labels.py",
        "CURRENT_PAPER.html",
        "results/thread_goal_completion_audit_20260508.md",
        "results/current_best_pipeline_artifact_index_20260508.md",
        "results/external_dataset_route_audit_20260508.md",
        "results/external_dataset_route_audit_20260508.json",
        "results/phone_tremor_route_consult_20260509.json",
        "results/phone_tremor_route_consult_20260509.md",
        "results/harmonized_accel_route_consult_20260509.json",
        "results/harmonized_accel_route_consult_20260509.md",
        "results/smartwatch_subitem_route_refresh_20260509.json",
        "results/smartwatch_subitem_route_refresh_20260509.md",
        "results/external_route_audit_monipar_bioclite_20260509.md",
        "results/derivative_multimodal_route_refresh_20260509.json",
        "results/derivative_multimodal_route_refresh_20260509.md",
        "results/request_only_actigraphy_route_refresh_20260509.json",
        "results/request_only_actigraphy_route_refresh_20260509.md",
        "results/luxembourg_upper_limb_route_refresh_20260509.json",
        "results/luxembourg_upper_limb_route_refresh_20260509.md",
        "results/prequantipark_route_refresh_20260509.json",
        "results/prequantipark_route_refresh_20260509.md",
        "results/tum_rocket_inception_route_refresh_20260509.json",
        "results/tum_rocket_inception_route_refresh_20260509.md",
        "results/paradigma_yin_route_refresh_20260509.json",
        "results/paradigma_yin_route_refresh_20260509.md",
        "run_t3_iter53_parkinsonathome.py",
        "results/preregistration_t3_iter53_parkinsonathome_zeroshot.json",
        "results/preregistration_t3_iter53_parkinsonathome_zeroshot.md",
        "results/iter53_parkinsonathome_probe.json",
        "results/iter53_parkinsonathome_features.csv",
        "results/iter53_parkinsonathome_features.csv.manifest.json",
        "results/parkinsonathome_route_refresh_20260509.json",
        "results/parkinsonathome_route_refresh_20260509.md",
        "results/ablation_v3_regeneration_probe_20260509.json",
        "results/ablation_v3_regeneration_probe_20260509.md",
        "results/weargait_missing_synapse_recovery_preflight_20260509.json",
        "results/weargait_missing_synapse_recovery_preflight_20260509.md",
        "results/t3_iter47_residual_anatomy_20260509.json",
        "results/t3_iter47_residual_anatomy_20260509.md",
        "results/t3_iter47_ccc_rescale_sanity_20260509.json",
        "results/t3_iter47_ccc_rescale_sanity_20260509.md",
        "results/current_headline_influence_audit_20260509.json",
        "results/current_headline_influence_audit_20260509.md",
        "results/t3_iter47_domain_residual_audit_20260509.json",
        "results/t3_iter47_domain_residual_audit_20260509.md",
        "results/t3_iter47_item_residual_audit_20260509.json",
        "results/t3_iter47_item_residual_audit_20260509.md",
        "results/tlvmc_fog_route_probe_20260509.json",
        "results/tlvmc_fog_route_probe_20260509.md",
        "results/preregistration_t3_iter51_tlvmc_defog_zeroshot.json",
        "results/preregistration_t3_iter51_tlvmc_defog_zeroshot_20260509_010408.json",
        "results/preregistration_t3_iter51_tlvmc_defog_zeroshot.md",
        "run_t3_iter51_tlvmc_defog.py",
        "results/iter51_tlvmc_defog_download_manifest.json",
        "results/iter51_tlvmc_defog_features.csv",
        "results/iter51_tlvmc_defog_features.csv.manifest.json",
        "results/iter51_tlvmc_defog_zeroshot.json",
        "results/iter51_tlvmc_defog_zeroshot_20260509_013357.json",
        "results/iter51_tlvmc_defog_zeroshot_rows_20260509_013357.csv",
        "results/preregistration_t3_iter52_pdfe_turning_zeroshot.json",
        "results/preregistration_t3_iter52_pdfe_turning_zeroshot.md",
        "results/iter52_pdfe_turning_probe.json",
        "results/iter52_pdfe_turning_download_manifest.json",
        "results/iter52_pdfe_turning_features.csv",
        "results/iter52_pdfe_turning_features.csv.manifest.json",
        "results/iter52_pdfe_turning_zeroshot.json",
        "results/iter52_pdfe_turning_zeroshot_20260509_092223.json",
        "results/iter52_pdfe_turning_zeroshot_rows_20260509_092223.csv",
        "results/current_best_pipeline_dashboard.html",
        "results/current_best_pipeline_dashboard/manifest.json",
        "results/current_paper_export/manifest.json",
        "results/prompt_objective_evidence_audit_20260508.json",
        "results/prompt_objective_evidence_audit_20260508.md",
        "results/cache_manifest_audit_20260508.json",
        "results/cache_manifest_audit_20260508.md",
        "results/item11_multiscale_recordings.csv.manifest.json",
        "results/missing_cache_manifest_origin_audit_20260509.json",
        "results/missing_cache_manifest_origin_audit_20260509.md",
        "results/manual_cache_backfill_evidence_20260509.json",
        "results/manual_cache_backfill_evidence_20260509.md",
        "results/cache_backfill_candidates_20260508.json",
        "results/cache_backfill_candidates_20260508.md",
        "results/cache_backfill_decisions_20260508.json",
        "results/cache_backfill_decisions_20260508.md",
        "results/cache_consumer_guard_audit_20260508.json",
        "results/cache_consumer_guard_audit_20260508.md",
        "results/transitive_cache_dependency_audit_20260508.json",
        "results/transitive_cache_dependency_audit_20260508.md",
        "results/runtime_cache_dependency_audit_20260508.json",
        "results/runtime_cache_dependency_audit_20260508.md",
        "results/dst_walkway_leakage_audit_20260508_multiseed.json",
        "results/dst_walkway_leakage_audit_20260508_multiseed.md",
        "results/dst_walkway_leakage_audit_rows_20260508_multiseed.csv",
        "results/dst_walkway_leakage_audit_subject_rows_20260508_multiseed.csv",
        "results/ablation_v3_cache_provenance_audit_20260508.json",
        "results/ablation_v3_cache_provenance_audit_20260508.md",
        "results/canonical_claim_consistency_audit_20260508.json",
        "results/canonical_claim_consistency_audit_20260508.md",
        "results/headline_metric_recompute_audit_20260508.json",
        "results/headline_metric_recompute_audit_20260508.md",
        "results/ccc_metric_integrity_audit_20260509.json",
        "results/ccc_metric_integrity_audit_20260509.md",
        "results/oof_artifact_integrity_audit_20260508.json",
        "results/oof_artifact_integrity_audit_20260508.md",
        "results/preregistration_temporal_integrity_audit_20260508.json",
        "results/preregistration_temporal_integrity_audit_20260508.md",
        "results/pre_audit_claim_labeling_audit_20260508.json",
        "results/pre_audit_claim_labeling_audit_20260508.md",
        "results/historical_subdomain_claim_labeling_audit_20260509.json",
        "results/historical_subdomain_claim_labeling_audit_20260509.md",
        "results/t1_candidate_claim_labeling_audit_20260508.json",
        "results/t1_candidate_claim_labeling_audit_20260508.md",
        "results/reportable_artifact_flag_audit_20260509.json",
        "results/reportable_artifact_flag_audit_20260509.md",
        "results/per_item_evidence_map_20260508.json",
        "results/per_item_evidence_map_20260508.md",
        "results/per_item_oof_companion_scope_audit_20260508.json",
        "results/per_item_oof_companion_scope_audit_20260508.md",
        "results/t1_iter12_batch_integrity_audit_20260508.json",
        "results/t1_iter12_batch_integrity_audit_20260508.md",
        "results/t1_iter12_honest_composite.json",
        "results/t1_iter12_honest_composite.oof.npy",
        "results/lockbox_t1_iter34_hybrid_20260510_233019.json",
        "results/lockbox_t1_iter34_hybrid_20260510_233019.oof.npy",
        "results/t1_iter34_hygiene_corrected_status_20260510.json",
        "results/lockbox_t1_iter34_hybrid_20260506_141720.json",
        "results/lockbox_t1_iter34_hybrid_20260506_141720.oof.npy",
        "results/audit_t1_iter34_n93_gap_20260508.json",
        "results/t1_iter48_aux_validrange_audit.json",
        "results/t1_iter34_aux_order_audit.json",
        "results/t1_iter34_aux_order_audit.md",
        "results/iter34_p2_robustness_20260508.json",
        "results/iter34_base_item_decomp_20260508.json",
        "results/preregistration_t1_iter46_etrobust_20260508_160501.json",
        "results/lockbox_t1_iter46_etrobust_20260508_162825.json",
        "results/lockbox_t1_iter46_etrobust_20260508_162825.oof.npy",
        "results/iter46_etrobust_local_comparisons_20260508.json",
        "results/iter37_harnet_finetune_screen_20260508_110641.json",
        "results/iter37_harnet_finetune_rows_20260508_110641.csv",
        "results/iter37_harnet_wrist_windows.npz",
        "results/lockbox_t3_iter5_A3_tier1_20260502_171604.json",
        "results/lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy",
        "results/t3_iter16_site_ipw_lockbox.json",
        "results/t3_conformal_abstention_20260505.json",
        "results/t3_iter5_deepdive/summary.json",
        "results/iter26_dua_status_20260508.json",
        "results/iter38_fogstar_probe_20260508_112546.json",
        "results/iter38_fogstar_stage1_screen_20260508_142623.json",
        "results/iter38_fogstar_stage1_screen_rows_20260508_142623.csv",
        "results/preregistration_t3_iter39_fogstar_zeroshot_20260508_143717.json",
        "results/iter39_fogstar_zeroshot_20260508_143717.json",
        "results/iter39_fogstar_zeroshot_rows_20260508_143717.csv",
        "results/iter39_fogstar_zeroshot.html",
        "results/iter39_fogstar_zeroshot/manifest.json",
        "results/openrouter_grok43_iter39_20260508.json",
        "results/openrouter_deepseekv4pro_iter39_retry_20260508.json",
        "results/iter40_local_residual_screen_20260508_144905.json",
        "results/iter40_local_residual_screen_rows_20260508_144905.csv",
        "results/preregistration_t3_iter50_lowdfconvex_screen_20260508_225105.json",
        "results/iter50_lowdf_convex_screen_20260508_225105.json",
        "results/iter50_lowdf_convex_screen_rows_20260508_225105.csv",
        "results/iter50_lowdf_convex_subject_preds_20260508_225105.csv",
        "results/preregistration_t3_iter49_cops.json",
        "results/iter49_cops_probe.json",
        "results/iter49_cops_download_manifest.json",
        "results/iter49_cops_features_full.csv",
        "results/iter49_cops_features_full.csv.manifest.json",
        "results/iter49_cops_zeroshot_20260508_185226.json",
        "results/iter49_cops_zeroshot.json",
        "results/iter49_cops_zeroshot_rows_20260508_185226.csv",
        "results/current_conformal_abstention_20260508.json",
        "results/current_conformal_abstention_intervals_20260508.csv",
        "results/current_conformal_abstention_curves_20260508.csv",
        "results/current_conformal_abstention.html",
        "results/t3_target_stage2_covariate_audit_20260508_165653.json",
        "results/t3_target_stage2_covariate_audit_target_rows_20260508_165653.csv",
        "results/t3_target_stage2_covariate_audit_stage2_rows_20260508_165653.csv",
        "results/preregistration_t3_iter41_targetfix_20260508_170021.json",
        "results/iter41_targetfix_20260508_170021.json",
        "results/iter41_targetfix_rows_20260508_170021.csv",
        "results/iter41_targetfix_subject_preds_20260508_170021.csv",
        "results/preregistration_t3_iter41_targetfix_loso_20260508_171003.json",
        "results/iter41_targetfix_loso_20260508_171003.json",
        "results/iter41_targetfix_loso_rows_20260508_171003.csv",
        "results/preregistration_t3_iter47_invalidcode_20260508_194605.json",
        "results/iter47_invalidcode_20260508_194605.json",
        "results/iter47_invalidcode_rows_20260508_194605.csv",
        "results/iter47_invalidcode_subject_preds_20260508_194605.csv",
        "results/preregistration_t3_iter47_invalidcode_loso_20260508_195424.json",
        "results/iter47_invalidcode_loso_20260508_195424.json",
        "results/iter47_invalidcode_loso_rows_20260508_195424.csv",
        "results/t3_iter47_target_integrity_audit_20260508.json",
        "results/t3_iter47_target_integrity_audit_20260508.md",
        "results/t3_complete33_claim_labeling_audit_20260509.json",
        "results/t3_complete33_claim_labeling_audit_20260509.md",
        "results/external_result_claim_labeling_audit_20260509.json",
        "results/external_result_claim_labeling_audit_20260509.md",
        "results/remaining_blocker_action_audit_20260509.json",
        "results/remaining_blocker_action_audit_20260509.md",
        "results/external_access_readiness_audit_20260509.json",
        "results/external_access_readiness_audit_20260509.md",
        "results/access_submission_tracker_20260509.json",
        "results/access_submission_tracker_20260509.md",
        "results/access_request_packet_validator_audit_20260515.json",
        "results/access_request_packet_validator_audit_20260515.md",
        "results/access_request_fill_checklist_audit_20260515.json",
        "results/access_request_fill_checklist_audit_20260515.md",
        "results/external_access_submission_index_20260515.json",
        "results/external_access_submission_index_20260515.md",
        "results/external_access_submission_index_audit_20260515.json",
        "results/external_access_submission_index_audit_20260515.md",
        "results/external_access_lifecycle_status_audit_20260515.json",
        "results/external_access_lifecycle_status_audit_20260515.md",
        "results/external_schema_probe_handoff_20260515.json",
        "results/external_schema_probe_handoff_20260515.md",
        "results/external_schema_probe_handoff_audit_20260515.json",
        "results/external_schema_probe_handoff_audit_20260515.md",
        "results/external_target_free_manifest_templates_20260515.json",
        "results/external_target_free_manifest_templates_20260515.md",
        "results/external_target_free_manifest_templates_audit_20260515.json",
        "results/external_target_free_manifest_templates_audit_20260515.md",
        "results/external_zeroshot_blueprint_handoff_20260515.json",
        "results/external_zeroshot_blueprint_handoff_20260515.md",
        "results/external_zeroshot_blueprint_handoff_audit_20260515.json",
        "results/external_zeroshot_blueprint_handoff_audit_20260515.md",
        "results/external_formula_sha_templates_20260515.json",
        "results/external_formula_sha_templates_20260515.md",
        "results/external_formula_sha_templates_audit_20260515.json",
        "results/external_formula_sha_templates_audit_20260515.md",
        "results/external_zeroshot_result_templates_20260515.json",
        "results/external_zeroshot_result_templates_20260515.md",
        "results/external_zeroshot_result_templates_audit_20260515.json",
        "results/external_zeroshot_result_templates_audit_20260515.md",
        "results/external_schema_probe_report_validator_audit_20260515.json",
        "results/external_schema_probe_report_validator_audit_20260515.md",
        "results/external_target_free_manifest_validator_audit_20260515.json",
        "results/external_target_free_manifest_validator_audit_20260515.md",
        "results/external_access_queue_status_audit_20260515.json",
        "results/external_access_queue_status_audit_20260515.md",
        "results/ppmi_verily_request_packet_audit_20260509.json",
        "results/ppmi_verily_request_packet_audit_20260509.md",
        "results/ppmi_verily_tier3_request_packet_template_20260515.docx",
        "results/ppmi_verily_tier3_request_packet_template_20260515.manifest.json",
        "results/ppmi_verily_submit_format_audit_20260515.json",
        "results/ppmi_verily_submit_format_audit_20260515.md",
        "results/ppmi_verily_submission_email_template_audit_20260515.json",
        "results/ppmi_verily_submission_email_template_audit_20260515.md",
        "results/ppmi_verily_submission_email_validator_audit_20260515.json",
        "results/ppmi_verily_submission_email_validator_audit_20260515.md",
        "results/ppmi_verily_submission_package_validator_audit_20260515.json",
        "results/ppmi_verily_submission_package_validator_audit_20260515.md",
        "results/ppmi_verily_user_fill_checklist_audit_20260515.json",
        "results/ppmi_verily_user_fill_checklist_audit_20260515.md",
        "results/ppmi_verily_schema_probe_checklist_audit_20260515.json",
        "results/ppmi_verily_schema_probe_checklist_audit_20260515.md",
        "results/ppmi_verily_schema_probe_report_template_audit_20260515.json",
        "results/ppmi_verily_schema_probe_report_template_audit_20260515.md",
        "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json",
        "results/ppmi_verily_schema_probe_report_validator_audit_20260515.md",
        "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json",
        "results/ppmi_verily_target_free_manifest_validator_audit_20260515.md",
        "results/ppmi_verily_completed_packet_validator_audit_20260515.json",
        "results/ppmi_verily_completed_packet_validator_audit_20260515.md",
        "results/ppmi_verily_submission_bundle_20260515.json",
        "results/ppmi_verily_submission_bundle_20260515.md",
        "results/ppmi_verily_zeroshot_blueprint_20260515.json",
        "results/ppmi_verily_zeroshot_blueprint_20260515.md",
        "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
        "results/ppmi_verily_zeroshot_blueprint_audit_20260515.md",
        "results/access_submission_recorder_audit_20260510.json",
        "results/access_submission_recorder_audit_20260510.md",
        "results/access_approval_recorder_audit_20260510.json",
        "results/access_approval_recorder_audit_20260510.md",
        "results/schema_probe_recorder_audit_20260510.json",
        "results/schema_probe_recorder_audit_20260510.md",
        "results/current_next_action_handoff_20260515.json",
        "results/current_next_action_handoff_20260515.md",
        "results/ppmi_verily_current_submission_handoff_20260515.json",
        "results/ppmi_verily_current_submission_handoff_20260515.md",
        "results/access_lifecycle_state_handoff_20260515.json",
        "results/access_lifecycle_state_handoff_20260515.md",
        "results/ppmi_verily_next_action_status_audit_20260515.json",
        "results/ppmi_verily_next_action_status_audit_20260515.md",
        "results/proresults_prompt_to_artifact_audit_20260515.json",
        "results/proresults_prompt_to_artifact_audit_20260515.md",
        "results/t3_slotF_replication_audit_20260515.json",
        "results/t3_slotF_replication_audit_20260515.md",
        "results/weargait_raw_data_recovery_runbook_audit_20260509.json",
        "results/weargait_raw_data_recovery_runbook_audit_20260509.md",
        "results/task_plan_current_scope_audit_20260509.json",
        "results/task_plan_current_scope_audit_20260509.md",
        "results/paper_generator_routing_audit_20260509.json",
        "results/paper_generator_routing_audit_20260509.md",
        "results/readme_claim_routing_audit_20260509.json",
        "results/readme_claim_routing_audit_20260509.md",
        "results/legacy_manuscript_surface_audit_20260509.json",
        "results/legacy_manuscript_surface_audit_20260509.md",
        "results/historical_archive_surface_audit_20260509.json",
        "results/historical_archive_surface_audit_20260509.md",
        "results/secret_hygiene_audit_20260509.json",
        "results/secret_hygiene_audit_20260509.md",
        "results/t3_iter47_ccc_rescale_sanity_20260509.json",
        "results/t3_iter47_ccc_rescale_sanity_20260509.md",
        "results/current_headline_influence_audit_20260509.json",
        "results/current_headline_influence_audit_20260509.md",
        "results/t3_iter47_domain_residual_audit_20260509.json",
        "results/t3_iter47_domain_residual_audit_20260509.md",
        "results/t3_iter47_item_residual_audit_20260509.json",
        "results/t3_iter47_item_residual_audit_20260509.md",
        "results/preregistration_t3_iter42_prorate_20260508_173412.json",
        "results/iter42_prorate_20260508_173412.json",
        "results/iter42_prorate_rows_20260508_173412.csv",
        "results/iter42_prorate_subject_preds_20260508_173412.csv",
        "results/preregistration_t3_iter42_prorate_loso_20260508_174349.json",
        "results/iter42_prorate_loso_20260508_174349.json",
        "results/iter42_prorate_loso_rows_20260508_174349.csv",
        "results/t3_clinical_dependency_20260508.json",
        "results/t3_clinical_dependency_20260508_subject_rows.csv",
    ]
    missing = [p for p in required_files if not (ROOT / p).exists()]
    v.check("required artifacts exist", not missing, {"missing": missing, "count": len(required_files)})

    claude = read_text(ROOT / "CLAUDE.md")
    agents = read_text(ROOT / "AGENTS.md")
    readme = read_text(ROOT / "README.md")
    findings = read_text(ROOT / "findings.md")
    progress = read_text(ROOT / "progress.md")
    task_plan = read_text(ROOT / "task_plan.md")
    audit_md = read_text(RESULTS / "thread_goal_completion_audit_20260508.md")
    index_md = read_text(RESULTS / "current_best_pipeline_artifact_index_20260508.md")
    external_audit_md = read_text(RESULTS / "external_dataset_route_audit_20260508.md")
    ppmi_runbook = read_text(ROOT / "scripts/ppmi_verily_setup.md")
    ppmi_packet = read_text(ROOT / "scripts/ppmi_verily_tier3_request_packet.md")
    ppmi_schema_probe_checklist = read_text(ROOT / "scripts/ppmi_verily_schema_probe_checklist.md")
    ppmi_schema_probe_template = read_text(ROOT / "scripts/ppmi_verily_schema_probe_report_template.md")
    ppp_runbook = read_text(ROOT / "scripts/ppp_pd_vme_request_setup.md")
    watchpd_runbook = read_text(ROOT / "scripts/watchpd_request_setup.md")
    icicle_runbook = read_text(ROOT / "scripts/icicle_request_setup.md")
    cns_runbook = read_text(ROOT / "scripts/cns_portugal_request_setup.md")
    hssayeni_runbook = read_text(ROOT / "scripts/synapse_hssayeni_setup.md")
    raw_recovery_runbook = read_text(ROOT / "scripts/weargait_raw_data_recovery_runbook.md")
    gpu_sh = read_text(ROOT / "gpu.sh")
    current_paper = read_text(ROOT / "CURRENT_PAPER.html")
    current_paper_text = html_lib.unescape(re.sub(r"<[^>]+>", " ", current_paper))
    current_paper_text = re.sub(r"\s+", " ", current_paper_text)

    v.check(
        "canonical numbers present in CLAUDE.md",
        all(s in claude for s in ["0.6550", "0.3784", "0.150", "target-contaminated", "compose_t1_iter12_honest.py", "run_t3_iter47_invalid_code_fix.py"]),
        {"snippets": ["0.6550", "0.3784", "0.150", "target-contaminated"]},
    )
    v.check(
        "SOTA web-search finding persisted",
        "F-web-20260508" in findings and "CARE-PD" in findings and "PASADENA" in findings and "FoG-STAR" in findings,
        {"required_section": "F-web-20260508"},
    )
    v.check(
        "remote defaults are configured to requested server",
        'REMOTE="${GPU_REMOTE:-fiod@165.22.71.91}"' in gpu_sh and 'PORT="${GPU_PORT:-2243}"' in gpu_sh,
        {"remote": "fiod@165.22.71.91", "port": 2243},
    )
    v.check(
        "planning files record active not-complete state",
        "Thread goal remains active / not complete" in task_plan
        and "Current completion criteria (post-iter47)" in task_plan
        and "goal remains **not complete**" in task_plan
        and "active thread goal is not complete" in progress,
        {"task_plan": "not complete with current completion criteria", "progress": "not complete"},
    )

    t1_floor = load_json(RESULTS / "t1_iter12_honest_composite.json")
    t1_iter12_batch_integrity = load_json(RESULTS / "t1_iter12_batch_integrity_audit_20260508.json")
    t1_best = load_json(RESULTS / "lockbox_t1_iter34_hybrid_20260510_233019.json")
    t1_hygiene = load_json(RESULTS / "t1_iter34_hygiene_corrected_status_20260510.json")
    t1_n93_gap = load_json(RESULTS / "audit_t1_iter34_n93_gap_20260508.json")
    t1_aux_valid = load_json(RESULTS / "t1_iter48_aux_validrange_audit.json")
    t1_aux_order = load_json(RESULTS / "t1_iter34_aux_order_audit.json")
    t1_p2 = load_json(RESULTS / "iter34_p2_robustness_20260508.json")
    t1_decomp = load_json(RESULTS / "iter34_base_item_decomp_20260508.json")
    t1_iter46 = load_json(RESULTS / "lockbox_t1_iter46_etrobust_20260508_162825.json")
    t1_iter46_cmp = load_json(RESULTS / "iter46_etrobust_local_comparisons_20260508.json")
    t1_iter37 = load_json(RESULTS / "iter37_harnet_finetune_screen_20260508_110641.json")
    t1_x4 = load_json(RESULTS / "lockbox_t1_X4_equal_weight_2bag_20260516T074106Z.json")
    t1_x4_status = load_json(RESULTS / "t1_x4_equal_weight_2bag_status_20260516.json")
    t3_old = load_json(RESULTS / "lockbox_t3_iter5_A3_tier1_20260502_171604.json")
    t3_audit = load_json(RESULTS / "t3_target_stage2_covariate_audit_20260508_165653.json")
    t3_iter41 = load_json(RESULTS / "iter41_targetfix_20260508_170021.json")
    t3_iter41_loso = load_json(RESULTS / "iter41_targetfix_loso_20260508_171003.json")
    t3_iter47 = load_json(RESULTS / "iter47_invalidcode_20260508_194605.json")
    t3_iter47_loso = load_json(RESULTS / "iter47_invalidcode_loso_20260508_195424.json")
    t3_iter47_target_integrity = load_json(RESULTS / "t3_iter47_target_integrity_audit_20260508.json")
    t3_iter47_residual_anatomy = load_json(RESULTS / "t3_iter47_residual_anatomy_20260509.json")
    t3_iter47_residual_anatomy_md = read_text(RESULTS / "t3_iter47_residual_anatomy_20260509.md")
    t3_iter47_ccc_rescale = load_json(RESULTS / "t3_iter47_ccc_rescale_sanity_20260509.json")
    t3_iter47_ccc_rescale_md = read_text(RESULTS / "t3_iter47_ccc_rescale_sanity_20260509.md")
    headline_influence = load_json(RESULTS / "current_headline_influence_audit_20260509.json")
    headline_influence_md = read_text(RESULTS / "current_headline_influence_audit_20260509.md")
    t3_domain_residual = load_json(RESULTS / "t3_iter47_domain_residual_audit_20260509.json")
    t3_domain_residual_md = read_text(RESULTS / "t3_iter47_domain_residual_audit_20260509.md")
    t3_item_residual = load_json(RESULTS / "t3_iter47_item_residual_audit_20260509.json")
    t3_item_residual_md = read_text(RESULTS / "t3_iter47_item_residual_audit_20260509.md")
    t3_iter42 = load_json(RESULTS / "iter42_prorate_20260508_173412.json")
    t3_iter42_loso = load_json(RESULTS / "iter42_prorate_loso_20260508_174349.json")
    t3_clinical = load_json(RESULTS / "t3_clinical_dependency_20260508.json")
    t3_deep = load_json(RESULTS / "t3_iter5_deepdive" / "summary.json")
    t3_site = load_json(RESULTS / "t3_iter16_site_ipw_lockbox.json")
    t3_iter38 = load_json(RESULTS / "iter38_fogstar_stage1_screen_20260508_142623.json")
    t3_iter39 = load_json(RESULTS / "iter39_fogstar_zeroshot_20260508_143717.json")
    t3_iter40 = load_json(RESULTS / "iter40_local_residual_screen_20260508_144905.json")
    t3_iter50_prereg = load_json(RESULTS / "preregistration_t3_iter50_lowdfconvex_screen_20260508_225105.json")
    t3_iter50 = load_json(RESULTS / "iter50_lowdf_convex_screen_20260508_225105.json")
    t3_iter49_prereg = load_json(RESULTS / "preregistration_t3_iter49_cops.json")
    t3_iter49_probe = load_json(RESULTS / "iter49_cops_probe.json")
    t3_iter49 = load_json(RESULTS / "iter49_cops_zeroshot.json")
    tlvmc_probe = load_json(RESULTS / "tlvmc_fog_route_probe_20260509.json")
    tlvmc_prereg = load_json(RESULTS / "preregistration_t3_iter51_tlvmc_defog_zeroshot.json")
    tlvmc_iter51 = load_json(RESULTS / "iter51_tlvmc_defog_zeroshot.json")
    pdfe_prereg = load_json(RESULTS / "preregistration_t3_iter52_pdfe_turning_zeroshot.json")
    pdfe_probe = load_json(RESULTS / "iter52_pdfe_turning_probe.json")
    pdfe_feature_manifest = load_json(RESULTS / "iter52_pdfe_turning_features.csv.manifest.json")
    pdfe_iter52 = load_json(RESULTS / "iter52_pdfe_turning_zeroshot.json")
    current_conformal = load_json(RESULTS / "current_conformal_abstention_20260508.json")
    per_item_map = load_json(RESULTS / "per_item_evidence_map_20260508.json")
    per_item_oof_scope = load_json(RESULTS / "per_item_oof_companion_scope_audit_20260508.json")

    v.check(
        "T1 canonical floor metrics match",
        approx_equal(t1_floor.get("ccc"), 0.6550) and approx_equal(t1_floor.get("mae"), 1.5614, 1e-3) and t1_floor.get("n") == 94,
        {"ccc": t1_floor.get("ccc"), "mae": t1_floor.get("mae"), "n": t1_floor.get("n")},
    )
    v.check(
        "T1 iter12 single-batch integrity audit passes",
        t1_iter12_batch_integrity.get("pass") is True
        and t1_iter12_batch_integrity.get("hard_failures") == []
        and t1_iter12_batch_integrity.get("warnings") == []
        and t1_iter12_batch_integrity.get("batch", {}).get("timestamp") == "20260430_143044"
        and t1_iter12_batch_integrity.get("batch", {}).get("single_coherent_batch") is True
        and t1_iter12_batch_integrity.get("batch", {}).get("uses_swaps") is False
        and approx_equal(t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("ccc"), 0.6550)
        and approx_equal(t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("mae"), 1.5614, 1e-3)
        and approx_equal(t1_iter12_batch_integrity.get("composite", {}).get("max_abs_diff_vs_stored_oof"), 0.0),
        {
            "pass": t1_iter12_batch_integrity.get("pass"),
            "hard_failures": t1_iter12_batch_integrity.get("hard_failures"),
            "warnings": t1_iter12_batch_integrity.get("warnings"),
            "batch": t1_iter12_batch_integrity.get("batch"),
            "composite": t1_iter12_batch_integrity.get("composite"),
            "item_count": len(t1_iter12_batch_integrity.get("item_checks", [])),
        },
    )
    v.check(
        "T1 corrected-candidate metrics match",
        approx_equal(t1_best.get("ccc"), 0.7170)
        and approx_equal(t1_best.get("mae"), 1.7356, 1e-3)
        and t1_best.get("n") == 92
        and t1_hygiene.get("status") == "corrected_candidate_degraded_but_above_0_700"
        and t1_hygiene.get("result_available") is True,
        {
            "ccc": t1_best.get("ccc"),
            "mae": t1_best.get("mae"),
            "n": t1_best.get("n"),
            "hygiene_status": t1_hygiene.get("status"),
        },
    )
    t1_gap_subject = t1_n93_gap.get("missing_from_iter34", {})
    t1_gap_verdict = t1_n93_gap.get("verdict", {})
    t1_gap_scenarios = t1_n93_gap.get("scenarios", {})
    v.check(
        "T1 iter34 N=93 gap audit records non-load-bearing caveat",
        t1_gap_subject.get("sid") == "WPD002"
        and t1_gap_subject.get("t1_items_complete") is True
        and t1_gap_subject.get("missing_items") == ["18"]
        and approx_equal(t1_gap_subject.get("t1_true"), 4.0)
        and approx_equal(t1_gap_scenarios.get("iter34_n93_locked", {}).get("ccc"), 0.736594, 1e-6)
        and approx_equal(t1_gap_scenarios.get("iter34_plus_excluded_grid_optimal_prediction", {}).get("ccc"), 0.736598, 1e-6)
        and t1_gap_verdict.get("n93_gap_material") is False,
        {
            "subject": t1_gap_subject,
            "locked": t1_gap_scenarios.get("iter34_n93_locked"),
            "grid_optimal": t1_gap_scenarios.get("iter34_plus_excluded_grid_optimal_prediction"),
            "verdict": t1_gap_verdict,
        },
    )
    t1_aux_invalid = t1_aux_valid.get("invalid_auxiliary_items_in_current_chain_cohort", [])
    t1_aux_first = t1_aux_invalid[0] if t1_aux_invalid else {}
    t1_aux_subparts = t1_aux_first.get("subparts", {})
    t1_aux_interp = t1_aux_valid.get("interpretation", {})
    v.check(
        "T1 iter34 auxiliary valid-range audit records document-only caveat",
        t1_aux_valid.get("current_loader", {}).get("t1_n") == 94
        and t1_aux_valid.get("current_loader", {}).get("chain_n") == 93
        and t1_aux_valid.get("validated_loader", {}).get("t1_n") == 94
        and t1_aux_valid.get("validated_loader", {}).get("chain_n") == 92
        and t1_aux_valid.get("cohort_deltas", {}).get("current_chain_minus_validated_chain") == ["NLS036"]
        and t1_aux_valid.get("cohort_deltas", {}).get("current_t1_minus_validated_t1") == []
        and t1_aux_first.get("sid") == "NLS036"
        and t1_aux_first.get("item") == 15
        and approx_equal(t1_aux_first.get("value"), 18.0)
        and approx_equal(t1_aux_first.get("valid_max"), 8.0)
        and approx_equal(t1_aux_subparts.get("(15, 'a')"), 9.0)
        and approx_equal(t1_aux_subparts.get("(15, 'b')"), 9.0)
        and t1_aux_valid.get("invalid_t1_target_items_in_current_t1_cohort") == []
        and t1_aux_interp.get("primary_t1_target_valid") is True
        and t1_aux_interp.get("iter34_auxiliary_chain_uses_invalid_label") is True
        and t1_aux_interp.get("recommended_status") == "document_only_no_posthoc_rerun_future_loader_fail_closed",
        {
            "current_loader": t1_aux_valid.get("current_loader"),
            "validated_loader": t1_aux_valid.get("validated_loader"),
            "cohort_deltas": t1_aux_valid.get("cohort_deltas"),
            "invalid_auxiliary_items": t1_aux_invalid,
            "interpretation": t1_aux_interp,
        },
    )
    t1_aux_order_summary = t1_aux_order.get("order_audit", {}).get("summary", {})
    t1_aux_order_rows = {
        int(row.get("seed")): row for row in t1_aux_order.get("order_audit", {}).get("rows", [])
    }
    t1_aux_order_impact = t1_aux_order.get("impact_screen", {}).get("common_sid_comparison", {})
    v.check(
        "T1 iter34 auxiliary random-chain order audit records tiny measured impact",
        t1_aux_order.get("mode") == "screen"
        and t1_aux_order_summary.get("kimi_fixed_order_assumption_status") == "falsified_by_code"
        and t1_aux_order_summary.get("iter34_lockbox_seeds_with_item15_upstream_of_any_t1") == [7, 1337]
        and t1_aux_order_summary.get("iter34_lockbox_seed_count_with_exposure") == 2
        and t1_aux_order_summary.get("iter34_lockbox_seed_count") == 3
        and t1_aux_order_summary.get("iter46_decomp_seed_count_with_exposure") == 4
        and t1_aux_order_rows.get(1337, {}).get("t1_items_after_item15") == [9, 10, 11, 12, 13, 14]
        and t1_aux_order_impact.get("excluded_from_validated") == ["NLS036"]
        and approx_equal(t1_aux_order_impact.get("delta_valid_minus_stale_common_ccc"), -0.0008185341, 1e-6)
        and t1_aux_order_impact.get("materiality_flag") is False,
        {
            "summary": t1_aux_order_summary,
            "seed_1337": t1_aux_order_rows.get(1337),
            "impact": t1_aux_order_impact,
            "status": t1_aux_order.get("impact_screen", {}).get("status"),
        },
    )
    t1_p2_summary = t1_p2.get("summary", {})
    t1_p2_verdict = t1_p2.get("verdict", {})
    v.check(
        "T1 iter34 P2 robustness audit records caveated status",
        approx_equal(t1_p2_summary.get("delta_mean"), -0.0171783421, 1e-6)
        and approx_equal(t1_p2_summary.get("delta_max"), 0.0389003890, 1e-6)
        and approx_equal(t1_p2_summary.get("bootstrap_ci_high_max"), 0.0857028549, 1e-6)
        and t1_p2_summary.get("all_point_deltas_pass_one_sided") is True
        and t1_p2_summary.get("all_bootstrap_upper_bounds_pass_one_sided") is False
        and t1_p2_verdict.get("p2_leakage_signal") is False
        and t1_p2_verdict.get("p2_robust_one_sided_pass") is False,
        {
            "summary": t1_p2_summary,
            "verdict": t1_p2_verdict,
        },
    )
    t1_decomp_summary = t1_decomp.get("summary", {})
    t1_decomp_combos = t1_decomp_summary.get("combo_summary", {})
    t1_decomp_all = t1_decomp_combos.get("all", {})
    t1_decomp_et = t1_decomp_combos.get("et", {})
    v.check(
        "T1 iter34 base/item decomposition records ET-only as robustness-only candidate",
        approx_equal(t1_decomp_summary.get("all_base_baseline_ccc_mean"), 0.7088128375, 1e-6)
        and approx_equal(t1_decomp_all.get("p2_bootstrap_ci_high_max"), 0.0888889910, 1e-6)
        and approx_equal(t1_decomp_et.get("baseline_ccc_mean"), 0.7056904677, 1e-6)
        and approx_equal(t1_decomp_et.get("delta_vs_all_mean"), -0.0031223697, 1e-6)
        and approx_equal(t1_decomp_et.get("p2_delta_max"), 0.0080727207, 1e-6)
        and approx_equal(t1_decomp_et.get("p2_bootstrap_ci_high_max"), 0.0442160889, 1e-6)
        and t1_decomp_et.get("robustification_screen_pass") is True
        and t1_decomp_et.get("ceiling_promotion_screen_pass") is False
        and t1_decomp_summary.get("ceiling_promotion_candidates") == []
        and t1_decomp_summary.get("robustification_candidates") == ["et"]
        and t1_decomp_summary.get("decision") == "future_preregister_if_candidate_exists",
        {
            "all": t1_decomp_all,
            "et": t1_decomp_et,
            "ceiling_promotion_candidates": t1_decomp_summary.get("ceiling_promotion_candidates"),
            "robustification_candidates": t1_decomp_summary.get("robustification_candidates"),
            "decision": t1_decomp_summary.get("decision"),
        },
    )
    t1_iter46_vs_iter12 = t1_iter46_cmp.get("comparisons", {}).get("iter12", {})
    t1_iter46_vs_iter34 = t1_iter46_cmp.get("comparisons", {}).get("iter34", {})
    t1_iter46_verdict = t1_iter46.get("verdict", {})
    t1_iter46_cmp_verdict = t1_iter46_cmp.get("verdict", {})
    v.check(
        "T1 iter46 ET-only lockbox is recorded as negative diagnostic",
        approx_equal(t1_iter46.get("ccc"), 0.7269)
        and approx_equal(t1_iter46.get("mae"), 1.7578, 1e-3)
        and t1_iter46.get("n") == 93
        and len(t1_iter46.get("per_seed", [])) == 5
        and approx_equal(t1_iter46.get("per_seed", [{}])[0].get("ccc_iter46_et"), 0.727628, 1e-6)
        and t1_iter46_verdict.get("is_canonical_update") is False
        and t1_iter46_verdict.get("breaks_iter34_ceiling") is False
        and approx_equal(t1_iter46_vs_iter12.get("delta_new_minus_comparator"), 0.0715279131, 1e-6)
        and approx_equal(t1_iter46_vs_iter12.get("bootstrap_delta", {}).get("frac_above_zero"), 0.9388, 1e-6)
        and approx_equal(t1_iter46_vs_iter34.get("delta_new_minus_comparator"), -0.0097086737, 1e-6)
        and approx_equal(t1_iter46_vs_iter34.get("bootstrap_delta", {}).get("frac_above_zero"), 0.166, 1e-6)
        and t1_iter46_cmp_verdict.get("above_iter12_same_sids") is False
        and t1_iter46_cmp_verdict.get("above_iter34_same_sids") is False,
        {
            "metrics": {
                "ccc": t1_iter46.get("ccc"),
                "mae": t1_iter46.get("mae"),
                "n": t1_iter46.get("n"),
                "per_seed_len": len(t1_iter46.get("per_seed", [])),
            },
            "verdict": t1_iter46_verdict,
            "comparisons": {
                "iter12": t1_iter46_vs_iter12,
                "iter34": t1_iter46_vs_iter34,
                "verdict": t1_iter46_cmp_verdict,
            },
        },
    )
    t1_x4_bag = t1_x4.get("bag", {})
    t1_x4_seed_a = t1_x4.get("bootstrap_seed_A", {})
    t1_x4_seed_b = t1_x4.get("bootstrap_seed_B", {})
    v.check(
        "T1 X4 equal-weight 2-bag is recorded as strongest near-miss",
        t1_x4.get("name") == "lockbox_t1_X4_equal_weight_2bag"
        and t1_x4.get("null_mode") == "real"
        and t1_x4.get("sanity_y_nan") is False
        and t1_x4.get("n_cohort") == 92
        and approx_equal(t1_x4.get("baselines", {}).get("loocv_ccc_iter34"), 0.7170378403, 1e-6)
        and approx_equal(t1_x4_bag.get("loocv_ccc"), 0.7345218264, 1e-6)
        and approx_equal(t1_x4_bag.get("delta_ccc"), 0.0174839861, 1e-6)
        and approx_equal(t1_x4_bag.get("delta_mae"), 0.0152489308, 1e-6)
        and approx_equal(t1_x4_seed_a.get("frac_pos"), 0.91, 1e-6)
        and approx_equal(t1_x4_seed_b.get("frac_pos"), 0.9112, 1e-6)
        and approx_equal(t1_x4.get("predictor_alignment_corr_v2_v3"), 0.9375829752, 1e-6)
        and approx_equal(t1_x4.get("fivefold_screen", {}).get("mean"), 0.0226300035, 1e-6)
        and t1_x4.get("verdict_provisional") == "NEAR_MISS_PRIMARY_GATE_BOTH_SEEDS",
        {
            "path": "results/lockbox_t1_X4_equal_weight_2bag_20260516T074106Z.json",
            "bag": t1_x4_bag,
            "bootstrap_seed_A": t1_x4_seed_a,
            "bootstrap_seed_B": t1_x4_seed_b,
            "fivefold_screen": t1_x4.get("fivefold_screen"),
            "verdict": t1_x4.get("verdict_provisional"),
        },
    )
    v.check(
        "T1 X4 status audit passes and keeps near-miss non-promoted",
        t1_x4_status.get("passed") is True
        and t1_x4_status.get("decision") == "x4_near_miss_not_promoted"
        and t1_x4_status.get("goal_complete") is False
        and t1_x4_status.get("promotion_gate", {}).get("passes") is False
        and approx_equal(t1_x4_status.get("real_result", {}).get("ccc"), 0.7345218264, 1e-6)
        and approx_equal(t1_x4_status.get("real_result", {}).get("delta_ccc"), 0.0174839861, 1e-6)
        and t1_x4_status.get("hard_failures") == [],
        {
            "path": "results/t1_x4_equal_weight_2bag_status_20260516.json",
            "decision": t1_x4_status.get("decision"),
            "promotion_gate": t1_x4_status.get("promotion_gate"),
            "real_result": t1_x4_status.get("real_result"),
            "hard_failures": t1_x4_status.get("hard_failures"),
        },
    )
    v.check(
        "T1 iter37 HARNet fine-tuning pilot is recorded as negative",
        approx_equal(t1_iter37.get("mean_ccc"), 0.1324)
        and approx_equal(t1_iter37.get("mean_mae"), 2.1949, 1e-3)
        and approx_equal(t1_iter37.get("min_fold_ccc"), -0.1199, 1e-3)
        and t1_iter37.get("feasibility_gate", {}).get("gate_pass") is False,
        {
            "mean_ccc": t1_iter37.get("mean_ccc"),
            "mean_mae": t1_iter37.get("mean_mae"),
            "min_fold_ccc": t1_iter37.get("min_fold_ccc"),
            "gate": t1_iter37.get("feasibility_gate"),
        },
    )
    iter47_cells = {
        (c["cohort"], c["stage2_policy"]): c
        for c in t3_iter47.get("cells", [])
    }
    iter47_loso_cells = {
        (c["cohort"], c["stage2_policy"]): c
        for c in t3_iter47_loso.get("cells", [])
    }
    min_current = iter47_cells.get(("drop_allmissing_validrange", "stage2_current"), {})
    min_nocv = iter47_cells.get(("drop_allmissing_validrange", "stage2_no_cv"), {})
    complete_current = iter47_cells.get(("complete33_validrange", "stage2_current"), {})
    complete_nocv = iter47_cells.get(("complete33_validrange", "stage2_no_cv"), {})
    min_loso = iter47_loso_cells.get(("drop_allmissing_validrange", "stage2_current"), {})
    min_loso_nocv = iter47_loso_cells.get(("drop_allmissing_validrange", "stage2_no_cv"), {})
    complete_loso = iter47_loso_cells.get(("complete33_validrange", "stage2_current"), {})
    target_change = (min_current.get("target_change_subjects") or [{}])[0]
    invalid_raw_values = t3_iter47.get("target_audit", {}).get("invalid_raw_subitem_values", [])
    v.check(
        "T3 valid-range corrected metrics match",
        approx_equal(min_current.get("new_refit_metrics", {}).get("ccc"), 0.3784)
        and approx_equal(min_current.get("new_refit_metrics", {}).get("mae"), 7.5280, 1e-3)
        and min_current.get("n") == 95
        and approx_equal(min_nocv.get("new_refit_metrics", {}).get("ccc"), 0.3771)
        and complete_current.get("n") == 88
        and approx_equal(complete_current.get("new_refit_metrics", {}).get("ccc"), 0.4281)
        and approx_equal(complete_nocv.get("new_refit_metrics", {}).get("ccc"), 0.4010)
        and approx_equal(min_loso.get("two_way_mean_ccc"), 0.1498, 1e-4)
        and approx_equal(min_loso.get("NLS_to_WPD_mean_ccc"), 0.1937, 1e-4)
        and approx_equal(min_loso.get("WPD_to_NLS_mean_ccc"), 0.1059, 1e-4)
        and approx_equal(min_loso_nocv.get("two_way_mean_ccc"), 0.1631333333, 1e-4)
        and approx_equal(complete_loso.get("two_way_mean_ccc"), 0.1060833333, 1e-4)
        and target_change.get("sid") == "NLS036"
        and approx_equal(target_change.get("old_target"), 46.0)
        and approx_equal(target_change.get("validrange_target"), 28.0)
        and approx_equal(target_change.get("delta_old_minus_validrange"), 18.0)
        and target_change.get("valid_subitems") == 31
        and sorted((row.get("column"), row.get("value")) for row in invalid_raw_values)
        == [("MDSUPDRS_3-15-L", 9.0), ("MDSUPDRS_3-15-R", 9.0)],
        {
            "minimal_current": min_current.get("new_refit_metrics"),
            "minimal_no_cv": min_nocv.get("new_refit_metrics"),
            "complete_current": complete_current.get("new_refit_metrics"),
            "complete_no_cv": complete_nocv.get("new_refit_metrics"),
            "minimal_loso": min_loso,
            "minimal_loso_no_cv": min_loso_nocv,
            "complete_loso": complete_loso,
            "target_change": target_change,
            "invalid_raw_values": invalid_raw_values,
        },
    )
    t3_integrity_current = next(
        (
            cell
            for cell in t3_iter47_target_integrity.get("loocv_cells", [])
            if cell.get("cohort") == "drop_allmissing_validrange"
            and cell.get("stage2_policy") == "stage2_current"
        ),
        {},
    )
    t3_integrity_loso = next(
        (
            cell
            for cell in t3_iter47_target_integrity.get("loso_cells", [])
            if cell.get("cohort") == "drop_allmissing_validrange"
            and cell.get("stage2_policy") == "stage2_current"
        ),
        {},
    )
    v.check(
        "T3 iter47 target-integrity audit passes",
        t3_iter47_target_integrity.get("pass") is True
        and t3_iter47_target_integrity.get("hard_failures") == []
        and t3_iter47_target_integrity.get("warnings") == []
        and t3_iter47_target_integrity.get("target", {}).get("n_part3_columns") == 33
        and t3_iter47_target_integrity.get("cohorts", {}).get("drop_allmissing_validrange", {}).get("n") == 95
        and t3_iter47_target_integrity.get("cohorts", {}).get("complete33_validrange", {}).get("n") == 88
        and sorted(t3_iter47_target_integrity.get("cohorts", {}).get("drop_allmissing_validrange", {}).get("excluded_sids", []))
        == ["NLS151", "NLS188", "WPD013"]
        and len(t3_iter47_target_integrity.get("target", {}).get("invalid_raw_subitem_values", [])) == 2
        and len(t3_iter47_target_integrity.get("target", {}).get("target_changed_rows", [])) == 1
        and approx_equal(t3_integrity_current.get("csv_recomputed_metrics", {}).get("ccc"), 0.3784)
        and approx_equal(t3_integrity_current.get("csv_recomputed_metrics", {}).get("mae"), 7.5280, 1e-3)
        and approx_equal(t3_integrity_loso.get("two_way_mean_ccc"), 0.1498, 1e-4),
        {
            "pass": t3_iter47_target_integrity.get("pass"),
            "hard_failures": t3_iter47_target_integrity.get("hard_failures"),
            "warnings": t3_iter47_target_integrity.get("warnings"),
            "target": t3_iter47_target_integrity.get("target"),
            "cohorts": t3_iter47_target_integrity.get("cohorts"),
            "current": t3_integrity_current,
            "loso_current": t3_integrity_loso,
        },
    )
    t3_resid_overall = t3_iter47_residual_anatomy.get("overall_metrics", {})
    t3_resid_quartiles = {
        row.get("group"): row
        for row in t3_iter47_residual_anatomy.get("severity_quartile_summary", [])
    }
    t3_resid_sites = {
        row.get("group"): row
        for row in t3_iter47_residual_anatomy.get("site_summary", [])
    }
    t3_resid_top = (
        t3_iter47_residual_anatomy.get("global_diagnostic_feature_correlations", [{}])[0]
        if t3_iter47_residual_anatomy.get("global_diagnostic_feature_correlations")
        else {}
    )
    v.check(
        "T3 iter47 residual-anatomy audit is diagnostic-only and current-target",
        t3_iter47_residual_anatomy.get("script") == "audit_t3_iter47_residual_anatomy.py"
        and t3_iter47_residual_anatomy.get("scope") == "diagnostic_only_no_model_selection"
        and t3_iter47_residual_anatomy.get("decision", {}).get("no_model_promotion") is True
        and t3_iter47_residual_anatomy.get("decision", {}).get("no_new_loocv") is True
        and t3_iter47_residual_anatomy.get("cohort", {}).get("name") == "drop_allmissing_validrange"
        and t3_iter47_residual_anatomy.get("cohort", {}).get("stage2_policy") == "stage2_current"
        and t3_iter47_residual_anatomy.get("cohort", {}).get("n") == 95
        and approx_equal(t3_resid_overall.get("ccc"), 0.3784)
        and approx_equal(t3_resid_overall.get("mae"), 7.5280, 1e-3)
        and approx_equal(t3_resid_overall.get("cal_slope_pred_on_true"), 0.2692)
        and approx_equal(t3_resid_overall.get("residual_corr_with_true"), -0.7771)
        and approx_equal(t3_resid_quartiles.get("Q1_low", {}).get("mean_residual_pred_minus_true"), 10.0243, 1e-3)
        and approx_equal(t3_resid_quartiles.get("Q4_high", {}).get("mean_residual_pred_minus_true"), -9.1984, 1e-3)
        and approx_equal(t3_resid_sites.get("WPD", {}).get("ccc"), 0.0515)
        and t3_resid_top.get("feature") == "fq_R_Wris_dw5"
        and approx_equal(t3_resid_top.get("abs_corr_with_residual"), 0.2899, 1e-3)
        and "global post-hoc diagnostics" in t3_iter47_residual_anatomy_md
        and "must not be used as a headline or lockbox gate" in t3_iter47_residual_anatomy_md,
        {
            "cohort": t3_iter47_residual_anatomy.get("cohort"),
            "overall": t3_resid_overall,
            "quartiles": t3_resid_quartiles,
            "sites": t3_resid_sites,
            "top_feature": t3_resid_top,
            "decision": t3_iter47_residual_anatomy.get("decision"),
        },
    )
    t3_rescale_methods = t3_iter47_ccc_rescale.get("methods", {})
    t3_rescale_base = t3_rescale_methods.get("base_iter47_current", {}).get("metrics", {})
    t3_rescale_variance = t3_rescale_methods.get("oof_level_leave_one_variance_match", {})
    t3_rescale_variance_metrics = t3_rescale_variance.get("metrics", {})
    t3_rescale_variance_boot = t3_rescale_variance.get("paired_bootstrap_vs_base", {})
    t3_rescale_affine = t3_rescale_methods.get("oof_level_leave_one_affine_y_on_pred", {})
    t3_rescale_affine_metrics = t3_rescale_affine.get("metrics", {})
    v.check(
        "T3 iter47 CCC-rescale sanity is diagnostic-only and non-reportable",
        t3_iter47_ccc_rescale.get("script") == "audit_t3_iter47_ccc_rescale_sanity.py"
        and t3_iter47_ccc_rescale.get("scope") == "diagnostic_only_not_reportable_model"
        and t3_iter47_ccc_rescale.get("cohort", {}).get("name") == "drop_allmissing_validrange"
        and t3_iter47_ccc_rescale.get("cohort", {}).get("stage2_policy") == "stage2_current"
        and t3_iter47_ccc_rescale.get("cohort", {}).get("n") == 95
        and t3_iter47_ccc_rescale.get("methodology_guardrail", {}).get("not_fully_nested") is True
        and t3_iter47_ccc_rescale.get("decision", {}).get("no_model_promotion") is True
        and t3_iter47_ccc_rescale.get("decision", {}).get("no_new_loocv") is True
        and approx_equal(t3_rescale_base.get("ccc"), 0.3784)
        and approx_equal(t3_rescale_base.get("mae"), 7.5280, 1e-3)
        and approx_equal(t3_rescale_affine_metrics.get("ccc"), 0.2572)
        and approx_equal(t3_rescale_variance_metrics.get("ccc"), 0.3996)
        and approx_equal(t3_rescale_variance_metrics.get("mae"), 8.6671, 1e-3)
        and approx_equal(t3_rescale_variance_boot.get("ccc_delta_mean"), 0.0208)
        and (t3_rescale_variance_boot.get("ccc_delta_ci95") or [1, -1])[0] < 0 < (t3_rescale_variance_boot.get("ccc_delta_ci95") or [1, -1])[1]
        and approx_equal(t3_rescale_variance_boot.get("mae_delta_mean"), 1.1398, 1e-3)
        and (t3_rescale_variance_boot.get("mae_delta_ci95") or [-1, -1])[0] > 0
        and "not a reportable model" in t3_iter47_ccc_rescale_md
        and "fully nested outer/inner prediction artifact" in t3_iter47_ccc_rescale_md,
        {
            "cohort": t3_iter47_ccc_rescale.get("cohort"),
            "methodology_guardrail": t3_iter47_ccc_rescale.get("methodology_guardrail"),
            "decision": t3_iter47_ccc_rescale.get("decision"),
            "base": t3_rescale_base,
            "affine": t3_rescale_affine_metrics,
            "variance_match": t3_rescale_variance_metrics,
            "variance_bootstrap_vs_base": t3_rescale_variance_boot,
        },
    )
    influence_t3 = headline_influence.get("audits", {}).get("t3_iter47_validrange_current", {})
    influence_t1 = headline_influence.get("audits", {}).get("t1_iter34_hybrid_candidate", {})
    influence_t3_jack = influence_t3.get("jackknife", {})
    influence_t3_conc = influence_t3.get("influence_concentration", {})
    influence_t3_corr = influence_t3.get("influence_correlations", {})
    influence_t1_matched = headline_influence.get("matched_t1_iter34_vs_iter12", {})
    domain_rows = {row.get("domain"): row for row in t3_domain_residual.get("domain_summary", [])}
    domain_unobs = domain_rows.get("unobservable_non_gait", {})
    domain_upper = domain_rows.get("upper_limb_brady_4_6", {})
    domain_appendicular = domain_rows.get("appendicular_brady_4_8_14", {})
    domain_gait = domain_rows.get("gait_balance_7_14", {})
    domain_multi = t3_domain_residual.get("multidomain_ridge10_privileged_oracle", {})
    item_top_residual = (t3_item_residual.get("top_items_by_abs_residual_corr") or [{}])[0]
    item_top_oracle = (t3_item_residual.get("top_items_by_privileged_oracle_delta_ccc") or [{}])[0]
    item_observable = t3_item_residual.get("observable_vs_unobservable_summary", {})
    v.check(
        "Current headline influence audit is diagnostic-only and no single-subject redline",
        headline_influence.get("script") == "audit_current_headline_influence.py"
        and headline_influence.get("decision", {}).get("scope") == "diagnostic_only_no_model_selection"
        and headline_influence.get("decision", {}).get("no_model_promotion") is True
        and headline_influence.get("decision", {}).get("no_new_loocv") is True
        and headline_influence.get("decision", {}).get("redline_summary", {}).get("single_subject_redline_hit") is False
        and headline_influence.get("decision", {}).get("redline_summary", {}).get("top5_share_redline_hit") is False
        and headline_influence.get("decision", {}).get("redline_summary", {}).get("tail_leverage_warning") is True
        and approx_equal(influence_t3.get("baseline_metrics", {}).get("ccc"), 0.3784)
        and approx_equal(influence_t3_jack.get("ccc_without_min"), 0.3402)
        and approx_equal(influence_t3_jack.get("ccc_without_max"), 0.4056)
        and approx_equal(influence_t3_conc.get("top1_abs_delta_ccc"), 0.0381)
        and approx_equal(influence_t3_conc.get("top5_fraction_of_sum_abs_delta"), 0.2840)
        and approx_equal(influence_t3_conc.get("gini_abs_delta_ccc"), 0.6009)
        and approx_equal(influence_t3_corr.get("abs_target_minus_median_vs_abs_delta_ccc"), 0.6779)
        and approx_equal(influence_t1.get("baseline_metrics", {}).get("ccc"), 0.7366)
        and approx_equal(influence_t1_matched.get("base_delta_iter34_minus_iter12"), 0.0812)
        and approx_equal(influence_t1_matched.get("leave_one_delta_min"), 0.0629)
        and influence_t1_matched.get("comparison_sign_flips") is False
        and influence_t1_matched.get("iter34_leave_one_below_iter12_canonical_0_6550") is False
        and "not a filtering rule" in headline_influence_md,
        {
            "decision": headline_influence.get("decision"),
            "t3_baseline": influence_t3.get("baseline_metrics"),
            "t3_jackknife": influence_t3_jack,
            "t3_concentration": influence_t3_conc,
            "t3_correlations": influence_t3_corr,
            "t1_matched": influence_t1_matched,
        },
    )
    v.check(
        "T3 iter47 domain residual audit is diagnostic-only and privileged",
        t3_domain_residual.get("script") == "audit_t3_iter47_domain_residuals.py"
        and t3_domain_residual.get("decision", {}).get("scope") == "diagnostic_only_privileged_ground_truth_domains"
        and t3_domain_residual.get("decision", {}).get("no_model_promotion") is True
        and t3_domain_residual.get("decision", {}).get("no_new_loocv") is True
        and t3_domain_residual.get("decision", {}).get("no_subject_filtering") is True
        and t3_domain_residual.get("guardrails", {}).get("clinical_domain_labels_are_ground_truth") is True
        and t3_domain_residual.get("guardrails", {}).get("oracle_corrections_are_privileged_and_non_deployable") is True
        and approx_equal(t3_domain_residual.get("guardrails", {}).get("parsed_total_max_abs_diff_vs_iter47_target"), 0.0)
        and approx_equal(t3_domain_residual.get("baseline_metrics", {}).get("ccc"), 0.3784)
        and t3_domain_residual.get("baseline_metrics", {}).get("n") == 95
        and approx_equal(domain_unobs.get("corr_domain_with_residual_pred_minus_true"), -0.8004)
        and approx_equal(domain_unobs.get("oracle_delta_ccc_vs_base"), 0.4716)
        and approx_equal(domain_upper.get("corr_domain_with_residual_pred_minus_true"), -0.6224)
        and approx_equal(domain_upper.get("oracle_delta_ccc_vs_base"), 0.3372)
        and approx_equal(domain_appendicular.get("corr_domain_with_residual_pred_minus_true"), -0.6156)
        and approx_equal(domain_gait.get("oracle_delta_ccc_vs_base"), 0.2083)
        and approx_equal(domain_multi.get("metrics", {}).get("ccc"), 0.8533)
        and approx_equal(domain_multi.get("delta_ccc_vs_base"), 0.4749)
        and "non-deployable" in t3_domain_residual_md
        and "true Part III domain labels" in t3_domain_residual_md,
        {
            "guardrails": t3_domain_residual.get("guardrails"),
            "decision": t3_domain_residual.get("decision"),
            "unobservable_non_gait": domain_unobs,
            "upper_limb_brady": domain_upper,
            "appendicular_brady": domain_appendicular,
            "gait_balance": domain_gait,
            "multidomain_oracle": domain_multi,
        },
    )
    v.check(
        "T3 iter47 item-level residual audit is diagnostic-only stop-rule evidence",
        t3_item_residual.get("script") == "audit_t3_iter47_item_residuals.py"
        and t3_item_residual.get("scope") == "diagnostic_only_saved_oof_no_model_selection_no_prereg_no_loocv"
        and t3_item_residual.get("decision", {}).get("no_model_promotion") is True
        and t3_item_residual.get("decision", {}).get("ceiling_broken") is False
        and approx_equal(t3_item_residual.get("target_reconstruction", {}).get("max_abs_parsed_total_minus_iter47_target"), 0.0)
        and approx_equal(t3_item_residual.get("base_metrics", {}).get("ccc"), 0.3784)
        and approx_equal(t3_item_residual.get("base_metrics", {}).get("residual_corr_with_true"), -0.7771)
        and item_top_residual.get("item") == 6
        and item_top_residual.get("weargait_observable") is False
        and approx_equal(item_top_residual.get("corr_item_with_residual_pred_minus_true"), -0.5705)
        and approx_equal(item_top_residual.get("loo_privileged_oracle", {}).get("delta_ccc_vs_base"), 0.2817)
        and item_top_oracle.get("item") == 6
        and approx_equal(item_observable.get("mean_abs_residual_corr_observable"), 0.2470)
        and approx_equal(item_observable.get("mean_abs_residual_corr_unobservable"), 0.3712)
        and approx_equal(item_observable.get("best_observable_oracle_delta_ccc"), 0.1485)
        and approx_equal(item_observable.get("best_unobservable_oracle_delta_ccc"), 0.2817)
        and "non-deployable" in t3_item_residual_md
        and "No model promotion" in t3_item_residual_md,
        {
            "scope": t3_item_residual.get("scope"),
            "decision": t3_item_residual.get("decision"),
            "target_reconstruction": t3_item_residual.get("target_reconstruction"),
            "base_metrics": t3_item_residual.get("base_metrics"),
            "top_residual_item": item_top_residual,
            "top_oracle_item": item_top_oracle,
            "observable_summary": item_observable,
        },
    )
    v.check(
        "T3 target audit records all-missing zero-label bug and hidden cv columns",
        t3_audit.get("target_summary", {}).get("feature_vs_raw33", {}).get("max_abs_diff") == 0.0
        and t3_audit.get("target_summary", {}).get("missing_raw_part3_subitems_among_v2_pd", {}).get("max_missing") == 33
        and t3_audit.get("target_summary", {}).get("missing_raw_part3_subitems_among_v2_pd", {}).get("subjects_with_any_missing") == 9
        and set(t3_audit.get("stage2_covariate_summary", {}).get("stage2_current_cv_columns", [])) == {"cv_age", "cv_dbs", "cv_ht", "cv_sex", "cv_wt", "cv_yrs"},
        {
            "target_summary": t3_audit.get("target_summary"),
            "stage2_cv": t3_audit.get("stage2_covariate_summary", {}).get("stage2_current_cv_columns"),
        },
    )
    iter42_cells = {
        (c["cohort"], c["stage2_policy"]): c
        for c in t3_iter42.get("cells", [])
    }
    iter42_loso_cells = {
        (c["cohort"], c["stage2_policy"]): c
        for c in t3_iter42_loso.get("cells", [])
    }
    iter42_le3_current = iter42_cells.get(("prorate_le3", "stage2_current"), {})
    iter42_le3_nocv = iter42_cells.get(("prorate_le3", "stage2_no_cv"), {})
    iter42_le7_current = iter42_cells.get(("prorate_le7", "stage2_current"), {})
    iter42_le7_nocv = iter42_cells.get(("prorate_le7", "stage2_no_cv"), {})
    iter42_le3_loso = iter42_loso_cells.get(("prorate_le3", "stage2_current"), {})
    iter42_le7_loso = iter42_loso_cells.get(("prorate_le7", "stage2_current"), {})
    v.check(
        "T3 iter42 proration audit records primary failure and loose sensitivity",
        approx_equal(iter42_le3_current.get("new_refit_metrics", {}).get("ccc"), 0.3468)
        and approx_equal(iter42_le3_nocv.get("new_refit_metrics", {}).get("ccc"), 0.3643)
        and approx_equal(iter42_le7_current.get("new_refit_metrics", {}).get("ccc"), 0.4165)
        and approx_equal(iter42_le7_nocv.get("new_refit_metrics", {}).get("ccc"), 0.3793)
        and approx_equal(iter42_le3_loso.get("two_way_mean_ccc"), 0.1439, 1e-4)
        and approx_equal(iter42_le7_loso.get("two_way_mean_ccc"), 0.1906, 1e-4),
        {
            "le3_current": iter42_le3_current.get("new_refit_metrics"),
            "le3_no_cv": iter42_le3_nocv.get("new_refit_metrics"),
            "le7_current": iter42_le7_current.get("new_refit_metrics"),
            "le7_no_cv": iter42_le7_nocv.get("new_refit_metrics"),
            "le3_loso": iter42_le3_loso,
            "le7_loso": iter42_le7_loso,
        },
    )
    clinical_rows = {
        row["stage1_policy"]: row
        for row in t3_clinical.get("policy_rows", [])
    }
    clinical_comparisons = t3_clinical.get("comparisons_vs_a3_hy_cv", {})
    clinical_verdict = t3_clinical.get("verdict", {})
    v.check(
        "T3 clinical-dependency audit records clinical/intake plus IMU framing",
        t3_clinical.get("n") == 95
        and t3_clinical.get("stage2_policy") == "stage2_no_cv"
        and approx_equal(clinical_rows.get("a3_hy_cv", {}).get("mean_prediction_metrics", {}).get("ccc"), 0.4017)
        and approx_equal(clinical_rows.get("cv_only", {}).get("mean_prediction_metrics", {}).get("ccc"), 0.3871)
        and approx_equal(clinical_rows.get("hy_only", {}).get("mean_prediction_metrics", {}).get("ccc"), 0.2899)
        and approx_equal(clinical_rows.get("intercept_only", {}).get("mean_prediction_metrics", {}).get("ccc"), 0.2449)
        and approx_equal(clinical_rows.get("a3_hy_cv", {}).get("mean_stage1_only_metrics", {}).get("ccc"), 0.3369)
        and approx_equal(clinical_rows.get("intercept_only", {}).get("mean_stage1_only_metrics", {}).get("ccc"), -0.0213)
        and approx_equal(clinical_comparisons.get("a3_hy_cv_minus_cv_only", {}).get("delta_mean"), 0.0136163360, 1e-6)
        and clinical_comparisons.get("a3_hy_cv_minus_cv_only", {}).get("ci_low", 1.0) < 0.0
        and clinical_comparisons.get("a3_hy_cv_minus_cv_only", {}).get("ci_high", -1.0) > 0.0
        and approx_equal(clinical_comparisons.get("a3_hy_cv_minus_intercept_only", {}).get("delta_mean"), 0.1519051580, 1e-6)
        and clinical_verdict.get("canonical_t3_changed") is False,
        {
            "policy_rows": {
                key: {
                    "full": row.get("mean_prediction_metrics"),
                    "stage1_only": row.get("mean_stage1_only_metrics"),
                }
                for key, row in clinical_rows.items()
            },
            "comparisons": clinical_comparisons,
            "verdict": clinical_verdict,
        },
    )
    v.check(
        "historical T3 sit-with-data summary matches old target-contaminated tail-shrinkage finding",
        approx_equal(t3_deep.get("residual_corr_with_true"), -0.698731305814378, 1e-6)
        and approx_equal(t3_deep["loso"].get("two_way_mean"), 0.341, 1e-6),
        {"residual_corr_with_true": t3_deep.get("residual_corr_with_true"), "loso": t3_deep.get("loso")},
    )
    v.check(
        "historical T3 LOSO artifact matches old target-contaminated transportability number",
        approx_equal(t3_site["loso"].get("two_way_mean"), 0.341, 1e-6),
        {"loso_two_way": t3_site["loso"].get("two_way_mean")},
    )
    v.check(
        "T3 iter38 FoG-STAR Stage-1 augmentation screen is recorded as negative",
        approx_equal(t3_iter38.get("baseline_seed_mean", {}).get("ccc"), 0.4888)
        and approx_equal(t3_iter38.get("augmented_seed_mean", {}).get("ccc"), 0.4896)
        and approx_equal(t3_iter38.get("delta_seed_mean_predictions"), 0.0008)
        and t3_iter38.get("gate", {}).get("pass") is False
        and t3_iter38.get("decision") == "screen_fail_no_lockbox_no_canonical_change",
        {
            "baseline": t3_iter38.get("baseline_seed_mean"),
            "augmented": t3_iter38.get("augmented_seed_mean"),
            "delta": t3_iter38.get("delta_seed_mean_predictions"),
            "gate": t3_iter38.get("gate"),
            "decision": t3_iter38.get("decision"),
        },
    )
    v.check(
        "T3 iter39 FoG-STAR zero-shot is recorded as partial external validity only",
        approx_equal(t3_iter39.get("track_a_wg_wrist_direct", {}).get("ccc"), -0.0180)
        and approx_equal(t3_iter39.get("track_b_iter5_style_clinical_plus_wrist", {}).get("ccc"), 0.2499)
        and approx_equal(t3_iter39.get("track_c_fogstar_only_loo_sanity", {}).get("ccc"), 0.0821)
        and t3_iter39.get("decision") == "zero_shot_external_validation_only_no_internal_canonical_change",
        {
            "track_a": t3_iter39.get("track_a_wg_wrist_direct"),
            "track_b": t3_iter39.get("track_b_iter5_style_clinical_plus_wrist"),
            "track_c": t3_iter39.get("track_c_fogstar_only_loo_sanity"),
            "decision": t3_iter39.get("decision"),
        },
    )
    v.check(
        "T3 iter40 local-residual wildcard is recorded as negative",
        approx_equal(t3_iter40.get("baseline_metrics_seed_mean", {}).get("ccc"), 0.4888)
        and approx_equal(t3_iter40.get("wildcard_metrics_seed_mean", {}).get("ccc"), 0.4332)
        and approx_equal(t3_iter40.get("seed_mean_delta_ccc"), -0.0556)
        and t3_iter40.get("promotion_gate", {}).get("strict_t3_gate_pass") is False
        and t3_iter40.get("promotion_gate", {}).get("relaxed_gate_pass") is False,
        {
            "baseline": t3_iter40.get("baseline_metrics_seed_mean"),
            "wildcard": t3_iter40.get("wildcard_metrics_seed_mean"),
            "delta": t3_iter40.get("seed_mean_delta_ccc"),
            "gate": t3_iter40.get("promotion_gate"),
            "bootstrap": t3_iter40.get("bootstrap_delta"),
        },
    )
    iter50_metrics = t3_iter50.get("mean_metrics", {})
    iter50_gate = t3_iter50.get("gate", {})
    iter50_boot = t3_iter50.get("bootstrap_nested_convex_minus_baseline", {})
    iter50_alpha = t3_iter50.get("alpha_summary", {})
    v.check(
        "T3 iter50 low-degree nested convex mix is recorded as negative",
        t3_iter50.get("script") == "run_t3_iter50_lowdf_convex.py"
        and t3_iter50.get("formula_sha256") == t3_iter50_prereg.get("formula_sha256")
        and t3_iter50.get("cohort", {}).get("n") == 95
        and approx_equal(iter50_metrics.get("baseline_seq_current", {}).get("ccc"), 0.3759)
        and approx_equal(iter50_metrics.get("clinical_only", {}).get("ccc"), 0.3068)
        and approx_equal(iter50_metrics.get("imu_only_no_cv", {}).get("ccc"), 0.2322)
        and approx_equal(iter50_metrics.get("nested_convex", {}).get("ccc"), 0.3083)
        and iter50_gate.get("strict_t3_gate_pass") is False
        and approx_equal(iter50_gate.get("delta_seed_mean_predictions"), -0.0675638436, 1e-6)
        and approx_equal(iter50_gate.get("seed_delta_std"), 0.0319018808, 1e-6)
        and approx_equal(iter50_boot.get("frac_gt_0"), 0.0348, 1e-6)
        and iter50_alpha.get("min") == 0.0
        and iter50_alpha.get("max") == 1.0
        and float(iter50_alpha.get("std", 0.0)) > 0.4
        and t3_iter50.get("decision") == "screen_fail_no_loocv_no_canonical_change",
        {
            "formula_sha256": t3_iter50.get("formula_sha256"),
            "mean_metrics": iter50_metrics,
            "gate": iter50_gate,
            "bootstrap": iter50_boot,
            "alpha_summary": iter50_alpha,
            "decision": t3_iter50.get("decision"),
        },
    )
    cops_listing = t3_iter49_probe.get("sample_zip", {}).get("zip_listing", {})
    cops_nested = cops_listing.get("nested_accelerometry_preview", {}) or {}
    cops_updrs_previews = cops_listing.get("updrs_csv_previews", {})
    cops_off = t3_iter49.get("metrics", {}).get("off_primary", {})
    cops_track_a = cops_off.get("track_a_right_wrist_direct", {})
    cops_track_b = cops_off.get("track_b_right_clinical_plus_wrist", {})
    cops_track_c = cops_off.get("track_c_cops_only_loo_sanity", {})
    cops_track_d = cops_off.get("track_d_bilateral_clinical_plus_wrist", {})
    cops_scale = t3_iter49.get("scale_checks", {})
    v.check(
        "T3 iter49 COPS zero-shot is recorded as partial external validity only",
        t3_iter49_prereg.get("formula_sha256") == t3_iter49_probe.get("preregistration_formula_sha256")
        and t3_iter49_prereg.get("formula_sha256") == t3_iter49.get("preregistration_formula_sha256")
        and t3_iter49_probe.get("decision", {}).get("cops_is_new_external_route") is True
        and t3_iter49_probe.get("decision", {}).get("not_an_internal_t3_update") is True
        and t3_iter49_probe.get("data_summary", {}).get("n_zip_files") == 66
        and 47.0 <= (float(t3_iter49_probe.get("data_summary", {}).get("total_zip_size_bytes", 0)) / 1e9) <= 49.0
        and t3_iter49_probe.get("demographics", {}).get("n_rows") == 66
        and t3_iter49.get("n_weargait_train") == 95
        and t3_iter49.get("n_cops_rows_total") == 64
        and t3_iter49.get("n_cops_off_labeled") == 62
        and t3_iter49.get("n_common_magnitude_features") == 60
        and t3_iter49.get("decision") == "external_zero_shot_only_no_internal_t3_canonical_change"
        and approx_equal(cops_scale.get("cops_right_raw_mag_mean_mps2_mean"), 9.8735, 5e-4)
        and approx_equal(cops_scale.get("cops_left_raw_mag_mean_mps2_mean"), 9.8573, 5e-4)
        and approx_equal(cops_track_a.get("ccc"), -0.0193)
        and approx_equal(cops_track_b.get("ccc"), 0.2412)
        and approx_equal(cops_track_d.get("ccc"), 0.2535)
        and approx_equal(cops_track_c.get("ccc"), 0.31)
        and approx_equal(cops_track_b.get("ccc_ci95", [None, None])[0], 0.1061)
        and approx_equal(cops_track_b.get("ccc_ci95", [None, None])[1], 0.3916)
        and "COPS-11/COPS-11_UPDRS_OFF.csv" in cops_updrs_previews
        and "COPS-11/COPS-11_UPDRS_ON.csv" in cops_updrs_previews
        and "TotalScore" in cops_updrs_previews.get("COPS-11/COPS-11_UPDRS_OFF.csv", {}).get("header", "")
        and cops_nested.get("header") == "Time;X;Y;Z;Photo;Temp",
        {
            "formula_sha256": t3_iter49.get("preregistration_formula_sha256"),
            "n_zip_files": t3_iter49_probe.get("data_summary", {}).get("n_zip_files"),
            "total_zip_size_gb": float(t3_iter49_probe.get("data_summary", {}).get("total_zip_size_bytes", 0)) / 1e9,
            "demographics_rows": t3_iter49_probe.get("demographics", {}).get("n_rows"),
            "n_weargait_train": t3_iter49.get("n_weargait_train"),
            "n_cops_rows_total": t3_iter49.get("n_cops_rows_total"),
            "n_cops_off_labeled": t3_iter49.get("n_cops_off_labeled"),
            "scale_checks": cops_scale,
            "track_a": cops_track_a,
            "track_b": cops_track_b,
            "track_c": cops_track_c,
            "track_d": cops_track_d,
            "updrs_previews": list(cops_updrs_previews),
            "nested_accelerometry_preview": cops_nested,
            "decision": t3_iter49.get("decision"),
        },
    )
    pdfe_tracks = pdfe_iter52.get("tracks", {})
    pdfe_track_a = pdfe_tracks.get("track_a_primary_wg_shank_to_pdfe", {})
    pdfe_track_b = pdfe_tracks.get("track_b_clinical_plus_shank", {})
    pdfe_track_c = pdfe_tracks.get("track_c_pdfe_only_loocv_sanity", {})
    v.check(
        "T3 iter52 PDFE turning zero-shot is recorded as external validity only",
        pdfe_prereg.get("formula_sha256") == "f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2"
        and pdfe_iter52.get("formula_sha256") == pdfe_prereg.get("formula_sha256")
        and pdfe_probe.get("decision") == "direct_public_external_t3_route_for_zero_shot_only"
        and pdfe_probe.get("n_session1_targets") == 35
        and pdfe_feature_manifest.get("n_subjects") == 35
        and pdfe_feature_manifest.get("leakage_status") == "external_dataset_feature_cache_not_for_internal_headline"
        and pdfe_iter52.get("policy", {}).get("internal_t3_canonical_update_allowed") is False
        and pdfe_iter52.get("n_weargait_train") == 95
        and pdfe_iter52.get("n_pdfe") == 35
        and pdfe_iter52.get("n_common_magnitude_features") == 54
        and approx_equal(pdfe_track_a.get("ccc"), -0.1008)
        and approx_equal(pdfe_track_a.get("ccc_bootstrap", {}).get("ci95_low"), -0.2877)
        and approx_equal(pdfe_track_a.get("ccc_bootstrap", {}).get("ci95_high"), 0.0554)
        and approx_equal(pdfe_track_b.get("ccc"), 0.1340)
        and approx_equal(pdfe_track_b.get("ccc_bootstrap", {}).get("ci95_low"), -0.0426)
        and approx_equal(pdfe_track_b.get("ccc_bootstrap", {}).get("ci95_high"), 0.3369)
        and approx_equal(pdfe_track_c.get("ccc"), 0.4020)
        and approx_equal(pdfe_track_c.get("ccc_bootstrap", {}).get("ci95_low"), 0.1569)
        and approx_equal(pdfe_track_c.get("ccc_bootstrap", {}).get("ci95_high"), 0.6519),
        {
            "formula_sha256": pdfe_iter52.get("formula_sha256"),
            "probe": pdfe_probe,
            "feature_manifest": {
                "n_subjects": pdfe_feature_manifest.get("n_subjects"),
                "leakage_status": pdfe_feature_manifest.get("leakage_status"),
            },
            "n_weargait_train": pdfe_iter52.get("n_weargait_train"),
            "n_pdfe": pdfe_iter52.get("n_pdfe"),
            "n_common_magnitude_features": pdfe_iter52.get("n_common_magnitude_features"),
            "track_a": pdfe_track_a,
            "track_b": pdfe_track_b,
            "track_c": pdfe_track_c,
            "policy": pdfe_iter52.get("policy"),
        },
    )
    conf_models = current_conformal.get("models", {})
    conf_t1_iter12 = conf_models.get("t1_iter12_honest", {})
    conf_t1_iter34 = conf_models.get("t1_iter34_hybrid", {})
    conf_t3_current = conf_models.get("t3_iter47_stage2_current", {})
    conf_t3_nocv = conf_models.get("t3_iter47_stage2_no_cv", {})
    v.check(
        "current conformal and abstention report covers post-audit T1/T3 OOFs",
        current_conformal.get("method", {}).get("model_refit") is False
        and current_conformal.get("method", {}).get("new_hyperparameter_tuning") is False
        and approx_equal(conf_t1_iter12.get("base_ccc"), 0.6550)
        and approx_equal(conf_t1_iter12.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 4.9923, 1e-3)
        and approx_equal(conf_t1_iter12.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 9.0785, 1e-3)
        and approx_equal(conf_t1_iter34.get("base_ccc"), 0.7366)
        and approx_equal(conf_t1_iter34.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 5.7408, 1e-3)
        and approx_equal(conf_t1_iter34.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 8.8126, 1e-3)
        and approx_equal(conf_t3_current.get("base_ccc"), 0.3784)
        and approx_equal(conf_t3_current.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 25.9414, 1e-3)
        and approx_equal(conf_t3_current.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 34.7241, 1e-3)
        and approx_equal(conf_t3_current.get("abstention_at_50pct_discard", {}).get("prediction_tail_distance_ccc"), 0.0108, 1e-3)
        and approx_equal(conf_t3_nocv.get("base_ccc"), 0.3771)
        and approx_equal(conf_t3_nocv.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 35.3452, 1e-3)
        and current_conformal.get("verdict") == "intervals_are_wide_and_deployable_abstention_does_not_break_t3_or_canonicalize_t1",
        {
            "method": current_conformal.get("method"),
            "t1_iter12": conf_t1_iter12,
            "t1_iter34": conf_t1_iter34,
            "t3_current": conf_t3_current,
            "t3_nocv": conf_t3_nocv,
            "verdict": current_conformal.get("verdict"),
        },
    )

    dashboard_manifest = load_json(RESULTS / "current_best_pipeline_dashboard" / "manifest.json")
    current_paper_manifest = load_json(RESULTS / "current_paper_export" / "manifest.json")
    v.check(
        "dashboard manifest has no missing artifacts",
        len(dashboard_manifest.get("artifacts", [])) >= 25
        and not [a for a in dashboard_manifest.get("artifacts", []) if not a.get("exists")],
        {
            "artifact_count": len(dashboard_manifest.get("artifacts", [])),
            "missing": [a["path"] for a in dashboard_manifest.get("artifacts", []) if not a.get("exists")],
        },
    )
    v.check(
        "dashboard manifest repeats not-complete verdict",
        dashboard_manifest.get("completion_verdict") == "not_complete_t3_validrange_ceiling_unbroken_and_hssayeni_dua_blocked",
        {"completion_verdict": dashboard_manifest.get("completion_verdict")},
    )
    v.check(
        "current paper export validation passed",
        current_paper_manifest.get("status") == "passed" and current_paper_manifest.get("validation_issues") == [],
        {"status": current_paper_manifest.get("status"), "validation_issues": current_paper_manifest.get("validation_issues")},
    )
    forbidden_stale = [
        "SSL ranking achieves CCC",
        "T1 CCC&nbsp;=&nbsp;0.868",
        "T3 CCC&nbsp;=&nbsp;0.776",
        "Ordinal ranking also improves broader targets",
    ]
    v.check(
        "current paper export lacks known stale SSL-ranking phrases",
        not any(s in current_paper for s in forbidden_stale),
        {"forbidden": forbidden_stale},
    )
    required_current_paper_snippets = [
        "0.3784",
        "0.150",
        "target-contaminated",
        "valid-range",
        "clinical/intake",
        "0.2449",
        "25.94",
        "34.72",
        "0.3766",
        "not fold-local",
        "ablation_v3_features.csv",
        "not to synthesize a clean manifest",
        "four reusable cache artifacts as complete-clean",
        "companion item11_multiscale_recordings.csv",
        "cache-consumer guard audit",
        "four current safe-cache consumers",
        "53 model/composer scripts remain diagnostic-only",
        "transitive/runtime cache dependency audits",
        "only diagnostic/partial cache opened at runtime is results/ablation_v3_features.csv",
        "missing-manifest origin audit covers 33 still-missing sidecars",
        "does not make any artifact headline-safe by itself",
        "Direct cache-consumer guard status is therefore not enough",
        "headline metric recompute audit",
        "CCC metric integrity audit",
        "Lin's population-moment convention",
        "OOF artifact integrity audit",
        "pre-registration temporal integrity audit",
        "pre-audit claim labeling audit",
        "Historical pre-audit subdomain prediction",
        "Historical pre-audit sensor ablation",
        "T1 candidate claim",
        "reportable artifact flag audit",
        "archived raw lockbox booleans are not current claim policy",
        "is_canonical_update = true",
        "RegressorChain(order=\"random\")",
        "delta = -0.0008",
        "auxiliary-label/order caveat",
        "per-item evidence",
        "per-item OOF companion scope audit",
        "T1 iter12 batch-integrity audit",
        "max summed-OOF difference 0.0",
        "T3 iter47 target-integrity audit",
        "External result claim labeling audit",
        "external-only numbers cannot update the internal T3 headline",
        "subject-CSV recomputed CCC = 0.3784",
        "LOSO-row recomputed two-way CCC = 0.1498",
        "residual corr = -0.7771",
        "WPD within-site CCC = 0.0515",
        "top post-hoc residual-feature |r| = 0.290",
        "OOF-level variance matching raises CCC to 0.3996",
        "MAE worsens by +1.1398",
        "not a fully nested meta-model",
        "T3 max absolute leave-one CCC delta is 0.0381",
        "T1 iter34-minus-iter12 matched delta stays positive",
        "influence remains severity-tail concentrated",
        "unobservable non-gait burden has residual r = -0.8004",
        "multidomain Ridge oracle reaches CCC = 0.8533",
        "require true Part III domain labels at prediction time",
        "item-level companion audit",
        "item 6 pronation/supination",
        "best gait/balance-observable items",
        "Mean |r(item,residual)| is 0.247",
        "no valid next WearGait-only model route to break T3 CCC",
        "Historical Pre-Audit Seed Stability",
        "iter50 low-degree convex mix",
        "nested-convex CCC",
        "0.3083",
        "TLVMC/DeFOG as another public direct T3 route",
        "137 medication-matched recordings across 45 subjects",
        "iter51 zero-shot result",
        "Track A lower-back magnitude CCC = +0.2695",
        "95% CI [+0.1693, +0.3600]",
        "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd",
        "PDFE turning-in-place refresh",
        "Track A WearGait shank-to-PDFE CCC = -0.101",
        "PDFE-only LOOCV sanity reaches CCC = +0.402",
        "f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2",
        "Harmonized Upper/Lower Limb Accelerometry",
        "daily-life ActiGraph summaries",
        "Monipar and BIOCLITE are public consumer-smartwatch exercise datasets",
        "neither can form the full T1 9-14 composite",
        "Zenodo 14848598 is also public",
        "derived CSF/clinical/gait-summary benchmark table",
        "advanced Parkinson's disease smartwatch home-monitoring study",
        "marital-dyad social-actigraphy study",
        "author-request-only small-N/schema-hidden rows",
        "Personalized Parkinson Project / PD Virtual Motor Exam",
        "RDSRC-gated and schema-hidden",
        "non-destructive regeneration probe",
        "blocked_missing_regeneration_inputs",
        "control clinical file, control CSV directory, and walkway metrics",
    ]
    v.check(
        "current paper export contains valid-range T3 framing",
        all(s in current_paper_text for s in required_current_paper_snippets),
        {"snippets": required_current_paper_snippets},
    )
    v.check(
        "current paper export contains T1 auxiliary-label caveat",
        all(
            s in current_paper
            for s in [
                "NLS036",
                "auxiliary-label caveat",
                "item 15 = 18",
                "post-hoc N = 92",
                "RegressorChain(order=\"random\")",
                "delta = -0.0008",
            ]
        ),
        {
            "snippets": [
                "NLS036",
                "auxiliary-label caveat",
                "item 15 = 18",
                "post-hoc N = 92",
                "RegressorChain(order=\"random\")",
                "delta = -0.0008",
            ]
        },
    )
    v.check(
        "completion audit explicitly says not complete",
        "Not complete" in audit_md and ("T3 remains at `0.5227`" in audit_md or "T3" in audit_md),
        {"audit": "thread_goal_completion_audit_20260508.md"},
    )
    v.check(
        "artifact index points to current render and stale-generator caveat",
        "CURRENT_PAPER.html" in index_md and "NEW4.html" in index_md and "stale pre-leakage narrative fragments" in index_md,
        {"index": "current_best_pipeline_artifact_index_20260508.md"},
    )
    external_route = load_json(RESULTS / "external_dataset_route_audit_20260508.json")
    external_access_readiness = load_json(RESULTS / "external_access_readiness_audit_20260509.json")
    access_submission_tracker = load_json(RESULTS / "access_submission_tracker_20260509.json")
    ppmi_packet_audit = load_json(RESULTS / "ppmi_verily_request_packet_audit_20260509.json")
    ppmi_submit_format_audit = load_json(RESULTS / "ppmi_verily_submit_format_audit_20260515.json")
    ppmi_email_template_audit = load_json(RESULTS / "ppmi_verily_submission_email_template_audit_20260515.json")
    ppmi_email_validator_audit = load_json(RESULTS / "ppmi_verily_submission_email_validator_audit_20260515.json")
    ppmi_package_validator_audit = load_json(
        RESULTS / "ppmi_verily_submission_package_validator_audit_20260515.json"
    )
    access_request_packet_validator_audit = load_json(
        RESULTS / "access_request_packet_validator_audit_20260515.json"
    )
    access_request_fill_checklist_audit = load_json(
        RESULTS / "access_request_fill_checklist_audit_20260515.json"
    )
    external_access_submission_index_audit = load_json(
        RESULTS / "external_access_submission_index_audit_20260515.json"
    )
    external_access_lifecycle_status_audit = load_json(
        RESULTS / "external_access_lifecycle_status_audit_20260515.json"
    )
    external_schema_probe_handoff_audit = load_json(
        RESULTS / "external_schema_probe_handoff_audit_20260515.json"
    )
    external_schema_probe_report_validator_audit = load_json(
        RESULTS / "external_schema_probe_report_validator_audit_20260515.json"
    )
    external_target_free_manifest_validator_audit = load_json(
        RESULTS / "external_target_free_manifest_validator_audit_20260515.json"
    )
    external_target_free_manifest_templates_audit = load_json(
        RESULTS / "external_target_free_manifest_templates_audit_20260515.json"
    )
    external_zeroshot_blueprint_handoff_audit = load_json(
        RESULTS / "external_zeroshot_blueprint_handoff_audit_20260515.json"
    )
    external_formula_sha_templates_audit = load_json(
        RESULTS / "external_formula_sha_templates_audit_20260515.json"
    )
    external_zeroshot_result_templates_audit = load_json(
        RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
    )
    external_formula_sha_ppmi = (
        external_formula_sha_templates_audit.get("route_results") or {}
    ).get("ppmi_verily") or {}
    external_zeroshot_result_ppmi = (
        external_zeroshot_result_templates_audit.get("route_results") or {}
    ).get("ppmi_verily") or {}
    ppmi_user_fill_checklist_audit = load_json(RESULTS / "ppmi_verily_user_fill_checklist_audit_20260515.json")
    ppmi_schema_probe_checklist_audit = load_json(
        RESULTS / "ppmi_verily_schema_probe_checklist_audit_20260515.json"
    )
    ppmi_schema_probe_template_audit = load_json(
        RESULTS / "ppmi_verily_schema_probe_report_template_audit_20260515.json"
    )
    ppmi_schema_probe_report_validator_audit = load_json(
        RESULTS / "ppmi_verily_schema_probe_report_validator_audit_20260515.json"
    )
    ppmi_target_free_manifest_validator_audit = load_json(
        RESULTS / "ppmi_verily_target_free_manifest_validator_audit_20260515.json"
    )
    ppmi_completed_packet_validator_audit = load_json(
        RESULTS / "ppmi_verily_completed_packet_validator_audit_20260515.json"
    )
    ppmi_submission_bundle = load_json(RESULTS / "ppmi_verily_submission_bundle_20260515.json")
    ppmi_current_submission_handoff = load_json(
        RESULTS / "ppmi_verily_current_submission_handoff_20260515.json"
    )
    ppmi_zeroshot_blueprint_audit = load_json(
        RESULTS / "ppmi_verily_zeroshot_blueprint_audit_20260515.json"
    )
    access_submission_recorder_audit = load_json(RESULTS / "access_submission_recorder_audit_20260510.json")
    access_approval_recorder_audit = load_json(RESULTS / "access_approval_recorder_audit_20260510.json")
    schema_probe_recorder_audit = load_json(RESULTS / "schema_probe_recorder_audit_20260510.json")
    current_next_action_handoff = load_json(RESULTS / "current_next_action_handoff_20260515.json")
    access_lifecycle_state_handoff = load_json(RESULTS / "access_lifecycle_state_handoff_20260515.json")
    ppmi_next_action_status_audit = load_json(
        RESULTS / "ppmi_verily_next_action_status_audit_20260515.json"
    )
    t1_t3_goal_status_audit = load_json(RESULTS / "t1_t3_goal_status_audit_20260516.json")
    external_access_queue_status_audit = load_json(
        RESULTS / "external_access_queue_status_audit_20260515.json"
    )
    external_queue_ppmi_gates = (
        external_access_queue_status_audit.get("ppmi_post_approval_contract_gates")
        or {}
    )
    external_queue_ppmi_formula_gate = (
        external_queue_ppmi_gates.get("formula_sha_record") or {}
    )
    external_queue_ppmi_result_gate = (
        external_queue_ppmi_gates.get("zeroshot_result_record") or {}
    )
    proresults_audit = load_json(RESULTS / "proresults_prompt_to_artifact_audit_20260515.json")
    proresults_t1_best = (
        proresults_audit.get("ceiling_break_evidence", {}).get("t1_best_attempt") or {}
    )
    t3_slotf_replication_audit = load_json(RESULTS / "t3_slotF_replication_audit_20260515.json")
    raw_recovery_runbook_audit = load_json(RESULTS / "weargait_raw_data_recovery_runbook_audit_20260509.json")
    task_plan_current_scope_audit = load_json(RESULTS / "task_plan_current_scope_audit_20260509.json")
    paper_generator_routing_audit = load_json(RESULTS / "paper_generator_routing_audit_20260509.json")
    readme_claim_routing_audit = load_json(RESULTS / "readme_claim_routing_audit_20260509.json")
    legacy_manuscript_surface_audit = load_json(RESULTS / "legacy_manuscript_surface_audit_20260509.json")
    historical_archive_surface_audit = load_json(RESULTS / "historical_archive_surface_audit_20260509.json")
    secret_hygiene_audit = load_json(RESULTS / "secret_hygiene_audit_20260509.json")
    phone_tremor_consult = load_json(RESULTS / "phone_tremor_route_consult_20260509.json")
    harmonized_accel_consult = load_json(RESULTS / "harmonized_accel_route_consult_20260509.json")
    smartwatch_subitem_refresh = load_json(RESULTS / "smartwatch_subitem_route_refresh_20260509.json")
    derivative_multimodal_refresh = load_json(RESULTS / "derivative_multimodal_route_refresh_20260509.json")
    request_only_actigraphy_refresh = load_json(RESULTS / "request_only_actigraphy_route_refresh_20260509.json")
    luxembourg_upper_limb_refresh = load_json(RESULTS / "luxembourg_upper_limb_route_refresh_20260509.json")
    prequantipark_refresh = load_json(RESULTS / "prequantipark_route_refresh_20260509.json")
    tum_rocket_inception_refresh = load_json(RESULTS / "tum_rocket_inception_route_refresh_20260509.json")
    paradigma_yin_refresh = load_json(RESULTS / "paradigma_yin_route_refresh_20260509.json")
    parkinsonathome_refresh = load_json(RESULTS / "parkinsonathome_route_refresh_20260509.json")
    care_pd = next((r for r in external_route.get("routes", []) if r.get("name") == "CARE-PD"), {})
    fogstar = next((r for r in external_route.get("routes", []) if r.get("name") == "FoG-STAR"), {})
    cops_route = next((r for r in external_route.get("routes", []) if r.get("name") == "COPS"), {})
    alameda_route = next((r for r in external_route.get("routes", []) if "ALAMEDA" in r.get("name", "")), {})
    mpower_route = next((r for r in external_route.get("routes", []) if r.get("name") == "mPower"), {})
    phone_tremor_route = next((r for r in external_route.get("routes", []) if r.get("name") == "Papadopoulos phone-call tremor"), {})
    harmonized_accel_route = next((r for r in external_route.get("routes", []) if r.get("name") == "Harmonized Upper/Lower Limb Accelerometry"), {})
    monipar_route = next((r for r in external_route.get("routes", []) if r.get("name") == "Monipar"), {})
    bioclite_route = next((r for r in external_route.get("routes", []) if r.get("name") == "BIOCLITE"), {})
    ppp_route = next((r for r in external_route.get("routes", []) if "Personalized Parkinson Project" in r.get("name", "")), {})
    monipar_refresh = next((r for r in smartwatch_subitem_refresh.get("routes", []) if r.get("name") == "Monipar"), {})
    bioclite_refresh = next((r for r in smartwatch_subitem_refresh.get("routes", []) if r.get("name") == "BIOCLITE"), {})
    ppp_refresh = next((r for r in smartwatch_subitem_refresh.get("routes", []) if "Personalized Parkinson Project" in r.get("name", "")), {})
    derivative_multimodal_route = next((r for r in external_route.get("routes", []) if r.get("name") == "Comprehensive Multi-Modal Dataset for Parkinson's Disease Prediction"), {})
    advanced_smartwatch_route = next((r for r in external_route.get("routes", []) if "Advanced PD smartwatch" in r.get("name", "")), {})
    dyad_actigraphy_route = next((r for r in external_route.get("routes", []) if "Marital-dyad" in r.get("name", "")), {})
    luxembourg_route = next((r for r in external_route.get("routes", []) if "Luxembourg" in r.get("name", "")), {})
    prequantipark_route = next((r for r in external_route.get("routes", []) if "Pre-QuantiPark" in r.get("name", "")), {})
    tum_rocket_inception_route = next((r for r in external_route.get("routes", []) if "TUM Donie" in r.get("name", "") or "TUM Donié" in r.get("name", "")), {})
    paradigma_route = next((r for r in external_route.get("routes", []) if "ParaDigMa" in r.get("name", "")), {})
    yin_route = next((r for r in external_route.get("routes", []) if "Yin et al" in r.get("name", "")), {})
    parkinsonathome_route = next((r for r in external_route.get("routes", []) if "Parkinson@Home" in r.get("name", "")), {})
    paradigma_refresh = next((r for r in paradigma_yin_refresh.get("routes", []) if "ParaDigMa" in r.get("name", "")), {})
    yin_refresh = next((r for r in paradigma_yin_refresh.get("routes", []) if "Yin et al" in r.get("name", "")), {})
    advanced_smartwatch_refresh = next((r for r in request_only_actigraphy_refresh.get("routes", []) if "Advanced PD smartwatch" in r.get("name", "")), {})
    dyad_actigraphy_refresh = next((r for r in request_only_actigraphy_refresh.get("routes", []) if "Marital-dyad" in r.get("name", "")), {})
    remap_route = next((r for r in external_route.get("routes", []) if r.get("name") == "REMAP Bristol"), {})
    oxford_route = next((r for r in external_route.get("routes", []) if "Oxford OPDC" in r.get("name", "")), {})
    biostamp_route = next((r for r in external_route.get("routes", []) if r.get("name") == "PD-BioStampRC21"), {})
    mjff_route = next((r for r in external_route.get("routes", []) if "MJFF" in r.get("name", "")), {})
    ppmi_route = next((r for r in external_route.get("routes", []) if "PPMI" in r.get("name", "")), {})
    watchpd_route = next((r for r in external_route.get("routes", []) if "WATCH-PD" in r.get("name", "")), {})
    icicle_route = next((r for r in external_route.get("routes", []) if "ICICLE" in r.get("name", "")), {})
    cns_route = next((r for r in external_route.get("routes", []) if "CNS Portugal" in r.get("name", "")), {})
    mobilised_route = next((r for r in external_route.get("routes", []) if "Mobilise-D" in r.get("name", "")), {})
    tlvmc_route = next((r for r in external_route.get("routes", []) if "TLVMC" in r.get("name", "")), {})
    pdfe_route = next((r for r in external_route.get("routes", []) if r.get("name") == "PDFE turning-in-place"), {})
    gait_biomech_route = next((r for r in external_route.get("routes", []) if r.get("name") == "Public overground walking full-body biomechanics"), {})
    ppmi_submission_route = next(
        (
            route
            for route in access_submission_tracker.get("routes", [])
            if route.get("id") == "ppmi_verily"
        ),
        {},
    )
    ppmi_official_recheck = ppmi_submission_route.get("official_source_recheck", {})
    lifecycle_pre_submission_handoff = (
        access_lifecycle_state_handoff.get("pre_submission_handoff") or {}
    )
    lifecycle_state = access_lifecycle_state_handoff.get("current_lifecycle_state")
    lifecycle_current_action = access_lifecycle_state_handoff.get("current_action") or {}
    lifecycle_local_counts = access_lifecycle_state_handoff.get("local_counts") or {}
    pre_access_blocked_actions = [
        "probe script against protected data",
        "download script",
        "cache extraction",
        "pre-registration using new labels",
        "remote job",
        "model run",
        "canonical T1/T3 claim update",
    ]
    schema_probe_only_blocked_actions = [
        "download script",
        "cache extraction",
        "pre-registration using new labels",
        "remote job",
        "model run",
        "canonical T1/T3 claim update",
    ]
    expected_lifecycle_actions = {
        "packet_ready": ("submit_access_request", False, True, pre_access_blocked_actions),
        "submitted_pending_approval": (
            "wait_for_access_approval",
            False,
            True,
            pre_access_blocked_actions,
        ),
        "approved_for_schema_probe": (
            "run_read_only_schema_probe",
            True,
            False,
            schema_probe_only_blocked_actions,
        ),
        "schema_probe_recorded": (
            "review_schema_probe_gates",
            False,
            False,
            schema_probe_only_blocked_actions,
        ),
        "invalid": ("fix_access_evidence", False, False, pre_access_blocked_actions),
    }
    expected_lifecycle_action = expected_lifecycle_actions.get(lifecycle_state)
    action_id_by_lifecycle_action = {
        "submit_access_request": "submit_ppmi_verily_access_request",
        "wait_for_access_approval": "wait_for_ppmi_verily_access_approval",
        "run_read_only_schema_probe": "run_ppmi_verily_read_only_schema_probe",
        "review_schema_probe_gates": "review_ppmi_verily_schema_probe_gates",
        "fix_access_evidence": "fix_ppmi_verily_access_evidence",
    }
    actor_by_lifecycle_action = {
        "submit_access_request": "user_or_institutional_pi",
        "wait_for_access_approval": "user_or_institutional_pi",
        "run_read_only_schema_probe": "approved_analyst",
        "review_schema_probe_gates": "analyst",
        "fix_access_evidence": "analyst",
    }
    expected_lifecycle_action_id = (
        action_id_by_lifecycle_action.get(expected_lifecycle_action[0])
        if expected_lifecycle_action
        else None
    )
    state_aware_access_lifecycle_ready = (
        access_lifecycle_state_handoff.get("passed") is True
        and access_lifecycle_state_handoff.get("decision")
        == "access_lifecycle_state_handoff_ready"
        and access_lifecycle_state_handoff.get("goal_complete") is False
        and access_lifecycle_state_handoff.get("not_a_model_result") is True
        and access_lifecycle_state_handoff.get("hard_failures") == []
        and expected_lifecycle_action is not None
        and lifecycle_current_action.get("action") == expected_lifecycle_action[0]
        and lifecycle_current_action.get("safe_to_execute_code")
        == expected_lifecycle_action[1]
        and lifecycle_current_action.get("requires_user_action")
        == expected_lifecycle_action[2]
        and list(lifecycle_current_action.get("blocked_actions_now", []))
        == expected_lifecycle_action[3]
        and lifecycle_local_counts.get("record_identities_redacted") is True
        and lifecycle_local_counts.get("record_paths_reported") is False
        and lifecycle_local_counts.get("protected_data_accessed") is False
        and any(
            row.get("name")
            == "current local access lifecycle state maps to the correct gated action"
            and row.get("passed") is True
            for row in access_lifecycle_state_handoff.get("checks", [])
        )
    )
    packet_ready_current_action_support_ready = (
        current_next_action_handoff.get("passed") is True
        and current_next_action_handoff.get("decision") == "current_next_action_handoff_ready"
        and current_next_action_handoff.get("goal_complete") is False
        and current_next_action_handoff.get("not_a_model_result") is True
        and current_next_action_handoff.get("hard_failures") == []
        and current_next_action_handoff.get("local_access_state", {}).get("real_access_submission_count") == 0
        and current_next_action_handoff.get("local_access_state", {}).get("real_access_approval_count") == 0
        and current_next_action_handoff.get("local_access_state", {}).get("schema_probe_artifact_count") == 0
        and current_next_action_handoff.get("next_action", {}).get("action_id")
        == "submit_ppmi_verily_access_request"
        and current_next_action_handoff.get("next_action", {}).get("safe_to_execute_code_now")
        is False
        and current_next_action_handoff.get("next_action", {}).get("use_word_packet_template")
        == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
        and current_next_action_handoff.get("next_action", {}).get("use_completed_email_validator")
        == "scripts/validate_ppmi_verily_submission_email.py"
        and current_next_action_handoff.get("next_action", {}).get("use_fill_checklist")
        == "scripts/ppmi_verily_user_fill_checklist.md"
        and current_next_action_handoff.get("next_action", {}).get("workflow_command_sequence")
        == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
        and any(
            row.get("name") == "current next-action handoff exposes submission and approval metadata recorders"
            and row.get("passed") is True
            for row in current_next_action_handoff.get("checks", [])
        )
    )
    lifecycle_next_action = dict(current_next_action_handoff.get("next_action") or {})
    if expected_lifecycle_action is not None:
        lifecycle_next_action.update(
            {
                "action_id": expected_lifecycle_action_id,
                "actor": actor_by_lifecycle_action.get(expected_lifecycle_action[0]),
                "route_id": lifecycle_current_action.get("route_id"),
                "route_name": "PPMI / Verily Study Watch",
                "current_lifecycle_state": lifecycle_state,
                "lifecycle_action": expected_lifecycle_action[0],
                "allowed_now": lifecycle_current_action.get("allowed_now", []),
                "requires_user_action": expected_lifecycle_action[2],
                "safe_to_execute_code_now": expected_lifecycle_action[1],
                "blocked_actions_now": expected_lifecycle_action[3],
            }
        )
    v.check(
        "external dataset audit distinguishes public, skipped, and gated external routes",
        care_pd.get("direct_t1_t3_eligible") is False
        and care_pd.get("label") == "UPDRS_GAIT"
        and fogstar.get("direct_t1_t3_eligible") is True
        and fogstar.get("screen_result", {}).get("gate_pass") is False
        and approx_equal(fogstar.get("zero_shot_result", {}).get("track_b_iter5_style_clinical_plus_wrist_ccc"), 0.2499)
        and cops_route.get("direct_t1_t3_eligible") is True
        and cops_route.get("status") == "zero_shot_complete_external_validity_only"
        and cops_route.get("n_osf_zip_records") == 66
        and cops_route.get("n_unique_subject_archives") == 64
        and cops_route.get("n_off_labeled_subjects") == 62
        and approx_equal(cops_route.get("zero_shot_result", {}).get("track_a_right_wrist_direct_ccc"), -0.0193)
        and approx_equal(cops_route.get("zero_shot_result", {}).get("track_b_right_clinical_plus_wrist_ccc"), 0.2412)
        and approx_equal(cops_route.get("zero_shot_result", {}).get("track_d_bilateral_clinical_plus_wrist_ccc"), 0.2535)
        and approx_equal(cops_route.get("zero_shot_result", {}).get("track_c_cops_only_loo_sanity_ccc"), 0.31)
        and tlvmc_route.get("direct_t1_t3_eligible") is True
        and tlvmc_route.get("status") == "zero_shot_complete_external_validity_only"
        and tlvmc_route.get("n_subjects_with_updrsiii") == 136
        and tlvmc_route.get("n_subject_visits_with_updrsiii") == 173
        and tlvmc_route.get("n_defog_subjects") == 45
        and tlvmc_route.get("n_defog_subject_visits") == 70
        and tlvmc_route.get("n_defog_recordings") == 137
        and tlvmc_route.get("n_defog_medication_matched_targets") == 137
        and tlvmc_route.get("n_defog_off_records") == 68
        and tlvmc_route.get("n_defog_off_subjects") == 44
        and tlvmc_route.get("preregistration", {}).get("formula_sha256") == "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd"
        and tlvmc_prereg.get("formula_sha256") == "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd"
        and tlvmc_prereg.get("formula", {}).get("fixed_battery", {}).get("primary_external_target", {}).get("expected_n_records") == 68
        and tlvmc_prereg.get("formula", {}).get("fixed_battery", {}).get("tracks", {}).get("A_zero_shot_lumbar_acc_magnitude", {}).get("labels_used_for_training") is False
        and tlvmc_iter51.get("preregistration_formula_sha256") == "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd"
        and tlvmc_iter51.get("decision") == "external_zero_shot_only_no_internal_t3_canonical_change"
        and tlvmc_iter51.get("n_defog_rows") == 136
        and tlvmc_iter51.get("n_defog_subjects") == 45
        and tlvmc_iter51.get("n_defog_off_rows") == 68
        and tlvmc_iter51.get("n_common_magnitude_features") == 54
        and approx_equal(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_a_mean", {}).get("ccc"), 0.2695)
        and approx_equal(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_a_mean", {}).get("ccc_ci95", [None, None])[0], 0.1693)
        and approx_equal(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_a_mean", {}).get("ccc_ci95", [None, None])[1], 0.36)
        and approx_equal(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_b_mean", {}).get("ccc"), 0.0485)
        and approx_equal(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_c_defog_loso_ridge", {}).get("ccc"), 0.345)
        and pdfe_route.get("direct_t1_t3_eligible") is True
        and pdfe_route.get("status") == "zero_shot_complete_external_validity_only"
        and pdfe_route.get("n_session1_targets") == 35
        and pdfe_route.get("preregistration", {}).get("formula_sha256") == "f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2"
        and approx_equal(pdfe_route.get("zero_shot_result", {}).get("track_a_weargait_shank_to_pdfe_ccc"), -0.1008)
        and approx_equal(pdfe_route.get("zero_shot_result", {}).get("track_b_clinical_plus_shank_ccc"), 0.1340)
        and approx_equal(pdfe_route.get("zero_shot_result", {}).get("track_c_pdfe_only_loo_ccc"), 0.4020)
        and gait_biomech_route.get("direct_t1_t3_eligible") is False
        and gait_biomech_route.get("status") == "document_only_wrong_modality_motion_capture_force_plates"
        and tlvmc_route.get("n_daily_recordings_with_visit_targets") == 65
        and tlvmc_route.get("n_tdcsfog_joined_updrsiii_targets") == 0
        and tlvmc_probe.get("row_level_metadata_persisted_in_repo") is False
        and tlvmc_probe.get("subjects", {}).get("unique_subjects") == 136
        and tlvmc_probe.get("recording_metadata", {}).get("defog", {}).get("rows_with_matching_medication_updrsiii_target") == 137
        and tlvmc_probe.get("recording_metadata", {}).get("tdcsfog", {}).get("rows_with_any_updrsiii_target") == 0
        and tlvmc_probe.get("raw_schema_samples", {}).get("defog", {}).get("rows") == 162907
        and tlvmc_probe.get("raw_schema_samples", {}).get("defog", {}).get("columns") == ["Time", "AccV", "AccML", "AccAP", "StartHesitation", "Turn", "Walking", "Valid", "Task"]
        and alameda_route.get("direct_t1_t3_eligible") is True
        and alameda_route.get("n_subjects") == 11
        and alameda_route.get("status") == "skipped_underpowered_no_preregistration"
        and mpower_route.get("direct_t1_t3_eligible") is False
        and mpower_route.get("status") == "skipped_not_direct_clinician_t3"
        and "self-reported" in mpower_route.get("label", "")
        and phone_tremor_route.get("direct_t1_t3_eligible") is False
        and phone_tremor_route.get("status") == "skipped_tremor_subitem_phone_not_t1_t3"
        and phone_tremor_route.get("n_clinically_examined_subjects") == 45
        and phone_tremor_route.get("n_self_reported_subjects") == 454
        and "tremor-subitem" in phone_tremor_route.get("verdict", "")
        and phone_tremor_consult.get("route", {}).get("direct_t1_t3_eligible") is False
        and phone_tremor_consult.get("route", {}).get("n_clinically_examined_subjects") == 45
        and phone_tremor_consult.get("consults", {}).get("kimi", {}).get("status") == "completed"
        and phone_tremor_consult.get("consults", {}).get("gemini", {}).get("status") == "completed"
        and phone_tremor_consult.get("consults", {}).get("claude", {}).get("status") == "failed"
        and phone_tremor_consult.get("consults", {}).get("glmcode", {}).get("status") == "not_available"
        and "No preregistration" in phone_tremor_consult.get("decision", "")
        and harmonized_accel_route.get("direct_t1_t3_eligible") is False
        and harmonized_accel_route.get("status") == "skipped_rehab_activity_summaries_no_t1_t3_targets"
        and harmonized_accel_route.get("n_subjects_total") == 790
        and harmonized_accel_route.get("n_recording_days") == 2885
        and harmonized_accel_route.get("approx_n_pd") == 55
        and "lacks confirmed total MDS-UPDRS Part III" in harmonized_accel_route.get("verdict", "")
        and harmonized_accel_consult.get("route", {}).get("direct_t1_t3_eligible") is False
        and harmonized_accel_consult.get("route", {}).get("approx_n_pd") == 55
        and harmonized_accel_consult.get("consults", {}).get("kimi", {}).get("status") == "completed"
        and harmonized_accel_consult.get("consults", {}).get("gemini", {}).get("status") == "completed"
        and harmonized_accel_consult.get("consults", {}).get("claude", {}).get("status") == "failed"
        and harmonized_accel_consult.get("consults", {}).get("glmcode", {}).get("status") == "not_available"
        and "No preregistration" in harmonized_accel_consult.get("decision", "")
        and monipar_route.get("direct_t1_t3_eligible") is False
        and monipar_route.get("status") == "skipped_public_subitem_only_tiny_supervised_n"
        and monipar_route.get("n_pd") == 21
        and monipar_route.get("n_supervised_pd") == 6
        and monipar_route.get("n_supervised_trials") == 46
        and "3.10" in monipar_route.get("covered_items", [])
        and bioclite_route.get("direct_t1_t3_eligible") is False
        and bioclite_route.get("status") == "skipped_public_subitem_only_no_t1_t3_endpoint"
        and bioclite_route.get("n_pd") == 24
        and bioclite_route.get("n_controls") == 16
        and "3.9" in bioclite_route.get("covered_items", [])
        and ppp_route.get("direct_t1_t3_eligible") is True
        and ppp_route.get("status") == "access_gated_document_only_no_scaffold_until_access"
        and ppp_route.get("n_subjects") == 517
        and ppp_route.get("n_vme_participants") == 388
        and ppp_route.get("access_runbook") == "scripts/ppp_pd_vme_request_setup.md"
        and smartwatch_subitem_refresh.get("decision") == "no_prereg_no_download_no_remote_job_for_active_t1_t3_ccc_objective"
        and smartwatch_subitem_refresh.get("consults", {}).get("kimi", {}).get("status") == "completed"
        and smartwatch_subitem_refresh.get("consults", {}).get("claude", {}).get("status") == "failed"
        and smartwatch_subitem_refresh.get("consults", {}).get("glmcode", {}).get("status") == "not_available"
        and monipar_refresh.get("direct_t1_t3_eligible") is False
        and monipar_refresh.get("n_supervised_pd") == 6
        and bioclite_refresh.get("direct_t1_t3_eligible") is False
        and ppp_refresh.get("direct_t1_t3_eligible") is True
        and derivative_multimodal_route.get("direct_t1_t3_eligible") is False
        and derivative_multimodal_route.get("status") == "skipped_derived_summary_table_not_raw_wearable_or_subject_aligned_t1_t3"
        and derivative_multimodal_route.get("n_clinical_gait_rows") == 2223
        and derivative_multimodal_route.get("n_unique_patients") == 771
        and derivative_multimodal_route.get("n_integrated_columns") == 1196
        and derivative_multimodal_refresh.get("decision") == "no_prereg_no_download_no_scaffold_no_remote_job_for_active_t1_t3_ccc_objective"
        and derivative_multimodal_refresh.get("route", {}).get("direct_t1_t3_eligible") is False
        and derivative_multimodal_refresh.get("route", {}).get("files", [{}])[0].get("inspection", {}).get("rows") == 2223
        and derivative_multimodal_refresh.get("route", {}).get("files", [{}, {}])[1].get("inspection", {}).get("columns") == 1196
        and advanced_smartwatch_route.get("direct_t1_t3_eligible") is False
        and advanced_smartwatch_route.get("status") == "request_only_document_only_no_scaffold"
        and advanced_smartwatch_route.get("n_pd_subjects") == 21
        and advanced_smartwatch_refresh.get("status") == "request_only_document_only_no_scaffold"
        and advanced_smartwatch_refresh.get("n_pd_subjects") == 21
        and "proprietary" in advanced_smartwatch_refresh.get("verdict", "")
        and dyad_actigraphy_route.get("direct_t1_t3_eligible") is False
        and dyad_actigraphy_route.get("status") == "request_only_document_only_no_scaffold"
        and dyad_actigraphy_route.get("n_dyads") == 27
        and dyad_actigraphy_route.get("n_individuals") == 54
        and dyad_actigraphy_refresh.get("status") == "request_only_document_only_no_scaffold"
        and dyad_actigraphy_refresh.get("n_dyads") == 27
        and request_only_actigraphy_refresh.get("decision") == "no_prereg_no_download_no_scaffold_no_remote_job_access_request_only"
        and request_only_actigraphy_refresh.get("consults", {}).get("kimi", {}).get("status") == "completed"
        and request_only_actigraphy_refresh.get("consults", {}).get("claude", {}).get("status") == "failed"
        and request_only_actigraphy_refresh.get("consults", {}).get("glmcode", {}).get("status") == "not_available"
        and luxembourg_route.get("direct_t1_t3_eligible") is False
        and luxembourg_route.get("status") == "skipped_request_only_subitem_only_observability_context"
        and luxembourg_route.get("n_pd") == 33
        and luxembourg_route.get("n_controls") == 12
        and "upper-limb observability context" in luxembourg_route.get("verdict", "")
        and "Do not create an access runbook" in luxembourg_route.get("verdict", "")
        and luxembourg_upper_limb_refresh.get("decision") == "document_only_no_runbook_no_scaffold_no_preregistration"
        and luxembourg_upper_limb_refresh.get("status") == "skipped_request_only_subitem_only_observability_context"
        and "skip_runbook_document_only" in luxembourg_upper_limb_refresh.get("consults", {}).get("kimi", "")
        and luxembourg_upper_limb_refresh.get("consults", {}).get("claude") == "failed_credit_balance_too_low"
        and luxembourg_upper_limb_refresh.get("consults", {}).get("glmcode") == "not_found_on_path"
        and prequantipark_route.get("direct_t1_t3_eligible") is False
        and prequantipark_route.get("potential_external_t3_if_access_and_schema_approved") is True
        and prequantipark_route.get("status") == "skipped_request_only_tiny_lct_no_scaffold"
        and prequantipark_route.get("n_pd") == 10
        and "levodopa-challenge" in prequantipark_route.get("verdict", "")
        and "Do not create an access runbook" in prequantipark_route.get("verdict", "")
        and prequantipark_refresh.get("decision") == "document_only_no_runbook_no_scaffold_no_preregistration"
        and prequantipark_refresh.get("status") == "skipped_request_only_tiny_lct_no_scaffold"
        and prequantipark_refresh.get("n_pd") == 10
        and prequantipark_refresh.get("direct_t1_t3_eligible") is False
        and "document_only_no_runbook" in prequantipark_refresh.get("consults", {}).get("kimi", "")
        and prequantipark_refresh.get("consults", {}).get("claude") == "failed_credit_balance_too_low"
        and prequantipark_refresh.get("consults", {}).get("glmcode") == "not_found_on_path"
        and remap_route.get("direct_t1_t3_eligible") is False
        and remap_route.get("n_pd") == 12
        and remap_route.get("status") == "skipped_controlled_tiny_n_range_labels"
        and oxford_route.get("direct_t1_t3_eligible") is False
        and oxford_route.get("status") == "skipped_no_public_aligned_sensor_data"
        and biostamp_route.get("direct_t1_t3_eligible") is False
        and biostamp_route.get("n_pd") == 17
        and biostamp_route.get("status") == "skipped_tiny_n_wrong_sensor_geometry"
        and mjff_route.get("direct_t1_t3_eligible") is True
        and mjff_route.get("status") == "synapse_dua_gated_no_scaffold_until_access"
        and mjff_route.get("access_runbook") == "scripts/synapse_hssayeni_setup.md"
        and "DUA" in mjff_route.get("access_status", "")
        and ppmi_route.get("direct_t1_t3_eligible") is True
        and ppmi_route.get("status") == "access_gated_no_scaffold_until_credentials"
        and ppmi_route.get("access_runbook") == "scripts/ppmi_verily_setup.md"
        and "MDS-UPDRS Part III" in ppmi_route.get("label", "")
        and "100 Hz" in ppmi_route.get("modality", "")
        and ppmi_route.get("consults", {}).get("kimi") == "document_as_access_gated_priority_route_no_scaffold_until_credentials"
        and watchpd_route.get("direct_t1_t3_eligible") is True
        and watchpd_route.get("status") == "request_gated_document_only_no_scaffold_until_access_schema"
        and watchpd_route.get("n_pd") == 82
        and watchpd_route.get("n_controls") == 50
        and "C-Path" in watchpd_route.get("access_status", "")
        and watchpd_route.get("access_runbook") == "scripts/watchpd_request_setup.md"
        and "MDS-UPDRS Part III" in watchpd_route.get("label", "")
        and "Apple Watch" in watchpd_route.get("modality", "")
        and watchpd_route.get("consults", {}).get("kimi") == "request_gated_document_only_no_scaffold_until_access_schema"
        and watchpd_route.get("consults", {}).get("gemini") == "request_gated_document_only_no_scaffold_ppmi_priority"
        and icicle_route.get("direct_t1_t3_eligible") is True
        and icicle_route.get("status") == "request_gated_document_only_no_scaffold_until_data"
        and icicle_route.get("n_pd") == 89
        and icicle_route.get("n_daily_samples") == 1476
        and icicle_route.get("access_runbook") == "scripts/icicle_request_setup.md"
        and "MDS-UPDRS Part III" in icicle_route.get("label", "")
        and "lower-back" in icicle_route.get("modality", "")
        and "100 Hz" in icicle_route.get("modality", "")
        and approx_equal(icicle_route.get("published_benchmark", {}).get("best_global_fl_mae"), 9.26)
        and approx_equal(icicle_route.get("published_benchmark", {}).get("best_global_fl_r"), 0.43)
        and icicle_route.get("consults", {}).get("kimi") == "document_as_request_gated_route_no_scaffold_until_data"
        and icicle_route.get("consults", {}).get("gemini") == "document_and_request_access_no_scaffold_until_schema"
        and cns_route.get("direct_t1_t3_eligible") is True
        and cns_route.get("status") == "request_gated_document_only_no_scaffold_until_data"
        and cns_route.get("n_pd") == 74
        and cns_route.get("n_sessions") == 104
        and cns_route.get("n_gait_instances") == 267
        and cns_route.get("access_runbook") == "scripts/cns_portugal_request_setup.md"
        and "MDS-UPDRS Part III" in cns_route.get("label", "")
        and "wrist and lower back" in cns_route.get("modality", "")
        and "100 Hz" in cns_route.get("modality", "")
        and approx_equal(cns_route.get("published_benchmark", {}).get("best_10pct_leftout_mae"), 4.26)
        and approx_equal(cns_route.get("published_benchmark", {}).get("best_loso_mae"), 9.99)
        and cns_route.get("consults", {}).get("kimi") == "add_request_gated_direct_t3_no_scaffold_subject_level"
        and cns_route.get("consults", {}).get("gemini") == "add_request_gated_direct_t3_no_scaffold_strict_subject_split"
        and mobilised_route.get("direct_t1_t3_eligible") is False
        and mobilised_route.get("status") == "watchlist_no_scaffold_until_cvs_release_or_schema"
        and mobilised_route.get("n_tvs_subjects_total") == 108
        and mobilised_route.get("n_cvs_pd_baseline_reported") == 600
        and mobilised_route.get("consults", {}).get("kimi") == "skip_tvs_watchlist_request_cvs_no_scaffold_until_schema"
        and mobilised_route.get("consults", {}).get("gemini") == "skip_tvs_watchlist_request_cvs_no_scaffold_until_row_level_release"
        and "algorithm-validation" in mobilised_route.get("verdict", "")
        and "scripts/ppmi_verily_setup.md" in external_audit_md
        and "scripts/ppp_pd_vme_request_setup.md" in external_audit_md
        and "scripts/synapse_hssayeni_setup.md" in external_audit_md
        and "WATCH-PD" in external_audit_md
        and "scripts/watchpd_request_setup.md" in external_audit_md
        and "scripts/icicle_request_setup.md" in external_audit_md
        and "scripts/cns_portugal_request_setup.md" in external_audit_md
        and "Mobilise-D TVS / CVS" in external_audit_md
        and "TLVMC / DeFOG" in external_audit_md
        and "PDFE turning-in-place" in external_audit_md
        and "Track A WearGait shank-to-PDFE CCC `-0.1008`" in external_audit_md
        and "Public overground walking full-body biomechanics" in external_audit_md
        and "Papadopoulos phone-call tremor" in external_audit_md
        and "Harmonized Upper/Lower Limb Accelerometry" in external_audit_md
        and "Monipar" in external_audit_md
        and "BIOCLITE" in external_audit_md
        and "Comprehensive Multi-Modal Dataset" in external_audit_md
        and "Advanced PD smartwatch home monitoring" in external_audit_md
        and "Marital-dyad social actigraphy" in external_audit_md
        and "Personalized Parkinson Project / PD Virtual Motor Exam" in external_audit_md
        and "Luxembourg upper-limb MDS-UPDRS III subitem study" in external_audit_md
        and "no access runbook, preregistration, download, scaffold, or remote job" in external_audit_md
        and "Pre-QuantiPark / ActiMyo levodopa-challenge wearable IMU pilot" in external_audit_md
        and "no access runbook, preregistration, download, scaffold, request packet, or remote job" in external_audit_md
        and tum_rocket_inception_route.get("direct_t1_t3_eligible") is False
        and tum_rocket_inception_route.get("status") == "document_only_hssayeni_alias_algorithm_dead_no_scaffold"
        and tum_rocket_inception_route.get("n_pd") == 27
        and tum_rocket_inception_route.get("underlying_route") == "MJFF Levodopa Response / Hssayeni syn20681023"
        and tum_rocket_inception_route.get("code_available") is True
        and "already-negative ROCKET/InceptionTime-style" in tum_rocket_inception_route.get("verdict", "")
        and tum_rocket_inception_refresh.get("decision") == "document_only_no_scaffold_no_preregistration_no_remote_job"
        and tum_rocket_inception_refresh.get("status") == "document_only_hssayeni_alias_algorithm_dead_no_scaffold"
        and tum_rocket_inception_refresh.get("n_pd") == 27
        and tum_rocket_inception_refresh.get("direct_t1_t3_eligible") is False
        and tum_rocket_inception_refresh.get("code_available") is True
        and "document_only_alias" in tum_rocket_inception_refresh.get("consults", {}).get("kimi", "")
        and tum_rocket_inception_refresh.get("consults", {}).get("claude") == "failed_credit_balance_too_low"
        and tum_rocket_inception_refresh.get("consults", {}).get("glmcode") == "not_found_on_path"
        and "TUM Donié ROCKET/InceptionTime wrist symptom-classification alias" in external_audit_md
        and "no access runbook, code clone, preregistration, download, scaffold, or remote job" in external_audit_md
        and paradigma_route.get("direct_t1_t3_eligible") is False
        and paradigma_route.get("status") == "local_feature_addition_dead_at_n94"
        and paradigma_route.get("code_available") is True
        and paradigma_route.get("data_available") is False
        and "local scalar" in paradigma_route.get("verdict", "")
        and yin_route.get("direct_t1_t3_eligible") is False
        and yin_route.get("status") == "request_only_underpowered_no_public_schema"
        and yin_route.get("n_pd") == 20
        and yin_route.get("n_controls") == 17
        and "no public row-level schema" in yin_route.get("access_status", "")
        and paradigma_refresh.get("decision") == "document_only_no_scaffold_no_preregistration_no_remote_job"
        and paradigma_refresh.get("status") == "local_feature_addition_dead_at_n94"
        and paradigma_refresh.get("direct_t1_t3_eligible") is False
        and yin_refresh.get("decision") == "document_only_no_scaffold_no_preregistration_no_remote_job"
        and yin_refresh.get("status") == "request_only_underpowered_no_public_schema"
        and yin_refresh.get("n_pd") == 20
        and paradigma_yin_refresh.get("consults", {}).get("claude") == "failed_credit_balance_too_low"
        and paradigma_yin_refresh.get("consults", {}).get("glmcode") == "not_found_on_path"
        and "ParaDigMa" in external_audit_md
        and "Yin et al Frontiers Neurology 2025" in external_audit_md
        and "Parkinson@Home arm-swing validation" in external_audit_md
        and parkinsonathome_route.get("direct_t1_t3_eligible") is True
        and parkinsonathome_route.get("status") == "probe_passed_zero_shot_hard_stop_n18_no_scoring"
        and parkinsonathome_route.get("n_pd") == 25
        and parkinsonathome_route.get("n_feature_readable_off_subjects") == 18
        and parkinsonathome_route.get("n_required_feature_readable_off_subjects") == 20
        and parkinsonathome_route.get("completed_result") is False
        and parkinsonathome_route.get("metrics_available") is False
        and parkinsonathome_refresh.get("status") == "probe_passed_zero_shot_hard_stop_n18_no_scoring"
        and parkinsonathome_refresh.get("hard_stop", {}).get("fired") is True
        and parkinsonathome_refresh.get("hard_stop", {}).get("observed_valid_off_subjects") == 18
        and parkinsonathome_refresh.get("hard_stop", {}).get("required_valid_off_subjects") == 20
        and parkinsonathome_refresh.get("hard_stop", {}).get("scoring_started") is False
        and parkinsonathome_refresh.get("metrics") is None
        and "Do not rerun iter53 under the same preregistration" in read_text(RESULTS / "parkinsonathome_route_refresh_20260509.md")
        and "68 OFF primary rows" in external_audit_md
        and "Track A lower-back magnitude zero-shot CCC `+0.2695`" in external_audit_md
        and "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd" in external_audit_md
        and "iter49 zero-shot complete" in external_audit_md,
        {
            "CARE-PD": care_pd,
            "FoG-STAR": fogstar,
            "COPS": cops_route,
            "TLVMC/DeFOG": {
                "route": tlvmc_route,
                "probe_subjects": tlvmc_probe.get("subjects"),
                "probe_defog": tlvmc_probe.get("recording_metadata", {}).get("defog"),
                "probe_tdcsfog": tlvmc_probe.get("recording_metadata", {}).get("tdcsfog"),
                "raw_schema_sample": tlvmc_probe.get("raw_schema_samples", {}).get("defog"),
                "preregistration": tlvmc_prereg.get("formula", {}).get("fixed_battery", {}).get("primary_external_target"),
                "result": {
                    "decision": tlvmc_iter51.get("decision"),
                    "n_defog_rows": tlvmc_iter51.get("n_defog_rows"),
                    "n_common_magnitude_features": tlvmc_iter51.get("n_common_magnitude_features"),
                    "track_a_mean_off": tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_a_mean"),
                    "track_b_mean_off": tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_b_mean"),
                    "track_c_defog_loso": tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_c_defog_loso_ridge"),
                },
            },
            "PDFE turning-in-place": {
                "route": pdfe_route,
                "probe": pdfe_probe,
                "result": {
                    "track_a": pdfe_track_a,
                    "track_b": pdfe_track_b,
                    "track_c": pdfe_track_c,
                },
            },
            "Public overground walking full-body biomechanics": gait_biomech_route,
            "ALAMEDA": alameda_route,
            "mPower": mpower_route,
            "Papadopoulos phone-call tremor": {
                "route": phone_tremor_route,
                "consult": phone_tremor_consult,
            },
            "Harmonized Upper/Lower Limb Accelerometry": {
                "route": harmonized_accel_route,
                "consult": harmonized_accel_consult,
            },
            "Monipar": {
                "route": monipar_route,
                "refresh": monipar_refresh,
            },
            "BIOCLITE": {
                "route": bioclite_route,
                "refresh": bioclite_refresh,
            },
            "Personalized Parkinson Project / PD-VME": {
                "route": ppp_route,
                "refresh": ppp_refresh,
            },
            "Comprehensive Multi-Modal Dataset": {
                "route": derivative_multimodal_route,
                "refresh": derivative_multimodal_refresh,
            },
            "Request-only actigraphy": {
                "advanced_smartwatch_route": advanced_smartwatch_route,
                "dyad_actigraphy_route": dyad_actigraphy_route,
                "refresh": request_only_actigraphy_refresh,
            },
            "Luxembourg upper-limb": {
                "route": luxembourg_route,
                "refresh": luxembourg_upper_limb_refresh,
            },
            "Pre-QuantiPark": {
                "route": prequantipark_route,
                "refresh": prequantipark_refresh,
            },
            "TUM Donie ROCKET/InceptionTime": {
                "route": tum_rocket_inception_route,
                "refresh": tum_rocket_inception_refresh,
            },
            "ParaDigMa": {
                "route": paradigma_route,
                "refresh": paradigma_refresh,
            },
            "Yin et al": {
                "route": yin_route,
                "refresh": yin_refresh,
            },
            "Parkinson@Home": {
                "route": parkinsonathome_route,
                "refresh": parkinsonathome_refresh,
            },
            "REMAP": remap_route,
            "Oxford": oxford_route,
            "PD-BioStampRC21": biostamp_route,
            "MJFF": mjff_route,
            "PPMI": ppmi_route,
            "WATCH-PD": watchpd_route,
            "ICICLE": icicle_route,
            "CNS Portugal": cns_route,
            "Mobilise-D": mobilised_route,
        },
    )
    v.check(
        "PPMI runbook preserves access-first no-scaffold boundary",
        all(
            s in ppmi_runbook
            for s in [
                "access-gated",
                "Do not build a probe scaffold",
                "Data Use Agreement",
                "MDS-UPDRS Part III",
                "100 Hz",
                "Train on WearGait-PD only",
                "validate_ppmi_verily_target_free_manifest.py",
                "Do not create placeholder versions",
            ]
        ),
        {"runbook": "scripts/ppmi_verily_setup.md"},
    )
    v.check(
        "pro-results prompt-to-artifact audit is first-class and keeps external route gated",
        proresults_audit.get("name") == "proresults_prompt_to_artifact_audit"
        and proresults_audit.get("prompt_source", {}).get("prompt_path") == "/tmp/pro-results.txt"
        and proresults_audit.get("prompt_source", {}).get("exists") is True
        and proresults_audit.get("prompt_source", {}).get("read_ok") is True
        and isinstance(proresults_audit.get("prompt_source", {}).get("sha256"), str)
        and len(proresults_audit.get("prompt_source", {}).get("sha256", "")) == 64
        and isinstance(proresults_audit.get("prompt_source", {}).get("byte_count"), int)
        and proresults_audit.get("prompt_source", {}).get("byte_count") > 0
        and isinstance(proresults_audit.get("prompt_source", {}).get("line_count"), int)
        and proresults_audit.get("prompt_source", {}).get("line_count") >= 100
        and proresults_audit.get("prompt_source", {}).get("missing_required_snippets") == []
        and proresults_audit.get("prompt_source", {}).get("missing_rank_headers") == []
        and any(
            row.get("id") == "prompt_file_loaded"
            and row.get("passed") is True
            and row.get("evidence", {}).get("sha256")
            == proresults_audit.get("prompt_source", {}).get("sha256")
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and proresults_audit.get("all_numbered_items_covered_or_access_blocked") is True
        and proresults_audit.get("completion_audit_passed") is True
        and proresults_audit.get("completion_audit_failures") == []
        and len(proresults_audit.get("completion_audit_checklist", [])) >= 14
        and all(
            row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and proresults_audit.get("explicit_directive_checklist_passed") is True
        and proresults_audit.get("explicit_directive_checklist_failures") == []
        and len(proresults_audit.get("explicit_directive_checklist", [])) >= 10
        and all(
            row.get("passed") is True
            for row in proresults_audit.get("explicit_directive_checklist", [])
        )
        and any(
            row.get("id") == "slotF_t3_deployable_replication_boundary_lift_not_promoted"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id") == "s13_s15_t3_transfer_extension_failed_and_not_promoted"
            and row.get("passed") is True
            and row.get("evidence", {}).get("fivefold_promotion") == "BELOW_SCREEN"
            and row.get("evidence", {}).get("joint_frac_positive", 1.0) < 0.95
            and row.get("evidence", {}).get("s15_cov70_frac_positive", 1.0) < 0.95
            and row.get("evidence", {}).get("s15_cov50_frac_positive", 1.0) < 0.95
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and proresults_audit.get("rejected_temptation_guard_passed") is True
        and proresults_audit.get("rejected_temptation_guard_failures") == []
        and len(proresults_audit.get("rejected_temptation_guard", [])) == 12
        and all(
            row.get("passed") is True
            for row in proresults_audit.get("rejected_temptation_guard", [])
        )
        and proresults_audit.get("checks_passed") is True
        and proresults_audit.get("check_failures") == []
        and len(proresults_audit.get("checks", []))
        == (
            len(proresults_audit.get("completion_audit_checklist", []))
            + len(proresults_audit.get("explicit_directive_checklist", []))
            + len(proresults_audit.get("rejected_temptation_guard", []))
        )
        and {row.get("check_group") for row in proresults_audit.get("checks", [])}
        == {
            "completion_audit_checklist",
            "explicit_directive_checklist",
            "rejected_temptation_guard",
        }
        and all(
            row.get("passed") is True and row.get("check_id")
            for row in proresults_audit.get("checks", [])
        )
        and proresults_audit.get("goal_complete") is False
        and len(proresults_audit.get("numbered_prompt_checklist", [])) == 12
        and [row.get("rank") for row in proresults_audit.get("numbered_prompt_checklist", [])]
        == list(range(1, 13))
        and all(
            str(row.get("status", "")).startswith(("covered", "blocked"))
            for row in proresults_audit.get("numbered_prompt_checklist", [])
        )
        and proresults_audit.get("external_access_state", {}).get("compute_ready_route_count") == 0
        and proresults_audit.get("external_access_state", {}).get("top_priority_route")
        == "PPMI / Verily Study Watch"
        and proresults_audit.get("external_access_state", {}).get(
            "generic_schema_probe_report_validator"
        )
        == "scripts/validate_schema_probe_report.py"
        and proresults_audit.get("external_access_state", {}).get(
            "generic_fill_checklist"
        )
        == "scripts/show_access_request_fill_checklist.py"
        and proresults_audit.get("external_access_state", {}).get(
            "generic_fill_checklist_decision"
        )
        == "access_request_fill_checklist_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "generic_fill_checklist_route_count"
        )
        == 6
        and proresults_audit.get("external_access_state", {}).get(
            "external_submission_index"
        )
        == "results/external_access_submission_index_20260515.md"
        and proresults_audit.get("external_access_state", {}).get(
            "external_submission_index_writer"
        )
        == "scripts/write_external_access_submission_index.py"
        and proresults_audit.get("external_access_state", {}).get(
            "external_submission_index_decision"
        )
        == "external_access_submission_index_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "external_lifecycle_status"
        )
        == "scripts/show_external_access_lifecycle.py"
        and proresults_audit.get("external_access_state", {}).get(
            "external_lifecycle_status_decision"
        )
        == "external_access_lifecycle_status_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "external_schema_probe_handoff"
        )
        == "results/external_schema_probe_handoff_20260515.md"
        and proresults_audit.get("external_access_state", {}).get(
            "external_schema_probe_handoff_writer"
        )
        == "scripts/write_external_schema_probe_handoff.py"
        and proresults_audit.get("external_access_state", {}).get(
            "external_schema_probe_handoff_decision"
        )
        == "external_schema_probe_handoff_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "external_schema_probe_handoff_route_count"
        )
        == 6
        and proresults_audit.get("external_access_state", {}).get(
            "generic_schema_probe_report_validator_decision"
        )
        == "external_schema_probe_report_validator_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "generic_schema_probe_report_validator_route_count"
        )
        == 6
        and proresults_audit.get("external_access_state", {}).get(
            "generic_target_free_manifest_validator"
        )
        == "scripts/validate_target_free_manifest.py"
        and proresults_audit.get("external_access_state", {}).get(
            "generic_target_free_manifest_validator_decision"
        )
        == "external_target_free_manifest_validator_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "generic_target_free_manifest_validator_route_count"
        )
        == 6
        and proresults_audit.get("external_access_state", {}).get(
            "external_target_free_manifest_templates"
        )
        == "results/external_target_free_manifest_templates_20260515.md"
        and proresults_audit.get("external_access_state", {}).get(
            "external_target_free_manifest_templates_writer"
        )
        == "scripts/write_external_target_free_manifest_templates.py"
        and proresults_audit.get("external_access_state", {}).get(
            "external_target_free_manifest_templates_decision"
        )
        == "external_target_free_manifest_templates_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "external_target_free_manifest_templates_route_count"
        )
        == 6
        and proresults_audit.get("external_access_state", {}).get(
            "external_zeroshot_blueprint_handoff"
        )
        == "results/external_zeroshot_blueprint_handoff_20260515.md"
        and proresults_audit.get("external_access_state", {}).get(
            "external_zeroshot_blueprint_handoff_writer"
        )
        == "scripts/write_external_zeroshot_blueprint_handoff.py"
        and proresults_audit.get("external_access_state", {}).get(
            "external_zeroshot_blueprint_handoff_decision"
        )
        == "external_zeroshot_blueprint_handoff_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "external_zeroshot_blueprint_handoff_route_count"
        )
        == 6
        and proresults_audit.get("external_access_state", {}).get(
            "external_formula_sha_templates"
        )
        == "results/external_formula_sha_templates_20260515.md"
        and proresults_audit.get("external_access_state", {}).get(
            "external_formula_sha_templates_writer"
        )
        == "scripts/write_external_formula_sha_templates.py"
        and proresults_audit.get("external_access_state", {}).get(
            "external_formula_sha_record_validator"
        )
        == "scripts/validate_external_formula_sha_record.py"
        and proresults_audit.get("external_access_state", {}).get(
            "external_formula_sha_templates_decision"
        )
        == "external_formula_sha_templates_ready"
        and proresults_audit.get("external_access_state", {}).get(
            "external_formula_sha_templates_route_count"
        )
        == 6
        and any(
            row.get("id")
            == "queued_external_schema_probe_reports_have_generic_content_free_preflight"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id") == "queued_external_access_requests_have_generic_fill_checklist"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id") == "queued_external_access_requests_have_stable_submission_index"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id") == "queued_external_access_requests_have_all_route_lifecycle_status"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id")
            == "queued_external_schema_probe_handoff_is_generic_and_content_free"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id")
            == "queued_external_target_free_manifests_have_generic_content_free_preflight"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id")
            == "queued_external_target_free_manifest_templates_are_generic_and_content_free"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id")
            == "queued_external_zeroshot_blueprint_handoff_is_generic_and_content_free"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id")
            == "queued_external_formula_sha_templates_are_generic_and_content_free"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and any(
            row.get("id") == "current_verified_next_action_is_ppmi_submission_not_compute"
            and row.get("passed") is True
            for row in proresults_audit.get("completion_audit_checklist", [])
        )
        and proresults_audit.get("current_verified_next_action", {}).get("goal_complete")
        is False
        and expected_lifecycle_action is not None
        and proresults_audit.get("current_verified_next_action", {}).get(
            "next_action", {}
        ).get("action_id") == expected_lifecycle_action_id
        and proresults_audit.get("current_verified_next_action", {}).get(
            "next_action", {}
        ).get("safe_to_execute_code_now") == expected_lifecycle_action[1]
        and proresults_audit.get("current_verified_next_action", {}).get(
            "access_lifecycle_current_action", {}
        ).get("action") == expected_lifecycle_action[0]
        and proresults_audit.get("current_verified_next_action", {}).get(
            "pre_submission_handoff", {}
        ).get("completed_package_validator")
        == "scripts/validate_ppmi_verily_submission_package.py"
        and proresults_t1_best.get("source") == "X4 equal-weight 2-bag V2+V3-GSP"
        and approx_equal(proresults_t1_best.get("ccc"), 0.7345218264, 1e-6)
        and approx_equal(proresults_t1_best.get("delta_vs_iter34"), 0.0174839861, 1e-6)
        and approx_equal(proresults_t1_best.get("frac_positive"), 0.91, 1e-6)
        and proresults_t1_best.get("passes_gate") is False
        and "No T1 full-cohort candidate beats iter34"
        in " ".join(proresults_audit.get("hard_gaps", []))
        and "No T3 full-cohort candidate beats iter47"
        in " ".join(proresults_audit.get("hard_gaps", []))
        and ppmi_packet_audit.get("passed") is True
        and ppmi_packet_audit.get("hard_failures") == []
        and ppmi_packet_audit.get("checks", {}).get("official_sources", {}).get("passed")
        is True
        and ppmi_packet_audit.get("checks", {}).get("tier3_submission", {}).get("passed")
        is True
        and ppmi_packet_audit.get("checks", {}).get("required_packet_fields", {}).get("passed")
        is True
        and ppmi_packet_audit.get("checks", {}).get("proresults_external_blueprint", {}).get("passed")
        is True
        and ppmi_submit_format_audit.get("passed") is True
        and ppmi_submit_format_audit.get("decision") == "ppmi_verily_word_template_ready_to_fill"
        and ppmi_submit_format_audit.get("output_docx")
        == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
        and ppmi_submit_format_audit.get("checks", {}).get("official_tier3_terms", {}).get("passed")
        is True
        and ppmi_submit_format_audit.get("checks", {}).get("proresults_blueprint_terms", {}).get("passed")
        is True
        and ppmi_submit_format_audit.get("checks", {}).get("compute_boundary_terms", {}).get("passed")
        is True
        and ppmi_submit_format_audit.get("goal_complete") is False
        and ppmi_email_template_audit.get("passed") is True
        and ppmi_email_template_audit.get("decision") == "ppmi_verily_submission_email_template_ready"
        and ppmi_email_template_audit.get("template") == "scripts/ppmi_verily_submission_email_template.md"
        and ppmi_email_template_audit.get("checks", {}).get("submission_route", {}).get("passed")
        is True
        and ppmi_email_template_audit.get("checks", {}).get("compute_boundary", {}).get("passed")
        is True
        and ppmi_email_template_audit.get("checks", {}).get("submission_recorder", {}).get("passed")
        is True
        and ppmi_email_template_audit.get("checks", {}).get("completed_email_preflight", {}).get("passed")
        is True
        and ppmi_email_template_audit.get("checks", {}).get("completed_package_preflight", {}).get("passed")
        is True
        and ppmi_email_template_audit.get("goal_complete") is False
        and ppmi_email_validator_audit.get("passed") is True
        and ppmi_email_validator_audit.get("decision") == "ppmi_verily_submission_email_validator_ready"
        and ppmi_email_validator_audit.get("validator") == "scripts/validate_ppmi_verily_submission_email.py"
        and ppmi_email_validator_audit.get("goal_complete") is False
        and any(
            row.get("name") == "validator output does not echo completed email path or filename"
            and row.get("passed") is True
            for row in ppmi_email_validator_audit.get("checks", [])
        )
        and ppmi_package_validator_audit.get("passed") is True
        and ppmi_package_validator_audit.get("decision") == "ppmi_verily_submission_package_validator_ready"
        and ppmi_package_validator_audit.get("validator") == "scripts/validate_ppmi_verily_submission_package.py"
        and ppmi_package_validator_audit.get("not_a_submission_record") is True
        and ppmi_package_validator_audit.get("not_access_approval") is True
        and ppmi_package_validator_audit.get("not_a_model_result") is True
        and ppmi_package_validator_audit.get("protected_data_included") is False
        and ppmi_package_validator_audit.get("credentials_or_tokens_included") is False
        and ppmi_package_validator_audit.get("goal_complete") is False
        and any(
            row.get("name") == "validator output does not echo package paths or filenames"
            and row.get("passed") is True
            for row in ppmi_package_validator_audit.get("checks", [])
        )
        and ppmi_user_fill_checklist_audit.get("passed") is True
        and ppmi_user_fill_checklist_audit.get("decision") == "ppmi_verily_user_fill_checklist_ready"
        and ppmi_user_fill_checklist_audit.get("checklist") == "scripts/ppmi_verily_user_fill_checklist.md"
        and ppmi_user_fill_checklist_audit.get("required_placeholder_count")
        == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
        and ppmi_user_fill_checklist_audit.get("packet_field_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
        and ppmi_user_fill_checklist_audit.get("email_field_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
        and ppmi_user_fill_checklist_audit.get("submission_metadata_field_count")
        == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
        and len(ppmi_user_fill_checklist_audit.get("required_placeholders", []))
        == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
        and len(ppmi_user_fill_checklist_audit.get("packet_fields", [])) == EXPECTED_PPMI_PACKET_FIELD_COUNT
        and len(ppmi_user_fill_checklist_audit.get("email_fields", [])) == EXPECTED_PPMI_EMAIL_FIELD_COUNT
        and ppmi_user_fill_checklist_audit.get("submission_metadata_placeholders")
        == [
            "<ISO8601_UTC>",
            "<non_protected_channel>",
            "<non_protected_submitter>",
            "<non_protected_receipt>",
        ]
        and ppmi_user_fill_checklist_audit.get("completed_packet_included") is False
        and ppmi_user_fill_checklist_audit.get("protected_data_included") is False
        and ppmi_user_fill_checklist_audit.get("goal_complete") is False
        and ppmi_schema_probe_checklist_audit.get("passed") is True
        and ppmi_schema_probe_checklist_audit.get("decision") == "ppmi_verily_schema_probe_checklist_ready"
        and ppmi_schema_probe_checklist_audit.get("checklist") == "scripts/ppmi_verily_schema_probe_checklist.md"
        and ppmi_schema_probe_checklist_audit.get("schema_probe_artifact_created") is False
        and ppmi_schema_probe_checklist_audit.get("protected_data_included") is False
        and ppmi_schema_probe_checklist_audit.get("goal_complete") is False
        and "do not use before data-owner approval" in ppmi_schema_probe_checklist.lower()
        and "scripts/record_schema_probe_report.py" in ppmi_schema_probe_checklist
        and "scripts/ppmi_verily_schema_probe_report_template.md" in ppmi_schema_probe_checklist
        and "scripts/validate_ppmi_verily_target_free_manifest.py" in ppmi_schema_probe_checklist
        and ppmi_schema_probe_template_audit.get("passed") is True
        and ppmi_schema_probe_template_audit.get("decision") == "ppmi_verily_schema_probe_report_template_ready"
        and ppmi_schema_probe_template_audit.get("template")
        == "scripts/ppmi_verily_schema_probe_report_template.md"
        and ppmi_schema_probe_template_audit.get("schema_probe_artifact_created") is False
        and ppmi_schema_probe_template_audit.get("protected_data_included") is False
        and ppmi_schema_probe_template_audit.get("goal_complete") is False
        and "post-approval scratch template" in ppmi_schema_probe_template.lower()
        and "do not use before data-owner approval" in ppmi_schema_probe_template.lower()
        and "do not commit a filled copy" in ppmi_schema_probe_template.lower()
        and "scripts/record_schema_probe_report.py" in ppmi_schema_probe_template
        and "scripts/validate_ppmi_verily_schema_probe_report.py" in ppmi_schema_probe_template
        and "scripts/validate_ppmi_verily_target_free_manifest.py" in ppmi_schema_probe_template
        and ppmi_schema_probe_report_validator_audit.get("passed") is True
        and ppmi_schema_probe_report_validator_audit.get("decision")
        == "ppmi_verily_schema_probe_report_validator_ready"
        and ppmi_schema_probe_report_validator_audit.get("validator")
        == "scripts/validate_ppmi_verily_schema_probe_report.py"
        and ppmi_schema_probe_report_validator_audit.get("not_a_schema_probe_artifact") is True
        and ppmi_schema_probe_report_validator_audit.get("protected_data_included") is False
        and ppmi_schema_probe_report_validator_audit.get("goal_complete") is False
        and ppmi_target_free_manifest_validator_audit.get("passed") is True
        and ppmi_target_free_manifest_validator_audit.get("decision")
        == "ppmi_verily_target_free_manifest_validator_ready"
        and ppmi_target_free_manifest_validator_audit.get("template")
        == "scripts/ppmi_verily_target_free_manifest_template.json"
        and ppmi_target_free_manifest_validator_audit.get("validator")
        == "scripts/validate_ppmi_verily_target_free_manifest.py"
        and ppmi_target_free_manifest_validator_audit.get("not_a_feature_manifest_artifact") is True
        and ppmi_target_free_manifest_validator_audit.get("not_a_schema_probe_artifact") is True
        and ppmi_target_free_manifest_validator_audit.get("not_a_preregistration") is True
        and ppmi_target_free_manifest_validator_audit.get("protected_data_included") is False
        and ppmi_target_free_manifest_validator_audit.get("credentials_or_tokens_included") is False
        and ppmi_target_free_manifest_validator_audit.get("goal_complete") is False
        and ppmi_completed_packet_validator_audit.get("passed") is True
        and ppmi_completed_packet_validator_audit.get("decision")
        == "ppmi_verily_completed_packet_validator_ready"
        and ppmi_completed_packet_validator_audit.get("validator")
        == "scripts/validate_ppmi_verily_completed_packet.py"
        and ppmi_completed_packet_validator_audit.get("goal_complete") is False
        and any(
            row.get("name") == "validator output does not echo completed packet path or filename"
            and row.get("passed") is True
            for row in ppmi_completed_packet_validator_audit.get("checks", [])
        )
        and any(
            row.get("name") == "synthetic completed packet passes without recording content"
            and row.get("passed") is True
            and row.get("evidence", {}).get("packet_identity_redacted") is True
            and row.get("evidence", {}).get("packet_path_reported") is False
            for row in ppmi_completed_packet_validator_audit.get("checks", [])
        )
        and ppmi_submission_bundle.get("passed") is True
        and ppmi_submission_bundle.get("decision") == "ppmi_verily_submission_bundle_ready"
        and ppmi_submission_bundle.get("completed_packet_included") is False
        and ppmi_submission_bundle.get("protected_data_included") is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("completed_packet_included")
        is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("completed_email_included")
        is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("protected_data_included")
        is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("credentials_or_tokens_included")
        is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("local_completed_paths_reported")
        is False
        and ppmi_submission_bundle.get("fill_fields", {}).get("source_checklist")
        == "scripts/ppmi_verily_user_fill_checklist.md"
        and ppmi_submission_bundle.get("fill_fields", {}).get("packet_field_count") == 13
        and ppmi_submission_bundle.get("fill_fields", {}).get("email_field_count") == 12
        and ppmi_submission_bundle.get("fill_fields", {}).get("submission_metadata_field_count") == 4
        and any(
            step.get("step_id") == "preflight_completed_package"
            and "scripts/validate_ppmi_verily_submission_package.py" in step.get("tools", [])
            for step in ppmi_submission_bundle.get("next_steps", [])
        )
        and any(
            step.get("step_id") == "record_submission_metadata"
            and "scripts/record_access_submission.py" in step.get("command_template", "")
            for step in ppmi_submission_bundle.get("next_steps", [])
        )
        and any(
            step.get("step_id") == "record_approval_metadata"
            and "scripts/record_access_approval.py" in step.get("command_template", "")
            and step.get("blocked_until_approval") is True
            and step.get("protected_compute_allowed") is False
            for step in ppmi_submission_bundle.get("next_steps", [])
        )
        and ppmi_submission_bundle.get("goal_complete") is False
        and (
            lifecycle_state != "packet_ready"
            or (
                ppmi_current_submission_handoff.get("passed") is True
                and ppmi_current_submission_handoff.get("decision")
                == "ppmi_verily_current_submission_handoff_ready"
                and ppmi_current_submission_handoff.get("goal_complete") is False
                and ppmi_current_submission_handoff.get("not_a_model_result") is True
                and ppmi_current_submission_handoff.get("not_access_approval") is True
                and ppmi_current_submission_handoff.get("not_a_schema_probe_artifact") is True
                and ppmi_current_submission_handoff.get("not_a_preregistration") is True
                and ppmi_current_submission_handoff.get("not_a_submission_record") is True
                and ppmi_current_submission_handoff.get("protected_data_included") is False
                and ppmi_current_submission_handoff.get("credentials_or_tokens_included") is False
                and ppmi_current_submission_handoff.get("record_paths_reported") is False
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("source_checklist")
                == "scripts/ppmi_verily_user_fill_checklist.md"
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("packet_field_count") == 13
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("email_field_count") == 12
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("submission_metadata_field_count") == 4
                and ppmi_current_submission_handoff.get("current_action", {}).get("action_id")
                == "submit_ppmi_verily_access_request"
                and ppmi_current_submission_handoff.get("current_action", {}).get("safe_to_execute_code_now")
                is False
                and ppmi_current_submission_handoff.get("package_artifacts", {}).get(
                    "completed_package_validator"
                )
                == "scripts/validate_ppmi_verily_submission_package.py"
                and ppmi_current_submission_handoff.get("workflow_command_sequence")
                == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                and any(
                    row.get("name")
                    == "current handoff exposes submission and approval metadata recorder commands"
                    and row.get("passed") is True
                    for row in ppmi_current_submission_handoff.get("checks", [])
                )
                and any(
                    row.get("name") == "workflow command sequence is complete and ordered"
                    and row.get("passed") is True
                    for row in ppmi_current_submission_handoff.get("checks", [])
                )
                and ppmi_current_submission_handoff.get("hard_failures") == []
            )
        )
        and ppmi_zeroshot_blueprint_audit.get("passed") is True
        and ppmi_zeroshot_blueprint_audit.get("decision") == "ppmi_verily_zeroshot_blueprint_ready"
        and ppmi_zeroshot_blueprint_audit.get("not_a_model_result") is True
        and ppmi_zeroshot_blueprint_audit.get("not_access_approval") is True
        and ppmi_zeroshot_blueprint_audit.get("not_a_schema_probe_artifact") is True
        and ppmi_zeroshot_blueprint_audit.get("not_a_preregistration") is True
        and ppmi_zeroshot_blueprint_audit.get("protected_data_included") is False
        and ppmi_zeroshot_blueprint_audit.get("credentials_or_tokens_included") is False
        and ppmi_zeroshot_blueprint_audit.get("goal_complete") is False
        and any(
            row.get("name")
            == "blueprint is anchored to exact pro-results prompt and rank4 directive"
            and row.get("passed") is True
            for row in ppmi_zeroshot_blueprint_audit.get("checks", [])
        )
        and t3_slotf_replication_audit.get("passed") is True
        and t3_slotf_replication_audit.get("decision") == "slotF_replication_boundary_lift_not_promoted"
        and t3_slotf_replication_audit.get("hard_failures") == []
        and t3_slotf_replication_audit.get("goal_complete") is False
        and all(
            row.get("replicated_gate_pass") is False
            for row in t3_slotf_replication_audit.get("coverage_rows", {}).values()
        )
        and all(
            term.lower() in ppmi_runbook.lower()
            for term in [
                "persistent homology",
                "multifractal",
                "gradientboostingregressor",
                "version 7.0",
                "15 feb 2026",
                "30 days",
                "pdf or word",
            ]
        )
        and all(
            term.lower() in ppmi_packet.lower()
            for term in [
                "persistent homology",
                "multifractal",
                "gradientboostingregressor",
                "no k-search",
                "version 7.0",
                "15 feb 2026",
                "30 days",
                "pdf or word",
            ]
        ),
        {
            "proresults_audit": {
                "all_numbered_items_covered_or_access_blocked": proresults_audit.get(
                    "all_numbered_items_covered_or_access_blocked"
                ),
                "goal_complete": proresults_audit.get("goal_complete"),
                "hard_gaps": proresults_audit.get("hard_gaps"),
                "t1_best_attempt": proresults_t1_best,
                "completion_audit_passed": proresults_audit.get("completion_audit_passed"),
                "completion_audit_failures": proresults_audit.get("completion_audit_failures"),
                "completion_audit_check_count": len(
                    proresults_audit.get("completion_audit_checklist", [])
                ),
                "prompt_source": proresults_audit.get("prompt_source"),
                "explicit_directive_checklist_passed": proresults_audit.get(
                    "explicit_directive_checklist_passed"
                ),
                "explicit_directive_checklist_failures": proresults_audit.get(
                    "explicit_directive_checklist_failures"
                ),
                "explicit_directive_check_count": len(
                    proresults_audit.get("explicit_directive_checklist", [])
                ),
                "rejected_temptation_guard_passed": proresults_audit.get(
                    "rejected_temptation_guard_passed"
                ),
                "rejected_temptation_guard_failures": proresults_audit.get(
                    "rejected_temptation_guard_failures"
                ),
                "checks_passed": proresults_audit.get("checks_passed"),
                "check_failures": proresults_audit.get("check_failures"),
                "combined_check_count": len(proresults_audit.get("checks", [])),
                "external_access_state": proresults_audit.get("external_access_state"),
                "current_verified_next_action": proresults_audit.get(
                    "current_verified_next_action"
                ),
                "next_non_redundant_actions": proresults_audit.get(
                    "next_non_redundant_actions"
                ),
                "s13_s15_check_passed": any(
                    row.get("id") == "s13_s15_t3_transfer_extension_failed_and_not_promoted"
                    and row.get("passed") is True
                    for row in proresults_audit.get("completion_audit_checklist", [])
                ),
            },
            "ppmi_packet_audit": {
                "passed": ppmi_packet_audit.get("passed"),
                "decision": ppmi_packet_audit.get("decision"),
                "proresults_external_blueprint": ppmi_packet_audit.get("checks", {}).get(
                    "proresults_external_blueprint", {}
                ),
                "official_sources": ppmi_packet_audit.get("checks", {}).get("official_sources", {}),
                "tier3_submission": ppmi_packet_audit.get("checks", {}).get("tier3_submission", {}),
                "required_packet_fields": ppmi_packet_audit.get("checks", {}).get(
                    "required_packet_fields", {}
                ),
            },
            "ppmi_submit_format_audit": {
                "passed": ppmi_submit_format_audit.get("passed"),
                "decision": ppmi_submit_format_audit.get("decision"),
                "output_docx": ppmi_submit_format_audit.get("output_docx"),
                "hard_failures": ppmi_submit_format_audit.get("hard_failures"),
            },
            "ppmi_submission_email_template_audit": {
                "passed": ppmi_email_template_audit.get("passed"),
                "decision": ppmi_email_template_audit.get("decision"),
                "template": ppmi_email_template_audit.get("template"),
                "hard_failures": ppmi_email_template_audit.get("hard_failures"),
            },
            "ppmi_submission_email_validator_audit": {
                "passed": ppmi_email_validator_audit.get("passed"),
                "decision": ppmi_email_validator_audit.get("decision"),
                "validator": ppmi_email_validator_audit.get("validator"),
                "hard_failures": ppmi_email_validator_audit.get("hard_failures"),
                "redaction_check_passed": any(
                    row.get("name") == "validator output does not echo completed email path or filename"
                    and row.get("passed") is True
                    for row in ppmi_email_validator_audit.get("checks", [])
                ),
            },
            "ppmi_submission_package_validator_audit": {
                "passed": ppmi_package_validator_audit.get("passed"),
                "decision": ppmi_package_validator_audit.get("decision"),
                "validator": ppmi_package_validator_audit.get("validator"),
                "hard_failures": ppmi_package_validator_audit.get("hard_failures"),
                "redaction_check_passed": any(
                    row.get("name") == "validator output does not echo package paths or filenames"
                    and row.get("passed") is True
                    for row in ppmi_package_validator_audit.get("checks", [])
                ),
            },
            "ppmi_user_fill_checklist_audit": {
                "passed": ppmi_user_fill_checklist_audit.get("passed"),
                "decision": ppmi_user_fill_checklist_audit.get("decision"),
                "checklist": ppmi_user_fill_checklist_audit.get("checklist"),
                "required_placeholder_count": ppmi_user_fill_checklist_audit.get(
                    "required_placeholder_count"
                ),
                "packet_field_count": ppmi_user_fill_checklist_audit.get("packet_field_count"),
                "email_field_count": ppmi_user_fill_checklist_audit.get("email_field_count"),
                "submission_metadata_field_count": ppmi_user_fill_checklist_audit.get(
                    "submission_metadata_field_count"
                ),
                "hard_failures": ppmi_user_fill_checklist_audit.get("hard_failures"),
            },
            "ppmi_schema_probe_checklist_audit": {
                "passed": ppmi_schema_probe_checklist_audit.get("passed"),
                "decision": ppmi_schema_probe_checklist_audit.get("decision"),
                "checklist": ppmi_schema_probe_checklist_audit.get("checklist"),
                "schema_probe_artifact_created": ppmi_schema_probe_checklist_audit.get(
                    "schema_probe_artifact_created"
                ),
                "hard_failures": ppmi_schema_probe_checklist_audit.get("hard_failures"),
            },
            "ppmi_schema_probe_report_template_audit": {
                "passed": ppmi_schema_probe_template_audit.get("passed"),
                "decision": ppmi_schema_probe_template_audit.get("decision"),
                "template": ppmi_schema_probe_template_audit.get("template"),
                "schema_probe_artifact_created": ppmi_schema_probe_template_audit.get(
                    "schema_probe_artifact_created"
                ),
                "hard_failures": ppmi_schema_probe_template_audit.get("hard_failures"),
            },
            "ppmi_schema_probe_report_validator_audit": {
                "passed": ppmi_schema_probe_report_validator_audit.get("passed"),
                "decision": ppmi_schema_probe_report_validator_audit.get("decision"),
                "validator": ppmi_schema_probe_report_validator_audit.get("validator"),
                "hard_failures": ppmi_schema_probe_report_validator_audit.get("hard_failures"),
            },
            "ppmi_target_free_manifest_validator_audit": {
                "passed": ppmi_target_free_manifest_validator_audit.get("passed"),
                "decision": ppmi_target_free_manifest_validator_audit.get("decision"),
                "template": ppmi_target_free_manifest_validator_audit.get("template"),
                "validator": ppmi_target_free_manifest_validator_audit.get("validator"),
                "hard_failures": ppmi_target_free_manifest_validator_audit.get("hard_failures"),
            },
            "ppmi_completed_packet_validator_audit": {
                "passed": ppmi_completed_packet_validator_audit.get("passed"),
                "decision": ppmi_completed_packet_validator_audit.get("decision"),
                "validator": ppmi_completed_packet_validator_audit.get("validator"),
                "hard_failures": ppmi_completed_packet_validator_audit.get("hard_failures"),
                "redaction_check_passed": any(
                    row.get("name")
                    == "validator output does not echo completed packet path or filename"
                    and row.get("passed") is True
                    for row in ppmi_completed_packet_validator_audit.get("checks", [])
                ),
            },
            "ppmi_submission_bundle": {
                "passed": ppmi_submission_bundle.get("passed"),
                "decision": ppmi_submission_bundle.get("decision"),
                "completed_packet_included": ppmi_submission_bundle.get("completed_packet_included"),
                "protected_data_included": ppmi_submission_bundle.get("protected_data_included"),
                "content_boundary": ppmi_submission_bundle.get("content_boundary"),
                "next_steps": ppmi_submission_bundle.get("next_steps"),
            },
            "ppmi_current_submission_handoff": {
                "passed": ppmi_current_submission_handoff.get("passed"),
                "decision": ppmi_current_submission_handoff.get("decision"),
                "current_action": ppmi_current_submission_handoff.get("current_action"),
                "package_artifacts": ppmi_current_submission_handoff.get("package_artifacts"),
                "content_boundary": ppmi_current_submission_handoff.get("content_boundary"),
            },
                "ppmi_zeroshot_blueprint_audit": {
                    "passed": ppmi_zeroshot_blueprint_audit.get("passed"),
                    "decision": ppmi_zeroshot_blueprint_audit.get("decision"),
                    "blueprint": ppmi_zeroshot_blueprint_audit.get("blueprint"),
                    "hard_failures": ppmi_zeroshot_blueprint_audit.get("hard_failures"),
                    "prompt_trace_check_passed": any(
                        row.get("name")
                        == "blueprint is anchored to exact pro-results prompt and rank4 directive"
                        and row.get("passed") is True
                        for row in ppmi_zeroshot_blueprint_audit.get("checks", [])
                    ),
                },
            "t3_slotF_replication_audit": {
                "passed": t3_slotf_replication_audit.get("passed"),
                "decision": t3_slotf_replication_audit.get("decision"),
                "coverage_rows": t3_slotf_replication_audit.get("coverage_rows"),
            },
        },
    )
    v.check(
        "WATCH-PD runbook preserves request-first no-scaffold boundary",
        all(
            s in watchpd_runbook
            for s in [
                "request-gated",
                "Do not build a probe scaffold",
                "C-Path 3DT",
                "WATCH-PD Steering Committee",
                "MDS-UPDRS Part III",
                "subject identifiers",
                "Zero-shot external validation first",
            ]
        ),
        {"runbook": "scripts/watchpd_request_setup.md"},
    )
    v.check(
        "ICICLE runbook preserves request-first no-scaffold boundary",
        all(
            s in icicle_runbook
            for s in [
                "request-gated",
                "Do not build a probe scaffold",
                "MDS-UPDRS Part III",
                "lower-back Axivity AX3",
                "100 Hz",
                "Subject-level grouping",
                "Train on WearGait-PD only",
            ]
        ),
        {"runbook": "scripts/icicle_request_setup.md"},
    )
    v.check(
        "CNS Portugal runbook preserves request-first no-scaffold boundary",
        all(
            s in cns_runbook
            for s in [
                "request-gated",
                "Do not build a probe scaffold",
                "MDS-UPDRS Part III",
                "Axivity AX3",
                "100 Hz",
                "subject/session-grouped",
                "Zero-shot external validation first",
            ]
        ),
        {"runbook": "scripts/cns_portugal_request_setup.md"},
    )
    access_rows = {
        row.get("name"): row
        for row in external_access_readiness.get("routes", [])
    }
    v.check(
        "external access readiness audit leaves no pre-access compute route",
        external_access_readiness.get("summary", {}).get("passed") is True
        and external_access_readiness.get("summary", {}).get("application_packet_ready_count") == 6
        and external_access_readiness.get("summary", {}).get("compute_ready_route_count") == 0
        and external_access_readiness.get("summary", {}).get("hard_failure_count") == 0
        and external_access_readiness.get("summary", {}).get("top_priority_route") == "PPMI / Verily Study Watch"
        and external_access_readiness.get("summary", {}).get("ppmi_submission_support_ready") is True
        and external_access_readiness.get("decision") == "access_packets_ready_no_compute"
        and access_rows.get("PPMI / Verily Study Watch", {}).get("action_packet_ready") is True
        and access_rows.get("Personalized Parkinson Project / PD Virtual Motor Exam", {}).get("action_packet_ready") is True
        and access_rows.get("MJFF Levodopa Response / Hssayeni", {}).get("action_packet_ready") is True
        and all(row.get("remote_job_allowed_now") is False for row in external_access_readiness.get("routes", []))
        and all(row.get("scaffold_allowed_now") is False for row in external_access_readiness.get("routes", []))
        and "Do not build a probe scaffold" in ppp_runbook
        and "read-only" in ppp_runbook
        and "Do not run a download" in hssayeni_runbook
        and "read-only probe" in hssayeni_runbook,
        {
            "summary": external_access_readiness.get("summary"),
            "decision": external_access_readiness.get("decision"),
            "route_actions": {
                name: {
                    "priority": row.get("priority"),
                    "action_packet_ready": row.get("action_packet_ready"),
                    "remote_job_allowed_now": row.get("remote_job_allowed_now"),
                    "runbook": row.get("runbook", {}).get("path"),
                    "submission_support": row.get("submission_support"),
                }
                for name, row in access_rows.items()
            },
        },
    )
    v.check(
        "external access queue exposes generic packet preflight while keeping compute blocked",
        access_request_packet_validator_audit.get("passed") is True
        and access_request_packet_validator_audit.get("decision")
        == "access_request_packet_validator_ready"
        and access_request_packet_validator_audit.get("validator")
        == "scripts/validate_access_request_packet.py"
        and len(access_request_packet_validator_audit.get("route_results", {})) == 6
        and access_request_packet_validator_audit.get("not_a_submission_record") is True
        and access_request_packet_validator_audit.get("not_access_approval") is True
        and access_request_packet_validator_audit.get("not_a_schema_probe_artifact") is True
        and access_request_packet_validator_audit.get("not_a_model_result") is True
        and access_request_packet_validator_audit.get("goal_complete") is False
        and access_request_packet_validator_audit.get("protected_data_included") is False
        and access_request_packet_validator_audit.get("credentials_or_tokens_included") is False
        and access_request_packet_validator_audit.get("hard_failures") == []
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("goal_complete") is False
        and external_access_queue_status_audit.get("not_a_model_result") is True
        and external_access_queue_status_audit.get("source_audit")
        == "results/access_submission_tracker_20260509.json"
        and external_access_queue_status_audit.get("packet_validator_audit")
        == "results/access_request_packet_validator_audit_20260515.json"
        and external_access_queue_status_audit.get("summary", {}).get("submit_ready_route_count") == 6
        and external_access_queue_status_audit.get("summary", {}).get("compute_ready_route_count") == 0
        and external_access_queue_status_audit.get("summary", {}).get("hard_failure_count") == 0
        and external_access_queue_status_audit.get("content_boundary", {}).get("completed_packets_included")
        is False
        and external_access_queue_status_audit.get("content_boundary", {}).get("protected_data_included")
        is False
        and external_access_queue_status_audit.get("content_boundary", {}).get("record_paths_reported")
        is False
        and external_queue_ppmi_formula_gate.get("validator_gate")
        == "ppmi_route_specific_formula_contract"
        and external_queue_ppmi_formula_gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_formula_contract"]
        and external_queue_ppmi_formula_gate.get("track_c_fixed_branch", {}).get("K") == 250
        and external_queue_ppmi_formula_gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        and external_queue_ppmi_result_gate.get("validator_gate")
        == "ppmi_route_specific_result_contract"
        and external_queue_ppmi_result_gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_result_contract"]
        and external_queue_ppmi_result_gate.get("track_c_fixed_branch", {}).get("K") == 250
        and external_queue_ppmi_result_gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "packet_validator": {
                "decision": access_request_packet_validator_audit.get("decision"),
                "route_count": len(access_request_packet_validator_audit.get("route_results", {})),
                "hard_failures": access_request_packet_validator_audit.get("hard_failures"),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "summary": external_access_queue_status_audit.get("summary"),
                "content_boundary": external_access_queue_status_audit.get("content_boundary"),
                "ppmi_contract_gates": external_queue_ppmi_gates,
            },
        },
    )
    v.check(
        "external access queue exposes generic fill checklist while keeping compute blocked",
        access_request_fill_checklist_audit.get("passed") is True
        and access_request_fill_checklist_audit.get("decision")
        == "access_request_fill_checklist_ready"
        and access_request_fill_checklist_audit.get("script")
        == "scripts/show_access_request_fill_checklist.py"
        and access_request_fill_checklist_audit.get("route_count") == 6
        and access_request_fill_checklist_audit.get("not_a_submission_record") is True
        and access_request_fill_checklist_audit.get("not_access_approval") is True
        and access_request_fill_checklist_audit.get("not_a_schema_probe_artifact") is True
        and access_request_fill_checklist_audit.get("not_a_feature_manifest_artifact") is True
        and access_request_fill_checklist_audit.get("not_a_model_result") is True
        and access_request_fill_checklist_audit.get("goal_complete") is False
        and access_request_fill_checklist_audit.get("protected_data_included") is False
        and access_request_fill_checklist_audit.get("credentials_or_tokens_included") is False
        and access_request_fill_checklist_audit.get("hard_failures") == []
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("fill_checklist_audit")
        == "results/access_request_fill_checklist_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "fill_checklist": {
                "decision": access_request_fill_checklist_audit.get("decision"),
                "route_count": access_request_fill_checklist_audit.get("route_count"),
                "hard_failures": access_request_fill_checklist_audit.get("hard_failures"),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "fill_checklist_audit": external_access_queue_status_audit.get(
                    "fill_checklist_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes a stable submission index while keeping compute blocked",
        external_access_submission_index_audit.get("passed") is True
        and external_access_submission_index_audit.get("decision")
        == "external_access_submission_index_ready"
        and external_access_submission_index_audit.get("writer")
        == "scripts/write_external_access_submission_index.py"
        and external_access_submission_index_audit.get("index_json")
        == "results/external_access_submission_index_20260515.json"
        and external_access_submission_index_audit.get("index_markdown")
        == "results/external_access_submission_index_20260515.md"
        and external_access_submission_index_audit.get("not_a_submission_record") is True
        and external_access_submission_index_audit.get("not_access_approval") is True
        and external_access_submission_index_audit.get("not_a_schema_probe_artifact") is True
        and external_access_submission_index_audit.get("not_a_feature_manifest_artifact") is True
        and external_access_submission_index_audit.get("not_a_model_result") is True
        and external_access_submission_index_audit.get("goal_complete") is False
        and external_access_submission_index_audit.get("protected_data_included") is False
        and external_access_submission_index_audit.get("credentials_or_tokens_included") is False
        and external_access_submission_index_audit.get("hard_failures") == []
        and any(
            row.get("name") == "every route exposes an ordered workflow command sequence"
            and row.get("passed") is True
            and row.get("evidence", {}).get("workflow_by_route", {}).get("ppmi_verily")
            == [
                "validate_completed_packet",
                "validate_completed_email",
                "validate_completed_package",
                "record_submission_metadata",
                "record_approval_metadata",
                "validate_schema_probe_report",
                "validate_target_free_manifest",
                "validate_formula_sha_record",
                "validate_zeroshot_result_record",
            ]
            for row in external_access_submission_index_audit.get("checks", [])
        )
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("submission_index_audit")
        == "results/external_access_submission_index_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "submission_index": {
                "decision": external_access_submission_index_audit.get("decision"),
                "index_markdown": external_access_submission_index_audit.get("index_markdown"),
                "hard_failures": external_access_submission_index_audit.get("hard_failures"),
                "workflow_check": next(
                    (
                        row
                        for row in external_access_submission_index_audit.get("checks", [])
                        if row.get("name")
                        == "every route exposes an ordered workflow command sequence"
                    ),
                    {},
                ),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "submission_index_audit": external_access_queue_status_audit.get(
                    "submission_index_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes all-route lifecycle status while keeping compute blocked",
        external_access_lifecycle_status_audit.get("passed") is True
        and external_access_lifecycle_status_audit.get("decision")
        == "external_access_lifecycle_status_ready"
        and external_access_lifecycle_status_audit.get("status_helper")
        == "scripts/show_external_access_lifecycle.py"
        and external_access_lifecycle_status_audit.get("not_a_submission_record") is True
        and external_access_lifecycle_status_audit.get("not_access_approval") is True
        and external_access_lifecycle_status_audit.get("not_a_schema_probe_artifact") is True
        and external_access_lifecycle_status_audit.get("not_a_model_result") is True
        and external_access_lifecycle_status_audit.get("goal_complete") is False
        and external_access_lifecycle_status_audit.get("protected_data_included") is False
        and external_access_lifecycle_status_audit.get("credentials_or_tokens_included") is False
        and external_access_lifecycle_status_audit.get("hard_failures") == []
        and any(
            row.get("name")
            == "every route exposes an ordered lifecycle workflow command sequence"
            and row.get("passed") is True
            and row.get("evidence", {}).get("default_workflow_by_route", {}).get("ppmi_verily")
            == [
                "validate_completed_packet",
                "validate_completed_email",
                "validate_completed_package",
                "record_submission_metadata",
                "record_approval_metadata",
                "validate_schema_probe_report",
                "validate_target_free_manifest",
                "validate_formula_sha_record",
                "validate_zeroshot_result_record",
            ]
            for row in external_access_lifecycle_status_audit.get("checks", [])
        )
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("lifecycle_status_audit")
        == "results/external_access_lifecycle_status_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "lifecycle_status": {
                "decision": external_access_lifecycle_status_audit.get("decision"),
                "status_helper": external_access_lifecycle_status_audit.get("status_helper"),
                "hard_failures": external_access_lifecycle_status_audit.get("hard_failures"),
                "workflow_check": next(
                    (
                        row
                        for row in external_access_lifecycle_status_audit.get("checks", [])
                        if row.get("name")
                        == "every route exposes an ordered lifecycle workflow command sequence"
                    ),
                    {},
                ),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "lifecycle_status_audit": external_access_queue_status_audit.get(
                    "lifecycle_status_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes generic schema-probe handoff while keeping compute blocked",
        external_schema_probe_handoff_audit.get("passed") is True
        and external_schema_probe_handoff_audit.get("decision")
        == "external_schema_probe_handoff_ready"
        and external_schema_probe_handoff_audit.get("writer")
        == "scripts/write_external_schema_probe_handoff.py"
        and external_schema_probe_handoff_audit.get("handoff_json")
        == "results/external_schema_probe_handoff_20260515.json"
        and external_schema_probe_handoff_audit.get("handoff_markdown")
        == "results/external_schema_probe_handoff_20260515.md"
        and external_schema_probe_handoff_audit.get("route_count") == 6
        and external_schema_probe_handoff_audit.get("not_a_submission_record") is True
        and external_schema_probe_handoff_audit.get("not_access_approval") is True
        and external_schema_probe_handoff_audit.get("not_a_schema_probe_artifact") is True
        and external_schema_probe_handoff_audit.get("not_a_feature_manifest_artifact") is True
        and external_schema_probe_handoff_audit.get("not_a_preregistration") is True
        and external_schema_probe_handoff_audit.get("not_a_model_result") is True
        and external_schema_probe_handoff_audit.get("goal_complete") is False
        and external_schema_probe_handoff_audit.get("protected_data_included") is False
        and external_schema_probe_handoff_audit.get("credentials_or_tokens_included") is False
        and external_schema_probe_handoff_audit.get("hard_failures") == []
        and external_schema_probe_handoff_audit.get(
            "post_approval_workflow_step_ids_by_route", {}
        ).get("ppmi_verily")
        == EXPECTED_SCHEMA_POST_APPROVAL_WORKFLOW_STEP_IDS
        and all(
            steps == EXPECTED_SCHEMA_POST_APPROVAL_WORKFLOW_STEP_IDS
            for steps in external_schema_probe_handoff_audit.get(
                "post_approval_workflow_step_ids_by_route", {}
            ).values()
        )
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("schema_probe_handoff_audit")
        == "results/external_schema_probe_handoff_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "schema_probe_handoff": {
                "decision": external_schema_probe_handoff_audit.get("decision"),
                "handoff_markdown": external_schema_probe_handoff_audit.get("handoff_markdown"),
                "hard_failures": external_schema_probe_handoff_audit.get("hard_failures"),
                "post_approval_workflow_step_ids_by_route": (
                    external_schema_probe_handoff_audit.get(
                        "post_approval_workflow_step_ids_by_route"
                    )
                ),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "schema_probe_handoff_audit": external_access_queue_status_audit.get(
                    "schema_probe_handoff_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes generic schema-probe report preflight while keeping compute blocked",
        external_schema_probe_report_validator_audit.get("passed") is True
        and external_schema_probe_report_validator_audit.get("decision")
        == "external_schema_probe_report_validator_ready"
        and external_schema_probe_report_validator_audit.get("validator")
        == "scripts/validate_schema_probe_report.py"
        and len(external_schema_probe_report_validator_audit.get("route_results", {})) == 6
        and external_schema_probe_report_validator_audit.get("not_a_submission_record") is True
        and external_schema_probe_report_validator_audit.get("not_access_approval") is True
        and external_schema_probe_report_validator_audit.get("not_a_schema_probe_artifact") is True
        and external_schema_probe_report_validator_audit.get("not_a_model_result") is True
        and external_schema_probe_report_validator_audit.get("goal_complete") is False
        and external_schema_probe_report_validator_audit.get("protected_data_included") is False
        and external_schema_probe_report_validator_audit.get("credentials_or_tokens_included") is False
        and external_schema_probe_report_validator_audit.get("hard_failures") == []
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("schema_probe_report_validator_audit")
        == "results/external_schema_probe_report_validator_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "schema_probe_report_validator": {
                "decision": external_schema_probe_report_validator_audit.get("decision"),
                "route_count": len(external_schema_probe_report_validator_audit.get("route_results", {})),
                "hard_failures": external_schema_probe_report_validator_audit.get("hard_failures"),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "schema_probe_report_validator_audit": external_access_queue_status_audit.get(
                    "schema_probe_report_validator_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes generic target-free manifest preflight while keeping compute blocked",
        external_target_free_manifest_validator_audit.get("passed") is True
        and external_target_free_manifest_validator_audit.get("decision")
        == "external_target_free_manifest_validator_ready"
        and external_target_free_manifest_validator_audit.get("validator")
        == "scripts/validate_target_free_manifest.py"
        and len(external_target_free_manifest_validator_audit.get("route_results", {})) == 6
        and external_target_free_manifest_validator_audit.get("not_a_submission_record") is True
        and external_target_free_manifest_validator_audit.get("not_access_approval") is True
        and external_target_free_manifest_validator_audit.get("not_a_schema_probe_artifact") is True
        and external_target_free_manifest_validator_audit.get("not_a_preregistration") is True
        and external_target_free_manifest_validator_audit.get("not_a_feature_manifest_artifact") is True
        and external_target_free_manifest_validator_audit.get("not_a_model_result") is True
        and external_target_free_manifest_validator_audit.get("goal_complete") is False
        and external_target_free_manifest_validator_audit.get("protected_data_included") is False
        and external_target_free_manifest_validator_audit.get("credentials_or_tokens_included") is False
        and external_target_free_manifest_validator_audit.get("hard_failures") == []
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("target_free_manifest_validator_audit")
        == "results/external_target_free_manifest_validator_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "target_free_manifest_validator": {
                "decision": external_target_free_manifest_validator_audit.get("decision"),
                "route_count": len(external_target_free_manifest_validator_audit.get("route_results", {})),
                "hard_failures": external_target_free_manifest_validator_audit.get("hard_failures"),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "target_free_manifest_validator_audit": external_access_queue_status_audit.get(
                    "target_free_manifest_validator_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes generic target-free manifest templates while keeping compute blocked",
        external_target_free_manifest_templates_audit.get("passed") is True
        and external_target_free_manifest_templates_audit.get("decision")
        == "external_target_free_manifest_templates_ready"
        and external_target_free_manifest_templates_audit.get("writer")
        == "scripts/write_external_target_free_manifest_templates.py"
        and external_target_free_manifest_templates_audit.get("templates_json")
        == "results/external_target_free_manifest_templates_20260515.json"
        and external_target_free_manifest_templates_audit.get("templates_markdown")
        == "results/external_target_free_manifest_templates_20260515.md"
        and external_target_free_manifest_templates_audit.get("route_count") == 6
        and external_target_free_manifest_templates_audit.get("not_a_submission_record") is True
        and external_target_free_manifest_templates_audit.get("not_access_approval") is True
        and external_target_free_manifest_templates_audit.get("not_a_schema_probe_artifact") is True
        and external_target_free_manifest_templates_audit.get("not_a_feature_manifest_artifact") is True
        and external_target_free_manifest_templates_audit.get("not_a_preregistration") is True
        and external_target_free_manifest_templates_audit.get("not_a_model_result") is True
        and external_target_free_manifest_templates_audit.get("goal_complete") is False
        and external_target_free_manifest_templates_audit.get("protected_data_included") is False
        and external_target_free_manifest_templates_audit.get("credentials_or_tokens_included") is False
        and external_target_free_manifest_templates_audit.get("hard_failures") == []
        and external_target_free_manifest_templates_audit.get(
            "post_schema_workflow_step_ids_by_route", {}
        ).get("ppmi_verily")
        == EXPECTED_TARGET_FREE_POST_SCHEMA_WORKFLOW_STEP_IDS
        and all(
            steps == EXPECTED_TARGET_FREE_POST_SCHEMA_WORKFLOW_STEP_IDS
            for steps in external_target_free_manifest_templates_audit.get(
                "post_schema_workflow_step_ids_by_route", {}
            ).values()
        )
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("target_free_manifest_templates_audit")
        == "results/external_target_free_manifest_templates_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "target_free_manifest_templates": {
                "decision": external_target_free_manifest_templates_audit.get("decision"),
                "templates_markdown": external_target_free_manifest_templates_audit.get(
                    "templates_markdown"
                ),
                "hard_failures": external_target_free_manifest_templates_audit.get(
                    "hard_failures"
                ),
                "post_schema_workflow_step_ids_by_route": (
                    external_target_free_manifest_templates_audit.get(
                        "post_schema_workflow_step_ids_by_route"
                    )
                ),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "target_free_manifest_templates_audit": external_access_queue_status_audit.get(
                    "target_free_manifest_templates_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes generic zero-shot blueprint handoff while keeping compute blocked",
        external_zeroshot_blueprint_handoff_audit.get("passed") is True
        and external_zeroshot_blueprint_handoff_audit.get("decision")
        == "external_zeroshot_blueprint_handoff_ready"
        and external_zeroshot_blueprint_handoff_audit.get("writer")
        == "scripts/write_external_zeroshot_blueprint_handoff.py"
        and external_zeroshot_blueprint_handoff_audit.get("handoff_json")
        == "results/external_zeroshot_blueprint_handoff_20260515.json"
        and external_zeroshot_blueprint_handoff_audit.get("handoff_markdown")
        == "results/external_zeroshot_blueprint_handoff_20260515.md"
        and external_zeroshot_blueprint_handoff_audit.get("route_count") == 6
        and external_zeroshot_blueprint_handoff_audit.get("not_a_submission_record") is True
        and external_zeroshot_blueprint_handoff_audit.get("not_access_approval") is True
        and external_zeroshot_blueprint_handoff_audit.get("not_a_schema_probe_artifact") is True
        and external_zeroshot_blueprint_handoff_audit.get("not_a_feature_manifest_artifact") is True
        and external_zeroshot_blueprint_handoff_audit.get("not_a_preregistration") is True
        and external_zeroshot_blueprint_handoff_audit.get("not_a_model_result") is True
        and external_zeroshot_blueprint_handoff_audit.get("goal_complete") is False
        and external_zeroshot_blueprint_handoff_audit.get("protected_data_included") is False
        and external_zeroshot_blueprint_handoff_audit.get("credentials_or_tokens_included") is False
        and external_zeroshot_blueprint_handoff_audit.get("hard_failures") == []
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("zeroshot_blueprint_handoff_audit")
        == "results/external_zeroshot_blueprint_handoff_audit_20260515.json"
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "zeroshot_blueprint_handoff": {
                "decision": external_zeroshot_blueprint_handoff_audit.get("decision"),
                "handoff_markdown": external_zeroshot_blueprint_handoff_audit.get(
                    "handoff_markdown"
                ),
                "hard_failures": external_zeroshot_blueprint_handoff_audit.get(
                    "hard_failures"
                ),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "zeroshot_blueprint_handoff_audit": external_access_queue_status_audit.get(
                    "zeroshot_blueprint_handoff_audit"
                ),
            },
        },
    )
    v.check(
        "external access queue exposes PPMI route-specific formula-SHA contract while keeping compute blocked",
        external_formula_sha_templates_audit.get("passed") is True
        and external_formula_sha_templates_audit.get("decision")
        == "external_formula_sha_templates_ready"
        and external_formula_sha_templates_audit.get("writer")
        == "scripts/write_external_formula_sha_templates.py"
        and external_formula_sha_templates_audit.get("validator")
        == "scripts/validate_external_formula_sha_record.py"
        and external_formula_sha_templates_audit.get("templates_json")
        == "results/external_formula_sha_templates_20260515.json"
        and external_formula_sha_templates_audit.get("templates_markdown")
        == "results/external_formula_sha_templates_20260515.md"
        and external_formula_sha_templates_audit.get("template_dir")
        == "results/external_formula_sha_templates_20260515"
        and external_formula_sha_templates_audit.get("route_count") == 6
        and external_formula_sha_templates_audit.get("not_a_submission_record") is True
        and external_formula_sha_templates_audit.get("not_access_approval") is True
        and external_formula_sha_templates_audit.get("not_a_schema_probe_artifact") is True
        and external_formula_sha_templates_audit.get("not_a_feature_manifest_artifact") is True
        and external_formula_sha_templates_audit.get("not_a_preregistration") is True
        and external_formula_sha_templates_audit.get("not_a_model_result") is True
        and external_formula_sha_templates_audit.get("goal_complete") is False
        and external_formula_sha_templates_audit.get("protected_data_included") is False
        and external_formula_sha_templates_audit.get("credentials_or_tokens_included") is False
        and external_formula_sha_templates_audit.get("hard_failures") == []
        and external_formula_sha_templates_audit.get(
            "post_formula_workflow_step_ids_by_route", {}
        ).get("ppmi_verily")
        == EXPECTED_FORMULA_POST_FORMULA_WORKFLOW_STEP_IDS
        and all(
            steps == EXPECTED_FORMULA_POST_FORMULA_WORKFLOW_STEP_IDS
            for steps in external_formula_sha_templates_audit.get(
                "post_formula_workflow_step_ids_by_route", {}
            ).values()
        )
        and external_formula_sha_ppmi.get("ppmi_formula_contract_present") is True
        and external_formula_sha_ppmi.get("ppmi_contract_negative_failed") is True
        and external_formula_sha_ppmi.get("ppmi_bad_contract_hard_failures")
        == ["ppmi_route_specific_formula_contract"]
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("formula_sha_templates_audit")
        == "results/external_formula_sha_templates_audit_20260515.json"
        and external_queue_ppmi_formula_gate.get("validator_gate")
        == "ppmi_route_specific_formula_contract"
        and external_queue_ppmi_formula_gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_formula_contract"]
        and external_queue_ppmi_formula_gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "formula_sha_templates": {
                "decision": external_formula_sha_templates_audit.get("decision"),
                "templates_markdown": external_formula_sha_templates_audit.get(
                    "templates_markdown"
                ),
                "hard_failures": external_formula_sha_templates_audit.get("hard_failures"),
                "post_formula_workflow_step_ids_by_route": (
                    external_formula_sha_templates_audit.get(
                        "post_formula_workflow_step_ids_by_route"
                    )
                ),
                "ppmi_formula_contract_present": external_formula_sha_ppmi.get(
                    "ppmi_formula_contract_present"
                ),
                "ppmi_contract_negative_failed": external_formula_sha_ppmi.get(
                    "ppmi_contract_negative_failed"
                ),
                "ppmi_bad_contract_hard_failures": external_formula_sha_ppmi.get(
                    "ppmi_bad_contract_hard_failures"
                ),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "formula_sha_templates_audit": external_access_queue_status_audit.get(
                    "formula_sha_templates_audit"
                ),
                "ppmi_contract_gate": external_queue_ppmi_formula_gate,
            },
        },
    )
    v.check(
        "external access queue exposes PPMI route-specific zero-shot result contract while keeping compute blocked",
        external_zeroshot_result_templates_audit.get("passed") is True
        and external_zeroshot_result_templates_audit.get("decision")
        == "external_zeroshot_result_templates_ready"
        and external_zeroshot_result_templates_audit.get("writer")
        == "scripts/write_external_zeroshot_result_templates.py"
        and external_zeroshot_result_templates_audit.get("validator")
        == "scripts/validate_external_zeroshot_result_record.py"
        and external_zeroshot_result_templates_audit.get("templates_json")
        == "results/external_zeroshot_result_templates_20260515.json"
        and external_zeroshot_result_templates_audit.get("templates_markdown")
        == "results/external_zeroshot_result_templates_20260515.md"
        and external_zeroshot_result_templates_audit.get("template_dir")
        == "results/external_zeroshot_result_templates_20260515"
        and external_zeroshot_result_templates_audit.get("route_count") == 6
        and external_zeroshot_result_templates_audit.get("not_a_submission_record") is True
        and external_zeroshot_result_templates_audit.get("not_access_approval") is True
        and external_zeroshot_result_templates_audit.get("not_a_schema_probe_artifact") is True
        and external_zeroshot_result_templates_audit.get("not_a_feature_manifest_artifact") is True
        and external_zeroshot_result_templates_audit.get("not_a_preregistration") is True
        and external_zeroshot_result_templates_audit.get("not_a_model_result") is True
        and external_zeroshot_result_templates_audit.get("goal_complete") is False
        and external_zeroshot_result_templates_audit.get("protected_data_included") is False
        and external_zeroshot_result_templates_audit.get("credentials_or_tokens_included") is False
        and external_zeroshot_result_templates_audit.get("hard_failures") == []
        and external_zeroshot_result_templates_audit.get(
            "post_score_reporting_workflow_step_ids_by_route", {}
        ).get("ppmi_verily")
        == EXPECTED_ZEROSHOT_RESULT_POST_SCORE_WORKFLOW_STEP_IDS
        and all(
            steps == EXPECTED_ZEROSHOT_RESULT_POST_SCORE_WORKFLOW_STEP_IDS
            for steps in external_zeroshot_result_templates_audit.get(
                "post_score_reporting_workflow_step_ids_by_route", {}
            ).values()
        )
        and external_zeroshot_result_ppmi.get("ppmi_result_contract_present") is True
        and external_zeroshot_result_ppmi.get("ppmi_contract_negative_failed") is True
        and external_zeroshot_result_ppmi.get("ppmi_bad_contract_hard_failures")
        == ["ppmi_route_specific_result_contract"]
        and external_access_queue_status_audit.get("passed") is True
        and external_access_queue_status_audit.get("decision") == "external_access_queue_status_ready"
        and external_access_queue_status_audit.get("zeroshot_result_templates_audit")
        == "results/external_zeroshot_result_templates_audit_20260515.json"
        and external_queue_ppmi_result_gate.get("validator_gate")
        == "ppmi_route_specific_result_contract"
        and external_queue_ppmi_result_gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_result_contract"]
        and external_queue_ppmi_result_gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        and all(row.get("passed") is True for row in external_access_queue_status_audit.get("checks", [])),
        {
            "zeroshot_result_templates": {
                "decision": external_zeroshot_result_templates_audit.get("decision"),
                "templates_markdown": external_zeroshot_result_templates_audit.get(
                    "templates_markdown"
                ),
                "hard_failures": external_zeroshot_result_templates_audit.get(
                    "hard_failures"
                ),
                "post_score_reporting_workflow_step_ids_by_route": (
                    external_zeroshot_result_templates_audit.get(
                        "post_score_reporting_workflow_step_ids_by_route"
                    )
                ),
                "ppmi_result_contract_present": external_zeroshot_result_ppmi.get(
                    "ppmi_result_contract_present"
                ),
                "ppmi_contract_negative_failed": external_zeroshot_result_ppmi.get(
                    "ppmi_contract_negative_failed"
                ),
                "ppmi_bad_contract_hard_failures": external_zeroshot_result_ppmi.get(
                    "ppmi_bad_contract_hard_failures"
                ),
            },
            "queue_status": {
                "decision": external_access_queue_status_audit.get("decision"),
                "zeroshot_result_templates_audit": external_access_queue_status_audit.get(
                    "zeroshot_result_templates_audit"
                ),
                "ppmi_contract_gate": external_queue_ppmi_result_gate,
            },
        },
    )
    v.check(
        "access submission and approval recorders keep PPMI lifecycle compute-blocked",
        access_submission_tracker.get("decision") == "access_submission_tracker_ready"
        and access_submission_tracker.get("summary", {}).get("passed") is True
        and access_submission_tracker.get("summary", {}).get("submit_ready_route_count") == 6
        and access_submission_tracker.get("summary", {}).get("compute_ready_route_count") == 0
        and access_submission_tracker.get("summary", {}).get("hard_failure_count") == 0
        and ppmi_submission_route.get("packet", {}).get("passed") is True
        and ppmi_submission_route.get("remote_job_allowed_now") is False
        and ppmi_submission_route.get("scaffold_allowed_now") is False
        and ppmi_official_recheck.get("official_sources_passed") is True
        and ppmi_official_recheck.get("tier3_submission_passed") is True
        and ppmi_official_recheck.get("required_packet_fields_passed") is True
        and ppmi_submit_format_audit.get("passed") is True
        and ppmi_submit_format_audit.get("decision") == "ppmi_verily_word_template_ready_to_fill"
        and ppmi_email_template_audit.get("passed") is True
        and ppmi_email_template_audit.get("decision") == "ppmi_verily_submission_email_template_ready"
        and ppmi_email_validator_audit.get("passed") is True
        and ppmi_email_validator_audit.get("decision") == "ppmi_verily_submission_email_validator_ready"
        and (ppmi_submission_route.get("completed_package_validator") or {}).get("validator")
        == "scripts/validate_ppmi_verily_submission_package.py"
        and (ppmi_submission_route.get("completed_package_validator") or {}).get("not_a_submission_record")
        is True
        and (ppmi_submission_route.get("completed_package_validator") or {}).get("not_access_approval")
        is True
        and (ppmi_submission_route.get("completed_package_validator") or {}).get("not_a_model_result")
        is True
        and (ppmi_submission_route.get("completed_package_validator") or {}).get("protected_data_included")
        is False
        and ppmi_user_fill_checklist_audit.get("passed") is True
        and ppmi_user_fill_checklist_audit.get("decision") == "ppmi_verily_user_fill_checklist_ready"
        and ppmi_user_fill_checklist_audit.get("required_placeholder_count")
        == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
        and ppmi_user_fill_checklist_audit.get("packet_field_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
        and ppmi_user_fill_checklist_audit.get("email_field_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
        and ppmi_user_fill_checklist_audit.get("submission_metadata_field_count")
        == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
        and ppmi_schema_probe_checklist_audit.get("passed") is True
        and ppmi_schema_probe_checklist_audit.get("decision") == "ppmi_verily_schema_probe_checklist_ready"
        and ppmi_schema_probe_template_audit.get("passed") is True
        and ppmi_schema_probe_template_audit.get("decision") == "ppmi_verily_schema_probe_report_template_ready"
        and ppmi_completed_packet_validator_audit.get("passed") is True
        and ppmi_completed_packet_validator_audit.get("decision") == "ppmi_verily_completed_packet_validator_ready"
        and any(
            row.get("name") == "validator output does not echo completed email path or filename"
            and row.get("passed") is True
            for row in ppmi_email_validator_audit.get("checks", [])
        )
        and any(
            row.get("name") == "validator output does not echo completed packet path or filename"
            and row.get("passed") is True
            for row in ppmi_completed_packet_validator_audit.get("checks", [])
        )
        and ppmi_submission_bundle.get("passed") is True
        and ppmi_submission_bundle.get("decision") == "ppmi_verily_submission_bundle_ready"
        and ppmi_submission_bundle.get("content_boundary", {}).get("completed_packet_included")
        is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("completed_email_included")
        is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("protected_data_included")
        is False
        and ppmi_submission_bundle.get("content_boundary", {}).get("credentials_or_tokens_included")
        is False
        and ppmi_submission_bundle.get("fill_fields", {}).get("source_checklist")
        == "scripts/ppmi_verily_user_fill_checklist.md"
        and ppmi_submission_bundle.get("fill_fields", {}).get("packet_field_count") == 13
        and ppmi_submission_bundle.get("fill_fields", {}).get("email_field_count") == 12
        and ppmi_submission_bundle.get("fill_fields", {}).get("submission_metadata_field_count") == 4
        and any(
            step.get("step_id") == "preflight_completed_package"
            and "scripts/validate_ppmi_verily_submission_package.py" in step.get("tools", [])
            for step in ppmi_submission_bundle.get("next_steps", [])
        )
        and any(
            step.get("step_id") == "record_submission_metadata"
            and "scripts/record_access_submission.py" in step.get("command_template", "")
            for step in ppmi_submission_bundle.get("next_steps", [])
        )
        and any(
            step.get("step_id") == "record_approval_metadata"
            and "scripts/record_access_approval.py" in step.get("command_template", "")
            and step.get("blocked_until_approval") is True
            and step.get("protected_compute_allowed") is False
            for step in ppmi_submission_bundle.get("next_steps", [])
        )
        and (
            lifecycle_state != "packet_ready"
            or (
                ppmi_current_submission_handoff.get("passed") is True
                and ppmi_current_submission_handoff.get("decision")
                == "ppmi_verily_current_submission_handoff_ready"
                and ppmi_current_submission_handoff.get("goal_complete") is False
                and ppmi_current_submission_handoff.get("not_a_model_result") is True
                and ppmi_current_submission_handoff.get("not_access_approval") is True
                and ppmi_current_submission_handoff.get("not_a_schema_probe_artifact") is True
                and ppmi_current_submission_handoff.get("not_a_preregistration") is True
                and ppmi_current_submission_handoff.get("not_a_submission_record") is True
                and ppmi_current_submission_handoff.get("protected_data_included") is False
                and ppmi_current_submission_handoff.get("credentials_or_tokens_included") is False
                and ppmi_current_submission_handoff.get("record_paths_reported") is False
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("source_checklist")
                == "scripts/ppmi_verily_user_fill_checklist.md"
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("packet_field_count") == 13
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("email_field_count") == 12
                and ppmi_current_submission_handoff.get("fill_fields", {}).get("submission_metadata_field_count") == 4
                and ppmi_current_submission_handoff.get("current_action", {}).get("action_id")
                == "submit_ppmi_verily_access_request"
                and ppmi_current_submission_handoff.get("current_action", {}).get("safe_to_execute_code_now")
                is False
                and ppmi_current_submission_handoff.get("package_artifacts", {}).get(
                    "completed_package_validator"
                )
                == "scripts/validate_ppmi_verily_submission_package.py"
                and ppmi_current_submission_handoff.get("workflow_command_sequence")
                == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                and any(
                    row.get("name")
                    == "current handoff exposes submission and approval metadata recorder commands"
                    and row.get("passed") is True
                    for row in ppmi_current_submission_handoff.get("checks", [])
                )
                and any(
                    row.get("name") == "workflow command sequence is complete and ordered"
                    and row.get("passed") is True
                    for row in ppmi_current_submission_handoff.get("checks", [])
                )
                and ppmi_current_submission_handoff.get("hard_failures") == []
            )
        )
        and ppmi_zeroshot_blueprint_audit.get("passed") is True
        and ppmi_zeroshot_blueprint_audit.get("decision") == "ppmi_verily_zeroshot_blueprint_ready"
        and ppmi_zeroshot_blueprint_audit.get("goal_complete") is False
        and access_submission_recorder_audit.get("passed") is True
        and access_submission_recorder_audit.get("decision") == "access_submission_recorder_passed"
        and access_submission_recorder_audit.get("hard_failures") == []
        and access_submission_recorder_audit.get("goal_complete") is False
        and access_submission_recorder_audit.get("not_a_model_result") is True
        and all(row.get("passed") is True for row in access_submission_recorder_audit.get("checks", []))
        and any(
            row.get("name") == "recorder refuses synthetic or audit-only submission sources"
            and row.get("passed") is True
            and row.get("evidence", {}).get("returncode") != 0
            for row in access_submission_recorder_audit.get("checks", [])
        )
        and any(
            row.get("name") == "recorder refuses unfilled submission command-template placeholders"
            and row.get("passed") is True
            and row.get("evidence", {}).get("returncode") != 0
            for row in access_submission_recorder_audit.get("checks", [])
        )
        and "submitted-pending-approval" in access_submission_recorder_audit.get("claim", "")
        and "all protected-data/model actions stay blocked" in access_submission_recorder_audit.get("claim", "")
        and "synthetic or audit-only submission sources are rejected"
        in access_submission_recorder_audit.get("claim", "")
        and "unfilled command-template placeholders are rejected"
        in access_submission_recorder_audit.get("claim", "")
        and access_approval_recorder_audit.get("passed") is True
        and access_approval_recorder_audit.get("decision") == "access_approval_recorder_passed"
        and access_approval_recorder_audit.get("hard_failures") == []
        and access_approval_recorder_audit.get("goal_complete") is False
        and access_approval_recorder_audit.get("not_a_model_result") is True
        and all(row.get("passed") is True for row in access_approval_recorder_audit.get("checks", []))
        and any(
            row.get("name") == "recorder refuses synthetic or audit-only approval sources"
            and row.get("passed") is True
            and row.get("evidence", {}).get("returncode") != 0
            for row in access_approval_recorder_audit.get("checks", [])
        )
        and any(
            row.get("name") == "recorder refuses unfilled approval command-template placeholders"
            and row.get("passed") is True
            and row.get("evidence", {}).get("returncode") != 0
            for row in access_approval_recorder_audit.get("checks", [])
        )
        and "read-only schema probing" in access_approval_recorder_audit.get("claim", "")
        and "canonical updates remain blocked" in access_approval_recorder_audit.get("claim", "")
        and "synthetic or audit-only approval sources are rejected"
        in access_approval_recorder_audit.get("claim", "")
        and "unfilled command-template placeholders are rejected"
        in access_approval_recorder_audit.get("claim", "")
        and schema_probe_recorder_audit.get("passed") is True
        and schema_probe_recorder_audit.get("decision") == "schema_probe_recorder_passed"
        and schema_probe_recorder_audit.get("hard_failures") == []
        and schema_probe_recorder_audit.get("goal_complete") is False
        and schema_probe_recorder_audit.get("not_a_model_result") is True
        and all(row.get("passed") is True for row in schema_probe_recorder_audit.get("checks", []))
        and any(
            row.get("name") == "approval record identity is redacted in schema-probe artifact and errors"
            and row.get("passed") is True
            and row.get("evidence", {}).get("approval_record_identity_redacted") is True
            and row.get("evidence", {}).get("approval_record_path_reported") is False
            and row.get("evidence", {}).get("approval_record_path_present") is False
            and row.get("evidence", {}).get("missing_error_path_echoed") is False
            and row.get("evidence", {}).get("missing_error_filename_echoed") is False
            and row.get("evidence", {}).get("bad_error_path_echoed") is False
            and row.get("evidence", {}).get("bad_error_filename_echoed") is False
            for row in schema_probe_recorder_audit.get("checks", [])
        )
        and any(
            row.get("name") == "synthetic approval record cannot unlock schema-probe recording"
            and row.get("passed") is True
            and row.get("evidence", {}).get("attempt_returncode") != 0
            and row.get("evidence", {}).get("synthetic_error_path_echoed") is False
            and row.get("evidence", {}).get("synthetic_error_filename_echoed") is False
            for row in schema_probe_recorder_audit.get("checks", [])
        )
        and any(
            row.get("name") == "recorder refuses unfilled schema-probe command-template placeholders"
            and row.get("passed") is True
            and row.get("evidence", {}).get("returncode") != 0
            for row in schema_probe_recorder_audit.get("checks", [])
        )
        and "approval-record local identity is redacted" in schema_probe_recorder_audit.get("claim", "")
        and "synthetic audit-only approval records cannot unlock schema-probe recording"
        in schema_probe_recorder_audit.get("claim", "")
        and "unfilled schema-probe command-template placeholders are rejected"
        in schema_probe_recorder_audit.get("claim", "")
        and state_aware_access_lifecycle_ready
        and (
            lifecycle_state != "packet_ready"
            or packet_ready_current_action_support_ready
        )
        and lifecycle_pre_submission_handoff.get("from_tracker") is True
        and lifecycle_pre_submission_handoff.get("checklist")
        == "scripts/ppmi_verily_user_fill_checklist.md"
        and lifecycle_pre_submission_handoff.get("completed_packet_validator")
        == "scripts/validate_ppmi_verily_completed_packet.py"
        and lifecycle_pre_submission_handoff.get("completed_email_validator")
        == "scripts/validate_ppmi_verily_submission_email.py"
        and lifecycle_pre_submission_handoff.get("completed_package_validator")
        == "scripts/validate_ppmi_verily_submission_package.py"
        and lifecycle_pre_submission_handoff.get("submission_email_template")
        == "scripts/ppmi_verily_submission_email_template.md"
        and lifecycle_pre_submission_handoff.get("not_a_submission_record") is True
        and lifecycle_pre_submission_handoff.get("not_access_approval") is True
        and lifecycle_pre_submission_handoff.get("not_a_model_result") is True
        and lifecycle_pre_submission_handoff.get("protected_data_included") is False
        and lifecycle_pre_submission_handoff.get("credentials_or_tokens_included") is False
        and "scripts/record_access_submission.py"
        in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "<ISO8601_UTC>"
        in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "<non_protected_channel>"
        in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "<non_protected_submitter>"
        in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "<non_protected_receipt>"
        in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "--pre-submission-preflight-passed"
        in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "<portal-or-email>"
        not in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "<approved-submitter>"
        not in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "<non-protected-receipt>"
        not in lifecycle_pre_submission_handoff.get("record_submission_command_template", "")
        and "scripts/record_access_approval.py"
        in lifecycle_pre_submission_handoff.get("record_approval_command_template", "")
        and "<ISO8601_UTC>"
        in lifecycle_pre_submission_handoff.get("record_approval_command_template", "")
        and "<non_protected_approval_source>"
        in lifecycle_pre_submission_handoff.get("record_approval_command_template", "")
        and "<approval-notice>"
        not in lifecycle_pre_submission_handoff.get("record_approval_command_template", "")
        and "<non-protected-approval-source>"
        not in lifecycle_pre_submission_handoff.get("record_approval_command_template", "")
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get("checklist")
        == "scripts/ppmi_verily_schema_probe_checklist.md"
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get("audit_passed")
        is True
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_template"
        )
        == "scripts/ppmi_verily_schema_probe_report_template.md"
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_template_audit_passed"
        )
        is True
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_validator"
        )
        == "scripts/validate_ppmi_verily_schema_probe_report.py"
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_validator_audit_passed"
        )
        is True
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "schema_probe_artifact_created"
        )
        is False
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "protected_data_included"
        )
        is False
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_template_schema_probe_artifact_created"
        )
        is False
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_template_protected_data_included"
        )
        is False
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_validator_not_a_schema_probe_artifact"
        )
        is True
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "report_validator_protected_data_included"
        )
        is False
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "target_free_manifest_validator"
        )
        == "scripts/validate_ppmi_verily_target_free_manifest.py"
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "target_free_manifest_validator_audit_passed"
        )
        is True
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "target_free_manifest_not_a_feature_manifest_artifact"
        )
        is True
        and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
            "target_free_manifest_protected_data_included"
        )
        is False
        and all(row.get("passed") is True for row in access_lifecycle_state_handoff.get("checks", []))
        and any(
            row.get("name") == "state-aware handoff exposes approval metadata recorder for submitted state"
            and row.get("passed") is True
            for row in access_lifecycle_state_handoff.get("checks", [])
        )
        and any(
            row.get("name") == "synthetic submission metadata is not treated as real lifecycle submission"
            and row.get("passed") is True
            and row.get("evidence", {}).get("synthetic_source_rejected") is True
            for row in access_lifecycle_state_handoff.get("checks", [])
        )
        and any(
            row.get("name") == "synthetic approval metadata is not treated as real lifecycle approval"
            and row.get("passed") is True
            and row.get("evidence", {}).get("synthetic_source_rejected") is True
            for row in access_lifecycle_state_handoff.get("checks", [])
        )
        and "Synthetic or audit-only submission/approval metadata is not treated as real lifecycle evidence"
        in access_lifecycle_state_handoff.get("claim", "")
        and ppmi_next_action_status_audit.get("passed") is True
        and ppmi_next_action_status_audit.get("decision") == "ppmi_verily_next_action_status_ready"
        and ppmi_next_action_status_audit.get("goal_complete") is False
        and ppmi_next_action_status_audit.get("not_a_model_result") is True
        and ppmi_next_action_status_audit.get("source_audit")
        == "results/access_lifecycle_state_handoff_20260515.json"
        and ppmi_next_action_status_audit.get("current_submission_handoff")
        == "results/ppmi_verily_current_submission_handoff_20260515.json"
        and ppmi_next_action_status_audit.get("content_boundary", {}).get("record_paths_reported")
        is False
        and ppmi_next_action_status_audit.get("content_boundary", {}).get("protected_data_included")
        is False
        and all(row.get("passed") is True for row in ppmi_next_action_status_audit.get("checks", []))
        and any(
            row.get("name") == "json command returns a redacted status object"
            and row.get("passed") is True
            and row.get("evidence", {}).get("workflow_command_sequence")
            == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
            for row in ppmi_next_action_status_audit.get("checks", [])
        ),
        {
            "access_submission_tracker": {
                **access_submission_tracker.get("summary", {}),
                "ppmi_official_source_recheck": ppmi_official_recheck,
                "ppmi_word_template": ppmi_submit_format_audit.get("output_docx"),
                "ppmi_submission_email_template": ppmi_email_template_audit.get("template"),
                "ppmi_submission_email_validator": ppmi_email_validator_audit.get("validator"),
                "ppmi_submission_package_validator": (
                    ppmi_submission_route.get("completed_package_validator") or {}
                ).get("validator"),
                "ppmi_user_fill_checklist": ppmi_user_fill_checklist_audit.get("checklist"),
                "ppmi_schema_probe_checklist": ppmi_schema_probe_checklist_audit.get("checklist"),
                "ppmi_schema_probe_report_template": ppmi_schema_probe_template_audit.get("template"),
                "ppmi_target_free_manifest_template": ppmi_target_free_manifest_validator_audit.get("template"),
                "ppmi_target_free_manifest_validator": ppmi_target_free_manifest_validator_audit.get("validator"),
                "ppmi_completed_packet_validator": ppmi_completed_packet_validator_audit.get("validator"),
                "ppmi_submission_bundle": "results/ppmi_verily_submission_bundle_20260515.json",
                "ppmi_current_submission_handoff": "results/ppmi_verily_current_submission_handoff_20260515.json",
                "ppmi_zeroshot_blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
            },
            "access_submission_recorder": {
                "passed": access_submission_recorder_audit.get("passed"),
                "decision": access_submission_recorder_audit.get("decision"),
                "hard_failures": access_submission_recorder_audit.get("hard_failures"),
                "claim": access_submission_recorder_audit.get("claim"),
            },
            "access_approval_recorder": {
                "passed": access_approval_recorder_audit.get("passed"),
                "decision": access_approval_recorder_audit.get("decision"),
                "hard_failures": access_approval_recorder_audit.get("hard_failures"),
                "claim": access_approval_recorder_audit.get("claim"),
            },
            "schema_probe_recorder": {
                "passed": schema_probe_recorder_audit.get("passed"),
                "decision": schema_probe_recorder_audit.get("decision"),
                "hard_failures": schema_probe_recorder_audit.get("hard_failures"),
                "redaction_check_passed": any(
                    row.get("name")
                    == "approval record identity is redacted in schema-probe artifact and errors"
                    and row.get("passed") is True
                    for row in schema_probe_recorder_audit.get("checks", [])
                ),
                "claim": schema_probe_recorder_audit.get("claim"),
            },
            "current_next_action_handoff": {
                "passed": current_next_action_handoff.get("passed"),
                "decision": current_next_action_handoff.get("decision"),
                "local_access_state": current_next_action_handoff.get("local_access_state"),
                "next_action": current_next_action_handoff.get("next_action"),
            },
            "ppmi_current_submission_handoff": {
                "passed": ppmi_current_submission_handoff.get("passed"),
                "decision": ppmi_current_submission_handoff.get("decision"),
                "current_action": ppmi_current_submission_handoff.get("current_action"),
                "package_artifacts": ppmi_current_submission_handoff.get("package_artifacts"),
                "content_boundary": ppmi_current_submission_handoff.get("content_boundary"),
            },
            "access_lifecycle_state_handoff": {
                "passed": access_lifecycle_state_handoff.get("passed"),
                "decision": access_lifecycle_state_handoff.get("decision"),
                "current_lifecycle_state": access_lifecycle_state_handoff.get("current_lifecycle_state"),
                "current_action": access_lifecycle_state_handoff.get("current_action"),
                "pre_submission_handoff": access_lifecycle_state_handoff.get(
                    "pre_submission_handoff"
                ),
                "post_approval_schema_probe_handoff": access_lifecycle_state_handoff.get(
                    "post_approval_schema_probe_handoff"
                ),
                "local_counts": access_lifecycle_state_handoff.get("local_counts"),
            },
            "ppmi_next_action_status": {
                "passed": ppmi_next_action_status_audit.get("passed"),
                "decision": ppmi_next_action_status_audit.get("decision"),
                "source_audit": ppmi_next_action_status_audit.get("source_audit"),
                "current_submission_handoff": ppmi_next_action_status_audit.get(
                    "current_submission_handoff"
                ),
                "content_boundary": ppmi_next_action_status_audit.get("content_boundary"),
                "workflow_command_sequence": EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE,
            },
        },
    )
    raw_entity_ids = {
        row.get("synapse_id")
        for row in raw_recovery_runbook_audit.get("entity_checks", {}).values()
    }
    v.check(
        "T1/T3 goal-status helper exposes current hard gaps and access action",
        t1_t3_goal_status_audit.get("passed") is True
        and t1_t3_goal_status_audit.get("decision") == "t1_t3_goal_status_ready"
        and t1_t3_goal_status_audit.get("goal_complete") is False
        and t1_t3_goal_status_audit.get("not_a_model_result") is True
        and t1_t3_goal_status_audit.get("not_access_submission") is True
        and t1_t3_goal_status_audit.get("not_access_approval") is True
        and t1_t3_goal_status_audit.get("not_a_schema_probe") is True
        and t1_t3_goal_status_audit.get("hard_failures") == []
        and t1_t3_goal_status_audit.get("content_boundary", {}).get("protected_data_included")
        is False
        and t1_t3_goal_status_audit.get("content_boundary", {}).get("record_paths_reported")
        is False
        and t1_t3_goal_status_audit.get("source_audits", {}).get("proresults")
        == "results/proresults_prompt_to_artifact_audit_20260515.json"
        and all(row.get("passed") is True for row in t1_t3_goal_status_audit.get("checks", []))
        and any(
            row.get("name")
            == "status helper refreshes lifecycle and queue state by default"
            and row.get("passed") is True
            for row in t1_t3_goal_status_audit.get("checks", [])
        )
        and any(
            row.get("name") == "status helper exposes executable access command templates"
            and row.get("passed") is True
            for row in t1_t3_goal_status_audit.get("checks", [])
        )
        and any(
            row.get("name") == "json status is a redacted incomplete-goal object"
            and row.get("passed") is True
            and row.get("evidence", {}).get("next_action", {}).get("action_id")
            == expected_lifecycle_action_id
            and row.get("evidence", {}).get("next_non_redundant_actions")
            == proresults_audit.get("next_non_redundant_actions")
            and row.get("evidence", {}).get("external_access_summary", {}).get(
                "compute_ready_route_count"
            )
            == 0
            and len(row.get("evidence", {}).get("hard_gaps", [])) == 2
            for row in t1_t3_goal_status_audit.get("checks", [])
        ),
        {"audit": t1_t3_goal_status_audit},
    )
    v.check(
        "WearGait raw-data recovery runbook fills provenance blocker without download",
        raw_recovery_runbook_audit.get("passed") is True
        and raw_recovery_runbook_audit.get("decision") == "raw_data_recovery_runbook_ready_no_download"
        and raw_recovery_runbook_audit.get("hard_failures") == []
        and raw_recovery_runbook_audit.get("current_status", {}).get("credentials_present") is False
        and raw_recovery_runbook_audit.get("current_status", {}).get("preflight_status") == "missing_inputs"
        and raw_recovery_runbook_audit.get("current_status", {}).get("regeneration_probe_status") == "blocked_missing_regeneration_inputs"
        and raw_recovery_runbook_audit.get("current_status", {}).get("frozen_cache_unchanged") is True
        and {"syn55105521", "syn61370552", "syn64589881"}.issubset(raw_entity_ids)
        and "Do not synthesize a clean cache manifest" in raw_recovery_runbook
        and "Do not start a new T1/T3 model run" in raw_recovery_runbook
        and "--confirm-large-control-csvs" in raw_recovery_runbook,
        {
            "audit": raw_recovery_runbook_audit,
            "runbook": "scripts/weargait_raw_data_recovery_runbook.md",
        },
    )
    task_plan_archive_checks = {
        row.get("name"): row.get("passed")
        for row in task_plan_current_scope_audit.get("archive_scope", {}).get("checks", [])
    }
    v.check(
        "task_plan current-scope guard keeps old success criteria archive-bound",
        task_plan_current_scope_audit.get("passed") is True
        and task_plan_current_scope_audit.get("decision") == "task_plan_current_scope_guard_passed"
        and task_plan_current_scope_audit.get("hard_failures") == []
        and task_plan_current_scope_audit.get("current_scope", {}).get("missing_required_snippets") == []
        and task_plan_current_scope_audit.get("current_scope", {}).get("legacy_success_findings") == []
        and task_plan_current_scope_audit.get("current_scope", {}).get("contains_current_completion_criteria") is True
        and task_plan_archive_checks.get("archive_contains_legacy_success_table") is True
        and task_plan_archive_checks.get("current_scope_has_no_legacy_success_header") is True
        and "Current completion criteria (post-iter47)" in task_plan
        and "Old T3 `0.5227`, `0.4694`, `0.341`, `0.3948`, and `0.4092`" in task_plan,
        {
            "audit": task_plan_current_scope_audit,
            "task_plan": "task_plan.md",
        },
    )
    v.check(
        "paper generator routing guard keeps current manuscript on render_current_paper",
        paper_generator_routing_audit.get("passed") is True
        and paper_generator_routing_audit.get("decision") == "current_paper_renderer_route_guard_passed"
        and paper_generator_routing_audit.get("hard_failures") == []
        and paper_generator_routing_audit.get("current_renderer", {}).get("manifest", {}).get("status") == "passed"
        and paper_generator_routing_audit.get("current_renderer", {}).get("manifest", {}).get("validation_issues") == []
        and paper_generator_routing_audit.get("current_renderer", {}).get("forbidden_hits") == []
        and all(
            not doc.get("missing_required")
            and not doc.get("bad_exact_snippets")
            and not doc.get("unguarded_generate_v4_or_new4_hits")
            for doc in paper_generator_routing_audit.get("active_docs", [])
        )
        and "uv run python render_current_paper.py" in claude
        and "uv run python render_current_paper.py" in agents
        and "uv run python render_current_paper.py" in readme
        and "generate_paper_v4.py` and `NEW4.html` as legacy/stale archaeology only" in agents
        and "generate_paper_v4.py` / `NEW4.html` are archaeology, not current evidence" in claude
        and "Older `generate_paper*.py` / `NEW*.html` outputs are historical snapshots only" in readme,
        {
            "audit": paper_generator_routing_audit,
            "active_docs": [doc.get("path") for doc in paper_generator_routing_audit.get("active_docs", [])],
        },
    )
    v.check(
        "README claim-routing guard quarantines old SSL ranking claims",
        readme_claim_routing_audit.get("passed") is True
        and readme_claim_routing_audit.get("decision") == "readme_current_claim_route_guard_passed"
        and readme_claim_routing_audit.get("hard_failures") == []
        and readme_claim_routing_audit.get("unguarded_dangerous_hits") == []
        and readme_claim_routing_audit.get("missing_required") == []
        and readme_claim_routing_audit.get("bad_current_route_hits") == []
        and "Current Post-Audit WearGait-PD Benchmark" in readme
        and "T1 canonical floor" in readme
        and "0.6550" in readme
        and "T1 corrected candidate" in readme
        and "0.7170" in readme
        and "N=92" in readme
        and "T3 current" in readme
        and "0.3784" in readme
        and "0.150" in readme
        and "run_t3_iter47_invalid_code_fix.py" in readme
        and "legacy/retracted/pre-audit" in readme
        and "target-contaminated" in readme,
        {
            "audit": readme_claim_routing_audit,
            "readme": "README.md",
        },
    )
    legacy_surface_rows = {
        row.get("path"): row
        for row in legacy_manuscript_surface_audit.get("legacy_surfaces", [])
    }
    v.check(
        "legacy manuscript-surface guard quarantines stale paper artifacts",
        legacy_manuscript_surface_audit.get("passed") is True
        and legacy_manuscript_surface_audit.get("decision") == "legacy_manuscript_surfaces_quarantined"
        and legacy_manuscript_surface_audit.get("hard_failures") == []
        and len(legacy_surface_rows) == 16
        and legacy_manuscript_surface_audit.get("total_dangerous_hits", 0) > 0
        and all(row.get("banner_present_near_top") is True for row in legacy_surface_rows.values())
        and all(row.get("missing_current_pointers") == [] for row in legacy_surface_rows.values())
        and legacy_surface_rows.get("paper.tex", {}).get("dangerous_hit_count", 0) > 0
        and legacy_surface_rows.get("NEW4.html", {}).get("banner_present_near_top") is True
        and legacy_surface_rows.get("NEW5.html", {}).get("banner_present_near_top") is True
        and legacy_surface_rows.get("NEW6.html", {}).get("banner_present_near_top") is True,
        {
            "audit": {
                "decision": legacy_manuscript_surface_audit.get("decision"),
                "hard_failures": legacy_manuscript_surface_audit.get("hard_failures"),
                "total_dangerous_hits": legacy_manuscript_surface_audit.get("total_dangerous_hits"),
            },
            "surfaces": sorted(legacy_surface_rows),
        },
    )
    historical_archive_rows = {
        row.get("path"): row
        for row in historical_archive_surface_audit.get("surfaces", [])
    }
    v.check(
        "historical archive-surface guard quarantines project-note artifacts",
        historical_archive_surface_audit.get("passed") is True
        and historical_archive_surface_audit.get("decision") == "historical_archive_surfaces_quarantined"
        and historical_archive_surface_audit.get("hard_failures") == 0
        and historical_archive_surface_audit.get("surfaces_checked") == 11
        and historical_archive_surface_audit.get("total_stale_pattern_hits_retained_under_archive_banners", 0) > 0
        and len(historical_archive_rows) == 11
        and all(row.get("missing_required") == [] for row in historical_archive_rows.values())
        and all(row.get("forbidden_hits") == [] for row in historical_archive_rows.values())
        and all(row.get("unguarded_stale_lines") == [] for row in historical_archive_rows.values())
        and historical_archive_rows.get("leakage_onepager.html", {}).get("stale_pattern_hits", 0) > 0,
        {
            "audit": {
                "decision": historical_archive_surface_audit.get("decision"),
                "hard_failures": historical_archive_surface_audit.get("hard_failures"),
                "surfaces_checked": historical_archive_surface_audit.get("surfaces_checked"),
                "stale_pattern_hits": historical_archive_surface_audit.get("total_stale_pattern_hits_retained_under_archive_banners"),
            },
            "surfaces": sorted(historical_archive_rows),
        },
    )
    v.check(
        "secret hygiene guard removes local credential leaks",
        secret_hygiene_audit.get("passed") is True
        and secret_hygiene_audit.get("decision") == "secret_hygiene_guard_passed"
        and secret_hygiene_audit.get("findings") == []
        and secret_hygiene_audit.get("hard_failures") == []
        and secret_hygiene_audit.get("scanned_file_count", 0) > 100
        and secret_hygiene_audit.get("sensitive_local_files", {}).get("TOKEN.md", {}).get("exists") is False
        and secret_hygiene_audit.get("sensitive_local_files", {}).get(".env", {}).get("exists") is False
        and "TOKEN.md" in read_text(ROOT / ".gitignore")
        and ".env" in read_text(ROOT / ".gitignore"),
        {
            "audit": {
                "decision": secret_hygiene_audit.get("decision"),
                "findings": len(secret_hygiene_audit.get("findings", [])),
                "hard_failures": len(secret_hygiene_audit.get("hard_failures", [])),
                "scanned_file_count": secret_hygiene_audit.get("scanned_file_count"),
                "sensitive_local_files": secret_hygiene_audit.get("sensitive_local_files"),
            }
        },
    )

    cache_audit = load_json(RESULTS / "cache_manifest_audit_20260508.json")
    prompt_audit = load_json(RESULTS / "prompt_objective_evidence_audit_20260508.json")
    prompt_audit_md = read_text(RESULTS / "prompt_objective_evidence_audit_20260508.md")
    prompt_statuses = {row.get("requirement"): row.get("status") for row in prompt_audit.get("checks", [])}
    v.check(
        "prompt objective evidence audit maps explicit goal requirements",
        prompt_audit.get("goal_complete") is False
        and len(prompt_audit.get("checks", [])) >= 12
        and len(prompt_audit.get("hard_gaps", [])) == 1
        and prompt_statuses.get("Use web search / current SOTA context") == "covered"
        and prompt_statuses.get("Use Kimi, Claude, GLMCode, and Gemini where available") == "covered_with_tool_friction"
        and prompt_statuses.get("Use remote server and inspect utilization") == "covered"
        and prompt_statuses.get("Keep artifact, claim-labeling, and reproducibility guards current") == "covered"
        and prompt_statuses.get("Attempt to break T1 CCC ceiling") == "attempted_with_caveated_candidate"
        and prompt_statuses.get("Attempt to break T3 CCC ceiling") == "attempted_no_breakthrough"
        and prompt_statuses.get("Completion condition: break T1 and/or T3 ceiling") == "not_complete"
        and "TLVMC/DeFOG iter51 is complete" in prompt_audit_md
        and "External access readiness audit passes with `6` access/request packets ready and `0` compute-ready routes before approval" in prompt_audit_md
        and "Current next-action handoff passes with `0` real submissions, `0` real approvals, and `0` schema-probe artifacts" in prompt_audit_md
        and "Task-plan current-scope audit passes with `task_plan_current_scope_guard_passed`" in prompt_audit_md
        and "Paper generator routing audit passes with `current_paper_renderer_route_guard_passed`" in prompt_audit_md
        and "Legacy manuscript-surface audit passes with `legacy_manuscript_surfaces_quarantined`" in prompt_audit_md
        and "Historical archive-surface audit passes with `historical_archive_surfaces_quarantined`" in prompt_audit_md
        and "Secret hygiene audit passes with `secret_hygiene_guard_passed`" in prompt_audit_md
        and "User-side PPMI DUA/application" in prompt_audit_md
        and "User-side Personalized Parkinson Project / PD-VME RDSRC request" in prompt_audit_md
        and "User-side WATCH-PD C-Path 3DT membership" in prompt_audit_md
        and "User-side ICICLE-PD/ICICLE-GAIT data request" in prompt_audit_md
        and "User-side CNS Portugal/Lobo data request" in prompt_audit_md
        and "Monitor/request Mobilise-D CVS" in prompt_audit_md
        and "Harmonized Upper/Lower Limb Accelerometry" in prompt_audit_md
        and "do not launch another WearGait-only model family" in prompt_audit_md,
        {
            "goal_complete": prompt_audit.get("goal_complete"),
            "statuses": prompt_statuses,
            "hard_gaps": prompt_audit.get("hard_gaps"),
        },
    )

    cache_counts = cache_audit.get("status_counts", {})
    missing_cache_origin = load_json(RESULTS / "missing_cache_manifest_origin_audit_20260509.json")
    missing_cache_origin_md = read_text(RESULTS / "missing_cache_manifest_origin_audit_20260509.md")
    manual_cache_backfill = load_json(RESULTS / "manual_cache_backfill_evidence_20260509.json")
    manual_cache_backfill_md = read_text(RESULTS / "manual_cache_backfill_evidence_20260509.md")
    cache_backfill = load_json(RESULTS / "cache_backfill_candidates_20260508.json")
    cache_backfill_md = read_text(RESULTS / "cache_backfill_candidates_20260508.md")
    cache_backfill_decisions = load_json(RESULTS / "cache_backfill_decisions_20260508.json")
    cache_backfill_decisions_md = read_text(RESULTS / "cache_backfill_decisions_20260508.md")
    cache_consumer = load_json(RESULTS / "cache_consumer_guard_audit_20260508.json")
    cache_consumer_md = read_text(RESULTS / "cache_consumer_guard_audit_20260508.md")
    transitive_cache = load_json(RESULTS / "transitive_cache_dependency_audit_20260508.json")
    transitive_cache_md = read_text(RESULTS / "transitive_cache_dependency_audit_20260508.md")
    runtime_cache = load_json(RESULTS / "runtime_cache_dependency_audit_20260508.json")
    runtime_cache_md = read_text(RESULTS / "runtime_cache_dependency_audit_20260508.md")
    dst_audit = load_json(RESULTS / "dst_walkway_leakage_audit_20260508_multiseed.json")
    dst_audit_md = read_text(RESULTS / "dst_walkway_leakage_audit_20260508_multiseed.md")
    ablation_v3_provenance = load_json(RESULTS / "ablation_v3_cache_provenance_audit_20260508.json")
    ablation_v3_provenance_md = read_text(RESULTS / "ablation_v3_cache_provenance_audit_20260508.md")
    ablation_v3_regeneration = load_json(RESULTS / "ablation_v3_regeneration_probe_20260509.json")
    ablation_v3_regeneration_md = read_text(RESULTS / "ablation_v3_regeneration_probe_20260509.md")
    synapse_recovery = load_json(RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.json")
    synapse_recovery_md = read_text(RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.md")
    canonical_claim_audit = load_json(RESULTS / "canonical_claim_consistency_audit_20260508.json")
    canonical_claim_audit_md = read_text(RESULTS / "canonical_claim_consistency_audit_20260508.md")
    metric_recompute_audit = load_json(RESULTS / "headline_metric_recompute_audit_20260508.json")
    metric_recompute_audit_md = read_text(RESULTS / "headline_metric_recompute_audit_20260508.md")
    ccc_metric_audit = load_json(RESULTS / "ccc_metric_integrity_audit_20260509.json")
    ccc_metric_audit_md = read_text(RESULTS / "ccc_metric_integrity_audit_20260509.md")
    oof_integrity_audit = load_json(RESULTS / "oof_artifact_integrity_audit_20260508.json")
    oof_integrity_audit_md = read_text(RESULTS / "oof_artifact_integrity_audit_20260508.md")
    prereg_temporal_audit = load_json(RESULTS / "preregistration_temporal_integrity_audit_20260508.json")
    prereg_temporal_audit_md = read_text(RESULTS / "preregistration_temporal_integrity_audit_20260508.md")
    pre_audit_labeling_audit = load_json(RESULTS / "pre_audit_claim_labeling_audit_20260508.json")
    pre_audit_labeling_audit_md = read_text(RESULTS / "pre_audit_claim_labeling_audit_20260508.md")
    historical_subdomain_labeling_audit = load_json(RESULTS / "historical_subdomain_claim_labeling_audit_20260509.json")
    historical_subdomain_labeling_audit_md = read_text(RESULTS / "historical_subdomain_claim_labeling_audit_20260509.md")
    t1_candidate_labeling_audit = load_json(RESULTS / "t1_candidate_claim_labeling_audit_20260508.json")
    t1_candidate_labeling_audit_md = read_text(RESULTS / "t1_candidate_claim_labeling_audit_20260508.md")
    t3_complete33_labeling_audit = load_json(RESULTS / "t3_complete33_claim_labeling_audit_20260509.json")
    t3_complete33_labeling_audit_md = read_text(RESULTS / "t3_complete33_claim_labeling_audit_20260509.md")
    external_result_labeling_audit = load_json(RESULTS / "external_result_claim_labeling_audit_20260509.json")
    external_result_labeling_audit_md = read_text(RESULTS / "external_result_claim_labeling_audit_20260509.md")
    remaining_blocker_action_audit = load_json(RESULTS / "remaining_blocker_action_audit_20260509.json")
    remaining_blocker_action_audit_md = read_text(RESULTS / "remaining_blocker_action_audit_20260509.md")
    reportable_flag_audit = load_json(RESULTS / "reportable_artifact_flag_audit_20260509.json")
    reportable_flag_audit_md = read_text(RESULTS / "reportable_artifact_flag_audit_20260509.md")
    per_item_map_md = read_text(RESULTS / "per_item_evidence_map_20260508.md")
    per_item_oof_scope_md = read_text(RESULTS / "per_item_oof_companion_scope_audit_20260508.md")
    v.check(
        "cache manifest audit records diagnostic-only provenance boundary",
        cache_audit.get("n_cache_like_artifacts", 0) >= 45
        and cache_counts.get("manifest_complete_clean_by_construction", 0) >= 4
        and (
            cache_counts.get("missing_manifest_diagnostic_only", 0)
            + cache_counts.get("partial_manifest_diagnostic_only", 0)
        )
        >= 41
        and "diagnostic-only" in cache_audit.get("policy", ""),
        {
            "n_cache_like_artifacts": cache_audit.get("n_cache_like_artifacts"),
            "status_counts": cache_counts,
            "policy": cache_audit.get("policy"),
        },
    )
    missing_origin_counts = missing_cache_origin.get("decision_counts", {})
    v.check(
        "missing cache-manifest origin audit is non-promotional",
        missing_cache_origin.get("source_audit") == "results/cache_manifest_audit_20260508.json"
        and missing_cache_origin.get("n_missing_manifests") == 33
        and missing_origin_counts == {
            "blocked_by_upstream_diagnostic_cache": 5,
            "insufficient_producer_evidence": 9,
            "manual_backfill_candidate_needs_human_patch": 5,
            "manual_review_label_or_clinical_tokens": 14,
        }
        and "Non-mutating origin map" in missing_cache_origin.get("policy", "")
        and "does not make any artifact headline-safe by itself" in missing_cache_origin_md,
        {
            "n_missing_manifests": missing_cache_origin.get("n_missing_manifests"),
            "decision_counts": missing_origin_counts,
            "policy": missing_cache_origin.get("policy"),
        },
    )
    manual_backfill_rows = {
        row.get("artifact"): row
        for row in manual_cache_backfill.get("artifacts", [])
    }
    v.check(
        "manual missing-cache backfill evidence avoids fabricated sidecars",
        manual_cache_backfill.get("source_audit") == "results/missing_cache_manifest_origin_audit_20260509.json"
        and manual_cache_backfill.get("n_candidates") == 5
        and manual_cache_backfill.get("decision_counts") == {"leave_missing_no_patch": 5}
        and set(manual_backfill_rows) == {
            "results/hc_ssl_subj_embeddings.csv",
            "results/joints_v2_subj.csv",
            "results/moment_subj_embeddings.csv",
            "results/stride_locked_subj.csv",
            "results/tug_transition_features.csv",
        }
        and all(row.get("decision") == "leave_missing_no_patch" for row in manual_backfill_rows.values())
        and any("broken" in " ".join(row.get("required_evidence_gaps", [])) for row in manual_backfill_rows.values())
        and any("missing locally" in " ".join(row.get("required_evidence_gaps", [])) for row in manual_backfill_rows.values())
        and manual_cache_backfill.get("remote_recovery_probe", {}).get("returncode") == 0
        and any("BROKEN_SYMLINK results/rocket_recordings.npz" in line for line in manual_cache_backfill.get("remote_recovery_probe", {}).get("output", []))
        and "All five artifacts remain diagnostic-only" in manual_cache_backfill_md,
        {
            "n_candidates": manual_cache_backfill.get("n_candidates"),
            "decision_counts": manual_cache_backfill.get("decision_counts"),
            "remote_output": manual_cache_backfill.get("remote_recovery_probe", {}).get("output"),
            "artifacts": {
                artifact: {
                    "decision": row.get("decision"),
                    "gaps": row.get("required_evidence_gaps"),
                }
                for artifact, row in manual_backfill_rows.items()
            },
        },
    )
    backfill_rows = {row.get("artifact"): row for row in cache_backfill.get("artifacts", [])}
    manual_candidates = {
        artifact
        for artifact, row in backfill_rows.items()
        if row.get("recommendation") == "manual_backfill_candidate"
    }
    do_not_backfill = {
        artifact
        for artifact, row in backfill_rows.items()
        if row.get("recommendation") == "do_not_backfill_for_internal_headline"
    }
    needs_commit = {
        artifact
        for artifact, row in backfill_rows.items()
        if row.get("recommendation") == "needs_commit_before_backfill"
    }
    v.check(
        "cache backfill candidate audit is conservative",
        cache_backfill.get("source_audit") == "results/cache_manifest_audit_20260508.json"
        and cache_backfill.get("counts") == {
            "manual_backfill_candidate": 2,
            "do_not_backfill_for_internal_headline": 4,
            "needs_commit_before_backfill": 2,
        }
        and manual_candidates == {
            "results/item_specific_features.csv",
            "results/unused_channels_features.csv",
        }
        and needs_commit == {
            "results/phaselocked_item9_features.csv",
            "results/phaselocked_item12_features.csv",
        }
        and {
            "results/indomain_ssl_embeddings.csv",
            "results/iter49_cops_features_full.csv",
            "results/iter49_cops_features_smoke.csv",
            "results/iter51_tlvmc_defog_features.csv",
        }.issubset(do_not_backfill)
        and "does not modify manifests" in cache_backfill_md
        and "does not make any artifact headline-safe" in cache_backfill_md,
        {
            "counts": cache_backfill.get("counts"),
            "manual_candidates": sorted(manual_candidates),
            "needs_commit": sorted(needs_commit),
            "do_not_backfill": sorted(do_not_backfill),
            "policy": cache_backfill.get("policy"),
        },
    )
    decision_rows = {
        row.get("artifact"): row
        for row in cache_backfill_decisions.get("decisions", [])
    }
    v.check(
        "cache backfill decisions avoid fabricated provenance",
        cache_backfill_decisions.get("source_candidates") == "results/cache_backfill_candidates_20260508.json"
        and cache_backfill_decisions.get("counts") == {"leave_partial_no_patch": 2}
        and set(decision_rows) == {
            "results/item_specific_features.csv",
            "results/unused_channels_features.csv",
        }
        and all(row.get("decision") == "leave_partial_no_patch" for row in decision_rows.values())
        and all("command" in row.get("blocking_fields", []) for row in decision_rows.values())
        and "Do not synthesize missing manifest fields" in cache_backfill_decisions.get("policy", "")
        and "Do not infer them from narrative docs" in cache_backfill_decisions_md,
        {
            "counts": cache_backfill_decisions.get("counts"),
            "decisions": {
                artifact: {
                    "decision": row.get("decision"),
                    "blocking_fields": row.get("blocking_fields"),
                }
                for artifact, row in decision_rows.items()
            },
            "policy": cache_backfill_decisions.get("policy"),
        },
    )
    consumer_counts = cache_consumer.get("classification_counts", {})
    v.check(
        "cache consumer guard audit blocks unguarded diagnostic caches from headline use",
        consumer_counts.get("current_safe_consumer_guarded") == 4
        and consumer_counts.get("diagnostic_only_consumer_block_reportable_use", 0) >= 50
        and consumer_counts.get("non_model_or_cache_producer_reference", 0) >= 30
        and not consumer_counts.get("unguarded_clean_cache_consumer_review")
        and set(cache_consumer.get("current_guarded_consumers", []))
        == {
            "compose_t1_iter14_fog.py",
            "compose_t1_iter15_harnet.py",
            "run_t3_iter23_clinical_ablation.py",
            "run_t3_iter24_stage2_forced.py",
        }
        and "Scripts that still reference missing/partial-manifest caches are diagnostic or historical" in cache_consumer.get("verdict", "")
        and "Diagnostic-Only Model Consumers" in cache_consumer_md,
        {
            "classification_counts": consumer_counts,
            "current_guarded_consumers": cache_consumer.get("current_guarded_consumers"),
            "diagnostic_only_model_consumers_count": len(cache_consumer.get("diagnostic_only_model_consumers", [])),
        },
    )
    transitive_counts = transitive_cache.get("classification_counts", {})
    transitive_reports = {
        row.get("entrypoint"): row
        for row in transitive_cache.get("entrypoint_reports", [])
    }
    v.check(
        "transitive cache dependency audit records import-closure provenance boundary",
        transitive_counts == {
            "entrypoint_direct_diagnostic_cache_reference": 5,
            "import_closure_contains_diagnostic_cache_reference": 7,
        }
        and set(transitive_cache.get("entrypoints", []))
        == {
            "compose_t1_iter12_honest.py",
            "run_t1_iter34_hybrid_8item_multibase.py",
            "run_t1_iter46_et_robust.py",
            "run_t3_iter47_invalid_code_fix.py",
            "run_t3_iter41_target_fix.py",
            "run_t3_iter5_clinical.py",
            "run_t3_iter16_site_ipw.py",
            "compose_t1_iter14_fog.py",
            "compose_t1_iter15_harnet.py",
            "run_t3_iter23_clinical_ablation.py",
            "run_t3_iter24_stage2_forced.py",
            "run_t3_iter49_cops.py",
        }
        and transitive_reports.get("compose_t1_iter12_honest.py", {}).get("classification")
        == "entrypoint_direct_diagnostic_cache_reference"
        and transitive_reports.get("run_t3_iter47_invalid_code_fix.py", {}).get("classification")
        == "import_closure_contains_diagnostic_cache_reference"
        and set(transitive_cache.get("direct_diagnostic_entrypoints", []))
        == {
            "compose_t1_iter12_honest.py",
            "run_t3_iter41_target_fix.py",
            "run_t3_iter5_clinical.py",
            "run_t3_iter16_site_ipw.py",
            "run_t3_iter49_cops.py",
        }
        and "Static import reachability is conservative" in transitive_cache_md
        and "Direct cache-consumer guard status is not enough" in transitive_cache.get("verdict", ""),
        {
            "classification_counts": transitive_counts,
            "direct_diagnostic_entrypoints": transitive_cache.get("direct_diagnostic_entrypoints"),
            "canonical_t1": {
                "classification": transitive_reports.get("compose_t1_iter12_honest.py", {}).get("classification"),
                "diagnostic_artifacts": transitive_reports.get("compose_t1_iter12_honest.py", {}).get("diagnostic_or_partial_cache_artifacts"),
            },
            "canonical_t3": {
                "classification": transitive_reports.get("run_t3_iter47_invalid_code_fix.py", {}).get("classification"),
                "diagnostic_artifacts": transitive_reports.get("run_t3_iter47_invalid_code_fix.py", {}).get("diagnostic_or_partial_cache_artifacts"),
            },
        },
    )
    runtime_reports = {
        row.get("target"): row
        for row in runtime_cache.get("target_reports", [])
    }
    runtime_t1 = runtime_reports.get("t1_iter12_recompute", {})
    runtime_t1_result = runtime_t1.get("result", {})
    runtime_iter34 = runtime_reports.get("t1_iter34_loader", {})
    runtime_iter34_result = runtime_iter34.get("result", {})
    runtime_t3 = runtime_reports.get("t3_iter47_filter_minimal", {})
    runtime_t3_result = runtime_t3.get("result", {})
    v.check(
        "runtime cache dependency audit records executed cache reads and narrowed T1 loader",
        runtime_cache.get("opened_diagnostic_or_partial_cache_artifacts") == ["results/ablation_v3_features.csv"]
        and runtime_cache.get("method", "").startswith("Python sys.addaudithook")
        and runtime_t1.get("status") == "ok"
        and approx_equal(runtime_t1_result.get("ccc"), 0.6550)
        and approx_equal(runtime_t1_result.get("mae"), 1.5614, 1e-3)
        and runtime_t1_result.get("n") == 94
        and runtime_iter34.get("status") == "ok"
        and runtime_iter34_result.get("n") == 92
        and runtime_iter34_result.get("available_aux") == [15, 18]
        and runtime_t3.get("status") == "ok"
        and runtime_t3_result.get("n") == 95
        and runtime_t3_result.get("target_changed_sids") == ["NLS036"]
        and "current fail-closed loader now produces N=92" in runtime_cache.get("verdict", "")
        and "Runtime tracing is diagnostic only" in runtime_cache_md
        and "from run_per_item_v2 import" not in read_text(ROOT / "compose_t1_iter12_honest.py"),
        {
            "opened_diagnostic_or_partial_cache_artifacts": runtime_cache.get("opened_diagnostic_or_partial_cache_artifacts"),
            "t1_iter12_recompute": runtime_t1_result,
            "t1_iter34_loader": runtime_iter34_result,
            "t3_iter47_filter_minimal": runtime_t3_result,
            "verdict": runtime_cache.get("verdict"),
        },
    )
    dst_schema = dst_audit.get("schema_audit", {})
    dst_current = dst_audit.get("policy_results", {}).get("stage2_current", {})
    dst_nodst = dst_audit.get("policy_results", {}).get("stage2_no_dst", {})
    dst_current_metrics = dst_current.get("mean_metrics", {})
    dst_nodst_metrics = dst_nodst.get("mean_metrics", {})
    dst_comp = dst_audit.get("comparisons", {}).get("stage2_no_dst_minus_current", {})
    dst_current_selected = sum(
        detail.get("selected_prefix_counts", {}).get("dst_", 0)
        for detail in dst_current.get("seed_details", {}).values()
    )
    dst_nodst_selected = sum(
        detail.get("selected_prefix_counts", {}).get("dst_", 0)
        for detail in dst_nodst.get("seed_details", {}).values()
    )
    v.check(
        "T3 dst walkway-distillation audit records non-load-bearing provenance caveat",
        dst_audit.get("script") == "audit_dst_walkway_leakage.py"
        and dst_audit.get("cohort", {}).get("n") == 95
        and dst_audit.get("cohort", {}).get("target_changed_sids") == ["NLS036"]
        and len(dst_schema.get("dst_columns_selected_by_current_filters", [])) == 31
        and len(dst_schema.get("cv_columns_selected_by_current_filters", [])) == 6
        and approx_equal(dst_current_metrics.get("ccc"), 0.3784)
        and approx_equal(dst_current_metrics.get("mae"), 7.528, 1e-3)
        and approx_equal(dst_nodst_metrics.get("ccc"), 0.3766)
        and approx_equal(dst_nodst_metrics.get("mae"), 7.5795, 1e-3)
        and dst_current_selected == 1611
        and dst_nodst_selected == 0
        and approx_equal(dst_comp.get("mean_delta"), -0.0004292355, 1e-6)
        and approx_equal(dst_comp.get("frac_gt_0"), 0.4796, 1e-6)
        and dst_comp.get("ci95", [1, 1])[0] < 0
        and dst_comp.get("ci95", [-1, -1])[1] > 0
        and "not fold-local for LOOCV" in dst_audit.get("verdict", "")
        and "selected dst count" in dst_audit_md,
        {
            "schema": {
                "n_columns_total": dst_schema.get("n_columns_total"),
                "n_v2_selected_by_current_filters": dst_schema.get("n_v2_selected_by_current_filters"),
                "dst_selected": len(dst_schema.get("dst_columns_selected_by_current_filters", [])),
                "cv_selected": len(dst_schema.get("cv_columns_selected_by_current_filters", [])),
            },
            "current": dst_current_metrics,
            "no_dst": dst_nodst_metrics,
            "selected_dst": {
                "current": dst_current_selected,
                "no_dst": dst_nodst_selected,
            },
            "comparison": dst_comp,
        },
    )
    ablation_schema = ablation_v3_provenance.get("schema_evidence", {})
    ablation_filter = ablation_schema.get("current_v2_filter", {})
    ablation_prefix_selected = ablation_filter.get("prefix_counts_selected", {})
    ablation_prior = ablation_v3_provenance.get("prior_audits", {})
    ablation_runtime_targets = {
        row.get("target")
        for row in ablation_prior.get("runtime_targets_opening_cache", [])
    }
    ablation_decision = ablation_v3_provenance.get("decision", {})
    v.check(
        "ablation_v3 live-cache provenance audit avoids synthesized manifest",
        ablation_v3_provenance.get("script") == "audit_ablation_v3_cache_provenance.py"
        and ablation_v3_provenance.get("cache", {}).get("sha256")
        == "b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4"
        and ablation_schema.get("rows") == 178
        and ablation_schema.get("columns") == 1877
        and ablation_filter.get("selected_columns") == 1752
        and ablation_prefix_selected.get("dst_") == 31
        and ablation_prefix_selected.get("cv_") == 6
        and ablation_v3_provenance.get("manifest_validation", {}).get("status")
        == "missing_manifest_diagnostic_only"
        and ablation_decision.get("decision") == "do_not_synthesize_clean_manifest"
        and ablation_decision.get("safe_for_cache_manifest_clean_headline") is False
        and {"t1_iter12_recompute", "t1_iter34_loader", "t3_iter47_filter_minimal"}.issubset(ablation_runtime_targets)
        and ablation_prior.get("dst_walkway_distillation_summary", {}).get("dst_columns_selected") == 31
        and "does not create or backfill a manifest sidecar" in ablation_v3_provenance_md
        and "do_not_synthesize_clean_manifest" in ablation_v3_provenance_md,
        {
            "cache": ablation_v3_provenance.get("cache"),
            "schema": {
                "rows": ablation_schema.get("rows"),
                "columns": ablation_schema.get("columns"),
                "selected_columns": ablation_filter.get("selected_columns"),
                "prefix_counts_selected": ablation_prefix_selected,
            },
            "manifest_validation": ablation_v3_provenance.get("manifest_validation"),
            "runtime_targets": sorted(ablation_runtime_targets),
            "decision": ablation_decision,
        },
    )
    regen_missing = ablation_v3_regeneration.get("input_status", {}).get("missing", [])
    v.check(
        "ablation_v3 regeneration probe fails closed on incomplete remote raw data",
        ablation_v3_regeneration.get("script") == "audit_ablation_v3_regeneration.py"
        and ablation_v3_regeneration.get("status") == "blocked_missing_regeneration_inputs"
        and ablation_v3_regeneration.get("frozen_cache_unchanged") is True
        and ablation_v3_regeneration.get("frozen_before", {}).get("sha256")
        == "b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4"
        and ablation_v3_regeneration.get("frozen_after", {}).get("sha256")
        == "b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4"
        and {
            "control_clinical",
            "control_csv_dir",
            "walkway_metrics",
        }.issubset(set(regen_missing))
        and all(status == "ok" for status in ablation_v3_regeneration.get("dependency_status", {}).values())
        and "No regenerated cache was written" in ablation_v3_regeneration_md
        and "blocked_missing_regeneration_inputs" in ablation_v3_regeneration_md,
        {
            "status": ablation_v3_regeneration.get("status"),
            "missing": regen_missing,
            "frozen_before": ablation_v3_regeneration.get("frozen_before"),
            "frozen_after": ablation_v3_regeneration.get("frozen_after"),
            "dependency_status": ablation_v3_regeneration.get("dependency_status"),
        },
    )
    recovery_entities = synapse_recovery.get("entities", {})
    recovery_missing = set(synapse_recovery.get("missing", []))
    v.check(
        "WearGait missing Synapse input recovery preflight is credential-safe and exact",
        synapse_recovery.get("mode") == "preflight"
        and synapse_recovery.get("status") == "missing_inputs"
        and {
            "control_clinical",
            "control_csv_folder",
            "walkway_metrics",
        }.issubset(recovery_missing)
        and synapse_recovery.get("credential_status", {}).get("can_attempt_download") is False
        and recovery_entities.get("control_clinical", {}).get("synapse_probe", {}).get("synapse_id") == "syn55105521"
        and recovery_entities.get("control_clinical", {}).get("synapse_probe", {}).get("status") == "ok"
        and recovery_entities.get("control_csv_folder", {}).get("synapse_probe", {}).get("synapse_id") == "syn61370552"
        and recovery_entities.get("control_csv_folder", {}).get("synapse_probe", {}).get("csv_children_count") == 680
        and recovery_entities.get("walkway_metrics", {}).get("synapse_probe", {}).get("synapse_id") == "syn64589881"
        and recovery_entities.get("walkway_metrics", {}).get("synapse_probe", {}).get("status") == "ok"
        and "--confirm-large-control-csvs" in synapse_recovery_md
        and "This recovery preflight does not promote" in synapse_recovery_md,
        {
            "status": synapse_recovery.get("status"),
            "missing": synapse_recovery.get("missing"),
            "credential_status": synapse_recovery.get("credential_status"),
            "control_csv_synapse_count": recovery_entities.get("control_csv_folder", {}).get("synapse_probe", {}).get("csv_children_count"),
        },
    )
    v.check(
        "canonical claim consistency audit blocks stale active-scope T3 wording",
        canonical_claim_audit.get("script") == "audit_canonical_claim_consistency.py"
        and canonical_claim_audit.get("passed") is True
        and canonical_claim_audit.get("stale_findings") == []
        and canonical_claim_audit.get("missing_required_snippets") == []
        and canonical_claim_audit.get("current_expected", {}).get("t1_canonical_ccc") == "0.6550"
        and canonical_claim_audit.get("current_expected", {}).get("t1_candidate_ccc") == "0.7170"
        and canonical_claim_audit.get("current_expected", {}).get("t3_current_ccc") == "0.3784"
        and canonical_claim_audit.get("current_expected", {}).get("t3_loso_ccc") == "0.150"
        and "Old T3 numbers may appear only when labelled historical" in canonical_claim_audit_md
        and "Passed: `True`" in canonical_claim_audit_md,
        {
            "passed": canonical_claim_audit.get("passed"),
            "current_expected": canonical_claim_audit.get("current_expected"),
            "stale_findings": canonical_claim_audit.get("stale_findings"),
            "missing_required_snippets": canonical_claim_audit.get("missing_required_snippets"),
        },
    )
    metric_recompute_names = {check.get("name") for check in metric_recompute_audit.get("checks", [])}
    metric_recompute_required = {
        "t1_iter12_honest_floor",
        "t1_iter34_hybrid_candidate",
        "t3_iter47_validrange_current",
        "t3_iter47_validrange_no_cv",
        "t3_iter47_complete33_current_sensitivity",
        "dst_audit_stage2_current",
        "dst_audit_stage2_no_dst",
        "t3_iter47_loso_drop_allmissing_validrange_stage2_current",
        "t3_iter47_loso_drop_allmissing_validrange_stage2_no_cv",
    }
    v.check(
        "headline metric recompute audit matches stored prediction artifacts",
        metric_recompute_audit.get("script") == "audit_headline_metric_recompute.py"
        and metric_recompute_audit.get("passed") is True
        and metric_recompute_names == metric_recompute_required
        and all(check.get("passed") is True for check in metric_recompute_audit.get("checks", []))
        and "t3_iter47_validrange_current" in metric_recompute_audit_md
        and "t1_iter12_honest_floor" in metric_recompute_audit_md,
        {
            "passed": metric_recompute_audit.get("passed"),
            "checks": len(metric_recompute_audit.get("checks", [])),
            "names": sorted(metric_recompute_names),
            "tolerance": metric_recompute_audit.get("tolerance"),
        },
    )
    ccc_metric_ids = {check.get("id") for check in ccc_metric_audit.get("headline_checks", [])}
    ccc_impl_ids = {check.get("id") for check in ccc_metric_audit.get("implementation_checks", [])}
    v.check(
        "CCC metric integrity audit pins Lin population-moment convention",
        ccc_metric_audit.get("script") == "audit_ccc_metric_integrity.py"
        and ccc_metric_audit.get("passed") is True
        and ccc_metric_audit.get("hard_failures") == []
        and ccc_metric_ids
        == {
            "t1_iter12_honest_floor",
            "t1_iter34_hybrid_candidate",
            "t1_iter46_etrobust_diagnostic",
            "t3_iter47_validrange_current",
            "t3_iter47_validrange_no_cv_sensitivity",
            "t3_iter47_complete33_current_sensitivity",
            "t3_iter5_historical_target_contaminated",
        }
        and {
            "identity",
            "shifted",
            "scaled",
            "anti_correlated",
            "constant_prediction",
            "n2_nonconstant",
            "nan_inf_masked",
        }.issubset(ccc_impl_ids)
        and ccc_metric_audit.get("max_abs_sample_minus_population_headline", 1.0) < 0.00001
        and any(w.get("id") == "degenerate_n2_policy_returns_zero" for w in ccc_metric_audit.get("warnings", []))
        and all(check.get("passed") is True for check in ccc_metric_audit.get("headline_checks", []))
        and "Reportable CCC uses Lin's population-moment concordance formula" in ccc_metric_audit.get("policy", "")
        and "Max absolute sample-minus-population shift" in ccc_metric_audit_md,
        {
            "passed": ccc_metric_audit.get("passed"),
            "headline_checks": len(ccc_metric_audit.get("headline_checks", [])),
            "implementation_checks": len(ccc_metric_audit.get("implementation_checks", [])),
            "max_abs_sample_minus_population_headline": ccc_metric_audit.get("max_abs_sample_minus_population_headline"),
            "warnings": ccc_metric_audit.get("warnings"),
        },
    )
    oof_integrity_names = {check.get("name") for check in oof_integrity_audit.get("checks", [])}
    v.check(
        "OOF binary artifacts match JSON per-subject predictions",
        oof_integrity_audit.get("script") == "audit_oof_artifact_integrity.py"
        and oof_integrity_audit.get("passed") is True
        and oof_integrity_names
        == {
            "t1_iter12_honest_floor",
            "t1_iter34_hybrid_candidate",
            "t1_iter46_etrobust_diagnostic",
            "t3_iter5_historical_target_contaminated",
        }
        and all(check.get("passed") is True for check in oof_integrity_audit.get("checks", []))
        and all(check.get("max_abs_diff") == 0.0 for check in oof_integrity_audit.get("checks", []))
        and "Max abs diff: `0.0`" in oof_integrity_audit_md,
        {
            "passed": oof_integrity_audit.get("passed"),
            "checks": len(oof_integrity_audit.get("checks", [])),
            "names": sorted(oof_integrity_names),
        },
    )
    prereg_temporal_names = {check.get("name") for check in prereg_temporal_audit.get("checks", [])}
    prereg_warning_types = {warning.get("warning") for warning in prereg_temporal_audit.get("warnings", [])}
    v.check(
        "pre-registration temporal integrity audit has no hard failures",
        prereg_temporal_audit.get("script") == "audit_preregistration_temporal_integrity.py"
        and prereg_temporal_audit.get("passed") is True
        and prereg_temporal_audit.get("hard_failures") == []
        and {
            "t1_iter12_honest_floor",
            "t1_iter34_hybrid_candidate",
            "t1_iter46_etrobust_diagnostic",
            "t3_iter47_validrange_current",
            "t3_iter47_validrange_loso",
            "t3_iter39_fogstar_zeroshot",
            "t3_iter49_cops_zeroshot",
            "t3_iter51_tlvmc_defog_zeroshot",
            "t3_iter5_historical",
        }.issubset(prereg_temporal_names)
        and "prereg_only_result_lacks_formula_link" in prereg_warning_types
        and "prereg_git_sha_unknown" in prereg_warning_types
        and "Hard failures: `0`" in prereg_temporal_audit_md,
        {
            "passed": prereg_temporal_audit.get("passed"),
            "checks": len(prereg_temporal_audit.get("checks", [])),
            "warnings": len(prereg_temporal_audit.get("warnings", [])),
            "warning_types": sorted(prereg_warning_types),
            "hard_failures": prereg_temporal_audit.get("hard_failures"),
        },
    )
    v.check(
        "pre-audit held-out claim labeling audit has zero findings",
        pre_audit_labeling_audit.get("script") == "audit_pre_audit_claim_labeling.py"
        and pre_audit_labeling_audit.get("passed") is True
        and pre_audit_labeling_audit.get("findings") == []
        and {doc.get("path") for doc in pre_audit_labeling_audit.get("docs", [])} == {"paper.md", "CURRENT_PAPER.html"}
        and "Findings: `0`" in pre_audit_labeling_audit_md
        and "Old held-out/stacking/ceiling claims" in pre_audit_labeling_audit_md,
        {
            "passed": pre_audit_labeling_audit.get("passed"),
            "docs": pre_audit_labeling_audit.get("docs"),
            "claim_patterns": pre_audit_labeling_audit.get("claim_patterns"),
        },
    )
    v.check(
        "historical subdomain/sensor claim labeling audit has zero findings",
        historical_subdomain_labeling_audit.get("script") == "audit_historical_subdomain_claim_labeling.py"
        and historical_subdomain_labeling_audit.get("passed") is True
        and historical_subdomain_labeling_audit.get("findings") == []
        and {doc.get("path") for doc in historical_subdomain_labeling_audit.get("docs", [])} == {"paper.md", "CURRENT_PAPER.html"}
        and "Findings: `0`" in historical_subdomain_labeling_audit_md
        and "Historical sensor-ablation and subdomain-prediction claims" in historical_subdomain_labeling_audit_md,
        {
            "passed": historical_subdomain_labeling_audit.get("passed"),
            "docs": historical_subdomain_labeling_audit.get("docs"),
            "claim_patterns": historical_subdomain_labeling_audit.get("claim_patterns"),
        },
    )
    v.check(
        "T1 iter34 candidate claim labeling audit has zero findings",
        t1_candidate_labeling_audit.get("script") == "audit_t1_candidate_claim_labeling.py"
        and t1_candidate_labeling_audit.get("passed") is True
        and t1_candidate_labeling_audit.get("findings") == []
        and t1_candidate_labeling_audit.get("missing_required_snippets") == []
        and "Findings: `0`" in t1_candidate_labeling_audit_md
        and "canonical floor" in t1_candidate_labeling_audit_md,
        {
            "passed": t1_candidate_labeling_audit.get("passed"),
            "findings": t1_candidate_labeling_audit.get("findings"),
            "missing_required_snippets": t1_candidate_labeling_audit.get("missing_required_snippets"),
        },
    )
    v.check(
        "T3 complete33 sensitivity claim labeling audit has zero findings",
        t3_complete33_labeling_audit.get("script") == "audit_t3_complete33_claim_labeling.py"
        and t3_complete33_labeling_audit.get("passed") is True
        and t3_complete33_labeling_audit.get("findings") == []
        and t3_complete33_labeling_audit.get("missing_required_snippets") == []
        and "Findings: `0`" in t3_complete33_labeling_audit_md
        and "current T3 internal headline remains the N=95 minimal valid-range CCC 0.3784" in t3_complete33_labeling_audit_md,
        {
            "passed": t3_complete33_labeling_audit.get("passed"),
            "findings": t3_complete33_labeling_audit.get("findings"),
            "missing_required_snippets": t3_complete33_labeling_audit.get("missing_required_snippets"),
            "docs": t3_complete33_labeling_audit.get("docs"),
        },
    )
    v.check(
        "external result claim labeling audit blocks external-to-internal T3 overclaim",
        external_result_labeling_audit.get("script") == "audit_external_result_claim_labeling.py"
        and external_result_labeling_audit.get("passed") is True
        and external_result_labeling_audit.get("findings") == []
        and external_result_labeling_audit.get("missing_required_snippets") == []
        and external_result_labeling_audit.get("artifact_failures") == []
        and len(external_result_labeling_audit.get("artifact_checks", [])) == 4
        and all(row.get("has_external_only_decision") is True for row in external_result_labeling_audit.get("artifact_checks", []))
        and "Artifact failures: `0`" in external_result_labeling_audit_md
        and "must not be framed as internal WearGait-PD T3 headline" in external_result_labeling_audit.get("policy", ""),
        {
            "passed": external_result_labeling_audit.get("passed"),
            "findings": external_result_labeling_audit.get("findings"),
            "missing_required_snippets": external_result_labeling_audit.get("missing_required_snippets"),
            "artifact_failures": external_result_labeling_audit.get("artifact_failures"),
            "artifact_checks": external_result_labeling_audit.get("artifact_checks"),
            "docs": external_result_labeling_audit.get("docs"),
        },
    )
    v.check(
        "remaining blocker action audit leaves no local WearGait-only model action",
        remaining_blocker_action_audit.get("script") == "audit_remaining_blocker_actions.py"
        and remaining_blocker_action_audit.get("passed") is True
        and remaining_blocker_action_audit.get("source_goal_complete") is False
        and remaining_blocker_action_audit.get("source_blocker_count") == 37
        and remaining_blocker_action_audit.get("unmatched_blockers") == []
        and remaining_blocker_action_audit.get("ambiguous_blockers") == []
        and remaining_blocker_action_audit.get("local_model_actions") == []
        and remaining_blocker_action_audit.get("action_type_counts", {}).get("no_local_weargait_model_run") == 8
        and remaining_blocker_action_audit.get("action_type_counts", {}).get("paper_uncertainty_only") == 2
        and remaining_blocker_action_audit.get("action_type_counts", {}).get("requires_user_or_data_owner_access") == 8
        and remaining_blocker_action_audit.get("action_type_counts", {}).get("requires_weargait_raw_data_restore") == 2
        and remaining_blocker_action_audit.get("action_type_counts", {}).get("paper_transportability_only") == 4
        and remaining_blocker_action_audit.get("action_type_counts", {}).get("no_prereg_no_rerun_same_policy") == 1
        and "Local WearGait-only model actions remaining: `0`" in remaining_blocker_action_audit_md
        and "Do not launch another WearGait-only T1/T3 model family" in remaining_blocker_action_audit_md,
        {
            "passed": remaining_blocker_action_audit.get("passed"),
            "source_blocker_count": remaining_blocker_action_audit.get("source_blocker_count"),
            "action_type_counts": remaining_blocker_action_audit.get("action_type_counts"),
            "local_model_actions": remaining_blocker_action_audit.get("local_model_actions"),
            "hard_failures": remaining_blocker_action_audit.get("hard_failures"),
        },
    )
    stale_flag_keys = {
        (row.get("artifact"), row.get("flag"))
        for row in reportable_flag_audit.get("stale_raw_flags", [])
    }
    reportable_check_ids = {check.get("id") for check in reportable_flag_audit.get("checks", [])}
    v.check(
        "reportable artifact flag audit overrides superseded raw canonical booleans",
        reportable_flag_audit.get("script") == "audit_reportable_artifact_flags.py"
        and reportable_flag_audit.get("passed") is True
        and reportable_flag_audit.get("hard_failures") == []
        and reportable_check_ids
        == {
            "t1_iter12_honest_floor",
            "t1_iter34_hybrid_candidate",
            "t1_iter46_etrobust_diagnostic",
            "t3_iter5_historical_target_contaminated",
            "t3_iter47_validrange_current",
        }
        and ("t1_iter34_hybrid_candidate", "is_canonical_update") in stale_flag_keys
        and ("t3_iter5_historical_target_contaminated", "is_lockbox_headline") in stale_flag_keys
        and "Current claim status is defined by the post-audit policy layer" in reportable_flag_audit.get("policy", "")
        and "current claim value is `False`" in reportable_flag_audit_md,
        {
            "passed": reportable_flag_audit.get("passed"),
            "checks": len(reportable_flag_audit.get("checks", [])),
            "stale_raw_flags": reportable_flag_audit.get("stale_raw_flags"),
            "hard_failures": reportable_flag_audit.get("hard_failures"),
        },
    )
    per_item_rows = {row.get("item"): row for row in per_item_map.get("rows", [])}
    per_item_counts = per_item_map.get("status_counts", {})
    per_item_check_names = {check.get("name") for check in per_item_map.get("key_checks", [])}
    v.check(
        "per-item evidence map labels current item CCC claim scope",
        per_item_map.get("script") == "audit_per_item_evidence_map.py"
        and per_item_map.get("passed") is True
        and per_item_counts
        == {
            "missing_or_backfill_only_unobservable": 3,
            "historical_iter8_per_item_lockbox_supplementary": 7,
            "current_t1_iter12_component": 6,
            "iter17_reportable_per_item_win": 2,
        }
        and set(per_item_rows) == set(range(1, 19))
        and per_item_rows.get(1, {}).get("status") == "missing_or_backfill_only_unobservable"
        and per_item_rows.get(9, {}).get("status") == "current_t1_iter12_component"
        and approx_equal(per_item_rows.get(9, {}).get("ccc"), 0.4436666667)
        and approx_equal(per_item_rows.get(12, {}).get("ccc"), 0.5928)
        and per_item_rows.get(15, {}).get("status") == "iter17_reportable_per_item_win"
        and approx_equal(per_item_rows.get(15, {}).get("ccc"), 0.1099)
        and per_item_rows.get(17, {}).get("n") == 93
        and per_item_rows.get(18, {}).get("status") == "iter17_reportable_per_item_win"
        and approx_equal(per_item_rows.get(18, {}).get("ccc"), 0.4858)
        and approx_equal(per_item_map.get("composites", {}).get("t1_iter12_sum", {}).get("ccc"), 0.6550)
        and per_item_map.get("composites", {}).get("t3_per_item_sum_historical", {}).get("status")
        == "historical_dead_route_not_current_t3"
        and approx_equal(per_item_map.get("composites", {}).get("t3_per_item_sum_historical", {}).get("ccc"), 0.2646)
        and per_item_map.get("missing_artifacts") == []
        and all(check.get("passed") is True for check in per_item_map.get("key_checks", []))
        and {
            "status_counts_match_current_claim_scope",
            "t3_per_item_sum_is_historical_dead_route",
            "all_source_artifacts_exist",
        }.issubset(per_item_check_names)
        and "T3 per-item sum" in per_item_map_md
        and "historical_dead_route_not_current_t3" in per_item_map_md,
        {
            "passed": per_item_map.get("passed"),
            "status_counts": per_item_counts,
            "t1_item9": per_item_rows.get(9),
            "t1_item12": per_item_rows.get(12),
            "item15": per_item_rows.get(15),
            "item17": per_item_rows.get(17),
            "item18": per_item_rows.get(18),
            "t3_per_item_sum": per_item_map.get("composites", {}).get("t3_per_item_sum_historical"),
            "checks": sorted(per_item_check_names),
        },
    )
    per_item_oof_key_names = {check.get("name") for check in per_item_oof_scope.get("key_checks", [])}
    per_item_oof_t1 = next(
        (
            check
            for check in per_item_oof_scope.get("key_checks", [])
            if check.get("name") == "t1_iter12_item_oofs_sum_to_canonical_oof"
        ),
        {},
    )
    per_item_oof_item18_warning = [
        warning
        for warning in per_item_oof_scope.get("warnings", [])
        if warning.get("item") == 18
        and warning.get("warning") == "json_reported_valid_n_differs_from_oof_slot_len"
    ]
    v.check(
        "per-item OOF companion scope audit verifies T1 summation and JSON-scope caveats",
        per_item_oof_scope.get("script") == "audit_per_item_oof_companion_scope.py"
        and per_item_oof_scope.get("passed") is True
        and per_item_oof_scope.get("oof_backed_rows") == 15
        and per_item_oof_scope.get("row_level_json_comparison_available_count") == 0
        and per_item_oof_scope.get("hard_warnings") == []
        and {
            "all_15_oof_backed_rows_have_finite_expected_slot_arrays",
            "row_level_json_prediction_comparison_unavailable_for_per_item_artifacts",
            "t1_iter12_item_oofs_sum_to_canonical_oof",
            "item18_valid_n_mismatch_recorded_as_warning_not_failure",
        }.issubset(per_item_oof_key_names)
        and all(check.get("passed") is True for check in per_item_oof_scope.get("key_checks", []))
        and per_item_oof_t1.get("max_abs_diff_vs_t1_composite_oof") == 0.0
        and approx_equal(per_item_oof_t1.get("t1_metrics_from_summed_item_oofs", {}).get("ccc"), 0.6550)
        and approx_equal(per_item_oof_t1.get("t1_metrics_from_summed_item_oofs", {}).get("mae"), 1.5614, 1e-3)
        and per_item_oof_t1.get("t1_metrics_from_summed_item_oofs", {}).get("n") == 94
        and bool(per_item_oof_item18_warning)
        and "Row-level JSON comparison available count: `0`" in per_item_oof_scope_md
        and "Max abs diff vs canonical T1 OOF" in per_item_oof_scope_md,
        {
            "passed": per_item_oof_scope.get("passed"),
            "oof_backed_rows": per_item_oof_scope.get("oof_backed_rows"),
            "row_level_json_comparison_available_count": per_item_oof_scope.get("row_level_json_comparison_available_count"),
            "key_checks": sorted(per_item_oof_key_names),
            "t1_check": per_item_oof_t1,
            "warnings": per_item_oof_scope.get("warnings"),
        },
    )
    safe_cache = validate_cache_manifest(RESULTS / "clinical_extras.csv")
    item11_recording_cache = validate_cache_manifest(RESULTS / "item11_multiscale_recordings.csv")
    harnet_cache = validate_cache_manifest(RESULTS / "harnet_subj_embeddings.csv")
    placeholder_cache = validate_cache_manifest(RESULTS / "item_specific_features.csv")
    missing_manifest_cache = validate_cache_manifest(RESULTS / "moment_subj_embeddings.csv")
    v.check(
        "cache provenance guard accepts concrete manifests and rejects remaining placeholders",
        safe_cache["safe_for_inductive_headline"] is True
        and safe_cache["data_sha256_matches"] is True
        and item11_recording_cache["safe_for_inductive_headline"] is True
        and item11_recording_cache["data_sha256_matches"] is True
        and harnet_cache["safe_for_inductive_headline"] is True
        and harnet_cache["data_sha256_matches"] is True
        and placeholder_cache["safe_for_inductive_headline"] is False
        and placeholder_cache["status"] == "partial_manifest_diagnostic_only"
        and "git_sha" in placeholder_cache["nullish_required_fields"]
        and missing_manifest_cache["safe_for_inductive_headline"] is False
        and missing_manifest_cache["status"] == "missing_manifest_diagnostic_only",
        {
            "safe_cache": {
                "path": safe_cache["cache_path"],
                "status": safe_cache["status"],
                "data_sha256_matches": safe_cache["data_sha256_matches"],
            },
            "item11_recording_cache": {
                "path": item11_recording_cache["cache_path"],
                "status": item11_recording_cache["status"],
                "data_sha256_matches": item11_recording_cache["data_sha256_matches"],
            },
            "harnet_cache": {
                "path": harnet_cache["cache_path"],
                "status": harnet_cache["status"],
                "data_sha256_matches": harnet_cache["data_sha256_matches"],
            },
            "placeholder_cache": {
                "path": placeholder_cache["cache_path"],
                "status": placeholder_cache["status"],
                "nullish_required_fields": placeholder_cache["nullish_required_fields"],
            },
            "missing_manifest_cache": {
                "path": missing_manifest_cache["cache_path"],
                "status": missing_manifest_cache["status"],
                "missing_required_fields": missing_manifest_cache["missing_required_fields"],
            },
        },
    )
    guard_integrated_scripts = [
        "compose_t1_iter14_fog.py",
        "compose_t1_iter15_harnet.py",
        "run_t3_iter23_clinical_ablation.py",
        "run_t3_iter24_stage2_forced.py",
    ]
    missing_guard_imports = [
        script
        for script in guard_integrated_scripts
        if "require_cache_manifest" not in read_text(ROOT / script)
    ]
    v.check(
        "safe-cache historical scripts use shared provenance guard",
        not missing_guard_imports,
        {"scripts": guard_integrated_scripts, "missing_guard_imports": missing_guard_imports},
    )

    dua_status = load_json(RESULTS / "iter26_dua_status_20260508.json")
    access_reqs = dua_status.get("access_requirements", [])
    denied_requirements = [ar for ar in access_reqs if ar.get("is_approved_for_user") is False]
    v.check(
        "Hssayeni Synapse access is still DUA-blocked",
        bool(denied_requirements),
        {"denied_requirement_ids": [ar.get("id") for ar in denied_requirements]},
        required=False,
    )

    t1_break_attempted = bool(t1_best.get("ccc", 0) > t1_floor.get("ccc", 0))
    t1_candidate_fully_cleared = bool(t1_p2_verdict.get("p2_robust_one_sided_pass"))
    t1_iter46_above_iter12_strict = bool(t1_iter46_cmp.get("verdict", {}).get("above_iter12_same_sids"))
    t1_iter46_above_iter34 = bool(t1_iter46_cmp.get("verdict", {}).get("above_iter34_same_sids"))
    t1_x4_frac_min = min(
        float(v)
        for v in (t1_x4_seed_a.get("frac_pos"), t1_x4_seed_b.get("frac_pos"))
        if isinstance(v, (int, float))
    )
    t1_x4_passes_gate = bool(
        isinstance(t1_x4_bag.get("delta_ccc"), (int, float))
        and t1_x4_bag.get("delta_ccc") >= 0.025
        and t1_x4_frac_min >= 0.95
    )
    t3_corrected_ccc = float(min_current.get("new_refit_metrics", {}).get("ccc", 0.0))
    t3_ceiling_broken = bool(t3_corrected_ccc > 0.5227 + 5e-4)
    hssayeni_blocked = bool(denied_requirements)
    goal_complete = bool(t1_break_attempted and t3_ceiling_broken and not hssayeni_blocked)
    blockers = []
    if not t3_ceiling_broken:
        blockers.append("T3 valid-range-corrected CCC is 0.3784; old iter5 0.5227 and iter41 0.3948 are target-contaminated or superseded, and no improved corrected lockbox exists.")
        blockers.append("T3 iter47 residual-anatomy audit shows tail compression remains dominant (residual corr -0.7771, Q1/Q4 mean residuals +10.02/-9.20, WPD within-site CCC 0.0515) and no single post-hoc residual-feature |r| exceeds 0.290.")
        blockers.append("T3 iter47 CCC-rescale sanity shows OOF-level variance matching can cosmetically raise CCC to 0.3996, but it worsens MAE by +1.1398 and is not a fully nested reportable meta-model.")
        blockers.append("Current headline influence audit finds no single-subject redline, but influence is severity-tail concentrated (T3 top leave-one |dCCC| 0.0381, abs target-distance vs abs influence r 0.6779).")
        blockers.append("T3 iter47 domain residual audit shows corrected residuals are dominated by true non-gait Part III burden (unobservable_non_gait residual r -0.8004); privileged domain oracles are non-deployable because they require true clinical labels.")
        blockers.append("T3 iter47 item-level residual audit localizes the largest residual associations to non-WearGait-observable clinical items (item 6 pronation/supination r -0.571, oracle dCCC +0.282; non-observable mean |r| 0.371 vs observable 0.247), so another WearGait-only scalar-feature or calibration screen is not justified.")
        blockers.append("T3 clinical-dependency audit shows corrected T3 is clinical/intake + IMU; intercept/IMU-only CCC is only 0.2449.")
        blockers.append("T3 current Stage 2 uses non-fold-local historical `dst_*` walkway-distiller features, but the no-`dst_*` sensitivity is essentially unchanged (CCC 0.3766 vs 0.3784); disclose as provenance caveat.")
        blockers.append("The live `ablation_v3_features.csv` V2 cache remains missing-manifest diagnostic-only; provenance audit records do_not_synthesize_clean_manifest.")
        blockers.append("A non-destructive `ablation_v3_features.csv` regeneration probe failed closed because the current remote lacks control clinical data, control CSVs, and walkway metrics; no clean sidecar was synthesized.")
        blockers.append("The exact WearGait Synapse recovery path is now known (`syn55105521`, `syn61370552`, `syn64589881`), but no Synapse token/config is present on the remote and the 680-file control CSV download has not been run.")
        blockers.append("FoG-STAR iter38 Stage-1 augmentation screen failed its gate; no T3 lockbox was run.")
        blockers.append("FoG-STAR iter39 is partial external-validity evidence only, not an internal ceiling break.")
        blockers.append("iter40 local-residual wildcard failed its 5-fold gate.")
        blockers.append("iter50 low-degree nested convex mix failed its corrected-target 5-fold gate; nested-convex CCC was 0.3083 vs baseline 0.3759.")
        blockers.append("iter42 primary Part III proration failed; loose le7 sensitivity is not promotable.")
        blockers.append("T3 Slot F CQR-width abstention opens a deployable-secondary boundary result (0.4237 @70%, 0.5370 @50%), but the seed-101 replication still fails the frac>full >= 0.95 promotion gate, so it does not rescue the full-cohort T3 ceiling.")
        blockers.append("T3 S13/S15 PH/MFDFA transfer extension is closed without promotion: S13 JOINT failed the 5-fold screen and S15 retained-bootstrap frac>full remains below 0.95 at both 70% and 50% coverage.")
        blockers.append("COPS iter49 full zero-shot is external-validity evidence only: wrist-only transfer is null, clinical+wrist transfer is partial, and it cannot update the internal T3 headline.")
        blockers.append("TLVMC/DeFOG iter51 is partial external-validity evidence only: Track A lower-back magnitude CCC is 0.2695 with compressed predictions, and no external outcome can update the internal T3 headline.")
        blockers.append("PDFE turning-in-place iter52 is external-validity evidence only: WearGait shank transfer is negative (Track A CCC -0.1008), clinical+shank transfer is weak/uncertain (Track B 0.1340 with CI crossing zero), and no external outcome can update the internal T3 headline.")
        blockers.append("Parkinson@Home iter53 is a public direct T3 route but hard-stopped before scoring: only 18 valid OFF PD subjects remained after the frozen feature-readability filter versus the pre-registered N>=20 minimum, so no Track A/C/D metric exists and no internal T3 headline can change.")
    if hssayeni_blocked:
        blockers.append("Hssayeni/MJFF external data path remains Synapse DUA-blocked.")
        blockers.append("PPMI/Verily is a newly documented priority external route, but it also requires PPMI DUA/application credentials before any scaffold or remote job is justified.")
        blockers.append("WATCH-PD is a protocol-matched direct T3 route, but it requires C-Path 3DT or Steering Committee access and row-level schema before any scaffold or remote job is justified.")
        blockers.append("ICICLE-PD/ICICLE-GAIT is a request-gated lower-back longitudinal T3 route; no scaffold or remote job is justified until data access and schema exist.")
        blockers.append("CNS Portugal/Lobo AX3 gait is a request-gated direct T3 route; no scaffold or remote job is justified until author/CNS data access and schema exist.")
        blockers.append("Mobilise-D TVS is not a clinical UPDRS-III regression route, and Mobilise-D CVS remains a release/schema watch route; no scaffold or remote job is justified until row-level data access exists.")
        blockers.append("Harmonized Upper/Lower Limb Accelerometry is daily-life ActiGraph rehab data with no confirmed Part III/T1 target; no scaffold or remote job is justified for T1/T3 CCC.")
        blockers.append("Monipar/BIOCLITE are public consumer-smartwatch subitem datasets, but neither has total T3 or the full T1 9-14 composite; no preregistration or download is justified for this objective.")
        blockers.append("Zenodo 14848598 is a public derived CSF/clinical/gait-summary table, not raw wearable IMU or an auditable T1/T3 sensor-clinical cohort; no preregistration or download is justified.")
        blockers.append("Fay-Karmon advanced-PD smartwatch monitoring is N=21, request-only, proprietary/schema-hidden, and no T1 route is visible; no scaffold or remote job is justified before author approval and row-level schema.")
        blockers.append("Marital-dyad GeneActiv social actigraphy is N=27 PD, request-only, daily-life/dyad oriented rather than structured gait/balance, and no T1 route is visible; no scaffold or remote job is justified before author approval and row-level schema.")
        blockers.append("Personalized Parkinson Project / PD-VME is a strong Verily-watch peer route, but it is RDSRC-gated and schema-hidden; no scaffold or remote job is justified until access exists.")
    if not t1_break_attempted:
        blockers.append("T1 has no candidate above the canonical floor.")
    if t1_break_attempted and not t1_candidate_fully_cleared:
        blockers.append("T1 hygiene-corrected iter34 is above the canonical floor but remains a candidate: CCC 0.7170 on N=92, below the superseded original N=93 iter34 value 0.7366.")
        blockers.append("T1 iter34 still carries robustness caveats: the original P2 noisy-test bootstrap upper bound crosses the +0.05 margin, and the valid-auxiliary rerun degraded rather than broke the old ceiling.")
    if not t1_iter46_above_iter12_strict or not t1_iter46_above_iter34:
        blockers.append("T1 iter46 ET-only robustification did not break iter34 and did not strictly clear iter12.")
    if not t1_x4_passes_gate:
        blockers.append("T1 X4 equal-weight 2-bag is the strongest current in-cohort lift (CCC 0.7345, delta +0.0175 vs iter34, frac>0 0.910/0.911), but it misses the delta >= +0.025 and frac>0 >= 0.95 promotion gates; report only as near-miss/external-replication candidate.")

    hard_failures = v.hard_failures
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "verify_current_goal_state.py",
        "current_state_verified": not hard_failures,
        "goal_complete": goal_complete,
        "next_allowed_action": proresults_audit.get("next_allowed_action"),
        "next_action": lifecycle_next_action,
        "access_lifecycle_current_action": access_lifecycle_state_handoff.get("current_action"),
        "pre_submission_handoff": access_lifecycle_state_handoff.get(
            "pre_submission_handoff"
        ),
        "ppmi_next_action_status": {
            "decision": ppmi_next_action_status_audit.get("decision"),
            "source_audit": ppmi_next_action_status_audit.get("source_audit"),
            "current_submission_handoff": ppmi_next_action_status_audit.get(
                "current_submission_handoff"
            ),
        },
        "t1_t3_goal_status": {
            "decision": t1_t3_goal_status_audit.get("decision"),
            "status_script": t1_t3_goal_status_audit.get("status_script"),
            "goal_complete": t1_t3_goal_status_audit.get("goal_complete"),
            "source_audits": t1_t3_goal_status_audit.get("source_audits"),
            "next_non_redundant_actions": proresults_audit.get(
                "next_non_redundant_actions"
            ),
        },
        "ppmi_current_submission_handoff": {
            "decision": ppmi_current_submission_handoff.get("decision"),
            "current_action": ppmi_current_submission_handoff.get("current_action"),
            "package_artifacts": ppmi_current_submission_handoff.get("package_artifacts"),
            "post_approval_artifacts": ppmi_current_submission_handoff.get(
                "post_approval_artifacts"
            ),
            "workflow_command_sequence": ppmi_current_submission_handoff.get(
                "workflow_command_sequence"
            ),
            "goal_complete": ppmi_current_submission_handoff.get("goal_complete"),
        },
        "ppmi_zeroshot_blueprint": {
            "decision": ppmi_zeroshot_blueprint_audit.get("decision"),
            "blueprint": ppmi_zeroshot_blueprint_audit.get("blueprint"),
            "goal_complete": ppmi_zeroshot_blueprint_audit.get("goal_complete"),
        },
        "ppmi_target_free_manifest_validator": {
            "decision": ppmi_target_free_manifest_validator_audit.get("decision"),
            "template": ppmi_target_free_manifest_validator_audit.get("template"),
            "validator": ppmi_target_free_manifest_validator_audit.get("validator"),
            "goal_complete": ppmi_target_free_manifest_validator_audit.get("goal_complete"),
        },
        "post_approval_schema_probe_handoff": access_lifecycle_state_handoff.get(
            "post_approval_schema_probe_handoff"
        ),
        "external_schema_probe_handoff": {
            "decision": external_schema_probe_handoff_audit.get("decision"),
            "handoff_markdown": external_schema_probe_handoff_audit.get("handoff_markdown"),
            "route_count": external_schema_probe_handoff_audit.get("route_count"),
            "goal_complete": external_schema_probe_handoff_audit.get("goal_complete"),
            "post_approval_workflow_step_ids_by_route": (
                external_schema_probe_handoff_audit.get(
                    "post_approval_workflow_step_ids_by_route"
                )
            ),
        },
        "external_target_free_manifest_templates": {
            "decision": external_target_free_manifest_templates_audit.get("decision"),
            "templates_markdown": external_target_free_manifest_templates_audit.get(
                "templates_markdown"
            ),
            "route_count": external_target_free_manifest_templates_audit.get("route_count"),
            "goal_complete": external_target_free_manifest_templates_audit.get("goal_complete"),
            "post_schema_workflow_step_ids_by_route": (
                external_target_free_manifest_templates_audit.get(
                    "post_schema_workflow_step_ids_by_route"
                )
            ),
        },
        "external_zeroshot_blueprint_handoff": {
            "decision": external_zeroshot_blueprint_handoff_audit.get("decision"),
            "handoff_markdown": external_zeroshot_blueprint_handoff_audit.get(
                "handoff_markdown"
            ),
            "route_count": external_zeroshot_blueprint_handoff_audit.get("route_count"),
            "goal_complete": external_zeroshot_blueprint_handoff_audit.get("goal_complete"),
        },
        "external_formula_sha_templates": {
            "decision": external_formula_sha_templates_audit.get("decision"),
            "templates_markdown": external_formula_sha_templates_audit.get(
                "templates_markdown"
            ),
            "route_count": external_formula_sha_templates_audit.get("route_count"),
            "ppmi_formula_contract_present": external_formula_sha_ppmi.get(
                "ppmi_formula_contract_present"
            ),
            "ppmi_contract_negative_failed": external_formula_sha_ppmi.get(
                "ppmi_contract_negative_failed"
            ),
            "ppmi_bad_contract_hard_failures": external_formula_sha_ppmi.get(
                "ppmi_bad_contract_hard_failures"
            ),
            "post_formula_workflow_step_ids_by_route": (
                external_formula_sha_templates_audit.get(
                    "post_formula_workflow_step_ids_by_route"
                )
            ),
            "goal_complete": external_formula_sha_templates_audit.get("goal_complete"),
        },
        "external_zeroshot_result_templates": {
            "decision": external_zeroshot_result_templates_audit.get("decision"),
            "templates_markdown": external_zeroshot_result_templates_audit.get(
                "templates_markdown"
            ),
            "route_count": external_zeroshot_result_templates_audit.get("route_count"),
            "ppmi_result_contract_present": external_zeroshot_result_ppmi.get(
                "ppmi_result_contract_present"
            ),
            "ppmi_contract_negative_failed": external_zeroshot_result_ppmi.get(
                "ppmi_contract_negative_failed"
            ),
            "ppmi_bad_contract_hard_failures": external_zeroshot_result_ppmi.get(
                "ppmi_bad_contract_hard_failures"
            ),
            "post_score_reporting_workflow_step_ids_by_route": (
                external_zeroshot_result_templates_audit.get(
                    "post_score_reporting_workflow_step_ids_by_route"
                )
            ),
            "goal_complete": external_zeroshot_result_templates_audit.get("goal_complete"),
        },
        "t1_break_attempted": t1_break_attempted,
        "t1_candidate_fully_cleared": t1_candidate_fully_cleared,
        "t1_iter46_above_iter12_strict": t1_iter46_above_iter12_strict,
        "t1_iter46_above_iter34": t1_iter46_above_iter34,
        "t1_x4_equal_weight_2bag": {
            "ccc": t1_x4_bag.get("loocv_ccc"),
            "delta_vs_iter34": t1_x4_bag.get("delta_ccc"),
            "delta_mae": t1_x4_bag.get("delta_mae"),
            "frac_positive_seed_A": t1_x4_seed_a.get("frac_pos"),
            "frac_positive_seed_B": t1_x4_seed_b.get("frac_pos"),
            "frac_positive_min": t1_x4_frac_min,
            "passes_gate": t1_x4_passes_gate,
            "verdict": t1_x4.get("verdict_provisional"),
            "path": "results/lockbox_t1_X4_equal_weight_2bag_20260516T074106Z.json",
        },
        "t3_ceiling_broken": t3_ceiling_broken,
        "hssayeni_dua_blocked": hssayeni_blocked,
        "completion_audit_goal_complete": proresults_audit.get("goal_complete"),
        "completion_audit_hard_gaps": proresults_audit.get("hard_gaps"),
        "blockers": blockers,
        "hard_failures": hard_failures,
        "checks": v.checks,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {OUT.relative_to(ROOT)}")
    print(f"current_state_verified={report['current_state_verified']}")
    print(f"goal_complete={report['goal_complete']}")
    if blockers:
        print("blockers:")
        for blocker in blockers:
            print(f"- {blocker}")
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
