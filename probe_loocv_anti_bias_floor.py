"""Probe: what CCC does a 'predict LOO train mean' baseline give vs true y on T1, N=94?

If structural anti-bias hypothesis is right, this should give CCC roughly in the
range observed by W#106 (-0.182) and W#108 (-0.176), confirming that the 5-null
gate threshold of 0.10 is too tight for LOOCV-with-mean-prediction at N=94.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from eval_utils import lins_ccc as ccc
from run_t1_iter4 import load_pd_data


def main():
    d = load_pd_data()
    y = d["t1"].astype(np.float64)
    n = len(y)
    rng = np.random.RandomState(42)
    y_scr = y.copy(); rng.shuffle(y_scr)

    # Predictor 1: LOO mean (constant per-fold)
    preds_loo_mean = np.array([y[np.arange(n) != i].mean() for i in range(n)])
    preds_loo_mean_scr = np.array([y_scr[np.arange(n) != i].mean() for i in range(n)])

    # Predictor 2: global mean (single constant)
    preds_const = np.full(n, y.mean())

    # Predictor 3: random Gaussian centered on mean(y)
    preds_rng = rng.normal(y.mean(), y.std(), n)

    # Predictor 4: LOO mean of scrambled y, but evaluated vs TRUE y
    # (this mimics what happens in 5-null: predictions trained on scrambled y, evaluated on truth)

    print(f"N=  {n}, y.mean={y.mean():.3f}, y.std={y.std():.3f}")
    print(f"CCC(predict LOO-mean(true y), true y):              {ccc(y, preds_loo_mean):+.4f}")
    print(f"CCC(predict LOO-mean(scrambled y), true y):         {ccc(y, preds_loo_mean_scr):+.4f}")
    print(f"CCC(predict constant mean, true y):                 {ccc(y, preds_const):+.4f}")
    print(f"CCC(predict Gaussian noise around mean, true y):    {ccc(y, preds_rng):+.4f}")
    print()
    print("LOO anti-bias hypothesis:")
    print(f"  if LGB predicts ~0 residual and Ridge_S1 predicts ~LOO-mean,")
    print(f"  the final pred ≈ LOO-mean → CCC of -{2*y.std()/n/y.std():.3f} to -{4*y.std()/n/y.std():.3f}")
    print(f"  expected magnitude ≈ 2σ_y / (N·σ_y) ≈ {2/n:.4f} × variance scale = small")
    print()

    # Many-shuffle null: characterize the noise floor
    n_shuffles = 50
    cccs = []
    for s in range(n_shuffles):
        rngs = np.random.RandomState(s + 1000)
        y_perm = y.copy(); rngs.shuffle(y_perm)
        preds = np.array([y_perm[np.arange(n) != i].mean() for i in range(n)])
        cccs.append(ccc(y, preds))
    cccs = np.array(cccs)
    print(f"50-shuffle LOO-mean-predictor CCC distribution (vs TRUE y):")
    print(f"  mean={cccs.mean():+.4f}  std={cccs.std():.4f}")
    print(f"  min={cccs.min():+.4f}  max={cccs.max():+.4f}")
    print(f"  P(|CCC|>0.10)={np.mean(np.abs(cccs)>0.10):.2f}")
    print(f"  P(|CCC|>0.20)={np.mean(np.abs(cccs)>0.20):.2f}")
    print(f"  P(|CCC|>0.25)={np.mean(np.abs(cccs)>0.25):.2f}")
    print(f"  95%-CI: [{np.percentile(cccs,2.5):+.4f}, {np.percentile(cccs,97.5):+.4f}]")


if __name__ == "__main__":
    main()
