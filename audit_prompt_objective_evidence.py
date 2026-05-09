"""Build a prompt-to-artifact evidence checklist for the active thread goal.

This is a completion-audit helper, not a success marker. It checks the broad
research objective against concrete repo artifacts and command status, then
writes both JSON and Markdown reports.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "prompt_objective_evidence_audit_20260508.json"
OUT_MD = RESULTS / "prompt_objective_evidence_audit_20260508.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def approx(value: Any, expected: float, tol: float = 5e-4) -> bool:
    try:
        return abs(float(value) - expected) <= tol
    except (TypeError, ValueError):
        return False


def exists_all(paths: list[str]) -> tuple[bool, list[str]]:
    missing = [p for p in paths if not (ROOT / p).exists()]
    return not missing, missing


def command_path(name: str) -> str | None:
    return shutil.which(name)


def run_status(cmd: list[str], timeout_s: int = 20) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "output_tail": proc.stdout[-3000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": "timeout",
            "output_tail": (exc.stdout or "")[-3000:] if isinstance(exc.stdout, str) else "",
        }
    except FileNotFoundError as exc:
        return {
            "cmd": cmd,
            "returncode": "not_found",
            "output_tail": str(exc),
        }


def checklist_item(requirement: str, passed: bool, status: str, evidence: Any) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "passed": bool(passed),
        "status": status,
        "evidence": evidence,
    }


def cell_by(result: dict[str, Any], cohort: str, stage2_policy: str) -> dict[str, Any]:
    for cell in result.get("cells", []):
        if cell.get("cohort") == cohort and cell.get("stage2_policy") == stage2_policy:
            return cell
    return {}


def policy_metrics(result: dict[str, Any], policy: str) -> dict[str, Any]:
    for row in result.get("policy_rows", []):
        if row.get("stage1_policy") == policy:
            return row.get("mean_prediction_metrics", {})
    return {}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)

    claude = read_text(ROOT / "CLAUDE.md")
    agents = read_text(ROOT / "AGENTS.md")
    findings = read_text(ROOT / "findings.md")
    progress = read_text(ROOT / "progress.md")
    task_plan = read_text(ROOT / "task_plan.md")
    readme = read_text(ROOT / "README.md")
    completion_audit = read_text(RESULTS / "thread_goal_completion_audit_20260508.md")
    external_md = read_text(RESULTS / "external_dataset_route_audit_20260508.md")
    index_md = read_text(RESULTS / "current_best_pipeline_artifact_index_20260508.md")
    ppmi_runbook = read_text(ROOT / "scripts/ppmi_verily_setup.md")
    ppp_runbook = read_text(ROOT / "scripts/ppp_pd_vme_request_setup.md")
    watchpd_runbook = read_text(ROOT / "scripts/watchpd_request_setup.md")
    icicle_runbook = read_text(ROOT / "scripts/icicle_request_setup.md")
    cns_runbook = read_text(ROOT / "scripts/cns_portugal_request_setup.md")
    hssayeni_runbook = read_text(ROOT / "scripts/synapse_hssayeni_setup.md")
    raw_recovery_runbook = read_text(ROOT / "scripts/weargait_raw_data_recovery_runbook.md")

    t1_iter12 = load_json(RESULTS / "t1_iter12_honest_composite.json")
    t1_iter34 = load_json(RESULTS / "lockbox_t1_iter34_hybrid_20260506_141720.json")
    t1_iter46 = load_json(RESULTS / "lockbox_t1_iter46_etrobust_20260508_162825.json")
    t1_p2 = load_json(RESULTS / "iter34_p2_robustness_20260508.json")
    t1_aux = load_json(RESULTS / "t1_iter48_aux_validrange_audit.json")
    t1_aux_order = load_json(RESULTS / "t1_iter34_aux_order_audit.json")
    t3_iter47 = load_json(RESULTS / "iter47_invalidcode_20260508_194605.json")
    t3_loso = load_json(RESULTS / "iter47_invalidcode_loso_20260508_195424.json")
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
    t3_clinical = load_json(RESULTS / "t3_clinical_dependency_20260508.json")
    t3_iter50 = load_json(RESULTS / "iter50_lowdf_convex_screen_20260508_225105.json")
    conformal = load_json(RESULTS / "current_conformal_abstention_20260508.json")
    external_json = load_json(RESULTS / "external_dataset_route_audit_20260508.json")
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
    verifier_json = load_json(RESULTS / "current_goal_state_verification_20260508.json")
    dashboard_manifest = load_json(RESULTS / "current_best_pipeline_dashboard" / "manifest.json")
    current_paper_manifest = load_json(RESULTS / "current_paper_export" / "manifest.json")
    canonical_claim_audit = load_json(RESULTS / "canonical_claim_consistency_audit_20260508.json")
    metric_recompute_audit = load_json(RESULTS / "headline_metric_recompute_audit_20260508.json")
    ccc_metric_audit = load_json(RESULTS / "ccc_metric_integrity_audit_20260509.json")
    oof_integrity_audit = load_json(RESULTS / "oof_artifact_integrity_audit_20260508.json")
    prereg_temporal_audit = load_json(RESULTS / "preregistration_temporal_integrity_audit_20260508.json")
    pre_audit_labeling_audit = load_json(RESULTS / "pre_audit_claim_labeling_audit_20260508.json")
    historical_subdomain_labeling_audit = load_json(RESULTS / "historical_subdomain_claim_labeling_audit_20260509.json")
    t1_candidate_labeling_audit = load_json(RESULTS / "t1_candidate_claim_labeling_audit_20260508.json")
    t3_complete33_labeling_audit = load_json(RESULTS / "t3_complete33_claim_labeling_audit_20260509.json")
    external_result_labeling_audit = load_json(RESULTS / "external_result_claim_labeling_audit_20260509.json")
    remaining_blocker_action_audit = load_json(RESULTS / "remaining_blocker_action_audit_20260509.json")
    external_access_readiness = load_json(RESULTS / "external_access_readiness_audit_20260509.json")
    access_submission_tracker = load_json(RESULTS / "access_submission_tracker_20260509.json")
    recent_external_web_leads = load_json(RESULTS / "recent_external_web_leads_20260509.json")
    kimi_recent_external_web_leads = read_text(RESULTS / "kimi_recent_external_web_leads_20260509.md")
    raw_recovery_runbook_audit = load_json(RESULTS / "weargait_raw_data_recovery_runbook_audit_20260509.json")
    task_plan_current_scope_audit = load_json(RESULTS / "task_plan_current_scope_audit_20260509.json")
    paper_generator_routing_audit = load_json(RESULTS / "paper_generator_routing_audit_20260509.json")
    readme_claim_routing_audit = load_json(RESULTS / "readme_claim_routing_audit_20260509.json")
    legacy_manuscript_surface_audit = load_json(RESULTS / "legacy_manuscript_surface_audit_20260509.json")
    historical_archive_surface_audit = load_json(RESULTS / "historical_archive_surface_audit_20260509.json")
    secret_hygiene_audit = load_json(RESULTS / "secret_hygiene_audit_20260509.json")
    reportable_flag_audit = load_json(RESULTS / "reportable_artifact_flag_audit_20260509.json")
    cache_manifest_audit = load_json(RESULTS / "cache_manifest_audit_20260508.json")
    missing_cache_origin_audit = load_json(RESULTS / "missing_cache_manifest_origin_audit_20260509.json")
    manual_cache_backfill_evidence = load_json(RESULTS / "manual_cache_backfill_evidence_20260509.json")
    per_item_map = load_json(RESULTS / "per_item_evidence_map_20260508.json")
    per_item_oof_scope = load_json(RESULTS / "per_item_oof_companion_scope_audit_20260508.json")
    t1_iter12_batch_integrity = load_json(RESULTS / "t1_iter12_batch_integrity_audit_20260508.json")
    ablation_v3_regeneration = load_json(RESULTS / "ablation_v3_regeneration_probe_20260509.json")
    synapse_recovery = load_json(RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.json")
    tlvmc_probe = load_json(RESULTS / "tlvmc_fog_route_probe_20260509.json")
    tlvmc_prereg = load_json(RESULTS / "preregistration_t3_iter51_tlvmc_defog_zeroshot.json")
    tlvmc_iter51 = load_json(RESULTS / "iter51_tlvmc_defog_zeroshot.json")
    pdfe_prereg = load_json(RESULTS / "preregistration_t3_iter52_pdfe_turning_zeroshot.json")
    pdfe_probe = load_json(RESULTS / "iter52_pdfe_turning_probe.json")
    pdfe_iter52 = load_json(RESULTS / "iter52_pdfe_turning_zeroshot.json")

    tool_paths = {
        "kimi": command_path("kimi"),
        "claude": command_path("claude"),
        "glmcode": command_path("glmcode"),
        "gemini": command_path("gemini"),
    }
    remote_status = run_status(["./gpu.sh", "--status"], timeout_s=30)

    t1_visuals_ok, t1_visuals_missing = exists_all(
        [
            "results/lockbox_t1_iter34_hybrid_20260506_141720.json",
            "results/lockbox_t1_iter34_hybrid_20260506_141720.oof.npy",
            "results/iter35_deepdive.html",
            "results/iter34_figures/fig1_oof_calibration_iter34.png",
        ]
    )
    t3_visuals_ok, t3_visuals_missing = exists_all(
        [
            "results/iter47_invalidcode_20260508_194605.json",
            "results/iter47_invalidcode_loso_20260508_195424.json",
            "results/t3_iter5_deepdive.html",
            "results/current_conformal_abstention.html",
        ]
    )
    external_ok, external_missing = exists_all(
        [
            "results/iter39_fogstar_zeroshot_20260508_143717.json",
            "results/iter49_cops_zeroshot.json",
            "scripts/probe_tlvmc_fog_route.py",
            "results/tlvmc_fog_route_probe_20260509.json",
            "results/tlvmc_fog_route_probe_20260509.md",
            "scripts/write_tlvmc_defog_prereg.py",
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
            "run_t3_iter52_pdfe_turning.py",
            "results/preregistration_t3_iter52_pdfe_turning_zeroshot.json",
            "results/preregistration_t3_iter52_pdfe_turning_zeroshot.md",
            "results/iter52_pdfe_turning_probe.json",
            "results/iter52_pdfe_turning_download_manifest.json",
            "results/iter52_pdfe_turning_features.csv",
            "results/iter52_pdfe_turning_features.csv.manifest.json",
            "results/iter52_pdfe_turning_zeroshot.json",
            "results/iter52_pdfe_turning_zeroshot_20260509_092223.json",
            "results/iter52_pdfe_turning_zeroshot_rows_20260509_092223.csv",
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
            "audit_recent_external_web_leads.py",
            "results/recent_external_web_leads_20260509.json",
            "results/recent_external_web_leads_20260509.md",
            "results/kimi_recent_external_web_leads_20260509.md",
            "scripts/ppmi_verily_setup.md",
            "scripts/ppp_pd_vme_request_setup.md",
            "scripts/watchpd_request_setup.md",
            "scripts/icicle_request_setup.md",
            "scripts/cns_portugal_request_setup.md",
            "scripts/synapse_hssayeni_setup.md",
            "audit_external_access_readiness.py",
            "results/external_access_readiness_audit_20260509.json",
            "results/external_access_readiness_audit_20260509.md",
            "audit_access_submission_tracker.py",
            "results/access_submission_tracker_20260509.json",
            "results/access_submission_tracker_20260509.md",
            "scripts/weargait_raw_data_recovery_runbook.md",
            "audit_weargait_raw_data_recovery_runbook.py",
            "results/weargait_raw_data_recovery_runbook_audit_20260509.json",
            "results/weargait_raw_data_recovery_runbook_audit_20260509.md",
            "audit_task_plan_current_scope.py",
            "results/task_plan_current_scope_audit_20260509.json",
            "results/task_plan_current_scope_audit_20260509.md",
            "audit_paper_generator_routing.py",
            "results/paper_generator_routing_audit_20260509.json",
            "results/paper_generator_routing_audit_20260509.md",
            "audit_readme_claim_routing.py",
            "results/readme_claim_routing_audit_20260509.json",
            "results/readme_claim_routing_audit_20260509.md",
            "audit_legacy_manuscript_surfaces.py",
            "results/legacy_manuscript_surface_audit_20260509.json",
            "results/legacy_manuscript_surface_audit_20260509.md",
            "audit_historical_archive_surfaces.py",
            "results/historical_archive_surface_audit_20260509.json",
            "results/historical_archive_surface_audit_20260509.md",
            "audit_secret_hygiene.py",
            "results/secret_hygiene_audit_20260509.json",
            "results/secret_hygiene_audit_20260509.md",
        ]
    )

    ppmi_route = next((r for r in external_json.get("routes", []) if "PPMI" in r.get("name", "")), {})
    watchpd_route = next((r for r in external_json.get("routes", []) if "WATCH-PD" in r.get("name", "")), {})
    icicle_route = next((r for r in external_json.get("routes", []) if "ICICLE" in r.get("name", "")), {})
    cns_route = next((r for r in external_json.get("routes", []) if "CNS Portugal" in r.get("name", "")), {})
    mobilised_route = next((r for r in external_json.get("routes", []) if "Mobilise-D" in r.get("name", "")), {})
    tlvmc_route = next((r for r in external_json.get("routes", []) if "TLVMC" in r.get("name", "")), {})
    pdfe_route = next((r for r in external_json.get("routes", []) if r.get("name") == "PDFE turning-in-place"), {})
    gait_biomech_route = next((r for r in external_json.get("routes", []) if r.get("name") == "Public overground walking full-body biomechanics"), {})
    hssayeni_route = next((r for r in external_json.get("routes", []) if "Hssayeni" in r.get("name", "")), {})
    phone_tremor_route = next((r for r in external_json.get("routes", []) if "Papadopoulos phone-call tremor" in r.get("name", "")), {})
    harmonized_accel_route = next((r for r in external_json.get("routes", []) if "Harmonized Upper/Lower Limb Accelerometry" in r.get("name", "")), {})
    monipar_route = next((r for r in external_json.get("routes", []) if r.get("name") == "Monipar"), {})
    bioclite_route = next((r for r in external_json.get("routes", []) if r.get("name") == "BIOCLITE"), {})
    ppp_route = next((r for r in external_json.get("routes", []) if "Personalized Parkinson Project" in r.get("name", "")), {})
    monipar_refresh = next((r for r in smartwatch_subitem_refresh.get("routes", []) if r.get("name") == "Monipar"), {})
    bioclite_refresh = next((r for r in smartwatch_subitem_refresh.get("routes", []) if r.get("name") == "BIOCLITE"), {})
    ppp_refresh = next((r for r in smartwatch_subitem_refresh.get("routes", []) if "Personalized Parkinson Project" in r.get("name", "")), {})
    derivative_multimodal_route = next((r for r in external_json.get("routes", []) if r.get("name") == "Comprehensive Multi-Modal Dataset for Parkinson's Disease Prediction"), {})
    advanced_smartwatch_route = next((r for r in external_json.get("routes", []) if "Advanced PD smartwatch" in r.get("name", "")), {})
    dyad_actigraphy_route = next((r for r in external_json.get("routes", []) if "Marital-dyad" in r.get("name", "")), {})
    luxembourg_route = next((r for r in external_json.get("routes", []) if "Luxembourg" in r.get("name", "")), {})
    prequantipark_route = next((r for r in external_json.get("routes", []) if "Pre-QuantiPark" in r.get("name", "")), {})
    tum_rocket_inception_route = next((r for r in external_json.get("routes", []) if "TUM Donie" in r.get("name", "") or "TUM Donié" in r.get("name", "")), {})
    paradigma_route = next((r for r in external_json.get("routes", []) if "ParaDigMa" in r.get("name", "")), {})
    yin_route = next((r for r in external_json.get("routes", []) if "Yin et al" in r.get("name", "")), {})
    parkinsonathome_route = next((r for r in external_json.get("routes", []) if "Parkinson@Home" in r.get("name", "")), {})
    paradigma_refresh = next((r for r in paradigma_yin_refresh.get("routes", []) if "ParaDigMa" in r.get("name", "")), {})
    yin_refresh = next((r for r in paradigma_yin_refresh.get("routes", []) if "Yin et al" in r.get("name", "")), {})
    smid_tremor_route = next((r for r in external_json.get("routes", []) if "Smid 2026" in r.get("name", "") or "Perioperative MDS-UPDRS-III tremor" in r.get("name", "")), {})
    pdassist_route = next((r for r in external_json.get("routes", []) if "PDAssist" in r.get("name", "") or "Guo 2025" in r.get("name", "")), {})
    smid_tremor_refresh = next((r for r in recent_external_web_leads.get("routes", []) if "Smid 2026" in r.get("name", "") or "Perioperative MDS-UPDRS-III tremor" in r.get("name", "")), {})
    pdassist_refresh = next((r for r in recent_external_web_leads.get("routes", []) if "PDAssist" in r.get("name", "") or "Guo 2025" in r.get("name", "")), {})
    yin_recent_refresh = next((r for r in recent_external_web_leads.get("routes", []) if "Yin et al" in r.get("name", "")), {})
    advanced_smartwatch_refresh = next((r for r in request_only_actigraphy_refresh.get("routes", []) if "Advanced PD smartwatch" in r.get("name", "")), {})
    dyad_actigraphy_refresh = next((r for r in request_only_actigraphy_refresh.get("routes", []) if "Marital-dyad" in r.get("name", "")), {})
    t3_iter47_current = cell_by(t3_iter47, "drop_allmissing_validrange", "stage2_current")
    t3_loso_current = cell_by(t3_loso, "drop_allmissing_validrange", "stage2_current")
    t3_intercept = policy_metrics(t3_clinical, "intercept_only")
    t3_conformal = conformal.get("models", {}).get("t3_iter47_stage2_current", {})
    t3_rescale_methods = t3_iter47_ccc_rescale.get("methods", {})
    t3_rescale_variance = t3_rescale_methods.get("oof_level_leave_one_variance_match", {})
    t3_rescale_variance_metrics = t3_rescale_variance.get("metrics", {})
    t3_rescale_variance_boot = t3_rescale_variance.get("paired_bootstrap_vs_base", {})
    influence_t3 = headline_influence.get("audits", {}).get("t3_iter47_validrange_current", {})
    influence_t3_conc = influence_t3.get("influence_concentration", {})
    influence_t3_corr = influence_t3.get("influence_correlations", {})
    influence_t1_matched = headline_influence.get("matched_t1_iter34_vs_iter12", {})
    domain_rows = {row.get("domain"): row for row in t3_domain_residual.get("domain_summary", [])}
    domain_unobs = domain_rows.get("unobservable_non_gait", {})
    domain_upper = domain_rows.get("upper_limb_brady_4_6", {})
    domain_multi = t3_domain_residual.get("multidomain_ridge10_privileged_oracle", {})
    item_top_residual = (t3_item_residual.get("top_items_by_abs_residual_corr") or [{}])[0]
    item_observable = t3_item_residual.get("observable_vs_unobservable_summary", {})

    checks = [
        checklist_item(
            "Act slowly/analytically and follow repo leakage discipline",
            all(s in task_plan for s in ["Immediate objective", "Verify the evidence", "Choose the next concrete action"])
            and "Current completion criteria (post-iter47)" in task_plan
            and "goal remains **not complete**" in task_plan
            and "Leakage Rules" in agents
            and "canonical-numbers source of truth" in agents,
            "covered",
            {"files": ["task_plan.md", "AGENTS.md"]},
        ),
        checklist_item(
            "Use web search / current SOTA context",
            "F-web-20260508" in findings
            and "CARE-PD" in findings
            and "FoG-STAR" in findings
            and "COPS" in external_md
            and "PPMI / Verily Study Watch" in external_md
            and "WATCH-PD" in external_md
            and "ICICLE-PD / ICICLE-GAIT" in external_md
            and "CNS Portugal / Lobo" in external_md
            and "Mobilise-D TVS / CVS" in external_md
            and "TLVMC / DeFOG" in external_md
            and "PDFE turning-in-place" in external_md
            and "Public overground walking full-body biomechanics" in external_md
            and "Papadopoulos phone-call tremor" in external_md
            and "Harmonized Upper/Lower Limb Accelerometry" in external_md
            and "Monipar" in external_md
            and "BIOCLITE" in external_md
            and "Comprehensive Multi-Modal Dataset" in external_md
            and "Advanced PD smartwatch home monitoring" in external_md
            and "Marital-dyad social actigraphy" in external_md
            and "Personalized Parkinson Project / PD Virtual Motor Exam" in external_md
            and "Parkinson@Home arm-swing validation" in external_md
            and "F-tlvmc-defog-route-20260509" in findings
            and "F-pdfe-turning-route-20260509" in findings
            and "F-phone-tremor-route-20260509" in findings
            and "F-harmonized-accel-route-20260509" in findings
            and "F-smartwatch-subitem-routes-20260509" in findings
            and "F-derivative-multimodal-route-20260509" in findings
            and "F-request-only-actigraphy-routes-20260509" in findings
            and "F-parkinsonathome-hard-stop-20260509" in findings,
            and "F-recent-external-web-leads-20260509" in findings
            and "Perioperative MDS-UPDRS-III tremor accelerometry" in external_md
            and "PDAssist de novo smartphone UPDRS Part III" in external_md,
            "covered",
            {"files": ["findings.md", "results/external_dataset_route_audit_20260508.md"]},
        ),
        checklist_item(
            "Use Kimi, Claude, GLMCode, and Gemini where available",
            "Kimi" in completion_audit
            and "Claude" in completion_audit
            and "glmcode" in completion_audit
            and "gemini" in completion_audit.lower()
            and tool_paths["kimi"] is not None
            and tool_paths["claude"] is not None
            and tool_paths["gemini"] is not None
            and tool_paths["glmcode"] is None,
            "covered_with_tool_friction",
            {
                "tool_paths": tool_paths,
                "persisted_evidence": "thread_goal_completion_audit_20260508.md records Kimi/Gemini use plus Claude low-credit and glmcode unavailable.",
            },
        ),
        checklist_item(
            "Use remote server and inspect utilization",
            "no jobs running" in str(remote_status.get("output_tail", "")).lower()
            and "165.22.71.91" in read_text(ROOT / "gpu.sh")
            and "2243" in read_text(ROOT / "gpu.sh"),
            "covered",
            {"remote_status": remote_status},
        ),
        checklist_item(
            "Create logs/visualizations of the best T1 and T3 pipelines",
            t1_visuals_ok and t3_visuals_ok and "current_best_pipeline_dashboard.html" in index_md,
            "covered",
            {
                "t1_missing": t1_visuals_missing,
                "t3_missing": t3_visuals_missing,
                "dashboard": "results/current_best_pipeline_dashboard.html",
            },
        ),
        checklist_item(
            "Keep artifact, claim-labeling, and reproducibility guards current",
            dashboard_manifest.get("completion_verdict") == "not_complete_t3_validrange_ceiling_unbroken_and_hssayeni_dua_blocked"
            and not [a for a in dashboard_manifest.get("artifacts", []) if not a.get("exists")]
            and current_paper_manifest.get("status") == "passed"
            and current_paper_manifest.get("validation_issues") == []
            and canonical_claim_audit.get("passed") is True
            and metric_recompute_audit.get("passed") is True
            and ccc_metric_audit.get("passed") is True
            and ccc_metric_audit.get("hard_failures") == []
            and ccc_metric_audit.get("max_abs_sample_minus_population_headline", 1.0) < 0.00001
            and oof_integrity_audit.get("passed") is True
            and prereg_temporal_audit.get("passed") is True
            and prereg_temporal_audit.get("hard_failures") == []
            and pre_audit_labeling_audit.get("passed") is True
            and pre_audit_labeling_audit.get("findings") == []
            and historical_subdomain_labeling_audit.get("passed") is True
            and historical_subdomain_labeling_audit.get("findings") == []
            and t1_candidate_labeling_audit.get("passed") is True
            and t1_candidate_labeling_audit.get("findings") == []
            and t1_candidate_labeling_audit.get("missing_required_snippets") == []
            and t3_complete33_labeling_audit.get("passed") is True
            and t3_complete33_labeling_audit.get("findings") == []
            and t3_complete33_labeling_audit.get("missing_required_snippets") == []
            and external_result_labeling_audit.get("passed") is True
            and external_result_labeling_audit.get("findings") == []
            and external_result_labeling_audit.get("missing_required_snippets") == []
            and external_result_labeling_audit.get("artifact_failures") == []
            and remaining_blocker_action_audit.get("passed") is True
            and remaining_blocker_action_audit.get("source_blocker_count") == 36
            and remaining_blocker_action_audit.get("local_model_actions") == []
            and remaining_blocker_action_audit.get("unmatched_blockers") == []
            and remaining_blocker_action_audit.get("action_type_counts", {}).get("no_prereg_no_rerun_same_policy") == 1
            and external_access_readiness.get("summary", {}).get("passed") is True
            and external_access_readiness.get("summary", {}).get("application_packet_ready_count") == 6
            and external_access_readiness.get("summary", {}).get("compute_ready_route_count") == 0
            and external_access_readiness.get("summary", {}).get("hard_failure_count") == 0
            and external_access_readiness.get("summary", {}).get("top_priority_route") == "PPMI / Verily Study Watch"
            and external_access_readiness.get("decision") == "access_packets_ready_no_compute"
            and access_submission_tracker.get("decision") == "access_submission_tracker_ready"
            and access_submission_tracker.get("summary", {}).get("passed") is True
            and access_submission_tracker.get("summary", {}).get("submit_ready_route_count") == 6
            and access_submission_tracker.get("summary", {}).get("compute_ready_route_count") == 0
            and access_submission_tracker.get("summary", {}).get("hard_failure_count") == 0
            and recent_external_web_leads.get("decision") == "recent_external_web_leads_documented_no_compute_route"
            and recent_external_web_leads.get("summary", {}).get("routes_checked") == 3
            and recent_external_web_leads.get("summary", {}).get("new_compute_ready_routes") == 0
            and recent_external_web_leads.get("summary", {}).get("new_scaffold_or_preregistration_actions") == 0
            and "None of the three leads justifies a scaffold" in kimi_recent_external_web_leads
            and raw_recovery_runbook_audit.get("passed") is True
            and raw_recovery_runbook_audit.get("decision") == "raw_data_recovery_runbook_ready_no_download"
            and raw_recovery_runbook_audit.get("hard_failures") == []
            and raw_recovery_runbook_audit.get("current_status", {}).get("preflight_status") == "missing_inputs"
            and raw_recovery_runbook_audit.get("current_status", {}).get("credentials_present") is False
            and raw_recovery_runbook_audit.get("current_status", {}).get("regeneration_probe_status") == "blocked_missing_regeneration_inputs"
            and "Do not synthesize a clean cache manifest" in raw_recovery_runbook
            and "Do not start a new T1/T3 model run" in raw_recovery_runbook
            and task_plan_current_scope_audit.get("passed") is True
            and task_plan_current_scope_audit.get("decision") == "task_plan_current_scope_guard_passed"
            and task_plan_current_scope_audit.get("hard_failures") == []
            and task_plan_current_scope_audit.get("current_scope", {}).get("legacy_success_findings") == []
            and paper_generator_routing_audit.get("passed") is True
            and paper_generator_routing_audit.get("decision") == "current_paper_renderer_route_guard_passed"
            and paper_generator_routing_audit.get("hard_failures") == []
            and paper_generator_routing_audit.get("current_renderer", {}).get("manifest", {}).get("status") == "passed"
            and paper_generator_routing_audit.get("current_renderer", {}).get("manifest", {}).get("validation_issues") == []
            and paper_generator_routing_audit.get("current_renderer", {}).get("forbidden_hits") == []
            and readme_claim_routing_audit.get("passed") is True
            and readme_claim_routing_audit.get("decision") == "readme_current_claim_route_guard_passed"
            and readme_claim_routing_audit.get("hard_failures") == []
            and readme_claim_routing_audit.get("unguarded_dangerous_hits") == []
            and readme_claim_routing_audit.get("missing_required") == []
            and "Current Post-Audit WearGait-PD Benchmark" in readme
            and "T1 canonical floor" in readme
            and "T1 strongest candidate" in readme
            and "T3 current" in readme
            and "legacy/retracted/pre-audit" in readme
            and legacy_manuscript_surface_audit.get("passed") is True
            and legacy_manuscript_surface_audit.get("decision") == "legacy_manuscript_surfaces_quarantined"
            and legacy_manuscript_surface_audit.get("hard_failures") == []
            and len(legacy_manuscript_surface_audit.get("legacy_surfaces", [])) == 16
            and legacy_manuscript_surface_audit.get("total_dangerous_hits", 0) > 0
            and historical_archive_surface_audit.get("passed") is True
            and historical_archive_surface_audit.get("decision") == "historical_archive_surfaces_quarantined"
            and historical_archive_surface_audit.get("hard_failures") == 0
            and historical_archive_surface_audit.get("surfaces_checked") == 11
            and historical_archive_surface_audit.get("total_stale_pattern_hits_retained_under_archive_banners", 0) > 0
            and secret_hygiene_audit.get("passed") is True
            and secret_hygiene_audit.get("decision") == "secret_hygiene_guard_passed"
            and secret_hygiene_audit.get("findings") == []
            and secret_hygiene_audit.get("hard_failures") == []
            and secret_hygiene_audit.get("sensitive_local_files", {}).get("TOKEN.md", {}).get("exists") is False
            and secret_hygiene_audit.get("sensitive_local_files", {}).get(".env", {}).get("exists") is False
            and reportable_flag_audit.get("passed") is True
            and reportable_flag_audit.get("hard_failures") == []
            and any(
                row.get("artifact") == "t1_iter34_hybrid_candidate"
                and row.get("flag") == "is_canonical_update"
                and row.get("current_claim_value") is False
                for row in reportable_flag_audit.get("stale_raw_flags", [])
            )
            and cache_manifest_audit.get("status_counts", {}).get("manifest_complete_clean_by_construction") == 4
            and cache_manifest_audit.get("status_counts", {}).get("missing_manifest_diagnostic_only") == 33
            and missing_cache_origin_audit.get("n_missing_manifests") == 33
            and missing_cache_origin_audit.get("decision_counts", {}).get("manual_backfill_candidate_needs_human_patch") == 5
            and manual_cache_backfill_evidence.get("n_candidates") == 5
            and manual_cache_backfill_evidence.get("decision_counts", {}).get("leave_missing_no_patch") == 5
            and per_item_map.get("passed") is True
            and per_item_map.get("missing_artifacts") == []
            and per_item_oof_scope.get("passed") is True
            and per_item_oof_scope.get("oof_backed_rows") == 15
            and per_item_oof_scope.get("row_level_json_comparison_available_count") == 0
            and t1_iter12_batch_integrity.get("pass") is True
            and t1_iter12_batch_integrity.get("hard_failures") == []
            and approx(t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("ccc"), 0.6550)
            and approx(t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("mae"), 1.5614, 1e-3)
            and t1_iter12_batch_integrity.get("batch", {}).get("single_coherent_batch") is True
            and t1_iter12_batch_integrity.get("batch", {}).get("uses_swaps") is False
            and t3_iter47_target_integrity.get("pass") is True
            and t3_iter47_target_integrity.get("hard_failures") == []
            and t3_iter47_target_integrity.get("warnings") == []
            and len(t3_iter47_target_integrity.get("target", {}).get("invalid_raw_subitem_values", [])) == 2
            and len(t3_iter47_target_integrity.get("target", {}).get("target_changed_rows", [])) == 1
            and t3_iter47_residual_anatomy.get("scope") == "diagnostic_only_no_model_selection"
            and approx(t3_iter47_residual_anatomy.get("overall_metrics", {}).get("residual_corr_with_true"), -0.7771)
            and t3_iter47_residual_anatomy.get("decision", {}).get("no_model_promotion") is True
            and "not fold-local feature selection" in t3_iter47_residual_anatomy_md
            and t3_iter47_ccc_rescale.get("scope") == "diagnostic_only_not_reportable_model"
            and t3_iter47_ccc_rescale.get("methodology_guardrail", {}).get("not_fully_nested") is True
            and t3_iter47_ccc_rescale.get("decision", {}).get("no_model_promotion") is True
            and approx(t3_rescale_variance_metrics.get("ccc"), 0.3996)
            and approx(t3_rescale_variance_boot.get("mae_delta_mean"), 1.1398, 1e-3)
            and "fully nested outer/inner prediction artifact" in t3_iter47_ccc_rescale_md
            and headline_influence.get("decision", {}).get("scope") == "diagnostic_only_no_model_selection"
            and headline_influence.get("decision", {}).get("redline_summary", {}).get("single_subject_redline_hit") is False
            and headline_influence.get("decision", {}).get("redline_summary", {}).get("top5_share_redline_hit") is False
            and headline_influence.get("decision", {}).get("redline_summary", {}).get("tail_leverage_warning") is True
            and approx(influence_t3_conc.get("top1_abs_delta_ccc"), 0.0381)
            and approx(influence_t1_matched.get("leave_one_delta_min"), 0.0629)
            and "not a filtering rule" in headline_influence_md
            and t3_domain_residual.get("decision", {}).get("scope") == "diagnostic_only_privileged_ground_truth_domains"
            and t3_domain_residual.get("decision", {}).get("no_model_promotion") is True
            and t3_domain_residual.get("guardrails", {}).get("oracle_corrections_are_privileged_and_non_deployable") is True
            and approx(t3_domain_residual.get("guardrails", {}).get("parsed_total_max_abs_diff_vs_iter47_target"), 0.0)
            and approx(domain_unobs.get("corr_domain_with_residual_pred_minus_true"), -0.8004)
            and approx(domain_unobs.get("oracle_delta_ccc_vs_base"), 0.4716)
            and approx(domain_multi.get("metrics", {}).get("ccc"), 0.8533)
            and "non-deployable" in t3_domain_residual_md
            and t3_item_residual.get("scope") == "diagnostic_only_saved_oof_no_model_selection_no_prereg_no_loocv"
            and t3_item_residual.get("decision", {}).get("no_model_promotion") is True
            and approx(t3_item_residual.get("target_reconstruction", {}).get("max_abs_parsed_total_minus_iter47_target"), 0.0)
            and item_top_residual.get("item") == 6
            and item_top_residual.get("weargait_observable") is False
            and approx(item_top_residual.get("corr_item_with_residual_pred_minus_true"), -0.5705)
            and approx(item_top_residual.get("loo_privileged_oracle", {}).get("delta_ccc_vs_base"), 0.2817)
            and approx(item_observable.get("mean_abs_residual_corr_observable"), 0.2470)
            and approx(item_observable.get("mean_abs_residual_corr_unobservable"), 0.3712)
            and "No model promotion" in t3_item_residual_md
            and ablation_v3_regeneration.get("status") == "blocked_missing_regeneration_inputs"
            and ablation_v3_regeneration.get("frozen_cache_unchanged") is True
            and {
                "control_clinical",
                "control_csv_dir",
                "walkway_metrics",
            }.issubset(set(ablation_v3_regeneration.get("input_status", {}).get("missing", [])))
            and synapse_recovery.get("status") == "missing_inputs"
            and synapse_recovery.get("credential_status", {}).get("can_attempt_download") is False
            and synapse_recovery.get("entities", {}).get("control_csv_folder", {}).get("synapse_probe", {}).get("csv_children_count") == 680,
            "covered",
            {
                "dashboard_artifacts": len(dashboard_manifest.get("artifacts", [])),
                "dashboard_missing": [a["path"] for a in dashboard_manifest.get("artifacts", []) if not a.get("exists")],
                "paper_export": {
                    "status": current_paper_manifest.get("status"),
                    "validation_issues": current_paper_manifest.get("validation_issues"),
                },
                "canonical_claim_consistency": {
                    "passed": canonical_claim_audit.get("passed"),
                    "stale_findings": len(canonical_claim_audit.get("stale_findings", [])),
                },
                "metric_recompute": {
                    "passed": metric_recompute_audit.get("passed"),
                    "checks": len(metric_recompute_audit.get("checks", [])),
                },
                "ccc_metric_integrity": {
                    "passed": ccc_metric_audit.get("passed"),
                    "headline_checks": len(ccc_metric_audit.get("headline_checks", [])),
                    "implementation_checks": len(ccc_metric_audit.get("implementation_checks", [])),
                    "max_abs_sample_minus_population_headline": ccc_metric_audit.get("max_abs_sample_minus_population_headline"),
                    "warnings": ccc_metric_audit.get("warnings"),
                },
                "oof_integrity": {
                    "passed": oof_integrity_audit.get("passed"),
                    "checks": len(oof_integrity_audit.get("checks", [])),
                },
                "prereg_temporal": {
                    "passed": prereg_temporal_audit.get("passed"),
                    "hard_failures": len(prereg_temporal_audit.get("hard_failures", [])),
                    "warnings": len(prereg_temporal_audit.get("warnings", [])),
                },
                "pre_audit_claim_labeling": {
                    "passed": pre_audit_labeling_audit.get("passed"),
                    "findings": len(pre_audit_labeling_audit.get("findings", [])),
                },
                "historical_subdomain_claim_labeling": {
                    "passed": historical_subdomain_labeling_audit.get("passed"),
                    "findings": len(historical_subdomain_labeling_audit.get("findings", [])),
                },
                "t1_candidate_claim_labeling": {
                    "passed": t1_candidate_labeling_audit.get("passed"),
                    "findings": len(t1_candidate_labeling_audit.get("findings", [])),
                    "missing_required_snippets": len(t1_candidate_labeling_audit.get("missing_required_snippets", [])),
                },
                "t3_complete33_claim_labeling": {
                    "passed": t3_complete33_labeling_audit.get("passed"),
                    "findings": len(t3_complete33_labeling_audit.get("findings", [])),
                    "missing_required_snippets": len(t3_complete33_labeling_audit.get("missing_required_snippets", [])),
                },
                "external_result_claim_labeling": {
                    "passed": external_result_labeling_audit.get("passed"),
                    "findings": len(external_result_labeling_audit.get("findings", [])),
                    "missing_required_snippets": len(external_result_labeling_audit.get("missing_required_snippets", [])),
                    "artifact_failures": len(external_result_labeling_audit.get("artifact_failures", [])),
                },
                "remaining_blocker_actions": {
                    "passed": remaining_blocker_action_audit.get("passed"),
                    "source_blocker_count": remaining_blocker_action_audit.get("source_blocker_count"),
                    "local_model_actions": len(remaining_blocker_action_audit.get("local_model_actions", [])),
                    "unmatched_blockers": len(remaining_blocker_action_audit.get("unmatched_blockers", [])),
                    "action_type_counts": remaining_blocker_action_audit.get("action_type_counts"),
                },
                "external_access_readiness": {
                    "passed": external_access_readiness.get("summary", {}).get("passed"),
                    "route_count": external_access_readiness.get("summary", {}).get("route_count"),
                    "application_packet_ready_count": external_access_readiness.get("summary", {}).get("application_packet_ready_count"),
                    "compute_ready_route_count": external_access_readiness.get("summary", {}).get("compute_ready_route_count"),
                    "top_priority_route": external_access_readiness.get("summary", {}).get("top_priority_route"),
                    "hard_failure_count": external_access_readiness.get("summary", {}).get("hard_failure_count"),
                },
                "access_submission_tracker": access_submission_tracker.get("summary"),
                "recent_external_web_leads": recent_external_web_leads.get("summary"),
                "weargait_raw_data_recovery_runbook": {
                    "passed": raw_recovery_runbook_audit.get("passed"),
                    "decision": raw_recovery_runbook_audit.get("decision"),
                    "current_status": raw_recovery_runbook_audit.get("current_status"),
                    "entity_checks": raw_recovery_runbook_audit.get("entity_checks"),
                },
                "task_plan_current_scope": {
                    "passed": task_plan_current_scope_audit.get("passed"),
                    "decision": task_plan_current_scope_audit.get("decision"),
                    "historical_boundary": task_plan_current_scope_audit.get("historical_boundary"),
                    "hard_failures": len(task_plan_current_scope_audit.get("hard_failures", [])),
                    "legacy_success_findings": len(task_plan_current_scope_audit.get("current_scope", {}).get("legacy_success_findings", [])),
                },
                "paper_generator_routing": {
                    "passed": paper_generator_routing_audit.get("passed"),
                    "decision": paper_generator_routing_audit.get("decision"),
                    "hard_failures": len(paper_generator_routing_audit.get("hard_failures", [])),
                    "active_doc_count": len(paper_generator_routing_audit.get("active_docs", [])),
                    "legacy_new4_transductive_hits": paper_generator_routing_audit.get("legacy_generator", {}).get("stale_phrase_counts", {}).get("new4_html_transductive"),
                },
                "readme_claim_routing": {
                    "passed": readme_claim_routing_audit.get("passed"),
                    "decision": readme_claim_routing_audit.get("decision"),
                    "hard_failures": len(readme_claim_routing_audit.get("hard_failures", [])),
                    "unguarded_stale_hits": len(readme_claim_routing_audit.get("unguarded_dangerous_hits", [])),
                    "missing_required": len(readme_claim_routing_audit.get("missing_required", [])),
                    "bad_current_route_hits": len(readme_claim_routing_audit.get("bad_current_route_hits", [])),
                },
                "legacy_manuscript_surface_audit": {
                    "passed": legacy_manuscript_surface_audit.get("passed"),
                    "decision": legacy_manuscript_surface_audit.get("decision"),
                    "hard_failures": len(legacy_manuscript_surface_audit.get("hard_failures", [])),
                    "legacy_surfaces": len(legacy_manuscript_surface_audit.get("legacy_surfaces", [])),
                    "total_dangerous_hits": legacy_manuscript_surface_audit.get("total_dangerous_hits"),
                },
                "historical_archive_surface_audit": {
                    "passed": historical_archive_surface_audit.get("passed"),
                    "decision": historical_archive_surface_audit.get("decision"),
                    "hard_failures": historical_archive_surface_audit.get("hard_failures"),
                    "surfaces_checked": historical_archive_surface_audit.get("surfaces_checked"),
                    "stale_pattern_hits_retained_under_archive_banners": historical_archive_surface_audit.get("total_stale_pattern_hits_retained_under_archive_banners"),
                },
                "secret_hygiene_audit": {
                    "passed": secret_hygiene_audit.get("passed"),
                    "decision": secret_hygiene_audit.get("decision"),
                    "findings": len(secret_hygiene_audit.get("findings", [])),
                    "hard_failures": len(secret_hygiene_audit.get("hard_failures", [])),
                    "scanned_file_count": secret_hygiene_audit.get("scanned_file_count"),
                    "sensitive_local_files": secret_hygiene_audit.get("sensitive_local_files"),
                },
                "reportable_artifact_flags": {
                    "passed": reportable_flag_audit.get("passed"),
                    "checks": len(reportable_flag_audit.get("checks", [])),
                    "stale_raw_flags": len(reportable_flag_audit.get("stale_raw_flags", [])),
                    "hard_failures": len(reportable_flag_audit.get("hard_failures", [])),
                },
                "cache_manifest_status_counts": cache_manifest_audit.get("status_counts"),
                "missing_cache_origin_counts": missing_cache_origin_audit.get("decision_counts"),
                "manual_cache_backfill_decisions": manual_cache_backfill_evidence.get("decision_counts"),
                "per_item_evidence_map": {
                    "passed": per_item_map.get("passed"),
                    "status_counts": per_item_map.get("status_counts"),
                    "missing_artifacts": len(per_item_map.get("missing_artifacts", [])),
                },
                "per_item_oof_companion_scope": {
                    "passed": per_item_oof_scope.get("passed"),
                    "oof_backed_rows": per_item_oof_scope.get("oof_backed_rows"),
                    "row_level_json_comparison_available_count": per_item_oof_scope.get("row_level_json_comparison_available_count"),
                    "warnings": len(per_item_oof_scope.get("warnings", [])),
                },
                "t1_iter12_batch_integrity": {
                    "passed": t1_iter12_batch_integrity.get("pass"),
                    "hard_failures": len(t1_iter12_batch_integrity.get("hard_failures", [])),
                    "warnings": len(t1_iter12_batch_integrity.get("warnings", [])),
                    "ccc": t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("ccc"),
                    "mae": t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("mae"),
                    "max_abs_diff_vs_stored_oof": t1_iter12_batch_integrity.get("composite", {}).get("max_abs_diff_vs_stored_oof"),
                },
                "t3_iter47_target_integrity": {
                    "passed": t3_iter47_target_integrity.get("pass"),
                    "hard_failures": len(t3_iter47_target_integrity.get("hard_failures", [])),
                    "warnings": len(t3_iter47_target_integrity.get("warnings", [])),
                    "invalid_raw_values": len(t3_iter47_target_integrity.get("target", {}).get("invalid_raw_subitem_values", [])),
                    "target_changed_rows": len(t3_iter47_target_integrity.get("target", {}).get("target_changed_rows", [])),
                },
                "t3_iter47_residual_anatomy": {
                    "scope": t3_iter47_residual_anatomy.get("scope"),
                    "residual_corr_with_true": t3_iter47_residual_anatomy.get("overall_metrics", {}).get("residual_corr_with_true"),
                    "q1_mean_residual": next((row.get("mean_residual_pred_minus_true") for row in t3_iter47_residual_anatomy.get("severity_quartile_summary", []) if row.get("group") == "Q1_low"), None),
                    "q4_mean_residual": next((row.get("mean_residual_pred_minus_true") for row in t3_iter47_residual_anatomy.get("severity_quartile_summary", []) if row.get("group") == "Q4_high"), None),
                    "wpd_within_site_ccc": next((row.get("ccc") for row in t3_iter47_residual_anatomy.get("site_summary", []) if row.get("group") == "WPD"), None),
                    "top_abs_residual_feature_corr": (t3_iter47_residual_anatomy.get("global_diagnostic_feature_correlations") or [{}])[0].get("abs_corr_with_residual"),
                },
                "t3_iter47_ccc_rescale_sanity": {
                    "scope": t3_iter47_ccc_rescale.get("scope"),
                    "not_fully_nested": t3_iter47_ccc_rescale.get("methodology_guardrail", {}).get("not_fully_nested"),
                    "decision": t3_iter47_ccc_rescale.get("decision"),
                    "variance_match_metrics": t3_rescale_variance_metrics,
                    "variance_bootstrap_vs_base": t3_rescale_variance_boot,
                },
                "current_headline_influence": {
                    "decision": headline_influence.get("decision"),
                    "t3_top1_abs_delta_ccc": influence_t3_conc.get("top1_abs_delta_ccc"),
                    "t3_top5_fraction_of_sum_abs_delta": influence_t3_conc.get("top5_fraction_of_sum_abs_delta"),
                    "t3_tail_leverage_corr": influence_t3_corr.get("abs_target_minus_median_vs_abs_delta_ccc"),
                    "t1_leave_one_delta_min": influence_t1_matched.get("leave_one_delta_min"),
                },
                "t3_iter47_domain_residual": {
                    "decision": t3_domain_residual.get("decision"),
                    "unobservable_non_gait": domain_unobs,
                    "upper_limb_brady": domain_upper,
                    "multidomain_oracle": domain_multi,
                },
                "ablation_v3_regeneration_probe": {
                    "status": ablation_v3_regeneration.get("status"),
                    "frozen_cache_unchanged": ablation_v3_regeneration.get("frozen_cache_unchanged"),
                    "missing_inputs": ablation_v3_regeneration.get("input_status", {}).get("missing"),
                },
                "weargait_missing_synapse_recovery_preflight": {
                    "status": synapse_recovery.get("status"),
                    "missing": synapse_recovery.get("missing"),
                    "credential_status": synapse_recovery.get("credential_status"),
                    "control_csv_synapse_count": synapse_recovery.get("entities", {}).get("control_csv_folder", {}).get("synapse_probe", {}).get("csv_children_count"),
                },
            },
        ),
        checklist_item(
            "Sit with the data and derive methodology fixes",
            "NLS036" in findings
            and "skipna-summed" in task_plan
            and t1_aux.get("invalid_t1_target_items_in_current_t1_cohort") == []
            and t1_aux.get("interpretation", {}).get("primary_t1_target_valid") is True
            and t1_aux_order.get("order_audit", {}).get("summary", {}).get("kimi_fixed_order_assumption_status") == "falsified_by_code"
            and t1_aux_order.get("order_audit", {}).get("summary", {}).get("iter34_lockbox_seeds_with_item15_upstream_of_any_t1") == [7, 1337]
            and approx(t1_aux_order.get("impact_screen", {}).get("common_sid_comparison", {}).get("delta_valid_minus_stale_common_ccc"), -0.0008, 1e-3)
            and t1_aux_order.get("impact_screen", {}).get("common_sid_comparison", {}).get("materiality_flag") is False
            and approx(t3_iter47_current.get("new_refit_metrics", {}).get("ccc"), 0.3784)
            and per_item_map.get("status_counts", {}).get("current_t1_iter12_component") == 6
            and per_item_map.get("status_counts", {}).get("missing_or_backfill_only_unobservable") == 3
            and per_item_oof_scope.get("passed") is True
            and t1_iter12_batch_integrity.get("pass") is True
            and t3_iter47_target_integrity.get("pass") is True
            and approx(t3_iter47_residual_anatomy.get("overall_metrics", {}).get("residual_corr_with_true"), -0.7771)
            and approx(next((row.get("ccc") for row in t3_iter47_residual_anatomy.get("site_summary", []) if row.get("group") == "WPD"), None), 0.0515)
            and (t3_iter47_residual_anatomy.get("global_diagnostic_feature_correlations") or [{}])[0].get("abs_corr_with_residual", 1.0) < 0.30
            and approx(t3_rescale_variance_metrics.get("ccc"), 0.3996)
            and approx(t3_rescale_variance_boot.get("mae_delta_mean"), 1.1398, 1e-3)
            and t3_iter47_ccc_rescale.get("methodology_guardrail", {}).get("not_fully_nested") is True
            and approx(influence_t3_conc.get("top1_abs_delta_ccc"), 0.0381)
            and approx(influence_t3_corr.get("abs_target_minus_median_vs_abs_delta_ccc"), 0.6779)
            and approx(influence_t1_matched.get("leave_one_delta_min"), 0.0629)
            and approx(domain_unobs.get("corr_domain_with_residual_pred_minus_true"), -0.8004)
            and approx(domain_upper.get("corr_domain_with_residual_pred_minus_true"), -0.6224)
            and approx(domain_multi.get("metrics", {}).get("ccc"), 0.8533)
            and item_top_residual.get("item") == 6
            and approx(item_top_residual.get("corr_item_with_residual_pred_minus_true"), -0.5705)
            and approx(item_observable.get("mean_abs_residual_corr_unobservable"), 0.3712),
            "covered",
            {
                "t1_aux_validrange": {
                    "primary_t1_target_valid": t1_aux.get("interpretation", {}).get("primary_t1_target_valid"),
                    "invalid_auxiliary_items": t1_aux.get("invalid_auxiliary_items_in_current_chain_cohort"),
                },
                "t1_aux_order": {
                    "order_summary": t1_aux_order.get("order_audit", {}).get("summary"),
                    "impact": t1_aux_order.get("impact_screen", {}).get("common_sid_comparison"),
                },
                "t3_iter47_minimal": t3_iter47_current.get("new_refit_metrics"),
                "per_item_evidence_map": {
                    "status_counts": per_item_map.get("status_counts"),
                    "t3_per_item_sum_historical": per_item_map.get("composites", {}).get("t3_per_item_sum_historical"),
                },
                "per_item_oof_companion_scope": {
                    "oof_backed_rows": per_item_oof_scope.get("oof_backed_rows"),
                    "row_level_json_comparison_available_count": per_item_oof_scope.get("row_level_json_comparison_available_count"),
                    "warnings": per_item_oof_scope.get("warnings"),
                },
                "t1_iter12_batch_integrity": {
                    "single_coherent_batch": t1_iter12_batch_integrity.get("batch", {}).get("single_coherent_batch"),
                    "uses_swaps": t1_iter12_batch_integrity.get("batch", {}).get("uses_swaps"),
                    "max_abs_diff_vs_stored_oof": t1_iter12_batch_integrity.get("composite", {}).get("max_abs_diff_vs_stored_oof"),
                },
                "t3_iter47_target_integrity": {
                    "minimal_n": t3_iter47_target_integrity.get("cohorts", {}).get("drop_allmissing_validrange", {}).get("n"),
                    "complete33_n": t3_iter47_target_integrity.get("cohorts", {}).get("complete33_validrange", {}).get("n"),
                    "target_changed_rows": t3_iter47_target_integrity.get("target", {}).get("target_changed_rows"),
                },
                "t3_iter47_residual_anatomy": {
                    "overall": t3_iter47_residual_anatomy.get("overall_metrics"),
                    "top_feature": (t3_iter47_residual_anatomy.get("global_diagnostic_feature_correlations") or [{}])[0],
                    "decision": t3_iter47_residual_anatomy.get("decision"),
                },
                "t3_iter47_ccc_rescale_sanity": {
                    "variance_match_metrics": t3_rescale_variance_metrics,
                    "variance_bootstrap_vs_base": t3_rescale_variance_boot,
                    "guardrail": t3_iter47_ccc_rescale.get("methodology_guardrail"),
                    "decision": t3_iter47_ccc_rescale.get("decision"),
                },
                "current_headline_influence": {
                    "decision": headline_influence.get("decision"),
                    "t3_influence_concentration": influence_t3_conc,
                    "t3_influence_correlations": influence_t3_corr,
                    "t1_matched_delta": influence_t1_matched,
                },
                "t3_iter47_domain_residual": {
                    "decision": t3_domain_residual.get("decision"),
                    "guardrails": t3_domain_residual.get("guardrails"),
                    "unobservable_non_gait": domain_unobs,
                    "upper_limb_brady": domain_upper,
                    "multidomain_oracle": domain_multi,
                },
                "t3_iter47_item_residual": {
                    "scope": t3_item_residual.get("scope"),
                    "decision": t3_item_residual.get("decision"),
                    "target_reconstruction": t3_item_residual.get("target_reconstruction"),
                    "top_residual_item": item_top_residual,
                    "observable_summary": item_observable,
                },
            },
        ),
        checklist_item(
            "Attempt to break T1 CCC ceiling",
            approx(t1_iter12.get("ccc"), 0.6550)
            and approx(t1_iter34.get("ccc"), 0.7366)
            and approx(t1_iter46.get("ccc"), 0.7269)
            and t1_p2.get("summary", {}).get("all_point_deltas_pass_one_sided") is True
            and t1_p2.get("summary", {}).get("all_bootstrap_upper_bounds_pass_one_sided") is False,
            "attempted_with_caveated_candidate",
            {
                "canonical_t1": {"ccc": t1_iter12.get("ccc"), "n": t1_iter12.get("n")},
                "strongest_candidate": {"ccc": t1_iter34.get("ccc"), "n": t1_iter34.get("n")},
                "iter46": {"ccc": t1_iter46.get("ccc"), "n": t1_iter46.get("n")},
                "p2_summary": t1_p2.get("summary"),
            },
        ),
        checklist_item(
            "Attempt to break T3 CCC ceiling",
            approx(t3_iter47_current.get("new_refit_metrics", {}).get("ccc"), 0.3784)
            and approx(t3_loso_current.get("two_way_mean_ccc"), 0.150, 1e-3)
            and approx(t3_intercept.get("ccc"), 0.2449)
            and approx(t3_iter50.get("mean_metrics", {}).get("nested_convex", {}).get("ccc"), 0.3083)
            and t3_iter50.get("gate", {}).get("strict_t3_gate_pass") is False
            and t3_iter50.get("decision") == "screen_fail_no_loocv_no_canonical_change"
            and any("T3" in blocker and "0.3784" in blocker for blocker in verifier_json.get("blockers", [])),
            "attempted_no_breakthrough",
            {
                "iter47_minimal": t3_iter47_current.get("new_refit_metrics"),
                "iter47_loso": t3_loso_current,
                "clinical_dependency_intercept_only": t3_intercept,
                "iter50_lowdf_convex": {
                    "baseline": t3_iter50.get("mean_metrics", {}).get("baseline_seq_current"),
                    "nested_convex": t3_iter50.get("mean_metrics", {}).get("nested_convex"),
                    "gate": t3_iter50.get("gate"),
                    "decision": t3_iter50.get("decision"),
                },
            },
        ),
        checklist_item(
            "Evaluate public external routes and avoid dead-end repeats",
            external_ok
            and ppmi_route.get("status") == "access_gated_no_scaffold_until_credentials"
            and watchpd_route.get("status") == "request_gated_document_only_no_scaffold_until_access_schema"
            and watchpd_route.get("direct_t1_t3_eligible") is True
            and watchpd_route.get("n_pd") == 82
            and watchpd_route.get("n_controls") == 50
            and "C-Path" in watchpd_route.get("access_status", "")
            and watchpd_route.get("access_runbook") == "scripts/watchpd_request_setup.md"
            and "Do not build a probe scaffold" in watchpd_runbook
            and icicle_route.get("status") == "request_gated_document_only_no_scaffold_until_data"
            and icicle_route.get("n_pd") == 89
            and icicle_route.get("access_runbook") == "scripts/icicle_request_setup.md"
            and "MDS-UPDRS Part III" in icicle_route.get("label", "")
            and "Do not build a probe scaffold" in icicle_runbook
            and cns_route.get("status") == "request_gated_document_only_no_scaffold_until_data"
            and cns_route.get("n_pd") == 74
            and cns_route.get("n_gait_instances") == 267
            and cns_route.get("access_runbook") == "scripts/cns_portugal_request_setup.md"
            and "MDS-UPDRS Part III" in cns_route.get("label", "")
            and "Do not build a probe scaffold" in cns_runbook
            and mobilised_route.get("status") == "watchlist_no_scaffold_until_cvs_release_or_schema"
            and mobilised_route.get("direct_t1_t3_eligible") is False
            and mobilised_route.get("n_tvs_subjects_total") == 108
            and mobilised_route.get("n_cvs_pd_baseline_reported") == 600
            and "algorithm-validation" in mobilised_route.get("verdict", "")
            and tlvmc_route.get("status") == "zero_shot_complete_external_validity_only"
            and tlvmc_route.get("direct_t1_t3_eligible") is True
            and tlvmc_route.get("n_subjects_with_updrsiii") == 136
            and tlvmc_route.get("n_defog_recordings") == 137
            and tlvmc_route.get("n_defog_medication_matched_targets") == 137
            and tlvmc_route.get("n_defog_off_records") == 68
            and tlvmc_route.get("n_defog_off_subjects") == 44
            and tlvmc_route.get("preregistration", {}).get("formula_sha256") == "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd"
            and tlvmc_prereg.get("formula_sha256") == "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd"
            and tlvmc_prereg.get("formula", {}).get("fixed_battery", {}).get("primary_external_target", {}).get("expected_n_records") == 68
            and tlvmc_iter51.get("preregistration_formula_sha256") == "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd"
            and tlvmc_iter51.get("decision") == "external_zero_shot_only_no_internal_t3_canonical_change"
            and tlvmc_iter51.get("n_defog_off_rows") == 68
            and tlvmc_iter51.get("n_common_magnitude_features") == 54
            and approx(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_a_mean", {}).get("ccc"), 0.2695)
            and approx(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_b_mean", {}).get("ccc"), 0.0485)
            and approx(tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_c_defog_loso_ridge", {}).get("ccc"), 0.3450)
            and pdfe_route.get("status") == "zero_shot_complete_external_validity_only"
            and pdfe_route.get("direct_t1_t3_eligible") is True
            and pdfe_route.get("n_session1_targets") == 35
            and pdfe_route.get("preregistration", {}).get("formula_sha256") == "f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2"
            and pdfe_prereg.get("formula_sha256") == "f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2"
            and pdfe_iter52.get("formula_sha256") == "f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2"
            and pdfe_probe.get("n_session1_targets") == 35
            and pdfe_iter52.get("n_pdfe") == 35
            and pdfe_iter52.get("n_common_magnitude_features") == 54
            and approx(pdfe_iter52.get("tracks", {}).get("track_a_primary_wg_shank_to_pdfe", {}).get("ccc"), -0.1008)
            and approx(pdfe_iter52.get("tracks", {}).get("track_b_clinical_plus_shank", {}).get("ccc"), 0.1340)
            and approx(pdfe_iter52.get("tracks", {}).get("track_c_pdfe_only_loocv_sanity", {}).get("ccc"), 0.4020)
            and gait_biomech_route.get("status") == "document_only_wrong_modality_motion_capture_force_plates"
            and tlvmc_probe.get("row_level_metadata_persisted_in_repo") is False
            and tlvmc_probe.get("recording_metadata", {}).get("tdcsfog", {}).get("rows_with_any_updrsiii_target") == 0
            and tlvmc_probe.get("raw_schema_samples", {}).get("defog", {}).get("columns") == ["Time", "AccV", "AccML", "AccAP", "StartHesitation", "Turn", "Walking", "Valid", "Task"]
            and phone_tremor_route.get("status") == "skipped_tremor_subitem_phone_not_t1_t3"
            and phone_tremor_route.get("direct_t1_t3_eligible") is False
            and phone_tremor_route.get("n_clinically_examined_subjects") == 45
            and "tremor-subitem" in phone_tremor_route.get("verdict", "")
            and phone_tremor_consult.get("route", {}).get("direct_t1_t3_eligible") is False
            and phone_tremor_consult.get("consults", {}).get("kimi", {}).get("status") == "completed"
            and phone_tremor_consult.get("consults", {}).get("gemini", {}).get("status") == "completed"
            and phone_tremor_consult.get("consults", {}).get("claude", {}).get("status") == "failed"
            and phone_tremor_consult.get("consults", {}).get("glmcode", {}).get("status") == "not_available"
            and "No preregistration" in phone_tremor_consult.get("decision", "")
            and harmonized_accel_route.get("status") == "skipped_rehab_activity_summaries_no_t1_t3_targets"
            and harmonized_accel_route.get("direct_t1_t3_eligible") is False
            and harmonized_accel_route.get("n_subjects_total") == 790
            and harmonized_accel_route.get("approx_n_pd") == 55
            and "lacks confirmed total MDS-UPDRS Part III" in harmonized_accel_route.get("verdict", "")
            and harmonized_accel_consult.get("route", {}).get("direct_t1_t3_eligible") is False
            and harmonized_accel_consult.get("consults", {}).get("kimi", {}).get("status") == "completed"
            and harmonized_accel_consult.get("consults", {}).get("gemini", {}).get("status") == "completed"
            and harmonized_accel_consult.get("consults", {}).get("claude", {}).get("status") == "failed"
            and harmonized_accel_consult.get("consults", {}).get("glmcode", {}).get("status") == "not_available"
            and "No preregistration" in harmonized_accel_consult.get("decision", "")
            and monipar_route.get("status") == "skipped_public_subitem_only_tiny_supervised_n"
            and monipar_route.get("direct_t1_t3_eligible") is False
            and monipar_route.get("n_pd") == 21
            and monipar_route.get("n_supervised_pd") == 6
            and monipar_route.get("n_supervised_trials") == 46
            and "3.10" in monipar_route.get("covered_items", [])
            and bioclite_route.get("status") == "skipped_public_subitem_only_no_t1_t3_endpoint"
            and bioclite_route.get("direct_t1_t3_eligible") is False
            and bioclite_route.get("n_pd") == 24
            and bioclite_route.get("n_controls") == 16
            and "3.9" in bioclite_route.get("covered_items", [])
            and ppp_route.get("status") == "access_gated_document_only_no_scaffold_until_access"
            and ppp_route.get("direct_t1_t3_eligible") is True
            and ppp_route.get("n_subjects") == 517
            and ppp_route.get("n_vme_participants") == 388
            and ppp_route.get("access_runbook") == "scripts/ppp_pd_vme_request_setup.md"
            and "Do not build a probe scaffold" in ppp_runbook
            and "read-only" in ppp_runbook
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
            and advanced_smartwatch_route.get("status") == "request_only_document_only_no_scaffold"
            and advanced_smartwatch_route.get("direct_t1_t3_eligible") is False
            and advanced_smartwatch_route.get("n_pd_subjects") == 21
            and advanced_smartwatch_refresh.get("status") == "request_only_document_only_no_scaffold"
            and advanced_smartwatch_refresh.get("n_pd_subjects") == 21
            and "proprietary" in advanced_smartwatch_refresh.get("verdict", "")
            and dyad_actigraphy_route.get("status") == "request_only_document_only_no_scaffold"
            and dyad_actigraphy_route.get("direct_t1_t3_eligible") is False
            and dyad_actigraphy_route.get("n_dyads") == 27
            and dyad_actigraphy_route.get("n_individuals") == 54
            and dyad_actigraphy_refresh.get("status") == "request_only_document_only_no_scaffold"
            and dyad_actigraphy_refresh.get("n_dyads") == 27
            and request_only_actigraphy_refresh.get("decision") == "no_prereg_no_download_no_scaffold_no_remote_job_access_request_only"
            and request_only_actigraphy_refresh.get("consults", {}).get("kimi", {}).get("status") == "completed"
            and request_only_actigraphy_refresh.get("consults", {}).get("claude", {}).get("status") == "failed"
            and request_only_actigraphy_refresh.get("consults", {}).get("glmcode", {}).get("status") == "not_available"
            and luxembourg_route.get("status") == "skipped_request_only_subitem_only_observability_context"
            and luxembourg_route.get("direct_t1_t3_eligible") is False
            and luxembourg_route.get("n_pd") == 33
            and luxembourg_route.get("n_controls") == 12
            and "upper-limb observability context" in luxembourg_route.get("verdict", "")
            and "Do not create an access runbook" in luxembourg_route.get("verdict", "")
            and luxembourg_upper_limb_refresh.get("decision") == "document_only_no_runbook_no_scaffold_no_preregistration"
            and luxembourg_upper_limb_refresh.get("status") == "skipped_request_only_subitem_only_observability_context"
            and "skip_runbook_document_only" in luxembourg_upper_limb_refresh.get("consults", {}).get("kimi", "")
            and luxembourg_upper_limb_refresh.get("consults", {}).get("claude") == "failed_credit_balance_too_low"
            and luxembourg_upper_limb_refresh.get("consults", {}).get("glmcode") == "not_found_on_path"
            and prequantipark_route.get("status") == "skipped_request_only_tiny_lct_no_scaffold"
            and prequantipark_route.get("direct_t1_t3_eligible") is False
            and prequantipark_route.get("potential_external_t3_if_access_and_schema_approved") is True
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
            and "Luxembourg upper-limb MDS-UPDRS III subitem study" in external_md
            and "no access runbook, preregistration, download, scaffold, or remote job" in external_md
            and "Pre-QuantiPark / ActiMyo levodopa-challenge wearable IMU pilot" in external_md
            and "no access runbook, preregistration, download, scaffold, request packet, or remote job" in external_md
            and tum_rocket_inception_route.get("status") == "document_only_hssayeni_alias_algorithm_dead_no_scaffold"
            and tum_rocket_inception_route.get("direct_t1_t3_eligible") is False
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
            and "TUM Donié ROCKET/InceptionTime wrist symptom-classification alias" in external_md
            and "no access runbook, code clone, preregistration, download, scaffold, or remote job" in external_md
            and paradigma_route.get("status") == "local_feature_addition_dead_at_n94"
            and paradigma_route.get("direct_t1_t3_eligible") is False
            and paradigma_route.get("code_available") is True
            and paradigma_route.get("data_available") is False
            and "local scalar" in paradigma_route.get("verdict", "")
            and yin_route.get("status") == "request_only_underpowered_no_public_schema"
            and yin_route.get("direct_t1_t3_eligible") is False
            and yin_route.get("n_pd") == 20
            and yin_route.get("n_controls") == 17
            and yin_route.get("data_available") is False
            and "no public row-level schema" in yin_route.get("access_status", "")
            and paradigma_refresh.get("decision") == "document_only_no_scaffold_no_preregistration_no_remote_job"
            and paradigma_refresh.get("status") == "local_feature_addition_dead_at_n94"
            and paradigma_refresh.get("direct_t1_t3_eligible") is False
            and yin_refresh.get("decision") == "document_only_no_scaffold_no_preregistration_no_remote_job"
            and yin_refresh.get("status") == "request_only_underpowered_no_public_schema"
            and yin_refresh.get("n_pd") == 20
            and paradigma_yin_refresh.get("consults", {}).get("claude") == "failed_credit_balance_too_low"
            and paradigma_yin_refresh.get("consults", {}).get("glmcode") == "not_found_on_path"
            and "ParaDigMa" in external_md
            and "Yin et al Frontiers Neurology 2025" in external_md
            and smid_tremor_route.get("status") == "document_only_tremor_subitems_no_t1_t3_endpoint"
            and smid_tremor_route.get("direct_t1_t3_eligible") is False
            and smid_tremor_route.get("n_pd") == 64
            and smid_tremor_route.get("n_controls") == 64
            and "tremor subitems" in smid_tremor_route.get("label", "").lower()
            and pdassist_route.get("status") == "document_only_smartphone_protocol_not_weargait_aligned"
            and pdassist_route.get("direct_t1_t3_eligible") is False
            and pdassist_route.get("potential_external_t3_if_access_and_schema_approved") is True
            and pdassist_route.get("n_pd") == 282
            and pdassist_route.get("n_controls") == 110
            and smid_tremor_refresh.get("decision") == "document_only_no_scaffold_no_preregistration_no_remote_job"
            and smid_tremor_refresh.get("direct_t1_t3_eligible") is False
            and pdassist_refresh.get("decision") == "document_only_no_scaffold_no_preregistration_no_remote_job"
            and pdassist_refresh.get("direct_t1_t3_eligible") is False
            and yin_recent_refresh.get("decision") == "already_recorded_no_new_action"
            and recent_external_web_leads.get("summary", {}).get("new_compute_ready_routes") == 0
            and recent_external_web_leads.get("summary", {}).get("new_scaffold_or_preregistration_actions") == 0
            and "Halt external web prospecting" in kimi_recent_external_web_leads
            and "Parkinson@Home arm-swing validation" in external_md
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
            and hssayeni_route.get("status") == "synapse_dua_gated_no_scaffold_until_access"
            and hssayeni_route.get("access_runbook") == "scripts/synapse_hssayeni_setup.md"
            and "DUA" in hssayeni_route.get("access_status", "")
            and "Do not run a download" in hssayeni_runbook
            and external_access_readiness.get("summary", {}).get("passed") is True
            and external_access_readiness.get("summary", {}).get("compute_ready_route_count") == 0
            and external_access_readiness.get("summary", {}).get("application_packet_ready_count") == 6,
            "covered",
            {
                "missing": external_missing,
                "paradigma_yin": paradigma_yin_refresh.get("routes", []),
                "paradigma": paradigma_route,
                "yin": yin_route,
                "recent_external_web_leads": recent_external_web_leads.get("summary"),
                "smid_tremor": {
                    "route": smid_tremor_route,
                    "refresh": smid_tremor_refresh,
                },
                "pdassist": {
                    "route": pdassist_route,
                    "refresh": pdassist_refresh,
                },
                "parkinsonathome": {
                    "route": parkinsonathome_route,
                    "refresh": parkinsonathome_refresh,
                },
                "ppmi": ppmi_route,
                "watchpd": watchpd_route,
                "icicle": icicle_route,
                "cns_portugal": cns_route,
                "mobilised": mobilised_route,
                "tlvmc_defog": {
                    "route": tlvmc_route,
                    "preregistration": {
                        "formula_sha256": tlvmc_prereg.get("formula_sha256"),
                        "primary": tlvmc_prereg.get("formula", {}).get("fixed_battery", {}).get("primary_external_target"),
                    },
                    "result": {
                        "decision": tlvmc_iter51.get("decision"),
                        "n_defog_rows": tlvmc_iter51.get("n_defog_rows"),
                        "n_common_magnitude_features": tlvmc_iter51.get("n_common_magnitude_features"),
                        "track_a_mean_off": tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_a_mean"),
                        "track_b_mean_off": tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_b_mean"),
                        "track_c_defog_loso": tlvmc_iter51.get("metrics", {}).get("off_primary", {}).get("track_c_defog_loso_ridge"),
                    },
                    "probe_subjects": tlvmc_probe.get("subjects"),
                    "probe_defog": tlvmc_probe.get("recording_metadata", {}).get("defog"),
                    "probe_tdcsfog": tlvmc_probe.get("recording_metadata", {}).get("tdcsfog"),
                    "raw_schema_sample": tlvmc_probe.get("raw_schema_samples", {}).get("defog"),
                },
                "pdfe_turning": {
                    "route": pdfe_route,
                    "probe": pdfe_probe,
                    "result": {
                        "track_a": pdfe_iter52.get("tracks", {}).get("track_a_primary_wg_shank_to_pdfe"),
                        "track_b": pdfe_iter52.get("tracks", {}).get("track_b_clinical_plus_shank"),
                        "track_c": pdfe_iter52.get("tracks", {}).get("track_c_pdfe_only_loocv_sanity"),
                    },
                },
                "public_gait_biomechanics": gait_biomech_route,
                "phone_call_tremor": {
                    "route": phone_tremor_route,
                    "consult": phone_tremor_consult,
                },
                "harmonized_accelerometry": {
                    "route": harmonized_accel_route,
                    "consult": harmonized_accel_consult,
                },
                "monipar": {
                    "route": monipar_route,
                    "refresh": monipar_refresh,
                },
                "bioclite": {
                    "route": bioclite_route,
                    "refresh": bioclite_refresh,
                },
                "ppp_pd_vme": {
                    "route": ppp_route,
                    "refresh": ppp_refresh,
                },
                "derivative_multimodal": {
                    "route": derivative_multimodal_route,
                    "refresh": derivative_multimodal_refresh,
                },
                "request_only_actigraphy": {
                    "advanced_smartwatch_route": advanced_smartwatch_route,
                    "dyad_actigraphy_route": dyad_actigraphy_route,
                    "refresh": request_only_actigraphy_refresh,
                },
                "luxembourg_upper_limb": {
                    "route": luxembourg_route,
                    "refresh": luxembourg_upper_limb_refresh,
                },
                "prequantipark": {
                    "route": prequantipark_route,
                    "refresh": prequantipark_refresh,
                },
                "tum_rocket_inception": {
                    "route": tum_rocket_inception_route,
                    "refresh": tum_rocket_inception_refresh,
                },
                "hssayeni": hssayeni_route,
                "external_access_readiness": external_access_readiness.get("summary"),
            },
        ),
        checklist_item(
            "Handle uncertainty / clinical utility",
            "intervals" in conformal
            or (
                "models" in conformal
                and approx(t3_conformal.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 25.94, 1e-2)
            ),
            "covered_no_rescue",
            {"conformal": t3_conformal},
        ),
        checklist_item(
            "Completion condition: break T1 and/or T3 ceiling",
            False,
            "not_complete",
            {
                "reason": (
                    "T1 strongest candidate remains caveated; T3 valid-range corrected "
                    "CCC is 0.3784 and no improved corrected lockbox exists."
                ),
                "verifier_goal_complete": verifier_json.get("goal_complete"),
            },
        ),
    ]

    hard_gaps = [
        c
        for c in checks
        if c["status"] in {"not_complete", "blocked", "unavailable"}
    ]
    report = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "objective": (
            "Act as a careful researcher; use web/CLI/remote evidence; inspect data; "
            "find methodology bugs; and try to break T1/T3 CCC ceilings."
        ),
        "checks": checks,
        "goal_complete": False,
        "hard_gaps": hard_gaps,
        "next_non_redundant_actions": [
            "Remaining blocker action audit classifies all 36 current blockers with 0 local WearGait-only model actions remaining.",
            "External access readiness audit passes with six access/request packets ready and zero compute-ready routes before approval.",
            "Access submission tracker passes with six submit-ready packets and zero compute-ready routes; completed packets and protected details must stay out of git.",
            "Recent external web-lead refresh found zero compute-ready routes and zero scaffold/pre-registration actions; stop external prospecting until an access route is approved.",
            "WearGait raw-data recovery runbook is ready for user-side Synapse credentials and explicit large-transfer confirmation; no download/cache promotion/model run has occurred.",
            "Task-plan current-scope audit passes and keeps post-iter47 completion criteria active while old success-tier thresholds remain archive-bound.",
            "User-side PPMI DUA/application, then read-only schema probe per scripts/ppmi_verily_setup.md.",
            "User-side Personalized Parkinson Project / PD-VME RDSRC request, then read-only schema probe only after approval.",
            "User-side WATCH-PD C-Path 3DT membership or Steering Committee proposal, then schema inspection; no scaffold before access exists.",
            "User-side ICICLE-PD/ICICLE-GAIT data request, then read-only schema probe per scripts/icicle_request_setup.md.",
            "User-side CNS Portugal/Lobo data request, then read-only schema probe per scripts/cns_portugal_request_setup.md.",
            "Optional author-side data requests for Fay-Karmon advanced-PD smartwatch monitoring or marital-dyad GeneActiv actigraphy; no scaffold before row-level files/schema exist.",
            "Monitor/request Mobilise-D CVS row-level wearable plus MDS-UPDRS release/schema; no scaffold before access exists.",
            "User-side Hssayeni/MJFF Synapse DUA approval, then run existing iter26 probe.",
            "Continue provenance/paper hardening only; do not launch another WearGait-only model family without new data or a new target representation.",
        ],
    }

    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_lines = [
        "# Prompt Objective Evidence Audit — 2026-05-09",
        "",
        f"Goal complete: `{str(report['goal_complete']).lower()}`",
        "",
        "## Checklist",
        "",
        "| Requirement | Status | Evidence |",
        "|---|---|---|",
    ]
    for check in checks:
        evidence = check["evidence"]
        if isinstance(evidence, dict):
            evidence_text = "; ".join(f"{k}={v}" for k, v in evidence.items())
        else:
            evidence_text = str(evidence)
        evidence_text = evidence_text.replace("\n", " ")[:500]
        md_lines.append(f"| {check['requirement']} | {check['status']} | {evidence_text} |")
    md_lines.extend(
        [
            "",
            "## External Result Update",
            "",
            "- TLVMC/DeFOG iter51 is complete: Track A lower-back magnitude zero-shot CCC `+0.2695` with 95% CI `[+0.1693,+0.3600]`; this is partial external validity only and cannot update the internal T3 headline.",
            "- PDFE turning-in-place iter52 is complete: Track A WearGait shank-to-PDFE CCC `-0.1008`, Track B clinical+shank CCC `+0.1340` with CI crossing zero, and Track C PDFE-only LOOCV sanity CCC `+0.4020`; this is protocol-specific external evidence only and cannot update the internal T3 headline.",
            "- Harmonized Upper/Lower Limb Accelerometry is closed as a no-preregistration/no-download route for this objective: it is daily-life ActiGraph rehabilitation accelerometry with no confirmed total MDS-UPDRS Part III or T1 item target.",
            "- Monipar/BIOCLITE are closed as no-preregistration/no-download public smartwatch subitem routes: they lack total T3 and the full T1 items 9-14 composite.",
            "- Zenodo `14848598` is closed as a no-preregistration/no-download derived multimodal benchmark: it has CSF/clinical/gait-summary tables rather than raw wearable IMU or auditable T1/T3 subject alignment.",
            "- Fay-Karmon advanced-PD smartwatch monitoring and the Sensors marital-dyad GeneActiv actigraphy study are closed as request-only/access-request rows: both are small-N and schema-hidden, and neither justifies a scaffold or remote job before author approval.",
            "- Personalized Parkinson Project / PD-VME is added to the gated Verily-watch queue, but remains RDSRC-gated and schema-hidden; no scaffold or remote job is justified before access.",
            "- Recent post-tracker web leads are closed as no-compute: Smid 2026 is tremor-subitem-only, Guo 2025 PDAssist is smartphone-protocol/schema-hidden, and Yin 2025 was already audited as request-only N=20.",
            "",
            "## Remaining Non-Redundant Actions",
            "",
            "- Remaining blocker action audit classifies all 36 current blockers with `0` local WearGait-only model actions remaining; access-gated data and raw-data restoration are prerequisites, not model-run instructions.",
            "- External access readiness audit passes with `6` access/request packets ready and `0` compute-ready routes before approval.",
            "- Access submission tracker passes with `6` submit-ready packets and `0` compute-ready routes; completed packets and protected details must stay out of git.",
            "- Recent external web-lead refresh found `0` compute-ready routes and `0` scaffold/pre-registration actions; stop external prospecting until an access route is approved.",
            "- WearGait raw-data recovery runbook audit passes and records `raw_data_recovery_runbook_ready_no_download`; user credentials and explicit large-transfer confirmation are still required before any recovery command.",
            "- Task-plan current-scope audit passes with `task_plan_current_scope_guard_passed`; post-iter47 completion criteria are active and old success-tier thresholds are archive-bound.",
            "- Paper generator routing audit passes with `current_paper_renderer_route_guard_passed`; current manuscript work routes through `render_current_paper.py` / `CURRENT_PAPER.html`, while `generate_paper_v4.py` / `NEW4.html` are legacy/stale archaeology only.",
            "- Legacy manuscript-surface audit passes with `legacy_manuscript_surfaces_quarantined`; 16 retained pre-audit paper/narrative surfaces carry stale/do-not-cite banners and current-route pointers.",
            "- Historical archive-surface audit passes with `historical_archive_surfaces_quarantined`; 11 retained project-note/archive surfaces carry archive-status banners, and `leakage_onepager.html` now uses the iter47 valid-range T3 headline instead of the superseded iter5 `0.5227` row.",
            "- Secret hygiene audit passes with `secret_hygiene_guard_passed`; local ignored `TOKEN.md` and `.env` credential files were removed and high-confidence credential findings are zero.",
            "- User-side PPMI DUA/application, then read-only schema probe per `scripts/ppmi_verily_setup.md`.",
            "- User-side Personalized Parkinson Project / PD-VME RDSRC request, then read-only schema probe only after approval.",
            "- User-side WATCH-PD C-Path 3DT membership or Steering Committee proposal, then schema inspection; no scaffold before access exists.",
            "- User-side ICICLE-PD/ICICLE-GAIT data request, then read-only schema probe per `scripts/icicle_request_setup.md`.",
            "- User-side CNS Portugal/Lobo data request, then read-only schema probe per `scripts/cns_portugal_request_setup.md`.",
            "- Optional author-side requests for Fay-Karmon advanced-PD smartwatch monitoring or marital-dyad GeneActiv actigraphy; no scaffold before row-level files/schema exist.",
            "- Monitor/request Mobilise-D CVS row-level wearable plus MDS-UPDRS release/schema; no scaffold before access exists.",
            "- User-side Hssayeni/MJFF Synapse DUA approval, then run the existing iter26 probe.",
            "- Continue provenance/paper hardening only; do not launch another WearGait-only model family without new data or a new target representation.",
        ]
    )
    OUT_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"goal_complete={report['goal_complete']}")
    print(f"checks={len(checks)} hard_gaps={len(hard_gaps)}")


if __name__ == "__main__":
    main()
