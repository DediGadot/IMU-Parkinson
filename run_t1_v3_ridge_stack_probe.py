"""Fast Ridge LOOCV probe for V3 family error-orthogonality vs V2 + V3-GSP.

Strategy: for each V3 family (TITD, PM, MoS, Recovery), train a fold-local
Stage-1 (iter5) + Ridge on T1 residual using the family's features. Compute the
OOF predictions. Then test stacking with existing V2 + V3-GSP OOFs.

This isolates the family's ORTHOGONALITY contribution from the chain
architecture. The chain run gave us CCCs for standalone family quality;
this probe gives us stacking efficiency.

If a family's Ridge LOOCV preds have low error correlation with V2 AND V3-GSP,
even at lower standalone CCC, the family can add to the stack.
"""
from __future__ import annotations

import os, sys, json, time
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import LeaveOneOut
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

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

V3_FAMILIES = {
    "v3_gsp": RESULTS_DIR / "v3_gsp_features.csv",
    "v3_mos": RESULTS_DIR / "v3_mos_features.csv",
    "v3_titd": RESULTS_DIR / "v3_titd_features.csv",
    "v3_pm": RESULTS_DIR / "v3_phase_manifold_features.csv",
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
    return np.array(rows), feat_cols


def ridge_loocv(X, y_resid, alpha=1.0, seed=42):
    """Fold-local Stage-1-residualized Ridge LOOCV.

    Returns OOF predictions of T1 residual (after Stage-1).
    """
    n = len(y_resid)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(np.arange(n)):
        # Fold-local imputation
        col_mean = np.nanmean(X[tr], axis=0)
        Xtr = X[tr].copy()
        Xte = X[te].copy()
        for j in range(X.shape[1]):
            m = col_mean[j] if np.isfinite(col_mean[j]) else 0.0
            Xtr[np.isnan(Xtr[:, j]), j] = m
            Xte[np.isnan(Xte[:, j]), j] = m
        # Fold-local z-score
        scaler = StandardScaler()
        Xtr_s = scaler.fit_transform(Xtr)
        Xte_s = scaler.transform(Xte)
        # Ridge fit on T1 residual
        rg = Ridge(alpha=alpha, random_state=seed)
        rg.fit(Xtr_s, y_resid[tr])
        preds[te] = rg.predict(Xte_s)
    return preds


def main():
    print("=== V3 family Ridge LOOCV probe — error orthogonality test ===\n", flush=True)
    sids, X_v2, y_t1, hy, items, _ = _load_t1_cohort_with_8items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    # Compute Stage-1 OOF preds
    print(f"Cohort N={n}, computing Stage-1 OOF residuals...", flush=True)
    s1_oof = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(np.arange(n)):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=1.0)
        s1_oof[te] = s1_te
    y_resid_full = y_t1 - s1_oof
    print(f"  Stage-1 OOF CCC = {ccc(y_t1, s1_oof):.4f}", flush=True)

    # Load V2-iter34 + V3-GSP OOFs (existing) for reference comparators
    with open(ITER34_JSON) as f:
        j_v2 = json.load(f)
    p_v2 = np.load(ITER34_OOF)
    sid_v2 = dict(zip([str(s) for s in j_v2["per_subject"]["sids"]], p_v2.tolist()))
    p_v2_a = np.array([sid_v2[str(s)] for s in sids])

    # V3-GSP OOF (from existing lockbox)
    GSP_OOF = RESULTS_DIR / "lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy"
    GSP_JSON = RESULTS_DIR / "lockbox_t1_v3_gsp_v3_only_20260512_195152.json"
    with open(GSP_JSON) as f:
        j_gsp = json.load(f)
    p_gsp = np.load(GSP_OOF)
    sid_gsp = dict(zip([str(s) for s in j_gsp["per_subject"]["sids"]], p_gsp.tolist()))
    p_gsp_a = np.array([sid_gsp.get(str(s), np.nan) for s in sids])

    print(f"\nReference predictors:")
    print(f"  V2 (iter34 chain)  CCC = {ccc(y_t1, p_v2_a):.4f}")
    print(f"  V3-GSP (iter34 ch) CCC = {ccc(y_t1, p_gsp_a):.4f}")

    # Per V3 family: Ridge LOOCV
    print(f"\nPer V3 family — Ridge on Stage-1 residual:", flush=True)
    family_preds: dict[str, np.ndarray] = {}
    family_preds["V2_chain"] = p_v2_a
    family_preds["V3GSP_chain"] = p_gsp_a
    for name, path in V3_FAMILIES.items():
        if not path.exists():
            print(f"  {name}: SKIP (file missing)")
            continue
        X, cols = _load_family(path, sids)
        n_feat = X.shape[1]
        # Ridge OOF on Stage-1 residual
        p_resid = ridge_loocv(X, y_resid_full, alpha=1.0)
        p_full = s1_oof + p_resid
        c = ccc(y_t1, p_full)
        family_preds[name] = p_full
        # Error correlations
        e_v2 = y_t1 - p_v2_a
        e_gsp = y_t1 - p_gsp_a
        e_fam = y_t1 - p_full
        rho_v2 = float(np.corrcoef(e_v2, e_fam)[0,1])
        rho_gsp = float(np.corrcoef(e_gsp, e_fam)[0,1])
        print(f"  {name:12s}: feats={n_feat:>4d}  CCC={c:.4f}  errcorr(V2)={rho_v2:.3f}  errcorr(V3-GSP)={rho_gsp:.3f}")

    # Stacking analysis
    print(f"\n=== Stacking grid search (3-way max, then 4-way) ===", flush=True)
    # Best 2-way V2 + V3-GSP
    p_b = 0.5 * p_v2_a + 0.5 * p_gsp_a
    print(f"\n  V2+V3-GSP (50/50): CCC = {ccc(y_t1, p_b):.4f}  Δ = {ccc(y_t1, p_b)-0.7170:+.4f}")

    # 3-way add each family
    keys_v3 = [k for k in family_preds if k.startswith("v3_")]
    for fam in keys_v3:
        p_f = family_preds[fam]
        # Grid search 3-way (V2, V3-GSP, fam)
        best_c, best_w = -1, None
        for w1 in np.arange(0, 1.01, 0.05):
            for w2 in np.arange(0, 1.01-w1, 0.05):
                w3 = 1 - w1 - w2
                if w3 < 0: continue
                p_w = w1*p_v2_a + w2*p_gsp_a + w3*p_f
                c = ccc(y_t1, p_w)
                if c > best_c:
                    best_c, best_w = c, (w1, w2, w3)
        print(f"  V2+V3GSP+{fam:10s} GRID: CCC={best_c:.4f}  Δ={best_c-0.7170:+.4f}  w=({best_w[0]:.2f},{best_w[1]:.2f},{best_w[2]:.2f})")

    # 4-way: V2 + V3-GSP + best Ridge family + 2nd best Ridge family (top picks: TITD, PM, MoS, Rec)
    print(f"\n  --- 4-way grid (subset of best families) ---", flush=True)
    fam_ridge = [k for k in keys_v3 if k != "v3_gsp"]
    print(f"  Families considered: {fam_ridge}")
    for i, f1 in enumerate(fam_ridge):
        for f2 in fam_ridge[i+1:]:
            best_c, best_w = -1, None
            for w1 in np.arange(0, 1.01, 0.1):
                for w2 in np.arange(0, 1.01-w1, 0.1):
                    for w3 in np.arange(0, 1.01-w1-w2, 0.1):
                        w4 = 1 - w1 - w2 - w3
                        if w4 < 0: continue
                        p_w = w1*p_v2_a + w2*p_gsp_a + w3*family_preds[f1] + w4*family_preds[f2]
                        c = ccc(y_t1, p_w)
                        if c > best_c:
                            best_c, best_w = c, (w1, w2, w3, w4)
            print(f"  V2+GSP+{f1:10s}+{f2:10s}: CCC={best_c:.4f}  Δ={best_c-0.7170:+.4f}  w=({best_w[0]:.2f},{best_w[1]:.2f},{best_w[2]:.2f},{best_w[3]:.2f})")

    # Save all OOF preds for further analysis
    out = {fam: pred.tolist() for fam, pred in family_preds.items()}
    out["y_true"] = y_t1.tolist()
    out["sids"] = [str(s) for s in sids]
    with open(RESULTS_DIR / "v3_ridge_probe_oof.json", "w") as f:
        json.dump(out, f)
    print(f"\nWrote V3 Ridge probe OOFs to {RESULTS_DIR / 'v3_ridge_probe_oof.json'}", flush=True)


if __name__ == "__main__":
    main()
