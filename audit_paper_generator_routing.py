#!/usr/bin/env python3
"""Audit current paper-renderer routing and legacy generator quarantine."""

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
OUT_JSON = RESULTS / "paper_generator_routing_audit_20260509.json"
OUT_MD = RESULTS / "paper_generator_routing_audit_20260509.md"

ACTIVE_DOCS = [
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "task_plan.md",
    "progress.md",
    "findings.md",
    "results/current_best_pipeline_artifact_index_20260508.md",
    "results/thread_goal_completion_audit_20260508.md",
]

LEGACY_QUARANTINE_DOCS = [
    ".claude/commands/update-paper.md",
]

BAD_ACTIVE_SNIPPETS = [
    "Rebuild the current paper with `uv run python generate_paper_v4.py`",
    "uv run python generate_paper_v4.py                       # current paper builder",
    "**Use `generate_paper_v4.py`**",
    "current paper builder \u2192 NEW4.html",
    "current paper builder -> NEW4.html",
    "Manuscript file: `/home/fiod/medical/NEW.html`** \u2014 this is the authoritative manuscript",
    "Manuscript file: `/home/fiod/medical/NEW.html`** - this is the authoritative manuscript",
]

CURRENT_REQUIRED = [
    "render_current_paper.py",
    "CURRENT_PAPER.html",
]

LEGACY_WORDS = re.compile(
    r"\b(legacy|stale|archaeology|historical|old|pre-audit|not current|not evidence|do not treat)\b",
    re.I,
)


