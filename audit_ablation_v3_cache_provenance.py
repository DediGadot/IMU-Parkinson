#!/usr/bin/env python3
"""Audit provenance evidence for the live V2 feature cache.

`results/ablation_v3_features.csv` is the remaining missing-manifest cache
opened by current lightweight T1/T3 data-load paths. This script gathers the
available evidence and deliberately does not synthesize a clean manifest. The
goal is to document what can be proven from files, git history, logs, and prior
audits, and to record why the cache remains a provenance boundary.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from cache_provenance import validate_cache_manifest


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CACHE = RESULTS / "ablation_v3_features.csv"
LOG = RESULTS / "ablation_v3.log"
PRODUCER_SCRIPTS = [ROOT / "run_ablation_v3.py", ROOT / "run_ablation_v2.py"]
MANIFEST_AUDIT = RESULTS / "cache_manifest_audit_20260508.json"
RUNTIME_AUDIT = RESULTS / "runtime_cache_dependency_audit_20260508.json"
TRANSITIVE_AUDIT = RESULTS / "transitive_cache_dependency_audit_20260508.json"
DST_AUDIT = RESULTS / "dst_walkway_leakage_audit_20260508_multiseed.json"
OUT_JSON = RESULTS / "ablation_v3_cache_provenance_audit_20260508.json"
OUT_MD = RESULTS / "ablation_v3_cache_provenance_audit_20260508.md"


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def run_cmd(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "args": args,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def path_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat() if path.exists() else None
    return {
        "path": rel(path),
        "exists": path.exists(),
        "bytes": stat.st_size if stat else None,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat() if stat else None,
        "sha256": sha256_file(path),
    }


def git_log_for(paths: list[Path]) -> list[dict[str, str]]:
    args = [
        "git",
        "log",
        "--format=%h%x09%H%x09%ci%x09%s",
        "--",
        *[rel(path) for path in paths],
    ]
    res = run_cmd(args)
    rows = []
    if res["returncode"] != 0:
        return rows
    for line in res["stdout"].splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            rows.append(
                {
                    "short": parts[0],
                    "sha": parts[1],
                    "date": parts[2],
                    "subject": parts[3],
                }
            )
    return rows


def git_evidence() -> dict[str, Any]:
    tracked = run_cmd(["git", "ls-files", "--stage", rel(CACHE)])
    head = run_cmd(["git", "rev-parse", "HEAD"])
    status = run_cmd(["git", "status", "--short", "--", rel(CACHE), *[rel(p) for p in PRODUCER_SCRIPTS]])
    return {
        "head_sha": head["stdout"] if head["returncode"] == 0 else None,
        "cache_tracked": bool(tracked["stdout"]),
        "cache_ls_files_stage": tracked["stdout"],
        "cache_history": git_log_for([CACHE]),
        "producer_script_history": git_log_for(PRODUCER_SCRIPTS),
        "scoped_worktree_status": status["stdout"].splitlines() if status["stdout"] else [],
        "producer_script_current_sha256": {
            rel(path): sha256_file(path) for path in PRODUCER_SCRIPTS
        },
    }


def schema_evidence() -> dict[str, Any]:
    df = pd.read_csv(CACHE)
    columns = list(df.columns)
    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    excluded_prefixes = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    selected = [
        col
        for col in columns
        if col not in excluded and not any(str(col).startswith(prefix) for prefix in excluded_prefixes)
    ]
    prefixes = ["dst_", "cv_", "nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_"]
    prefix_counts_total = {
        prefix: len([col for col in columns if str(col).startswith(prefix)])
        for prefix in prefixes
    }
    prefix_counts_selected = {
        prefix: len([col for col in selected if str(col).startswith(prefix)])
        for prefix in prefixes
    }
    sid_series = df["sid"].astype(str) if "sid" in df else pd.Series(dtype=str)
    target_summary: dict[str, Any] = {}
    if "updrs3" in df:
        target = pd.to_numeric(df["updrs3"], errors="coerce")
        target_summary = {
            "non_null": int(target.notna().sum()),
            "min": float(target.min()),
            "max": float(target.max()),
            "mean": float(target.mean()),
        }
    return {
        "rows": int(len(df)),
        "columns": int(len(columns)),
        "unique_sids": int(sid_series.nunique()),
        "sid_prefix_counts": {
            "NLS": int(sid_series.str.startswith("NLS").sum()),
            "WPD": int(sid_series.str.startswith("WPD").sum()),
            "other": int((~sid_series.str.startswith(("NLS", "WPD"))).sum()),
        },
        "label_or_clinical_columns_present": [
            col for col in ["updrs3", "hy", "obs_subscore"] if col in columns
        ],
        "current_v2_filter": {
            "excluded_exact": sorted(excluded),
            "excluded_prefixes": list(excluded_prefixes),
            "selected_columns": int(len(selected)),
            "prefix_counts_total": prefix_counts_total,
            "prefix_counts_selected": prefix_counts_selected,
            "dst_columns_selected": [col for col in selected if str(col).startswith("dst_")],
            "cv_columns_selected": [col for col in selected if str(col).startswith("cv_")],
        },
        "updrs3_column_summary": target_summary,
    }


def log_evidence() -> dict[str, Any]:
    if not LOG.exists():
        return {"exists": False}
    text = LOG.read_text(encoding="utf-8", errors="replace")
    relevant_markers = [
        "Loaded split:",
        "V3 extraction:",
        "Walkway loaded:",
        "Distilled",
        "Cached:",
        "[cache]",
        "PHASE",
    ]
    lines = text.splitlines()
    return {
        "exists": True,
        "metadata": path_metadata(LOG),
        "first_lines": lines[:12],
        "relevant_lines": [
            line
            for line in lines
            if any(marker in line for marker in relevant_markers)
        ][:40],
        "contains_exact_command": False,
        "contains_git_sha": "git" in text.lower() and "sha" in text.lower(),
    }


def prior_audit_evidence() -> dict[str, Any]:
    manifest_audit = load_json(MANIFEST_AUDIT) or {}
    runtime_audit = load_json(RUNTIME_AUDIT) or {}
    transitive_audit = load_json(TRANSITIVE_AUDIT) or {}
    dst_audit = load_json(DST_AUDIT) or {}

    manifest_row = None
    for row in manifest_audit.get("artifacts", []):
        if row.get("artifact") == rel(CACHE):
            manifest_row = row
            break

    runtime_targets = []
    for row in runtime_audit.get("target_reports", []):
        opened = row.get("opened_diagnostic_or_partial_cache_artifacts", [])
        if rel(CACHE) in opened:
            runtime_targets.append(
                {
                    "target": row.get("target"),
                    "status": row.get("status"),
                    "result": row.get("result"),
                }
            )

    transitive_entrypoints = []
    for row in transitive_audit.get("entrypoint_reports", []):
        artifacts = row.get("diagnostic_or_partial_cache_artifacts", [])
        if rel(CACHE) in artifacts:
            transitive_entrypoints.append(
                {
                    "entrypoint": row.get("entrypoint"),
                    "classification": row.get("classification"),
                }
            )

    dst_summary: dict[str, Any] = {}
    if dst_audit:
        current = dst_audit.get("policy_results", {}).get("stage2_current", {})
        no_dst = dst_audit.get("policy_results", {}).get("stage2_no_dst", {})
        dst_summary = {
            "audit": rel(DST_AUDIT),
            "dst_columns_selected": len(
                dst_audit.get("schema_audit", {}).get("dst_columns_selected_by_current_filters", [])
            ),
            "current_metrics": current.get("mean_metrics", {}),
            "no_dst_metrics": no_dst.get("mean_metrics", {}),
            "no_dst_minus_current": dst_audit.get("comparisons", {}).get("stage2_no_dst_minus_current", {}),
            "verdict": dst_audit.get("verdict"),
        }

    return {
        "manifest_audit_row": manifest_row,
        "runtime_targets_opening_cache": runtime_targets,
        "transitive_entrypoints_reaching_cache": transitive_entrypoints,
        "dst_walkway_distillation_summary": dst_summary,
    }


def decision_block(validation: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reasons = [
        "No ablation_v3_features.csv.manifest.json sidecar exists.",
        "The available ablation_v3.log records split sizes, extraction, distillation, and cache path, but not an exact command, creation timestamp, raw-data hash, producing git SHA, or manifest schema fields.",
        "The cache contains compatibility target/clinical columns and the current V2 feature filter selects six cv_* columns; this is disclosed but not a clean label-free feature-cache sidecar.",
        "The cache also contains 31 selected dst_* pressure-walkway-distiller columns from a once-trained historical dev-split model; the no-dst sensitivity is non-material, but the distiller is not LOOCV fold-local.",
    ]
    if validation.get("status") != "missing_manifest_diagnostic_only":
        reasons.append(f"Manifest validator status is {validation.get('status')}, not clean-by-construction.")
    if schema.get("current_v2_filter", {}).get("prefix_counts_selected", {}).get("dst_", 0) != 31:
        reasons.append("Unexpected dst_* selected-count mismatch; inspect schema before relying on this audit.")
    return {
        "decision": "do_not_synthesize_clean_manifest",
        "manifest_backfill_status": "blocked_without_exact_command_runtime_git_datahash_evidence",
        "safe_for_cache_manifest_clean_headline": False,
        "acceptable_current_use": (
            "Historical/current reports may cite pipelines that read this cache only with explicit "
            "provenance caveats and, for T3, the no-dst sensitivity. Future cache-manifest-clean "
            "headlines need a real regeneration/backfill or narrower reproduction artifacts."
        ),
        "reasons": reasons,
    }


def write_markdown(report: dict[str, Any]) -> None:
    schema = report["schema_evidence"]
    current_filter = schema["current_v2_filter"]
    prior = report["prior_audits"]
    dst = prior["dst_walkway_distillation_summary"]
    decision = report["decision"]
    git = report["git_evidence"]
    cache_meta = report["cache"]
    log = report["log_evidence"]

    lines = [
        "# Ablation V3 Cache Provenance Audit - 2026-05-08",
        "",
        "This is a non-mutating evidence report for `results/ablation_v3_features.csv`. It does not create or backfill a manifest sidecar.",
        "",
        "## Summary",
        "",
        f"- Cache SHA256: `{cache_meta['sha256']}`",
        f"- Shape: `{schema['rows']}` rows x `{schema['columns']}` columns; `{schema['unique_sids']}` unique SIDs.",
        f"- Manifest validator status: `{report['manifest_validation']['status']}`.",
        f"- Current V2 filters select `{current_filter['selected_columns']}` columns, including `{current_filter['prefix_counts_selected']['dst_']}` `dst_*` and `{current_filter['prefix_counts_selected']['cv_']}` `cv_*` columns.",
        f"- Runtime cache audit targets opening this cache: `{len(prior['runtime_targets_opening_cache'])}`.",
        f"- Decision: `{decision['decision']}`.",
        "",
        "## Proven Evidence",
        "",
        f"- Git tracks the cache: `{git['cache_tracked']}`; cache history: "
        + ", ".join(f"`{row['short']} {row['subject']}`" for row in git["cache_history"]) + ".",
        f"- Current producer script hashes: "
        + ", ".join(f"`{path}`=`{sha}`" for path, sha in git["producer_script_current_sha256"].items()),
        f"- Log SHA256: `{log.get('metadata', {}).get('sha256')}`.",
        "",
        "Relevant log lines:",
        "",
        "```text",
        *log.get("first_lines", []),
        "```",
        "",
        "## Prior Audits Linked",
        "",
        "- `audit_runtime_cache_dependencies.py` found this is the only diagnostic/partial cache opened by lightweight iter12/iter34/iter47 paths.",
    ]
    for row in prior["runtime_targets_opening_cache"]:
        lines.append(f"  - `{row['target']}`: status `{row['status']}`, result `{row['result']}`")
    lines.extend(
        [
            "- `audit_dst_walkway_leakage.py` measured the selected `dst_*` caveat on corrected T3.",
            f"  - current Stage 2 CCC `{dst.get('current_metrics', {}).get('ccc')}`, no-`dst_*` CCC `{dst.get('no_dst_metrics', {}).get('ccc')}`.",
            f"  - bootstrap delta no-`dst` minus current `{dst.get('no_dst_minus_current', {}).get('mean_delta')}`.",
            "",
            "## Decision",
            "",
        ]
    )
    for reason in decision["reasons"]:
        lines.append(f"- {reason}")
    lines.extend(
        [
            "",
            f"Recommended use: {decision['acceptable_current_use']}",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    validation = validate_cache_manifest(CACHE)
    schema = schema_evidence()
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_ablation_v3_cache_provenance.py",
        "cache": path_metadata(CACHE),
        "producer_scripts": [path_metadata(path) for path in PRODUCER_SCRIPTS],
        "git_evidence": git_evidence(),
        "schema_evidence": schema,
        "log_evidence": log_evidence(),
        "manifest_validation": validation,
        "prior_audits": prior_audit_evidence(),
        "regeneration_status": {
            "attempted_by_this_script": False,
            "rationale": (
                "This audit records existing evidence only. Exact regeneration is not inferred "
                "from narrative logs; a future regeneration should write a complete manifest "
                "at cache creation time."
            ),
        },
        "decision": decision_block(validation, schema),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({
        "manifest_status": validation["status"],
        "decision": report["decision"]["decision"],
        "dst_selected": schema["current_v2_filter"]["prefix_counts_selected"]["dst_"],
        "cv_selected": schema["current_v2_filter"]["prefix_counts_selected"]["cv_"],
    }, indent=2))


if __name__ == "__main__":
    main()
