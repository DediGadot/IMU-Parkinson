#!/usr/bin/env python3
"""Write a content-free zero-shot blueprint handoff for queued external routes."""

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
DEFAULT_JSON = RESULTS / "external_zeroshot_blueprint_handoff_20260515.json"
DEFAULT_MD = RESULTS / "external_zeroshot_blueprint_handoff_20260515.md"

ANALYSIS_ORDER = [
    "approval_metadata_record",
    "read_only_schema_probe",
    "schema_probe_report_preflight",
    "schema_probe_metadata_record",
    "target_free_manifest_preflight",
    "formula_sha256_after_manifest_before_extraction_or_scoring",
    "zero_shot_external_validation",
    "aggregate_result_record_preflight_after_external_scoring",
    "route_only_grouped_sanity_if_zero_shot_fails_or_for_context",
    "fresh_augmentation_preregistration_only_after_zero_shot",
]
LOCKED_NO_SEARCH_RULES = [
    "no scaffold before approved schema probe",
    "no cache extraction before schema-probe metadata recorded",
    "no external labels for zero-shot feature selection",
    "no PH/MFDFA column search on the external route",
    "no TopoFractal component-count search on the external route",
    "no K-search on the external route",
    "no adaptive stacking before zero-shot results",
    "no endpoint switching after external outcomes",
    "no canonical WearGait-PD T1/T3 update from external-only metrics",
]
TRACK_IDS = ("A", "B", "C", "D")
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


def schema_report_validator_for(route_id: str) -> str:
    if route_id == "ppmi_verily":
        return "scripts/validate_ppmi_verily_schema_probe_report.py"
    return "scripts/validate_schema_probe_report.py"


def target_free_manifest_validator_for(route_id: str) -> str:
    if route_id == "ppmi_verily":
        return "scripts/validate_ppmi_verily_target_free_manifest.py"
    return "scripts/validate_target_free_manifest.py"


