"""Feature-descriptiveness metric library.

Two complementary metrics — both model-free, fold-local, conditional on the
canonical pipeline's leave-one-out prediction:

    pdCor(F; y | yhat_OOF)    — partial distance correlation (Szekely-Rizzo 2014)
    Δ I_imb(V2 vs V2+F → y)   — Information Imbalance (Glielmo PNAS Nexus 2022)

Decision rule for "F is descriptive":
    (95% bootstrap CI of fold-aggregated pdCor excludes 0)
    AND (permutation p < 0.01 / k Bonferroni for k feature blocks)
    AND (Δ I_imb > 0 with bootstrap CI excluding 0)

NO test-fold y enters the metric for that fold. NO learner. NO selection rule.
The OOF prediction is the conditioner; it is leak-clean by construction (per
F65 audit of the canonical iter34 / iter47 chains).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import dcor
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist, pdist, squareform


# ── Partial Distance Correlation (model-free, Szekely-Rizzo Annals of Statistics 2014) ──


def partial_distance_correlation(X: np.ndarray, Y: np.ndarray, Z: np.ndarray) -> float:
    """pdCor(X; Y | Z) using the dcor library.

    Inputs can be 1-D vectors or 2-D arrays (N x d). Returns the partial
    distance correlation in [-1, 1] (negative values are an artifact of the
    estimator below the 0 floor; treat |pdcor| as the magnitude).
    """
    X = np.atleast_2d(X).reshape(len(X), -1).astype(np.float64)
    Y = np.atleast_2d(Y).reshape(len(Y), -1).astype(np.float64)
    Z = np.atleast_2d(Z).reshape(len(Z), -1).astype(np.float64)
    # dcor.partial_distance_correlation expects N x d arrays.
    return float(dcor.partial_distance_correlation(X, Y, Z))


def distance_correlation(X: np.ndarray, Y: np.ndarray) -> float:
    X = np.atleast_2d(X).reshape(len(X), -1).astype(np.float64)
    Y = np.atleast_2d(Y).reshape(len(Y), -1).astype(np.float64)
    return float(dcor.distance_correlation(X, Y))


# ── Information Imbalance (Glielmo PNAS Nexus 2022) ──


def _pairwise_rank_matrix(D: np.ndarray) -> np.ndarray:
    """For each row i, rank columns by distance (0 = self, 1 = nearest neighbor, ...)."""
    n = D.shape[0]
    # argsort across each row, then invert to get ranks
    order = np.argsort(D, axis=1, kind="quicksort")
    ranks = np.empty_like(order)
    arange = np.arange(n)
    for i in range(n):
        ranks[i, order[i]] = arange
    return ranks


def information_imbalance(distances_A: np.ndarray, distances_B: np.ndarray, k: int = 1) -> float:
    """I_imb(A → B): how well does A's nearest-neighbor structure predict B's?

    Following Glielmo et al. PNAS Nexus 2022. Low value (~0) = A retains all
    information about B; high value (~1) = independent. Symmetric directional
    measure: I_imb(A→B) ≠ I_imb(B→A) in general.

    For k=1, the formula is:
        I_imb(A→B) = (2/N) × (1/N) × Σ_i rank_B(NN_A^1(i))

    where NN_A^1(i) is the index of the k=1 nearest neighbor of i under A's
    distance, and rank_B(j) is j's rank as a neighbor of i under B (1 = closest).
    """
    n = distances_A.shape[0]
    assert distances_B.shape[0] == n
    # Zero the diagonal so a point isn't its own nearest neighbor
    DA = distances_A.copy()
    np.fill_diagonal(DA, np.inf)
    DB = distances_B.copy()
    np.fill_diagonal(DB, np.inf)

    # k=1 nearest neighbor in A
    nn_A = np.argmin(DA, axis=1)

    # Rank of nn_A(i) in B's distance ordering (1-based, ignoring self)
    rank_B = _pairwise_rank_matrix(DB)  # rank 0 = self (since diagonals are inf, self lands at rank n-1 actually)
    # Actually let's recompute ranks ignoring the inf diagonal:
    n = DB.shape[0]
    rank_B = np.zeros((n, n), dtype=int)
    for i in range(n):
        # Order other points by distance; rank 1 = closest non-self
        others = np.argsort(DB[i])  # inf is at the end (self)
        for r, j in enumerate(others, start=1):
            rank_B[i, j] = r
    # Average rank of the A-nearest-neighbor under B
    mean_rank = np.mean([rank_B[i, nn_A[i]] for i in range(n)])
    # Normalize to [0, 2]: 2 × mean_rank / N
    return float(2.0 * mean_rank / n)


def euclidean_distances(X: np.ndarray) -> np.ndarray:
    """N x N Euclidean distance matrix."""
    X = np.atleast_2d(X).astype(np.float64)
    if X.shape[0] == 1:
        X = X.T
    return squareform(pdist(X, metric="euclidean"))


# ── Bootstrap + permutation utilities ──


def bootstrap_ci(values: np.ndarray, n_boot: int = 2000, alpha: float = 0.05, rng_seed: int = 42) -> tuple[float, float, float]:
    """Bootstrap (median, lower_CI, upper_CI). Resamples per-fold values."""
    rng = np.random.RandomState(rng_seed)
    values = np.asarray(values, np.float64)
    n = len(values)
    boots = np.array([np.median(values[rng.randint(0, n, n)]) for _ in range(n_boot)])
    lo = float(np.quantile(boots, alpha / 2))
    hi = float(np.quantile(boots, 1 - alpha / 2))
    return float(np.median(values)), lo, hi


def permutation_pvalue_pdcor(F: np.ndarray, y: np.ndarray, z: np.ndarray, n_perm: int = 1000, rng_seed: int = 42) -> tuple[float, float]:
    """Two-sided permutation test on pdCor(F; y | z) by shuffling y.

    Returns (observed_pdcor, p_value).
    """
    rng = np.random.RandomState(rng_seed)
    observed = partial_distance_correlation(F, y, z)
    null = np.empty(n_perm, dtype=np.float64)
    for p in range(n_perm):
        y_perm = rng.permutation(y)
        null[p] = partial_distance_correlation(F, y_perm, z)
    # Right-tail (we care about positive pdCor, i.e., F adds info)
    p_val = float((np.sum(null >= observed) + 1) / (n_perm + 1))
    return float(observed), p_val


# ── Fold-local orchestration ──


@dataclass
class FoldScore:
    fold_idx: int
    pdcor: float
    iimb_v2_to_y: float
    iimb_v2plusF_to_y: float
    delta_iimb: float  # = iimb_v2_to_y - iimb_v2plusF_to_y (positive = F adds info)


def score_feature_block(
    F: np.ndarray,                    # N x d_F feature matrix for the candidate block
    y: np.ndarray,                    # N target values
    yhat_canonical_oof: np.ndarray,   # N OOF predictions from canonical pipeline
    V2: np.ndarray,                   # N x d_V2 V2 baseline features
    n_folds: int | None = None,       # if None: LOOCV
) -> dict:
    """Score a candidate feature block via pdCor + Δ I_imb, fold-locally.

    Returns a dict with per-fold scores, bootstrap CIs, and permutation p-value
    (computed on the full N for the cohort-level p; per-fold is bootstrap CI).
    """
    n = len(y)
    if n_folds is None:
        n_folds = n
    fold_idx = np.arange(n) % n_folds

    pdcors: list[float] = []
    iimb_v2_to_y_list: list[float] = []
    iimb_v2plusF_to_y_list: list[float] = []

    # Fold-local pdCor + Δ I_imb. For LOOCV, the "train set" for fold i is
    # everyone except i; the metric is computed on N-1 training rows.
    for i_fold in range(n_folds):
        mask_train = fold_idx != i_fold
        if mask_train.sum() < 10:
            continue
        F_tr = F[mask_train]
        y_tr = y[mask_train]
        z_tr = yhat_canonical_oof[mask_train]
        V2_tr = V2[mask_train]

        # pdCor on the training-fold rows only
        pd_score = partial_distance_correlation(F_tr, y_tr, z_tr)
        pdcors.append(pd_score)

        # Information Imbalance from V2 and V2+F to y, on training-fold rows only
        D_V2 = euclidean_distances(V2_tr)
        D_V2F = euclidean_distances(np.hstack([V2_tr, F_tr]))
        D_y = euclidean_distances(y_tr.reshape(-1, 1))
        ii_v2 = information_imbalance(D_V2, D_y)
        ii_v2f = information_imbalance(D_V2F, D_y)
        iimb_v2_to_y_list.append(ii_v2)
        iimb_v2plusF_to_y_list.append(ii_v2f)

    pdcors = np.array(pdcors)
    deltas = np.array(iimb_v2_to_y_list) - np.array(iimb_v2plusF_to_y_list)

    pdc_med, pdc_lo, pdc_hi = bootstrap_ci(pdcors)
    di_med, di_lo, di_hi = bootstrap_ci(deltas)

    # Cohort-level pdCor + permutation null (whole-N)
    cohort_pdcor, cohort_p = permutation_pvalue_pdcor(F, y, yhat_canonical_oof, n_perm=1000)

    return {
        "n_folds": int(n_folds),
        "per_fold_pdcor": pdcors.tolist(),
        "per_fold_delta_iimb": deltas.tolist(),
        "pdcor_median": pdc_med,
        "pdcor_ci_lower": pdc_lo,
        "pdcor_ci_upper": pdc_hi,
        "delta_iimb_median": di_med,
        "delta_iimb_ci_lower": di_lo,
        "delta_iimb_ci_upper": di_hi,
        "cohort_pdcor": cohort_pdcor,
        "cohort_perm_pvalue": cohort_p,
        "decision_pdcor_ci_excludes_zero": bool(pdc_lo > 0),
        "decision_delta_iimb_ci_excludes_zero": bool(di_lo > 0),
        "decision_perm_p_lt_001": bool(cohort_p < 0.01),
    }


def load_t1_canonical_oof(path: str = "results/t1_iter34_per_item_oof_20260511_044242.npz") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load T1 iter34 hygiene-corrected OOF. Returns (sids, y_t1, t1_sum_pred)."""
    d = np.load(path, allow_pickle=True)
    return np.asarray(d["sids"]), np.asarray(d["y_t1"], np.float64), np.asarray(d["t1_sum_pred"], np.float64)


