"""Focused robustness audit for iter34's noisy-test-X P2 leakage probe.

The original iter34 leakage audit used an absolute criterion:
abs(CCC_noisy_test_X - CCC_stage1_only) <= 0.05. It soft-failed because noisy
test features made the hybrid worse than Stage 1, not better. For a leakage
canary the risk is one-sided: invalid test X should not improve over Stage 1.

This script repeats P2 across multiple 5-fold seeds and reports a one-sided
criterion, bootstrap upper bounds, and per-fold diagnostics. It does not train a
new candidate model or change iter34's locked OOF predictions.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("PD_IMU_N_CORES", "1")

from inductive_lib import ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_t1_iter33b_8item_chain import (
    AUX_ITEMS,
    T1_SUM_ITEMS,
    _load_t1_cohort_with_8items,
)
from run_t1_iter34_leakage_audit import _kfold, run_5fold


DEFAULT_SEEDS = [42, 1337, 7, 2026, 9001]
ONE_SIDED_MARGIN = 0.05


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if len(a) < 3 or np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _bootstrap_delta(
    y: np.ndarray,
    p_noisy: np.ndarray,
    p_stage1: np.ndarray,
    *,
    seed: int,
    n_boot: int,
) -> dict[str, Any]:
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
    y_base, p_base = run_5fold(
        X, y_t1, hy, items_arr, item_order, sids, seed=seed, n_workers=n_workers
    )
    y_s1, p_s1 = run_5fold(
        X,
        y_t1,
        hy,
        items_arr,
        item_order,
        sids,
        stage1_only=True,
        seed=seed,
        n_workers=n_workers,
    )
    y_p2, p_p2 = run_5fold(
        X,
        y_t1,
        hy,
        items_arr,
        item_order,
        sids,
        noisy_test=True,
        seed=seed,
        n_workers=n_workers,
    )

    if not np.allclose(y_base, y_s1) or not np.allclose(y_base, y_p2):
        raise RuntimeError(f"y vectors differ for seed={seed}")

    ccc_base = float(ccc_fn(y_base, p_base))
    ccc_s1 = float(ccc_fn(y_s1, p_s1))
    ccc_p2 = float(ccc_fn(y_p2, p_p2))
    delta = ccc_p2 - ccc_s1

    residual = y_base - p_s1
    base_stage2 = p_base - p_s1
    p2_stage2 = p_p2 - p_s1

    per_fold = []
    for fold_id, (_, te) in enumerate(_kfold(len(y_base), seed=seed)):
        fold_s1 = float(ccc_fn(y_base[te], p_s1[te]))
        fold_p2 = float(ccc_fn(y_base[te], p_p2[te]))
        per_fold.append(
            {
                "fold": int(fold_id),
                "n": int(len(te)),
                "stage1_ccc": fold_s1,
                "p2_ccc": fold_p2,
                "delta_p2_minus_stage1": fold_p2 - fold_s1,
            }
        )

    boot = _bootstrap_delta(y_base, p_p2, p_s1, seed=seed + 20260508, n_boot=n_boot)
    return {
        "seed": int(seed),
        "baseline_ccc": ccc_base,
        "stage1_ccc": ccc_s1,
        "p2_noisy_test_ccc": ccc_p2,
        "delta_p2_minus_stage1": delta,
        "one_sided_pass": bool(delta <= ONE_SIDED_MARGIN),
        "bootstrap_delta": boot,
        "bootstrap_one_sided_pass": bool(boot["ci_high"] <= ONE_SIDED_MARGIN),
        "baseline_stage2_residual_corr": _pearson(base_stage2, residual),
        "p2_stage2_residual_corr": _pearson(p2_stage2, residual),
        "per_fold": per_fold,
        "max_per_fold_delta": float(max(f["delta_p2_minus_stage1"] for f in per_fold)),
        "wall_time_s": float(time.time() - t0),
    }


def run_audit(seeds: list[int], n_workers: int, n_boot: int) -> dict[str, Any]:
    sids, X, y_t1, hy, items_dict, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    expected_order = list(T1_SUM_ITEMS) + list(AUX_ITEMS)
    if item_order != expected_order:
        raise RuntimeError(f"unexpected item_order={item_order}, expected={expected_order}")
    items_arr = np.column_stack([items_dict[i] for i in item_order])

    rows = []
    for seed in seeds:
        print(f"\n[P2] seed={seed} ...", flush=True)
        row = _seed_audit(
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
        rows.append(row)
        print(
            "  baseline={baseline_ccc:+.4f} stage1={stage1_ccc:+.4f} "
            "p2={p2_noisy_test_ccc:+.4f} delta={delta_p2_minus_stage1:+.4f} "
            "boot_hi={boot_hi:+.4f}".format(
                **row, boot_hi=row["bootstrap_delta"]["ci_high"]
            ),
            flush=True,
        )

    deltas = np.asarray([r["delta_p2_minus_stage1"] for r in rows], dtype=np.float64)
    boot_hi = np.asarray([r["bootstrap_delta"]["ci_high"] for r in rows], dtype=np.float64)
    p2_corrs = np.asarray([r["p2_stage2_residual_corr"] for r in rows], dtype=np.float64)
    baseline_corrs = np.asarray(
        [r["baseline_stage2_residual_corr"] for r in rows], dtype=np.float64
    )
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "audit": "t1_iter34_p2_robustness",
        "n": int(len(sids)),
        "seeds": [int(s) for s in seeds],
        "one_sided_margin": ONE_SIDED_MARGIN,
        "n_boot_per_seed": int(n_boot),
        "n_workers": int(n_workers),
        "interpretation": (
            "P2 is a one-sided leakage canary. Noisy test X is suspicious only "
            "if it improves over Stage1-only by more than the margin; performing "
            "worse than Stage1 indicates out-of-distribution fragility, not leakage."
        ),
        "rows": rows,
        "summary": {
            "delta_mean": float(np.mean(deltas)),
            "delta_min": float(np.min(deltas)),
            "delta_max": float(np.max(deltas)),
            "bootstrap_ci_high_max": float(np.max(boot_hi)),
            "all_point_deltas_pass_one_sided": bool(np.max(deltas) <= ONE_SIDED_MARGIN),
            "all_bootstrap_upper_bounds_pass_one_sided": bool(
                np.max(boot_hi) <= ONE_SIDED_MARGIN
            ),
            "baseline_stage2_residual_corr_mean": float(np.mean(baseline_corrs)),
            "p2_stage2_residual_corr_mean": float(np.mean(p2_corrs)),
        },
        "verdict": {
            "p2_leakage_signal": bool(np.max(deltas) > ONE_SIDED_MARGIN),
            "p2_robust_one_sided_pass": bool(
                np.max(deltas) <= ONE_SIDED_MARGIN
                and np.max(boot_hi) <= ONE_SIDED_MARGIN
            ),
            "absolute_threshold_reinterpreted": (
                "The prior absolute-threshold soft-fail was caused by negative "
                "delta, not positive above-Stage1 performance."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="*", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--n_workers", type=int, default=11)
    parser.add_argument("--n_boot", type=int, default=2000)
    parser.add_argument(
        "--out",
        default="iter34_p2_robustness_20260508.json",
        help="Output JSON filename under results/.",
    )
    args = parser.parse_args()

    payload = run_audit(args.seeds, args.n_workers, args.n_boot)
    out_path = RESULTS_DIR / args.out
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print("\n=== P2 ROBUSTNESS VERDICT ===", flush=True)
    print(json.dumps(payload["summary"], indent=2), flush=True)
    print(json.dumps(payload["verdict"], indent=2), flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
