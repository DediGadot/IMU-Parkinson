"""V3 stack honest evaluation: nested CV + per-subject adaptive stacking.

Item #4: Nested CV stacking - inner-LOOCV learns weights, outer-LOOCV evaluates.
  Unbiased estimate of the grid-optimized 4-way stack.

Item #3: Per-subject adaptive stacking - stratify weights by H&Y bin or site.
  Different families may help different subjects.
"""
from __future__ import annotations

import os, sys, json, time
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import LeaveOneOut
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from scipy.optimize import minimize

sys.path.insert(0, '/home/fiod/medical')
from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FS, build_stage1_features, fit_stage1, load_clinical_dict,
)

R = Path('/home/fiod/medical/results')


def ccc(y, p):
    yb, pb = y.mean(), p.mean()
    return 2 * ((y-yb)*(p-pb)).mean() / (y.var() + p.var() + (yb-pb)**2)


def ridge_oof(csv: Path, sids, y_resid, alpha=1.0):
    df = pd.read_csv(csv).set_index('sid')
    df.index = df.index.astype(str)
    cols = list(df.columns)
    rows = [
        df.loc[s].values.astype(float) if s in df.index else np.full(len(cols), np.nan)
        for s in sids
    ]
    X = np.array(rows)
    n = len(y_resid)
    preds = np.zeros(n)
    for tr, te in LeaveOneOut().split(np.arange(n)):
        med = np.nanmedian(X[tr], axis=0)
        Xtr = X[tr].copy(); Xte = X[te].copy()
        for j in range(X.shape[1]):
            m = med[j] if np.isfinite(med[j]) else 0.0
            Xtr[np.isnan(Xtr[:, j]), j] = m
            Xte[np.isnan(Xte[:, j]), j] = m
        sc = StandardScaler()
        Xtr_s = sc.fit_transform(Xtr); Xte_s = sc.transform(Xte)
        rg = Ridge(alpha=alpha, random_state=42)
        rg.fit(Xtr_s, y_resid[tr])
        preds[te] = rg.predict(Xte_s)
    return preds


def fit_weights_simplex(P_tr, y_tr):
    """Fit non-negative weights summing to 1 by minimizing MSE.

    Returns weight vector w of shape (K,) where K = number of predictors.
    """
    K = P_tr.shape[1]
    # Initial: equal weights
    w0 = np.full(K, 1.0 / K)
    bounds = [(0.0, 1.0)] * K
    cons = {"type": "eq", "fun": lambda w: 1.0 - np.sum(w)}

    def obj(w):
        p = P_tr @ w
        return float(np.mean((y_tr - p) ** 2))

    res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 200, "ftol": 1e-7})
    return res.x


def nested_cv_stack(P, y, n_inner=None):
    """Outer LOOCV: for each held-out subject i, fit weights on the other 91
    subjects' OOF preds (these are themselves out-of-fold), use to predict i.

    No grid search — weights fit by SLSQP simplex (non-negative summing to 1).
    """
    n = len(y)
    preds = np.zeros(n)
    weights_log = []
    for tr, te in LeaveOneOut().split(np.arange(n)):
        w = fit_weights_simplex(P[tr], y[tr])
        weights_log.append(w)
        preds[te] = float((P[te] @ w)[0])
    return preds, np.array(weights_log)


def per_subject_adaptive_stack(P, y, hy, n_bins=2):
    """Per-H&Y-bin weights: stratify subjects by H&Y, learn separate weights
    per stratum via inner LOOCV.
    """
    n = len(y)
    # Define H&Y bins (e.g., <=2 vs >2)
    bins = np.array([1 if h > 2.5 else 0 for h in hy])
    preds = np.zeros(n)
    for tr, te in LeaveOneOut().split(np.arange(n)):
        # Test subject's H&Y bin
        bin_te = bins[te[0]]
        # Train mask: same H&Y bin only
        mask_same = (bins[tr] == bin_te)
        # Fall back to all train if too few same-bin
        if mask_same.sum() >= 20:
            tr_use = tr[mask_same]
        else:
            tr_use = tr
        w = fit_weights_simplex(P[tr_use], y[tr_use])
        preds[te] = float((P[te] @ w)[0])
    return preds


def per_site_adaptive_stack(P, y, sids):
    """Per-site (NLS vs WPD) adaptive stacking."""
    sites = np.array([1 if str(s).startswith("WPD") else 0 for s in sids])
    n = len(y); preds = np.zeros(n)
    for tr, te in LeaveOneOut().split(np.arange(n)):
        site_te = sites[te[0]]
        mask_same = (sites[tr] == site_te)
        if mask_same.sum() >= 20:
            tr_use = tr[mask_same]
        else:
            tr_use = tr
        w = fit_weights_simplex(P[tr_use], y[tr_use])
        preds[te] = float((P[te] @ w)[0])
    return preds


