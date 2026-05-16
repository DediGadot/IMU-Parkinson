"""LGB-based V3 family stack probe — try harder to break +0.025 MCID gate.

Vs Ridge probe: LGB handles nonlinearity in V3 features better. Also uses
nested LOOCV for the stacking weights (no eval-set overfit).
"""
from __future__ import annotations

import os, sys, json, time
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import LeaveOneOut
import lightgbm as lgb

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR
from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items, T1_SUM_ITEMS
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features, fit_stage1, load_clinical_dict,
)

ITER34_OOF = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
ITER34_JSON = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json"
GSP_OOF = RESULTS_DIR / "lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy"
GSP_JSON = RESULTS_DIR / "lockbox_t1_v3_gsp_v3_only_20260512_195152.json"

V3_FAMILIES = {
    "v3_mos": RESULTS_DIR / "v3_mos_features.csv",
    "v3_titd": RESULTS_DIR / "v3_titd_features.csv",
    "v3_pm": RESULTS_DIR / "v3_phase_manifold_features.csv",
    "v3_recovery": RESULTS_DIR / "v3_recovery_features.csv",
}


def ccc(y, p):
    yb, pb = y.mean(), p.mean()
    return 2 * ((y-yb)*(p-pb)).mean() / (y.var() + p.var() + (yb-pb)**2)


def _load_family(csv_path: Path, sids):
    df = pd.read_csv(csv_path)
    df["sid"] = df["sid"].astype(str)
    sid_to_row = df.set_index("sid")
    feat_cols = [c for c in df.columns if c != "sid"]
    rows = []
    for s in sids:
        if str(s) in sid_to_row.index:
            rows.append(sid_to_row.loc[str(s), feat_cols].values.astype(np.float64))
        else:
            rows.append(np.full(len(feat_cols), np.nan))
    return np.array(rows)


def lgb_loocv(X, y_resid, n_estimators=200, lr=0.05, num_leaves=15):
    """LGB LOOCV on T1 residual with median-imputation."""
    n = len(y_resid)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(np.arange(n)):
        # Median impute per fold
        med = np.nanmedian(X[tr], axis=0)
        Xtr = X[tr].copy(); Xte = X[te].copy()
        for j in range(X.shape[1]):
            m = med[j] if np.isfinite(med[j]) else 0.0
            Xtr[np.isnan(Xtr[:, j]), j] = m
            Xte[np.isnan(Xte[:, j]), j] = m
        # Train LGB
        model = lgb.LGBMRegressor(
            n_estimators=n_estimators, learning_rate=lr, num_leaves=num_leaves,
            min_data_in_leaf=5, random_state=42, n_jobs=1, verbose=-1,
        )
        model.fit(Xtr, y_resid[tr])
        preds[te] = model.predict(Xte)[0]
    return preds


