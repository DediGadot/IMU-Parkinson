"""T3 stride 30-seed with LGB-importance K-best — apples-to-apples 30-seed confirmation."""
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
SEEDS = tuple(range(1, 31))

def lgb_kselect(X, y, k, seed):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    from lightgbm import LGBMRegressor
    sel = LGBMRegressor(n_estimators=200, learning_rate=0.1, num_leaves=15,
                        min_data_in_leaf=5, verbose=-1, random_state=seed)
    sel.fit(X, y)
    return np.argsort(-sel.feature_importances_)[:k]

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
        sel = lgb_kselect(Xtr, resid, K_BEST, seed)
        m2 = fit_lgb(Xtr[:, sel], resid, seed)
        preds[te[0]] = s1te[0] + m2.predict(Xte[:, sel])[0]
    return preds

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xc = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)
    stride = pd.read_csv(REPO / "results" / "stride_locked_subj.csv")
    sl = {str(s): i for i, s in enumerate(stride["sid"].astype(str))}
    s_cols = [c for c in stride.columns if c != "sid"]
    Xs = np.full((len(sids), len(s_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in sl: Xs[i] = stride.iloc[sl[s]][s_cols].to_numpy()
    Xaug = np.column_stack([Xv2, Xs])
    print(f"  N={len(sids)}, aug dim={Xaug.shape[1]}")

    base_p, aug_p = [], []
    t0 = time.time()
    for seed_idx, seed in enumerate(SEEDS):
        pb = run(Xv2, Xc, y, seed)
        pa = run(Xaug, Xc, y, seed)
        d = ccc(y, pa) - ccc(y, pb)
        print(f"  seed {seed_idx+1}/30 = {seed}: base={ccc(y, pb):.4f} aug={ccc(y, pa):.4f} Δ={d:+.4f} elapsed={time.time()-t0:.1f}s", flush=True)
        base_p.append(pb); aug_p.append(pa)

    seed_deltas = [float(ccc(y, a) - ccc(y, b)) for a, b in zip(aug_p, base_p)]
    pb_m = np.mean(base_p, axis=0); pa_m = np.mean(aug_p, axis=0)
    n_pos = sum(1 for d in seed_deltas if d > 0)
    n_mcid = sum(1 for d in seed_deltas if d >= 0.025)
    print(f"  Mean Δ = {np.mean(seed_deltas):+.4f}, std = {np.std(seed_deltas):.4f}")
    print(f"  Positive: {n_pos}/30, above-MCID: {n_mcid}/30")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_lgbimp_stride_30seed_{ts}.json"
    out.write_text(json.dumps({
        "name": "t3_lgbimp_stride_30seed",
        "kbest": "LGB-importance (iter47 canonical)",
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(float(np.mean(seed_deltas)), 4),
        "seed_delta_std": round(float(np.std(seed_deltas)), 4),
        "n_positive": n_pos,
        "n_above_mcid": n_mcid,
        "pooled_base_ccc": float(ccc(y, pb_m)),
        "pooled_aug_ccc": float(ccc(y, pa_m)),
        "pooled_delta": float(ccc(y, pa_m) - ccc(y, pb_m)),
    }, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()
