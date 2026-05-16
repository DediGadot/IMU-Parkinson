"""T1 iter29-A — Pairwise rank + isotonic calibration on T1.

Hypothesis: at N=94, converting regression into ~C(94,2)=4371 pairwise comparisons
multiplies effective training samples ~50× — the highest-leverage data hack we
haven't tried.

Per fold:
  1. Enumerate all (i,j) pairs in the train fold (~3500 pairs at N_tr≈75).
  2. For each pair, build (x_i, x_j) with feature_diff = x_i - x_j and
     feature_avg = (x_i + x_j)/2 → label = sign(y_i - y_j) (drop ties).
  3. Train LGBMClassifier on (X_pair, sign).
  4. For each test subject, score it against ALL training subjects → mean
     P(y_test > y_train_i). This produces a continuous "rank percentile" in [0, 1].
  5. Fit isotonic regression on (train_rank_percentile_OOF, y_train) to map
     rank → T1.
     - For computing train rank percentiles, do ANOTHER inner 5-fold for OOF rankings.
  6. Predict held-out subjects via isotonic-mapped rank.

Comparator: iter5-direct-T1 same fold/seed.

Iter5 Stage 1 (Ridge on H&Y + clinical) is preserved: feed (X_v2, hy, clinical) into
the pair representation by appending hy, cv_yrs, cv_sex, cv_dbs to each subject's row.
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
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import load_pd_data as load_t1_pd_data

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500


def _load_t1_cohort():
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    valid = ~np.isnan(y)
    return sids[valid], X[valid], y[valid], hy[valid]


def _make_pair_features(X: np.ndarray, idx_pairs: np.ndarray) -> np.ndarray:
    """X[i] - X[j] and (X[i] + X[j])/2 stacked → pair features."""
    a = X[idx_pairs[:, 0]]
    b = X[idx_pairs[:, 1]]
    return np.column_stack([a - b, (a + b) / 2.0])


def _train_pairwise_classifier(X: np.ndarray, y: np.ndarray, seed: int):
    """Generate all unordered pairs, train LGB classifier on sign(y_i - y_j)."""
    import lightgbm as lgb

    n = len(y)
    pairs = []
    labels = []
    for i in range(n):
        for j in range(i + 1, n):
            d = y[i] - y[j]
            if abs(d) < 1e-9:
                continue  # drop ties
            pairs.append((i, j))
            labels.append(1 if d > 0 else 0)
    pairs_arr = np.asarray(pairs, dtype=np.int64)
    labels_arr = np.asarray(labels, dtype=np.int64)
    Xp = _make_pair_features(X, pairs_arr)
    clf = lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=15,
        min_data_in_leaf=10, random_state=seed, n_jobs=1, verbose=-1,
    )
    clf.fit(Xp, labels_arr)
    return clf


def _rank_score_against_train(clf, X_test: np.ndarray, X_train: np.ndarray) -> np.ndarray:
    """For each test subject, compute mean P(test > each train) → rank percentile in [0,1]."""
    n_te, n_tr = X_test.shape[0], X_train.shape[0]
    a_idx = np.repeat(np.arange(n_te), n_tr)
    b_idx = np.tile(np.arange(n_tr), n_te)
    a = X_test[a_idx]
    b = X_train[b_idx]
    Xp = np.column_stack([a - b, (a + b) / 2.0])
    probs = clf.predict_proba(Xp)[:, 1].reshape(n_te, n_tr)
    return probs.mean(axis=1)


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def _stage2_residual_pairwise(
    Xtr_sel: np.ndarray, residual_tr: np.ndarray, Xte_sel: np.ndarray, seed: int
) -> np.ndarray:
    """Pairwise rank on the residual target. Outer model is the residual residual_tr;
    we train an LGB binary classifier on sign(residual_i - residual_j), then map
    test rank percentile → residual via isotonic on (inner-OOF-rank, residual_tr).
    """
    n_tr = len(residual_tr)
    # Inner 5-fold OOF rank percentiles for training subjects (for isotonic calibration)
    inner_ranks = np.zeros(n_tr)
    for tr_in, te_in in _kfold(n_tr, seed=seed + 10001):
        clf_in = _train_pairwise_classifier(Xtr_sel[tr_in], residual_tr[tr_in], seed)
        inner_ranks[te_in] = _rank_score_against_train(clf_in, Xtr_sel[te_in], Xtr_sel[tr_in])
    # Outer classifier on full train
    clf_out = _train_pairwise_classifier(Xtr_sel, residual_tr, seed)
    test_ranks = _rank_score_against_train(clf_out, Xte_sel, Xtr_sel)
    # Isotonic calibration: rank → residual
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(inner_ranks, residual_tr)
    return iso.predict(test_ranks).astype(np.float64)


def run_one_seed_pairwise(
    seed: int, feature_set: str = "A3_tier1"
) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y_t1, hy = _load_t1_cohort()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        s2_te = _stage2_residual_pairwise(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed=seed)
        preds[te] = s1_te + s2_te
    return y_t1, preds


def run_one_seed_iter5_baseline(
    seed: int, feature_set: str = "A3_tier1"
) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y_t1, hy = _load_t1_cohort()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
    return y_t1, preds


def run_screen(seeds: tuple[int, ...], feature_set: str) -> Path:
    print(
        f"\n=== T1 iter29-A SCREEN: pairwise rank + isotonic (5-fold, "
        f"feature_set={feature_set}, {len(seeds)} seeds) ===\n",
        flush=True,
    )
    rows = []
    oof_dict = {}
    for seed in seeds:
        t0 = time.time()
        y_t1, preds_pw = run_one_seed_pairwise(seed, feature_set)
        wall_pw = time.time() - t0
        y2, preds_i5 = run_one_seed_iter5_baseline(seed, feature_set)
        assert np.allclose(y_t1, y2)
        c_pw = float(ccc_fn(y_t1, preds_pw))
        c_i5 = float(ccc_fn(y_t1, preds_i5))
        rows.append({
            "seed": seed, "ccc_pairwise": round(c_pw, 4), "ccc_iter5_direct": round(c_i5, 4),
            "delta": round(c_pw - c_i5, 4),
            "mae_pairwise": round(float(mae_fn(y_t1, preds_pw)), 3),
            "r_pairwise": round(float(pearson_r(y_t1, preds_pw)), 4),
            "wall_time_s": round(wall_pw, 1),
        })
        oof_dict[f"seed{seed}_pred"] = preds_pw.tolist()
        oof_dict[f"seed{seed}_iter5"] = preds_i5.tolist()
        oof_dict[f"seed{seed}_y"] = y_t1.tolist()
        print(
            f"  seed={seed}: pairwise CCC={c_pw:.4f} | iter5-direct CCC={c_i5:.4f} | "
            f"Δ={c_pw-c_i5:+.4f} | MAE={rows[-1]['mae_pairwise']:.3f} | "
            f"r={rows[-1]['r_pairwise']:.4f} | {wall_pw:.1f}s",
            flush=True,
        )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter29a_pairwise_5fold_{ts}.csv"
    df.to_csv(out, index=False)

    import json as _json
    out_oof = RESULTS_DIR / f"iter29a_pairwise_5fold_{ts}.oof.json"
    with open(out_oof, "w") as f:
        _json.dump(oof_dict, f)

    print(
        f"\nMean pairwise CCC = {df['ccc_pairwise'].mean():.4f} ± {df['ccc_pairwise'].std():.4f}; "
        f"Mean iter5-direct CCC = {df['ccc_iter5_direct'].mean():.4f} ± {df['ccc_iter5_direct'].std():.4f}; "
        f"Δ̄ = {df['delta'].mean():+.4f}",
        flush=True,
    )
    print(f"Wrote {out}\n      {out_oof}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    args = ap.parse_args()
    run_screen(tuple(args.seeds), args.feature_set)


if __name__ == "__main__":
    main()