def read_text(path: str | Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256(path: str | Path) -> str | None:
    p = ROOT / path
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def text_line_context(text: str, line_no: int, radius: int = 1) -> str:
    lines = text.splitlines()
    start = max(0, line_no - 1 - radius)
    end = min(len(lines), line_no + radius)
    return " ".join(line.strip() for line in lines[start:end] if line.strip())


def line_hits(text: str, pattern: str) -> list[dict[str, Any]]:
    regex = re.compile(pattern, re.I)
    hits = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if regex.search(line):
            hits.append(
                {
                    "line": idx,
                    "line_text": line.strip(),
                    "context": text_line_context(text, idx),
                }
            )
    return hits


def audit_active_doc(path: str) -> dict[str, Any]:
    text = read_text(path)
    missing_required = [snippet for snippet in CURRENT_REQUIRED if snippet not in text]
    bad_exact = [snippet for snippet in BAD_ACTIVE_SNIPPETS if snippet in text]
    unguarded_new4 = []
    for hit in line_hits(text, r"generate_paper_v4\.py|NEW4\.html"):
        if not LEGACY_WORDS.search(hit["context"]):
            unguarded_new4.append(hit)

    return {
        "path": path,
        "missing_required": missing_required,
        "bad_exact_snippets": bad_exact,
        "unguarded_generate_v4_or_new4_hits": unguarded_new4,
        "contains_current_render_command": "uv run python render_current_paper.py" in text,
        "contains_legacy_quarantine": bool(LEGACY_WORDS.search(text)),
        "sha256": sha256(path),
    }


def audit_legacy_doc(path: str) -> dict[str, Any]:
    text = read_text(path)
    required = [
        "LEGACY PRE-AUDIT",
        "Current-route warning",
        "render_current_paper.py",
        "CURRENT_PAPER.html",
        "Do not use this file as the current manuscript pipeline",
    ]
    missing_required = [snippet for snippet in required if snippet not in text]
    stale_hits = line_hits(text, r"0\.868|0\.776|generate_paper\.py|NEW\.html")
    return {
        "path": path,
        "missing_required": missing_required,
        "stale_or_legacy_hit_count": len(stale_hits),
        "sample_stale_or_legacy_hits": stale_hits[:10],
        "sha256": sha256(path),
    }


def audit_current_renderer() -> dict[str, Any]:
    renderer = read_text("render_current_paper.py")
    manifest = load_json("results/current_paper_export/manifest.json")
    current_html = read_text("CURRENT_PAPER.html")
    plain = html.unescape(re.sub(r"<[^>]+>", " ", current_html))
    plain = re.sub(r"\s+", " ", plain)
    forbidden = manifest.get("forbidden_stale_snippets", [])
    forbidden_hits = [snippet for snippet in forbidden if html.unescape(snippet) in plain or snippet in current_html]

    required = [
        'OUTPUT = ROOT / "CURRENT_PAPER.html"',
        "Use this export instead of NEW4.html",
        "NEW4.html is a legacy generator output with stale pre-leakage narrative fragments",
        "T1 LOOCV CCC = 0.6550",
        "valid-range-corrected T3 LOOCV CCC = 0.3784",
        "valid-range LOSO transportability falling to CCC = 0.150",
    ]
    missing_required = [snippet for snippet in required if snippet not in renderer and snippet not in current_html]
    mtime_ok = (ROOT / "results/current_paper_export/manifest.json").stat().st_mtime >= (
        ROOT / "render_current_paper.py"
    ).stat().st_mtime
    return {
        "script": "render_current_paper.py",
        "output": "CURRENT_PAPER.html",
        "missing_required": missing_required,
        "manifest": {
            "status": manifest.get("status"),
            "source": manifest.get("source"),
            "output": manifest.get("output"),
            "validation_issues": manifest.get("validation_issues"),
            "required_snippet_count": len(manifest.get("required_snippets", [])),
            "forbidden_stale_snippet_count": len(forbidden),
            "manifest_mtime_gte_renderer_mtime": mtime_ok,
        },
        "forbidden_hits": forbidden_hits,
        "sha256": sha256("render_current_paper.py"),
        "output_sha256": sha256("CURRENT_PAPER.html"),
    }


def audit_legacy_generator() -> dict[str, Any]:
    script = read_text("generate_paper_v4.py")
    new4 = read_text("NEW4.html")
    required_script = [
        "LEGACY generator for stale pre-audit NEW4.html",
        'OUTPUT_FILE = ROOT / "NEW4.html"',
        "0.868",
        "0.776",
        "SSL ranking",
        "transductive",
    ]
    required_new4 = ["0.868", "0.776", "Ordinal ranking", "transductive"]
    return {
        "script": "generate_paper_v4.py",
        "output": "NEW4.html",
        "script_missing_required_evidence": [s for s in required_script if s not in script],
        "new4_missing_stale_evidence": [s for s in required_new4 if s not in new4],
        "stale_phrase_counts": {
            "generate_paper_v4_py_0_868": script.count("0.868"),
            "generate_paper_v4_py_0_776": script.count("0.776"),
            "new4_html_0_868": new4.count("0.868"),
            "new4_html_0_776": new4.count("0.776"),
            "new4_html_transductive": len(re.findall("transductive", new4, flags=re.I)),
        },
        "sha256": sha256("generate_paper_v4.py"),
        "output_sha256": sha256("NEW4.html"),
    }


def build_report() -> dict[str, Any]:
    active_docs = [audit_active_doc(path) for path in ACTIVE_DOCS]
    legacy_docs = [audit_legacy_doc(path) for path in LEGACY_QUARANTINE_DOCS]
    current_renderer = audit_current_renderer()
    legacy_generator = audit_legacy_generator()

    hard_failures: list[dict[str, Any]] = []
    for doc in active_docs:
        if doc["missing_required"] or doc["bad_exact_snippets"] or doc["unguarded_generate_v4_or_new4_hits"]:
            hard_failures.append({"check": "active_doc_routing", "doc": doc})
    for doc in legacy_docs:
        if doc["missing_required"]:
            hard_failures.append({"check": "legacy_doc_quarantine", "doc": doc})
    if (
        current_renderer["missing_required"]
        or current_renderer["manifest"]["status"] != "passed"
        or current_renderer["manifest"]["validation_issues"] != []
        or not current_renderer["manifest"]["manifest_mtime_gte_renderer_mtime"]
        or current_renderer["forbidden_hits"]
    ):
        hard_failures.append({"check": "current_renderer", "evidence": current_renderer})
    if legacy_generator["script_missing_required_evidence"] or legacy_generator["new4_missing_stale_evidence"]:
        hard_failures.append({"check": "legacy_generator_evidence", "evidence": legacy_generator})

    passed = not hard_failures
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_paper_generator_routing.py",
        "policy": (
            "Current paper work must route to render_current_paper.py -> CURRENT_PAPER.html. "
            "generate_paper_v4.py / NEW4.html may exist only as explicitly quarantined legacy archaeology."
        ),
        "passed": passed,
        "decision": "current_paper_renderer_route_guard_passed" if passed else "current_paper_renderer_route_guard_failed",
        "active_docs": active_docs,
        "legacy_quarantine_docs": legacy_docs,
        "current_renderer": current_renderer,
        "legacy_generator": legacy_generator,
        "kimi_consult_summary": (
            "Kimi agreed this is a non-redundant publication-surface routing guard: docs should point "
            "to render_current_paper.py/CURRENT_PAPER.html, legacy generators should be marked stale, "
            "and no WearGait-only model run is justified by this issue."
        ),
        "hard_failures": hard_failures,
        "warnings": [],
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Paper Generator Routing Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Current Route",
        "",
        f"- Renderer: `{report['current_renderer']['script']}`",
        f"- Output: `{report['current_renderer']['output']}`",
        f"- Export manifest status: `{report['current_renderer']['manifest']['status']}`",
        f"- Export validation issues: `{len(report['current_renderer']['manifest']['validation_issues'])}`",
        f"- Renderer required snippets missing: `{len(report['current_renderer']['missing_required'])}`",
        f"- Forbidden stale snippets in current export: `{len(report['current_renderer']['forbidden_hits'])}`",
        f"- Manifest mtime >= renderer mtime: `{report['current_renderer']['manifest']['manifest_mtime_gte_renderer_mtime']}`",
        "",
        "## Active Docs",
        "",
    ]
    for doc in report["active_docs"]:
        lines.append(
            f"- `{doc['path']}`: missing current-route snippets `{len(doc['missing_required'])}`, "
            f"bad exact snippets `{len(doc['bad_exact_snippets'])}`, "
            f"unguarded legacy hits `{len(doc['unguarded_generate_v4_or_new4_hits'])}`"
        )
    lines.extend(["", "## Legacy Quarantine", ""])
    for doc in report["legacy_quarantine_docs"]:
        lines.append(
            f"- `{doc['path']}`: missing quarantine snippets `{len(doc['missing_required'])}`, "
            f"stale/legacy hits retained `{doc['stale_or_legacy_hit_count']}`"
        )
    lines.extend(
        [
            "",
            "## Legacy Generator Evidence",
            "",
            f"- Script: `{report['legacy_generator']['script']}`",
            f"- Output: `{report['legacy_generator']['output']}`",
            f"- Script missing stale/quarantine evidence: `{len(report['legacy_generator']['script_missing_required_evidence'])}`",
            f"- NEW4 missing stale evidence: `{len(report['legacy_generator']['new4_missing_stale_evidence'])}`",
            f"- Stale phrase counts: `{report['legacy_generator']['stale_phrase_counts']}`",
            "",
            "## Kimi Consult",
            "",
            report["kimi_consult_summary"],
        ]
    )
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
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
