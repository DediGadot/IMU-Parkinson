#!/usr/bin/env python3
"""Residual-anatomy audit for the hygiene-corrected T1 iter34 candidate.

This is intentionally not a model run. It uses existing OOF artifacts plus the
current valid-range per-item labels to decide whether the corrected candidate
exposes a fresh, non-ruled-out local architecture angle.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from inductive_lib import ccc as ccc_fn
from updrs_columns import valid_updrs_item_total


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

CURRENT_RESULT = RESULTS / "lockbox_t1_iter34_hybrid_20260510_233019.json"
ORIGINAL_RESULT = RESULTS / "lockbox_t1_iter34_hybrid_20260506_141720.json"
ITER12_RESULT = RESULTS / "t1_iter12_honest_composite.json"
OUT_JSON = RESULTS / "t1_hygiene_residual_anatomy_20260510.json"
OUT_MD = RESULTS / "t1_hygiene_residual_anatomy_20260510.md"
OUT_ROWS = RESULTS / "t1_hygiene_residual_anatomy_rows_20260510.csv"
PER_ITEM_CACHE = RESULTS / "per_item_scores.json"
FEATURE_CACHE = RESULTS / "ablation_v3_features.csv"
T1_ITEMS = [9, 10, 11, 12, 13, 14]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def result_vectors(path: Path) -> tuple[list[str], np.ndarray, np.ndarray]:
    payload = load_json(path)
    per_subject = payload["per_subject"]
    sids = [str(sid) for sid in per_subject["sids"]]
    return (
        sids,
        np.asarray(per_subject["y_true"], dtype=np.float64),
        np.asarray(per_subject["y_pred"], dtype=np.float64),
    )


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 3:
        return 0.0
    aa = a[mask]
    bb = b[mask]
    if float(np.std(aa)) < 1e-9 or float(np.std(bb)) < 1e-9:
        return 0.0
    return float(np.corrcoef(aa, bb)[0, 1])


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(y, dtype=np.float64) - np.asarray(p, dtype=np.float64))))


def metric_row(y: np.ndarray, p: np.ndarray) -> dict[str, float | int]:
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    return {
        "n": int(len(y)),
        "ccc": float(ccc_fn(y, p)),
        "mae": mae(y, p),
        "r": pearson(y, p),
        "pred_mean": float(np.mean(p)),
        "pred_std": float(np.std(p)),
        "true_mean": float(np.mean(y)),
        "true_std": float(np.std(y)),
    }


def aligned_predictions(path: Path, sids: list[str]) -> np.ndarray:
    other_sids, _, other_pred = result_vectors(path)
    sid_to_pred = dict(zip(other_sids, other_pred.tolist()))
    return np.asarray([sid_to_pred[sid] for sid in sids], dtype=np.float64)


def load_t1_context() -> dict[str, dict[str, Any]]:
    raw_items = load_json(PER_ITEM_CACHE)
    context: dict[str, dict[str, Any]] = {}
    for sid, scores in raw_items.items():
        item_values: dict[int, float] = {}
        for item in range(1, 19):
            raw_value = scores.get(str(item))
            valid_value = valid_updrs_item_total(item, raw_value)
            if valid_value is not None:
                item_values[item] = float(valid_value)
        context[str(sid)] = {"items": item_values, "hy": None, "obs": None}

    with FEATURE_CACHE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = str(row.get("sid", ""))
            if sid not in context:
                continue
            context[sid]["hy"] = parse_optional_float(row.get("hy"))
            context[sid]["obs"] = parse_optional_float(row.get("obs_subscore"))
    return context


def parse_optional_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return parsed if np.isfinite(parsed) else float("nan")


def quantile_bins(y: np.ndarray, p: np.ndarray, signed_error: np.ndarray) -> list[dict[str, Any]]:
    quartiles = np.quantile(y, [0.25, 0.50, 0.75])
    bins = np.digitize(y, quartiles)
    rows: list[dict[str, Any]] = []
    for idx in range(4):
        mask = bins == idx
        rows.append(
            {
                "bin": int(idx),
                "n": int(mask.sum()),
                "target_min": float(np.min(y[mask])),
                "target_max": float(np.max(y[mask])),
                "ccc": float(ccc_fn(y[mask], p[mask])),
                "mae": mae(y[mask], p[mask]),
                "mean_signed_error_pred_minus_true": float(np.mean(signed_error[mask])),
            }
        )
    return rows


def site_rows(sids: list[str], y: np.ndarray, p: np.ndarray, signed_error: np.ndarray) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sid_arr = np.asarray(sids)
    for site in ("NLS", "WPD"):
        mask = np.asarray([sid.startswith(site) for sid in sid_arr], dtype=bool)
        rows.append(
            {
                "site": site,
                "n": int(mask.sum()),
                "ccc": float(ccc_fn(y[mask], p[mask])),
                "mae": mae(y[mask], p[mask]),
                "mean_signed_error_pred_minus_true": float(np.mean(signed_error[mask])),
            }
        )
    return rows


def leave_one_influence(sids: list[str], y: np.ndarray, p: np.ndarray) -> list[dict[str, Any]]:
    base = float(ccc_fn(y, p))
    rows: list[dict[str, Any]] = []
    for idx, sid in enumerate(sids):
        mask = np.ones(len(sids), dtype=bool)
        mask[idx] = False
        without = float(ccc_fn(y[mask], p[mask]))
        rows.append(
            {
                "sid": sid,
                "target": float(y[idx]),
                "prediction": float(p[idx]),
                "signed_error_pred_minus_true": float(p[idx] - y[idx]),
                "ccc_without_subject": without,
                "delta_without_minus_full": float(without - base),
                "abs_delta": float(abs(without - base)),
            }
        )
    return sorted(rows, key=lambda row: row["abs_delta"], reverse=True)


def build_report() -> dict[str, Any]:
    sids, y, p = result_vectors(CURRENT_RESULT)
    current_payload = load_json(CURRENT_RESULT)
    signed_error = p - y
    abs_error = np.abs(signed_error)

    context = load_t1_context()
    missing_data = [
        sid for sid in sids
        if sid not in context or not all(item in context[sid]["items"] for item in T1_ITEMS)
    ]
    if missing_data:
        raise RuntimeError(f"current result SIDs missing valid T1 context: {missing_data}")

    item_values = {
        item: np.asarray([context[sid]["items"][item] for sid in sids], dtype=np.float64)
        for item in T1_ITEMS
    }
    hy = np.asarray([context[sid]["hy"] for sid in sids], dtype=np.float64)
    obs = np.asarray([context[sid]["obs"] for sid in sids], dtype=np.float64)

    iter12_pred = aligned_predictions(ITER12_RESULT, sids)
    original_pred = aligned_predictions(ORIGINAL_RESULT, sids)

    item_residual_rows = []
    for item, values in item_values.items():
        item_residual_rows.append(
            {
                "item": int(item),
                "target_mean": float(np.mean(values)),
                "signed_error_corr": pearson(signed_error, values),
                "abs_error_corr": pearson(abs_error, values),
            }
        )
    item_residual_rows = sorted(
        item_residual_rows,
        key=lambda row: max(abs(row["signed_error_corr"]), abs(row["abs_error_corr"])),
        reverse=True,
    )

    influence_rows = leave_one_influence(sids, y, p)
    subject_rows = []
    for idx, sid in enumerate(sids):
        subject_rows.append(
            {
                "sid": sid,
                "site": "NLS" if sid.startswith("NLS") else "WPD" if sid.startswith("WPD") else "other",
                "y_true": float(y[idx]),
                "y_pred": float(p[idx]),
                "signed_error_pred_minus_true": float(signed_error[idx]),
                "abs_error": float(abs_error[idx]),
                "iter12_pred_common_sid": float(iter12_pred[idx]),
                "original_iter34_pred_common_sid": float(original_pred[idx]),
                "hy": float(hy[idx]) if np.isfinite(hy[idx]) else None,
                "obs_subscore": float(obs[idx]) if np.isfinite(obs[idx]) else None,
                **{f"item_{item}": float(item_values[item][idx]) for item in T1_ITEMS},
            }
        )

    common_iter12 = metric_row(y, iter12_pred)
    common_original = metric_row(y, original_pred)
    current = metric_row(y, p)
    max_item_signed = max(item_residual_rows, key=lambda row: abs(row["signed_error_corr"]))
    max_item_abs = max(item_residual_rows, key=lambda row: abs(row["abs_error_corr"]))
    max_influence = influence_rows[0]
    site_summary = site_rows(sids, y, p, signed_error)
    nls_ccc = next(row["ccc"] for row in site_summary if row["site"] == "NLS")
    wpd_ccc = next(row["ccc"] for row in site_summary if row["site"] == "WPD")

    checks = [
        {
            "name": "current corrected result is N=92 and non-canonical",
            "passed": (
                current_payload.get("n") == 92
                and current_payload.get("is_canonical_update") is False
                and current_payload.get("canonical_update_policy")
                == "disabled_for_hygiene_correction_replication"
            ),
            "evidence": {
                "n": current_payload.get("n"),
                "is_canonical_update": current_payload.get("is_canonical_update"),
                "canonical_update_policy": current_payload.get("canonical_update_policy"),
            },
        },
        {
            "name": "corrected candidate still lifts over iter12 on common SIDs",
            "passed": current["ccc"] > common_iter12["ccc"],
            "evidence": {
                "current_common_ccc": current["ccc"],
                "iter12_common_ccc": common_iter12["ccc"],
                "delta": float(current["ccc"] - common_iter12["ccc"]),
            },
        },
        {
            "name": "corrected candidate is degraded versus original iter34 on common SIDs",
            "passed": current["ccc"] < common_original["ccc"],
            "evidence": {
                "current_common_ccc": current["ccc"],
                "original_common_ccc": common_original["ccc"],
                "delta": float(current["ccc"] - common_original["ccc"]),
            },
        },
        {
            "name": "no single-subject redline above 0.05 leave-one CCC impact",
            "passed": max_influence["abs_delta"] < 0.05,
            "evidence": max_influence,
        },
    ]

    decision = "diagnostic_only_external_data_first_remains"
    if abs(max_item_signed["signed_error_corr"]) >= 0.45 or abs(max_item_abs["abs_error_corr"]) >= 0.45:
        decision = "diagnostic_item_signal_present_requires_fresh_screen"
    if abs(float(nls_ccc) - float(wpd_ccc)) >= 0.15:
        decision = "diagnostic_site_gap_present_no_local_lockbox_without_new_data"

    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_t1_hygiene_residual_anatomy.py",
        "not_a_model_run": True,
        "goal_complete": False,
        "passed": all(row["passed"] for row in checks),
        "decision": decision,
        "inputs": {
            "current_result": CURRENT_RESULT.relative_to(ROOT).as_posix(),
            "original_iter34_result": ORIGINAL_RESULT.relative_to(ROOT).as_posix(),
            "iter12_result": ITER12_RESULT.relative_to(ROOT).as_posix(),
        },
        "current_metrics": current,
        "iter12_common_sid_metrics": common_iter12,
        "original_iter34_common_sid_metrics": common_original,
        "delta_current_vs_iter12_common_ccc": float(current["ccc"] - common_iter12["ccc"]),
        "delta_current_vs_original_common_ccc": float(current["ccc"] - common_original["ccc"]),
        "prediction_corr_current_vs_iter12": pearson(p, iter12_pred),
        "prediction_corr_current_vs_original": pearson(p, original_pred),
        "residual_correlations": {
            "target_signed_error": pearson(signed_error, y),
            "target_abs_error": pearson(abs_error, y),
            "hy_signed_error": pearson(signed_error, hy),
            "hy_abs_error": pearson(abs_error, hy),
            "obs_signed_error": pearson(signed_error, obs),
            "obs_abs_error": pearson(abs_error, obs),
        },
        "item_residual_rows": item_residual_rows,
        "target_quantile_rows": quantile_bins(y, p, signed_error),
        "site_rows": site_summary,
        "top_leave_one_influence": influence_rows[:10],
        "top_abs_error_subjects": sorted(subject_rows, key=lambda row: row["abs_error"], reverse=True)[:10],
        "checks": checks,
        "hard_failures": [row for row in checks if not row["passed"]],
        "interpretation": (
            "The hygiene-corrected T1 candidate keeps a common-SID lift over iter12, "
            "but it is lower than the original contaminated/caveated iter34. Residual "
            "structure is mostly tail/site/postural-item anatomy already represented "
            "in previous failed local screens, so this audit does not justify a new "
            "WearGait-only lockbox. The architecture recommendation remains "
            "external-data-first."
        ),
        "rows_csv": OUT_ROWS.relative_to(ROOT).as_posix(),
    }, subject_rows


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report, subject_rows = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    with OUT_ROWS.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(subject_rows[0].keys()))
        writer.writeheader()
        writer.writerows(subject_rows)

    item_lines = [
        f"- Item `{row['item']}`: signed-error r `{row['signed_error_corr']:+.3f}`, abs-error r `{row['abs_error_corr']:+.3f}`"
        for row in report["item_residual_rows"][:6]
    ]
    quantile_lines = [
        (
            f"| {row['bin']} | {row['n']} | {row['target_min']:.1f}-{row['target_max']:.1f} | "
            f"{row['ccc']:+.3f} | {row['mae']:.3f} | {row['mean_signed_error_pred_minus_true']:+.3f} |"
        )
        for row in report["target_quantile_rows"]
    ]
    site_lines = [
        f"| {row['site']} | {row['n']} | {row['ccc']:+.3f} | {row['mae']:.3f} | {row['mean_signed_error_pred_minus_true']:+.3f} |"
        for row in report["site_rows"]
    ]
    lines = [
        "# T1 Hygiene-Corrected Residual Anatomy - 2026-05-10",
        "",
        "This audit uses existing OOF artifacts only. It is not a model run and does not update canonicals.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Current corrected CCC: `{report['current_metrics']['ccc']:.4f}`",
        f"- Delta vs iter12 on common SIDs: `{report['delta_current_vs_iter12_common_ccc']:+.4f}`",
        f"- Delta vs original iter34 on common SIDs: `{report['delta_current_vs_original_common_ccc']:+.4f}`",
        f"- Max leave-one |dCCC|: `{report['top_leave_one_influence'][0]['abs_delta']:.4f}`",
        "",
        "## Item Residual Associations",
        "",
        *item_lines,
        "",
        "## Target Bins",
        "",
        "| Bin | N | T1 range | CCC | MAE | Mean signed error |",
        "|---:|---:|---:|---:|---:|---:|",
        *quantile_lines,
        "",
        "## Site Summary",
        "",
        "| Site | N | CCC | MAE | Mean signed error |",
        "|---|---:|---:|---:|---:|",
        *site_lines,
        "",
        "## Interpretation",
        "",
        report["interpretation"],
        "",
        f"Rows: `{report['rows_csv']}`",
        f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_ROWS}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "current_ccc": report["current_metrics"]["ccc"],
                "delta_vs_iter12_common": report["delta_current_vs_iter12_common_ccc"],
                "delta_vs_original_common": report["delta_current_vs_original_common_ccc"],
                "hard_failures": len(report["hard_failures"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if report["hard_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
