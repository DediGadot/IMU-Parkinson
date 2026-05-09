#!/usr/bin/env python3
"""Non-destructive regeneration probe for the historical ablation V3 cache.

This script never writes to results/ablation_v3_features.csv.  It can be run on
the GPU slave to regenerate the cache under a timestamped path, then compares the
new artifact against the frozen historical cache.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cache_provenance import sha256_file
from project_paths import DATA_DIR, RESULTS_DIR, ensure_dir


FROZEN_CACHE = RESULTS_DIR / "ablation_v3_features.csv"
OUT_JSON = RESULTS_DIR / "ablation_v3_regeneration_probe_20260509.json"
OUT_MD = RESULTS_DIR / "ablation_v3_regeneration_probe_20260509.md"
REQUIRED_DEPS = ["antropy", "pywt", "lightgbm", "xgboost", "catboost"]


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def check_deps() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for mod in REQUIRED_DEPS:
        try:
            spec = importlib.util.find_spec(mod)
            statuses[mod] = "ok" if spec is not None else "missing"
        except Exception as exc:
            statuses[mod] = f"error:{type(exc).__name__}:{exc}"
    return statuses


def file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def count_csvs(path: Path) -> int | None:
    if not path.exists() or not path.is_dir():
        return None
    return sum(1 for child in path.glob("*.csv") if child.is_file())


def regeneration_input_status() -> dict[str, Any]:
    pd_csv_dir = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
    control_csv_dir = DATA_DIR / "CONTROL PARTICIPANTS" / "CSV files"
    paths = {
        "data_dir": DATA_DIR,
        "pd_clinical": DATA_DIR / "PD - Demographic+Clinical - datasetV1.csv",
        "control_clinical": DATA_DIR / "CONTROLS - Demographic+Clinical - datasetV1.csv",
        "pd_csv_dir": pd_csv_dir,
        "control_csv_dir": control_csv_dir,
        "walkway_metrics": DATA_DIR / "Walkway-derived metrics" / "PKMAS Walkway Gait Metrics - HP+SP.csv",
    }
    checks = {
        name: {
            "path": str(path),
            "exists": path.exists(),
            "is_dir": path.is_dir(),
            "csv_count": count_csvs(path),
        }
        for name, path in paths.items()
    }
    missing = [name for name, check in checks.items() if not check["exists"]]
    return {
        "checks": checks,
        "missing": missing,
        "complete_for_full_178_subject_regeneration": not missing,
        "note": (
            "Full ablation_v3_features.csv regeneration requires PD and control "
            "clinical files, PD and control CSV directories, and the walkway metrics "
            "file because the frozen cache has HC rows and selected dst_* columns."
        ),
    }


def list_sha(values: list[str]) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(value.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def dataframe_signature(df: pd.DataFrame) -> dict[str, Any]:
    columns = [str(c) for c in df.columns]
    sid_values = [str(s) for s in df["sid"].tolist()] if "sid" in df.columns else []
    prefix_counts = {
        "cv_": sum(c.startswith("cv_") for c in columns),
        "dst_": sum(c.startswith("dst_") for c in columns),
        "ext_": sum(c.startswith("ext_") for c in columns),
        "ix_": sum(c.startswith("ix_") for c in columns),
    }
    return {
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "unique_sids": int(pd.Series(sid_values).nunique()) if sid_values else 0,
        "column_order_sha256": list_sha(columns),
        "sorted_column_sha256": list_sha(sorted(columns)),
        "sid_order_sha256": list_sha(sid_values),
        "sorted_sid_sha256": list_sha(sorted(sid_values)),
        "prefix_counts": prefix_counts,
        "contains_updrs3": "updrs3" in columns,
        "contains_hy": "hy" in columns,
        "contains_obs_subscore": "obs_subscore" in columns,
    }


def compare_frames(frozen: pd.DataFrame, regenerated: pd.DataFrame) -> dict[str, Any]:
    same_columns_order = list(frozen.columns) == list(regenerated.columns)
    same_sid_order = (
        "sid" in frozen.columns
        and "sid" in regenerated.columns
        and frozen["sid"].astype(str).tolist() == regenerated["sid"].astype(str).tolist()
    )
    comparison: dict[str, Any] = {
        "same_shape": tuple(frozen.shape) == tuple(regenerated.shape),
        "same_columns_order": same_columns_order,
        "same_column_set": set(frozen.columns) == set(regenerated.columns),
        "same_sid_order": same_sid_order,
        "same_sid_set": set(frozen.get("sid", pd.Series(dtype=str)).astype(str))
        == set(regenerated.get("sid", pd.Series(dtype=str)).astype(str)),
    }

    if not comparison["same_column_set"] or not comparison["same_sid_set"]:
        comparison["numeric_alignment_available"] = False
        comparison["columns_only_in_frozen"] = sorted(set(frozen.columns) - set(regenerated.columns))[:50]
        comparison["columns_only_in_regenerated"] = sorted(set(regenerated.columns) - set(frozen.columns))[:50]
        comparison["sids_only_in_frozen"] = sorted(
            set(frozen.get("sid", pd.Series(dtype=str)).astype(str))
            - set(regenerated.get("sid", pd.Series(dtype=str)).astype(str))
        )
        comparison["sids_only_in_regenerated"] = sorted(
            set(regenerated.get("sid", pd.Series(dtype=str)).astype(str))
            - set(frozen.get("sid", pd.Series(dtype=str)).astype(str))
        )
        return comparison

    frozen_aligned = frozen.sort_values("sid").reset_index(drop=True)
    regen_aligned = regenerated[list(frozen.columns)].sort_values("sid").reset_index(drop=True)
    numeric_cols = [c for c in frozen.columns if c != "sid"]
    frozen_num = frozen_aligned[numeric_cols].apply(pd.to_numeric, errors="coerce")
    regen_num = regen_aligned[numeric_cols].apply(pd.to_numeric, errors="coerce")
    diff = (frozen_num - regen_num).abs().replace([np.inf, -np.inf], np.nan)
    max_by_col = diff.max(axis=0).fillna(0.0)
    changed_cols = max_by_col[max_by_col > 1e-9].sort_values(ascending=False)
    comparison.update(
        {
            "numeric_alignment_available": True,
            "numeric_columns": len(numeric_cols),
            "max_abs_numeric_diff": float(max_by_col.max()) if len(max_by_col) else 0.0,
            "changed_numeric_columns_gt_1e_9": int((max_by_col > 1e-9).sum()),
            "changed_numeric_cells_gt_1e_9": int((diff.values > 1e-9).sum()),
            "top_changed_columns": [
                {"column": str(col), "max_abs_diff": float(val)}
                for col, val in changed_cols.head(20).items()
            ],
        }
    )
    return comparison


def write_markdown(report: dict[str, Any], path: Path) -> None:
    before = report.get("frozen_before", {})
    after = report.get("frozen_after", {})
    comparison = report.get("comparison", {})
    regen = report.get("regenerated", {})
    try:
        report_path = OUT_JSON.relative_to(Path.cwd())
    except ValueError:
        report_path = OUT_JSON
    lines = [
        "# Ablation V3 Regeneration Probe - 2026-05-09",
        "",
        "This is a non-destructive regeneration/provenance probe. It does not promote",
        "`results/ablation_v3_features.csv` to cache-manifest-clean headline use.",
        "",
        "## Summary",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Frozen cache SHA before: `{before.get('sha256')}`",
        f"- Frozen cache SHA after: `{after.get('sha256')}`",
        f"- Frozen cache unchanged: `{report.get('frozen_cache_unchanged')}`",
        f"- Regenerated cache: `{regen.get('path')}`",
        f"- Regenerated SHA: `{regen.get('sha256')}`",
        f"- Same shape: `{comparison.get('same_shape')}`",
        f"- Same column order: `{comparison.get('same_columns_order')}`",
        f"- Same SID order: `{comparison.get('same_sid_order')}`",
        f"- Max abs numeric diff: `{comparison.get('max_abs_numeric_diff')}`",
        f"- Changed numeric columns >1e-9: `{comparison.get('changed_numeric_columns_gt_1e_9')}`",
        "",
        "## Promotion Decision",
        "",
        report.get("promotion_decision", ""),
        "",
        "## Guardrail Rationale",
        "",
        "- The regenerated cache still contains `cv_*` clinical/intake columns.",
        "- The regenerated cache still contains `dst_*` walkway-distiller columns from a once-trained historical dev-split distiller.",
        "- `updrs3`, `hy`, and `obs_subscore` are present for compatibility and must not be treated as deployable IMU features.",
        "- A hash/schema match is reproducibility evidence only; it is not a fold-locality proof.",
        "",
        f"Machine-readable report: `{report_path}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    ensure_dir(RESULTS_DIR)
    deps = check_deps()
    frozen_before = file_fingerprint(FROZEN_CACHE)
    if not frozen_before.get("exists"):
        raise FileNotFoundError(FROZEN_CACHE)
    input_status = regeneration_input_status()
    if not input_status["complete_for_full_178_subject_regeneration"]:
        frozen_after = file_fingerprint(FROZEN_CACHE)
        report = {
            "script": "audit_ablation_v3_regeneration.py",
            "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "mode": "probe",
            "status": "blocked_missing_regeneration_inputs",
            "dependency_status": deps,
            "input_status": input_status,
            "frozen_before": frozen_before,
            "frozen_after": frozen_after,
            "frozen_cache_unchanged": frozen_before == frozen_after,
            "promotion_decision": (
                "No regenerated cache was written. The current remote lacks the full "
                "WearGait raw-data inputs needed to reproduce the frozen 178-subject "
                "cache. Do not synthesize a clean manifest or promote the historical "
                "cache; keep using the existing provenance caveats until the full raw "
                "data are restored and a non-destructive regeneration succeeds."
            ),
        }
        OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        write_markdown(report, OUT_MD)
        return report

    tag = args.tag or utc_now_compact()
    output_path = RESULTS_DIR / f"ablation_v3_regen_probe_{tag}.csv"
    if output_path.resolve() == FROZEN_CACHE.resolve():
        raise RuntimeError("Refusing to use the frozen cache path as regeneration output.")
    if output_path.exists() and not args.overwrite_output:
        raise FileExistsError(output_path)

    import run_ablation_v3 as v3

    v3.FEATURE_CACHE = str(output_path)
    subjects = v3.parse_clinical()
    split = v3.load_split()
    all_sids = split["dev_sids"] + split["test_sids"]
    regenerated_df = v3.build_v3_features(subjects, all_sids, split["dev_sids"])

    if not output_path.exists():
        regenerated_df.to_csv(output_path, index=False)

    frozen_after = file_fingerprint(FROZEN_CACHE)
    regenerated_fp = file_fingerprint(output_path)
    frozen_df = pd.read_csv(FROZEN_CACHE)
    regenerated_df = pd.read_csv(output_path)
    comparison = compare_frames(frozen_df, regenerated_df)

    report: dict[str, Any] = {
        "script": "audit_ablation_v3_regeneration.py",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "probe",
        "status": "completed",
        "dependency_status": deps,
        "frozen_before": frozen_before,
        "frozen_after": frozen_after,
        "frozen_cache_unchanged": frozen_before == frozen_after,
        "regenerated": regenerated_fp,
        "frozen_signature": dataframe_signature(frozen_df),
        "regenerated_signature": dataframe_signature(regenerated_df),
        "comparison": comparison,
        "promotion_decision": (
            "Do not promote this regenerated cache to cache-manifest-clean headline use. "
            "The probe can establish current-code reproducibility, but the artifact still "
            "contains clinical/intake `cv_*` columns and non-fold-local `dst_*` walkway "
            "distiller columns, plus compatibility target/clinical fields. Use it only as "
            "provenance evidence unless a new clean cache builder drops or refits those "
            "features under fold-local rules."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, OUT_MD)
    return report


def run_preflight() -> dict[str, Any]:
    ensure_dir(RESULTS_DIR)
    report = {
        "script": "audit_ablation_v3_regeneration.py",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "preflight",
        "status": "completed",
        "dependency_status": check_deps(),
        "input_status": regeneration_input_status(),
        "frozen_cache": file_fingerprint(FROZEN_CACHE),
        "note": "Preflight does not import run_ablation_v3.py and does not regenerate features.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, OUT_MD)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["preflight", "probe"], default="preflight")
    parser.add_argument("--tag", default="", help="Tag for regenerated CSV filename.")
    parser.add_argument("--overwrite-output", action="store_true")
    args = parser.parse_args()

    report = run_preflight() if args.mode == "preflight" else run_probe(args)
    print(json.dumps({k: report.get(k) for k in ["mode", "status", "frozen_cache_unchanged"]}, indent=2))
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
