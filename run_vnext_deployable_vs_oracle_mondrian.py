"""Deployable vs oracle Mondrian-CP: distinguishes y-free from y-aware retention.

Two retention rules tested on the SAME calibration:
  Bin labels = outer-train LOO quartile of PREDICTED Y (y-free, OK).
  Bin threshold τ_bin = per-bin LOO quantile of |y - ŷ| over OTHER N-1 calib subjects
                       (y-aware in CALIBRATION, but standard split-conformal — y comes
                       from training labels, not test labels).

  ORACLE retention (Cell A's recipe): retain[i] = |y_i - ŷ_i| ≤ τ_bin_i
    Uses y_i in the retention decision at "test time" — NOT deployable.

  DEPLOYABLE retention (proper Mondrian-CP): retain[i] = τ_bin_i ≤ τ_overall_cutoff
    Sort bins by τ_bin. Keep subjects in the bottom-coverage fraction of bins.
    y-FREE at retention time (you decide based on the bin a test subject falls into,
    and the bin's calibrated threshold is known from training).

The DEPLOYABLE retained CCC is the honest deployment-mode metric.
The ORACLE retained CCC is a diagnostic upper bound.

Outputs: results/lockbox_vnext_deployable_vs_oracle_mondrian_<TS>.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc

RESULTS_DIR = REPO_ROOT / "results"
ITER47_OOF_CSV = RESULTS_DIR / "iter47_invalidcode_subject_preds_20260508_194605.csv"
ITER34_PER_ITEM_OOF = RESULTS_DIR / "t1_iter34_per_item_oof_20260511_044242.npz"
COVERAGE_TARGETS = (1.0, 0.85, 0.70, 0.50)
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def predicted_bins(pred):
    n = len(pred); bins = np.zeros(n, dtype=int)
    for i in range(n):
        mask = np.arange(n) != i
        q = np.quantile(pred[mask], [0.25, 0.5, 0.75])
        bins[i] = int(np.searchsorted(q, pred[i]))
    return bins


def per_subject_bin_threshold(y, pred, bins):
    """For each subject i, compute τ_bin_i = LOO max-quantile of |y - ŷ| over
    OTHER subjects in the same bin. We compute it ONCE at coverage 1.0 (per-bin
    max-residual quantile excluding own bin). The retention coverage is varied
    later by comparing τ_bin_i to the overall coverage cutoff."""
    n = len(y); abs_res = np.abs(y - pred)
    tau = np.zeros(n)
    for i in range(n):
        mask = (bins == bins[i]) & (np.arange(n) != i)
        if mask.sum() < 4:
            mask = np.arange(n) != i
        # tau is the (cov=1.0) quantile == max of residuals in the bin
        # but we'd rather have a smooth per-bin threshold at each coverage
        # → store the SORTED abs_res in the bin (excluding subject i)
        # Then at any coverage τ, threshold = quantile(τ) of this set
        # Here we precompute it as a function — return the sorted array per i.
        pass
    # Simpler: build per-bin sorted residuals once, then look up τ at each coverage.
    return None  # not used directly


def oracle_retained_metrics(y, pred, bins, coverages):
    """ORACLE retention: retain[i] = |y_i - ŷ_i| ≤ τ_bin_i (uses y_i)."""
    n = len(y); abs_res = np.abs(y - pred); rows = []
    for cov in coverages:
        retain = np.zeros(n, dtype=bool)
        for i in range(n):
            mask = (bins == bins[i]) & (np.arange(n) != i)
            if mask.sum() < 4:
                mask = np.arange(n) != i
            thr = float(np.quantile(abs_res[mask], cov))
            retain[i] = abs_res[i] <= thr
        rows.append(_metrics(y, pred, retain, cov, "oracle"))
    return rows


def deployable_retained_metrics(y, pred, bins, coverages):
    """DEPLOYABLE retention: retain[i] = τ_bin_i ≤ overall coverage cutoff.

    For each subject i:
      - compute τ_bin_i = (1-cov_eff)-quantile of |y - ŷ| over OTHER subjects
        in same bin (this is the per-bin calibrated interval width)
      - retain if τ_bin_i is in the bottom-`cov`-fraction of all τ_bin_i values
    """
    n = len(y); abs_res = np.abs(y - pred); rows = []
    # For each bin, precompute the bin's CALIBRATED threshold at the highest
    # coverage (= the max of LOO bin-quantiles at cov=1.0, i.e. the bin's
    # overall residual upper bound). This is the y-free interval width.
    # We use a robust per-bin summary: the median LOO max-residual within the
    # bin (each subject's τ_bin_i computed as the bin's 95th percentile of
    # |y - ŷ| excluding subject i, since 95% is a conventional interval).
    tau = np.zeros(n)
    for i in range(n):
        mask = (bins == bins[i]) & (np.arange(n) != i)
        if mask.sum() < 4:
            mask = np.arange(n) != i
        tau[i] = float(np.quantile(abs_res[mask], 0.95))  # bin's 95% interval width
    # For each target coverage, retain the lowest-`cov`-fraction by tau.
    for cov in coverages:
        if cov >= 1.0:
            retain = np.ones(n, dtype=bool)
        else:
            cutoff = float(np.quantile(tau, cov))
            retain = tau <= cutoff
        rows.append(_metrics(y, pred, retain, cov, "deployable_tau_bin_95"))
    return rows


def disagreement_retained_metrics(y, pred_a, pred_b, coverages):
    """y-FREE disagreement abstention: retain[i] = |pred_a[i] - pred_b[i]| ≤ cutoff."""
    n = len(y); score = np.abs(pred_a - pred_b); rows = []
    for cov in coverages:
        if cov >= 1.0:
            retain = np.ones(n, dtype=bool)
        else:
            # LOO quantile to be consistent
            retain = np.zeros(n, dtype=bool)
            for i in range(n):
                mask = np.arange(n) != i
                thr = float(np.quantile(score[mask], cov))
                retain[i] = score[i] <= thr
        rows.append(_metrics(y, pred_a, retain, cov, "disagreement"))
    return rows


def _metrics(y, pred, retain, cov, label):
    n_ret = int(retain.sum())
    if n_ret < 5:
        return {"label": label, "coverage_target": float(cov),
                "retained_n": n_ret, "retained_ccc": float("nan"),
                "retained_mae": float("nan")}
    yt, yp = y[retain], pred[retain]
    return {
        "label": label, "coverage_target": float(cov),
        "retained_n": n_ret,
        "retained_ccc": float(ccc(yt, yp)),
        "retained_mae": float(np.mean(np.abs(yt - yp))),
    }


def t3_audit():
    df = pd.read_csv(ITER47_OOF_CSV)
    df = df[(df["cohort"] == "drop_allmissing_validrange")
            & (df["stage2_policy"] == "stage2_current")].copy().reset_index(drop=True)
    y = df["y_true_validrange"].to_numpy(np.float64)
    pred = df["y_pred"].to_numpy(np.float64)
    bins = predicted_bins(pred)
    oracle = oracle_retained_metrics(y, pred, bins, COVERAGE_TARGETS)
    deploy = deployable_retained_metrics(y, pred, bins, COVERAGE_TARGETS)
    return {"target": "T3", "n": len(y), "oracle": oracle, "deployable": deploy}


def t1_audit():
    npz = np.load(ITER34_PER_ITEM_OOF)
    y = npz["y_t1"]; pred = npz["t1_sum_pred"]
    bins = predicted_bins(pred)
    oracle = oracle_retained_metrics(y, pred, bins, COVERAGE_TARGETS)
    deploy = deployable_retained_metrics(y, pred, bins, COVERAGE_TARGETS)
    # ALSO compare to the 2026-05-12 V2-only conformal recipe: |p_v2 - p_v3|
    v2 = np.load(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy")
    v3 = np.load(RESULTS_DIR / "lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy")
    disagree = disagreement_retained_metrics(y, v2, v3, COVERAGE_TARGETS)
    return {"target": "T1", "n": len(y), "oracle": oracle,
            "deployable": deploy, "v2_v3_disagreement_baseline": disagree}


def main():
    out = {
        "name": "deployable_vs_oracle_mondrian_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "ts": TS,
        "audit_purpose": (
            "Distinguish y-aware ORACLE Mondrian retention (Cell A recipe — "
            "retain[i] = |y_i - ŷ_i| ≤ τ_bin_i, NOT deployable) from y-FREE "
            "DEPLOYABLE Mondrian retention (retain by τ_bin position in the "
            "ordering across bins). Compare both against the 2026-05-12 V2-only "
            "disagreement baseline for T1."
        ),
        "T1": t1_audit(),
        "T3": t3_audit(),
    }
    path = RESULTS_DIR / f"lockbox_vnext_deployable_vs_oracle_mondrian_{TS}.json"
    path.write_text(json.dumps(out, indent=2,
                                default=lambda o: o.tolist() if hasattr(o, "tolist") else o))
    # Print summary
    print(f"[deployable-audit] wrote {path.name}\n")
    for target in ("T1", "T3"):
        t = out[target]
        print(f"=== {target} (N={t['n']}) ===")
        print(f"{'recipe':<26s}  {'cov':>5s}  {'n':>4s}  {'CCC':>8s}  {'MAE':>6s}")
        for row in t["oracle"]:
            print(f"  {'ORACLE':<24s}  {row['coverage_target']:>5.2f}  "
                  f"{row['retained_n']:>4d}  {row['retained_ccc']:>8.4f}  "
                  f"{row['retained_mae']:>6.2f}")
        for row in t["deployable"]:
            print(f"  {'DEPLOYABLE (tau_bin)':<24s}  {row['coverage_target']:>5.2f}  "
                  f"{row['retained_n']:>4d}  {row['retained_ccc']:>8.4f}  "
                  f"{row['retained_mae']:>6.2f}")
        if "v2_v3_disagreement_baseline" in t:
            for row in t["v2_v3_disagreement_baseline"]:
                print(f"  {'V2-V3 disagreement':<24s}  {row['coverage_target']:>5.2f}  "
                      f"{row['retained_n']:>4d}  {row['retained_ccc']:>8.4f}  "
                      f"{row['retained_mae']:>6.2f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
