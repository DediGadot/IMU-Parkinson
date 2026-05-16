#!/usr/bin/env python3
"""Audit gated external-data routes for access readiness.

This is an operational readiness audit, not a modeling result. It turns the
remaining external-data blockers into an ordered access queue and fails if any
high-priority direct T1/T3 route is missing a runbook, stop condition, or
no-scaffold boundary.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SOURCE_JSON = RESULTS / "external_dataset_route_audit_20260508.json"
BLOCKER_JSON = RESULTS / "remaining_blocker_action_audit_20260509.json"
RECOVERY_JSON = RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.json"
RAW_RECOVERY_RUNBOOK = ROOT / "scripts" / "weargait_raw_data_recovery_runbook.md"
RAW_RECOVERY_RUNBOOK_AUDIT = RESULTS / "weargait_raw_data_recovery_runbook_audit_20260509.json"
PPMI_SUBMIT_FORMAT_JSON = RESULTS / "ppmi_verily_submit_format_audit_20260515.json"
PPMI_EMAIL_TEMPLATE_JSON = RESULTS / "ppmi_verily_submission_email_template_audit_20260515.json"
PPMI_USER_FILL_CHECKLIST_JSON = RESULTS / "ppmi_verily_user_fill_checklist_audit_20260515.json"
PPMI_SCHEMA_PROBE_CHECKLIST_JSON = RESULTS / "ppmi_verily_schema_probe_checklist_audit_20260515.json"
PPMI_SCHEMA_PROBE_TEMPLATE_JSON = RESULTS / "ppmi_verily_schema_probe_report_template_audit_20260515.json"
PPMI_COMPLETED_PACKET_VALIDATOR_JSON = RESULTS / "ppmi_verily_completed_packet_validator_audit_20260515.json"
PPMI_COMPLETED_EMAIL_VALIDATOR_JSON = RESULTS / "ppmi_verily_submission_email_validator_audit_20260515.json"
PPMI_COMPLETED_PACKAGE_VALIDATOR_JSON = RESULTS / "ppmi_verily_submission_package_validator_audit_20260515.json"
PPMI_SUBMISSION_BUNDLE_JSON = RESULTS / "ppmi_verily_submission_bundle_20260515.json"
OUT_JSON = RESULTS / "external_access_readiness_audit_20260509.json"
OUT_MD = RESULTS / "external_access_readiness_audit_20260509.md"

EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT = 19
EXPECTED_PPMI_PACKET_FIELD_COUNT = 13
EXPECTED_PPMI_EMAIL_FIELD_COUNT = 12
EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT = 4


ROUTES: list[dict[str, Any]] = [
    {
        "id": "ppmi_verily",
        "name": "PPMI / Verily Study Watch",
        "priority": 1,
        "readiness_class": "application_packet_ready_after_user_dua",
        "runbook": "scripts/ppmi_verily_setup.md",
        "access_blocker": "PPMI qualified-researcher account, DUA, online application, and DPC approval.",
        "why": "Largest priority wrist-native Verily route with clinical/sensor data and MDS-UPDRS III/H&Y.",
        "first_allowed_action_after_access": "Read-only schema probe; no pre-registration until subject/visit/sensor/label fields are known.",
        "request_packet": "scripts/ppmi_verily_tier3_request_packet.md",
        "request_packet_audit": "results/ppmi_verily_request_packet_audit_20260509.json",
        "direct_required": True,
        "action_packet_ready_expected": True,
    },
    {
        "id": "ppp_pd_vme",
        "name": "Personalized Parkinson Project / PD Virtual Motor Exam",
        "priority": 2,
        "readiness_class": "request_packet_ready_after_rdsrc",
        "runbook": "scripts/ppp_pd_vme_request_setup.md",
        "access_blocker": "PPP RDSRC/request approval, Qualified Researcher Agreement, fees, and PEP repository access.",
        "why": "Strong Verily Study Watch peer route with PD-VME active tasks and MDS-UPDRS Part III/subitem labels.",
        "first_allowed_action_after_access": "Read-only schema probe; no loader until raw/exportable sensor and label linkage is visible.",
        "request_packet": "scripts/ppp_pd_vme_request_packet.md",
        "request_packet_audit": "results/ppp_pd_vme_request_packet_audit_20260509.json",
        "direct_required": True,
        "action_packet_ready_expected": True,
    },
    {
        "id": "watchpd",
        "name": "WATCH-PD",
        "priority": 3,
        "readiness_class": "proposal_packet_ready_after_cpath_or_steering_committee",
        "runbook": "scripts/watchpd_request_setup.md",
        "access_blocker": "C-Path 3DT Stage 2 membership or accepted WATCH-PD Steering Committee proposal.",
        "why": "Protocol-relevant route: APDM sensors during MDS-UPDRS Part III plus Apple Watch/iPhone longitudinal data.",
        "first_allowed_action_after_access": "Read-only APDM/Apple/iPhone schema probe with subject and visit linkage checks.",
        "request_packet": "scripts/watchpd_request_packet.md",
        "request_packet_audit": "results/watchpd_request_packet_audit_20260509.json",
        "direct_required": True,
        "action_packet_ready_expected": True,
    },
    {
        "id": "cns_portugal_lobo",
        "name": "CNS Portugal / Lobo IS2022 AX3 gait",
        "priority": 4,
        "readiness_class": "author_request_packet_ready_after_data_owner_approval",
        "runbook": "scripts/cns_portugal_request_setup.md",
        "access_blocker": "Author/CNS data-owner approval and row-level AX3 plus Part III schema.",
        "why": "Structured 10-meter walk route with wrist and lower-back AX3 plus direct MDS-UPDRS Part III.",
        "first_allowed_action_after_access": "Read-only schema probe; require subject/session-grouped validation only.",
        "request_packet": "scripts/cns_portugal_request_packet.md",
        "request_packet_audit": "results/cns_portugal_request_packet_audit_20260509.json",
        "direct_required": True,
        "action_packet_ready_expected": True,
    },
    {
        "id": "hssayeni_mjff",
        "name": "MJFF Levodopa Response / Hssayeni",
        "priority": 5,
        "readiness_class": "synapse_dua_packet_ready_after_approval",
        "runbook": "scripts/synapse_hssayeni_setup.md",
        "access_blocker": "Synapse DUA/READ approval for syn20681023.",
        "why": "Small but direct MJFF wearable-UPDRS route; existing iter26 scaffold remains DUA-blocked.",
        "first_allowed_action_after_access": "Read-only Synapse child-tree and schema probe before any cache/model run.",
        "request_packet": "scripts/hssayeni_mjff_dua_request_packet.md",
        "request_packet_audit": "results/hssayeni_mjff_dua_request_packet_audit_20260509.json",
        "direct_required": True,
        "action_packet_ready_expected": True,
    },
    {
        "id": "icicle_gait",
        "name": "ICICLE-PD / ICICLE-GAIT",
        "priority": 6,
        "readiness_class": "request_packet_ready_after_newcastle_approval",
        "runbook": "scripts/icicle_request_setup.md",
        "access_blocker": "Newcastle/data-owner request approval and lower-back AX3 plus MDS-UPDRS schema.",
        "why": "Longitudinal lower-back gait route with MDS-UPDRS Part III and H&Y; not wrist-native.",
        "first_allowed_action_after_access": "Read-only schema probe; freeze visit/day aggregation before modeling.",
        "request_packet": "scripts/icicle_request_packet.md",
        "request_packet_audit": "results/icicle_request_packet_audit_20260509.json",
        "direct_required": True,
        "action_packet_ready_expected": True,
    },
    {
        "id": "mobilised_cvs",
        "name": "Mobilise-D TVS / CVS",
        "priority": 7,
        "readiness_class": "watch_release_schema_only",
        "runbook": None,
        "access_blocker": "CVS row-level wearable plus MDS-UPDRS release/access/schema is not visible; public TVS is not a clinical-inference target.",
        "why": "Plausible future lower-back longitudinal T3 row, but not compute-ready from current public TVS.",
        "first_allowed_action_after_access": "Monitor or request CVS row-level release; no scaffold until label and wearable schema exist.",
        "direct_required": False,
        "action_packet_ready_expected": False,
    },
    {
        "id": "fay_karmon",
        "name": "Advanced PD smartwatch home monitoring / Fay-Karmon 2024",
        "priority": 8,
        "readiness_class": "low_priority_author_request_only",
        "runbook": None,
        "access_blocker": "Corresponding-author request; proprietary/schema-hidden smartwatch route and N=21.",
        "why": "Potential T3 context only after data-owner approval; not an active application-ready route.",
        "first_allowed_action_after_access": "Schema review only; no WearGait comparison before raw/exportable sensors and labels are confirmed.",
        "direct_required": False,
        "action_packet_ready_expected": False,
    },
    {
        "id": "marital_dyad",
        "name": "Marital-dyad social actigraphy / Sensors 2023",
        "priority": 9,
        "readiness_class": "low_priority_author_request_only",
        "runbook": None,
        "access_blocker": "Author request; small daily-life/social-actigraphy schema-hidden route and no T1 endpoint.",
        "why": "Potential low-priority T3 context only, after stronger direct routes.",
        "first_allowed_action_after_access": "Schema review only; no scaffold before subject IDs, sensor windows, and Part III labels are visible.",
        "direct_required": False,
        "action_packet_ready_expected": False,
    },
]


RUNBOOK_REQUIRED_CHECKS = {
    "no_scaffold_boundary": ("do not", ("scaffold", "remote job", "download", "pre-registration", "preregistration")),
    "post_access_probe": ("probe", ("after access", "after approval", "post-approval", "read-only")),
    "subject_linkage": ("subject", ()),
    "part3_label": (("mds-updrs", "part iii", "updrs"), ()),
    "stop_conditions": ("stop", ()),
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def contains_any(text: str, choices: tuple[str, ...] | str) -> bool:
    if isinstance(choices, str):
        return choices in text
    return any(choice in text for choice in choices)


def find_route(routes: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for route in routes:
        if route.get("name") == name:
            return route
    return None


def runbook_status(path_str: str | None) -> dict[str, Any]:
    if path_str is None:
        return {
            "path": None,
            "exists": False,
            "passed": False,
            "checks": {},
            "missing_checks": ["runbook_not_required_or_not_configured"],
        }
    path = ROOT / path_str
    if not path.exists():
        return {
            "path": path_str,
            "exists": False,
            "passed": False,
            "checks": {},
            "missing_checks": ["missing_runbook_file"],
        }
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    checks: dict[str, bool] = {}
    for check, (must_have, any_of) in RUNBOOK_REQUIRED_CHECKS.items():
        passed = contains_any(text, must_have) and (not any_of or contains_any(text, any_of))
        checks[check] = passed
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "path": path_str,
        "exists": True,
        "passed": not missing,
        "checks": checks,
        "missing_checks": missing,
    }


def request_packet_status(path_str: str | None, audit_str: str | None) -> dict[str, Any]:
    if path_str is None:
        return {
            "path": None,
            "required": False,
            "exists": False,
            "audit": None,
            "audit_exists": False,
            "passed": True,
        }
    path = ROOT / path_str
    audit_path = ROOT / audit_str if audit_str else None
    audit_payload: dict[str, Any] = {}
    if audit_path and audit_path.exists():
        audit_payload = load_json(audit_path)
    return {
        "path": path_str,
        "required": True,
        "exists": path.exists(),
        "audit": audit_str,
        "audit_exists": bool(audit_path and audit_path.exists()),
        "audit_decision": audit_payload.get("decision"),
        "passed": path.exists() and bool(audit_payload.get("passed")),
    }


def ppmi_submission_support_status() -> dict[str, Any]:
    submit_format = load_json_optional(PPMI_SUBMIT_FORMAT_JSON)
    email_template = load_json_optional(PPMI_EMAIL_TEMPLATE_JSON)
    user_fill_checklist = load_json_optional(PPMI_USER_FILL_CHECKLIST_JSON)
    schema_probe_checklist = load_json_optional(PPMI_SCHEMA_PROBE_CHECKLIST_JSON)
    schema_probe_template = load_json_optional(PPMI_SCHEMA_PROBE_TEMPLATE_JSON)
    completed_validator = load_json_optional(PPMI_COMPLETED_PACKET_VALIDATOR_JSON)
    completed_email_validator = load_json_optional(PPMI_COMPLETED_EMAIL_VALIDATOR_JSON)
    completed_package_validator = load_json_optional(PPMI_COMPLETED_PACKAGE_VALIDATOR_JSON)
    submission_bundle = load_json_optional(PPMI_SUBMISSION_BUNDLE_JSON)

    checks = {
        "word_template": (
            submit_format.get("passed") is True
            and submit_format.get("decision") == "ppmi_verily_word_template_ready_to_fill"
            and submit_format.get("output_docx")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
        ),
        "submission_email": (
            email_template.get("passed") is True
            and email_template.get("decision") == "ppmi_verily_submission_email_template_ready"
            and email_template.get("template") == "scripts/ppmi_verily_submission_email_template.md"
        ),
        "user_fill_checklist": (
            user_fill_checklist.get("passed") is True
            and user_fill_checklist.get("decision") == "ppmi_verily_user_fill_checklist_ready"
            and user_fill_checklist.get("checklist") == "scripts/ppmi_verily_user_fill_checklist.md"
            and user_fill_checklist.get("required_placeholder_count")
            == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
            and user_fill_checklist.get("packet_field_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
            and user_fill_checklist.get("email_field_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
            and user_fill_checklist.get("submission_metadata_field_count")
            == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
            and len(user_fill_checklist.get("required_placeholders", []))
            == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
            and len(user_fill_checklist.get("packet_fields", [])) == EXPECTED_PPMI_PACKET_FIELD_COUNT
            and len(user_fill_checklist.get("email_fields", [])) == EXPECTED_PPMI_EMAIL_FIELD_COUNT
            and user_fill_checklist.get("submission_metadata_placeholders")
            == [
                "<ISO8601_UTC>",
                "<non_protected_channel>",
                "<non_protected_submitter>",
                "<non_protected_receipt>",
            ]
        ),
        "completed_packet_validator": (
            completed_validator.get("passed") is True
            and completed_validator.get("decision") == "ppmi_verily_completed_packet_validator_ready"
            and completed_validator.get("validator") == "scripts/validate_ppmi_verily_completed_packet.py"
        ),
        "completed_email_validator": (
            completed_email_validator.get("passed") is True
            and completed_email_validator.get("decision") == "ppmi_verily_submission_email_validator_ready"
            and completed_email_validator.get("validator") == "scripts/validate_ppmi_verily_submission_email.py"
        ),
        "completed_package_validator": (
            completed_package_validator.get("passed") is True
            and completed_package_validator.get("decision") == "ppmi_verily_submission_package_validator_ready"
            and completed_package_validator.get("validator") == "scripts/validate_ppmi_verily_submission_package.py"
            and completed_package_validator.get("not_a_submission_record") is True
            and completed_package_validator.get("not_access_approval") is True
            and completed_package_validator.get("not_a_model_result") is True
            and completed_package_validator.get("protected_data_included") is False
            and completed_package_validator.get("credentials_or_tokens_included") is False
        ),
        "schema_probe_checklist": (
            schema_probe_checklist.get("passed") is True
            and schema_probe_checklist.get("decision") == "ppmi_verily_schema_probe_checklist_ready"
            and schema_probe_checklist.get("checklist") == "scripts/ppmi_verily_schema_probe_checklist.md"
            and schema_probe_checklist.get("schema_probe_artifact_created") is False
            and schema_probe_checklist.get("protected_data_included") is False
        ),
        "schema_probe_report_template": (
            schema_probe_template.get("passed") is True
            and schema_probe_template.get("decision") == "ppmi_verily_schema_probe_report_template_ready"
            and schema_probe_template.get("template") == "scripts/ppmi_verily_schema_probe_report_template.md"
            and schema_probe_template.get("schema_probe_artifact_created") is False
            and schema_probe_template.get("protected_data_included") is False
        ),
        "submission_bundle": (
            submission_bundle.get("passed") is True
            and submission_bundle.get("decision") == "ppmi_verily_submission_bundle_ready"
            and submission_bundle.get("completed_packet_included") is False
            and submission_bundle.get("protected_data_included") is False
            and submission_bundle.get("credentials_or_tokens_included") is False
            and submission_bundle.get("audit_states", {}).get("user_fill_checklist_audit", {}).get("passed") is True
            and submission_bundle.get("audit_states", {})
            .get("user_fill_checklist_audit", {})
            .get("required_placeholder_count")
            == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
            and submission_bundle.get("audit_states", {})
            .get("user_fill_checklist_audit", {})
            .get("packet_field_count")
            == EXPECTED_PPMI_PACKET_FIELD_COUNT
            and submission_bundle.get("audit_states", {})
            .get("user_fill_checklist_audit", {})
            .get("email_field_count")
            == EXPECTED_PPMI_EMAIL_FIELD_COUNT
            and submission_bundle.get("audit_states", {})
            .get("user_fill_checklist_audit", {})
            .get("submission_metadata_field_count")
            == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
            and submission_bundle.get("audit_states", {}).get("completed_email_validator_audit", {}).get("passed")
            is True
            and submission_bundle.get("audit_states", {}).get("completed_package_validator_audit", {}).get("passed")
            is True
            and submission_bundle.get("audit_states", {}).get("schema_probe_checklist_audit", {}).get("passed") is True
            and submission_bundle.get("audit_states", {}).get("schema_probe_report_template_audit", {}).get("passed")
            is True
        ),
    }
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not missing,
        "checks": checks,
        "missing_checks": missing,
        "word_template": {
            "audit": str(PPMI_SUBMIT_FORMAT_JSON.relative_to(ROOT)),
            "path": submit_format.get("output_docx"),
            "decision": submit_format.get("decision"),
        },
        "submission_email": {
            "audit": str(PPMI_EMAIL_TEMPLATE_JSON.relative_to(ROOT)),
            "path": email_template.get("template"),
            "decision": email_template.get("decision"),
        },
        "user_fill_checklist": {
            "audit": str(PPMI_USER_FILL_CHECKLIST_JSON.relative_to(ROOT)),
            "path": user_fill_checklist.get("checklist"),
            "decision": user_fill_checklist.get("decision"),
            "required_placeholder_count": user_fill_checklist.get("required_placeholder_count"),
            "packet_field_count": user_fill_checklist.get("packet_field_count"),
            "email_field_count": user_fill_checklist.get("email_field_count"),
            "submission_metadata_field_count": user_fill_checklist.get("submission_metadata_field_count"),
            "required_placeholder_list_count": len(user_fill_checklist.get("required_placeholders", [])),
        },
        "completed_packet_validator": {
            "audit": str(PPMI_COMPLETED_PACKET_VALIDATOR_JSON.relative_to(ROOT)),
            "path": completed_validator.get("validator"),
            "decision": completed_validator.get("decision"),
        },
        "completed_email_validator": {
            "audit": str(PPMI_COMPLETED_EMAIL_VALIDATOR_JSON.relative_to(ROOT)),
            "path": completed_email_validator.get("validator"),
            "decision": completed_email_validator.get("decision"),
        },
        "completed_package_validator": {
            "audit": str(PPMI_COMPLETED_PACKAGE_VALIDATOR_JSON.relative_to(ROOT)),
            "path": completed_package_validator.get("validator"),
            "decision": completed_package_validator.get("decision"),
        },
        "schema_probe_checklist": {
            "audit": str(PPMI_SCHEMA_PROBE_CHECKLIST_JSON.relative_to(ROOT)),
            "path": schema_probe_checklist.get("checklist"),
            "decision": schema_probe_checklist.get("decision"),
        },
        "schema_probe_report_template": {
            "audit": str(PPMI_SCHEMA_PROBE_TEMPLATE_JSON.relative_to(ROOT)),
            "path": schema_probe_template.get("template"),
            "decision": schema_probe_template.get("decision"),
        },
        "submission_bundle": {
            "audit": str(PPMI_SUBMISSION_BUNDLE_JSON.relative_to(ROOT)),
            "decision": submission_bundle.get("decision"),
        },
    }


def source_list(route: dict[str, Any]) -> list[str]:
    sources = route.get("sources", route.get("source_urls", []))
    return [str(item) for item in sources if item]


def make_route_row(config: dict[str, Any], route: dict[str, Any] | None) -> dict[str, Any]:
    rb = runbook_status(config.get("runbook"))
    packet = request_packet_status(config.get("request_packet"), config.get("request_packet_audit"))
    submission_support = ppmi_submission_support_status() if config["id"] == "ppmi_verily" else None
    route_sources = source_list(route or {})
    direct_eligible = bool((route or {}).get("direct_t1_t3_eligible"))
    status = str((route or {}).get("status") or (route or {}).get("access_status") or "")
    route_runbook = (route or {}).get("access_runbook")
    runbook_matches_json = (
        config.get("runbook") is None
        or route_runbook == config.get("runbook")
        or config.get("runbook") in route_sources
    )
    current_allowed_action = (
        "access_request_only"
        if config["action_packet_ready_expected"]
        else "monitor_or_document_only"
    )
    action_packet_ready = bool(
        config["action_packet_ready_expected"]
        and rb["passed"]
        and runbook_matches_json
        and packet["passed"]
        and (submission_support is None or submission_support["passed"])
    )
    return {
        "id": config["id"],
        "name": config["name"],
        "priority": config["priority"],
        "route_present": route is not None,
        "readiness_class": config["readiness_class"],
        "access_blocker": config["access_blocker"],
        "why": config["why"],
        "status": status,
        "direct_t1_t3_eligible": direct_eligible,
        "direct_required": bool(config["direct_required"]),
        "runbook": rb,
        "request_packet": packet,
        "route_json_runbook": route_runbook,
        "runbook_matches_json": bool(runbook_matches_json),
        "source_count": len(route_sources),
        "action_packet_ready": action_packet_ready,
        "submission_support": submission_support,
        "remote_job_allowed_now": False,
        "scaffold_allowed_now": False,
        "first_allowed_action_after_access": config["first_allowed_action_after_access"],
        "current_allowed_action": current_allowed_action,
    }


def make_provenance_row() -> dict[str, Any]:
    if not RECOVERY_JSON.exists():
        return {
            "id": "weargait_raw_input_recovery",
            "present": False,
            "readiness_class": "recovery_preflight_missing",
            "runbook": str(RAW_RECOVERY_RUNBOOK.relative_to(ROOT)),
            "runbook_ready": RAW_RECOVERY_RUNBOOK.exists(),
            "runbook_audit": str(RAW_RECOVERY_RUNBOOK_AUDIT.relative_to(ROOT)),
            "remote_job_allowed_now": False,
            "next_action": "Run the recovery preflight before attempting raw-data restoration.",
        }
    recovery = load_json(RECOVERY_JSON)
    missing = recovery.get("missing_inputs", recovery.get("missing", []))
    credential = recovery.get("credential_status", recovery.get("auth_status", "unknown"))
    return {
        "id": "weargait_raw_input_recovery",
        "present": True,
        "readiness_class": "raw_data_recovery_credentials_needed",
        "status": recovery.get("status"),
        "runbook": str(RAW_RECOVERY_RUNBOOK.relative_to(ROOT)),
        "runbook_ready": RAW_RECOVERY_RUNBOOK.exists(),
        "runbook_audit": str(RAW_RECOVERY_RUNBOOK_AUDIT.relative_to(ROOT)),
        "credential_status": credential,
        "missing_inputs": missing,
        "remote_job_allowed_now": False,
        "next_action": "Provide Synapse credentials/config and explicit large-download confirmation before control/walkway recovery.",
    }


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    external = load_json(SOURCE_JSON)
    routes = external.get("routes", [])
    blocker = load_json(BLOCKER_JSON) if BLOCKER_JSON.exists() else {}

    route_rows = [make_route_row(config, find_route(routes, config["name"])) for config in ROUTES]
    provenance_row = make_provenance_row()

    hard_failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for row in route_rows:
        if not row["route_present"]:
            hard_failures.append({"route": row["name"], "issue": "missing_from_external_route_audit"})
            continue
        if row["direct_required"] and not row["direct_t1_t3_eligible"]:
            hard_failures.append({"route": row["name"], "issue": "expected_direct_t1_t3_route_not_marked_direct"})
        if row["priority"] <= 6 and row["source_count"] == 0:
            hard_failures.append({"route": row["name"], "issue": "high_priority_route_has_no_sources"})
        if row["priority"] <= 6 and not row["runbook"]["passed"]:
            hard_failures.append(
                {
                    "route": row["name"],
                    "issue": "high_priority_route_runbook_incomplete",
                    "missing_checks": row["runbook"]["missing_checks"],
                    "path": row["runbook"]["path"],
                }
            )
        if row["priority"] <= 6 and not row["runbook_matches_json"]:
            hard_failures.append(
                {
                    "route": row["name"],
                    "issue": "external_route_json_not_linked_to_expected_runbook",
                    "expected_runbook": row["runbook"]["path"],
                    "route_json_runbook": row["route_json_runbook"],
                }
            )
        if row["priority"] <= 6 and row["request_packet"]["required"] and not row["request_packet"]["passed"]:
            hard_failures.append(
                {
                    "route": row["name"],
                    "issue": "required_request_packet_incomplete",
                    "path": row["request_packet"]["path"],
                    "audit": row["request_packet"]["audit"],
                    "audit_exists": row["request_packet"]["audit_exists"],
                }
            )
        if row["id"] == "ppmi_verily" and not (row.get("submission_support") or {}).get("passed"):
            hard_failures.append(
                {
                    "route": row["name"],
                    "issue": "ppmi_submission_support_incomplete",
                    "missing_checks": (row.get("submission_support") or {}).get("missing_checks", []),
                }
            )
        if row["remote_job_allowed_now"] or row["scaffold_allowed_now"]:
            hard_failures.append({"route": row["name"], "issue": "pre_access_compute_or_scaffold_marked_allowed"})
        if row["priority"] > 6 and row["runbook"]["path"] is None:
            warnings.append({"route": row["name"], "issue": "low_priority_or_watchlist_route_has_no_runbook_by_design"})

    blocker_counts = blocker.get("action_type_counts", {})
    no_local_actions = blocker_counts.get("no_local_weargait_model_run", 0)
    access_required = blocker_counts.get("requires_user_or_data_owner_access", 0)

    compute_ready_routes = [
        row["name"]
        for row in route_rows
        if row["remote_job_allowed_now"] or row["scaffold_allowed_now"]
    ]
    application_ready_routes = [
        row["name"]
        for row in route_rows
        if row["action_packet_ready"]
    ]

    summary = {
        "passed": not hard_failures,
        "route_count": len(route_rows),
        "application_packet_ready_count": len(application_ready_routes),
        "compute_ready_route_count": len(compute_ready_routes),
        "top_priority_route": "PPMI / Verily Study Watch",
        "no_local_weargait_model_actions_remaining": no_local_actions,
        "verifier_access_required_blockers": access_required,
        "provenance_recovery_class": provenance_row.get("readiness_class"),
        "hard_failure_count": len(hard_failures),
        "warning_count": len(warnings),
        "ppmi_submission_support_ready": bool(
            next(
                (
                    (row.get("submission_support") or {}).get("passed")
                    for row in route_rows
                    if row["id"] == "ppmi_verily"
                ),
                False,
            )
        ),
    }

    out = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Operationalize remaining gated external-data and raw-data-restoration blockers without launching new local model runs.",
        "source_audit": str(SOURCE_JSON.relative_to(ROOT)),
        "blocker_audit": str(BLOCKER_JSON.relative_to(ROOT)) if BLOCKER_JSON.exists() else None,
        "summary": summary,
        "routes": route_rows,
        "provenance_recovery": provenance_row,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "decision": (
            "access_packets_ready_no_compute"
            if not hard_failures
            else "access_readiness_audit_failed"
        ),
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines: list[str] = []
    lines.append("# External Access Readiness Audit - 2026-05-09")
    lines.append("")
    lines.append("This is an access/readiness audit, not a model result and not a completion marker.")
    lines.append("")
    lines.append(f"- Passed: `{summary['passed']}`")
    lines.append(f"- Application/request packets ready: `{summary['application_packet_ready_count']}`")
    lines.append(f"- Compute-ready routes before access: `{summary['compute_ready_route_count']}`")
    lines.append(f"- Top priority route: `{summary['top_priority_route']}`")
    lines.append(f"- Raw-data recovery class: `{summary['provenance_recovery_class']}`")
    lines.append("")
    lines.append("## Ordered Access Queue")
    lines.append("")
    lines.append("| Priority | Route | Readiness class | Current allowed action | Access blocker | Runbook | Request packet | Submission support |")
    lines.append("|---:|---|---|---|---|---|---|---|")
    for row in sorted(route_rows, key=lambda r: int(r["priority"])):
        rb = row["runbook"]["path"] or "not required"
        packet = row["request_packet"]["path"] or "not required"
        support = "ready" if (row.get("submission_support") or {}).get("passed") else ("not required" if row["id"] != "ppmi_verily" else "not ready")
        lines.append(
            f"| {row['priority']} | {row['name']} | `{row['readiness_class']}` | "
            f"`{row['current_allowed_action']}` | {row['access_blocker']} | `{rb}` | `{packet}` | `{support}` |"
        )
    lines.append("")
    lines.append("## Guardrails")
    lines.append("")
    lines.append("- No route is compute-ready before access; remote jobs remain disallowed.")
    lines.append("- The first allowed code action after approval is a read-only schema probe.")
    lines.append("- High-priority direct routes require runbooks with no-scaffold boundaries, subject linkage, Part III labels, probe steps, and stop conditions.")
    lines.append("- Mobilise-D CVS and the small request-only actigraphy routes are not application-ready; they remain watch/request-only until row-level wearable plus label schemas exist.")
    lines.append("")
    lines.append("## Provenance Recovery")
    lines.append("")
    lines.append(f"- Class: `{provenance_row.get('readiness_class')}`")
    lines.append(f"- Runbook: `{provenance_row.get('runbook')}`")
    lines.append(f"- Runbook ready: `{provenance_row.get('runbook_ready')}`")
    lines.append(f"- Remote job allowed now: `{provenance_row.get('remote_job_allowed_now')}`")
    lines.append(f"- Next action: {provenance_row.get('next_action')}")
    lines.append("")
    lines.append("## Failures And Warnings")
    lines.append("")
    if hard_failures:
        for failure in hard_failures:
            lines.append(f"- HARD: `{failure}`")
    else:
        lines.append("- Hard failures: `0`")
    if warnings:
        for warning in warnings:
            lines.append(f"- WARN: `{warning}`")
    else:
        lines.append("- Warnings: `0`")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(
        "The next valid work is user/data-owner access requests and read-only schema probes after approval. "
        "Do not start another local WearGait-only model run from these blockers."
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