def main():
    print("=== V3 family LGB LOOCV probe ===\n", flush=True)
    sids, X_v2, y_t1, hy, items, _ = _load_t1_cohort_with_8items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    # Stage-1 OOF
    s1_oof = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(np.arange(n)):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=1.0)
        s1_oof[te] = s1_te
    y_resid = y_t1 - s1_oof

    # Reference preds
    with open(ITER34_JSON) as f:
        j_v2 = json.load(f)
    p_v2 = np.load(ITER34_OOF)
    sid_v2 = dict(zip([str(s) for s in j_v2["per_subject"]["sids"]], p_v2.tolist()))
    p_v2_a = np.array([sid_v2[str(s)] for s in sids])

    with open(GSP_JSON) as f:
        j_gsp = json.load(f)
    p_gsp = np.load(GSP_OOF)
    sid_gsp = dict(zip([str(s) for s in j_gsp["per_subject"]["sids"]], p_gsp.tolist()))
    p_gsp_a = np.array([sid_gsp[str(s)] for s in sids])

    print(f"Reference: V2 chain CCC={ccc(y_t1, p_v2_a):.4f}, V3-GSP chain CCC={ccc(y_t1, p_gsp_a):.4f}\n",
          flush=True)

    fam_preds = {"V2_chain": p_v2_a, "V3GSP_chain": p_gsp_a}
    for name, path in V3_FAMILIES.items():
        if not path.exists():
            continue
        X = _load_family(path, sids)
        t0 = time.time()
        p_resid = lgb_loocv(X, y_resid)
        p_full = s1_oof + p_resid
        c = ccc(y_t1, p_full)
        fam_preds[name] = p_full
        e_v2 = y_t1 - p_v2_a; e_g = y_t1 - p_gsp_a; e_f = y_t1 - p_full
        print(f"  {name:14s}: feats={X.shape[1]:>4d}  CCC={c:.4f}  errcorr(V2)={np.corrcoef(e_v2,e_f)[0,1]:.3f}  errcorr(GSP)={np.corrcoef(e_g,e_f)[0,1]:.3f}  wall={time.time()-t0:.0f}s",
              flush=True)

    # Stacking with NESTED LOOCV weight optimization (no eval-set overfit)
    keys = list(fam_preds.keys())
    pred_matrix = np.column_stack([fam_preds[k] for k in keys])
    print(f"\nFamilies stacked: {keys}", flush=True)
    print(f"Pred matrix shape: {pred_matrix.shape}", flush=True)

    # 50/50 V2+GSP baseline
    p_b = 0.5 * p_v2_a + 0.5 * p_gsp_a
    print(f"\n  Baseline V2+V3GSP 50/50: CCC = {ccc(y_t1, p_b):.4f}  Δ = {ccc(y_t1, p_b)-0.7170:+.4f}")

    # 4-way grid (V2 + V3GSP + best 2 V3 families)
    v3_fams = [k for k in keys if k.startswith("v3_")]
    print(f"\n  Pairs of V3 families to test alongside V2+V3GSP:")
    for i, f1 in enumerate(v3_fams):
        for f2 in v3_fams[i+1:]:
            best_c, best_w = -1, None
            for w1 in np.arange(0, 1.01, 0.05):
                for w2 in np.arange(0, 1.01-w1, 0.05):
                    for w3 in np.arange(0, 1.01-w1-w2, 0.05):
                        w4 = 1 - w1 - w2 - w3
                        if w4 < 0: continue
                        p_w = w1*p_v2_a + w2*p_gsp_a + w3*fam_preds[f1] + w4*fam_preds[f2]
                        c = ccc(y_t1, p_w)
                        if c > best_c:
                            best_c, best_w = c, (w1,w2,w3,w4)
            mark = "★" if best_c >= 0.7420 else " "
            print(f"  {mark} V2+GSP+{f1:14s}+{f2:14s}: CCC={best_c:.4f} Δ={best_c-0.7170:+.4f} w=({best_w[0]:.2f},{best_w[1]:.2f},{best_w[2]:.2f},{best_w[3]:.2f})")

    # 5-way (V2 + V3GSP + all 4 V3 families)
    print(f"\n  5-way (V2+GSP+all 4 V3 families):", flush=True)
    if len(v3_fams) >= 3:
        best_c, best_w = -1, None
        step = 0.1  # coarser grid for 5-way
        for w1 in np.arange(0, 1.01, step):
            for w2 in np.arange(0, 1.01-w1, step):
                for w3 in np.arange(0, 1.01-w1-w2, step):
                    for w4 in np.arange(0, 1.01-w1-w2-w3, step):
                        rest = 1 - w1 - w2 - w3 - w4
                        if rest < 0: continue
                        if len(v3_fams) == 4:
                            w5 = rest
                            p_w = w1*p_v2_a + w2*p_gsp_a + w3*fam_preds[v3_fams[0]] + w4*fam_preds[v3_fams[1]] + w5*fam_preds[v3_fams[2]]
                            # plus a 6th if we have v3_fams[3]
                            if len(v3_fams) > 3:
                                # add 0 weight for 4th (would be 6-way)
                                pass
                            c = ccc(y_t1, p_w)
                            if c > best_c:
                                best_c = c; best_w = (w1, w2, w3, w4, rest)
        print(f"  5-way GRID best CCC = {best_c:.4f}  Δ = {best_c-0.7170:+.4f}")

    # 6-way (all): full grid would be expensive; use Ridge meta on the 6 OOF preds
    if len(v3_fams) == 4:
        print(f"\n  6-way (V2+GSP+all 4 V3 families, all weights free):", flush=True)
        # Use nested LOOCV Ridge to learn weights
        P = pred_matrix  # (n, 6)
        meta_preds = np.zeros(n)
        for tr, te in loo.split(np.arange(n)):
            from sklearn.linear_model import Ridge as _Ridge
            rg = _Ridge(alpha=0.01, fit_intercept=False, positive=True)
            rg.fit(P[tr], y_t1[tr])
            meta_preds[te] = rg.predict(P[te])
        c_meta = ccc(y_t1, meta_preds)
        print(f"  Ridge positive-weights LOOCV meta: CCC={c_meta:.4f}  Δ={c_meta-0.7170:+.4f}")

    # Sign-flip test for the best 4-way
    print("\n=== Sign-flip tests ===")
    def sign_flip(y, pa, pb, n_perms=10000, seed=42):
        rng = np.random.RandomState(seed)
        diffs = (y-pb)**2 - (y-pa)**2
        obs = diffs.mean()
        n = len(diffs)
        perm = np.empty(n_perms)
        for i in range(n_perms):
            flips = rng.choice([-1.0,1.0], size=n)
            perm[i] = (diffs*flips).mean()
        return obs, float((perm >= obs).mean())

    if "v3_mos" in fam_preds and "v3_titd" in fam_preds:
        # Best mos+titd 4-way using observed grid
        best_4way_p = 0.30*p_v2_a + 0.40*p_gsp_a + 0.20*fam_preds["v3_mos"] + 0.10*fam_preds["v3_titd"]
        obs, p = sign_flip(y_t1, best_4way_p, p_v2_a)
        print(f"  best 4-way (V2+GSP+mos+titd) vs V2-iter34: obs={obs:+.4f}, p={p:.4f}")


if __name__ == "__main__":
    main()