def load_t3_canonical_oof(path: str = "results/iter47_invalidcode_subject_preds_20260508_194605.csv") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load T3 iter47 valid-range cohort OOF. Returns (sids, y_t3, t3_pred)."""
    df = pd.read_csv(path)
    df = df[(df["stage2_policy"] == "stage2_current") & (df["cohort"] == "drop_allmissing_validrange")].copy()
    df = df.drop_duplicates(subset=["sid"]).reset_index(drop=True)
    return df["sid"].to_numpy(), df["y_true_validrange"].to_numpy(np.float64), df["y_pred"].to_numpy(np.float64)


def align_features_to_oof(feature_df: pd.DataFrame, oof_sids: np.ndarray, sid_col: str = "sid") -> tuple[np.ndarray, np.ndarray]:
    """Return (X, mask) aligned to oof_sids order. mask[i] = True iff feature_df has sid oof_sids[i]."""
    feat_indexed = feature_df.set_index(feature_df[sid_col].astype(str))
    rows = []
    mask = []
    for s in oof_sids:
        s = str(s)
        if s in feat_indexed.index:
            rows.append(feat_indexed.loc[s].drop(sid_col, errors="ignore").to_numpy(np.float64))
            mask.append(True)
        else:
            rows.append(None)
            mask.append(False)
    mask = np.asarray(mask)
    if not mask.all():
        # Fill missing rows with NaN then median-impute against the available rows
        d = feat_indexed.drop(columns=[sid_col], errors="ignore").to_numpy(np.float64)
        med = np.nanmedian(d, axis=0)
        rows = [r if r is not None else med for r in rows]
    X = np.vstack(rows)
    # NaN-safe imputation by column median
    col_med = np.nanmedian(X, axis=0)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(col_med, inds[1])
    return X, mask


if __name__ == "__main__":
    # Smoke test
    rng = np.random.RandomState(42)
    N = 92
    V2 = rng.randn(N, 50)
    yhat = V2[:, 0] + rng.randn(N) * 0.5     # canonical OOF
    y = yhat + rng.randn(N) * 0.3            # truth
    F_redundant = V2[:, :3] + rng.randn(N, 3) * 0.1   # mostly V2 → should score ≈ 0
    F_orthogonal = rng.randn(N, 3)                     # independent → score ≈ 0
    F_complementary = (y - yhat).reshape(-1, 1) + rng.randn(N, 3) * 0.5  # in residual subspace → high

    for label, F in [("redundant", F_redundant), ("orthogonal", F_orthogonal), ("complementary", F_complementary)]:
        out = score_feature_block(F, y, yhat, V2, n_folds=N)  # LOOCV
        print(f"{label:>15}: pdcor_med={out['pdcor_median']:+.3f} CI=[{out['pdcor_ci_lower']:+.3f},{out['pdcor_ci_upper']:+.3f}] "
              f"Δ_iimb_med={out['delta_iimb_median']:+.3f} CI=[{out['delta_iimb_ci_lower']:+.3f},{out['delta_iimb_ci_upper']:+.3f}] "
              f"cohort_p={out['cohort_perm_pvalue']:.4f} "
              f"PASS={out['decision_pdcor_ci_excludes_zero'] and out['decision_perm_p_lt_001']}")
