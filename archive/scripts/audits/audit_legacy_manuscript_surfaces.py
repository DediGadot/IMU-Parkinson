#!/usr/bin/env python3
"""Audit legacy manuscript surfaces for visible stale-claim quarantine."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "legacy_manuscript_surface_audit_20260509.json"
OUT_MD = RESULTS / "legacy_manuscript_surface_audit_20260509.md"

BANNER = "STALE -- LEGACY MANUSCRIPT SURFACE -- DO NOT CITE"
CURRENT_POINTERS = [
    "CLAUDE.md",
    "paper.md",
    "CURRENT_PAPER.html",
    "render_current_paper.py",
    "0.6550",
    "0.7366",
    "0.3784",
    "0.150",
    "target-contaminated",
]

LEGACY_SURFACES = [
    "paper.tex",
    "paper_new2.tex",
    "CALIB-EXPERIMENTS.md",
    "HOW.md",
    "REPRODUCIBILITY.md",
    "review_report.md",
    "review_report_numbers.md",
    "generate_paper.py",
    "generate_paper_v2.py",
    "generate_paper_v3.py",
    "generate_paper_v4.py",
    "generate_paper_v5.py",
    "generate_paper_v6.py",
    "NEW4.html",
    "NEW5.html",
    "NEW6.html",
]

DANGEROUS_PATTERNS = [
    r"0\.868",
    r"0\.776",
    r"0\.986",
    r"0\.882",
    r"CCC\s*=\s*0\.865",
    r"CCC\s*=\s*0\.864",
    r"Healthy-control-anchored",
    r"healthy controls? as calibration anchors",
    r"semi-supervised ranking",
    r"SSL ranking",
    r"XGBRanker",
    r"trained on all 178",
    r"This work \(T[13], SSL\)",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def normalize(text: str) -> str:
    text = html.unescape(text)
    text = text.replace(r"\_", "_")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def line_hits(text: str, pattern: str) -> list[dict[str, Any]]:
    hits = []
    rx = re.compile(pattern, flags=re.IGNORECASE)
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if rx.search(line):
            start = max(0, idx - 2)
            end = min(len(lines), idx + 1)
            hits.append(
                {
                    "line": idx,
                    "pattern": pattern,
                    "line_text": line.strip()[:300],
                    "context": " ".join(x.strip() for x in lines[start:end] if x.strip())[:600],
                }
            )
    return hits


def audit_surface(path_str: str) -> dict[str, Any]:
    path = ROOT / path_str
    exists = path.exists()
    if not exists:
        return {
            "path": path_str,
            "exists": False,
            "sha256": None,
            "banner_present_near_top": False,
            "missing_current_pointers": CURRENT_POINTERS,
            "dangerous_hit_count": 0,
            "sample_dangerous_hits": [],
        }

    text = read_text(path)
    lines = text.splitlines()
    top_lines = lines[:140]
    if path.suffix.lower() in {".html", ".htm"}:
        for idx, line in enumerate(lines):
            if "<body" in line.lower():
                top_lines.extend(lines[idx : idx + 60])
                break
    top = "\n".join(top_lines)
    normalized_top = normalize(top)
    normalized_all = normalize(text)
    dangerous: list[dict[str, Any]] = []
    for pattern in DANGEROUS_PATTERNS:
        dangerous.extend(line_hits(text, pattern))
    return {
        "path": path_str,
        "exists": True,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "banner_present_near_top": BANNER in normalized_top,
        "missing_current_pointers": [
            snippet for snippet in CURRENT_POINTERS if snippet not in normalized_top
        ],
        "contains_current_render_route": "render_current_paper.py" in normalized_all
        and "CURRENT_PAPER.html" in normalized_all,
        "dangerous_hit_count": len(dangerous),
        "sample_dangerous_hits": dangerous[:12],
    }


def build_report() -> dict[str, Any]:
    surfaces = [audit_surface(path) for path in LEGACY_SURFACES]
    hard_failures = []
    for row in surfaces:
        if not row["exists"]:
            hard_failures.append({"check": "legacy_surface_missing", "surface": row})
            continue
        if not row["banner_present_near_top"]:
            hard_failures.append({"check": "missing_visible_legacy_banner", "surface": row})
        if row["missing_current_pointers"]:
            hard_failures.append({"check": "missing_current_claim_pointer", "surface": row})
        if row["dangerous_hit_count"] and not row["banner_present_near_top"]:
            hard_failures.append({"check": "dangerous_stale_claim_without_banner", "surface": row})

    passed = not hard_failures
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_legacy_manuscript_surfaces.py",
        "policy": (
            "Legacy manuscript/narrative files may retain stale SSL/XGBRanker numbers only when "
            "they carry a visible near-top stale/pre-audit do-not-cite banner pointing to "
            "CLAUDE.md, paper.md, render_current_paper.py, and CURRENT_PAPER.html."
        ),
        "passed": passed,
        "decision": "legacy_manuscript_surfaces_quarantined" if passed else "legacy_manuscript_surface_quarantine_failed",
        "banner": BANNER,
        "current_pointers": CURRENT_POINTERS,
        "legacy_surfaces": surfaces,
        "total_dangerous_hits": sum(row.get("dangerous_hit_count", 0) for row in surfaces),
        "hard_failures": hard_failures,
        "kimi_consult_summary": (
            "Kimi recommended bannering retained legacy manuscript/builder surfaces, not deleting "
            "or rewriting the historical claims, and not running new model code."
        ),
        "claude_consult_status": "failed_low_credit",
        "glmcode_status": "not_available",
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Legacy Manuscript Surface Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Legacy surfaces checked: `{len(report['legacy_surfaces'])}`",
        f"- Total stale-pattern hits retained under banners: `{report['total_dangerous_hits']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Surfaces",
        "",
        "| Surface | Banner | Missing pointers | Stale hits |",
        "|---|---:|---:|---:|",
    ]
    for row in report["legacy_surfaces"]:
        lines.append(
            f"| `{row['path']}` | `{row.get('banner_present_near_top')}` | "
            f"`{len(row.get('missing_current_pointers', []))}` | `{row.get('dangerous_hit_count', 0)}` |"
        )
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- `{failure['check']}` on `{failure['surface'].get('path')}`")
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
                "surfaces": len(report["legacy_surfaces"]),
                "total_dangerous_hits": report["total_dangerous_hits"],
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
