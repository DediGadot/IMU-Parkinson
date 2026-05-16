#!/usr/bin/env python3
"""Diagnostic residual anatomy for the corrected iter47 T3 artifact.

This is not a model-selection script. It reads saved subject-level OOF
predictions from the valid-range-corrected T3 audit and summarizes where the
current error lives. Any residual-feature correlations are global post-hoc
diagnostics only; they are not a gate, preregistration, or feature proposal.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eval_utils import cal_slope, lins_ccc


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PRED_PATH = RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv"
FEATURE_PATH = RESULTS / "ablation_v3_features.csv"
TARGET_AUDIT_PATH = RESULTS / "t3_iter47_target_integrity_audit_20260508.json"
OUT_JSON = RESULTS / "t3_iter47_residual_anatomy_20260509.json"
OUT_MD = RESULTS / "t3_iter47_residual_anatomy_20260509.md"


def corr(a: np.ndarray, b: np.ndarray) -> float | None:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 5:
        return None
    aa = a[mask]
    bb = b[mask]
    if np.std(aa) < 1e-12 or np.std(bb) < 1e-12:
        return None
    return float(np.corrcoef(aa, bb)[0, 1])


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    err = pred - y
    return {
        "n": int(len(y)),
        "ccc": float(lins_ccc(y, pred)),
        "mae": float(np.mean(np.abs(err))),
        "r": corr(y, pred),
        "cal_slope_pred_on_true": float(cal_slope(y, pred)),
        "mean_error_pred_minus_true": float(np.mean(err)),
        "prediction_sd": float(np.std(pred)),
        "target_sd": float(np.std(y)),
        "residual_corr_with_true": corr(err, y),
        "residual_corr_with_pred": corr(err, pred),
    }


def group_summary(df: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    rows = []
    for value, sub in df.groupby(group_col, dropna=False):
        y = sub["y_true"].to_numpy(float)
        pred = sub["y_pred"].to_numpy(float)
        err = sub["residual_pred_minus_true"].to_numpy(float)
        rows.append(
            {
                "group": str(value),
                "n": int(len(sub)),
                "mean_y": float(np.mean(y)),
                "mean_pred": float(np.mean(pred)),
                "mean_residual_pred_minus_true": float(np.mean(err)),
                "mae": float(np.mean(np.abs(err))),
                "ccc": float(lins_ccc(y, pred)) if len(sub) >= 3 else None,
                "r": corr(y, pred),
            }
        )
    return rows


def numeric_joined_features(features: pd.DataFrame, sids: list[str]) -> pd.DataFrame:
    selected = features.set_index("sid", drop=True).loc[sids].reset_index(drop=True)
    feat = pd.concat([pd.Series(sids, name="sid"), selected], axis=1).copy()
    drop_exact = {"sid", "updrs3", "hy", "obs_subscore"}
    keep = []
    for col in feat.columns:
        if col in drop_exact:
            continue
        if col.startswith("cv_") or col.startswith("dst_"):
            continue
        if pd.api.types.is_numeric_dtype(feat[col]):
            keep.append(col)
    return feat[["sid"] + keep]


def top_feature_correlations(df: pd.DataFrame, feat: pd.DataFrame) -> list[dict[str, Any]]:
    merged = df[["sid", "y_true", "y_pred", "residual_pred_minus_true"]].merge(feat, on="sid")
    rows = []
    for col in feat.columns:
        if col == "sid":
            continue
        values = pd.to_numeric(merged[col], errors="coerce").to_numpy(float)
        c_resid = corr(values, merged["residual_pred_minus_true"].to_numpy(float))
        c_target = corr(values, merged["y_true"].to_numpy(float))
        c_pred = corr(values, merged["y_pred"].to_numpy(float))
        if c_resid is None:
            continue
        rows.append(
            {
                "feature": col,
                "corr_with_residual": c_resid,
                "abs_corr_with_residual": abs(c_resid),
                "corr_with_target": c_target,
                "corr_with_prediction": c_pred,
                "nonmissing": int(np.isfinite(values).sum()),
            }
        )
    rows.sort(key=lambda r: r["abs_corr_with_residual"], reverse=True)
    return rows[:25]


def derive_interpretation(report: dict[str, Any]) -> list[str]:
    notes = []
    m = report["overall_metrics"]
    if (m.get("residual_corr_with_true") or 0) < -0.5:
        notes.append(
            "Tail shrinkage remains the dominant corrected-target failure mode: residuals are strongly negative-correlated with true severity."
        )
    if m.get("prediction_sd", 0) < 0.5 * m.get("target_sd", 1):
        notes.append(
            "Predictions are range-compressed: prediction SD is less than half the target SD."
        )
    site_rows = {row["group"]: row for row in report["site_summary"]}
    if {"NLS", "WPD"}.issubset(site_rows):
        gap = abs(site_rows["NLS"]["mean_residual_pred_minus_true"] - site_rows["WPD"]["mean_residual_pred_minus_true"])
        if gap > 2.0:
            notes.append(
                "Site residual means differ by more than 2 UPDRS-III points, so corrected-target internal validity still carries cohort-shift risk."
            )
        if min(site_rows["NLS"]["ccc"], site_rows["WPD"]["ccc"]) < 0.10:
            notes.append(
                "WPD rank ordering is still near-collapsed under the corrected target, matching the broader LOSO transportability warning."
            )
    top_abs = report["global_diagnostic_feature_correlations"][0]["abs_corr_with_residual"] if report["global_diagnostic_feature_correlations"] else 0
    if top_abs < 0.35:
        notes.append(
            "No single post-hoc IMU feature has a large residual correlation; this supports the current stop rule against another scalar feature-fishing pass."
        )
    else:
        notes.append(
            "Some single features have moderate global residual correlations, but this is post-hoc and not fold-local; use only to formulate a future preregistered target-representation hypothesis."
        )
    return notes


def main() -> None:
    preds = pd.read_csv(PRED_PATH)
    preds = preds[
        (preds["cohort"] == "drop_allmissing_validrange")
        & (preds["stage2_policy"] == "stage2_current")
    ].copy()
    preds = preds.rename(columns={"y_true_validrange": "y_true"})
    preds["sid"] = preds["sid"].astype(str)
    preds["site"] = preds["sid"].str.extract(r"^([A-Z]+)", expand=False)
    preds["residual_pred_minus_true"] = preds["y_pred"] - preds["y_true"]
    preds["abs_error"] = preds["residual_pred_minus_true"].abs()
    preds["severity_quartile"] = pd.qcut(
        preds["y_true"], q=4, labels=["Q1_low", "Q2", "Q3", "Q4_high"]
    )

    features = pd.read_csv(FEATURE_PATH)
    v2 = features.set_index("sid")
    for col in ["hy", "cv_yrs", "cv_sex", "cv_dbs", "cv_age", "obs_subscore"]:
        if col in v2.columns:
            preds[col] = [v2.loc[sid, col] if sid in v2.index else np.nan for sid in preds["sid"]]

    clinical_cols = [
        "hy",
        "cv_yrs",
        "cv_sex",
        "cv_dbs",
        "cv_age",
        "obs_subscore",
        "raw_part3_missing_validrange",
        "target_delta_original_minus_validrange",
    ]
    clinical_corrs = []
    for col in clinical_cols:
        if col in preds.columns:
            clinical_corrs.append(
                {
                    "variable": col,
                    "corr_with_residual": corr(preds[col].to_numpy(float), preds["residual_pred_minus_true"].to_numpy(float)),
                    "corr_with_target": corr(preds[col].to_numpy(float), preds["y_true"].to_numpy(float)),
                    "corr_with_prediction": corr(preds[col].to_numpy(float), preds["y_pred"].to_numpy(float)),
                }
            )

    target_audit = json.loads(TARGET_AUDIT_PATH.read_text())
    numeric_features = numeric_joined_features(features, preds["sid"].tolist())
    top_corrs = top_feature_correlations(preds, numeric_features)

    high_error = preds.sort_values("abs_error", ascending=False).head(15)
    report: dict[str, Any] = {
        "script": "audit_t3_iter47_residual_anatomy.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "diagnostic_only_no_model_selection",
        "inputs": {
            "predictions": str(PRED_PATH),
            "features": str(FEATURE_PATH),
            "target_integrity_audit": str(TARGET_AUDIT_PATH),
        },
        "cohort": {
            "name": "drop_allmissing_validrange",
            "stage2_policy": "stage2_current",
            "n": int(len(preds)),
            "sites": preds["site"].value_counts().to_dict(),
            "target_changed_sids": [row["sid"] for row in target_audit.get("target", {}).get("target_changed_rows", [])],
        },
        "overall_metrics": metrics(preds["y_true"].to_numpy(float), preds["y_pred"].to_numpy(float)),
        "severity_quartile_summary": group_summary(preds, "severity_quartile"),
        "site_summary": group_summary(preds, "site"),
        "site_by_quartile_mean_residual": (
            preds.pivot_table(
                index="site",
                columns="severity_quartile",
                values="residual_pred_minus_true",
                aggfunc="mean",
                observed=False,
            )
            .round(4)
            .to_dict()
        ),
        "clinical_covariate_correlations": clinical_corrs,
        "global_diagnostic_feature_correlations": top_corrs,
        "high_error_subjects": [
            {
                "sid": str(row.sid),
                "site": str(row.site),
                "y_true": float(row.y_true),
                "y_pred": float(row.y_pred),
                "residual_pred_minus_true": float(row.residual_pred_minus_true),
                "abs_error": float(row.abs_error),
                "severity_quartile": str(row.severity_quartile),
                "raw_part3_missing_validrange": int(row.raw_part3_missing_validrange),
                "target_delta_original_minus_validrange": float(row.target_delta_original_minus_validrange),
            }
            for row in high_error.itertuples(index=False)
        ],
        "interpretation": [],
        "decision": {
            "no_model_promotion": True,
            "no_new_loocv": True,
            "recommended_next": "Do not launch another WearGait-only scalar feature addition. Use this audit to justify either data access/restoration or a fresh preregistered target-representation hypothesis.",
        },
    }
    report["interpretation"] = derive_interpretation(report)

    RESULTS.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")

    top_features = report["global_diagnostic_feature_correlations"][:8]
    lines = [
        "# T3 Iter47 Residual Anatomy",
        "",
        f"- Created: `{report['created_at_utc']}`",
        "- Scope: diagnostic only; no model selection or promotion.",
        f"- Cohort: `{report['cohort']['name']}` / `{report['cohort']['stage2_policy']}` / N={report['cohort']['n']}",
        "",
        "## Overall",
        "",
        f"- CCC: `{report['overall_metrics']['ccc']:.4f}`",
        f"- MAE: `{report['overall_metrics']['mae']:.4f}`",
        f"- Calibration slope pred-on-true: `{report['overall_metrics']['cal_slope_pred_on_true']:.4f}`",
        f"- Residual correlation with true severity: `{report['overall_metrics']['residual_corr_with_true']:.4f}`",
        f"- Prediction SD / target SD: `{report['overall_metrics']['prediction_sd']:.4f}` / `{report['overall_metrics']['target_sd']:.4f}`",
        "",
        "## Interpretation",
        "",
    ]
    lines.extend(f"- {note}" for note in report["interpretation"])
    lines.extend(["", "## Severity Quartiles", ""])
    for row in report["severity_quartile_summary"]:
        lines.append(
            f"- `{row['group']}`: n={row['n']}, mean_y={row['mean_y']:.2f}, "
            f"mean_pred={row['mean_pred']:.2f}, mean_residual={row['mean_residual_pred_minus_true']:.2f}, "
            f"MAE={row['mae']:.2f}"
        )
    lines.extend(["", "## Site Summary", ""])
    for row in report["site_summary"]:
        lines.append(
            f"- `{row['group']}`: n={row['n']}, mean_y={row['mean_y']:.2f}, "
            f"mean_pred={row['mean_pred']:.2f}, mean_residual={row['mean_residual_pred_minus_true']:.2f}, "
            f"CCC={row['ccc']:.4f}"
        )
    lines.extend(["", "## Top Global Residual-Feature Correlations", ""])
    for row in top_features:
        lines.append(
            f"- `{row['feature']}`: corr(residual)={row['corr_with_residual']:.3f}, "
            f"corr(target)={row['corr_with_target']:.3f}, corr(prediction)={row['corr_with_prediction']:.3f}"
        )
    lines.extend(["", "## Guardrail", ""])
    lines.append(
        "These feature correlations are global post-hoc diagnostics from saved OOF residuals. "
        "They are not fold-local feature selection and must not be used as a headline or lockbox gate."
    )
    lines.extend(["", f"Machine-readable report: `results/{OUT_JSON.name}`", ""])
    OUT_MD.write_text("\n".join(lines))
    print(json.dumps({"status": "written", "n": report["cohort"]["n"], "ccc": report["overall_metrics"]["ccc"]}, indent=2))
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
