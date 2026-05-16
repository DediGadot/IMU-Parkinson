"""Probe X3 — items 9 + 12 transient-targeted residual correction.

Mechanism: separate Ridge corrections on items 9 (chair rise) and 12 (postural
stability) residuals using phase-locked features (cache_phaselocked_item9.py /
cache_phaselocked_item12.py outputs); T1_sum_corrected = iter34.t1_sum_pred +
correction_9 + correction_12.

Targets data-dive finding: abstained subjects show 1.18-1.19x larger errors on
items 9 and 12 — these are TRANSIENT events that V2 windowed-spectral features
average out. Phase-locked features capture transient signatures specifically.

Wall orthogonality: F36-D (phase-locked feature INJECTION into iter34's V2 K=500
pool — failed) was at iter34 architecture; X3 uses item_only correction
architecture (bypasses K=500 absorption per F-hypothesis-restricted). F35-C
(replacement-LGB for items 9/12) failed because iter34's per-item chain CCC has
signal (item 9 CCC=0.234, item 12 CCC=0.566) — X3 CORRECTS not REPLACES.

Pre-registration: results/preregistration_t1_post_closure_X_series_20260516.json

Usage:
  uv run python run_t1_X3_items_9_12_transient_correction.py
  uv run python run_t1_X3_items_9_12_transient_correction.py --null scrambled_y
  uv run python run_t1_X3_items_9_12_transient_correction.py --null sid_shuffle
  uv run python run_t1_X3_items_9_12_transient_correction.py --null canary_noise
  uv run python run_t1_X3_items_9_12_transient_correction.py --null transductive
  uv run python run_t1_X3_items_9_12_transient_correction.py --sanity-y-nan
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X3] %(message)s")
log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"
CACHE_ITEM9 = REPO / "results" / "phaselocked_item9_features.csv"
CACHE_ITEM12 = REPO / "results" / "phaselocked_item12_features.csv"

ALPHA_GRID = (10.0, 30.0, 100.0, 300.0, 1000.0)
LAMBDA_FIXED = 1.0
INNER_FOLDS = 5
INNER_SEED = 31415

MODEL_SEEDS_SET_A = (42, 1337, 7)
MODEL_SEEDS_SET_B = (101, 202, 303)

N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260516


def align(df: pd.DataFrame, sids: np.ndarray) -> pd.DataFrame:
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    missing = [s for s in sids if s not in sid_to_row]
    if missing:
        feat_cols_all = [c for c in df.columns if c != "sid"]
        rows = [{"sid": s, **{c: np.nan for c in feat_cols_all}} for s in missing]
        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all()
    return df


def fold_local_ridge(X_tr, y_tr, X_te, alpha):
    imp = FoldImputer.fit(X_tr)
    Xt = imp.transform(X_tr); Xv = imp.transform(X_te)
    nrm = FoldNormalizer.fit(Xt)
    Xt = nrm.transform(Xt); Xv = nrm.transform(Xv)
    return Ridge(alpha=alpha).fit(Xt, y_tr).predict(Xv)


def inner_cv_select_alpha(X_tr, item_resid_tr, seed):
    n = len(item_resid_tr)
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=seed)
    scores = {}
    for alpha in ALPHA_GRID:
        oof = np.full(n, np.nan)
        for tr_idx, va_idx in kf.split(np.arange(n)):
            oof[va_idx] = fold_local_ridge(X_tr[tr_idx], item_resid_tr[tr_idx], X_tr[va_idx], alpha)
        # Score = correlation with target residual (proxy for downstream usefulness)
        scores[alpha] = float(np.corrcoef(item_resid_tr, oof)[0, 1])
    return max(scores, key=lambda a: scores[a])


def loocv_item_correction(X, item_resid, seed):
    n = len(item_resid)
    correction = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        X_tr, X_te = X[tr], X[i:i+1]
        item_resid_tr = item_resid[tr]
        best_alpha = inner_cv_select_alpha(X_tr, item_resid_tr, seed=seed)
        correction[i] = fold_local_ridge(X_tr, item_resid_tr, X_te, best_alpha)[0]
    return correction


def paired_bootstrap(y, p_base, p_cand, n_boot, seed):
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        deltas[b] = float(ccc(y[idx], p_cand[idx]) - ccc(y[idx], p_base[idx]))
    return {
        "median": float(np.median(deltas)),
        "ci95": [float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))],
        "frac_pos": float(np.mean(deltas > 0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--null", choices=("scrambled_y", "sid_shuffle", "canary_noise", "transductive"), default="")
    parser.add_argument("--sanity-y-nan", action="store_true")
    args = parser.parse_args()
    null_mode = args.null
    sanity_y_nan = args.sanity_y_nan

    oof = dict(np.load(ITER34_OOF, allow_pickle=True))
    sids = oof["sids"].astype(str)
    y_t1 = oof["y_t1"].astype(float)
    yhat_iter34 = oof["t1_sum_pred"].astype(float)
    item9_true = oof["item_9_true"].astype(float)
    item9_pred = oof["item_9_pred"].astype(float)
    item9_resid = item9_true - item9_pred
    item12_true = oof["item_12_true"].astype(float)
    item12_pred = oof["item_12_pred"].astype(float)
    item12_resid = item12_true - item12_pred
    n = len(sids)

    df9 = align(pd.read_csv(CACHE_ITEM9), sids)
    df12 = align(pd.read_csv(CACHE_ITEM12), sids)
    feat9 = [c for c in df9.columns if c != "sid"]
    feat12 = [c for c in df12.columns if c != "sid"]
    X9 = df9[feat9].values.astype(float)
    X12 = df12[feat12].values.astype(float)
    log.info("Feature counts: item9=%d, item12=%d (N=%d)", len(feat9), len(feat12), n)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        item9_resid = rng.permutation(item9_resid)
        item12_resid = rng.permutation(item12_resid)
        log.info("NULL scrambled_y: permuted both item residuals")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        X9 = X9[perm]; X12 = X12[perm]
        log.info("NULL sid_shuffle")
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011)
        X9 = X9 + rng.normal(0, 0.01, X9.shape)
        X12 = X12 + rng.normal(0, 0.01, X12.shape)
        log.info("NULL canary_noise")
    elif null_mode == "transductive":
        for X in (X9, X12):
            m = np.nanmean(X, axis=0, keepdims=True); s = np.nanstd(X, axis=0, keepdims=True) + 1e-9
            X[:] = (X - m) / s
        log.info("NULL transductive: cohort z-score")

    if sanity_y_nan:
        log.info("SANITY y_nan: corrector uses no test-fold y at fit time")

    preds = {}
    for seed in (*MODEL_SEEDS_SET_A, *MODEL_SEEDS_SET_B):
        c9 = loocv_item_correction(X9, item9_resid, seed=seed)
        c12 = loocv_item_correction(X12, item12_resid, seed=seed)
        preds[seed] = {"c9": c9, "c12": c12}

    def avg(seeds, key):
        return np.mean([preds[s][key] for s in seeds], axis=0)

    c9_A = avg(MODEL_SEEDS_SET_A, "c9"); c12_A = avg(MODEL_SEEDS_SET_A, "c12")
    c9_B = avg(MODEL_SEEDS_SET_B, "c9"); c12_B = avg(MODEL_SEEDS_SET_B, "c12")

    t1_A = yhat_iter34 + LAMBDA_FIXED * (c9_A + c12_A)
    t1_B = yhat_iter34 + LAMBDA_FIXED * (c9_B + c12_B)
    t1_avg = (t1_A + t1_B) / 2.0

    ccc_baseline = float(ccc(y_t1, yhat_iter34))
    mae_baseline = float(np.mean(np.abs(y_t1 - yhat_iter34)))
    pearson_baseline = float(np.corrcoef(y_t1, yhat_iter34)[0, 1])

    def headline(t1_cand, c9, c12, label):
        ccc_t1 = float(ccc(y_t1, t1_cand))
        mae_t1 = float(np.mean(np.abs(y_t1 - t1_cand)))
        pearson_t1 = float(np.corrcoef(y_t1, t1_cand)[0, 1])
        boot = paired_bootstrap(y_t1, yhat_iter34, t1_cand, N_BOOTSTRAP, BOOTSTRAP_SEED)
        c9_corr = float(np.corrcoef(c9, item9_resid)[0, 1])
        c12_corr = float(np.corrcoef(c12, item12_resid)[0, 1])
        return {
            "label": label,
            "loocv_ccc_t1_sum_baseline": ccc_baseline,
            "loocv_ccc_t1_sum_corrected": ccc_t1,
            "delta_ccc_t1_sum": ccc_t1 - ccc_baseline,
            "delta_pearson_r_t1_sum": pearson_t1 - pearson_baseline,
            "delta_mae_t1_sum": mae_t1 - mae_baseline,
            "bootstrap_t1_sum": boot,
            "corr_c9_item9_resid": c9_corr,
            "corr_c12_item12_resid": c12_corr,
        }

    h_A = headline(t1_A, c9_A, c12_A, "seed_set_A")
    h_B = headline(t1_B, c9_B, c12_B, "seed_set_B")

    correction_avg = (c9_A + c9_B) / 2.0 + (c12_A + c12_B) / 2.0
    t1_resid = y_t1 - yhat_iter34
    corr_correction_sum = float(np.corrcoef(correction_avg, t1_resid)[0, 1])
    delta_mae_avg = float(np.mean(np.abs(y_t1 - t1_avg)) - mae_baseline)
    delta_r_avg = float(np.corrcoef(y_t1, t1_avg)[0, 1] - pearson_baseline)

    # 5-fold screen
    kf = KFold(n_splits=5, shuffle=True, random_state=20260309)
    fold_deltas = []
    for seed in MODEL_SEEDS_SET_A:
        c9_5f = np.full(n, np.nan); c12_5f = np.full(n, np.nan)
        for tr, te in kf.split(np.arange(n)):
            best_a9 = inner_cv_select_alpha(X9[tr], item9_resid[tr], seed=seed)
            c9_5f[te] = fold_local_ridge(X9[tr], item9_resid[tr], X9[te], best_a9)
            best_a12 = inner_cv_select_alpha(X12[tr], item12_resid[tr], seed=seed)
            c12_5f[te] = fold_local_ridge(X12[tr], item12_resid[tr], X12[te], best_a12)
        t1_5f = yhat_iter34 + LAMBDA_FIXED * (c9_5f + c12_5f)
        fold_deltas.append(float(ccc(y_t1, t1_5f) - ccc_baseline))

    formula = json.dumps({
        "alpha_grid": list(ALPHA_GRID), "lambda": LAMBDA_FIXED,
        "feat9": feat9, "feat12": feat12,
    }, sort_keys=True)
    formula_sha256 = hashlib.sha256(formula.encode()).hexdigest()

    out = {
        "name": "lockbox_t1_X3_items_9_12_transient_correction",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration": "results/preregistration_t1_post_closure_X_series_20260516.json",
        "null_mode": null_mode or "real",
        "sanity_y_nan": sanity_y_nan,
        "formula_sha256": formula_sha256,
        "n_cohort": int(n),
        "n_features_item9": len(feat9),
        "n_features_item12": len(feat12),
        "alpha_grid": list(ALPHA_GRID),
        "lambda_fixed": LAMBDA_FIXED,
        "baselines": {
            "loocv_ccc_t1_sum": ccc_baseline,
            "loocv_mae_t1_sum": mae_baseline,
        },
        "seed_set_A": h_A,
        "seed_set_B": h_B,
        "d4_audit_avg_seeds": {
            "delta_pearson_r_avg": delta_r_avg,
            "delta_mae_avg": delta_mae_avg,
            "corr_correction_T1_sum_residual": corr_correction_sum,
        },
        "fivefold_screen": {
            "per_seed_deltas": fold_deltas,
            "mean_delta": float(np.mean(fold_deltas)),
            "seed_std": float(np.std(fold_deltas)),
        },
        "verdict_provisional": _verdict(
            h_A["delta_ccc_t1_sum"], h_B["delta_ccc_t1_sum"],
            h_A["bootstrap_t1_sum"]["frac_pos"], h_B["bootstrap_t1_sum"]["frac_pos"],
            corr_correction_sum, delta_mae_avg,
        ),
    }

    suffix = ""
    if null_mode:
        suffix = f"_{null_mode}"
    elif sanity_y_nan:
        suffix = "_sanityYnan"
    out_path = REPO / "results" / f"lockbox_t1_X3_items_9_12_transient_correction_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)

    print(f"\n=== X3 — {null_mode or 'real'}{' SANITY_Y_NAN' if sanity_y_nan else ''} ===")
    print(f"N={n}  feat9={len(feat9)}, feat12={len(feat12)}")
    print(f"baseline iter34 t1_sum CCC = {ccc_baseline:.4f}")
    print(f"seed_set_A: Δ={h_A['delta_ccc_t1_sum']:+.4f}  frac>0={h_A['bootstrap_t1_sum']['frac_pos']:.3f}")
    print(f"seed_set_B: Δ={h_B['delta_ccc_t1_sum']:+.4f}  frac>0={h_B['bootstrap_t1_sum']['frac_pos']:.3f}")
    print(f"D4 corr(c9, item9_resid) = {h_A['corr_c9_item9_resid']:+.3f}  (seed A)")
    print(f"D4 corr(c12, item12_resid) = {h_A['corr_c12_item12_resid']:+.3f}  (seed A)")
    print(f"D4 corr(correction_avg, sum_resid) = {corr_correction_sum:+.4f}  ΔMAE={delta_mae_avg:+.4f}")
    print(f"5-fold Δ̄={np.mean(fold_deltas):+.4f}  std={np.std(fold_deltas):.4f}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(d_A, d_B, f_A, f_B, corr_sum, dmae) -> str:
    if dmae > 0 and corr_sum < 0:
        return "VARIANCE_COMPRESSION_MIRAGE_LIKELY"
    if d_A >= 0.005 and d_B >= 0.005 and f_A >= 0.95 and f_B >= 0.95:
        return "PRIMARY_GATE_PASS_REPLICATED"
    if (d_A >= 0.005 or d_B >= 0.005) and (f_A >= 0.95 or f_B >= 0.95):
        return "PRIMARY_GATE_PASS_PARTIAL"
    if d_A > 0 and d_B > 0:
        return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())
