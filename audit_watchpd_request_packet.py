#!/usr/bin/env python3
"""Audit the local WATCH-PD proposal packet template.

This is an access-readiness guard, not a model result. It verifies that the
proposal template captures WATCH-PD's access path and the repo's leakage and
claim-boundary guardrails before the user fills/submits it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PACKET = ROOT / "scripts" / "watchpd_request_packet.md"
RUNBOOK = ROOT / "scripts" / "watchpd_request_setup.md"
OUT_JSON = ROOT / "results" / "watchpd_request_packet_audit_20260509.json"
OUT_MD = ROOT / "results" / "watchpd_request_packet_audit_20260509.md"


REQUIRED_CHECKS: dict[str, list[str]] = {
    "official_sources": [
        "c-path.org/program/critical-path-for-parkinsons",
        "mdsabstracts.org/abstract/watch-pd",
        "nature.com/articles/s41531-023-00497-x",
        "critical-path-for-parkinsons-3dt-initiative",
    ],
    "access_path": [
        "cpp_3dt_stage2_member_or_steering_committee_proposal",
        "watch-pd steering committee",
        "de-identified baseline",
    ],
    "specific_data_inventory": [
        "apdm opal",
        "accelerometer",
        "gyroscope",
        "magnetometer",
        "apple watch",
        "iphone brainbaseline",
        "site identifiers",
    ],
    "clinical_linkage_inventory": [
        "mds-updrs part iii",
        "mds-updrs part ii",
        "items 9-14",
        "hoehn & yahr",
        "treatment status",
    ],
    "required_packet_fields": [
        "scientific rationale",
        "specific data requested",
        "intended use",
        "analysis synopsis",
        "named research team",
        "data custodian",
    ],
    "security_publication_terms": [
        "encrypted",
        "access-controlled",
        "do not commit",
        "consumer cloud",
        "citation and publication terms",
        "aggregate, non-identifiable",
    ],
    "methodology_guardrails": [
        "read-only schema probe",
        "zero-shot external validation",
        "subject-level splits",
        "pre-registration",
        "valid-range",
        "manifest sidecar",
    ],
    "watchpd_specific_guardrails": [
        "apple watch and iphone data are diagnostic-only",
        "healthy controls are diagnostic-only",
        "below 20",
        "repeated visits from the same subject must stay in the same fold",
        "external-validity / transportability evidence only",
    ],
    "no_premature_compute_boundary": [
        "do not create a probe scaffold",
        "will not present watch-pd metrics as internal weargait-pd canonical",
        "no watch-pd label peeking",
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
        runbook_mentions_packet = "watchpd_request_packet.md" in runbook_text

    hard_failures: list[str] = []
    if not packet_exists:
        hard_failures.append("missing_packet_template")
    if not runbook_exists:
        hard_failures.append("missing_watchpd_runbook")
    if missing:
        hard_failures.append("packet_missing_required_terms")
    if not runbook_mentions_packet:
        hard_failures.append("runbook_does_not_link_packet_template")

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not hard_failures,
        "decision": "watchpd_request_packet_ready" if not hard_failures else "packet_needs_revision",
        "packet": str(PACKET.relative_to(ROOT)),
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "packet_exists": packet_exists,
        "runbook_exists": runbook_exists,
        "runbook_mentions_packet": runbook_mentions_packet,
        "checks": checks,
        "missing": missing,
        "hard_failures": hard_failures,
        "official_requirements_encoded": {
            "access_path": "WATCH-PD data are available to CPP 3DT Stage 2 members; non-members may propose to the WATCH-PD Steering Committee via the corresponding author for de-identified baseline datasets.",
            "cpath_boundary": "The C-Path Integrated Parkinson's Database does not include digital health technology data, so the ordinary IPD route is insufficient for WATCH-PD sensors.",
            "watchpd_route": "WATCH-PD includes Apple Watch, iPhone BrainBaseline, and APDM Opal data plus MDS-UPDRS Parts I-III and H&Y in early untreated PD.",
        },
        "not_a_model_result": True,
        "goal_complete": False,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# WATCH-PD Request Packet Audit - 2026-05-09",
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
            "The WATCH-PD proposal packet is ready to fill for the user/data-owner access step. "
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
