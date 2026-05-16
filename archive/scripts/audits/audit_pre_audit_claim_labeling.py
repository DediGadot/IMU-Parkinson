#!/usr/bin/env python3
"""Audit manuscript labeling for pre-audit held-out/stacking claims."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "pre_audit_claim_labeling_audit_20260508.json"
OUT_MD = RESULTS / "pre_audit_claim_labeling_audit_20260508.md"

FILES = [ROOT / "paper.md", ROOT / "CURRENT_PAPER.html"]

CLAIM_PATTERNS = {
    "mae_6_89": re.compile(r"MAE\s*=\s*6\.89"),
    "r_0_860": re.compile(r"r\s*=\s*0\.860(?!\d)"),
    "ceiling_6_43": re.compile(r"\b6\.43\b"),
    "ceiling_r_0_848": re.compile(r"\b0\.848\b"),
    "proper_held_out": re.compile(r"proper held-out test", re.IGNORECASE),
    "most_rigorous": re.compile(r"most rigorous evaluation", re.IGNORECASE),
    "approaching_clinical_utility": re.compile(r"approaching clinical utility", re.IGNORECASE),
}

ALLOWED_CONTEXT = re.compile(
    r"\b(pre-audit|historical|retained|original|no longer|not cited|"
    r"audit context|historical comparability|prior reporting|before|post-audit)\b",
    re.IGNORECASE,
)


def read(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".html":
        text = normalize_html(text)
    return text


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def normalize_html(text: str) -> str:
    """Convert rendered HTML to audit-friendly lines while preserving semantics."""
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "\n", text, flags=re.IGNORECASE | re.DOTALL)

    def heading(match: re.Match[str]) -> str:
        level = int(match.group(1))
        title = re.sub(r"\s+", " ", strip_tags(match.group(2))).strip()
        return "\n" + ("#" * level) + f" {title}\n"

    text = re.sub(
        r"<h([1-6])\b[^>]*>(.*?)</h\1>",
        heading,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def table_row(match: re.Match[str]) -> str:
        cells = [
            re.sub(r"\s+", " ", strip_tags(cell)).strip()
            for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", match.group(1), flags=re.IGNORECASE | re.DOTALL)
        ]
        cells = [cell for cell in cells if cell]
        return "\n" + " | ".join(cells) + "\n" if cells else "\n"

    text = re.sub(r"<tr\b[^>]*>(.*?)</tr>", table_row, text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</(p|li|tr|blockquote|div|section|header|table)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</t[dh]>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def current_section(lines: list[str], idx: int) -> str:
    for j in range(idx, -1, -1):
        line = lines[j].strip()
        if re.match(r"^#{1,6}\s+\S", line):
            return line
    return ""


def context(lines: list[str], idx: int, radius: int = 2) -> str:
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    return " ".join(lines[start:end])


def audit_file(path: Path) -> dict[str, Any]:
    text = read(path)
    lines = text.splitlines()
    findings = []
    for idx, line in enumerate(lines):
        for name, pattern in CLAIM_PATTERNS.items():
            if not pattern.search(line):
                continue
            ctx = context(lines, idx)
            section = current_section(lines, idx)
            allowed = bool(ALLOWED_CONTEXT.search(ctx) or ALLOWED_CONTEXT.search(section))
            if not allowed:
                findings.append(
                    {
                        "path": str(path.relative_to(ROOT)),
                        "line": idx + 1,
                        "claim_type": name,
                        "section": section,
                        "line_text": line.strip(),
                        "context": ctx.strip(),
                    }
                )
    return {
        "path": str(path.relative_to(ROOT)),
        "findings": findings,
        "n_findings": len(findings),
    }


def build_report() -> dict[str, Any]:
    docs = [audit_file(path) for path in FILES]
    findings = [finding for doc in docs for finding in doc["findings"]]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_pre_audit_claim_labeling.py",
        "policy": "Old held-out/stacking/ceiling claims must be locally labeled as pre-audit, historical, original, retained, or no longer deployment evidence.",
        "passed": not findings,
        "claim_patterns": sorted(CLAIM_PATTERNS),
        "findings": findings,
        "docs": docs,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Pre-Audit Claim Labeling Audit - 2026-05-08",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Findings: `{len(report['findings'])}`",
        "",
    ]
    if report["findings"]:
        lines.extend(["## Findings", ""])
        for finding in report["findings"]:
            lines.append(
                f"- `{finding['path']}:{finding['line']}` `{finding['claim_type']}` "
                f"in section `{finding['section']}`: {finding['line_text']}"
            )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"passed": report["passed"], "findings": len(report["findings"])}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
