#!/usr/bin/env python3
"""Audit the local PPMI / Verily Tier-3 request packet template.

This is an access-readiness guard, not a model result. It verifies that the
packet template contains the official Tier-3 request ingredients and the repo's
leakage/claim-boundary guardrails before the user fills and submits it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PACKET = ROOT / "scripts" / "ppmi_verily_tier3_request_packet.md"
RUNBOOK = ROOT / "scripts" / "ppmi_verily_setup.md"
OUT_JSON = ROOT / "results" / "ppmi_verily_request_packet_audit_20260509.json"
OUT_MD = ROOT / "results" / "ppmi_verily_request_packet_audit_20260509.md"

OFFICIAL_SOURCE_RECHECK = {
    "verified_on": "2026-05-16",
    "access_page": "https://www.ppmi-info.org/access-data-specimens/download-data",
    "guidelines_pdf": "https://www.ppmi-info.org/sites/default/files/docs/PPMI%20Data%20Access%20Guidelines.pdf",
    "access_page_requirements": [
        "sign the Data Use Agreement",
        "submit an online application",
        "comply with the Publications Policy",
        "Data and Publications Committee review within one week",
    ],
    "guidelines_version": "Version 7.0, 15 Feb 2026",
    "tier3_contact": "resources@michaeljfox.org",
    "tier3_review_target": "30 days after receipt",
    "tier3_verily_access_level": "Tier 3",
}

REQUIRED_CHECKS: dict[str, list[str]] = {
    "official_sources": [
        "ppmi-info.org/access-data-specimens/download-data",
        "ppmi data access guidelines",
        "version 7.0",
        "15 feb 2026",
        "nature.com/articles/s41531-025-01034-8",
    ],
    "official_source_recheck_20260516": [
        "current official source recheck on 2026-05-16",
        "sign the data use agreement",
        "submit an online application",
        "comply with the publications policy",
        "data and publications committee within one week",
    ],
    "tier3_submission": [
        "verily raw device data",
        "tier 3",
        "resources@michaeljfox.org",
        "pdf or word",
        "30 days",
    ],
    "specific_data_inventory": [
        "raw triaxial accelerometer",
        "sampling frequency",
        "wrist laterality",
        "axis frame",
        "wearable collection intervals",
    ],
    "clinical_linkage_inventory": [
        "mds-updrs part iii",
        "mds-updrs part ii",
        "items 9-14",
        "hoehn & yahr",
        "medication state",
    ],
    "required_packet_fields": [
        "principal investigator",
        "intended use",
        "analysis synopsis",
        "named research team",
        "data custodian",
        "all requesting research-team members",
    ],
    "purpose_and_no_sharing": [
        "will not be shared beyond investigators named",
        "only be used for the purpose described",
        "not attempt participant re-identification",
    ],
    "security_plan": [
        "encrypted",
        "access-controlled",
        "do not commit credentials",
        "consumer cloud",
    ],
    "methodology_guardrails": [
        "read-only schema probe",
        "zero-shot external validation",
        "subject-level splits",
        "pre-registration",
        "formula_sha256",
        "valid-range",
        "manifest sidecars",
    ],
    "proresults_external_blueprint": [
        "ppmi_verily_zeroshot_blueprint_20260515.json",
        "analysis-order and no-search boundary",
        "not a preregistration",
        "persistent homology",
        "multifractal detrended fluctuation analysis",
        "ph/mfdfa",
        "topofractal",
        "k=250",
        "gradientboostingregressor",
        "no k-search",
        "no endpoint switching",
    ],
    "no_premature_compute_boundary": [
        "not be presented as an internal weargait-pd canonical",
        "no ppmi label peeking",
        "no endpoint switching",
    ],
}


def contains_all(text: str, needles: list[str]) -> tuple[bool, list[str]]:
    missing = [needle for needle in needles if needle not in text]
    return not missing, missing


def main() -> None:
    packet_exists = PACKET.exists()
    runbook_exists = RUNBOOK.exists()
    text = PACKET.read_text(encoding="utf-8", errors="replace").lower() if packet_exists else ""

    checks: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    for check_id, needles in REQUIRED_CHECKS.items():
        passed, missing_needles = contains_all(text, needles)
        checks[check_id] = {
            "passed": passed,
            "required_terms": needles,
            "missing_terms": missing_needles,
        }
        if missing_needles:
            missing.append({"check": check_id, "missing_terms": missing_needles})

    runbook_mentions_packet = False
    if runbook_exists:
        runbook_text = RUNBOOK.read_text(encoding="utf-8", errors="replace").lower()
        runbook_mentions_packet = "ppmi_verily_tier3_request_packet.md" in runbook_text
        runbook_official_recheck_passed, runbook_official_recheck_missing = contains_all(
            runbook_text,
            REQUIRED_CHECKS["official_source_recheck_20260516"]
            + [
                "verily raw device data",
                "version 7.0",
                "15 feb 2026",
                "resources@michaeljfox.org",
                "30 days after receipt",
            ],
        )
    else:
        runbook_official_recheck_passed = False
        runbook_official_recheck_missing = ["missing_ppmi_runbook"]

    hard_failures: list[str] = []
    if not packet_exists:
        hard_failures.append("missing_packet_template")
    if not runbook_exists:
        hard_failures.append("missing_ppmi_runbook")
    if missing:
        hard_failures.append("packet_missing_required_terms")
    if not runbook_mentions_packet:
        hard_failures.append("runbook_does_not_link_packet_template")
    if not runbook_official_recheck_passed:
        hard_failures.append("runbook_missing_current_official_source_recheck")

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not hard_failures,
        "decision": "ppmi_verily_tier3_request_packet_ready" if not hard_failures else "packet_needs_revision",
        "packet": str(PACKET.relative_to(ROOT)),
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "packet_exists": packet_exists,
        "runbook_exists": runbook_exists,
        "runbook_mentions_packet": runbook_mentions_packet,
        "official_source_recheck": {
            **OFFICIAL_SOURCE_RECHECK,
            "packet_terms_passed": checks["official_source_recheck_20260516"]["passed"],
            "runbook_terms_passed": runbook_official_recheck_passed,
            "runbook_missing_terms": runbook_official_recheck_missing,
            "not_access_submission": True,
            "not_access_approval": True,
            "not_a_schema_probe": True,
        },
        "checks": checks,
        "missing": missing,
        "hard_failures": hard_failures,
        "official_requirements_encoded": {
            "standard_access": "qualified-researcher registration, Data Use Agreement, online application, and Publications Policy acknowledgement",
            "tier3_verily": "Verily Raw Device Data is Tier 3 and needs a specific request packet",
            "tier3_packet_fields": [
                "specific requested Tier-3 data",
                "intended use",
                "brief synopsis of proposed analyses",
                "names of all requesting research-team members",
                "re-acknowledgement of no-sharing and purpose limits",
            ],
        },
        "not_a_model_result": True,
        "goal_complete": False,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Request Packet Audit - 2026-05-09",
        "",
        "This is an access-readiness guard, not a model result and not a completion marker.",
        "",
        f"- Passed: `{result['passed']}`",
        f"- Decision: `{result['decision']}`",
        f"- Packet: `{result['packet']}`",
        f"- Runbook links packet: `{runbook_mentions_packet}`",
        f"- Official source recheck: `{OFFICIAL_SOURCE_RECHECK['verified_on']}`",
        f"- Runbook official-source terms passed: `{runbook_official_recheck_passed}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Missing Terms |",
        "|---|---|---|",
    ]
    for check_id, check in checks.items():
        missing_terms = ", ".join(f"`{term}`" for term in check["missing_terms"]) or "-"
        lines.append(f"| `{check_id}` | `{check['passed']}` | {missing_terms} |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The packet is ready to fill locally for the user/data-owner PPMI access step. "
            "It does not authorize a scaffold, preregistration, download, remote job, or model run. "
            "The first allowed code action after approval remains a read-only schema probe.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"passed={result['passed']} hard_failures={len(hard_failures)}")
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
