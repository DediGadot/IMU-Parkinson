#!/usr/bin/env python3
"""Audit the generic external access request fill-checklist command."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "show_access_request_fill_checklist.py"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
OUT_JSON = RESULTS / "access_request_fill_checklist_audit_20260515.json"
OUT_MD = RESULTS / "access_request_fill_checklist_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
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
ALLOWED_PLACEHOLDER_SNIPPETS = [
    "[LOCAL_COMPLETED_PACKET_PATH]",
    "[LOCAL_COMPLETED_EMAIL_PATH]",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{rel(path)} must contain a JSON object")
    return payload


def run_script(*args: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    parsed: dict[str, Any] | None = None
    if "--json" in args:
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "returncode": proc.returncode,
        "parsed": parsed,
        "stdout": proc.stdout,
        "output_tail": proc.stdout[-1600:],
    }


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def forbidden_found(text: str) -> list[str]:
    for allowed in ALLOWED_PLACEHOLDER_SNIPPETS:
        text = text.replace(allowed, "")
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def row_command_surface_valid(row: dict[str, Any]) -> bool:
    route_id = row.get("id")
    approval_command_valid = row.get("record_approval_command_template") == (
        "uv run python scripts/record_access_approval.py "
        f"--route-id {route_id} "
        "--approved-at-utc <ISO8601_UTC> "
        "--source <non_protected_approval_source>"
    )
    submission_command_valid = (
        "scripts/record_access_submission.py" in row.get("record_submission_command_template", "")
        and f"--route-id {route_id}" in row.get("record_submission_command_template", "")
        and "--pre-submission-preflight-passed" in row.get("record_submission_command_template", "")
    )
    placeholder_policy_valid = (
        "Do not use --allow-placeholders for a real pre-submission check"
        in row.get("placeholder_audit_policy", "")
        and "audit-only" in row.get("placeholder_audit_policy", "")
        and "not valid for submission" in row.get("placeholder_audit_policy", "")
        and "--allow-placeholders" not in row.get("completed_packet_validator_command", "")
    )
    if route_id == "ppmi_verily":
        return (
            row.get("completed_packet_validator")
            == "scripts/validate_ppmi_verily_completed_packet.py"
            and placeholder_policy_valid
            and submission_command_valid
            and approval_command_valid
            and row.get("completed_packet_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                "--packet <completed_packet_path_outside_git>"
            )
            and row.get("post_approval_schema_report_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            and row.get("post_schema_target_free_manifest_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and "scripts/validate_access_request_packet.py --route-id ppmi_verily"
            not in row.get("completed_packet_validator_command", "")
            and "scripts/validate_schema_probe_report.py --route-id ppmi_verily"
            not in row.get("post_approval_schema_report_validator_command", "")
            and "scripts/validate_target_free_manifest.py --route-id ppmi_verily"
            not in row.get("post_schema_target_free_manifest_validator_command", "")
            and "scripts/validate_external_formula_sha_record.py"
            in row.get("post_manifest_formula_sha_validator_command", "")
            and f"--route-id {route_id}" in row.get(
                "post_manifest_formula_sha_validator_command", ""
            )
            and "scripts/validate_external_zeroshot_result_record.py"
            in row.get("post_score_zeroshot_result_validator_command", "")
            and f"--route-id {route_id}" in row.get(
                "post_score_zeroshot_result_validator_command", ""
            )
        )
    return (
        row.get("completed_packet_validator")
        == "scripts/validate_access_request_packet.py"
        and placeholder_policy_valid
        and submission_command_valid
        and approval_command_valid
        and f"--route-id {route_id}" in row.get("completed_packet_validator_command", "")
        and "scripts/validate_schema_probe_report.py"
        in row.get("post_approval_schema_report_validator_command", "")
        and f"--route-id {route_id}" in row.get(
            "post_approval_schema_report_validator_command", ""
        )
        and "scripts/validate_target_free_manifest.py"
        in row.get("post_schema_target_free_manifest_validator_command", "")
        and f"--route-id {route_id}" in row.get(
            "post_schema_target_free_manifest_validator_command", ""
        )
        and "scripts/validate_external_formula_sha_record.py"
        in row.get("post_manifest_formula_sha_validator_command", "")
        and f"--route-id {route_id}" in row.get(
            "post_manifest_formula_sha_validator_command", ""
        )
        and "scripts/validate_external_zeroshot_result_record.py"
        in row.get("post_score_zeroshot_result_validator_command", "")
        and f"--route-id {route_id}" in row.get(
            "post_score_zeroshot_result_validator_command", ""
        )
    )


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Access Request Fill Checklist Audit - 2026-05-15",
        "",
        "This audits a content-free fill-checklist helper for queued external access requests. It is not a completed packet, submission record, approval, schema probe, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Script: `{report['script']}`",
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
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The fill-checklist command is ready for user-side access packet completion across the six queued routes. It prints placeholder names and command templates only.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    tracker = load_json(TRACKER)
    tracker_routes = {
        row.get("id"): row
        for row in tracker.get("routes", [])
        if isinstance(row, dict)
    }
    all_json_run = run_script("--json")
    text_run = run_script()
    ppmi_json_run = run_script("--route-id", "ppmi_verily", "--json")
    unknown_run = run_script("--route-id", "not_a_real_route", "--json")
    parsed = all_json_run.get("parsed") or {}
    routes = parsed.get("routes") or []
    route_ids = [row.get("id") for row in routes]
    boundary = parsed.get("content_boundary") or {}
    combined_output = all_json_run["stdout"] + "\n" + text_run["stdout"] + "\n" + ppmi_json_run["stdout"]
    found_forbidden = forbidden_found(combined_output)

    checks = [
        check("fill-checklist script exists", SCRIPT.exists(), {"script": rel(SCRIPT)}),
        check(
            "json command returns all six routes in tracker order",
            all_json_run["returncode"] == 0
            and parsed.get("decision") == "access_request_fill_checklist_ready"
            and parsed.get("goal_complete") is False
            and parsed.get("not_a_model_result") is True
            and parsed.get("route_count") == 6
            and route_ids == EXPECTED_ROUTE_IDS
            and parsed.get("summary", {}).get("submit_ready_route_count") == 6
            and parsed.get("summary", {}).get("compute_ready_route_count") == 0,
            {
                "returncode": all_json_run["returncode"],
                "route_ids": route_ids,
                "summary": parsed.get("summary"),
            },
        ),
        check(
            "placeholder counts match the source tracker",
            all(
                row.get("placeholder_count")
                == len(tracker_routes.get(row.get("id"), {}).get("packet_placeholders", []))
                for row in routes
            ),
            {
                "route_placeholder_counts": {
                    row.get("id"): row.get("placeholder_count")
                    for row in routes
                }
            },
        ),
        check(
            "every route exposes safe preflights with PPMI-specific overrides",
            all(row_command_surface_valid(row) for row in routes),
            {
            "commands_by_route": {
                    row.get("id"): {
                        "packet": row.get("completed_packet_validator_command"),
                        "approval": row.get("record_approval_command_template"),
                        "schema_report": row.get("post_approval_schema_report_validator_command"),
                        "target_free": row.get("post_schema_target_free_manifest_validator_command"),
                        "formula_sha": row.get("post_manifest_formula_sha_validator_command"),
                        "zeroshot_result": row.get("post_score_zeroshot_result_validator_command"),
                    }
                    for row in routes
                }
            },
        ),
        check(
            "PPMI route preserves specialized package support",
            ppmi_json_run["returncode"] == 0
            and (ppmi_json_run.get("parsed") or {}).get("route_count") == 1
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("fill_fields", {})
            .get("source_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("fill_fields", {})
            .get("packet_field_count")
            == 13
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("fill_fields", {})
            .get("email_field_count")
            == 12
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("fill_fields", {})
            .get("submission_metadata_field_count")
            == 4
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("completed_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("completed_email_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            )
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("completed_package_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            )
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("schema_report_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("target_free_manifest_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
            .get("ppmi_submission_support", {})
            .get("user_fill_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md",
            {
                "returncode": ppmi_json_run["returncode"],
                "ppmi_support": (ppmi_json_run.get("parsed") or {}).get("routes", [{}])[0]
                .get("ppmi_submission_support", {}),
            },
        ),
        check(
            "text command surfaces PPMI packet/email/metadata fill counts",
            "PPMI packet fields to fill: 13" in text_run["stdout"]
            and "PPMI email fields to fill: 12" in text_run["stdout"]
            and "PPMI submission metadata fields: 4" in text_run["stdout"],
            {"stdout_tail": text_run["output_tail"]},
        ),
        check(
            "text command warns placeholder audit mode is not real preflight",
            text_run["stdout"].count("Placeholder audit policy:") == 6
            and "Do not use --allow-placeholders for a real pre-submission check"
            in text_run["stdout"]
            and "not valid for submission" in text_run["stdout"],
            {"stdout_tail": text_run["output_tail"]},
        ),
        check(
            "unknown route id fails closed without leaking local paths",
            unknown_run["returncode"] != 0
            and "unknown route_id" in unknown_run["stdout"]
            and ".access_" not in unknown_run["stdout"]
            and "_submission.json" not in unknown_run["stdout"],
            {
                "returncode": unknown_run["returncode"],
                "output_tail": unknown_run["output_tail"],
            },
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
            "output does not expose completed artifacts or private material",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
        check(
            "source tracker remains submit-ready with compute blocked",
            tracker.get("decision") == "access_submission_tracker_ready"
            and tracker.get("summary", {}).get("passed") is True
            and tracker.get("summary", {}).get("submit_ready_route_count") == 6
            and tracker.get("summary", {}).get("compute_ready_route_count") == 0
            and tracker.get("summary", {}).get("hard_failure_count") == 0
            and tracker.get("goal_complete") is False,
            {
                "tracker": rel(TRACKER),
                "summary": tracker.get("summary"),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/show_access_request_fill_checklist.py",
        "source_tracker": "results/access_submission_tracker_20260509.json",
        "passed": not hard_failures,
        "decision": (
            "access_request_fill_checklist_ready"
            if not hard_failures
            else "access_request_fill_checklist_failed"
        ),
        "route_count": len(routes),
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
                "route_count": report["route_count"],
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
