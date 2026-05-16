"""T3 nonlinear clinical Stage-1 — add interaction terms to Stage-1 Ridge."""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def fit_lgb(Xt, yt, seed):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(n_estimators=500, learning_rate=0.05, num_leaves=15,
                         min_data_in_leaf=10, feature_fraction=0.8, bagging_fraction=0.8,
                         bagging_freq=3, verbose=-1, random_state=seed).fit(Xt, yt)

def run(X, Xc, y, seed):
    n = len(y); preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y[tr] - s1tr
        imp = FoldImputer.fit(X[tr])
        Xtr = imp.transform(X[tr]); Xte = imp.transform(X[te])
        sel = kselect(Xtr, resid, K_BEST)
        m2 = fit_lgb(Xtr[:, sel], resid, seed)
        preds[te[0]] = s1te[0] + m2.predict(Xte[:, sel])[0]
    return preds

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    X_clin_lin = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)
    
    # Nonlinear features: hy^2, hy*cv_dbs, hy*cv_yrs, cv_yrs*cv_dbs, cv_yrs^2
    feat_names = ["hy"] + [feats[i] for i in cc]
    hy_sq = (hy**2).reshape(-1, 1)
    interactions = []
    if "cv_yrs" in feat_names:
        idx_yrs = feat_names.index("cv_yrs")
        interactions.append((X_clin_lin[:, 0] * X_clin_lin[:, idx_yrs]).reshape(-1,1))  # hy*cv_yrs
        if "cv_dbs" in feat_names:
            idx_dbs = feat_names.index("cv_dbs")
            interactions.append((X_clin_lin[:, idx_yrs] * X_clin_lin[:, idx_dbs]).reshape(-1,1))  # cv_yrs*cv_dbs
            interactions.append((X_clin_lin[:, 0] * X_clin_lin[:, idx_dbs]).reshape(-1,1))  # hy*cv_dbs
        interactions.append((X_clin_lin[:, idx_yrs]**2).reshape(-1,1))  # cv_yrs^2
    X_clin_nl = np.column_stack([X_clin_lin, hy_sq] + interactions)
    print(f"  Clinical linear dim: {X_clin_lin.shape[1]}, nonlinear dim: {X_clin_nl.shape[1]}")

    base_p = []
    nl_p = []
    for seed in (42, 1337, 7):
        pb = run(Xv2, X_clin_lin, y, seed)
        pn = run(Xv2, X_clin_nl, y, seed)
        d = ccc(y, pn) - ccc(y, pb)
        print(f"  seed={seed} linear={ccc(y, pb):.4f} nonlinear={ccc(y, pn):.4f} Δ={d:+.4f}", flush=True)
        base_p.append(pb); nl_p.append(pn)
    
    pb_m = np.mean(base_p, axis=0); pn_m = np.mean(nl_p, axis=0)
    delta = float(ccc(y, pn_m) - ccc(y, pb_m))
    print(f"  Δ_pooled = {delta:+.4f}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_nonlinear_clin_{ts}.json"
    out.write_text(json.dumps({"name": "t3_nonlinear_clin", "linear_ccc": float(ccc(y, pb_m)), "nonlinear_ccc": float(ccc(y, pn_m)), "delta": delta}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()
