#!/usr/bin/env python3
"""Write a content-free schema-probe handoff for queued external routes."""

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
from pd_imu.experiments import (  # noqa: E402
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
)


RESULTS = ROOT / "results"
TRACKER_JSON = RESULTS / "access_submission_tracker_20260509.json"
DEFAULT_JSON = RESULTS / "external_schema_probe_handoff_20260515.json"
DEFAULT_MD = RESULTS / "external_schema_probe_handoff_20260515.md"


def load_tracker(path: Path = TRACKER_JSON) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("access submission tracker has not been generated") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("access submission tracker JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("access submission tracker JSON must contain an object")
    return payload


def command_templates(route_id: str) -> dict[str, str]:
    commands = {
        "validate_schema_probe_report": (
            "uv run python scripts/validate_schema_probe_report.py "
            f"--route-id {route_id} "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
        "record_schema_probe_metadata": (
            "uv run python scripts/record_schema_probe_report.py "
            f"--route-id {route_id} "
            "--sections-present <csv> "
            "--grouping-keys-found <csv> "
            "--target-columns-found <csv> "
            "--sensor-modalities-found <csv> "
            "--valid-subject-count <n>"
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


def post_approval_workflow_sequence(
    route_id: str,
    commands: dict[str, str],
) -> list[dict[str, str]]:
    step_ids = [
        "validate_schema_probe_report",
        "record_schema_probe_metadata",
        "validate_target_free_manifest",
        "validate_formula_sha_record",
        "validate_zeroshot_result_record",
    ]
    return [
        {"step_id": step_id, "command": commands[step_id]}
        for step_id in step_ids
        if commands.get(step_id)
    ]


def ppmi_specific_support(route_id: str) -> dict[str, str]:
    if route_id != "ppmi_verily":
        return {}
    commands = command_templates(route_id)
    return {
        "schema_probe_checklist": "scripts/ppmi_verily_schema_probe_checklist.md",
        "schema_probe_report_template": "scripts/ppmi_verily_schema_probe_report_template.md",
        "schema_probe_checklist_audit": (
            "results/ppmi_verily_schema_probe_checklist_audit_20260515.json"
        ),
        "schema_probe_report_template_audit": (
            "results/ppmi_verily_schema_probe_report_template_audit_20260515.json"
        ),
        "schema_probe_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
        "schema_probe_validator_command": commands["validate_schema_probe_report"],
        "target_free_manifest_template": "scripts/ppmi_verily_target_free_manifest_template.json",
        "target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
        "target_free_manifest_validator_command": commands["validate_target_free_manifest"],
    }


def route_priority_map(tracker: dict[str, Any]) -> dict[str, int]:
    return {
        str(row.get("id")): int(row.get("priority"))
        for row in tracker.get("routes", [])
        if isinstance(row, dict) and row.get("id") is not None and row.get("priority") is not None
    }


def route_row(spec: Any, *, priority: int | None) -> dict[str, Any]:
    commands = command_templates(spec.route_id)
    return {
        "priority": priority,
        "id": spec.route_id,
        "name": spec.name,
        "protected_access_required": spec.protected_access_required,
        "required_sections": list(spec.required_sections),
        "required_grouping_keys": list(spec.required_grouping_keys),
        "required_target_columns": list(spec.required_target_columns),
        "required_sensor_modalities": list(spec.required_sensor_modalities),
        "min_subjects": spec.min_subjects,
        "post_approval_commands": commands,
        "post_approval_workflow_sequence": post_approval_workflow_sequence(
            spec.route_id,
            commands,
        ),
        "blocked_before_approval": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
        "blocked_until_schema_and_manifest_gates_pass": list(
            SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
        ),
        "ppmi_specific_support": ppmi_specific_support(spec.route_id),
    }


def build_payload(tracker: dict[str, Any]) -> dict[str, Any]:
    priorities = route_priority_map(tracker)
    routes = [
        route_row(spec, priority=priorities.get(spec.route_id))
        for spec in external_schema_probe_specs()
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": "external_schema_probe_handoff_ready",
        "source_tracker": "results/access_submission_tracker_20260509.json",
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
        "content_boundary": {
            "completed_packets_included": False,
            "completed_emails_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "feature_manifest_artifacts_included": False,
            "record_paths_reported": False,
            "credentials_or_tokens_included": False,
            "target_values_included": False,
            "row_level_data_included": False,
            "model_outputs_included": False,
        },
    }


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# External Schema-Probe Handoff - 2026-05-15",
        "",
        "This is a content-free post-approval handoff. It is not an access approval, completed schema probe, target-free feature manifest, preregistration, model run, protected-data artifact, or T1/T3 claim update.",
        "",
        f"- Decision: `{payload['decision']}`",
        f"- Goal complete: `{payload['goal_complete']}`",
        f"- Route count: `{payload['route_count']}`",
        f"- Schema contract: `{payload['source_schema_contract']}`",
        "",
        "## Routes",
        "",
    ]
    for row in payload["routes"]:
        commands = row["post_approval_commands"]
        lines.extend(
            [
                f"### {row['priority']}. {row['name']} (`{row['id']}`)",
                "",
                f"- Protected access required: `{row['protected_access_required']}`",
                f"- Required sections: `{', '.join(row['required_sections'])}`",
                f"- Required grouping keys: `{', '.join(row['required_grouping_keys'])}`",
                f"- Required target columns: `{', '.join(row['required_target_columns'])}`",
                f"- Required sensor modalities: `{', '.join(row['required_sensor_modalities'])}`",
                f"- Minimum valid subjects: `{row['min_subjects']}`",
                "",
                "Post-approval workflow sequence:",
                "",
                *(
                    f"{idx}. `{step['step_id']}` - `{step['command']}`"
                    for idx, step in enumerate(
                        row["post_approval_workflow_sequence"],
                        start=1,
                    )
                ),
                "",
                "Post-approval commands:",
                "",
                f"- Validate local schema report: `{commands['validate_schema_probe_report']}`",
                f"- Record scrubbed schema metadata after validation: `{commands['record_schema_probe_metadata']}`",
                f"- Validate target-free manifest: `{commands['validate_target_free_manifest']}`",
                f"- Validate formula-SHA record before extraction or scoring: `{commands['validate_formula_sha_record']}`",
                f"- Validate aggregate external result record after scoring: `{commands['validate_zeroshot_result_record']}`",
                "",
                "Still blocked until approval and schema/manifest gates pass:",
                "",
                *(
                    f"- {action}"
                    for action in row["blocked_until_schema_and_manifest_gates_pass"]
                ),
                "",
            ]
        )
        support = row.get("ppmi_specific_support") or {}
        if support:
            lines.extend(
                [
                    "PPMI/Verily-specific support:",
                    "",
                    f"- Checklist: `{support['schema_probe_checklist']}`",
                    f"- Report template: `{support['schema_probe_report_template']}`",
                    f"- Checklist audit: `{support['schema_probe_checklist_audit']}`",
                    f"- Report-template audit: `{support['schema_probe_report_template_audit']}`",
                    f"- Route-specific validator: `{support['schema_probe_validator']}`",
                    f"- Route-specific validator command: `{support['schema_probe_validator_command']}`",
                    f"- Target-free manifest template: `{support['target_free_manifest_template']}`",
                    f"- Target-free manifest validator: `{support['target_free_manifest_validator']}`",
                    f"- Target-free manifest validator command: `{support['target_free_manifest_validator_command']}`",
                    "",
                ]
            )
    lines.extend(
        [
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
    payload = build_payload(load_tracker())
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
