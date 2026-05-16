#!/usr/bin/env python3
"""Audit T3 complete33 sensitivity wording for headline overclaim."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "t3_complete33_claim_labeling_audit_20260509.json"
OUT_MD = RESULTS / "t3_complete33_claim_labeling_audit_20260509.md"

FILES = [
    ROOT / "paper.md",
    ROOT / "CURRENT_PAPER.html",
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    ROOT / "task_plan.md",
    ROOT / "progress.md",
    ROOT / "findings.md",
    RESULTS / "thread_goal_completion_audit_20260508.md",
    RESULTS / "current_best_pipeline_artifact_index_20260508.md",
]

MENTION = re.compile(
    r"\b(complete[-_ ]?33|0\.4281|0\.4010|N\s*=\s*88|N=`88`|N=88)\b",
    re.IGNORECASE,
)
DANGEROUS = re.compile(
    r"\b(headline|canonical|audit[- ]truth|current\s+T3|deployment|deployable|"
    r"breakthrough|ceiling break|best|promote|promotable|replacement|"
    r"complete|achieved|goal_complete)\b",
    re.IGNORECASE,
)
ALLOWED = re.compile(
    r"\b(sensitivity|sensitivity-only|not a headline|not headline|not canonical|"
    r"not promotable|no canonical|no T3 metric change|no T3 metric|"
    r"minimal valid-range|minimal N\s*=\s*95|minimal valid-label|"
    r"partial(?:ly)? missing|complete-case|stricter complete|"
    r"target/provenance hardening|target hygiene|not a ceiling break|"
    r"lowers audit truth|target lowers audit truth|"
    r"not a new model result|does not move T3|current minimal|"
    r"valid-range-corrected 0\.3784|audit truth is 0\.3784|"
    r"underperforms old iter5|excluded additional)\b",
    re.IGNORECASE,
)
ALLOWED_GUARD_CONTEXT = re.compile(
    r"\b(claim-label guard|claim labeling audit|claim-labeling audit|claim-guard|"
    r"artifact and claim-guard snippets)\b",
    re.IGNORECASE,
)

REQUIRED_SNIPPETS = {
    "paper.md": [
        "The complete-33 results are sensitivity-only",
        "minimal valid-range result replaces",
        "valid-range-corrected 0.3784 -> 0.150 cliff",
    ],
    "CLAUDE.md": [
        "Complete33-validrange sensitivity is",
        "not a headline",
        "target hygiene correction, not a ceiling break",
    ],
    "AGENTS.md": [
        "complete33-validrange sensitivity N=88",
        "not a headline",
        "Complete33-validrange N=88 current `0.4281` is sensitivity-only",
    ],
    "results/thread_goal_completion_audit_20260508.md": [
        "complete33 N=`88`",
        "not a headline",
    ],
    "results/current_best_pipeline_artifact_index_20260508.md": [
        "Complete33-validrange sensitivities",
        "sensitivity-only",
    ],
}


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


def read(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return normalize_html(text) if path.suffix == ".html" else text


def current_scope(path: Path, text: str) -> str:
    rel = str(path.relative_to(ROOT))
    if rel == "task_plan.md":
        marker = "\n---\n\n# ACTIVE MISSION"
        return text.split(marker, 1)[0]
    if rel == "progress.md":
        marker = "\n## Session: 2026-05-05"
        return text.split(marker, 1)[0]
    if rel == "findings.md":
        early = text.split("\n## F31", 1)[0]
        tail_marker = "\n## F-iter41-20260508"
        tail = text.split(tail_marker, 1)[1] if tail_marker in text else ""
        return early + "\n## F-iter41-20260508" + tail
    return text


def current_section(lines: list[str], idx: int) -> str:
    for j in range(idx, -1, -1):
        line = lines[j].strip()
        if re.match(r"^#{1,6}\s+\S", line):
            return line
    return ""


def context(lines: list[str], idx: int, radius: int = 6) -> str:
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    return " ".join(lines[start:end])


def audit_file(path: Path) -> dict[str, Any]:
    text = current_scope(path, read(path))
    rel = str(path.relative_to(ROOT))
    lines = text.splitlines()
    findings = []
    mentions = 0
    for idx, line in enumerate(lines):
        if not MENTION.search(line):
            continue
        mentions += 1
        ctx = context(lines, idx)
        section = current_section(lines, idx)
        trigger_text = f"{line} {section}"
        if not DANGEROUS.search(trigger_text):
            continue
        if ALLOWED.search(ctx) or ALLOWED.search(section) or ALLOWED_GUARD_CONTEXT.search(ctx):
            continue
        findings.append(
            {
                "path": rel,
                "line": idx + 1,
                "section": section,
                "line_text": line.strip(),
                "context": ctx.strip(),
            }
        )
    missing = [
        snippet
        for snippet in REQUIRED_SNIPPETS.get(rel, [])
        if snippet not in text
    ]
    return {
        "path": rel,
        "current_scope_lines": len(lines),
        "mentions": mentions,
        "findings": findings,
        "missing_required_snippets": missing,
    }


def build_report() -> dict[str, Any]:
    docs = [audit_file(path) for path in FILES if path.exists()]
    findings = [row for doc in docs for row in doc["findings"]]
    missing = [
        {"path": doc["path"], "missing_required_snippet": snippet}
        for doc in docs
        for snippet in doc["missing_required_snippets"]
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_t3_complete33_claim_labeling.py",
        "policy": (
            "T3 iter47 complete33/N=88 values may appear only as sensitivity-only "
            "complete-case or partial-missing target-hygiene context. The current "
            "T3 internal headline remains the N=95 minimal valid-range CCC 0.3784."
        ),
        "passed": not findings and not missing,
        "claim_patterns": ["complete33", "0.4281", "0.4010", "N=88"],
        "findings": findings,
        "missing_required_snippets": missing,
        "docs": docs,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# T3 Complete33 Claim Labeling Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Findings: `{len(report['findings'])}`",
        f"- Missing required snippets: `{len(report['missing_required_snippets'])}`",
        "",
    ]
    if report["findings"]:
        lines.extend(["## Findings", ""])
        for row in report["findings"]:
            lines.append(
                f"- `{row['path']}:{row['line']}` in section `{row['section']}`: {row['line_text']}"
            )
    if report["missing_required_snippets"]:
        lines.extend(["## Missing Required Snippets", ""])
        for row in report["missing_required_snippets"]:
            lines.append(f"- `{row['path']}` missing `{row['missing_required_snippet']}`")
    lines.extend(["", "## Scanned Documents", ""])
    for doc in report["docs"]:
        lines.append(
            f"- `{doc['path']}`: mentions `{doc['mentions']}`, findings `{len(doc['findings'])}`, "
            f"missing snippets `{len(doc['missing_required_snippets'])}`"
        )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "findings": len(report["findings"]),
                "missing_required_snippets": len(report["missing_required_snippets"]),
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
