#!/usr/bin/env python3
"""Validate a locally completed gated-route access packet before submission.

This is a user-side preflight helper for the external access queue. It reads a
completed local packet, checks that template placeholders have been replaced and
route-specific methodological guardrails remain present, then prints a
content-free JSON summary. It does not write or echo completed packet contents,
personal fields, credentials, protected metadata, submission evidence, or
approval claims.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACKER = ROOT / "results" / "access_submission_tracker_20260509.json"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
ALLOWED_SUFFIXES = {".docx", ".pdf", ".md", ".txt"}

COMMON_REQUIRED_TERMS = [
    "read-only schema probe",
    "MDS-UPDRS",
    "subject-level",
    "external",
    "internal WearGait-PD canonical",
    "no",
    "pre-registration",
]

ROUTE_REQUIRED_TERMS: dict[str, list[str]] = {
    "ppmi_verily": [
        "Verily Raw Device Data",
        "Tier 3",
        "resources@michaeljfox.org",
        "zero-shot external validation",
    ],
    "ppp_pd_vme": [
        "PPP",
        "PD-VME",
        "Verily Study Watch",
        "Qualified Researcher Agreement",
        "PEP",
    ],
    "watchpd": [
        "WATCH-PD",
        "APDM",
        "Apple Watch",
        "iPhone",
    ],
    "cns_portugal_lobo": [
        "CNS Portugal",
        "AX3",
        "ten-meter",
        "session",
    ],
    "hssayeni_mjff": [
        "syn20681023",
        "Synapse",
        "MJFF",
        "levodopa",
    ],
    "icicle_gait": [
        "ICICLE",
        "lower-back AX3",
        "daily row",
        "participant-level",
    ],
}

FORBIDDEN_TERMS = [
    "synapse_auth_token",
    "password=",
    "secret_key",
    "api_key",
    "private_key",
    "begin private key",
]


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    return "".join(root.itertext())


def pdf_text(path: Path) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise ValueError("PDF validation requires pdftotext on PATH")
    proc = subprocess.run(
        [pdftotext, "-layout", str(path), "-"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise ValueError("pdftotext failed")
    return proc.stdout


def packet_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx_text(path)
    if suffix == ".pdf":
        return pdf_text(path)
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(
        f"unsupported packet extension {suffix!r}; expected one of {sorted(ALLOWED_SUFFIXES)}"
    )


def load_tracker(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("access submission tracker is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("access submission tracker JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("access submission tracker must contain a JSON object")
    return payload


def route_from_tracker(tracker: dict[str, Any], route_id: str) -> dict[str, Any]:
    for row in tracker.get("routes", []):
        if row.get("id") == route_id:
            return row
    raise ValueError(f"route_id {route_id!r} not found in access submission tracker")


def check_terms(text: str, terms: list[str]) -> dict[str, Any]:
    low = text.lower()
    missing = [term for term in terms if term.lower() not in low]
    return {
        "passed": not missing,
        "missing_terms": missing,
        "required_term_count": len(terms),
    }


def validate_packet(
    *,
    route_id: str,
    packet_path: Path,
    tracker_path: Path,
    allow_placeholders: bool = False,
) -> dict[str, Any]:
    tracker = load_tracker(tracker_path)
    route = route_from_tracker(tracker, route_id)
    if route.get("submission_status") != "ready_to_submit_after_user_fill_and_governance":
        raise ValueError("route is not currently submit-ready in access submission tracker")
    if route.get("remote_job_allowed_now") or route.get("scaffold_allowed_now"):
        raise ValueError("route unexpectedly allows compute/scaffold before approval")
    if not packet_path.exists():
        raise ValueError("packet path does not exist")
    if packet_path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported packet extension {packet_path.suffix!r}")

    text = packet_text(packet_path)
    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    low = text.lower()
    route_terms = ROUTE_REQUIRED_TERMS.get(route_id, [])
    expected_placeholders = [f"[{value}]" for value in route.get("packet_placeholders", [])]
    remaining_expected = [value for value in expected_placeholders if value in placeholders]

    checks: dict[str, Any] = {
        "route_is_submit_ready": {
            "passed": True,
            "route_id": route_id,
            "route_priority": route.get("priority"),
        },
        "path_exists": {"passed": True, "suffix": packet_path.suffix.lower()},
        "placeholders_replaced": {
            "passed": allow_placeholders or not placeholders,
            "remaining_placeholder_count": len(placeholders),
            "remaining_expected_placeholder_count": len(remaining_expected),
            "remaining_placeholders": placeholders,
        },
        "forbidden_terms_absent": {
            "passed": not [term for term in FORBIDDEN_TERMS if term in low],
            "forbidden_terms_found": [term for term in FORBIDDEN_TERMS if term in low],
        },
        "common_method_terms_present": check_terms(text, COMMON_REQUIRED_TERMS),
        "route_specific_terms_present": check_terms(text, route_terms),
        "pre_access_compute_boundary_present": check_terms(
            text,
            [
                "do not",
                "download",
                "cache",
                "model",
            ],
        ),
    }

    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    passed = not hard_failures
    pre_submission_preflight_valid = passed and not allow_placeholders
    decision = (
        "access_request_packet_preflight_passed"
        if pre_submission_preflight_valid
        else "placeholder_tolerant_access_packet_audit_passed"
        if passed and allow_placeholders
        else "access_request_packet_preflight_failed"
    )
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": route_id,
        "route_name": route.get("name"),
        "packet_identity_redacted": True,
        "packet_path_reported": False,
        "packet_suffix": packet_path.suffix.lower(),
        "packet_size_bytes": packet_path.stat().st_size,
        "passed": passed,
        "decision": decision,
        "allow_placeholders_used": bool(allow_placeholders),
        "pre_submission_preflight_valid": pre_submission_preflight_valid,
        "not_valid_for_submission": bool(allow_placeholders),
        "checks": checks,
        "hard_failures": hard_failures,
        "content_not_recorded": True,
        "completed_packet_included": False,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "next_action": (
            "If this is a real completed packet, submit it through the route's "
            "data-owner workflow and then record only non-protected submission metadata."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", required=True)
    parser.add_argument(
        "--packet",
        required=True,
        help="Path to a completed .docx, .pdf, .md, or .txt access packet",
    )
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER))
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Allow template placeholders. Intended only for auditing unfinished templates.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = validate_packet(
            route_id=args.route_id,
            packet_path=Path(args.packet),
            tracker_path=Path(args.tracker),
            allow_placeholders=args.allow_placeholders,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
