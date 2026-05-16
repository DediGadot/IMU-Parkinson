#!/usr/bin/env python3
"""Audit `/tmp/pro-results.txt` coverage against concrete artifacts.

This is a completion-audit helper for the active objective:
"break the T1 + T3 CCC glass ceiling by following `/tmp/pro-results.txt`".

It is deliberately not a model run.  It maps each numbered recommendation in
the prompt to local evidence, distinguishes failed/blocked/secondary-only
routes from missing coverage, and reports whether the actual ceiling-break
success criterion has been met.
"""

from __future__ import annotations

import glob
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PROMPT = Path("/tmp/pro-results.txt")
OUT_JSON = RESULTS / "proresults_prompt_to_artifact_audit_20260515.json"
OUT_MD = RESULTS / "proresults_prompt_to_artifact_audit_20260515.md"

T1_CEILING = 0.7170
T3_CEILING = 0.3784
T1_MCID = 0.025
T3_MCID = 0.025
T1_SLOTD_COV70 = 0.7876
T1_SLOTD_COV50 = 0.8338
T3_SLOTF_COV70 = 0.4237
T3_SLOTF_COV50 = 0.5370
PROMOTION_FRAC_POS_MIN = 0.95
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}
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

ACTION_ID_BY_LIFECYCLE_ACTION = {
    "submit_access_request": "submit_ppmi_verily_access_request",
    "wait_for_access_approval": "wait_for_ppmi_verily_access_approval",
    "run_read_only_schema_probe": "run_ppmi_verily_read_only_schema_probe",
    "review_schema_probe_gates": "review_ppmi_verily_schema_probe_gates",
    "fix_access_evidence": "fix_ppmi_verily_access_evidence",
}

PROMPT_REQUIRED_SNIPPETS = [
    "Sum-aware multi-task Bayesian residual composer",
    "Target-free TopoFractal-8 compression",
    "Ordinal bounded item-distribution composer",
    "PPMI/Verily topology-first external transport",
    "Fixed PH/MFDFA micro-batch correction",
    "Stability-constrained sparse biomechanical score discovery",
    "Y-free item-level selective prediction",
    "TUG phase-specific PH/MFDFA microfeatures",
    "Fold-local sparse prototype regression",
    "K=250 sklearn Gradient Boosting",
    "Latent observable-T3 decomposition",
    "T3 unobservability-risk abstention",
    "Do rank #1",
    "PPMI/Verily topology-first external transport",
    "No y-test-dependent abstention",
    "No post-hoc cohort surgery",
    "No broad 952-feature omnibuses",
    "No internal T3 hyperparameter fishing",
    "No LOOCV reruns after observing multiple variants",
]

REJECTED_TEMPTATIONS = [
    {
        "id": "no_y_test_dependent_abstention",
        "prompt_snippet": "No y-test-dependent abstention",
        "evidence": [
            ("CLAUDE.md", "oracle metric"),
            ("CLAUDE.md", "y-free retention rule"),
            ("findings.md", "uses y_i at retention"),
        ],
    },
    {
        "id": "no_post_hoc_cohort_surgery",
        "prompt_snippet": "No post-hoc cohort surgery",
        "evidence": [
            ("findings.md", "post-hoc cohort surgery"),
            ("AGENTS.md", "do not run a post-hoc N=92 lockbox"),
        ],
    },
    {
        "id": "no_broad_952_feature_omnibuses",
        "prompt_snippet": "No broad 952-feature omnibuses",
        "evidence": [
            ("findings.md", "Omnibus 952-feature stack"),
            ("findings.md", "catastrophic overfit"),
        ],
    },
    {
        "id": "no_v2_pdcor_selection_model_rule",
        "prompt_snippet": "No V2 pdCor-selection as a model rule",
        "evidence": [
            ("findings.md", "V2 pdCor-selection on T1"),
            ("progress.md", "pdCor is a DESCRIPTIVENESS metric"),
        ],
    },
    {
        "id": "no_global_target_derived_selectors_or_rankers",
        "prompt_snippet": "No global target-derived selectors or rankers",
        "evidence": [
            ("AGENTS.md", "Never pre-compute XGBRanker ranks"),
            ("CLAUDE.md", "No global imputers"),
        ],
    },
    {
        "id": "no_unlabeled_encoder_reruns_without_new_data",
        "prompt_snippet": "No unlabeled encoder reruns without new architecture/data",
        "evidence": [
            ("AGENTS.md", "Frozen healthy-population-pretrained encoders are dead"),
            ("CLAUDE.md", "frozen MOMENT/HC-SSL/HARNet"),
        ],
    },
    {
        "id": "no_healthy_control_anchors_as_deployable_signal",
        "prompt_snippet": "No healthy-control anchors as deployable severity signal",
        "evidence": [
            ("AGENTS.md", "Healthy controls are diagnostic-only"),
            ("CLAUDE.md", "HC anchors HURT"),
        ],
    },
    {
        "id": "no_old_retracted_number_claims",
        "prompt_snippet": "No claims from old retracted T1/T3 numbers",
        "evidence": [
            ("AGENTS.md", "Retracted numbers"),
            ("CLAUDE.md", "Superseded/caveated values"),
        ],
    },
    {
        "id": "no_t3_clinical_label_oracle_features",
        "prompt_snippet": "No T3 clinical-label oracle corrections as deployable features",
        "evidence": [
            ("AGENTS.md", "Privileged oracles are large"),
            ("AGENTS.md", "not a deployable model"),
        ],
    },
    {
        "id": "no_internal_t3_hyperparameter_fishing",
        "prompt_snippet": "No internal T3 hyperparameter fishing",
        "evidence": [
            ("findings.md", "K=250 GB finding is retracted"),
            ("findings.md", "seed-shopping artifact"),
        ],
    },
    {
        "id": "no_per_item_cherry_picking_after_loocv",
        "prompt_snippet": "No per-item cherry-picking after LOOCV",
        "evidence": [
            ("AGENTS.md", "Composite-level cherry-picking ban"),
            ("CLAUDE.md", "No composite-level cherry-picking"),
        ],
    },
    {
        "id": "no_loocv_reruns_after_multiple_variants",
        "prompt_snippet": "No LOOCV reruns after observing multiple variants",
        "evidence": [
            ("CLAUDE.md", "Never re-run LOOCV across variants"),
            ("AGENTS.md", "pre-register exactly one winner"),
        ],
    },
]


def latest(pattern: str) -> Path | None:
    paths = [Path(p) for p in glob.glob(str(ROOT / pattern))]
    paths = [p for p in paths if p.is_file()]
    return sorted(paths)[-1] if paths else None


def latest_real(pattern: str) -> Path | None:
    paths = [Path(p) for p in glob.glob(str(ROOT / pattern))]
    paths = [
        p for p in paths
        if p.is_file()
        and "_scrambled_y" not in p.name
        and "_sid_shuffle" not in p.name
        and "_sanityYnan" not in p.name
    ]
    return sorted(paths)[-1] if paths else None


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - audit must fail closed, not crash
        return {"_load_error": str(exc), "_path": str(path)}


def load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - audit must fail closed
        return f"__LOAD_ERROR__ {exc}"


def prompt_source_metadata(text: str) -> dict[str, Any]:
    try:
        raw = PROMPT.read_bytes()
        read_bytes_ok = True
        read_bytes_error = None
    except Exception as exc:  # noqa: BLE001 - audit must fail closed
        raw = b""
        read_bytes_ok = False
        read_bytes_error = str(exc)
    return {
        "prompt_path": str(PROMPT),
        "exists": PROMPT.exists(),
        "read_ok": "__LOAD_ERROR__" not in text and read_bytes_ok,
        "read_bytes_error": read_bytes_error,
        "sha256": hashlib.sha256(raw).hexdigest() if read_bytes_ok else None,
        "byte_count": len(raw) if read_bytes_ok else None,
        "line_count": len(text.splitlines()) if "__LOAD_ERROR__" not in text else None,
    }


