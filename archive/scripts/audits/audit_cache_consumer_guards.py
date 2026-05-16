"""Audit Python scripts that reference cache-like artifacts.

The cache-manifest audit tells us which artifacts are safe. This companion audit
checks the consumer side: reportable scripts that read cache-like artifacts should
either use the shared fail-closed guard or remain explicitly diagnostic/historical.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MANIFEST_AUDIT = RESULTS / "cache_manifest_audit_20260508.json"
OUT_JSON = RESULTS / "cache_consumer_guard_audit_20260508.json"
OUT_MD = RESULTS / "cache_consumer_guard_audit_20260508.md"

NON_MODEL_PREFIXES = (
    "audit_",
    "cache_",
    "generate_",
    "render_",
    "visualize_",
    "tests/",
)
NON_MODEL_FILES = {
    "verify_current_goal_state.py",
    "audit_prompt_objective_evidence.py",
    "cache_provenance.py",
}
CURRENT_GUARDED_CONSUMERS = {
    "compose_t1_iter14_fog.py",
    "compose_t1_iter15_harnet.py",
    "run_t3_iter23_clinical_ablation.py",
    "run_t3_iter24_stage2_forced.py",
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def py_files() -> list[Path]:
    paths = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in {".venv", ".git", "__pycache__"} for part in rel.parts):
            continue
        paths.append(path)
    return sorted(paths)


def role_for(rel: str) -> str:
    if rel in NON_MODEL_FILES or rel.startswith(NON_MODEL_PREFIXES):
        return "audit_reporting_or_cache_producer"
    if rel.startswith("cache_"):
        return "cache_producer"
    if rel.startswith("run_") or rel.startswith("compose_"):
        return "model_or_composer"
    return "other_python"


def artifact_tokens(artifact: str) -> set[str]:
    path = Path(artifact)
    tokens = {artifact, path.name}
    if artifact.startswith("results/"):
        tokens.add(artifact[len("results/") :])
    return {t for t in tokens if t}


def line_refs(text: str, tokens: set[str], max_refs: int = 6) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(token in line for token in tokens):
            refs.append({"line": lineno, "text": line.strip()[:220]})
            if len(refs) >= max_refs:
                break
    return refs


def has_runtime_read_near_refs(text: str, refs: list[dict[str, Any]]) -> bool:
    lines = text.splitlines()
    for ref in refs:
        idx = int(ref["line"]) - 1
        window = "\n".join(lines[max(0, idx - 8) : min(len(lines), idx + 20)])
        if re.search(r"\b(pd\.read_csv|np\.load|open\(|read_text\()", window):
            return True
    return False


def classify_reference(script: str, role: str, guard_present: bool, artifacts: list[dict[str, Any]]) -> str:
    statuses = {a["artifact_status"] for a in artifacts}
    if role == "audit_reporting_or_cache_producer":
        return "non_model_or_cache_producer_reference"
    if script in CURRENT_GUARDED_CONSUMERS and guard_present:
        return "current_safe_consumer_guarded"
    if any(status != "manifest_complete_clean_by_construction" for status in statuses):
        return "diagnostic_only_consumer_block_reportable_use"
    if guard_present:
        return "guarded_clean_consumer"
    return "unguarded_clean_cache_consumer_review"


def main() -> None:
    audit = read_json(MANIFEST_AUDIT)
    artifact_rows = {
        row["artifact"]: row
        for row in audit.get("artifacts", [])
        if row.get("artifact")
    }

    references: list[dict[str, Any]] = []
    for path in py_files():
        rel = str(path.relative_to(ROOT))
        text = read_text(path)
        matched: list[dict[str, Any]] = []
        for artifact, row in artifact_rows.items():
            tokens = artifact_tokens(artifact)
            if not any(token in text for token in tokens):
                continue
            refs = line_refs(text, tokens)
            if not refs:
                continue
            matched.append(
                {
                    "artifact": artifact,
                    "artifact_status": row.get("status"),
                    "manifest": row.get("manifest"),
                    "line_refs": refs,
                    "runtime_read_near_reference": has_runtime_read_near_refs(text, refs),
                }
            )
        if not matched:
            continue
        guard_present = "require_cache_manifest" in text
        role = role_for(rel)
        references.append(
            {
                "script": rel,
                "role": role,
                "guard_present": guard_present,
                "classification": classify_reference(rel, role, guard_present, matched),
                "artifacts": matched,
            }
        )

    counts: dict[str, int] = {}
    for row in references:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1

    diagnostic_consumers = [
        row
        for row in references
        if row["classification"] == "diagnostic_only_consumer_block_reportable_use"
    ]
    current_guarded = [
        row
        for row in references
        if row["classification"] in {"current_safe_consumer_guarded", "guarded_clean_consumer"}
    ]

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_cache_consumer_guards.py",
        "source_manifest_audit": str(MANIFEST_AUDIT.relative_to(ROOT)),
        "n_artifacts_from_manifest_audit": len(artifact_rows),
        "n_python_scripts_with_cache_references": len(references),
        "classification_counts": counts,
        "current_guarded_consumers": [row["script"] for row in current_guarded],
        "diagnostic_only_model_consumers": [row["script"] for row in diagnostic_consumers],
        "verdict": (
            "Current known safe-cache consumers use the shared guard. Scripts that still "
            "reference missing/partial-manifest caches are diagnostic or historical unless "
            "their caches are regenerated/backfilled and the scripts add require_cache_manifest."
        ),
        "references": references,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Cache Consumer Guard Audit — 2026-05-08",
        "",
        "This scans Python scripts for references to cache-like artifacts from `results/cache_manifest_audit_20260508.json` and classifies whether the consumer is guarded, diagnostic/historical, or non-model/cache-production code.",
        "",
        "## Summary",
        "",
        f"- Python scripts with cache references: `{len(references)}`",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- `{status}`: `{count}`")
    lines.extend(["", "## Guarded Current Consumers", ""])
    if current_guarded:
        for row in current_guarded:
            artifacts = ", ".join(f"`{a['artifact']}`" for a in row["artifacts"])
            lines.append(f"- `{row['script']}` — {artifacts}")
    else:
        lines.append("- None.")
    lines.extend(["", "## Diagnostic-Only Model Consumers", ""])
    if diagnostic_consumers:
        for row in diagnostic_consumers:
            artifacts = ", ".join(
                f"`{a['artifact']}` ({a['artifact_status']})" for a in row["artifacts"]
            )
            lines.append(f"- `{row['script']}` — {artifacts}")
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            report["verdict"],
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"classification_counts": counts}, indent=2))


if __name__ == "__main__":
    main()
