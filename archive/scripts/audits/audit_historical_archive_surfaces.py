#!/usr/bin/env python3
"""Guard historical project-note surfaces against current-claim drift."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STAMP = "20260509"
OUT_JSON = RESULTS / f"historical_archive_surface_audit_{STAMP}.json"
OUT_MD = RESULTS / f"historical_archive_surface_audit_{STAMP}.md"

ARCHIVE_SURFACES = [
    "CONT.md",
    "EXP.md",
    "EXP-SUMMARY.md",
    "LEARNINGS.md",
    "VNEXT.md",
    "NEXTNEXT.md",
    "literature_review.md",
    "paper_supplement_iter33_gate_demo.md",
    "CODEX-PROPOSALS.md",
    "PROPOSALS.md",
    "leakage_onepager.html",
]

COMMON_MD_SNIPPETS = [
    "Archive status, 2026-05-09",
    "CLAUDE.md",
    "CURRENT_PAPER.html",
    "render_current_paper.py",
]

LEAKAGE_ONEPAGER_REQUIRED = [
    "Archive status, 2026-05-09",
    "Current T3 valid-range headline is iter47 CCC = 0.3784 / LOSO = 0.150",
    "run_t3_iter47_invalid_code_fix.py",
    "CCC = 0.3784, MAE = 7.528",
    "old iter5 T3 CCC = 0.5227 is superseded",
]

LEAKAGE_ONEPAGER_FORBIDDEN = [
    "Post-fix canonical results",
    "Headline T1 = 0.7366, T3 = 0.5227",
    '<td class="num clean">CCC = 0.5227, MAE = 7.525</td>',
]

ARCHIVE_PATTERNS = [
    re.compile(r"\b0\.5227\b"),
    re.compile(r"\b6\.89\b"),
    re.compile(r"\br\s*=\s*0\.860\b"),
    re.compile(r"\b0\.776\b"),
    re.compile(r"\b0\.878\b"),
    re.compile(r"\b0\.7219\b"),
]

GUARD_TERMS = (
    "archive",
    "historical",
    "superseded",
    "old",
    "not current",
    "not as a current",
    "not current deployment",
    "candidate",
    "caveat",
    "retracted",
)


@dataclass
class SurfaceResult:
    path: str
    exists: bool
    missing_required: list[str]
    forbidden_hits: list[str]
    unguarded_stale_lines: list[str]
    stale_pattern_hits: int


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def audit_surface(rel_path: str) -> SurfaceResult:
    path = ROOT / rel_path
    if not path.exists():
        return SurfaceResult(
            path=rel_path,
            exists=False,
            missing_required=["file exists"],
            forbidden_hits=[],
            unguarded_stale_lines=[],
            stale_pattern_hits=0,
        )

    text = read_text(path)
    required = LEAKAGE_ONEPAGER_REQUIRED if rel_path == "leakage_onepager.html" else COMMON_MD_SNIPPETS
    missing_required = [snippet for snippet in required if snippet not in text]

    forbidden_hits = []
    if rel_path == "leakage_onepager.html":
        forbidden_hits = [snippet for snippet in LEAKAGE_ONEPAGER_FORBIDDEN if snippet in text]

    stale_pattern_hits = 0
    unguarded_stale_lines = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not any(pattern.search(line) for pattern in ARCHIVE_PATTERNS):
            continue
        stale_pattern_hits += 1
        lowered = line.lower()
        if rel_path == "leakage_onepager.html" and "0.5227" in line and not any(term in lowered for term in GUARD_TERMS):
            unguarded_stale_lines.append(f"{line_no}: {line.strip()[:220]}")

    return SurfaceResult(
        path=rel_path,
        exists=True,
        missing_required=missing_required,
        forbidden_hits=forbidden_hits,
        unguarded_stale_lines=unguarded_stale_lines,
        stale_pattern_hits=stale_pattern_hits,
    )


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    surfaces = [audit_surface(path) for path in ARCHIVE_SURFACES]
    hard_failures = sum(
        (not surface.exists)
        or bool(surface.missing_required)
        or bool(surface.forbidden_hits)
        or bool(surface.unguarded_stale_lines)
        for surface in surfaces
    )
    total_stale_hits = sum(surface.stale_pattern_hits for surface in surfaces)
    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": hard_failures == 0,
        "decision": "historical_archive_surfaces_quarantined" if hard_failures == 0 else "historical_archive_surface_guard_failed",
        "hard_failures": hard_failures,
        "surfaces_checked": len(surfaces),
        "total_stale_pattern_hits_retained_under_archive_banners": total_stale_hits,
        "surfaces": [asdict(surface) for surface in surfaces],
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Historical Archive Surface Audit",
        "",
        f"- decision: `{payload['decision']}`",
        f"- passed: `{payload['passed']}`",
        f"- hard_failures: `{hard_failures}`",
        f"- surfaces_checked: `{len(surfaces)}`",
        f"- stale_pattern_hits_retained_under_archive_banners: `{total_stale_hits}`",
        "",
        "| Surface | Missing Required | Forbidden Hits | Unguarded Stale Lines | Stale Hits |",
        "|---|---:|---:|---:|---:|",
    ]
    for surface in surfaces:
        lines.append(
            f"| `{surface.path}` | {len(surface.missing_required)} | {len(surface.forbidden_hits)} | "
            f"{len(surface.unguarded_stale_lines)} | {surface.stale_pattern_hits} |"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "passed": payload["passed"],
        "decision": payload["decision"],
        "hard_failures": hard_failures,
        "surfaces_checked": len(surfaces),
        "stale_hits": total_stale_hits,
    }, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
