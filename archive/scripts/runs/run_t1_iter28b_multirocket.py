"""T1 iter28-B — MultiROCKET random kernels on raw IMU, T1 target.

Mirrors run_t3_iter28b_multirocket.py:
  Stage 1 = Ridge alpha=1.0 on H&Y + cv_yrs + cv_sex + cv_dbs, target=T1 (sum items 9-14).
  Stage 2 = MultiROCKET features (cached from T3 28b) → standardised RidgeCV on T1-residual.

Cohort = 94 PD subjects with full items 9-14. We sub-select by SID from the 98-subject
T3 MultiROCKET cache (multirocket_features_seed{seed}_k10000.npz), since features are
unsupervised per subject — same cache, same kernels, just SID filter.

Modes: extract | screen.

Comparator on each seed/fold = T1 iter5-direct (Stage1+Stage2-LGB, same target, same fold/seed).
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldNormalizer, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import load_pd_data as load_t1_pd_data
from run_t3_iter28b_multirocket import extract_multirocket_per_subject

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
ALPHA_GRID: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0)
PUBLISHED_T1_LOOCV_CCC = 0.6550
STAGE1_ALPHA = 1.0
K_FEATURES = 500


def _load_t1_cohort() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (sids, X_v2, y_t1, hy) on the 94-PD T1 cohort."""
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y_t1 = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    valid = ~np.isnan(y_t1)
    return sids[valid], X[valid], y_t1[valid], hy[valid]


def _t3_cache_path(seed: int, num_kernels: int) -> Path:
    return RESULTS_DIR / f"multirocket_features_seed{seed}_k{num_kernels}.npz"


def _load_or_extract_features(
    sids: np.ndarray, num_kernels: int, seed: int, n_workers: int
) -> np.ndarray:
    """Sub-select rocket features for `sids` from the T3 98-cohort cache; extract if missing."""
    t3_cache = _t3_cache_path(seed, num_kernels)
    if t3_cache.exists():
        with np.load(t3_cache) as z:
            cached = z["features"].astype(np.float32)
            cached_sids = [str(s) for s in z["sids"].tolist()]
        sid_to_idx = {s: i for i, s in enumerate(cached_sids)}
        try:
            rows = [sid_to_idx[str(s)] for s in sids]
        except KeyError as e:
            raise RuntimeError(f"T1 cohort SID {e} not in T3 cache; rebuild needed.")
        feats = cached[np.asarray(rows, dtype=np.int64)]
        print(f"  T3-cache HIT, sub-selected {feats.shape[0]} of {cached.shape[0]} subjects", flush=True)
        return feats
    # No T3 cache → extract fresh on T1 cohort
    cache_path = RESULTS_DIR / f"multirocket_features_t1_seed{seed}_k{num_kernels}.npz"
    return extract_multirocket_per_subject(
        sids=sids, num_kernels=num_kernels, seed=seed, n_workers=n_workers, cache_path=cache_path,
    )


def stage2_rocket_ridge(
    rocket_tr: np.ndarray, residual_tr: np.ndarray, rocket_te: np.ndarray, seed: int,
) -> tuple[np.ndarray, float]:
    nrm = FoldNormalizer.fit(rocket_tr)
    Xtr, Xte = nrm.transform(rocket_tr), nrm.transform(rocket_te)
    m = RidgeCV(alphas=list(ALPHA_GRID), cv=5, fit_intercept=True)
    m.fit(Xtr, residual_tr)
    return m.predict(Xte), float(m.alpha_)


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def run_one_5fold(
    seed: int, feature_set: str, rocket_feats: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    sids, _Xv2, y_t1, hy = _load_t1_cohort()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    alphas: list[float] = []
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        s2_te, a = stage2_rocket_ridge(rocket_feats[tr], y_t1[tr] - s1_tr, rocket_feats[te], seed)
        preds[te] = s1_te + s2_te
        alphas.append(a)
    return y_t1, preds, alphas


def _iter5_direct_t1_kfold(seed: int, feature_set: str) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y_t1, hy = _load_t1_cohort()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed)
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
    return y_t1, preds


