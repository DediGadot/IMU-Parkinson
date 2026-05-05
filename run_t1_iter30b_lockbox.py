"""T1 iter30-B LOCKBOX — formula_sha256 pre-registration + LOOCV + paired bootstrap.

Per multi-LLM consult convergence (codex/gemini/deepseek/grok/kimi all agreed):
the iter29b breakthrough cannot be lockboxed without a formula_sha256 pre-reg
written BEFORE the headline LOOCV is run. This script:

  --mode write_prereg     →  write JSON pre-reg with formula_sha256, no eval.
  --mode lockbox          →  load pre-reg, verify formula_sha256 still matches,
                             then run LOOCV (3 seeds, mean preds), paired bootstrap
                             vs iter5-direct-T1 LOOCV OOF and iter12 honest composite.
                             Writes lockbox JSON + .oof.npy.

Variant frozen via --variant; one of V1_random / V2_clinical / V3_correlation /
V4_catboost / V6_calibrated / V7_blend_with_iter5 (matches run_t1_iter30b_multitask_variants.py).
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
from sklearn.model_selection import KFold, LeaveOneOut

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
from run_t1_iter30b_multitask_variants import (
    _multitask_predict, _load_t1_cohort_with_items, run_variant,
)

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
PUBLISHED_T1_LOOCV_CCC = 0.6550


def _formula_payload(variant: str) -> dict[str, Any]:
    return {
        "experiment": "T1 iter30-B multi-task LGB chain on items 9-14",
        "cohort": {"target": "T1 = sum(items 9-14)", "n_subjects": 94, "filter": "PD with full items 9-14"},
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9,  # 6 H&Y dummies + 3 clinical
            "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
            "target": "T1 (sum items 9-14)",
        },
        "stage2": {
            "model": "sklearn.multioutput.RegressorChain over LGBMRegressor",
            "variant": variant,
            "lgb_params": {
                "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 15,
                "min_data_in_leaf": 10, "n_jobs": 1, "verbose": -1,
            },
            "items_targets": list(T1_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES,
            "imputation": "fold_local_median",
            "post_combine_formula": "Stage1_pred + (sum(item_pred + train_mean) - sum(train_mean))",
        },
        "eval": {
            "loocv_n": 94, "seeds": list(SEEDS_DEFAULT),
            "fold_construction_5fold": "KFold(shuffle=True, random_state=seed)",
            "headline_metric": "CCC of mean-of-3-seed predictions",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
            "comparator_iter12_honest_loocv_oof": "results/t1_iter12_honest_composite.oof.npy",
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run.",
            "Headline = CCC of mean-of-3-seed preds on N=94.",
            "Pass-canonical: paired-bootstrap (n=5000) vs iter5-direct-T1 frac>0 ≥ 0.95 AND headline > 0.6550.",
            "Pre-reg written BEFORE any LOOCV run for this variant (per multi-LLM consult).",
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


def write_preregistration(variant: str) -> Path:
    payload = _formula_payload(variant)
    sha = _formula_sha256(payload)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts, "iso_datetime": datetime.now().isoformat(),
        "experiment": f"T1 iter30-B {variant} — multi-task LGB chain LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "n_subjects": 94, "variant": variant,
        "eval_protocol": (
            "LOOCV (n=94) on T1 cohort. Stage-1 Ridge (alpha=1.0) on H&Y + cv_yrs + "
            "cv_sex + cv_dbs with per-fold standardisation, target=T1. Stage-2 "
            f"RegressorChain(LGBMRegressor) variant '{variant}' on per-item residuals "
            "(items 9-14, train-mean-centered) with K=500 LGB-importance selection per fold. "
            "3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_iter30b_{variant}_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _multitask_loocv(variant: str, seed: int, feature_set="A3_tier1") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pure LOOCV on the T1 cohort using the pre-registered variant config."""
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    t0 = time.time()
    for fold_id, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
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

        if variant == "V1_random":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb", order="random")
        elif variant == "V2_clinical":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb", order="clinical")
        elif variant == "V3_correlation":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb",
                                    order="correlation", y_t1_tr=y_t1[tr])
        elif variant == "V4_catboost":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="catboost", order="random")
        else:
            raise NotImplementedError(f"LOOCV not yet wired for variant {variant!r}")

        item_pred_te = ip + np.array([item_means[i] for i in T1_ITEMS])
        t1_pred_from_items = item_pred_te.sum(axis=1)
        sum_means = float(sum(item_means.values()))
        preds[te] = s1_te + (t1_pred_from_items - sum_means)
        if (fold_id + 1) % 10 == 0:
            print(f"    seed={seed} fold {fold_id+1}/{n}  elapsed={time.time()-t0:.0f}s", flush=True)
    return sids, y_t1, preds


def _iter5_direct_loocv(seed: int, feature_set="A3_tier1") -> tuple[np.ndarray, np.ndarray]:
    sids, X, y_t1, hy, _ = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in LeaveOneOut().split(np.arange(n)):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
    return y_t1, preds


