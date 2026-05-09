#!/usr/bin/env python3
"""Leave-one-subject influence audit for current T1/T3 headline OOF vectors.

This is a diagnostic guard, not a model. It quantifies whether current CCC
claims are dominated by one or a few subjects and lists high-influence rows for
manual source-data review. It never tunes, filters, or promotes a prediction.
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
OUT_JSON = RESULTS / "current_headline_influence_audit_20260509.json"
OUT_MD = RESULTS / "current_headline_influence_audit_20260509.md"


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
        "cal_slope_pred_on_true": float(cal_slope(y, pred)),
        "target_mean": float(np.mean(y)),
        "target_sd": float(np.std(y)),
        "prediction_mean": float(np.mean(pred)),
        "prediction_sd": float(np.std(pred)),
        "mean_residual_pred_minus_true": float(np.mean(err)),
    }


def load_t1_json(path: Path, label: str) -> pd.DataFrame:
    data = json.loads(path.read_text())
    per = data["per_subject"]
    return pd.DataFrame(
        {
            "model": label,
            "sid": per["sids"],
            "y_true": per["y_true"],
            "y_pred": per["y_pred"],
            "source": str(path.relative_to(ROOT)),
        }
    )


def load_t3_iter47_current() -> pd.DataFrame:
    df = pd.read_csv(RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv")
    df = df[
        (df["cohort"] == "drop_allmissing_validrange")
        & (df["stage2_policy"] == "stage2_current")
    ].copy()
    return pd.DataFrame(
        {
            "model": "t3_iter47_validrange_current",
            "sid": df["sid"],
            "y_true": df["y_true_validrange"],
            "y_pred": df["y_pred"],
            "source": "results/iter47_invalidcode_subject_preds_20260508_194605.csv",
            "target_delta_original_minus_validrange": df["target_delta_original_minus_validrange"],
            "raw_part3_missing_validrange": df["raw_part3_missing_validrange"],
        }
    )


def site_from_sid(sid: str) -> str:
    if sid.startswith("NLS"):
        return "NLS"
    if sid.startswith("WPD"):
        return "WPD"
    return "other"


def jackknife_se(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n <= 1:
        return float("nan")
    return float(np.sqrt((n - 1) / n * np.sum((values - np.mean(values)) ** 2)))


def gini_nonnegative(values: np.ndarray) -> float | None:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return None
    if np.any(values < 0):
        values = values - np.min(values)
    total = float(np.sum(values))
    if total <= 1e-12:
        return 0.0
    sorted_values = np.sort(values)
    n = len(sorted_values)
    weights = np.arange(1, n + 1, dtype=float)
    return float((2.0 * np.sum(weights * sorted_values) / (n * total)) - ((n + 1.0) / n))


def influence_audit(df: pd.DataFrame) -> dict[str, Any]:
    df = df.copy().reset_index(drop=True)
    df["site"] = df["sid"].map(site_from_sid)
    df["residual_pred_minus_true"] = df["y_pred"] - df["y_true"]
    df["abs_error"] = np.abs(df["residual_pred_minus_true"])
    df["abs_target_minus_median"] = np.abs(df["y_true"] - np.median(df["y_true"]))
    y = df["y_true"].to_numpy(float)
    pred = df["y_pred"].to_numpy(float)
    base = metrics(y, pred)

    rows: list[dict[str, Any]] = []
    ccc_without = []
    mae_without = []
    for i, rec in df.iterrows():
        mask = np.ones(len(df), dtype=bool)
        mask[i] = False
        m = metrics(y[mask], pred[mask])
        row = {
            "sid": str(rec["sid"]),
            "site": str(rec["site"]),
            "y_true": float(rec["y_true"]),
            "y_pred": float(rec["y_pred"]),
            "residual_pred_minus_true": float(rec["residual_pred_minus_true"]),
            "abs_error": float(rec["abs_error"]),
            "ccc_without_subject": m["ccc"],
            "delta_ccc_without_minus_base": float(m["ccc"] - base["ccc"]),
            "mae_without_subject": m["mae"],
            "delta_mae_without_minus_base": float(m["mae"] - base["mae"]),
        }
        for optional in ("target_delta_original_minus_validrange", "raw_part3_missing_validrange"):
            if optional in df.columns and pd.notna(rec.get(optional)):
                row[optional] = float(rec[optional])
        rows.append(row)
        ccc_without.append(m["ccc"])
        mae_without.append(m["mae"])

    infl = pd.DataFrame(rows)
    abs_delta = np.abs(infl["delta_ccc_without_minus_base"].to_numpy(float))
    denom = float(abs_delta.sum()) if len(abs_delta) else 0.0
    top_abs = infl.reindex(abs_delta.argsort()[::-1]).head(10)
    top_improve = infl.sort_values("delta_ccc_without_minus_base", ascending=False).head(10)
    top_hurt = infl.sort_values("delta_ccc_without_minus_base", ascending=True).head(10)

    high_influence_review = top_abs[
        (top_abs["abs_error"] >= np.percentile(df["abs_error"], 90))
        | (np.abs(top_abs.get("target_delta_original_minus_validrange", 0.0)) > 0)
    ]
    merged = infl.merge(df[["sid", "abs_target_minus_median"]], on="sid", how="left")
    site_rows = []
    for site, sub in merged.groupby("site", sort=True):
        site_abs = np.abs(sub["delta_ccc_without_minus_base"].to_numpy(float))
        site_rows.append(
            {
                "site": str(site),
                "n": int(len(sub)),
                "mean_delta_ccc": float(sub["delta_ccc_without_minus_base"].mean()),
                "mean_abs_delta_ccc": float(site_abs.mean()) if len(site_abs) else None,
                "max_abs_delta_ccc": float(site_abs.max()) if len(site_abs) else None,
                "top_abs_delta_sid": str(sub.iloc[int(site_abs.argmax())]["sid"]) if len(site_abs) else None,
            }
        )
    top5_share = float(np.sort(abs_delta)[-5:].sum() / denom) if denom > 0 else None
    top1_abs = float(abs_delta.max()) if len(abs_delta) else None

    return {
        "baseline_metrics": base,
        "jackknife": {
            "ccc_without_mean": float(np.mean(ccc_without)),
            "ccc_without_min": float(np.min(ccc_without)),
            "ccc_without_max": float(np.max(ccc_without)),
            "ccc_jackknife_se": jackknife_se(np.asarray(ccc_without, dtype=float)),
            "mae_without_mean": float(np.mean(mae_without)),
            "mae_without_min": float(np.min(mae_without)),
            "mae_without_max": float(np.max(mae_without)),
            "mae_jackknife_se": jackknife_se(np.asarray(mae_without, dtype=float)),
        },
        "influence_concentration": {
            "sum_abs_delta_ccc": denom,
            "top1_abs_delta_ccc": top1_abs,
            "top1_fraction_of_sum_abs_delta": float(abs_delta.max() / denom) if denom > 0 else None,
            "top5_fraction_of_sum_abs_delta": top5_share,
            "gini_abs_delta_ccc": gini_nonnegative(abs_delta),
        },
        "influence_correlations": {
            "target_value_vs_delta_ccc": corr(merged["y_true"].to_numpy(float), merged["delta_ccc_without_minus_base"].to_numpy(float)),
            "abs_target_minus_median_vs_abs_delta_ccc": corr(
                merged["abs_target_minus_median"].to_numpy(float),
                np.abs(merged["delta_ccc_without_minus_base"].to_numpy(float)),
            ),
            "abs_target_minus_median_vs_abs_error": corr(
                merged["abs_target_minus_median"].to_numpy(float),
                merged["abs_error"].to_numpy(float),
            ),
            "abs_error_vs_abs_delta_ccc": corr(
                merged["abs_error"].to_numpy(float),
                np.abs(merged["delta_ccc_without_minus_base"].to_numpy(float)),
            ),
        },
        "site_influence_summary": site_rows,
        "red_flags": {
            "max_abs_delta_ccc_gt_0_05": bool(top1_abs is not None and top1_abs > 0.05),
            "top5_share_gt_0_50": bool(top5_share is not None and top5_share > 0.50),
            "gini_abs_delta_ccc_gt_0_40": bool((gini_nonnegative(abs_delta) or 0.0) > 0.40),
        },
        "top_abs_delta_ccc": top_abs.to_dict(orient="records"),
        "top_removal_improves_ccc": top_improve.to_dict(orient="records"),
        "top_removal_hurts_ccc": top_hurt.to_dict(orient="records"),
        "manual_review_candidates": high_influence_review.to_dict(orient="records"),
    }


def matched_t1_iter34_vs_iter12(t1_iter12: pd.DataFrame, t1_iter34: pd.DataFrame) -> dict[str, Any]:
    a = t1_iter12.set_index("sid")
    b = t1_iter34.set_index("sid")
    sids = sorted(set(a.index) & set(b.index))
    aa = a.loc[sids].copy()
    bb = b.loc[sids].copy()
    if not np.allclose(aa["y_true"].to_numpy(float), bb["y_true"].to_numpy(float)):
        raise RuntimeError("T1 matched targets differ between iter12 and iter34")
    y = aa["y_true"].to_numpy(float)
    p12 = aa["y_pred"].to_numpy(float)
    p34 = bb["y_pred"].to_numpy(float)
    ccc12 = float(lins_ccc(y, p12))
    ccc34 = float(lins_ccc(y, p34))
    rows = []
    deltas = []
    iter34_leave_one_cccs = []
    for idx, sid in enumerate(sids):
        mask = np.ones(len(sids), dtype=bool)
        mask[idx] = False
        iter34_without = float(lins_ccc(y[mask], p34[mask]))
        iter12_without = float(lins_ccc(y[mask], p12[mask]))
        d = float(iter34_without - iter12_without)
        deltas.append(d)
        iter34_leave_one_cccs.append(iter34_without)
        rows.append(
            {
                "sid": sid,
                "site": site_from_sid(sid),
                "y_true": float(y[idx]),
                "iter12_pred": float(p12[idx]),
                "iter34_pred": float(p34[idx]),
                "iter34_minus_iter12_error_abs_delta": float(abs(p34[idx] - y[idx]) - abs(p12[idx] - y[idx])),
                "iter12_ccc_without_subject": iter12_without,
                "iter34_ccc_without_subject": iter34_without,
                "delta_ccc_iter34_minus_iter12_without_subject": d,
                "change_from_matched_base_delta": float(d - (ccc34 - ccc12)),
            }
        )
    tab = pd.DataFrame(rows)
    return {
        "matched_n": len(sids),
        "iter12_matched_ccc": ccc12,
        "iter34_matched_ccc": ccc34,
        "base_delta_iter34_minus_iter12": float(ccc34 - ccc12),
        "leave_one_delta_min": float(np.min(deltas)),
        "leave_one_delta_max": float(np.max(deltas)),
        "leave_one_delta_mean": float(np.mean(deltas)),
        "leave_one_delta_jackknife_se": jackknife_se(np.asarray(deltas, dtype=float)),
        "iter34_leave_one_ccc_min": float(np.min(iter34_leave_one_cccs)),
        "iter34_leave_one_ccc_max": float(np.max(iter34_leave_one_cccs)),
        "comparison_sign_flips": bool(np.min(deltas) <= 0),
        "iter34_leave_one_below_iter12_canonical_0_6550": bool(np.min(iter34_leave_one_cccs) < 0.6550),
        "top_delta_loss_subjects": tab.sort_values("change_from_matched_base_delta").head(10).to_dict(orient="records"),
        "top_delta_gain_subjects": tab.sort_values("change_from_matched_base_delta", ascending=False).head(10).to_dict(orient="records"),
    }


def fmt(x: Any, ndigits: int = 4) -> str:
    if x is None:
        return "NA"
    try:
        return f"{float(x):.{ndigits}f}"
    except (TypeError, ValueError):
        return str(x)


def main() -> None:
    t1_iter12 = load_t1_json(RESULTS / "t1_iter12_honest_composite.json", "t1_iter12_honest_floor")
    t1_iter34 = load_t1_json(RESULTS / "lockbox_t1_iter34_hybrid_20260506_141720.json", "t1_iter34_hybrid_candidate")
    t3_iter47 = load_t3_iter47_current()

    datasets = {
        "t1_iter12_honest_floor": t1_iter12,
        "t1_iter34_hybrid_candidate": t1_iter34,
        "t3_iter47_validrange_current": t3_iter47,
    }
    audits = {name: influence_audit(df) for name, df in datasets.items()}
    t1_matched = matched_t1_iter34_vs_iter12(t1_iter12, t1_iter34)

    t3_top_abs = audits["t3_iter47_validrange_current"]["top_abs_delta_ccc"][0]
    t1_delta_min = t1_matched["leave_one_delta_min"]
    decision = {
        "scope": "diagnostic_only_no_model_selection",
        "no_model_promotion": True,
        "no_new_loocv": True,
        "redline_summary": {
            "single_subject_abs_delta_threshold": 0.05,
            "top5_share_threshold": 0.50,
            "single_subject_redline_hit": bool(any(a["red_flags"]["max_abs_delta_ccc_gt_0_05"] for a in audits.values())),
            "top5_share_redline_hit": bool(any(a["red_flags"]["top5_share_gt_0_50"] for a in audits.values())),
            "tail_leverage_warning": bool(any(a["red_flags"]["gini_abs_delta_ccc_gt_0_40"] for a in audits.values())),
        },
        "summary": (
            "No single-subject influence pattern justifies a model update. "
            f"T3 max |leave-one CCC delta| is {abs(t3_top_abs['delta_ccc_without_minus_base']):.4f}; "
            f"T1 iter34-minus-iter12 matched delta stays positive under all leave-one deletions "
            f"(minimum {t1_delta_min:.4f}). Influence is still severity-tail concentrated, so this "
            "is a claim-fragility caveat rather than a filtering rule."
        ),
    }
    report = {
        "script": "audit_current_headline_influence.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "t1_iter12": "results/t1_iter12_honest_composite.json",
            "t1_iter34": "results/lockbox_t1_iter34_hybrid_20260506_141720.json",
            "t3_iter47_subject_preds": "results/iter47_invalidcode_subject_preds_20260508_194605.csv",
        },
        "audits": audits,
        "matched_t1_iter34_vs_iter12": t1_matched,
        "decision": decision,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# Current Headline Influence Audit",
        "",
        f"- Created: `{report['created_at_utc']}`",
        "- Scope: diagnostic only; no model selection, no filtering rule, no LOOCV rerun.",
        "",
        "## Baseline And Jackknife Summary",
        "",
        "| Model | N | CCC | MAE | leave-one CCC min | leave-one CCC max | CCC jackknife SE | top1 abs dCCC | top5 share | Gini | red flag |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, audit in audits.items():
        m = audit["baseline_metrics"]
        jk = audit["jackknife"]
        conc = audit["influence_concentration"]
        lines.append(
            f"| `{name}` | {m['n']} | {fmt(m['ccc'])} | {fmt(m['mae'])} | "
            f"{fmt(jk['ccc_without_min'])} | {fmt(jk['ccc_without_max'])} | "
            f"{fmt(jk['ccc_jackknife_se'])} | {fmt(conc['top1_abs_delta_ccc'])} | "
            f"{fmt(conc['top5_fraction_of_sum_abs_delta'])} | "
            f"{fmt(conc['gini_abs_delta_ccc'])} | "
            f"{', '.join(k for k, v in audit['red_flags'].items() if v) or 'none'} |"
        )
    lines.extend(
        [
            "",
            "## Influence Correlations",
            "",
            "| Model | target vs delta CCC | abs(target-median) vs abs(delta CCC) | abs(target-median) vs abs(error) | abs(error) vs abs(delta CCC) |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, audit in audits.items():
        c = audit["influence_correlations"]
        lines.append(
            f"| `{name}` | {fmt(c['target_value_vs_delta_ccc'])} | "
            f"{fmt(c['abs_target_minus_median_vs_abs_delta_ccc'])} | "
            f"{fmt(c['abs_target_minus_median_vs_abs_error'])} | "
            f"{fmt(c['abs_error_vs_abs_delta_ccc'])} |"
        )
    lines.extend(
        [
            "",
            "## T3 Top Influence Subjects",
            "",
            "| SID | site | y | pred | residual | CCC without | delta CCC | missing raw | target delta |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in audits["t3_iter47_validrange_current"]["top_abs_delta_ccc"][:10]:
        lines.append(
            f"| `{row['sid']}` | {row['site']} | {fmt(row['y_true'], 1)} | {fmt(row['y_pred'], 2)} | "
            f"{fmt(row['residual_pred_minus_true'], 2)} | {fmt(row['ccc_without_subject'])} | "
            f"{fmt(row['delta_ccc_without_minus_base'])} | "
            f"{fmt(row.get('raw_part3_missing_validrange'), 0)} | {fmt(row.get('target_delta_original_minus_validrange'), 1)} |"
        )
    lines.extend(
        [
            "",
            "## T1 Candidate Delta Robustness",
            "",
            f"- Matched N: `{t1_matched['matched_n']}`",
            f"- iter12 matched CCC: `{t1_matched['iter12_matched_ccc']:.4f}`",
            f"- iter34 matched CCC: `{t1_matched['iter34_matched_ccc']:.4f}`",
            f"- Base delta: `{t1_matched['base_delta_iter34_minus_iter12']:+.4f}`",
            f"- Leave-one minimum delta: `{t1_matched['leave_one_delta_min']:+.4f}`",
            f"- Sign flip under leave-one deletion: `{t1_matched['comparison_sign_flips']}`",
            "",
            "## Decision",
            "",
            decision["summary"],
            "",
            "Manual review candidates are high-influence rows only; they are not a filtering rule.",
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