def mode_extract(seeds, num_kernels, n_workers) -> None:
    sids, _X, _y, _hy = _load_t1_cohort()
    print(f"\n=== T1 iter28-B EXTRACT (cohort N={len(sids)}, num_kernels={num_kernels}) ===\n", flush=True)
    for seed in seeds:
        feats = _load_or_extract_features(sids, num_kernels, seed, n_workers)
        print(f"  seed={seed}: features shape = {feats.shape}", flush=True)


def mode_screen(seeds, num_kernels, n_workers, feature_set: str = "A3_tier1") -> Path:
    sids, _X, _y, _hy = _load_t1_cohort()
    print(
        f"\n=== T1 iter28-B 5-FOLD SCREEN (cohort N={len(sids)}, "
        f"{len(seeds)} seeds, num_kernels={num_kernels}, stage2=RidgeCV) ===\n",
        flush=True,
    )
    rows = []
    for seed in seeds:
        feats = _load_or_extract_features(sids, num_kernels, seed, n_workers)
        t0 = time.time()
        y_t1, preds_rocket, alphas = run_one_5fold(seed, feature_set, feats)
        elapsed = time.time() - t0
        y_ref, preds_iter5 = _iter5_direct_t1_kfold(seed, feature_set)
        assert np.allclose(y_ref, y_t1)
        c_r = float(ccc_fn(y_t1, preds_rocket))
        c_i5 = float(ccc_fn(y_t1, preds_iter5))
        rows.append({
            "seed": seed, "variant": "iter5_stage1+rocket_stage2",
            "feature_set": feature_set, "stage2": "ridgecv",
            "n_rocket_features": int(feats.shape[1]),
            "ccc": round(c_r, 4),
            "mae": round(float(mae_fn(y_t1, preds_rocket)), 3),
            "r": round(float(pearson_r(y_t1, preds_rocket)), 4),
            "alpha_mean": round(float(np.mean(alphas)), 4),
            "alpha_median": round(float(np.median(alphas)), 4),
            "wall_time_s": round(elapsed, 1),
            "iter5_direct_t1_5fold_ccc": round(c_i5, 4),
            "delta_vs_iter5_direct": round(c_r - c_i5, 4),
        })
        print(
            f"  seed={seed}: ROCKET-T1 CCC={c_r:.4f} | iter5-direct-T1 CCC={c_i5:.4f} | "
            f"Δ={c_r-c_i5:+.4f} | MAE={rows[-1]['mae']:.3f} | "
            f"alpha_med={rows[-1]['alpha_median']:.3g} | {elapsed:.1f}s",
            flush=True,
        )
    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter28b_t1_multirocket_5fold_{ts}.csv"
    df.to_csv(out, index=False)
    print(
        f"\nMean ROCKET-T1 CCC = {df['ccc'].mean():.4f} ± {df['ccc'].std():.4f}; "
        f"Mean iter5-direct-T1 CCC = {df['iter5_direct_t1_5fold_ccc'].mean():.4f} ± "
        f"{df['iter5_direct_t1_5fold_ccc'].std():.4f}; "
        f"Δ̄ = {df['delta_vs_iter5_direct'].mean():+.4f}",
        flush=True,
    )
    print(f"Wrote {out}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["extract", "screen"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--num_kernels", type=int, default=10000)
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("ITER28B_T1_WORKERS", 8)))
    ap.add_argument("--feature_set", default="A3_tier1")
    args = ap.parse_args()

    seeds = tuple(args.seeds)
    if args.mode == "extract":
        mode_extract(seeds, args.num_kernels, args.n_workers)
    elif args.mode == "screen":
        mode_screen(seeds, args.num_kernels, args.n_workers, feature_set=args.feature_set)


if __name__ == "__main__":
    main()
