#!/usr/bin/env python3
"""Audit the all-route external access lifecycle status helper."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "show_external_access_lifecycle.py"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
SYNTH = RESULTS / "external_access_lifecycle_status_synthetic"
OUT_JSON = RESULTS / "external_access_lifecycle_status_audit_20260515.json"
OUT_MD = RESULTS / "external_access_lifecycle_status_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
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
        "stdout": proc.stdout,
        "parsed": parsed,
        "tail": proc.stdout[-1600:],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prepare_synthetic_dirs() -> dict[str, Path]:
    if SYNTH.exists():
        shutil.rmtree(SYNTH)
    dirs = {
        "submission": SYNTH / "submissions",
        "approval": SYNTH / "approvals",
        "schema": SYNTH / "schema_probes",
        "bad_schema": SYNTH / "bad_schema_probes",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    write_json(
        dirs["submission"] / "ppp_pd_vme_submission.json",
        {
            "submission_evidence": {
                "route_id": "ppp_pd_vme",
                "submitted_at_utc": "2026-05-15T00:00:00Z",
                "submission_channel": "PPP official submission portal",
                "submitted_by": "approved institutional delegate",
                "confirmation_reference": "non-protected receipt 123",
                "pre_submission_preflight_passed": True,
                "notes": "Non-protected lifecycle audit fixture",
            }
        },
    )
    write_json(
        dirs["approval"] / "ppmi_verily_approval.json",
        {
            "approval_evidence": {
                "route_id": "ppmi_verily",
                "source": "non-protected PPMI approval notice",
                "approved_at_utc": "2026-05-15T00:00:00Z",
                "approved_access": True,
                "data_use_terms_accepted": True,
                "storage_plan_documented": True,
                "notes": "Non-protected lifecycle audit fixture",
            }
        },
    )
    write_json(
        dirs["approval"] / "watchpd_approval.json",
        {
            "approval_evidence": {
                "route_id": "watchpd",
                "source": "non-protected WATCH-PD governance approval notice",
                "approved_at_utc": "2026-05-15T00:00:00Z",
                "approved_access": True,
                "data_use_terms_accepted": True,
                "storage_plan_documented": True,
                "notes": "Non-protected lifecycle audit fixture",
            }
        },
    )
    write_json(
        dirs["approval"] / "cns_portugal_lobo_approval.json",
        {
            "approval_evidence": {
                "route_id": "cns_portugal_lobo",
                "source": "non-protected CNS Portugal approval notice",
                "approved_at_utc": "2026-05-15T00:00:00Z",
                "approved_access": True,
                "data_use_terms_accepted": True,
                "storage_plan_documented": True,
                "notes": "Non-protected lifecycle audit fixture",
            }
        },
    )
    write_json(
        dirs["schema"] / "cns_portugal_lobo_schema_probe.json",
        {
            "route_id": "cns_portugal_lobo",
            "schema_probe_metadata_only": True,
            "protected_data_included": False,
            "not_a_model_result": True,
        },
    )
    write_json(
        dirs["bad_schema"] / "hssayeni_mjff_schema_probe.json",
        {
            "route_id": "hssayeni_mjff",
            "schema_probe_metadata_only": True,
            "protected_data_included": False,
        },
    )
    return dirs


def forbidden_found(text: str) -> list[str]:
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


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
        if commands.get(step_id)
    ]


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Access Lifecycle Status Audit - 2026-05-15",
        "",
        "This audits the all-route lifecycle status helper. It is not a submission record, approval, schema probe, protected-data artifact, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Status helper: `{report['status_helper']}`",
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
    dirs = prepare_synthetic_dirs()
    default_json = run_script("--json")
    default_text = run_script()
    synthetic_json = run_script(
        "--json",
        "--submission-dir",
        str(dirs["submission"]),
        "--approval-dir",
        str(dirs["approval"]),
        "--schema-probe-dir",
        str(dirs["schema"]),
    )
    bad_schema_json = run_script(
        "--json",
        "--submission-dir",
        str(dirs["submission"]),
        "--approval-dir",
        str(dirs["approval"]),
        "--schema-probe-dir",
        str(dirs["bad_schema"]),
    )
    default = default_json.get("parsed") or {}
    synthetic = synthetic_json.get("parsed") or {}
    bad_schema = bad_schema_json.get("parsed") or {}
    default_routes = default.get("routes") or []
    default_routes_by_id = {row.get("id"): row for row in default_routes}
    synthetic_routes = {row.get("id"): row for row in synthetic.get("routes") or []}
    bad_routes = {row.get("id"): row for row in bad_schema.get("routes") or []}
    combined_output = "\n".join(
        [
            default_json["stdout"],
            default_text["stdout"],
            synthetic_json["stdout"],
            bad_schema_json["stdout"],
        ]
    )
    found_forbidden = forbidden_found(combined_output)
    boundary = default.get("content_boundary") or {}

    checks = [
        check("status helper exists", SCRIPT.exists(), {"script": rel(SCRIPT)}),
        check(
            "default status shows six packet-ready routes and zero records",
            default_json["returncode"] == 0
            and default.get("decision") == "external_access_lifecycle_status_ready"
            and default.get("goal_complete") is False
            and default.get("route_count") == 6
            and [row.get("id") for row in default_routes] == EXPECTED_ROUTE_IDS
            and default.get("summary", {}).get("state_counts") == {"packet_ready": 6}
            and default.get("summary", {}).get("action_counts") == {"submit_access_request": 6}
            and default.get("summary", {}).get("non_audit_submission_record_count") == 0
            and default.get("summary", {}).get("non_audit_approval_record_count") == 0
            and default.get("summary", {}).get("non_audit_schema_probe_record_count") == 0
            and all(row.get("safe_to_execute_code") is False for row in default_routes),
            {
                "returncode": default_json["returncode"],
                "summary": default.get("summary"),
            },
        ),
        check(
            "text status is content-free and action-oriented",
            default_text["returncode"] == 0
            and "External access lifecycle status" in default_text["stdout"]
            and "State counts: {'packet_ready': 6}" in default_text["stdout"]
            and "Recommended next:" in default_text["stdout"]
            and "Recommended next: uv run python scripts/show_ppmi_verily_next_action.py"
            in default_text["stdout"]
            and "Pre-submit packet validator: uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>"
            in default_text["stdout"]
            and "Pre-submit email validator: uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>"
            in default_text["stdout"]
            and "Pre-submit package validator: uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>"
            in default_text["stdout"]
            and "Record submission metadata: uv run python scripts/record_access_submission.py --route-id ppmi_verily"
            in default_text["stdout"]
            and "--pre-submission-preflight-passed"
            in default_text["stdout"]
            and "Record approval metadata: uv run python scripts/record_access_approval.py --route-id ppmi_verily"
            in default_text["stdout"]
            and "Workflow command sequence:" in default_text["stdout"]
            and "1. validate_completed_packet: uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>"
            in default_text["stdout"]
            and "9. validate_zeroshot_result_record: uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>"
            in default_text["stdout"]
            and "PPMI handoff: results/ppmi_verily_current_submission_handoff_20260515.md"
            in default_text["stdout"]
            and (
                "Post-approval schema report validator: "
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            in default_text["stdout"]
            and "Post-manifest formula-SHA validator:" in default_text["stdout"]
            and "Post-score aggregate result validator:" in default_text["stdout"]
            and "Goal complete: False" in default_text["stdout"],
            {"returncode": default_text["returncode"], "tail": default_text["tail"]},
        ),
        check(
            "PPMI route recommends the stricter PPMI-specific current handoff",
            (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get("recommended_next")
            == "uv run python scripts/show_ppmi_verily_next_action.py"
            and (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "ppmi_current_submission_handoff"
            )
            == "results/ppmi_verily_current_submission_handoff_20260515.md",
            {"ppmi_verily": default_routes_by_id.get("ppmi_verily")},
        ),
        check(
            "PPMI route exposes PPMI-specific pre-submit validators",
            (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "validate_completed_packet"
            )
            == (
                "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                "--packet <completed_packet_path_outside_git>"
            )
            and (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "validate_completed_email"
            )
            == (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            )
            and (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "validate_completed_package"
            )
            == (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            ),
            {"ppmi_verily": default_routes_by_id.get("ppmi_verily")},
        ),
        check(
            "every route exposes an ordered lifecycle workflow command sequence",
            all(route_workflow_is_valid(row) for row in default_routes)
            and all(route_workflow_is_valid(row) for row in synthetic.get("routes") or []),
            {
                "default_workflow_by_route": {
                    row.get("id"): [
                        step.get("step_id")
                        for step in row.get("workflow_command_sequence", [])
                    ]
                    for row in default_routes
                },
                "synthetic_workflow_by_route": {
                    row.get("id"): [
                        step.get("step_id")
                        for step in row.get("workflow_command_sequence", [])
                    ]
                    for row in synthetic.get("routes") or []
                },
            },
        ),
        check(
            "every route exposes packet, submission, and approval command gates",
            all(
                (
                    (
                        row.get("id") == "ppmi_verily"
                        and "scripts/validate_ppmi_verily_completed_packet.py"
                        in (row.get("commands") or {}).get("validate_completed_packet", "")
                        and "scripts/validate_ppmi_verily_submission_email.py"
                        in (row.get("commands") or {}).get("validate_completed_email", "")
                        and "scripts/validate_ppmi_verily_submission_package.py"
                        in (row.get("commands") or {}).get("validate_completed_package", "")
                    )
                    or (
                        row.get("id") != "ppmi_verily"
                        and "scripts/validate_access_request_packet.py"
                        in (row.get("commands") or {}).get("validate_completed_packet", "")
                        and f"--route-id {row.get('id')}"
                        in (row.get("commands") or {}).get("validate_completed_packet", "")
                        and (row.get("commands") or {}).get("validate_completed_email") is None
                        and (row.get("commands") or {}).get("validate_completed_package") is None
                    )
                )
                and "scripts/record_access_submission.py"
                in (row.get("commands") or {}).get("record_submission_metadata", "")
                and f"--route-id {row.get('id')}"
                in (row.get("commands") or {}).get("record_submission_metadata", "")
                and "--pre-submission-preflight-passed"
                in (row.get("commands") or {}).get("record_submission_metadata", "")
                and "scripts/record_access_approval.py"
                in (row.get("commands") or {}).get("record_approval_metadata", "")
                and f"--route-id {row.get('id')}"
                in (row.get("commands") or {}).get("record_approval_metadata", "")
                for row in default_routes
            ),
            {
                "commands_by_route": {
                    row.get("id"): {
                        "packet": (row.get("commands") or {}).get("validate_completed_packet"),
                        "email": (row.get("commands") or {}).get("validate_completed_email"),
                        "package": (row.get("commands") or {}).get("validate_completed_package"),
                        "submission": (row.get("commands") or {}).get("record_submission_metadata"),
                        "approval": (row.get("commands") or {}).get("record_approval_metadata"),
                    }
                    for row in default_routes
                }
            },
        ),
        check(
            "PPMI route exposes PPMI-specific post-approval validators",
            "scripts/validate_ppmi_verily_schema_probe_report.py"
            in (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "validate_schema_probe_report", ""
            )
            and "scripts/validate_ppmi_verily_target_free_manifest.py"
            in (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "validate_target_free_manifest", ""
            )
            and "--route-id ppmi_verily"
            not in (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "validate_schema_probe_report", ""
            )
            and "--route-id ppmi_verily"
            not in (default_routes_by_id.get("ppmi_verily", {}).get("commands") or {}).get(
                "validate_target_free_manifest", ""
            ),
            {"ppmi_verily": default_routes_by_id.get("ppmi_verily")},
        ),
        check(
            "every route exposes schema, manifest, formula, and result validators",
            all(
                (
                    (
                        row.get("id") == "ppmi_verily"
                        and "scripts/validate_ppmi_verily_schema_probe_report.py"
                        in (row.get("commands") or {}).get("validate_schema_probe_report", "")
                        and "--route-id ppmi_verily"
                        not in (row.get("commands") or {}).get("validate_schema_probe_report", "")
                        and "scripts/validate_ppmi_verily_target_free_manifest.py"
                        in (row.get("commands") or {}).get("validate_target_free_manifest", "")
                    )
                    or (
                        row.get("id") != "ppmi_verily"
                        and "scripts/validate_schema_probe_report.py"
                        in (row.get("commands") or {}).get("validate_schema_probe_report", "")
                        and f"--route-id {row.get('id')}"
                        in (row.get("commands") or {}).get("validate_schema_probe_report", "")
                        and "scripts/validate_target_free_manifest.py"
                        in (row.get("commands") or {}).get("validate_target_free_manifest", "")
                        and f"--route-id {row.get('id')}"
                        in (row.get("commands") or {}).get("validate_target_free_manifest", "")
                    )
                )
                and "scripts/validate_external_formula_sha_record.py"
                in (row.get("commands") or {}).get("validate_formula_sha_record", "")
                and f"--route-id {row.get('id')}"
                in (row.get("commands") or {}).get("validate_formula_sha_record", "")
                and "scripts/validate_external_zeroshot_result_record.py"
                in (row.get("commands") or {}).get("validate_zeroshot_result_record", "")
                and f"--route-id {row.get('id')}"
                in (row.get("commands") or {}).get("validate_zeroshot_result_record", "")
                for row in default_routes
            ),
            {
                "commands_by_route": {
                    row.get("id"): {
                        "schema_report": (row.get("commands") or {}).get("validate_schema_probe_report"),
                        "target_free": (row.get("commands") or {}).get("validate_target_free_manifest"),
                        "formula_sha": (row.get("commands") or {}).get("validate_formula_sha_record"),
                        "zeroshot_result": (row.get("commands") or {}).get("validate_zeroshot_result_record"),
                    }
                    for row in default_routes
                }
            },
        ),
        check(
            "synthetic submitted route waits for approval with compute blocked",
            synthetic_json["returncode"] == 0
            and synthetic_routes.get("ppp_pd_vme", {}).get("lifecycle_state")
            == "submitted_pending_approval"
            and synthetic_routes.get("ppp_pd_vme", {}).get("action")
            == "wait_for_access_approval"
            and synthetic_routes.get("ppp_pd_vme", {}).get("safe_to_execute_code") is False
            and "model run"
            in synthetic_routes.get("ppp_pd_vme", {}).get("blocked_actions_now", []),
            {"ppp_pd_vme": synthetic_routes.get("ppp_pd_vme")},
        ),
        check(
            "synthetic approved route permits only read-only schema probe",
            synthetic_routes.get("watchpd", {}).get("lifecycle_state")
            == "approved_for_schema_probe"
            and synthetic_routes.get("watchpd", {}).get("action")
            == "run_read_only_schema_probe"
            and synthetic_routes.get("watchpd", {}).get("safe_to_execute_code") is True
            and synthetic_routes.get("watchpd", {}).get("allowed_now")
            == ["read-only schema probe"]
            and synthetic_routes.get("watchpd", {}).get("blocked_actions_now")
            == [
                "download script",
                "cache extraction",
                "pre-registration using new labels",
                "remote job",
                "model run",
                "canonical T1/T3 claim update",
            ],
            {"watchpd": synthetic_routes.get("watchpd")},
        ),
        check(
            "synthetic approved PPMI route recommends PPMI-specific schema preflight",
            synthetic_routes.get("ppmi_verily", {}).get("lifecycle_state")
            == "approved_for_schema_probe"
            and synthetic_routes.get("ppmi_verily", {}).get("action")
            == "run_read_only_schema_probe"
            and synthetic_routes.get("ppmi_verily", {}).get("safe_to_execute_code") is True
            and (synthetic_routes.get("ppmi_verily", {}).get("commands") or {}).get("recommended_next")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            ),
            {"ppmi_verily": synthetic_routes.get("ppmi_verily")},
        ),
        check(
            "synthetic schema-probe-recorded route blocks modeling",
            synthetic_routes.get("cns_portugal_lobo", {}).get("lifecycle_state")
            == "schema_probe_recorded"
            and synthetic_routes.get("cns_portugal_lobo", {}).get("action")
            == "review_schema_probe_gates"
            and synthetic_routes.get("cns_portugal_lobo", {}).get("safe_to_execute_code") is False
            and synthetic_routes.get("cns_portugal_lobo", {}).get("has_schema_probe_record") is True
            and "model run"
            in synthetic_routes.get("cns_portugal_lobo", {}).get("blocked_actions_now", []),
            {"cns_portugal_lobo": synthetic_routes.get("cns_portugal_lobo")},
        ),
        check(
            "schema probe record without approval fails closed",
            bad_schema_json["returncode"] == 0
            and bad_routes.get("hssayeni_mjff", {}).get("lifecycle_state") == "invalid"
            and bad_routes.get("hssayeni_mjff", {}).get("action") == "fix_access_evidence"
            and bad_routes.get("hssayeni_mjff", {}).get("safe_to_execute_code") is False
            and "schema-probe record exists without approval metadata"
            in bad_routes.get("hssayeni_mjff", {}).get("errors", []),
            {"hssayeni_mjff": bad_routes.get("hssayeni_mjff")},
        ),
        check(
            "content boundary blocks private artifacts",
            boundary.get("completed_packets_included") is False
            and boundary.get("completed_emails_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("record_paths_reported") is False
            and boundary.get("credentials_or_tokens_included") is False,
            {"content_boundary": boundary},
        ),
        check(
            "status output redacts local record identities and private snippets",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_access_lifecycle_status.py",
        "status_helper": "scripts/show_external_access_lifecycle.py",
        "source_tracker": "results/access_submission_tracker_20260509.json",
        "passed": not hard_failures,
        "decision": (
            "external_access_lifecycle_status_ready"
            if not hard_failures
            else "external_access_lifecycle_status_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
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
