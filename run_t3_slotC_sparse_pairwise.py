"""T3 Slot C: Sparse pairwise-interaction proxy for the F68 K=250 GB hump.

Hypothesis (mechanism test, not a 7th K-sweep):
  The K=250 sklearn-GB lift (Δ=+0.073, frac>0=0.9518, Bonferroni-fails by 0.04)
  is fundamentally a mid-dim INTERACTION structure. If the K=250 hump truly
  encodes pairwise interactions among ~15-30 dominant features, then constructing
  TOP-30 univariate + 50 TARGETED pairwise products (top-15 × top-15) should
  reproduce the +0.07 lift with TIGHTER bootstrap CI (fewer features → less
  variance → cleaner frac>0).

Architecture (orthogonal to all prior K-sweeps):
  - Stage 1: H&Y + cv_yrs + cv_sex + cv_dbs Ridge α=1.0 (canonical iter47)
  - Stage 2: 30 univariate features by Pearson |corr| with Stage-1 residual
             + 50 BEST pairwise products (top-15 × top-15 = 105 pairs;
             keep 50 highest |corr| with residual, fold-local selection)
  - Model: sklearn GradientBoostingRegressor(n_est=300, max_depth=3, lr=0.05,
           min_samples_leaf=10, subsample=0.8) on Stage-2 residual
  - Outer LOOCV, 3 seeds
  - Inner CV not needed — feature counts pre-declared

Distinct from F68/F69 K=250: this uses TOTAL 80 features (30 univariate + 50
pairwise), an order of magnitude fewer than K=250. If it MATCHES F68 magnitude,
the interaction hypothesis is confirmed. If it BEATS Bonferroni, the T3 ceiling
breaks.

Lifetime FWER family = 8. Bonferroni gate frac>0 ≥ 0.99375.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import GradientBoostingRegressor

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

# Reuse iter47 plumbing
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter41_target_fix import build_stage1_matrix, filter_stage2

SEEDS = [42, 1337, 7]
N_TOP_UNIVARIATE = 30
N_TOP_PAIRWISE_BASE = 15  # top-15 × top-15 = 105 candidate pairs
N_TOP_PAIRWISE_SELECTED = 50
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515

GB_PARAMS = dict(
    n_estimators=300, max_depth=3, learning_rate=0.05,
    min_samples_leaf=10, subsample=0.8, random_state=0,
)


def fold_local_univariate_topk(
    X_tr_n: np.ndarray, resid_tr: np.ndarray, k: int
) -> np.ndarray:
    """Fold-local Pearson-|corr| top-k feature indices."""
    Xs = X_tr_n - X_tr_n.mean(axis=0, keepdims=True)
    ys = resid_tr - resid_tr.mean()
    sx = np.nan_to_num(Xs.std(axis=0), nan=1e-9) + 1e-9
    sy = ys.std() + 1e-9
    cov = (Xs * ys[:, None]).mean(axis=0)
    corr = np.abs(cov / (sx * sy))
    corr = np.where(np.isnan(corr), 0.0, corr)
    return np.argsort(corr)[::-1][:k]


def build_pairwise_features(
    X_tr_n: np.ndarray, X_te_n: np.ndarray,
    base_idx: np.ndarray, resid_tr: np.ndarray, k_pair: int,
) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """Construct top-K pairwise products from base_idx feature set; select fold-locally."""
    K = len(base_idx)
    # Generate all pairs (i, j) with i <= j
    pairs = [(int(base_idx[i]), int(base_idx[j])) for i in range(K) for j in range(i, K)]
    # Compute products on train fold
    prod_tr = np.column_stack([X_tr_n[:, i] * X_tr_n[:, j] for i, j in pairs])
    prod_te = np.column_stack([X_te_n[:, i] * X_te_n[:, j] for i, j in pairs])
    # Select top-K pairs by |corr| with residual on train fold only
    Xs = prod_tr - prod_tr.mean(axis=0, keepdims=True)
    ys = resid_tr - resid_tr.mean()
    sx = np.nan_to_num(Xs.std(axis=0), nan=1e-9) + 1e-9
    sy = ys.std() + 1e-9
    cov = (Xs * ys[:, None]).mean(axis=0)
    corr = np.abs(cov / (sx * sy))
    corr = np.where(np.isnan(corr), 0.0, corr)
    sel = np.argsort(corr)[::-1][:k_pair]
    return prod_tr[:, sel], prod_te[:, sel], [pairs[s] for s in sel]


def slot_c_loocv(data: dict, seed: int) -> np.ndarray:
    """Outer LOOCV with seed-controlled GB."""
    sids = data["sids"]
    X = data["X"]
    feat_cols = data["feat_cols"]
    y = data["y_t3"]
    hy = data["hy"]
    n = len(sids)

    # Stage-2 features (canonical iter47 policy stage2_current)
    X_s2, _ = filter_stage2(X, feat_cols, "stage2_current")
    X_s1 = build_stage1_matrix(sids, hy)

    preds = np.full(n, np.nan)
    gb_params = dict(GB_PARAMS)
    gb_params["random_state"] = seed
    for i in range(n):
        tr = np.arange(n) != i
        # Stage 1: Ridge α=1
        ridge = Ridge(alpha=1.0).fit(X_s1[tr], y[tr])
        s1_tr = ridge.predict(X_s1[tr])
        s1_te = ridge.predict(X_s1[i:i+1])
        resid_tr = y[tr] - s1_tr

        # Stage 2: impute + normalize ONCE on train fold
        Xt_raw, Xv_raw = X_s2[tr], X_s2[i:i+1]
        imp = FoldImputer.fit(Xt_raw)
        Xt_i = imp.transform(Xt_raw)
        Xv_i = imp.transform(Xv_raw)
        nrm = FoldNormalizer.fit(Xt_i)
        Xt_n = nrm.transform(Xt_i)
        Xv_n = nrm.transform(Xv_i)

        # Top-30 univariate
        top_uni = fold_local_univariate_topk(Xt_n, resid_tr, N_TOP_UNIVARIATE)
        # Top-15 base for pairwise
        base_pair = fold_local_univariate_topk(Xt_n, resid_tr, N_TOP_PAIRWISE_BASE)
        # Top-50 pairwise from top-15 × top-15
        pair_tr, pair_te, _ = build_pairwise_features(
            Xt_n, Xv_n, base_pair, resid_tr, N_TOP_PAIRWISE_SELECTED
        )

        # Concatenate Stage-2 features
        Xs2_tr = np.column_stack([Xt_n[:, top_uni], pair_tr])
        Xs2_te = np.column_stack([Xv_n[:, top_uni], pair_te])

        # Stage 2 model: sklearn GB on residual
        gb = GradientBoostingRegressor(**gb_params)
        gb.fit(Xs2_tr, resid_tr)
        s2_te = gb.predict(Xs2_te)
        preds[i] = s1_te[0] + s2_te[0]

        if (i + 1) % 20 == 0:
            print(f"  seed {seed} fold {i+1}/{n}: pred={preds[i]:.3f}")
    return preds


def main(null_mode: str = ""):
    data = filter_cohort("drop_allmissing_validrange")
    y = data["y_t3"]
    n = len(y)
    print(f"[Slot C] T3 N={n} (drop_allmissing_validrange = iter47 canonical cohort)")
    print(f"[Slot C] null_mode={null_mode or 'none'}, seeds={SEEDS}")
    print(f"[Slot C] features = top-{N_TOP_UNIVARIATE} univariate + top-{N_TOP_PAIRWISE_SELECTED} pairwise (from top-{N_TOP_PAIRWISE_BASE} base)")

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        y = rng.permutation(y)
        data = {**data, "y_t3": y}
        print(f"[Slot C NULL] scrambled y_t3")

    # iter47 baseline preds for paired bootstrap — recompute fresh to ensure same cohort
    # Use the canonical iter47 stage2_current pipeline
    from run_t3_iter41_target_fix import fit_stage1
    X_s2_pool, _ = filter_stage2(data["X"], data["feat_cols"], "stage2_current")
    X_s1_pool = build_stage1_matrix(data["sids"], data["hy"])

    iter47_preds_per_seed = []
    slot_c_preds_per_seed = []
    for seed in SEEDS:
        # iter47 reference
        import lightgbm as lgb
        iter47_preds = np.full(n, np.nan)
        for i in range(n):
            tr = np.arange(n) != i
            s1_tr, s1_te = fit_stage1(X_s1_pool[tr], y[tr], X_s1_pool[i:i+1], alpha=1.0)
            resid_tr = y[tr] - s1_tr
            imp = FoldImputer.fit(X_s2_pool[tr])
            Xt_n = imp.transform(X_s2_pool[tr])
            Xv_n = imp.transform(X_s2_pool[i:i+1])
            nrm = FoldNormalizer.fit(Xt_n)
            Xt_n = nrm.transform(Xt_n)
            Xv_n = nrm.transform(Xv_n)
            # iter47 = top-500 univariate K-best + LGB
            top500 = fold_local_univariate_topk(Xt_n, resid_tr, 500)
            lgb_m = lgb.LGBMRegressor(
                n_estimators=300, num_leaves=15, min_child_samples=5,
                learning_rate=0.05, reg_lambda=0.0, random_state=seed,
                verbosity=-1, n_jobs=1,
            )
            lgb_m.fit(Xt_n[:, top500], resid_tr)
            iter47_preds[i] = s1_te[0] + lgb_m.predict(Xv_n[:, top500])[0]
        iter47_preds_per_seed.append(iter47_preds)
        print(f"  seed {seed}: iter47 CCC = {ccc(y, iter47_preds):.4f}")

        # Slot C
        slot_c_preds = slot_c_loocv(data, seed)
        slot_c_preds_per_seed.append(slot_c_preds)
        print(f"  seed {seed}: Slot C CCC = {ccc(y, slot_c_preds):.4f}")

    iter47_mean = np.mean(iter47_preds_per_seed, axis=0)
    slot_c_mean = np.mean(slot_c_preds_per_seed, axis=0)
    iter47_seed_cccs = [float(ccc(y, p)) for p in iter47_preds_per_seed]
    slot_c_seed_cccs = [float(ccc(y, p)) for p in slot_c_preds_per_seed]

    iter47_ccc = float(ccc(y, iter47_mean))
    slot_c_ccc = float(ccc(y, slot_c_mean))
    delta_ccc = slot_c_ccc - iter47_ccc
    delta_mae = float(np.mean(np.abs(y - slot_c_mean)) - np.mean(np.abs(y - iter47_mean)))

    print(f"\n[Slot C] iter47 CCC={iter47_ccc:.4f}, seed_std={np.std(iter47_seed_cccs):.4f}")
    print(f"[Slot C] Slot C CCC={slot_c_ccc:.4f}, seed_std={np.std(slot_c_seed_cccs):.4f}")
    print(f"[Slot C] Δ: CCC={delta_ccc:+.4f}, MAE={delta_mae:+.4f}")

    # Paired-bootstrap
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    deltas_boot = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = rng.choice(n, size=n, replace=True)
        d = float(ccc(y[idx], slot_c_mean[idx]) - ccc(y[idx], iter47_mean[idx]))
        deltas_boot[b] = d
    boot_ci = (float(np.percentile(deltas_boot, 2.5)),
               float(np.percentile(deltas_boot, 97.5)))
    frac_pos = float((deltas_boot > 0).mean())
    print(f"[Slot C] Bootstrap: median={np.median(deltas_boot):+.4f}, "
          f"CI=[{boot_ci[0]:+.4f}, {boot_ci[1]:+.4f}], frac>0={frac_pos:.4f}")

    LIFETIME_FWER = 8
    bonf_gate_lifetime = 1.0 - 0.05 / LIFETIME_FWER
    if frac_pos >= bonf_gate_lifetime and delta_ccc >= 0.025:
        verdict = "PASS_LIFETIME_BONFERRONI"
    elif frac_pos >= 0.95 and delta_ccc >= 0.025:
        verdict = "PASS_UNCORRECTED_FAILS_FWER"
    elif frac_pos >= 0.95:
        verdict = "PASS_UNCORRECTED_DELTA_BELOW_MCID"
    else:
        verdict = "FAIL"

    out = {
        "name": "lockbox_t3_slotC_sparse_pairwise",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "session": "2026-05-15-PM-extended",
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_master.json",
        "null_mode": null_mode or "real",
        "cohort": "drop_allmissing_validrange",
        "n": n,
        "seeds": SEEDS,
        "n_top_univariate": N_TOP_UNIVARIATE,
        "n_top_pairwise_base": N_TOP_PAIRWISE_BASE,
        "n_top_pairwise_selected": N_TOP_PAIRWISE_SELECTED,
        "gb_params": GB_PARAMS,
        "stage1": "H&Y + cv_yrs + cv_sex + cv_dbs Ridge alpha=1.0",
        "stage2": "30 univariate + 50 pairwise products from top-15 base, sklearn GB",
        "baseline_iter47": {
            "ccc": round(iter47_ccc, 4),
            "per_seed": [round(c, 4) for c in iter47_seed_cccs],
            "seed_std": round(float(np.std(iter47_seed_cccs)), 4),
        },
        "slot_c_metrics": {
            "ccc": round(slot_c_ccc, 4),
            "per_seed": [round(c, 4) for c in slot_c_seed_cccs],
            "seed_std": round(float(np.std(slot_c_seed_cccs)), 4),
        },
        "delta": {
            "ccc": round(delta_ccc, 4),
            "mae": round(delta_mae, 4),
        },
        "bootstrap": {
            "n_boot": N_BOOTSTRAP,
            "median_delta": round(float(np.median(deltas_boot)), 4),
            "ci95_lower": round(boot_ci[0], 4),
            "ci95_upper": round(boot_ci[1], 4),
            "frac_positive": round(frac_pos, 4),
        },
        "gates": {
            "lifetime_n8_bonferroni_gate": round(bonf_gate_lifetime, 5),
            "mcid_delta_ccc": 0.025,
        },
        "verdict": verdict,
    }
    ts = out["created_at_utc"]
    suffix = f"_{null_mode}" if null_mode else ""
    path = Path(f"results/lockbox_t3_slotC_sparse_pairwise_{ts}{suffix}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[Slot C] Verdict: {verdict}")
    print(f"[Slot C] Wrote {path}")


if __name__ == "__main__":
    null_mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        null_mode = sys.argv[1].split("=", 1)[1]
    main(null_mode=null_mode)