def rel(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def exists_rel(path: str) -> dict[str, Any]:
    p = ROOT / path
    return {"path": path, "exists": p.exists()}


def get_path(obj: dict[str, Any], *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def screen_summary(path: Path | None) -> dict[str, Any]:
    obj = load_json(path)
    ensemble = obj.get("ensemble_summary") or get_path(obj, "real_screen", "ensemble") or {}
    if not ensemble and obj.get("arms"):
        arms = obj["arms"]
        if isinstance(arms, list) and arms:
            ensemble = arms[0].get("ensemble", {})
    return {
        "path": rel(path),
        "exists": path is not None and path.exists(),
        "verdict": obj.get("verdict"),
        "n": obj.get("n") or obj.get("n_cohort"),
        "baseline_ccc": get_path(ensemble, "baseline", "ccc")
        or get_path(obj, "baseline", "ccc"),
        "candidate_ccc": get_path(ensemble, "candidate", "ccc")
        or get_path(ensemble, "decomposed_metrics", "ccc"),
        "delta_ccc": ensemble.get("delta_ccc") if isinstance(ensemble, dict) else None,
        "frac_positive": get_path(ensemble, "bootstrap", "frac_positive")
        or get_path(ensemble, "bootstrap", "frac_gt_0"),
        "gate_pass": get_path(obj, "promotion_gate", "gate_pass")
        or get_path(obj, "promotion_gate", "promotion_gate_pass"),
    }


def lockbox_arm_summary(path: Path | None, arm: str) -> dict[str, Any]:
    obj = load_json(path)
    arm_obj = get_path(obj, "arms", arm) or {}
    return {
        "path": rel(path),
        "exists": path is not None and path.exists(),
        "verdict": arm_obj.get("verdict") or obj.get("verdict"),
        "baseline_ccc": arm_obj.get("loocv_ccc_baseline"),
        "candidate_ccc": arm_obj.get("loocv_ccc_corrected"),
        "delta_ccc": arm_obj.get("delta_ccc"),
        "frac_positive": arm_obj.get("frac_pos_bootstrap"),
    }


def x4_equal_weight_2bag_summary(path: Path | None) -> dict[str, Any]:
    obj = load_json(path)
    bag = obj.get("bag") or {}
    seed_a = obj.get("bootstrap_seed_A") or {}
    seed_b = obj.get("bootstrap_seed_B") or {}
    frac_values = [
        float(v)
        for v in (seed_a.get("frac_pos"), seed_b.get("frac_pos"))
        if isinstance(v, (int, float))
    ]
    frac_min = min(frac_values) if frac_values else None
    delta_ccc = bag.get("delta_ccc")
    return {
        "path": rel(path),
        "exists": path is not None and path.exists(),
        "verdict": obj.get("verdict_provisional"),
        "n": obj.get("n_cohort"),
        "baseline_ccc": get_path(obj, "baselines", "loocv_ccc_iter34"),
        "candidate_ccc": bag.get("loocv_ccc"),
        "candidate_mae": bag.get("loocv_mae"),
        "delta_ccc": delta_ccc,
        "delta_mae": bag.get("delta_mae"),
        "delta_pearson_r": bag.get("delta_pearson_r"),
        "frac_positive": frac_min,
        "frac_positive_seed_A": seed_a.get("frac_pos"),
        "frac_positive_seed_B": seed_b.get("frac_pos"),
        "bootstrap_ci95_seed_A": seed_a.get("ci95"),
        "bootstrap_ci95_seed_B": seed_b.get("ci95"),
        "predictor_alignment_corr_v2_v3": obj.get("predictor_alignment_corr_v2_v3"),
        "fivefold_screen_mean_delta": get_path(obj, "fivefold_screen", "mean"),
        "passes_gate": bool(
            isinstance(delta_ccc, (int, float))
            and delta_ccc >= T1_MCID
            and isinstance(frac_min, (int, float))
            and frac_min >= PROMOTION_FRAC_POS_MIN
        ),
    }


def retained_summary(path: Path | None, source: str) -> dict[str, Any]:
    obj = load_json(path)
    if source == "s7":
        cov = obj.get("per_coverage_results", {})
        def best_s7_ccc(key: str) -> float | None:
            arms = cov.get(key, {}).get("arms", {})
            vals = [
                arm.get("S7_retained_ccc_with_item13_PH_correction")
                for arm in arms.values()
                if isinstance(arm, dict)
            ]
            vals = [float(v) for v in vals if isinstance(v, (int, float))]
            return max(vals) if vals else None
        return {
            "path": rel(path),
            "exists": path is not None and path.exists(),
            "verdict": obj.get("verdict"),
            "cov_70_best_ccc": best_s7_ccc("cov_70"),
            "cov_50_best_ccc": best_s7_ccc("cov_50"),
            "slotD_reference_cov70": obj.get("baseline_slotD_retained_ccc_cov_70") or T1_SLOTD_COV70,
            "slotD_reference_cov50": obj.get("baseline_slotD_retained_ccc_cov_50") or T1_SLOTD_COV50,
        }
    if source == "s12":
        cov = obj.get("retained_results", {})
        def best_ccc(key: str) -> float | None:
            row = cov.get(key, {})
            vals = [
                get_path(row, "iter47_locked_retained", "ccc"),
                get_path(row, "s11_direct_retained", "ccc"),
                get_path(row, "s11_decomp_retained", "ccc"),
            ]
            vals = [float(v) for v in vals if isinstance(v, (int, float))]
            return max(vals) if vals else None
        return {
            "path": rel(path),
            "exists": path is not None and path.exists(),
            "verdict": obj.get("verdict"),
            "cov_70_best_ccc": best_ccc("cov_70"),
            "cov_50_best_ccc": best_ccc("cov_50"),
            "slotF_reference_cov70": get_path(cov, "cov_70", "slotF_reference_retained_ccc") or T3_SLOTF_COV70,
            "slotF_reference_cov50": get_path(cov, "cov_50", "slotF_reference_retained_ccc") or T3_SLOTF_COV50,
            "beats_slotF_any": bool(
                get_path(cov, "cov_70", "beats_slotF_reference")
                or get_path(cov, "cov_50", "beats_slotF_reference")
            ),
            "monotone_50_ge_70": get_path(obj, "decision_checks", "monotone_50_ge_70"),
        }
    return {"path": rel(path), "exists": path is not None and path.exists()}


def s13_s15_summary(
    s13_path: Path | None,
    s15_path: Path | None,
    scrambled_path: Path | None,
    sid_shuffle_path: Path | None,
    sanity_path: Path | None,
) -> dict[str, Any]:
    s13 = load_json(s13_path)
    s15 = load_json(s15_path)
    scrambled = load_json(scrambled_path)
    sid_shuffle = load_json(sid_shuffle_path)
    sanity = load_json(sanity_path)

    cov70 = get_path(s15, "results", "cov_70", "s13JOINT_retain_by_corrJOINT_mag") or {}
    cov50 = get_path(s15, "results", "cov_50", "s13JOINT_retain_by_corrJOINT_mag") or {}
    return {
        "s13_path": rel(s13_path),
        "s15_bootstrap_path": rel(s15_path),
        "scrambled_y_path": rel(scrambled_path),
        "sid_shuffle_path": rel(sid_shuffle_path),
        "sanity_y_nan_path": rel(sanity_path),
        "exists": all(
            path is not None and path.exists()
            for path in (s13_path, s15_path, scrambled_path, sid_shuffle_path, sanity_path)
        ),
        "n_cohort": s13.get("n_cohort"),
        "fivefold_promotion": s13.get("fivefold_promotion"),
        "fivefold_screen_JOINT_mean": s13.get("fivefold_screen_JOINT_mean"),
        "fivefold_screen_JOINT_std": s13.get("fivefold_screen_JOINT_std"),
        "ph_only_delta": get_path(s13, "arms", "ph_only", "delta_ccc"),
        "ph_only_frac_positive": get_path(s13, "arms", "ph_only", "frac_pos_bootstrap"),
        "ph_only_verdict": get_path(s13, "arms", "ph_only", "verdict"),
        "mfdfa_only_delta": get_path(s13, "arms", "mfdfa_only", "delta_ccc"),
        "mfdfa_only_frac_positive": get_path(s13, "arms", "mfdfa_only", "frac_pos_bootstrap"),
        "mfdfa_only_verdict": get_path(s13, "arms", "mfdfa_only", "verdict"),
        "joint_delta": get_path(s13, "arms", "JOINT", "delta_ccc"),
        "joint_frac_positive": get_path(s13, "arms", "JOINT", "frac_pos_bootstrap"),
        "joint_verdict": get_path(s13, "arms", "JOINT", "verdict"),
        "scrambled_joint_delta": get_path(scrambled, "arms", "JOINT", "delta_ccc"),
        "scrambled_joint_frac_positive": get_path(scrambled, "arms", "JOINT", "frac_pos_bootstrap"),
        "sid_shuffle_joint_delta": get_path(sid_shuffle, "arms", "JOINT", "delta_ccc"),
        "sid_shuffle_joint_frac_positive": get_path(sid_shuffle, "arms", "JOINT", "frac_pos_bootstrap"),
        "sanity_y_nan_decision_y_free_cov70": get_path(
            sanity, "s15_abstention", "cov_70", "decision_is_y_free"
        ),
        "sanity_y_nan_decision_y_free_cov50": get_path(
            sanity, "s15_abstention", "cov_50", "decision_is_y_free"
        ),
        "s15_cov70_retained_ccc": cov70.get("ccc_retained"),
        "s15_cov70_delta_vs_full": cov70.get("delta_vs_full_cohort_iter47"),
        "s15_cov70_delta_vs_slotF": cov70.get("delta_vs_slotF_ref"),
        "s15_cov70_frac_positive": cov70.get("bootstrap_frac_pos_vs_full"),
        "s15_cov50_retained_ccc": cov50.get("ccc_retained"),
        "s15_cov50_delta_vs_full": cov50.get("delta_vs_full_cohort_iter47"),
        "s15_cov50_delta_vs_slotF": cov50.get("delta_vs_slotF_ref"),
        "s15_cov50_frac_positive": cov50.get("bootstrap_frac_pos_vs_full"),
    }


def external_status() -> dict[str, Any]:
    tracker = load_json(RESULTS / "access_submission_tracker_20260509.json")
    readiness = load_json(RESULTS / "external_access_readiness_audit_20260509.json")
    packet_validator = load_json(RESULTS / "access_request_packet_validator_audit_20260515.json")
    fill_checklist = load_json(RESULTS / "access_request_fill_checklist_audit_20260515.json")
    submission_index = load_json(RESULTS / "external_access_submission_index_audit_20260515.json")
    lifecycle_status = load_json(RESULTS / "external_access_lifecycle_status_audit_20260515.json")
    schema_handoff = load_json(RESULTS / "external_schema_probe_handoff_audit_20260515.json")
    schema_report_validator = load_json(
        RESULTS / "external_schema_probe_report_validator_audit_20260515.json"
    )
    target_free_manifest_validator = load_json(
        RESULTS / "external_target_free_manifest_validator_audit_20260515.json"
    )
    target_free_manifest_templates = load_json(
        RESULTS / "external_target_free_manifest_templates_audit_20260515.json"
    )
    zeroshot_blueprint_handoff = load_json(
        RESULTS / "external_zeroshot_blueprint_handoff_audit_20260515.json"
    )
    formula_sha_templates = load_json(
        RESULTS / "external_formula_sha_templates_audit_20260515.json"
    )
    zeroshot_result_templates = load_json(
        RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
    )
    formula_ppmi = (
        formula_sha_templates.get("route_results", {}).get("ppmi_verily", {})
        if isinstance(formula_sha_templates.get("route_results"), dict)
        else {}
    )
    zeroshot_result_ppmi = (
        zeroshot_result_templates.get("route_results", {}).get("ppmi_verily", {})
        if isinstance(zeroshot_result_templates.get("route_results"), dict)
        else {}
    )
    queue_status = load_json(RESULTS / "external_access_queue_status_audit_20260515.json")
    submission_index_workflow_check = next(
        (
            row
            for row in submission_index.get("checks", [])
            if row.get("name") == "every route exposes an ordered workflow command sequence"
        ),
        {},
    )
    lifecycle_status_workflow_check = next(
        (
            row
            for row in lifecycle_status.get("checks", [])
            if row.get("name")
            == "every route exposes an ordered lifecycle workflow command sequence"
        ),
        {},
    )
    schema_handoff_workflow_check = next(
        (
            row
            for row in schema_handoff.get("checks", [])
            if row.get("name")
            == "every route exposes an ordered post-approval workflow sequence"
        ),
        {},
    )
    target_free_templates_workflow_check = next(
        (
            row
            for row in target_free_manifest_templates.get("checks", [])
            if row.get("name")
            == "every route exposes an ordered post-schema workflow sequence"
        ),
        {},
    )
    formula_sha_templates_workflow_check = next(
        (
            row
            for row in formula_sha_templates.get("checks", [])
            if row.get("name")
            == "every route exposes an ordered post-formula workflow sequence"
        ),
        {},
    )
    zeroshot_result_templates_workflow_check = next(
        (
            row
            for row in zeroshot_result_templates.get("checks", [])
            if row.get("name")
            == "every route exposes an ordered post-score reporting workflow sequence"
        ),
        {},
    )
    queue_ppmi_gates = queue_status.get("ppmi_post_approval_contract_gates") or {}
    queue_ppmi_formula_gate = queue_ppmi_gates.get("formula_sha_record") or {}
    queue_ppmi_result_gate = queue_ppmi_gates.get("zeroshot_result_record") or {}
    approvals = sorted((ROOT / ".access_approvals").glob("*.json")) if (ROOT / ".access_approvals").exists() else []
    real_approvals = [
        p.name for p in approvals
        if "audit" not in p.name and "schema_probe_recorder" not in p.name
    ]
    return {
        "access_submission_tracker": "results/access_submission_tracker_20260509.json",
        "external_access_readiness": "results/external_access_readiness_audit_20260509.json",
        "submit_ready_route_count": get_path(tracker, "summary", "submit_ready_route_count"),
        "compute_ready_route_count": get_path(tracker, "summary", "compute_ready_route_count"),
        "blocked_actions_now": get_path(tracker, "summary", "blocked_actions_now"),
        "top_priority_route": get_path(tracker, "summary", "top_priority_route")
        or get_path(readiness, "summary", "top_priority_route"),
        "non_audit_approval_records": real_approvals,
        "has_non_audit_approval": bool(real_approvals),
        "readiness_decision": readiness.get("decision"),
        "generic_packet_validator": "scripts/validate_access_request_packet.py",
        "generic_packet_validator_audit": "results/access_request_packet_validator_audit_20260515.json",
        "generic_packet_validator_decision": packet_validator.get("decision"),
        "generic_packet_validator_route_count": len(packet_validator.get("route_results", {})),
        "generic_packet_validator_hard_failures": packet_validator.get("hard_failures"),
        "generic_packet_validator_content_free": (
            packet_validator.get("not_a_submission_record") is True
            and packet_validator.get("not_access_approval") is True
            and packet_validator.get("not_a_schema_probe_artifact") is True
            and packet_validator.get("not_a_model_result") is True
            and packet_validator.get("protected_data_included") is False
            and packet_validator.get("credentials_or_tokens_included") is False
        ),
        "generic_fill_checklist": "scripts/show_access_request_fill_checklist.py",
        "generic_fill_checklist_audit": "results/access_request_fill_checklist_audit_20260515.json",
        "generic_fill_checklist_decision": fill_checklist.get("decision"),
        "generic_fill_checklist_route_count": fill_checklist.get("route_count"),
        "generic_fill_checklist_hard_failures": fill_checklist.get("hard_failures"),
        "generic_fill_checklist_content_free": (
            fill_checklist.get("not_a_submission_record") is True
            and fill_checklist.get("not_access_approval") is True
            and fill_checklist.get("not_a_schema_probe_artifact") is True
            and fill_checklist.get("not_a_feature_manifest_artifact") is True
            and fill_checklist.get("not_a_model_result") is True
            and fill_checklist.get("protected_data_included") is False
            and fill_checklist.get("credentials_or_tokens_included") is False
        ),
        "external_submission_index": "results/external_access_submission_index_20260515.md",
        "external_submission_index_writer": "scripts/write_external_access_submission_index.py",
        "external_submission_index_audit": (
            "results/external_access_submission_index_audit_20260515.json"
        ),
        "external_submission_index_decision": submission_index.get("decision"),
        "external_submission_index_hard_failures": submission_index.get("hard_failures"),
        "external_submission_index_content_free": (
            submission_index.get("not_a_submission_record") is True
            and submission_index.get("not_access_approval") is True
            and submission_index.get("not_a_schema_probe_artifact") is True
            and submission_index.get("not_a_feature_manifest_artifact") is True
            and submission_index.get("not_a_model_result") is True
            and submission_index.get("protected_data_included") is False
            and submission_index.get("credentials_or_tokens_included") is False
        ),
        "external_submission_index_workflow_sequence_check": submission_index_workflow_check.get(
            "passed"
        ),
        "external_submission_index_workflow_by_route": (
            submission_index_workflow_check.get("evidence", {}).get("workflow_by_route")
        ),
        "external_lifecycle_status": "scripts/show_external_access_lifecycle.py",
        "external_lifecycle_status_audit": (
            "results/external_access_lifecycle_status_audit_20260515.json"
        ),
        "external_lifecycle_status_decision": lifecycle_status.get("decision"),
        "external_lifecycle_status_hard_failures": lifecycle_status.get("hard_failures"),
        "external_lifecycle_status_content_free": (
            lifecycle_status.get("not_a_submission_record") is True
            and lifecycle_status.get("not_access_approval") is True
            and lifecycle_status.get("not_a_schema_probe_artifact") is True
            and lifecycle_status.get("not_a_model_result") is True
            and lifecycle_status.get("protected_data_included") is False
            and lifecycle_status.get("credentials_or_tokens_included") is False
        ),
        "external_lifecycle_status_workflow_sequence_check": lifecycle_status_workflow_check.get(
            "passed"
        ),
        "external_lifecycle_status_workflow_by_route": (
            lifecycle_status_workflow_check.get("evidence", {}).get(
                "default_workflow_by_route"
            )
        ),
        "external_schema_probe_handoff": "results/external_schema_probe_handoff_20260515.md",
        "external_schema_probe_handoff_writer": (
            "scripts/write_external_schema_probe_handoff.py"
        ),
        "external_schema_probe_handoff_audit": (
            "results/external_schema_probe_handoff_audit_20260515.json"
        ),
        "external_schema_probe_handoff_decision": schema_handoff.get("decision"),
        "external_schema_probe_handoff_route_count": schema_handoff.get("route_count"),
        "external_schema_probe_handoff_hard_failures": schema_handoff.get("hard_failures"),
        "external_schema_probe_handoff_content_free": (
            schema_handoff.get("not_a_submission_record") is True
            and schema_handoff.get("not_access_approval") is True
            and schema_handoff.get("not_a_schema_probe_artifact") is True
            and schema_handoff.get("not_a_feature_manifest_artifact") is True
            and schema_handoff.get("not_a_preregistration") is True
            and schema_handoff.get("not_a_model_result") is True
            and schema_handoff.get("protected_data_included") is False
            and schema_handoff.get("credentials_or_tokens_included") is False
        ),
        "external_schema_probe_handoff_post_approval_workflow_check": (
            schema_handoff_workflow_check.get("passed")
        ),
        "external_schema_probe_handoff_post_approval_workflow_by_route": (
            schema_handoff_workflow_check.get("evidence", {}).get("workflow_by_route")
        ),
        "generic_schema_probe_report_validator": "scripts/validate_schema_probe_report.py",
        "generic_schema_probe_report_validator_audit": (
            "results/external_schema_probe_report_validator_audit_20260515.json"
        ),
        "generic_schema_probe_report_validator_decision": schema_report_validator.get("decision"),
        "generic_schema_probe_report_validator_route_count": len(
            schema_report_validator.get("route_results", {})
        ),
        "generic_schema_probe_report_validator_hard_failures": schema_report_validator.get(
            "hard_failures"
        ),
        "generic_schema_probe_report_validator_content_free": (
            schema_report_validator.get("not_a_submission_record") is True
            and schema_report_validator.get("not_access_approval") is True
            and schema_report_validator.get("not_a_schema_probe_artifact") is True
            and schema_report_validator.get("not_a_model_result") is True
            and schema_report_validator.get("protected_data_included") is False
            and schema_report_validator.get("credentials_or_tokens_included") is False
        ),
        "generic_target_free_manifest_validator": "scripts/validate_target_free_manifest.py",
        "generic_target_free_manifest_validator_audit": (
            "results/external_target_free_manifest_validator_audit_20260515.json"
        ),
        "generic_target_free_manifest_validator_decision": target_free_manifest_validator.get("decision"),
        "generic_target_free_manifest_validator_route_count": len(
            target_free_manifest_validator.get("route_results", {})
        ),
        "generic_target_free_manifest_validator_hard_failures": target_free_manifest_validator.get(
            "hard_failures"
        ),
        "generic_target_free_manifest_validator_content_free": (
            target_free_manifest_validator.get("not_a_submission_record") is True
            and target_free_manifest_validator.get("not_access_approval") is True
            and target_free_manifest_validator.get("not_a_schema_probe_artifact") is True
            and target_free_manifest_validator.get("not_a_preregistration") is True
            and target_free_manifest_validator.get("not_a_feature_manifest_artifact") is True
            and target_free_manifest_validator.get("not_a_model_result") is True
            and target_free_manifest_validator.get("protected_data_included") is False
            and target_free_manifest_validator.get("credentials_or_tokens_included") is False
        ),
        "external_target_free_manifest_templates": (
            "results/external_target_free_manifest_templates_20260515.md"
        ),
        "external_target_free_manifest_templates_writer": (
            "scripts/write_external_target_free_manifest_templates.py"
        ),
        "external_target_free_manifest_templates_audit": (
            "results/external_target_free_manifest_templates_audit_20260515.json"
        ),
        "external_target_free_manifest_templates_decision": (
            target_free_manifest_templates.get("decision")
        ),
        "external_target_free_manifest_templates_route_count": (
            target_free_manifest_templates.get("route_count")
        ),
        "external_target_free_manifest_templates_hard_failures": (
            target_free_manifest_templates.get("hard_failures")
        ),
        "external_target_free_manifest_templates_content_free": (
            target_free_manifest_templates.get("not_a_submission_record") is True
            and target_free_manifest_templates.get("not_access_approval") is True
            and target_free_manifest_templates.get("not_a_schema_probe_artifact") is True
            and target_free_manifest_templates.get("not_a_preregistration") is True
            and target_free_manifest_templates.get("not_a_feature_manifest_artifact") is True
            and target_free_manifest_templates.get("not_a_model_result") is True
            and target_free_manifest_templates.get("protected_data_included") is False
            and target_free_manifest_templates.get("credentials_or_tokens_included") is False
        ),
        "external_target_free_manifest_templates_post_schema_workflow_check": (
            target_free_templates_workflow_check.get("passed")
        ),
        "external_target_free_manifest_templates_post_schema_workflow_by_route": (
            target_free_templates_workflow_check.get("evidence", {}).get("workflow_by_route")
        ),
        "external_zeroshot_blueprint_handoff": (
            "results/external_zeroshot_blueprint_handoff_20260515.md"
        ),
        "external_zeroshot_blueprint_handoff_writer": (
            "scripts/write_external_zeroshot_blueprint_handoff.py"
        ),
        "external_zeroshot_blueprint_handoff_audit": (
            "results/external_zeroshot_blueprint_handoff_audit_20260515.json"
        ),
        "external_zeroshot_blueprint_handoff_decision": (
            zeroshot_blueprint_handoff.get("decision")
        ),
        "external_zeroshot_blueprint_handoff_route_count": (
            zeroshot_blueprint_handoff.get("route_count")
        ),
        "external_zeroshot_blueprint_handoff_hard_failures": (
            zeroshot_blueprint_handoff.get("hard_failures")
        ),
        "external_zeroshot_blueprint_handoff_content_free": (
            zeroshot_blueprint_handoff.get("not_a_submission_record") is True
            and zeroshot_blueprint_handoff.get("not_access_approval") is True
            and zeroshot_blueprint_handoff.get("not_a_schema_probe_artifact") is True
            and zeroshot_blueprint_handoff.get("not_a_preregistration") is True
            and zeroshot_blueprint_handoff.get("not_a_feature_manifest_artifact") is True
            and zeroshot_blueprint_handoff.get("not_a_model_result") is True
            and zeroshot_blueprint_handoff.get("protected_data_included") is False
            and zeroshot_blueprint_handoff.get("credentials_or_tokens_included") is False
        ),
        "external_formula_sha_templates": "results/external_formula_sha_templates_20260515.md",
        "external_formula_sha_templates_writer": (
            "scripts/write_external_formula_sha_templates.py"
        ),
        "external_formula_sha_record_validator": (
            "scripts/validate_external_formula_sha_record.py"
        ),
        "external_formula_sha_templates_audit": (
            "results/external_formula_sha_templates_audit_20260515.json"
        ),
        "external_formula_sha_templates_decision": formula_sha_templates.get("decision"),
        "external_formula_sha_templates_route_count": formula_sha_templates.get("route_count"),
        "external_formula_sha_templates_hard_failures": formula_sha_templates.get(
            "hard_failures"
        ),
        "external_formula_sha_templates_content_free": (
            formula_sha_templates.get("not_a_submission_record") is True
            and formula_sha_templates.get("not_access_approval") is True
            and formula_sha_templates.get("not_a_schema_probe_artifact") is True
            and formula_sha_templates.get("not_a_preregistration") is True
            and formula_sha_templates.get("not_a_feature_manifest_artifact") is True
            and formula_sha_templates.get("not_a_model_result") is True
            and formula_sha_templates.get("protected_data_included") is False
            and formula_sha_templates.get("credentials_or_tokens_included") is False
        ),
        "external_formula_sha_templates_post_formula_workflow_check": (
            formula_sha_templates_workflow_check.get("passed")
        ),
        "external_formula_sha_templates_post_formula_workflow_by_route": (
            formula_sha_templates_workflow_check.get("evidence", {}).get("workflow_by_route")
        ),
        "external_formula_sha_ppmi_contract_present": formula_ppmi.get(
            "ppmi_formula_contract_present"
        ),
        "external_formula_sha_ppmi_contract_negative_failed": formula_ppmi.get(
            "ppmi_contract_negative_failed"
        ),
        "external_formula_sha_ppmi_bad_contract_hard_failures": formula_ppmi.get(
            "ppmi_bad_contract_hard_failures"
        ),
        "external_queue_ppmi_formula_x4_policy": queue_ppmi_formula_gate.get(
            "x4_v3_gsp_compatibility_policy"
        ),
        "external_zeroshot_result_templates": (
            "results/external_zeroshot_result_templates_20260515.md"
        ),
        "external_zeroshot_result_templates_writer": (
            "scripts/write_external_zeroshot_result_templates.py"
        ),
        "external_zeroshot_result_record_validator": (
            "scripts/validate_external_zeroshot_result_record.py"
        ),
        "external_zeroshot_result_templates_audit": (
            "results/external_zeroshot_result_templates_audit_20260515.json"
        ),
        "external_zeroshot_result_templates_decision": (
            zeroshot_result_templates.get("decision")
        ),
        "external_zeroshot_result_templates_route_count": (
            zeroshot_result_templates.get("route_count")
        ),
        "external_zeroshot_result_templates_hard_failures": (
            zeroshot_result_templates.get("hard_failures")
        ),
        "external_zeroshot_result_templates_content_free": (
            zeroshot_result_templates.get("not_a_submission_record") is True
            and zeroshot_result_templates.get("not_access_approval") is True
            and zeroshot_result_templates.get("not_a_schema_probe_artifact") is True
            and zeroshot_result_templates.get("not_a_preregistration") is True
            and zeroshot_result_templates.get("not_a_feature_manifest_artifact") is True
            and zeroshot_result_templates.get("not_a_model_result") is True
            and zeroshot_result_templates.get("protected_data_included") is False
            and zeroshot_result_templates.get("credentials_or_tokens_included") is False
        ),
        "external_zeroshot_result_templates_post_score_workflow_check": (
            zeroshot_result_templates_workflow_check.get("passed")
        ),
        "external_zeroshot_result_templates_post_score_workflow_by_route": (
            zeroshot_result_templates_workflow_check.get("evidence", {}).get(
                "workflow_by_route"
            )
        ),
        "external_zeroshot_result_ppmi_contract_present": zeroshot_result_ppmi.get(
            "ppmi_result_contract_present"
        ),
        "external_zeroshot_result_ppmi_contract_negative_failed": (
            zeroshot_result_ppmi.get("ppmi_contract_negative_failed")
        ),
        "external_zeroshot_result_ppmi_bad_contract_hard_failures": (
            zeroshot_result_ppmi.get("ppmi_bad_contract_hard_failures")
        ),
        "external_queue_ppmi_result_x4_policy": queue_ppmi_result_gate.get(
            "x4_v3_gsp_compatibility_policy"
        ),
        "external_queue_status": "scripts/show_external_access_queue.py",
        "external_queue_status_audit": "results/external_access_queue_status_audit_20260515.json",
        "external_queue_status_decision": queue_status.get("decision"),
        "external_queue_status_content_boundary": queue_status.get("content_boundary"),
    }


def get_prompt_requirements() -> dict[str, Any]:
    text = load_text(PROMPT)
    missing = [snippet for snippet in PROMPT_REQUIRED_SNIPPETS if snippet not in text]
    rank_headers = [f"### {i}." for i in range(1, 13)]
    missing_rank_headers = [header for header in rank_headers if header not in text]
    source = prompt_source_metadata(text)
    return {
        **source,
        "required_snippet_count": len(PROMPT_REQUIRED_SNIPPETS),
        "missing_required_snippets": missing,
        "missing_rank_headers": missing_rank_headers,
        "mentions_promotion_delta_0025": "delta ≥ +0.025" in text or "delta >= +0.025" in text,
        "mentions_frac_positive_095": "frac>0 ≥ 0.95" in text or "frac>0 >= 0.95" in text,
        "mentions_five_null_gate": "five-null gate" in text,
    }


def build_rejected_temptation_guard() -> list[dict[str, Any]]:
    prompt_text = load_text(PROMPT)
    text_cache: dict[str, str] = {"/tmp/pro-results.txt": prompt_text}
    checks = []
    for rule in REJECTED_TEMPTATIONS:
        evidence_hits = []
        missing_evidence = []
        for rel_path, snippet in rule["evidence"]:
            if rel_path not in text_cache:
                text_cache[rel_path] = load_text(ROOT / rel_path)
            hit = snippet in text_cache[rel_path]
            if hit:
                evidence_hits.append({"path": rel_path, "snippet": snippet})
            else:
                missing_evidence.append({"path": rel_path, "snippet": snippet})
        prompt_present = rule["prompt_snippet"] in prompt_text
        checks.append(
            {
                "id": rule["id"],
                "prompt_snippet": rule["prompt_snippet"],
                "prompt_present": prompt_present,
                "evidence_hits": evidence_hits,
                "missing_evidence": missing_evidence,
                "passed": prompt_present and bool(evidence_hits) and not missing_evidence,
            }
        )
    return checks


def below_gate(row: dict[str, Any]) -> bool:
    ev = row["evidence"]
    delta = ev.get("delta_ccc")
    frac = ev.get("frac_positive")
    gate_pass = ev.get("gate_pass")
    if gate_pass is False:
        return True
    if isinstance(delta, (int, float)) and delta < T1_MCID:
        return True
    if isinstance(frac, (int, float)) and frac < PROMOTION_FRAC_POS_MIN:
        return True
    return False


def t1_retained_below_reference(ev: dict[str, Any]) -> bool:
    return (
        isinstance(ev.get("cov_70_best_ccc"), (int, float))
        and isinstance(ev.get("cov_50_best_ccc"), (int, float))
        and ev["cov_70_best_ccc"] < ev.get("slotD_reference_cov70", T1_SLOTD_COV70)
        and ev["cov_50_best_ccc"] < ev.get("slotD_reference_cov50", T1_SLOTD_COV50)
    )


def t3_retained_below_reference(ev: dict[str, Any]) -> bool:
    return (
        isinstance(ev.get("cov_70_best_ccc"), (int, float))
        and isinstance(ev.get("cov_50_best_ccc"), (int, float))
        and ev["cov_70_best_ccc"] < ev.get("slotF_reference_cov70", T3_SLOTF_COV70)
        and ev["cov_50_best_ccc"] < ev.get("slotF_reference_cov50", T3_SLOTF_COV50)
        and ev.get("beats_slotF_any") is False
    )


def num_lt(value: Any, threshold: float) -> bool:
    return isinstance(value, (int, float)) and value < threshold


def build_completion_checklist(
    numbered: list[dict[str, Any]],
    access: dict[str, Any],
    slotf_replication_audit: dict[str, Any],
    s13_s15: dict[str, Any],
    ppmi_submit_format_audit: dict[str, Any],
    ppmi_email_template_audit: dict[str, Any],
    ppmi_email_validator_audit: dict[str, Any],
    ppmi_package_validator_audit: dict[str, Any],
    ppmi_schema_probe_checklist_audit: dict[str, Any],
    ppmi_schema_probe_template_audit: dict[str, Any],
    ppmi_schema_probe_report_validator_audit: dict[str, Any],
    ppmi_target_free_manifest_validator_audit: dict[str, Any],
    ppmi_completed_packet_validator_audit: dict[str, Any],
    ppmi_next_action_status_audit: dict[str, Any],
    ppmi_submission_bundle: dict[str, Any],
    ppmi_current_submission_handoff: dict[str, Any],
    ppmi_zeroshot_blueprint_audit: dict[str, Any],
    current_state_verification: dict[str, Any],
    current_next_action_handoff: dict[str, Any],
) -> list[dict[str, Any]]:
    by_rank = {row["rank"]: row for row in numbered}
    prompt = get_prompt_requirements()
    s6 = by_rank[6]["evidence"]
    s8 = by_rank[8]["evidence"]
    rank10 = by_rank[10]["evidence"]
    rank11 = by_rank[11]["evidence"]
    current_lifecycle_action = current_state_verification.get(
        "access_lifecycle_current_action"
    ) or {}
    lifecycle_action = current_lifecycle_action.get("action")
    expected_lifecycle_action_id = ACTION_ID_BY_LIFECYCLE_ACTION.get(lifecycle_action)
    packet_ready_state = lifecycle_action == "submit_access_request"

    checks = [
        {
            "id": "prompt_file_loaded",
            "passed": prompt["exists"] and prompt["read_ok"],
            "evidence": prompt,
        },
        {
            "id": "all_12_numbered_recommendations_present_in_prompt",
            "passed": not prompt["missing_rank_headers"] and not prompt["missing_required_snippets"],
            "evidence": prompt,
        },
        {
            "id": "prompt_gate_terms_are_explicit",
            "passed": (
                prompt["mentions_promotion_delta_0025"]
                and prompt["mentions_frac_positive_095"]
                and prompt["mentions_five_null_gate"]
            ),
            "evidence": prompt,
        },
        {
            "id": "rank1_to_rank3_internal_t1_screens_failed_below_promotion_gate",
            "passed": all(below_gate(by_rank[i]) for i in (1, 2, 3)),
            "evidence": {str(i): by_rank[i]["evidence"] for i in (1, 2, 3)},
        },
        {
            "id": "rank4_ppmi_verily_external_route_is_access_blocked_but_packeted",
            "passed": (
                access.get("compute_ready_route_count") == 0
                and access.get("has_non_audit_approval") is False
                and (ROOT / "scripts/ppmi_verily_tier3_request_packet.md").exists()
                and (RESULTS / "ppmi_verily_request_packet_audit_20260509.json").exists()
                and (RESULTS / "ppmi_verily_tier3_request_packet_template_20260515.docx").exists()
                and ppmi_submit_format_audit.get("passed") is True
                and ppmi_submit_format_audit.get("decision") == "ppmi_verily_word_template_ready_to_fill"
                and (ROOT / "scripts/ppmi_verily_submission_email_template.md").exists()
                and ppmi_email_template_audit.get("passed") is True
                and ppmi_email_template_audit.get("decision") == "ppmi_verily_submission_email_template_ready"
                and (ROOT / "scripts/validate_ppmi_verily_submission_email.py").exists()
                and ppmi_email_validator_audit.get("passed") is True
                and ppmi_email_validator_audit.get("decision")
                == "ppmi_verily_submission_email_validator_ready"
                and ppmi_email_validator_audit.get("validator")
                == "scripts/validate_ppmi_verily_submission_email.py"
                and any(
                    row.get("name") == "validator output does not echo completed email path or filename"
                    and row.get("passed") is True
                    for row in ppmi_email_validator_audit.get("checks", [])
                )
                and (ROOT / "scripts/validate_ppmi_verily_submission_package.py").exists()
                and ppmi_package_validator_audit.get("passed") is True
                and ppmi_package_validator_audit.get("decision")
                == "ppmi_verily_submission_package_validator_ready"
                and ppmi_package_validator_audit.get("validator")
                == "scripts/validate_ppmi_verily_submission_package.py"
                and ppmi_package_validator_audit.get("not_a_submission_record") is True
                and ppmi_package_validator_audit.get("not_access_approval") is True
                and ppmi_package_validator_audit.get("not_a_model_result") is True
                and ppmi_package_validator_audit.get("protected_data_included") is False
                and ppmi_package_validator_audit.get("credentials_or_tokens_included") is False
                and any(
                    row.get("name") == "validator output does not echo package paths or filenames"
                    and row.get("passed") is True
                    for row in ppmi_package_validator_audit.get("checks", [])
                )
                and (ROOT / "scripts/ppmi_verily_schema_probe_checklist.md").exists()
                and ppmi_schema_probe_checklist_audit.get("passed") is True
                and ppmi_schema_probe_checklist_audit.get("decision")
                == "ppmi_verily_schema_probe_checklist_ready"
                and ppmi_schema_probe_checklist_audit.get("schema_probe_artifact_created") is False
                and ppmi_schema_probe_checklist_audit.get("protected_data_included") is False
                and (ROOT / "scripts/ppmi_verily_schema_probe_report_template.md").exists()
                and ppmi_schema_probe_template_audit.get("passed") is True
                and ppmi_schema_probe_template_audit.get("decision")
                == "ppmi_verily_schema_probe_report_template_ready"
                and ppmi_schema_probe_template_audit.get("template")
                == "scripts/ppmi_verily_schema_probe_report_template.md"
                and ppmi_schema_probe_template_audit.get("schema_probe_artifact_created") is False
                and ppmi_schema_probe_template_audit.get("protected_data_included") is False
                and (ROOT / "scripts/validate_ppmi_verily_schema_probe_report.py").exists()
                and ppmi_schema_probe_report_validator_audit.get("passed") is True
                and ppmi_schema_probe_report_validator_audit.get("decision")
                == "ppmi_verily_schema_probe_report_validator_ready"
                and ppmi_schema_probe_report_validator_audit.get("validator")
                == "scripts/validate_ppmi_verily_schema_probe_report.py"
                and ppmi_schema_probe_report_validator_audit.get("not_a_schema_probe_artifact") is True
                and ppmi_schema_probe_report_validator_audit.get("protected_data_included") is False
                and (ROOT / "scripts/ppmi_verily_target_free_manifest_template.json").exists()
                and (ROOT / "scripts/validate_ppmi_verily_target_free_manifest.py").exists()
                and ppmi_target_free_manifest_validator_audit.get("passed") is True
                and ppmi_target_free_manifest_validator_audit.get("decision")
                == "ppmi_verily_target_free_manifest_validator_ready"
                and ppmi_target_free_manifest_validator_audit.get("template")
                == "scripts/ppmi_verily_target_free_manifest_template.json"
                and ppmi_target_free_manifest_validator_audit.get("validator")
                == "scripts/validate_ppmi_verily_target_free_manifest.py"
                and ppmi_target_free_manifest_validator_audit.get("not_a_feature_manifest_artifact")
                is True
                and ppmi_target_free_manifest_validator_audit.get("not_a_schema_probe_artifact")
                is True
                and ppmi_target_free_manifest_validator_audit.get("not_a_preregistration") is True
                and ppmi_target_free_manifest_validator_audit.get("protected_data_included") is False
                and (ROOT / "scripts/validate_ppmi_verily_completed_packet.py").exists()
                and ppmi_completed_packet_validator_audit.get("passed") is True
                and ppmi_completed_packet_validator_audit.get("decision")
                == "ppmi_verily_completed_packet_validator_ready"
                and (ROOT / "scripts/show_ppmi_verily_next_action.py").exists()
                and ppmi_next_action_status_audit.get("passed") is True
                and ppmi_next_action_status_audit.get("decision")
                == "ppmi_verily_next_action_status_ready"
                and ppmi_next_action_status_audit.get("source_audit")
                == "results/access_lifecycle_state_handoff_20260515.json"
                and ppmi_next_action_status_audit.get("current_submission_handoff")
                == "results/ppmi_verily_current_submission_handoff_20260515.json"
                and ppmi_next_action_status_audit.get("content_boundary", {}).get(
                    "record_paths_reported"
                )
                is False
                and ppmi_next_action_status_audit.get("content_boundary", {}).get(
                    "protected_data_included"
                )
                is False
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
                and ppmi_submission_bundle.get("content_boundary", {}).get(
                    "completed_packet_included"
                )
                is False
                and ppmi_submission_bundle.get("content_boundary", {}).get(
                    "completed_email_included"
                )
                is False
                and ppmi_submission_bundle.get("content_boundary", {}).get(
                    "protected_data_included"
                )
                is False
                and ppmi_submission_bundle.get("content_boundary", {}).get(
                    "credentials_or_tokens_included"
                )
                is False
                and ppmi_submission_bundle.get("content_boundary", {}).get(
                    "local_completed_paths_reported"
                )
                is False
                and ppmi_submission_bundle.get("fill_fields", {}).get("source_checklist")
                == "scripts/ppmi_verily_user_fill_checklist.md"
                and ppmi_submission_bundle.get("fill_fields", {}).get("packet_field_count")
                == 13
                and ppmi_submission_bundle.get("fill_fields", {}).get("email_field_count")
                == 12
                and ppmi_submission_bundle.get("fill_fields", {}).get("submission_metadata_field_count")
                == 4
                and any(
                    step.get("step_id") == "preflight_completed_package"
                    and "scripts/validate_ppmi_verily_submission_package.py"
                    in step.get("tools", [])
                    for step in ppmi_submission_bundle.get("next_steps", [])
                )
                and (
                    not packet_ready_state
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
                        and ppmi_current_submission_handoff.get("fill_fields", {}).get("packet_field_count")
                        == 13
                        and ppmi_current_submission_handoff.get("fill_fields", {}).get("email_field_count")
                        == 12
                        and ppmi_current_submission_handoff.get("fill_fields", {}).get("submission_metadata_field_count")
                        == 4
                        and ppmi_current_submission_handoff.get("current_action", {}).get("action_id")
                        == "submit_ppmi_verily_access_request"
                        and ppmi_current_submission_handoff.get("current_action", {}).get(
                            "safe_to_execute_code_now"
                        )
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
                and ppmi_zeroshot_blueprint_audit.get("decision")
                == "ppmi_verily_zeroshot_blueprint_ready"
                and ppmi_zeroshot_blueprint_audit.get("not_a_model_result") is True
                and ppmi_zeroshot_blueprint_audit.get("not_access_approval") is True
                and ppmi_zeroshot_blueprint_audit.get("not_a_schema_probe_artifact") is True
                and ppmi_zeroshot_blueprint_audit.get("not_a_preregistration") is True
                and ppmi_zeroshot_blueprint_audit.get("goal_complete") is False
                and any(
                    row.get("name")
                    == "blueprint is anchored to exact pro-results prompt and rank4 directive"
                    and row.get("passed") is True
                    for row in ppmi_zeroshot_blueprint_audit.get("checks", [])
                )
            ),
            "evidence": {
                **access,
                "request_packet": exists_rel("scripts/ppmi_verily_tier3_request_packet.md"),
                "packet_audit": exists_rel("results/ppmi_verily_request_packet_audit_20260509.json"),
                "word_template": exists_rel("results/ppmi_verily_tier3_request_packet_template_20260515.docx"),
                "word_template_audit": exists_rel("results/ppmi_verily_submit_format_audit_20260515.json"),
                "word_template_decision": ppmi_submit_format_audit.get("decision"),
                "submission_email_template": exists_rel("scripts/ppmi_verily_submission_email_template.md"),
                "submission_email_template_audit": exists_rel(
                    "results/ppmi_verily_submission_email_template_audit_20260515.json"
                ),
                "submission_email_template_decision": ppmi_email_template_audit.get("decision"),
                "submission_email_validator": exists_rel("scripts/validate_ppmi_verily_submission_email.py"),
                "submission_email_validator_audit": exists_rel(
                    "results/ppmi_verily_submission_email_validator_audit_20260515.json"
                ),
                "submission_email_validator_decision": ppmi_email_validator_audit.get("decision"),
                "submission_package_validator": exists_rel("scripts/validate_ppmi_verily_submission_package.py"),
                "submission_package_validator_audit": exists_rel(
                    "results/ppmi_verily_submission_package_validator_audit_20260515.json"
                ),
                "submission_package_validator_decision": ppmi_package_validator_audit.get("decision"),
                "schema_probe_checklist": exists_rel("scripts/ppmi_verily_schema_probe_checklist.md"),
                "schema_probe_checklist_audit": exists_rel(
                    "results/ppmi_verily_schema_probe_checklist_audit_20260515.json"
                ),
                "schema_probe_checklist_decision": ppmi_schema_probe_checklist_audit.get("decision"),
                "schema_probe_artifact_created": ppmi_schema_probe_checklist_audit.get(
                    "schema_probe_artifact_created"
                ),
                "schema_probe_report_template": exists_rel(
                    "scripts/ppmi_verily_schema_probe_report_template.md"
                ),
                "schema_probe_report_template_audit": exists_rel(
                    "results/ppmi_verily_schema_probe_report_template_audit_20260515.json"
                ),
                "schema_probe_report_template_decision": ppmi_schema_probe_template_audit.get("decision"),
                "schema_probe_report_validator": exists_rel(
                    "scripts/validate_ppmi_verily_schema_probe_report.py"
                ),
                "schema_probe_report_validator_audit": exists_rel(
                    "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json"
                ),
                "schema_probe_report_validator_decision": ppmi_schema_probe_report_validator_audit.get(
                    "decision"
                ),
                "target_free_manifest_template": exists_rel(
                    "scripts/ppmi_verily_target_free_manifest_template.json"
                ),
                "target_free_manifest_validator": exists_rel(
                    "scripts/validate_ppmi_verily_target_free_manifest.py"
                ),
                "target_free_manifest_validator_audit": exists_rel(
                    "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
                ),
                "target_free_manifest_validator_decision": ppmi_target_free_manifest_validator_audit.get(
                    "decision"
                ),
                "completed_packet_validator": exists_rel("scripts/validate_ppmi_verily_completed_packet.py"),
                "completed_packet_validator_audit": exists_rel(
                    "results/ppmi_verily_completed_packet_validator_audit_20260515.json"
                ),
                "completed_packet_validator_decision": ppmi_completed_packet_validator_audit.get("decision"),
                "next_action_status": exists_rel("scripts/show_ppmi_verily_next_action.py"),
                "next_action_status_audit": exists_rel(
                    "results/ppmi_verily_next_action_status_audit_20260515.json"
                ),
                "next_action_status_decision": ppmi_next_action_status_audit.get("decision"),
                "next_action_status_current_submission_handoff": ppmi_next_action_status_audit.get(
                    "current_submission_handoff"
                ),
                "submission_bundle": exists_rel("results/ppmi_verily_submission_bundle_20260515.json"),
                "submission_bundle_decision": ppmi_submission_bundle.get("decision"),
                "current_submission_handoff": exists_rel(
                    "results/ppmi_verily_current_submission_handoff_20260515.json"
                ),
                "current_submission_handoff_decision": ppmi_current_submission_handoff.get("decision"),
                "zeroshot_blueprint": exists_rel("results/ppmi_verily_zeroshot_blueprint_20260515.json"),
                "zeroshot_blueprint_audit": exists_rel(
                    "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json"
                ),
                "zeroshot_blueprint_decision": ppmi_zeroshot_blueprint_audit.get("decision"),
                "zeroshot_blueprint_prompt_trace_check": any(
                    row.get("name")
                    == "blueprint is anchored to exact pro-results prompt and rank4 directive"
                    and row.get("passed") is True
                    for row in ppmi_zeroshot_blueprint_audit.get("checks", [])
                ),
            },
        },
        {
            "id": "queued_external_access_packets_have_generic_content_free_preflight",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("generic_packet_validator") == "scripts/validate_access_request_packet.py"
                and access.get("generic_packet_validator_audit")
                == "results/access_request_packet_validator_audit_20260515.json"
                and access.get("generic_packet_validator_decision")
                == "access_request_packet_validator_ready"
                and access.get("generic_packet_validator_route_count") == 6
                and access.get("generic_packet_validator_hard_failures") == []
                and access.get("generic_packet_validator_content_free") is True
                and access.get("external_queue_status") == "scripts/show_external_access_queue.py"
                and access.get("external_queue_status_audit")
                == "results/external_access_queue_status_audit_20260515.json"
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
                and access.get("external_queue_status_content_boundary", {}).get(
                    "completed_packets_included"
                )
                is False
                and access.get("external_queue_status_content_boundary", {}).get(
                    "protected_data_included"
                )
                is False
                and access.get("external_queue_status_content_boundary", {}).get(
                    "record_paths_reported"
                )
                is False
            ),
            "evidence": {
                "generic_packet_validator": access.get("generic_packet_validator"),
                "generic_packet_validator_audit": access.get("generic_packet_validator_audit"),
                "generic_packet_validator_decision": access.get("generic_packet_validator_decision"),
                "generic_packet_validator_route_count": access.get(
                    "generic_packet_validator_route_count"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
                "content_boundary": access.get("external_queue_status_content_boundary"),
            },
        },
        {
            "id": "queued_external_access_requests_have_generic_fill_checklist",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("generic_fill_checklist")
                == "scripts/show_access_request_fill_checklist.py"
                and access.get("generic_fill_checklist_audit")
                == "results/access_request_fill_checklist_audit_20260515.json"
                and access.get("generic_fill_checklist_decision")
                == "access_request_fill_checklist_ready"
                and access.get("generic_fill_checklist_route_count") == 6
                and access.get("generic_fill_checklist_hard_failures") == []
                and access.get("generic_fill_checklist_content_free") is True
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "generic_fill_checklist": access.get("generic_fill_checklist"),
                "generic_fill_checklist_audit": access.get("generic_fill_checklist_audit"),
                "generic_fill_checklist_decision": access.get("generic_fill_checklist_decision"),
                "generic_fill_checklist_route_count": access.get(
                    "generic_fill_checklist_route_count"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_access_requests_have_stable_submission_index",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("external_submission_index")
                == "results/external_access_submission_index_20260515.md"
                and access.get("external_submission_index_writer")
                == "scripts/write_external_access_submission_index.py"
                and access.get("external_submission_index_audit")
                == "results/external_access_submission_index_audit_20260515.json"
                and access.get("external_submission_index_decision")
                == "external_access_submission_index_ready"
                and access.get("external_submission_index_hard_failures") == []
                and access.get("external_submission_index_content_free") is True
                and access.get("external_submission_index_workflow_sequence_check") is True
                and (
                    access.get("external_submission_index_workflow_by_route", {})
                    .get("ppmi_verily")
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
                )
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "external_submission_index": access.get("external_submission_index"),
                "external_submission_index_writer": access.get(
                    "external_submission_index_writer"
                ),
                "external_submission_index_audit": access.get(
                    "external_submission_index_audit"
                ),
                "external_submission_index_decision": access.get(
                    "external_submission_index_decision"
                ),
                "external_submission_index_workflow_by_route": access.get(
                    "external_submission_index_workflow_by_route"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_access_requests_have_all_route_lifecycle_status",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("external_lifecycle_status")
                == "scripts/show_external_access_lifecycle.py"
                and access.get("external_lifecycle_status_audit")
                == "results/external_access_lifecycle_status_audit_20260515.json"
                and access.get("external_lifecycle_status_decision")
                == "external_access_lifecycle_status_ready"
                and access.get("external_lifecycle_status_hard_failures") == []
                and access.get("external_lifecycle_status_content_free") is True
                and access.get("external_lifecycle_status_workflow_sequence_check") is True
                and (
                    access.get("external_lifecycle_status_workflow_by_route", {})
                    .get("ppmi_verily")
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
                )
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "external_lifecycle_status": access.get("external_lifecycle_status"),
                "external_lifecycle_status_audit": access.get(
                    "external_lifecycle_status_audit"
                ),
                "external_lifecycle_status_decision": access.get(
                    "external_lifecycle_status_decision"
                ),
                "external_lifecycle_status_workflow_by_route": access.get(
                    "external_lifecycle_status_workflow_by_route"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_schema_probe_handoff_is_generic_and_content_free",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("external_schema_probe_handoff")
                == "results/external_schema_probe_handoff_20260515.md"
                and access.get("external_schema_probe_handoff_writer")
                == "scripts/write_external_schema_probe_handoff.py"
                and access.get("external_schema_probe_handoff_audit")
                == "results/external_schema_probe_handoff_audit_20260515.json"
                and access.get("external_schema_probe_handoff_decision")
                == "external_schema_probe_handoff_ready"
                and access.get("external_schema_probe_handoff_route_count") == 6
                and access.get("external_schema_probe_handoff_hard_failures") == []
                and access.get("external_schema_probe_handoff_content_free") is True
                and access.get(
                    "external_schema_probe_handoff_post_approval_workflow_check"
                )
                is True
                and access.get(
                    "external_schema_probe_handoff_post_approval_workflow_by_route",
                    {},
                ).get("ppmi_verily")
                == EXPECTED_SCHEMA_POST_APPROVAL_WORKFLOW_STEP_IDS
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "external_schema_probe_handoff": access.get(
                    "external_schema_probe_handoff"
                ),
                "external_schema_probe_handoff_writer": access.get(
                    "external_schema_probe_handoff_writer"
                ),
                "external_schema_probe_handoff_audit": access.get(
                    "external_schema_probe_handoff_audit"
                ),
                "external_schema_probe_handoff_decision": access.get(
                    "external_schema_probe_handoff_decision"
                ),
                "external_schema_probe_handoff_route_count": access.get(
                    "external_schema_probe_handoff_route_count"
                ),
                "post_approval_workflow_by_route": access.get(
                    "external_schema_probe_handoff_post_approval_workflow_by_route"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_schema_probe_reports_have_generic_content_free_preflight",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("generic_schema_probe_report_validator")
                == "scripts/validate_schema_probe_report.py"
                and access.get("generic_schema_probe_report_validator_audit")
                == "results/external_schema_probe_report_validator_audit_20260515.json"
                and access.get("generic_schema_probe_report_validator_decision")
                == "external_schema_probe_report_validator_ready"
                and access.get("generic_schema_probe_report_validator_route_count") == 6
                and access.get("generic_schema_probe_report_validator_hard_failures") == []
                and access.get("generic_schema_probe_report_validator_content_free") is True
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "generic_schema_probe_report_validator": access.get(
                    "generic_schema_probe_report_validator"
                ),
                "generic_schema_probe_report_validator_audit": access.get(
                    "generic_schema_probe_report_validator_audit"
                ),
                "generic_schema_probe_report_validator_decision": access.get(
                    "generic_schema_probe_report_validator_decision"
                ),
                "generic_schema_probe_report_validator_route_count": access.get(
                    "generic_schema_probe_report_validator_route_count"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_target_free_manifests_have_generic_content_free_preflight",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("generic_target_free_manifest_validator")
                == "scripts/validate_target_free_manifest.py"
                and access.get("generic_target_free_manifest_validator_audit")
                == "results/external_target_free_manifest_validator_audit_20260515.json"
                and access.get("generic_target_free_manifest_validator_decision")
                == "external_target_free_manifest_validator_ready"
                and access.get("generic_target_free_manifest_validator_route_count") == 6
                and access.get("generic_target_free_manifest_validator_hard_failures") == []
                and access.get("generic_target_free_manifest_validator_content_free") is True
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "generic_target_free_manifest_validator": access.get(
                    "generic_target_free_manifest_validator"
                ),
                "generic_target_free_manifest_validator_audit": access.get(
                    "generic_target_free_manifest_validator_audit"
                ),
                "generic_target_free_manifest_validator_decision": access.get(
                    "generic_target_free_manifest_validator_decision"
                ),
                "generic_target_free_manifest_validator_route_count": access.get(
                    "generic_target_free_manifest_validator_route_count"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_target_free_manifest_templates_are_generic_and_content_free",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("external_target_free_manifest_templates")
                == "results/external_target_free_manifest_templates_20260515.md"
                and access.get("external_target_free_manifest_templates_writer")
                == "scripts/write_external_target_free_manifest_templates.py"
                and access.get("external_target_free_manifest_templates_audit")
                == "results/external_target_free_manifest_templates_audit_20260515.json"
                and access.get("external_target_free_manifest_templates_decision")
                == "external_target_free_manifest_templates_ready"
                and access.get("external_target_free_manifest_templates_route_count") == 6
                and access.get("external_target_free_manifest_templates_hard_failures")
                == []
                and access.get("external_target_free_manifest_templates_content_free") is True
                and access.get(
                    "external_target_free_manifest_templates_post_schema_workflow_check"
                )
                is True
                and access.get(
                    "external_target_free_manifest_templates_post_schema_workflow_by_route",
                    {},
                ).get("ppmi_verily")
                == EXPECTED_TARGET_FREE_POST_SCHEMA_WORKFLOW_STEP_IDS
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "external_target_free_manifest_templates": access.get(
                    "external_target_free_manifest_templates"
                ),
                "external_target_free_manifest_templates_writer": access.get(
                    "external_target_free_manifest_templates_writer"
                ),
                "external_target_free_manifest_templates_audit": access.get(
                    "external_target_free_manifest_templates_audit"
                ),
                "external_target_free_manifest_templates_decision": access.get(
                    "external_target_free_manifest_templates_decision"
                ),
                "external_target_free_manifest_templates_route_count": access.get(
                    "external_target_free_manifest_templates_route_count"
                ),
                "post_schema_workflow_by_route": access.get(
                    "external_target_free_manifest_templates_post_schema_workflow_by_route"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_zeroshot_blueprint_handoff_is_generic_and_content_free",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("external_zeroshot_blueprint_handoff")
                == "results/external_zeroshot_blueprint_handoff_20260515.md"
                and access.get("external_zeroshot_blueprint_handoff_writer")
                == "scripts/write_external_zeroshot_blueprint_handoff.py"
                and access.get("external_zeroshot_blueprint_handoff_audit")
                == "results/external_zeroshot_blueprint_handoff_audit_20260515.json"
                and access.get("external_zeroshot_blueprint_handoff_decision")
                == "external_zeroshot_blueprint_handoff_ready"
                and access.get("external_zeroshot_blueprint_handoff_route_count") == 6
                and access.get("external_zeroshot_blueprint_handoff_hard_failures")
                == []
                and access.get("external_zeroshot_blueprint_handoff_content_free") is True
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "external_zeroshot_blueprint_handoff": access.get(
                    "external_zeroshot_blueprint_handoff"
                ),
                "external_zeroshot_blueprint_handoff_writer": access.get(
                    "external_zeroshot_blueprint_handoff_writer"
                ),
                "external_zeroshot_blueprint_handoff_audit": access.get(
                    "external_zeroshot_blueprint_handoff_audit"
                ),
                "external_zeroshot_blueprint_handoff_decision": access.get(
                    "external_zeroshot_blueprint_handoff_decision"
                ),
                "external_zeroshot_blueprint_handoff_route_count": access.get(
                    "external_zeroshot_blueprint_handoff_route_count"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_formula_sha_templates_are_generic_and_content_free",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("external_formula_sha_templates")
                == "results/external_formula_sha_templates_20260515.md"
                and access.get("external_formula_sha_templates_writer")
                == "scripts/write_external_formula_sha_templates.py"
                and access.get("external_formula_sha_record_validator")
                == "scripts/validate_external_formula_sha_record.py"
                and access.get("external_formula_sha_templates_audit")
                == "results/external_formula_sha_templates_audit_20260515.json"
                and access.get("external_formula_sha_templates_decision")
                == "external_formula_sha_templates_ready"
                and access.get("external_formula_sha_templates_route_count") == 6
                and access.get("external_formula_sha_templates_hard_failures") == []
                and access.get("external_formula_sha_templates_content_free") is True
                and access.get("external_formula_sha_templates_post_formula_workflow_check")
                is True
                and access.get(
                    "external_formula_sha_templates_post_formula_workflow_by_route",
                    {},
                ).get("ppmi_verily")
                == EXPECTED_FORMULA_POST_FORMULA_WORKFLOW_STEP_IDS
                and access.get("external_formula_sha_ppmi_contract_present") is True
                and access.get("external_formula_sha_ppmi_contract_negative_failed")
                is True
                and access.get("external_formula_sha_ppmi_bad_contract_hard_failures")
                == ["ppmi_route_specific_formula_contract"]
                and access.get("external_queue_ppmi_formula_x4_policy")
                == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "external_formula_sha_templates": access.get(
                    "external_formula_sha_templates"
                ),
                "external_formula_sha_templates_writer": access.get(
                    "external_formula_sha_templates_writer"
                ),
                "external_formula_sha_record_validator": access.get(
                    "external_formula_sha_record_validator"
                ),
                "external_formula_sha_templates_audit": access.get(
                    "external_formula_sha_templates_audit"
                ),
                "external_formula_sha_templates_decision": access.get(
                    "external_formula_sha_templates_decision"
                ),
                "external_formula_sha_templates_route_count": access.get(
                    "external_formula_sha_templates_route_count"
                ),
                "post_formula_workflow_by_route": access.get(
                    "external_formula_sha_templates_post_formula_workflow_by_route"
                ),
                "external_formula_sha_ppmi_contract_present": access.get(
                    "external_formula_sha_ppmi_contract_present"
                ),
                "external_formula_sha_ppmi_contract_negative_failed": access.get(
                    "external_formula_sha_ppmi_contract_negative_failed"
                ),
                "external_formula_sha_ppmi_bad_contract_hard_failures": access.get(
                    "external_formula_sha_ppmi_bad_contract_hard_failures"
                ),
                "external_queue_ppmi_formula_x4_policy": access.get(
                    "external_queue_ppmi_formula_x4_policy"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "queued_external_zeroshot_result_templates_are_generic_and_content_free",
            "passed": (
                access.get("submit_ready_route_count") == 6
                and access.get("compute_ready_route_count") == 0
                and access.get("external_zeroshot_result_templates")
                == "results/external_zeroshot_result_templates_20260515.md"
                and access.get("external_zeroshot_result_templates_writer")
                == "scripts/write_external_zeroshot_result_templates.py"
                and access.get("external_zeroshot_result_record_validator")
                == "scripts/validate_external_zeroshot_result_record.py"
                and access.get("external_zeroshot_result_templates_audit")
                == "results/external_zeroshot_result_templates_audit_20260515.json"
                and access.get("external_zeroshot_result_templates_decision")
                == "external_zeroshot_result_templates_ready"
                and access.get("external_zeroshot_result_templates_route_count") == 6
                and access.get("external_zeroshot_result_templates_hard_failures") == []
                and access.get("external_zeroshot_result_templates_content_free") is True
                and access.get(
                    "external_zeroshot_result_templates_post_score_workflow_check"
                )
                is True
                and access.get(
                    "external_zeroshot_result_templates_post_score_workflow_by_route",
                    {},
                ).get("ppmi_verily")
                == EXPECTED_ZEROSHOT_RESULT_POST_SCORE_WORKFLOW_STEP_IDS
                and access.get("external_zeroshot_result_ppmi_contract_present") is True
                and access.get("external_zeroshot_result_ppmi_contract_negative_failed")
                is True
                and access.get(
                    "external_zeroshot_result_ppmi_bad_contract_hard_failures"
                )
                == ["ppmi_route_specific_result_contract"]
                and access.get("external_queue_ppmi_result_x4_policy")
                == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
                and access.get("external_queue_status_decision")
                == "external_access_queue_status_ready"
            ),
            "evidence": {
                "external_zeroshot_result_templates": access.get(
                    "external_zeroshot_result_templates"
                ),
                "external_zeroshot_result_templates_writer": access.get(
                    "external_zeroshot_result_templates_writer"
                ),
                "external_zeroshot_result_record_validator": access.get(
                    "external_zeroshot_result_record_validator"
                ),
                "external_zeroshot_result_templates_audit": access.get(
                    "external_zeroshot_result_templates_audit"
                ),
                "external_zeroshot_result_templates_decision": access.get(
                    "external_zeroshot_result_templates_decision"
                ),
                "external_zeroshot_result_templates_route_count": access.get(
                    "external_zeroshot_result_templates_route_count"
                ),
                "external_zeroshot_result_templates_post_score_workflow_check": (
                    access.get(
                        "external_zeroshot_result_templates_post_score_workflow_check"
                    )
                ),
                "external_zeroshot_result_templates_post_score_workflow_by_route": (
                    access.get(
                        "external_zeroshot_result_templates_post_score_workflow_by_route"
                    )
                ),
                "external_zeroshot_result_ppmi_contract_present": access.get(
                    "external_zeroshot_result_ppmi_contract_present"
                ),
                "external_zeroshot_result_ppmi_contract_negative_failed": access.get(
                    "external_zeroshot_result_ppmi_contract_negative_failed"
                ),
                "external_zeroshot_result_ppmi_bad_contract_hard_failures": access.get(
                    "external_zeroshot_result_ppmi_bad_contract_hard_failures"
                ),
                "external_queue_ppmi_result_x4_policy": access.get(
                    "external_queue_ppmi_result_x4_policy"
                ),
                "external_queue_status": access.get("external_queue_status"),
                "external_queue_status_audit": access.get("external_queue_status_audit"),
                "external_queue_status_decision": access.get("external_queue_status_decision"),
            },
        },
        {
            "id": "current_verified_next_action_is_ppmi_submission_not_compute",
            "passed": (
                current_state_verification.get("goal_complete") is False
                and expected_lifecycle_action_id is not None
                and current_state_verification.get("next_action", {}).get("action_id")
                == expected_lifecycle_action_id
                and current_state_verification.get("next_action", {}).get(
                    "safe_to_execute_code_now"
                )
                == current_lifecycle_action.get("safe_to_execute_code")
                and current_state_verification.get("next_action", {}).get(
                    "use_completed_package_validator"
                )
                == "scripts/validate_ppmi_verily_submission_package.py"
                and current_state_verification.get("next_action", {}).get(
                    "use_fill_checklist"
                )
                == "scripts/ppmi_verily_user_fill_checklist.md"
                and current_state_verification.get("next_action", {})
                .get("fill_fields", {})
                .get("source_checklist")
                == "scripts/ppmi_verily_user_fill_checklist.md"
                and current_state_verification.get("next_action", {})
                .get("fill_fields", {})
                .get("packet_field_count")
                == 13
                and current_state_verification.get("next_action", {})
                .get("fill_fields", {})
                .get("email_field_count")
                == 12
                and current_state_verification.get("next_action", {})
                .get("fill_fields", {})
                .get("submission_metadata_field_count")
                == 4
                and current_state_verification.get("pre_submission_handoff", {}).get(
                    "completed_package_validator"
                )
                == "scripts/validate_ppmi_verily_submission_package.py"
                and current_state_verification.get("pre_submission_handoff", {}).get(
                    "not_a_submission_record"
                )
                is True
                and current_state_verification.get("pre_submission_handoff", {}).get(
                    "not_access_approval"
                )
                is True
                and current_state_verification.get("pre_submission_handoff", {}).get(
                    "not_a_model_result"
                )
                is True
                and current_state_verification.get("pre_submission_handoff", {}).get(
                    "protected_data_included"
                )
                is False
                and current_state_verification.get("pre_submission_handoff", {}).get(
                    "credentials_or_tokens_included"
                )
                is False
                and "scripts/record_access_approval.py"
                in current_state_verification.get("pre_submission_handoff", {}).get(
                    "record_approval_command_template", ""
                )
                and "<ISO8601_UTC>"
                in current_state_verification.get("pre_submission_handoff", {}).get(
                    "record_approval_command_template", ""
                )
                and "<non_protected_approval_source>"
                in current_state_verification.get("pre_submission_handoff", {}).get(
                    "record_approval_command_template", ""
                )
                and (
                    not packet_ready_state
                    or any(
                        row.get("name")
                        == "current next-action handoff exposes submission and approval metadata recorders"
                        and row.get("passed") is True
                        for row in current_next_action_handoff.get("checks", [])
                    )
                )
                and current_state_verification.get("access_lifecycle_current_action", {}).get(
                    "action"
                )
                == lifecycle_action
                and current_state_verification.get("access_lifecycle_current_action", {}).get(
                    "safe_to_execute_code"
                )
                == current_lifecycle_action.get("safe_to_execute_code")
                and "model run"
                in current_state_verification.get("access_lifecycle_current_action", {}).get(
                    "blocked_actions_now", []
                )
            ),
            "evidence": {
                "current_state": "results/current_goal_state_verification_20260508.json",
                "next_action": current_state_verification.get("next_action"),
                "pre_submission_handoff": current_state_verification.get(
                    "pre_submission_handoff"
                ),
                "access_lifecycle_current_action": current_state_verification.get(
                    "access_lifecycle_current_action"
                ),
            },
        },
        {
            "id": "current_submission_handoff_is_content_free_and_actionable",
            "passed": (
                not packet_ready_state
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
                    and ppmi_current_submission_handoff.get("current_action", {}).get("action_id")
                    == "submit_ppmi_verily_access_request"
                    and ppmi_current_submission_handoff.get("current_action", {}).get(
                        "safe_to_execute_code_now"
                    )
                    is False
                    and ppmi_current_submission_handoff.get("package_artifacts", {}).get(
                        "word_packet_template"
                    )
                    == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
                    and ppmi_current_submission_handoff.get("package_artifacts", {}).get(
                        "completed_package_validator"
                    )
                    == "scripts/validate_ppmi_verily_submission_package.py"
                    and ppmi_current_submission_handoff.get("workflow_command_sequence")
                    == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                    and [
                        step.get("step_id")
                        for step in ppmi_current_submission_handoff.get("next_steps", [])
                    ]
                    == [
                        "fill_local_packet_and_email",
                        "preflight_completed_package",
                        "submit_access_request",
                        "record_submission_metadata",
                        "wait_for_data_owner_approval",
                        "record_approval_metadata",
                        "post_approval_read_only_schema_probe",
                    ]
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
            ),
            "evidence": {
                "path": "results/ppmi_verily_current_submission_handoff_20260515.json",
                "decision": ppmi_current_submission_handoff.get("decision"),
                "current_action": ppmi_current_submission_handoff.get("current_action"),
                "package_artifacts": ppmi_current_submission_handoff.get("package_artifacts"),
                "content_boundary": ppmi_current_submission_handoff.get("content_boundary"),
                "workflow_command_sequence": ppmi_current_submission_handoff.get(
                    "workflow_command_sequence"
                ),
            },
        },
        {
            "id": "rank5_microbatch_and_joint_followup_are_sub_mcid",
            "passed": (
                num_lt(get_path(by_rank[5], "evidence", "item13_microbatch", "delta_ccc"), T1_MCID)
                and num_lt(get_path(by_rank[5], "evidence", "best_followup_joint_item12_13", "delta_ccc"), T1_MCID)
                and num_lt(
                    get_path(by_rank[5], "evidence", "best_followup_joint_item12_13", "frac_positive"),
                    PROMOTION_FRAC_POS_MIN,
                )
            ),
            "evidence": by_rank[5]["evidence"],
        },
        {
            "id": "rank6_stability_descriptor_has_no_stable_columns",
            "passed": (
                s6.get("stable_cols_item10") == 0
                and s6.get("stable_cols_item13") == 0
                and s6.get("stable_cols_item14") == 0
            ),
            "evidence": s6,
        },
        {
            "id": "rank7_t1_selective_prediction_failed_existing_slotD_secondary_references",
            "passed": t1_retained_below_reference(by_rank[7]["evidence"]),
            "evidence": by_rank[7]["evidence"],
        },
        {
            "id": "rank8_tug_phase_cache_manifest_exists_and_screen_fails_gate",
            "passed": (
                s8.get("exists") is True
                and s8.get("cache") is not None
                and s8.get("manifest") is not None
                and (ROOT / str(s8.get("cache"))).exists()
                and (ROOT / str(s8.get("manifest"))).exists()
                and below_gate(by_rank[8])
            ),
            "evidence": s8,
        },
        {
            "id": "rank9_sparse_prototype_screen_failed_below_promotion_gate",
            "passed": below_gate(by_rank[9]),
            "evidence": by_rank[9]["evidence"],
        },
        {
            "id": "rank10_k250_internal_replication_negative_and_external_branch_blocked",
            "passed": (
                rank10.get("fresh_internal_ccc") is not None
                and rank10.get("fresh_internal_ccc") < T3_CEILING
                and rank10.get("frac_positive", 0.0) < PROMOTION_FRAC_POS_MIN
                and get_path(rank10, "external_access", "compute_ready_route_count") == 0
                and (ROOT / rank10["external_blueprint"]).exists()
            ),
            "evidence": rank10,
        },
        {
            "id": "rank11_t3_observable_decomposition_failed_full_cohort_gate",
            "passed": (
                isinstance(rank11.get("delta_ccc"), (int, float))
                and rank11["delta_ccc"] < T3_MCID
                and isinstance(rank11.get("frac_positive"), (int, float))
                and rank11["frac_positive"] < PROMOTION_FRAC_POS_MIN
            ),
            "evidence": rank11,
        },
        {
            "id": "rank12_t3_unobservability_abstention_failed_slotF_secondary_references",
            "passed": t3_retained_below_reference(by_rank[12]["evidence"]),
            "evidence": by_rank[12]["evidence"],
        },
        {
            "id": "s13_s15_t3_transfer_extension_failed_and_not_promoted",
            "passed": (
                s13_s15.get("exists") is True
                and s13_s15.get("n_cohort") == 95
                and s13_s15.get("fivefold_promotion") == "BELOW_SCREEN"
                and isinstance(s13_s15.get("fivefold_screen_JOINT_mean"), (int, float))
                and s13_s15["fivefold_screen_JOINT_mean"] < T3_MCID
                and isinstance(s13_s15.get("fivefold_screen_JOINT_std"), (int, float))
                and s13_s15["fivefold_screen_JOINT_std"] > 0.020
                and isinstance(s13_s15.get("ph_only_frac_positive"), (int, float))
                and s13_s15["ph_only_frac_positive"] < PROMOTION_FRAC_POS_MIN
                and isinstance(s13_s15.get("joint_delta"), (int, float))
                and s13_s15["joint_delta"] < T3_MCID
                and isinstance(s13_s15.get("joint_frac_positive"), (int, float))
                and s13_s15["joint_frac_positive"] < PROMOTION_FRAC_POS_MIN
                and isinstance(s13_s15.get("scrambled_joint_delta"), (int, float))
                and s13_s15["scrambled_joint_delta"] < 0
                and isinstance(s13_s15.get("sid_shuffle_joint_frac_positive"), (int, float))
                and s13_s15["sid_shuffle_joint_frac_positive"] < PROMOTION_FRAC_POS_MIN
                and s13_s15.get("sanity_y_nan_decision_y_free_cov70") is True
                and s13_s15.get("sanity_y_nan_decision_y_free_cov50") is True
                and isinstance(s13_s15.get("s15_cov70_frac_positive"), (int, float))
                and s13_s15["s15_cov70_frac_positive"] < PROMOTION_FRAC_POS_MIN
                and isinstance(s13_s15.get("s15_cov50_frac_positive"), (int, float))
                and s13_s15["s15_cov50_frac_positive"] < PROMOTION_FRAC_POS_MIN
                and isinstance(s13_s15.get("s15_cov50_delta_vs_slotF"), (int, float))
                and s13_s15["s15_cov50_delta_vs_slotF"] < 0
            ),
            "evidence": s13_s15,
        },
        {
            "id": "slotF_t3_deployable_replication_boundary_lift_not_promoted",
            "passed": (
                slotf_replication_audit.get("passed") is True
                and slotf_replication_audit.get("decision") == "slotF_replication_boundary_lift_not_promoted"
                and slotf_replication_audit.get("hard_failures") == []
                and slotf_replication_audit.get("goal_complete") is False
                and all(
                    row.get("replicated_gate_pass") is False
                    for row in slotf_replication_audit.get("coverage_rows", {}).values()
                )
            ),
            "evidence": slotf_replication_audit,
        },
        {
            "id": "no_numbered_item_is_missing_or_unverified",
            "passed": all(
                row["status"].startswith("covered") or row["status"].startswith("blocked")
                for row in numbered
            ),
            "evidence": {
                str(row["rank"]): {"status": row["status"], "path": row["evidence"].get("path")}
                for row in numbered
            },
        },
    ]
    return checks


def build_explicit_directive_checklist(
    numbered: list[dict[str, Any]],
    access: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map the prompt's non-numbered directives to concrete evidence.

    The numbered checklist covers ranks 1-12.  The prompt also has explicit
    bottom-line instructions: run the rank-1 screen first, keep PPMI/Verily
    access-first, preserve fixed K=250/no-search externally, and stop local
    WearGait-only T3 fishing.  This checklist makes those requirements
    auditable without treating any proxy artifact as goal completion.
    """

    by_rank = {row["rank"]: row for row in numbered}
    prompt_text = load_text(PROMPT)
    s1_result_path = latest("results/screen_t1_S1_sumaware_bayesian_*.json")
    s1_result = load_json(s1_result_path)
    s1_text = load_text(ROOT / "run_t1_S1_sumaware_bayesian.py")
    topofractal_result_path = latest("results/screen_t1_topofractal8_sumaware_*.json")
    topofractal_result = load_json(topofractal_result_path)
    topofractal_text = load_text(ROOT / "run_t1_topofractal_sumaware_screen.py")
    ppmi_runbook = load_text(ROOT / "scripts/ppmi_verily_setup.md")
    ppmi_packet = load_text(ROOT / "scripts/ppmi_verily_tier3_request_packet.md")
    ppmi_email = load_text(ROOT / "scripts/ppmi_verily_submission_email_template.md")
    ppmi_schema_probe_checklist = load_text(ROOT / "scripts/ppmi_verily_schema_probe_checklist.md")
    ppmi_schema_probe_template = load_text(ROOT / "scripts/ppmi_verily_schema_probe_report_template.md")
    ppmi_bundle = load_json(RESULTS / "ppmi_verily_submission_bundle_20260515.json")
    ppmi_package_validator_audit = load_json(
        RESULTS / "ppmi_verily_submission_package_validator_audit_20260515.json"
    )
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
    ppmi_zeroshot_blueprint = load_json(RESULTS / "ppmi_verily_zeroshot_blueprint_20260515.json")
    ppmi_zeroshot_blueprint_audit = load_json(
        RESULTS / "ppmi_verily_zeroshot_blueprint_audit_20260515.json"
    )
    remaining_blockers = load_json(RESULTS / "remaining_blocker_action_audit_20260509.json")
    blueprint = ppmi_zeroshot_blueprint.get("blueprint", {})
    blueprint_tracks = {track.get("track_id"): track for track in blueprint.get("tracks", [])}
    blueprint_prompt_trace = blueprint.get("source_prompt_trace", {})
    prompt_source = get_prompt_requirements()

    s1_gate = s1_result.get("promotion_gate", {})
    s1_nulls = s1_result.get("null_results", {})
    topofractal_nulls = topofractal_result.get("null_results", {})

    return [
        {
            "id": "objective_success_criteria_are_concrete_and_unmet",
            "directive": "Break the T1/T3 CCC ceiling, not merely produce secondary/access artifacts.",
            "passed": (
                "0.7170" in prompt_text
                and "0.3784" in prompt_text
                and by_rank[1]["status"].startswith("covered")
                and by_rank[10]["status"].startswith("blocked")
            ),
            "evidence": {
                "t1_ceiling": T1_CEILING,
                "t3_ceiling": T3_CEILING,
                "prompt_mentions_current_t1_ceiling": "0.7170" in prompt_text,
                "prompt_mentions_current_t3_ceiling": "0.3784" in prompt_text,
            },
        },
        {
            "id": "best_immediate_rank1_algorithm_executed_as_screen",
            "directive": "Do rank #1: sum-aware multi-task Bayesian residual composer over TopoFractal-8.",
            "passed": (
                (ROOT / "run_t1_S1_sumaware_bayesian.py").exists()
                and s1_result_path is not None
                and s1_result.get("verdict") == "SCREEN_FAIL_NO_LOOCV"
                and by_rank[1]["evidence"].get("path") == rel(s1_result_path)
            ),
            "evidence": {
                "script": "run_t1_S1_sumaware_bayesian.py",
                "result": rel(s1_result_path),
                "verdict": s1_result.get("verdict"),
                "rank1_status": by_rank[1]["status"],
            },
        },
        {
            "id": "rank1_algorithm_steps_1_to_4_are_implemented",
            "directive": "Use iter34 baseline, fixed TopoFractal block, Bayesian/Ridge correction, and sum-residual loss.",
            "passed": all(
                snippet in s1_text
                for snippet in [
                    "ITER34_OOF_NPZ",
                    "BayesianRidge",
                    "lambda_sum * (r_sum",
                    "inner_select_lambda",
                    "FoldImputer",
                    "FoldNormalizer",
                ]
            )
            and all(
                snippet in topofractal_text
                for snippet in [
                    "GROUP_SPECS",
                    "BayesianRidge",
                    "target-free",
                    "PCA(n_components=1",
                ]
            )
            and topofractal_result_path is not None,
            "evidence": {
                "s1_script": "run_t1_S1_sumaware_bayesian.py",
                "topofractal_script": "run_t1_topofractal_sumaware_screen.py",
                "topofractal_result": rel(topofractal_result_path),
            },
        },
        {
            "id": "rank1_screen_gate_prevented_loocv",
            "directive": "Screen only in 5-fold OOF; promote to LOOCV only if delta >= +0.025 and frac>0 >= 0.95.",
            "passed": (
                s1_result.get("verdict") == "SCREEN_FAIL_NO_LOOCV"
                and s1_gate.get("gate_pass") is False
                and s1_gate.get("mean_seed_delta_ccc_min") == T1_MCID
                and s1_gate.get("ensemble_bootstrap_frac_positive_min") == PROMOTION_FRAC_POS_MIN
                and get_path(s1_result, "ensemble_summary", "delta_ccc") < T1_MCID
                and get_path(s1_result, "ensemble_summary", "bootstrap_frac_positive")
                < PROMOTION_FRAC_POS_MIN
            ),
            "evidence": {
                "result": rel(s1_result_path),
                "verdict": s1_result.get("verdict"),
                "promotion_gate": s1_gate,
                "delta_ccc": get_path(s1_result, "ensemble_summary", "delta_ccc"),
                "frac_positive": get_path(s1_result, "ensemble_summary", "bootstrap_frac_positive"),
            },
        },
        {
            "id": "rank1_null_and_no_headline_boundary_respected",
            "directive": "Run null gates before any headline claim; failed screen cannot become a headline.",
            "passed": (
                isinstance(s1_nulls, dict)
                and "scrambled_y" in s1_nulls
                and "sid_shuffle" in s1_nulls
                and get_path(s1_nulls, "retrieval_library_exclusion", "status") == "not_applicable"
                and get_path(s1_nulls, "scrambled_y", "ensemble_summary", "delta_ccc") < 0
                and get_path(s1_nulls, "sid_shuffle", "ensemble_summary", "delta_ccc") < 0
            ),
            "evidence": {
                "result": rel(s1_result_path),
                "null_modes": sorted(s1_nulls.keys()) if isinstance(s1_nulls, dict) else None,
                "scrambled_delta": get_path(s1_nulls, "scrambled_y", "ensemble_summary", "delta_ccc"),
                "sid_shuffle_delta": get_path(s1_nulls, "sid_shuffle", "ensemble_summary", "delta_ccc"),
            },
        },
        {
            "id": "topofractal_screen_nulls_and_canary_respected",
            "directive": "Target-free TopoFractal compression must use fold-local transforms and leakage checks.",
            "passed": (
                topofractal_result.get("verdict") == "SCREEN_FAIL_NO_LOOCV"
                and isinstance(topofractal_nulls, dict)
                and get_path(topofractal_nulls, "scrambled_y", "delta_ccc") < 0
                and get_path(topofractal_nulls, "sid_shuffle", "delta_ccc") < 0
                and get_path(topofractal_nulls, "test_only_canary", "passes") is True
                and get_path(topofractal_nulls, "retrieval_library_exclusion", "status") == "not_applicable"
            ),
            "evidence": {
                "result": rel(topofractal_result_path),
                "verdict": topofractal_result.get("verdict"),
                "null_results": topofractal_nulls,
            },
        },
        {
            "id": "best_one_month_ppmi_algorithm_is_packeted_access_first",
            "directive": (
                "After PPMI/Verily access: schema probe, target-free manifest, "
                "formula SHA, zero-shot scoring, then aggregate result-record preflight."
            ),
            "passed": (
                access.get("compute_ready_route_count") == 0
                and ppmi_bundle.get("decision") == "ppmi_verily_submission_bundle_ready"
                and ppmi_package_validator_audit.get("passed") is True
                and ppmi_package_validator_audit.get("decision")
                == "ppmi_verily_submission_package_validator_ready"
                and ppmi_package_validator_audit.get("validator")
                == "scripts/validate_ppmi_verily_submission_package.py"
                and ppmi_package_validator_audit.get("not_a_submission_record") is True
                and ppmi_package_validator_audit.get("not_access_approval") is True
                and ppmi_package_validator_audit.get("not_a_model_result") is True
                and ppmi_package_validator_audit.get("protected_data_included") is False
                and any(
                    row.get("name") == "validator output does not echo package paths or filenames"
                    and row.get("passed") is True
                    for row in ppmi_package_validator_audit.get("checks", [])
                )
                and ppmi_schema_probe_checklist_audit.get("passed") is True
                and ppmi_schema_probe_checklist_audit.get("decision")
                == "ppmi_verily_schema_probe_checklist_ready"
                and ppmi_schema_probe_checklist_audit.get("schema_probe_artifact_created") is False
                and ppmi_schema_probe_checklist_audit.get("protected_data_included") is False
                and ppmi_schema_probe_template_audit.get("passed") is True
                and ppmi_schema_probe_template_audit.get("decision")
                == "ppmi_verily_schema_probe_report_template_ready"
                and ppmi_schema_probe_template_audit.get("schema_probe_artifact_created") is False
                and ppmi_schema_probe_template_audit.get("protected_data_included") is False
                and ppmi_schema_probe_report_validator_audit.get("passed") is True
                and ppmi_schema_probe_report_validator_audit.get("decision")
                == "ppmi_verily_schema_probe_report_validator_ready"
                and ppmi_schema_probe_report_validator_audit.get("not_a_schema_probe_artifact") is True
                and ppmi_schema_probe_report_validator_audit.get("protected_data_included") is False
                and ppmi_target_free_manifest_validator_audit.get("passed") is True
                and ppmi_target_free_manifest_validator_audit.get("decision")
                == "ppmi_verily_target_free_manifest_validator_ready"
                and ppmi_target_free_manifest_validator_audit.get("template")
                == "scripts/ppmi_verily_target_free_manifest_template.json"
                and ppmi_target_free_manifest_validator_audit.get("validator")
                == "scripts/validate_ppmi_verily_target_free_manifest.py"
                and ppmi_target_free_manifest_validator_audit.get("not_a_feature_manifest_artifact")
                is True
                and ppmi_target_free_manifest_validator_audit.get("not_a_schema_probe_artifact")
                is True
                and ppmi_target_free_manifest_validator_audit.get("not_a_preregistration") is True
                and ppmi_target_free_manifest_validator_audit.get("protected_data_included") is False
                and ppmi_zeroshot_blueprint_audit.get("passed") is True
                and ppmi_zeroshot_blueprint_audit.get("decision")
                == "ppmi_verily_zeroshot_blueprint_ready"
                and ppmi_zeroshot_blueprint_audit.get("not_a_model_result") is True
                and ppmi_zeroshot_blueprint_audit.get("not_access_approval") is True
                and ppmi_zeroshot_blueprint_audit.get("not_a_schema_probe_artifact") is True
                and ppmi_zeroshot_blueprint_audit.get("not_a_preregistration") is True
                and ppmi_zeroshot_blueprint_audit.get("goal_complete") is False
                and blueprint_prompt_trace.get("prompt_sha256") == prompt_source.get("sha256")
                and blueprint_prompt_trace.get("prompt_rank") == 4
                and any(
                    row.get("name")
                    == "blueprint is anchored to exact pro-results prompt and rank4 directive"
                    and row.get("passed") is True
                    for row in ppmi_zeroshot_blueprint_audit.get("checks", [])
                )
                and blueprint.get("analysis_order")
                == [
                        "read_only_schema_probe",
                        "schema_probe_report_preflight",
                        "schema_probe_metadata_record",
                        "target_free_manifest_before_scoring",
                        "formula_sha256_after_manifest_before_extraction_or_scoring",
                        "zero_shot_external_validation",
                        "aggregate_result_record_preflight_after_external_scoring",
                        "ppmi_only_sanity_if_zero_shot_fails_or_for_context",
                        "fresh_augmentation_preregistration_only_after_zero_shot",
                    ]
                and get_path(
                    blueprint,
                    "reporting_gates",
                    "aggregate_result_record_preflight_before_reporting",
                )
                is True
                and get_path(
                    blueprint,
                    "result_record_requirements",
                    "template",
                )
                == (
                    "results/external_zeroshot_result_templates_20260515/"
                    "ppmi_verily_zeroshot_result_record_template.json"
                )
                and get_path(
                    blueprint,
                    "result_record_requirements",
                    "validator",
                )
                == "scripts/validate_external_zeroshot_result_record.py"
                and access.get("external_zeroshot_result_templates_decision")
                == "external_zeroshot_result_templates_ready"
                and access.get("external_zeroshot_result_templates_content_free") is True
                and access.get("external_formula_sha_ppmi_contract_present") is True
                and access.get("external_formula_sha_ppmi_contract_negative_failed")
                is True
                and access.get("external_zeroshot_result_ppmi_contract_present") is True
                and access.get("external_zeroshot_result_ppmi_contract_negative_failed")
                is True
                and "no cross-branch adaptive stacking before zero-shot results"
                in blueprint.get("locked_no_search_rules", [])
                and all(
                    term.lower() in ppmi_runbook.lower()
                    for term in [
                        "read-only schema probe",
                        "pre-registered",
                        "target-free",
                        "zero-shot",
                        "do not create placeholder versions",
                    ]
                )
                and all(
                    term.lower() in ppmi_schema_probe_checklist.lower()
                    for term in [
                        "do not use before data-owner approval",
                        "record_schema_probe_report.py",
                        "ppmi_verily_schema_probe_report_template.md",
                        "validate_ppmi_verily_target_free_manifest.py",
                        "sid",
                        "visit_id",
                        "updrs3",
                        "wrist_accelerometer",
                    ]
                )
                and all(
                    term.lower() in ppmi_schema_probe_template.lower()
                    for term in [
                        "post-approval scratch template",
                        "do not use before data-owner approval",
                        "do not commit a filled copy",
                        "record_schema_probe_report.py",
                        "validate_ppmi_verily_schema_probe_report.py",
                        "validate_ppmi_verily_target_free_manifest.py",
                        "sid",
                        "visit_id",
                        "updrs3",
                        "wrist_accelerometer",
                    ]
                )
                and all(
                    term.lower() in ppmi_packet.lower()
                    for term in [
                        "read-only schema probe",
                        "formula_sha256",
                        "manifest sidecars",
                        "zero-shot external validation",
                    ]
                )
            ),
            "evidence": {
                "runbook": "scripts/ppmi_verily_setup.md",
                "packet": "scripts/ppmi_verily_tier3_request_packet.md",
                "schema_probe_checklist": "scripts/ppmi_verily_schema_probe_checklist.md",
                "schema_probe_checklist_audit": (
                    "results/ppmi_verily_schema_probe_checklist_audit_20260515.json"
                ),
                "schema_probe_report_template": "scripts/ppmi_verily_schema_probe_report_template.md",
                "schema_probe_report_template_audit": (
                    "results/ppmi_verily_schema_probe_report_template_audit_20260515.json"
                ),
                "schema_probe_report_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
                "schema_probe_report_validator_audit": (
                    "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json"
                ),
                "target_free_manifest_template": "scripts/ppmi_verily_target_free_manifest_template.json",
                "target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
                "target_free_manifest_validator_audit": (
                    "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
                ),
                "target_free_manifest_validator_decision": ppmi_target_free_manifest_validator_audit.get(
                    "decision"
                ),
                "submission_package_validator": "scripts/validate_ppmi_verily_submission_package.py",
                "submission_package_validator_audit": (
                    "results/ppmi_verily_submission_package_validator_audit_20260515.json"
                ),
                "submission_package_validator_decision": ppmi_package_validator_audit.get("decision"),
                "submission_bundle": "results/ppmi_verily_submission_bundle_20260515.json",
                "zeroshot_blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
                "zeroshot_blueprint_audit": "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
                "zeroshot_blueprint_decision": ppmi_zeroshot_blueprint_audit.get("decision"),
                "zeroshot_blueprint_prompt_trace": blueprint_prompt_trace,
                "analysis_order": blueprint.get("analysis_order"),
                "result_record_requirements": blueprint.get("result_record_requirements"),
                "formula_sha_ppmi_contract_present": access.get(
                    "external_formula_sha_ppmi_contract_present"
                ),
                "formula_sha_ppmi_contract_negative_failed": access.get(
                    "external_formula_sha_ppmi_contract_negative_failed"
                ),
                "zeroshot_result_ppmi_contract_present": access.get(
                    "external_zeroshot_result_ppmi_contract_present"
                ),
                "zeroshot_result_ppmi_contract_negative_failed": access.get(
                    "external_zeroshot_result_ppmi_contract_negative_failed"
                ),
                "compute_ready_route_count": access.get("compute_ready_route_count"),
            },
        },
        {
            "id": "k250_external_branch_fixed_no_search",
            "directive": "K=250 sklearn GradientBoostingRegressor is a single fixed external branch, not a new internal sweep.",
            "passed": (
                "K=250" in ppmi_runbook
                and "GradientBoostingRegressor" in ppmi_runbook
                and "No K-search" in ppmi_packet
                and ppmi_zeroshot_blueprint_audit.get("passed") is True
                and get_path(blueprint_tracks.get("C", {}), "fixed_branch", "formula_sha256")
                == "489ca6bbc96520c2ea56cc53ee52b03542bec799f9bd41c34d9c9ef5b61ebee4"
                and get_path(blueprint_tracks.get("C", {}), "fixed_branch", "model")
                == "sklearn.ensemble.GradientBoostingRegressor"
                and get_path(blueprint_tracks.get("C", {}), "fixed_branch", "K") == 250
                and by_rank[10]["evidence"].get("fresh_internal_ccc") < T3_CEILING
                and get_path(by_rank[10], "evidence", "external_access", "compute_ready_route_count") == 0
            ),
            "evidence": {
                **by_rank[10]["evidence"],
                "zeroshot_blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
                "track_c": blueprint_tracks.get("C"),
            },
        },
        {
            "id": "user_side_submission_sequence_is_available_without_protected_content",
            "directive": "External access is the next action; package must support user-side submission without committing protected content.",
            "passed": (
                ppmi_bundle.get("passed") is True
                and ppmi_bundle.get("completed_packet_included") is False
                and ppmi_bundle.get("protected_data_included") is False
                and ppmi_bundle.get("content_boundary", {}).get("completed_packet_included")
                is False
                and ppmi_bundle.get("content_boundary", {}).get("completed_email_included")
                is False
                and ppmi_bundle.get("content_boundary", {}).get("protected_data_included")
                is False
                and ppmi_bundle.get("content_boundary", {}).get("credentials_or_tokens_included")
                is False
                and ppmi_bundle.get("content_boundary", {}).get("local_completed_paths_reported")
                is False
                and ppmi_bundle.get("fill_fields", {}).get("source_checklist")
                == "scripts/ppmi_verily_user_fill_checklist.md"
                and ppmi_bundle.get("fill_fields", {}).get("packet_field_count") == 13
                and ppmi_bundle.get("fill_fields", {}).get("email_field_count") == 12
                and ppmi_bundle.get("fill_fields", {}).get("submission_metadata_field_count") == 4
                and any(
                    "ppmi_verily_schema_probe_checklist.md" in str(step)
                    for step in ppmi_bundle.get("user_side_sequence", [])
                )
                and any(
                    "validate_ppmi_verily_submission_email.py" in str(step)
                    for step in ppmi_bundle.get("user_side_sequence", [])
                )
                and any(
                    "validate_ppmi_verily_submission_package.py" in str(step)
                    for step in ppmi_bundle.get("user_side_sequence", [])
                )
                and "validate_ppmi_verily_completed_packet.py" in ppmi_email
                and "validate_ppmi_verily_submission_email.py" in ppmi_email
                and "validate_ppmi_verily_submission_package.py" in ppmi_email
                and ppmi_package_validator_audit.get("passed") is True
                and ppmi_package_validator_audit.get("decision")
                == "ppmi_verily_submission_package_validator_ready"
                and "record_access_submission.py" in ppmi_email
                and "--pre-submission-preflight-passed" in ppmi_email
                and len(ppmi_bundle.get("user_side_sequence", [])) >= 6
                and any(
                    step.get("step_id") == "preflight_completed_package"
                    and "scripts/validate_ppmi_verily_submission_package.py"
                    in step.get("tools", [])
                    for step in ppmi_bundle.get("next_steps", [])
                )
                and any(
                    step.get("step_id") == "record_submission_metadata"
                    and "scripts/record_access_submission.py" in step.get("command_template", "")
                    for step in ppmi_bundle.get("next_steps", [])
                )
                and any(
                    step.get("step_id") == "record_approval_metadata"
                    and "scripts/record_access_approval.py" in step.get("command_template", "")
                    and step.get("blocked_until_approval") is True
                    and step.get("protected_compute_allowed") is False
                    for step in ppmi_bundle.get("next_steps", [])
                )
            ),
            "evidence": {
                "bundle": "results/ppmi_verily_submission_bundle_20260515.json",
                "email_template": "scripts/ppmi_verily_submission_email_template.md",
                "email_validator": "scripts/validate_ppmi_verily_submission_email.py",
                "package_validator": "scripts/validate_ppmi_verily_submission_package.py",
                "package_validator_audit": (
                    "results/ppmi_verily_submission_package_validator_audit_20260515.json"
                ),
                "completed_packet_included": ppmi_bundle.get("completed_packet_included"),
                "protected_data_included": ppmi_bundle.get("protected_data_included"),
                "content_boundary": ppmi_bundle.get("content_boundary"),
                "fill_fields": ppmi_bundle.get("fill_fields"),
                "schema_probe_checklist": "scripts/ppmi_verily_schema_probe_checklist.md",
                "next_steps": ppmi_bundle.get("next_steps"),
                "user_side_sequence": ppmi_bundle.get("user_side_sequence"),
            },
        },
        {
            "id": "no_remaining_local_weargait_model_action",
            "directive": "No more WearGait-only internal T3 CCC pushes without new data/access.",
            "passed": (
                remaining_blockers.get("passed") is True
                and len(remaining_blockers.get("local_model_actions", [])) == 0
                and len(remaining_blockers.get("unmatched_blockers", [])) == 0
                and "No more **WearGait-only internal T3 CCC pushes**" in prompt_text
            ),
            "evidence": {
                "audit": "results/remaining_blocker_action_audit_20260509.json",
                "passed": remaining_blockers.get("passed"),
                "local_model_action_count": len(remaining_blockers.get("local_model_actions", [])),
                "unmatched_blocker_count": len(remaining_blockers.get("unmatched_blockers", [])),
            },
        },
    ]


def combine_audit_checks(
    completion_checklist: list[dict[str, Any]],
    explicit_directive_checklist: list[dict[str, Any]],
    rejected_temptation_guard: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose all completion-audit checks under one generic field.

    The report keeps the three detailed checklist sections for readability.
    This normalized list prevents generic downstream consumers from treating
    the completion audit as having no checks simply because the checks are
    grouped by purpose.
    """

    combined: list[dict[str, Any]] = []
    for group, rows in [
        ("completion_audit_checklist", completion_checklist),
        ("explicit_directive_checklist", explicit_directive_checklist),
        ("rejected_temptation_guard", rejected_temptation_guard),
    ]:
        for row in rows:
            normalized = dict(row)
            normalized["check_group"] = group
            normalized["check_id"] = row.get("id")
            combined.append(normalized)
    return combined


def build_report() -> dict[str, Any]:
    prompt_source = get_prompt_requirements()
    rank1 = screen_summary(latest("results/screen_t1_S1_sumaware_bayesian_*.json"))
    rank2 = screen_summary(latest("results/screen_t1_topofractal8_sumaware_*.json"))
    rank3 = screen_summary(latest("results/screen_t1_S3_ordinal_composer_*.json"))
    rank5 = lockbox_arm_summary(
        latest_real("results/lockbox_t1_S5_microbatch_item13only_audit_*.json"),
        "item13_PH_alpha100_PRIMARY",
    )
    rank6_obj = load_json(latest_real("results/lockbox_t1_S6_stability_sparse_score_*.json"))
    rank7 = retained_summary(latest_real("results/lockbox_t1_S7_multiitem_topology_abstention_*.json"), "s7")
    rank8 = screen_summary(latest("results/screen_t1_rank8_tug_phase_ph_mfdfa_*.json"))
    rank9 = screen_summary(latest("results/screen_t1_S9_topofractal_prototype_*.json"))
    rank10 = load_json(latest("results/lockbox_t3_S10_k250_hgb_fresh_replication_*.json"))
    rank11 = screen_summary(latest("results/screen_t3_S11_observable_decomposition_*.json"))
    rank12 = retained_summary(latest("results/screen_t3_S12_unobservability_abstention_*.json"), "s12")
    s13_s15 = s13_s15_summary(
        latest_real("results/lockbox_t3_S13_ph_mfdfa_t3_transfer_*.json"),
        latest("results/audit_t3_S13_S15_retained_bootstrap_*.json"),
        latest("results/lockbox_t3_S13_ph_mfdfa_t3_transfer_*_scrambled_y.json"),
        latest("results/lockbox_t3_S13_ph_mfdfa_t3_transfer_*_sid_shuffle.json"),
        latest("results/lockbox_t3_S13_ph_mfdfa_t3_transfer_*_sanityYnan.json"),
    )
    s8_joint = lockbox_arm_summary(
        latest_real("results/lockbox_t1_S8_item12mfdfa_item13ph_joint_*.json"),
        "JOINT",
    )
    x4_2bag = x4_equal_weight_2bag_summary(
        latest_real("results/lockbox_t1_X4_equal_weight_2bag_*.json"),
    )
    x4_status_audit = load_json(RESULTS / "t1_x4_equal_weight_2bag_status_20260516.json")
    access = external_status()
    slotf_replication_audit = load_json(RESULTS / "t3_slotF_replication_audit_20260515.json")
    ppmi_submit_format_audit = load_json(RESULTS / "ppmi_verily_submit_format_audit_20260515.json")
    ppmi_email_template_audit = load_json(
        RESULTS / "ppmi_verily_submission_email_template_audit_20260515.json"
    )
    ppmi_email_validator_audit = load_json(
        RESULTS / "ppmi_verily_submission_email_validator_audit_20260515.json"
    )
    ppmi_package_validator_audit = load_json(
        RESULTS / "ppmi_verily_submission_package_validator_audit_20260515.json"
    )
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
    ppmi_next_action_status_audit = load_json(
        RESULTS / "ppmi_verily_next_action_status_audit_20260515.json"
    )
    ppmi_submission_bundle = load_json(RESULTS / "ppmi_verily_submission_bundle_20260515.json")
    ppmi_current_submission_handoff = load_json(
        RESULTS / "ppmi_verily_current_submission_handoff_20260515.json"
    )
    ppmi_zeroshot_blueprint_audit = load_json(
        RESULTS / "ppmi_verily_zeroshot_blueprint_audit_20260515.json"
    )
    current_state_verification = load_json(
        RESULTS / "current_goal_state_verification_20260508.json"
    )
    current_next_action_handoff = load_json(
        RESULTS / "current_next_action_handoff_20260515.json"
    )

    numbered = [
        {
            "rank": 1,
            "requirement": "Sum-aware multi-task Bayesian residual composer over PH/MFDFA item heads",
            "status": "covered_failed",
            "evidence": rank1,
        },
        {
            "rank": 2,
            "requirement": "Target-free TopoFractal-8 PH/MFDFA compression",
            "status": "covered_failed",
            "evidence": rank2,
        },
        {
            "rank": 3,
            "requirement": "Ordinal bounded item-distribution composer",
            "status": "covered_failed_class_sparsity",
            "evidence": rank3,
        },
        {
            "rank": 4,
            "requirement": "PPMI/Verily topology-first external transport after access approval",
            "status": "blocked_external_access_required",
            "evidence": {
                **access,
                "generic_completed_packet_validator": "scripts/validate_access_request_packet.py",
                "generic_completed_packet_validator_audit": (
                    "results/access_request_packet_validator_audit_20260515.json"
                ),
                "generic_fill_checklist": "scripts/show_access_request_fill_checklist.py",
                "generic_fill_checklist_audit": (
                    "results/access_request_fill_checklist_audit_20260515.json"
                ),
                "external_submission_index": "results/external_access_submission_index_20260515.md",
                "external_submission_index_audit": (
                    "results/external_access_submission_index_audit_20260515.json"
                ),
                "external_lifecycle_status": "scripts/show_external_access_lifecycle.py",
                "external_lifecycle_status_audit": (
                    "results/external_access_lifecycle_status_audit_20260515.json"
                ),
                "external_schema_probe_handoff": (
                    "results/external_schema_probe_handoff_20260515.md"
                ),
                "external_schema_probe_handoff_audit": (
                    "results/external_schema_probe_handoff_audit_20260515.json"
                ),
                "generic_schema_probe_report_validator": "scripts/validate_schema_probe_report.py",
                "generic_schema_probe_report_validator_audit": (
                    "results/external_schema_probe_report_validator_audit_20260515.json"
                ),
                "generic_target_free_manifest_validator": "scripts/validate_target_free_manifest.py",
                "generic_target_free_manifest_validator_audit": (
                    "results/external_target_free_manifest_validator_audit_20260515.json"
                ),
                "external_target_free_manifest_templates": (
                    "results/external_target_free_manifest_templates_20260515.md"
                ),
                "external_target_free_manifest_templates_audit": (
                    "results/external_target_free_manifest_templates_audit_20260515.json"
                ),
                "external_zeroshot_blueprint_handoff": (
                    "results/external_zeroshot_blueprint_handoff_20260515.md"
                ),
                "external_zeroshot_blueprint_handoff_audit": (
                    "results/external_zeroshot_blueprint_handoff_audit_20260515.json"
                ),
                "external_formula_sha_templates": (
                    "results/external_formula_sha_templates_20260515.md"
                ),
                "external_formula_sha_templates_audit": (
                    "results/external_formula_sha_templates_audit_20260515.json"
                ),
                "external_zeroshot_result_templates": (
                    "results/external_zeroshot_result_templates_20260515.md"
                ),
                "external_zeroshot_result_templates_audit": (
                    "results/external_zeroshot_result_templates_audit_20260515.json"
                ),
                "external_access_queue_status": "scripts/show_external_access_queue.py",
                "external_access_queue_status_audit": (
                    "results/external_access_queue_status_audit_20260515.json"
                ),
                "request_packet": "scripts/ppmi_verily_tier3_request_packet.md",
                "word_template": "results/ppmi_verily_tier3_request_packet_template_20260515.docx",
                "word_template_audit": "results/ppmi_verily_submit_format_audit_20260515.json",
                "submission_email_template": "scripts/ppmi_verily_submission_email_template.md",
                "submission_email_template_audit": (
                    "results/ppmi_verily_submission_email_template_audit_20260515.json"
                ),
                "submission_email_validator": "scripts/validate_ppmi_verily_submission_email.py",
                "submission_email_validator_audit": (
                    "results/ppmi_verily_submission_email_validator_audit_20260515.json"
                ),
                "submission_package_validator": "scripts/validate_ppmi_verily_submission_package.py",
                "submission_package_validator_audit": (
                    "results/ppmi_verily_submission_package_validator_audit_20260515.json"
                ),
                "schema_probe_checklist": "scripts/ppmi_verily_schema_probe_checklist.md",
                "schema_probe_checklist_audit": (
                    "results/ppmi_verily_schema_probe_checklist_audit_20260515.json"
                ),
                "schema_probe_report_template": "scripts/ppmi_verily_schema_probe_report_template.md",
                "schema_probe_report_template_audit": (
                    "results/ppmi_verily_schema_probe_report_template_audit_20260515.json"
                ),
                "schema_probe_report_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
                "schema_probe_report_validator_audit": (
                    "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json"
                ),
                "target_free_manifest_template": "scripts/ppmi_verily_target_free_manifest_template.json",
                "target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
                "target_free_manifest_validator_audit": (
                    "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
                ),
                "completed_packet_validator": "scripts/validate_ppmi_verily_completed_packet.py",
                "completed_packet_validator_audit": (
                    "results/ppmi_verily_completed_packet_validator_audit_20260515.json"
                ),
                "next_action_status": "scripts/show_ppmi_verily_next_action.py",
                "next_action_status_audit": (
                    "results/ppmi_verily_next_action_status_audit_20260515.json"
                ),
                "submission_bundle": "results/ppmi_verily_submission_bundle_20260515.json",
                "zeroshot_blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
                "zeroshot_blueprint_audit": "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
                "k250_blueprint": "results/lockbox_ppmi_replication_blueprint_20260514T151939Z.json",
            },
        },
        {
            "rank": 5,
            "requirement": "Fixed PH/MFDFA micro-batch correction for items 10/13/14",
            "status": "covered_failed_or_sub_mcid",
            "evidence": {
                "item13_microbatch": rank5,
                "best_followup_joint_item12_13": s8_joint,
            },
        },
        {
            "rank": 6,
            "requirement": "Stability-constrained sparse biomechanical score discovery",
            "status": "covered_descriptiveness_null",
            "evidence": {
                "path": rel(latest("results/lockbox_t1_S6_stability_sparse_score_*.json")),
                "verdict": rank6_obj.get("verdict"),
                "stable_cols_item13": len(get_path(rank6_obj, "stable_cols_per_item", "item_13") or []),
                "stable_cols_item14": len(get_path(rank6_obj, "stable_cols_per_item", "item_14") or []),
                "stable_cols_item10": len(get_path(rank6_obj, "stable_cols_per_item", "item_10") or []),
            },
        },
        {
            "rank": 7,
            "requirement": "Y-free item-level selective prediction from topology disagreement",
            "status": "covered_failed_deployable_secondary",
            "evidence": rank7,
        },
        {
            "rank": 8,
            "requirement": "TUG phase-specific PH/MFDFA microfeatures",
            "status": "covered_failed",
            "evidence": {
                **rank8,
                "cache": rel(latest("results/cache_tug_phase_ph_mfdfa_*.csv")),
                "manifest": rel(latest("results/cache_tug_phase_ph_mfdfa_*.csv.manifest.json")),
            },
        },
        {
            "rank": 9,
            "requirement": "Fold-local sparse prototype regression over TopoFractal state",
            "status": "covered_failed",
            "evidence": rank9,
        },
        {
            "rank": 10,
            "requirement": "Canonical Stage-1 + K=250 sklearn Gradient Boosting tail model",
            "status": "blocked_for_external_replication_internal_checks_negative",
            "evidence": {
                "fresh_internal_replication": rel(latest("results/lockbox_t3_S10_k250_hgb_fresh_replication_*.json")),
                "fresh_internal_ccc": rank10.get("k250_hgb_pooled_ccc"),
                "delta_vs_iter47": rank10.get("delta_vs_iter47"),
                "frac_positive": rank10.get("bootstrap_frac_pos"),
                "verdict": rank10.get("verdict"),
                "external_blueprint": "results/lockbox_ppmi_replication_blueprint_20260514T151939Z.json",
                "zeroshot_blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
                "zeroshot_blueprint_audit": "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
                "external_access": access,
            },
        },
        {
            "rank": 11,
            "requirement": "Latent observable-T3 decomposition with non-gait nuisance prior",
            "status": "covered_failed",
            "evidence": rank11,
        },
        {
            "rank": 12,
            "requirement": "T3 unobservability-risk abstention from decomposition disagreement",
            "status": "covered_failed_deployable_secondary",
            "evidence": rank12,
        },
    ]

    s8_t1_attempt = {
        "source": "S8 item12 MFDFA + item13 PH joint follow-up",
        "path": s8_joint.get("path"),
        "ccc": s8_joint.get("candidate_ccc"),
        "delta_vs_iter34": s8_joint.get("delta_ccc"),
        "frac_positive": s8_joint.get("frac_positive"),
        "verdict": s8_joint.get("verdict"),
        "passes_gate": bool(
            isinstance(s8_joint.get("delta_ccc"), (int, float))
            and s8_joint["delta_ccc"] >= T1_MCID
            and isinstance(s8_joint.get("frac_positive"), (int, float))
            and s8_joint["frac_positive"] >= 0.95
        ),
    }
    x4_t1_attempt = {
        "source": "X4 equal-weight 2-bag V2+V3-GSP",
        "path": x4_2bag.get("path"),
        "ccc": x4_2bag.get("candidate_ccc"),
        "mae": x4_2bag.get("candidate_mae"),
        "delta_vs_iter34": x4_2bag.get("delta_ccc"),
        "delta_mae": x4_2bag.get("delta_mae"),
        "frac_positive": x4_2bag.get("frac_positive"),
        "frac_positive_seed_A": x4_2bag.get("frac_positive_seed_A"),
        "frac_positive_seed_B": x4_2bag.get("frac_positive_seed_B"),
        "verdict": x4_2bag.get("verdict"),
        "status_audit": "results/t1_x4_equal_weight_2bag_status_20260516.json",
        "status_audit_passed": x4_status_audit.get("passed"),
        "status_decision": x4_status_audit.get("decision"),
        "passes_gate": x4_2bag.get("passes_gate") is True,
    }
    t1_candidate_attempts = [
        attempt
        for attempt in (s8_t1_attempt, x4_t1_attempt)
        if isinstance(attempt.get("ccc"), (int, float))
    ]
    t1_best = max(t1_candidate_attempts, key=lambda attempt: attempt["ccc"])
    t3_best = {
        "source": "S11 direct 5-fold screen / S10 fresh replication",
        "screen_direct_ccc": get_path(
            load_json(latest("results/screen_t3_S11_observable_decomposition_*.json")),
            "real_screen",
            "ensemble",
            "direct_metrics",
            "ccc",
        ),
        "screen_decomposed_ccc": rank11.get("candidate_ccc"),
        "fresh_k250_ccc": rank10.get("k250_hgb_pooled_ccc"),
        "passes_gate": False,
    }

    completion_checklist = build_completion_checklist(
        numbered,
        access,
        slotf_replication_audit,
        s13_s15,
        ppmi_submit_format_audit,
        ppmi_email_template_audit,
        ppmi_email_validator_audit,
        ppmi_package_validator_audit,
        ppmi_schema_probe_checklist_audit,
        ppmi_schema_probe_template_audit,
        ppmi_schema_probe_report_validator_audit,
        ppmi_target_free_manifest_validator_audit,
        ppmi_completed_packet_validator_audit,
        ppmi_next_action_status_audit,
        ppmi_submission_bundle,
        ppmi_current_submission_handoff,
        ppmi_zeroshot_blueprint_audit,
        current_state_verification,
        current_next_action_handoff,
    )
    rejected_temptation_guard = build_rejected_temptation_guard()
    explicit_directive_checklist = build_explicit_directive_checklist(numbered, access)
    checks = combine_audit_checks(
        completion_checklist,
        explicit_directive_checklist,
        rejected_temptation_guard,
    )
    completion_checklist_failures = [
        check["id"] for check in completion_checklist if not check["passed"]
    ]
    rejected_guard_failures = [
        check["id"] for check in rejected_temptation_guard if not check["passed"]
    ]
    explicit_directive_failures = [
        check["id"] for check in explicit_directive_checklist if not check["passed"]
    ]
    hard_gaps = []
    if not t1_best["passes_gate"]:
        hard_gaps.append("No T1 full-cohort candidate beats iter34 by the promotion/MCID gate.")
    if not t3_best["passes_gate"]:
        hard_gaps.append("No T3 full-cohort candidate beats iter47 by the promotion/MCID gate.")
    if access["compute_ready_route_count"] != 0:
        hard_gaps.append("Unexpected external compute-ready route state needs manual review.")
    if completion_checklist_failures:
        hard_gaps.append(
            "Prompt-to-artifact completion checklist has failed checks: "
            + ", ".join(completion_checklist_failures)
        )
    if rejected_guard_failures:
        hard_gaps.append(
            "Rejected-temptation guard has failed checks: "
            + ", ".join(rejected_guard_failures)
        )
    if explicit_directive_failures:
        hard_gaps.append(
            "Explicit prompt-directive checklist has failed checks: "
            + ", ".join(explicit_directive_failures)
        )

    current_verified_next_action = {
        "source": "results/current_goal_state_verification_20260508.json",
        "current_state_verified": current_state_verification.get("current_state_verified"),
        "goal_complete": current_state_verification.get("goal_complete"),
        "next_action": current_state_verification.get("next_action"),
        "pre_submission_handoff": current_state_verification.get("pre_submission_handoff"),
        "access_lifecycle_current_action": current_state_verification.get(
            "access_lifecycle_current_action"
        ),
    }

    return {
        "name": "proresults_prompt_to_artifact_audit",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "objective": "Break the T1 + T3 CCC glass ceiling by following /tmp/pro-results.txt.",
        "prompt_source": prompt_source,
        "success_criteria": {
            "t1": "Reportable full-cohort T1 CCC must beat iter34 hygiene-corrected 0.7170 under current gates.",
            "t3": "Reportable full-cohort T3 CCC must beat iter47 corrected-target 0.3784 under current gates.",
            "secondary": "Retained-coverage/deployable improvements do not complete the full-cohort objective.",
        },
        "completion_audit_checklist": completion_checklist,
        "completion_audit_passed": not completion_checklist_failures,
        "completion_audit_failures": completion_checklist_failures,
        "explicit_directive_checklist": explicit_directive_checklist,
        "explicit_directive_checklist_passed": not explicit_directive_failures,
        "explicit_directive_checklist_failures": explicit_directive_failures,
        "rejected_temptation_guard": rejected_temptation_guard,
        "rejected_temptation_guard_passed": not rejected_guard_failures,
        "rejected_temptation_guard_failures": rejected_guard_failures,
        "checks": checks,
        "checks_passed": all(check["passed"] for check in checks),
        "check_failures": [
            f"{check['check_group']}:{check['check_id']}"
            for check in checks
            if not check["passed"]
        ],
        "numbered_prompt_checklist": numbered,
        "ceiling_break_evidence": {
            "t1_best_attempt": t1_best,
            "t1_candidate_attempts": t1_candidate_attempts,
            "t3_best_attempt": t3_best,
            "s13_s15_t3_transfer_extension": s13_s15,
            "t3_slotF_deployable_replication": {
                "audit": "results/t3_slotF_replication_audit_20260515.json",
                "decision": slotf_replication_audit.get("decision"),
                "coverage_rows": slotf_replication_audit.get("coverage_rows"),
            },
        },
        "external_access_state": access,
        "current_verified_next_action": current_verified_next_action,
        "current_submission_handoff": {
            "source": "results/ppmi_verily_current_submission_handoff_20260515.json",
            "passed": ppmi_current_submission_handoff.get("passed"),
            "decision": ppmi_current_submission_handoff.get("decision"),
            "current_action": ppmi_current_submission_handoff.get("current_action"),
            "package_artifacts": ppmi_current_submission_handoff.get("package_artifacts"),
            "content_boundary": ppmi_current_submission_handoff.get("content_boundary"),
        },
        "all_numbered_items_covered_or_access_blocked": all(
            row["status"].startswith("covered") or row["status"].startswith("blocked")
            for row in numbered
        ),
        "goal_complete": False,
        "hard_gaps": hard_gaps,
        "next_allowed_action": (
            "No local WearGait-only model run is justified by this checklist. "
            "The next ceiling-break action is external access approval/submission "
            "for PPMI/Verily or another queued route, then a read-only schema probe."
        ),
        "next_non_redundant_actions": [
            "User or institutional PI completes and submits the PPMI/Verily access request packet.",
            "Use results/external_access_submission_index_20260515.md as the stable content-free route handoff before filling packets outside git.",
            "Use scripts/show_external_access_lifecycle.py to choose the next safe route action after any submission, approval, or schema-probe metadata record.",
            "Use results/external_schema_probe_handoff_20260515.md after approval to map each queued route to its required schema sections, grouping keys, targets, sensors, and ordered post-approval workflow commands.",
            "Use results/external_target_free_manifest_templates_20260515.md after schema metadata is recorded to fill a route-specific target-free manifest outside git and follow its ordered post-schema validation workflow before scoring/reporting.",
            "Use results/external_zeroshot_blueprint_handoff_20260515.md after schema and manifest preflight to keep the first route score on the locked zero-shot analysis order.",
            "Use results/external_formula_sha_templates_20260515.md after schema and manifest preflight to validate a formula SHA before external extraction or scoring.",
            "Use results/external_zeroshot_result_templates_20260515.md after external zero-shot scoring to validate aggregate-only result reporting without internal canonical promotion.",
            "Before sending, run the completed-packet, completed-email, and combined package validators from the current verified next-action handoff.",
            "For PPMI/Verily, use scripts/show_ppmi_verily_next_action.py and scripts/ppmi_verily_user_fill_checklist.md before filling the local packet/email outside git; for non-PPMI queued routes, run scripts/show_access_request_fill_checklist.py with that route_id before filling the local request packet outside git.",
            "For any non-PPMI queued route, first run scripts/validate_access_request_packet.py with that route_id and the local completed packet path.",
            "After sending, record only non-protected submission metadata with scripts/record_access_submission.py and --pre-submission-preflight-passed.",
            "After data-owner approval, record non-protected approval metadata, then preflight PPMI local schema-probe reports with scripts/validate_ppmi_verily_schema_probe_report.py and PPMI target-free manifests with scripts/validate_ppmi_verily_target_free_manifest.py; non-PPMI routes use scripts/validate_schema_probe_report.py and scripts/validate_target_free_manifest.py. Record schema metadata, validate the formula-SHA record with scripts/validate_external_formula_sha_record.py before extraction or scoring, then validate aggregate result metadata with scripts/validate_external_zeroshot_result_record.py after scoring and before reporting.",
        ],
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Pro-Results Prompt-to-Artifact Audit - 2026-05-15",
        "",
        f"Objective: {report['objective']}",
        f"Prompt source: `{report['prompt_source']['prompt_path']}` "
        f"(sha256 `{report['prompt_source']['sha256']}`, "
        f"{report['prompt_source']['line_count']} lines)",
        "",
        "## Success Criteria",
        "",
        f"- T1: {report['success_criteria']['t1']}",
        f"- T3: {report['success_criteria']['t3']}",
        f"- Secondary: {report['success_criteria']['secondary']}",
        "",
        "## Numbered Checklist",
        "",
        "| Rank | Status | Requirement | Evidence | Key result |",
        "|---:|---|---|---|---|",
    ]
    for row in report["numbered_prompt_checklist"]:
        ev = row["evidence"]
        evidence_path = (
            ev.get("path")
            or ev.get("fresh_internal_replication")
            or ev.get("request_packet")
            or get_path(ev, "item13_microbatch", "path")
            or get_path(ev, "best_followup_joint_item12_13", "path")
        )
        key_bits = []
        for label, key in (
            ("ccc", "candidate_ccc"),
            ("delta", "delta_ccc"),
            ("frac", "frac_positive"),
            ("verdict", "verdict"),
            ("cov70", "cov_70_best_ccc"),
            ("cov50", "cov_50_best_ccc"),
        ):
            val = ev.get(key)
            if val is not None:
                key_bits.append(f"{label}={val}")
        if row["rank"] == 4:
            key_bits.append(f"compute_ready={ev.get('compute_ready_route_count')}")
        if row["rank"] == 10:
            key_bits.append(f"fresh_ccc={ev.get('fresh_internal_ccc')}")
            key_bits.append(f"delta={ev.get('delta_vs_iter47')}")
        if row["rank"] == 5:
            key_bits.append(f"item13_delta={get_path(ev, 'item13_microbatch', 'delta_ccc')}")
            key_bits.append(f"joint_delta={get_path(ev, 'best_followup_joint_item12_13', 'delta_ccc')}")
        lines.append(
            f"| {row['rank']} | `{row['status']}` | {row['requirement']} | "
            f"`{evidence_path}` | {'; '.join(key_bits)} |"
        )

    lines.extend([
        "",
        "## Completion-Audit Coverage",
        "",
        "| Check | Passed | Evidence |",
        "|---|---:|---|",
    ])
    for check in report["completion_audit_checklist"]:
        evidence = check.get("evidence", {})
        if isinstance(evidence, dict):
            if evidence.get("path"):
                evidence_text = evidence["path"]
            elif evidence.get("prompt_path"):
                evidence_text = evidence["prompt_path"]
            elif evidence.get("request_packet"):
                evidence_text = evidence["request_packet"].get("path", "request_packet")
            else:
                evidence_text = ", ".join(sorted(str(k) for k in evidence.keys())[:6])
        else:
            evidence_text = str(evidence)
        lines.append(f"| `{check['id']}` | `{check['passed']}` | {evidence_text} |")

    lines.extend([
        "",
        "## Explicit Prompt Directives",
        "",
        "| Directive | Passed | Evidence |",
        "|---|---:|---|",
    ])
    for check in report["explicit_directive_checklist"]:
        evidence = check.get("evidence", {})
        if isinstance(evidence, dict):
            if evidence.get("result"):
                evidence_text = evidence["result"]
            elif evidence.get("audit"):
                evidence_text = evidence["audit"]
            elif evidence.get("runbook"):
                evidence_text = evidence["runbook"]
            elif evidence.get("bundle"):
                evidence_text = evidence["bundle"]
            else:
                evidence_text = ", ".join(sorted(str(k) for k in evidence.keys())[:6])
        else:
            evidence_text = str(evidence)
        lines.append(f"| `{check['id']}` | `{check['passed']}` | {evidence_text} |")

    lines.extend([
        "",
        "## Rejected-Temptation Guard",
        "",
        "| Rule | Passed | Evidence |",
        "|---|---:|---|",
    ])
    for check in report["rejected_temptation_guard"]:
        hits = check.get("evidence_hits", [])
        evidence_text = "; ".join(
            f"{hit['path']}::{hit['snippet']}" for hit in hits[:2]
        )
        lines.append(f"| `{check['id']}` | `{check['passed']}` | {evidence_text} |")

    lines.extend([
        "",
        "## Ceiling Break Evidence",
        "",
        f"- T1 best attempt: `{report['ceiling_break_evidence']['t1_best_attempt']['source']}`; "
        f"CCC `{report['ceiling_break_evidence']['t1_best_attempt']['ccc']}`, "
        f"delta `{report['ceiling_break_evidence']['t1_best_attempt']['delta_vs_iter34']}`, "
        f"frac>0 `{report['ceiling_break_evidence']['t1_best_attempt']['frac_positive']}`.",
        f"- T3 best attempt: `{report['ceiling_break_evidence']['t3_best_attempt']['source']}`; "
        f"fresh K250 CCC `{report['ceiling_break_evidence']['t3_best_attempt']['fresh_k250_ccc']}`, "
        f"S11 direct screen CCC `{report['ceiling_break_evidence']['t3_best_attempt']['screen_direct_ccc']}`.",
        f"- S13/S15 T3 transfer extension: S13 JOINT delta "
        f"`{report['ceiling_break_evidence']['s13_s15_t3_transfer_extension']['joint_delta']}`, "
        f"S15 @70% frac>full "
        f"`{report['ceiling_break_evidence']['s13_s15_t3_transfer_extension']['s15_cov70_frac_positive']}`, "
        f"S15 @50% frac>full "
        f"`{report['ceiling_break_evidence']['s13_s15_t3_transfer_extension']['s15_cov50_frac_positive']}`.",
        "",
        "## Decision",
        "",
        f"- All numbered items covered or access-blocked: `{report['all_numbered_items_covered_or_access_blocked']}`",
        f"- Completion-audit checklist passed: `{report['completion_audit_passed']}`",
        f"- Explicit prompt-directive checklist passed: `{report['explicit_directive_checklist_passed']}`",
        f"- Rejected-temptation guard passed: `{report['rejected_temptation_guard_passed']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Hard gaps: `{len(report['hard_gaps'])}`",
    ])
    for gap in report["hard_gaps"]:
        lines.append(f"  - {gap}")
    next_action = report.get("current_verified_next_action", {}).get("next_action") or {}
    pre_submission = (
        report.get("current_verified_next_action", {}).get("pre_submission_handoff") or {}
    )
    lines.extend(
        [
            "",
            "## Current Verified Next Action",
            "",
            f"- Source: `{report.get('current_verified_next_action', {}).get('source')}`",
            f"- Action: `{next_action.get('action_id')}`",
            f"- Safe to execute code now: `{next_action.get('safe_to_execute_code_now')}`",
            f"- Fill checklist: `{next_action.get('use_fill_checklist')}`",
            f"- Packet fields to fill: `{(next_action.get('fill_fields') or {}).get('packet_field_count')}`",
            f"- Email fields to fill: `{(next_action.get('fill_fields') or {}).get('email_field_count')}`",
            f"- Completed package validator: `{pre_submission.get('completed_package_validator')}`",
            f"- Record submission command template: `{pre_submission.get('record_submission_command_template')}`",
            f"- Record approval command template: `{pre_submission.get('record_approval_command_template')}`",
            "",
            f"Next allowed action: {report['next_allowed_action']}",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"goal_complete={report['goal_complete']}")
    print(f"hard_gaps={len(report['hard_gaps'])}")


if __name__ == "__main__":
    main()
