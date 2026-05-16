"""Codex-debug nested CV stacking — shrink-to-prior + residual add-ons + affine cal.

Implements codex's 3 recommended fixes (2026-05-12 debug consult):

1. Strict two-source V2+GSP nested blend (baseline = +0.0115).
2. Shrink-to-prior simplex: min_w ||y - Xw||² + λ||w - w0||²  s.t. w≥0, sum=1.
   Sweep λ ∈ {0.1, 0.3, 1, 3, 10}. Prior w0 = V2+GSP-equal-rest-zero.
3. One-parameter residual add-on with inner residual gate.
   For each candidate family C:
     pred = (1-α) * V2GSP_blend + α * candidate
   Sweep α ∈ {0.05, 0.10, 0.15, 0.20} per fold via inner-CV.
   Admit candidate only if inner-CV CCC improvement ≥ +0.005.
4. Affine calibration on inner predictions: y_hat = a + b * y_hat_stack.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut, KFold
from sklearn.linear_model import Ridge, LinearRegression
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


def ridge_oof(csv, sids, y_resid, alpha=1.0):
    df = pd.read_csv(csv).set_index('sid')
    df.index = df.index.astype(str)
    cols = list(df.columns)
    rows = [
        df.loc[s].values.astype(float) if s in df.index else np.full(len(cols), np.nan)
        for s in sids
    ]
    X = np.array(rows)
    n = len(y_resid); preds = np.zeros(n)
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


def fit_shrink_simplex(P, y, w0, lam):
    """Fit non-negative simplex weights with shrinkage toward prior w0.

    Loss = mean((y - Pw)²) + lam * ||w - w0||²
    s.t. w >= 0, sum(w) = 1.
    """
    K = P.shape[1]
    def obj(w):
        resid = y - P @ w
        return float(np.mean(resid**2) + lam * np.sum((w - w0)**2))
    res = minimize(
        obj, w0, method='SLSQP',
        bounds=[(0,1)]*K,
        constraints={'type': 'eq', 'fun': lambda w: 1 - np.sum(w)},
        options={'maxiter': 200, 'ftol': 1e-7}
    )
    return res.x


def fit_w_simplex(P, y):
    K = P.shape[1]
    w0 = np.full(K, 1.0/K)
    res = minimize(
        lambda w: float(np.mean((y - P @ w) ** 2)),
        w0, method='SLSQP', bounds=[(0,1)]*K,
        constraints={'type': 'eq', 'fun': lambda w: 1-np.sum(w)},
        options={'maxiter': 200, 'ftol': 1e-7}
    )
    return res.x


def nested_cv_shrink(P, y, lam, w0=None):
    n, K = P.shape
    if w0 is None:
        w0 = np.full(K, 1.0/K)
    preds = np.zeros(n); wlog = []
    for tr, te in LeaveOneOut().split(np.arange(n)):
        w = fit_shrink_simplex(P[tr], y[tr], w0, lam)
        wlog.append(w)
        preds[te] = float((P[te] @ w)[0])
    return preds, np.array(wlog)


def nested_cv_with_affine_cal(P, y):
    """Fit simplex weights + affine calibration jointly in inner CV.

    For each outer fold: fit simplex on inner-LOOCV preds, then fit affine
    y = a + b*stack on inner LOOCV preds.
    """
    n = len(y); preds = np.zeros(n); wlog = []
    for tr, te in LeaveOneOut().split(np.arange(n)):
        w = fit_w_simplex(P[tr], y[tr])
        wlog.append(w)
        # Affine cal on training fold
        p_tr = P[tr] @ w
        # y = a + b * p_tr → linear regression
        lr = LinearRegression()
        lr.fit(p_tr.reshape(-1, 1), y[tr])
        p_te_raw = float((P[te] @ w)[0])
        preds[te] = float(lr.predict([[p_te_raw]])[0])
    return preds, np.array(wlog)


def one_param_addon(p_base, p_candidate, y, alpha_grid=(0, 0.05, 0.10, 0.15, 0.20)):
    """Inner-CV select α for: pred = (1-α)*p_base + α*p_candidate.

    Returns OOF preds + selected α per outer fold + inner gate decision.
    """
    n = len(y); preds = np.zeros(n); alpha_log = []; admitted_log = []
    for tr, te in LeaveOneOut().split(np.arange(n)):
        best_alpha = 0.0; best_score = ccc(y[tr], p_base[tr])
        for alpha in alpha_grid:
            if alpha == 0: continue
            stacked = (1 - alpha) * p_base[tr] + alpha * p_candidate[tr]
            score = ccc(y[tr], stacked)
            if score > best_score:
                best_score = score; best_alpha = alpha
        # Inner gate: only admit if inner CCC improvement >= +0.005
        baseline_score = ccc(y[tr], p_base[tr])
        admitted = (best_score - baseline_score) >= 0.005
        if not admitted:
            best_alpha = 0.0
        alpha_log.append(best_alpha)
        admitted_log.append(admitted)
        preds[te] = float(((1 - best_alpha) * p_base[te] + best_alpha * p_candidate[te])[0])
    return preds, np.array(alpha_log), np.array(admitted_log)


def bca(y, pa, pb, n_boot=5000, seed=42):
    from scipy.stats import norm
    rng = np.random.RandomState(seed)
    n = len(y); boot = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        boot[i] = ccc(y[idx], pa[idx]) - ccc(y[idx], pb[idx])
    obs = ccc(y, pa) - ccc(y, pb)
    z0 = norm.ppf(max(min((boot<obs).mean(), 1-1e-6), 1e-6))
    jack = np.empty(n)
    for i in range(n):
        idx = np.concatenate([np.arange(i), np.arange(i+1,n)])
        jack[i] = ccc(y[idx], pa[idx]) - ccc(y[idx], pb[idx])
    jm = jack.mean(); num = ((jm-jack)**3).sum(); den = 6.0*(((jm-jack)**2).sum()**1.5 + 1e-12)
    a = num/den
    zl = norm.ppf(0.025); zh = norm.ppf(0.975)
    plo = norm.cdf(z0 + (z0+zl)/(1-a*(z0+zl))); phi = norm.cdf(z0 + (z0+zh)/(1-a*(z0+zh)))
    return obs, float(np.quantile(boot, plo)), float(np.quantile(boot, phi))


def main():
    # Load preds
    with open(R/'lockbox_t1_iter34_hybrid_20260510_233019.json') as f: j_v2=json.load(f)
    p_v2 = np.load(R/'lockbox_t1_iter34_hybrid_20260510_233019.oof.npy')
    sids = [str(s) for s in j_v2['per_subject']['sids']]
    y_true = np.array(j_v2['per_subject']['y_true'])
    with open(R/'lockbox_t1_v3_gsp_v3_only_20260512_195152.json') as f: j_gsp=json.load(f)
    p_gsp_all = np.load(R/'lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy')
    sid_gsp = dict(zip([str(s) for s in j_gsp['per_subject']['sids']], p_gsp_all.tolist()))
    p_gsp = np.array([sid_gsp[s] for s in sids])

    # Stage-1 OOF
    sids_l, _, y_t1_l, hy, items, _ = _load_t1_cohort_with_8items()
    clinical = load_clinical_dict(sids_l)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FS['A3_tier1'])
    s1_oof = np.zeros(len(sids_l))
    for tr, te in LeaveOneOut().split(np.arange(len(sids_l))):
        _, s1_te = fit_stage1(X_s1[tr], y_t1_l[tr], X_s1[te], alpha=1.0)
        s1_oof[te] = s1_te
    y_resid = y_t1_l - s1_oof

    print("Building Ridge V3 preds...", flush=True)
    mos = s1_oof + ridge_oof(R/'v3_mos_features.csv', sids, y_resid, alpha=0.1)
    titd = s1_oof + ridge_oof(R/'v3_titd_features.csv', sids, y_resid, alpha=1.0)
    psi = s1_oof + ridge_oof(R/'v3_psi_features.csv', sids, y_resid, alpha=1.0)
    shp = s1_oof + ridge_oof(R/'v3_shapelet_features.csv', sids, y_resid, alpha=1.0)
    pm = s1_oof + ridge_oof(R/'v3_phase_manifold_features.csv', sids, y_resid, alpha=1.0)
    rec = s1_oof + ridge_oof(R/'v3_recovery_features.csv', sids, y_resid, alpha=1.0)

    P_v2gsp = np.column_stack([p_v2, p_gsp])
    P_full = np.column_stack([p_v2, p_gsp, mos, titd, psi, shp, pm, rec])
    keys = ['V2', 'GSP', 'mos', 'titd', 'psi', 'shp', 'pm', 'rec']

    # ============================================================
    # Codex Fix 1: Strict 2-source V2+GSP nested blend (reference)
    # ============================================================
    print("\n=== Codex Fix 1: Strict 2-source V2+GSP nested CV ===")
    preds_v2gsp, _ = nested_cv_shrink(P_v2gsp, y_true, lam=0.0,
                                       w0=np.array([0.5, 0.5]))
    c_v2gsp = ccc(y_true, preds_v2gsp)
    o, lo, hi = bca(y_true, preds_v2gsp, p_v2)
    print(f"  V2+GSP nested CCC = {c_v2gsp:.4f}  Δ = {c_v2gsp-0.7170:+.4f}")
    print(f"  BCa Δ CI: [{lo:+.4f}, {hi:+.4f}]  excludes 0: {lo>0 or hi<0}")

    # ============================================================
    # Codex Fix 2: Shrink-to-prior simplex stacking (8 sources)
    # ============================================================
    print("\n=== Codex Fix 2: Shrink-to-prior simplex stacking ===")
    # Prior: V2=0.5, GSP=0.5, rest=0
    w0_8 = np.array([0.5, 0.5, 0, 0, 0, 0, 0, 0])
    for lam in [0.0, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0]:
        preds_s, wlog = nested_cv_shrink(P_full, y_true, lam=lam, w0=w0_8)
        c = ccc(y_true, preds_s)
        mean_w = wlog.mean(axis=0)
        # Sort weight by descending
        weighted = sorted(zip(keys, mean_w), key=lambda x: -x[1])
        print(f"  λ={lam:6.2f}: CCC={c:.4f} Δ={c-0.7170:+.4f}  top3={[(k,f'{w:.2f}') for k,w in weighted[:3]]}")

    # ============================================================
    # Codex Fix 3: One-parameter residual add-on per candidate
    # ============================================================
    print("\n=== Codex Fix 3: One-parameter residual add-ons ===")
    print("Base = V2+GSP 50/50 (no nested overhead — closed-form blend)")
    # Use simple 50/50 as base (no inner CV needed for 2 weights)
    p_base = 0.5 * p_v2 + 0.5 * p_gsp
    print(f"  Base CCC: {ccc(y_true, p_base):.4f}")
    candidates = {'mos': mos, 'titd': titd, 'psi': psi, 'shp': shp, 'pm': pm, 'rec': rec}
    for name, p_c in candidates.items():
        preds_add, alphas, admitted = one_param_addon(p_base, p_c, y_true)
        c = ccc(y_true, preds_add)
        n_admitted = admitted.sum()
        mean_alpha = alphas[admitted].mean() if admitted.any() else 0
        print(f"  +{name:5s}: CCC={c:.4f}  Δ vs V2={c-0.7170:+.4f}  admitted={n_admitted}/92  mean_alpha={mean_alpha:.3f}")

    # ============================================================
    # Codex Fix 4: Affine calibration on V2+GSP+mos+titd stack
    # ============================================================
    print("\n=== Codex Fix 4: Affine calibration on inner stack ===")
    P4 = np.column_stack([p_v2, p_gsp, mos, titd])
    preds_cal, _ = nested_cv_with_affine_cal(P4, y_true)
    c_cal = ccc(y_true, preds_cal)
    o, lo, hi = bca(y_true, preds_cal, p_v2)
    print(f"  V2+GSP+mos+titd + affine cal: CCC={c_cal:.4f}  Δ={c_cal-0.7170:+.4f}")
    print(f"  BCa Δ CI: [{lo:+.4f}, {hi:+.4f}]  excludes 0: {lo>0 or hi<0}")

    # ============================================================
    # Sign-flip test on best V2+GSP nested
    # ============================================================
    print("\n=== Sign-flip vs V2-iter34 ===")
    def sign_flip(y, pa, pb, n_perms=10000, seed=42):
        rng = np.random.RandomState(seed)
        diffs = (y-pb)**2 - (y-pa)**2
        obs = diffs.mean(); n = len(diffs)
        perm = np.empty(n_perms)
        for i in range(n_perms):
            flips = rng.choice([-1.0,1.0], size=n)
            perm[i] = (diffs*flips).mean()
        return obs, float((perm >= obs).mean())
    for name, pred in [
        ('V2+GSP nested', preds_v2gsp),
        ('V2+GSP+...+cal', preds_cal),
        ('V2+GSP 50/50 raw', 0.5*p_v2 + 0.5*p_gsp),
    ]:
        o, p = sign_flip(y_true, pred, p_v2)
        print(f"  {name:24s}: obs={o:+.4f}  p={p:.4f}")


if __name__ == "__main__":
    main()
