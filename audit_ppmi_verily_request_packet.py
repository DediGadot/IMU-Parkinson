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


REQUIRED_CHECKS: dict[str, list[str]] = {
    "official_sources": [
        "ppmi-info.org/access-data-specimens/download-data",
        "ppmi data access guidelines",
        "nature.com/articles/s41531-025-01034-8",
    ],
    "tier3_submission": [
        "verily raw device data",
        "tier 3",
        "resources@michaeljfox.org",
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

    hard_failures: list[str] = []
    if not packet_exists:
        hard_failures.append("missing_packet_template")
    if not runbook_exists:
        hard_failures.append("missing_ppmi_runbook")
    if missing:
        hard_failures.append("packet_missing_required_terms")
    if not runbook_mentions_packet:
        hard_failures.append("runbook_does_not_link_packet_template")

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not hard_failures,
        "decision": "ppmi_verily_tier3_request_packet_ready" if not hard_failures else "packet_needs_revision",
        "packet": str(PACKET.relative_to(ROOT)),
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "packet_exists": packet_exists,
        "runbook_exists": runbook_exists,
        "runbook_mentions_packet": runbook_mentions_packet,
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
