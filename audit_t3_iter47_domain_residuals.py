#!/usr/bin/env python3
"""Diagnostic domain decomposition of the current T3 iter47 residuals.

This audit uses saved OOF predictions plus ground-truth MDS-UPDRS Part III item
scores. The domain labels are clinical target information, so every oracle
correction here is privileged and non-deployable. The purpose is to locate which
clinical domains drive the corrected T3 residual, not to select a model.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from eval_utils import lins_ccc
from project_paths import RESULTS_DIR
from updrs_columns import find_updrs_value


ROOT = Path(__file__).resolve().parent
RESULTS = RESULTS_DIR
OUT_JSON = RESULTS / "t3_iter47_domain_residual_audit_20260509.json"
OUT_MD = RESULTS / "t3_iter47_domain_residual_audit_20260509.md"

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
    2: "facial",
    3: "rigidity",
    4: "finger_tap",
    5: "hand_movement",
    6: "pronation",
    7: "toe_tap",
    8: "leg_agility",
    9: "arising",
    10: "gait",
    11: "freezing",
    12: "postural_stability",
    13: "posture",
    14: "body_bradykinesia",
    15: "postural_tremor",
    16: "kinetic_tremor",
    17: "rest_tremor_amplitude",
    18: "rest_tremor_constancy",
}

DOMAINS = {
    "t1_items_9_14": [9, 10, 11, 12, 13, 14],
    "gait_balance_7_14": [7, 8, 9, 10, 11, 12, 13, 14],
    "pigdf_like_9_13": [9, 10, 11, 12, 13],
    "appendicular_brady_4_8_14": [4, 5, 6, 7, 8, 14],
    "upper_limb_brady_4_6": [4, 5, 6],
    "lower_limb_brady_7_8": [7, 8],
    "rigidity_3": [3],
    "tremor_15_18": [15, 16, 17, 18],
    "speech_face_1_2": [1, 2],
    "unobservable_non_gait": [1, 2, 3, 4, 5, 6, 15, 16, 17, 18],
}

DEPLOYABLE_PROXY_DOMAINS = {"t1_items_9_14", "gait_balance_7_14", "pigdf_like_9_13", "lower_limb_brady_7_8"}


def corr(a: np.ndarray, b: np.ndarray) -> float | None:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 3:
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
        "mean_residual_pred_minus_true": float(np.mean(err)),
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


def load_item_domain_table() -> tuple[pd.DataFrame, Path]:
    clinical, path = load_pd_clinical()
    rows = []
    for _, row in clinical.iterrows():
        sid = str(row["sid"])
        if not sid.startswith(("NLS", "WPD")):
            continue
        out: dict[str, Any] = {"sid": sid}
        total = 0.0
        valid_components = 0
        missing_components = 0
        for item in range(1, 19):
            value, valid_n, missing_n = score_item(row, clinical.columns, item)
            out[f"item_{item:02d}_{ITEM_NAMES[item]}"] = value
            out[f"item_{item:02d}_valid_components"] = valid_n
            out[f"item_{item:02d}_missing_components"] = missing_n
            if value is not None:
                total += float(value)
                valid_components += valid_n
            missing_components += missing_n
        out["parsed_validrange_total"] = total
        out["parsed_valid_components"] = valid_components
        out["parsed_missing_components"] = missing_components
        for domain, items in DOMAINS.items():
            domain_values = [
                out[f"item_{item:02d}_{ITEM_NAMES[item]}"]
                for item in items
                if out[f"item_{item:02d}_{ITEM_NAMES[item]}"] is not None
            ]
            # Match the iter47 valid-range total arithmetic: missing subitems
            # are excluded from the sum. Keep *_valid_items so fully missing
            # domain blocks remain visible in the audit instead of silently
            # becoming evidence of true zero severity.
            out[domain] = float(np.sum(domain_values)) if domain_values else 0.0
            out[f"{domain}_valid_items"] = len(domain_values)
        rows.append(out)
    return pd.DataFrame(rows), path


def load_iter47_current() -> pd.DataFrame:
    df = pd.read_csv(RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv")
    df = df[
        (df["cohort"] == "drop_allmissing_validrange")
        & (df["stage2_policy"] == "stage2_current")
    ].copy()
    df["site"] = np.where(df["sid"].astype(str).str.startswith("NLS"), "NLS", "WPD")
    df["residual_pred_minus_true"] = df["y_pred"] - df["y_true_validrange"]
    df["abs_error"] = np.abs(df["residual_pred_minus_true"])
    return df


def leave_one_domain_oracle(y: np.ndarray, pred: np.ndarray, domain: np.ndarray) -> dict[str, Any]:
    residual = pred - y
    corrected = np.full_like(pred, np.nan, dtype=float)
    coeffs = []
    for i in range(len(y)):
        mask = np.ones(len(y), dtype=bool)
        mask[i] = False
        x_train = domain[mask].astype(float)
        x_test = float(domain[i])
        y_train = residual[mask].astype(float)
        x_mean = float(np.mean(x_train))
        x_sd = float(np.std(x_train))
        if x_sd < 1e-12:
            resid_hat = float(np.mean(y_train))
            slope = 0.0
            intercept = resid_hat
        else:
            z_train = (x_train - x_mean) / x_sd
            z_test = (x_test - x_mean) / x_sd
            X = np.column_stack([np.ones_like(z_train), z_train])
            beta, *_ = np.linalg.lstsq(X, y_train, rcond=None)
            intercept = float(beta[0])
            slope = float(beta[1])
            resid_hat = float(intercept + slope * z_test)
        corrected[i] = pred[i] - resid_hat
        coeffs.append({"intercept": intercept, "slope_per_train_sd": slope})
    return {
        "metrics": metrics(y, corrected),
        "delta_ccc_vs_base": float(lins_ccc(y, corrected) - lins_ccc(y, pred)),
        "delta_mae_vs_base": float(np.mean(np.abs(corrected - y)) - np.mean(np.abs(pred - y))),
        "mean_slope_per_train_sd": float(np.mean([c["slope_per_train_sd"] for c in coeffs])),
    }


def leave_one_multidomain_ridge_oracle(y: np.ndarray, pred: np.ndarray, X: np.ndarray) -> dict[str, Any]:
    residual = pred - y
    corrected = np.full_like(pred, np.nan, dtype=float)
    for i in range(len(y)):
        mask = np.ones(len(y), dtype=bool)
        mask[i] = False
        X_train = X[mask].astype(float)
        X_test = X[[i]].astype(float)
        mean = X_train.mean(axis=0)
        sd = X_train.std(axis=0)
        sd[sd < 1e-12] = 1.0
        model = Ridge(alpha=10.0)
        model.fit((X_train - mean) / sd, residual[mask])
        resid_hat = float(model.predict((X_test - mean) / sd)[0])
        corrected[i] = pred[i] - resid_hat
    return {
        "alpha": 10.0,
        "features": list(DOMAINS),
        "metrics": metrics(y, corrected),
        "delta_ccc_vs_base": float(lins_ccc(y, corrected) - lins_ccc(y, pred)),
        "delta_mae_vs_base": float(np.mean(np.abs(corrected - y)) - np.mean(np.abs(pred - y))),
    }


def quartile_rows(df: pd.DataFrame, domain: str) -> list[dict[str, Any]]:
    q = pd.qcut(df[domain].rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
    rows = []
    for label in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[q == label]
        rows.append(
            {
                "quartile": label,
                "n": int(len(sub)),
                "domain_min": float(sub[domain].min()),
                "domain_max": float(sub[domain].max()),
                "mean_true_t3": float(sub["y_true_validrange"].mean()),
                "mean_pred_t3": float(sub["y_pred"].mean()),
                "mean_residual_pred_minus_true": float(sub["residual_pred_minus_true"].mean()),
                "mean_abs_error": float(sub["abs_error"].mean()),
            }
        )
    return rows


def top_subject_rows(df: pd.DataFrame, domain: str, n: int = 8) -> list[dict[str, Any]]:
    cols = [
        "sid",
        "site",
        "y_true_validrange",
        "y_pred",
        "residual_pred_minus_true",
        "abs_error",
        domain,
    ]
    return (
        df.sort_values(["abs_error", domain], ascending=[False, False])[cols]
        .head(n)
        .to_dict(orient="records")
    )


def fmt(x: Any, digits: int = 4) -> str:
    if x is None:
        return "NA"
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return str(x)


def main() -> None:
    pred_df = load_iter47_current()
    item_df, clinical_path = load_item_domain_table()
    df = pred_df.merge(item_df, on="sid", how="left", validate="one_to_one")
    if df[list(DOMAINS)].isna().any().any():
        missing = df.loc[df[list(DOMAINS)].isna().any(axis=1), "sid"].tolist()
        raise RuntimeError(f"Missing parsed domain scores for current cohort: {missing}")

    total_diff = df["parsed_validrange_total"] - df["y_true_validrange"]
    max_total_abs_diff = float(np.max(np.abs(total_diff.to_numpy(float))))
    y = df["y_true_validrange"].to_numpy(float)
    pred = df["y_pred"].to_numpy(float)
    base = metrics(y, pred)

    domain_rows = []
    oracle_rows: dict[str, Any] = {}
    for domain, items in DOMAINS.items():
        values = df[domain].to_numpy(float)
        oracle = leave_one_domain_oracle(y, pred, values)
        oracle_rows[domain] = oracle
        domain_rows.append(
            {
                "domain": domain,
                "items": items,
                "deployable_proxy_candidate": domain in DEPLOYABLE_PROXY_DOMAINS,
                "mean": float(np.mean(values)),
                "sd": float(np.std(values)),
                "max": float(np.max(values)),
                "corr_domain_with_true_t3": corr(values, y),
                "corr_domain_with_pred_t3": corr(values, pred),
                "corr_domain_with_residual_pred_minus_true": corr(
                    values, df["residual_pred_minus_true"].to_numpy(float)
                ),
                "corr_domain_with_abs_error": corr(values, df["abs_error"].to_numpy(float)),
                "leave_one_privileged_oracle_ccc": oracle["metrics"]["ccc"],
                "leave_one_privileged_oracle_mae": oracle["metrics"]["mae"],
                "oracle_delta_ccc_vs_base": oracle["delta_ccc_vs_base"],
                "oracle_delta_mae_vs_base": oracle["delta_mae_vs_base"],
                "oracle_mean_slope_per_domain_sd": oracle["mean_slope_per_train_sd"],
            }
        )
    domain_summary = sorted(
        domain_rows,
        key=lambda r: abs(float(r["corr_domain_with_residual_pred_minus_true"] or 0.0)),
        reverse=True,
    )
    X = df[list(DOMAINS)].to_numpy(float)
    multi_oracle = leave_one_multidomain_ridge_oracle(y, pred, X)

    best_oracle = max(domain_rows, key=lambda r: float(r["oracle_delta_ccc_vs_base"]))
    best_deployable_proxy = max(
        [r for r in domain_rows if r["deployable_proxy_candidate"]],
        key=lambda r: float(r["oracle_delta_ccc_vs_base"]),
    )
    redlines = {
        "observable_domain_abs_residual_corr_threshold": 0.50,
        "observable_domain_oracle_delta_ccc_threshold": 0.05,
        "observable_domain_route_flag": bool(
            abs(float(best_deployable_proxy["corr_domain_with_residual_pred_minus_true"] or 0.0)) >= 0.50
            and float(best_deployable_proxy["oracle_delta_ccc_vs_base"]) >= 0.05
        ),
        "best_overall_domain": best_oracle["domain"],
        "best_deployable_proxy_domain": best_deployable_proxy["domain"],
    }
    decision = {
        "scope": "diagnostic_only_privileged_ground_truth_domains",
        "no_model_promotion": True,
        "no_new_loocv": True,
        "no_subject_filtering": True,
        "redlines": redlines,
        "summary": (
            f"Current iter47 T3 residuals are most associated with "
            f"{domain_summary[0]['domain']} (r={domain_summary[0]['corr_domain_with_residual_pred_minus_true']:.4f}). "
            f"The best single-domain privileged oracle is {best_oracle['domain']} "
            f"(delta CCC {best_oracle['oracle_delta_ccc_vs_base']:+.4f}); the best gait-observable proxy is "
            f"{best_deployable_proxy['domain']} (delta CCC {best_deployable_proxy['oracle_delta_ccc_vs_base']:+.4f}). "
            "Because these corrections use true clinical domain labels, they are explanation only."
        ),
    }

    report = {
        "script": "audit_t3_iter47_domain_residuals.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "clinical_path": str(clinical_path.relative_to(ROOT) if clinical_path.is_relative_to(ROOT) else clinical_path),
            "predictions": "results/iter47_invalidcode_subject_preds_20260508_194605.csv",
            "cohort": "drop_allmissing_validrange",
            "stage2_policy": "stage2_current",
        },
        "guardrails": {
            "clinical_domain_labels_are_ground_truth": True,
            "oracle_corrections_are_privileged_and_non_deployable": True,
            "domain_scores_validrange_subitems_only": True,
            "parsed_total_max_abs_diff_vs_iter47_target": max_total_abs_diff,
        },
        "baseline_metrics": base,
        "domain_definitions": DOMAINS,
        "domain_summary": domain_summary,
        "domain_oracles": oracle_rows,
        "multidomain_ridge10_privileged_oracle": multi_oracle,
        "quartiles": {
            domain_summary[0]["domain"]: quartile_rows(df, domain_summary[0]["domain"]),
            best_deployable_proxy["domain"]: quartile_rows(df, best_deployable_proxy["domain"]),
        },
        "top_error_subjects_with_domains": {
            domain_summary[0]["domain"]: top_subject_rows(df, domain_summary[0]["domain"]),
            best_deployable_proxy["domain"]: top_subject_rows(df, best_deployable_proxy["domain"]),
        },
        "decision": decision,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# T3 Iter47 Domain Residual Audit",
        "",
        f"- Created: `{report['created_at_utc']}`",
        "- Scope: diagnostic only; uses true clinical domain labels; no model promotion, no filtering, no LOOCV rerun.",
        f"- Parsed valid-range total max absolute difference vs iter47 target: `{max_total_abs_diff:.6f}`",
        "",
        "## Baseline",
        "",
        f"- Current iter47 CCC: `{base['ccc']:.4f}`",
        f"- Current iter47 MAE: `{base['mae']:.4f}`",
        f"- N: `{base['n']}`",
        "",
        "## Domain Residual Associations",
        "",
        "| Domain | Items | residual r | true r | pred r | abs-error r | oracle CCC | dCCC | dMAE | deployable proxy |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in domain_summary:
        lines.append(
            f"| `{row['domain']}` | {','.join(map(str, row['items']))} | "
            f"{fmt(row['corr_domain_with_residual_pred_minus_true'])} | "
            f"{fmt(row['corr_domain_with_true_t3'])} | "
            f"{fmt(row['corr_domain_with_pred_t3'])} | "
            f"{fmt(row['corr_domain_with_abs_error'])} | "
            f"{fmt(row['leave_one_privileged_oracle_ccc'])} | "
            f"{fmt(row['oracle_delta_ccc_vs_base'])} | "
            f"{fmt(row['oracle_delta_mae_vs_base'])} | "
            f"{'yes' if row['deployable_proxy_candidate'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Privileged Multidomain Oracle",
            "",
            f"- Ridge alpha: `{multi_oracle['alpha']}`",
            f"- CCC: `{multi_oracle['metrics']['ccc']:.4f}`",
            f"- MAE: `{multi_oracle['metrics']['mae']:.4f}`",
            f"- Delta CCC vs current: `{multi_oracle['delta_ccc_vs_base']:+.4f}`",
            f"- Delta MAE vs current: `{multi_oracle['delta_mae_vs_base']:+.4f}`",
            "",
            "## Decision",
            "",
            decision["summary"],
            "",
            "These oracle corrections are non-deployable because they require true Part III domain labels at test time. Use this only to explain residual anatomy and to decide whether a future target representation needs external data.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": "written", "decision": decision}, indent=2))
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
