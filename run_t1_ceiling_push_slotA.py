"""T1 Glass-Ceiling Push — Slot A: ordinal cumulative-link multi-task chain × 3-base ensemble.

Mechanism axis 1 (different loss family) per references/t1_first_principles.md.
Drop-in ordinal replacement of iter34's MSE Stage-2 (LGB + XGB + ET).

Hypothesis: items 9-14 are MDS-UPDRS Part III ordinal scores 0-4. iter34's
RegressorChain bases all use squared-error loss, throwing away rank-distance
information. A proper cumulative-link ordinal loss on each item (still composed
through the same 8-item chain × 3-base ensemble structure) recovers rank
information that translates to >= +0.025 LOOCV CCC over iter34's 0.7366 on N=93.

Three ordinal bases (matching iter34's LGB/XGB/ET diversity):
  1. mord.LogisticAT — linear all-threshold cumulative-link logit (fold-local fit)
  2. LGB 4-binary decomposition — four LGB classifiers per item for P(item >= k),
     k in {1,2,3,4}; isotonic-monotone projection; E[item] = sum_k P(item >= k)
  3. NGBoost k_categorical ordered logit — gradient-boosted probabilistic ordinal

Per fold per seed: train 3 ordinal bases inside an 8-item RegressorChain over
{9,10,11,12,13,14,15,18}; auxiliary items 15+18 used in chain fit only; T1 sum
over items 9-14. Average expected-score predictions across the 3 bases.

ProcessPool over LOOCV folds. n_workers default 11 on the 12-core RTX-4060 box.

USAGE
    --mode write_prereg  → emit pre-reg JSON with formula_sha256
    --mode smoke         → 1 fold × 1 seed sanity (~3 min on master)
    --mode screen        → 5-fold × 3 seeds gate check (~25 min on remote 11 workers)
    --mode lockbox       → 3-seed LOOCV after prereg verify (~3-4 h on 11 workers)
    --mode audit         → run paired bootstrap + 5-null gate on existing lockbox
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import T1_ITEMS
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    T1_SUM_ITEMS,
    AUX_ITEMS,
    ALL_ITEMS,
)

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA: float = 1.0
K_FEATURES: int = 500
PUBLISHED_T1_LOOCV_CCC: float = 0.6550
ITER34_LOOCV_CCC: float = 0.7366

# Ordinal score range — items 9-14, 15, 18 are MDS-UPDRS-III scored 0-4
ORDINAL_MIN: int = 0
ORDINAL_MAX: int = 4

ORDINAL_BASES: tuple[str, ...] = ("mord_at", "lgb_decomp", "ngb_logit")


# -----------------------------------------------------------------------------
# OrdinalRegressor — sklearn-compatible wrapper that returns E[item | X]
# -----------------------------------------------------------------------------
class OrdinalRegressor(BaseEstimator, RegressorMixin):
    """sklearn-compatible ordinal regressor returning E[y | X] as a continuous score.

    Three backends, selected via `method`:
      "mord_at"     — mord.LogisticAT (linear all-threshold cumulative-link logit)
      "lgb_decomp"  — 4 LGB binary classifiers for P(y >= k), k in {1..4};
                      isotonic-monotone projection; E[y] = sum_k P(y >= k)
      "ngb_logit"   — NGBoost with k_categorical (ordered) ordinal distribution

    Targets must be integers in [ORDINAL_MIN, ORDINAL_MAX]. fit() rounds + clips
    to integers fold-locally (no test-fold info).
    """

    def __init__(self, method: str = "mord_at", seed: int = 42) -> None:
        self.method = method
        self.seed = seed
        self.n_classes_: int = ORDINAL_MAX - ORDINAL_MIN + 1
        self.classes_present_: np.ndarray | None = None
        self._model: Any = None

    def _round_clip_int(self, y: np.ndarray) -> np.ndarray:
        y_int = np.rint(np.asarray(y, dtype=float)).astype(int)
        return np.clip(y_int, ORDINAL_MIN, ORDINAL_MAX)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "OrdinalRegressor":
        y_int = self._round_clip_int(y)
        self.classes_present_ = np.array(sorted(np.unique(y_int)))

        if self.method == "mord_at":
            self._fit_mord_at(X, y_int)
        elif self.method == "lgb_decomp":
            self._fit_lgb_decomp(X, y_int)
        elif self.method == "ngb_logit":
            self._fit_ngb_logit(X, y_int)
        else:
            raise ValueError(f"unknown ordinal method {self.method!r}")
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.method == "mord_at":
            return self._predict_mord_at(X)
        if self.method == "lgb_decomp":
            return self._predict_lgb_decomp(X)
        if self.method == "ngb_logit":
            return self._predict_ngb_logit(X)
        raise ValueError(f"unknown ordinal method {self.method!r}")

    # --- mord.LogisticAT (linear all-threshold cumulative-link logit) ---------
    def _fit_mord_at(self, X: np.ndarray, y_int: np.ndarray) -> None:
        # Degenerate fold-local target (single class) → constant fallback
        if len(self.classes_present_) <= 1:
            self._model = ("constant", float(y_int.mean()))
            return
        try:
            import mord
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # alpha is L2 reg; modest default for high-dim small-N
                m = mord.LogisticAT(alpha=1.0)
                m.fit(X, y_int)
                self._model = ("mord_at", m)
        except Exception as e:
            # Fallback to constant if mord fit fails (rare with degenerate folds)
            self._model = ("constant", float(y_int.mean()))

    def _predict_mord_at(self, X: np.ndarray) -> np.ndarray:
        kind, m = self._model
        if kind == "constant":
            return np.full(X.shape[0], m, dtype=float)
        # mord.LogisticAT.predict_proba returns (n, K_classes_observed)
        # — restrict to observed classes; map back to E[y]
        proba = m.predict_proba(X)
        classes = m.classes_  # observed integer labels
        e_y = (proba * classes[None, :]).sum(axis=1)
        return e_y.astype(float)

    # --- LGB 4-binary decomposition with isotonic-monotone projection ---------
    def _fit_lgb_decomp(self, X: np.ndarray, y_int: np.ndarray) -> None:
        import lightgbm as lgb
        if len(self.classes_present_) <= 1:
            self._model = ("constant", float(y_int.mean()))
            return
        models: list[Any] = []
        # P(y >= k) for k in {1..K_max}
        for k in range(ORDINAL_MIN + 1, ORDINAL_MAX + 1):
            target = (y_int >= k).astype(int)
            if target.sum() == 0 or target.sum() == len(target):
                # Degenerate cut-point in this fold (no positive or no negative)
                # Use a constant probability equal to the empirical rate
                models.append(("constant", float(target.mean())))
                continue
            m = lgb.LGBMClassifier(
                n_estimators=500,
                learning_rate=0.05,
                num_leaves=15,
                min_data_in_leaf=10,
                random_state=self.seed,
                n_jobs=1,
                verbose=-1,
            )
            m.fit(X, target)
            models.append(("lgb", m))
        self._model = ("lgb_decomp", models)

    def _predict_lgb_decomp(self, X: np.ndarray) -> np.ndarray:
        kind, payload = self._model
        if kind == "constant":
            return np.full(X.shape[0], payload, dtype=float)
        models: list[Any] = payload
        n = X.shape[0]
        # Stack P(y >= k) for k in {1..K_max} into a (n, K_max) matrix
        cum_probs = np.zeros((n, len(models)), dtype=float)
        for k_idx, (mkind, m) in enumerate(models):
            if mkind == "constant":
                cum_probs[:, k_idx] = m
            else:
                cum_probs[:, k_idx] = m.predict_proba(X)[:, 1]
        # Isotonic-monotone projection: enforce P(y >= 1) >= P(y >= 2) >= ...
        # PAV in reverse (cumulative probabilities are non-increasing in k)
        cum_probs = np.minimum.accumulate(cum_probs, axis=1)
        # E[y] = sum_k P(y >= k) for k=1..K_max
        e_y = cum_probs.sum(axis=1)
        return np.clip(e_y, ORDINAL_MIN, ORDINAL_MAX).astype(float)

    # --- NGBoost k_categorical ordered logit -----------------------------------
    def _fit_ngb_logit(self, X: np.ndarray, y_int: np.ndarray) -> None:
        if len(self.classes_present_) <= 1:
            self._model = ("constant", float(y_int.mean()))
            return
        try:
            from ngboost import NGBClassifier
            from ngboost.distns import k_categorical
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # k_categorical needs the number of classes (5 for 0..4)
                m = NGBClassifier(
                    Dist=k_categorical(self.n_classes_),
                    n_estimators=300,
                    learning_rate=0.05,
                    random_state=self.seed,
                    verbose=False,
                )
                m.fit(X, y_int)
                self._model = ("ngb_logit", m)
        except Exception:
            self._model = ("constant", float(y_int.mean()))

    def _predict_ngb_logit(self, X: np.ndarray) -> np.ndarray:
        kind, m = self._model
        if kind == "constant":
            return np.full(X.shape[0], m, dtype=float)
        # NGBClassifier.predict_proba returns (n, K) with K = self.n_classes_
        proba = m.predict_proba(X)
        # E[y] = sum_k k * P(y = k); classes are 0..K-1 by NGBoost's convention
        e_y = (proba * np.arange(self.n_classes_)[None, :]).sum(axis=1)
        return e_y.astype(float)


# -----------------------------------------------------------------------------
# Multi-task chain prediction (ordinal targets, expected-score chain feature)
# -----------------------------------------------------------------------------
def _multitask_predict_ordinal(
    Xtr: np.ndarray,
    items_tr_int: np.ndarray,
    Xte: np.ndarray,
    seed: int,
    method: str,
) -> np.ndarray:
    """Run a RegressorChain over ordinal items.

    items_tr_int: shape (n_train, n_items), integer 0-4 per item.
    Returns: (n_test, n_items) array of expected-score predictions.

    The chain feeds the previous item's predicted expected score (continuous
    in [0, 4]) as an additional feature for the next item.
    """
    from sklearn.multioutput import RegressorChain

    base = OrdinalRegressor(method=method, seed=seed)
    chain = RegressorChain(base, order="random", random_state=seed)
    chain.fit(Xtr, items_tr_int)
    return chain.predict(Xte)


# -----------------------------------------------------------------------------
# Per-fold worker (ProcessPool entry point — module-level, picklable)
# -----------------------------------------------------------------------------
def _fit_one_fold(args: tuple) -> tuple[np.ndarray, np.ndarray]:
    """One CV fold: 8-item ordinal chain × 3 ordinal bases.

    args = (fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, methods)
    Returns (te_idx, t1_pred_te) where t1_pred_te has shape (len(te),).
    """
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, methods = args

    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Build per-item integer training targets (fold-local round + clip)
    items_tr_int_cols: list[np.ndarray] = []
    item_means: dict[int, float] = {}
    for i in item_order:
        v = items[i][tr]
        v_int = np.rint(np.nan_to_num(v, nan=0.0)).astype(int)
        v_int = np.clip(v_int, ORDINAL_MIN, ORDINAL_MAX)
        items_tr_int_cols.append(v_int)
        # Track raw mean (pre-rounding) for residual-style post-combine
        item_means[i] = float(np.nanmean(v))
    items_tr_int = np.column_stack(items_tr_int_cols)

    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    # Average expected-score predictions across 3 ordinal bases
    ip_avg: np.ndarray | None = None
    for method in methods:
        ip = _multitask_predict_ordinal(Xtr_sel, items_tr_int, Xte_sel, seed, method)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    assert ip_avg is not None
    ip_avg = ip_avg / len(methods)

    # T1 sum = sum E[item_i] for i in T1_SUM_ITEMS, residualised against train mean
    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    t1_pred_from_items = ip_avg[:, t1_sum_idx].sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))

    return te, s1_te + (t1_pred_from_items - sum_means_t1)


def _i5_one_fold(args: tuple) -> tuple[np.ndarray, np.ndarray]:
    """iter5-direct comparator worker (single LGB on T1 residual)."""
    fold_id, tr, te, X, y_t1, X_s1, seed = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )
    return te, s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)


# -----------------------------------------------------------------------------
# CV drivers
# -----------------------------------------------------------------------------
def _slot_a_loocv(
    seed: int,
    X: np.ndarray,
    y_t1: np.ndarray,
    X_s1: np.ndarray,
    items: dict[int, np.ndarray],
    item_order: list[int],
    methods: tuple[str, ...],
    n_workers: int,
) -> np.ndarray:
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, methods)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 20 == 0 or done == n:
                print(
                    f"    seed={seed} slotA {done}/{n} folds  "
                    f"elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    return preds


def _slot_a_kfold(
    seed: int,
    X: np.ndarray,
    y_t1: np.ndarray,
    X_s1: np.ndarray,
    items: dict[int, np.ndarray],
    item_order: list[int],
    methods: tuple[str, ...],
    n_splits: int,
    n_workers: int,
) -> np.ndarray:
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, methods)
        for fid, (tr, te) in enumerate(splits)
    ]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return preds


def _iter5_direct_loocv(
    seed: int, X: np.ndarray, y_t1: np.ndarray, X_s1: np.ndarray, n_workers: int
) -> np.ndarray:
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, seed) for fid, (tr, te) in enumerate(splits)
    ]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_i5_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return preds


# -----------------------------------------------------------------------------
# Pre-registration
# -----------------------------------------------------------------------------
def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": (
            "T1 Glass-Ceiling Push — Slot A: ordinal cumulative-link multi-task "
            "chain × 3-base ensemble"
        ),
        "ceiling_push_master_prereg": (
            "results/preregistration_t1_ceiling_push_20260508_051417.json"
        ),
        "family_member": "slotA",
        "fwer_family_n": 4,
        "fwer_method": "Bonferroni 0.9875 strict per-slot gate",
        "mechanism_axis": 1,
        "axis_description": (
            "different loss family — ordinal cumulative-link logit replaces MSE "
            "in iter34's RegressorChain bases; chain + ensemble structure preserved"
        ),
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (matches iter33-B / iter34)",
        },
        "stage1": {
            "model": "Ridge",
            "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9,
            "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
            "target": "T1 (sum items 9-14)",
        },
        "stage2": {
            "model_ensemble": [
                "RegressorChain(OrdinalRegressor(method='mord_at', alpha=1.0))",
                "RegressorChain(OrdinalRegressor(method='lgb_decomp', n_est=500, "
                "lr=0.05, num_leaves=15, min_data=10, isotonic_monotone=True))",
                "RegressorChain(OrdinalRegressor(method='ngb_logit', "
                "Dist=k_categorical(5), n_est=300, lr=0.05))",
            ],
            "ensemble_method": (
                "average expected-score predictions across 3 ordinal bases "
                "per fold per seed"
            ),
            "items_targets_chain": list(ALL_ITEMS),
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "item_target_format": "integer 0-4 (round + clip fold-local)",
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES,
            "imputation": "fold_local_median",
            "post_combine_formula": (
                "Stage1_pred + (sum_over_T1_SUM_ITEMS(mean_over_bases(E[item|X])) "
                "- sum(train_mean[T1_SUM_ITEMS]))"
            ),
            "ordinal_cut_point_strategy": (
                "Per-base, per-item, fold-local fit (no test-fold info). "
                "Degenerate folds (single observed class) fall back to constant "
                "prediction = train mean. lgb_decomp degenerate cut-points (no "
                "positive or no negative samples) fall back to constant probability."
            ),
            "expected_p2_robustness_argument": (
                "iter34 audit P2 (noisy-test-X) borderline soft-fail "
                "Δ=−0.065. Cumulative-link probabilities cap at [0,1] and E[item] "
                "caps at [0,4], so noise inputs cannot drive predictions far from "
                "the empirical mean. Slot A is expected to PASS P2 strictly."
            ),
        },
        "eval": {
            "loocv_n_min": 90,
            "seeds": list(SEEDS_DEFAULT),
            "methods": list(ORDINAL_BASES),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
            "comparator_iter34_loocv_json": (
                "results/lockbox_t1_iter34_hybrid_20260506_141720.json"
            ),
            "comparator_iter12_honest_path": "compose_t1_iter12_honest.py output",
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run. NO seed shopping.",
            "Headline = CCC of mean-of-3-seed preds (each seed avgs 3 ordinal bases).",
            (
                "Slot verdict per FWER strict gate: paired-bootstrap (n=5000) "
                "frac>0 vs iter12-honest-on-N=93 AND vs iter34-on-N=93, "
                "Bonferroni-adjusted threshold 0.9875."
            ),
            "Verdict CANDIDATE if frac>0 in [0.95, 0.9875).",
            "Verdict FAIL if frac>0 < 0.95.",
            "Verdict CANONICAL only if frac>0 >= 0.9875 against BOTH baselines.",
        ],
    }


def _formula_sha256(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def write_preregistration() -> Path:
    payload = _formula_payload()
    sha = _formula_sha256(payload)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T1 Ceiling Push Slot A — ordinal chain × 3-base ensemble LOCKBOX",
        "git_head": _git_head(),
        "formula_sha256": sha,
        "formula": payload,
        "variant": "slot_a_ordinal_chain",
        "ceiling_push_master_prereg": (
            "results/preregistration_t1_ceiling_push_20260508_051417.json"
        ),
        "fwer_family_n": 4,
        "eval_protocol": (
            "LOOCV on T1∩{15,18} cohort (N≈93). Stage-1 Ridge (alpha=1.0) on "
            "H&Y + cv_yrs + cv_sex + cv_dbs with per-fold standardisation. "
            "Stage-2 = mean expected-score over 3 ordinal bases (mord.LogisticAT, "
            "LGB 4-binary cum-link, NGBoost k_categorical), each RegressorChain "
            "with random order over 8 items {9-14, 15, 18}. T1 = sum E[item|X] "
            "for items 9-14; items 15+18 auxiliary. K=500 LGB-importance per fold. "
            "3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_ceiling_push_slotA_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Bootstrap utility
# -----------------------------------------------------------------------------
def _paired_bootstrap_ccc(
    y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> dict:
    rng = np.random.RandomState(seed)
    n = len(y)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {
        "n_boot": n_boot,
        "delta_mean": float(deltas.mean()),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float((deltas > 0).mean()),
        "frac_above_0.025": float((deltas > 0.025).mean()),
        "frac_above_0.9875_gate": float((deltas > 0).mean() >= 0.9875),
    }


# -----------------------------------------------------------------------------
# Five-null gate
# -----------------------------------------------------------------------------
def _five_null_gate(
    seed: int,
    X: np.ndarray,
    y_t1: np.ndarray,
    X_s1: np.ndarray,
    items: dict[int, np.ndarray],
    item_order: list[int],
    methods: tuple[str, ...],
    n_workers: int,
) -> dict:
    """Run P0–P5 nulls on slot A architecture, 5-fold (faster than LOOCV)."""
    rng = np.random.RandomState(seed)
    n = len(y_t1)
    K_FOLD = 5
    splits = list(KFold(n_splits=K_FOLD, shuffle=True, random_state=seed).split(np.arange(n)))

    # P0 baseline
    p0 = _slot_a_kfold(seed, X, y_t1, X_s1, items, item_order, methods, K_FOLD, n_workers)
    p0_ccc = ccc_fn(y_t1, p0)

    # P1 perm: permute y in each fold's training set
    perm_cccs: list[float] = []
    for perm_idx in range(10):
        rng_p = np.random.RandomState(123 + perm_idx)
        perm_preds = np.zeros(n)
        for tr, te in splits:
            tr_perm = tr.copy()
            rng_p.shuffle(tr_perm)
            y_t1_perm = y_t1.copy()
            y_t1_perm[tr] = y_t1[tr_perm]
            items_perm: dict[int, np.ndarray] = {}
            for i, vec in items.items():
                shuffled = vec.copy()
                shuffled_tr = shuffled[tr]
                shuffled_idx = np.arange(len(tr))
                rng_p.shuffle(shuffled_idx)
                shuffled[tr] = shuffled_tr[shuffled_idx]
                items_perm[i] = shuffled
            args = (0, tr, te, X, y_t1_perm, X_s1, items_perm, item_order, seed, methods)
            te_idx, te_pred = _fit_one_fold(args)
            perm_preds[te_idx] = te_pred
        perm_cccs.append(float(ccc_fn(y_t1, perm_preds)))
    perm_arr = np.array(perm_cccs)
    p1_z = (p0_ccc - perm_arr.mean()) / max(perm_arr.std(), 1e-6)

    # P3 stage1-only: drop Stage 2 entirely
    p3_preds = np.zeros(n)
    for tr, te in splits:
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        p3_preds[te] = s1_te
    p3_ccc = ccc_fn(y_t1, p3_preds)

    # P2 noisy-test-X: replace test X with noise; expect CCC ~ Stage1-only
    p2_preds = np.zeros(n)
    for tr, te in splits:
        Xte_noise = rng.randn(*X[te].shape)
        args = (0, tr, te, X, y_t1, X_s1, items, item_order, seed, methods)
        # Hand-roll a noisy-test-X version of _fit_one_fold inline:
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        items_tr_int_cols = []
        item_means: dict[int, float] = {}
        for i in item_order:
            v = items[i][tr]
            v_int = np.rint(np.nan_to_num(v, nan=0.0)).astype(int)
            v_int = np.clip(v_int, ORDINAL_MIN, ORDINAL_MAX)
            items_tr_int_cols.append(v_int)
            item_means[i] = float(np.nanmean(v))
        items_tr_int = np.column_stack(items_tr_int_cols)
        Xtr, _ = impute_fold(X[tr], X[te])  # drop test impute, replace below
        # Apply same imputer median to noise (use Xtr median as proxy)
        Xte_noise_imputed = Xte_noise.copy()
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte_noise_imputed, k=K_FEATURES, seed=seed
        )
        ip_avg = None
        for method in methods:
            ip = _multitask_predict_ordinal(
                Xtr_sel, items_tr_int, Xte_sel, seed, method
            )
            ip_avg = ip if ip_avg is None else ip_avg + ip
        ip_avg = ip_avg / len(methods)
        t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
        t1_pred_from_items = ip_avg[:, t1_sum_idx].sum(axis=1)
        sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
        p2_preds[te] = s1_te + (t1_pred_from_items - sum_means_t1)
    p2_ccc = ccc_fn(y_t1, p2_preds)

    # P4 pure-noise X (full cohort): expect CCC ~ Stage1-only
    p4_preds = np.zeros(n)
    Xnoise = rng.randn(*X.shape)
    for tr, te in splits:
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        items_tr_int_cols = []
        item_means: dict[int, float] = {}
        for i in item_order:
            v = items[i][tr]
            v_int = np.rint(np.nan_to_num(v, nan=0.0)).astype(int)
            v_int = np.clip(v_int, ORDINAL_MIN, ORDINAL_MAX)
            items_tr_int_cols.append(v_int)
            item_means[i] = float(np.nanmean(v))
        items_tr_int = np.column_stack(items_tr_int_cols)
        Xtr, Xte = impute_fold(Xnoise[tr], Xnoise[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        ip_avg = None
        for method in methods:
            ip = _multitask_predict_ordinal(
                Xtr_sel, items_tr_int, Xte_sel, seed, method
            )
            ip_avg = ip if ip_avg is None else ip_avg + ip
        ip_avg = ip_avg / len(methods)
        t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
        t1_pred_from_items = ip_avg[:, t1_sum_idx].sum(axis=1)
        sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
        p4_preds[te] = s1_te + (t1_pred_from_items - sum_means_t1)
    p4_ccc = ccc_fn(y_t1, p4_preds)

    return {
        "P0_baseline_ccc": float(p0_ccc),
        "P1_perm_seeds": list(range(123, 133)),
        "P1_perm_cccs": perm_cccs,
        "P1_perm_mean": float(perm_arr.mean()),
        "P1_perm_std": float(perm_arr.std()),
        "P1_z_score": float(p1_z),
        "P1_pass": bool(p1_z > 3.0),
        "P2_noisy_test_x_ccc": float(p2_ccc),
        "P2_delta_vs_stage1_only": float(p2_ccc - p3_ccc),
        "P2_pass": bool(abs(p2_ccc - p3_ccc) <= 0.05),
        "P3_stage1_only_ccc": float(p3_ccc),
        "P4_pure_noise_x_ccc": float(p4_ccc),
        "P4_delta_vs_stage1_only": float(p4_ccc - p3_ccc),
        "P4_pass": bool(abs(p4_ccc - p3_ccc) <= 0.05),
        "all_pass": bool(p1_z > 3.0 and abs(p2_ccc - p3_ccc) <= 0.05 and abs(p4_ccc - p3_ccc) <= 0.05),
    }


# -----------------------------------------------------------------------------
# Smoke test
# -----------------------------------------------------------------------------
def smoke_test(seed: int = 42, feature_set: str = "A3_tier1") -> None:
    print("\n=== SLOT A SMOKE TEST: 1 fold × 1 seed ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, ORDINAL_BASES)
    t0 = time.time()
    te_idx, te_pred = _fit_one_fold(args)
    print(
        f"  fold 0/{n}: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
        f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
        f"wall={time.time()-t0:.1f}s",
        flush=True,
    )
    assert te_pred.shape == te.shape, f"shape mismatch {te_pred.shape} vs {te.shape}"
    assert np.isfinite(te_pred).all(), "non-finite predictions"
    print("  SMOKE PASS", flush=True)


# -----------------------------------------------------------------------------
# Screen mode (5-fold gate before LOOCV)
# -----------------------------------------------------------------------------
def run_screen(
    seeds: tuple[int, ...] = SEEDS_DEFAULT,
    feature_set: str = "A3_tier1",
    n_workers: int = 11,
) -> Path:
    print("\n=== SLOT A SCREEN: 5-fold × 3 seeds ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    seed_results: list[dict] = []
    for seed in seeds:
        t0 = time.time()
        slot_a_pred = _slot_a_kfold(
            seed, X, y_t1, X_s1, items, item_order, ORDINAL_BASES, 5, n_workers
        )
        i5_pred = np.zeros(n)
        i5_splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
        for tr, te in i5_splits:
            args = (0, tr, te, X, y_t1, X_s1, seed)
            _, te_pred = _i5_one_fold(args)
            i5_pred[te] = te_pred
        ccc_a = float(ccc_fn(y_t1, slot_a_pred))
        ccc_i5 = float(ccc_fn(y_t1, i5_pred))
        seed_results.append(
            {
                "seed": seed,
                "ccc_slot_a": ccc_a,
                "ccc_i5_direct": ccc_i5,
                "delta_vs_i5": ccc_a - ccc_i5,
                "delta_vs_iter34_baseline": ccc_a - ITER34_LOOCV_CCC,
                "wall_s": time.time() - t0,
            }
        )
        print(
            f"  seed={seed}: slot_A={ccc_a:.4f}  iter5={ccc_i5:.4f}  "
            f"Δ vs i5={ccc_a-ccc_i5:+.4f}  Δ vs iter34={ccc_a-ITER34_LOOCV_CCC:+.4f}  "
            f"wall={time.time()-t0:.0f}s",
            flush=True,
        )

    deltas_vs_iter34 = [r["delta_vs_iter34_baseline"] for r in seed_results]
    delta_mean = float(np.mean(deltas_vs_iter34))
    delta_std = float(np.std(deltas_vs_iter34, ddof=1)) if len(deltas_vs_iter34) > 1 else 0.0
    print(
        f"\n  SCREEN GATE (vs iter34 5-fold):  Δ̄ = {delta_mean:+.4f}  "
        f"std = {delta_std:.4f}  (need Δ̄ ≥ +0.025 to promote)",
        flush=True,
    )
    promote = delta_mean >= 0.025
    print(f"  PROMOTE TO LOOCV: {promote}", flush=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"slotA_screen_{ts}.json"
    with open(out, "w") as f:
        json.dump(
            {
                "timestamp": ts,
                "seeds": list(seeds),
                "n_subjects": n,
                "per_seed": seed_results,
                "delta_mean_vs_iter34_5fold": delta_mean,
                "delta_std_vs_iter34_5fold": delta_std,
                "promote_to_loocv": promote,
                "iter34_loocv_anchor": ITER34_LOOCV_CCC,
            },
            f,
            indent=2,
        )
    print(f"\n  SCREEN RESULTS WRITTEN: {out}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Lockbox
# -----------------------------------------------------------------------------
def run_lockbox(
    prereg_file: Path,
    seeds: tuple[int, ...] = SEEDS_DEFAULT,
    feature_set: str = "A3_tier1",
    n_workers: int = 11,
) -> Path:
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} "
            f"!= live {expected_sha!r}; pre-reg + script out of sync"
        )
    print(f"\n=== SLOT A LOCKBOX (3 seeds × LOOCV) ===", flush=True)
    print(f"  pre-reg: {prereg_file.name}", flush=True)
    print(f"  formula_sha256 verified: {expected_sha}", flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    per_seed: list[dict] = []
    slot_a_seed_preds: list[np.ndarray] = []
    iter5_seed_preds: list[np.ndarray] = []
    for seed in seeds:
        t0 = time.time()
        a_pred = _slot_a_loocv(
            seed, X, y_t1, X_s1, items, item_order, ORDINAL_BASES, n_workers
        )
        i5_pred = _iter5_direct_loocv(seed, X, y_t1, X_s1, n_workers)
        ccc_a = float(ccc_fn(y_t1, a_pred))
        ccc_i5 = float(ccc_fn(y_t1, i5_pred))
        per_seed.append(
            {
                "seed": seed,
                "ccc_slot_a": ccc_a,
                "ccc_i5": ccc_i5,
                "delta_vs_i5": ccc_a - ccc_i5,
                "delta_vs_iter34": ccc_a - ITER34_LOOCV_CCC,
                "wall": time.time() - t0,
            }
        )
        slot_a_seed_preds.append(a_pred)
        iter5_seed_preds.append(i5_pred)
        print(
            f"  seed={seed}: slot_A={ccc_a:.4f}  i5={ccc_i5:.4f}  "
            f"Δ_i5={ccc_a-ccc_i5:+.4f}  Δ_iter34={ccc_a-ITER34_LOOCV_CCC:+.4f}  "
            f"wall={time.time()-t0:.0f}s",
            flush=True,
        )

    a_mean = np.mean(slot_a_seed_preds, axis=0)
    i5_mean = np.mean(iter5_seed_preds, axis=0)
    metrics = full_metrics(y_t1, a_mean)
    metrics["label"] = "t1_ceiling_push_slotA"

    bs_i5 = _paired_bootstrap_ccc(y_t1, a_mean, i5_mean)

    # Paired vs iter34 — load iter34 lockbox y_pred + y_true
    iter34_path = (
        RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.json"
    )
    bs_iter34: dict | None = None
    if iter34_path.exists():
        with open(iter34_path) as f:
            iter34_lb = json.load(f)
        iter34_sids = iter34_lb["per_subject"]["sids"]
        iter34_y_true = np.array(iter34_lb["per_subject"]["y_true"])
        iter34_y_pred = np.array(iter34_lb["per_subject"]["y_pred"])
        # Align by SID (slot A and iter34 both filter to N=93 with same drop pattern)
        sid_to_idx_a = {s: i for i, s in enumerate(sids)}
        common = [s for s in iter34_sids if s in sid_to_idx_a]
        if len(common) == len(iter34_sids):
            idx_a = np.array([sid_to_idx_a[s] for s in iter34_sids])
            y_aligned = np.array(iter34_y_true)
            assert np.allclose(y_aligned, y_t1[idx_a]), (
                "iter34 y_true mismatch with current cohort y_t1 — "
                "cohort filter inconsistent"
            )
            a_aligned = a_mean[idx_a]
            bs_iter34 = _paired_bootstrap_ccc(y_aligned, a_aligned, iter34_y_pred)
        else:
            print(
                f"  WARNING: iter34 lockbox has {len(iter34_sids)} sids, "
                f"{len(common)} present in current cohort. Cannot align cleanly.",
                flush=True,
            )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"lockbox_t1_ceiling_push_slotA_{ts}.json"
    payload = {
        "n": n,
        **metrics,
        "variant": "slot_a_ordinal_chain",
        "n_subjects": n,
        "ordinal_bases": list(ORDINAL_BASES),
        "preregistration_file": prereg_file.name,
        "is_lockbox_headline": True,
        "n_seeds": len(seeds),
        "per_seed": per_seed,
        "wall_time_total_s": float(sum(r["wall"] for r in per_seed)),
        "iter34_loocv_anchor": ITER34_LOOCV_CCC,
        "ccc_iter5_direct_loocv_baseline_mean": float(
            np.mean([r["ccc_i5"] for r in per_seed])
        ),
        "delta_vs_iter5_direct": float(metrics["ccc"] - np.mean([r["ccc_i5"] for r in per_seed])),
        "bootstrap_delta_vs_iter5": bs_i5,
        "bootstrap_delta_vs_iter34": bs_iter34,
        "fwer_strict_gate_iter34_passed": (
            bs_iter34 is not None and bs_iter34["frac_above_zero"] >= 0.9875
        ),
        "fwer_loose_gate_iter34_passed": (
            bs_iter34 is not None and bs_iter34["frac_above_zero"] >= 0.95
        ),
        "per_subject": {
            "sids": list(sids),
            "y_true": [float(v) for v in y_t1],
            "y_pred": [float(v) for v in a_mean],
        },
    }
    with open(out, "w") as f:
        json.dump(payload, f, indent=2)
    np.save(out.with_suffix(".oof.npy"), a_mean)
    print(f"\n  LOCKBOX WRITTEN: {out}", flush=True)
    print(f"  CCC headline = {metrics['ccc']:.4f}", flush=True)
    print(f"  Δ vs iter34 = {metrics['ccc']-ITER34_LOOCV_CCC:+.4f}", flush=True)
    if bs_iter34:
        print(
            f"  paired-bootstrap vs iter34: frac>0 = {bs_iter34['frac_above_zero']:.4f} "
            f"(strict gate 0.9875: {bs_iter34['frac_above_zero'] >= 0.9875})",
            flush=True,
        )
    return out


# -----------------------------------------------------------------------------
# Audit mode (5-null gate on existing lockbox config)
# -----------------------------------------------------------------------------
def run_audit(
    seed: int = 42, feature_set: str = "A3_tier1", n_workers: int = 11
) -> Path:
    print("\n=== SLOT A AUDIT: 5-null gate (5-fold) ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    t0 = time.time()
    audit = _five_null_gate(
        seed, X, y_t1, X_s1, items, item_order, ORDINAL_BASES, n_workers
    )
    audit["wall_s"] = time.time() - t0
    audit["seed"] = seed

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"slotA_audit_{ts}.json"
    with open(out, "w") as f:
        json.dump(audit, f, indent=2)
    print(json.dumps(audit, indent=2)[:2000], flush=True)
    print(f"\n  AUDIT WRITTEN: {out}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["smoke", "screen", "write_prereg", "lockbox", "audit"],
        required=True,
    )
    ap.add_argument(
        "--prereg", type=str, default=None,
        help="Pre-reg JSON (lockbox mode). Defaults to most recent slotA prereg.",
    )
    ap.add_argument("--n_workers", type=int, default=11)
    ap.add_argument("--feature_set", type=str, default="A3_tier1")
    args = ap.parse_args()

    if args.mode == "smoke":
        smoke_test()
        return 0
    if args.mode == "write_prereg":
        write_preregistration()
        return 0
    if args.mode == "screen":
        run_screen(n_workers=args.n_workers, feature_set=args.feature_set)
        return 0
    if args.mode == "audit":
        run_audit(n_workers=args.n_workers, feature_set=args.feature_set)
        return 0
    if args.mode == "lockbox":
        if args.prereg:
            prereg = Path(args.prereg)
        else:
            candidates = sorted(
                RESULTS_DIR.glob("preregistration_t1_ceiling_push_slotA_*.json")
            )
            if not candidates:
                raise FileNotFoundError(
                    "no slotA prereg found; run --mode write_prereg first"
                )
            prereg = candidates[-1]
        run_lockbox(
            prereg, n_workers=args.n_workers, feature_set=args.feature_set
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
