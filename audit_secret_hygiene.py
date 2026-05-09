#!/usr/bin/env python3
"""Audit the workspace for high-confidence credential leaks without echoing secrets."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "secret_hygiene_audit_20260509.json"
OUT_MD = RESULTS / "secret_hygiene_audit_20260509.md"

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".swarm",
    ".venv",
    "__pycache__",
    "data",
    "figures",
}
EXCLUDED_SUFFIXES = {
    ".csv",
    ".gz",
    ".joblib",
    ".jpg",
    ".jpeg",
    ".log",
    ".npy",
    ".npz",
    ".oof",
    ".parquet",
    ".pdf",
    ".png",
    ".pkl",
    ".sqlite",
    ".zip",
}
MAX_BYTES = 8_000_000

SECRET_PATTERNS = [
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("github_legacy", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
]

SENSITIVE_LOCAL_FILES = ["TOKEN.md", "GPU.md", ".env", "synapse_credentials.json"]
REQUIRED_GITIGNORE_SNIPPETS = ["TOKEN.md", "GPU.md", ".env", "synapse_credentials.json"]


def is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\0" in chunk


def should_scan(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    if any(part in EXCLUDED_DIRS for part in rel_parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    try:
        if path.stat().st_size > MAX_BYTES:
            return False
    except OSError:
        return False
    return path.is_file() and not is_binary(path)


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8", errors="replace")).hexdigest()


def scan_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = []
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "line": line,
                    "pattern": name,
                    "match_sha256": fingerprint(match.group(0)),
                    "match_length": len(match.group(0)),
                }
            )
    return findings


def build_report() -> dict[str, Any]:
    scanned_files = []
    findings = []
    for path in sorted(ROOT.rglob("*")):
        if not should_scan(path):
            continue
        scanned_files.append(str(path.relative_to(ROOT)))
        findings.extend(scan_file(path))

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
    missing_gitignore = [snippet for snippet in REQUIRED_GITIGNORE_SNIPPETS if snippet not in gitignore]
    sensitive_status = {
        name: {
            "exists": (ROOT / name).exists(),
            "bytes": (ROOT / name).stat().st_size if (ROOT / name).exists() else 0,
        }
        for name in SENSITIVE_LOCAL_FILES
    }
    hard_failures = []
    if findings:
        hard_failures.append({"check": "high_confidence_secret_pattern", "findings": findings})
    if missing_gitignore:
        hard_failures.append({"check": "missing_gitignore_secret_patterns", "missing": missing_gitignore})
    if sensitive_status["TOKEN.md"]["exists"]:
        hard_failures.append({"check": "token_md_present", "status": sensitive_status["TOKEN.md"]})

    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_secret_hygiene.py",
        "policy": (
            "No high-confidence credential patterns may remain in repository text surfaces. "
            "Reports include only SHA-256 fingerprints and lengths, never raw secret strings."
        ),
        "passed": not hard_failures,
        "decision": "secret_hygiene_guard_passed" if not hard_failures else "secret_hygiene_guard_failed",
        "scanned_file_count": len(scanned_files),
        "scanned_files": scanned_files,
        "excluded_dirs": sorted(EXCLUDED_DIRS),
        "excluded_suffixes": sorted(EXCLUDED_SUFFIXES),
        "findings": findings,
        "sensitive_local_files": sensitive_status,
        "missing_gitignore": missing_gitignore,
        "hard_failures": hard_failures,
        "remediation_note": (
            "Local ignored TOKEN.md and .env files containing JWT-like credentials were removed during the "
            "2026-05-09 continuation. Any credential that was ever written there should be revoked/rotated."
        ),
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Secret Hygiene Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Scanned files: `{report['scanned_file_count']}`",
        f"- Findings: `{len(report['findings'])}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Sensitive Local Files",
        "",
        "| Path | Exists | Bytes |",
        "|---|---:|---:|",
    ]
    for path, status in report["sensitive_local_files"].items():
        lines.append(f"| `{path}` | `{status['exists']}` | `{status['bytes']}` |")
    lines.extend(["", "## Findings", ""])
    if report["findings"]:
        lines.append("| Path | Line | Pattern | SHA-256 | Length |")
        lines.append("|---|---:|---|---|---:|")
        for row in report["findings"]:
            lines.append(
                f"| `{row['path']}` | `{row['line']}` | `{row['pattern']}` | "
                f"`{row['match_sha256']}` | `{row['match_length']}` |"
            )
    else:
        lines.append("No high-confidence credential patterns found.")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- `{failure['check']}`")
    lines.extend(["", report["remediation_note"], "", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(json.dumps(
        {
            "passed": report["passed"],
            "decision": report["decision"],
            "findings": len(report["findings"]),
            "hard_failures": len(report["hard_failures"]),
            "scanned_files": report["scanned_file_count"],
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
