"""T3 Slot F: Y-free CQR (Conformalized Quantile Regression) interval-width abstention.

Per CLAUDE.md 'T3 conformal status (2026-05-14): No deployable T3 conformal exists
yet... Open: legitimate y-free T3 abstention recipes (CQR interval width, ...).'

This implements CQR interval width:
  - Train two LGB-quantile heads (α=0.05, α=0.95) on Stage-1 residual per fold
  - Width(x) = pred_q95(x) - pred_q05(x), computed on test fold from features only
  - Y-free by construction
  - Retain bottom-X% by width (narrow interval = high confidence)
  - Report retained CCC at 70%, 50% coverage using iter47 POINT predictions

Distinct from W#73 (LGB-quantile median as POINT predictor failed): here LGB-quantile
provides INTERVAL WIDTH as an abstention score, NOT a point estimate. iter47's point
predictions are unchanged.

If retained CCC > 0.45 at 70% (full-cohort 0.378 + MCID 0.025 + margin), this OPENS
a new T3 deployable-secondary ceiling that didn't exist before.

Sanity y-nan: width is y-free; mask must be identical with y=nan.

Lifetime FWER family = 11 (Slot E was n=10).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

# Reuse iter47 plumbing
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter41_target_fix import build_stage1_matrix, filter_stage2, fit_stage1

ITER47_SUBJ_PREDS_CSV = "results/iter47_invalidcode_subject_preds_20260508_194605.csv"

COVERAGES = [0.70, 0.50]
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515
N_TOP_K = 500  # match iter47

QUANTILES = [0.05, 0.95]
LGB_QUANT_PARAMS = dict(
    n_estimators=300, num_leaves=15, learning_rate=0.05,
    min_data_in_leaf=5, reg_lambda=0.0, verbosity=-1, n_jobs=1,
)


def fold_local_univariate_topk(X_tr_n: np.ndarray, y_tr: np.ndarray, k: int) -> np.ndarray:
    Xs = X_tr_n - X_tr_n.mean(axis=0, keepdims=True)
    ys = y_tr - y_tr.mean()
    sx = np.nan_to_num(Xs.std(axis=0), nan=1e-9) + 1e-9
    sy = ys.std() + 1e-9
    cov = (Xs * ys[:, None]).mean(axis=0)
    corr = np.abs(cov / (sx * sy))
    corr = np.where(np.isnan(corr), 0.0, corr)
    return np.argsort(corr)[::-1][:k]


def compute_quantile_widths_loocv(data: dict, seed: int = 42) -> np.ndarray:
    """Per-subject CQR interval width (y-free at test time, y-trained at fit time)."""
    sids = data["sids"]
    X = data["X"]
    feat_cols = data["feat_cols"]
    y = data["y_t3"]
    hy = data["hy"]
    n = len(sids)
    X_s2, _ = filter_stage2(X, feat_cols, "stage2_current")
    X_s1 = build_stage1_matrix(sids, hy)

    widths = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[i:i+1], alpha=1.0)
        resid_tr = y[tr] - s1_tr

        imp = FoldImputer.fit(X_s2[tr])
        Xt = imp.transform(X_s2[tr])
        Xv = imp.transform(X_s2[i:i+1])
        nrm = FoldNormalizer.fit(Xt)
        Xt = nrm.transform(Xt)
        Xv = nrm.transform(Xv)
        top500 = fold_local_univariate_topk(Xt, resid_tr, N_TOP_K)

        # Quantile heads on residual
        pred_per_q = {}
        for q in QUANTILES:
            params = dict(LGB_QUANT_PARAMS)
            params["objective"] = "quantile"
            params["alpha"] = q
            params["random_state"] = seed
            m = lgb.LGBMRegressor(**params)
            m.fit(Xt[:, top500], resid_tr)
            pred_per_q[q] = float(m.predict(Xv[:, top500])[0])
        widths[i] = pred_per_q[0.95] - pred_per_q[0.05]
        if (i + 1) % 20 == 0:
            print(f"  fold {i+1}/{n}: width={widths[i]:+.3f}")
    return widths


def retained_ccc_at_coverage(
    y: np.ndarray, yhat: np.ndarray, score: np.ndarray, coverage: float
) -> tuple[float, np.ndarray, int]:
    n = len(y)
    k = int(round(coverage * n))
    if k < 5:
        return float("nan"), np.zeros(n, dtype=bool), 0
    order = np.argsort(score, kind="stable")
    mask = np.zeros(n, dtype=bool)
    mask[order[:k]] = True
    return float(ccc(y[mask], yhat[mask])), mask, int(mask.sum())


def load_iter47_aligned(data: dict) -> np.ndarray:
    df = pd.read_csv(ITER47_SUBJ_PREDS_CSV)
    df = df[(df["cohort"] == "drop_allmissing_validrange") & (df["stage2_policy"] == "stage2_current")]
    sid_to_pred = dict(zip(df["sid"].astype(str), df["y_pred"].astype(float)))
    preds = np.array([sid_to_pred.get(str(s), np.nan) for s in data["sids"]])
    if np.isnan(preds).any():
        preds = np.where(np.isnan(preds), np.nanmean(preds), preds)
    return preds


def sanity_y_nan(data: dict, iter47_preds: np.ndarray, widths: np.ndarray):
    y = data["y_t3"]
    n = len(y)
    y_nan = np.full(n, np.nan)
    masks_real = {}
    masks_nan = {}
    for cov in COVERAGES:
        _, mr, _ = retained_ccc_at_coverage(y, iter47_preds, widths, cov)
        _, mn, _ = retained_ccc_at_coverage(y_nan, iter47_preds, widths, cov)
        masks_real[f"cov_{int(cov*100)}"] = mr.tolist()
        masks_nan[f"cov_{int(cov*100)}"] = mn.tolist()
    all_match = all(masks_real[k] == masks_nan[k] for k in masks_real)
    receipt = {
        "name": "abstention_sanity_t3_slotF_cqr_width",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "lockbox_target": "lockbox_t3_slotF_cqr_width_conformal",
        "retention_rule_form": "g(x) = quantile_pred_q95(x) - quantile_pred_q05(x) from train-fold quantile heads, NO y_test",
        "n_subjects": n,
        "masks_identical_with_y_nan": all_match,
        "test_passes": all_match,
    }
    ts = receipt["created_at_utc"]
    path = Path(f"results/abstention_sanity_{ts}.json")
    path.write_text(json.dumps(receipt, indent=2))
    print(f"[Sanity y_nan] all_match={all_match}, wrote {path}")
    return all_match


def main(
    null_mode: str = "",
    quantile_seed: int = 42,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    n_bootstrap: int = N_BOOTSTRAP,
    tag: str = "",
):
    data = filter_cohort("drop_allmissing_validrange")
    y = data["y_t3"]
    n = len(y)
    iter47_preds = load_iter47_aligned(data)
    full_ccc = float(ccc(y, iter47_preds))
    print(f"[Slot F] N={n}, full-cohort iter47 CCC={full_ccc:.4f}")
    print(f"[Slot F] null_mode={null_mode or 'none'}")
    print(f"[Slot F] quantile_seed={quantile_seed}, bootstrap_seed={bootstrap_seed}, n_bootstrap={n_bootstrap}")

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        y = y[perm]
        iter47_preds = iter47_preds[perm]
        data = {**data, "y_t3": y}
        print(f"[Slot F NULL] permuted y + iter47_preds")

    print(f"[Slot F] Computing CQR widths (LOOCV, seed={quantile_seed})...")
    widths = compute_quantile_widths_loocv(data, seed=quantile_seed)
    print(f"[Slot F] Width distribution: median={np.median(widths):.3f}, "
          f"min={np.min(widths):.3f}, max={np.max(widths):.3f}")

    # Sanity y_nan
    ok = sanity_y_nan(data, iter47_preds, widths)
    print(f"[Slot F] Sanity y_nan = {ok}")

    rng = np.random.default_rng(bootstrap_seed)
    results_per_coverage = {}
    for cov in COVERAGES:
        retained_ccc, mask, n_ret = retained_ccc_at_coverage(y, iter47_preds, widths, cov)
        retained_mae = float(np.mean(np.abs(y[mask] - iter47_preds[mask])))
        delta_vs_full = retained_ccc - full_ccc

        retained_idx = np.where(mask)[0]
        retained_cccs_boot = np.empty(n_bootstrap)
        for b in range(n_bootstrap):
            idx_resampled = rng.choice(retained_idx, size=len(retained_idx), replace=True)
            retained_cccs_boot[b] = float(ccc(y[idx_resampled], iter47_preds[idx_resampled]))
        ci = (float(np.percentile(retained_cccs_boot, 2.5)),
              float(np.percentile(retained_cccs_boot, 97.5)))
        frac_above_full = float((retained_cccs_boot > full_ccc).mean())

        results_per_coverage[f"cov_{int(cov*100)}"] = {
            "coverage": cov,
            "n_retained": n_ret,
            "iter47_full_cohort_ccc": round(full_ccc, 4),
            "iter47_retained_ccc": round(retained_ccc, 4),
            "delta_retained_vs_full": round(delta_vs_full, 4),
            "iter47_retained_mae": round(retained_mae, 4),
            "bootstrap_retained_ccc_ci95": [round(ci[0], 4), round(ci[1], 4)],
            "frac_retained_above_full": round(frac_above_full, 4),
        }
        print(f"[Slot F] coverage={int(cov*100)}%, n_retained={n_ret}: "
              f"retained CCC={retained_ccc:.4f}, Δ vs full={delta_vs_full:+.4f}, "
              f"frac>full={frac_above_full:.4f}")

    LIFETIME_FWER = 11
    bonf_gate = 1.0 - 0.05 / LIFETIME_FWER

    verdicts = {}
    for k, v in results_per_coverage.items():
        if v["frac_retained_above_full"] >= bonf_gate and v["delta_retained_vs_full"] >= 0.05:
            verdicts[k] = "BREAK_T3_DEPLOYABLE_SECONDARY_BONFERRONI"
        elif v["frac_retained_above_full"] >= 0.95 and v["delta_retained_vs_full"] >= 0.05:
            verdicts[k] = "BREAK_T3_DEPLOYABLE_SECONDARY_UNCORRECTED"
        elif v["frac_retained_above_full"] >= 0.95 and v["delta_retained_vs_full"] >= 0.025:
            verdicts[k] = "BREAK_T3_DEPLOYABLE_SECONDARY_SUB_BONFERRONI_MCID"
        elif v["frac_retained_above_full"] >= 0.95:
            verdicts[k] = "PASS_BUT_BELOW_MCID"
        else:
            verdicts[k] = "FAIL"

    out = {
        "name": "lockbox_t3_slotF_cqr_width_conformal",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "session": "2026-05-15-PM-extended",
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_master.json",
        "replication_tag": tag or "original_seed42" if quantile_seed == 42 else tag or "explicit_seed",
        "null_mode": null_mode or "real",
        "estimand_label": "T3_deployable_secondary_retained_ccc_at_coverage_via_CQR_width",
        "y_free_score": "LGB-quantile q95 - q05 width on Stage-1 residual",
        "n_full_cohort": n,
        "full_cohort_iter47_ccc": round(full_ccc, 4),
        "quantiles": QUANTILES,
        "lgb_quantile_params": LGB_QUANT_PARAMS,
        "quantile_seed": quantile_seed,
        "bootstrap_seed": bootstrap_seed,
        "n_bootstrap": n_bootstrap,
        "n_top_k": N_TOP_K,
        "sanity_y_nan_passes": ok,
        "results_per_coverage": results_per_coverage,
        "verdicts_per_coverage": verdicts,
        "gates": {
            "lifetime_n11_bonferroni_gate": round(bonf_gate, 5),
            "mcid_delta_retained_vs_full": 0.025,
            "bonferroni_mcid_delta": 0.05,
        },
    }
    ts = out["created_at_utc"]
    parts = []
    if tag:
        parts.append(tag)
    if null_mode:
        parts.append(null_mode)
    suffix = f"_{'_'.join(parts)}" if parts else ""
    path = Path(f"results/lockbox_t3_slotF_cqr_width_conformal_{ts}{suffix}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[Slot F] Per-coverage verdicts: {verdicts}")
    print(f"[Slot F] Wrote {path}")


def parse_args(argv: list[str]) -> dict:
    null_mode = ""
    quantile_seed = 42
    bootstrap_seed = BOOTSTRAP_SEED
    n_bootstrap = N_BOOTSTRAP
    tag = ""
    for arg in argv:
        if arg.startswith("--null="):
            null_mode = arg.split("=", 1)[1]
        elif arg.startswith("--seed="):
            quantile_seed = int(arg.split("=", 1)[1])
        elif arg.startswith("--bootstrap-seed="):
            bootstrap_seed = int(arg.split("=", 1)[1])
        elif arg.startswith("--n-bootstrap="):
            n_bootstrap = int(arg.split("=", 1)[1])
        elif arg.startswith("--tag="):
            tag = arg.split("=", 1)[1]
        else:
            raise SystemExit(f"Unknown argument: {arg}")
    return {
        "null_mode": null_mode,
        "quantile_seed": quantile_seed,
        "bootstrap_seed": bootstrap_seed,
        "n_bootstrap": n_bootstrap,
        "tag": tag,
    }


if __name__ == "__main__":
    main(**parse_args(sys.argv[1:]))