def run_lockbox(preregistration_file: Path, variant: str,
                seeds: tuple[int, ...] = SEEDS_DEFAULT, feature_set="A3_tier1") -> Path:
    if not preregistration_file.exists():
        raise FileNotFoundError(f"missing preregistration: {preregistration_file}")
    with open(preregistration_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload(variant))
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )
    print(f"\n=== T1 iter30-B {variant} LOCKBOX LOOCV ({len(seeds)} seeds, N=94) ===", flush=True)

    all_mt: list[np.ndarray] = []
    all_i5: list[np.ndarray] = []
    sids_ref: np.ndarray | None = None
    y_ref: np.ndarray | None = None
    per_seed = []
    for seed in seeds:
        t0 = time.time()
        sids, y_t1, p_mt = _multitask_loocv(variant, seed, feature_set)
        _, p_i5 = _iter5_direct_loocv(seed, feature_set)
        c_mt, c_i5 = float(ccc_fn(y_t1, p_mt)), float(ccc_fn(y_t1, p_i5))
        per_seed.append({"seed": seed, "ccc_mt": c_mt, "ccc_i5": c_i5,
                         "delta": c_mt - c_i5, "wall": time.time() - t0})
        print(f"  seed={seed}: mt={c_mt:.4f} | i5={c_i5:.4f} | Δ={c_mt-c_i5:+.4f} | "
              f"{time.time()-t0:.0f}s", flush=True)
        all_mt.append(p_mt); all_i5.append(p_i5)
        sids_ref = sids; y_ref = y_t1

    mean_mt = np.mean(np.column_stack(all_mt), axis=1)
    mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
    headline = full_metrics(y_ref, mean_mt, label=f"t1_iter30b_{variant}")
    headline_i5 = full_metrics(y_ref, mean_i5, label="iter5_direct_t1_loocv_baseline")

    # Bootstrap Δ vs iter5-direct
    rng = np.random.RandomState(42)
    n = len(y_ref)
    deltas_i5 = np.empty(5000)
    for i in range(5000):
        idx = rng.randint(0, n, n)
        deltas_i5[i] = ccc_fn(y_ref[idx], mean_mt[idx]) - ccc_fn(y_ref[idx], mean_i5[idx])
    boot_i5 = {
        "n_boot": 5000, "delta_mean": float(deltas_i5.mean()),
        "delta_ci_low": float(np.percentile(deltas_i5, 2.5)),
        "delta_ci_high": float(np.percentile(deltas_i5, 97.5)),
        "frac_above_zero": float((deltas_i5 > 0).mean()),
        "frac_above_0.025": float((deltas_i5 > 0.025).mean()),
    }

    # Compare to iter12 honest if available
    iter12_path = RESULTS_DIR / "t1_iter12_honest_composite.oof.npy"
    iter12_json = RESULTS_DIR / "t1_iter12_honest_composite.json"
    iter12_block = None
    if iter12_path.exists() and iter12_json.exists():
        with open(iter12_json) as f:
            i12 = json.load(f)
        sids_i12 = i12.get("per_subject", {}).get("sids", [])
        y_i12 = i12.get("per_subject", {}).get("y_true", [])
        p_i12 = np.load(iter12_path)
        if len(sids_i12) == len(sids_ref) and all(str(a) == str(b) for a, b in zip(sids_i12, sids_ref)):
            ccc_i12 = float(ccc_fn(np.asarray(y_i12), p_i12))
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
            }

    is_canonical = bool(boot_i5["frac_above_zero"] >= 0.95 and headline["ccc"] > PUBLISHED_T1_LOOCV_CCC)

    headline.update({
        "variant": variant, "preregistration_file": preregistration_file.name,
        "is_lockbox_headline": True, "n_seeds": len(seeds), "per_seed": per_seed,
        "ccc_iter5_direct_loocv_baseline": round(headline_i5["ccc"], 4),
        "delta_vs_iter5_direct": round(headline["ccc"] - headline_i5["ccc"], 4),
        "bootstrap_delta_vs_iter5": boot_i5,
        "bootstrap_delta_vs_iter12_honest": iter12_block,
        "is_canonical_update": is_canonical,
        "per_subject": {"sids": [str(s) for s in sids_ref],
                        "y_true": y_ref.tolist(), "y_pred": mean_mt.tolist()},
    })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter30b_{variant}_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter30b_{variant}_{ts}.oof.npy"
    np.save(out_npy, mean_mt)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
          f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===", flush=True)
    print(f"  iter5-direct LOOCV (mean of 3 seeds): {headline_i5['ccc']:.4f}  Δ={headline['delta_vs_iter5_direct']:+.4f}", flush=True)
    print(f"  Bootstrap vs iter5: mean Δ={boot_i5['delta_mean']:+.4f}, "
          f"CI=[{boot_i5['delta_ci_low']:+.4f}, {boot_i5['delta_ci_high']:+.4f}], "
          f"frac>0={boot_i5['frac_above_zero']:.3f}", flush=True)
    if iter12_block:
        print(f"  vs iter12 honest 0.6550: ccc_i12={iter12_block['ccc_iter12']:.4f}, "
              f"Δ̄={iter12_block['delta_mean']:+.4f}, frac>0={iter12_block['frac_above_zero']:.3f}", flush=True)
    print(f"  is_canonical_update = {is_canonical}", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "lockbox"], required=True)
    ap.add_argument("--variant", required=True,
                    choices=["V1_random", "V2_clinical", "V3_correlation", "V4_catboost"])
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()
    if args.mode == "write_prereg":
        write_preregistration(args.variant)
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox")
        run_lockbox(Path(args.preregistration_file), args.variant,
                    seeds=tuple(args.seeds), feature_set=args.feature_set)


if __name__ == "__main__":
    main()
