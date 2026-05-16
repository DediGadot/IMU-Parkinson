"""T1 iter39 — Per-item-averaged K=500 feature selection (slot C of T1 ceiling push).

Slot C of T1 Glass-Ceiling Push 2026-05-10 (master pre-reg
results/preregistration_t1_ceiling_push_20260510_134829.json).

PIVOT FROM ORIGINAL quantile-LGB DESIGN per slot A+B null evidence:
Both slot A (post-K500 chain-step routing for items 9+12) and slot B (post-K500
chain-step routing for items 11+13 with new representation) returned Δ̄ ≈ 0
vs iter34 5-fold (slot A: -0.002, slot B: -0.0002), validating kimi's 17th
wall data point: V2 already covers the phase-conditional gait structure
subspace at N=92, so adding new feature blocks (regardless of post-K500 vs
in-K500 routing) does not move the needle. Original slot C (quantile-LGB
chain base) would burn FWER on a small base-learner-family change adjacent to
F35-A loss-family wall.

Slot C revised: change the K=500 SELECTION RULE itself, not the features.

MECHANISM:
  - Iter34: K=500 = top features by LGB-importance against (y_t1[tr] − s1_tr),
    a SINGLE T1-residual rank. Item-blind: features useful for item 10 (gait)
    but noise on item 13 (posture) compete with features useful for items 9, 12,
    14 against a single global criterion.
  - Slot C: K=500 = top features by AVERAGED LGB-importance across 8 item
    residuals (items 9, 10, 11, 12, 13, 14, 15, 18). Item-aware: features that
    are jointly useful across multiple items rank higher than features
    dominated by one item.

DISTINCTION FROM WALL:
  - F44/F19 (K=500 absorption when ADDING features to V2): slot C does NOT add
    features. Same V2, same K=500 size, same chain. Only the importance ranking
    changes.
  - F66/F67 (variance reduction via more seeds / chain orders / base avg): slot
    C is structural (selection rule change), not stochastic averaging.
  - F35-A loss families: slot C does NOT change the loss; same MSE-on-residuals.
  - Slot A/B post-K500 routing: slot C is PRE-K500 selection rule change; the
    per-item averaging happens before feature selection completes.

EXPECTED FALSIFYING SIGNATURES:
  - 5-fold Δ̄ vs iter34 < +0.005 across 3 seeds → mechanism collapses to "K=500
    selection is well-calibrated for T1 sum already", which is actually a
    POSITIVE epistemic finding.
  - K=500 union with iter34's K=500 > 80% overlap → per-item averaging picks
    nearly the same features iter34 picks; mechanism is null by construction.

Modes:
  --mode write_prereg / smoke / screen / lockbox
  --measure_overlap        : just compute the overlap ratio with iter34's K=500 selection per fold (cheap diagnostic)
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import hashlib
import json
import multiprocessing as mp
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from pd_imu.core.legacy_experiment_api import (
    ALL_ITEMS, AUX_ITEMS, ITER5_FEATURE_SETS, T1_ITEMS, T1_SUM_ITEMS,
    _load_t1_cohort_with_8items, build_stage1_features,
    fit_stage1, impute_fold, load_clinical_dict,
)
from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
ITER34_LOOCV_CCC = 0.7366
PUBLISHED_T1_LOOCV_CCC = 0.6550
BASE_LEARNERS: tuple[str, ...] = ("lgb", "xgb", "et")


def _make_regr(base: str, seed: int):
    if base == "lgb":
        import lightgbm as lgb
        return lgb.LGBMRegressor(
            n_estimators=500, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, random_state=seed, n_jobs=1, verbose=-1,
        )
    if base == "xgb":
        import xgboost as xgb
        return xgb.XGBRegressor(
            n_estimators=500, learning_rate=0.05, max_depth=4,
            min_child_weight=5, tree_method="hist",
            random_state=seed, n_jobs=1, verbosity=0,
        )
    if base == "et":
        from sklearn.ensemble import ExtraTreesRegressor
        return ExtraTreesRegressor(
            n_estimators=300, max_depth=10, min_samples_leaf=5,
            random_state=seed, n_jobs=1,
        )
    raise ValueError(f"unknown base learner {base!r}")


def _peritem_kselect(X_tr, items_tr_residual, X_te, k=K_FEATURES, seed=42):
    """K=500 selection by averaged LGB-importance across item residuals.
    Returns (X_tr_sel, X_te_sel, idx)."""
    if X_tr.shape[1] <= k:
        return X_tr, X_te, np.arange(X_tr.shape[1])
    import lightgbm as lgb
    n_items = items_tr_residual.shape[1]
    imp_sum = np.zeros(X_tr.shape[1], dtype=np.float64)
    for i in range(n_items):
        sel = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.1, num_leaves=15,
                                 min_data_in_leaf=5, n_jobs=1, random_state=seed, verbosity=-1)
        sel.fit(X_tr, items_tr_residual[:, i])
        imp_sum += sel.feature_importances_.astype(np.float64)
    imp_avg = imp_sum / n_items
    idx = np.argsort(imp_avg)[::-1][:k]
    return X_tr[:, idx], X_te[:, idx], idx


def _iter34_kselect(X_tr, y_resid_tr, X_te, k=K_FEATURES, seed=42):
    """Mirror iter34's selection (single LGB on T1 residual)."""
    if X_tr.shape[1] <= k:
        return X_tr, X_te, np.arange(X_tr.shape[1])
    import lightgbm as lgb
    sel = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.1, num_leaves=15,
                             min_data_in_leaf=5, n_jobs=1, random_state=seed, verbosity=-1)
    sel.fit(X_tr, y_resid_tr)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return X_tr[:, idx], X_te[:, idx], idx


