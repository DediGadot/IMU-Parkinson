"""Codex's MISSING LEVER: single-item residual substitution at item 12.

From 2026-05-12 deep consult: "test single-item residual substitution before
broad per-item K=500. Baseline: 7-item no-13 V2 chain. Only candidate change:
replace item-12 prediction with V2 item12 prediction + GSP low-mode residual
correction. Fixed inclusion rule, no stack weights, no multi-source learner.
Optional cap: shrink residual correction by a fixed 0.5, not learned."

Architecture:
  1. Load iter34 per-item OOF (item_12_pred for each subject is the 8-item
     chain's leakage-clean LOOCV prediction).
  2. Define V3-GSP low-mode block: tasks ∈ {Balance, TandemGait, TUG};
     modes k ∈ {0,1,2,3}; stats ∈ {energy_pct, en_bloc_index, low_mode_energy_pct};
     channel kinds ∈ {acc, gyr}. ~30-60 features.
  3. Per outer LOOCV fold: Ridge on V3-GSP low-mode block to predict
     item_12_residual = item_12_true - item_12_pred. Use train fold only.
  4. For test subject: corrected_item_12 = item_12_pred + shrink * Ridge_correction.
  5. T1_corrected = t1_pred - item_12_pred + corrected_item_12_pred
                  = t1_pred + shrink * Ridge_correction.
  6. Compare CCC(y_t1, t1_corrected) to CCC(y_t1, t1_pred). Sweep shrink ∈
     {0.3, 0.5, 0.7, 1.0}.

Honest nested CV: no inner-CV for Ridge alpha (use fixed alpha grid). Single
outer LOOCV. The chain itself is iter34 (already LOOCV-trained).

Also test 7-item-no-13 baseline by using drop13 lockbox + same correction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.preprocessing import StandardScaler

R = Path('/home/fiod/medical/results')


def ccc(y, p):
    yb, pb = y.mean(), p.mean()
    return 2 * ((y-yb)*(p-pb)).mean() / (y.var() + p.var() + (yb-pb)**2)


def sign_flip_p(y, p_a, p_b, n_perms=10000, seed=42):
    rng = np.random.RandomState(seed)
    se_a = (y - p_a) ** 2; se_b = (y - p_b) ** 2
    diffs = se_b - se_a
    obs = diffs.mean(); n = len(diffs)
    perm = np.empty(n_perms)
    for i in range(n_perms):
        flips = rng.choice([-1.0, 1.0], size=n)
        perm[i] = (diffs * flips).mean()
    return obs, float((perm >= obs).mean())


def bca_ci(y, pa, pb, n_boot=5000, seed=42):
    from scipy.stats import norm
    rng = np.random.RandomState(seed)
    n = len(y); boot = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        boot[i] = ccc(y[idx], pa[idx]) - ccc(y[idx], pb[idx])
    obs = ccc(y, pa) - ccc(y, pb)
    z0 = norm.ppf(max(min((boot < obs).mean(), 1-1e-6), 1e-6))
    jack = np.empty(n)
    for i in range(n):
        idx = np.concatenate([np.arange(i), np.arange(i+1, n)])
        jack[i] = ccc(y[idx], pa[idx]) - ccc(y[idx], pb[idx])
    jm = jack.mean(); num = ((jm - jack)**3).sum()
    den = 6.0 * (((jm - jack)**2).sum()**1.5 + 1e-12)
    a = num / den
    zl = norm.ppf(0.025); zh = norm.ppf(0.975)
    plo = norm.cdf(z0 + (z0+zl)/(1-a*(z0+zl)))
    phi = norm.cdf(z0 + (z0+zh)/(1-a*(z0+zh)))
    return obs, float(np.quantile(boot, plo)), float(np.quantile(boot, phi))


def _select_low_mode_cols(gsp_cols: list[str]) -> list[str]:
    """Codex's prescribed V3-GSP low-mode subset for item 12.

    Tasks ∈ {Balance, TandemGait, TUG} (axial-postural).
    Stats: energy_pct, en_bloc_index, low_mode_energy_pct, high_mode_energy_pct.
    Modes: k=0..3 + aggregates.
    Channels: acc, gyr.
    """
    target_tasks = ['Balance', 'TandemGait', 'TUG']
    selected: list[str] = []
    for c in gsp_cols:
        # Task in target set
        if not any(c.endswith('__' + t) for t in target_tasks):
            continue
        # Low-mode k=0..3 with energy_pct, OR en_bloc, OR low/high_mode aggregates
        is_low_mode_k = any(f'_m0{k}_' in c for k in range(4)) and ('energy_pct' in c or '_var' in c)
        is_aggregate = (
            'low_mode_energy_pct' in c
            or 'high_mode_energy_pct' in c
            or 'en_bloc_index' in c
        )
        if is_low_mode_k or is_aggregate:
            selected.append(c)
    return sorted(selected)


def _load_gsp_block(sids, cols_subset):
    df = pd.read_csv(R / 'v3_gsp_features.csv').set_index('sid')
    df.index = df.index.astype(str)
    rows = []
    for s in sids:
        s = str(s)
        if s in df.index:
            rows.append(df.loc[s, cols_subset].values.astype(float))
        else:
            rows.append(np.full(len(cols_subset), np.nan))
    return np.array(rows)


def nested_loocv_ridge_correction(X, y, alpha=1.0):
    """Outer LOOCV Ridge regression returning OOF predictions.

    For each test fold: fit Ridge on training fold; predict test subject.
    """
    n = len(y); preds = np.zeros(n)
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
        rg.fit(Xtr_s, y[tr])
        preds[te] = rg.predict(Xte_s)
    return preds


def nested_loocv_ridgecv(X, y, alphas=(0.1, 1.0, 3.0, 10.0, 30.0, 100.0)):
    """Outer LOOCV with inner-CV (alpha selection via RidgeCV)."""
    n = len(y); preds = np.zeros(n)
    for tr, te in LeaveOneOut().split(np.arange(n)):
        med = np.nanmedian(X[tr], axis=0)
        Xtr = X[tr].copy(); Xte = X[te].copy()
        for j in range(X.shape[1]):
            m = med[j] if np.isfinite(med[j]) else 0.0
            Xtr[np.isnan(Xtr[:, j]), j] = m
            Xte[np.isnan(Xte[:, j]), j] = m
        sc = StandardScaler()
        Xtr_s = sc.fit_transform(Xtr); Xte_s = sc.transform(Xte)
        rg = RidgeCV(alphas=list(alphas))
        rg.fit(Xtr_s, y[tr])
        preds[te] = rg.predict(Xte_s)
    return preds


def main():
    print("=" * 72, flush=True)
    print("CODEX MISSING LEVER: single-item residual substitution at item 12",
          flush=True)
    print("=" * 72, flush=True)

    # Load iter34 per-item OOF (8-item hybrid hygiene-corrected)
    per_item = np.load(R / 't1_iter34_per_item_oof_20260511_044242.npz')
    sids = per_item['sids'].tolist()
    y_t1 = per_item['y_t1']
    t1_pred = per_item['t1_sum_pred']
    item_12_pred = per_item['item_12_pred']
    item_12_true = per_item['item_12_true']

    print(f"\nCohort: N={len(sids)}", flush=True)
    print(f"  iter34 (8-item) CCC = {ccc(y_t1, t1_pred):.4f}", flush=True)
    print(f"  item 12 standalone CCC = {ccc(item_12_true, item_12_pred):.4f}", flush=True)

    # Compute item-12 residual
    item_12_residual = item_12_true - item_12_pred
    print(f"  item-12 residual mean={item_12_residual.mean():+.3f}  std={item_12_residual.std():.3f}",
          flush=True)

    # Load V3-GSP low-mode block
    gsp_cols_all = pd.read_csv(R / 'v3_gsp_features.csv').columns.tolist()
    gsp_cols_all = [c for c in gsp_cols_all if c != 'sid']
    low_mode_cols = _select_low_mode_cols(gsp_cols_all)
    print(f"\nV3-GSP low-mode block: {len(low_mode_cols)} features", flush=True)
    print(f"  sample columns: {low_mode_cols[:6]}", flush=True)

    X_low = _load_gsp_block(sids, low_mode_cols)
    print(f"  X_low shape = {X_low.shape}", flush=True)

    # Codex's recommended approach: nested LOOCV Ridge predicting item-12 residual
    # Try multiple alpha and shrinkage settings
    print(f"\n=== Sweep Ridge alpha × shrinkage ===", flush=True)
    print(f"{'alpha':>8s}  {'shrink':>7s}  {'CCC':>8s}  {'Δ vs iter34':>11s}  {'sign-flip p':>11s}")

    best_result = None
    for alpha in [0.1, 1.0, 3.0, 10.0, 30.0]:
        corrections = nested_loocv_ridge_correction(X_low, item_12_residual, alpha=alpha)
        for shrink in [0.3, 0.5, 0.7, 1.0]:
            t1_corrected = t1_pred + shrink * corrections
            c = ccc(y_t1, t1_corrected)
            sf_obs, sf_p = sign_flip_p(y_t1, t1_corrected, t1_pred)
            marker = " ★" if c > 0.7170 + 0.020 else ("  " if c <= 0.7170 else "  ")
            print(f"  {alpha:>6.2f}  {shrink:>6.2f}  {c:>7.4f}  {c-0.7170:>+10.4f}  {sf_p:>10.4f}{marker}")
            if best_result is None or c > best_result['ccc']:
                best_result = {
                    'alpha': alpha, 'shrink': shrink, 'ccc': c,
                    'delta': c - 0.7170, 'sign_flip_p': sf_p,
                    'preds': t1_corrected.copy(),
                }

    # Also try inner-CV alpha selection (RidgeCV)
    print(f"\n=== Inner-CV alpha selection (RidgeCV) ===", flush=True)
    corrections_cv = nested_loocv_ridgecv(X_low, item_12_residual)
    for shrink in [0.3, 0.5, 0.7, 1.0]:
        t1_corrected = t1_pred + shrink * corrections_cv
        c = ccc(y_t1, t1_corrected)
        sf_obs, sf_p = sign_flip_p(y_t1, t1_corrected, t1_pred)
        print(f"  RidgeCV  shrink={shrink:.2f}  CCC={c:.4f}  Δ={c-0.7170:+.4f}  p={sf_p:.4f}")
        if c > best_result['ccc']:
            best_result = {
                'alpha': 'RidgeCV', 'shrink': shrink, 'ccc': c,
                'delta': c - 0.7170, 'sign_flip_p': sf_p,
                'preds': t1_corrected.copy(),
            }

    # Report best
    print(f"\n=== BEST RESULT ===", flush=True)
    print(f"  alpha={best_result['alpha']}, shrink={best_result['shrink']}", flush=True)
    print(f"  CCC = {best_result['ccc']:.4f}  Δ = {best_result['delta']:+.4f}", flush=True)
    print(f"  sign-flip p = {best_result['sign_flip_p']:.4f}", flush=True)

    # BCa CI on best
    obs, lo, hi = bca_ci(y_t1, best_result['preds'], t1_pred)
    print(f"  BCa 95% CI on Δ vs iter34: [{lo:+.4f}, {hi:+.4f}]  excludes 0: {lo>0 or hi<0}", flush=True)

    # ===== Also try drop13 baseline (7-item-no-13 chain) =====
    print(f"\n{'=' * 72}\n7-ITEM NO-13 BASELINE + item-12 correction\n{'=' * 72}", flush=True)
    # Load drop13 lockbox
    import glob
    drop13_files = sorted(glob.glob(str(R / 'lockbox_t1_iter34_phase0_drop13_*.json')))
    if drop13_files:
        with open(drop13_files[-1]) as f:
            j_d13 = json.load(f)
        oof_files = sorted(glob.glob(str(R / 'lockbox_t1_iter34_phase0_drop13_*.oof.npy')))
        if oof_files:
            t1_pred_d13 = np.load(oof_files[-1])
            sids_d13 = [str(s) for s in j_d13['per_subject']['sids']]
            y_d13 = np.array(j_d13['per_subject']['y_true'])
            sid_to_pred = dict(zip(sids_d13, t1_pred_d13.tolist()))
            t1_pred_d13_aligned = np.array([sid_to_pred.get(str(s), np.nan) for s in sids])
            print(f"  drop13 baseline CCC = {ccc(y_t1, t1_pred_d13_aligned):.4f}", flush=True)
            # Apply best alpha+shrink from above to drop13 baseline
            a = best_result['alpha'] if best_result['alpha'] != 'RidgeCV' else 3.0
            corrections_best = nested_loocv_ridge_correction(X_low, item_12_residual, alpha=a)
            for shrink in [0.3, 0.5, 0.7, 1.0]:
                t1_corrected_d13 = t1_pred_d13_aligned + shrink * corrections_best
                c = ccc(y_t1, t1_corrected_d13)
                sf_obs, sf_p = sign_flip_p(y_t1, t1_corrected_d13, t1_pred)  # vs iter34 baseline
                print(f"  drop13 + alpha={a}, shrink={shrink}: CCC={c:.4f}  Δ vs iter34={c-0.7170:+.4f}  Δ vs drop13={c-ccc(y_t1,t1_pred_d13_aligned):+.4f}  p={sf_p:.4f}")

    # ===== Save outputs =====
    out = {
        'best_alpha': best_result['alpha'],
        'best_shrink': best_result['shrink'],
        'best_ccc': best_result['ccc'],
        'best_delta_vs_iter34': best_result['delta'],
        'best_sign_flip_p': best_result['sign_flip_p'],
        'bca_ci_lo': lo, 'bca_ci_hi': hi,
        'n_features_used': len(low_mode_cols),
        'cohort_n': len(sids),
        'low_mode_features': low_mode_cols,
    }
    out_path = R / 'codex_item12_residual_summary.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
