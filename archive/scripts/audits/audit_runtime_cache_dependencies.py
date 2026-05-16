"""Trace cache-like artifact reads during lightweight headline data-load paths.

The transitive cache audit is intentionally conservative: it reports any cache
path reachable through local imports. This runtime audit installs a Python audit
hook before importing the target modules, then runs small data-load/recompute
paths that avoid LOOCV fitting. It records which cache-like artifacts are
actually opened in those paths.

This is diagnostic evidence only. A negative runtime trace does not prove a path
is unreachable under every flag or future edit; static import cleanliness or
concrete manifests remain the durable provenance fixes.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MANIFEST_AUDIT = RESULTS / "cache_manifest_audit_20260508.json"
OUT_JSON = RESULTS / "runtime_cache_dependency_audit_20260508.json"
OUT_MD = RESULTS / "runtime_cache_dependency_audit_20260508.md"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def artifact_rows() -> dict[str, dict[str, Any]]:
    audit = read_json(MANIFEST_AUDIT)
    return {
        row["artifact"]: row
        for row in audit.get("artifacts", [])
        if row.get("artifact")
    }


class OpenRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        if event != "open" or not args:
            return
        path_obj = args[0]
        if isinstance(path_obj, int):
            return
        try:
            path = Path(path_obj)
        except TypeError:
            return
        mode = args[1] if len(args) > 1 else None
        self.events.append(
            {
                "path": rel(path),
                "path_abs": str(path.resolve()) if path.exists() else str(path),
                "mode": str(mode),
            }
        )


RECORDER = OpenRecorder()
sys.addaudithook(RECORDER.hook)


def _opened_cache_artifacts(events: list[dict[str, Any]], rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    opened_paths = {event["path"] for event in events}
    opened_abs = {event["path_abs"] for event in events}
    out = []
    for artifact, row in rows.items():
        artifact_path = ROOT / artifact
        if artifact in opened_paths or str(artifact_path.resolve()) in opened_abs:
            out.append(
                {
                    "artifact": artifact,
                    "artifact_status": row.get("status"),
                    "manifest": row.get("manifest"),
                    "event_count": sum(
                        1
                        for event in events
                        if event["path"] == artifact
                        or event["path_abs"] == str(artifact_path.resolve())
                    ),
                }
            )
    return sorted(out, key=lambda item: item["artifact"])


def target_t1_iter12_recompute() -> dict[str, Any]:
    from compose_t1_iter12_honest import (
        ITER8_TS,
        ITER8_VARIANTS,
        T1_ITEMS,
        load_composite_target_data,
    )
    from inductive_lib import full_metrics

    d = load_composite_target_data()
    sids = np.asarray(d["sids"])
    oofs = []
    for item in T1_ITEMS:
        path = RESULTS / f"lockbox_peritem_{item}_{ITER8_VARIANTS[item]}_{ITER8_TS}.oof.npy"
        oofs.append(np.load(path))
    y_pred = np.sum(np.column_stack(oofs), axis=1)
    y_true = np.asarray(d["t1"], dtype=float)
    valid = ~np.isnan(y_true)
    metrics = full_metrics(y_true[valid], y_pred[valid], label="t1_iter12_runtime_recompute")
    return {
        "n": int(valid.sum()),
        "n_sids": int(len(sids)),
        "ccc": round(float(metrics["ccc"]), 4),
        "mae": round(float(metrics["mae"]), 4),
    }


def target_t1_iter34_loader() -> dict[str, Any]:
    from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items
    from run_t3_iter5_clinical import FEATURE_SETS, build_stage1_features, load_clinical_dict

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    clinical = load_clinical_dict(sids)
    stage1, stage1_names = build_stage1_features(hy, clinical, FEATURE_SETS["A3_tier1"])
    return {
        "n": int(len(sids)),
        "x_cols": int(X.shape[1]),
        "stage1_cols": int(stage1.shape[1]),
        "stage1_names": list(stage1_names),
        "available_aux": list(available_aux),
        "t1_mean": round(float(np.nanmean(y_t1)), 4),
        "item_keys": sorted(int(k) for k in items),
    }


def target_t3_iter47_filter_minimal() -> dict[str, Any]:
    from run_t3_iter47_invalid_code_fix import filter_cohort

    data = filter_cohort("drop_allmissing_validrange")
    return {
        "n": int(len(data["sids"])),
        "x_cols": int(data["X"].shape[1]),
        "excluded_sids": list(map(str, data["excluded_sids"])),
        "target_changed_sids": [
            str(sid)
            for sid, delta in zip(data["sids"], data["target_delta_original_minus_validrange"])
            if abs(float(delta)) > 1e-9
        ],
    }


TARGETS: list[tuple[str, str, Callable[[], dict[str, Any]]]] = [
    (
        "t1_iter12_recompute",
        "Recompute the iter12 honest composite metrics with the narrowed local target loader; no prereg/write path.",
        target_t1_iter12_recompute,
    ),
    (
        "t1_iter34_loader",
        "Load the iter34/iter46 T1 cohort plus Stage-1 clinical design without fitting folds.",
        target_t1_iter34_loader,
    ),
    (
        "t3_iter47_filter_minimal",
        "Load the current T3 valid-range minimal cohort without fitting LOOCV.",
        target_t3_iter47_filter_minimal,
    ),
]


def run_targets() -> list[dict[str, Any]]:
    rows = artifact_rows()
    reports = []
    for name, description, func in TARGETS:
        start_idx = len(RECORDER.events)
        start_time = time.time()
        status = "ok"
        result: dict[str, Any] | None = None
        error: str | None = None
        try:
            result = func()
        except Exception as exc:  # pragma: no cover - surfaced in report.
            status = "error"
            error = f"{exc.__class__.__name__}: {exc}"
        events = RECORDER.events[start_idx:]
        opened = _opened_cache_artifacts(events, rows)
        reports.append(
            {
                "target": name,
                "description": description,
                "status": status,
                "error": error,
                "duration_s": round(time.time() - start_time, 3),
                "result": result,
                "n_open_events": len(events),
                "opened_cache_artifacts": opened,
                "opened_diagnostic_or_partial_cache_artifacts": [
                    item["artifact"]
                    for item in opened
                    if item["artifact_status"] != "manifest_complete_clean_by_construction"
                ],
            }
        )
    return reports


def main() -> None:
    reports = run_targets()
    all_opened = sorted(
        {
            artifact
            for report in reports
            for artifact in report["opened_diagnostic_or_partial_cache_artifacts"]
        }
    )
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_runtime_cache_dependencies.py",
        "source_manifest_audit": str(MANIFEST_AUDIT.relative_to(ROOT)),
        "method": "Python sys.addaudithook('open') around lightweight in-process data-load/recompute paths",
        "limitations": [
            "Diagnostic only: a negative trace is not proof for unexercised branches or future flags.",
            "Does not replace static import cleanliness or concrete cache manifests.",
            "In-process audit hook does not trace subprocesses spawned outside this interpreter.",
        ],
        "targets": [name for name, _description, _func in TARGETS],
        "opened_diagnostic_or_partial_cache_artifacts": all_opened,
        "target_reports": reports,
        "verdict": (
            "The narrowed T1 iter12 recompute executes only the V2 SID-order cache among "
            "cache-like artifacts, eliminating the previous executed per-item/MOMENT/HC-SSL/"
            "walkway cache reads. T1 iter34's current fail-closed loader now produces N=92 "
            "after the auxiliary valid-range fix, so it is not a reproduction path for the "
            "historical N=93 lockbox; it still executes ablation_v3_features.csv. T3 iter47 "
            "also executes ablation_v3_features.csv. Static velinc reachability did not "
            "execute in these lightweight paths. Runtime tracing is diagnostic and does not "
            "make missing manifests headline-safe."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Runtime Cache Dependency Audit — 2026-05-08",
        "",
        "This installs a Python `sys.addaudithook('open')` hook, then runs lightweight data-load/recompute paths for current headline/candidate scripts. It distinguishes executed cache reads from static import-only reachability for these paths.",
        "",
        "Runtime tracing is diagnostic only. It does not prove unexercised branches are safe and does not replace static import cleanup or concrete cache manifests.",
        "",
        "## Summary",
        "",
        "- Diagnostic/partial cache-like artifacts opened: "
        + (", ".join(f"`{artifact}`" for artifact in all_opened) if all_opened else "none"),
        "",
        "## Targets",
        "",
    ]
    for item in reports:
        opened = item["opened_cache_artifacts"]
        lines.append(f"### `{item['target']}`")
        lines.append(f"- Status: `{item['status']}`")
        lines.append(f"- Result: `{item['result']}`")
        if opened:
            lines.append(
                "- Opened cache-like artifacts: "
                + ", ".join(
                    f"`{row['artifact']}` ({row['artifact_status']}, events={row['event_count']})"
                    for row in opened
                )
            )
        else:
            lines.append("- Opened cache-like artifacts: none")
        if item["error"]:
            lines.append(f"- Error: `{item['error']}`")
        lines.append("")
    lines.extend(["## Verdict", "", report["verdict"], "", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"opened_diagnostic_or_partial_cache_artifacts": all_opened}, indent=2))


if __name__ == "__main__":
    main()