def _fit_one_fold(args):
    """Worker: 8-item chain × 3 base learners with PER-ITEM-AVERAGED K=500 selection."""
    from sklearn.multioutput import RegressorChain
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means: dict[int, float] = {}
    items_tr_resid: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_resid.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_resid)
    Xtr, Xte = impute_fold(X[tr], X[te])

    # Per-item K=500 selection (the slot C mechanism)
    Xtr_sel, Xte_sel, sel_idx = _peritem_kselect(Xtr, items_tr_arr, Xte, k=K_FEATURES, seed=seed)

    # Chain identical to iter34's baseline (sklearn RegressorChain)
    ip_avg = None
    for b in bases:
        regr = _make_regr(b, seed)
        chain = RegressorChain(regr, order="random", random_state=seed)
        chain.fit(Xtr_sel, items_tr_arr)
        ip = chain.predict(Xte_sel)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg /= len(bases)
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    return te, s1_te + (item_pred.sum(axis=1) - float(sum(item_means[i] for i in T1_SUM_ITEMS))), {"sel_idx": sel_idx.tolist()}


def _i34_one_fold(args):
    """iter34 baseline using identical pipeline with iter34's K=500 selection rule."""
    from sklearn.multioutput import RegressorChain
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means = {}; items_tr_resid = []
    for i in item_order:
        v = items[i][tr]; mu = float(np.nanmean(v)); item_means[i] = mu
        items_tr_resid.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_resid)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, sel_idx = _iter34_kselect(Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed)
    ip_avg = None
    for b in bases:
        regr = _make_regr(b, seed)
        chain = RegressorChain(regr, order="random", random_state=seed)
        chain.fit(Xtr_sel, items_tr_arr)
        ip = chain.predict(Xte_sel)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg /= len(bases)
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    return te, s1_te + (item_pred.sum(axis=1) - float(sum(item_means[i] for i in T1_SUM_ITEMS))), {"sel_idx": sel_idx.tolist()}


def _run_cv(seed, splits, X, y_t1, X_s1, items, item_order, bases, n_workers, label, worker_fn):
    n = len(y_t1)
    preds = np.zeros(n)
    selections = []
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
            for fid, (tr, te) in enumerate(splits)]
    ctx = mp.get_context("spawn")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(worker_fn, j): j[0] for j in jobs}
        done = 0
        for fut in as_completed(futs):
            te_idx, te_pred, info = fut.result()
            preds[te_idx] = te_pred
            selections.append({"fold_id": int(futs[fut]), "sel_idx": info["sel_idx"]})
            done += 1
            print(f"    seed={seed} {label} {done}/{len(splits)}  elapsed={time.time()-t0:.0f}s", flush=True)
    return preds, selections


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 iter39 — per-item-averaged K=500 feature selection",
        "slot": "C of T1 Glass-Ceiling Push 2026-05-10 (master prereg "
                "results/preregistration_t1_ceiling_push_20260510_134829.json, FWER n=4)",
        "is_post_publication_replication_target": False,
        "mechanism_change": "K=500 selection ranks features by AVERAGED LGB-importance across 8 item residuals (items 9-14, 15, 18) instead of by single LGB-importance against T1 residual",
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (matches iter34 cohort)",
            "split_file": "results/paper3_split.json",
        },
        "stage1": {"model": "Ridge", "alpha": STAGE1_ALPHA, "feature_set_name": "A3_tier1",
                   "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"], "stage1_total_features": 9},
        "stage2": {
            "model_ensemble": ["RegressorChain(LGB)", "RegressorChain(XGB-hist)", "RegressorChain(ET)"],
            "items_targets_chain": list(ALL_ITEMS),
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "feature_select_method": "per_item_averaged_lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES,
            "selection_rule_change": "iter34: argsort(LGB.feature_importances_(y_t1−s1)) → slot_C: argsort(mean over 8 items: LGB.feature_importances_(item_resid))",
        },
        "eval": {"loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT), "bases": list(BASE_LEARNERS)},
        "screen_gate": {"n_splits": 5, "promote": "Δ̄≥+0.025 AND frac>0≥0.95"},
        "lockbox_rules": ["ONE pre-registered config. ONE LOOCV run. SLOT C of FWER n=4 family.",
                          "Bonferroni gates: frac>0 ≥ 0.9875 vs iter12-honest-n93 AND vs iter34-n93."],
    }


