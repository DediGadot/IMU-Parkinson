#!/usr/bin/env python3
"""Post-audit conformal intervals and abstention diagnostics.

This script uses existing lockbox/OOF predictions only. For each subject, the
conformal interval is calibrated from all other subjects' OOF residuals, so the
subject's own label never sets its interval width.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "current_conformal_abstention_20260508.json"
OUT_CONFORMAL = RESULTS / "current_conformal_abstention_intervals_20260508.csv"
OUT_ABSTENTION = RESULTS / "current_conformal_abstention_curves_20260508.csv"
OUT_HTML = RESULTS / "current_conformal_abstention.html"

TARGET_LEVELS = (0.50, 0.80, 0.95)
DISCARD_FRACS = tuple(np.round(np.arange(0.0, 0.51, 0.10), 2))


@dataclass(frozen=True)
class PredictionSet:
    name: str
    label: str
    target: str
    source: str
    sids: list[str]
    y_true: np.ndarray
    y_pred: np.ndarray
    status: str


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ccc(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mt = float(np.mean(y_true))
    mp = float(np.mean(y_pred))
    vt = float(np.var(y_true))
    vp = float(np.var(y_pred))
    cov = float(np.mean((y_true - mt) * (y_pred - mp)))
    denom = vt + vp + (mt - mp) ** 2
    if denom <= 0:
        return 0.0
    return float(2 * cov / denom)


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def pearson(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_true) == 0 or np.std(y_pred) == 0:
        return 0.0
    return float(np.corrcoef(y_true, y_pred)[0, 1])


def quantile_higher(values: np.ndarray, coverage: float) -> float:
    values = np.sort(np.asarray(values, dtype=float))
    n = len(values)
    if n == 0:
        return float("nan")
    rank = int(np.ceil((n + 1) * coverage))
    if rank > n:
        return float("inf")
    return float(values[max(rank - 1, 0)])


def load_t1_json(path: str, *, name: str, label: str, status: str) -> PredictionSet:
    obj = load_json(RESULTS / path)
    per = obj["per_subject"]
    return PredictionSet(
        name=name,
        label=label,
        target="T1_items_9_14",
        source=f"results/{path}",
        sids=[str(s) for s in per["sids"]],
        y_true=np.asarray(per["y_true"], dtype=float),
        y_pred=np.asarray(per["y_pred"], dtype=float),
        status=status,
    )


def load_t3_iter47(stage2_policy: str, *, label: str, status: str) -> PredictionSet:
    df = pd.read_csv(RESULTS / "iter47_invalidcode_subject_preds_20260508_194605.csv")
    df = df[(df["cohort"] == "drop_allmissing_validrange") & (df["stage2_policy"] == stage2_policy)].copy()
    if df.empty:
        raise ValueError(f"No iter47 rows found for {stage2_policy}")
    return PredictionSet(
        name=f"t3_iter47_{stage2_policy}",
        label=label,
        target="T3_total_UPDRS_III_validrange",
        source="results/iter47_invalidcode_subject_preds_20260508_194605.csv",
        sids=[str(s) for s in df["sid"].tolist()],
        y_true=df["y_true_validrange"].to_numpy(dtype=float),
        y_pred=df["y_pred"].to_numpy(dtype=float),
        status=status,
    )


def site_of_sid(sid: str) -> str:
    if sid.startswith("WPD"):
        return "WPD"
    if sid.startswith("NLS"):
        return "NLS"
    return "other"


def conformal_rows(pred_set: PredictionSet) -> list[dict[str, Any]]:
    residuals = np.abs(pred_set.y_true - pred_set.y_pred)
    rows: list[dict[str, Any]] = []
    for coverage in TARGET_LEVELS:
        alpha = 1.0 - coverage
        lowers = []
        uppers = []
        widths = []
        covered = []
        q_values = []
        for idx in range(len(residuals)):
            calib = np.delete(residuals, idx)
            q = quantile_higher(calib, coverage)
            lo = pred_set.y_pred[idx] - q
            hi = pred_set.y_pred[idx] + q
            q_values.append(q)
            lowers.append(lo)
            uppers.append(hi)
            widths.append(hi - lo)
            covered.append(bool(lo <= pred_set.y_true[idx] <= hi))
        sites = np.asarray([site_of_sid(sid) for sid in pred_set.sids])
        covered_arr = np.asarray(covered, dtype=bool)
        for group in ["all", "NLS", "WPD"]:
            mask = np.ones(len(sites), dtype=bool) if group == "all" else sites == group
            if not mask.any():
                continue
            rows.append(
                {
                    "model": pred_set.name,
                    "label": pred_set.label,
                    "target": pred_set.target,
                    "status": pred_set.status,
                    "source": pred_set.source,
                    "group": group,
                    "nominal_coverage": coverage,
                    "alpha": alpha,
                    "n": int(mask.sum()),
                    "empirical_coverage": float(np.mean(covered_arr[mask])),
                    "mean_interval_width": float(np.mean(np.asarray(widths)[mask])),
                    "median_interval_width": float(np.median(np.asarray(widths)[mask])),
                    "min_q": float(np.min(np.asarray(q_values)[mask])),
                    "max_q": float(np.max(np.asarray(q_values)[mask])),
                }
            )
    return rows


def subset_metrics(pred_set: PredictionSet, keep_mask: np.ndarray) -> dict[str, Any]:
    yp = pred_set.y_pred[keep_mask]
    yt = pred_set.y_true[keep_mask]
    return {
        "retained_n": int(keep_mask.sum()),
        "ccc": ccc(yt, yp),
        "mae": mae(yt, yp),
        "r": pearson(yt, yp),
    }


def abstention_rows(pred_set: PredictionSet) -> list[dict[str, Any]]:
    n = len(pred_set.y_true)
    residual_score = np.abs(pred_set.y_true - pred_set.y_pred)
    pred_median = float(np.median(pred_set.y_pred))
    pred_tail_score = np.abs(pred_set.y_pred - pred_median)
    policies = [
        (
            "prediction_tail_distance",
            pred_tail_score,
            "deployable_proxy_discards_predictions_farthest_from_prediction_median",
        ),
        (
            "oracle_abs_error_upper_bound",
            residual_score,
            "not_deployable_uses_true_error_for_diagnostic_ceiling_only",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for policy, score, note in policies:
        order = np.argsort(score)
        for discard_frac in DISCARD_FRACS:
            retained_n = max(int(round(n * (1.0 - discard_frac))), 0)
            if retained_n < 3:
                continue
            keep_idx = order[:retained_n]
            keep_mask = np.zeros(n, dtype=bool)
            keep_mask[keep_idx] = True
            metrics = subset_metrics(pred_set, keep_mask)
            rows.append(
                {
                    "model": pred_set.name,
                    "label": pred_set.label,
                    "target": pred_set.target,
                    "status": pred_set.status,
                    "source": pred_set.source,
                    "policy": policy,
                    "policy_note": note,
                    "discard_frac": float(discard_frac),
                    "retained_frac": float(1.0 - discard_frac),
                    "score_threshold": float(np.max(score[keep_mask])),
                    **metrics,
                }
            )
    return rows


def summary_for(pred_set: PredictionSet, conformal: pd.DataFrame, abstention: pd.DataFrame) -> dict[str, Any]:
    base = {
        "label": pred_set.label,
        "target": pred_set.target,
        "status": pred_set.status,
        "source": pred_set.source,
        "n": len(pred_set.y_true),
        "base_ccc": ccc(pred_set.y_true, pred_set.y_pred),
        "base_mae": mae(pred_set.y_true, pred_set.y_pred),
        "base_r": pearson(pred_set.y_true, pred_set.y_pred),
    }
    conformal_all = conformal[(conformal["model"] == pred_set.name) & (conformal["group"] == "all")]
    base["conformal"] = {
        f"{int(row.nominal_coverage * 100)}pct": {
            "empirical_coverage": float(row.empirical_coverage),
            "mean_interval_width": float(row.mean_interval_width),
        }
        for row in conformal_all.itertuples(index=False)
    }
    pred_policy = abstention[
        (abstention["model"] == pred_set.name)
        & (abstention["policy"] == "prediction_tail_distance")
        & (abstention["discard_frac"] == 0.5)
    ]
    oracle_policy = abstention[
        (abstention["model"] == pred_set.name)
        & (abstention["policy"] == "oracle_abs_error_upper_bound")
        & (abstention["discard_frac"] == 0.5)
    ]
    base["abstention_at_50pct_discard"] = {
        "prediction_tail_distance_ccc": float(pred_policy.iloc[0]["ccc"]) if not pred_policy.empty else None,
        "prediction_tail_distance_mae": float(pred_policy.iloc[0]["mae"]) if not pred_policy.empty else None,
        "oracle_abs_error_ccc": float(oracle_policy.iloc[0]["ccc"]) if not oracle_policy.empty else None,
        "oracle_abs_error_mae": float(oracle_policy.iloc[0]["mae"]) if not oracle_policy.empty else None,
    }
    return base


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return html.escape(str(value))


def render_html(summary: dict[str, Any], conformal: pd.DataFrame, abstention: pd.DataFrame) -> str:
    cards = []
    for name, item in summary["models"].items():
        cards.append(
            "<tr>"
            f"<td>{html.escape(item['label'])}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{item['n']}</td>"
            f"<td>{fmt(item['base_ccc'])}</td>"
            f"<td>{fmt(item['base_mae'], 3)}</td>"
            f"<td>{fmt(item['conformal']['80pct']['mean_interval_width'], 2)}</td>"
            f"<td>{fmt(item['conformal']['95pct']['mean_interval_width'], 2)}</td>"
            f"<td>{fmt(item['abstention_at_50pct_discard']['prediction_tail_distance_ccc'])}</td>"
            "</tr>"
        )
    conformal_rows_html = []
    for row in conformal[conformal["group"] == "all"].itertuples(index=False):
        conformal_rows_html.append(
            "<tr>"
            f"<td>{html.escape(row.label)}</td>"
            f"<td>{int(row.nominal_coverage * 100)}%</td>"
            f"<td>{row.n}</td>"
            f"<td>{fmt(row.empirical_coverage, 3)}</td>"
            f"<td>{fmt(row.mean_interval_width, 2)}</td>"
            "</tr>"
        )
    abst_rows_html = []
    deployable = abstention[abstention["policy"] == "prediction_tail_distance"]
    for row in deployable.itertuples(index=False):
        abst_rows_html.append(
            "<tr>"
            f"<td>{html.escape(row.label)}</td>"
            f"<td>{int(row.discard_frac * 100)}%</td>"
            f"<td>{row.retained_n}</td>"
            f"<td>{fmt(row.ccc)}</td>"
            f"<td>{fmt(row.mae, 3)}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Current Conformal and Abstention Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #18212b; }}
    h1, h2 {{ margin-bottom: 8px; }}
    p {{ max-width: 1040px; line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; margin: 14px 0 28px; }}
    th, td {{ border-bottom: 1px solid #d9dee7; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f4f6f8; }}
    .note {{ border-left: 4px solid #176f6b; padding: 10px 14px; background: #f2f8f7; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  </style>
</head>
<body>
  <h1>Current Conformal and Abstention Report</h1>
  <p>Generated {html.escape(summary['generated_at_utc'])}. This report uses existing lockbox/OOF predictions only. Each subject's interval is calibrated from all other subjects' OOF residuals.</p>
  <div class="note"><p><strong>Interpretation:</strong> conformal intervals are wide, especially for T3. The deployable abstention proxy based only on prediction extremeness does not rescue the corrected T3 ceiling. The oracle curve is saved in CSV/JSON as a non-deployable diagnostic upper bound.</p></div>
  <h2>Summary</h2>
  <table><thead><tr><th>Model</th><th>Status</th><th>N</th><th>Base CCC</th><th>Base MAE</th><th>80% Width</th><th>95% Width</th><th>CCC After 50% Deployable Discard</th></tr></thead><tbody>{''.join(cards)}</tbody></table>
  <h2>Conformal Coverage</h2>
  <table><thead><tr><th>Model</th><th>Nominal</th><th>N</th><th>Empirical Coverage</th><th>Mean Width</th></tr></thead><tbody>{''.join(conformal_rows_html)}</tbody></table>
  <h2>Deployable Abstention Proxy</h2>
  <p>Rows discard predictions farthest from the model's own prediction median. This uses no labels at decision time, but it is only a coarse uncertainty proxy.</p>
  <table><thead><tr><th>Model</th><th>Discarded</th><th>Retained N</th><th>CCC</th><th>MAE</th></tr></thead><tbody>{''.join(abst_rows_html)}</tbody></table>
</body>
</html>
"""


