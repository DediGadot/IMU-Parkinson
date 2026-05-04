"""Shared utilities for strictly-inductive WearGait-PD experiments.

Every helper here enforces the train/test firewall: anything that "fits" must
be passed only training-fold data, and the corresponding "transform" is
applied to test data at inference. No global statistics. No cohort-wide caches
get fitted from outer-test data.

This is the single source of truth for the inductive contract — `run_*.py`
scripts must import these helpers and not reimplement the gating logic.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import StratifiedShuffleSplit, train_test_split
from sklearn.preprocessing import StandardScaler

# ── METRICS (canonical, polyfit-based slope, matches eval_utils) ──────────────


def ccc(y_true, y_pred) -> float:
    yt, yp = np.asarray(y_true, np.float64), np.asarray(y_pred, np.float64)
    if yt.size < 2 or yt.std() < 1e-9 or yp.std() < 1e-9:
        return 0.0
    cov = float(np.mean((yt - yt.mean()) * (yp - yp.mean())))
    return (2 * cov) / (yt.var() + yp.var() + (yt.mean() - yp.mean()) ** 2)


def cal_slope(y_true, y_pred) -> float:
    yt, yp = np.asarray(y_true, np.float64), np.asarray(y_pred, np.float64)
    if yt.size < 3 or yt.std() < 1e-8:
        return 0.0
    return float(np.polyfit(yt, yp, 1)[0])


def mae(y_true, y_pred) -> float:
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def pearson_r(y_true, y_pred) -> float:
    if np.std(y_true) < 1e-9 or np.std(y_pred) < 1e-9:
        return 0.0
    return float(np.corrcoef(y_true, y_pred)[0, 1])


def full_metrics(y_true, y_pred, label: str = "") -> dict:
    yt = np.asarray(y_true, np.float64)
    yp = np.asarray(y_pred, np.float64)
    return {
        "n": int(len(yt)),
        "ccc": round(ccc(yt, yp), 4),
        "cal_slope": round(cal_slope(yt, yp), 4),
        "mae": round(mae(yt, yp), 4),
        "r": round(pearson_r(yt, yp), 4),
        "pred_mean": round(float(yp.mean()), 3),
        "pred_std": round(float(yp.std()), 3),
        "true_mean": round(float(yt.mean()), 3),
        "true_std": round(float(yt.std()), 3),
        "label": label,
    }


# ── FOLD-LOCAL FIT/TRANSFORM HELPERS ──────────────────────────────────────────


@dataclass(frozen=True)
class FoldImputer:
    """Fit-on-train, transform-on-test imputer. NO global stats."""
    medians: np.ndarray  # shape (n_features,)

    @classmethod
    def fit(cls, X_train: np.ndarray) -> "FoldImputer":
        return cls(medians=np.nanmedian(X_train, axis=0))

    def transform(self, X: np.ndarray) -> np.ndarray:
        out = X.copy()
        nan_mask = np.isnan(out)
        if nan_mask.any():
            for j in range(out.shape[1]):
                col_nan = nan_mask[:, j]
                if col_nan.any():
                    out[col_nan, j] = self.medians[j]
        return out


@dataclass(frozen=True)
class FoldNormalizer:
    """Standard-scaler fit on train fold only. NEVER call with test data in fit()."""
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, X_train: np.ndarray, eps: float = 1e-8) -> "FoldNormalizer":
        m = X_train.mean(axis=0)
        s = X_train.std(axis=0)
        s = np.where(s < eps, 1.0, s)
        return cls(mean=m, std=s)

    def transform(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / self.std


@dataclass(frozen=True)
class FoldSeverityBins:
    """Severity quantile bins fit on TRAIN targets only. Used for stratified
    sampling, contrastive grouping, etc. — never on the held-out target."""
    edges: np.ndarray  # shape (n_bins-1,)

    @classmethod
    def fit(cls, y_train: np.ndarray, n_bins: int = 4) -> "FoldSeverityBins":
        qs = np.linspace(0, 100, n_bins + 1)[1:-1]
        return cls(edges=np.percentile(y_train, qs))

    def transform(self, y: np.ndarray) -> np.ndarray:
        return np.digitize(y, self.edges)


def fit_demo_ridge(X_demo_train: np.ndarray, y_train: np.ndarray,
                   alpha: float = 1.0, seed: int = 42) -> Ridge:
    """Train-fold ridge on demographic features. Used for B4 baseline AND
    for the demographics-first-residual experiment (Phase 2.1)."""
    m = Ridge(alpha=alpha, random_state=seed)
    m.fit(X_demo_train, y_train)
    return m


# ── 5-NULL TEST GATE (codex #14) ──────────────────────────────────────────────
# Run this gate against any new experiment before reporting a number.


def _check_subject_disjoint(train_sids: Sequence[str], test_sids: Sequence[str]) -> None:
    overlap = set(train_sids) & set(test_sids)
    assert not overlap, f"SUBJECT-LEVEL LEAK: {len(overlap)} SIDs in both folds: {sorted(overlap)[:5]}..."


def null_scrambled_label(predict_fn, X_train: np.ndarray, y_train: np.ndarray,
                         X_test: np.ndarray, seed: int = 42) -> dict:
    """Null #1: shuffle PD targets within train fold; expect test CCC ≈ 0.

    predict_fn: callable (X_train, y_train, X_test) -> y_pred_test
    """
    rng = np.random.RandomState(seed)
    y_shuffled = y_train.copy()
    rng.shuffle(y_shuffled)
    return {"name": "scrambled_label", "y_pred": predict_fn(X_train, y_shuffled, X_test)}


def null_subject_id_shuffle(predict_fn, X_train_loaded_by_sid_fn,
                            train_sids: Sequence[str], y_train: np.ndarray,
                            X_test: np.ndarray, seed: int = 42) -> dict:
    """Null #2: shuffle the SID→features mapping before any cache join.

    Catches leaks via cache join keys (e.g., a per-subject normalisation file
    keyed by SID would still match by SID after target shuffle, but not after
    SID shuffle).
    """
    rng = np.random.RandomState(seed)
    shuffled_sids = list(train_sids)
    rng.shuffle(shuffled_sids)
    X_train_shuffled = X_train_loaded_by_sid_fn(shuffled_sids)
    return {"name": "subject_id_shuffle",
            "y_pred": predict_fn(X_train_shuffled, y_train, X_test)}


def null_canary_feature(predict_fn, X_train: np.ndarray, y_train: np.ndarray,
                        X_test: np.ndarray, canary_value: float = 999.0) -> dict:
    """Null #3: inject a canary feature ONLY into the test fold; the model
    must ignore it (it never saw this feature in training)."""
    n_train, n_feats = X_train.shape
    canary_train = np.zeros((n_train, 1), dtype=X_train.dtype)
    canary_test = np.full((X_test.shape[0], 1), canary_value, dtype=X_test.dtype)
    Xt = np.hstack([X_train, canary_train])
    Xe = np.hstack([X_test, canary_test])
    return {"name": "canary_feature", "y_pred": predict_fn(Xt, y_train, Xe)}


def assert_library_excludes_test(library_sids: Sequence[str], test_sid: str) -> None:
    """Null #4: any retrieval/kNN library MUST exclude the test subject."""
    assert test_sid not in library_sids, (
        f"RETRIEVAL LEAK: test subject {test_sid} is in retrieval library of "
        f"size {len(library_sids)}"
    )


