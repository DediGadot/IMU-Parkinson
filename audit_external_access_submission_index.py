#!/usr/bin/env python3
"""Audit the content-free external access submission index."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "write_external_access_submission_index.py"
INDEX_JSON = RESULTS / "external_access_submission_index_20260515.json"
INDEX_MD = RESULTS / "external_access_submission_index_20260515.md"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
OUT_JSON = RESULTS / "external_access_submission_index_audit_20260515.json"
OUT_MD = RESULTS / "external_access_submission_index_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
EXPECTED_COMMANDS = {
    "show_fill_checklist",
    "validate_completed_packet",
    "record_submission_metadata",
    "record_approval_metadata",
    "validate_schema_probe_report",
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
}
EXPECTED_PPMI_EXTRA_COMMANDS = {
    "validate_completed_email",
    "validate_completed_package",
}
EXPECTED_PPMI_WORKFLOW_STEP_IDS = [
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
EXPECTED_GENERIC_WORKFLOW_STEP_IDS = [
    "validate_completed_packet",
    "record_submission_metadata",
    "record_approval_metadata",
    "validate_schema_probe_report",
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


def route_commands_are_valid(row: dict[str, Any]) -> bool:
    route_id = row.get("id")
    commands = row.get("commands") or {}
    if route_id == "ppmi_verily":
        if set(commands.keys()) != EXPECTED_COMMANDS | EXPECTED_PPMI_EXTRA_COMMANDS:
            return False
        return (
            commands.get("show_fill_checklist")
            == "uv run python scripts/show_ppmi_verily_next_action.py"
            and commands.get("validate_completed_packet")
            == (
                "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                "--packet <completed_packet_path_outside_git>"
            )
            and commands.get("validate_completed_email")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            )
            and commands.get("validate_completed_package")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            )
            and commands.get("validate_schema_probe_report")
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
                    "record_submission_metadata",
                    "record_approval_metadata",
                    "validate_formula_sha_record",
                    "validate_zeroshot_result_record",
                )
            )
            and "--pre-submission-preflight-passed"
            in commands.get("record_submission_metadata", "")
        )
    if EXPECTED_COMMANDS != set(commands.keys()):
        return False
    return (
        all(f"--route-id {route_id}" in command for command in commands.values())
        and "scripts/show_access_request_fill_checklist.py"
        in commands.get("show_fill_checklist", "")
        and "scripts/validate_access_request_packet.py"
        in commands.get("validate_completed_packet", "")
        and "scripts/validate_schema_probe_report.py"
        in commands.get("validate_schema_probe_report", "")
        and "scripts/validate_target_free_manifest.py"
        in commands.get("validate_target_free_manifest", "")
        and "scripts/validate_external_formula_sha_record.py"
        in commands.get("validate_formula_sha_record", "")
        and "scripts/validate_external_zeroshot_result_record.py"
        in commands.get("validate_zeroshot_result_record", "")
    )


def route_workflow_is_valid(row: dict[str, Any]) -> bool:
    route_id = row.get("id")
    commands = row.get("commands") or {}
    workflow = row.get("workflow_command_sequence") or []
    expected_step_ids = (
        EXPECTED_PPMI_WORKFLOW_STEP_IDS
        if route_id == "ppmi_verily"
        else EXPECTED_GENERIC_WORKFLOW_STEP_IDS
    )
    return workflow == [
        {"step_id": step_id, "command": commands.get(step_id)}
        for step_id in expected_step_ids
    ]


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Access Submission Index Audit - 2026-05-15",
        "",
        "This audits the stable, content-free external access submission index. It is not a completed packet, submission record, approval, schema probe, protected-data artifact, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Index JSON: `{report['index_json']}`",
        f"- Index Markdown: `{report['index_markdown']}`",
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
    index = load_json(INDEX_JSON) if INDEX_JSON.exists() else {}
    tracker = load_json(TRACKER)
    md_text = INDEX_MD.read_text(encoding="utf-8") if INDEX_MD.exists() else ""
    routes = index.get("routes") or []
    route_ids = [row.get("id") for row in routes]
    tracker_routes = {
        row.get("id"): row
        for row in tracker.get("routes", [])
        if isinstance(row, dict)
    }
    combined_text = json.dumps(index, sort_keys=True) + "\n" + md_text + "\n" + writer["stdout"]
    found_forbidden = forbidden_found(combined_text)
    boundary = index.get("content_boundary") or {}

    checks = [
        check(
            "writer command succeeds and writes both outputs",
            writer["returncode"] == 0
            and (writer.get("parsed") or {}).get("json") == rel(INDEX_JSON)
            and (writer.get("parsed") or {}).get("markdown") == rel(INDEX_MD)
            and INDEX_JSON.exists()
            and INDEX_MD.exists(),
            {"returncode": writer["returncode"], "stdout": writer["stdout"][-800:]},
        ),
        check(
            "index covers six submit-ready routes in tracker order",
            index.get("decision") == "external_access_submission_index_ready"
            and index.get("goal_complete") is False
            and index.get("route_count") == 6
            and route_ids == EXPECTED_ROUTE_IDS
            and index.get("summary", {}).get("submit_ready_route_count") == 6
            and index.get("summary", {}).get("compute_ready_route_count") == 0
            and tracker.get("summary", {}).get("compute_ready_route_count") == 0,
            {
                "route_ids": route_ids,
                "index_summary": index.get("summary"),
                "tracker_summary": tracker.get("summary"),
            },
        ),
        check(
            "open field counts mirror tracker placeholders",
            all(
                row.get("open_field_count")
                == len(tracker_routes.get(row.get("id"), {}).get("packet_placeholders", []))
                for row in routes
            ),
            {
                "open_field_counts": {
                    row.get("id"): row.get("open_field_count")
                    for row in routes
                }
            },
        ),
        check(
            "every route has safe command templates with route-specific PPMI overrides",
            all(route_commands_are_valid(row) for row in routes),
            {
                "commands_by_route": {
                    row.get("id"): sorted((row.get("commands") or {}).keys())
                    for row in routes
                }
            },
        ),
        check(
            "every route exposes an ordered workflow command sequence",
            all(route_workflow_is_valid(row) for row in routes)
            and "Workflow command sequence:" in md_text
            and "1. `validate_completed_packet`: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`"
            in md_text
            and "9. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`"
            in md_text,
            {
                "workflow_by_route": {
                    row.get("id"): [
                        step.get("step_id")
                        for step in row.get("workflow_command_sequence", [])
                    ]
                    for row in routes
                },
                "ppmi_markdown_has_numbered_workflow": (
                    "9. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`"
                    in md_text
                ),
            },
        ),
        check(
            "markdown includes post-manifest and post-score gates",
            "Post-manifest formula-SHA preflight" in md_text
            and "Post-score aggregate result preflight" in md_text
            and "scripts/validate_external_formula_sha_record.py" in md_text
            and "scripts/validate_external_zeroshot_result_record.py" in md_text,
            {
                "formula_gate_present": "Post-manifest formula-SHA preflight" in md_text,
                "result_gate_present": "Post-score aggregate result preflight" in md_text,
            },
        ),
        check(
            "markdown PPMI route uses PPMI-specific preflight commands",
            "Fill checklist: `uv run python scripts/show_ppmi_verily_next_action.py`"
            in md_text
            and "Completed-packet preflight: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`"
            in md_text
            and "Completed-email preflight: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`"
            in md_text
            and "Completed-package preflight: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`"
            in md_text
            and "Post-approval schema report preflight: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`"
            in md_text
            and "Post-schema target-free manifest preflight: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`"
            in md_text
            and "Formula-SHA validator: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`"
            in md_text
            and "Aggregate result validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`"
            in md_text
            and "scripts/validate_schema_probe_report.py --route-id ppmi_verily"
            not in md_text
            and "scripts/validate_target_free_manifest.py --route-id ppmi_verily"
            not in md_text,
            {"ppmi_markdown": md_text.split("### 2.", 1)[0][-1800:]},
        ),
        check(
            "all routes remain compute blocked",
            all(row.get("remote_job_allowed_now") is False for row in routes)
            and all(row.get("scaffold_allowed_now") is False for row in routes)
            and all("model run" in row.get("blocked_actions_now", []) for row in routes),
            {
                "route_compute_flags": {
                    row.get("id"): {
                        "remote_job_allowed_now": row.get("remote_job_allowed_now"),
                        "scaffold_allowed_now": row.get("scaffold_allowed_now"),
                    }
                    for row in routes
                }
            },
        ),
        check(
            "PPMI specialized submission support is present",
            (routes[0].get("ppmi_submission_support") or {}).get("word_packet_template")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
            and (routes[0].get("ppmi_submission_support") or {}).get("user_fill_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and (routes[0].get("ppmi_submission_support") or {}).get("next_action_command")
            == "uv run python scripts/show_ppmi_verily_next_action.py"
            and (routes[0].get("ppmi_submission_support") or {}).get("completed_packet_validator")
            == "scripts/validate_ppmi_verily_completed_packet.py"
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("completed_packet_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                "--packet <completed_packet_path_outside_git>"
            )
            and (routes[0].get("ppmi_submission_support") or {}).get("completed_email_validator")
            == "scripts/validate_ppmi_verily_submission_email.py"
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("completed_email_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            )
            and (routes[0].get("ppmi_submission_support") or {}).get("completed_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("completed_package_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            )
            and (routes[0].get("ppmi_submission_support") or {}).get("current_submission_handoff")
            == "results/ppmi_verily_current_submission_handoff_20260515.md"
            and (routes[0].get("ppmi_submission_support") or {}).get("schema_probe_validator")
            == "scripts/validate_ppmi_verily_schema_probe_report.py"
            and (routes[0].get("ppmi_submission_support") or {}).get("schema_probe_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("target_free_manifest_validator")
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("target_free_manifest_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("formula_sha_record_validator")
            == "scripts/validate_external_formula_sha_record.py"
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("formula_sha_record_validator_command")
            == (
                "uv run python scripts/validate_external_formula_sha_record.py "
                "--route-id ppmi_verily "
                "--record <completed_formula_sha_record_path_outside_git>"
            )
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("zeroshot_result_record_validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("zeroshot_result_record_validator_command")
            == (
                "uv run python scripts/validate_external_zeroshot_result_record.py "
                "--route-id ppmi_verily "
                "--record <completed_external_zeroshot_result_record_path_outside_git>"
            )
            and (
                routes[0].get("ppmi_submission_support") or {}
            ).get("workflow_command_sequence")
            == routes[0].get("workflow_command_sequence"),
            {"ppmi_submission_support": routes[0].get("ppmi_submission_support") if routes else None},
        ),
        check(
            "content boundary blocks completed/protected artifacts",
            boundary.get("completed_packets_included") is False
            and boundary.get("completed_emails_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("feature_manifest_artifacts_included") is False
            and boundary.get("record_paths_reported") is False
            and boundary.get("credentials_or_tokens_included") is False,
            {"content_boundary": boundary},
        ),
        check(
            "index output does not expose private artifacts",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_access_submission_index.py",
        "writer": "scripts/write_external_access_submission_index.py",
        "index_json": rel(INDEX_JSON),
        "index_markdown": rel(INDEX_MD),
        "source_tracker": rel(TRACKER),
        "passed": not hard_failures,
        "decision": (
            "external_access_submission_index_ready"
            if not hard_failures
            else "external_access_submission_index_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
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
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
