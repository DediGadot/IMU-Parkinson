#!/usr/bin/env python3
"""Diagnostic CCC rescaling sanity check for corrected iter47 T3 predictions.

This script does not create a reportable model. It intentionally works from the
saved iter47 OOF vector to quantify a tempting failure mode: range-expanding
predictions can improve CCC accounting while worsening MAE. Because the saved
OOF vector is reused for second-level calibration, these transforms are not a
fully nested meta-model and must not be promoted as a lockbox result.
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
OUT_JSON = RESULTS / "t3_iter47_ccc_rescale_sanity_20260509.json"
OUT_MD = RESULTS / "t3_iter47_ccc_rescale_sanity_20260509.md"


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
    }


def leave_one_affine(y: np.ndarray, pred: np.ndarray) -> np.ndarray:
    out = np.empty_like(pred, dtype=float)
    for i in range(len(y)):
        mask = np.ones(len(y), dtype=bool)
        mask[i] = False
        x = np.c_[np.ones(mask.sum()), pred[mask]]
        a, b = np.linalg.lstsq(x, y[mask], rcond=None)[0]
        out[i] = a + b * pred[i]
    return out


def leave_one_variance_match(y: np.ndarray, pred: np.ndarray) -> np.ndarray:
    out = np.empty_like(pred, dtype=float)
    for i in range(len(y)):
        mask = np.ones(len(y), dtype=bool)
        mask[i] = False
        pred_sd = float(np.std(pred[mask]))
        scale = float(np.std(y[mask]) / pred_sd) if pred_sd > 1e-12 else 1.0
        out[i] = float(np.mean(y[mask]) + (pred[i] - np.mean(pred[mask])) * scale)
    return out


def paired_bootstrap_delta(
    y: np.ndarray,
    base: np.ndarray,
    candidate: np.ndarray,
    *,
    n_boot: int = 10000,
    seed: int = 42,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n = len(y)
    ccc_delta = np.empty(n_boot, dtype=float)
    mae_delta = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        ccc_delta[b] = lins_ccc(y[idx], candidate[idx]) - lins_ccc(y[idx], base[idx])
        mae_delta[b] = np.mean(np.abs(candidate[idx] - y[idx])) - np.mean(np.abs(base[idx] - y[idx]))
    return {
        "n_boot": n_boot,
        "seed": seed,
        "ccc_delta_mean": float(np.mean(ccc_delta)),
        "ccc_delta_ci95": [float(np.percentile(ccc_delta, 2.5)), float(np.percentile(ccc_delta, 97.5))],
        "ccc_delta_frac_above_zero": float(np.mean(ccc_delta > 0)),
        "mae_delta_mean": float(np.mean(mae_delta)),
        "mae_delta_ci95": [float(np.percentile(mae_delta, 2.5)), float(np.percentile(mae_delta, 97.5))],
        "mae_delta_frac_below_zero": float(np.mean(mae_delta < 0)),
    }


def quartile_summary(y: np.ndarray, pred: np.ndarray) -> list[dict[str, Any]]:
    labels = pd.qcut(y, q=4, labels=["Q1_low", "Q2", "Q3", "Q4_high"])
    df = pd.DataFrame({"y": y, "pred": pred, "q": labels})
    df["err"] = df["pred"] - df["y"]
    rows = []
    for q, sub in df.groupby("q", observed=False):
        rows.append(
            {
                "group": str(q),
                "n": int(len(sub)),
                "mean_y": float(sub["y"].mean()),
                "mean_pred": float(sub["pred"].mean()),
                "mean_residual_pred_minus_true": float(sub["err"].mean()),
                "mae": float(np.mean(np.abs(sub["err"]))),
            }
        )
    return rows


def main() -> None:
    preds = pd.read_csv(PRED_PATH)
    preds = preds[
        (preds["cohort"] == "drop_allmissing_validrange")
        & (preds["stage2_policy"] == "stage2_current")
    ].copy()
    y = preds["y_true_validrange"].to_numpy(float)
    base = preds["y_pred"].to_numpy(float)

    candidates = {
        "base_iter47_current": base,
        "oof_level_leave_one_affine_y_on_pred": leave_one_affine(y, base),
        "oof_level_leave_one_variance_match": leave_one_variance_match(y, base),
    }
    methods = {}
    for name, values in candidates.items():
        row = {
            "metrics": metrics(y, values),
            "severity_quartiles": quartile_summary(y, values),
        }
        if name != "base_iter47_current":
            row["paired_bootstrap_vs_base"] = paired_bootstrap_delta(y, base, values)
        methods[name] = row

    vm = methods["oof_level_leave_one_variance_match"]["metrics"]
    base_m = methods["base_iter47_current"]["metrics"]
    report = {
        "script": "audit_t3_iter47_ccc_rescale_sanity.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "diagnostic_only_not_reportable_model",
        "input_predictions": str(PRED_PATH),
        "cohort": {
            "name": "drop_allmissing_validrange",
            "stage2_policy": "stage2_current",
            "n": int(len(y)),
        },
        "methods": methods,
        "methodology_guardrail": {
            "not_fully_nested": True,
            "reason": (
                "Second-level transforms are fit on the saved OOF vector. For a held-out subject i, "
                "the calibration set includes predictions for other subjects generated by base models "
                "whose training folds included subject i. This is acceptable as a diagnostic but not "
                "as a reportable nested meta-model."
            ),
            "future_reportable_requirement": (
                "A reportable rescaling/meta-calibration would need outer-fold base predictions and "
                "inner-OOF calibration predictions generated without the outer test subject."
            ),
        },
        "decision": {
            "no_model_promotion": True,
            "no_new_loocv": True,
            "reason": (
                "The best diagnostic CCC lift is small and non-reportable; variance matching raises "
                f"CCC by {vm['ccc'] - base_m['ccc']:+.4f} but worsens MAE by {vm['mae'] - base_m['mae']:+.4f}."
            ),
        },
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# T3 Iter47 CCC Rescale Sanity",
        "",
        f"- Created: `{report['created_at_utc']}`",
        "- Scope: diagnostic only; not a reportable model.",
        "- Cohort: `drop_allmissing_validrange` / `stage2_current` / N=95",
        "",
        "## Methods",
        "",
    ]
    for name, row in methods.items():
        m = row["metrics"]
        lines.append(
            f"- `{name}`: CCC `{m['ccc']:.4f}`, MAE `{m['mae']:.4f}`, "
            f"r `{m['r']:.4f}`, pred SD `{m['prediction_sd']:.4f}`, "
            f"residual corr `{m['residual_corr_with_true']:.4f}`"
        )
        if name != "base_iter47_current":
            b = row["paired_bootstrap_vs_base"]
            lines.append(
                f"  - Delta vs base: CCC mean `{b['ccc_delta_mean']:+.4f}` "
                f"CI `[{b['ccc_delta_ci95'][0]:+.4f},{b['ccc_delta_ci95'][1]:+.4f}]`, "
                f"MAE mean `{b['mae_delta_mean']:+.4f}` "
                f"CI `[{b['mae_delta_ci95'][0]:+.4f},{b['mae_delta_ci95'][1]:+.4f}]`"
            )
    lines.extend(
        [
            "",
            "## Guardrail",
            "",
            report["methodology_guardrail"]["reason"],
            "",
            "A reportable version would need a fully nested outer/inner prediction artifact. "
            "Given that even this optimistic diagnostic lift is small and worsens MAE, this is not a productive lockbox route.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": "written", "best_ccc": vm["ccc"], "base_ccc": base_m["ccc"]}, indent=2))
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
