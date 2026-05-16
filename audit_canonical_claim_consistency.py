#!/usr/bin/env python3
"""Audit current docs for stale canonical-number claims.

This catches a different paper-facing failure mode than unit tests: old T3
numbers can remain in narrative files after target audits. Historical mentions
are allowed only when the surrounding text labels them as historical,
superseded, target-contaminated, retracted, or time-local.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "canonical_claim_consistency_audit_20260508.json"
OUT_MD = RESULTS / "canonical_claim_consistency_audit_20260508.md"

CURRENT_EXPECTED = {
    "t1_canonical_ccc": "0.6550",
    "t1_candidate_ccc": "0.7170",
    "t3_current_ccc": "0.3784",
    "t3_loso_ccc": "0.150",
}

STALE_NUMBERS = {
    "0.5227": "old iter5 T3 target-contaminated LOOCV",
    "0.341": "old iter16 target-contaminated/historical LOSO",
    "0.3948": "iter41 all-missing-only correction superseded by iter47",
}

CLAIM_WORDS = re.compile(
    r"\b(canonical|internal|headline|audit[- ]truth|deployment|"
    r"deployable|unchanged|remains|remain|holds|hold|truth|reference)\b",
    re.IGNORECASE,
)

ALLOWED_CONTEXT = re.compile(
    r"\b(old|historical|history|target-contaminated|superseded|retracted|"
    r"pre-audit|post-leakage|then-believed|then-current|at that point|"
    r"before iter4[17]|after iter4[17]|no longer|not current|not canonical|"
    r"previous|archived|was canonical|was then|retained only)\b",
    re.IGNORECASE,
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def html_to_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def slice_current(path: Path, text: str) -> str:
    rel = str(path.relative_to(ROOT))
    if rel == "task_plan.md":
        marker = "\n---\n\n# ACTIVE MISSION — iter26"
        return text.split(marker, 1)[0]
    if rel == "progress.md":
        marker = "\n## Session: 2026-05-05"
        return text.split(marker, 1)[0]
    if rel == "findings.md":
        # Keep early 2026-05-08 current-audit sections plus the post-target-audit tail.
        early = text.split("\n## F31", 1)[0]
        tail_marker = "\n## F-iter41-20260508"
        tail = text.split(tail_marker, 1)[1] if tail_marker in text else ""
        return early + "\n## F-iter41-20260508" + tail
    if path.suffix == ".html":
        return html_to_text(text)
    return text


def context_lines(lines: list[str], idx: int, radius: int = 1) -> str:
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    return " ".join(lines[start:end])


def stale_claim_findings(path: Path, current_text: str) -> list[dict[str, Any]]:
    lines = current_text.splitlines()
    findings: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        for number, description in STALE_NUMBERS.items():
            if number not in line:
                continue
            ctx = context_lines(lines, i)
            if not CLAIM_WORDS.search(ctx):
                continue
            if ALLOWED_CONTEXT.search(ctx):
                continue
            findings.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "line": i + 1,
                    "number": number,
                    "description": description,
                    "line_text": line.strip(),
                    "context": ctx.strip(),
                }
            )
    return findings


def required_snippet_findings(path: Path, current_text: str) -> list[dict[str, Any]]:
    rel = str(path.relative_to(ROOT))
    required_by_file = {
        "CLAUDE.md": [
            "T3 iter47",
            "0.3784",
            "0.150",
            "target-contaminated",
            "0.5227",
        ],
        "AGENTS.md": [
            "Current honest canonical numbers",
            "0.3784",
            "0.150",
            "not current canonicals",
        ],
        "paper.md": [
            "valid-range-corrected T3 LOOCV CCC = 0.3784",
            "valid-range LOSO transportability falling to CCC = 0.150",
            "target-contaminated",
        ],
        "results/thread_goal_completion_audit_20260508.md": [
            "Ablation V3 cache provenance audit",
            "goal is **not complete**",
            "0.3784",
        ],
        "results/current_best_pipeline_artifact_index_20260508.md": [
            "audit_ablation_v3_cache_provenance.py",
            "do_not_synthesize_clean_manifest",
        ],
    }
    missing = []
    for snippet in required_by_file.get(rel, []):
        if snippet not in current_text:
            missing.append(
                {
                    "path": rel,
                    "missing_required_snippet": snippet,
                }
            )
    return missing


def main() -> None:
    paths = [
        ROOT / "CLAUDE.md",
        ROOT / "AGENTS.md",
        ROOT / "paper.md",
        ROOT / "CURRENT_PAPER.html",
        ROOT / "task_plan.md",
        ROOT / "progress.md",
        ROOT / "findings.md",
        ROOT / "results" / "thread_goal_completion_audit_20260508.md",
        ROOT / "results" / "current_best_pipeline_artifact_index_20260508.md",
    ]
    docs = []
    stale_findings: list[dict[str, Any]] = []
    missing_snippets: list[dict[str, Any]] = []
    for path in paths:
        text = read(path)
        current_text = slice_current(path, text)
        stale = stale_claim_findings(path, current_text)
        missing = required_snippet_findings(path, current_text)
        stale_findings.extend(stale)
        missing_snippets.extend(missing)
        docs.append(
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "current_scope_lines": len(current_text.splitlines()),
                "stale_findings": stale,
                "missing_required_snippets": missing,
            }
        )

    passed = not stale_findings and not missing_snippets
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_canonical_claim_consistency.py",
        "policy": (
            "Old T3 numbers may appear only when labelled historical, superseded, "
            "target-contaminated, retracted, archived, or time-local."
        ),
        "current_expected": CURRENT_EXPECTED,
        "stale_numbers": STALE_NUMBERS,
        "passed": passed,
        "stale_findings": stale_findings,
        "missing_required_snippets": missing_snippets,
        "docs": docs,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Canonical Claim Consistency Audit - 2026-05-08",
        "",
        report["policy"],
        "",
        "## Expected Current Claims",
        "",
    ]
    for key, value in CURRENT_EXPECTED.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Result", "", f"- Passed: `{passed}`"])
    lines.append(f"- Stale findings: `{len(stale_findings)}`")
    lines.append(f"- Missing required snippets: `{len(missing_snippets)}`")
    if stale_findings:
        lines.extend(["", "## Stale Findings", ""])
        for row in stale_findings:
            lines.append(
                f"- `{row['path']}:{row['line']}` `{row['number']}` "
                f"({row['description']}): {row['line_text']}"
            )
    if missing_snippets:
        lines.extend(["", "## Missing Required Snippets", ""])
        for row in missing_snippets:
            lines.append(
                f"- `{row['path']}` missing `{row['missing_required_snippet']}`"
            )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"passed": passed, "stale_findings": len(stale_findings), "missing_required_snippets": len(missing_snippets)}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