def _formula_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def write_preregistration() -> Path:
    payload = _formula_payload()
    sha = _formula_sha256(payload)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts, "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "T1 iter39 — per-item-averaged K=500 selection",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": "peritem_kselect_avg_importance",
        "master_prereg_id": "t1_ceiling_push_20260510_134829",
        "master_prereg_path": "results/preregistration_t1_ceiling_push_20260510_134829.json",
        "slot_id": "C",
        "fwer_family_size_n": 4,
    }
    out = RESULTS_DIR / f"preregistration_t1_iter39_peritem_kselect_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _paired_bootstrap_ccc(y, p_a, p_b, n_boot=5000, seed=42):
    rng = np.random.RandomState(seed); n = len(y)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {"n_boot": n_boot, "delta_mean": float(deltas.mean()),
            "delta_ci_low": float(np.percentile(deltas, 2.5)),
            "delta_ci_high": float(np.percentile(deltas, 97.5)),
            "frac_above_zero": float((deltas > 0).mean()),
            "frac_above_0.025": float((deltas > 0.025).mean())}


def run_null_gate(seed: int = 42) -> dict:
    """Corrected chain null gate for per-item auxiliary targets.

    The scrambled-label null shuffles every target-derived training array
    (`y_t1` and item labels) by the same train-fold permutation. The canary
    check measures prediction invariance after adding a test-only random
    feature, rather than requiring the normal model's CCC to be near zero.
    """
    print("\n=== Slot C corrected null gate ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    rng = np.random.RandomState(seed)
    perm = rng.permutation(n)
    cut = int(0.8 * n)
    tr_idx, te_idx = perm[:cut], perm[cut:]
    print(f"  cohort N={n}, train={len(tr_idx)}, test={len(te_idx)}", flush=True)

    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    def _predict(y_train: np.ndarray, item_train_values: dict[int, np.ndarray], X_train, X_test):
        s1_tr, s1_te = fit_stage1(X_s1[tr_idx], y_train, X_s1[te_idx], alpha=STAGE1_ALPHA)
        item_means: dict[int, float] = {}
        items_tr_resid: list[np.ndarray] = []
        for i in item_order:
            v = item_train_values[i]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_resid.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_resid)
        Xtr, Xte = impute_fold(X_train, X_test)
        Xtr_sel, Xte_sel, _ = _peritem_kselect(Xtr, items_tr_arr, Xte, k=K_FEATURES, seed=seed)
        ip_avg = None
        for b in BASE_LEARNERS:
            regr = _make_regr(b, seed)
            from sklearn.multioutput import RegressorChain
            chain = RegressorChain(regr, order="random", random_state=seed)
            chain.fit(Xtr_sel, items_tr_arr)
            ip = chain.predict(Xte_sel)
            ip_avg = ip if ip_avg is None else ip_avg + ip
        ip_avg /= len(BASE_LEARNERS)
        t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
        item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
        return s1_te + item_pred.sum(axis=1) - float(sum(item_means[i] for i in T1_SUM_ITEMS))

    true_item_train = {i: items[i][tr_idx] for i in item_order}
    normal_pred = _predict(y_t1[tr_idx], true_item_train, X[tr_idx], X[te_idx])

    scramble_order = rng.permutation(len(tr_idx))
    scrambled_item_train = {i: items[i][tr_idx][scramble_order] for i in item_order}
    pred_sc = _predict(y_t1[tr_idx][scramble_order], scrambled_item_train, X[tr_idx], X[te_idx])

    canary_tr = np.zeros((len(tr_idx), 1))
    canary_te = np.random.RandomState(seed).randn(len(te_idx), 1) * 5.0
    pred_cn = _predict(
        y_t1[tr_idx],
        true_item_train,
        np.hstack([X[tr_idx], canary_tr]),
        np.hstack([X[te_idx], canary_te]),
    )

    s1_full_tr, s1_full_te = fit_stage1(X_s1, y_t1, X_s1[te_idx], alpha=STAGE1_ALPHA)
    items_full = np.column_stack([
        np.nan_to_num(items[i] - float(np.nanmean(items[i])), nan=0.0) for i in item_order
    ])
    Xtr_full, Xte_full = impute_fold(X, X[te_idx])
    Xtr_full_sel, Xte_full_sel, _ = _peritem_kselect(Xtr_full, items_full, Xte_full, k=K_FEATURES, seed=seed)
    ip_avg = None
    for b in BASE_LEARNERS:
        regr = _make_regr(b, seed)
        from sklearn.multioutput import RegressorChain
        chain = RegressorChain(regr, order="random", random_state=seed)
        chain.fit(Xtr_full_sel, items_full)
        ip = chain.predict(Xte_full_sel)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg /= len(BASE_LEARNERS)
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_means_full = {i: float(np.nanmean(items[i])) for i in T1_SUM_ITEMS}
    item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means_full[i] for i in T1_SUM_ITEMS])
    pred_full = s1_full_te + item_pred.sum(axis=1) - float(sum(item_means_full.values()))

    canary_delta = pred_cn - normal_pred
    nulls = {
        "null_seed": int(seed),
        "n_train": int(len(tr_idx)),
        "n_test": int(len(te_idx)),
        "normal_ccc": round(float(ccc_fn(y_t1[te_idx], normal_pred)), 4),
        "scrambled_label_ccc": round(float(ccc_fn(y_t1[te_idx], pred_sc)), 4),
        "canary_feature_ccc": round(float(ccc_fn(y_t1[te_idx], pred_cn)), 4),
        "canary_vs_normal_max_abs_delta": float(np.max(np.abs(canary_delta))),
        "canary_vs_normal_mean_abs_delta": float(np.mean(np.abs(canary_delta))),
        "transductive_sanity_ccc": round(float(ccc_fn(y_t1[te_idx], pred_full)), 4),
    }
    nulls["null_gate_pass"] = bool(
        abs(nulls["scrambled_label_ccc"]) < 0.05
        and nulls["canary_vs_normal_max_abs_delta"] < 1e-6
        and nulls["transductive_sanity_ccc"] > 0.5
    )
    print(
        f"  normal={nulls['normal_ccc']:+.4f}  "
        f"scrambled={nulls['scrambled_label_ccc']:+.4f}  "
        f"canary_delta_max={nulls['canary_vs_normal_max_abs_delta']:.3g}  "
        f"transductive={nulls['transductive_sanity_ccc']:+.4f}  "
        f"pass={nulls['null_gate_pass']}",
        flush=True,
    )
    return nulls


