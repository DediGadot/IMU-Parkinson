#!/usr/bin/env python3
"""Audit per-item OOF companion arrays and their reporting scope.

The per-item lockbox JSONs do not store row-level predictions. They store
summary metrics, often as seed means, while the ``.oof.npy`` companions are the
slot-aligned prediction arrays used by composite scripts. This audit verifies
the companion arrays are present, numeric, finite, and correctly scoped without
pretending that a row-level JSON comparison is available.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from compose_t1_iter12_honest import T1_ITEMS, load_composite_target_data
from inductive_lib import ccc as ccc_fn, mae as mae_fn


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "per_item_oof_companion_scope_audit_20260508.json"
OUT_MD = RESULTS / "per_item_oof_companion_scope_audit_20260508.md"

PER_ITEM_MAP = RESULTS / "per_item_evidence_map_20260508.json"
T1_COMPOSITE_JSON = RESULTS / "t1_iter12_honest_composite.json"
T1_COMPOSITE_OOF = RESULTS / "t1_iter12_honest_composite.oof.npy"

CURRENT_T1_OOF_SLOTS = 94
TOL = 1e-9


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def clean(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def approx(value: Any, expected: float, tol: float = 5e-4) -> bool:
    try:
        return abs(float(value) - expected) <= tol
    except (TypeError, ValueError):
        return False


def oof_path_for(artifact: str) -> Path:
    return (ROOT / artifact).with_suffix(".oof.npy")


def first_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            if isinstance(value, bool):
                continue
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def json_reported_n(data: dict[str, Any], row: dict[str, Any]) -> int | None:
    return first_int(
        data.get("n"),
        data.get("n_subjects"),
        data.get("n_subjects_valid"),
        row.get("n"),
    )


def audit_row(row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    artifact = row.get("individual_lockbox_artifact")
    if not artifact:
        return (
            {
                "item": row.get("item"),
                "status": row.get("status"),
                "has_oof_companion": False,
                "passed": True,
                "reason": "backfill-only row has no individual lockbox artifact",
            },
            warnings,
        )

    json_path = ROOT / artifact
    oof_path = oof_path_for(artifact)
    data = load_json(json_path)
    reported_n = json_reported_n(data, row)
    has_row_predictions = isinstance(data.get("per_subject"), dict) and "y_pred" in data.get("per_subject", {})

    arr: np.ndarray | None = None
    load_error: str | None = None
    if oof_path.exists():
        try:
            arr = np.load(oof_path, allow_pickle=False)
        except Exception as exc:  # pragma: no cover - defensive guard for corrupted artifacts
            load_error = repr(exc)

    numeric = bool(arr is not None and np.issubdtype(arr.dtype, np.number))
    finite = bool(arr is not None and numeric and np.isfinite(arr).all())
    one_dimensional = bool(arr is not None and arr.ndim == 1)
    slot_len = int(arr.shape[0]) if arr is not None and arr.ndim >= 1 else None
    expected_slot_shape = bool(
        one_dimensional
        and slot_len is not None
        and (slot_len == reported_n or slot_len == CURRENT_T1_OOF_SLOTS)
    )
    reported_n_matches_slots = reported_n == slot_len

    if has_row_predictions:
        warnings.append(
            {
                "item": row.get("item"),
                "warning": "unexpected_row_level_predictions_in_per_item_json",
                "artifact": artifact,
            }
        )
    if reported_n is not None and slot_len is not None and reported_n != slot_len:
        warnings.append(
            {
                "item": row.get("item"),
                "warning": "json_reported_valid_n_differs_from_oof_slot_len",
                "artifact": artifact,
                "json_reported_n": reported_n,
                "oof_slot_len": slot_len,
                "interpretation": "companion array has full 94-slot cohort shape; JSON reports valid target/evaluation count.",
            }
        )
    if row.get("n") is not None and reported_n is not None and int(row["n"]) != reported_n:
        warnings.append(
            {
                "item": row.get("item"),
                "warning": "per_item_map_n_differs_from_lockbox_json_n",
                "artifact": artifact,
                "map_n": int(row["n"]),
                "json_reported_n": reported_n,
                "interpretation": "Regenerate the per-item evidence map so historical rows use individual lockbox N.",
            }
        )

    passed = bool(
        json_path.exists()
        and oof_path.exists()
        and load_error is None
        and numeric
        and finite
        and expected_slot_shape
        and not has_row_predictions
    )
    check = {
        "item": row.get("item"),
        "status": row.get("status"),
        "variant": row.get("variant"),
        "json": str(json_path.relative_to(ROOT)),
        "oof": str(oof_path.relative_to(ROOT)),
        "json_exists": json_path.exists(),
        "oof_exists": oof_path.exists(),
        "json_reported_n": reported_n,
        "oof_shape": list(arr.shape) if arr is not None else None,
        "oof_dtype": str(arr.dtype) if arr is not None else None,
        "oof_numeric": numeric,
        "oof_finite": finite,
        "expected_slot_shape": expected_slot_shape,
        "reported_n_matches_slots": reported_n_matches_slots,
        "row_level_json_comparison_available": has_row_predictions,
        "json_top_level_keys": sorted(data.keys()),
        "load_error": load_error,
        "passed": passed,
    }
    return check, warnings


def t1_companion_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_by_item = {int(row["item"]): row for row in rows}
    target_data = load_composite_target_data()
    item_targets = target_data["items"]
    t1_target = np.asarray(target_data["t1"], dtype=float)

    summed = np.zeros(CURRENT_T1_OOF_SLOTS, dtype=float)
    per_item_metrics = []
    for item in T1_ITEMS:
        row = row_by_item[item]
        oof = np.load(oof_path_for(row["individual_lockbox_artifact"]), allow_pickle=False)
        if oof.shape != (CURRENT_T1_OOF_SLOTS,):
            raise ValueError(f"T1 item {item} OOF shape {oof.shape} != ({CURRENT_T1_OOF_SLOTS},)")
        summed += oof
        y = np.asarray(item_targets[item], dtype=float)
        valid = np.isfinite(y) & np.isfinite(oof)
        per_item_metrics.append(
            {
                "item": item,
                "valid_target_n": int(valid.sum()),
                "oof_companion_ccc": float(ccc_fn(y[valid], oof[valid])),
                "oof_companion_mae": float(mae_fn(y[valid], oof[valid])),
                "map_summary_ccc": row.get("ccc"),
                "map_summary_mae": row.get("mae"),
                "metric_relation": "OOF companion metric is not expected to equal map summary metric because the per-item JSON stores seed-summary metrics, not row-level ensemble predictions.",
            }
        )

    composite_oof = np.load(T1_COMPOSITE_OOF, allow_pickle=False)
    same_shape = summed.shape == composite_oof.shape
    max_abs_diff = float(np.max(np.abs(summed - composite_oof))) if same_shape else None
    valid_t1 = np.isfinite(t1_target) & np.isfinite(summed)
    t1_metrics = {
        "n": int(valid_t1.sum()),
        "ccc": float(ccc_fn(t1_target[valid_t1], summed[valid_t1])),
        "mae": float(mae_fn(t1_target[valid_t1], summed[valid_t1])),
    }
    t1_json = load_json(T1_COMPOSITE_JSON)
    passed = bool(
        same_shape
        and max_abs_diff is not None
        and max_abs_diff <= TOL
        and all(row["valid_target_n"] == CURRENT_T1_OOF_SLOTS for row in per_item_metrics)
        and t1_metrics["n"] == t1_json.get("n")
        and approx(t1_metrics["ccc"], t1_json.get("ccc"), 5e-4)
        and approx(t1_metrics["mae"], t1_json.get("mae"), 5e-4)
    )
    return {
        "name": "t1_iter12_item_oofs_sum_to_canonical_oof",
        "passed": passed,
        "items": list(T1_ITEMS),
        "summed_shape": list(summed.shape),
        "composite_oof_shape": list(composite_oof.shape),
        "max_abs_diff_vs_t1_composite_oof": max_abs_diff,
        "tolerance": TOL,
        "t1_metrics_from_summed_item_oofs": t1_metrics,
        "t1_json_metrics": {
            "n": t1_json.get("n"),
            "ccc": t1_json.get("ccc"),
            "mae": t1_json.get("mae"),
        },
        "per_item_oof_companion_metrics": per_item_metrics,
    }


def build_report() -> dict[str, Any]:
    per_item_map = load_json(PER_ITEM_MAP)
    rows = per_item_map.get("rows", [])
    checks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for row in rows:
        check, row_warnings = audit_row(row)
        if check.get("has_oof_companion") is not False:
            checks.append(check)
        warnings.extend(row_warnings)

    t1_check = t1_companion_check(rows)
    oof_backed = [check for check in checks if check.get("oof")]
    row_level_unavailable = [
        check for check in oof_backed if not check.get("row_level_json_comparison_available")
    ]
    item18_warning = [
        warning
        for warning in warnings
        if warning.get("item") == 18
        and warning.get("warning") == "json_reported_valid_n_differs_from_oof_slot_len"
    ]

    key_checks = [
        {
            "name": "per_item_map_source_passed",
            "passed": per_item_map.get("passed") is True,
            "evidence": {"source": str(PER_ITEM_MAP.relative_to(ROOT))},
        },
        {
            "name": "all_15_oof_backed_rows_have_finite_expected_slot_arrays",
            "passed": len(oof_backed) == 15 and all(check.get("passed") is True for check in oof_backed),
            "evidence": {
                "n_oof_backed": len(oof_backed),
                "failed": [
                    check
                    for check in oof_backed
                    if check.get("passed") is not True
                ],
            },
        },
        {
            "name": "row_level_json_prediction_comparison_unavailable_for_per_item_artifacts",
            "passed": len(row_level_unavailable) == 15,
            "evidence": {
                "n_unavailable": len(row_level_unavailable),
                "policy": "Per-item JSONs lack per_subject.y_pred; this audit checks companion scope and T1 summation instead.",
            },
        },
        t1_check,
        {
            "name": "item18_valid_n_mismatch_recorded_as_warning_not_failure",
            "passed": bool(item18_warning),
            "evidence": item18_warning,
        },
    ]
    hard_warning_types = {
        "unexpected_row_level_predictions_in_per_item_json",
    }
    hard_warnings = [w for w in warnings if w.get("warning") in hard_warning_types]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_per_item_oof_companion_scope.py",
        "policy": (
            "Per-item OOF companions are scope/integrity checked as finite one-dimensional arrays "
            "whose length matches either the JSON-reported evaluation N or the current 94-slot T1 cohort. "
            "Per-item JSON row-level equality cannot be checked because the JSON artifacts do not "
            "contain per_subject.y_pred. For current T1 items 9-14, the companion arrays must sum "
            "exactly to the canonical iter12 T1 OOF vector."
        ),
        "passed": all(check.get("passed") is True for check in key_checks) and not hard_warnings,
        "source_per_item_map": str(PER_ITEM_MAP.relative_to(ROOT)),
        "current_t1_oof_slots": CURRENT_T1_OOF_SLOTS,
        "oof_backed_rows": len(oof_backed),
        "row_level_json_comparison_available_count": 15 - len(row_level_unavailable),
        "checks": checks,
        "key_checks": key_checks,
        "warnings": warnings,
        "hard_warnings": hard_warnings,
    }
    return clean(report)


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def write_markdown(report: dict[str, Any]) -> None:
    t1_check = next(
        check
        for check in report["key_checks"]
        if check["name"] == "t1_iter12_item_oofs_sum_to_canonical_oof"
    )
    lines = [
        "# Per-Item OOF Companion Scope Audit - 2026-05-08",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- OOF-backed rows: `{report['oof_backed_rows']}`",
        f"- Row-level JSON comparison available count: `{report['row_level_json_comparison_available_count']}`",
        f"- Warnings: `{len(report['warnings'])}`",
        "",
        "## Key Checks",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for check in report["key_checks"]:
        lines.append(f"| {check['name']} | `{check['passed']}` |")

    t1_metrics = t1_check["t1_metrics_from_summed_item_oofs"]
    lines.extend(
        [
            "",
            "## T1 Iter12 Companion Summation",
            "",
            f"- Max abs diff vs canonical T1 OOF: `{fmt(t1_check['max_abs_diff_vs_t1_composite_oof'], 10)}`",
            f"- Recomputed CCC from summed item OOFs: `{fmt(t1_metrics['ccc'])}`",
            f"- Recomputed MAE from summed item OOFs: `{fmt(t1_metrics['mae'], 3)}`",
            "",
            "| Item | Valid target N | OOF companion CCC | Map summary CCC | Relation |",
            "|---:|---:|---:|---:|---|",
        ]
    )
    for row in t1_check["per_item_oof_companion_metrics"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["item"]),
                    str(row["valid_target_n"]),
                    fmt(row["oof_companion_ccc"]),
                    fmt(row["map_summary_ccc"]),
                    row["metric_relation"],
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## OOF-Backed Rows",
            "",
            "| Item | Status | JSON N | OOF shape | Finite | Row-level JSON comparison | Passed |",
            "|---:|---|---:|---|---:|---:|---:|",
        ]
    )
    for check in report["checks"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(check["item"]),
                    str(check["status"]),
                    str(check.get("json_reported_n") or "n/a"),
                    str(check.get("oof_shape")),
                    f"`{check.get('oof_finite')}`",
                    f"`{check.get('row_level_json_comparison_available')}`",
                    f"`{check.get('passed')}`",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Warnings",
            "",
        ]
    )
    if report["warnings"]:
        for warning in report["warnings"]:
            lines.append(f"- item {warning.get('item')}: `{warning.get('warning')}` ({warning})")
    else:
        lines.append("- none")
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "oof_backed_rows": report["oof_backed_rows"],
                "warnings": len(report["warnings"]),
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
