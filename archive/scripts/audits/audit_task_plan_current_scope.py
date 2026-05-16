#!/usr/bin/env python3
"""Audit task_plan.md current-scope criteria and archive boundary."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TASK_PLAN = ROOT / "task_plan.md"
OUT_JSON = RESULTS / "task_plan_current_scope_audit_20260509.json"
OUT_MD = RESULTS / "task_plan_current_scope_audit_20260509.md"

REQUIRED_CURRENT_SNIPPETS = [
    "CANONICAL NUMBERS LIVE IN `CLAUDE.md`",
    "## Current completion criteria (post-iter47)",
    "goal remains **not complete**",
    "Current T1 canonical floor: `0.6550`",
    "Current T1 ceiling-break candidate: `0.7170`",
    "Current T3 internal headline: `0.3784`",
    "current T3 LOSO two-way mean is `0.150`",
    "Old T3 `0.5227`, `0.4694`, `0.341`, `0.3948`, and `0.4092`",
    "no local WearGait-only model actions remaining",
]

LEGACY_NUMBERS = {
    "0.5227": "old iter5 T3 target-contaminated LOOCV",
    "0.4694": "old iter16 LOOCV-IPW sensitivity",
    "0.341": "old iter16 target-contaminated LOSO",
    "0.3948": "iter41 all-missing-only correction superseded by iter47",
    "0.4092": "pre-iter5 T3 hy_residual baseline",
    "0.43": "old historical target tier",
    "0.46": "old historical breakthrough tier",
    "0.50": "old historical unlikely tier",
}

DANGEROUS_CONTEXT = re.compile(
    r"\b(success|criteria|target|floor|breakthrough|canonical|headline|"
    r"current|active|deployment|deployable|complete|goal_complete)\b",
    re.IGNORECASE,
)
LEGACY_TIER_CONTEXT = re.compile(
    r"\b(Tier|T1 LOOCV|T3 LOOCV|success criteria|process win|unlikely)\b",
    re.IGNORECASE,
)
ALLOWED_LEGACY_CONTEXT = re.compile(
    r"\b(old|historical|target-contaminated|superseded|sensitivity-only|"
    r"not active success criteria|not canonical|not current|caveat|"
    r"retracted|archived|archive|target hygiene|previous)\b",
    re.IGNORECASE,
)


def split_scope(text: str) -> tuple[str, str, dict[str, Any]]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    boundary_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ACTIVE MISSION") and "iter26" in stripped:
            boundary_idx = idx
            break
    if boundary_idx is None:
        return text, "", {"found": False, "line": None, "offset": None}

    marker_idx = boundary_idx
    if boundary_idx >= 2 and lines[boundary_idx - 2].strip() == "---" and not lines[boundary_idx - 1].strip():
        marker_idx = boundary_idx - 2
    boundary_offset = offsets[marker_idx]
    metadata = {
        "found": True,
        "line": marker_idx + 1,
        "heading_line": boundary_idx + 1,
        "heading": lines[boundary_idx].strip(),
        "offset": boundary_offset,
    }
    return text[:boundary_offset], text[boundary_offset:], metadata


def line_context(lines: list[str], idx: int, radius: int = 2) -> str:
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    return " ".join(line.strip() for line in lines[start:end] if line.strip())


def find_current_scope_legacy_findings(current: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = current.splitlines()
    for idx, line in enumerate(lines):
        ctx = line_context(lines, idx)
        for number, description in LEGACY_NUMBERS.items():
            if number not in line:
                continue
            if number in {"0.43", "0.46", "0.50"} and not LEGACY_TIER_CONTEXT.search(ctx):
                continue
            if not DANGEROUS_CONTEXT.search(ctx):
                continue
            if ALLOWED_LEGACY_CONTEXT.search(ctx):
                continue
            findings.append(
                {
                    "line": idx + 1,
                    "number": number,
                    "description": description,
                    "line_text": line.strip(),
                    "context": ctx,
                }
            )
    return findings


def check_archive(archive: str, boundary: dict[str, Any], current: str) -> list[dict[str, Any]]:
    old_thresholds = {number: (number in archive) for number in ["0.4092", "0.43", "0.46", "0.50"]}
    checks = [
        {
            "name": "historical_boundary_found",
            "passed": bool(boundary.get("found")),
            "evidence": boundary,
        },
        {
            "name": "top_banner_warns_archive_below",
            "passed": "BELOW IT IS A HISTORICAL ARCHIVE" in current,
            "evidence": "BELOW IT IS A HISTORICAL ARCHIVE",
        },
        {
            "name": "archive_contains_legacy_success_table",
            "passed": "## Success Criteria" in archive and "Tier 0" in archive,
            "evidence": {
                "success_criteria_present": "## Success Criteria" in archive,
                "tier0_present": "Tier 0" in archive,
            },
        },
        {
            "name": "archive_contains_old_threshold_values",
            "passed": all(old_thresholds.values()),
            "evidence": old_thresholds,
        },
        {
            "name": "current_scope_has_no_legacy_success_header",
            "passed": "## Success Criteria" not in current and "| Tier | T1 LOOCV | T3 LOOCV |" not in current,
            "evidence": {
                "success_criteria_header_in_current": "## Success Criteria" in current,
                "legacy_tier_table_in_current": "| Tier | T1 LOOCV | T3 LOOCV |" in current,
            },
        },
    ]
    return checks


def build_report() -> dict[str, Any]:
    text = TASK_PLAN.read_text(encoding="utf-8")
    current, archive, boundary = split_scope(text)
    missing = [snippet for snippet in REQUIRED_CURRENT_SNIPPETS if snippet not in current]
    legacy_findings = find_current_scope_legacy_findings(current)
    archive_checks = check_archive(archive, boundary, current)
    hard_failures = []
    if missing:
        hard_failures.append(
            {
                "check": "current_scope_required_snippets",
                "missing": missing,
            }
        )
    if legacy_findings:
        hard_failures.append(
            {
                "check": "current_scope_legacy_success_findings",
                "findings": legacy_findings,
            }
        )
    for check in archive_checks:
        if not check["passed"]:
            hard_failures.append(
                {
                    "check": check["name"],
                    "evidence": check["evidence"],
                }
            )

    passed = not hard_failures
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_task_plan_current_scope.py",
        "policy": (
            "The active head of task_plan.md must carry explicit post-iter47 "
            "completion criteria, while older success tiers remain archive-bound."
        ),
        "passed": passed,
        "decision": "task_plan_current_scope_guard_passed" if passed else "task_plan_current_scope_guard_failed",
        "task_plan": str(TASK_PLAN.relative_to(ROOT)),
        "historical_boundary": boundary,
        "current_scope": {
            "line_count": len(current.splitlines()),
            "required_snippet_count": len(REQUIRED_CURRENT_SNIPPETS),
            "missing_required_snippets": missing,
            "legacy_success_findings": legacy_findings,
            "contains_current_completion_criteria": "## Current completion criteria (post-iter47)" in current,
            "contains_goal_not_complete": "goal remains **not complete**" in current,
        },
        "archive_scope": {
            "line_count": len(archive.splitlines()),
            "checks": archive_checks,
        },
        "hard_failures": hard_failures,
        "warnings": [],
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Task Plan Current Scope Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Historical boundary line: `{report['historical_boundary'].get('line')}`",
        f"- Current-scope lines: `{report['current_scope']['line_count']}`",
        f"- Archive-scope lines: `{report['archive_scope']['line_count']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Current Scope",
        "",
        f"- Required snippets: `{report['current_scope']['required_snippet_count']}`",
        f"- Missing snippets: `{len(report['current_scope']['missing_required_snippets'])}`",
        f"- Legacy success findings: `{len(report['current_scope']['legacy_success_findings'])}`",
        "",
        "## Archive Boundary",
        "",
    ]
    for check in report["archive_scope"]["checks"]:
        lines.append(f"- `{check['name']}`: `{check['passed']}`")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- `{failure['check']}`: `{failure}`")
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failures": len(report["hard_failures"]),
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