def smoke_test(seed: int = 42) -> None:
    print("\n=== iter39 slot C SMOKE: 1 fold × 1 seed ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])
    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, BASE_LEARNERS)
    t0 = time.time()
    te_idx, te_pred, info = _fit_one_fold(args)
    print(f"  fold 0/{n}: y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
          f"wall={time.time()-t0:.1f}s, k_selected={len(info['sel_idx'])}", flush=True)
    # Compare overlap with iter34's K=500
    te_idx2, te_pred2, info2 = _i34_one_fold(args)
    overlap = len(set(info["sel_idx"]) & set(info2["sel_idx"]))
    print(f"  overlap with iter34 K=500: {overlap}/500 = {overlap/500:.1%}", flush=True)
    assert np.isfinite(te_pred).all()
    print("  SMOKE PASS", flush=True)


def run_screen(seeds=SEEDS_DEFAULT, n_workers: int = 5) -> dict:
    print("\n=== 5-fold × 3 seed SCREEN: slot C vs iter34 ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])
    per_seed = []; pl_oofs = []; i34_oofs = []
    overlap_per_fold = []
    for seed in seeds:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        splits = list(kf.split(np.arange(n)))
        t0 = time.time()
        pl_pred, sel_c = _run_cv(seed, splits, X, y_t1, X_s1, items, item_order, BASE_LEARNERS,
                                  n_workers, "slotC", _fit_one_fold)
        i34_pred, sel_i34 = _run_cv(seed, splits, X, y_t1, X_s1, items, item_order, BASE_LEARNERS,
                                     n_workers, "iter34", _i34_one_fold)
        # Compute selection overlap per fold
        ovs = []
        sel_c_by_fold = {s["fold_id"]: set(s["sel_idx"]) for s in sel_c}
        sel_i34_by_fold = {s["fold_id"]: set(s["sel_idx"]) for s in sel_i34}
        for fid in sel_c_by_fold:
            ov = len(sel_c_by_fold[fid] & sel_i34_by_fold.get(fid, set()))
            ovs.append(ov)
        overlap_per_fold.extend(ovs)
        c_pl = float(ccc_fn(y_t1, pl_pred)); c_i34 = float(ccc_fn(y_t1, i34_pred))
        per_seed.append({"seed": int(seed), "ccc_slotC": c_pl, "ccc_iter34_5fold": c_i34,
                         "delta": c_pl - c_i34, "wall_s": float(time.time() - t0),
                         "mean_kselect_overlap_with_iter34": float(np.mean(ovs))})
        pl_oofs.append(pl_pred); i34_oofs.append(i34_pred)
        print(f"  seed={seed}: slot_C={c_pl:.4f}  iter34={c_i34:.4f}  Δ={c_pl-c_i34:+.4f}  "
              f"K-overlap={np.mean(ovs):.0f}/500={np.mean(ovs)/500:.1%}", flush=True)
    mean_pl = np.mean(np.column_stack(pl_oofs), axis=1)
    mean_i34 = np.mean(np.column_stack(i34_oofs), axis=1)
    delta_mean = float(np.mean([s["delta"] for s in per_seed]))
    delta_std = float(np.std([s["delta"] for s in per_seed], ddof=1))
    boot = _paired_bootstrap_ccc(y_t1, mean_pl, mean_i34)
    pass_screen = (delta_mean >= 0.025) and (boot["frac_above_zero"] >= 0.95)
    summary = {
        "n_subjects": int(n), "seeds": list(seeds), "per_seed": per_seed,
        "delta_mean": delta_mean, "delta_std": delta_std,
        "ccc_slotC_meanof_seedmeans": float(ccc_fn(y_t1, mean_pl)),
        "ccc_iter34_5fold_meanof_seedmeans": float(ccc_fn(y_t1, mean_i34)),
        "bootstrap_paired_delta": boot,
        "screen_gate_pass": bool(pass_screen),
        "overlap_per_fold_summary": {
            "mean": float(np.mean(overlap_per_fold)),
            "std": float(np.std(overlap_per_fold)),
            "min": int(np.min(overlap_per_fold)),
            "max": int(np.max(overlap_per_fold)),
        },
    }
    print(f"\n  SCREEN: Δ̄={delta_mean:+.4f}  std={delta_std:.4f}  frac>0={boot['frac_above_zero']:.3f}  "
          f"→ {'PASS' if pass_screen else 'FAIL'}", flush=True)
    print(f"  K-overlap with iter34: {summary['overlap_per_fold_summary']['mean']:.0f} ± "
          f"{summary['overlap_per_fold_summary']['std']:.0f} (out of 500)", flush=True)
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("smoke", "write_prereg", "null_only", "screen", "lockbox"), default="smoke")
    p.add_argument("--prereg", help="prereg path")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n_workers", type=int, default=5)
    args = p.parse_args()
    if args.mode == "smoke": smoke_test(seed=args.seed)
    elif args.mode == "write_prereg": write_preregistration()
    elif args.mode == "null_only":
        nulls = run_null_gate(seed=args.seed)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = RESULTS_DIR / f"t1_iter39_slotC_nulls_{ts}.json"
        with open(out, "w") as f:
            json.dump(nulls, f, indent=2)
        print(f"\nNULLS saved: {out}", flush=True)
    elif args.mode == "screen":
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = RESULTS_DIR / f"screen_t1_iter39_slotC_{ts}.json"
        nulls = run_null_gate(seed=args.seed)
        if not nulls["null_gate_pass"]:
            screen = {
                "screen_aborted": True,
                "abort_reason": "null_gate_failed",
                "nulls": nulls,
                "screen_gate_pass": False,
            }
            print("\nSCREEN ABORTED: null gate failed", flush=True)
        else:
            screen = run_screen(n_workers=args.n_workers)
            screen["nulls"] = nulls
        with open(out, "w") as f:
            json.dump(screen, f, indent=2, default=str)
        print(f"\nSCREEN saved: {out}", flush=True)
    elif args.mode == "lockbox":
        print("LOCKBOX not implemented for slot C — pending screen result", flush=True)


if __name__ == "__main__":
    main()
