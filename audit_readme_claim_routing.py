#!/usr/bin/env python3
"""Audit root README current-claim routing and stale SSL-claim quarantine."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
README = ROOT / "README.md"
OUT_JSON = RESULTS / "readme_claim_routing_audit_20260509.json"
OUT_MD = RESULTS / "readme_claim_routing_audit_20260509.md"

CURRENT_REQUIRED = [
    "Current Post-Audit WearGait-PD Benchmark",
    "T1 canonical floor",
    "0.6550",
    "T1 strongest candidate",
    "0.7366",
    "N=93",
    "T3 current",
    "0.3784",
    "0.150",
    "run_t3_iter47_invalid_code_fix.py",
    "render_current_paper.py",
    "CURRENT_PAPER.html",
    "legacy/retracted/pre-audit",
    "0.868",
    "0.776",
    "target-contaminated",
]

FORBIDDEN_HEADLINES = [
    "Healthy-Control-Anchored Semi-Supervised Ranking Improves Calibration",
]

DANGEROUS_PATTERNS = [
    r"0\.868",
    r"0\.776",
    r"0\.852",
    r"0\.882",
    r"0\.893",
    r"CCC\s+\*\*0\.87\*\*",
    r"T1 MAE\s*=\s*0\.986",
    r"\bSSL ranking\b",
    r"\bXGBRanker\b",
    r"healthy controls as calibration anchors",
    r"P5 SSL Ranking",
    r"This work \(T3, SSL\)",
    r"This work \(T1, SSL\)",
    r"Stage 1\s+[—-]\s+XGBRanker",
    r"trained\s+\*\*once on all 178 subjects\*\*",
    r"trained on all 178 subjects",
    r"run_compression_ablation\.py.*PRIMARY",
]

GUARD_WORDS = re.compile(
    r"\b("
    r"historical|legacy|pre-audit|retracted|target-contaminated|"
    r"not current|not evidence|not deployable|not cite|do not cite|"
    r"do not treat|archaeology|superseded|old|invalid"
    r")\b",
    re.IGNORECASE,
)

BAD_CURRENT_ROUTE_PATTERNS = [
    r"current .*generate_paper(?:_v4)?\.py",
    r"generate_paper(?:_v4)?\.py.*current",
    r"current .*NEW4?\.html",
    r"NEW4?\.html.*authoritative",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def context(lines: list[str], line_index: int, radius: int = 2) -> str:
    start = max(0, line_index - radius)
    end = min(len(lines), line_index + radius + 1)
    return " ".join(line.strip() for line in lines[start:end] if line.strip())


def dangerous_hits(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    hits: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        for pattern in DANGEROUS_PATTERNS:
            if not re.search(pattern, line, flags=re.IGNORECASE):
                continue
            ctx = context(lines, idx)
            guarded = bool(GUARD_WORDS.search(ctx))
            hits.append(
                {
                    "line": idx + 1,
                    "pattern": pattern,
                    "line_text": line.strip(),
                    "context": ctx,
                    "guarded": guarded,
                }
            )
    return hits


def bad_current_route_hits(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    hits: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        for pattern in BAD_CURRENT_ROUTE_PATTERNS:
            if not re.search(pattern, line, flags=re.IGNORECASE):
                continue
            ctx = context(lines, idx)
            if GUARD_WORDS.search(ctx):
                continue
            hits.append(
                {
                    "line": idx + 1,
                    "pattern": pattern,
                    "line_text": line.strip(),
                    "context": ctx,
                }
            )
    return hits


def build_report() -> dict[str, Any]:
    text = read_text(README)
    missing_required = [snippet for snippet in CURRENT_REQUIRED if snippet not in text]
    forbidden_headline_hits = [snippet for snippet in FORBIDDEN_HEADLINES if snippet in text]
    dangerous = dangerous_hits(text)
    unguarded_dangerous = [hit for hit in dangerous if not hit["guarded"]]
    bad_routes = bad_current_route_hits(text)
    primary_bad = [
        hit
        for hit in dangerous
        if hit["pattern"] == r"run_compression_ablation\.py.*PRIMARY"
        and not hit["guarded"]
    ]
    current_paper_route_ok = (
        "uv run python render_current_paper.py" in text
        and "CURRENT_PAPER.html" in text
        and "generate_paper_v4.py" in text
        and bool(re.search(r"generate_paper_v4\.py.*(?:Legacy|legacy|Historical|historical|stale)", text))
    )
    hard_failures = []
    if missing_required:
        hard_failures.append({"check": "missing_required_current_readme_snippets", "items": missing_required})
    if forbidden_headline_hits:
        hard_failures.append({"check": "forbidden_old_headline", "items": forbidden_headline_hits})
    if unguarded_dangerous:
        hard_failures.append({"check": "unguarded_stale_ssl_or_number_claim", "items": unguarded_dangerous})
    if bad_routes:
        hard_failures.append({"check": "bad_current_paper_route", "items": bad_routes})
    if primary_bad:
        hard_failures.append({"check": "historical_runner_marked_primary", "items": primary_bad})
    if not current_paper_route_ok:
        hard_failures.append(
            {
                "check": "current_paper_route_missing_or_legacy_route_unlabeled",
                "evidence": {
                    "has_render_command": "uv run python render_current_paper.py" in text,
                    "has_current_output": "CURRENT_PAPER.html" in text,
                    "has_generate_v4": "generate_paper_v4.py" in text,
                    "legacy_generate_v4_labeled": bool(
                        re.search(r"generate_paper_v4\.py.*(?:Legacy|legacy|Historical|historical|stale)", text)
                    ),
                },
            }
        )

    passed = not hard_failures
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_readme_claim_routing.py",
        "policy": (
            "README.md must route readers to current post-audit T1/T3 claims and may mention "
            "old SSL/XGBRanker numbers only when locally guarded as legacy/retracted/pre-audit "
            "or target-contaminated."
        ),
        "passed": passed,
        "decision": "readme_current_claim_route_guard_passed" if passed else "readme_current_claim_route_guard_failed",
        "readme_sha256": sha256(README),
        "missing_required": missing_required,
        "forbidden_headline_hits": forbidden_headline_hits,
        "dangerous_hits": dangerous,
        "unguarded_dangerous_hits": unguarded_dangerous,
        "bad_current_route_hits": bad_routes,
        "current_paper_route_ok": current_paper_route_ok,
        "kimi_consult_summary": (
            "Kimi confirmed README.md is un-audited for stale numerical/methodology claims; "
            "a README patch plus guard is non-redundant provided no canonical LOOCV is in flight."
        ),
        "hard_failures": hard_failures,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# README Claim Routing Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Unguarded stale hits: `{len(report['unguarded_dangerous_hits'])}`",
        f"- Missing required snippets: `{len(report['missing_required'])}`",
        f"- Bad current-route hits: `{len(report['bad_current_route_hits'])}`",
        "",
        "## Required Current README Claims",
        "",
    ]
    for snippet in CURRENT_REQUIRED:
        status = "present" if snippet not in report["missing_required"] else "missing"
        lines.append(f"- `{snippet}`: {status}")
    lines.extend(["", "## Dangerous Hits", ""])
    if report["dangerous_hits"]:
        for hit in report["dangerous_hits"]:
            marker = "guarded" if hit["guarded"] else "UNGUARDED"
            lines.append(
                f"- `{hit['line']}` `{hit['pattern']}` {marker}: {hit['line_text']}"
            )
    else:
        lines.append("- none")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- `{failure['check']}`")
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
                "unguarded_stale_hits": len(report["unguarded_dangerous_hits"]),
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
