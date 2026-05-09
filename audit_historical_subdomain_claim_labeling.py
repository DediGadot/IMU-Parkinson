#!/usr/bin/env python3
"""Audit paper labeling for historical subdomain and sensor-ablation claims."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "historical_subdomain_claim_labeling_audit_20260509.json"
OUT_MD = RESULTS / "historical_subdomain_claim_labeling_audit_20260509.md"

FILES = [ROOT / "paper.md", ROOT / "CURRENT_PAPER.html"]

CLAIM_PATTERNS = {
    "subdomain_mae_2_61": re.compile(r"\b2\.61\b"),
    "observable_motor_subdomain": re.compile(r"observable motor subdomain", re.IGNORECASE),
    "subdomain_prediction": re.compile(r"subdomain prediction", re.IGNORECASE),
    "development_test_item_subset": re.compile(r"N\s*=\s*117\s+development,\s*30\s+test", re.IGNORECASE),
    "sensor_ablation_wrist_mae": re.compile(r"\b7\.58\b"),
    "lower_back_redundant": re.compile(r"lower back sensor is entirely redundant", re.IGNORECASE),
    "clinically_actionable_subscores": re.compile(r"clinically actionable prediction", re.IGNORECASE),
}

ALLOWED_CONTEXT = re.compile(
    r"\b(pre-audit|historical|retained|context|hypothesis-generating|"
    r"current post-audit|post-audit T1|residual audit|not a deployment|"
    r"not deployment|strict inductive|claim-label)\b",
    re.IGNORECASE,
)


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def normalize_html(text: str) -> str:
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


def read(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return normalize_html(text) if path.suffix == ".html" else text


def current_section(lines: list[str], idx: int) -> str:
    for j in range(idx, -1, -1):
        line = lines[j].strip()
        if "|" in line:
            continue
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
        for claim_type, pattern in CLAIM_PATTERNS.items():
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
                        "claim_type": claim_type,
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
    docs = [audit_file(path) for path in FILES if path.exists()]
    findings = [finding for doc in docs for finding in doc["findings"]]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_historical_subdomain_claim_labeling.py",
        "policy": (
            "Historical sensor-ablation and subdomain-prediction claims must be "
            "locally labeled as pre-audit/historical/context, or tied explicitly "
            "to current post-audit T1 and residual-audit support."
        ),
        "passed": not findings,
        "claim_patterns": sorted(CLAIM_PATTERNS),
        "findings": findings,
        "docs": docs,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Historical Subdomain Claim Labeling Audit - 2026-05-09",
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
