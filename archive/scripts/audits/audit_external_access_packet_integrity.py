#!/usr/bin/env python3
"""Verify the external-data access packet chain for the architecture objective.

This audit is intentionally operational, not statistical. The local WearGait-only
model search is closed by prior screen artifacts; the next model-architecture
lever is approved external wearable-UPDRS data. This script verifies that the
access packets and route plan are current, submit-ready after user fill, and
still blocked from protected-data compute until approval and schema inspection.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import AccessPacketQueue, REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "external_access_packet_integrity_audit_20260510.json"
OUT_MD = RESULTS / "external_access_packet_integrity_audit_20260510.md"

EXPECTED_ROUTE_IDS = (
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
)

EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT = 19
EXPECTED_PPMI_PACKET_FIELD_COUNT = 13
EXPECTED_PPMI_EMAIL_FIELD_COUNT = 12
EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT = 4

AUDIT_COMMANDS = (
    ("ppmi_verily_packet", "audit_ppmi_verily_request_packet.py"),
    ("ppmi_verily_submit_format", "audit_ppmi_verily_submit_format.py"),
    ("ppmi_verily_submission_email", "audit_ppmi_verily_submission_email_template.py"),
    ("ppmi_verily_submission_email_validator", "audit_ppmi_verily_submission_email_validator.py"),
    ("ppmi_verily_submission_package_validator", "audit_ppmi_verily_submission_package_validator.py"),
    ("ppmi_verily_user_fill_checklist", "audit_ppmi_verily_user_fill_checklist.py"),
    ("ppmi_verily_schema_probe_report_template", "audit_ppmi_verily_schema_probe_report_template.py"),
    ("ppmi_verily_completed_packet_validator", "audit_ppmi_verily_completed_packet_validator.py"),
    ("ppmi_verily_submission_bundle", "audit_ppmi_verily_submission_bundle.py"),
    ("ppp_pd_vme_packet", "audit_ppp_pd_vme_request_packet.py"),
    ("watchpd_packet", "audit_watchpd_request_packet.py"),
    ("cns_portugal_packet", "audit_cns_portugal_request_packet.py"),
    ("hssayeni_mjff_packet", "audit_hssayeni_mjff_dua_request_packet.py"),
    ("icicle_packet", "audit_icicle_request_packet.py"),
    ("external_access_readiness", "audit_external_access_readiness.py"),
    ("access_submission_tracker", "audit_access_submission_tracker.py"),
    ("external_architecture_route_plan", "audit_external_architecture_route_plan.py"),
)


def run_cmd(script: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["uv", "run", "python", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=180,
    )
    return {
        "script": script,
        "returncode": proc.returncode,
        "output_tail": proc.stdout[-4000:],
    }


def load_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def path_has_text(path: str, needles: tuple[str, ...]) -> tuple[bool, list[str]]:
    text = (ROOT / path).read_text(encoding="utf-8", errors="replace").lower()
    missing = [needle for needle in needles if needle.lower() not in text]
    return not missing, missing


def route_ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("id")) for row in rows]


def main() -> None:
    RESULTS.mkdir(exist_ok=True)

    command_results = {name: run_cmd(script) for name, script in AUDIT_COMMANDS}

    tracker = load_json("results/access_submission_tracker_20260509.json")
    readiness = load_json("results/external_access_readiness_audit_20260509.json")
    route_plan = load_json("results/external_architecture_route_plan_20260510.json")
    ppmi_submit_format = load_json("results/ppmi_verily_submit_format_audit_20260515.json")
    ppmi_email_template = load_json("results/ppmi_verily_submission_email_template_audit_20260515.json")
    ppmi_email_validator = load_json("results/ppmi_verily_submission_email_validator_audit_20260515.json")
    ppmi_package_validator = load_json("results/ppmi_verily_submission_package_validator_audit_20260515.json")
    ppmi_user_fill_checklist = load_json("results/ppmi_verily_user_fill_checklist_audit_20260515.json")
    ppmi_schema_probe_template = load_json("results/ppmi_verily_schema_probe_report_template_audit_20260515.json")
    ppmi_completed_packet_validator = load_json("results/ppmi_verily_completed_packet_validator_audit_20260515.json")
    ppmi_submission_bundle = load_json("results/ppmi_verily_submission_bundle_20260515.json")

    hard_failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for name, result in command_results.items():
        if result["returncode"] != 0:
            hard_failures.append(
                {
                    "check": "sub_audit_command",
                    "name": name,
                    "script": result["script"],
                    "returncode": result["returncode"],
                }
            )

    tracker_summary = tracker.get("summary", {})
    readiness_summary = readiness.get("summary", {})

    if tracker.get("decision") != "access_submission_tracker_ready":
        hard_failures.append({"check": "tracker_decision", "value": tracker.get("decision")})
    if tracker_summary.get("submit_ready_route_count") != 6:
        hard_failures.append(
            {"check": "tracker_submit_ready_route_count", "value": tracker_summary.get("submit_ready_route_count")}
        )
    if tracker_summary.get("compute_ready_route_count") != 0:
        hard_failures.append(
            {"check": "tracker_compute_ready_route_count", "value": tracker_summary.get("compute_ready_route_count")}
        )
    if tracker_summary.get("top_priority_route") != "PPMI / Verily Study Watch":
        hard_failures.append({"check": "tracker_top_priority", "value": tracker_summary.get("top_priority_route")})
    if ppmi_submit_format.get("passed") is not True:
        hard_failures.append({"check": "ppmi_submit_format_passed", "value": ppmi_submit_format.get("passed")})
    if ppmi_submit_format.get("decision") != "ppmi_verily_word_template_ready_to_fill":
        hard_failures.append({"check": "ppmi_submit_format_decision", "value": ppmi_submit_format.get("decision")})
    if ppmi_submit_format.get("output_docx") != "results/ppmi_verily_tier3_request_packet_template_20260515.docx":
        hard_failures.append({"check": "ppmi_submit_format_docx", "value": ppmi_submit_format.get("output_docx")})
    if ppmi_email_template.get("passed") is not True:
        hard_failures.append({"check": "ppmi_email_template_passed", "value": ppmi_email_template.get("passed")})
    if ppmi_email_template.get("decision") != "ppmi_verily_submission_email_template_ready":
        hard_failures.append({"check": "ppmi_email_template_decision", "value": ppmi_email_template.get("decision")})
    if ppmi_email_validator.get("passed") is not True:
        hard_failures.append({"check": "ppmi_email_validator_passed", "value": ppmi_email_validator.get("passed")})
    if ppmi_email_validator.get("decision") != "ppmi_verily_submission_email_validator_ready":
        hard_failures.append({"check": "ppmi_email_validator_decision", "value": ppmi_email_validator.get("decision")})
    if ppmi_email_validator.get("validator") != "scripts/validate_ppmi_verily_submission_email.py":
        hard_failures.append({"check": "ppmi_email_validator_path", "value": ppmi_email_validator.get("validator")})
    if not any(
        row.get("name") == "validator output does not echo completed email path or filename"
        and row.get("passed") is True
        for row in ppmi_email_validator.get("checks", [])
    ):
        hard_failures.append({"check": "ppmi_email_validator_redaction", "value": False})
    if ppmi_package_validator.get("passed") is not True:
        hard_failures.append({"check": "ppmi_package_validator_passed", "value": ppmi_package_validator.get("passed")})
    if ppmi_package_validator.get("decision") != "ppmi_verily_submission_package_validator_ready":
        hard_failures.append({"check": "ppmi_package_validator_decision", "value": ppmi_package_validator.get("decision")})
    if ppmi_package_validator.get("validator") != "scripts/validate_ppmi_verily_submission_package.py":
        hard_failures.append({"check": "ppmi_package_validator_path", "value": ppmi_package_validator.get("validator")})
    if not (
        ppmi_package_validator.get("not_a_submission_record") is True
        and ppmi_package_validator.get("not_access_approval") is True
        and ppmi_package_validator.get("not_a_model_result") is True
        and ppmi_package_validator.get("protected_data_included") is False
        and ppmi_package_validator.get("credentials_or_tokens_included") is False
    ):
        hard_failures.append({"check": "ppmi_package_validator_boundary", "value": False})
    if not any(
        row.get("name") == "validator output does not echo package paths or filenames"
        and row.get("passed") is True
        for row in ppmi_package_validator.get("checks", [])
    ):
        hard_failures.append({"check": "ppmi_package_validator_redaction", "value": False})
    if ppmi_user_fill_checklist.get("passed") is not True:
        hard_failures.append(
            {"check": "ppmi_user_fill_checklist_passed", "value": ppmi_user_fill_checklist.get("passed")}
        )
    if ppmi_user_fill_checklist.get("decision") != "ppmi_verily_user_fill_checklist_ready":
        hard_failures.append(
            {"check": "ppmi_user_fill_checklist_decision", "value": ppmi_user_fill_checklist.get("decision")}
        )
    if ppmi_user_fill_checklist.get("checklist") != "scripts/ppmi_verily_user_fill_checklist.md":
        hard_failures.append(
            {"check": "ppmi_user_fill_checklist_path", "value": ppmi_user_fill_checklist.get("checklist")}
        )
    if ppmi_user_fill_checklist.get("required_placeholder_count") != EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT:
        hard_failures.append(
            {
                "check": "ppmi_user_fill_checklist_top_level_placeholder_count",
                "value": ppmi_user_fill_checklist.get("required_placeholder_count"),
            }
        )
    if len(ppmi_user_fill_checklist.get("required_placeholders", [])) != EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT:
        hard_failures.append(
            {
                "check": "ppmi_user_fill_checklist_placeholder_list_count",
                "value": len(ppmi_user_fill_checklist.get("required_placeholders", [])),
            }
        )
    if len(ppmi_user_fill_checklist.get("packet_fields", [])) != EXPECTED_PPMI_PACKET_FIELD_COUNT:
        hard_failures.append(
            {
                "check": "ppmi_user_fill_checklist_packet_field_list_count",
                "value": len(ppmi_user_fill_checklist.get("packet_fields", [])),
            }
        )
    if len(ppmi_user_fill_checklist.get("email_fields", [])) != EXPECTED_PPMI_EMAIL_FIELD_COUNT:
        hard_failures.append(
            {
                "check": "ppmi_user_fill_checklist_email_field_list_count",
                "value": len(ppmi_user_fill_checklist.get("email_fields", [])),
            }
        )
    if ppmi_user_fill_checklist.get("packet_field_count") != EXPECTED_PPMI_PACKET_FIELD_COUNT:
        hard_failures.append(
            {
                "check": "ppmi_user_fill_checklist_packet_field_count",
                "value": ppmi_user_fill_checklist.get("packet_field_count"),
            }
        )
    if ppmi_user_fill_checklist.get("email_field_count") != EXPECTED_PPMI_EMAIL_FIELD_COUNT:
        hard_failures.append(
            {
                "check": "ppmi_user_fill_checklist_email_field_count",
                "value": ppmi_user_fill_checklist.get("email_field_count"),
            }
        )
    if (
        ppmi_user_fill_checklist.get("submission_metadata_field_count")
        != EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
    ):
        hard_failures.append(
            {
                "check": "ppmi_user_fill_checklist_submission_metadata_field_count",
                "value": ppmi_user_fill_checklist.get("submission_metadata_field_count"),
            }
        )
    if ppmi_schema_probe_template.get("passed") is not True:
        hard_failures.append(
            {"check": "ppmi_schema_probe_report_template_passed", "value": ppmi_schema_probe_template.get("passed")}
        )
    if ppmi_schema_probe_template.get("decision") != "ppmi_verily_schema_probe_report_template_ready":
        hard_failures.append(
            {
                "check": "ppmi_schema_probe_report_template_decision",
                "value": ppmi_schema_probe_template.get("decision"),
            }
        )
    if ppmi_schema_probe_template.get("template") != "scripts/ppmi_verily_schema_probe_report_template.md":
        hard_failures.append(
            {
                "check": "ppmi_schema_probe_report_template_path",
                "value": ppmi_schema_probe_template.get("template"),
            }
        )
    if (
        ppmi_schema_probe_template.get("schema_probe_artifact_created") is not False
        or ppmi_schema_probe_template.get("protected_data_included") is not False
    ):
        hard_failures.append({"check": "ppmi_schema_probe_report_template_content_free", "value": False})
    if ppmi_completed_packet_validator.get("passed") is not True:
        hard_failures.append(
            {
                "check": "ppmi_completed_packet_validator_passed",
                "value": ppmi_completed_packet_validator.get("passed"),
            }
        )
    if ppmi_completed_packet_validator.get("decision") != "ppmi_verily_completed_packet_validator_ready":
        hard_failures.append(
            {
                "check": "ppmi_completed_packet_validator_decision",
                "value": ppmi_completed_packet_validator.get("decision"),
            }
        )
    if not any(
        row.get("name") == "validator output does not echo completed packet path or filename"
        and row.get("passed") is True
        for row in ppmi_completed_packet_validator.get("checks", [])
    ):
        hard_failures.append({"check": "ppmi_completed_packet_validator_redaction", "value": False})
    if ppmi_submission_bundle.get("passed") is not True:
        hard_failures.append({"check": "ppmi_submission_bundle_passed", "value": ppmi_submission_bundle.get("passed")})
    if ppmi_submission_bundle.get("decision") != "ppmi_verily_submission_bundle_ready":
        hard_failures.append(
            {"check": "ppmi_submission_bundle_decision", "value": ppmi_submission_bundle.get("decision")}
        )
    if ppmi_submission_bundle.get("completed_packet_included") is not False:
        hard_failures.append(
            {
                "check": "ppmi_submission_bundle_completed_packet_boundary",
                "value": ppmi_submission_bundle.get("completed_packet_included"),
            }
        )

    if readiness.get("decision") != "access_packets_ready_no_compute":
        hard_failures.append({"check": "readiness_decision", "value": readiness.get("decision")})
    if readiness_summary.get("application_packet_ready_count", 0) < 6:
        hard_failures.append(
            {
                "check": "readiness_application_packet_ready_count",
                "value": readiness_summary.get("application_packet_ready_count"),
            }
        )
    if readiness_summary.get("compute_ready_route_count") != 0:
        hard_failures.append(
            {"check": "readiness_compute_ready_route_count", "value": readiness_summary.get("compute_ready_route_count")}
        )

    if route_plan.get("passed") is not True:
        hard_failures.append({"check": "route_plan_passed", "value": route_plan.get("passed")})
    if route_plan.get("decision") != "external_architecture_routes_blocked_until_access":
        hard_failures.append({"check": "route_plan_decision", "value": route_plan.get("decision")})
    if route_plan.get("compute_ready_route_count") != 0:
        hard_failures.append(
            {"check": "route_plan_compute_ready_route_count", "value": route_plan.get("compute_ready_route_count")}
        )
    if route_plan.get("access_request_route_count") != 6:
        hard_failures.append(
            {"check": "route_plan_access_request_route_count", "value": route_plan.get("access_request_route_count")}
        )
    if route_plan.get("ppmi_submission_support_ready") is not True:
        hard_failures.append(
            {
                "check": "route_plan_ppmi_submission_support_ready",
                "value": route_plan.get("ppmi_submission_support_ready"),
            }
        )

    tracker_routes = tracker.get("routes", [])
    access_queue = AccessPacketQueue.from_tracker_rows(tracker_routes[:6])
    queue_errors = access_queue.validation_errors(expected_route_ids=EXPECTED_ROUTE_IDS)
    for error in queue_errors:
        hard_failures.append({"check": "access_packet_queue_contract", "error": error})

    for row in tracker_routes[:6]:
        route_id = str(row.get("id"))
        packet = row.get("packet", {})

        packet_path = packet.get("path")
        if packet_path:
            ok, missing_terms = path_has_text(
                str(packet_path),
                (
                    "ready-to-fill template",
                    "do not commit",
                    "read-only schema probe",
                    "internal weargait-pd canonical",
                ),
            )
            if not ok:
                hard_failures.append(
                    {
                        "route": route_id,
                        "check": "packet_missing_common_boundary_terms",
                        "path": packet_path,
                        "missing_terms": missing_terms,
                    }
                )

    for row in route_plan.get("routes", []):
        route_id = str(row.get("id"))
        blocked = set(row.get("blocked_actions_now", []))
        if row.get("compute_ready"):
            hard_failures.append({"route": route_id, "check": "route_plan_compute_ready"})
        if row.get("can_probe_schema") or row.get("can_preregister"):
            hard_failures.append(
                {
                    "route": route_id,
                    "check": "route_plan_pre_access_probe_or_prereg_allowed",
                    "can_probe_schema": row.get("can_probe_schema"),
                    "can_preregister": row.get("can_preregister"),
                }
            )
        missing_blocked = sorted(set(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS) - blocked)
        if missing_blocked:
            hard_failures.append({"route": route_id, "check": "route_plan_missing_blocked_actions", "missing": missing_blocked})

    if readiness.get("provenance_recovery", {}).get("remote_job_allowed_now"):
        hard_failures.append({"check": "weargait_raw_recovery_remote_job_allowed"})
    if readiness.get("provenance_recovery", {}).get("readiness_class") != "raw_data_recovery_credentials_needed":
        warnings.append(
            {
                "check": "weargait_raw_recovery_readiness_class",
                "value": readiness.get("provenance_recovery", {}).get("readiness_class"),
            }
        )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_access_packet_integrity.py",
        "objective_link": "External-data-first model architecture path remains the next valid lever after local WearGait-only screens failed.",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "external_access_packets_integrity_passed_no_compute"
        if not hard_failures
        else "external_access_packets_integrity_failed",
        "expected_route_ids": list(EXPECTED_ROUTE_IDS),
        "sub_audits": command_results,
        "summary": {
            "submit_ready_route_count": tracker_summary.get("submit_ready_route_count"),
            "application_packet_ready_count": readiness_summary.get("application_packet_ready_count"),
            "access_request_route_count": route_plan.get("access_request_route_count"),
            "compute_ready_route_count": route_plan.get("compute_ready_route_count"),
            "top_priority_route": route_plan.get("top_priority_route"),
            "route_plan_ppmi_submission_support_ready": route_plan.get("ppmi_submission_support_ready"),
            "ppmi_word_template": ppmi_submit_format.get("output_docx"),
            "ppmi_submission_email_template": ppmi_email_template.get("template"),
            "ppmi_submission_email_validator": ppmi_email_validator.get("validator"),
            "ppmi_submission_package_validator": ppmi_package_validator.get("validator"),
            "ppmi_user_fill_checklist": ppmi_user_fill_checklist.get("checklist"),
            "ppmi_schema_probe_report_template": ppmi_schema_probe_template.get("template"),
            "ppmi_completed_packet_validator": ppmi_completed_packet_validator.get("validator"),
            "ppmi_submission_bundle": "results/ppmi_verily_submission_bundle_20260515.json",
            "hard_failure_count": len(hard_failures),
            "warning_count": len(warnings),
        },
        "hard_failures": hard_failures,
        "warnings": warnings,
        "next_valid_action": "Fill and submit the PPMI / Verily packet through the data-owner workflow; after approval, run a read-only schema probe before any preregistration or model run.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Access Packet Integrity Audit - 2026-05-10",
        "",
        "This is an operational architecture-readiness audit, not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Submit-ready routes: `{report['summary']['submit_ready_route_count']}`",
        f"- Compute-ready routes: `{report['summary']['compute_ready_route_count']}`",
        f"- Top priority route: `{report['summary']['top_priority_route']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Sub-Audits",
        "",
        "| Audit | Script | Return code |",
        "|---|---|---:|",
    ]
    for name, result in command_results.items():
        lines.append(f"| `{name}` | `{result['script']}` | `{result['returncode']}` |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            report["next_valid_action"],
            "",
            "Protected-data probes, downloads, cache extraction, preregistrations using new labels, remote jobs, model runs, and canonical claim updates remain blocked.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failures": len(hard_failures),
                "compute_ready_route_count": report["summary"]["compute_ready_route_count"],
                "submit_ready_route_count": report["summary"]["submit_ready_route_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
