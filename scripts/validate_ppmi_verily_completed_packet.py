#!/usr/bin/env python3
"""Validate a locally completed PPMI / Verily Tier-3 packet before submission.

This script is designed for user-side preflight only. It reads a completed
packet path, checks that required submission terms remain present and template
placeholders have been replaced, then prints a content-free JSON summary. It
does not write the packet, packet text, personal fields, credentials, protected
metadata, or approval claims.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
ALLOWED_SUFFIXES = {".docx", ".pdf", ".md", ".txt"}

TERM_GROUPS: dict[str, list[str]] = {
    "official_tier3_terms": [
        "verily raw device data",
        "tier 3",
        "resources@michaeljfox.org",
        "version 7.0",
        "15 feb 2026",
    ],
    "official_source_recheck": [
        "current official source recheck on 2026-05-16",
        "data use agreement",
        "online application",
        "publications policy",
        "data and publications committee within one week",
        "ppmi data access guidelines version 7.0",
        "30 days after receipt",
        "file-size transfer restrictions",
        "data complexity",
    ],
    "packet_contents": [
        "principal investigator",
        "specific tier-3 data",
        "intended use",
        "analysis synopsis",
        "named research team",
        "data custodian",
        "no-sharing",
    ],
    "analysis_boundary": [
        "read-only schema probe",
        "zero-shot external validation",
        "not be presented as an internal weargait-pd canonical",
        "no ppmi label peeking",
    ],
}

FORBIDDEN_TERMS = [
    "synapse_auth_token",
    "password=",
    "secret_key",
    "api_key",
    "private_key",
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
    raise ValueError(f"unsupported packet extension {suffix!r}; expected one of {sorted(ALLOWED_SUFFIXES)}")


def check_terms(text: str, terms: list[str]) -> dict[str, Any]:
    low = text.lower()
    missing = [term for term in terms if term not in low]
    return {
        "passed": not missing,
        "missing_terms": missing,
        "required_term_count": len(terms),
    }


def validate_packet(path: Path, allow_placeholders: bool = False) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("packet path does not exist")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported packet extension {path.suffix!r}")
    text = packet_text(path)
    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    low = text.lower()
    checks: dict[str, Any] = {
        "path_exists": {"passed": True, "suffix": path.suffix.lower()},
        "placeholders_replaced": {
            "passed": allow_placeholders or not placeholders,
            "remaining_placeholder_count": len(placeholders),
            "remaining_placeholders": placeholders,
        },
        "forbidden_terms_absent": {
            "passed": not [term for term in FORBIDDEN_TERMS if term in low],
            "forbidden_terms_found": [term for term in FORBIDDEN_TERMS if term in low],
        },
    }
    for group, terms in TERM_GROUPS.items():
        checks[group] = check_terms(text, terms)

    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    passed = not hard_failures
    pre_submission_preflight_valid = passed and not allow_placeholders
    decision = (
        "completed_packet_preflight_passed"
        if pre_submission_preflight_valid
        else "placeholder_tolerant_packet_audit_passed"
        if passed and allow_placeholders
        else "completed_packet_preflight_failed"
    )
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "packet_identity_redacted": True,
        "packet_path_reported": False,
        "packet_suffix": path.suffix.lower(),
        "packet_size_bytes": path.stat().st_size,
        "passed": passed,
        "decision": decision,
        "allow_placeholders_used": bool(allow_placeholders),
        "pre_submission_preflight_valid": pre_submission_preflight_valid,
        "not_valid_for_submission": bool(allow_placeholders),
        "checks": checks,
        "hard_failures": hard_failures,
        "content_not_recorded": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "next_action": (
            "If this is a real completed packet, email it through the PPMI access workflow and "
            "then record only non-protected submission metadata."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, help="Path to a completed .docx, .pdf, .md, or .txt packet")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Allow template placeholders. Intended only for auditing unfinished templates.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = validate_packet(Path(args.packet), allow_placeholders=args.allow_placeholders)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
