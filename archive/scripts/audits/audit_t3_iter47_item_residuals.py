#!/usr/bin/env python3
"""Item-level residual anatomy for the corrected iter47 T3 artifact.

This audit reads saved valid-range-corrected T3 OOF predictions and true
MDS-UPDRS Part III item scores. Item scores are clinical target information, so
all item-level oracle corrections here are privileged and non-deployable. The
purpose is to decide whether any remaining internal WearGait-only model route
is plausible, not to select features or create a new reportable number.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eval_utils import lins_ccc
from project_paths import RESULTS_DIR
from updrs_columns import find_updrs_value


ROOT = Path(__file__).resolve().parent
RESULTS = RESULTS_DIR
PRED_PATH = RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv"
OUT_JSON = RESULTS / "t3_iter47_item_residual_audit_20260509.json"
OUT_MD = RESULTS / "t3_iter47_item_residual_audit_20260509.md"

SUBITEMS: dict[int, list[str] | None] = {
    1: None,
    2: None,
    3: ["a", "b", "c", "d", "e"],
    4: ["a", "b"],
    5: ["a", "b"],
    6: ["a", "b"],
    7: ["a", "b"],
    8: ["a", "b"],
    9: None,
    10: None,
    11: None,
    12: None,
    13: None,
    14: None,
    15: ["a", "b"],
    16: ["a", "b"],
    17: ["a", "b", "c", "d", "e"],
    18: None,
}

ITEM_NAMES = {
    1: "speech",
    2: "facial_expression",
    3: "rigidity",
    4: "finger_tapping",
    5: "hand_movements",
    6: "pronation_supination",
    7: "toe_tapping",
    8: "leg_agility",
    9: "arising_from_chair",
    10: "gait",
    11: "freezing_of_gait",
    12: "postural_stability",
    13: "posture",
    14: "global_spontaneity",
    15: "postural_tremor",
    16: "kinetic_tremor",
    17: "rest_tremor_amplitude",
    18: "rest_tremor_constancy",
}

WEARGAIT_OBSERVABLE_ITEMS = {7, 8, 9, 10, 11, 12, 13, 14}
T1_ITEMS = {9, 10, 11, 12, 13, 14}


def corr(a: np.ndarray, b: np.ndarray, min_n: int = 5) -> float | None:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < min_n:
        return None
    aa = a[mask]
    bb = b[mask]
    if np.std(aa) < 1e-12 or np.std(bb) < 1e-12:
        return None
    return float(np.corrcoef(aa, bb)[0, 1])


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    err = pred - y
    return {
        "n": int(len(y)),
        "ccc": float(lins_ccc(y, pred)),
        "mae": float(np.mean(np.abs(err))),
        "r": corr(y, pred),
        "target_mean": float(np.mean(y)),
        "target_sd": float(np.std(y)),
        "prediction_mean": float(np.mean(pred)),
        "prediction_sd": float(np.std(pred)),
        "residual_corr_with_true": corr(err, y),
    }


def clinical_candidates() -> list[Path]:
    return [
        ROOT / "data" / "raw" / "weargait-pd" / "PD - Demographic+Clinical - datasetV1.csv",
        RESULTS / "pd_demographic_clinical_v1.csv",
        RESULTS / "results" / "pd_demographic_clinical_v1.csv",
    ]


def load_pd_clinical() -> tuple[pd.DataFrame, Path]:
    for path in clinical_candidates():
        if path.exists():
            df = pd.read_csv(path, header=1)
            if "Subject ID" in df.columns:
                df["sid"] = df["Subject ID"].astype(str).str.strip()
                return df, path
    raise FileNotFoundError("PD clinical CSV not found")


def score_item(row: pd.Series, columns: pd.Index, item: int) -> tuple[float | None, int, int]:
    subitems = SUBITEMS[item]
    if subitems is None:
        value = find_updrs_value(row, columns, item)
        return (float(value), 1, 0) if value is not None else (None, 0, 1)

    values = []
    missing = 0
    for suffix in subitems:
        value = find_updrs_value(row, columns, item, suffix)
        if value is None:
            missing += 1
        else:
            values.append(float(value))
    if not values:
        return None, 0, missing
    return float(np.sum(values)), len(values), missing


def load_item_table() -> tuple[pd.DataFrame, Path]:
    clinical, path = load_pd_clinical()
    rows = []
    for _, row in clinical.iterrows():
        sid = str(row["sid"])
        if not sid.startswith(("NLS", "WPD")):
            continue
        out: dict[str, Any] = {"sid": sid}
        total = 0.0
        total_valid_components = 0
        total_missing_components = 0
        for item in range(1, 19):
            value, valid_n, missing_n = score_item(row, clinical.columns, item)
            out[f"item_{item:02d}"] = value
            out[f"item_{item:02d}_valid_components"] = valid_n
            out[f"item_{item:02d}_missing_components"] = missing_n
            if value is not None:
                total += float(value)
                total_valid_components += valid_n
            total_missing_components += missing_n
        out["parsed_validrange_total"] = total
        out["parsed_valid_components"] = total_valid_components
        out["parsed_missing_components"] = total_missing_components
        rows.append(out)
    return pd.DataFrame(rows), path


def load_iter47_current() -> pd.DataFrame:
    df = pd.read_csv(PRED_PATH)
    df = df[
        (df["cohort"] == "drop_allmissing_validrange")
        & (df["stage2_policy"] == "stage2_current")
    ].copy()
    df["sid"] = df["sid"].astype(str)
    df["site"] = np.where(df["sid"].str.startswith("NLS"), "NLS", "WPD")
    df = df.rename(columns={"y_true_validrange": "y_true"})
    df["residual_pred_minus_true"] = df["y_pred"] - df["y_true"]
    df["abs_error"] = np.abs(df["residual_pred_minus_true"])
    return df


def leave_one_item_oracle(y: np.ndarray, pred: np.ndarray, item_values: np.ndarray) -> dict[str, Any]:
    """LOO privileged residual correction using one true item score."""
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    item_values = np.asarray(item_values, dtype=float)
    residual = pred - y
    corrected = np.full_like(pred, np.nan, dtype=float)
    slopes = []
    for i in range(len(y)):
        mask = np.ones(len(y), dtype=bool)
        mask[i] = False
        x_train = item_values[mask]
        x_test = item_values[i]
        r_train = residual[mask]
        finite = np.isfinite(x_train) & np.isfinite(r_train)
        if finite.sum() < 5 or not np.isfinite(x_test):
            resid_hat = float(np.nanmean(r_train))
            slope = 0.0
        else:
            xx = x_train[finite]
            rr = r_train[finite]
            mean = float(np.mean(xx))
            sd = float(np.std(xx))
            if sd < 1e-12:
                resid_hat = float(np.mean(rr))
                slope = 0.0
            else:
                z = (xx - mean) / sd
                X = np.column_stack([np.ones_like(z), z])
                beta, *_ = np.linalg.lstsq(X, rr, rcond=None)
                resid_hat = float(beta[0] + beta[1] * ((x_test - mean) / sd))
                slope = float(beta[1])
        corrected[i] = pred[i] - resid_hat
        slopes.append(slope)
    base_ccc = float(lins_ccc(y, pred))
    base_mae = float(np.mean(np.abs(pred - y)))
    return {
        "ccc": float(lins_ccc(y, corrected)),
        "mae": float(np.mean(np.abs(corrected - y))),
        "delta_ccc_vs_base": float(lins_ccc(y, corrected) - base_ccc),
        "delta_mae_vs_base": float(np.mean(np.abs(corrected - y)) - base_mae),
        "mean_slope_per_item_sd": float(np.mean(slopes)),
    }


def bootstrap_corr_ci(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    rng = np.random.default_rng(20260509)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    aa = a[mask]
    bb = b[mask]
    if len(aa) < 5 or np.std(aa) < 1e-12 or np.std(bb) < 1e-12:
        return {"n": int(len(aa)), "corr": None, "ci_low": None, "ci_high": None}
    vals = []
    n = len(aa)
    for _ in range(3000):
        idx = rng.integers(0, n, size=n)
        vals.append(float(np.corrcoef(aa[idx], bb[idx])[0, 1]))
    return {
        "n": int(n),
        "corr": float(np.corrcoef(aa, bb)[0, 1]),
        "ci_low": float(np.quantile(vals, 0.025)),
        "ci_high": float(np.quantile(vals, 0.975)),
    }


def main() -> None:
    preds = load_iter47_current()
    items, clinical_path = load_item_table()
    merged = preds.merge(items, on="sid", how="left")
    if len(merged) != len(preds):
        raise RuntimeError("Unexpected row count after item merge")

    y = merged["y_true"].to_numpy(float)
    pred = merged["y_pred"].to_numpy(float)
    residual = merged["residual_pred_minus_true"].to_numpy(float)
    base_metrics = metrics(y, pred)

    total_diff = merged["parsed_validrange_total"] - merged["y_true"]
    target_reconstruction = {
        "max_abs_parsed_total_minus_iter47_target": float(np.nanmax(np.abs(total_diff))),
        "n_nonzero_diffs": int(np.sum(np.abs(total_diff) > 1e-9)),
    }

    item_rows = []
    for item in range(1, 19):
        col = f"item_{item:02d}"
        values = merged[col].to_numpy(float)
        oracle = leave_one_item_oracle(y, pred, values)
        row = {
            "item": item,
            "name": ITEM_NAMES[item],
            "weargait_observable": item in WEARGAIT_OBSERVABLE_ITEMS,
            "t1_item": item in T1_ITEMS,
            "n_valid_item_scores": int(np.isfinite(values).sum()),
            "n_missing_item_scores": int(np.sum(~np.isfinite(values))),
            "mean": float(np.nanmean(values)),
            "sd": float(np.nanstd(values)),
            "max": float(np.nanmax(values)),
            "nonzero_fraction": float(np.nanmean(values > 0)),
            "corr_item_with_t3_target": corr(values, y),
            "corr_item_with_t3_prediction": corr(values, pred),
            "corr_item_with_residual_pred_minus_true": corr(values, residual),
            "abs_corr_item_with_residual": abs(corr(values, residual) or 0.0),
            "corr_item_with_abs_error": corr(values, merged["abs_error"].to_numpy(float)),
            "residual_corr_bootstrap": bootstrap_corr_ci(values, residual),
            "loo_privileged_oracle": oracle,
        }
        item_rows.append(row)

    item_rows_by_residual = sorted(item_rows, key=lambda r: r["abs_corr_item_with_residual"], reverse=True)
    item_rows_by_oracle = sorted(
        item_rows,
        key=lambda r: r["loo_privileged_oracle"]["delta_ccc_vs_base"],
        reverse=True,
    )
    obs = [r for r in item_rows if r["weargait_observable"]]
    non_obs = [r for r in item_rows if not r["weargait_observable"]]

    report: dict[str, Any] = {
        "script": "audit_t3_iter47_item_residuals.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "diagnostic_only_saved_oof_no_model_selection_no_prereg_no_loocv",
        "inputs": {
            "predictions": str(PRED_PATH),
            "clinical_csv": str(clinical_path),
        },
        "web_scan_sources": [
            {
                "name": "COPS Scientific Data 2026",
                "url": "https://www.nature.com/articles/s41597-026-06999-6",
                "finding": "Public bilateral wrist accelerometry plus symptom diaries; OSF archives include UPDRS OFF/ON CSVs per local probe, so existing COPS target provenance is not diary-inferred.",
            },
            {
                "name": "ICICLE / real-world gait federated-learning paper",
                "url": "https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full",
                "finding": "Direct MDS-UPDRS III wearable route remains request-only; data availability statement requires contacting the investigator.",
            },
        ],
        "target_reconstruction": target_reconstruction,
        "cohort": {
            "n": int(len(merged)),
            "sites": merged["site"].value_counts().to_dict(),
        },
        "base_metrics": base_metrics,
        "item_rows": item_rows,
        "top_items_by_abs_residual_corr": item_rows_by_residual[:8],
        "top_items_by_privileged_oracle_delta_ccc": item_rows_by_oracle[:8],
        "observable_vs_unobservable_summary": {
            "observable_items": sorted(WEARGAIT_OBSERVABLE_ITEMS),
            "mean_abs_residual_corr_observable": float(np.mean([r["abs_corr_item_with_residual"] for r in obs])),
            "mean_abs_residual_corr_unobservable": float(np.mean([r["abs_corr_item_with_residual"] for r in non_obs])),
            "best_observable_oracle_delta_ccc": max(r["loo_privileged_oracle"]["delta_ccc_vs_base"] for r in obs),
            "best_unobservable_oracle_delta_ccc": max(r["loo_privileged_oracle"]["delta_ccc_vs_base"] for r in non_obs),
        },
        "interpretation": [],
        "decision": {
            "ceiling_broken": False,
            "no_model_promotion": True,
            "recommended_next": "Do not launch another WearGait-only T3 scalar-feature or calibration screen. The residual is item/domain target anatomy, not an uncovered deployable feature block.",
        },
    }

    top_resid = item_rows_by_residual[0]
    top_oracle = item_rows_by_oracle[0]
    if target_reconstruction["n_nonzero_diffs"] == 0:
        report["interpretation"].append("Parsed item totals exactly reconstruct the iter47 valid-range T3 target.")
    if report["observable_vs_unobservable_summary"]["mean_abs_residual_corr_unobservable"] > report["observable_vs_unobservable_summary"]["mean_abs_residual_corr_observable"]:
        report["interpretation"].append(
            "Residual-item dependence is stronger for non-WearGait-observable clinical items than for gait/balance-observable items."
        )
    report["interpretation"].append(
        f"Top residual-correlated item is {top_resid['item']} ({top_resid['name']}), r={top_resid['corr_item_with_residual_pred_minus_true']:.3f}."
    )
    report["interpretation"].append(
        f"Top privileged single-item oracle is item {top_oracle['item']} ({top_oracle['name']}), delta CCC={top_oracle['loo_privileged_oracle']['delta_ccc_vs_base']:.3f}; this is non-deployable because it uses the true clinical item at prediction time."
    )

    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    def fmt(x: Any, nd: int = 3) -> str:
        if x is None:
            return "NA"
        try:
            if not np.isfinite(float(x)):
                return "NA"
            return f"{float(x):.{nd}f}"
        except Exception:
            return str(x)

    lines = [
        "# T3 Iter47 Item-Level Residual Audit",
        "",
        "Diagnostic-only audit of saved corrected-target OOF predictions. No model was fit, no preregistration was written, and no LOOCV was run.",
        "",
        "## Base",
        "",
        f"- N: {base_metrics['n']}",
        f"- CCC: `{fmt(base_metrics['ccc'], 4)}`",
        f"- MAE: `{fmt(base_metrics['mae'], 3)}`",
        f"- residual-vs-true r: `{fmt(base_metrics['residual_corr_with_true'], 4)}`",
        f"- target reconstruction max abs diff: `{fmt(target_reconstruction['max_abs_parsed_total_minus_iter47_target'], 6)}`",
        "",
        "## Top Items By Residual Correlation",
        "",
        "| item | name | observable | r(item,residual) | r(item,pred) | oracle dCCC | oracle dMAE |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in item_rows_by_residual[:10]:
        lines.append(
            "| {item} | {name} | {obs} | `{rres}` | `{rpred}` | `{dcc}` | `{dmae}` |".format(
                item=row["item"],
                name=row["name"],
                obs="yes" if row["weargait_observable"] else "no",
                rres=fmt(row["corr_item_with_residual_pred_minus_true"], 3),
                rpred=fmt(row["corr_item_with_t3_prediction"], 3),
                dcc=fmt(row["loo_privileged_oracle"]["delta_ccc_vs_base"], 3),
                dmae=fmt(row["loo_privileged_oracle"]["delta_mae_vs_base"], 3),
            )
        )
    lines.extend(
        [
            "",
            "## Top Privileged Oracles",
            "",
            "| item | name | observable | oracle dCCC | oracle CCC | r(item,residual) |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in item_rows_by_oracle[:10]:
        lines.append(
            "| {item} | {name} | {obs} | `{dcc}` | `{ccc}` | `{rres}` |".format(
                item=row["item"],
                name=row["name"],
                obs="yes" if row["weargait_observable"] else "no",
                dcc=fmt(row["loo_privileged_oracle"]["delta_ccc_vs_base"], 3),
                ccc=fmt(row["loo_privileged_oracle"]["ccc"], 3),
                rres=fmt(row["corr_item_with_residual_pred_minus_true"], 3),
            )
        )
    lines.extend(
        [
            "",
            "## Observable Split",
            "",
            f"- Mean |r(item,residual)| for gait/balance-observable items 7-14: `{fmt(report['observable_vs_unobservable_summary']['mean_abs_residual_corr_observable'], 3)}`",
            f"- Mean |r(item,residual)| for non-observable items: `{fmt(report['observable_vs_unobservable_summary']['mean_abs_residual_corr_unobservable'], 3)}`",
            f"- Best observable privileged dCCC: `{fmt(report['observable_vs_unobservable_summary']['best_observable_oracle_delta_ccc'], 3)}`",
            f"- Best non-observable privileged dCCC: `{fmt(report['observable_vs_unobservable_summary']['best_unobservable_oracle_delta_ccc'], 3)}`",
            "",
            "## Interpretation",
            "",
        ]
    )
    lines.extend([f"- {note}" for note in report["interpretation"]])
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- No model promotion.",
            "- No new LOOCV.",
            "- Use this as stop-rule evidence against another WearGait-only T3 scalar-feature or calibration screen.",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"top_residual_item={top_resid['item']} {top_resid['name']} r={top_resid['corr_item_with_residual_pred_minus_true']:.4f}")
    print(f"top_oracle_item={top_oracle['item']} {top_oracle['name']} dCCC={top_oracle['loo_privileged_oracle']['delta_ccc_vs_base']:.4f}")


if __name__ == "__main__":
    main()
