"""Screen-only decomposition audit for T1 iter34.

The active T1 question is not whether the locked iter34 OOF can be edited. It
cannot. The question is whether the remaining P2 noisy-test-X caveat is caused
by one base learner / item channel, and whether a simpler pre-specified base
subset is worth a future pre-registered lockbox.

This script runs 5-fold screens only. It reports:
  * baseline CCC by base subset across seeds;
  * P2 noisy-test-X one-sided deltas vs Stage1-only, including bootstraps;
  * per-item chain prediction CCC for items 9-14 plus auxiliaries 15/18.

It does not change iter34's locked N=93 LOOCV artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("PD_IMU_N_CORES", "1")

from inductive_lib import ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import FEATURE_SETS, build_stage1_features, fit_stage1, load_clinical_dict
from run_t1_iter33b_8item_chain import AUX_ITEMS, T1_SUM_ITEMS, _load_t1_cohort_with_8items
from run_t1_iter34_hybrid_8item_multibase import BASE_LEARNERS, _multitask_predict
from run_t1_iter34_leakage_audit import _kfold


DEFAULT_SEEDS = [42, 1337, 7, 2026, 9001]
FEATURE_SET = "A3_tier1"
STAGE1_ALPHA = 1.0
K_FEATURES = 500
ONE_SIDED_MARGIN = 0.05
COMBOS: dict[str, tuple[str, ...]] = {
    "lgb": ("lgb",),
    "xgb": ("xgb",),
    "et": ("et",),
    "lgb_xgb": ("lgb", "xgb"),
    "lgb_et": ("lgb", "et"),
    "xgb_et": ("xgb", "et"),
    "all": tuple(BASE_LEARNERS),
}


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if len(a) < 3 or np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(y, dtype=np.float64) - np.asarray(p, dtype=np.float64))))


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "ccc": float(ccc_fn(y, p)),
        "mae": _mae(y, p),
        "r": _pearson(y, p),
        "pred_mean": float(np.mean(p)),
        "pred_std": float(np.std(p)),
    }


def _bootstrap_delta(
    y: np.ndarray,
    p_noisy: np.ndarray,
    p_stage1: np.ndarray,
    *,
    seed: int,
    n_boot: int,
) -> dict[str, float | int]:
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[b] = ccc_fn(y[idx], p_noisy[idx]) - ccc_fn(y[idx], p_stage1[idx])
    return {
        "n_boot": int(n_boot),
        "delta_mean": float(np.mean(deltas)),
        "ci_low": float(np.quantile(deltas, 0.025)),
        "ci_high": float(np.quantile(deltas, 0.975)),
        "frac_above_zero": float(np.mean(deltas > 0)),
        "frac_above_margin": float(np.mean(deltas > ONE_SIDED_MARGIN)),
    }


def _fold_worker(args: tuple[Any, ...]) -> dict[str, Any]:
    (
        fold_id,
        tr,
        te,
        X,
        y_t1,
        X_s1,
        items_arr,
        item_order,
        seed,
        noisy_test,
    ) = args

    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
    for pos, item in enumerate(item_order):
        values = items_arr[:, pos][tr]
        mu = float(np.nanmean(values))
        item_means[item] = mu
        items_tr_residual.append(np.nan_to_num(values - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    Xtr, Xte = impute_fold(X[tr], X[te])
    if noisy_test:
        rng = np.random.RandomState(seed + fold_id + 9999)
        for col in range(Xtr.shape[1]):
            Xte[:, col] = rng.choice(Xtr[:, col], size=Xte.shape[0], replace=True)

    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr,
        y_t1[tr] - s1_tr,
        Xte,
        k=K_FEATURES,
        seed=seed,
    )

    t1_sum_idx = [item_order.index(item) for item in T1_SUM_ITEMS]
    sum_means_t1 = float(sum(item_means[item] for item in T1_SUM_ITEMS))
    base_t1: dict[str, list[float]] = {}
    base_items: dict[str, list[list[float]]] = {}
    for base in BASE_LEARNERS:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=base)
        raw_item_pred = ip + np.array([item_means[item] for item in item_order])
        t1_from_items = raw_item_pred[:, t1_sum_idx].sum(axis=1)
        base_t1[base] = [float(x) for x in (s1_te + (t1_from_items - sum_means_t1))]
        base_items[base] = raw_item_pred.astype(float).tolist()

    return {
        "fold_id": int(fold_id),
        "te": [int(i) for i in te],
        "stage1": [float(x) for x in s1_te],
        "base_t1": base_t1,
        "base_items": base_items,
    }


def _run_pass(
    X: np.ndarray,
    y_t1: np.ndarray,
    hy: np.ndarray,
    items_arr: np.ndarray,
    item_order: list[int],
    sids: np.ndarray,
    *,
    seed: int,
    noisy_test: bool,
    n_workers: int,
) -> dict[str, Any]:
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, FEATURE_SETS[FEATURE_SET])
    splits = _kfold(len(sids), seed=seed)
    jobs = [
        (fold_id, tr, te, X, y_t1, X_s1, items_arr, item_order, seed, noisy_test)
        for fold_id, (tr, te) in enumerate(splits)
    ]

    stage1 = np.zeros(len(sids), dtype=np.float64)
    base_t1 = {base: np.zeros(len(sids), dtype=np.float64) for base in BASE_LEARNERS}
    base_items = {
        base: np.zeros((len(sids), len(item_order)), dtype=np.float64)
        for base in BASE_LEARNERS
    }

    done = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fold_worker, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            row = fut.result()
            te = np.asarray(row["te"], dtype=int)
            stage1[te] = np.asarray(row["stage1"], dtype=np.float64)
            for base in BASE_LEARNERS:
                base_t1[base][te] = np.asarray(row["base_t1"][base], dtype=np.float64)
                base_items[base][te, :] = np.asarray(row["base_items"][base], dtype=np.float64)
            done += 1
            print(
                f"    seed={seed} noisy={noisy_test} fold-pass {done}/{len(jobs)}",
                flush=True,
            )

    return {
        "stage1": stage1,
        "base_t1": base_t1,
        "base_items": base_items,
    }


def _combo_t1(base_t1: dict[str, np.ndarray], combo: tuple[str, ...]) -> np.ndarray:
    return np.mean(np.column_stack([base_t1[base] for base in combo]), axis=1)


def _combo_items(base_items: dict[str, np.ndarray], combo: tuple[str, ...]) -> np.ndarray:
    return np.mean(np.stack([base_items[base] for base in combo], axis=0), axis=0)


def _seed_audit(
    seed: int,
    X: np.ndarray,
    y_t1: np.ndarray,
    hy: np.ndarray,
    items_arr: np.ndarray,
    item_order: list[int],
    sids: np.ndarray,
    *,
    n_workers: int,
    n_boot: int,
) -> dict[str, Any]:
    t0 = time.time()
    print(f"\n[iter34-decomp] seed={seed} baseline pass", flush=True)
    baseline = _run_pass(
        X, y_t1, hy, items_arr, item_order, sids,
        seed=seed, noisy_test=False, n_workers=n_workers,
    )
    print(f"[iter34-decomp] seed={seed} P2 noisy-test pass", flush=True)
    noisy = _run_pass(
        X, y_t1, hy, items_arr, item_order, sids,
        seed=seed, noisy_test=True, n_workers=n_workers,
    )

    stage1 = baseline["stage1"]
    if not np.allclose(stage1, noisy["stage1"]):
        raise RuntimeError(f"stage1 mismatch between baseline and P2 for seed={seed}")
    residual = y_t1 - stage1
    stage1_metrics = _metrics(y_t1, stage1)

    combos: dict[str, Any] = {}
    all_pred = _combo_t1(baseline["base_t1"], COMBOS["all"])
    all_ccc = float(ccc_fn(y_t1, all_pred))
    for combo_name, combo in COMBOS.items():
        pred = _combo_t1(baseline["base_t1"], combo)
        p2_pred = _combo_t1(noisy["base_t1"], combo)
        base_metrics = _metrics(y_t1, pred)
        p2_metrics = _metrics(y_t1, p2_pred)
        p2_delta = p2_metrics["ccc"] - stage1_metrics["ccc"]
        item_pred = _combo_items(baseline["base_items"], combo)
        item_metrics = {}
        for pos, item in enumerate(item_order):
            item_metrics[str(item)] = _metrics(items_arr[:, pos], item_pred[:, pos])
        boot = _bootstrap_delta(
            y_t1,
            p2_pred,
            stage1,
            seed=seed + 34000 + len(combo_name),
            n_boot=n_boot,
        )
        combos[combo_name] = {
            "bases": list(combo),
            "baseline_metrics": base_metrics,
            "delta_vs_all_baseline_ccc": float(base_metrics["ccc"] - all_ccc),
            "p2_noisy_metrics": p2_metrics,
            "p2_delta_vs_stage1_ccc": float(p2_delta),
            "p2_point_one_sided_pass": bool(p2_delta <= ONE_SIDED_MARGIN),
            "p2_bootstrap_delta": boot,
            "p2_bootstrap_one_sided_pass": bool(boot["ci_high"] <= ONE_SIDED_MARGIN),
            "baseline_stage2_residual_corr": _pearson(pred - stage1, residual),
            "p2_stage2_residual_corr": _pearson(p2_pred - stage1, residual),
            "item_metrics": item_metrics,
        }

    return {
        "seed": int(seed),
        "stage1_metrics": stage1_metrics,
        "combo_rows": combos,
        "wall_time_s": float(time.time() - t0),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    combo_summary: dict[str, Any] = {}
    all_cccs = np.asarray(
        [row["combo_rows"]["all"]["baseline_metrics"]["ccc"] for row in rows],
        dtype=np.float64,
    )
    for combo_name in COMBOS:
        cccs = np.asarray(
            [row["combo_rows"][combo_name]["baseline_metrics"]["ccc"] for row in rows],
            dtype=np.float64,
        )
        deltas_vs_all = np.asarray(
            [row["combo_rows"][combo_name]["delta_vs_all_baseline_ccc"] for row in rows],
            dtype=np.float64,
        )
        p2_deltas = np.asarray(
            [row["combo_rows"][combo_name]["p2_delta_vs_stage1_ccc"] for row in rows],
            dtype=np.float64,
        )
        p2_boot_hi = np.asarray(
            [row["combo_rows"][combo_name]["p2_bootstrap_delta"]["ci_high"] for row in rows],
            dtype=np.float64,
        )
        combo_summary[combo_name] = {
            "bases": list(COMBOS[combo_name]),
            "baseline_ccc_mean": float(np.mean(cccs)),
            "baseline_ccc_std": float(np.std(cccs)),
            "delta_vs_all_mean": float(np.mean(deltas_vs_all)),
            "delta_vs_all_min": float(np.min(deltas_vs_all)),
            "p2_delta_mean": float(np.mean(p2_deltas)),
            "p2_delta_max": float(np.max(p2_deltas)),
            "p2_bootstrap_ci_high_max": float(np.max(p2_boot_hi)),
            "p2_point_one_sided_all_pass": bool(np.max(p2_deltas) <= ONE_SIDED_MARGIN),
            "p2_bootstrap_one_sided_all_pass": bool(np.max(p2_boot_hi) <= ONE_SIDED_MARGIN),
            "ceiling_promotion_screen_pass": bool(
                np.mean(deltas_vs_all) >= 0.025
                and np.std(cccs) < 0.020
                and np.max(p2_deltas) <= ONE_SIDED_MARGIN
                and np.max(p2_boot_hi) <= ONE_SIDED_MARGIN
            ),
            "robustification_screen_pass": bool(
                np.mean(deltas_vs_all) >= -0.010
                and np.mean(cccs) >= 0.700
                and np.max(p2_deltas) <= ONE_SIDED_MARGIN
                and np.max(p2_boot_hi) <= ONE_SIDED_MARGIN
            ),
        }

    best_by_ccc = max(combo_summary, key=lambda key: combo_summary[key]["baseline_ccc_mean"])
    robust_candidates = [
        key for key, val in combo_summary.items()
        if val["robustification_screen_pass"]
    ]
    ceiling_candidates = [
        key for key, val in combo_summary.items()
        if val["ceiling_promotion_screen_pass"]
    ]
    return {
        "all_base_baseline_ccc_mean": float(np.mean(all_cccs)),
        "all_base_baseline_ccc_std": float(np.std(all_cccs)),
        "best_combo_by_mean_ccc": best_by_ccc,
        "ceiling_promotion_candidates": ceiling_candidates,
        "robustification_candidates": robust_candidates,
        "combo_summary": combo_summary,
        "decision": (
            "future_preregister_if_candidate_exists"
            if ceiling_candidates or robust_candidates
            else "diagnostic_only_no_future_lockbox"
        ),
    }


def run_audit(seeds: list[int], n_workers: int, n_boot: int) -> dict[str, Any]:
    sids, X, y_t1, hy, items_dict, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    expected = list(T1_SUM_ITEMS) + list(AUX_ITEMS)
    if item_order != expected:
        raise RuntimeError(f"unexpected item_order={item_order}, expected={expected}")
    items_arr = np.column_stack([items_dict[item] for item in item_order])

    rows = []
    for seed in seeds:
        rows.append(
            _seed_audit(
                seed,
                X,
                y_t1,
                hy,
                items_arr,
                item_order,
                sids,
                n_workers=n_workers,
                n_boot=n_boot,
            )
        )

    summary = _summarize(rows)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "audit": "t1_iter34_base_item_p2_decomposition",
        "n": int(len(sids)),
        "seeds": [int(seed) for seed in seeds],
        "n_workers": int(n_workers),
        "n_boot_per_seed_combo": int(n_boot),
        "item_order": [int(item) for item in item_order],
        "combos": {name: list(combo) for name, combo in COMBOS.items()},
        "one_sided_margin": ONE_SIDED_MARGIN,
        "promotion_rules": {
            "ceiling_promotion_screen_pass": (
                "mean delta vs all-base iter34 5-fold >= +0.025, seed std < 0.020, "
                "and P2 point/bootstrap one-sided pass"
            ),
            "robustification_screen_pass": (
                "mean delta vs all-base iter34 5-fold >= -0.010, mean CCC >= 0.700, "
                "and P2 point/bootstrap one-sided pass"
            ),
            "scope": "screen only; any passing candidate still needs fresh pre-registration before LOOCV",
        },
        "summary": summary,
        "seed_rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="*", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--n_workers", type=int, default=11)
    parser.add_argument("--n_boot", type=int, default=1000)
    parser.add_argument(
        "--out",
        default="iter34_base_item_decomp_20260508.json",
        help="Output JSON filename under results/.",
    )
    args = parser.parse_args()

    payload = run_audit(args.seeds, args.n_workers, args.n_boot)
    out_path = RESULTS_DIR / args.out
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("\n=== iter34 base/item/P2 decomposition summary ===", flush=True)
    print(json.dumps(payload["summary"], indent=2), flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
