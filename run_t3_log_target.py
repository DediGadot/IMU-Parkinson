"""T3 with log(y+1) target transform — predict in log-space, exponentiate back."""
from __future__ import annotations
import json, sys, time
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
SEEDS = (42, 1337, 7)

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

def run(X, Xc, y, seed, log_target):
    n = len(y); preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        if log_target:
            y_tr_t = np.log1p(y[tr])
        else:
            y_tr_t = y[tr]
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y_tr_t)
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y_tr_t - s1tr
        imp = FoldImputer.fit(X[tr])
        Xtr = imp.transform(X[tr]); Xte = imp.transform(X[te])
        sel = kselect(Xtr, resid, K_BEST)
        m2 = fit_lgb(Xtr[:, sel], resid, seed)
        pred_t = float(s1te[0] + m2.predict(Xte[:, sel])[0])
        if log_target:
            preds[te[0]] = max(0.0, np.expm1(pred_t))
        else:
            preds[te[0]] = pred_t
    return preds

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xc = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)
    print(f"  N={len(sids)}, y range [{y.min():.1f}, {y.max():.1f}]", flush=True)

    seed_p_lin, seed_p_log = [], []
    for seed in SEEDS:
        p_lin = run(Xv2, Xc, y, seed, log_target=False)
        p_log = run(Xv2, Xc, y, seed, log_target=True)
        print(f"  seed={seed} linear CCC={ccc(y, p_lin):.4f} log CCC={ccc(y, p_log):.4f} Δ={ccc(y, p_log)-ccc(y, p_lin):+.4f}", flush=True)
        seed_p_lin.append(p_lin); seed_p_log.append(p_log)

    p_lin_m = np.mean(seed_p_lin, axis=0); p_log_m = np.mean(seed_p_log, axis=0)
    delta = float(ccc(y, p_log_m) - ccc(y, p_lin_m))
    print(f"  Pooled linear CCC = {ccc(y, p_lin_m):.4f}")
    print(f"  Pooled log CCC = {ccc(y, p_log_m):.4f}")
    print(f"  Δ pooled = {delta:+.4f}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_log_target_{ts}.json"
    out.write_text(json.dumps({"name": "t3_log_target", "linear_ccc": float(ccc(y, p_lin_m)),
                                "log_ccc": float(ccc(y, p_log_m)), "delta": delta}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()
