#!/usr/bin/env python3
"""Write content-free external zero-shot result record templates."""

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


RESULTS = ROOT / "results"
DEFAULT_JSON = RESULTS / "external_zeroshot_result_templates_20260515.json"
DEFAULT_MD = RESULTS / "external_zeroshot_result_templates_20260515.md"
DEFAULT_TEMPLATE_DIR = RESULTS / "external_zeroshot_result_templates_20260515"

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


def ppmi_result_contract_acknowledgement() -> dict[str, Any]:
    return {
        "blueprint_record_id": "ppmi_verily_zeroshot_blueprint_20260515",
        "blueprint_sha256": PPMI_BLUEPRINT_SHA256,
        "formula_record_validator_gate": "ppmi_route_specific_formula_contract",
        "formula_record_preflight_must_have_passed": True,
        "route_specific_track_names": dict(PPMI_ROUTE_SPECIFIC_TRACKS),
        "required_locked_formula_components": list(PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS),
        "track_c_required_fixed_branch": {
            "endpoint_scope": "T3 only",
            "model": "sklearn.ensemble.GradientBoostingRegressor",
            "selector": "univariate_corr_top_K",
            "K": 250,
            "formula_sha256": PPMI_K250_FORMULA_SHA256,
        },
        "x4_v3_gsp_compatibility_policy": dict(
            PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        ),
        "path_references_in_completed_result_record": False,
        "aggregate_result_claim_scope": (
            "external transportability or PPMI-internal sanity evidence only"
        ),
    }


def tracks_for(spec: Any) -> list[dict[str, Any]]:
    track_names = (
        PPMI_ROUTE_SPECIFIC_TRACKS
        if spec.route_id == "ppmi_verily"
        else {
            "A": "weargait_trained_sensor_zeroshot",
            "B": "weargait_trained_clinical_plus_sensor_zeroshot",
            "C": f"{spec.route_id}_only_grouped_sanity",
            "D": "augmentation_screen_after_zero_shot_only",
        }
    )
    return [
        {
            "track_id": "A",
            "name": track_names["A"],
            "status": "<FILL_scored_or_not_run>",
            "aggregate_metrics": {
                "n": "<FILL_AGGREGATE_N>",
                "ccc": "<FILL_AGGREGATE_CCC>",
                "mae": "<FILL_AGGREGATE_MAE>",
                "r": "<FILL_OPTIONAL_AGGREGATE_R_OR_NULL>",
            },
            "claim_boundary": (
                "External transportability evidence only; not an internal "
                "WearGait-PD T1/T3 headline update."
            ),
        },
        {
            "track_id": "B",
            "name": track_names["B"],
            "status": "<FILL_scored_or_not_run>",
            "aggregate_metrics": {
                "n": "<FILL_AGGREGATE_N_OR_NULL>",
                "ccc": "<FILL_AGGREGATE_CCC_OR_NULL>",
                "mae": "<FILL_AGGREGATE_MAE_OR_NULL>",
            },
            "claim_boundary": (
                "External comparator evidence only; not an internal WearGait-PD "
                "T1/T3 canonical update."
            ),
        },
        {
            "track_id": "C",
            "name": track_names["C"],
            "status": "<FILL_scored_or_not_run>",
            "aggregate_metrics": {
                "n": "<FILL_AGGREGATE_N_OR_NULL>",
                "ccc": "<FILL_AGGREGATE_CCC_OR_NULL>",
                "mae": "<FILL_AGGREGATE_MAE_OR_NULL>",
            },
            "claim_boundary": (
                "External within-route sanity evidence only; not internal "
                "WearGait deployment performance or an internal canonical update."
            ),
        },
        {
            "track_id": "D",
            "name": track_names["D"],
            "status": "blocked",
            "aggregate_metrics": {},
            "claim_boundary": (
                "Blocked unless a future fresh internal augmentation "
                "preregistration clears promotion gates."
            ),
        },
    ]


