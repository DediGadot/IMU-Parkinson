#!/usr/bin/env python3
"""Audit the content-free PPMI / Verily zero-shot transport blueprint."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
WRITER = ROOT / "scripts" / "write_ppmi_verily_zeroshot_blueprint.py"
BLUEPRINT_JSON = RESULTS / "ppmi_verily_zeroshot_blueprint_20260515.json"
OUT_JSON = RESULTS / "ppmi_verily_zeroshot_blueprint_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_zeroshot_blueprint_audit_20260515.md"
PRORESULTS_AUDIT = RESULTS / "proresults_prompt_to_artifact_audit_20260515.json"
ZEROSHOT_RESULT_TEMPLATES_AUDIT = RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
K250_FORMULA_SHA = "489ca6bbc96520c2ea56cc53ee52b03542bec799f9bd41c34d9c9ef5b61ebee4"

EXPECTED_ANALYSIS_ORDER = [
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


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_path(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def track_by_id(blueprint: dict[str, Any], track_id: str) -> dict[str, Any]:
    for track in blueprint.get("tracks", []):
        if track.get("track_id") == track_id:
            return track
    return {}


def check(name: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    writer_proc = subprocess.run(
        [sys.executable, str(WRITER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    report = load_json(BLUEPRINT_JSON)
    blueprint = report.get("blueprint", {})
    track_a = track_by_id(blueprint, "A")
    track_b = track_by_id(blueprint, "B")
    track_c = track_by_id(blueprint, "C")
    track_d = track_by_id(blueprint, "D")
    analysis_order = blueprint.get("analysis_order", [])
    no_search = blueprint.get("locked_no_search_rules", [])
    manifest_fields = get_path(blueprint, "manifest_requirements", "required_fields") or []
    manifest_requirements = blueprint.get("manifest_requirements", {})
    result_record_requirements = blueprint.get("result_record_requirements", {})
    source_prompt_trace = blueprint.get("source_prompt_trace", {})
    current_internal_refs = blueprint.get("current_internal_references", {})
    if not isinstance(current_internal_refs, dict):
        current_internal_refs = {}
    t1_candidate = current_internal_refs.get("t1_candidate") or {}
    t1_reference_baseline = current_internal_refs.get("t1_reference_baseline") or {}
    source_best_t1 = source_prompt_trace.get("current_best_failed_t1_attempt") or {}
    x4_boundary = get_path(
        blueprint, "sensor_compatibility_boundaries", "x4_v2_v3_gsp_2bag"
    ) or {}
    proresults_audit = load_json(PRORESULTS_AUDIT)
    prompt_source = proresults_audit.get("prompt_source", {})
    zeroshot_result_templates_audit = load_json(ZEROSHOT_RESULT_TEMPLATES_AUDIT)

    checks = [
        check(
            "writer runs and writes blueprint",
            writer_proc.returncode == 0 and BLUEPRINT_JSON.exists(),
            {"returncode": writer_proc.returncode, "output_tail": writer_proc.stdout[-2000:]},
        ),
        check(
            "blueprint is content-free and not a completion marker",
            report.get("not_a_model_result") is True
            and report.get("not_access_approval") is True
            and report.get("not_a_schema_probe") is True
            and report.get("not_a_preregistration") is True
            and report.get("protected_data_included") is False
            and report.get("credentials_or_tokens_included") is False
            and report.get("goal_complete") is False
            and get_path(blueprint, "content_boundary", "goal_complete") is False,
            {
                "not_a_model_result": report.get("not_a_model_result"),
                "not_access_approval": report.get("not_access_approval"),
                "not_a_schema_probe": report.get("not_a_schema_probe"),
                "not_a_preregistration": report.get("not_a_preregistration"),
                "protected_data_included": report.get("protected_data_included"),
                "credentials_or_tokens_included": report.get("credentials_or_tokens_included"),
                "goal_complete": report.get("goal_complete"),
            },
        ),
        check(
            "blueprint is anchored to exact pro-results prompt and rank4 directive",
            source_prompt_trace.get("source_audit")
            == "results/proresults_prompt_to_artifact_audit_20260515.json"
            and source_prompt_trace.get("prompt_path") == "/tmp/pro-results.txt"
            and source_prompt_trace.get("prompt_sha256") == prompt_source.get("sha256")
            and isinstance(source_prompt_trace.get("prompt_sha256"), str)
            and len(source_prompt_trace.get("prompt_sha256", "")) == 64
            and source_prompt_trace.get("prompt_line_count") == prompt_source.get("line_count")
            and source_prompt_trace.get("prompt_rank") == 4
            and source_prompt_trace.get("prompt_rank_requirement")
            == "PPMI/Verily topology-first external transport after access approval"
            and source_prompt_trace.get("best_algorithm_with_data_access")
            == "PPMI/Verily topology-first external transport"
            and source_prompt_trace.get("source_goal_complete") is False
            and "No T1 full-cohort candidate beats iter34 by the promotion/MCID gate."
            in (source_prompt_trace.get("source_hard_gaps") or [])
            and "No T3 full-cohort candidate beats iter47 by the promotion/MCID gate."
            in (source_prompt_trace.get("source_hard_gaps") or [])
            and all(
                item in (source_prompt_trace.get("required_locked_formula_components") or [])
                for item in [
                    "small fixed TopoFractal PH/MFDFA branch",
                    "canonical comparator",
                    "separate fixed K=250 sklearn-GB branch for T3 only",
                    "no omnibus feature expansion",
                    "no cross-branch adaptive stacking before zero-shot results",
                ]
            ),
            {
                "source_prompt_trace": source_prompt_trace,
                "proresults_prompt_source": prompt_source,
                "proresults_goal_complete": proresults_audit.get("goal_complete"),
                "proresults_hard_gaps": proresults_audit.get("hard_gaps"),
            },
        ),
        check(
            "source trace records X4 as current failed T1 near-miss",
            source_best_t1.get("source") == "X4 equal-weight 2-bag V2+V3-GSP"
            and source_best_t1.get("passes_gate") is False
            and source_best_t1.get("status_decision") == "x4_near_miss_not_promoted"
            and source_best_t1.get("status_audit")
            == "results/t1_x4_equal_weight_2bag_status_20260516.json"
            and source_best_t1.get("status_audit_passed") is True
            and abs(float(source_best_t1.get("ccc", 0.0)) - 0.7345218263626917)
            < 1e-12
            and abs(
                float(source_best_t1.get("delta_vs_iter34", 0.0))
                - 0.017483986061199164
            )
            < 1e-12,
            {"current_best_failed_t1_attempt": source_best_t1},
        ),
        check(
            "current T1 references use X4 near-miss with iter34 baseline",
            t1_candidate.get("name") == "T1 X4 equal-weight 2-bag V2+V3-GSP near-miss"
            and abs(float(t1_candidate.get("ccc", 0.0)) - 0.7345218263626917)
            < 1e-12
            and abs(
                float(t1_candidate.get("delta_vs_iter34", 0.0))
                - 0.017483986061199164
            )
            < 1e-12
            and t1_candidate.get("status_decision") == "x4_near_miss_not_promoted"
            and "not promoted" in str(t1_candidate.get("claim_boundary", ""))
            and "wrist-only PPMI" in str(t1_candidate.get("claim_boundary", ""))
            and t1_reference_baseline.get("name") == "T1 iter34 hygiene-corrected candidate"
            and t1_reference_baseline.get("ccc") == 0.7170
            and t1_reference_baseline.get("n") == 92,
            {
                "t1_candidate": t1_candidate,
                "t1_reference_baseline": t1_reference_baseline,
            },
        ),
        check(
            "route and access prerequisites are explicit",
            blueprint.get("route_id") == "ppmi_verily"
            and blueprint.get("status") == "pre_access_design_blueprint_not_preregistration"
            and "standard PPMI approval" in blueprint.get("access_prerequisites", [])
            and "Verily Raw Device Data Tier-3 approval" in blueprint.get("access_prerequisites", [])
            and "read-only schema probe" in blueprint.get("access_prerequisites", [])
            and "completed schema-probe report validator pass" in blueprint.get("access_prerequisites", []),
            {"route_id": blueprint.get("route_id"), "access_prerequisites": blueprint.get("access_prerequisites")},
        ),
        check(
            "rank4 topology-first analysis order is locked",
            analysis_order == EXPECTED_ANALYSIS_ORDER,
            {"analysis_order": analysis_order},
        ),
        check(
            "schema requirements cover linkage, labels, wrist sensor, and minimum N",
            set(get_path(blueprint, "schema_requirements", "required_linkage_fields") or []) >= {"sid", "visit_id"}
            and "updrs3" in (get_path(blueprint, "schema_requirements", "required_target_fields") or [])
            and "t1_items_9_14" in (get_path(blueprint, "schema_requirements", "optional_target_fields") or [])
            and get_path(blueprint, "schema_requirements", "required_sensor_modality") == "wrist_accelerometer"
            and get_path(blueprint, "schema_requirements", "minimum_linked_subjects_for_any_scoring") >= 20,
            {"schema_requirements": blueprint.get("schema_requirements")},
        ),
        check(
            "X4 sensor boundary excludes 13-sensor GSP from wrist-only PPMI formula",
            x4_boundary.get("status") == "strongest_in_cohort_near_miss_not_promoted"
            and x4_boundary.get("source_audit")
            == "results/t1_x4_equal_weight_2bag_status_20260516.json"
            and x4_boundary.get("requires_sensor_layout")
            == "WearGait-compatible 13-node anatomical IMU graph"
            and x4_boundary.get("ppmi_zero_shot_default_sensor_scope")
            == "wrist_accelerometer"
            and "excluded from Track A/B for wrist-only PPMI schemas"
            in str(x4_boundary.get("zero_shot_formula_role", ""))
            and "before formula SHA freeze"
            in str(x4_boundary.get("zero_shot_formula_role", ""))
            and x4_boundary.get("external_label_selection_allowed") is False,
            {"sensor_compatibility_boundaries": x4_boundary},
        ),
        check(
            "Track A is WearGait-trained wrist TopoFractal zero-shot",
            track_a.get("name") == "weargait_trained_wrist_topofractal_zeroshot"
            and track_a.get("training_data") == "WearGait-PD only"
            and track_a.get("ppmi_label_role") == "final scoring only"
            and any("TopoFractal PH/MFDFA" in item for item in track_a.get("feature_policy", []))
            and any("persistent homology" in item for item in track_a.get("feature_policy", []))
            and any("multifractal detrended fluctuation" in item for item in track_a.get("feature_policy", []))
            and any(
                "exclude X4 13-sensor V2+V3-GSP branch" in item
                for item in track_a.get("feature_policy", [])
            ),
            {"track_a": track_a},
        ),
        check(
            "Track B is canonical comparator plus wrist branch",
            track_b.get("name") == "weargait_trained_clinical_plus_wrist_zeroshot"
            and any("iter47-style clinical/intake comparator" in item for item in track_b.get("feature_policy", []))
            and any("compatible wrist branch" in item for item in track_b.get("feature_policy", []))
            and track_b.get("ppmi_label_role") == "final scoring only",
            {"track_b": track_b},
        ),
        check(
            "Track C preserves fixed K250 GradientBoostingRegressor branch for T3 only",
            track_c.get("name") == "ppmi_only_subject_grouped_sanity"
            and track_c.get("endpoint_scope") == "T3 only"
            and get_path(track_c, "fixed_branch", "formula_sha256") == K250_FORMULA_SHA
            and get_path(track_c, "fixed_branch", "model") == "sklearn.ensemble.GradientBoostingRegressor"
            and get_path(track_c, "fixed_branch", "K") == 250
            and get_path(track_c, "fixed_branch", "source_blueprint")
            == "results/lockbox_ppmi_replication_blueprint_20260514T151939Z.json"
            and "not WearGait deployment performance" in track_c.get("claim_boundary", ""),
            {"track_c": track_c},
        ),
        check(
            "Track D is blocked until zero-shot evidence and fresh formula preregistration",
            track_d.get("name") == "augmentation_screen_after_zero_shot_only"
            and any("zero-shot evidence exists" in item for item in track_d.get("blocked_until", []))
            and any("fresh formula_sha256 preregistration" in item for item in track_d.get("blocked_until", [])),
            {"track_d": track_d},
        ),
        check(
            "no-search and claim-boundary rules are explicit",
            all(
                rule in no_search
                for rule in [
                    "no scaffold before approved schema probe",
                    "no cache extraction before schema-probe metadata recorded",
                    "no PPMI labels for zero-shot feature selection",
                    "no PH/MFDFA column search on PPMI",
                    "no TopoFractal component-count search on PPMI",
                    "no K-search around K=250",
                    "no cross-branch adaptive stacking before zero-shot results",
                    "no X4 13-sensor V2+V3-GSP transfer on wrist-only PPMI unless approved schema proves comparable multi-node sensors before formula freeze",
                    "no endpoint switching after PPMI outcomes",
                    "no canonical WearGait-PD T1/T3 update from external-only metrics",
                ]
            ),
            {"locked_no_search_rules": no_search},
        ),
        check(
            "manifest and reporting gates are explicit",
            get_path(blueprint, "manifest_requirements", "target_free_feature_manifest_before_scoring") is True
            and manifest_requirements.get("template")
            == "scripts/ppmi_verily_target_free_manifest_template.json"
            and manifest_requirements.get("validator")
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and manifest_requirements.get("validator_audit")
            == "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
            and all(
                field in manifest_fields
                for field in [
                    "script",
                    "git_sha",
                    "command",
                    "created_at_utc",
                    "data_version_or_download_date",
                    "data_sha256_or_file_manifest",
                    "labels_used",
                    "fold_scope",
                    "cohort_statistics_used",
                    "normalization_scope",
                    "leakage_status",
                    "leakage_rationale",
                ]
            )
            and get_path(blueprint, "reporting_gates", "external_label_required") is True
            and get_path(
                blueprint,
                "reporting_gates",
                "aggregate_result_record_preflight_before_reporting",
            )
            is True
            and get_path(blueprint, "reporting_gates", "internal_headline_update_from_external_only_metrics") is False
            and get_path(blueprint, "reporting_gates", "augmentation_delta_min") == 0.025
            and get_path(blueprint, "reporting_gates", "augmentation_frac_positive_min") == 0.95,
            {
                "manifest_requirements": blueprint.get("manifest_requirements"),
                "reporting_gates": blueprint.get("reporting_gates"),
            },
        ),
        check(
            "aggregate result-record preflight is explicit before reporting",
            result_record_requirements.get("aggregate_result_record_after_scoring") is True
            and result_record_requirements.get("template_index")
            == "results/external_zeroshot_result_templates_20260515.md"
            and result_record_requirements.get("template")
            == (
                "results/external_zeroshot_result_templates_20260515/"
                "ppmi_verily_zeroshot_result_record_template.json"
            )
            and result_record_requirements.get("validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and result_record_requirements.get("validator_audit")
            == "results/external_zeroshot_result_templates_audit_20260515.json"
            and "internal_canonical_update_claims"
            in (result_record_requirements.get("excluded_content") or [])
            and zeroshot_result_templates_audit.get("passed") is True
            and zeroshot_result_templates_audit.get("decision")
            == "external_zeroshot_result_templates_ready"
            and zeroshot_result_templates_audit.get("route_count") == 6
            and zeroshot_result_templates_audit.get("hard_failures") == [],
            {
                "result_record_requirements": result_record_requirements,
                "zeroshot_result_templates_audit": {
                    "decision": zeroshot_result_templates_audit.get("decision"),
                    "route_count": zeroshot_result_templates_audit.get("route_count"),
                    "hard_failures": zeroshot_result_templates_audit.get("hard_failures"),
                },
            },
        ),
    ]
    hard_failures = [row["name"] for row in checks if not row["passed"]]
    audit = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_ppmi_verily_zeroshot_blueprint.py",
        "passed": not hard_failures,
        "decision": "ppmi_verily_zeroshot_blueprint_ready"
        if not hard_failures
        else "ppmi_verily_zeroshot_blueprint_failed",
        "blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
        "blueprint_sha256": report.get("blueprint_sha256"),
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_preregistration": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Zero-Shot Blueprint Audit - 2026-05-15",
        "",
        "This audit validates a content-free route blueprint. It is not a model result, schema probe, access approval, or preregistration.",
        "",
        f"- Passed: `{audit['passed']}`",
        f"- Decision: `{audit['decision']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        f"- Blueprint SHA256: `{audit['blueprint_sha256']}`",
        "",
        "## Checks",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for row in checks:
        lines.append(f"| {row['name']} | `{row['passed']}` |")
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"passed": audit["passed"], "hard_failures": hard_failures}, indent=2))
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
