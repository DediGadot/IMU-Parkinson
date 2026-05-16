#!/usr/bin/env python3
"""Audit the content-free all-route external schema-probe handoff."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import external_schema_probe_specs
from pd_imu.experiments import (
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "write_external_schema_probe_handoff.py"
HANDOFF_JSON = RESULTS / "external_schema_probe_handoff_20260515.json"
HANDOFF_MD = RESULTS / "external_schema_probe_handoff_20260515.md"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
PPMI_CHECKLIST_AUDIT = RESULTS / "ppmi_verily_schema_probe_checklist_audit_20260515.json"
PPMI_TEMPLATE_AUDIT = RESULTS / "ppmi_verily_schema_probe_report_template_audit_20260515.json"
OUT_JSON = RESULTS / "external_schema_probe_handoff_audit_20260515.json"
OUT_MD = RESULTS / "external_schema_probe_handoff_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
EXPECTED_COMMANDS = {
    "validate_schema_probe_report",
    "record_schema_probe_metadata",
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
}
EXPECTED_POST_APPROVAL_WORKFLOW_STEP_IDS = [
    "validate_schema_probe_report",
    "record_schema_probe_metadata",
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
]
FORBIDDEN_SNIPPETS = [
    ".access_",
    "_submission.json",
    "_approval.json",
    "_schema_probe.json",
    "LOCAL_COMPLETED",
    "password",
    "api_key",
    "private_key",
    "raw sample",
    "raw rows",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{rel(path)} must contain a JSON object")
    return payload


def run_writer() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "parsed": parsed,
    }


def forbidden_found(text: str) -> list[str]:
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def row_matches_spec(row: dict[str, Any], spec: Any) -> bool:
    return (
        row.get("id") == spec.route_id
        and row.get("name") == spec.name
        and tuple(row.get("required_sections") or ()) == spec.required_sections
        and tuple(row.get("required_grouping_keys") or ()) == spec.required_grouping_keys
        and tuple(row.get("required_target_columns") or ()) == spec.required_target_columns
        and tuple(row.get("required_sensor_modalities") or ())
        == spec.required_sensor_modalities
        and row.get("min_subjects") == spec.min_subjects
        and row.get("protected_access_required") == spec.protected_access_required
    )


def post_approval_commands_valid(row: dict[str, Any]) -> bool:
    route_id = row.get("id")
    commands = row.get("post_approval_commands") or {}
    if EXPECTED_COMMANDS != set(commands):
        return False
    if route_id == "ppmi_verily":
        return (
            commands.get("validate_schema_probe_report")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            and commands.get("validate_target_free_manifest")
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and "scripts/validate_schema_probe_report.py --route-id ppmi_verily"
            not in commands.get("validate_schema_probe_report", "")
            and "scripts/validate_target_free_manifest.py --route-id ppmi_verily"
            not in commands.get("validate_target_free_manifest", "")
            and all(
                f"--route-id {route_id}" in commands[key]
                for key in (
                    "record_schema_probe_metadata",
                    "validate_formula_sha_record",
                    "validate_zeroshot_result_record",
                )
            )
        )
    return (
        all(f"--route-id {route_id}" in command for command in commands.values())
        and "completed_schema_probe_report_path_outside_git"
        in commands.get("validate_schema_probe_report", "")
        and "completed_target_free_manifest_path_outside_git"
        in commands.get("validate_target_free_manifest", "")
        and "scripts/validate_external_formula_sha_record.py"
        in commands.get("validate_formula_sha_record", "")
        and "completed_formula_sha_record_path_outside_git"
        in commands.get("validate_formula_sha_record", "")
        and "scripts/validate_external_zeroshot_result_record.py"
        in commands.get("validate_zeroshot_result_record", "")
        and "completed_external_zeroshot_result_record_path_outside_git"
        in commands.get("validate_zeroshot_result_record", "")
    )


def post_approval_workflow_valid(row: dict[str, Any]) -> bool:
    commands = row.get("post_approval_commands") or {}
    workflow = row.get("post_approval_workflow_sequence") or []
    return workflow == [
        {"step_id": step_id, "command": commands.get(step_id)}
        for step_id in EXPECTED_POST_APPROVAL_WORKFLOW_STEP_IDS
    ]


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Schema-Probe Handoff Audit - 2026-05-15",
        "",
        "This audits the generic post-approval schema-probe handoff. It is not an approval, schema probe, feature manifest, preregistration, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Handoff JSON: `{report['handoff_json']}`",
        f"- Handoff Markdown: `{report['handoff_markdown']}`",
        f"- Route count: `{report['route_count']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Checks",
        "",
    ]
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- {failure['name']}: {failure['evidence']}")
    else:
        lines.extend(["", "## Hard Failures", "", "- None."])
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    writer = run_writer()
    handoff = load_json(HANDOFF_JSON) if HANDOFF_JSON.exists() else {}
    tracker = load_json(TRACKER)
    ppmi_checklist_audit = load_json(PPMI_CHECKLIST_AUDIT)
    ppmi_template_audit = load_json(PPMI_TEMPLATE_AUDIT)
    md_text = HANDOFF_MD.read_text(encoding="utf-8") if HANDOFF_MD.exists() else ""
    specs = external_schema_probe_specs()
    routes = handoff.get("routes") or []
    route_ids = [row.get("id") for row in routes]
    route_by_id = {row.get("id"): row for row in routes}
    spec_by_id = {spec.route_id: spec for spec in specs}
    tracker_route_ids = [
        row.get("id")
        for row in tracker.get("routes", [])
        if isinstance(row, dict)
    ]
    combined_text = json.dumps(handoff, sort_keys=True) + "\n" + md_text + "\n" + writer["stdout"]
    found_forbidden = forbidden_found(combined_text)
    boundary = handoff.get("content_boundary") or {}
    ppmi_support = route_by_id.get("ppmi_verily", {}).get("ppmi_specific_support") or {}

    checks = [
        check(
            "writer command succeeds and writes both handoff outputs",
            writer["returncode"] == 0
            and (writer.get("parsed") or {}).get("json") == rel(HANDOFF_JSON)
            and (writer.get("parsed") or {}).get("markdown") == rel(HANDOFF_MD)
            and HANDOFF_JSON.exists()
            and HANDOFF_MD.exists(),
            {"returncode": writer["returncode"], "stdout": writer["stdout"][-800:]},
        ),
        check(
            "handoff covers six schema-probe routes in contract order",
            handoff.get("decision") == "external_schema_probe_handoff_ready"
            and handoff.get("route_count") == 6
            and route_ids == EXPECTED_ROUTE_IDS
            and route_ids == [spec.route_id for spec in specs]
            and tracker_route_ids[:6] == EXPECTED_ROUTE_IDS
            and handoff.get("goal_complete") is False,
            {
                "route_ids": route_ids,
                "spec_route_ids": [spec.route_id for spec in specs],
                "tracker_route_ids": tracker_route_ids[:6],
            },
        ),
        check(
            "route rows mirror pd_imu schema-probe specs",
            all(row_matches_spec(route_by_id.get(spec.route_id, {}), spec) for spec in specs),
            {
                "route_contracts": {
                    spec.route_id: {
                        "row": route_by_id.get(spec.route_id, {}),
                        "spec": spec.to_dict(),
                    }
                    for spec in specs
                }
            },
        ),
        check(
            "every route has post-approval commands with PPMI-specific validator overrides",
            all(post_approval_commands_valid(row) for row in routes),
            {
                "commands_by_route": {
                    row.get("id"): sorted((row.get("post_approval_commands") or {}).keys())
                    for row in routes
                }
            },
        ),
        check(
            "every route exposes an ordered post-approval workflow sequence",
            all(post_approval_workflow_valid(row) for row in routes)
            and "Post-approval workflow sequence:" in md_text
            and "1. `validate_schema_probe_report`" in md_text
            and "2. `record_schema_probe_metadata`" in md_text
            and "3. `validate_target_free_manifest`" in md_text
            and "4. `validate_formula_sha_record`" in md_text
            and "5. `validate_zeroshot_result_record`" in md_text,
            {
                "expected_step_ids": EXPECTED_POST_APPROVAL_WORKFLOW_STEP_IDS,
                "workflow_by_route": {
                    row.get("id"): [
                        step.get("step_id")
                        for step in row.get("post_approval_workflow_sequence", [])
                    ]
                    for row in routes
                },
                "ppmi_workflow": route_by_id.get("ppmi_verily", {}).get(
                    "post_approval_workflow_sequence"
                ),
            },
        ),
        check(
            "markdown includes formula-SHA and aggregate-result gates",
            "Validate formula-SHA record before extraction or scoring" in md_text
            and "Validate aggregate external result record after scoring" in md_text
            and "scripts/validate_external_formula_sha_record.py" in md_text
            and "scripts/validate_external_zeroshot_result_record.py" in md_text,
            {
                "formula_gate_present": (
                    "Validate formula-SHA record before extraction or scoring" in md_text
                ),
                "result_gate_present": (
                    "Validate aggregate external result record after scoring" in md_text
                ),
            },
        ),
        check(
            "markdown PPMI route uses PPMI-specific schema and manifest validators",
            "Validate local schema report: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`"
            in md_text
            and "Validate target-free manifest: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`"
            in md_text
            and "scripts/validate_schema_probe_report.py --route-id ppmi_verily"
            not in md_text
            and "scripts/validate_target_free_manifest.py --route-id ppmi_verily"
            not in md_text,
            {"ppmi_markdown": md_text.split("### 2.", 1)[0][-1800:]},
        ),
        check(
            "blocked actions remain explicit before and after schema-probe handoff",
            all(
                tuple(row.get("blocked_before_approval") or ())
                == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS
                and tuple(row.get("blocked_until_schema_and_manifest_gates_pass") or ())
                == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
                and "model run"
                in (row.get("blocked_until_schema_and_manifest_gates_pass") or [])
                and "canonical T1/T3 claim update"
                in (row.get("blocked_until_schema_and_manifest_gates_pass") or [])
                for row in routes
            ),
            {
                "blocked_before_approval": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
                "blocked_until_schema": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
            },
        ),
        check(
            "PPMI-specific schema-probe template and checklist remain wired and audited",
            ppmi_support.get("schema_probe_checklist")
            == "scripts/ppmi_verily_schema_probe_checklist.md"
            and ppmi_support.get("schema_probe_report_template")
            == "scripts/ppmi_verily_schema_probe_report_template.md"
            and ppmi_support.get("schema_probe_checklist_audit")
            == "results/ppmi_verily_schema_probe_checklist_audit_20260515.json"
            and ppmi_support.get("schema_probe_report_template_audit")
            == "results/ppmi_verily_schema_probe_report_template_audit_20260515.json"
            and ppmi_support.get("schema_probe_validator")
            == "scripts/validate_ppmi_verily_schema_probe_report.py"
            and ppmi_support.get("schema_probe_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            and ppmi_support.get("target_free_manifest_template")
            == "scripts/ppmi_verily_target_free_manifest_template.json"
            and ppmi_support.get("target_free_manifest_validator")
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and ppmi_support.get("target_free_manifest_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and "Route-specific validator command: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`"
            in md_text
            and "Target-free manifest validator command: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`"
            in md_text
            and ppmi_checklist_audit.get("passed") is True
            and ppmi_checklist_audit.get("decision")
            == "ppmi_verily_schema_probe_checklist_ready"
            and ppmi_checklist_audit.get("schema_probe_artifact_created") is False
            and ppmi_checklist_audit.get("protected_data_included") is False
            and ppmi_template_audit.get("passed") is True
            and ppmi_template_audit.get("decision")
            == "ppmi_verily_schema_probe_report_template_ready"
            and ppmi_template_audit.get("schema_probe_artifact_created") is False
            and ppmi_template_audit.get("protected_data_included") is False,
            {
                "ppmi_support": ppmi_support,
                "checklist_decision": ppmi_checklist_audit.get("decision"),
                "template_decision": ppmi_template_audit.get("decision"),
            },
        ),
        check(
            "content boundary blocks completed/protected artifacts",
            handoff.get("not_a_submission_record") is True
            and handoff.get("not_access_approval") is True
            and handoff.get("not_a_schema_probe_artifact") is True
            and handoff.get("not_a_feature_manifest_artifact") is True
            and handoff.get("not_a_preregistration") is True
            and handoff.get("not_a_model_result") is True
            and boundary.get("completed_packets_included") is False
            and boundary.get("completed_emails_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("feature_manifest_artifacts_included") is False
            and boundary.get("record_paths_reported") is False
            and boundary.get("credentials_or_tokens_included") is False
            and boundary.get("target_values_included") is False
            and boundary.get("row_level_data_included") is False
            and boundary.get("model_outputs_included") is False,
            {"content_boundary": boundary},
        ),
        check(
            "handoff output does not expose private artifacts",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_schema_probe_handoff.py",
        "writer": "scripts/write_external_schema_probe_handoff.py",
        "handoff_json": rel(HANDOFF_JSON),
        "handoff_markdown": rel(HANDOFF_MD),
        "source_tracker": rel(TRACKER),
        "source_schema_contract": "pd_imu.datasets.external_schema_probe_specs",
        "passed": not hard_failures,
        "decision": (
            "external_schema_probe_handoff_ready"
            if not hard_failures
            else "external_schema_probe_handoff_failed"
        ),
        "route_count": len(routes),
        "route_ids": route_ids,
        "post_approval_workflow_step_ids_by_route": {
            row.get("id"): [
                step.get("step_id")
                for step in row.get("post_approval_workflow_sequence", [])
            ]
            for row in routes
        },
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_preregistration": True,
        "not_a_model_result": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failure_count": len(hard_failures),
                "route_count": report["route_count"],
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
