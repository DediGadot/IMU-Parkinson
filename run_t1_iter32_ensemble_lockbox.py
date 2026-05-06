"""T1 iter32 — Multi-task chain ENSEMBLE LOCKBOX (V1_random + V2_clinical + V3_correlation).

Per multi-LLM convergence (codex GPT-5.5 + gemini-3.1-pro post-iter31):
  Highest-EV move to push T1 multi-task bootstrap frac>0 above strict 0.95 gate
  is to AVERAGE the predictions of three independent chain-order variants.
  Target-sequence bias is the main unmitigated variance source in RegressorChain.

Per fold (LOOCV × 3 seeds × 3 orders = 9× per fold):
  Stage 1 = same as iter30b lockbox (Ridge α=1.0 on H&Y + cv_yrs + cv_sex + cv_dbs).
  Stage 2 = mean of three RegressorChain(LGBMRegressor) predictions:
    • V1_random  (default RegressorChain random order, seeded by outer seed)
    • V2_clinical (gait→FoG→stability→posture→brady fixed clinical-domain order)
    • V3_correlation (sort items by |corr(item, T1)| in train fold, descending)
  Final pred = Stage1 + (mean_chain_pred - sum_train_means)

Comparator: iter5-direct-T1 LOOCV mean preds.
Modes: write_prereg | lockbox.

formula_sha256 written BEFORE LOOCV (post F47 retraction discipline).
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
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import load_pd_data as load_t1_pd_data, T1_ITEMS
from run_t1_iter30b_multitask_variants import _multitask_predict, _load_t1_cohort_with_items

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
PUBLISHED_T1_LOOCV_CCC = 0.6550

ENSEMBLE_ORDERS = ("random", "clinical", "correlation")


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 iter32 multi-task chain ENSEMBLE (V1+V2+V3 averaged)",
        "cohort": {"target": "T1 = sum(items 9-14)", "n_subjects": 94},
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA, "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9, "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1", "target": "T1",
        },
        "stage2": {
            "model": "Mean of 3 sklearn.multioutput.RegressorChain(LGBMRegressor)",
            "ensemble_orders": list(ENSEMBLE_ORDERS),
            "lgb_params": {
                "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 15,
                "min_data_in_leaf": 10, "n_jobs": 1, "verbose": -1,
            },
            "items_targets": list(T1_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES, "imputation": "fold_local_median",
            "post_combine_formula": (
                "Stage1_pred + (mean_over_orders(sum_item_pred + train_mean) - sum_train_means)"
            ),
            "ensemble_weights": "uniform across orders",
        },
        "eval": {
            "loocv_n": 94, "seeds": list(SEEDS_DEFAULT),
            "headline_metric": "CCC of mean-of-3-seed predictions (each seed = mean of 3 orders)",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
            "comparator_iter12_honest_loocv_oof": "results/t1_iter12_honest_composite.oof.npy",
            "comparator_iter30b_v1_lockbox_oof": "results/lockbox_t1_iter30b_V1_random_20260505_211112.oof.npy",
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run.",
            "Headline = CCC of mean-of-3-seed preds on N=94.",
            "Pass-canonical: paired-bootstrap (n=5000) vs iter5-direct frac>0 ≥ 0.95 AND headline > 0.6550.",
            "Pre-reg written BEFORE any LOOCV run for this ensemble (per multi-LLM consult).",
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
        "timestamp": ts, "iso_datetime": datetime.now().isoformat(),
        "experiment": "T1 iter32 multi-task chain ENSEMBLE (V1+V2+V3) LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "n_subjects": 94, "variant": "ensemble_v1_v2_v3",
        "eval_protocol": (
            "LOOCV (n=94) on T1 cohort. Stage-1 Ridge (alpha=1.0) on H&Y + cv_yrs + "
            "cv_sex + cv_dbs with per-fold standardisation. Stage-2 mean of three "
            "RegressorChain(LGBMRegressor) predictions: random/clinical/correlation orders, "
            "each on per-item residuals (items 9-14, train-mean-centered) with "
            "K=500 LGB-importance selection per fold. 3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_iter32_ensemble_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _fit_one_fold(args):
    """Worker: fit Stage1+ensemble Stage2 for one LOOCV fold. Returns (te_idx, te_pred)."""
    fold_id, tr, te, X, y_t1, X_s1, items, seed = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means = {}
    items_tr_residual = []
    for i in T1_ITEMS:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )
    order_preds = []
    for order in ENSEMBLE_ORDERS:
        kwargs = {"base": "lgb", "order": order}
        if order == "correlation":
            kwargs["y_t1_tr"] = y_t1[tr]
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, **kwargs)
        item_pred_te = ip + np.array([item_means[i] for i in T1_ITEMS])
        order_preds.append(item_pred_te.sum(axis=1))
    t1_pred_from_items = np.mean(np.column_stack(order_preds), axis=1)
    sum_means = float(sum(item_means.values()))
    return te, s1_te + (t1_pred_from_items - sum_means)


def _ensemble_loocv(seed: int, feature_set="A3_tier1", n_workers: int = 14):
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, seed) for fid, (tr, te) in enumerate(splits)]
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 20 == 0:
                print(f"    seed={seed} {done}/{n} folds done  elapsed={time.time()-t0:.0f}s", flush=True)
    return sids, y_t1, preds


def _i5_one_fold(args):
    fold_id, tr, te, X, y_t1, X_s1, seed = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )
    return te, s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)


def _iter5_direct_loocv(seed: int, feature_set="A3_tier1", n_workers: int = 14):
    sids, X, y_t1, hy, _ = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [(fid, tr, te, X, y_t1, X_s1, seed) for fid, (tr, te) in enumerate(splits)]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_i5_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return y_t1, preds


def run_lockbox(prereg_file: Path, seeds: tuple[int, ...] = SEEDS_DEFAULT, feature_set="A3_tier1", n_workers: int = 14):
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )
    print(f"\n=== T1 iter32 ENSEMBLE LOCKBOX LOOCV ({len(seeds)} seeds, N=94, "
          f"orders={ENSEMBLE_ORDERS}) ===", flush=True)

    all_mt: list[np.ndarray] = []
    all_i5: list[np.ndarray] = []
    sids_ref = None; y_ref = None
    per_seed = []
    for seed in seeds:
        t0 = time.time()
        sids, y_t1, p_mt = _ensemble_loocv(seed, feature_set, n_workers=n_workers)
        _, p_i5 = _iter5_direct_loocv(seed, feature_set, n_workers=n_workers)
        c_mt, c_i5 = float(ccc_fn(y_t1, p_mt)), float(ccc_fn(y_t1, p_i5))
        per_seed.append({"seed": seed, "ccc_mt": c_mt, "ccc_i5": c_i5,
                         "delta": c_mt - c_i5, "wall": time.time() - t0})
        print(f"  seed={seed}: ENS={c_mt:.4f} | i5={c_i5:.4f} | Δ={c_mt-c_i5:+.4f} | "
              f"{time.time()-t0:.0f}s", flush=True)
        all_mt.append(p_mt); all_i5.append(p_i5)
        sids_ref = sids; y_ref = y_t1

    mean_mt = np.mean(np.column_stack(all_mt), axis=1)
    mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
    headline = full_metrics(y_ref, mean_mt, label="t1_iter32_ensemble")

    # Bootstrap vs iter5-direct
    rng = np.random.RandomState(42)
    n = len(y_ref)
    deltas = np.empty(5000)
    for i in range(5000):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y_ref[idx], mean_mt[idx]) - ccc_fn(y_ref[idx], mean_i5[idx])
    boot_i5 = {
        "n_boot": 5000, "delta_mean": float(deltas.mean()),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float((deltas > 0).mean()),
        "frac_above_0.025": float((deltas > 0.025).mean()),
    }

    # Bootstrap vs iter12 honest
    iter12_path = RESULTS_DIR / "t1_iter12_honest_composite.oof.npy"
    iter12_json = RESULTS_DIR / "t1_iter12_honest_composite.json"
    iter12_block = None
    if iter12_path.exists() and iter12_json.exists():
        with open(iter12_json) as f:
            i12 = json.load(f)
        sids_i12 = [str(s) for s in i12["per_subject"]["sids"]]
        p_i12_full = np.load(iter12_path)
        sid_to_pred = dict(zip(sids_i12, p_i12_full.tolist()))
        try:
            p_i12 = np.array([sid_to_pred[str(s)] for s in sids_ref])
            ccc_i12 = float(ccc_fn(y_ref, p_i12))
            deltas_i12 = np.empty(5000)
            for i in range(5000):
                idx = rng.randint(0, n, n)
                deltas_i12[i] = ccc_fn(y_ref[idx], mean_mt[idx]) - ccc_fn(y_ref[idx], p_i12[idx])
            iter12_block = {
                "ccc_iter12": round(ccc_i12, 4),
                "delta_mean": float(deltas_i12.mean()),
                "delta_ci_low": float(np.percentile(deltas_i12, 2.5)),
                "delta_ci_high": float(np.percentile(deltas_i12, 97.5)),
                "frac_above_zero": float((deltas_i12 > 0).mean()),
                "frac_above_0.025": float((deltas_i12 > 0.025).mean()),
            }
        except KeyError:
            iter12_block = None

    # Bootstrap vs iter30b V1 lockbox (compare ENSEMBLE to single-order V1)
    v1_path = RESULTS_DIR / "lockbox_t1_iter30b_V1_random_20260505_211112.oof.npy"
    v1_json = RESULTS_DIR / "lockbox_t1_iter30b_V1_random_20260505_211112.json"
    v1_block = None
    if v1_path.exists() and v1_json.exists():
        with open(v1_json) as f:
            v1 = json.load(f)
        sids_v1 = [str(s) for s in v1["per_subject"]["sids"]]
        p_v1_full = np.load(v1_path)
        sid_to_pred_v1 = dict(zip(sids_v1, p_v1_full.tolist()))
        try:
            p_v1 = np.array([sid_to_pred_v1[str(s)] for s in sids_ref])
            ccc_v1 = float(ccc_fn(y_ref, p_v1))
            deltas_v1 = np.empty(5000)
            for i in range(5000):
                idx = rng.randint(0, n, n)
                deltas_v1[i] = ccc_fn(y_ref[idx], mean_mt[idx]) - ccc_fn(y_ref[idx], p_v1[idx])
            v1_block = {
                "ccc_v1_lockbox": round(ccc_v1, 4),
                "delta_mean": float(deltas_v1.mean()),
                "delta_ci_low": float(np.percentile(deltas_v1, 2.5)),
                "delta_ci_high": float(np.percentile(deltas_v1, 97.5)),
                "frac_above_zero": float((deltas_v1 > 0).mean()),
            }
        except KeyError:
            v1_block = None

    is_canonical = bool(boot_i5["frac_above_zero"] >= 0.95 and headline["ccc"] > PUBLISHED_T1_LOOCV_CCC)
    headline.update({
        "preregistration_file": prereg_file.name, "is_lockbox_headline": True,
        "n_seeds": len(seeds), "per_seed": per_seed,
        "ccc_iter5_direct_loocv_baseline": round(float(ccc_fn(y_ref, mean_i5)), 4),
        "delta_vs_iter5_direct": round(headline["ccc"] - float(ccc_fn(y_ref, mean_i5)), 4),
        "bootstrap_delta_vs_iter5": boot_i5,
        "bootstrap_delta_vs_iter12_honest": iter12_block,
        "bootstrap_delta_vs_iter30b_v1_random": v1_block,
        "is_canonical_update": is_canonical,
        "per_subject": {"sids": [str(s) for s in sids_ref],
                        "y_true": y_ref.tolist(), "y_pred": mean_mt.tolist()},
    })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter32_ensemble_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter32_ensemble_{ts}.oof.npy"
    np.save(out_npy, mean_mt)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
          f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===", flush=True)
    print(f"  iter5-direct LOOCV: Δ={headline['delta_vs_iter5_direct']:+.4f}, "
          f"frac>0={boot_i5['frac_above_zero']:.3f}", flush=True)
    if iter12_block:
        print(f"  vs iter12 honest 0.6550: ccc_i12={iter12_block['ccc_iter12']:.4f}, "
              f"Δ̄={iter12_block['delta_mean']:+.4f}, frac>0={iter12_block['frac_above_zero']:.3f}", flush=True)
    if v1_block:
        print(f"  vs iter30b V1 single-order: ccc_v1={v1_block['ccc_v1_lockbox']:.4f}, "
              f"Δ̄={v1_block['delta_mean']:+.4f}, frac>0={v1_block['frac_above_zero']:.3f}", flush=True)
    print(f"  is_canonical_update = {is_canonical}", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("ITER32_WORKERS", 14)))
    args = ap.parse_args()
    if args.mode == "write_prereg":
        write_preregistration()
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required")
        run_lockbox(Path(args.preregistration_file), tuple(args.seeds), args.feature_set,
                    n_workers=args.n_workers)


if __name__ == "__main__":
    main()
