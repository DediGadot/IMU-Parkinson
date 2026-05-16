#!/usr/bin/env python3
"""Audit the local PPP / PD-VME request packet template.

This is an access-readiness guard, not a model result. It verifies that the
packet template captures PPP's request mechanics and the repo's leakage and
claim-boundary guardrails before the user fills/submits it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PACKET = ROOT / "scripts" / "ppp_pd_vme_request_packet.md"
RUNBOOK = ROOT / "scripts" / "ppp_pd_vme_request_setup.md"
OUT_JSON = ROOT / "results" / "ppp_pd_vme_request_packet_audit_20260509.json"
OUT_MD = ROOT / "results" / "ppp_pd_vme_request_packet_audit_20260509.md"


REQUIRED_CHECKS: dict[str, list[str]] = {
    "official_sources": [
        "personalizedparkinsonproject.com/data-sharing/requesting-data",
        "personalizedparkinsonproject.com/data-sharing/available-data",
        "personalizedparkinsonproject.com/data-sharing/using-data",
        "nature.com/articles/s41746-022-00607-8",
    ],
    "request_mechanics": [
        "project-proposal template",
        "phd applicant",
        "rdsrc",
        "qualified researcher agreement",
        "cost quote",
        "pep repository",
    ],
    "specific_data_inventory": [
        "verily study watch accelerometer",
        "gyroscope",
        "pd-vme active-task sensor recordings",
        "wrist laterality",
        "sampling rates",
        "axis frames",
    ],
    "clinical_linkage_inventory": [
        "mds-updrs part iii",
        "off and on",
        "consensus subitem ratings",
        "mds-updrs part ii",
        "items 9-14",
        "hoehn & yahr",
    ],
    "required_packet_fields": [
        "scientific rationale",
        "specific data requested",
        "intended use",
        "analysis synopsis",
        "named research team",
        "data custodian",
    ],
    "sharing_publication_terms": [
        "will not be redistributed",
        "45 days before first submission",
        "derived data",
        "uploaded back to the pep repository",
    ],
    "security_plan": [
        "encrypted",
        "access-controlled",
        "do not commit",
        "consumer cloud",
        "pep client configuration",
    ],
    "methodology_guardrails": [
        "read-only schema probe",
        "zero-shot external validation",
        "subject-level splits",
        "pre-registration",
        "formula_sha256",
        "valid-range",
        "manifest sidecar",
    ],
    "no_premature_compute_boundary": [
        "will not present ppp/pd-vme metrics as weargait-pd internal canonical",
        "no ppp label peeking",
        "do not use ppp labels for feature selection",
        "ppg and skin conductance are excluded from first analysis",
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
        runbook_mentions_packet = "ppp_pd_vme_request_packet.md" in runbook_text

    hard_failures: list[str] = []
    if not packet_exists:
        hard_failures.append("missing_packet_template")
    if not runbook_exists:
        hard_failures.append("missing_ppp_runbook")
    if missing:
        hard_failures.append("packet_missing_required_terms")
    if not runbook_mentions_packet:
        hard_failures.append("runbook_does_not_link_packet_template")

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not hard_failures,
        "decision": "ppp_pd_vme_request_packet_ready" if not hard_failures else "packet_needs_revision",
        "packet": str(PACKET.relative_to(ROOT)),
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "packet_exists": packet_exists,
        "runbook_exists": runbook_exists,
        "runbook_mentions_packet": runbook_mentions_packet,
        "checks": checks,
        "missing": missing,
        "hard_failures": hard_failures,
        "official_requirements_encoded": {
            "request_mechanics": "PPP project-proposal template, at least one PhD applicant, pre-submission data-management check, RDSRC review if not pre-approved, short PI CV, QRA after approval, cost quote/fees, and PEP repository access.",
            "sharing_terms": "No open sharing beyond named approved researchers, manuscript submission to Research Support at least 45 days before first submission, and derived-data upload to PEP when required.",
            "pd_vme_route": "PD-VME includes Verily Study Watch active/passive sensor data and MDS-UPDRS Part III consensus ratings in early PD.",
        },
        "not_a_model_result": True,
        "goal_complete": False,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPP / PD-VME Request Packet Audit - 2026-05-09",
        "",
        "This is an access-readiness guard, not a model result and not a completion marker.",
        "",
        f"- Passed: `{result['passed']}`",
        f"- Decision: `{result['decision']}`",
        f"- Packet: `{result['packet']}`",
        f"- Runbook links packet: `{runbook_mentions_packet}`",
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
            "The PPP / PD-VME request packet is ready to fill for the user/data-owner access step. "
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
