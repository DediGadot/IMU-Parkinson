"""T3 V2+PSI at different K values (PSI was 30% K=500 picks but K=500 hurt)."""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

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

def run(X, Xc, y, seed, k):
    n = len(y); preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y[tr] - s1tr
        imp = FoldImputer.fit(X[tr])
        Xtr = imp.transform(X[tr]); Xte = imp.transform(X[te])
        sel = kselect(Xtr, resid, k)
        m2 = fit_lgb(Xtr[:, sel], resid, seed)
        preds[te[0]] = s1te[0] + m2.predict(Xte[:, sel])[0]
    return preds

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xc = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)
    psi = pd.read_csv(REPO / "results" / "v3_psi_features.csv")
    lk = {str(s): i for i, s in enumerate(psi["sid"].astype(str))}
    cols = [c for c in psi.columns if c != "sid"]
    Xpsi = np.full((len(sids), len(cols)), np.nan)
    for i, s in enumerate(sids):
        if s in lk: Xpsi[i] = psi.iloc[lk[s]][cols].to_numpy()
    Xaug = np.column_stack([Xv2, Xpsi])
    res = {}
    for k in (100, 200, 300, 500, 800):
        seed_pb = []
        for seed in (42, 1337, 7):
            pb = run(Xv2, Xc, y, seed, k)
            pa = run(Xaug, Xc, y, seed, k)
            d = ccc(y, pa) - ccc(y, pb)
            print(f"  K={k} seed={seed} base={ccc(y, pb):.4f} aug={ccc(y, pa):.4f} Δ={d:+.4f}", flush=True)
            seed_pb.append((pb, pa))
        pb_m = np.mean([s[0] for s in seed_pb], axis=0)
        pa_m = np.mean([s[1] for s in seed_pb], axis=0)
        delta = float(ccc(y, pa_m) - ccc(y, pb_m))
        res[k] = {"k": k, "base_ccc": float(ccc(y, pb_m)), "aug_ccc": float(ccc(y, pa_m)), "delta": round(delta, 4)}
    best = max(res, key=lambda k: res[k]["delta"])
    print(f"  Best K = {best} Δ = {res[best]['delta']:+.4f}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_psi_k_sweep_{ts}.json"
    out.write_text(json.dumps({"name": "t3_psi_k_sweep", "results_by_k": res, "best_k": best}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()
