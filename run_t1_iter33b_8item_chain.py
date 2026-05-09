"""T1 iter33-B — 8-item auxiliary-task chain {9,10,11,12,13,14,15,18}.

Mechanism: F50 (iter17) lockbox wins on items 15 (postural tremor, +0.1099 LOOCV)
and 18 (rest tremor constancy, +0.4858 LOOCV) prove these two carry HARVESTABLE
within-PD severity signal that bypasses K=500 absorption when small features feed
through item-only or hy_residual_item_v2 architectures. F65 multi-task chain on
items 9-14 alone gave T1 LOOCV CCC=0.7087 by exploiting axial-item residual
correlations.

THIS PROBE: extend the chain to 8 items (add 15+18 as AUXILIARY targets only) so
the chain learns a richer shared latent severity representation. T1 sum still =
items 9-14 only (we discard predictions for 15+18). Auxiliary tasks regularize
chain links via shared input features without adding DOF to T1's prediction.

  --mode screen_5fold     →  5-fold screen across seeds, paired bootstrap vs iter5.
  --mode write_prereg     →  emit pre-reg with formula_sha256.
  --mode lockbox          →  load pre-reg, verify SHA, run LOOCV across seeds.
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
from run_t1_iter4 import T1_ITEMS, load_pd_data as load_t1_pd_data

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
PUBLISHED_T1_LOOCV_CCC = 0.6550
ITER30B_V1_LOOCV_CCC = 0.7087

T1_SUM_ITEMS: tuple[int, ...] = tuple(T1_ITEMS)  # items 9-14, T1 = sum of these
AUX_ITEMS: tuple[int, ...] = (15, 18)  # F50 lockbox wins (auxiliary chain targets)
ALL_ITEMS: tuple[int, ...] = T1_SUM_ITEMS + AUX_ITEMS  # 8-item chain target space


def _load_t1_cohort_with_8items():
    """Load T1 cohort plus items 15 and 18 if available; subjects must have all 8."""
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y_t1 = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    items_all: dict[int, np.ndarray] = {}
    for i in T1_SUM_ITEMS:
        items_all[i] = np.asarray(d["items"][i], dtype=np.float64)
    available_aux = []
    for i in AUX_ITEMS:
        if i in d["items"]:
            items_all[i] = np.asarray(d["items"][i], dtype=np.float64)
            available_aux.append(i)
        else:
            print(f"  WARN: item {i} not in load_t1_pd_data() output; chain will use {6 + len(available_aux)} targets",
                  flush=True)
    valid_t1 = ~np.isnan(y_t1)
    valid_aux = np.ones(len(sids), dtype=bool)
    for i in available_aux:
        valid_aux &= ~np.isnan(items_all[i])
    valid = valid_t1 & valid_aux
    print(f"  cohort: T1-only N={valid_t1.sum()} | with-aux N={valid.sum()} "
          f"(aux items used: {available_aux})", flush=True)
    items_valid = {i: items_all[i][valid] for i in items_all}
    return sids[valid], X[valid], y_t1[valid], hy[valid], items_valid, tuple(available_aux)


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def _multitask_predict_8item(Xtr, items_tr, Xte, seed):
    """RegressorChain with 8 columns (T1_SUM_ITEMS first, AUX_ITEMS last).
    The chain order is random for diversity; t1_sum is computed only over the
    T1_SUM_ITEMS columns of the prediction.
    """
    import lightgbm as lgb
    from sklearn.multioutput import RegressorChain

    regr = lgb.LGBMRegressor(
        n_estimators=500, learning_rate=0.05, num_leaves=15,
        min_data_in_leaf=10, random_state=seed, n_jobs=1, verbose=-1,
    )
    chain = RegressorChain(regr, order="random", random_state=seed)
    chain.fit(Xtr, items_tr)
    return chain.predict(Xte)


def _run_one_fold(X, y_t1, hy, items, item_order, X_s1, tr, te, seed):
    """Returns (s1_te, item_pred_te_sum_subset, n_t1_items)."""
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )
    ip = _multitask_predict_8item(Xtr_sel, items_tr_arr, Xte_sel, seed)
    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    return s1_te + (t1_pred_from_items - sum_means_t1)


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


def screen_5fold(seeds: tuple[int, ...], feature_set: str = "A3_tier1") -> Path:
    print(f"\n=== T1 iter33-B 8-item chain SCREEN: 5-fold × {len(seeds)} seeds ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  chain item_order = {item_order} (T1 sum over {list(T1_SUM_ITEMS)})", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    rows = []
    oofs_mt: list[np.ndarray] = []
    oofs_i5: list[np.ndarray] = []
    for seed in seeds:
        t0 = time.time()
        preds_mt = np.zeros(n)
        for tr, te in _kfold(n, seed):
            preds_mt[te] = _run_one_fold(X, y_t1, hy, items, item_order, X_s1, tr, te, seed)
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
    out = RESULTS_DIR / f"iter33b_8item_5fold_{ts}.json"
    payload = {
        "experiment": "T1 iter33-B 8-item auxiliary-task chain — 5-fold screen",
        "n_subjects": n, "item_order": item_order,
        "auxiliary_items_used": list(available_aux),
        "seeds": list(seeds), "per_seed": rows,
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
        "experiment": "T1 iter33-B — 8-item auxiliary-task multi-task LGB chain",
        "cohort": {"target": "T1 = sum(items 9-14)", "n_subjects_min": 90,
                   "filter": "PD with full items 9-14, 15, 18"},
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9, "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
            "target": "T1 (sum items 9-14)",
        },
        "stage2": {
            "model": "sklearn.multioutput.RegressorChain over LGBMRegressor",
            "variant": "V1_random_8item",
            "lgb_params": {
                "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 15,
                "min_data_in_leaf": 10, "n_jobs": 1, "verbose": -1,
            },
            "items_targets_chain": list(ALL_ITEMS),
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES,
            "imputation": "fold_local_median",
            "post_combine_formula": (
                "Stage1_pred + (sum(item_pred[T1_SUM_ITEMS] + train_mean[T1_SUM_ITEMS]) "
                "- sum(train_mean[T1_SUM_ITEMS]))  -- aux items 15,18 used in fit only"
            ),
        },
        "eval": {
            "loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT),
            "fold_construction_5fold": "KFold(shuffle=True, random_state=seed)",
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run.",
            "Headline = CCC of mean-of-3-seed preds on filter cohort.",
            "Pass-canonical: paired-bootstrap (n=5000) vs iter5-direct frac>0 ≥ 0.95 AND headline > 0.6550.",
            "Mechanism: auxiliary items 15+18 (F50 lockbox wins) regularize chain via shared latent severity.",
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
        "experiment": "T1 iter33-B 8-item auxiliary-task chain LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": "V1_random_8item",
        "eval_protocol": (
            "LOOCV on T1∩aux-items cohort. Stage-1 Ridge (alpha=1.0) on H&Y + "
            "cv_yrs + cv_sex + cv_dbs. Stage-2 RegressorChain(LGBMRegressor) "
            "random order over 8 items {9,10,11,12,13,14,15,18}. T1 = sum predictions "
            "for items 9-14 only; items 15+18 used as auxiliary chain targets. "
            "3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_iter33b_8item_{ts}.json"
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
    print(f"\n=== T1 iter33-B 8-item LOCKBOX LOOCV ({len(seeds)} seeds) ===", flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
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
            preds_mt[te] = _run_one_fold(X, y_t1, hy, items, item_order, X_s1, tr, te, seed)
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
    headline = full_metrics(y_t1, mean_mt, label="t1_iter33b_8item")
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
        "variant": "V1_random_8item", "n_subjects": n,
        "item_order_chain": item_order, "auxiliary_items_used": list(available_aux),
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
    out_json = RESULTS_DIR / f"lockbox_t1_iter33b_8item_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter33b_8item_{ts}.oof.npy"
    np.save(out_npy, mean_mt)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f} ===", flush=True)
    print(f"  Δ vs iter5-direct (mean of seeds): {headline['delta_vs_iter5_direct']:+.4f}",
          flush=True)
    print(f"  Bootstrap vs iter5: Δ̄={boot_i5['delta_mean']:+.4f}, "
          f"frac>0={boot_i5['frac_above_zero']:.3f}", flush=True)
    print(f"  is_canonical_update = {is_canonical}", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen_5fold", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()
    if args.mode == "screen_5fold":
        screen_5fold(tuple(args.seeds), args.feature_set)
    elif args.mode == "write_prereg":
        write_preregistration()
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox")
        run_lockbox(Path(args.preregistration_file),
                    seeds=tuple(args.seeds), feature_set=args.feature_set)


if __name__ == "__main__":
    main()
