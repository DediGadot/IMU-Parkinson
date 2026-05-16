#!/usr/bin/env python3
"""Write content-free formula-SHA record templates for queued external routes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pd_imu.datasets import external_schema_probe_specs  # noqa: E402
from pd_imu.experiments import SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS  # noqa: E402


RESULTS = ROOT / "results"
DEFAULT_JSON = RESULTS / "external_formula_sha_templates_20260515.json"
DEFAULT_MD = RESULTS / "external_formula_sha_templates_20260515.md"
DEFAULT_TEMPLATE_DIR = RESULTS / "external_formula_sha_templates_20260515"

ANALYSIS_ORDER = [
    "schema_probe_metadata_record",
    "target_free_manifest_preflight",
    "formula_sha256_after_manifest_before_extraction_or_scoring",
    "zero_shot_external_validation",
]
LOCKED_NO_SEARCH_RULES = [
    "no external labels for zero-shot feature selection",
    "no PH/MFDFA column search on the external route",
    "no TopoFractal component-count search on the external route",
    "no K-search on the external route",
    "no endpoint switching after external outcomes",
    "no canonical WearGait-PD T1/T3 update from external-only metrics",
]
PPMI_K250_FORMULA_SHA256 = (
    "489ca6bbc96520c2ea56cc53ee52b03542bec799f9bd41c34d9c9ef5b61ebee4"
)
PPMI_BLUEPRINT_SHA256 = (
    "4540fbc00a3bb92b6bedca34e954bb0e8ae00cbee30ee6f9651c56229591e13f"
)
PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS = [
    "small fixed TopoFractal PH/MFDFA branch",
    "canonical comparator",
    "separate fixed K=250 sklearn-GB branch for T3 only",
    "no omnibus feature expansion",
    "no cross-branch adaptive stacking before zero-shot results",
]
PPMI_ROUTE_SPECIFIC_TRACKS = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}


def ppmi_track_specs(spec: Any) -> list[dict[str, Any]]:
    return [
        {
            "track_id": "A",
            "name": PPMI_ROUTE_SPECIFIC_TRACKS["A"],
            "training_data": "WearGait-PD only",
            "external_label_role": "final scoring only",
            "feature_source": "target-free compatible wrist branch",
            "branch_contract": {
                "branch_type": "small_fixed_topofractal",
                "sensor_modality": "wrist_accelerometer",
                "component_count_policy": "fixed_no_search",
                "components": [
                    "canonical_compatible_wrist_features",
                    "persistent_homology_summaries",
                    "multifractal_detrended_fluctuation_analysis_summaries",
                ],
                "ph_mfdfa_column_search_on_external_route": False,
                "topofractal_component_count_search_on_external_route": False,
                "x4_v3_gsp_compatibility_policy": dict(
                    PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
                ),
            },
        },
        {
            "track_id": "B",
            "name": PPMI_ROUTE_SPECIFIC_TRACKS["B"],
            "training_data": "WearGait-PD only",
            "external_label_role": "final scoring only",
            "feature_source": "Track A plus schema-proved compatible clinical/intake fields",
            "branch_contract": {
                "branch_type": "canonical_comparator",
                "comparator_family": "iter47_style_clinical_intake_plus_sensor",
                "clinical_covariate_policy": "schema_proved_fields_only_before_scoring",
                "missing_covariate_policy": "declared_before_scoring",
            },
        },
        {
            "track_id": "C",
            "name": PPMI_ROUTE_SPECIFIC_TRACKS["C"],
            "training_data": spec.name,
            "external_label_role": "within-route grouped training/evaluation only",
            "grouping_policy": "subject_or_visit_grouped_by_schema_keys",
            "endpoint_scope": "T3 only",
            "fixed_branch": {
                "model": "sklearn.ensemble.GradientBoostingRegressor",
                "model_params": {
                    "learning_rate": 0.05,
                    "max_depth": 4,
                    "min_samples_leaf": 10,
                    "n_estimators": 300,
                    "random_state": "seed_from_seeds_list",
                    "subsample": 0.8,
                },
                "selector": "univariate_corr_top_K",
                "K": 250,
                "formula_sha256": PPMI_K250_FORMULA_SHA256,
                "seeds": [42, 1337, 7],
                "stage_1": {
                    "model": "sklearn.linear_model.Ridge",
                    "alpha": 1.0,
                    "covariates": ["hy_stage", "cv_years", "cv_sex", "cv_dbs"],
                },
            },
        },
        {
            "track_id": "D",
            "name": PPMI_ROUTE_SPECIFIC_TRACKS["D"],
            "training_data": "blocked until zero-shot evidence and fresh preregistration",
            "external_label_role": "blocked for this formula record",
            "blocked_until": [
                "zero-shot evidence exists",
                "schema metadata exists",
                "fresh formula_sha256 preregistration exists before PPMI labels enter development",
            ],
        },
    ]


def generic_track_specs(spec: Any) -> list[dict[str, Any]]:
    return [
        {
            "track_id": "A",
            "name": "weargait_trained_sensor_zeroshot",
            "training_data": "WearGait-PD only",
            "external_label_role": "final scoring only",
            "feature_source": "target-free manifest compatible sensor branch",
        },
        {
            "track_id": "B",
            "name": "weargait_trained_clinical_plus_sensor_zeroshot",
            "training_data": "WearGait-PD only",
            "external_label_role": "final scoring only",
            "feature_source": "Track A plus schema-proved compatible clinical/intake fields",
        },
        {
            "track_id": "C",
            "name": f"{spec.route_id}_only_grouped_sanity",
            "training_data": spec.name,
            "external_label_role": "within-route grouped training/evaluation only",
            "grouping_policy": "subject_or_visit_grouped_by_schema_keys",
        },
        {
            "track_id": "D",
            "name": "augmentation_screen_after_zero_shot_only",
            "training_data": "blocked until zero-shot evidence and fresh preregistration",
            "external_label_role": "blocked for this formula record",
        },
    ]


def route_specific_formula_contract(spec: Any) -> dict[str, Any] | None:
    if spec.route_id != "ppmi_verily":
        return None
    return {
        "blueprint_record_id": "ppmi_verily_zeroshot_blueprint_20260515",
        "blueprint_audit_record_id": "ppmi_verily_zeroshot_blueprint_audit_20260515",
        "blueprint_sha256": PPMI_BLUEPRINT_SHA256,
        "must_use_for_exact_track_definitions": True,
        "required_locked_formula_components": list(PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS),
        "route_specific_track_names": dict(PPMI_ROUTE_SPECIFIC_TRACKS),
        "path_references_in_completed_formula_record": False,
        "track_a_required_branch_type": "small_fixed_topofractal",
        "track_b_required_branch_type": "canonical_comparator",
        "track_c_required_fixed_branch": {
            "endpoint_scope": "T3 only",
            "model": "sklearn.ensemble.GradientBoostingRegressor",
            "selector": "univariate_corr_top_K",
            "K": 250,
            "formula_sha256": PPMI_K250_FORMULA_SHA256,
        },
        "global_branch_policy": {
            "omnibus_feature_expansion": False,
            "cross_branch_adaptive_stacking_before_zero_shot_results": False,
            "external_label_branch_selection": False,
        },
        "x4_v3_gsp_compatibility_policy": dict(
            PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        ),
    }


def formula_json_for(spec: Any) -> dict[str, Any]:
    tracks = (
        ppmi_track_specs(spec)
        if spec.route_id == "ppmi_verily"
        else generic_track_specs(spec)
    )
    payload = {
        "route_id": spec.route_id,
        "formula_scope": "zero_shot_external_validation",
        "required_grouping_keys": list(spec.required_grouping_keys),
        "required_target_columns": list(spec.required_target_columns),
        "required_sensor_modalities": list(spec.required_sensor_modalities),
        "minimum_linked_subjects": spec.min_subjects,
        "tracks": tracks,
        "transform_policy": {
            "external_label_feature_selection": False,
            "target_free_manifest_required": True,
            "schema_compatible_fields_only": True,
            "formula_changes_after_scoring": False,
            "omnibus_feature_expansion": False,
            "cross_branch_adaptive_stacking_before_zero_shot_results": False,
        },
    }
    route_contract = route_specific_formula_contract(spec)
    if route_contract is not None:
        payload["route_specific_blueprint_contract"] = route_contract
    return payload


def template_for(spec: Any) -> dict[str, Any]:
    return {
        "route_id": spec.route_id,
        "record_stage": "post_schema_pre_extraction_or_scoring_formula_sha",
        "status": "template_complete_outside_git_after_schema_and_manifest_preflight",
        "schema_probe_metadata_recorded": False,
        "target_free_manifest_preflight_passed": False,
        "schema_probe_record_reference": (
            f"<FILL_{spec.route_id.upper()}_RECORDED_SCHEMA_PROBE_METADATA_HASH_OR_ID>"
        ),
        "target_free_manifest_reference": (
            f"<FILL_{spec.route_id.upper()}_VALIDATED_TARGET_FREE_MANIFEST_HASH_OR_ID>"
        ),
        "formula_scope": "zero_shot_external_validation",
        "formula_name": f"{spec.route_id}_zero_shot_external_formula",
        "formula_sha256": f"<FILL_{spec.route_id.upper()}_FORMULA_SHA256>",
        "formula_json": formula_json_for(spec),
        "created_at_utc": "<FILL_UTC_TIMESTAMP>",
        "git_sha": "<FILL_GIT_SHA>",
        "analysis_order_acknowledged": list(ANALYSIS_ORDER),
        "locked_no_search_rules_acknowledged": list(LOCKED_NO_SEARCH_RULES),
        "external_labels_used_to_design_formula": False,
        "target_values_used_to_design_formula": False,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "raw_rows_or_samples_included": False,
        "feature_matrix_included": False,
        "target_values_included": False,
        "model_predictions_included": False,
        "local_paths_included": False,
        "preregistration_written": False,
        "claim_boundary": (
            "External-only metrics are transportability or within-route sanity "
            "evidence, not internal WearGait-PD T1/T3 headline updates."
        ),
    }


def route_row(spec: Any, template_path: Path) -> dict[str, Any]:
    validator_command = (
        "uv run python scripts/validate_external_formula_sha_record.py "
        f"--route-id {spec.route_id} "
        "--record <completed_formula_sha_record_path_outside_git>"
    )
    result_validator_command = (
        "uv run python scripts/validate_external_zeroshot_result_record.py "
        f"--route-id {spec.route_id} "
        "--record <completed_external_zeroshot_result_record_path_outside_git>"
    )
    return {
        "id": spec.route_id,
        "name": spec.name,
        "template_path": template_path.relative_to(ROOT).as_posix(),
        "required_grouping_keys": list(spec.required_grouping_keys),
        "required_target_columns": list(spec.required_target_columns),
        "required_sensor_modalities": list(spec.required_sensor_modalities),
        "min_subjects": spec.min_subjects,
        "validator_command": validator_command,
        "post_formula_workflow_sequence": [
            {
                "step_id": "validate_formula_sha_record",
                "command": validator_command,
            },
            {
                "step_id": "validate_zeroshot_result_record",
                "command": result_validator_command,
            },
        ],
        "blocked_until_formula_preflight_passes": list(
            SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
        ),
        "template": template_for(spec),
    }


def build_payload(template_dir: Path) -> dict[str, Any]:
    routes = [
        route_row(spec, template_dir / f"{spec.route_id}_formula_sha_record_template.json")
        for spec in external_schema_probe_specs()
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": "external_formula_sha_templates_ready",
        "source_schema_contract": "pd_imu.datasets.external_schema_probe_specs",
        "template_dir": template_dir.relative_to(ROOT).as_posix(),
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_preregistration": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "route_count": len(routes),
        "routes": routes,
        "content_boundary": {
            "completed_formula_records_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "feature_manifest_artifacts_included": False,
            "preregistration_artifacts_included": False,
            "credentials_or_tokens_included": False,
            "target_values_included": False,
            "row_level_data_included": False,
            "feature_matrix_included": False,
            "model_outputs_included": False,
            "local_paths_included": False,
            "path_like_values_allowed": False,
            "completed_file_references_in_values_allowed": False,
            "subject_visit_identifier_value_dumps_allowed": False,
        },
    }


def write_templates(payload: dict[str, Any]) -> None:
    for row in payload["routes"]:
        path = ROOT / row["template_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(row["template"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# External Formula-SHA Record Templates - 2026-05-15",
        "",
        "These are blank, content-free templates for the post-schema, post-manifest formula-SHA preflight required before external extraction or scoring. They are not completed formula records, schema probes, feature manifests, preregistrations, model runs, or T1/T3 claim updates.",
        "",
        f"- Decision: `{payload['decision']}`",
        f"- Goal complete: `{payload['goal_complete']}`",
        f"- Template directory: `{payload['template_dir']}`",
        f"- Route count: `{payload['route_count']}`",
        "",
        "## Routes",
        "",
    ]
    for row in payload["routes"]:
        formula = row["template"]["formula_json"]
        lines.extend(
            [
                f"### {row['name']} (`{row['id']}`)",
                "",
                f"- Template: `{row['template_path']}`",
                f"- Grouping keys: `{', '.join(row['required_grouping_keys'])}`",
                f"- Target columns: `{', '.join(row['required_target_columns'])}`",
                f"- Sensor modalities: `{', '.join(row['required_sensor_modalities'])}`",
                f"- Validator: `{row['validator_command']}`",
                "",
                "Post-formula workflow sequence:",
                "",
                *(
                    f"{idx}. `{step['step_id']}` - `{step['command']}`"
                    for idx, step in enumerate(
                        row["post_formula_workflow_sequence"],
                        start=1,
                    )
                ),
                "",
            ]
        )
        contract = formula.get("route_specific_blueprint_contract")
        if contract:
            lines.extend(
                [
                    "Route-specific formula contract:",
                    "",
                    f"- Blueprint record ID: `{contract['blueprint_record_id']}`",
                    f"- Blueprint SHA256: `{contract['blueprint_sha256']}`",
                    f"- Must use exact route track definitions: `{contract['must_use_for_exact_track_definitions']}`",
                    "- Required locked formula components:",
                ]
            )
            for component in contract["required_locked_formula_components"]:
                lines.append(f"  - {component}")
            lines.append("- Route-specific track names:")
            for track_id, name in contract["route_specific_track_names"].items():
                lines.append(f"  - Track {track_id}: `{name}`")
            lines.extend(
                [
                    f"- Fixed T3 branch model: `{contract['track_c_required_fixed_branch']['model']}`",
                    f"- Fixed T3 branch selector/K: `{contract['track_c_required_fixed_branch']['selector']}` / `{contract['track_c_required_fixed_branch']['K']}`",
                    "",
                ]
            )
    lines.extend(
        [
            "## Boundary",
            "",
            "Complete these templates only after route approval, schema-probe metadata recording, and target-free manifest preflight. Keep completed formula records outside git unless a future audit explicitly allows a scrubbed artifact. Do not include protected rows, target values, feature matrices, credentials, local paths, model predictions, approval records, or preregistrations. Completed records must also omit path-like values inside otherwise allowed fields: local scratch paths, completed-file extensions, download/file-path strings, and subject/visit identifier value dumps. Validators fail closed on those markers.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    template_dir = Path(args.template_dir)
    if not json_out.is_absolute():
        json_out = ROOT / json_out
    if not md_out.is_absolute():
        md_out = ROOT / md_out
    if not template_dir.is_absolute():
        template_dir = ROOT / template_dir
    payload = build_payload(template_dir)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    write_templates(payload)
    json_out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(payload, md_out)
    print(
        json.dumps(
            {
                "json": json_out.relative_to(ROOT).as_posix(),
                "markdown": md_out.relative_to(ROOT).as_posix(),
                "template_dir": template_dir.relative_to(ROOT).as_posix(),
                "route_count": payload["route_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