def template_for(spec: Any) -> dict[str, Any]:
    payload = {
        "route_id": spec.route_id,
        "result_stage": "post_score_external_zero_shot_result_record",
        "status": "template_complete_outside_git_after_external_zero_shot_scoring",
        "approved_access_recorded": False,
        "schema_probe_metadata_recorded": False,
        "target_free_manifest_preflight_passed": False,
        "formula_sha_record_preflight_passed": False,
        "schema_probe_record_reference": (
            f"<FILL_{spec.route_id.upper()}_RECORDED_SCHEMA_PROBE_METADATA_HASH_OR_ID>"
        ),
        "target_free_manifest_reference": (
            f"<FILL_{spec.route_id.upper()}_VALIDATED_TARGET_FREE_MANIFEST_HASH_OR_ID>"
        ),
        "formula_sha_record_reference": (
            f"<FILL_{spec.route_id.upper()}_VALIDATED_FORMULA_SHA_RECORD_HASH_OR_ID>"
        ),
        "formula_sha256": f"<FILL_{spec.route_id.upper()}_FORMULA_SHA256>",
        "scoring_command": f"<FILL_{spec.route_id.upper()}_ZERO_SHOT_SCORING_COMMAND>",
        "created_at_utc": "<FILL_UTC_TIMESTAMP>",
        "git_sha": "<FILL_GIT_SHA>",
        "tracks": tracks_for(spec),
        "external_only": True,
        "internal_canonical_update_allowed": False,
        "claim_boundary": (
            "Aggregate external zero-shot metrics are transportability or "
            "within-route sanity evidence only, not internal WearGait-PD T1/T3 "
            "headline, canonical, deployment, or ceiling-break updates."
        ),
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "raw_rows_or_samples_included": False,
        "feature_matrix_included": False,
        "target_values_included": False,
        "row_predictions_included": False,
        "model_predictions_included": False,
        "local_paths_included": False,
        "preregistration_written": False,
    }
    if spec.route_id == "ppmi_verily":
        payload["route_specific_formula_contract_acknowledged"] = (
            ppmi_result_contract_acknowledgement()
        )
    return payload


def route_row(spec: Any, template_path: Path) -> dict[str, Any]:
    validator_command = (
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
        "post_score_reporting_workflow_sequence": [
            {
                "step_id": "validate_zeroshot_result_record",
                "command": validator_command,
            },
            {
                "step_id": "audit_external_result_claim_labeling",
                "command": "uv run python audit_external_result_claim_labeling.py",
            },
            {
                "step_id": "audit_prompt_objective_evidence",
                "command": "uv run python audit_prompt_objective_evidence.py",
            },
            {
                "step_id": "verify_current_goal_state",
                "command": "uv run python verify_current_goal_state.py",
            },
        ],
        "template": template_for(spec),
    }


def build_payload(template_dir: Path) -> dict[str, Any]:
    routes = [
        route_row(spec, template_dir / f"{spec.route_id}_zeroshot_result_record_template.json")
        for spec in external_schema_probe_specs()
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": "external_zeroshot_result_templates_ready",
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
            "completed_result_records_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "feature_manifest_artifacts_included": False,
            "preregistration_artifacts_included": False,
            "credentials_or_tokens_included": False,
            "target_values_included": False,
            "row_level_data_included": False,
            "feature_matrix_included": False,
            "row_predictions_included": False,
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
        "# External Zero-Shot Result Record Templates - 2026-05-15",
        "",
        "These are blank, content-free templates for aggregate external zero-shot result reporting. They are not completed result records, schema probes, feature manifests, preregistrations, model runs, or T1/T3 claim updates.",
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
        contract = row["template"].get("route_specific_formula_contract_acknowledged")
        lines.extend(
            [
                f"### {row['name']} (`{row['id']}`)",
                "",
                f"- Template: `{row['template_path']}`",
                f"- Target columns: `{', '.join(row['required_target_columns'])}`",
                f"- Sensor modalities: `{', '.join(row['required_sensor_modalities'])}`",
                f"- Validator: `{row['validator_command']}`",
                "",
                "Post-score reporting workflow sequence:",
                "",
            ]
        )
        for idx, step in enumerate(
            row["post_score_reporting_workflow_sequence"], start=1
        ):
            lines.append(f"{idx}. `{step['step_id']}` - `{step['command']}`")
        lines.append("")
        if contract:
            lines.extend(
                [
                    "Route-specific result contract:",
                    "",
                    f"- Blueprint record ID: `{contract['blueprint_record_id']}`",
                    f"- Blueprint SHA256: `{contract['blueprint_sha256']}`",
                    f"- Formula validator gate: `{contract['formula_record_validator_gate']}`",
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
            "Complete these templates only after route approval, schema metadata, target-free manifest preflight, formula-SHA preflight, and external zero-shot scoring. Keep completed aggregate result records outside git unless a future audit explicitly allows a scrubbed artifact. Do not include protected rows, target values, row predictions, feature matrices, credentials, local paths, or internal canonical update claims. Completed records must also omit path-like values inside otherwise allowed fields: local scratch paths, completed-file extensions, download/file-path strings, and subject/visit identifier value dumps. Validators fail closed on those markers.",
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
