#!/usr/bin/env python3
"""Write a content-free PPMI / Verily zero-shot transport blueprint.

This is a pre-access design artifact. It is not a preregistration, schema
probe, data-access approval, model result, or executable protected-data
scaffold. Its purpose is to freeze the analysis order and no-search boundaries
for the PPMI / Verily route before any approved schema probe can happen.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "ppmi_verily_zeroshot_blueprint_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_zeroshot_blueprint_20260515.md"
K250_BLUEPRINT = RESULTS / "lockbox_ppmi_replication_blueprint_20260514T151939Z.json"
PRORESULTS_AUDIT = RESULTS / "proresults_prompt_to_artifact_audit_20260515.json"
X4_STATUS_AUDIT = RESULTS / "t1_x4_equal_weight_2bag_status_20260516.json"
K250_FORMULA_SHA = "489ca6bbc96520c2ea56cc53ee52b03542bec799f9bd41c34d9c9ef5b61ebee4"


def git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return "unknown"
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else "unknown"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_blueprint() -> dict[str, Any]:
    old_k250 = load_json(K250_BLUEPRINT)
    old_formula = old_k250.get("primary_formula", {})
    proresults = load_json(PRORESULTS_AUDIT)
    prompt_source = proresults.get("prompt_source") or {}
    x4_status = load_json(X4_STATUS_AUDIT)
    x4_result = x4_status.get("real_result") or {}

    return {
        "route_id": "ppmi_verily",
        "title": "PPMI / Verily topology-first external transport blueprint",
        "status": "pre_access_design_blueprint_not_preregistration",
        "scope": (
            "Content-free analysis design for the first eligible PPMI / Verily "
            "work after data-owner approval and schema-probe metadata exist."
        ),
        "current_internal_references": {
            "t1_candidate": {
                "name": "T1 X4 equal-weight 2-bag V2+V3-GSP near-miss",
                "ccc": x4_result.get("ccc"),
                "mae": x4_result.get("mae"),
                "n": 92,
                "delta_vs_iter34": x4_result.get("delta_ccc"),
                "frac_positive_seed_A": x4_result.get("frac_positive_seed_A"),
                "frac_positive_seed_B": x4_result.get("frac_positive_seed_B"),
                "status_audit": "results/t1_x4_equal_weight_2bag_status_20260516.json",
                "status_decision": x4_status.get("decision"),
                "claim_boundary": (
                    "strongest current in-cohort T1 near-miss / external-replication "
                    "candidate only; not promoted, not canonical, and not directly "
                    "eligible for wrist-only PPMI Track A/B zero-shot formula"
                ),
            },
            "t1_reference_baseline": {
                "name": "T1 iter34 hygiene-corrected candidate",
                "ccc": 0.7170,
                "mae": 1.736,
                "n": 92,
                "claim_boundary": "current iter34 comparator for X4; not canonical floor",
            },
            "t3_canonical": {
                "name": "T3 iter47 corrected valid-range canonical",
                "ccc": 0.3784,
                "mae": 7.528,
                "n": 95,
                "claim_boundary": "current internal WearGait-PD T3 canonical",
            },
        },
        "source_prompt_trace": {
            "source_audit": "results/proresults_prompt_to_artifact_audit_20260515.json",
            "prompt_path": prompt_source.get("prompt_path"),
            "prompt_sha256": prompt_source.get("sha256"),
            "prompt_line_count": prompt_source.get("line_count"),
            "prompt_rank": 4,
            "prompt_rank_requirement": "PPMI/Verily topology-first external transport after access approval",
            "best_algorithm_with_data_access": "PPMI/Verily topology-first external transport",
            "required_locked_formula_components": [
                "small fixed TopoFractal PH/MFDFA branch",
                "canonical comparator",
                "separate fixed K=250 sklearn-GB branch for T3 only",
                "no omnibus feature expansion",
                "no cross-branch adaptive stacking before zero-shot results",
            ],
            "source_goal_complete": proresults.get("goal_complete"),
            "source_hard_gaps": proresults.get("hard_gaps"),
            "current_best_failed_t1_attempt": proresults.get(
                "ceiling_break_evidence", {}
            ).get("t1_best_attempt"),
        },
        "sensor_compatibility_boundaries": {
            "x4_v2_v3_gsp_2bag": {
                "status": "strongest_in_cohort_near_miss_not_promoted",
                "source_audit": "results/t1_x4_equal_weight_2bag_status_20260516.json",
                "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
                "ppmi_zero_shot_default_sensor_scope": "wrist_accelerometer",
                "zero_shot_formula_role": (
                    "excluded from Track A/B for wrist-only PPMI schemas; may only "
                    "enter a future formula if the approved read-only schema probe "
                    "proves comparable multi-node anatomical sensors before formula "
                    "SHA freeze"
                ),
                "external_label_selection_allowed": False,
                "claim_boundary": "not an internal headline or canonical update",
            },
        },
        "access_prerequisites": [
            "standard PPMI approval",
            "Verily Raw Device Data Tier-3 approval",
            "metadata-only approval record in .access_approvals",
            "read-only schema probe",
            "completed schema-probe report validator pass",
        ],
        "schema_requirements": {
            "required_linkage_fields": ["sid", "visit_id"],
            "required_target_fields": ["updrs3"],
            "optional_target_fields": ["t1_items_9_14"],
            "optional_clinical_covariates": [
                "hoehn_yahr",
                "disease_duration_or_age",
                "sex",
                "dbs",
                "medication_state_or_dose_timing",
            ],
            "required_sensor_modality": "wrist_accelerometer",
            "required_sensor_metadata": [
                "sampling_rate",
                "axis_frame",
                "accelerometer_units",
                "laterality",
                "visit_or_session_alignment",
                "medication_state_or_dose_timing_if_available",
                "wear_or_compliance_metadata",
            ],
            "minimum_linked_subjects_for_any_scoring": 20,
        },
        "analysis_order": [
            "read_only_schema_probe",
            "schema_probe_report_preflight",
            "schema_probe_metadata_record",
            "target_free_manifest_before_scoring",
            "formula_sha256_after_manifest_before_extraction_or_scoring",
            "zero_shot_external_validation",
            "aggregate_result_record_preflight_after_external_scoring",
            "ppmi_only_sanity_if_zero_shot_fails_or_for_context",
            "fresh_augmentation_preregistration_only_after_zero_shot",
        ],
        "tracks": [
            {
                "track_id": "A",
                "name": "weargait_trained_wrist_topofractal_zeroshot",
                "purpose": "External zero-shot transport of target-free wrist IMU features.",
                "training_data": "WearGait-PD only",
                "ppmi_label_role": "final scoring only",
                "feature_policy": [
                    "canonical compatible wrist feature map when schema permits",
                    "small fixed TopoFractal PH/MFDFA representation",
                    "persistent homology summaries from predeclared wrist windows",
                    "multifractal detrended fluctuation analysis summaries from predeclared wrist windows",
                    "exclude X4 13-sensor V2+V3-GSP branch unless schema proves comparable multi-node anatomical sensors before formula freeze",
                ],
                "claim_boundary": "external-validity evidence only; no internal WearGait-PD headline update",
            },
            {
                "track_id": "B",
                "name": "weargait_trained_clinical_plus_wrist_zeroshot",
                "purpose": "Canonical comparator style zero-shot transport with compatible clinical fields.",
                "training_data": "WearGait-PD only",
                "ppmi_label_role": "final scoring only",
                "feature_policy": [
                    "iter47-style clinical/intake comparator when compatible covariates exist",
                    "compatible wrist branch from Track A",
                    "a priori missing-covariate policy before scoring",
                ],
                "claim_boundary": "external comparator only; not a new internal T3 canonical",
            },
            {
                "track_id": "C",
                "name": "ppmi_only_subject_grouped_sanity",
                "purpose": "Determine whether PPMI contains within-cohort signal if zero-shot fails or for context.",
                "training_data": "PPMI only with subject-level grouping",
                "ppmi_label_role": "within-PPMI training/evaluation only",
                "endpoint_scope": "T3 only",
                "fixed_branch": {
                    "source_blueprint": "results/lockbox_ppmi_replication_blueprint_20260514T151939Z.json",
                    "formula_sha256": old_k250.get("formula_sha256") or K250_FORMULA_SHA,
                    "model": old_formula.get("model") or "sklearn.ensemble.GradientBoostingRegressor",
                    "model_params": old_formula.get(
                        "model_params",
                        {
                            "n_estimators": 300,
                            "max_depth": 4,
                            "min_samples_leaf": 10,
                            "subsample": 0.8,
                            "learning_rate": 0.05,
                            "random_state": "seed_from_seeds_list",
                        },
                    ),
                    "selector": old_formula.get("selector") or "univariate_corr_top_K",
                    "K": old_formula.get("K") or 250,
                    "stage_1": old_formula.get(
                        "stage_1",
                        {
                            "model": "sklearn.linear_model.Ridge",
                            "alpha": 1.0,
                            "covariates": ["hy_stage", "cv_years", "cv_sex", "cv_dbs"],
                        },
                    ),
                    "seeds": old_formula.get("seeds") or [42, 1337, 7],
                },
                "claim_boundary": (
                    "PPMI-internal sanity only; not WearGait deployment performance "
                    "and not an internal headline update"
                ),
            },
            {
                "track_id": "D",
                "name": "augmentation_screen_after_zero_shot_only",
                "purpose": "Only a later, separately registered WearGait/PPMI augmentation screen.",
                "blocked_until": [
                    "zero-shot evidence exists",
                    "schema metadata exists",
                    "fresh formula_sha256 preregistration exists before PPMI labels enter development",
                ],
                "claim_boundary": "cannot update canonical WearGait-PD T1/T3 without promotion gate and null gates",
            },
        ],
        "locked_no_search_rules": [
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
        ],
        "formula_sha_policy": {
            "zero_shot_formula_sha256": (
                "write after approved schema probe, schema metadata recording, and "
                "target-free manifest preflight; validate before extraction or scoring"
            ),
            "ppmi_only_k250_formula_sha256": K250_FORMULA_SHA,
            "augmentation_formula_sha256": "fresh preregistration required after zero-shot evidence",
        },
        "manifest_requirements": {
            "target_free_feature_manifest_before_scoring": True,
            "template": "scripts/ppmi_verily_target_free_manifest_template.json",
            "validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
            "validator_audit": "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json",
            "required_fields": [
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
            ],
            "zero_shot_feature_manifest_labels_used": "False before scoring",
            "zero_shot_fold_scope": "train on WearGait-PD only; PPMI labels held for final scoring",
        },
        "result_record_requirements": {
            "aggregate_result_record_after_scoring": True,
            "template_index": "results/external_zeroshot_result_templates_20260515.md",
            "template": (
                "results/external_zeroshot_result_templates_20260515/"
                "ppmi_verily_zeroshot_result_record_template.json"
            ),
            "validator": "scripts/validate_external_zeroshot_result_record.py",
            "validator_audit": "results/external_zeroshot_result_templates_audit_20260515.json",
            "claim_scope": "external-validity or route-only sanity evidence only",
            "excluded_content": [
                "protected_rows",
                "target_values",
                "row_predictions",
                "feature_matrices",
                "credentials",
                "local_protected_paths",
                "internal_canonical_update_claims",
            ],
        },
        "reporting_gates": {
            "external_label_required": True,
            "aggregate_result_record_preflight_before_reporting": True,
            "internal_headline_update_from_external_only_metrics": False,
            "augmentation_delta_min": 0.025,
            "augmentation_frac_positive_min": 0.95,
            "null_gates_before_headline": [
                "scrambled_labels",
                "sid_shuffle_before_cache_join",
                "test_only_canary",
                "retrieval_library_test_exclusion_where_applicable",
                "transductive_sanity_variant",
            ],
        },
        "blocked_actions_now": [
            "protected data download",
            "schema-probe execution",
            "feature cache extraction",
            "pre-registration using unknown PPMI schema",
            "remote job",
            "model scoring",
        ],
        "content_boundary": {
            "not_a_model_result": True,
            "not_access_approval": True,
            "not_a_schema_probe": True,
            "not_a_preregistration": True,
            "protected_data_included": False,
            "credentials_or_tokens_included": False,
            "goal_complete": False,
        },
    }


def write_markdown(report: dict[str, Any]) -> None:
    blueprint = report["blueprint"]
    lines = [
        "# PPMI / Verily Zero-Shot Blueprint - 2026-05-15",
        "",
        "This is a content-free pre-access design blueprint. It is not a model result, access approval, schema probe, or preregistration.",
        "",
        f"- Route: `{blueprint['route_id']}`",
        f"- Status: `{blueprint['status']}`",
        f"- Blueprint SHA256: `{report['blueprint_sha256']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        "",
        "## Analysis Order",
        "",
    ]
    for step in blueprint["analysis_order"]:
        lines.append(f"- `{step}`")
    lines.extend(["", "## Tracks", ""])
    for track in blueprint["tracks"]:
        lines.append(f"- Track {track['track_id']}: `{track['name']}` - {track['claim_boundary']}")
    trace = blueprint.get("source_prompt_trace", {})
    lines.extend(
        [
            "",
            "## Source Prompt Trace",
            "",
            f"- Source audit: `{trace.get('source_audit')}`",
            f"- Prompt path: `{trace.get('prompt_path')}`",
            f"- Prompt SHA256: `{trace.get('prompt_sha256')}`",
            f"- Prompt rank: `{trace.get('prompt_rank')}` - {trace.get('prompt_rank_requirement')}",
            f"- Source goal complete: `{trace.get('source_goal_complete')}`",
        ]
    )
    lines.extend(["", "## No-Search Rules", ""])
    for rule in blueprint["locked_no_search_rules"]:
        lines.append(f"- {rule}")
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "External-only metrics cannot update the internal WearGait-PD T1/T3 canonical claims. "
            "Any augmentation attempt needs a fresh formula_sha256 preregistration after zero-shot evidence.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    blueprint = build_blueprint()
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/write_ppmi_verily_zeroshot_blueprint.py",
        "git_sha": git_sha(),
        "blueprint_sha256": stable_sha(blueprint),
        "blueprint": blueprint,
        "not_a_model_result": True,
        "not_access_approval": True,
        "not_a_schema_probe": True,
        "not_a_preregistration": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"blueprint_sha256": report["blueprint_sha256"], "goal_complete": False}, indent=2))


if __name__ == "__main__":
    main()
