#!/usr/bin/env python3
"""Audit the Word-format PPMI / Verily Tier-3 packet template.

This verifies that the generated `.docx` is a valid ready-to-fill template and
that it preserves the access-packet guardrails. It is not an access approval,
schema probe, model result, or completion marker.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SOURCE = ROOT / "scripts" / "ppmi_verily_tier3_request_packet.md"
DOCX = RESULTS / "ppmi_verily_tier3_request_packet_template_20260515.docx"
MANIFEST = RESULTS / "ppmi_verily_tier3_request_packet_template_20260515.manifest.json"
OUT_JSON = RESULTS / "ppmi_verily_submit_format_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_submit_format_audit_20260515.md"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
EXPECTED_PLACEHOLDERS = {
    "[PI_NAME]",
    "[INSTITUTION]",
    "[DEPARTMENT_OR_LAB]",
    "[PI_EMAIL]",
    "[PI_PHONE]",
    "[ADDRESS]",
    "[IRB_ID_OR_STATUS]",
    "[CONTACT]",
    "[PPMI_ID]",
    "[ANALYST_NAME]",
    "[EMAIL]",
    "[DATA_CUSTODIAN]",
    "[CUSTODIAN_EMAIL]",
}

TERM_GROUPS: dict[str, list[str]] = {
    "official_tier3_terms": [
        "verily raw device data",
        "tier 3",
        "resources@michaeljfox.org",
        "pdf or word",
        "version 7.0",
        "15 feb 2026",
        "30 days",
    ],
    "required_packet_fields": [
        "principal investigator",
        "intended use",
        "analysis synopsis",
        "named research team",
        "data custodian",
        "no-sharing",
    ],
    "proresults_blueprint_terms": [
        "persistent homology",
        "multifractal detrended fluctuation analysis",
        "topofractal",
        "k=250",
        "gradientboostingregressor",
        "no k-search",
    ],
    "compute_boundary_terms": [
        "read-only schema probe",
        "zero-shot external validation",
        "not be presented as an internal weargait-pd canonical",
        "no ppmi label peeking",
    ],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    return "".join(root.itertext())


def term_check(text: str, terms: list[str]) -> dict[str, Any]:
    low = text.lower()
    missing = [term for term in terms if term not in low]
    return {
        "passed": not missing,
        "required_terms": terms,
        "missing_terms": missing,
    }


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    manifest = load_manifest()
    source_text = SOURCE.read_text(encoding="utf-8", errors="replace") if SOURCE.exists() else ""
    extracted_text = docx_text(DOCX) if DOCX.exists() else ""
    source_placeholders = sorted(set(PLACEHOLDER_RE.findall(source_text)))
    docx_placeholders = sorted(set(PLACEHOLDER_RE.findall(extracted_text)))

    checks: dict[str, Any] = {
        "source_exists": {"passed": SOURCE.exists(), "path": rel(SOURCE) if SOURCE.exists() else str(SOURCE)},
        "docx_exists": {"passed": DOCX.exists(), "path": rel(DOCX) if DOCX.exists() else str(DOCX)},
        "manifest_exists": {
            "passed": MANIFEST.exists(),
            "path": rel(MANIFEST) if MANIFEST.exists() else str(MANIFEST),
        },
        "docx_is_zip_package": {"passed": False},
        "manifest_hashes_match": {"passed": False},
        "placeholders_preserved": {
            "passed": EXPECTED_PLACEHOLDERS.issubset(set(docx_placeholders)),
            "expected": sorted(EXPECTED_PLACEHOLDERS),
            "docx_placeholders": docx_placeholders,
            "source_placeholders": source_placeholders,
        },
        "protected_data_absent": {
            "passed": all(term not in extracted_text.lower() for term in ["synapse_auth_token", "password=", "secret_key"]),
            "forbidden_terms_checked": ["synapse_auth_token", "password=", "secret_key"],
        },
    }

    if DOCX.exists():
        try:
            with zipfile.ZipFile(DOCX) as zf:
                names = set(zf.namelist())
            checks["docx_is_zip_package"] = {
                "passed": "[Content_Types].xml" in names and "word/document.xml" in names,
                "required_members": ["[Content_Types].xml", "word/document.xml"],
            }
        except zipfile.BadZipFile as exc:
            checks["docx_is_zip_package"] = {"passed": False, "error": str(exc)}

    if SOURCE.exists() and DOCX.exists() and manifest:
        checks["manifest_hashes_match"] = {
            "passed": (
                manifest.get("source_sha256") == sha256(SOURCE)
                and manifest.get("output_docx_sha256") == sha256(DOCX)
                and manifest.get("output_docx") == rel(DOCX)
                and manifest.get("source") == rel(SOURCE)
            ),
            "manifest_source_sha256": manifest.get("source_sha256"),
            "actual_source_sha256": sha256(SOURCE),
            "manifest_docx_sha256": manifest.get("output_docx_sha256"),
            "actual_docx_sha256": sha256(DOCX),
            "manifest_output_docx": manifest.get("output_docx"),
        }

    for group, terms in TERM_GROUPS.items():
        checks[group] = term_check(extracted_text, terms)

    hard_failures = [name for name, check in checks.items() if not check.get("passed")]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_ppmi_verily_submit_format.py",
        "source": rel(SOURCE),
        "output_docx": rel(DOCX),
        "manifest": rel(MANIFEST),
        "passed": not hard_failures,
        "decision": "ppmi_verily_word_template_ready_to_fill" if not hard_failures else "ppmi_verily_word_template_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_access_approval": True,
        "goal_complete": False,
        "next_action": "Fill user-side placeholders locally and submit through the PPMI access workflow; do not run protected-data compute before approval.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Submit-Format Audit - 2026-05-15",
        "",
        "This is an access-packet format audit, not a model result, schema probe, or approval record.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Word template: `{report['output_docx']}`",
        f"- Manifest: `{report['manifest']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Missing Terms |",
        "|---|---|---|",
    ]
    for name, check in checks.items():
        missing = ", ".join(f"`{term}`" for term in check.get("missing_terms", [])) or "-"
        lines.append(f"| `{name}` | `{check.get('passed')}` | {missing} |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            report["next_action"],
            "",
            f"Machine-readable report: `{rel(OUT_JSON)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"passed": report["passed"], "hard_failures": hard_failures}, indent=2))
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