def main() -> None:
    pred_sets = [
        load_t1_json(
            "t1_iter12_honest_composite.json",
            name="t1_iter12_honest",
            label="T1 iter12 honest floor",
            status="canonical_floor",
        ),
        load_t1_json(
            "lockbox_t1_iter34_hybrid_20260506_141720.json",
            name="t1_iter34_hybrid",
            label="T1 iter34 hybrid candidate",
            status="candidate_caveated",
        ),
        load_t3_iter47(
            "stage2_current",
            label="T3 iter47 valid-range current",
            status="corrected_audit_truth",
        ),
        load_t3_iter47(
            "stage2_no_cv",
            label="T3 iter47 valid-range no-cv",
            status="sensitivity",
        ),
    ]

    conformal = pd.DataFrame([row for pred_set in pred_sets for row in conformal_rows(pred_set)])
    abstention = pd.DataFrame([row for pred_set in pred_sets for row in abstention_rows(pred_set)])
    conformal.to_csv(OUT_CONFORMAL, index=False)
    abstention.to_csv(OUT_ABSTENTION, index=False)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "run_current_conformal_abstention.py",
        "method": {
            "conformal": "leave-one-subject-out residual quantiles over existing OOF predictions",
            "abstention_deployable": "discard predictions farthest from the prediction median",
            "abstention_oracle": "saved as non-deployable diagnostic upper bound using true absolute error",
            "model_refit": False,
            "new_hyperparameter_tuning": False,
        },
        "outputs": {
            "json": str(OUT_JSON.relative_to(ROOT)),
            "conformal_csv": str(OUT_CONFORMAL.relative_to(ROOT)),
            "abstention_csv": str(OUT_ABSTENTION.relative_to(ROOT)),
            "html": str(OUT_HTML.relative_to(ROOT)),
        },
        "models": {},
        "verdict": "intervals_are_wide_and_deployable_abstention_does_not_break_t3_or_canonicalize_t1",
    }
    for pred_set in pred_sets:
        summary["models"][pred_set.name] = summary_for(pred_set, conformal, abstention)

    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    OUT_HTML.write_text(render_html(summary, conformal, abstention), encoding="utf-8")

    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_CONFORMAL.relative_to(ROOT)}")
    print(f"Wrote {OUT_ABSTENTION.relative_to(ROOT)}")
    print(f"Wrote {OUT_HTML.relative_to(ROOT)}")
    for name, item in summary["models"].items():
        print(
            f"{name}: n={item['n']} ccc={item['base_ccc']:.4f} "
            f"mae={item['base_mae']:.3f} "
            f"width80={item['conformal']['80pct']['mean_interval_width']:.2f} "
            f"width95={item['conformal']['95pct']['mean_interval_width']:.2f} "
            f"deployable50_ccc={item['abstention_at_50pct_discard']['prediction_tail_distance_ccc']:.4f}"
        )


if __name__ == "__main__":
    main()
