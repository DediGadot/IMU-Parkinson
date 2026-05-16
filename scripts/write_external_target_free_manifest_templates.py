#!/usr/bin/env python3
"""Write content-free target-free manifest templates for queued routes."""

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
DEFAULT_JSON = RESULTS / "external_target_free_manifest_templates_20260515.json"
DEFAULT_MD = RESULTS / "external_target_free_manifest_templates_20260515.md"
DEFAULT_TEMPLATE_DIR = RESULTS / "external_target_free_manifest_templates_20260515"


def feature_blocks_for(spec: Any) -> list[dict[str, Any]]:
    modalities = spec.required_sensor_modalities or ("wearable_imu",)
    return [
        {
            "name": f"{modality}_topofractal_ph_mfdfa",
            "source_modality": modality,
            "locked_pre_score": True,
            "selection_rule": "predeclared_no_external_label_selection",
            "columns_or_schema_reference": (
                f"<FILL_{spec.route_id.upper()}_{modality.upper()}_SCHEMA_REFERENCE_NO_VALUES>"
            ),
        }
        for modality in modalities
    ]


def template_for(spec: Any) -> dict[str, Any]:
    return {
        "route_id": spec.route_id,
        "manifest_stage": "post_schema_pre_scoring_target_free_feature_manifest",
        "status": "template_complete_outside_git_after_schema_probe_metadata_recorded",
        "schema_probe_metadata_recorded": False,
        "schema_probe_artifact_reference": (
            f"<FILL_{spec.route_id.upper()}_RECORDED_SCHEMA_PROBE_METADATA_HASH_OR_ID>"
        ),
        "script": f"<FILL_{spec.route_id.upper()}_TARGET_FREE_EXTRACTION_SCRIPT>",
        "git_sha": "<FILL_GIT_SHA>",
        "command": f"<FILL_{spec.route_id.upper()}_TARGET_FREE_EXTRACTION_COMMAND>",
        "created_at_utc": "<FILL_UTC_TIMESTAMP>",
        "data_version_or_download_date": f"<FILL_{spec.route_id.upper()}_DATA_VERSION>",
        "data_sha256_or_file_manifest": (
            f"<FILL_{spec.route_id.upper()}_AGGREGATE_DATA_SHA256_OR_FILE_MANIFEST>"
        ),
        "labels_used": False,
        "fold_scope": (
            "target_free_zero_shot_feature_extraction_only_labels_held_for_final_scoring"
        ),
        "cohort_statistics_used": (
            "none_or_target_free_sensor_only_aggregates_no_label_statistics"
        ),
        "normalization_scope": (
            "fixed_from_weargait_or_target_free_unsupervised_before_labels"
        ),
        "leakage_status": "target_free_pre_scoring",
        "leakage_rationale": (
            "External labels are not loaded or used during feature extraction, "
            "feature selection, normalization, outlier filtering, endpoint choice, "
            "or model selection."
        ),
        "feature_blocks": feature_blocks_for(spec),
        "grouping_keys": list(spec.required_grouping_keys),
        "target_columns_reserved_for_final_scoring": list(spec.required_target_columns),
        "target_columns_used_for_feature_selection": [],
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "raw_rows_or_samples_included": False,
        "feature_matrix_included": False,
        "target_values_included": False,
        "model_predictions_included": False,
        "local_paths_included": False,
    }


def route_row(spec: Any, template_path: Path) -> dict[str, Any]:
    validator_command = (
        "uv run python scripts/validate_target_free_manifest.py "
        f"--route-id {spec.route_id} "
        "--manifest <completed_target_free_manifest_path_outside_git>"
    )
    if spec.route_id == "ppmi_verily":
        validator_command = (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        )
    workflow_commands = {
        "validate_target_free_manifest": validator_command,
        "validate_formula_sha_record": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            f"--route-id {spec.route_id} "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "validate_zeroshot_result_record": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            f"--route-id {spec.route_id} "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    }
    workflow_sequence = [
        {"step_id": step_id, "command": workflow_commands[step_id]}
        for step_id in (
            "validate_target_free_manifest",
            "validate_formula_sha_record",
            "validate_zeroshot_result_record",
        )
    ]
    return {
        "id": spec.route_id,
        "name": spec.name,
        "template_path": template_path.relative_to(ROOT).as_posix(),
        "required_grouping_keys": list(spec.required_grouping_keys),
        "required_target_columns": list(spec.required_target_columns),
        "required_sensor_modalities": list(spec.required_sensor_modalities),
        "min_subjects": spec.min_subjects,
        "validator_command": validator_command,
        "post_schema_workflow_sequence": workflow_sequence,
        "blocked_until_manifest_preflight_passes": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
        "template": template_for(spec),
    }


def ppmi_specific_support() -> dict[str, str]:
    return {
        "route_id": "ppmi_verily",
        "existing_ppmi_template": "scripts/ppmi_verily_target_free_manifest_template.json",
        "existing_ppmi_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
        "existing_ppmi_validator_command": (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
        "existing_ppmi_template_audit": (
            "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
        ),
    }


def build_payload(template_dir: Path) -> dict[str, Any]:
    routes = [
        route_row(spec, template_dir / f"{spec.route_id}_target_free_manifest_template.json")
        for spec in external_schema_probe_specs()
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": "external_target_free_manifest_templates_ready",
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
        "ppmi_specific_support": ppmi_specific_support(),
        "content_boundary": {
            "completed_manifest_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "feature_manifest_artifacts_included": False,
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
        "# External Target-Free Manifest Templates - 2026-05-15",
        "",
        "These are blank, content-free templates for post-schema, pre-scoring feature-manifest preflight. They are not completed manifests, schema probes, protected-data artifacts, preregistrations, model runs, or T1/T3 claim updates.",
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
        lines.extend(
            [
                f"### {row['name']} (`{row['id']}`)",
                "",
                f"- Template: `{row['template_path']}`",
                f"- Grouping keys: `{', '.join(row['required_grouping_keys'])}`",
                f"- Reserved target columns: `{', '.join(row['required_target_columns'])}`",
                f"- Sensor modalities: `{', '.join(row['required_sensor_modalities'])}`",
                f"- Validator: `{row['validator_command']}`",
                "",
                "Post-schema workflow sequence:",
                "",
                *(
                    f"{idx}. `{step['step_id']}` - `{step['command']}`"
                    for idx, step in enumerate(
                        row["post_schema_workflow_sequence"],
                        start=1,
                    )
                ),
                "",
            ]
        )
    support = payload["ppmi_specific_support"]
    lines.extend(
        [
            "## PPMI/Verily Support",
            "",
            f"- Existing route-specific template: `{support['existing_ppmi_template']}`",
            f"- Existing route-specific validator: `{support['existing_ppmi_validator']}`",
            f"- Existing route-specific validator command: `{support['existing_ppmi_validator_command']}`",
            f"- Existing route-specific audit: `{support['existing_ppmi_template_audit']}`",
            "",
            "## Boundary",
            "",
            "Complete these templates only after route approval and schema-probe metadata recording. Keep completed manifests outside git unless a future audit explicitly allows a scrubbed artifact. Do not include protected rows, target values, feature matrices, credentials, local paths, model predictions, or approval records. Completed records must also omit path-like values inside otherwise allowed fields: local scratch paths, completed-file extensions, download/file-path strings, and subject/visit identifier value dumps. Validators fail closed on those markers.",
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
