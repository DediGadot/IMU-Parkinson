"""T1 stride+GSP combined Ridge correction on iter34.

Test: combine stride_locked_subj + V3-GSP features as Ridge correction on
iter34 T1 residual. If either family alone hurts, maybe combined doesn't.
"""
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
from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

ALPHA = 50.0
K_BEST = 64
SHRINK = 0.5

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def run(X, res, seed):
    n = len(res); pr = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        imp = FoldImputer.fit(X[tr])
        Xtr = imp.transform(X[tr]); Xte = imp.transform(X[te])
        sel = kselect(Xtr, res[tr], K_BEST)
        nrm = FoldNormalizer.fit(Xtr[:, sel])
        Xtr_n = nrm.transform(Xtr[:, sel]); Xte_n = nrm.transform(Xte[:, sel])
        m = Ridge(alpha=ALPHA, random_state=seed)
        m.fit(Xtr_n, res[tr])
        pr[te[0]] = m.predict(Xte_n)[0]
    return pr

def main():
    d = np.load(REPO / "results" / "t1_iter34_per_item_oof_20260511_044242.npz", allow_pickle=True)
    sids = np.array([str(s) for s in d["sids"]])
    y_t1 = d["y_t1"]; t1_base = d["t1_sum_pred"]
    print(f"  iter34 baseline CCC = {ccc(y_t1, t1_base):.4f}")
    residual = y_t1 - t1_base

    stride = pd.read_csv(REPO / "results" / "stride_locked_subj.csv")
    sl = {str(s): i for i, s in enumerate(stride["sid"].astype(str))}
    s_cols = [c for c in stride.columns if c != "sid"]
    Xs = np.full((len(sids), len(s_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in sl: Xs[i] = stride.iloc[sl[s]][s_cols].to_numpy()

    gsp = pd.read_csv(REPO / "results" / "v3_gsp_features.csv")
    gl = {str(s): i for i, s in enumerate(gsp["sid"].astype(str))}
    g_cols = [c for c in gsp.columns if c != "sid"]
    Xg = np.full((len(sids), len(g_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in gl: Xg[i] = gsp.iloc[gl[s]][g_cols].to_numpy()

    Xc = np.column_stack([Xs, Xg])
    print(f"  combined dim = {Xc.shape[1]}")

    seed_corr = []
    for seed in (42, 1337, 7):
        c = run(Xc, residual, seed)
        t1_new = np.clip(t1_base + SHRINK * c, 0, 24)
        d_seed = float(ccc(y_t1, t1_new) - ccc(y_t1, t1_base))
        print(f"  seed={seed} Δ = {d_seed:+.4f}", flush=True)
        seed_corr.append(c)
    
    c_mean = np.mean(seed_corr, axis=0)
    t1_new = np.clip(t1_base + SHRINK * c_mean, 0, 24)
    delta = float(ccc(y_t1, t1_new) - ccc(y_t1, t1_base))
    print(f"  Δ pooled = {delta:+.4f}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t1_stride_gsp_combined_{ts}.json"
    out.write_text(json.dumps({"name": "t1_stride_gsp_combined", "delta": delta,
                                "baseline_ccc": float(ccc(y_t1, t1_base)),
                                "corrected_ccc": float(ccc(y_t1, t1_new))}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()