def command_templates_for(route_id: str) -> dict[str, str]:
    commands = {
        "validate_schema_probe_report": (
            "uv run python scripts/validate_schema_probe_report.py "
            f"--route-id {route_id} "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
        "validate_target_free_manifest": (
            "uv run python scripts/validate_target_free_manifest.py "
            f"--route-id {route_id} "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
        "validate_formula_sha_record": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            f"--route-id {route_id} "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "validate_zeroshot_result_record": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            f"--route-id {route_id} "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    }
    if route_id == "ppmi_verily":
        commands.update(
            {
                "validate_schema_probe_report": (
                    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                    "--report <completed_schema_probe_report_path_outside_git>"
                ),
                "validate_target_free_manifest": (
                    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                    "--manifest <completed_target_free_manifest_path_outside_git>"
                ),
            }
        )
    return commands


def endpoint_scope_for(spec: Any) -> str:
    targets = set(spec.required_target_columns)
    if "updrs3" in targets:
        return (
            "T3 primary via updrs3; T1 only after a future schema record proves full "
            "items 9-14 are available and a fresh formula preregistration exists"
        )
    return "schema-proved endpoint only; no endpoint switching after outcomes"


def route_tracks(spec: Any) -> list[dict[str, Any]]:
    sensor_label = "+".join(spec.required_sensor_modalities) or "wearable_imu"
    grouping_label = "+".join(spec.required_grouping_keys)
    return [
        {
            "track_id": "A",
            "name": "weargait_trained_sensor_zeroshot",
            "purpose": "External zero-shot transport of the fixed compatible IMU branch.",
            "training_data": "WearGait-PD only",
            "external_label_role": "final scoring only",
            "sensor_modalities": list(spec.required_sensor_modalities),
            "feature_policy": [
                f"fixed compatible {sensor_label} feature map after schema proves compatibility",
                "target-free extraction only before final scoring",
                "no external-label feature selection or model selection",
            ],
            "claim_boundary": (
                "external-validity or transportability evidence only; no internal "
                "WearGait-PD headline update"
            ),
        },
        {
            "track_id": "B",
            "name": "weargait_trained_clinical_plus_sensor_zeroshot",
            "purpose": "Iter47-style clinical/intake comparator when compatible fields exist.",
            "training_data": "WearGait-PD only",
            "external_label_role": "final scoring only",
            "sensor_modalities": list(spec.required_sensor_modalities),
            "feature_policy": [
                "fixed clinical/intake covariate map only if schema proves compatibility",
                "same sensor branch as Track A",
                "a priori missing-covariate policy before scoring",
            ],
            "claim_boundary": "external comparator only; not a new internal canonical",
        },
        {
            "track_id": "C",
            "name": f"{spec.route_id}_only_grouped_sanity",
            "purpose": "Check whether the external route contains within-cohort signal.",
            "training_data": f"{spec.name} only",
            "external_label_role": "within-route grouped training/evaluation only",
            "grouping_policy": f"group by {grouping_label}; no subject leakage across folds",
            "endpoint_scope": endpoint_scope_for(spec),
            "claim_boundary": (
                "route-internal sanity only; not WearGait deployment performance and "
                "not an internal headline update"
            ),
        },
        {
            "track_id": "D",
            "name": "augmentation_screen_after_zero_shot_only",
            "purpose": "Only a later, separately registered WearGait/external augmentation screen.",
            "blocked_until": [
                "zero-shot evidence exists",
                "schema metadata exists",
                "target-free manifest preflight passes",
                "fresh formula_sha256 preregistration exists before external labels enter development",
            ],
            "claim_boundary": (
                "cannot update canonical WearGait-PD T1/T3 without promotion gate, "
                "null gates, and a full-cohort internal result"
            ),
        },
    ]


def route_row(spec: Any) -> dict[str, Any]:
    template = (
        "results/external_target_free_manifest_templates_20260515/"
        f"{spec.route_id}_target_free_manifest_template.json"
    )
    commands = command_templates_for(spec.route_id)
    row = {
        "id": spec.route_id,
        "name": spec.name,
        "protected_access_required": spec.protected_access_required,
        "required_grouping_keys": list(spec.required_grouping_keys),
        "required_target_columns": list(spec.required_target_columns),
        "required_sensor_modalities": list(spec.required_sensor_modalities),
        "min_subjects": spec.min_subjects,
        "analysis_order": list(ANALYSIS_ORDER),
        "prerequisites": [
            "non-protected approval metadata record",
            "read-only schema probe",
            "schema-probe report validator pass",
            "schema-probe metadata record",
            "target-free manifest validator pass",
            "formula_sha256 recorded after schema and before extraction or scoring",
            "aggregate external result record validator pass before reporting",
        ],
        "supporting_artifacts": {
            "schema_probe_handoff": "results/external_schema_probe_handoff_20260515.md",
            "schema_report_validator": schema_report_validator_for(spec.route_id),
            "schema_report_validator_command": commands["validate_schema_probe_report"],
            "target_free_manifest_template": template,
            "target_free_manifest_validator": target_free_manifest_validator_for(spec.route_id),
            "target_free_manifest_validator_command": commands[
                "validate_target_free_manifest"
            ],
            "formula_sha_template": (
                "results/external_formula_sha_templates_20260515/"
                f"{spec.route_id}_formula_sha_record_template.json"
            ),
            "formula_sha_validator": "scripts/validate_external_formula_sha_record.py",
            "formula_sha_validator_command": commands["validate_formula_sha_record"],
            "zeroshot_result_template": (
                "results/external_zeroshot_result_templates_20260515/"
                f"{spec.route_id}_zeroshot_result_record_template.json"
            ),
            "zeroshot_result_validator": "scripts/validate_external_zeroshot_result_record.py",
            "zeroshot_result_validator_command": commands[
                "validate_zeroshot_result_record"
            ],
        },
        "post_schema_command_templates": commands,
        "tracks": route_tracks(spec),
        "locked_no_search_rules": list(LOCKED_NO_SEARCH_RULES),
        "blocked_until_schema_and_manifest_gates_pass": list(
            SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
        ),
        "claim_boundary": (
            "External rows may support transportability or within-route sanity claims "
            "only; they must not be framed as internal WearGait-PD T1/T3 headline, "
            "canonical, deployment, or ceiling-break updates."
        ),
    }
    if spec.route_id == "ppmi_verily":
        row["route_specific_blueprint"] = {
            "blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
            "blueprint_markdown": "results/ppmi_verily_zeroshot_blueprint_20260515.md",
            "blueprint_audit": "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
            "must_use_for_exact_track_definitions": True,
            "required_locked_formula_components": list(PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS),
            "route_specific_track_names": dict(PPMI_ROUTE_SPECIFIC_TRACKS),
            "formula_sha_policy": (
                "write formula_sha256 after approved schema probe, schema metadata recording, and "
                "target-free manifest preflight; validate before extraction or scoring"
            ),
        }
    return row


def build_payload() -> dict[str, Any]:
    routes = [route_row(spec) for spec in external_schema_probe_specs()]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": "external_zeroshot_blueprint_handoff_ready",
        "source_schema_contract": "pd_imu.datasets.external_schema_probe_specs",
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_preregistration": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "route_count": len(routes),
        "routes": routes,
        "analysis_order": list(ANALYSIS_ORDER),
        "locked_no_search_rules": list(LOCKED_NO_SEARCH_RULES),
        "ppmi_specific_support": {
            "route_id": "ppmi_verily",
            "blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
            "blueprint_audit": "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
        },
        "content_boundary": {
            "completed_packets_included": False,
            "completed_emails_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "feature_manifest_artifacts_included": False,
            "preregistration_artifacts_included": False,
            "record_paths_reported": False,
            "credentials_or_tokens_included": False,
            "target_values_included": False,
            "row_level_data_included": False,
            "feature_matrix_included": False,
            "model_outputs_included": False,
        },
    }


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# External Zero-Shot Blueprint Handoff - 2026-05-15",
        "",
        "This is a content-free zero-shot analysis-order handoff for queued gated external routes. It is not an access approval, schema probe, completed feature manifest, preregistration, model run, protected-data artifact, or T1/T3 claim update.",
        "",
        f"- Decision: `{payload['decision']}`",
        f"- Goal complete: `{payload['goal_complete']}`",
        f"- Route count: `{payload['route_count']}`",
        "",
        "## Shared Analysis Order",
        "",
    ]
    for step in payload["analysis_order"]:
        lines.append(f"- `{step}`")
    lines.extend(["", "## Routes", ""])
    for row in payload["routes"]:
        artifacts = row["supporting_artifacts"]
        lines.extend(
            [
                f"### {row['name']} (`{row['id']}`)",
                "",
                f"- Grouping keys: `{', '.join(row['required_grouping_keys'])}`",
                f"- Target columns: `{', '.join(row['required_target_columns'])}`",
                f"- Sensor modalities: `{', '.join(row['required_sensor_modalities'])}`",
                f"- Minimum linked subjects: `{row['min_subjects']}`",
                f"- Schema handoff: `{artifacts['schema_probe_handoff']}`",
                f"- Schema validator: `{artifacts['schema_report_validator']}`",
                f"- Schema validator command: `{artifacts['schema_report_validator_command']}`",
                f"- Target-free manifest template: `{artifacts['target_free_manifest_template']}`",
                f"- Target-free manifest validator: `{artifacts['target_free_manifest_validator']}`",
                f"- Target-free manifest validator command: `{artifacts['target_free_manifest_validator_command']}`",
                f"- Formula-SHA template: `{artifacts['formula_sha_template']}`",
                f"- Formula-SHA validator: `{artifacts['formula_sha_validator']}`",
                f"- Formula-SHA validator command: `{artifacts['formula_sha_validator_command']}`",
                f"- Aggregate result template: `{artifacts['zeroshot_result_template']}`",
                f"- Aggregate result validator: `{artifacts['zeroshot_result_validator']}`",
                f"- Aggregate result validator command: `{artifacts['zeroshot_result_validator_command']}`",
                "",
                "Tracks:",
                "",
            ]
        )
        for track in row["tracks"]:
            lines.append(
                f"- Track {track['track_id']}: `{track['name']}` - {track['claim_boundary']}"
            )
        if row.get("route_specific_blueprint"):
            blueprint = row["route_specific_blueprint"]
            lines.extend(
                [
                    "",
                    "Route-specific locked blueprint:",
                    "",
                    f"- Blueprint: `{blueprint['blueprint']}`",
                    f"- Blueprint audit: `{blueprint['blueprint_audit']}`",
                    f"- Must use for exact track definitions: `{blueprint['must_use_for_exact_track_definitions']}`",
                    "- Required locked formula components:",
                ]
            )
            for component in blueprint["required_locked_formula_components"]:
                lines.append(f"  - {component}")
            lines.append("- Route-specific track names:")
            for track_id, name in blueprint["route_specific_track_names"].items():
                lines.append(f"  - Track {track_id}: `{name}`")
        lines.extend(["", "Locked no-search rules:", ""])
        for rule in row["locked_no_search_rules"]:
            lines.append(f"- {rule}")
        lines.append("")
    support = payload["ppmi_specific_support"]
    lines.extend(
        [
            "## PPMI/Verily Support",
            "",
            f"- Route-specific blueprint: `{support['blueprint']}`",
            f"- Route-specific blueprint audit: `{support['blueprint_audit']}`",
            "",
            "## Boundary",
            "",
            "Do not add completed packets, approval evidence, credentials, local data paths, protected rows, target values, schema-probe outputs, completed manifests, formula records, row-level predictions, downloads, caches, preregistrations, model runs, or canonical claim updates to this repo from this handoff.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    if not json_out.is_absolute():
        json_out = ROOT / json_out
    if not md_out.is_absolute():
        md_out = ROOT / md_out
    payload = build_payload()
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
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
                "route_count": payload["route_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