def transductive_sanity_predict(predict_fn, X_all: np.ndarray, y_all: np.ndarray,
                                test_idx: int) -> dict:
    """Null #5 (sanity): intentionally LEAK target. Train on (X_all, y_all)
    including test_idx, predict test_idx. CCC across folds should approach
    the leaky ceiling (~0.85 on T1). Proves the architecture CAN learn."""
    return {"name": "transductive_sanity",
            "y_pred": predict_fn(X_all, y_all, X_all[test_idx:test_idx + 1])}


def run_null_test_gate(
    predict_fn,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    train_sids: Sequence[str] = None,
    test_sid: str = None,
) -> dict:
    """Run the full 5-null gate (where applicable) and return a dict of CCCs.

    Returns: {scrambled_label_ccc, canary_feature_ccc, ...}
    Reportable iff scrambled_label_ccc and canary_feature_ccc are both ≈ 0.
    """
    results = {}

    # Null #1: scrambled label
    sc = null_scrambled_label(predict_fn, X_train, y_train, X_test)
    results["scrambled_label_ccc"] = round(ccc(y_test, sc["y_pred"]), 4)

    # Null #3: canary feature
    cf = null_canary_feature(predict_fn, X_train, y_train, X_test)
    results["canary_feature_ccc"] = round(ccc(y_test, cf["y_pred"]), 4)

    # Subject-disjoint check (cheap, always run)
    if train_sids is not None and test_sid is not None:
        _check_subject_disjoint(train_sids, [test_sid])
        results["subject_disjoint_passed"] = True

    return results


# ── PER-FOLD SPLIT (matches run_inductive_ablation.py for comparability) ──────


def gen_5fold_split(pd_merged: pd.DataFrame, target_key: str, n_splits: int = 5):
    """Stratified 5-fold split. Yields (split_i, train_sids, test_sids).

    Mirrors the published `gen_split` from run_compression_ablation.py so new
    experiment numbers are directly comparable.
    """
    from sklearn.model_selection import train_test_split as _tts
    target_col = f"{target_key}_target"
    y = pd_merged[target_col].values
    sids = pd_merged["sid"].values
    bins = np.digitize(y, np.percentile(y, [25, 50, 75]))
    for split_i in range(1, n_splits + 1):
        train_sids, test_sids = _tts(
            sids, test_size=0.2, random_state=split_i, stratify=bins,
        )
        yield split_i, train_sids.tolist(), test_sids.tolist()


# ── PRE-REGISTRATION (lockbox protocol) ───────────────────────────────────────


def write_preregistration(spec: dict, results_dir: Path) -> Path:
    """Write a pre-registration JSON for the LOOCV-headline pipeline."""
    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = results_dir / f"preregistration_{timestamp}.json"
    with open(path, "w") as f:
        json.dump(spec, f, indent=2, default=str)
    return path
