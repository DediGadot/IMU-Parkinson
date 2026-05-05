"""T3 iter31 — Multi-task LGB on items 1-18 LOCKBOX (formula_sha256 + LOOCV).

Mirror of run_t1_iter30b_lockbox.py adapted for T3 cohort (N=98, target=updrs3
column from V2_FEATURES). Comparator: iter5-direct-T3 (canonical CCC=0.5227 LOOCV)
plus iter5 lockbox OOF.

Modes: write_prereg | lockbox.
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
from run_t3_iter3 import load_full_pd_data
from run_t3_iter30a_multitask import _load_t3_cohort_with_items, ALL_ITEMS
from run_t1_iter29b_multitask_lgb import _multitask_lgb_predict

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
PUBLISHED_T3_LOOCV_CCC = 0.5227
ITER5_LOCKBOX_OOF = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy"
ITER5_LOCKBOX_JSON = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.json"


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T3 iter31 multi-task LGB chain on items 1-18",
        "cohort": {"target": "updrs3 (V2_FEATURES column)", "n_subjects": 98},
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA, "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9, "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1", "target": "updrs3",
        },
        "stage2": {
            "model": "sklearn.multioutput.RegressorChain over LGBMRegressor",
            "variant": "V1_random",
            "lgb_params": {
                "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 15,
                "min_data_in_leaf": 10, "n_jobs": 1, "verbose": -1,
            },
            "items_targets": list(ALL_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES, "imputation": "fold_local_median",
            "post_combine_formula": "Stage1_pred + (sum(item_pred + train_mean) - sum(train_mean))",
        },
        "eval": {
            "loocv_n": 98, "seeds": list(SEEDS_DEFAULT),
            "headline_metric": "CCC of mean-of-3-seed predictions",
            "comparator_iter5_lockbox_oof": ITER5_LOCKBOX_OOF.name,
            "comparator_iter5_published_loocv": PUBLISHED_T3_LOOCV_CCC,
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run.",
            "Headline = CCC of mean-of-3-seed preds on N=98.",
            "Pass-canonical: paired-bootstrap (n=5000) vs iter5-lockbox-OOF frac>0 ≥ 0.95 AND headline > 0.5227.",
        ],
    }


def _formula_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
        "experiment": "T3 iter31 multi-task LGB chain on items 1-18 LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "n_subjects": 98, "variant": "V1_random",
        "eval_protocol": (
            "LOOCV (n=98) on T3 cohort. Stage-1 Ridge (alpha=1.0) on H&Y + cv_yrs + "
            "cv_sex + cv_dbs with per-fold standardisation, target=updrs3. Stage-2 "
            "RegressorChain(LGBMRegressor) random order on per-item residuals "
            "(items 1-18, train-mean-centered) with K=500 LGB-importance selection per fold. "
            "3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t3_iter31_multitask_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _multitask_loocv_t3(seed: int, feature_set="A3_tier1"):
    sids, X, y_t3, hy, items = _load_t3_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    t0 = time.time()
    for fold_id, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=STAGE1_ALPHA)
        item_means = {}
        items_tr_residual = []
        for i in ALL_ITEMS:
            v = items[i][tr]
            mu = float(np.nanmean(v)) if np.any(~np.isnan(v)) else 0.0
            item_means[i] = mu
            items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_residual)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t3[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        ip = _multitask_lgb_predict(Xtr_sel, items_tr_arr, Xte_sel, seed)
        item_pred_te = ip + np.array([item_means[i] for i in ALL_ITEMS])
        t3_pred_from_items = item_pred_te.sum(axis=1)
        sum_means = float(sum(item_means.values()))
        preds[te] = s1_te + (t3_pred_from_items - sum_means)
        if (fold_id + 1) % 10 == 0:
            print(f"    seed={seed} fold {fold_id+1}/{n}  elapsed={time.time()-t0:.0f}s", flush=True)
    return sids, y_t3, preds


def _iter5_direct_loocv_t3(seed: int, feature_set="A3_tier1"):
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in LeaveOneOut().split(np.arange(n)):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t3[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t3[tr] - s1_tr, Xte_sel, seed)
    return y_t3, preds


def _load_iter5_lockbox_oof(sids_ref, y_ref):
    if not (ITER5_LOCKBOX_OOF.exists() and ITER5_LOCKBOX_JSON.exists()):
        return None
    iter5 = np.load(ITER5_LOCKBOX_OOF)
    with open(ITER5_LOCKBOX_JSON) as f:
        meta = json.load(f)
    sids_lb = list(meta["per_subject"]["sids"])
    y_lb = np.array(meta["per_subject"]["y_true"], dtype=np.float64)
    if [str(s) for s in sids_lb] != [str(s) for s in sids_ref]:
        # Try alignment
        sid_to_pred = dict(zip(sids_lb, iter5.tolist()))
        return np.array([sid_to_pred.get(str(s), np.nan) for s in sids_ref])
    if not np.allclose(y_lb, y_ref, atol=1e-6):
        return None
    return iter5


def run_lockbox(prereg_file: Path, seeds: tuple[int, ...] = SEEDS_DEFAULT, feature_set="A3_tier1"):
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )
    print(f"\n=== T3 iter31 multi-task LOCKBOX LOOCV ({len(seeds)} seeds, N=98) ===", flush=True)

    all_mt: list[np.ndarray] = []
    all_i5: list[np.ndarray] = []
    sids_ref = None; y_ref = None
    per_seed = []
    for seed in seeds:
        t0 = time.time()
        sids, y_t3, p_mt = _multitask_loocv_t3(seed, feature_set)
        _, p_i5 = _iter5_direct_loocv_t3(seed, feature_set)
        c_mt, c_i5 = float(ccc_fn(y_t3, p_mt)), float(ccc_fn(y_t3, p_i5))
        per_seed.append({"seed": seed, "ccc_mt": c_mt, "ccc_i5": c_i5,
                         "delta": c_mt - c_i5, "wall": time.time() - t0})
        print(f"  seed={seed}: mt={c_mt:.4f} | i5={c_i5:.4f} | Δ={c_mt-c_i5:+.4f} | "
              f"{time.time()-t0:.0f}s", flush=True)
        all_mt.append(p_mt); all_i5.append(p_i5)
        sids_ref = sids; y_ref = y_t3

    mean_mt = np.mean(np.column_stack(all_mt), axis=1)
    mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
    headline = full_metrics(y_ref, mean_mt, label="t3_iter31_multitask")

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

    iter5_lb = _load_iter5_lockbox_oof(sids_ref, y_ref)
    iter5_lb_block = None
    if iter5_lb is not None:
        ccc_lb = float(ccc_fn(y_ref, iter5_lb))
        deltas_lb = np.empty(5000)
        for i in range(5000):
            idx = rng.randint(0, n, n)
            deltas_lb[i] = ccc_fn(y_ref[idx], mean_mt[idx]) - ccc_fn(y_ref[idx], iter5_lb[idx])
        iter5_lb_block = {
            "ccc_iter5_lockbox": round(ccc_lb, 4),
            "delta_mean": float(deltas_lb.mean()),
            "delta_ci_low": float(np.percentile(deltas_lb, 2.5)),
            "delta_ci_high": float(np.percentile(deltas_lb, 97.5)),
            "frac_above_zero": float((deltas_lb > 0).mean()),
        }
    is_canonical = bool(boot_i5["frac_above_zero"] >= 0.95 and headline["ccc"] > PUBLISHED_T3_LOOCV_CCC)
    headline.update({
        "preregistration_file": prereg_file.name, "is_lockbox_headline": True,
        "n_seeds": len(seeds), "per_seed": per_seed,
        "ccc_iter5_direct_loocv_baseline": round(float(ccc_fn(y_ref, mean_i5)), 4),
        "delta_vs_iter5_direct": round(headline["ccc"] - float(ccc_fn(y_ref, mean_i5)), 4),
        "bootstrap_delta_vs_iter5_direct": boot_i5,
        "bootstrap_delta_vs_iter5_lockbox": iter5_lb_block,
        "is_canonical_update": is_canonical,
        "per_subject": {"sids": [str(s) for s in sids_ref],
                        "y_true": y_ref.tolist(), "y_pred": mean_mt.tolist()},
    })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t3_iter31_multitask_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t3_iter31_multitask_{ts}.oof.npy"
    np.save(out_npy, mean_mt)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f} ===", flush=True)
    print(f"  iter5-direct LOOCV: Δ={headline['delta_vs_iter5_direct']:+.4f}, frac>0={boot_i5['frac_above_zero']:.3f}", flush=True)
    if iter5_lb_block:
        print(f"  vs iter5 lockbox 0.5227: ccc_lb={iter5_lb_block['ccc_iter5_lockbox']:.4f}, "
              f"Δ̄={iter5_lb_block['delta_mean']:+.4f}, frac>0={iter5_lb_block['frac_above_zero']:.3f}", flush=True)
    print(f"  is_canonical_update = {is_canonical}", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()
    if args.mode == "write_prereg":
        write_preregistration()
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required")
        run_lockbox(Path(args.preregistration_file), tuple(args.seeds), args.feature_set)


if __name__ == "__main__":
    main()
