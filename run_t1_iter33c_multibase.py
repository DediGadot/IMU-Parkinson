"""T1 iter33-C — Diverse-base-learner chain ensemble {LGB, XGB-hist, ExtraTrees}.

Mechanism: F66 NULL was within-LGB chain-order averaging — V1+V2+V3 chain orders
on the same LGB backend produce highly correlated OOFs (paired bootstrap V1 vs
ensemble: frac>0=0.318), so averaging didn't reduce variance.

Different BASE LEARNERS produce DECORRELATED OOFs by construction (LGB gradient
boosting / XGB histogram boosting / ExtraTrees random splits). Same V1_random
chain architecture, three independent fits per fold, average the 3 OOFs. Should
deliver real variance reduction unlike F66.

  --mode screen_5fold     →  5-fold screen across 3 base learners × seeds.
  --mode write_prereg     →  emit pre-reg with formula_sha256.
  --mode lockbox          →  load pre-reg, verify SHA, run LOOCV.
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
from run_t1_iter30b_multitask_variants import _load_t1_cohort_with_items

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
PUBLISHED_T1_LOOCV_CCC = 0.6550
ITER30B_V1_LOOCV_CCC = 0.7087

BASE_LEARNERS = ("lgb", "xgb", "et")


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


def _multitask_predict(Xtr, items_tr, Xte, seed, base: str):
    from sklearn.multioutput import RegressorChain
    regr = _make_regr(base, seed)
    chain = RegressorChain(regr, order="random", random_state=seed)
    chain.fit(Xtr, items_tr)
    return chain.predict(Xte)


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def _run_one_fold(X, y_t1, hy, items, X_s1, tr, te, seed, bases: tuple[str, ...]):
    """Fit each base, average chain-output OOFs across bases. Returns t1_pred for te."""
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
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

    ip_avg = None
    for b in bases:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)

    item_pred_te = ip_avg + np.array([item_means[i] for i in T1_ITEMS])
    t1_pred_from_items = item_pred_te.sum(axis=1)
    sum_means = float(sum(item_means.values()))
    return s1_te + (t1_pred_from_items - sum_means)


def _iter5_direct_5fold(X, y_t1, X_s1, n, seed):
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
    return preds


def _iter5_direct_loocv(X, y_t1, X_s1, n, seed):
    preds = np.zeros(n)
    for tr, te in LeaveOneOut().split(np.arange(n)):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
    return preds


def screen_5fold(seeds: tuple[int, ...], bases: tuple[str, ...] = BASE_LEARNERS,
                 feature_set: str = "A3_tier1") -> Path:
    print(f"\n=== T1 iter33-C multi-base SCREEN: bases={bases}, "
          f"5-fold × {len(seeds)} seeds ===", flush=True)
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    rows = []
    oofs_mt: list[np.ndarray] = []
    oofs_i5: list[np.ndarray] = []
    for seed in seeds:
        t0 = time.time()
        preds_mt = np.zeros(n)
        for tr, te in _kfold(n, seed):
            preds_mt[te] = _run_one_fold(X, y_t1, hy, items, X_s1, tr, te, seed, bases)
        preds_i5 = _iter5_direct_5fold(X, y_t1, X_s1, n, seed)
        c_mt = float(ccc_fn(y_t1, preds_mt))
        c_i5 = float(ccc_fn(y_t1, preds_i5))
        rows.append({"seed": seed, "ccc_mt": round(c_mt, 4),
                     "ccc_i5": round(c_i5, 4), "delta": round(c_mt - c_i5, 4),
                     "wall_time_s": round(time.time() - t0, 1)})
        oofs_mt.append(preds_mt)
        oofs_i5.append(preds_i5)
        print(f"  seed={seed}: mt={c_mt:.4f} | i5={c_i5:.4f} | "
              f"Δ={c_mt-c_i5:+.4f} | {time.time()-t0:.1f}s", flush=True)

    mean_mt = np.mean(np.column_stack(oofs_mt), axis=1)
    mean_i5 = np.mean(np.column_stack(oofs_i5), axis=1)
    ccc_mt_mean = float(ccc_fn(y_t1, mean_mt))
    ccc_i5_mean = float(ccc_fn(y_t1, mean_i5))
    delta_seed = np.array([r["delta"] for r in rows])
    rng = np.random.RandomState(42)
    deltas = np.empty(5000)
    for i in range(5000):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y_t1[idx], mean_mt[idx]) - ccc_fn(y_t1[idx], mean_i5[idx])
    boot = {
        "delta_mean": float(deltas.mean()),
        "ci_low": float(np.percentile(deltas, 2.5)),
        "ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float((deltas > 0).mean()),
        "frac_above_0.025": float((deltas > 0.025).mean()),
    }
    gate_pass = bool(delta_seed.mean() >= 0.025 and boot["frac_above_zero"] >= 0.95)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter33c_multibase_5fold_{ts}.json"
    payload = {
        "experiment": "T1 iter33-C diverse-base-learner chain ensemble — 5-fold screen",
        "n_subjects": n, "bases": list(bases), "seeds": list(seeds),
        "per_seed": rows,
        "ccc_mt_meanof_seeds": round(ccc_mt_mean, 4),
        "ccc_i5_meanof_seeds": round(ccc_i5_mean, 4),
        "delta_meanof_seeds": round(ccc_mt_mean - ccc_i5_mean, 4),
        "delta_seed_mean": float(delta_seed.mean()),
        "delta_seed_std": float(delta_seed.std()),
        "paired_bootstrap_vs_iter5": boot,
        "gate_pass": gate_pass,
        "gate_threshold": "Δ̄_seed ≥ +0.025 AND paired_bootstrap_frac>0 ≥ 0.95",
    }
    with open(out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  Δ̄_seed = {delta_seed.mean():+.4f} ± {delta_seed.std():.4f}", flush=True)
    print(f"  bootstrap Δ̄ = {boot['delta_mean']:+.4f}, frac>0 = {boot['frac_above_zero']:.3f}",
          flush=True)
    print(f"  GATE_PASS = {gate_pass}", flush=True)
    print(f"Wrote {out}", flush=True)
    return out


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 iter33-C — diverse-base-learner chain ensemble {LGB, XGB-hist, ExtraTrees}",
        "cohort": {"target": "T1 = sum(items 9-14)", "n_subjects": 94,
                   "filter": "PD with full items 9-14"},
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA, "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9, "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
            "target": "T1 (sum items 9-14)",
        },
        "stage2": {
            "model_ensemble": [
                "RegressorChain(LGBMRegressor random_state=seed, 500 trees, lr=0.05)",
                "RegressorChain(XGBRegressor hist, 500 trees, lr=0.05, depth=4, min_child_weight=5)",
                "RegressorChain(ExtraTreesRegressor 300 trees, max_depth=10, min_samples_leaf=5)",
            ],
            "ensemble_method": "average chain-output across bases per fold per seed",
            "items_targets": list(T1_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES,
            "imputation": "fold_local_median",
            "post_combine_formula": "Stage1_pred + (sum(item_pred + train_mean) - sum(train_mean))",
            "decorrelation_argument": (
                "F66 NULL: within-LGB chain-order avg has frac>0=0.318 (highly correlated). "
                "Different base learners (gradient boosting / hist boosting / random splits) "
                "produce decorrelated trees by construction → real variance reduction."
            ),
        },
        "eval": {
            "loocv_n": 94, "seeds": list(SEEDS_DEFAULT),
            "bases": list(BASE_LEARNERS),
            "fold_construction_5fold": "KFold(shuffle=True, random_state=seed)",
            "headline_metric": "CCC of mean-of-seed predictions vs y_t1",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run.",
            "Headline = CCC of mean-of-3-seed preds (each seed averages 3 base learners).",
            "Pass-canonical: paired-bootstrap (n=5000) vs iter5-direct frac>0 ≥ 0.95 AND headline > 0.6550.",
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
        "experiment": "T1 iter33-C diverse-base-learner chain ensemble LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "n_subjects": 94, "variant": "V1_random_multibase",
        "eval_protocol": (
            "LOOCV (n=94) on T1 cohort. Stage-1 Ridge on H&Y + cv_yrs + cv_sex + cv_dbs. "
            "Stage-2 RegressorChain V1_random with 3 base learners {LGB, XGB-hist, "
            "ExtraTrees}; chain-output OOFs averaged per fold. 3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_iter33c_multibase_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def run_lockbox(preregistration_file: Path,
                seeds: tuple[int, ...] = SEEDS_DEFAULT,
                feature_set: str = "A3_tier1") -> Path:
    if not preregistration_file.exists():
        raise FileNotFoundError(f"missing preregistration: {preregistration_file}")
    with open(preregistration_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )
    print(f"\n=== T1 iter33-C multi-base LOCKBOX LOOCV ({len(seeds)} seeds, N=94) ===", flush=True)

    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    all_mt: list[np.ndarray] = []
    all_i5: list[np.ndarray] = []
    per_seed = []
    for seed in seeds:
        t0 = time.time()
        preds_mt = np.zeros(n)
        for fold_id, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
            preds_mt[te] = _run_one_fold(X, y_t1, hy, items, X_s1, tr, te, seed, BASE_LEARNERS)
            if (fold_id + 1) % 20 == 0:
                print(f"    seed={seed} fold {fold_id+1}/{n}  elapsed={time.time()-t0:.0f}s",
                      flush=True)
        preds_i5 = _iter5_direct_loocv(X, y_t1, X_s1, n, seed)
        c_mt = float(ccc_fn(y_t1, preds_mt))
        c_i5 = float(ccc_fn(y_t1, preds_i5))
        per_seed.append({"seed": seed, "ccc_mt": c_mt, "ccc_i5": c_i5,
                         "delta": c_mt - c_i5, "wall": time.time() - t0})
        print(f"  seed={seed}: mt={c_mt:.4f} | i5={c_i5:.4f} | "
              f"Δ={c_mt-c_i5:+.4f} | {time.time()-t0:.0f}s", flush=True)
        all_mt.append(preds_mt); all_i5.append(preds_i5)

    mean_mt = np.mean(np.column_stack(all_mt), axis=1)
    mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
    headline = full_metrics(y_t1, mean_mt, label="t1_iter33c_multibase")
    headline_i5 = full_metrics(y_t1, mean_i5, label="iter5_direct_t1_loocv_baseline")

    rng = np.random.RandomState(42)
    deltas_i5 = np.empty(5000)
    for i in range(5000):
        idx = rng.randint(0, n, n)
        deltas_i5[i] = ccc_fn(y_t1[idx], mean_mt[idx]) - ccc_fn(y_t1[idx], mean_i5[idx])
    boot_i5 = {
        "n_boot": 5000, "delta_mean": float(deltas_i5.mean()),
        "delta_ci_low": float(np.percentile(deltas_i5, 2.5)),
        "delta_ci_high": float(np.percentile(deltas_i5, 97.5)),
        "frac_above_zero": float((deltas_i5 > 0).mean()),
        "frac_above_0.025": float((deltas_i5 > 0.025).mean()),
    }
    is_canonical = bool(boot_i5["frac_above_zero"] >= 0.95
                        and headline["ccc"] > PUBLISHED_T1_LOOCV_CCC)

    headline.update({
        "variant": "V1_random_multibase", "bases": list(BASE_LEARNERS),
        "preregistration_file": preregistration_file.name,
        "is_lockbox_headline": True, "n_seeds": len(seeds), "per_seed": per_seed,
        "ccc_iter5_direct_loocv_baseline": round(headline_i5["ccc"], 4),
        "delta_vs_iter5_direct": round(headline["ccc"] - headline_i5["ccc"], 4),
        "bootstrap_delta_vs_iter5": boot_i5,
        "is_canonical_update": is_canonical,
        "per_subject": {"sids": [str(s) for s in sids],
                        "y_true": y_t1.tolist(), "y_pred": mean_mt.tolist()},
    })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter33c_multibase_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter33c_multibase_{ts}.oof.npy"
    np.save(out_npy, mean_mt)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f} ===", flush=True)
    print(f"  Δ vs iter5-direct: {headline['delta_vs_iter5_direct']:+.4f}", flush=True)
    print(f"  Bootstrap vs iter5: Δ̄={boot_i5['delta_mean']:+.4f}, "
          f"frac>0={boot_i5['frac_above_zero']:.3f}", flush=True)
    print(f"  is_canonical_update = {is_canonical}", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen_5fold", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--bases", nargs="+", default=list(BASE_LEARNERS))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()
    if args.mode == "screen_5fold":
        screen_5fold(tuple(args.seeds), tuple(args.bases), args.feature_set)
    elif args.mode == "write_prereg":
        write_preregistration()
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox")
        run_lockbox(Path(args.preregistration_file),
                    seeds=tuple(args.seeds), feature_set=args.feature_set)


if __name__ == "__main__":
    main()
