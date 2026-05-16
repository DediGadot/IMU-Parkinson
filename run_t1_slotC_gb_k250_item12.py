"""T1 Glass-Ceiling Push 2026-05-13, Slot C — sklearn GradientBoostingRegressor + K=250 at item-12.

Mechanism: custom 8-item RegressorChain where:
  - Item 12 chain step uses V2 features at K=250 univariate-corr-K-best
    (vs T1 residual). Base learner = sklearn GradientBoostingRegressor
    (n_estimators=300, max_depth=4, lr=0.05, subsample=0.8, min_samples_leaf=10).
  - Other items: V2 K=500 LGB-importance + LGB+XGB+ET ensemble (iter34 standard).
  - Chain order CCC-descending [12, 10, 14, 9, 11, 13, 15, 18] (item 12 first).

Mechanism source: T3 K-sweep wall #69 (2026-05-13) revealed sklearn GB at K=250
univariate-corr-K-best has different bias-variance from LGB at low N (T3 Δ=+0.073
vs iter47 LGB at K=500). Hypothesis: same hump curve applies to T1 item-12 residual.

This is orthogonal to Slot B (V3-GSP at item-12): same item, different mechanism
(model class + selection rule vs feature family).

Pre-registration: master `results/preregistration_t1_ceiling_push_20260513_043852.json` Slot C.
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
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import T1_ITEMS
from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES_V2 = 500
K_FEATURES_GB_ITEM12 = 250

T1_SUM_ITEMS: tuple[int, ...] = tuple(T1_ITEMS)
AUX_ITEMS: tuple[int, ...] = (15, 18)
CHAIN_ORDER: tuple[int, ...] = (12, 10, 14, 9, 11, 13, 15, 18)

BASE_LEARNERS_DEFAULT: tuple[str, ...] = ("lgb", "xgb", "et")


def _univariate_kselect(X, y, k):
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    yc = y - y.mean()
    Xc = X - X.mean(0)
    s = X.std(0) + 1e-9
    ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s * ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


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
    if base == "gb":
        return GradientBoostingRegressor(
            n_estimators=300, learning_rate=0.05, max_depth=4,
            min_samples_leaf=10, subsample=0.8, random_state=seed,
        )
    raise ValueError(f"unknown base learner {base!r}")


def _custom_chain_item12_gb(
    Xtr_v2_imp: np.ndarray,
    Xte_v2_imp: np.ndarray,
    Xtr_v2sel: np.ndarray,
    Xte_v2sel: np.ndarray,
    items_tr_residual: np.ndarray,
    y_t1_residual_tr: np.ndarray,
    seed: int,
    base_other: str,
):
    """Custom 8-item chain.

    Item 12 step: V2 K=250 univariate-corr-K-best selected against y_t1_residual_tr.
                  Base learner = sklearn GradientBoostingRegressor.
    Other steps:  V2 K=500 LGB-importance (Xtr_v2sel/Xte_v2sel), base learner = base_other.
    Chain order = CHAIN_ORDER (CCC-descending; item 12 first).
    """
    n_train, n_test = Xtr_v2sel.shape[0], Xte_v2sel.shape[0]
    n_items = len(CHAIN_ORDER)
    pred_test = np.zeros((n_test, n_items))

    for chain_step, item_id in enumerate(CHAIN_ORDER):
        if item_id == 12:
            # K=250 univariate-corr-K-best on full V2 imputed against y_t1 residual
            sel_idx = _univariate_kselect(Xtr_v2_imp, y_t1_residual_tr, K_FEATURES_GB_ITEM12)
            Xtr_step = Xtr_v2_imp[:, sel_idx]
            Xte_step = Xte_v2_imp[:, sel_idx]
            regr = _make_regr("gb", seed)
        else:
            Xtr_step = Xtr_v2sel
            Xte_step = Xte_v2sel
            regr = _make_regr(base_other, seed)
        # Add chain residuals from prior steps
        if chain_step > 0:
            Xtr_step = np.concatenate([Xtr_step, items_tr_residual[:, :chain_step]], axis=1)
            Xte_step = np.concatenate([Xte_step, pred_test[:, :chain_step]], axis=1)
        regr.fit(Xtr_step, items_tr_residual[:, chain_step])
        pred_test[:, chain_step] = regr.predict(Xte_step)
    return pred_test


def _fit_one_fold(args):
    fold_id, tr, te, X_v2, y_t1, X_s1, items, seed, bases_other = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # items residuals in CHAIN_ORDER ordering
    item_means: dict[int, float] = {}
    items_tr_cols: list[np.ndarray] = []
    for i in CHAIN_ORDER:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_cols.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_cols)

    # V2 imputation + V2 K=500 (for non-item-12 steps)
    Xtr_imp, Xte_imp = impute_fold(X_v2[tr], X_v2[te])
    y_t1_resid_tr = y_t1[tr] - s1_tr
    Xtr_v2sel, Xte_v2sel, _ = feature_select_fold(
        Xtr_imp, y_t1_resid_tr, Xte_imp, k=K_FEATURES_V2, seed=seed
    )

    # Average chain across non-item-12 base learners (still 3 in ensemble for fairness)
    ip_avg = None
    for b in bases_other:
        ip = _custom_chain_item12_gb(
            Xtr_imp, Xte_imp, Xtr_v2sel, Xte_v2sel,
            items_tr_arr, y_t1_resid_tr, seed, base_other=b,
        )
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases_other)

    t1_idx = [CHAIN_ORDER.index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    return te, s1_te + (t1_pred_from_items - sum_means_t1)


def _slotC_kfold(seed, X_v2, y_t1, X_s1, items, n_workers, n_splits=5):
    n = len(y_t1)
    preds = np.zeros(n)
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    jobs = [
        (fid, tr, te, X_v2, y_t1, X_s1, items, seed, BASE_LEARNERS_DEFAULT)
        for fid, (tr, te) in enumerate(kf.split(np.arange(n)))
    ]
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    print(f"    seed={seed} 5fold wall={time.time()-t0:.0f}s", flush=True)
    return preds


def _slotC_loocv(seed, X_v2, y_t1, X_s1, items, n_workers):
    n = len(y_t1)
    preds = np.zeros(n)
    jobs = [
        (fid, tr, te, X_v2, y_t1, X_s1, items, seed, BASE_LEARNERS_DEFAULT)
        for fid, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n)))
    ]
    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 15 == 0 or done == n:
                print(f"    seed={seed} {done}/{n} wall={time.time()-t0:.0f}s", flush=True)
    return preds


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 Glass-Ceiling Push 2026-05-13 Slot C — sklearn GB + K=250 at item-12 + CCC-descending order",
        "mechanism_source": "T3 K-sweep Wall #69 (2026-05-13): sklearn GB at K=250 univariate-corr-K-best gives T3 Δ=+0.073 vs iter47 canonical LGB at K=500. Hypothesis: same hump curve applies to T1 item-12.",
        "is_t1_ceiling_push_2026-05-13_slotC": True,
        "master_prereg": "results/preregistration_t1_ceiling_push_20260513_043852.json",
        "fwer_family_size": 4,
        "fwer_per_slot_gate_frac_gt0": 0.9875,
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "iter34 hygiene-corrected cohort N=92",
        },
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
        },
        "stage2": {
            "chain_order": list(CHAIN_ORDER),
            "chain_order_policy": "FIXED CCC-descending; item 12 step first",
            "per_step_feature_routing": {
                "item_12": f"V2 K={K_FEATURES_GB_ITEM12} univariate-corr-K-best (against y_t1 residual)",
                "items_9_10_11_13_14_15_18": f"V2 K={K_FEATURES_V2} LGB-importance (iter34 standard)",
            },
            "per_step_base_learner": {
                "item_12": "sklearn GradientBoostingRegressor(n_estimators=300, max_depth=4, lr=0.05, subsample=0.8, min_samples_leaf=10)",
                "items_9_10_11_13_14_15_18": "LGB + XGB-hist + ExtraTrees ensemble (iter34 canonical)",
            },
            "feature_select_k_v2": K_FEATURES_V2,
            "feature_select_k_gb_item12": K_FEATURES_GB_ITEM12,
            "ensemble_method": "average chain output across 3 'other' base learners",
            "items_summed_for_t1": list(T1_SUM_ITEMS),
        },
        "eval": {
            "screen_n_splits": 5,
            "screen_seeds": list(SEEDS_DEFAULT),
            "loocv_seeds": list(SEEDS_DEFAULT),
            "screen_gate": "5-fold Δ̄ vs iter34-5-fold (same KFold seeds) ≥ +0.020 AND seed std < 0.020",
            "loocv_gate": "paired bootstrap frac>0 ≥ 0.9875 vs iter34 LOOCV on N=92 AND vs iter12-honest on N=92",
            "comparator_iter34_5fold_oof": "results/iter34_5fold_comparator_20260513_050158.oof.npy",
        },
        "leakage_assertions": [
            "Stage-1 Ridge fit fold-local",
            "feature_select_fold + impute_fold operate on outer-train only",
            "K=250 univariate-corr selection at item-12 step uses outer-train labels only (y_t1 residual)",
            "sklearn GB uses subsample=0.8 (fold-internal stochasticity, no test info)",
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
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"preregistration_t1_slotC_gb_k250_item12_{ts}.json"
    with open(out, "w") as f:
        json.dump({
            "timestamp_utc": ts,
            "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
            "name": "T1 Glass-Ceiling Push 2026-05-13 Slot C pre-registration",
            "formula_sha256": sha,
            "formula_payload": payload,
            "git_sha": _git_head(),
        }, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _paired_bootstrap_ccc(y, p_a, p_b, n_boot=5000, seed=42):
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
    }


def smoke_test(seed=42, feature_set="A3_tier1"):
    print("\n=== Slot C SMOKE TEST: 1 fold × 1 seed ===", flush=True)
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X_v2, y_t1, X_s1, items, seed, BASE_LEARNERS_DEFAULT)
    t0 = time.time()
    te_idx, te_pred = _fit_one_fold(args)
    print(f"  fold 0/{n}: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
          f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
          f"wall={time.time()-t0:.1f}s", flush=True)
    assert np.isfinite(te_pred).all(), "non-finite predictions"
    print("  SMOKE PASS", flush=True)


def run_screen_5fold(seeds=SEEDS_DEFAULT, feature_set="A3_tier1", n_workers=2):
    print(f"\n=== Slot C 5-FOLD SCREEN ({len(seeds)} seeds, workers={n_workers}) ===", flush=True)
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    comparators = sorted(RESULTS_DIR.glob("iter34_5fold_comparator_*.json"))
    if not comparators:
        raise FileNotFoundError("No iter34_5fold_comparator_*.json — run iter34_5fold_comparator.py first")
    comp_json = json.loads(comparators[-1].read_text())
    sids_c = [str(s) for s in comp_json["per_subject"]["sids"]]
    sid_to_pred = dict(zip(sids_c, comp_json["per_subject"]["y_pred_pooled"]))
    iter34_5fold = np.array([sid_to_pred[str(s)] for s in sids])
    comparator_label = comparators[-1].stem
    print(f"  comparator: {comparator_label}, CCC={ccc_fn(y_t1, iter34_5fold):.4f}", flush=True)

    per_seed = []
    seed_preds = []
    for seed in seeds:
        t0 = time.time()
        p = _slotC_kfold(seed, X_v2, y_t1, X_s1, items, n_workers)
        c_slotC = float(ccc_fn(y_t1, p))
        c_iter34 = float(ccc_fn(y_t1, iter34_5fold))
        delta = c_slotC - c_iter34
        per_seed.append({"seed": seed, "ccc_slotC_5fold": round(c_slotC, 4),
                         "ccc_iter34_5fold": round(c_iter34, 4),
                         "delta": round(delta, 4),
                         "wall_sec": round(time.time() - t0, 1)})
        print(f"  seed={seed}: slotC_5fold={c_slotC:.4f} | iter34_5fold={c_iter34:.4f} | "
              f"Δ={delta:+.4f} | wall={time.time()-t0:.0f}s", flush=True)
        seed_preds.append(p)

    deltas = [p["delta"] for p in per_seed]
    mean_delta = float(np.mean(deltas))
    std_delta = float(np.std(deltas))
    screen_pass = bool(mean_delta >= 0.020 and std_delta < 0.020)
    verdict = "PROMOTE_TO_LOOCV" if screen_pass else "CLOSE_SLOT_SCREEN_FAIL"
    pooled = np.mean(np.column_stack(seed_preds), axis=1)
    pooled_ccc = float(ccc_fn(y_t1, pooled))
    pooled_delta = pooled_ccc - float(ccc_fn(y_t1, iter34_5fold))

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"screen_t1_slotC_gb_k250_item12_{ts}.json"
    with open(out, "w") as f:
        json.dump({
            "name": "T1 Slot C 5-fold screen (sklearn GB + K=250 at item-12)",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "cohort_N": int(n),
            "chain_order": list(CHAIN_ORDER),
            "comparator_label": comparator_label,
            "per_seed": per_seed,
            "mean_delta": round(mean_delta, 4),
            "std_delta": round(std_delta, 4),
            "pooled_ccc_slotC": round(pooled_ccc, 4),
            "pooled_delta_vs_iter34": round(pooled_delta, 4),
            "screen_gate": "Δ̄ ≥ +0.020 AND std < 0.020",
            "screen_pass": screen_pass,
            "verdict": verdict,
        }, f, indent=2)
    print(f"\n  5-fold result: mean_delta={mean_delta:+.4f}, std={std_delta:.4f}, pooled CCC={pooled_ccc:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out}")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["write_prereg", "smoke", "screen_5fold", "lockbox"], default="smoke")
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()
    if args.mode == "write_prereg":
        write_preregistration()
    elif args.mode == "smoke":
        smoke_test()
    elif args.mode == "screen_5fold":
        run_screen_5fold(n_workers=args.workers)
    elif args.mode == "lockbox":
        raise SystemExit("lockbox mode pending; first run screen_5fold")


if __name__ == "__main__":
    main()