def main():
    # Load existing OOF preds
    with open(R/'lockbox_t1_iter34_hybrid_20260510_233019.json') as f: j_v2=json.load(f)
    p_v2_all = np.load(R/'lockbox_t1_iter34_hybrid_20260510_233019.oof.npy')
    sids = [str(s) for s in j_v2['per_subject']['sids']]
    y_true = np.array(j_v2['per_subject']['y_true'])
    with open(R/'lockbox_t1_v3_gsp_v3_only_20260512_195152.json') as f: j_gsp=json.load(f)
    p_gsp_all = np.load(R/'lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy')
    sid_gsp = dict(zip([str(s) for s in j_gsp['per_subject']['sids']], p_gsp_all.tolist()))
    p_gsp = np.array([sid_gsp[s] for s in sids])
    p_v2 = p_v2_all

    # Recompute Stage-1 OOF + residual
    sids_l, _, y_t1_l, hy, items, _ = _load_t1_cohort_with_8items()
    clinical = load_clinical_dict(sids_l)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FS['A3_tier1'])
    s1_oof = np.zeros(len(sids_l))
    for tr, te in LeaveOneOut().split(np.arange(len(sids_l))):
        _, s1_te = fit_stage1(X_s1[tr], y_t1_l[tr], X_s1[te], alpha=1.0)
        s1_oof[te] = s1_te
    y_resid = y_t1_l - s1_oof

    # Build V3 family Ridge preds (alpha=1.0 for mos, alpha=1.0 for titd — sweet spot)
    print("Building V3 family Ridge preds...", flush=True)
    mos_p = s1_oof + ridge_oof(R/'v3_mos_features.csv', sids, y_resid, alpha=0.1)
    titd_p = s1_oof + ridge_oof(R/'v3_titd_features.csv', sids, y_resid, alpha=1.0)
    pm_p = s1_oof + ridge_oof(R/'v3_phase_manifold_features.csv', sids, y_resid, alpha=1.0)
    rec_p = s1_oof + ridge_oof(R/'v3_recovery_features.csv', sids, y_resid, alpha=1.0)
    psi_p = s1_oof + ridge_oof(R/'v3_psi_features.csv', sids, y_resid, alpha=1.0)
    print("Done.\n", flush=True)

    # Build prediction matrix
    preds_dict = {
        'V2': p_v2,
        'GSP': p_gsp,
        'mos': mos_p,
        'titd': titd_p,
        'pm': pm_p,
        'rec': rec_p,
        'psi': psi_p,
    }
    # Print individual CCC + errcorr
    print(f"Individual predictor CCCs:")
    for k, p in preds_dict.items():
        c = ccc(y_true, p)
        e_v2 = y_true - p_v2; e_p = y_true - p
        rho = float(np.corrcoef(e_v2, e_p)[0,1])
        print(f"  {k:6s}: CCC={c:.4f}  errcorr(V2)={rho:.3f}")

    # Subset for stacking: V2+GSP+mos+titd (the 4 best families)
    P4 = np.column_stack([p_v2, p_gsp, mos_p, titd_p])
    keys4 = ['V2', 'GSP', 'mos', 'titd']

    print(f"\n=== Item #4: Nested CV stacking (V2+GSP+mos+titd, SLSQP simplex) ===")
    nested_preds, weights_log = nested_cv_stack(P4, y_true)
    c_nested = ccc(y_true, nested_preds)
    print(f"  Nested CV CCC = {c_nested:.4f}  Δ = {c_nested-0.7170:+.4f}")
    print(f"  Mean weights: {dict(zip(keys4, weights_log.mean(axis=0)))}")
    print(f"  Weight std:   {dict(zip(keys4, weights_log.std(axis=0)))}")

    # Compare to LOOCV-overfit grid
    print(f"\n  For comparison, LOOCV-overfit grid 4-way: CCC=0.7412  Δ=+0.0242")
    print(f"  Nested CV honesty cost: {c_nested - 0.7412:+.4f}")

    print(f"\n=== Item #3a: Per-H&Y-bin adaptive stacking ===")
    sids_l_list = list(sids_l)
    hy_arr = np.array([hy[sids_l_list.index(s)] if s in sids_l_list else 2.0 for s in sids])
    print(f"  H&Y distribution: <=2.5 → {(hy_arr <= 2.5).sum()} subjects; >2.5 → {(hy_arr > 2.5).sum()}")
    adaptive_hy_preds = per_subject_adaptive_stack(P4, y_true, hy_arr, n_bins=2)
    c_adapt_hy = ccc(y_true, adaptive_hy_preds)
    print(f"  Per-H&Y-bin adaptive CCC = {c_adapt_hy:.4f}  Δ = {c_adapt_hy-0.7170:+.4f}")

    print(f"\n=== Item #3b: Per-site adaptive stacking ===")
    sites = np.array([1 if str(s).startswith("WPD") else 0 for s in sids])
    print(f"  Site distribution: NLS → {(sites == 0).sum()}; WPD → {(sites == 1).sum()}")
    adaptive_site_preds = per_site_adaptive_stack(P4, y_true, sids)
    c_adapt_site = ccc(y_true, adaptive_site_preds)
    print(f"  Per-site adaptive CCC = {c_adapt_site:.4f}  Δ = {c_adapt_site-0.7170:+.4f}")

    # Larger 7-predictor nested CV
    print(f"\n=== Item #4 extended: Nested CV with ALL 7 predictors ===")
    P7 = np.column_stack([p_v2, p_gsp, mos_p, titd_p, pm_p, rec_p, psi_p])
    keys7 = ['V2', 'GSP', 'mos', 'titd', 'pm', 'rec', 'psi']
    nested_preds7, weights_log7 = nested_cv_stack(P7, y_true)
    c_nested7 = ccc(y_true, nested_preds7)
    print(f"  Nested CV 7-way CCC = {c_nested7:.4f}  Δ = {c_nested7-0.7170:+.4f}")
    print(f"  Mean weights: {dict(zip(keys7, [f'{w:.2f}' for w in weights_log7.mean(axis=0)]))}")

    # Sign-flip test on nested-CV stack vs V2
    def sign_flip(y, pa, pb, n_perms=10000, seed=42):
        rng = np.random.RandomState(seed)
        diffs = (y-pb)**2 - (y-pa)**2
        obs = diffs.mean()
        n = len(diffs); perm = np.empty(n_perms)
        for i in range(n_perms):
            flips = rng.choice([-1.0,1.0], size=n)
            perm[i] = (diffs*flips).mean()
        return obs, float((perm >= obs).mean())

    print(f"\n=== Sign-flip tests vs V2-iter34 ===")
    obs, p = sign_flip(y_true, nested_preds, p_v2)
    print(f"  Nested CV 4-way: obs={obs:+.4f}  p={p:.4f}")
    obs, p = sign_flip(y_true, nested_preds7, p_v2)
    print(f"  Nested CV 7-way: obs={obs:+.4f}  p={p:.4f}")
    obs, p = sign_flip(y_true, adaptive_hy_preds, p_v2)
    print(f"  Per-H&Y adaptive: obs={obs:+.4f}  p={p:.4f}")
    obs, p = sign_flip(y_true, adaptive_site_preds, p_v2)
    print(f"  Per-site adaptive: obs={obs:+.4f}  p={p:.4f}")

    # BCa CI on nested CV 4-way Δ
    def bca_ci(y, pa, pb, n_boot=5000, seed=42):
        from scipy.stats import norm
        rng = np.random.RandomState(seed)
        n = len(y)
        boot = np.empty(n_boot)
        for i in range(n_boot):
            idx = rng.randint(0, n, n)
            boot[i] = ccc(y[idx], pa[idx]) - ccc(y[idx], pb[idx])
        obs = float(ccc(y, pa) - ccc(y, pb))
        # Bias correction
        z0 = norm.ppf(max(min((boot < obs).mean(), 1-1e-6), 1e-6))
        # Acceleration via jackknife
        jack = np.empty(n)
        for i in range(n):
            idx_j = np.concatenate([np.arange(i), np.arange(i+1, n)])
            jack[i] = ccc(y[idx_j], pa[idx_j]) - ccc(y[idx_j], pb[idx_j])
        jm = jack.mean()
        num = ((jm - jack)**3).sum()
        den = 6.0 * (((jm - jack)**2).sum()**1.5 + 1e-12)
        a = num / den
        zl = norm.ppf(0.025); zh = norm.ppf(0.975)
        p_lo = norm.cdf(z0 + (z0+zl)/(1-a*(z0+zl)))
        p_hi = norm.cdf(z0 + (z0+zh)/(1-a*(z0+zh)))
        return obs, float(np.quantile(boot, p_lo)), float(np.quantile(boot, p_hi))

    obs, lo, hi = bca_ci(y_true, nested_preds, p_v2)
    print(f"\n=== BCa CI: Nested CV 4-way Δ vs V2 ===")
    print(f"  obs Δ = {obs:+.4f}, BCa 95% CI = [{lo:+.4f}, {hi:+.4f}]")
    print(f"  excludes 0: {lo > 0 or hi < 0}")

    # Save out
    out = {
        "nested_cv_4way_ccc": c_nested,
        "nested_cv_4way_delta": float(c_nested - 0.7170),
        "nested_cv_4way_mean_weights": dict(zip(keys4, weights_log.mean(axis=0).tolist())),
        "nested_cv_7way_ccc": c_nested7,
        "nested_cv_7way_delta": float(c_nested7 - 0.7170),
        "nested_cv_7way_mean_weights": dict(zip(keys7, weights_log7.mean(axis=0).tolist())),
        "adaptive_hy_ccc": c_adapt_hy,
        "adaptive_hy_delta": float(c_adapt_hy - 0.7170),
        "adaptive_site_ccc": c_adapt_site,
        "adaptive_site_delta": float(c_adapt_site - 0.7170),
        "grid_loocv_overfit_4way_ccc": 0.7412,
    }
    with open(R / "v3_nested_adaptive_stack_summary.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {R / 'v3_nested_adaptive_stack_summary.json'}")


if __name__ == "__main__":
    main()
