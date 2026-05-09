#!/usr/bin/env python3
"""Audit cache-like result artifacts for manifest sidecar coverage."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cache_provenance import (
    REQUIRED_MANIFEST_FIELDS,
    is_nullish_required_value,
)

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "cache_manifest_audit_20260508.json"
OUT_MD = RESULTS / "cache_manifest_audit_20260508.md"

EXCLUDE_PATTERNS = [
    "screen",
    "5split",
    "5fold",
    "loocv",
    "lockbox",
    "summary",
    "oof",
    "preregistration",
    "learning_curve",
    "feature_importance",
    "subject_preds",
    "subject_rows",
    "pd_demographic",
    "structured_items",
]

INCLUDE_PATTERNS = [
    "features",
    "embeddings",
    "_subj",
    "_recording",
    "fm_embeddings",
    "rocket_recordings",
    "joints_v2",
    "stride_locked",
    "walkway_joint",
    "mahalanobis",
    "clinical_extras",
    "item11_multiscale",
    "item9_event_moment",
    "v2_self_normalized",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_cache_like(path: Path) -> bool:
    name = path.name
    if path.suffix not in {".csv", ".npz"}:
        return False
    if any(p in name for p in EXCLUDE_PATTERNS):
        return False
    return any(p in name for p in INCLUDE_PATTERNS)


def load_manifest(path: Path) -> dict[str, Any] | None:
    manifest_path = Path(str(path) + ".manifest.json")
    if not manifest_path.exists():
        return None
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def manifest_completeness(manifest: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    if manifest is None:
        return REQUIRED_MANIFEST_FIELDS[:], []
    missing = [k for k in REQUIRED_MANIFEST_FIELDS if k not in manifest]
    nullish = [
        k
        for k in REQUIRED_MANIFEST_FIELDS
        if k in manifest and is_nullish_required_value(k, manifest.get(k))
    ]
    return missing, nullish


def csv_shape(path: Path) -> dict[str, int | None]:
    if path.suffix != ".csv":
        return {"rows": None, "columns": None}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return {"rows": 0, "columns": 0}
        rows = sum(1 for _ in reader)
    return {"rows": rows, "columns": len(header)}


def status_for(manifest: dict[str, Any] | None, missing: list[str], nullish: list[str]) -> str:
    if manifest is None:
        return "missing_manifest_diagnostic_only"
    if missing or nullish:
        return "partial_manifest_diagnostic_only"
    if manifest.get("labels_used") is not False:
        return "manifest_present_but_labels_used_not_false"
    if manifest.get("leakage_status") != "clean_by_construction":
        return "manifest_present_not_clean_by_construction"
    return "manifest_complete_clean_by_construction"


def main() -> None:
    artifacts = sorted([p for p in RESULTS.iterdir() if p.is_file() and is_cache_like(p)])
    rows: list[dict[str, Any]] = []
    for path in artifacts:
        manifest_path = Path(str(path) + ".manifest.json")
        manifest = load_manifest(path)
        missing, nullish = manifest_completeness(manifest)
        rows.append(
            {
                "artifact": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                **csv_shape(path),
                "manifest": str(manifest_path.relative_to(ROOT)) if manifest_path.exists() else None,
                "manifest_exists": manifest is not None,
                "missing_required_fields": missing,
                "nullish_required_fields": nullish,
                "labels_used": None if manifest is None else manifest.get("labels_used"),
                "leakage_status": None if manifest is None else manifest.get("leakage_status"),
                "status": status_for(manifest, missing, nullish),
            }
        )

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_cache_manifests.py",
        "required_manifest_fields": REQUIRED_MANIFEST_FIELDS,
        "n_cache_like_artifacts": len(rows),
        "status_counts": counts,
        "headline_safe_artifacts": [r["artifact"] for r in rows if r["status"] == "manifest_complete_clean_by_construction"],
        "diagnostic_only_artifacts": [r["artifact"] for r in rows if r["status"] != "manifest_complete_clean_by_construction"],
        "artifacts": rows,
        "policy": "Per AGENTS.md, cache-like artifacts without complete provenance sidecars are diagnostic-only and must not feed inductive headlines until backfilled from real command/script/git evidence.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Cache Manifest Audit — 2026-05-08",
        "",
        "Policy: per `AGENTS.md`, reusable cache artifacts feeding inductive headlines need sidecar manifests with script, command, git SHA, data hash, label-use, fold scope, cohort-statistics scope, normalization scope, leakage status, and leakage rationale. Missing or partial manifests are diagnostic-only.",
        "",
        "## Summary",
        "",
        f"- Cache-like artifacts audited: `{len(rows)}`",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- `{status}`: `{count}`")
    lines.extend(["", "## Headline-Safe Artifacts", ""])
    safe = [r for r in rows if r["status"] == "manifest_complete_clean_by_construction"]
    if safe:
        for row in safe:
            lines.append(f"- `{row['artifact']}` — manifest `{row['manifest']}`")
    else:
        lines.append("- None.")
    lines.extend(["", "## Diagnostic-Only Artifacts Requiring Backfill", ""])
    for row in rows:
        if row["status"] == "manifest_complete_clean_by_construction":
            continue
        fields = row["missing_required_fields"] + row["nullish_required_fields"]
        reason = "missing manifest" if not row["manifest_exists"] else "missing/null fields: " + ", ".join(fields)
        lines.append(f"- `{row['artifact']}` — `{row['status']}` ({reason})")
    lines.extend(
        [
            "",
            "## Backfill Discipline",
            "",
            "No manifests were synthesized in this audit. Backfill should be done only when the producing script, command, git SHA, data hash, and leakage rationale can be reconstructed from real evidence. Otherwise the artifact remains diagnostic-only.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"status_counts": counts, "n_cache_like_artifacts": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
