"""Iter 2 — T3 modeling experiments. Self-contained.

Variants (run as `--variant <name>`):
  per_item_sum         — train per-item LGB, sum predictions = T3 prediction
  per_item_weighted    — same but weight residuals by inverse-MSE (item-importance)
  item_stack_ridge     — per-item LGB OOF preds → Ridge meta on T3 (Phase 6 style)
  item_stack_lgb       — per-item LGB OOF preds → LGB meta on T3
  subscore_shrink      — predict T1 (best pipeline) per fold, shrinkage map T1_pred → T3
  subscore_shrink_aug  — subscore_shrink + non-T1 items prediction (best of both)
  cqr_quantile         — LGB quantile objective for [0.1, 0.5, 0.9]
  conformal_residual   — standard LGB + conformal residual quantiles per fold
  ipw_site             — logistic propensity for site → LGB sample_weight
  kendall_mtl          — homoscedastic MTL with learnable σ_i (NN, small)
  normative_pca        — train PCA on HC features, use reconstruction error of PD as feature
  base_lgb             — control: same params, direct T3 LGB

Output: results/iter2_<variant>_t3_5split.json with full metrics + pred_dispersion.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 6)))
SEEDS = [42, 1337, 7]

V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
PER_ITEM_CACHE = RESULTS_DIR / "per_item_scores.json"

T1_ITEMS = [9, 10, 11, 12, 13, 14]
T3_ALL_ITEMS = list(range(1, 19))
NON_T1_ITEMS = [i for i in T3_ALL_ITEMS if i not in T1_ITEMS]
V2_EXCLUDED_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")

LGB_DEFAULTS = dict(
    n_estimators=500, learning_rate=0.05, num_leaves=15, max_depth=-1,
    min_data_in_leaf=10, reg_alpha=0.1, reg_lambda=0.3,
    feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
    n_jobs=N_CORES, verbosity=-1,
)


def site_of(sid: str) -> str:
    return "NLS" if sid.startswith("NLS") else ("WPD" if sid.startswith("WPD") else "OTHER")


def is_pd(sid: str) -> bool:
    s = sid.upper()
    return s.startswith("NLS") or s.startswith("WPD")


def is_hc(sid: str) -> bool:
    return not is_pd(sid)


def load_per_item_scores() -> dict:
    with open(PER_ITEM_CACHE) as f:
        raw = json.load(f)
    out = {}
    for sid, scores in raw.items():
        per_item = {}
        for k, v in scores.items():
            if k.startswith("("):
                continue
            try:
                ki = int(k)
                if 1 <= ki <= 18:
                    per_item[ki] = float(v)
            except ValueError:
                continue
        out[sid] = per_item
    return out


def load_data(include_hc: bool = False):
    """Load v2 features + per-item targets + T3, optionally including HC."""
    df = pd.read_csv(V2_FEATURES)
    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    feat_cols = [c for c in df.columns
                 if c not in excluded and not any(c.startswith(p) for p in V2_EXCLUDED_PREFIXES)]
    pis = load_per_item_scores()
    rows = []; sids = []; feats = []
    items_arr = {i: [] for i in T3_ALL_ITEMS}
    t3_arr = []
    for _, r in df.iterrows():
        sid = r["sid"]
        if is_pd(sid):
            if sid not in pis:
                continue
            items = pis[sid]
            if not all(i in items for i in T3_ALL_ITEMS):
                continue
            for i in T3_ALL_ITEMS:
                items_arr[i].append(items[i])
            t3_arr.append(float(r["updrs3"]))
            sids.append(sid)
            feats.append(r[feat_cols].to_numpy(dtype=np.float64))
        elif include_hc:
            for i in T3_ALL_ITEMS:
                items_arr[i].append(0.0)  # HC = healthy = 0
            t3_arr.append(0.0)
            sids.append(sid)
            feats.append(r[feat_cols].to_numpy(dtype=np.float64))
    return (
        np.array(sids), np.vstack(feats), feat_cols,
        np.array(t3_arr, dtype=np.float64),
        {i: np.array(items_arr[i], dtype=np.float64) for i in T3_ALL_ITEMS},
    )


# ── Fold-local helpers ───────────────────────────────────────────────────────


def impute_fold(X_tr, X_te):
    med = np.nanmedian(X_tr, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    return (np.where(np.isnan(X_tr), med, X_tr),
            np.where(np.isnan(X_te), med, X_te))


def feature_select_fold(X_tr, y_tr, X_te, k=500, seed=42):
    """Per-fold importance-based selection."""
    if X_tr.shape[1] <= k:
        return X_tr, X_te, np.arange(X_tr.shape[1])
    import lightgbm as lgb
    sel = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.1, num_leaves=15,
                            min_data_in_leaf=5, n_jobs=N_CORES, random_state=seed, verbosity=-1)
    sel.fit(X_tr, y_tr)
    imp = sel.feature_importances_
    idx = np.argsort(imp)[::-1][:k]
    return X_tr[:, idx], X_te[:, idx], idx


def train_lgb(X_tr, y_tr, X_te, seed: int, **kw):
    import lightgbm as lgb
    params = {**LGB_DEFAULTS, "random_state": seed, **kw}
    model = lgb.LGBMRegressor(**params)
    model.fit(X_tr, y_tr)
    return model.predict(X_te)


def kfold_split(n: int, n_splits=5, seed=42):
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    return list(kf.split(np.arange(n)))


# ── 5-null gate (compact) ────────────────────────────────────────────────────


def run_null_gate_lgb(X_pd, y_pd, splits_seed=42, k_features=200):
    """Quick 3-null-gate (subset of 5) for screening.

    Returns dict with scrambled_label_ccc and canary_ccc."""
    n = len(y_pd)
    splits = kfold_split(n, n_splits=5, seed=splits_seed)
    # 1. Scrambled labels
    rng = np.random.default_rng(0)
    y_shuf = rng.permutation(y_pd)
    preds_shuf = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_pd[tr], X_pd[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_shuf[tr], Xte, k=k_features, seed=splits_seed)
        preds_shuf[te] = train_lgb(Xtr, y_shuf[tr], Xte, splits_seed, n_estimators=200)
    scrambled_ccc = ccc_fn(y_pd, preds_shuf)

    # 2. Canary feature in test only — train sees random noise, test sees y as feature
    X_aug = np.column_stack([X_pd, np.zeros(n)])
    canary_col = X_aug.shape[1] - 1
    preds_can = np.zeros(n)
    for tr, te in splits:
        Xa = X_aug.copy()
        Xa[te, canary_col] = y_pd[te]  # canary is test-set y; should NOT help
        Xa[tr, canary_col] = rng.standard_normal(len(tr))
        Xtr, Xte = impute_fold(Xa[tr], Xa[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_pd[tr], Xte, k=k_features, seed=splits_seed)
        preds_can[te] = train_lgb(Xtr, y_pd[tr], Xte, splits_seed, n_estimators=200)
    canary_ccc = ccc_fn(y_pd, preds_can)

    return {
        "scrambled_label_ccc": float(scrambled_ccc),
        "canary_test_ccc": float(canary_ccc),
        "scrambled_pass": bool(abs(scrambled_ccc) < 0.10),
        "canary_pass": bool(abs(canary_ccc) < 0.40),  # canary should still give ~baseline since y is in test
    }


# ── VARIANTS ─────────────────────────────────────────────────────────────────


def variant_base_lgb(sids, X, y_t3, items, seed=42):
    """Control: direct T3 LGB."""
    n = len(sids)
    preds = np.zeros(n)
    splits = kfold_split(n, 5, seed=seed)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        preds[te] = train_lgb(Xtr, y_t3[tr], Xte, seed)
    return preds


def variant_per_item_sum(sids, X, y_t3, items, seed=42):
    """Train per-item LGB; predict each item; sum."""
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    per_item_preds = {}
    for item in T3_ALL_ITEMS:
        y_item = items[item]
        if y_item.std() < 1e-6:
            continue
        item_preds = np.zeros(n)
        for tr, te in splits:
            Xtr, Xte = impute_fold(X[tr], X[te])
            Xtr, Xte, _ = feature_select_fold(Xtr, y_item[tr], Xte, k=500, seed=seed)
            item_preds[te] = train_lgb(Xtr, y_item[tr], Xte, seed)
        per_item_preds[item] = item_preds
        preds += item_preds
    return preds, per_item_preds


def variant_per_item_weighted(sids, X, y_t3, items, seed=42):
    """Per-item sum but weighted by per-item inductive predictability."""
    preds_sum, per_item_preds = variant_per_item_sum(sids, X, y_t3, items, seed=seed)
    # Compute per-item CCC; downweight items with low CCC
    weights = {}
    for item, p in per_item_preds.items():
        c = max(0.05, ccc_fn(items[item], p))  # floor at 0.05
        weights[item] = c
    total_w = sum(weights.values())
    norm = {k: v / total_w for k, v in weights.items()}
    # Reweighted sum: predict T3 by weighted combination of per-item × actual_item_mean (prior)
    n = len(sids)
    preds = np.zeros(n)
    # Better approach: for each subject, pred_T3 = sum_i [w_i * pred_item_i + (1-w_i) * mean_item_i_train]
    # But we need per-fold to be inductive. Simpler: weight by w_i (less reliable items contribute less)
    # then add (1-w_i) * train mean of that item per fold
    splits = kfold_split(n, 5, seed=seed)
    item_arr_list = list(per_item_preds.keys())
    for tr, te in splits:
        for item in item_arr_list:
            mean_train = items[item][tr].mean()
            w = weights[item]
            # blend: w * pred + (1-w) * mean
            preds[te] += w * per_item_preds[item][te] + (1 - w) * mean_train
    return preds


def variant_item_stack_ridge(sids, X, y_t3, items, seed=42):
    """Per-item LGB OOF → Ridge meta on T3."""
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    # Get per-item OOF predictions
    _, per_item_preds = variant_per_item_sum(sids, X, y_t3, items, seed=seed)
    # Stack per-item OOF as features
    item_keys = sorted(per_item_preds.keys())
    Z = np.column_stack([per_item_preds[k] for k in item_keys])
    # Ridge meta inductively
    preds = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0)
        ridge.fit(Z[tr], y_t3[tr])
        preds[te] = ridge.predict(Z[te])
    return preds


def variant_item_stack_lgb(sids, X, y_t3, items, seed=42):
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    _, per_item_preds = variant_per_item_sum(sids, X, y_t3, items, seed=seed)
    item_keys = sorted(per_item_preds.keys())
    Z = np.column_stack([per_item_preds[k] for k in item_keys])
    preds = np.zeros(n)
    for tr, te in splits:
        preds[te] = train_lgb(Z[tr], y_t3[tr], Z[te], seed,
                              n_estimators=200, num_leaves=8, min_data_in_leaf=5)
    return preds


def variant_subscore_shrink(sids, X, y_t3, items, seed=42):
    """Predict T1 (sum items 9-14) per fold, then learn shrinkage T1_pred → T3 inductively."""
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    y_t1 = sum(items[i] for i in T1_ITEMS)
    # Per-fold: train T1 LGB on fold, predict T1 on test; train shrinkage T1_train → T3_train; apply to T1_test
    preds = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t1[tr], Xte, k=500, seed=seed)
        # Predict T1 on both train (CV-internal) and test
        # For train shrinkage map: need OOF T1 preds on train. Use inner 5-fold.
        t1_tr_oof = np.zeros(len(tr))
        inner_splits = kfold_split(len(tr), 5, seed=seed + 1)
        for itr, ite in inner_splits:
            Xitr, Xite = impute_fold(Xtr[itr], Xtr[ite])
            t1_tr_oof[ite] = train_lgb(Xitr, y_t1[tr][itr], Xite, seed,
                                         n_estimators=300, learning_rate=0.05)
        t1_te = train_lgb(Xtr, y_t1[tr], Xte, seed)
        # Shrinkage: linear T1_oof → T3_train
        coef = np.polyfit(t1_tr_oof, y_t3[tr], 1)
        preds[te] = np.polyval(coef, t1_te)
    return preds


def variant_subscore_shrink_aug(sids, X, y_t3, items, seed=42):
    """Subscore shrink + augmented per-item LGB residual on non-T1 items."""
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    y_t1 = sum(items[i] for i in T1_ITEMS)
    y_residual = y_t3 - y_t1  # this is the non-T1 sum
    preds = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        # T1_pred for test
        t1_te_pred = train_lgb(Xtr, y_t1[tr], Xte, seed)
        # Residual prediction
        res_te_pred = train_lgb(Xtr, y_residual[tr], Xte, seed)
        # Combine
        preds[te] = t1_te_pred + res_te_pred
    return preds


def variant_cqr_quantile(sids, X, y_t3, items, seed=42):
    """LGB quantile objective for median; conformal residuals for PIs."""
    import lightgbm as lgb
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    pred_lo = np.zeros(n); pred_hi = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        models = {}
        for q, name in [(0.5, "median"), (0.1, "lo"), (0.9, "hi")]:
            params = {**LGB_DEFAULTS, "objective": "quantile", "alpha": q,
                      "random_state": seed, "metric": "quantile"}
            m = lgb.LGBMRegressor(**params)
            m.fit(Xtr, y_t3[tr])
            models[name] = m.predict(Xte)
        preds[te] = models["median"]
        pred_lo[te] = models["lo"]
        pred_hi[te] = models["hi"]
    return preds, {"pred_lo_q0.1": pred_lo, "pred_hi_q0.9": pred_hi}


def variant_ipw_site(sids, X, y_t3, items, seed=42):
    """Logistic site propensity → LGB sample weight."""
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    sites = np.array([1 if site_of(s) == "NLS" else 0 for s in sids])  # NLS=1
    preds = np.zeros(n)
    # Per-fold: fit logistic on (X_tr, sites_tr), compute propensity, then IPW weights
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        # Logistic on training fold, predict propensity
        # Standardize for stability
        mu = Xtr.mean(axis=0); sigma = Xtr.std(axis=0); sigma[sigma < 1e-9] = 1.0
        Xtr_s = (Xtr - mu) / sigma
        try:
            lr = LogisticRegression(max_iter=500, C=0.1, n_jobs=1)
            lr.fit(Xtr_s, sites[tr])
            propensity = lr.predict_proba(Xtr_s)[:, 1]
            # IPW = 1 / P(observed_site)
            ipw_w = np.where(sites[tr] == 1, 1.0 / np.clip(propensity, 0.05, 0.95),
                             1.0 / np.clip(1 - propensity, 0.05, 0.95))
            ipw_w = ipw_w / ipw_w.mean()  # normalize
        except Exception:
            ipw_w = np.ones(len(tr))
        # LGB with sample_weight
        import lightgbm as lgb
        params = {**LGB_DEFAULTS, "random_state": seed}
        m = lgb.LGBMRegressor(**params)
        m.fit(Xtr, y_t3[tr], sample_weight=ipw_w)
        preds[te] = m.predict(Xte)
    return preds


def variant_kendall_mtl(sids, X, y_t3, items, seed=42):
    """Homoscedastic MTL with learnable σ_i — small NN, runs on CPU.

    Predicts T3 + 5 most-predictable items as auxiliary tasks; loss weights
    are learnable σ_i (Kendall et al. 2018)."""
    try:
        import torch
        from torch import nn, optim
    except ImportError:
        return None  # skip if torch missing
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    # Aux items: items with strongest standalone signal (12, 10, 14, 9, 11)
    aux_items = [12, 10, 14, 9, 11]
    preds = np.zeros(n)
    for tr, te in splits:
        Xtr_raw, Xte_raw = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr_raw, y_t3[tr], Xte_raw, k=200, seed=seed)
        mu = Xtr.mean(axis=0); sigma = Xtr.std(axis=0); sigma[sigma < 1e-9] = 1.0
        Xtr_s = (Xtr - mu) / sigma
        Xte_s = (Xte - mu) / sigma
        # Build target tensor: [T3, aux1, ..., auxK]
        Y_tr = np.column_stack([y_t3[tr]] + [items[i][tr] for i in aux_items])
        Y_tr_mean = Y_tr.mean(axis=0); Y_tr_std = Y_tr.std(axis=0); Y_tr_std[Y_tr_std < 1e-9] = 1.0
        Y_tr_s = (Y_tr - Y_tr_mean) / Y_tr_std
        torch.manual_seed(seed)
        Xt = torch.from_numpy(Xtr_s.astype(np.float32))
        Yt = torch.from_numpy(Y_tr_s.astype(np.float32))
        d_in = Xt.shape[1]; d_out = Yt.shape[1]
        net = nn.Sequential(
            nn.Linear(d_in, 64), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(64, 32), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(32, d_out),
        )
        log_sigmas = torch.zeros(d_out, requires_grad=True)
        opt = optim.Adam(list(net.parameters()) + [log_sigmas], lr=1e-3, weight_decay=1e-4)
        for epoch in range(150):
            opt.zero_grad()
            pred = net(Xt)
            mse = ((pred - Yt) ** 2).mean(axis=0)
            sigmas2 = torch.exp(2 * log_sigmas)
            loss = (mse / (2 * sigmas2) + log_sigmas).sum()
            loss.backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            Xe = torch.from_numpy(Xte_s.astype(np.float32))
            pred_e = net(Xe).numpy()
        # Unstandardize T3 (column 0)
        preds[te] = pred_e[:, 0] * Y_tr_std[0] + Y_tr_mean[0]
    return preds


def variant_normative_pca(sids_pd, X_pd, y_t3, items, seed=42, X_hc=None):
    """Train PCA on HC features, use reconstruction error of PD as auxiliary feature.

    NOTE: HC are loaded inductively per-fold (only HC + train PD seen, not test PD).
    For simplicity here, since HC are out-of-sample for PD CV, we fit PCA on HC GLOBALLY
    once (no leakage since HC don't overlap with PD test fold).
    """
    if X_hc is None or len(X_hc) == 0:
        return None
    from sklearn.decomposition import PCA
    n = len(sids_pd)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    # PCA on HC (no PD test contamination — HC are disjoint subjects)
    X_hc_imp = np.where(np.isnan(X_hc), 0.0, X_hc)
    mu_hc = X_hc_imp.mean(axis=0); sigma_hc = X_hc_imp.std(axis=0); sigma_hc[sigma_hc < 1e-9] = 1.0
    X_hc_s = (X_hc_imp - mu_hc) / sigma_hc
    # Use top features only
    nv = min(200, X_hc_s.shape[1])
    var_hc = X_hc_s.var(axis=0)
    top_idx = np.argsort(var_hc)[::-1][:nv]
    pca = PCA(n_components=20, random_state=seed)
    pca.fit(X_hc_s[:, top_idx])
    # For each PD: compute reconstruction error
    X_pd_imp = np.where(np.isnan(X_pd), 0.0, X_pd)
    X_pd_s = (X_pd_imp - mu_hc) / sigma_hc
    X_pd_top = X_pd_s[:, top_idx]
    Z_pd = pca.transform(X_pd_top)
    X_pd_recon = pca.inverse_transform(Z_pd)
    recon_err = np.linalg.norm(X_pd_top - X_pd_recon, axis=1)
    # Augment PD features with recon_err + Z (latent code)
    extra = np.column_stack([recon_err.reshape(-1, 1), Z_pd])  # 21 features
    X_pd_aug = np.column_stack([X_pd, extra])
    # Run base LGB on augmented features
    return variant_base_lgb(sids_pd, X_pd_aug, y_t3, items, seed=seed)


VARIANTS = {
    "base_lgb":             variant_base_lgb,
    "per_item_sum":         variant_per_item_sum,
    "per_item_weighted":    variant_per_item_weighted,
    "item_stack_ridge":     variant_item_stack_ridge,
    "item_stack_lgb":       variant_item_stack_lgb,
    "subscore_shrink":      variant_subscore_shrink,
    "subscore_shrink_aug":  variant_subscore_shrink_aug,
    "cqr_quantile":         variant_cqr_quantile,
    "ipw_site":             variant_ipw_site,
    "kendall_mtl":          variant_kendall_mtl,
    "normative_pca":        variant_normative_pca,
}


def run_variant(name, n_seeds=3):
    print(f"=== {name} ({n_seeds} seeds) ===")
    use_hc = name in ("normative_pca",)
    sids, X, fc, y_t3, items = load_data(include_hc=False)
    X_hc = None
    if use_hc:
        sids_all, X_all, _, _, _ = load_data(include_hc=True)
        is_hc_mask = np.array([is_hc(s) for s in sids_all])
        X_hc = X_all[is_hc_mask]
        print(f"  loaded {len(X_hc)} HC subjects for normative PCA")

    fn = VARIANTS[name]
    all_preds = []
    extras = None
    for seed_idx, seed in enumerate(SEEDS[:n_seeds]):
        t0 = time.time()
        if name == "normative_pca":
            preds = fn(sids, X, y_t3, items, seed=seed, X_hc=X_hc)
        elif name in ("per_item_sum", "cqr_quantile"):
            out = fn(sids, X, y_t3, items, seed=seed)
            if isinstance(out, tuple):
                preds, extras = out[0], out[1]
            else:
                preds = out
        else:
            preds = fn(sids, X, y_t3, items, seed=seed)
        if preds is None:
            print(f"  seed {seed}: skipped (None returned)")
            continue
        c = ccc_fn(y_t3, preds)
        m = mae_fn(y_t3, preds)
        r = pearson_r(y_t3, preds)
        print(f"  seed {seed}: CCC={c:.4f}, MAE={m:.3f}, r={r:.3f}, took {time.time()-t0:.1f}s")
        all_preds.append((seed, preds))

    if not all_preds:
        return None

    # Aggregate metrics across seeds (mean of per-seed metrics)
    seed_results = []
    for seed, preds in all_preds:
        seed_results.append({
            "seed": seed,
            "ccc": float(ccc_fn(y_t3, preds)),
            "mae": float(mae_fn(y_t3, preds)),
            "r": float(pearson_r(y_t3, preds)),
            "pred_std": float(preds.std()),
            "true_std": float(y_t3.std()),
            "ratio": float(preds.std() / y_t3.std()) if y_t3.std() > 0 else 0,
        })
    cccs = [s["ccc"] for s in seed_results]
    mean_preds = np.mean(np.column_stack([p for _, p in all_preds]), axis=1)
    summary = full_metrics(y_t3, mean_preds, label=name)
    summary.update({
        "variant": name,
        "ccc_mean_across_seeds": float(np.mean(cccs)),
        "ccc_std_across_seeds": float(np.std(cccs)),
        "per_seed": seed_results,
        "n": len(sids),
        "target": "t3",
        "eval_mode": "5split",
    })
    if extras:
        summary["extras_summary"] = {k: {"mean": float(v.mean()), "std": float(v.std())} for k, v in extras.items()}
    out_path = RESULTS_DIR / f"iter2_{name}_t3_5split.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  → wrote {out_path}")
    print(f"  CCC across {len(cccs)} seeds: {np.mean(cccs):.4f} ± {np.std(cccs):.4f}")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variant", default="all")
    p.add_argument("--seeds", type=int, default=3)
    args = p.parse_args()

    if args.variant == "all":
        names = list(VARIANTS.keys())
    else:
        names = [v.strip() for v in args.variant.split(",")]
    for name in names:
        if name not in VARIANTS:
            print(f"UNKNOWN variant: {name}")
            continue
        try:
            run_variant(name, n_seeds=args.seeds)
        except Exception as e:
            import traceback
            traceback.print_exc()
            with open(RESULTS_DIR / f"iter2_{name}_t3_5split.json", "w") as f:
                json.dump({"error": str(e), "variant": name, "tb": traceback.format_exc()}, f, indent=2)


if __name__ == "__main__":
    main()
