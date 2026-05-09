#!/usr/bin/env python3
"""Build a unified dashboard for the current post-audit best pipelines."""

from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_DIR = RESULTS / "current_best_pipeline_dashboard"
OUT_HTML = RESULTS / "current_best_pipeline_dashboard.html"
OUT_MANIFEST = OUT_DIR / "manifest.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_record(path: str, role: str) -> dict[str, Any]:
    p = ROOT / path
    return {
        "path": path,
        "role": role,
        "exists": p.exists(),
        "bytes": p.stat().st_size if p.exists() and p.is_file() else None,
        "sha256": sha256_file(p),
    }


def fmt_num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return html.escape(str(value))


def rel_results(path: str) -> str:
    p = Path(path)
    if p.parts and p.parts[0] == "results":
        return str(Path(*p.parts[1:]))
    return path


def table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def metric_card(label: str, value: str, detail: str = "") -> str:
    detail_html = f"<span>{html.escape(detail)}</span>" if detail else ""
    return (
        '<div class="metric">'
        f"<strong>{html.escape(value)}</strong>"
        f"<em>{html.escape(label)}</em>"
        f"{detail_html}"
        "</div>"
    )


def image_tile(path: str, title: str) -> str:
    return (
        '<figure class="figure-tile">'
        f'<a href="{html.escape(rel_results(path))}">'
        f'<img src="{html.escape(rel_results(path))}" alt="{html.escape(title)}">'
        "</a>"
        f"<figcaption>{html.escape(title)}</figcaption>"
        "</figure>"
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    t1_floor = load_json(RESULTS / "t1_iter12_honest_composite.json")
    t1_best = load_json(RESULTS / "lockbox_t1_iter34_hybrid_20260506_141720.json")
    t1_audit = load_json(RESULTS / "iter34_leakage_audit_20260506_143922.json")
    t1_loso = load_json(RESULTS / "iter34_loso_2026_05_06.json")
    t1_n93_gap = load_json(RESULTS / "audit_t1_iter34_n93_gap_20260508.json")
    t1_aux_valid = load_json(RESULTS / "t1_iter48_aux_validrange_audit.json")
    t1_aux_order = load_json(RESULTS / "t1_iter34_aux_order_audit.json")
    t1_p2 = load_json(RESULTS / "iter34_p2_robustness_20260508.json")
    t1_decomp = load_json(RESULTS / "iter34_base_item_decomp_20260508.json")
    t1_iter46 = load_json(RESULTS / "lockbox_t1_iter46_etrobust_20260508_162825.json")
    t1_iter46_cmp = load_json(RESULTS / "iter46_etrobust_local_comparisons_20260508.json")
    t1_iter37 = load_json(RESULTS / "iter37_harnet_finetune_screen_20260508_110641.json")
    t1_iter12_batch_integrity = load_json(RESULTS / "t1_iter12_batch_integrity_audit_20260508.json")
    t3_old = load_json(RESULTS / "lockbox_t3_iter5_A3_tier1_20260502_171604.json")
    t3_audit = load_json(RESULTS / "t3_target_stage2_covariate_audit_20260508_165653.json")
    t3_iter41 = load_json(RESULTS / "iter41_targetfix_20260508_170021.json")
    t3_iter41_loso = load_json(RESULTS / "iter41_targetfix_loso_20260508_171003.json")
    t3_iter47 = load_json(RESULTS / "iter47_invalidcode_20260508_194605.json")
    t3_iter47_loso = load_json(RESULTS / "iter47_invalidcode_loso_20260508_195424.json")
    t3_iter47_target_integrity = load_json(RESULTS / "t3_iter47_target_integrity_audit_20260508.json")
    t3_complete33_labeling_audit = load_json(RESULTS / "t3_complete33_claim_labeling_audit_20260509.json")
    external_result_labeling_audit = load_json(RESULTS / "external_result_claim_labeling_audit_20260509.json")
    remaining_blocker_action_audit = load_json(RESULTS / "remaining_blocker_action_audit_20260509.json")
    external_access_readiness = load_json(RESULTS / "external_access_readiness_audit_20260509.json")
    access_submission_tracker = load_json(RESULTS / "access_submission_tracker_20260509.json")
    ppmi_packet_audit = load_json(RESULTS / "ppmi_verily_request_packet_audit_20260509.json")
    ppp_packet_audit = load_json(RESULTS / "ppp_pd_vme_request_packet_audit_20260509.json")
    watchpd_packet_audit = load_json(RESULTS / "watchpd_request_packet_audit_20260509.json")
    cns_packet_audit = load_json(RESULTS / "cns_portugal_request_packet_audit_20260509.json")
    hssayeni_packet_audit = load_json(RESULTS / "hssayeni_mjff_dua_request_packet_audit_20260509.json")
    icicle_packet_audit = load_json(RESULTS / "icicle_request_packet_audit_20260509.json")
    raw_data_recovery_runbook_audit = load_json(RESULTS / "weargait_raw_data_recovery_runbook_audit_20260509.json")
    task_plan_current_scope_audit = load_json(RESULTS / "task_plan_current_scope_audit_20260509.json")
    paper_generator_routing_audit = load_json(RESULTS / "paper_generator_routing_audit_20260509.json")
    readme_claim_routing_audit = load_json(RESULTS / "readme_claim_routing_audit_20260509.json")
    legacy_manuscript_surface_audit = load_json(RESULTS / "legacy_manuscript_surface_audit_20260509.json")
    historical_archive_surface_audit = load_json(RESULTS / "historical_archive_surface_audit_20260509.json")
    secret_hygiene_audit = load_json(RESULTS / "secret_hygiene_audit_20260509.json")
    t3_iter47_residual_anatomy = load_json(RESULTS / "t3_iter47_residual_anatomy_20260509.json")
    t3_iter47_ccc_rescale = load_json(RESULTS / "t3_iter47_ccc_rescale_sanity_20260509.json")
    headline_influence = load_json(RESULTS / "current_headline_influence_audit_20260509.json")
    t3_domain_residual = load_json(RESULTS / "t3_iter47_domain_residual_audit_20260509.json")
    t3_item_residual = load_json(RESULTS / "t3_iter47_item_residual_audit_20260509.json")
    t3_iter42 = load_json(RESULTS / "iter42_prorate_20260508_173412.json")
    t3_iter42_loso = load_json(RESULTS / "iter42_prorate_loso_20260508_174349.json")
    t3_clinical = load_json(RESULTS / "t3_clinical_dependency_20260508.json")
    t3_deep = load_json(RESULTS / "t3_iter5_deepdive" / "summary.json")
    t3_site = load_json(RESULTS / "t3_iter16_site_ipw_lockbox.json")
    t3_conf = load_json(RESULTS / "t3_conformal_abstention_20260505.json")
    current_conf = load_json(RESULTS / "current_conformal_abstention_20260508.json")
    t3_iter38 = load_json(RESULTS / "iter38_fogstar_stage1_screen_20260508_142623.json")
    t3_iter39 = load_json(RESULTS / "iter39_fogstar_zeroshot_20260508_143717.json")
    t3_iter40 = load_json(RESULTS / "iter40_local_residual_screen_20260508_144905.json")
    t3_iter50 = load_json(RESULTS / "iter50_lowdf_convex_screen_20260508_225105.json")
    t3_iter49_probe = load_json(RESULTS / "iter49_cops_probe.json")
    t3_iter49 = load_json(RESULTS / "iter49_cops_zeroshot.json")
    tlvmc_probe = load_json(RESULTS / "tlvmc_fog_route_probe_20260509.json")
    tlvmc_prereg = load_json(RESULTS / "preregistration_t3_iter51_tlvmc_defog_zeroshot.json")
    tlvmc_iter51 = load_json(RESULTS / "iter51_tlvmc_defog_zeroshot.json")
    pdfe_prereg = load_json(RESULTS / "preregistration_t3_iter52_pdfe_turning_zeroshot.json")
    pdfe_probe = load_json(RESULTS / "iter52_pdfe_turning_probe.json")
    pdfe_iter52 = load_json(RESULTS / "iter52_pdfe_turning_zeroshot.json")
    luxembourg_upper_limb_refresh = load_json(RESULTS / "luxembourg_upper_limb_route_refresh_20260509.json")
    prequantipark_refresh = load_json(RESULTS / "prequantipark_route_refresh_20260509.json")
    tum_rocket_inception_refresh = load_json(RESULTS / "tum_rocket_inception_route_refresh_20260509.json")
    paradigma_yin_refresh = load_json(RESULTS / "paradigma_yin_route_refresh_20260509.json")
    parkinsonathome_refresh = load_json(RESULTS / "parkinsonathome_route_refresh_20260509.json")
    kimi_next_action = load_json(RESULTS / "kimi_next_action_after_parkinsonathome_20260509.json")
    recent_external_web_leads = load_json(RESULTS / "recent_external_web_leads_20260509.json")
    t3_dst_audit = load_json(RESULTS / "dst_walkway_leakage_audit_20260508_multiseed.json")
    ablation_v3_provenance = load_json(RESULTS / "ablation_v3_cache_provenance_audit_20260508.json")
    ablation_v3_regeneration = load_json(RESULTS / "ablation_v3_regeneration_probe_20260509.json")
    synapse_recovery = load_json(RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.json")
    cache_manifest_audit = load_json(RESULTS / "cache_manifest_audit_20260508.json")
    cache_backfill_candidates = load_json(RESULTS / "cache_backfill_candidates_20260508.json")
    missing_cache_origin_audit = load_json(RESULTS / "missing_cache_manifest_origin_audit_20260509.json")
    manual_cache_backfill_evidence = load_json(RESULTS / "manual_cache_backfill_evidence_20260509.json")
    cache_consumer_audit = load_json(RESULTS / "cache_consumer_guard_audit_20260508.json")
    transitive_cache_audit = load_json(RESULTS / "transitive_cache_dependency_audit_20260508.json")
    runtime_cache_audit = load_json(RESULTS / "runtime_cache_dependency_audit_20260508.json")
    canonical_claim_audit = load_json(RESULTS / "canonical_claim_consistency_audit_20260508.json")
    metric_recompute_audit = load_json(RESULTS / "headline_metric_recompute_audit_20260508.json")
    ccc_metric_audit = load_json(RESULTS / "ccc_metric_integrity_audit_20260509.json")
    oof_integrity_audit = load_json(RESULTS / "oof_artifact_integrity_audit_20260508.json")
    prereg_temporal_audit = load_json(RESULTS / "preregistration_temporal_integrity_audit_20260508.json")
    pre_audit_labeling_audit = load_json(RESULTS / "pre_audit_claim_labeling_audit_20260508.json")
    historical_subdomain_labeling_audit = load_json(RESULTS / "historical_subdomain_claim_labeling_audit_20260509.json")
    t1_candidate_labeling_audit = load_json(RESULTS / "t1_candidate_claim_labeling_audit_20260508.json")
    reportable_flag_audit = load_json(RESULTS / "reportable_artifact_flag_audit_20260509.json")
    per_item_map = load_json(RESULTS / "per_item_evidence_map_20260508.json")
    per_item_oof_scope = load_json(RESULTS / "per_item_oof_companion_scope_audit_20260508.json")
    t3_iter41_cells = {
        (c["cohort"], c["stage2_policy"]): c for c in t3_iter41.get("cells", [])
    }
    t3_iter41_loso_cells = {
        (c["cohort"], c["stage2_policy"]): c for c in t3_iter41_loso.get("cells", [])
    }
    t3_iter47_cells = {
        (c["cohort"], c["stage2_policy"]): c for c in t3_iter47.get("cells", [])
    }
    t3_iter47_loso_cells = {
        (c["cohort"], c["stage2_policy"]): c for c in t3_iter47_loso.get("cells", [])
    }
    t3_current = t3_iter47_cells[("drop_allmissing_validrange", "stage2_current")]
    t3_nocv = t3_iter47_cells[("drop_allmissing_validrange", "stage2_no_cv")]
    t3_loso_current = t3_iter47_loso_cells[("drop_allmissing_validrange", "stage2_current")]
    t3_current_metrics = t3_current["new_refit_metrics"]
    t3_nocv_metrics = t3_nocv["new_refit_metrics"]
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
    t3_resid_overall = t3_iter47_residual_anatomy.get("overall_metrics", {})
    t3_resid_quartiles = {
        row.get("group"): row
        for row in t3_iter47_residual_anatomy.get("severity_quartile_summary", [])
    }
    t3_resid_sites = {
        row.get("group"): row
        for row in t3_iter47_residual_anatomy.get("site_summary", [])
    }
    t3_resid_top_feature = (
        t3_iter47_residual_anatomy.get("global_diagnostic_feature_correlations", [{}])[0]
        if t3_iter47_residual_anatomy.get("global_diagnostic_feature_correlations")
        else {}
    )
    t3_rescale_methods = t3_iter47_ccc_rescale.get("methods", {})
    t3_rescale_base = t3_rescale_methods.get("base_iter47_current", {}).get("metrics", {})
    t3_rescale_variance = t3_rescale_methods.get("oof_level_leave_one_variance_match", {})
    t3_rescale_variance_metrics = t3_rescale_variance.get("metrics", {})
    t3_rescale_variance_boot = t3_rescale_variance.get("paired_bootstrap_vs_base", {})
    influence_t3 = headline_influence.get("audits", {}).get("t3_iter47_validrange_current", {})
    influence_t1_matched = headline_influence.get("matched_t1_iter34_vs_iter12", {})
    influence_t3_conc = influence_t3.get("influence_concentration", {})
    influence_t3_corr = influence_t3.get("influence_correlations", {})
    influence_t3_jack = influence_t3.get("jackknife", {})
    domain_rows = {row["domain"]: row for row in t3_domain_residual.get("domain_summary", [])}
    domain_unobs = domain_rows.get("unobservable_non_gait", {})
    domain_upper = domain_rows.get("upper_limb_brady_4_6", {})
    domain_gait = domain_rows.get("gait_balance_7_14", {})
    domain_multi = t3_domain_residual.get("multidomain_ridge10_privileged_oracle", {})
    item_top_residual = (t3_item_residual.get("top_items_by_abs_residual_corr") or [{}])[0]
    item_top_oracle = (t3_item_residual.get("top_items_by_privileged_oracle_delta_ccc") or [{}])[0]
    item_observable = t3_item_residual.get("observable_vs_unobservable_summary", {})
    t3_dst_current = t3_dst_audit["policy_results"]["stage2_current"]["mean_metrics"]
    t3_dst_nodst = t3_dst_audit["policy_results"]["stage2_no_dst"]["mean_metrics"]
    t3_dst_comp = t3_dst_audit["comparisons"]["stage2_no_dst_minus_current"]
    t3_iter42_cells = {
        (c["cohort"], c["stage2_policy"]): c for c in t3_iter42.get("cells", [])
    }
    t3_iter42_loso_cells = {
        (c["cohort"], c["stage2_policy"]): c for c in t3_iter42_loso.get("cells", [])
    }
    t3_clinical_policies = {
        row["stage1_policy"]: row for row in t3_clinical.get("policy_rows", [])
    }
    t3_iter49_off = t3_iter49.get("metrics", {}).get("off_primary", {})
    t3_iter49_track_a = t3_iter49_off.get("track_a_right_wrist_direct", {})
    t3_iter49_track_b = t3_iter49_off.get("track_b_right_clinical_plus_wrist", {})
    t3_iter49_track_c = t3_iter49_off.get("track_c_cops_only_loo_sanity", {})
    t3_iter49_track_d = t3_iter49_off.get("track_d_bilateral_clinical_plus_wrist", {})
    tlvmc_off = tlvmc_iter51.get("metrics", {}).get("off_primary", {})
    tlvmc_track_a = tlvmc_off.get("track_a_mean", {})
    tlvmc_track_b = tlvmc_off.get("track_b_mean", {})
    tlvmc_track_c = tlvmc_off.get("track_c_defog_loso_ridge", {})
    pdfe_tracks = pdfe_iter52.get("tracks", {})
    pdfe_track_a = pdfe_tracks.get("track_a_primary_wg_shank_to_pdfe", {})
    pdfe_track_b = pdfe_tracks.get("track_b_clinical_plus_shank", {})
    pdfe_track_c = pdfe_tracks.get("track_c_pdfe_only_loocv_sanity", {})

    artifacts = [
        artifact_record("compose_t1_iter12_honest.py", "T1 canonical floor script"),
        artifact_record("results/preregistration_t1_iter12_honest_20260503_053105.json", "T1 canonical preregistration"),
        artifact_record("results/t1_iter12_honest_composite.json", "T1 canonical lockbox JSON"),
        artifact_record("results/t1_iter12_honest_composite.oof.npy", "T1 canonical OOF"),
        artifact_record("audit_t1_iter12_batch_integrity.py", "T1 iter12 batch-integrity audit script"),
        artifact_record("results/t1_iter12_batch_integrity_audit_20260508.json", "T1 iter12 batch-integrity audit JSON"),
        artifact_record("results/t1_iter12_batch_integrity_audit_20260508.md", "T1 iter12 batch-integrity audit Markdown"),
        artifact_record("run_t1_iter34_hybrid_8item_multibase.py", "T1 strongest-candidate script"),
        artifact_record("results/preregistration_t1_iter34_hybrid_20260506_135932.json", "T1 iter34 preregistration"),
        artifact_record("results/lockbox_t1_iter34_hybrid_20260506_141720.json", "T1 iter34 lockbox JSON"),
        artifact_record("results/lockbox_t1_iter34_hybrid_20260506_141720.oof.npy", "T1 iter34 OOF"),
        artifact_record("results/iter34_leakage_audit_20260506_143922.json", "T1 iter34 leakage audit"),
        artifact_record("results/iter34_loso_2026_05_06.json", "T1 iter34 LOSO"),
        artifact_record("audit_t1_iter34_n93_gap.py", "T1 iter34 N=93 caveat audit script"),
        artifact_record("results/audit_t1_iter34_n93_gap_20260508.json", "T1 iter34 N=93 caveat audit JSON"),
        artifact_record("audit_t1_iter48_aux_validrange.py", "T1 iter34 auxiliary-label valid-range audit script"),
        artifact_record("results/t1_iter48_aux_validrange_audit.json", "T1 iter34 auxiliary-label valid-range audit JSON"),
        artifact_record("audit_t1_iter34_aux_order.py", "T1 iter34 auxiliary random-chain order audit script"),
        artifact_record("results/t1_iter34_aux_order_audit.json", "T1 iter34 auxiliary random-chain order audit JSON"),
        artifact_record("results/t1_iter34_aux_order_audit.md", "T1 iter34 auxiliary random-chain order audit Markdown"),
        artifact_record("tests/test_run_t1_iter4_labels.py", "T1 valid item-total loader regression test"),
        artifact_record("audit_t1_iter34_p2_robustness.py", "T1 iter34 P2 robustness audit script"),
        artifact_record("results/iter34_p2_robustness_20260508.json", "T1 iter34 P2 robustness audit JSON"),
        artifact_record("audit_t1_iter34_base_item_decomp.py", "T1 iter34 base/item/P2 decomposition script"),
        artifact_record("results/iter34_base_item_decomp_20260508.json", "T1 iter34 base/item/P2 decomposition JSON"),
        artifact_record("run_t1_iter46_et_robust.py", "T1 iter46 ET-only robustification script"),
        artifact_record("results/preregistration_t1_iter46_etrobust_20260508_160501.json", "T1 iter46 preregistration"),
        artifact_record("results/lockbox_t1_iter46_etrobust_20260508_162825.json", "T1 iter46 lockbox JSON"),
        artifact_record("results/lockbox_t1_iter46_etrobust_20260508_162825.oof.npy", "T1 iter46 OOF"),
        artifact_record("results/iter46_etrobust_local_comparisons_20260508.json", "T1 iter46 local comparator alignment"),
        artifact_record("run_t1_iter37_harnet_finetune.py", "T1 iter37 HARNet fine-tuning pilot script"),
        artifact_record("results/iter37_harnet_finetune_screen_20260508_110641.json", "T1 iter37 HARNet fine-tuning screen JSON"),
        artifact_record("results/iter37_harnet_finetune_rows_20260508_110641.csv", "T1 iter37 HARNet fine-tuning OOF rows"),
        artifact_record("results/iter37_harnet_wrist_windows.npz", "T1 iter37 raw wrist-window cache"),
        artifact_record("audit_t3_target_stage2_covariates.py", "T3 target and Stage-2 covariate audit script"),
        artifact_record("results/t3_target_stage2_covariate_audit_20260508_165653.json", "T3 target and Stage-2 covariate audit JSON"),
        artifact_record("run_t3_iter41_target_fix.py", "T3 corrected-target audit-truth script"),
        artifact_record("results/preregistration_t3_iter41_targetfix_20260508_170021.json", "T3 iter41 corrected-target preregistration"),
        artifact_record("results/iter41_targetfix_20260508_170021.json", "T3 iter41 corrected-target LOOCV JSON"),
        artifact_record("results/iter41_targetfix_subject_preds_20260508_170021.csv", "T3 iter41 corrected-target OOF rows"),
        artifact_record("results/preregistration_t3_iter41_targetfix_loso_20260508_171003.json", "T3 iter41 corrected-target LOSO preregistration"),
        artifact_record("results/iter41_targetfix_loso_20260508_171003.json", "T3 iter41 corrected-target LOSO JSON"),
        artifact_record("run_t3_iter47_invalid_code_fix.py", "T3 iter47 invalid-code target correction script"),
        artifact_record("results/preregistration_t3_iter47_invalidcode_20260508_194605.json", "T3 iter47 invalid-code target correction preregistration"),
        artifact_record("results/iter47_invalidcode_20260508_194605.json", "T3 iter47 invalid-code LOOCV JSON"),
        artifact_record("results/iter47_invalidcode_rows_20260508_194605.csv", "T3 iter47 invalid-code seed rows"),
        artifact_record("results/iter47_invalidcode_subject_preds_20260508_194605.csv", "T3 iter47 invalid-code subject predictions"),
        artifact_record("results/preregistration_t3_iter47_invalidcode_loso_20260508_195424.json", "T3 iter47 invalid-code LOSO preregistration"),
        artifact_record("results/iter47_invalidcode_loso_20260508_195424.json", "T3 iter47 invalid-code LOSO JSON"),
        artifact_record("results/iter47_invalidcode_loso_rows_20260508_195424.csv", "T3 iter47 invalid-code LOSO rows"),
        artifact_record("audit_t3_iter47_target_integrity.py", "T3 iter47 target-integrity audit script"),
        artifact_record("results/t3_iter47_target_integrity_audit_20260508.json", "T3 iter47 target-integrity audit JSON"),
        artifact_record("results/t3_iter47_target_integrity_audit_20260508.md", "T3 iter47 target-integrity audit Markdown"),
        artifact_record("audit_t3_complete33_claim_labeling.py", "T3 complete33/N=88 claim labeling audit script"),
        artifact_record("results/t3_complete33_claim_labeling_audit_20260509.json", "T3 complete33/N=88 claim labeling audit JSON"),
        artifact_record("results/t3_complete33_claim_labeling_audit_20260509.md", "T3 complete33/N=88 claim labeling audit Markdown"),
        artifact_record("audit_external_result_claim_labeling.py", "External-result claim labeling audit script"),
        artifact_record("results/external_result_claim_labeling_audit_20260509.json", "External-result claim labeling audit JSON"),
        artifact_record("results/external_result_claim_labeling_audit_20260509.md", "External-result claim labeling audit Markdown"),
        artifact_record("audit_remaining_blocker_actions.py", "Remaining blocker action audit script"),
        artifact_record("results/remaining_blocker_action_audit_20260509.json", "Remaining blocker action audit JSON"),
        artifact_record("results/remaining_blocker_action_audit_20260509.md", "Remaining blocker action audit Markdown"),
        artifact_record("audit_external_access_readiness.py", "External access readiness audit script"),
        artifact_record("results/external_access_readiness_audit_20260509.json", "External access readiness audit JSON"),
        artifact_record("results/external_access_readiness_audit_20260509.md", "External access readiness audit Markdown"),
        artifact_record("audit_access_submission_tracker.py", "External access submission tracker script"),
        artifact_record("results/access_submission_tracker_20260509.json", "External access submission tracker JSON"),
        artifact_record("results/access_submission_tracker_20260509.md", "External access submission tracker Markdown"),
        artifact_record("scripts/weargait_raw_data_recovery_runbook.md", "WearGait raw-data recovery runbook"),
        artifact_record("audit_weargait_raw_data_recovery_runbook.py", "WearGait raw-data recovery runbook audit script"),
        artifact_record("results/weargait_raw_data_recovery_runbook_audit_20260509.json", "WearGait raw-data recovery runbook audit JSON"),
        artifact_record("results/weargait_raw_data_recovery_runbook_audit_20260509.md", "WearGait raw-data recovery runbook audit Markdown"),
        artifact_record("audit_task_plan_current_scope.py", "Task-plan current-scope guard script"),
        artifact_record("results/task_plan_current_scope_audit_20260509.json", "Task-plan current-scope guard JSON"),
        artifact_record("results/task_plan_current_scope_audit_20260509.md", "Task-plan current-scope guard Markdown"),
        artifact_record("audit_paper_generator_routing.py", "Current-paper renderer routing audit script"),
        artifact_record("results/paper_generator_routing_audit_20260509.json", "Current-paper renderer routing audit JSON"),
        artifact_record("results/paper_generator_routing_audit_20260509.md", "Current-paper renderer routing audit Markdown"),
        artifact_record("audit_readme_claim_routing.py", "README current-claim routing audit script"),
        artifact_record("results/readme_claim_routing_audit_20260509.json", "README current-claim routing audit JSON"),
        artifact_record("results/readme_claim_routing_audit_20260509.md", "README current-claim routing audit Markdown"),
        artifact_record("audit_legacy_manuscript_surfaces.py", "Legacy manuscript-surface quarantine audit script"),
        artifact_record("results/legacy_manuscript_surface_audit_20260509.json", "Legacy manuscript-surface quarantine audit JSON"),
        artifact_record("results/legacy_manuscript_surface_audit_20260509.md", "Legacy manuscript-surface quarantine audit Markdown"),
        artifact_record("audit_historical_archive_surfaces.py", "Historical archive-surface quarantine audit script"),
        artifact_record("results/historical_archive_surface_audit_20260509.json", "Historical archive-surface quarantine audit JSON"),
        artifact_record("results/historical_archive_surface_audit_20260509.md", "Historical archive-surface quarantine audit Markdown"),
        artifact_record("audit_secret_hygiene.py", "Secret hygiene audit script"),
        artifact_record("results/secret_hygiene_audit_20260509.json", "Secret hygiene audit JSON"),
        artifact_record("results/secret_hygiene_audit_20260509.md", "Secret hygiene audit Markdown"),
        artifact_record("audit_t3_iter47_residual_anatomy.py", "T3 iter47 residual-anatomy audit script"),
        artifact_record("results/t3_iter47_residual_anatomy_20260509.json", "T3 iter47 residual-anatomy audit JSON"),
        artifact_record("results/t3_iter47_residual_anatomy_20260509.md", "T3 iter47 residual-anatomy audit Markdown"),
        artifact_record("audit_t3_iter47_ccc_rescale_sanity.py", "T3 iter47 CCC-rescale sanity audit script"),
        artifact_record("results/t3_iter47_ccc_rescale_sanity_20260509.json", "T3 iter47 CCC-rescale sanity audit JSON"),
        artifact_record("results/t3_iter47_ccc_rescale_sanity_20260509.md", "T3 iter47 CCC-rescale sanity audit Markdown"),
        artifact_record("audit_current_headline_influence.py", "Current headline leave-one influence audit script"),
        artifact_record("results/current_headline_influence_audit_20260509.json", "Current headline leave-one influence audit JSON"),
        artifact_record("results/current_headline_influence_audit_20260509.md", "Current headline leave-one influence audit Markdown"),
        artifact_record("audit_t3_iter47_domain_residuals.py", "T3 iter47 domain residual audit script"),
        artifact_record("results/t3_iter47_domain_residual_audit_20260509.json", "T3 iter47 domain residual audit JSON"),
        artifact_record("results/t3_iter47_domain_residual_audit_20260509.md", "T3 iter47 domain residual audit Markdown"),
        artifact_record("audit_t3_iter47_item_residuals.py", "T3 iter47 item-level residual audit script"),
        artifact_record("results/t3_iter47_item_residual_audit_20260509.json", "T3 iter47 item-level residual audit JSON"),
        artifact_record("results/t3_iter47_item_residual_audit_20260509.md", "T3 iter47 item-level residual audit Markdown"),
        artifact_record("audit_dst_walkway_leakage.py", "T3 dst walkway-distillation provenance audit script"),
        artifact_record("results/dst_walkway_leakage_audit_20260508_multiseed.json", "T3 dst walkway-distillation multiseed audit JSON"),
        artifact_record("results/dst_walkway_leakage_audit_20260508_multiseed.md", "T3 dst walkway-distillation multiseed audit Markdown"),
        artifact_record("results/dst_walkway_leakage_audit_subject_rows_20260508_multiseed.csv", "T3 dst walkway-distillation subject rows"),
        artifact_record("audit_ablation_v3_cache_provenance.py", "Ablation V3 live-cache provenance audit script"),
        artifact_record("results/ablation_v3_cache_provenance_audit_20260508.json", "Ablation V3 live-cache provenance audit JSON"),
        artifact_record("results/ablation_v3_cache_provenance_audit_20260508.md", "Ablation V3 live-cache provenance audit Markdown"),
        artifact_record("audit_ablation_v3_regeneration.py", "Ablation V3 non-destructive regeneration probe script"),
        artifact_record("results/ablation_v3_regeneration_probe_20260509.json", "Ablation V3 regeneration probe JSON"),
        artifact_record("results/ablation_v3_regeneration_probe_20260509.md", "Ablation V3 regeneration probe Markdown"),
        artifact_record("scripts/download_weargait_missing_synapse.py", "WearGait missing Synapse input recovery helper"),
        artifact_record("results/weargait_missing_synapse_recovery_preflight_20260509.json", "WearGait missing Synapse input recovery preflight JSON"),
        artifact_record("results/weargait_missing_synapse_recovery_preflight_20260509.md", "WearGait missing Synapse input recovery preflight Markdown"),
        artifact_record("audit_cache_consumer_guards.py", "Cache consumer guard audit script"),
        artifact_record("results/cache_consumer_guard_audit_20260508.json", "Cache consumer guard audit JSON"),
        artifact_record("results/cache_consumer_guard_audit_20260508.md", "Cache consumer guard audit Markdown"),
        artifact_record("audit_transitive_cache_dependencies.py", "Transitive cache dependency audit script"),
        artifact_record("results/transitive_cache_dependency_audit_20260508.json", "Transitive cache dependency audit JSON"),
        artifact_record("results/transitive_cache_dependency_audit_20260508.md", "Transitive cache dependency audit Markdown"),
        artifact_record("audit_runtime_cache_dependencies.py", "Runtime cache dependency audit script"),
        artifact_record("results/runtime_cache_dependency_audit_20260508.json", "Runtime cache dependency audit JSON"),
        artifact_record("results/runtime_cache_dependency_audit_20260508.md", "Runtime cache dependency audit Markdown"),
        artifact_record("audit_canonical_claim_consistency.py", "Canonical claim consistency audit script"),
        artifact_record("results/canonical_claim_consistency_audit_20260508.json", "Canonical claim consistency audit JSON"),
        artifact_record("results/canonical_claim_consistency_audit_20260508.md", "Canonical claim consistency audit Markdown"),
        artifact_record("audit_headline_metric_recompute.py", "Headline metric recompute audit script"),
        artifact_record("results/headline_metric_recompute_audit_20260508.json", "Headline metric recompute audit JSON"),
        artifact_record("results/headline_metric_recompute_audit_20260508.md", "Headline metric recompute audit Markdown"),
        artifact_record("audit_ccc_metric_integrity.py", "CCC metric integrity audit script"),
        artifact_record("results/ccc_metric_integrity_audit_20260509.json", "CCC metric integrity audit JSON"),
        artifact_record("results/ccc_metric_integrity_audit_20260509.md", "CCC metric integrity audit Markdown"),
        artifact_record("audit_oof_artifact_integrity.py", "OOF artifact integrity audit script"),
        artifact_record("results/oof_artifact_integrity_audit_20260508.json", "OOF artifact integrity audit JSON"),
        artifact_record("results/oof_artifact_integrity_audit_20260508.md", "OOF artifact integrity audit Markdown"),
        artifact_record("audit_preregistration_temporal_integrity.py", "Pre-registration temporal integrity audit script"),
        artifact_record("results/preregistration_temporal_integrity_audit_20260508.json", "Pre-registration temporal integrity audit JSON"),
        artifact_record("results/preregistration_temporal_integrity_audit_20260508.md", "Pre-registration temporal integrity audit Markdown"),
        artifact_record("audit_pre_audit_claim_labeling.py", "Pre-audit claim labeling audit script"),
        artifact_record("results/pre_audit_claim_labeling_audit_20260508.json", "Pre-audit claim labeling audit JSON"),
        artifact_record("results/pre_audit_claim_labeling_audit_20260508.md", "Pre-audit claim labeling audit Markdown"),
        artifact_record("audit_historical_subdomain_claim_labeling.py", "Historical subdomain/sensor claim labeling audit script"),
        artifact_record("results/historical_subdomain_claim_labeling_audit_20260509.json", "Historical subdomain/sensor claim labeling audit JSON"),
        artifact_record("results/historical_subdomain_claim_labeling_audit_20260509.md", "Historical subdomain/sensor claim labeling audit Markdown"),
        artifact_record("audit_t1_candidate_claim_labeling.py", "T1 candidate claim labeling audit script"),
        artifact_record("results/t1_candidate_claim_labeling_audit_20260508.json", "T1 candidate claim labeling audit JSON"),
        artifact_record("results/t1_candidate_claim_labeling_audit_20260508.md", "T1 candidate claim labeling audit Markdown"),
        artifact_record("audit_reportable_artifact_flags.py", "Reportable artifact raw-flag policy audit script"),
        artifact_record("results/reportable_artifact_flag_audit_20260509.json", "Reportable artifact raw-flag policy audit JSON"),
        artifact_record("results/reportable_artifact_flag_audit_20260509.md", "Reportable artifact raw-flag policy audit Markdown"),
        artifact_record("audit_per_item_evidence_map.py", "Per-item evidence map audit script"),
        artifact_record("results/per_item_evidence_map_20260508.json", "Per-item evidence map JSON"),
        artifact_record("results/per_item_evidence_map_20260508.md", "Per-item evidence map Markdown"),
        artifact_record("audit_per_item_oof_companion_scope.py", "Per-item OOF companion scope audit script"),
        artifact_record("results/per_item_oof_companion_scope_audit_20260508.json", "Per-item OOF companion scope audit JSON"),
        artifact_record("results/per_item_oof_companion_scope_audit_20260508.md", "Per-item OOF companion scope audit Markdown"),
        artifact_record("run_t3_iter42_target_prorate.py", "T3 iter42 partial-missing proration audit script"),
        artifact_record("results/preregistration_t3_iter42_prorate_20260508_173412.json", "T3 iter42 proration preregistration"),
        artifact_record("results/iter42_prorate_20260508_173412.json", "T3 iter42 proration LOOCV JSON"),
        artifact_record("results/iter42_prorate_subject_preds_20260508_173412.csv", "T3 iter42 proration OOF rows"),
        artifact_record("results/preregistration_t3_iter42_prorate_loso_20260508_174349.json", "T3 iter42 proration LOSO preregistration"),
        artifact_record("results/iter42_prorate_loso_20260508_174349.json", "T3 iter42 proration LOSO JSON"),
        artifact_record("audit_t3_clinical_dependency.py", "T3 corrected clinical-dependency audit script"),
        artifact_record("results/t3_clinical_dependency_20260508.json", "T3 corrected clinical-dependency audit JSON"),
        artifact_record("results/t3_clinical_dependency_20260508_subject_rows.csv", "T3 corrected clinical-dependency subject rows"),
        artifact_record("run_t3_iter5_clinical.py", "T3 historical iter5 script"),
        artifact_record("results/preregistration_t3_iter5_20260502_171604.json", "T3 historical iter5 preregistration"),
        artifact_record("results/lockbox_t3_iter5_A3_tier1_20260502_171604.json", "T3 historical target-contaminated iter5 JSON"),
        artifact_record("results/lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy", "T3 historical target-contaminated iter5 OOF"),
        artifact_record("visualize_t3_iter5.py", "T3 historical deep-dive generator"),
        artifact_record("results/t3_iter5_deepdive/summary.json", "T3 historical deep-dive summary"),
        artifact_record("results/t3_iter16_site_ipw_lockbox.json", "T3 historical site-IPW and LOSO"),
        artifact_record("results/t3_conformal_abstention_20260505.json", "T3 historical conformal and abstention"),
        artifact_record("run_current_conformal_abstention.py", "Current conformal and abstention script"),
        artifact_record("results/current_conformal_abstention_20260508.json", "Current conformal and abstention JSON"),
        artifact_record("results/current_conformal_abstention_intervals_20260508.csv", "Current conformal interval rows"),
        artifact_record("results/current_conformal_abstention_curves_20260508.csv", "Current abstention curve rows"),
        artifact_record("results/current_conformal_abstention.html", "Current conformal and abstention HTML"),
        artifact_record("run_t3_iter38_fogstar_stage1.py", "T3 iter38 FoG-STAR Stage-1 augmentation screen script"),
        artifact_record("results/iter38_fogstar_probe_20260508_112546.json", "T3 iter38 FoG-STAR schema probe"),
        artifact_record("results/iter38_fogstar_stage1_screen_20260508_142623.json", "T3 iter38 FoG-STAR Stage-1 augmentation screen JSON"),
        artifact_record("results/iter38_fogstar_stage1_screen_rows_20260508_142623.csv", "T3 iter38 FoG-STAR Stage-1 augmentation rows"),
        artifact_record("run_t3_iter39_fogstar_zeroshot.py", "T3 iter39 FoG-STAR zero-shot script"),
        artifact_record("results/preregistration_t3_iter39_fogstar_zeroshot_20260508_143717.json", "T3 iter39 FoG-STAR zero-shot preregistration"),
        artifact_record("results/iter39_fogstar_zeroshot_20260508_143717.json", "T3 iter39 FoG-STAR zero-shot result JSON"),
        artifact_record("results/iter39_fogstar_zeroshot_rows_20260508_143717.csv", "T3 iter39 FoG-STAR zero-shot rows"),
        artifact_record("visualize_fogstar_iter39.py", "T3 iter39 FoG-STAR visualization generator"),
        artifact_record("results/iter39_fogstar_zeroshot.html", "T3 iter39 FoG-STAR zero-shot visualization"),
        artifact_record("results/openrouter_grok43_iter39_20260508.json", "OpenRouter Grok 4.3 iter39 consult"),
        artifact_record("results/openrouter_deepseekv4pro_iter39_retry_20260508.json", "OpenRouter DeepSeek V4 Pro iter39 consult"),
        artifact_record("run_t3_iter40_local_residual.py", "T3 iter40 local-residual wildcard script"),
        artifact_record("results/iter40_local_residual_screen_20260508_144905.json", "T3 iter40 local-residual wildcard screen JSON"),
        artifact_record("results/iter40_local_residual_screen_rows_20260508_144905.csv", "T3 iter40 local-residual wildcard screen rows"),
        artifact_record("run_t3_iter50_lowdf_convex.py", "T3 iter50 low-degree nested convex-mix script"),
        artifact_record("results/preregistration_t3_iter50_lowdfconvex_screen_20260508_225105.json", "T3 iter50 low-degree convex-mix screen declaration"),
        artifact_record("results/iter50_lowdf_convex_screen_20260508_225105.json", "T3 iter50 low-degree convex-mix screen JSON"),
        artifact_record("results/iter50_lowdf_convex_screen_rows_20260508_225105.csv", "T3 iter50 low-degree convex-mix fold rows"),
        artifact_record("results/iter50_lowdf_convex_subject_preds_20260508_225105.csv", "T3 iter50 low-degree convex-mix subject predictions"),
        artifact_record("run_t3_iter49_cops.py", "T3 iter49 COPS external route script"),
        artifact_record("results/preregistration_t3_iter49_cops.json", "T3 iter49 COPS stable preregistration"),
        artifact_record("results/preregistration_t3_iter49_cops_20260508_173452.json", "T3 iter49 COPS local preregistration"),
        artifact_record("results/iter49_cops_probe.json", "T3 iter49 COPS route probe JSON"),
        artifact_record("results/iter49_cops_probe_20260508_173929.json", "T3 iter49 COPS route probe timestamped JSON"),
        artifact_record("results/iter49_cops_download_manifest.json", "T3 iter49 COPS download manifest"),
        artifact_record("results/iter49_cops_features_full.csv", "T3 iter49 COPS full feature cache"),
        artifact_record("results/iter49_cops_features_full.csv.manifest.json", "T3 iter49 COPS feature-cache manifest"),
        artifact_record("results/iter49_cops_zeroshot_20260508_185226.json", "T3 iter49 COPS zero-shot result JSON"),
        artifact_record("results/iter49_cops_zeroshot.json", "T3 iter49 COPS stable zero-shot result JSON"),
        artifact_record("results/iter49_cops_zeroshot_rows_20260508_185226.csv", "T3 iter49 COPS zero-shot row predictions"),
        artifact_record("scripts/probe_tlvmc_fog_route.py", "TLVMC/DeFOG route probe script"),
        artifact_record("results/tlvmc_fog_route_probe_20260509.json", "TLVMC/DeFOG route probe JSON"),
        artifact_record("results/tlvmc_fog_route_probe_20260509.md", "TLVMC/DeFOG route probe Markdown"),
        artifact_record("scripts/write_tlvmc_defog_prereg.py", "TLVMC/DeFOG iter51 preregistration writer"),
        artifact_record("results/preregistration_t3_iter51_tlvmc_defog_zeroshot.json", "TLVMC/DeFOG iter51 stable preregistration"),
        artifact_record("results/preregistration_t3_iter51_tlvmc_defog_zeroshot_20260509_010408.json", "TLVMC/DeFOG iter51 timestamped preregistration"),
        artifact_record("results/preregistration_t3_iter51_tlvmc_defog_zeroshot.md", "TLVMC/DeFOG iter51 preregistration summary"),
        artifact_record("run_t3_iter51_tlvmc_defog.py", "TLVMC/DeFOG iter51 zero-shot runner"),
        artifact_record("results/iter51_tlvmc_defog_download_manifest.json", "TLVMC/DeFOG iter51 download manifest"),
        artifact_record("results/iter51_tlvmc_defog_features.csv", "TLVMC/DeFOG iter51 feature cache"),
        artifact_record("results/iter51_tlvmc_defog_features.csv.manifest.json", "TLVMC/DeFOG iter51 feature manifest"),
        artifact_record("results/iter51_tlvmc_defog_zeroshot.json", "TLVMC/DeFOG iter51 stable zero-shot result JSON"),
        artifact_record("results/iter51_tlvmc_defog_zeroshot_20260509_013357.json", "TLVMC/DeFOG iter51 timestamped zero-shot result JSON"),
        artifact_record("results/iter51_tlvmc_defog_zeroshot_rows_20260509_013357.csv", "TLVMC/DeFOG iter51 row predictions"),
        artifact_record("run_t3_iter52_pdfe_turning.py", "PDFE iter52 turning-in-place external zero-shot runner"),
        artifact_record("results/preregistration_t3_iter52_pdfe_turning_zeroshot.json", "PDFE iter52 stable preregistration"),
        artifact_record("results/preregistration_t3_iter52_pdfe_turning_zeroshot.md", "PDFE iter52 preregistration summary"),
        artifact_record("results/iter52_pdfe_turning_probe.json", "PDFE iter52 route probe JSON"),
        artifact_record("results/iter52_pdfe_turning_download_manifest.json", "PDFE iter52 download manifest"),
        artifact_record("results/iter52_pdfe_turning_features.csv", "PDFE iter52 feature cache"),
        artifact_record("results/iter52_pdfe_turning_features.csv.manifest.json", "PDFE iter52 feature manifest"),
        artifact_record("results/iter52_pdfe_turning_zeroshot.json", "PDFE iter52 stable zero-shot result JSON"),
        artifact_record("results/iter52_pdfe_turning_zeroshot_20260509_092223.json", "PDFE iter52 timestamped zero-shot result JSON"),
        artifact_record("results/iter52_pdfe_turning_zeroshot_rows_20260509_092223.csv", "PDFE iter52 row predictions"),
        artifact_record("results/phone_tremor_route_consult_20260509.json", "Papadopoulos phone-call tremor route consult JSON"),
        artifact_record("results/phone_tremor_route_consult_20260509.md", "Papadopoulos phone-call tremor route consult Markdown"),
        artifact_record("results/harmonized_accel_route_consult_20260509.json", "Harmonized accelerometry route consult JSON"),
        artifact_record("results/harmonized_accel_route_consult_20260509.md", "Harmonized accelerometry route consult Markdown"),
        artifact_record("results/smartwatch_subitem_route_refresh_20260509.json", "Monipar/BIOCLITE smartwatch subitem route refresh JSON"),
        artifact_record("results/smartwatch_subitem_route_refresh_20260509.md", "Monipar/BIOCLITE smartwatch subitem route refresh Markdown"),
        artifact_record("results/external_route_audit_monipar_bioclite_20260509.md", "Kimi Monipar/BIOCLITE route consult Markdown"),
        artifact_record("results/derivative_multimodal_route_refresh_20260509.json", "Derivative multimodal route refresh JSON"),
        artifact_record("results/derivative_multimodal_route_refresh_20260509.md", "Derivative multimodal route refresh Markdown"),
        artifact_record("results/request_only_actigraphy_route_refresh_20260509.json", "Request-only actigraphy route refresh JSON"),
        artifact_record("results/request_only_actigraphy_route_refresh_20260509.md", "Request-only actigraphy route refresh Markdown"),
        artifact_record("results/luxembourg_upper_limb_route_refresh_20260509.json", "Luxembourg upper-limb route refresh JSON"),
        artifact_record("results/luxembourg_upper_limb_route_refresh_20260509.md", "Luxembourg upper-limb route refresh Markdown"),
        artifact_record("results/prequantipark_route_refresh_20260509.json", "Pre-QuantiPark route refresh JSON"),
        artifact_record("results/prequantipark_route_refresh_20260509.md", "Pre-QuantiPark route refresh Markdown"),
        artifact_record("results/tum_rocket_inception_route_refresh_20260509.json", "TUM ROCKET/InceptionTime route refresh JSON"),
        artifact_record("results/tum_rocket_inception_route_refresh_20260509.md", "TUM ROCKET/InceptionTime route refresh Markdown"),
        artifact_record("results/paradigma_yin_route_refresh_20260509.json", "ParaDigMa/Yin route refresh JSON"),
        artifact_record("results/paradigma_yin_route_refresh_20260509.md", "ParaDigMa/Yin route refresh Markdown"),
        artifact_record("run_t3_iter53_parkinsonathome.py", "Parkinson@Home iter53 route runner"),
        artifact_record("results/preregistration_t3_iter53_parkinsonathome_zeroshot.json", "Parkinson@Home iter53 stable preregistration"),
        artifact_record("results/preregistration_t3_iter53_parkinsonathome_zeroshot.md", "Parkinson@Home iter53 preregistration summary"),
        artifact_record("results/iter53_parkinsonathome_probe.json", "Parkinson@Home iter53 probe JSON"),
        artifact_record("results/iter53_parkinsonathome_features.csv", "Parkinson@Home iter53 feature cache"),
        artifact_record("results/iter53_parkinsonathome_features.csv.manifest.json", "Parkinson@Home iter53 feature manifest"),
        artifact_record("results/parkinsonathome_route_refresh_20260509.json", "Parkinson@Home route refresh JSON"),
        artifact_record("results/parkinsonathome_route_refresh_20260509.md", "Parkinson@Home route refresh Markdown"),
        artifact_record("results/kimi_next_action_after_parkinsonathome_20260509.json", "Kimi post-Parkinson@Home next-action consult JSON"),
        artifact_record("results/kimi_next_action_after_parkinsonathome_20260509.md", "Kimi post-Parkinson@Home next-action consult Markdown"),
        artifact_record("audit_recent_external_web_leads.py", "Recent external web-leads audit script"),
        artifact_record("results/recent_external_web_leads_20260509.json", "Recent external web-leads audit JSON"),
        artifact_record("results/recent_external_web_leads_20260509.md", "Recent external web-leads audit Markdown"),
        artifact_record("results/kimi_recent_external_web_leads_20260509.md", "Kimi recent external web-leads advice Markdown"),
        artifact_record("results/kimi_ppmi_packet_advice_20260509.md", "Kimi PPMI request-packet advice Markdown"),
        artifact_record("results/external_dataset_route_audit_20260508.json", "External dataset route audit JSON"),
        artifact_record("results/external_dataset_route_audit_20260508.md", "External dataset route audit Markdown"),
        artifact_record("scripts/ppmi_verily_setup.md", "PPMI/Verily access runbook"),
        artifact_record("scripts/ppmi_verily_tier3_request_packet.md", "PPMI/Verily Tier-3 request packet template"),
        artifact_record("audit_ppmi_verily_request_packet.py", "PPMI/Verily Tier-3 request packet audit script"),
        artifact_record("results/ppmi_verily_request_packet_audit_20260509.json", "PPMI/Verily Tier-3 request packet audit JSON"),
        artifact_record("results/ppmi_verily_request_packet_audit_20260509.md", "PPMI/Verily Tier-3 request packet audit Markdown"),
        artifact_record("scripts/ppp_pd_vme_request_setup.md", "PPP/PD-VME access runbook"),
        artifact_record("scripts/ppp_pd_vme_request_packet.md", "PPP/PD-VME request packet template"),
        artifact_record("audit_ppp_pd_vme_request_packet.py", "PPP/PD-VME request packet audit script"),
        artifact_record("results/ppp_pd_vme_request_packet_audit_20260509.json", "PPP/PD-VME request packet audit JSON"),
        artifact_record("results/ppp_pd_vme_request_packet_audit_20260509.md", "PPP/PD-VME request packet audit Markdown"),
        artifact_record("results/kimi_ppp_packet_advice_20260509.md", "Kimi PPP/PD-VME request-packet advice Markdown"),
        artifact_record("scripts/watchpd_request_setup.md", "WATCH-PD access runbook"),
        artifact_record("scripts/watchpd_request_packet.md", "WATCH-PD proposal packet template"),
        artifact_record("audit_watchpd_request_packet.py", "WATCH-PD proposal packet audit script"),
        artifact_record("results/watchpd_request_packet_audit_20260509.json", "WATCH-PD proposal packet audit JSON"),
        artifact_record("results/watchpd_request_packet_audit_20260509.md", "WATCH-PD proposal packet audit Markdown"),
        artifact_record("results/kimi_watchpd_packet_advice_20260509.md", "Kimi WATCH-PD proposal-packet advice Markdown"),
        artifact_record("scripts/cns_portugal_request_setup.md", "CNS Portugal access runbook"),
        artifact_record("scripts/cns_portugal_request_packet.md", "CNS Portugal author request packet template"),
        artifact_record("audit_cns_portugal_request_packet.py", "CNS Portugal request packet audit script"),
        artifact_record("results/cns_portugal_request_packet_audit_20260509.json", "CNS Portugal request packet audit JSON"),
        artifact_record("results/cns_portugal_request_packet_audit_20260509.md", "CNS Portugal request packet audit Markdown"),
        artifact_record("results/kimi_cns_portugal_packet_advice_20260509.md", "Kimi CNS Portugal request-packet advice Markdown"),
        artifact_record("scripts/icicle_request_setup.md", "ICICLE access runbook"),
        artifact_record("scripts/icicle_request_packet.md", "ICICLE request packet template"),
        artifact_record("audit_icicle_request_packet.py", "ICICLE request packet audit script"),
        artifact_record("results/icicle_request_packet_audit_20260509.json", "ICICLE request packet audit JSON"),
        artifact_record("results/icicle_request_packet_audit_20260509.md", "ICICLE request packet audit Markdown"),
        artifact_record("results/kimi_icicle_packet_advice_20260509.md", "Kimi ICICLE request-packet advice Markdown"),
        artifact_record("scripts/synapse_hssayeni_setup.md", "Hssayeni Synapse access runbook"),
        artifact_record("scripts/hssayeni_mjff_dua_request_packet.md", "Hssayeni/MJFF Synapse DUA request packet template"),
        artifact_record("audit_hssayeni_mjff_dua_request_packet.py", "Hssayeni/MJFF DUA request packet audit script"),
        artifact_record("results/hssayeni_mjff_dua_request_packet_audit_20260509.json", "Hssayeni/MJFF DUA request packet audit JSON"),
        artifact_record("results/hssayeni_mjff_dua_request_packet_audit_20260509.md", "Hssayeni/MJFF DUA request packet audit Markdown"),
        artifact_record("results/kimi_hssayeni_packet_advice_20260509.md", "Kimi Hssayeni/MJFF DUA request-packet advice Markdown"),
        artifact_record("run_t3_iter26_hssayeni.py", "Hssayeni/MJFF acquisition scaffold"),
        artifact_record("results/iter26_dua_status_20260508.json", "Hssayeni DUA status"),
        artifact_record("results/current_best_pipeline_artifact_index_20260508.md", "Best-pipeline artifact index"),
        artifact_record("results/thread_goal_completion_audit_20260508.md", "Thread completion audit"),
        artifact_record("render_current_paper.py", "Current manuscript renderer"),
        artifact_record("CURRENT_PAPER.html", "Current manuscript HTML export"),
        artifact_record("results/current_paper_export/manifest.json", "Current manuscript export manifest"),
        artifact_record("verify_current_goal_state.py", "Current goal-state verifier"),
        artifact_record("results/current_goal_state_verification_20260508.json", "Current goal-state verification report"),
        artifact_record("audit_prompt_objective_evidence.py", "Prompt-to-artifact objective audit script"),
        artifact_record("results/prompt_objective_evidence_audit_20260508.json", "Prompt-to-artifact objective audit JSON"),
        artifact_record("results/prompt_objective_evidence_audit_20260508.md", "Prompt-to-artifact objective audit Markdown"),
        artifact_record("audit_cache_manifests.py", "Cache manifest audit script"),
        artifact_record("results/cache_manifest_audit_20260508.json", "Cache manifest audit JSON"),
        artifact_record("results/cache_manifest_audit_20260508.md", "Cache manifest audit Markdown"),
        artifact_record("results/item11_multiscale_recordings.csv.manifest.json", "Item11 recording companion manifest"),
        artifact_record("audit_missing_cache_manifest_origins.py", "Missing cache-manifest origin audit script"),
        artifact_record("results/missing_cache_manifest_origin_audit_20260509.json", "Missing cache-manifest origin audit JSON"),
        artifact_record("results/missing_cache_manifest_origin_audit_20260509.md", "Missing cache-manifest origin audit Markdown"),
        artifact_record("audit_manual_cache_backfill_evidence.py", "Manual missing-cache backfill evidence script"),
        artifact_record("results/manual_cache_backfill_evidence_20260509.json", "Manual missing-cache backfill evidence JSON"),
        artifact_record("results/manual_cache_backfill_evidence_20260509.md", "Manual missing-cache backfill evidence Markdown"),
        artifact_record("cache_provenance.py", "Shared cache provenance guard"),
        artifact_record("tests/test_cache_provenance.py", "Cache provenance guard tests"),
        artifact_record("compose_t1_iter14_fog.py", "FoG cache consumer using shared guard"),
        artifact_record("compose_t1_iter15_harnet.py", "HARNet cache consumer using shared guard"),
        artifact_record("run_t3_iter23_clinical_ablation.py", "Clinical-extras cache consumer using shared guard"),
        artifact_record("run_t3_iter24_stage2_forced.py", "Clinical-extras forced-stage2 consumer using shared guard"),
    ]

    t1_rows = [
        [
            "T1 iter12 honest floor",
            "canonical floor",
            fmt_num(t1_floor.get("ccc")),
            fmt_num(t1_floor.get("mae"), 3),
            str(t1_floor.get("n", "n/a")),
            "`compose_t1_iter12_honest.py`",
        ],
        [
            "T1 iter34 hybrid",
            "strongest candidate",
            fmt_num(t1_best.get("ccc")),
            fmt_num(t1_best.get("mae"), 3),
            str(t1_best.get("n", "n/a")),
            "`run_t1_iter34_hybrid_8item_multibase.py`",
        ],
        [
            "T1 iter46 ET-only",
            "robustification diagnostic",
            fmt_num(t1_iter46.get("ccc")),
            fmt_num(t1_iter46.get("mae"), 3),
            str(t1_iter46.get("n", "n/a")),
            "`run_t1_iter46_et_robust.py`",
        ],
    ]
    t3_rows = [
        [
            "T3 iter47 valid-range target",
            "audit-truth LOOCV",
            fmt_num(t3_current_metrics.get("ccc")),
            fmt_num(t3_current_metrics.get("mae"), 3),
            str(t3_current.get("n", "n/a")),
            "`run_t3_iter47_invalid_code_fix.py --mode run`",
        ],
        [
            "T3 iter47 no-dst Stage 2",
            "provenance sensitivity",
            fmt_num(t3_dst_nodst.get("ccc")),
            fmt_num(t3_dst_nodst.get("mae"), 3),
            str(t3_dst_audit.get("cohort", {}).get("n", "n/a")),
            "`audit_dst_walkway_leakage.py`",
        ],
        [
            "T3 iter47 no-cv Stage 2",
            "sensitivity",
            fmt_num(t3_nocv_metrics.get("ccc")),
            fmt_num(t3_nocv_metrics.get("mae"), 3),
            str(t3_nocv.get("n", "n/a")),
            "`run_t3_iter47_invalid_code_fix.py --mode run`",
        ],
        [
            "T3 iter47 LOSO",
            "valid-range transportability",
            fmt_num(t3_loso_current.get("two_way_mean_ccc")),
            f"NLS->WPD {fmt_num(t3_loso_current.get('NLS_to_WPD_mean_ccc'))}; WPD->NLS {fmt_num(t3_loso_current.get('WPD_to_NLS_mean_ccc'))}",
            str(t3_loso_current.get("n", "n/a")),
            "`run_t3_iter47_invalid_code_fix.py --mode loso`",
        ],
        [
            "T3 iter5 clinical",
            "historical target-contaminated",
            fmt_num(t3_old.get("ccc")),
            fmt_num(t3_old.get("mae"), 3),
            str(t3_old.get("n", "n/a")),
            "`run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1`",
        ],
    ]

    t1_boot = t1_best["bootstrap_delta_vs_iter5"]
    t1_audit_verdict = t1_audit["verdict"]
    t1_gap_subject = t1_n93_gap["missing_from_iter34"]
    t1_gap_grid = t1_n93_gap["one_subject_upper_bound"]["metrics"]
    t1_aux_invalid = (t1_aux_valid.get("invalid_auxiliary_items_in_current_chain_cohort") or [{}])[0]
    t1_aux_deltas = t1_aux_valid.get("cohort_deltas", {})
    t1_aux_order_summary = t1_aux_order.get("order_audit", {}).get("summary", {})
    t1_aux_order_impact = t1_aux_order.get("impact_screen", {}).get("common_sid_comparison", {})
    t1_p2_summary = t1_p2["summary"]
    t1_p2_verdict = t1_p2["verdict"]
    t1_decomp_summary = t1_decomp["summary"]
    t1_iter46_vs_iter12 = t1_iter46_cmp["comparisons"]["iter12"]
    t1_iter46_vs_iter34 = t1_iter46_cmp["comparisons"]["iter34"]
    t1_loso_rows = [
        [
            "NLS to WPD",
            fmt_num(t1_loso.get("ccc_NLS_to_WPD")),
            fmt_num(t1_loso.get("mae_NLS_to_WPD"), 3),
            fmt_num(t1_loso.get("r_NLS_to_WPD")),
        ],
        [
            "WPD to NLS",
            fmt_num(t1_loso.get("ccc_WPD_to_NLS")),
            fmt_num(t1_loso.get("mae_WPD_to_NLS"), 3),
            fmt_num(t1_loso.get("r_WPD_to_NLS")),
        ],
        [
            "Two-way mean",
            fmt_num(t1_loso.get("headline_two_way_mean_ccc")),
            "n/a",
            "n/a",
        ],
    ]
    t3_quartile_rows = [
        [
            row["quartile"],
            str(row["n"]),
            fmt_num(row["true_mean"], 2),
            fmt_num(row["pred_mean"], 2),
            fmt_num(row["residual_mean"], 2),
            fmt_num(row["mae"], 2),
        ]
        for row in t3_deep["quartile_rows"]
    ]
    t3_site_rows = [
        [
            row["site"],
            str(row["n"]),
            fmt_num(row["ccc"]),
            fmt_num(row["mae"], 3),
            fmt_num(row["r"]),
            fmt_num(row["bias_pred_minus_true"], 3),
        ]
        for row in t3_deep["site_rows"]
    ]
    conformal_rows = [
        [
            f"{int(row['nominal_coverage'] * 100)}%",
            fmt_num(row["empirical_coverage"], 3),
            fmt_num(row["interval_width"], 2),
            str(row["n_calib"]),
        ]
        for row in t3_conf["conformal"]
    ]
    current_conformal_models = current_conf.get("models", {})
    current_t3_conf = current_conformal_models.get("t3_iter47_stage2_current", {})
    current_t3_nocv_conf = current_conformal_models.get("t3_iter47_stage2_no_cv", {})
    current_t1_conf = current_conformal_models.get("t1_iter12_honest", {})
    current_t1_iter34_conf = current_conformal_models.get("t1_iter34_hybrid", {})
    current_conformal_rows = [
        [
            "T1 iter12 honest",
            fmt_num(current_t1_conf.get("base_ccc")),
            fmt_num(current_t1_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t1_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t1_conf.get("abstention_at_50pct_discard", {}).get("prediction_tail_distance_ccc")),
        ],
        [
            "T1 iter34 candidate",
            fmt_num(current_t1_iter34_conf.get("base_ccc")),
            fmt_num(current_t1_iter34_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t1_iter34_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t1_iter34_conf.get("abstention_at_50pct_discard", {}).get("prediction_tail_distance_ccc")),
        ],
        [
            "T3 iter47 current",
            fmt_num(current_t3_conf.get("base_ccc")),
            fmt_num(current_t3_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t3_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t3_conf.get("abstention_at_50pct_discard", {}).get("prediction_tail_distance_ccc")),
        ],
        [
            "T3 iter47 no-cv",
            fmt_num(current_t3_nocv_conf.get("base_ccc")),
            fmt_num(current_t3_nocv_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t3_nocv_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 2),
            fmt_num(current_t3_nocv_conf.get("abstention_at_50pct_discard", {}).get("prediction_tail_distance_ccc")),
        ],
    ]
    clinical_labels = {
        "a3_hy_cv": "A3 H&Y + intake",
        "hy_only": "H&Y only",
        "cv_only": "intake only",
        "intercept_only": "intercept / IMU-only",
    }
    clinical_rows = [
        [
            clinical_labels.get(policy, policy),
            fmt_num(row["mean_prediction_metrics"].get("ccc")),
            fmt_num(row["mean_prediction_metrics"].get("mae"), 3),
            fmt_num(row["mean_stage1_only_metrics"].get("ccc")),
            fmt_num(row["mean_stage1_only_metrics"].get("mae"), 3),
            str(row.get("n", "n/a")),
        ]
        for policy, row in t3_clinical_policies.items()
    ]

    t1_figures = [
        ("results/iter34_figures/fig1_oof_calibration_iter34.png", "T1 iter34 calibration"),
        ("results/iter34_figures/fig2_residual_by_quartile_iter34.png", "T1 residuals by quartile"),
        ("results/iter34_figures/fig3_per_subject_delta_iter34.png", "T1 per-subject delta"),
        ("results/iter35_visuals/fig02_residual_vs_true.png", "T1 residual vs true"),
        ("results/iter35_visuals/fig07_pearson_vs_ccc_decomposition.png", "T1 Pearson vs CCC"),
    ]
    t3_figures = [
        ("results/t3_iter5_deepdive/fig1_t3_iter5_calibration.png", "Historical T3 iter5 calibration"),
        ("results/t3_iter5_deepdive/fig2_t3_iter5_residual_quartiles.png", "Historical T3 residuals by quartile"),
        ("results/t3_iter5_deepdive/fig3_t3_iter5_site_loso_cliff.png", "Historical T3 site and LOSO cliff"),
        ("results/t3_iter5_deepdive/fig4_t3_iter5_conformal_abstention.png", "Historical T3 conformal and abstention"),
        ("results/t3_iter5_deepdive/fig5_t3_iter5_subject_errors.png", "Historical T3 subject errors"),
    ]

    artifact_rows = [
        [
            html.escape(a["role"]),
            f'<code>{html.escape(a["path"])}</code>',
            "yes" if a["exists"] else "no",
            str(a["bytes"] or ""),
            f'<code>{html.escape((a["sha256"] or "")[:12])}</code>',
        ]
        for a in artifacts
    ]

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "generated_at_utc": generated_at,
        "script": "visualize_current_best_pipeline.py",
        "outputs": {
            "html": str(OUT_HTML.relative_to(ROOT)),
            "manifest": str(OUT_MANIFEST.relative_to(ROOT)),
        },
        "headline": {
            "t1_canonical_floor": {
                "ccc": t1_floor.get("ccc"),
                "mae": t1_floor.get("mae"),
                "n": t1_floor.get("n"),
            },
            "t1_strongest_candidate_iter34": {
                "ccc": t1_best.get("ccc"),
                "mae": t1_best.get("mae"),
                "n": t1_best.get("n"),
                "audit_all_pass": t1_audit_verdict.get("all_pass"),
                "loso_two_way_mean_ccc": t1_loso.get("headline_two_way_mean_ccc"),
                "n93_gap_material": t1_n93_gap.get("verdict", {}).get("n93_gap_material"),
                "n94_grid_optimal_ccc": t1_n93_gap.get("one_subject_upper_bound", {}).get("metrics", {}).get("ccc"),
                "aux_validrange_caveat": {
                    "historical_chain_n": t1_aux_valid.get("current_loader", {}).get("chain_n"),
                    "validated_chain_n": t1_aux_valid.get("validated_loader", {}).get("chain_n"),
                    "affected_sids": t1_aux_deltas.get("current_chain_minus_validated_chain"),
                    "invalid_auxiliary_item": t1_aux_invalid,
                    "primary_t1_target_valid": t1_aux_valid.get("interpretation", {}).get("primary_t1_target_valid"),
                    "recommended_status": t1_aux_valid.get("interpretation", {}).get("recommended_status"),
                    "random_chain_order_exposure": t1_aux_order_summary,
                    "stale_vs_valid_common_delta_ccc": t1_aux_order_impact.get("delta_valid_minus_stale_common_ccc"),
                    "materiality_flag": t1_aux_order_impact.get("materiality_flag"),
                },
                "p2_leakage_signal": t1_p2_verdict.get("p2_leakage_signal"),
                "p2_robust_one_sided_pass": t1_p2_verdict.get("p2_robust_one_sided_pass"),
            },
            "t1_iter37_harnet_finetune_negative": {
                "mean_ccc": t1_iter37.get("mean_ccc"),
                "mean_mae": t1_iter37.get("mean_mae"),
                "min_fold_ccc": t1_iter37.get("min_fold_ccc"),
                "gate_pass": t1_iter37.get("feasibility_gate", {}).get("gate_pass"),
            },
            "t1_iter46_et_robustification_negative": {
                "ccc": t1_iter46.get("ccc"),
                "mae": t1_iter46.get("mae"),
                "n": t1_iter46.get("n"),
                "delta_vs_iter34": t1_iter46_vs_iter34.get("delta_new_minus_comparator"),
                "delta_vs_iter12": t1_iter46_vs_iter12.get("delta_new_minus_comparator"),
                "frac_above_iter12": t1_iter46_vs_iter12.get("bootstrap_delta", {}).get("frac_above_zero"),
                "et_screen_p2_bootstrap_high": t1_decomp_summary["combo_summary"]["et"]["p2_bootstrap_ci_high_max"],
                "decision": "diagnostic_only_not_canonical",
            },
            "t3_corrected_validrange_iter47": {
                "ccc": t3_current_metrics.get("ccc"),
                "mae": t3_current_metrics.get("mae"),
                "n": t3_current.get("n"),
                "stage2_no_cv_sensitivity_ccc": t3_nocv_metrics.get("ccc"),
                "stage2_no_dst_sensitivity_ccc": t3_dst_nodst.get("ccc"),
                "stage2_no_dst_sensitivity_mae": t3_dst_nodst.get("mae"),
                "stage2_no_dst_delta_mean": t3_dst_comp.get("mean_delta"),
                "stage2_no_dst_delta_ci95": t3_dst_comp.get("ci95"),
                "loso_two_way_mean_ccc": t3_loso_current.get("two_way_mean_ccc"),
                "loso_NLS_to_WPD_ccc": t3_loso_current.get("NLS_to_WPD_mean_ccc"),
                "loso_WPD_to_NLS_ccc": t3_loso_current.get("WPD_to_NLS_mean_ccc"),
                "target_change_subjects": t3_current.get("target_change_subjects"),
                "dst_walkway_distiller_caveat": "31 non-fold-local dst_* columns are included by current V2 filters; no-dst sensitivity is non-material but should be disclosed.",
                "residual_anatomy": {
                    "scope": t3_iter47_residual_anatomy.get("scope"),
                    "decision": t3_iter47_residual_anatomy.get("decision"),
                    "residual_corr_with_true": t3_resid_overall.get("residual_corr_with_true"),
                    "cal_slope_pred_on_true": t3_resid_overall.get("cal_slope_pred_on_true"),
                    "q1_mean_residual": t3_resid_quartiles.get("Q1_low", {}).get("mean_residual_pred_minus_true"),
                    "q4_mean_residual": t3_resid_quartiles.get("Q4_high", {}).get("mean_residual_pred_minus_true"),
                    "wpd_within_site_ccc": t3_resid_sites.get("WPD", {}).get("ccc"),
                    "top_global_posthoc_residual_feature_abs_r": t3_resid_top_feature.get("abs_corr_with_residual"),
                    "top_global_posthoc_residual_feature": t3_resid_top_feature.get("feature"),
                },
                "item_residual_audit": {
                    "scope": t3_item_residual.get("scope"),
                    "decision": t3_item_residual.get("decision"),
                    "target_reconstruction": t3_item_residual.get("target_reconstruction"),
                    "top_residual_item": item_top_residual,
                    "top_privileged_oracle_item": item_top_oracle,
                    "observable_vs_unobservable_summary": item_observable,
                },
                "ccc_rescale_sanity": {
                    "scope": t3_iter47_ccc_rescale.get("scope"),
                    "methodology_guardrail": t3_iter47_ccc_rescale.get("methodology_guardrail"),
                    "decision": t3_iter47_ccc_rescale.get("decision"),
                    "base_ccc": t3_rescale_base.get("ccc"),
                    "base_mae": t3_rescale_base.get("mae"),
                    "variance_match_ccc": t3_rescale_variance_metrics.get("ccc"),
                    "variance_match_mae": t3_rescale_variance_metrics.get("mae"),
                    "variance_match_ccc_delta_mean": t3_rescale_variance_boot.get("ccc_delta_mean"),
                    "variance_match_ccc_delta_ci95": t3_rescale_variance_boot.get("ccc_delta_ci95"),
                    "variance_match_mae_delta_mean": t3_rescale_variance_boot.get("mae_delta_mean"),
                    "variance_match_mae_delta_ci95": t3_rescale_variance_boot.get("mae_delta_ci95"),
                },
                "headline_influence": {
                    "decision": headline_influence.get("decision"),
                    "t3_leave_one_ccc_min": influence_t3_jack.get("ccc_without_min"),
                    "t3_leave_one_ccc_max": influence_t3_jack.get("ccc_without_max"),
                    "t3_top1_abs_delta_ccc": influence_t3_conc.get("top1_abs_delta_ccc"),
                    "t3_top5_fraction_of_sum_abs_delta": influence_t3_conc.get("top5_fraction_of_sum_abs_delta"),
                    "t3_gini_abs_delta_ccc": influence_t3_conc.get("gini_abs_delta_ccc"),
                    "t3_abs_target_minus_median_vs_abs_delta_ccc": influence_t3_corr.get("abs_target_minus_median_vs_abs_delta_ccc"),
                    "t1_iter34_minus_iter12_leave_one_delta_min": influence_t1_matched.get("leave_one_delta_min"),
                    "t1_iter34_leave_one_ccc_min": influence_t1_matched.get("iter34_leave_one_ccc_min"),
                },
                "ablation_v3_cache_provenance": {
                    "cache_sha256": ablation_v3_provenance.get("cache", {}).get("sha256"),
                    "manifest_status": ablation_v3_provenance.get("manifest_validation", {}).get("status"),
                    "decision": ablation_v3_provenance.get("decision", {}).get("decision"),
                    "selected_columns": ablation_v3_provenance.get("schema_evidence", {}).get("current_v2_filter", {}).get("selected_columns"),
                    "selected_dst": ablation_v3_provenance.get("schema_evidence", {}).get("current_v2_filter", {}).get("prefix_counts_selected", {}).get("dst_"),
                    "selected_cv": ablation_v3_provenance.get("schema_evidence", {}).get("current_v2_filter", {}).get("prefix_counts_selected", {}).get("cv_"),
                },
                "ablation_v3_regeneration_probe": {
                    "status": ablation_v3_regeneration.get("status"),
                    "frozen_cache_unchanged": ablation_v3_regeneration.get("frozen_cache_unchanged"),
                    "missing_inputs": ablation_v3_regeneration.get("input_status", {}).get("missing"),
                    "promotion_decision": ablation_v3_regeneration.get("promotion_decision"),
                },
                "weargait_missing_synapse_recovery_preflight": {
                    "status": synapse_recovery.get("status"),
                    "missing": synapse_recovery.get("missing"),
                    "credential_status": synapse_recovery.get("credential_status"),
                    "control_csv_synapse_count": synapse_recovery.get("entities", {}).get("control_csv_folder", {}).get("synapse_probe", {}).get("csv_children_count"),
                },
            },
            "t3_historical_iter5_target_contaminated": {
                "ccc": t3_old.get("ccc"),
                "mae": t3_old.get("mae"),
                "n": t3_old.get("n"),
                "residual_corr_with_true": t3_deep.get("residual_corr_with_true"),
                "loso_two_way_mean_ccc": t3_deep["loso"].get("two_way_mean"),
                "target_audit_all_missing_zero_labels": t3_audit.get("target_summary", {}).get("missing_raw_part3_subitems_among_v2_pd", {}).get("missing_count_hist", {}).get("33"),
            },
            "t3_iter42_prorate_negative": {
                "primary_prorate_le3_current_ccc": t3_iter42_cells[("prorate_le3", "stage2_current")]["new_refit_metrics"].get("ccc"),
                "primary_prorate_le3_no_cv_ccc": t3_iter42_cells[("prorate_le3", "stage2_no_cv")]["new_refit_metrics"].get("ccc"),
                "primary_prorate_le3_loso_two_way": t3_iter42_loso_cells[("prorate_le3", "stage2_current")].get("two_way_mean_ccc"),
                "sensitivity_prorate_le7_current_ccc": t3_iter42_cells[("prorate_le7", "stage2_current")]["new_refit_metrics"].get("ccc"),
                "sensitivity_prorate_le7_loso_two_way": t3_iter42_loso_cells[("prorate_le7", "stage2_current")].get("two_way_mean_ccc"),
                "decision": "primary_le3_failed_loose_le7_sensitivity_not_promotable",
            },
            "t3_clinical_dependency_audit": {
                "stage2_policy": t3_clinical.get("stage2_policy"),
                "a3_hy_cv_ccc": t3_clinical_policies["a3_hy_cv"]["mean_prediction_metrics"].get("ccc"),
                "cv_only_ccc": t3_clinical_policies["cv_only"]["mean_prediction_metrics"].get("ccc"),
                "hy_only_ccc": t3_clinical_policies["hy_only"]["mean_prediction_metrics"].get("ccc"),
                "intercept_only_imu_only_ccc": t3_clinical_policies["intercept_only"]["mean_prediction_metrics"].get("ccc"),
                "a3_minus_cv_only": t3_clinical.get("comparisons_vs_a3_hy_cv", {}).get("a3_hy_cv_minus_cv_only"),
                "canonical_t3_changed": t3_clinical.get("verdict", {}).get("canonical_t3_changed"),
            },
            "current_conformal_abstention": {
                "t1_iter12_width80": current_t1_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"),
                "t1_iter12_width95": current_t1_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"),
                "t1_iter34_width80": current_t1_iter34_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"),
                "t1_iter34_width95": current_t1_iter34_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"),
                "t3_iter47_current_width80": current_t3_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"),
                "t3_iter47_current_width95": current_t3_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"),
                "t3_iter47_current_deployable_50pct_ccc": current_t3_conf.get("abstention_at_50pct_discard", {}).get("prediction_tail_distance_ccc"),
                "verdict": current_conf.get("verdict"),
            },
            "t3_iter38_fogstar_stage1_negative": {
                "baseline_seed_mean_ccc": t3_iter38.get("baseline_seed_mean", {}).get("ccc"),
                "augmented_seed_mean_ccc": t3_iter38.get("augmented_seed_mean", {}).get("ccc"),
                "delta_seed_mean_predictions": t3_iter38.get("delta_seed_mean_predictions"),
                "gate_pass": t3_iter38.get("gate", {}).get("pass"),
            },
            "t3_iter39_fogstar_zeroshot_partial": {
                "track_a_wrist_direct_ccc": t3_iter39.get("track_a_wg_wrist_direct", {}).get("ccc"),
                "track_b_clinical_plus_wrist_ccc": t3_iter39.get("track_b_iter5_style_clinical_plus_wrist", {}).get("ccc"),
                "track_c_fogstar_only_loo_ccc": t3_iter39.get("track_c_fogstar_only_loo_sanity", {}).get("ccc"),
                "decision": t3_iter39.get("decision"),
            },
            "t3_iter40_local_residual_negative": {
                "baseline_seed_mean_ccc": t3_iter40.get("baseline_metrics_seed_mean", {}).get("ccc"),
                "wildcard_seed_mean_ccc": t3_iter40.get("wildcard_metrics_seed_mean", {}).get("ccc"),
                "delta_ccc": t3_iter40.get("seed_mean_delta_ccc"),
                "strict_gate_pass": t3_iter40.get("promotion_gate", {}).get("strict_t3_gate_pass"),
            },
            "t3_iter50_lowdf_convex_negative": {
                "formula_sha256": t3_iter50.get("formula_sha256"),
                "baseline_ccc": t3_iter50.get("mean_metrics", {}).get("baseline_seq_current", {}).get("ccc"),
                "clinical_only_ccc": t3_iter50.get("mean_metrics", {}).get("clinical_only", {}).get("ccc"),
                "imu_only_no_cv_ccc": t3_iter50.get("mean_metrics", {}).get("imu_only_no_cv", {}).get("ccc"),
                "nested_convex_ccc": t3_iter50.get("mean_metrics", {}).get("nested_convex", {}).get("ccc"),
                "delta_seed_mean_predictions": t3_iter50.get("gate", {}).get("delta_seed_mean_predictions"),
                "seed_delta_std": t3_iter50.get("gate", {}).get("seed_delta_std"),
                "strict_gate_pass": t3_iter50.get("gate", {}).get("strict_t3_gate_pass"),
                "bootstrap_frac_gt_0": t3_iter50.get("bootstrap_nested_convex_minus_baseline", {}).get("frac_gt_0"),
                "alpha_summary": t3_iter50.get("alpha_summary"),
                "decision": t3_iter50.get("decision"),
            },
            "t3_iter49_cops_zeroshot_partial_external": {
                "formula_sha256": t3_iter49.get("preregistration_formula_sha256"),
                "n_probe_zip_records": t3_iter49_probe.get("data_summary", {}).get("n_zip_files"),
                "total_probe_zip_size_bytes": t3_iter49_probe.get("data_summary", {}).get("total_zip_size_bytes"),
                "demographics_rows": t3_iter49_probe.get("demographics", {}).get("n_rows"),
                "n_weargait_train": t3_iter49.get("n_weargait_train"),
                "n_cops_rows_total": t3_iter49.get("n_cops_rows_total"),
                "n_cops_off_labeled": t3_iter49.get("n_cops_off_labeled"),
                "n_common_magnitude_features": t3_iter49.get("n_common_magnitude_features"),
                "track_a_right_wrist_direct_ccc": t3_iter49_track_a.get("ccc"),
                "track_b_right_clinical_plus_wrist_ccc": t3_iter49_track_b.get("ccc"),
                "track_d_bilateral_clinical_plus_wrist_ccc": t3_iter49_track_d.get("ccc"),
                "track_c_cops_only_loo_ccc": t3_iter49_track_c.get("ccc"),
                "scale_checks": t3_iter49.get("scale_checks"),
                "decision": t3_iter49.get("decision"),
            },
            "tlvmc_defog_route_probe": {
                "record_id": tlvmc_probe.get("zenodo", {}).get("record_id"),
                "doi": tlvmc_probe.get("zenodo", {}).get("doi"),
                "license": tlvmc_probe.get("zenodo", {}).get("license"),
                "row_level_metadata_persisted_in_repo": tlvmc_probe.get("row_level_metadata_persisted_in_repo"),
                "unique_subjects_with_updrsiii": tlvmc_probe.get("subjects", {}).get("unique_subjects_with_any_updrsiii_target"),
                "subject_visit_rows": tlvmc_probe.get("subjects", {}).get("rows"),
                "updrsiii_on_n": tlvmc_probe.get("subjects", {}).get("updrsiii_on", {}).get("n"),
                "updrsiii_off_n": tlvmc_probe.get("subjects", {}).get("updrsiii_off", {}).get("n"),
                "defog_recordings": tlvmc_probe.get("recording_metadata", {}).get("defog", {}).get("rows"),
                "defog_subjects": tlvmc_probe.get("recording_metadata", {}).get("defog", {}).get("unique_subjects"),
                "defog_subject_visits": tlvmc_probe.get("recording_metadata", {}).get("defog", {}).get("unique_subject_visits"),
                "defog_medication_matched_targets": tlvmc_probe.get("recording_metadata", {}).get("defog", {}).get("rows_with_matching_medication_updrsiii_target"),
                "daily_visit_level_targets": tlvmc_probe.get("recording_metadata", {}).get("daily", {}).get("rows_with_any_updrsiii_target"),
                "tdcsfog_joined_targets": tlvmc_probe.get("recording_metadata", {}).get("tdcsfog", {}).get("rows_with_any_updrsiii_target"),
                "preregistration_formula_sha256": tlvmc_prereg.get("formula_sha256"),
                "preregistration_created_at_utc": tlvmc_prereg.get("created_at_utc"),
                "primary_expected_n_records": tlvmc_prereg.get("formula", {}).get("fixed_battery", {}).get("primary_external_target", {}).get("expected_n_records"),
                "primary_expected_n_subjects": tlvmc_prereg.get("formula", {}).get("fixed_battery", {}).get("primary_external_target", {}).get("expected_n_subjects"),
                "primary_track": "A_zero_shot_lumbar_acc_magnitude",
                "decision": "public_direct_t3_route_preregistered_and_modeled_external_only",
            },
            "tlvmc_defog_iter51_zeroshot_partial_external": {
                "decision": tlvmc_iter51.get("decision"),
                "preregistration_formula_sha256": tlvmc_iter51.get("preregistration_formula_sha256"),
                "n_defog_rows": tlvmc_iter51.get("n_defog_rows"),
                "n_defog_subjects": tlvmc_iter51.get("n_defog_subjects"),
                "n_defog_off_rows": tlvmc_iter51.get("n_defog_off_rows"),
                "n_defog_on_rows": tlvmc_iter51.get("n_defog_on_rows"),
                "n_common_magnitude_features": tlvmc_iter51.get("n_common_magnitude_features"),
                "track_a_mean_off_ccc": tlvmc_track_a.get("ccc"),
                "track_a_mean_off_ci95": tlvmc_track_a.get("ccc_ci95"),
                "track_a_mean_off_mae": tlvmc_track_a.get("mae"),
                "track_b_mean_off_ccc": tlvmc_track_b.get("ccc"),
                "track_c_defog_only_loso_ccc": tlvmc_track_c.get("ccc"),
                "interpretation": tlvmc_iter51.get("interpretation"),
            },
            "pdfe_turning_iter52_zeroshot_external": {
                "decision": pdfe_iter52.get("policy", {}).get("decision"),
                "formula_sha256": pdfe_iter52.get("formula_sha256"),
                "preregistration_formula_sha256": pdfe_prereg.get("formula_sha256"),
                "n_metadata_rows": pdfe_probe.get("n_metadata_rows"),
                "n_session1_targets": pdfe_probe.get("n_session1_targets"),
                "n_weargait_train": pdfe_iter52.get("n_weargait_train"),
                "n_pdfe": pdfe_iter52.get("n_pdfe"),
                "n_common_magnitude_features": pdfe_iter52.get("n_common_magnitude_features"),
                "track_a_weargait_shank_to_pdfe_ccc": pdfe_track_a.get("ccc"),
                "track_a_weargait_shank_to_pdfe_ci95": [
                    pdfe_track_a.get("ccc_bootstrap", {}).get("ci95_low"),
                    pdfe_track_a.get("ccc_bootstrap", {}).get("ci95_high"),
                ],
                "track_b_clinical_plus_shank_ccc": pdfe_track_b.get("ccc"),
                "track_b_clinical_plus_shank_ci95": [
                    pdfe_track_b.get("ccc_bootstrap", {}).get("ci95_low"),
                    pdfe_track_b.get("ccc_bootstrap", {}).get("ci95_high"),
                ],
                "track_c_pdfe_only_loocv_ccc": pdfe_track_c.get("ccc"),
                "track_c_pdfe_only_loocv_ci95": [
                    pdfe_track_c.get("ccc_bootstrap", {}).get("ci95_low"),
                    pdfe_track_c.get("ccc_bootstrap", {}).get("ci95_high"),
                ],
                "interpretation": "external-validity evidence only; no internal WearGait-PD T3 canonical change",
            },
            "luxembourg_upper_limb_route_refresh": {
                "decision": luxembourg_upper_limb_refresh.get("decision"),
                "status": luxembourg_upper_limb_refresh.get("status"),
                "route": luxembourg_upper_limb_refresh.get("route"),
                "consults": luxembourg_upper_limb_refresh.get("consults"),
                "interpretation": "document-only upper-limb subitem observability context; no runbook, scaffold, preregistration, download, or remote job",
            },
            "prequantipark_route_refresh": {
                "decision": prequantipark_refresh.get("decision"),
                "status": prequantipark_refresh.get("status"),
                "route": prequantipark_refresh.get("route"),
                "n_pd": prequantipark_refresh.get("n_pd"),
                "consults": prequantipark_refresh.get("consults"),
                "interpretation": "document-only levodopa-challenge context; N=10/request-only/schema-hidden, no runbook, scaffold, preregistration, download, or remote job",
            },
            "tum_rocket_inception_route_refresh": {
                "decision": tum_rocket_inception_refresh.get("decision"),
                "status": tum_rocket_inception_refresh.get("status"),
                "route": tum_rocket_inception_refresh.get("route"),
                "n_pd": tum_rocket_inception_refresh.get("n_pd"),
                "underlying_data_route": tum_rocket_inception_refresh.get("underlying_data_route"),
                "consults": tum_rocket_inception_refresh.get("consults"),
                "interpretation": "document-only alias to the Hssayeni/MJFF DUA gate and already-negative ROCKET/InceptionTime-style local routes; no clone, scaffold, preregistration, download, or remote job",
            },
            "paradigma_yin_route_refresh": {
                "routes": [
                    {
                        "name": route.get("name"),
                        "decision": route.get("decision"),
                        "status": route.get("status"),
                        "direct_t1_t3_eligible": route.get("direct_t1_t3_eligible"),
                        "n_pd": route.get("n_pd"),
                    }
                    for route in paradigma_yin_refresh.get("routes", [])
                ],
                "consults": paradigma_yin_refresh.get("consults"),
                "interpretation": "document-only route refresh; ParaDigMa is software-only local feature fishing and Yin et al is request-only/small-N/schema-hidden",
            },
            "parkinsonathome_route_refresh": {
                "decision": parkinsonathome_refresh.get("decision"),
                "status": parkinsonathome_refresh.get("status"),
                "direct_t1_t3_eligible": parkinsonathome_refresh.get("direct_t1_t3_eligible"),
                "hard_stop": parkinsonathome_refresh.get("hard_stop"),
                "n_pd_off_valid_target_rows": parkinsonathome_refresh.get("probe", {}).get("n_pd_off_valid_target_rows"),
                "n_feature_readable_off_subjects": parkinsonathome_refresh.get("extraction", {}).get("n_pre_valid_target_subjects"),
                "consults": parkinsonathome_refresh.get("consults"),
                "interpretation": "public direct T3 route that hard-stopped before scoring at N=18 vs the preregistered N>=20 feature-readability rule; no metric or internal canonical update",
            },
            "kimi_next_action_after_parkinsonathome": {
                "created_at_utc": kimi_next_action.get("created_at_utc"),
                "model_action_justified": kimi_next_action.get("recommendation", {}).get("model_action_justified"),
                "single_next_non_redundant_action": kimi_next_action.get("recommendation", {}).get("single_next_non_redundant_action"),
                "runbook": kimi_next_action.get("recommendation", {}).get("runbook"),
                "fallback": kimi_next_action.get("recommendation", {}).get("fallback_if_ppmi_already_pending"),
                "interpretation": "advisor decision artifact; no local model action is justified, and the next non-redundant action is user/data-owner access for PPMI/Verily before any read-only schema probe",
            },
        },
        "artifacts": artifacts,
        "canonical_claim_consistency_audit": {
            "passed": canonical_claim_audit.get("passed"),
            "stale_findings": len(canonical_claim_audit.get("stale_findings", [])),
            "missing_required_snippets": len(canonical_claim_audit.get("missing_required_snippets", [])),
        },
        "headline_metric_recompute_audit": {
            "passed": metric_recompute_audit.get("passed"),
            "checks": len(metric_recompute_audit.get("checks", [])),
            "tolerance": metric_recompute_audit.get("tolerance"),
        },
        "ccc_metric_integrity_audit": {
            "passed": ccc_metric_audit.get("passed"),
            "headline_checks": len(ccc_metric_audit.get("headline_checks", [])),
            "implementation_checks": len(ccc_metric_audit.get("implementation_checks", [])),
            "max_abs_sample_minus_population_headline": ccc_metric_audit.get("max_abs_sample_minus_population_headline"),
            "warnings": len(ccc_metric_audit.get("warnings", [])),
        },
        "oof_artifact_integrity_audit": {
            "passed": oof_integrity_audit.get("passed"),
            "checks": len(oof_integrity_audit.get("checks", [])),
            "max_abs_diff_max": max(
                (check.get("max_abs_diff") or 0.0 for check in oof_integrity_audit.get("checks", [])),
                default=None,
            ),
        },
        "cache_dependency_audits": {
            "cache_manifest_status": {
                "status_counts": cache_manifest_audit.get("status_counts"),
                "headline_safe_artifacts": cache_manifest_audit.get("headline_safe_artifacts"),
            },
            "partial_manifest_backfill_candidates": {
                "counts": cache_backfill_candidates.get("counts"),
            },
            "missing_manifest_origin_audit": {
                "n_missing_manifests": missing_cache_origin_audit.get("n_missing_manifests"),
                "decision_counts": missing_cache_origin_audit.get("decision_counts"),
                "policy": missing_cache_origin_audit.get("policy"),
            },
            "manual_missing_manifest_backfill_evidence": {
                "n_candidates": manual_cache_backfill_evidence.get("n_candidates"),
                "decision_counts": manual_cache_backfill_evidence.get("decision_counts"),
                "remote_recovery_probe": manual_cache_backfill_evidence.get("remote_recovery_probe"),
            },
            "cache_consumer_guard": {
                "classification_counts": cache_consumer_audit.get("classification_counts"),
                "current_guarded_consumers": cache_consumer_audit.get("current_guarded_consumers"),
                "diagnostic_only_model_consumers": len(cache_consumer_audit.get("diagnostic_only_model_consumers", [])),
            },
            "transitive_import_closure": {
                "classification_counts": transitive_cache_audit.get("classification_counts"),
                "entrypoints": transitive_cache_audit.get("entrypoints"),
                "direct_diagnostic_entrypoints": transitive_cache_audit.get("direct_diagnostic_entrypoints"),
            },
            "runtime_cache_reads": {
                "target_count": len(runtime_cache_audit.get("target_reports", [])),
                "opened_diagnostic_or_partial_cache_artifacts": runtime_cache_audit.get("opened_diagnostic_or_partial_cache_artifacts"),
                "method": runtime_cache_audit.get("method"),
            },
        },
        "t3_iter47_target_integrity_audit": {
            "passed": t3_iter47_target_integrity.get("pass"),
            "hard_failures": len(t3_iter47_target_integrity.get("hard_failures", [])),
            "warnings": len(t3_iter47_target_integrity.get("warnings", [])),
            "minimal_n": t3_iter47_target_integrity.get("cohorts", {}).get("drop_allmissing_validrange", {}).get("n"),
            "complete33_n": t3_iter47_target_integrity.get("cohorts", {}).get("complete33_validrange", {}).get("n"),
            "invalid_raw_values": len(t3_iter47_target_integrity.get("target", {}).get("invalid_raw_subitem_values", [])),
            "target_changed_rows": len(t3_iter47_target_integrity.get("target", {}).get("target_changed_rows", [])),
        },
        "t3_complete33_claim_labeling_audit": {
            "passed": t3_complete33_labeling_audit.get("passed"),
            "findings": len(t3_complete33_labeling_audit.get("findings", [])),
            "missing_required_snippets": len(t3_complete33_labeling_audit.get("missing_required_snippets", [])),
            "docs": [doc.get("path") for doc in t3_complete33_labeling_audit.get("docs", [])],
        },
        "external_result_claim_labeling_audit": {
            "passed": external_result_labeling_audit.get("passed"),
            "findings": len(external_result_labeling_audit.get("findings", [])),
            "missing_required_snippets": len(external_result_labeling_audit.get("missing_required_snippets", [])),
            "artifact_failures": len(external_result_labeling_audit.get("artifact_failures", [])),
            "artifact_checks": [row.get("path") for row in external_result_labeling_audit.get("artifact_checks", [])],
            "docs": [doc.get("path") for doc in external_result_labeling_audit.get("docs", [])],
        },
        "remaining_blocker_action_audit": {
            "passed": remaining_blocker_action_audit.get("passed"),
            "source_blocker_count": remaining_blocker_action_audit.get("source_blocker_count"),
            "local_model_actions": len(remaining_blocker_action_audit.get("local_model_actions", [])),
            "unmatched_blockers": len(remaining_blocker_action_audit.get("unmatched_blockers", [])),
            "action_type_counts": remaining_blocker_action_audit.get("action_type_counts"),
            "recommended_next_actions": remaining_blocker_action_audit.get("recommended_next_actions"),
        },
        "external_access_readiness_audit": {
            "passed": external_access_readiness.get("summary", {}).get("passed"),
            "route_count": external_access_readiness.get("summary", {}).get("route_count"),
            "application_packet_ready_count": external_access_readiness.get("summary", {}).get("application_packet_ready_count"),
            "compute_ready_route_count": external_access_readiness.get("summary", {}).get("compute_ready_route_count"),
            "top_priority_route": external_access_readiness.get("summary", {}).get("top_priority_route"),
            "hard_failure_count": external_access_readiness.get("summary", {}).get("hard_failure_count"),
            "warning_count": external_access_readiness.get("summary", {}).get("warning_count"),
            "decision": external_access_readiness.get("decision"),
        },
        "access_submission_tracker": {
            "passed": access_submission_tracker.get("summary", {}).get("passed"),
            "decision": access_submission_tracker.get("decision"),
            "submit_ready_route_count": access_submission_tracker.get("summary", {}).get("submit_ready_route_count"),
            "compute_ready_route_count": access_submission_tracker.get("summary", {}).get("compute_ready_route_count"),
            "hard_failure_count": access_submission_tracker.get("summary", {}).get("hard_failure_count"),
            "top_priority_route": access_submission_tracker.get("summary", {}).get("top_priority_route"),
        },
        "recent_external_web_leads": {
            "decision": recent_external_web_leads.get("decision"),
            "routes_checked": recent_external_web_leads.get("summary", {}).get("routes_checked"),
            "new_compute_ready_routes": recent_external_web_leads.get("summary", {}).get("new_compute_ready_routes"),
            "new_scaffold_or_preregistration_actions": recent_external_web_leads.get("summary", {}).get("new_scaffold_or_preregistration_actions"),
            "master_routes_changed": recent_external_web_leads.get("summary", {}).get("master_routes_changed"),
            "already_present_routes": recent_external_web_leads.get("summary", {}).get("already_present_routes"),
        },
        "ppmi_verily_request_packet_audit": {
            "passed": ppmi_packet_audit.get("passed"),
            "decision": ppmi_packet_audit.get("decision"),
            "packet": ppmi_packet_audit.get("packet"),
            "hard_failures": len(ppmi_packet_audit.get("hard_failures", [])),
            "checks": len(ppmi_packet_audit.get("checks", {})),
            "missing": len(ppmi_packet_audit.get("missing", [])),
        },
        "ppp_pd_vme_request_packet_audit": {
            "passed": ppp_packet_audit.get("passed"),
            "decision": ppp_packet_audit.get("decision"),
            "packet": ppp_packet_audit.get("packet"),
            "hard_failures": len(ppp_packet_audit.get("hard_failures", [])),
            "checks": len(ppp_packet_audit.get("checks", {})),
            "missing": len(ppp_packet_audit.get("missing", [])),
        },
        "watchpd_request_packet_audit": {
            "passed": watchpd_packet_audit.get("passed"),
            "decision": watchpd_packet_audit.get("decision"),
            "packet": watchpd_packet_audit.get("packet"),
            "hard_failures": len(watchpd_packet_audit.get("hard_failures", [])),
            "checks": len(watchpd_packet_audit.get("checks", {})),
            "missing": len(watchpd_packet_audit.get("missing", [])),
        },
        "cns_portugal_request_packet_audit": {
            "passed": cns_packet_audit.get("passed"),
            "decision": cns_packet_audit.get("decision"),
            "packet": cns_packet_audit.get("packet"),
            "hard_failures": len(cns_packet_audit.get("hard_failures", [])),
            "checks": len(cns_packet_audit.get("checks", {})),
            "missing": len(cns_packet_audit.get("missing", [])),
        },
        "hssayeni_mjff_dua_request_packet_audit": {
            "passed": hssayeni_packet_audit.get("passed"),
            "decision": hssayeni_packet_audit.get("decision"),
            "packet": hssayeni_packet_audit.get("packet"),
            "hard_failures": len(hssayeni_packet_audit.get("hard_failures", [])),
            "checks": len(hssayeni_packet_audit.get("checks", {})),
            "missing": len(hssayeni_packet_audit.get("missing", [])),
        },
        "icicle_request_packet_audit": {
            "passed": icicle_packet_audit.get("passed"),
            "decision": icicle_packet_audit.get("decision"),
            "packet": icicle_packet_audit.get("packet"),
            "hard_failures": len(icicle_packet_audit.get("hard_failures", [])),
            "checks": len(icicle_packet_audit.get("checks", {})),
            "missing": len(icicle_packet_audit.get("missing", [])),
        },
        "weargait_raw_data_recovery_runbook_audit": {
            "passed": raw_data_recovery_runbook_audit.get("passed"),
            "decision": raw_data_recovery_runbook_audit.get("decision"),
            "preflight_status": raw_data_recovery_runbook_audit.get("current_status", {}).get("preflight_status"),
            "credentials_present": raw_data_recovery_runbook_audit.get("current_status", {}).get("credentials_present"),
            "regeneration_probe_status": raw_data_recovery_runbook_audit.get("current_status", {}).get("regeneration_probe_status"),
            "hard_failures": len(raw_data_recovery_runbook_audit.get("hard_failures", [])),
            "warnings": len(raw_data_recovery_runbook_audit.get("warnings", [])),
        },
        "task_plan_current_scope_audit": {
            "passed": task_plan_current_scope_audit.get("passed"),
            "decision": task_plan_current_scope_audit.get("decision"),
            "historical_boundary_line": task_plan_current_scope_audit.get("historical_boundary", {}).get("line"),
            "current_scope_lines": task_plan_current_scope_audit.get("current_scope", {}).get("line_count"),
            "archive_scope_lines": task_plan_current_scope_audit.get("archive_scope", {}).get("line_count"),
            "hard_failures": len(task_plan_current_scope_audit.get("hard_failures", [])),
            "legacy_success_findings": len(task_plan_current_scope_audit.get("current_scope", {}).get("legacy_success_findings", [])),
        },
        "paper_generator_routing_audit": {
            "passed": paper_generator_routing_audit.get("passed"),
            "decision": paper_generator_routing_audit.get("decision"),
            "hard_failures": len(paper_generator_routing_audit.get("hard_failures", [])),
            "active_doc_count": len(paper_generator_routing_audit.get("active_docs", [])),
            "current_renderer_status": paper_generator_routing_audit.get("current_renderer", {}).get("manifest", {}).get("status"),
            "current_renderer_validation_issues": len(
                paper_generator_routing_audit.get("current_renderer", {}).get("manifest", {}).get("validation_issues", [])
            ),
            "legacy_new4_transductive_hits": paper_generator_routing_audit.get("legacy_generator", {}).get("stale_phrase_counts", {}).get("new4_html_transductive"),
        },
        "readme_claim_routing_audit": {
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
        "t3_iter47_ccc_rescale_sanity": {
            "scope": t3_iter47_ccc_rescale.get("scope"),
            "not_fully_nested": t3_iter47_ccc_rescale.get("methodology_guardrail", {}).get("not_fully_nested"),
            "no_model_promotion": t3_iter47_ccc_rescale.get("decision", {}).get("no_model_promotion"),
            "base_ccc": t3_rescale_base.get("ccc"),
            "variance_match_ccc": t3_rescale_variance_metrics.get("ccc"),
            "variance_match_mae": t3_rescale_variance_metrics.get("mae"),
            "variance_match_bootstrap": t3_rescale_variance_boot,
        },
        "current_headline_influence_audit": {
            "decision": headline_influence.get("decision"),
            "t3_leave_one_ccc_min": influence_t3_jack.get("ccc_without_min"),
            "t3_leave_one_ccc_max": influence_t3_jack.get("ccc_without_max"),
            "t3_top1_abs_delta_ccc": influence_t3_conc.get("top1_abs_delta_ccc"),
            "t3_top5_fraction_of_sum_abs_delta": influence_t3_conc.get("top5_fraction_of_sum_abs_delta"),
            "t3_gini_abs_delta_ccc": influence_t3_conc.get("gini_abs_delta_ccc"),
            "t3_abs_target_minus_median_vs_abs_delta_ccc": influence_t3_corr.get("abs_target_minus_median_vs_abs_delta_ccc"),
            "t1_iter34_minus_iter12_leave_one_delta_min": influence_t1_matched.get("leave_one_delta_min"),
            "t1_iter34_leave_one_ccc_min": influence_t1_matched.get("iter34_leave_one_ccc_min"),
        },
        "t3_iter47_domain_residual_audit": {
            "decision": t3_domain_residual.get("decision"),
            "parsed_total_max_abs_diff_vs_iter47_target": t3_domain_residual.get("guardrails", {}).get("parsed_total_max_abs_diff_vs_iter47_target"),
            "unobservable_non_gait_residual_r": domain_unobs.get("corr_domain_with_residual_pred_minus_true"),
            "unobservable_non_gait_oracle_delta_ccc": domain_unobs.get("oracle_delta_ccc_vs_base"),
            "upper_limb_brady_residual_r": domain_upper.get("corr_domain_with_residual_pred_minus_true"),
            "upper_limb_brady_oracle_delta_ccc": domain_upper.get("oracle_delta_ccc_vs_base"),
            "gait_balance_residual_r": domain_gait.get("corr_domain_with_residual_pred_minus_true"),
            "gait_balance_oracle_delta_ccc": domain_gait.get("oracle_delta_ccc_vs_base"),
            "multidomain_privileged_oracle_ccc": domain_multi.get("metrics", {}).get("ccc"),
            "multidomain_privileged_oracle_delta_ccc": domain_multi.get("delta_ccc_vs_base"),
        },
        "t3_iter47_item_residual_audit": {
            "scope": t3_item_residual.get("scope"),
            "no_model_promotion": t3_item_residual.get("decision", {}).get("no_model_promotion"),
            "target_reconstruction_max_abs_diff": t3_item_residual.get("target_reconstruction", {}).get("max_abs_parsed_total_minus_iter47_target"),
            "top_residual_item": item_top_residual,
            "top_privileged_oracle_item": item_top_oracle,
            "mean_abs_residual_corr_observable": item_observable.get("mean_abs_residual_corr_observable"),
            "mean_abs_residual_corr_unobservable": item_observable.get("mean_abs_residual_corr_unobservable"),
            "best_observable_oracle_delta_ccc": item_observable.get("best_observable_oracle_delta_ccc"),
            "best_unobservable_oracle_delta_ccc": item_observable.get("best_unobservable_oracle_delta_ccc"),
        },
        "preregistration_temporal_integrity_audit": {
            "passed": prereg_temporal_audit.get("passed"),
            "checks": len(prereg_temporal_audit.get("checks", [])),
            "warnings": len(prereg_temporal_audit.get("warnings", [])),
            "hard_failures": len(prereg_temporal_audit.get("hard_failures", [])),
        },
        "pre_audit_claim_labeling_audit": {
            "passed": pre_audit_labeling_audit.get("passed"),
            "findings": len(pre_audit_labeling_audit.get("findings", [])),
            "docs": [doc.get("path") for doc in pre_audit_labeling_audit.get("docs", [])],
        },
        "historical_subdomain_claim_labeling_audit": {
            "passed": historical_subdomain_labeling_audit.get("passed"),
            "findings": len(historical_subdomain_labeling_audit.get("findings", [])),
            "docs": [doc.get("path") for doc in historical_subdomain_labeling_audit.get("docs", [])],
        },
        "t1_candidate_claim_labeling_audit": {
            "passed": t1_candidate_labeling_audit.get("passed"),
            "findings": len(t1_candidate_labeling_audit.get("findings", [])),
            "missing_required_snippets": len(t1_candidate_labeling_audit.get("missing_required_snippets", [])),
        },
        "reportable_artifact_flag_audit": {
            "passed": reportable_flag_audit.get("passed"),
            "checks": len(reportable_flag_audit.get("checks", [])),
            "stale_raw_flags": len(reportable_flag_audit.get("stale_raw_flags", [])),
            "hard_failures": len(reportable_flag_audit.get("hard_failures", [])),
            "iter34_raw_canonical_flag_superseded": any(
                row.get("artifact") == "t1_iter34_hybrid_candidate"
                and row.get("flag") == "is_canonical_update"
                and row.get("current_claim_value") is False
                for row in reportable_flag_audit.get("stale_raw_flags", [])
            ),
        },
        "per_item_evidence_map": {
            "passed": per_item_map.get("passed"),
            "status_counts": per_item_map.get("status_counts"),
            "t1_iter12_sum_ccc": per_item_map.get("composites", {}).get("t1_iter12_sum", {}).get("ccc"),
            "t3_per_item_sum_historical_ccc": per_item_map.get("composites", {}).get("t3_per_item_sum_historical", {}).get("ccc"),
            "missing_artifacts": len(per_item_map.get("missing_artifacts", [])),
        },
        "per_item_oof_companion_scope_audit": {
            "passed": per_item_oof_scope.get("passed"),
            "oof_backed_rows": per_item_oof_scope.get("oof_backed_rows"),
            "row_level_json_comparison_available_count": per_item_oof_scope.get("row_level_json_comparison_available_count"),
            "warnings": len(per_item_oof_scope.get("warnings", [])),
            "hard_warnings": len(per_item_oof_scope.get("hard_warnings", [])),
            "t1_max_abs_diff_vs_composite_oof": next(
                (
                    check.get("max_abs_diff_vs_t1_composite_oof")
                    for check in per_item_oof_scope.get("key_checks", [])
                    if check.get("name") == "t1_iter12_item_oofs_sum_to_canonical_oof"
                ),
                None,
            ),
        },
        "t1_iter12_batch_integrity_audit": {
            "passed": t1_iter12_batch_integrity.get("pass"),
            "hard_failures": len(t1_iter12_batch_integrity.get("hard_failures", [])),
            "warnings": len(t1_iter12_batch_integrity.get("warnings", [])),
            "ccc": t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("ccc"),
            "mae": t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("mae"),
            "max_abs_diff_vs_stored_oof": t1_iter12_batch_integrity.get("composite", {}).get("max_abs_diff_vs_stored_oof"),
            "single_coherent_batch": t1_iter12_batch_integrity.get("batch", {}).get("single_coherent_batch"),
            "uses_swaps": t1_iter12_batch_integrity.get("batch", {}).get("uses_swaps"),
        },
        "completion_verdict": "not_complete_t3_validrange_ceiling_unbroken_and_hssayeni_dua_blocked",
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    css = """
    :root {
      color-scheme: light;
      --ink: #17202a;
      --muted: #596573;
      --line: #d9dee7;
      --panel: #f7f8fb;
      --accent: #176f6b;
      --warn: #9b4d00;
      --bad: #8a1c1c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #ffffff;
      line-height: 1.45;
    }
    header, section {
      padding: 28px clamp(20px, 5vw, 72px);
      border-bottom: 1px solid var(--line);
    }
    header {
      background: #eef4f3;
    }
    h1, h2, h3 { margin: 0 0 12px; line-height: 1.15; letter-spacing: 0; }
    h1 { font-size: 2.1rem; max-width: 980px; }
    h2 { font-size: 1.35rem; }
    h3 { font-size: 1rem; margin-top: 18px; }
    p { max-width: 1120px; margin: 0 0 14px; }
    .subtle { color: var(--muted); }
    .metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      max-width: 1120px;
      margin-top: 18px;
    }
    .metric {
      border: 1px solid var(--line);
      background: #fff;
      padding: 12px;
      min-height: 96px;
    }
    .metric strong { display: block; font-size: 1.7rem; line-height: 1.1; }
    .metric em { display: block; font-style: normal; color: var(--muted); margin-top: 6px; }
    .metric span { display: block; color: var(--muted); font-size: .9rem; margin-top: 6px; }
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0 22px;
      font-size: .94rem;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
    }
    th { background: var(--panel); font-weight: 650; }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .9em;
      overflow-wrap: anywhere;
    }
    .note {
      border-left: 4px solid var(--accent);
      background: #f2f8f7;
      padding: 12px 14px;
      max-width: 1120px;
      margin: 12px 0 18px;
    }
    .warning {
      border-left-color: var(--warn);
      background: #fff7ed;
    }
    .bad {
      border-left-color: var(--bad);
      background: #fff5f5;
    }
    .gallery {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
      margin-top: 14px;
    }
    .figure-tile {
      margin: 0;
      border: 1px solid var(--line);
      background: #fff;
    }
    .figure-tile img {
      display: block;
      width: 100%;
      height: auto;
      background: #fff;
    }
    figcaption {
      padding: 8px 10px;
      color: var(--muted);
      font-size: .9rem;
      border-top: 1px solid var(--line);
    }
    .two-col {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
      max-width: 1280px;
    }
    .small { font-size: .9rem; }
    """

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WearGait-PD Current Best Pipeline Dashboard</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <p class="subtle">Generated {html.escape(generated_at)} from post-audit lockbox artifacts</p>
    <h1>WearGait-PD Current Best Pipeline Dashboard</h1>
    <p>This dashboard is a compact map of the current evidence. It separates the conservative T1 floor, the strongest T1 candidate, the valid-range-corrected T3 audit truth, site transportability, and the remaining external-data access blockers.</p>
    <div class="metrics">
      {metric_card("T1 canonical floor", fmt_num(t1_floor.get("ccc")), f"MAE {fmt_num(t1_floor.get('mae'), 3)}, N={t1_floor.get('n')}")}
      {metric_card("T1 strongest candidate", fmt_num(t1_best.get("ccc")), f"iter34, MAE {fmt_num(t1_best.get('mae'), 3)}, N={t1_best.get('n')}")}
      {metric_card("T1 ET robust diagnostic", fmt_num(t1_iter46.get("ccc")), f"below iter34 by {fmt_num(t1_iter46_vs_iter34.get('delta_new_minus_comparator'))}")}
      {metric_card("HARNet fine-tune pilot", fmt_num(t1_iter37.get("mean_ccc")), f"gate {'PASS' if t1_iter37.get('feasibility_gate', {}).get('gate_pass') else 'FAIL'}, min fold {fmt_num(t1_iter37.get('min_fold_ccc'))}")}
      {metric_card("T3 valid-range target", fmt_num(t3_current_metrics.get("ccc")), f"iter47, MAE {fmt_num(t3_current_metrics.get('mae'), 3)}, N={t3_current.get('n')}")}
      {metric_card("T3 no-dst sensitivity", fmt_num(t3_dst_nodst.get("ccc")), "walkway distiller removed")}
      {metric_card("T3 LOSO two-way", fmt_num(t3_loso_current.get("two_way_mean_ccc")), "corrected transportability")}
      {metric_card("T3 95% interval width", fmt_num(current_t3_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 2), "current conformal")}
      {metric_card("T3 intake-only + IMU", fmt_num(t3_clinical_policies["cv_only"]["mean_prediction_metrics"].get("ccc")), "Stage2 no-cv framing audit")}
      {metric_card("T3 IMU-only residual", fmt_num(t3_clinical_policies["intercept_only"]["mean_prediction_metrics"].get("ccc")), "Stage2 no-cv framing audit")}
      {metric_card("FoG-STAR Stage-1 aug", fmt_num(t3_iter38.get("delta_seed_mean_predictions")), f"gate {'PASS' if t3_iter38.get('gate', {}).get('pass') else 'FAIL'}, aug CCC {fmt_num(t3_iter38.get('augmented_seed_mean', {}).get('ccc'))}")}
      {metric_card("FoG-STAR zero-shot Track B", fmt_num(t3_iter39.get("track_b_iter5_style_clinical_plus_wrist", {}).get("ccc")), "partial external validity")}
      {metric_card("T3 local-residual wildcard", fmt_num(t3_iter40.get("seed_mean_delta_ccc")), f"gate {'PASS' if t3_iter40.get('promotion_gate', {}).get('strict_t3_gate_pass') else 'FAIL'}")}
      {metric_card("T3 low-df convex mix", fmt_num(t3_iter50.get("gate", {}).get("delta_seed_mean_predictions")), f"nested CCC {fmt_num(t3_iter50.get('mean_metrics', {}).get('nested_convex', {}).get('ccc'))}, gate {'PASS' if t3_iter50.get('gate', {}).get('strict_t3_gate_pass') else 'FAIL'}")}
      {metric_card("COPS zero-shot Track B", fmt_num(t3_iter49_track_b.get("ccc")), f"N={t3_iter49_track_b.get('n', 'n/a')}, external only")}
      {metric_card("TLVMC DeFOG Track A", fmt_num(tlvmc_track_a.get("ccc")), f"N={tlvmc_track_a.get('n', 'n/a')}, external only")}
      {metric_card("PDFE Track A", fmt_num(pdfe_track_a.get("ccc")), f"N={pdfe_iter52.get('n_pdfe', 'n/a')}, external only")}
    </div>
  </header>

  <section>
    <h2>Completion State</h2>
    <div class="note bad">
      <p><strong>Goal not achieved.</strong> T1 has a strong post-publication candidate at CCC {fmt_num(t1_best.get("ccc"))}, but the conservative canonical floor remains CCC {fmt_num(t1_floor.get("ccc"))}. T3 corrected-target audit truth is only CCC {fmt_num(t3_current_metrics.get("ccc"))}, with corrected LOSO two-way CCC {fmt_num(t3_loso_current.get("two_way_mean_ccc"))}; the old iter5 CCC {fmt_num(t3_old.get("ccc"))} is target-contaminated. Current conformal intervals are wide for T3 and deployable abstention does not rescue CCC. FoG-STAR Stage-1 augmentation failed its gate; FoG-STAR, COPS, TLVMC/DeFOG, and PDFE zero-shot are partial or negative external evidence only; ALAMEDA/mPower/Papadopoulos/HarmonizedAccel/REMAP/Oxford/BioStamp/Mobilise-D TVS are documented no-prereg leads; PPMI/Verily, PPP/PD-VME, WATCH-PD, CNS Portugal/Lobo, Hssayeni/MJFF, and ICICLE-GAIT are access/request-gated; the local-residual wildcard failed; and no route is compute-ready before access.</p>
    </div>
    <div class="note">
      <p><strong>Current best next action.</strong> Do not rerun dead internal variants. The access-readiness queue has {external_access_readiness.get("summary", {}).get("application_packet_ready_count")} request packets ready and {external_access_readiness.get("summary", {}).get("compute_ready_route_count")} compute-ready routes; top priority is {html.escape(str(external_access_readiness.get("summary", {}).get("top_priority_route")))}. The first code action after any approval is a read-only schema probe, not a model run.</p>
      <p><strong>Access submission tracker.</strong> The consolidated tracker records {access_submission_tracker.get("summary", {}).get("submit_ready_route_count")} submit-ready packet routes, {access_submission_tracker.get("summary", {}).get("compute_ready_route_count")} compute-ready routes before approval, and hard failures {access_submission_tracker.get("summary", {}).get("hard_failure_count")}. It is the user-facing action board for filling packets while keeping protected details out of git.</p>
      <p><strong>Latest advisor consult.</strong> Kimi's post-Parkinson@Home recommendation records model action justified = <code>{html.escape(str(kimi_next_action.get("recommendation", {}).get("model_action_justified")))}</code>; the single next non-redundant action is <code>{html.escape(str(kimi_next_action.get("recommendation", {}).get("single_next_non_redundant_action")))}</code> via <code>{html.escape(str(kimi_next_action.get("recommendation", {}).get("runbook")))}</code>.</p>
      <p><strong>Recent web-lead refresh.</strong> The post-tracker web sweep checked {recent_external_web_leads.get("summary", {}).get("routes_checked")} superficially relevant leads and found {recent_external_web_leads.get("summary", {}).get("new_compute_ready_routes")} compute-ready routes and {recent_external_web_leads.get("summary", {}).get("new_scaffold_or_preregistration_actions")} scaffold/preregistration actions. Smid 2026 is tremor-subitem-only, Guo 2025 is smartphone-protocol and schema-hidden, and Yin 2025 was already audited request-only.</p>
      <p><strong>PPMI Tier-3 packet.</strong> The local request template <code>{html.escape(str(ppmi_packet_audit.get("packet")))}</code> now passes <code>{html.escape(str(ppmi_packet_audit.get("decision")))}</code> with hard failures {len(ppmi_packet_audit.get("hard_failures", []))}. It is an access packet only; no scaffold, preregistration, download, remote job, or model run is allowed before approval and a read-only schema probe.</p>
      <p><strong>PPP / PD-VME packet.</strong> The second-priority Verily-watch route now has a fillable request template <code>{html.escape(str(ppp_packet_audit.get("packet")))}</code> and audit decision <code>{html.escape(str(ppp_packet_audit.get("decision")))}</code>. This remains request-gated access work; no PEP probe or model code before approval.</p>
      <p><strong>WATCH-PD packet.</strong> The third-priority protocol-matched route now has a fillable proposal template <code>{html.escape(str(watchpd_packet_audit.get("packet")))}</code> and audit decision <code>{html.escape(str(watchpd_packet_audit.get("decision")))}</code>. This remains 3DT/Steering-Committee gated access work; no APDM/Apple/iPhone probe or model code before approval.</p>
      <p><strong>CNS Portugal packet.</strong> The fourth-priority AX3 gait route now has a fillable author/CNS data-owner request template <code>{html.escape(str(cns_packet_audit.get("packet")))}</code> and audit decision <code>{html.escape(str(cns_packet_audit.get("decision")))}</code>. This remains request-gated access work; no CNS probe, preregistration, download, remote job, or model code before approval and row-level schema inspection.</p>
      <p><strong>Hssayeni / MJFF packet.</strong> The fifth-priority Synapse route now has a fillable DUA/request template <code>{html.escape(str(hssayeni_packet_audit.get("packet")))}</code> and audit decision <code>{html.escape(str(hssayeni_packet_audit.get("decision")))}</code>. This remains Synapse-controlled access work; the existing iter26 scaffold is not permission for a probe, download, cache extraction, remote job, or model run before DUA approval and schema inspection.</p>
      <p><strong>ICICLE packet.</strong> The sixth-priority Newcastle lower-back gait route now has a fillable request template <code>{html.escape(str(icicle_packet_audit.get("packet")))}</code> and audit decision <code>{html.escape(str(icicle_packet_audit.get("decision")))}</code>. This remains request-gated access work; no ICICLE probe, preregistration, download, cache extraction, remote job, or model code is allowed before data-owner approval and row-level schema inspection.</p>
    </div>
    <div class="note warning">
      <p><strong>Current uncertainty audit.</strong> Current conformal/abstention uses post-audit OOF rows only. T3 iter47 current has 80% / 95% interval widths {fmt_num(current_t3_conf.get("conformal", {}).get("80pct", {}).get("mean_interval_width"), 2)} / {fmt_num(current_t3_conf.get("conformal", {}).get("95pct", {}).get("mean_interval_width"), 2)} UPDRS-III points, and deployable 50% abstention drops CCC to {fmt_num(current_t3_conf.get("abstention_at_50pct_discard", {}).get("prediction_tail_distance_ccc"))}. This is uncertainty evidence, not a model update.</p>
      <p><strong>Latest T3 iter47 residual anatomy.</strong> The corrected-target OOF vector remains tail-compressed: residual corr = {fmt_num(t3_resid_overall.get("residual_corr_with_true"))}, Q1/Q4 mean residuals = {fmt_num(t3_resid_quartiles.get("Q1_low", {}).get("mean_residual_pred_minus_true"), 2)} / {fmt_num(t3_resid_quartiles.get("Q4_high", {}).get("mean_residual_pred_minus_true"), 2)}, and WPD within-site CCC = {fmt_num(t3_resid_sites.get("WPD", {}).get("ccc"))}. Top post-hoc residual-feature |r| = {fmt_num(t3_resid_top_feature.get("abs_corr_with_residual"), 3)} (<code>{html.escape(str(t3_resid_top_feature.get("feature", "n/a")))}</code>); this is diagnostic-only and not fold-local feature selection.</p>
      <p><strong>Latest T3 iter47 CCC-rescale sanity.</strong> OOF-level variance matching raises CCC to {fmt_num(t3_rescale_variance_metrics.get("ccc"))} but MAE worsens to {fmt_num(t3_rescale_variance_metrics.get("mae"), 3)}; paired bootstrap gives CCC delta {fmt_num(t3_rescale_variance_boot.get("ccc_delta_mean"))} with CI [{fmt_num((t3_rescale_variance_boot.get("ccc_delta_ci95") or [None, None])[0])}, {fmt_num((t3_rescale_variance_boot.get("ccc_delta_ci95") or [None, None])[1])}] and MAE delta {fmt_num(t3_rescale_variance_boot.get("mae_delta_mean"), 3)}. This is not a fully nested meta-model and is not a reportable lockbox route.</p>
      <p><strong>Latest headline influence audit.</strong> No single-subject redline was found. T3 iter47 leave-one CCC ranges from {fmt_num(influence_t3_jack.get("ccc_without_min"))} to {fmt_num(influence_t3_jack.get("ccc_without_max"))}; max absolute leave-one CCC delta is {fmt_num(influence_t3_conc.get("top1_abs_delta_ccc"))} and top-five influence share is {fmt_num(influence_t3_conc.get("top5_fraction_of_sum_abs_delta"))}. T1 iter34-minus-iter12 matched delta stays positive under all leave-one deletions, minimum {fmt_num(influence_t1_matched.get("leave_one_delta_min"))}. Influence remains severity-tail concentrated: T3 abs(target-median) vs abs(delta CCC) r = {fmt_num(influence_t3_corr.get("abs_target_minus_median_vs_abs_delta_ccc"))} and Gini = {fmt_num(influence_t3_conc.get("gini_abs_delta_ccc"))}. Diagnostic-only; no filtering or model update.</p>
      <p><strong>Latest T3 domain residual audit.</strong> Parsed valid-range item totals match the iter47 target exactly. True non-gait burden dominates residuals: unobservable-non-gait residual r = {fmt_num(domain_unobs.get("corr_domain_with_residual_pred_minus_true"))}, upper-limb brady r = {fmt_num(domain_upper.get("corr_domain_with_residual_pred_minus_true"))}, and appendicular/gait-balance oracle checks are privileged. The multidomain Ridge oracle reaches CCC {fmt_num(domain_multi.get("metrics", {}).get("ccc"))}, but it requires true clinical domain labels at prediction time and is non-deployable.</p>
      <p><strong>Latest T3 item-level residual audit.</strong> The top residual-correlated item is item {html.escape(str(item_top_residual.get("item", "n/a")))} ({html.escape(str(item_top_residual.get("name", "n/a")))}) with r = {fmt_num(item_top_residual.get("corr_item_with_residual_pred_minus_true"), 3)} and privileged oracle dCCC {fmt_num(item_top_residual.get("loo_privileged_oracle", {}).get("delta_ccc_vs_base"), 3)}. Mean |r(item,residual)| is {fmt_num(item_observable.get("mean_abs_residual_corr_observable"), 3)} for gait/balance-observable items and {fmt_num(item_observable.get("mean_abs_residual_corr_unobservable"), 3)} for non-observable items; the best observable single-item oracle dCCC is only {fmt_num(item_observable.get("best_observable_oracle_delta_ccc"), 3)}. This is stop-rule evidence, not a WearGait-only model route.</p>
      <p><strong>Latest provenance sensitivity.</strong> The current V2 pool includes 31 <code>dst_*</code> pressure-walkway distiller columns that were trained once on a historical dev split, not refit inside LOOCV. Removing only those columns gives corrected T3 CCC {fmt_num(t3_dst_nodst.get("ccc"))} versus current {fmt_num(t3_dst_current.get("ccc"))}; bootstrap delta no-dst minus current is {fmt_num(t3_dst_comp.get("mean_delta"))} with CI [{fmt_num(t3_dst_comp.get("ci95", [None, None])[0])}, {fmt_num(t3_dst_comp.get("ci95", [None, None])[1])}]. This is a disclosure caveat, not a material T3 change.</p>
      <p><strong>Latest cache provenance audit.</strong> <code>ablation_v3_features.csv</code> is hash-stable and git-tracked, but the audit decision is <code>{html.escape(str(ablation_v3_provenance.get("decision", {}).get("decision")))}</code> because exact command/runtime/git/raw-data/fold-scope evidence is incomplete. Do not call the V2 cache manifest-clean.</p>
      <p><strong>Latest cache manifest backfill.</strong> Clean cache artifacts: {cache_manifest_audit.get("status_counts", {}).get("manifest_complete_clean_by_construction", "n/a")} complete, {cache_manifest_audit.get("status_counts", {}).get("partial_manifest_diagnostic_only", "n/a")} partial, {cache_manifest_audit.get("status_counts", {}).get("missing_manifest_diagnostic_only", "n/a")} missing. The new concrete companion sidecar is <code>item11_multiscale_recordings.csv.manifest.json</code>. The missing-manifest origin audit maps {missing_cache_origin_audit.get("n_missing_manifests", "n/a")} still-missing sidecars and does not make any artifact headline-safe.</p>
      <p><strong>Manual missing-cache backfill evidence.</strong> The follow-up audit leaves {manual_cache_backfill_evidence.get("decision_counts", {}).get("leave_missing_no_patch", "n/a")} human-patch missing-manifest candidates as <code>leave_missing_no_patch</code>: MOMENT/HC-SSL/TUG-transition depend on a broken <code>rocket_recordings.npz</code> symlink, joints/stride depend on a missing raw CSV directory, and exact command/runtime evidence is absent.</p>
      <p><strong>Ablation V3 regeneration probe.</strong> The non-destructive regeneration probe status is <code>{html.escape(str(ablation_v3_regeneration.get("status")))}</code>. Frozen cache unchanged: <code>{html.escape(str(ablation_v3_regeneration.get("frozen_cache_unchanged")))}</code>. Missing inputs: <code>{html.escape(", ".join(ablation_v3_regeneration.get("input_status", {}).get("missing", [])))}</code>. No regenerated cache was written and no clean sidecar was synthesized.</p>
      <p><strong>WearGait raw-input recovery preflight.</strong> The recovery helper status is <code>{html.escape(str(synapse_recovery.get("status")))}</code>. Synapse credentials present: <code>{html.escape(str(synapse_recovery.get("credential_status", {}).get("can_attempt_download")))}</code>. Exact missing IDs are <code>syn55105521</code> (control clinical), <code>syn61370552</code> ({html.escape(str(synapse_recovery.get("entities", {}).get("control_csv_folder", {}).get("synapse_probe", {}).get("csv_children_count")))} control CSVs), and <code>syn64589881</code> (PKMAS walkway metrics). The helper is dry-run by default and requires <code>--confirm-large-control-csvs</code> before downloading the control CSV folder.</p>
      <p><strong>Latest WearGait raw-data recovery runbook audit.</strong> The human-facing runbook audit passes with hard failures {len(raw_data_recovery_runbook_audit.get("hard_failures", []))} and decision <code>{html.escape(str(raw_data_recovery_runbook_audit.get("decision")))}</code>. It preserves the three recovery IDs, records credentials present as <code>{html.escape(str(raw_data_recovery_runbook_audit.get("current_status", {}).get("credentials_present")))}</code>, and keeps the branch at no-download/no-cache-promotion/no-model-run until credentials, explicit large-transfer confirmation, and a successful non-destructive regeneration probe exist.</p>
      <p><strong>Latest task-plan current-scope audit.</strong> The active plan head now has explicit post-iter47 completion criteria and the old success-tier table is archive-bound. Decision <code>{html.escape(str(task_plan_current_scope_audit.get("decision")))}</code>; hard failures {len(task_plan_current_scope_audit.get("hard_failures", []))}; current-scope legacy success findings {len(task_plan_current_scope_audit.get("current_scope", {}).get("legacy_success_findings", []))}.</p>
      <p><strong>Latest paper generator routing audit.</strong> Current manuscript work routes through <code>render_current_paper.py</code> to <code>CURRENT_PAPER.html</code>; <code>generate_paper_v4.py</code> and <code>NEW4.html</code> are explicitly quarantined as legacy/stale archaeology. Decision <code>{html.escape(str(paper_generator_routing_audit.get("decision")))}</code>; hard failures {len(paper_generator_routing_audit.get("hard_failures", []))}; active docs checked {len(paper_generator_routing_audit.get("active_docs", []))}; retained <code>NEW4.html</code> transductive hits {paper_generator_routing_audit.get("legacy_generator", {}).get("stale_phrase_counts", {}).get("new4_html_transductive", "n/a")}.</p>
      <p><strong>Latest README claim-routing audit.</strong> The root README now opens with current post-audit T1/T3 claims and quarantines old SSL/XGBRanker numbers as legacy/retracted/pre-audit target-contaminated archaeology. Decision <code>{html.escape(str(readme_claim_routing_audit.get("decision")))}</code>; hard failures {len(readme_claim_routing_audit.get("hard_failures", []))}; unguarded stale hits {len(readme_claim_routing_audit.get("unguarded_dangerous_hits", []))}; missing required current snippets {len(readme_claim_routing_audit.get("missing_required", []))}.</p>
      <p><strong>Latest legacy manuscript-surface audit.</strong> Retained pre-audit paper/narrative surfaces now carry near-top stale/do-not-cite banners and current-route pointers. Decision <code>{html.escape(str(legacy_manuscript_surface_audit.get("decision")))}</code>; hard failures {len(legacy_manuscript_surface_audit.get("hard_failures", []))}; legacy surfaces checked {len(legacy_manuscript_surface_audit.get("legacy_surfaces", []))}; stale-pattern hits retained only under quarantine {legacy_manuscript_surface_audit.get("total_dangerous_hits", "n/a")}.</p>
      <p><strong>Latest historical archive-surface audit.</strong> Retained project-note/archive surfaces such as <code>CONT.md</code>, <code>VNEXT.md</code>, and <code>leakage_onepager.html</code> now carry archive-status banners and current-route pointers. The one-pager's stale T3 iter5 canonical row was corrected to the iter47 valid-range headline. Decision <code>{html.escape(str(historical_archive_surface_audit.get("decision")))}</code>; hard failures {historical_archive_surface_audit.get("hard_failures", "n/a")}; surfaces checked {historical_archive_surface_audit.get("surfaces_checked", "n/a")}; stale-pattern hits retained under archive banners {historical_archive_surface_audit.get("total_stale_pattern_hits_retained_under_archive_banners", "n/a")}.</p>
      <p><strong>Latest secret hygiene audit.</strong> A local ignored <code>TOKEN.md</code> and <code>.env</code> containing JWT-like credentials were removed, and high-confidence credential scanning now passes. Decision <code>{html.escape(str(secret_hygiene_audit.get("decision")))}</code>; findings {len(secret_hygiene_audit.get("findings", []))}; hard failures {len(secret_hygiene_audit.get("hard_failures", []))}; scanned files {secret_hygiene_audit.get("scanned_file_count", "n/a")}.</p>
      <p><strong>Latest cache consumer guard audit.</strong> Known current safe-cache consumers guarded by <code>require_cache_manifest</code>: {len(cache_consumer_audit.get("current_guarded_consumers", []))}. Model/composer scripts that still reference missing or partial manifests remain diagnostic-only: {len(cache_consumer_audit.get("diagnostic_only_model_consumers", []))}. Non-model or cache-producer references: {cache_consumer_audit.get("classification_counts", {}).get("non_model_or_cache_producer_reference", "n/a")}.</p>
      <p><strong>Latest transitive/runtime cache dependency audits.</strong> Static import-closure scanning covers {len(transitive_cache_audit.get("entrypoints", []))} headline/reportable entrypoints and records {len(transitive_cache_audit.get("direct_diagnostic_entrypoints", []))} direct diagnostic-cache entrypoints. Runtime tracing across {len(runtime_cache_audit.get("target_reports", []))} lightweight paths opened diagnostic/partial cache artifacts: <code>{html.escape(", ".join(runtime_cache_audit.get("opened_diagnostic_or_partial_cache_artifacts", [])))}</code>. Runtime tracing is diagnostic only; it does not make missing manifests headline-safe.</p>
      <p><strong>Latest claim consistency audit.</strong> Active-scope docs now pass the stale-number scanner: old T3 values are allowed only when labeled historical, superseded, target-contaminated, or time-local. Stale findings: {len(canonical_claim_audit.get("stale_findings", []))}.</p>
      <p><strong>Latest metric recompute audit.</strong> Stored prediction artifacts reproduce the current headline and sensitivity metrics across {len(metric_recompute_audit.get("checks", []))} checks within tolerance {fmt_num(metric_recompute_audit.get("tolerance"), 4)}; audit pass is {html.escape(str(metric_recompute_audit.get("passed")))}.</p>
      <p><strong>Latest CCC metric integrity audit.</strong> Reportable CCC is pinned to Lin's population-moment convention. The audit covers {len(ccc_metric_audit.get("headline_checks", []))} headline/candidate vectors and {len(ccc_metric_audit.get("implementation_checks", []))} synthetic implementation checks; max sample-minus-population shift is {fmt_num(ccc_metric_audit.get("max_abs_sample_minus_population_headline"), 8)} and hard failures are {len(ccc_metric_audit.get("hard_failures", []))}. The only retained warning is the deliberate fewer-than-three-finite-pairs policy.</p>
      <p><strong>Latest OOF integrity audit.</strong> Selected lockbox <code>.oof.npy</code> files exactly match their JSON <code>per_subject.y_pred</code> arrays across {len(oof_integrity_audit.get("checks", []))} checks; max absolute diff is {fmt_num(max((check.get("max_abs_diff") or 0.0 for check in oof_integrity_audit.get("checks", [])), default=0.0), 1)}.</p>
      <p><strong>Latest T3 iter47 target-integrity audit.</strong> The current T3 target audit passes with hard failures {len(t3_iter47_target_integrity.get("hard_failures", []))} and warnings {len(t3_iter47_target_integrity.get("warnings", []))}: minimal valid-range N={t3_iter47_target_integrity.get("cohorts", {}).get("drop_allmissing_validrange", {}).get("n")}, complete33 N={t3_iter47_target_integrity.get("cohorts", {}).get("complete33_validrange", {}).get("n")}, invalid raw subitem values={len(t3_iter47_target_integrity.get("target", {}).get("invalid_raw_subitem_values", []))}, target-changed rows={len(t3_iter47_target_integrity.get("target", {}).get("target_changed_rows", []))}. Saved subject rows recompute current CCC {fmt_num(t3_integrity_current.get("csv_recomputed_metrics", {}).get("ccc"))}; LOSO rows recompute two-way CCC {fmt_num(t3_integrity_loso.get("two_way_mean_ccc"))}.</p>
      <p><strong>Latest T3 complete33 claim audit.</strong> The N=88 complete33 values are allowed only as sensitivity-only complete-case / partial-missing context, while the current T3 headline remains the N=95 minimal valid-range CCC 0.3784. Findings: {len(t3_complete33_labeling_audit.get("findings", []))}; missing required snippets: {len(t3_complete33_labeling_audit.get("missing_required_snippets", []))}.</p>
      <p><strong>Latest external result claim audit.</strong> FoG-STAR, COPS, TLVMC/DeFOG, PDFE, and PADS numbers are allowed only as external-validity or within-dataset sanity evidence; they cannot update the internal T3 headline. Findings: {len(external_result_labeling_audit.get("findings", []))}; missing required snippets: {len(external_result_labeling_audit.get("missing_required_snippets", []))}; artifact failures: {len(external_result_labeling_audit.get("artifact_failures", []))}.</p>
      <p><strong>Latest remaining-blocker action audit.</strong> The current verifier's {remaining_blocker_action_audit.get("source_blocker_count")} blockers are all classified with {len(remaining_blocker_action_audit.get("unmatched_blockers", []))} unclassified rows and {len(remaining_blocker_action_audit.get("local_model_actions", []))} local WearGait-only model actions remaining. The next valid actions are gated-data access, raw-data restoration for cache provenance, or paper/provenance hardening.</p>
      <p><strong>Latest external access readiness audit.</strong> The access queue covers {external_access_readiness.get("summary", {}).get("route_count")} routes, passes with hard failures {external_access_readiness.get("summary", {}).get("hard_failure_count")}, and records {external_access_readiness.get("summary", {}).get("application_packet_ready_count")} application/request packets ready but {external_access_readiness.get("summary", {}).get("compute_ready_route_count")} compute-ready routes before access. PPP/PD-VME and Hssayeni now have explicit runbook boundaries; remote jobs remain disallowed until approval and schema inspection.</p>
      <p><strong>Latest PPMI request-packet audit.</strong> The top-priority PPMI / Verily route now has a fillable Tier-3 request template and audit. Packet decision <code>{html.escape(str(ppmi_packet_audit.get("decision")))}</code>; checks {len(ppmi_packet_audit.get("checks", {}))}; missing required terms {len(ppmi_packet_audit.get("missing", []))}; hard failures {len(ppmi_packet_audit.get("hard_failures", []))}.</p>
      <p><strong>Latest PPP request-packet audit.</strong> The second-priority PPP / PD-VME route now has a fillable project-proposal packet and audit. Packet decision <code>{html.escape(str(ppp_packet_audit.get("decision")))}</code>; checks {len(ppp_packet_audit.get("checks", {}))}; missing required terms {len(ppp_packet_audit.get("missing", []))}; hard failures {len(ppp_packet_audit.get("hard_failures", []))}.</p>
      <p><strong>Latest WATCH-PD request-packet audit.</strong> The third-priority WATCH-PD route now has a fillable 3DT/Steering-Committee proposal packet and audit. Packet decision <code>{html.escape(str(watchpd_packet_audit.get("decision")))}</code>; checks {len(watchpd_packet_audit.get("checks", {}))}; missing required terms {len(watchpd_packet_audit.get("missing", []))}; hard failures {len(watchpd_packet_audit.get("hard_failures", []))}.</p>
      <p><strong>Latest CNS Portugal request-packet audit.</strong> The fourth-priority CNS Portugal / Lobo AX3 gait route now has a fillable author-request packet and audit. Packet decision <code>{html.escape(str(cns_packet_audit.get("decision")))}</code>; checks {len(cns_packet_audit.get("checks", {}))}; missing required terms {len(cns_packet_audit.get("missing", []))}; hard failures {len(cns_packet_audit.get("hard_failures", []))}. The published left-out 10% window result remains context-only; subject/session-grouped validation is required.</p>
      <p><strong>Latest Hssayeni / MJFF request-packet audit.</strong> The fifth-priority MJFF Levodopa Response Study route now has a fillable Synapse DUA/request packet and audit. Packet decision <code>{html.escape(str(hssayeni_packet_audit.get("decision")))}</code>; checks {len(hssayeni_packet_audit.get("checks", {}))}; missing required terms {len(hssayeni_packet_audit.get("missing", []))}; hard failures {len(hssayeni_packet_audit.get("hard_failures", []))}. The route must hard-stop if approved data expose only limb-specific symptom labels and no total Part III or valid item/subitem endpoint.</p>
      <p><strong>Latest ICICLE request-packet audit.</strong> The sixth-priority ICICLE-PD / ICICLE-GAIT route now has a fillable Newcastle investigator request packet and audit. Packet decision <code>{html.escape(str(icicle_packet_audit.get("decision")))}</code>; checks {len(icicle_packet_audit.get("checks", {}))}; missing required terms {len(icicle_packet_audit.get("missing", []))}; hard failures {len(icicle_packet_audit.get("hard_failures", []))}. Daily rows with repeated visit-level Part III labels must be grouped and aggregated before reported CCC/MAE; test-data median imputation is prohibited.</p>
      <p><strong>Latest pre-registration audit.</strong> Embedded or filename timestamps show no hard temporal-order failures across {len(prereg_temporal_audit.get("checks", []))} reportable artifacts. The audit records {len(prereg_temporal_audit.get("warnings", []))} warnings for legacy/weak fields such as missing result-side formula links or <code>git_sha: unknown</code>.</p>
      <p><strong>Latest pre-audit claim labeling audit.</strong> Old held-out/stacking/ceiling claims are allowed only with local historical/pre-audit framing in <code>paper.md</code> and <code>CURRENT_PAPER.html</code>. Findings: {len(pre_audit_labeling_audit.get("findings", []))}; pass is {html.escape(str(pre_audit_labeling_audit.get("passed")))}.</p>
      <p><strong>Latest historical subdomain claim audit.</strong> Historical sensor-ablation and subdomain-prediction claims are now allowed only with local pre-audit/context framing, or when explicitly tied to current post-audit T1 and residual-audit support. Findings: {len(historical_subdomain_labeling_audit.get("findings", []))}; pass is {html.escape(str(historical_subdomain_labeling_audit.get("passed")))}.</p>
      <p><strong>Latest T1 candidate claim audit.</strong> Iter34 / 0.7366 is allowed only as a strongest-candidate claim with the N=93, P2, and auxiliary-label caveats, while iter12 remains the canonical floor. Findings: {len(t1_candidate_labeling_audit.get("findings", []))}; missing required snippets: {len(t1_candidate_labeling_audit.get("missing_required_snippets", []))}.</p>
      <p><strong>Latest artifact flag audit.</strong> Raw lockbox booleans are not current claim policy. The audit covers {len(reportable_flag_audit.get("checks", []))} reportable artifacts, records {len(reportable_flag_audit.get("stale_raw_flags", []))} superseded raw flags, and explicitly overrides iter34's archived <code>is_canonical_update=true</code> with the current strongest-candidate status. Hard failures: {len(reportable_flag_audit.get("hard_failures", []))}.</p>
      <p><strong>Latest per-item evidence map.</strong> The per-item audit labels all 18 items by current claim scope: {per_item_map.get("status_counts", {}).get("current_t1_iter12_component", 0)} current iter12 T1 components, {per_item_map.get("status_counts", {}).get("iter17_reportable_per_item_win", 0)} supplementary iter17 per-item wins, {per_item_map.get("status_counts", {}).get("historical_iter8_per_item_lockbox_supplementary", 0)} historical iter8 lockboxes, and {per_item_map.get("status_counts", {}).get("missing_or_backfill_only_unobservable", 0)} backfill-only items. The historical 18-item T3 sum is explicitly marked dead-route at CCC {fmt_num(per_item_map.get("composites", {}).get("t3_per_item_sum_historical", {}).get("ccc"))}.</p>
      <p><strong>Latest per-item OOF companion scope audit.</strong> Per-item JSONs lack row-level <code>per_subject.y_pred</code>, so the companion audit checks scope directly: {per_item_oof_scope.get("oof_backed_rows")} OOF-backed rows are finite expected-length arrays, row-level JSON comparison availability is {per_item_oof_scope.get("row_level_json_comparison_available_count")}, and the six current T1 item OOF companions sum to the canonical iter12 T1 OOF with max absolute diff {fmt_num(next((check.get("max_abs_diff_vs_t1_composite_oof") for check in per_item_oof_scope.get("key_checks", []) if check.get("name") == "t1_iter12_item_oofs_sum_to_canonical_oof"), 0.0), 1)}. The retained warning is item 18's JSON N=93 versus 94-slot companion array.</p>
      <p><strong>Latest T1 iter12 batch-integrity audit.</strong> The canonical T1 floor is reproducible from one coherent iter8 batch with no swaps: pass is {html.escape(str(t1_iter12_batch_integrity.get("pass")))}, hard failures {len(t1_iter12_batch_integrity.get("hard_failures", []))}, warnings {len(t1_iter12_batch_integrity.get("warnings", []))}, recomputed CCC {fmt_num(t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("ccc"))}, MAE {fmt_num(t1_iter12_batch_integrity.get("composite", {}).get("metrics", {}).get("mae"), 4)}, and max summed-OOF diff {fmt_num(t1_iter12_batch_integrity.get("composite", {}).get("max_abs_diff_vs_stored_oof"), 1)}.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest internal negative.</strong> The last allowed encoder variant, HARNet end-to-end tail fine-tuning, failed its strict subject-level feasibility screen: OOF CCC {fmt_num(t1_iter37.get("mean_ccc"))}, MAE {fmt_num(t1_iter37.get("mean_mae"), 3)}, min fold CCC {fmt_num(t1_iter37.get("min_fold_ccc"))}. It is now on the dead list.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest T1 robustification negative.</strong> ET-only cleared the iter34 P2 bootstrap screen in 5-fold decomposition, but the pre-registered iter46 LOOCV landed at CCC {fmt_num(t1_iter46.get("ccc"))}: delta vs iter34 {fmt_num(t1_iter46_vs_iter34.get("delta_new_minus_comparator"))}, and same-SID bootstrap frac&gt;0 vs iter12 {fmt_num(t1_iter46_vs_iter12.get("bootstrap_delta", {}).get("frac_above_zero"), 4)}. It is diagnostic only.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest T1 label audit.</strong> The iter48 valid-range audit found that historical iter34 used an invalid auxiliary item-15 label for {html.escape(str(t1_aux_invalid.get("sid", "n/a")))}: value {fmt_num(t1_aux_invalid.get("value"), 1)} with valid max {fmt_num(t1_aux_invalid.get("valid_max"), 1)}. The primary T1 target items 9-14 are valid, but valid-range auxiliary filtering changes the chain cohort from N={t1_aux_valid.get("current_loader", {}).get("chain_n")} to N={t1_aux_valid.get("validated_loader", {}).get("chain_n")}. This is documented; no post-hoc N=92 rerun is planned.</p>
      <p><strong>Latest T1 auxiliary-order audit.</strong> The follow-up audit corrected a false fixed-order assumption: iter34 uses <code>RegressorChain(order=&quot;random&quot;)</code>, and item15 is upstream of T1 items in {t1_aux_order_summary.get("iter34_lockbox_seed_count_with_exposure")} of {t1_aux_order_summary.get("iter34_lockbox_seed_count")} locked seeds. The bounded all-base stale-vs-valid 5-fold screen found common-SID CCC delta {fmt_num(t1_aux_order_impact.get("delta_valid_minus_stale_common_ccc"), 4)} with materiality flag <code>{html.escape(str(t1_aux_order_impact.get("materiality_flag")))}</code>; it sharpens the caveat but does not justify a post-hoc lockbox.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest external negative.</strong> FoG-STAR is a direct public T3 route, but the conservative iter38 Stage-1 augmentation screen did not move WearGait-PD T3: same-loop baseline CCC {fmt_num(t3_iter38.get("baseline_seed_mean", {}).get("ccc"))}, augmented CCC {fmt_num(t3_iter38.get("augmented_seed_mean", {}).get("ccc"))}, delta {fmt_num(t3_iter38.get("delta_seed_mean_predictions"))}; gate {'PASS' if t3_iter38.get('gate', {}).get('pass') else 'FAIL'}.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest external route.</strong> COPS iter49 is complete: {t3_iter49_probe.get("data_summary", {}).get("n_zip_files")} OSF ZIP records ({t3_iter49.get("n_cops_rows_total")} unique feature rows), {fmt_num(t3_iter49_probe.get("data_summary", {}).get("total_zip_size_bytes", 0) / 1e9, 2)} GB probed total, {t3_iter49.get("n_cops_off_labeled")} OFF-labeled subjects, and {t3_iter49.get("n_common_magnitude_features")} common magnitude features. Track A right-wrist CCC {fmt_num(t3_iter49_track_a.get("ccc"))}, Track B right clinical+wrist CCC {fmt_num(t3_iter49_track_b.get("ccc"))}, Track D bilateral clinical+wrist CCC {fmt_num(t3_iter49_track_d.get("ccc"))}, and Track C COPS-only LOOCV sanity CCC {fmt_num(t3_iter49_track_c.get("ccc"))}. This is external-validity evidence only and cannot change the internal T3 headline.</p>
      <p><strong>Latest public external result.</strong> TLVMC/DeFOG iter51 is complete under the frozen formula SHA <code>{tlvmc_prereg.get("formula_sha256")}</code>. The feature cache has {tlvmc_iter51.get("n_defog_rows")} rows across {tlvmc_iter51.get("n_defog_subjects")} subjects, including {tlvmc_iter51.get("n_defog_off_rows")} OFF primary rows, and {tlvmc_iter51.get("n_common_magnitude_features")} common magnitude features. Track A lower-back magnitude zero-shot CCC is {fmt_num(tlvmc_track_a.get("ccc"))} with 95% CI [{fmt_num(tlvmc_track_a.get("ccc_ci95", [None, None])[0])}, {fmt_num(tlvmc_track_a.get("ccc_ci95", [None, None])[1])}], MAE {fmt_num(tlvmc_track_a.get("mae"))}; Track B wrist-to-lumbar stress CCC is {fmt_num(tlvmc_track_b.get("ccc"))}; Track C DeFOG-only subject-grouped LOSO sanity CCC is {fmt_num(tlvmc_track_c.get("ccc"))}. This is partial external validity only and cannot change the internal WearGait-PD T3 headline.</p>
      <p><strong>Latest external transportability stress test.</strong> PDFE turning-in-place iter52 is complete under the frozen formula SHA <code>{pdfe_prereg.get("formula_sha256")}</code>. The probe found {pdfe_probe.get("n_session1_targets")} session-1 UPDRS-III targets; the model run used {pdfe_iter52.get("n_pdfe")} PDFE subjects and {pdfe_iter52.get("n_common_magnitude_features")} common shank magnitude features. Track A WearGait shank-to-PDFE CCC is {fmt_num(pdfe_track_a.get("ccc"))} with 95% CI [{fmt_num(pdfe_track_a.get("ccc_bootstrap", {}).get("ci95_low"))}, {fmt_num(pdfe_track_a.get("ccc_bootstrap", {}).get("ci95_high"))}], Track B clinical+shank CCC is {fmt_num(pdfe_track_b.get("ccc"))}, and Track C PDFE-only LOOCV sanity CCC is {fmt_num(pdfe_track_c.get("ccc"))}. This confirms within-PDFE signal but failed WearGait transfer; it cannot change the internal WearGait-PD T3 headline.</p>
      <p><strong>Route watchlist.</strong> PPMI/Verily is the first gated application target because it is larger and wrist-native. PPP/PD-VME is a strong Verily-watch peer but remains RDSRC-gated and schema-hidden. WATCH-PD, CNS Portugal/Lobo, Hssayeni/MJFF, and ICICLE-GAIT are direct/request-gated routes with runbooks; Mobilise-D is TVS-skip / CVS-watch until row-level wearable plus MDS-UPDRS access exists. No scaffold or remote job is justified before access and schema.</p>
      <p><strong>Route closeout.</strong> ALAMEDA is public/direct but only N=11; mPower is phone-based and self-reported; Papadopoulos phone-call tremor is public but tremor-subitem-only; Harmonized Upper/Lower Limb Accelerometry is DASH-gated daily-life ActiGraph rehab summary data without confirmed Part III/T1 targets; Monipar/BIOCLITE are public consumer-smartwatch subitem datasets without total T3 or full T1 items 9-14; Zenodo 14848598 is a derived CSF/clinical/gait-summary table rather than raw wearable IMU; Fay-Karmon advanced-PD smartwatch monitoring and marital-dyad GeneActiv actigraphy are request-only small-N/schema-hidden rows; Luxembourg/NCER-PD upper-limb IMU is request-only and subitem-only observability context; Pre-QuantiPark/ActiMyo is request-only, N={prequantipark_refresh.get("n_pd")}, and levodopa-challenge trajectory data rather than stable cross-sectional severity; TUM Donié ROCKET/InceptionTime is public code over the same DUA-gated Hssayeni/MJFF route with task-level symptom labels and already-negative local algorithm families; ParaDigMa is software-only and would be a dead local scalar feature-addition route; Yin et al 2025 is request-only, N=20, schema-hidden, and likely gait-parameter/instrumented-walkway rather than raw WearGait-aligned IMU; Parkinson@Home is public/direct T3 but hard-stopped before scoring at N={parkinsonathome_refresh.get("hard_stop", {}).get("observed_valid_off_subjects")} vs the preregistered N&gt;=20 feature-readability rule; REMAP Bristol is controlled N=12 with range labels; Oxford OPDC/OxQUIP has no current public aligned IMU route; PD-BioStampRC21 is open but N=17 with forearm/chest/thigh sensors. None warrants another same-policy preregistration or download for the active T1/T3 CCC objective. PPP/PD-VME is a strong Verily-watch peer to PPMI, but remains RDSRC-gated and schema-hidden.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest wildcard negative.</strong> The iter40 local-residual smoother tested a non-tree Stage-2 residual map and still lost to the same-fold iter5 baseline before the target audit: baseline CCC {fmt_num(t3_iter40.get("baseline_metrics_seed_mean", {}).get("ccc"))}, wildcard CCC {fmt_num(t3_iter40.get("wildcard_metrics_seed_mean", {}).get("ccc"))}, delta {fmt_num(t3_iter40.get("seed_mean_delta_ccc"))}; strict gate {'PASS' if t3_iter40.get('promotion_gate', {}).get('strict_t3_gate_pass') else 'FAIL'}.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest corrected-target low-degree mixer negative.</strong> Iter50 tested a nested convex mix of A3 clinical-only Ridge and direct IMU-only/no-<code>cv_*</code> LGB on the valid-range N=95 T3 cohort. Baseline CCC {fmt_num(t3_iter50.get("mean_metrics", {}).get("baseline_seq_current", {}).get("ccc"))}; nested-convex CCC {fmt_num(t3_iter50.get("mean_metrics", {}).get("nested_convex", {}).get("ccc"))}; delta {fmt_num(t3_iter50.get("gate", {}).get("delta_seed_mean_predictions"))}; seed-delta std {fmt_num(t3_iter50.get("gate", {}).get("seed_delta_std"))}; bootstrap frac&gt;0 {fmt_num(t3_iter50.get("bootstrap_nested_convex_minus_baseline", {}).get("frac_gt_0"))}. Decision: <code>{html.escape(str(t3_iter50.get("decision")))}</code>.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest target-hygiene negative.</strong> The iter42 literature-backed primary Part III proration rule failed: <code>prorate_le3</code> LOOCV CCC {fmt_num(t3_iter42_cells[("prorate_le3", "stage2_current")]["new_refit_metrics"].get("ccc"))} current / {fmt_num(t3_iter42_cells[("prorate_le3", "stage2_no_cv")]["new_refit_metrics"].get("ccc"))} no-cv, with LOSO two-way {fmt_num(t3_iter42_loso_cells[("prorate_le3", "stage2_current")].get("two_way_mean_ccc"))}. The loose <code>prorate_le7</code> sensitivity reached internal CCC {fmt_num(t3_iter42_cells[("prorate_le7", "stage2_current")]["new_refit_metrics"].get("ccc"))}, but is not promotable because it includes a five-missing whole-rigidity-block row and was sensitivity-only.</p>
    </div>
    <div class="note warning">
      <p><strong>Latest framing audit.</strong> The iter41 clinical-dependency audit shows that T3 is not pure IMU: with Stage 2 stripped of hidden <code>cv_*</code> columns, A3 H&Y+intake reaches CCC {fmt_num(t3_clinical_policies["a3_hy_cv"]["mean_prediction_metrics"].get("ccc"))}, intake-only reaches {fmt_num(t3_clinical_policies["cv_only"]["mean_prediction_metrics"].get("ccc"))}, H&Y-only reaches {fmt_num(t3_clinical_policies["hy_only"]["mean_prediction_metrics"].get("ccc"))}, and intercept/IMU-only reaches {fmt_num(t3_clinical_policies["intercept_only"]["mean_prediction_metrics"].get("ccc"))}. Canonical T3 is now iter47 valid-range current Stage 2 at CCC {fmt_num(t3_current_metrics.get("ccc"))}; the clinical-dependency audit remains a framing diagnostic.</p>
    </div>
  </section>

  <section>
    <h2>Headline Metrics</h2>
    <h3>T1</h3>
    {table(["Target", "Status", "CCC", "MAE", "N", "Script"], t1_rows)}
    <h3>T3</h3>
    {table(["Target", "Status", "CCC", "MAE", "N", "Script"], t3_rows)}
  </section>

  <section>
    <h2>T1 Sit-With-Data Summary</h2>
    <div class="two-col">
      <div>
        <p>iter34 hybrid is the strongest T1 candidate: eight-item residual chain over items 9-14 plus auxiliary items 15 and 18, averaged across LGB, XGB-hist, and ExtraTrees.</p>
        {table(["Check", "Value"], [
            ["Bootstrap delta vs iter5", f"{fmt_num(t1_boot.get('delta_mean'))} [{fmt_num(t1_boot.get('delta_ci_low'))}, {fmt_num(t1_boot.get('delta_ci_high'))}]"],
            ["Frac above zero vs iter5", fmt_num(t1_boot.get("frac_above_zero"))],
            ["Audit P1 scrambled-label pass", str(t1_audit_verdict.get("P1_pass"))],
            ["Audit P2 noisy-test pass", str(t1_audit_verdict.get("P2_pass"))],
            ["Audit P4 pure-noise-X pass", str(t1_audit_verdict.get("P4_pass"))],
            ["Audit all pass", str(t1_audit_verdict.get("all_pass"))],
            ["P2 robustness max point delta", fmt_num(t1_p2_summary.get("delta_max"), 4)],
            ["P2 bootstrap upper max", fmt_num(t1_p2_summary.get("bootstrap_ci_high_max"), 4)],
            ["P2 leakage signal", str(t1_p2_verdict.get("p2_leakage_signal"))],
            ["iter46 ET-only CCC", fmt_num(t1_iter46.get("ccc"), 4)],
            ["iter46 delta vs iter34", fmt_num(t1_iter46_vs_iter34.get("delta_new_minus_comparator"), 4)],
            ["iter46 frac>0 vs iter12", fmt_num(t1_iter46_vs_iter12.get("bootstrap_delta", {}).get("frac_above_zero"), 4)],
            ["ET-only P2 bootstrap high in screen", fmt_num(t1_decomp_summary["combo_summary"]["et"]["p2_bootstrap_ci_high_max"], 4)],
            ["N=93 caveat subject", f"{t1_gap_subject.get('sid')} (T1={fmt_num(t1_gap_subject.get('t1_true'))}, missing item {', '.join(t1_gap_subject.get('missing_items', []))})"],
            ["Grid-optimal N=94 bound", fmt_num(t1_gap_grid.get("ccc"), 6)],
            ["Aux valid-range chain N", f"{t1_aux_valid.get('current_loader', {}).get('chain_n')} -> {t1_aux_valid.get('validated_loader', {}).get('chain_n')}"],
            ["Invalid aux subject", f"{t1_aux_invalid.get('sid')} item {t1_aux_invalid.get('item')}={fmt_num(t1_aux_invalid.get('value'), 1)} (valid max {fmt_num(t1_aux_invalid.get('valid_max'), 1)})"],
            ["Random-chain item15 exposure", f"{t1_aux_order_summary.get('iter34_lockbox_seed_count_with_exposure')}/{t1_aux_order_summary.get('iter34_lockbox_seed_count')} locked seeds"],
            ["Valid-vs-stale common CCC delta", fmt_num(t1_aux_order_impact.get("delta_valid_minus_stale_common_ccc"), 4)],
            ["Invalid T1 target items", str(len(t1_aux_valid.get("invalid_t1_target_items_in_current_t1_cohort", [])))],
        ])}
      </div>
      <div>
        <p>LOSO shows the candidate is not deployment-ready under site shift, despite the high internal LOOCV score.</p>
        {table(["Direction", "CCC", "MAE", "r"], t1_loso_rows)}
      </div>
    </div>
    <div class="gallery">
      {''.join(image_tile(path, title) for path, title in t1_figures)}
    </div>
  </section>

  <section>
    <h2>T3 Sit-With-Data Summary</h2>
    <p>The iter47 valid-range T3 result replaces the old iter5 headline and supersedes iter41: CCC {fmt_num(t3_current_metrics.get("ccc"))}, MAE {fmt_num(t3_current_metrics.get("mae"), 3)}, N={t3_current.get("n")}. The old iter5 deep-dive remains historical error anatomy only; its residual-vs-true correlation was {fmt_num(t3_deep.get("residual_corr_with_true"))}, with low severity over-predicted and high severity under-predicted.</p>
    <div class="two-col">
      <div>
        {table(["Quartile", "N", "True mean", "Pred mean", "Residual mean", "MAE"], t3_quartile_rows)}
      </div>
      <div>
        {table(["Site", "N", "CCC", "MAE", "r", "Bias"], t3_site_rows)}
        <h3>Current Conformal / Abstention</h3>
        {table(["Model", "Base CCC", "80% width", "95% width", "CCC after 50% deployable discard"], current_conformal_rows)}
        <h3>Historical Iter5 Conformal</h3>
        <p class="small">Target-contaminated iter5 uncertainty anatomy only; current reporting uses the table above.</p>
        {table(["Nominal", "Empirical", "Width", "N calib"], conformal_rows)}
      </div>
    </div>
    <h3>Corrected T3 Clinical Dependency</h3>
    <p>These cells use the iter41 all-missing-corrected N=95 target and remove hidden <code>cv_*</code> columns from Stage 2 for every policy. They predate the later NLS036 valid-range recode, so they are a decomposition/framing audit, not a replacement headline.</p>
    {table(["Stage 1 policy", "Full CCC", "Full MAE", "Stage1-only CCC", "Stage1-only MAE", "N"], clinical_rows)}
    <div class="gallery">
      {''.join(image_tile(path, title) for path, title in t3_figures)}
    </div>
  </section>

  <section>
    <h2>Artifact Manifest</h2>
    <p>The manifest JSON with file existence, sizes, and SHA-256 hashes is at <code>{html.escape(str(OUT_MANIFEST.relative_to(ROOT)))}</code>.</p>
    <p>The validated current manuscript export is <code>CURRENT_PAPER.html</code>. The legacy <code>NEW4.html</code> output is intentionally not listed as current evidence because it still contains stale pre-leakage narrative fragments.</p>
    {table(["Role", "Path", "Exists", "Bytes", "SHA-256 prefix"], artifact_rows)}
  </section>
</body>
</html>
"""
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {OUT_HTML.relative_to(ROOT)}")
    print(f"Wrote {OUT_MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
