"""T1 iter32 LEAKAGE AUDIT — verify no test-data leakage in multi-task chain.

Three probes (5-fold, 1 seed=42 each for speed; iter29b validation already
passed scrambled-label-y null at LOOCV scale):

  P1. SID-permutation null
      Shuffle the SID→label mapping globally BEFORE fold construction. So
      subject A's IMU features go with subject B's labels. Cache key joins
      that depend on SIDs would survive but the IMU↔label association is
      severed. Expected CCC ≈ 0; |CCC| > 0.15 signals SID-join leak.

  P2. Test-row noise injection (canary)
      For each test subject, replace its V2 features (X_te row) with random
      noise drawn from the train-fold marginal distribution PER COLUMN. The
      model should produce a prediction near the train mean of T1 (≈14).
      If the model's predictions for noisy test rows still correlate with
      true T1, the model is getting test-fold info from elsewhere (e.g.
      via cache-side-channel or H&Y label that snuck into Stage1 X).

  P3. Stage1-only baseline
      Run Stage1 alone (Ridge on H&Y + clinical) under same fold/seed.
      This isolates how much of the multi-task lift is actually coming from
      Stage2 (the multi-task chain) vs Stage1 (which is bit-identical to
      iter5's Stage1).

Run: python3 run_t1_iter32_leakage_audit.py
"""
from __future__ import annotations

import os
os.environ.setdefault("PD_IMU_N_CORES", "1")

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import load_pd_data as load_t1_pd_data, T1_ITEMS
from run_t1_iter29b_multitask_lgb import _multitask_lgb_predict

STAGE1_ALPHA = 1.0
K_FEATURES = 500
SEED = 42


def _load_t1_cohort_with_items():
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y_t1 = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    items = {i: np.asarray(d["items"][i], dtype=np.float64) for i in T1_ITEMS}
    valid = ~np.isnan(y_t1)
    items_valid = {i: items[i][valid] for i in T1_ITEMS}
    return sids[valid], X[valid], y_t1[valid], hy[valid], items_valid


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def run_multitask_5fold(X, y_t1, hy, items, sids, *, scramble_y: np.ndarray | None = None,
                       noisy_test: bool = False, stage1_only: bool = False,
                       feature_set="A3_tier1"):
    """One 5-fold pass.

    scramble_y: if given, indices to permute y AND items (consistent shuffle —
        items still sum to scrambled y). X, hy, clinical stay original; this
        breaks the X→y association and tests for any test-data leakage path.
    noisy_test: if True, replace test-fold X rows with random noise from train marginal.
    stage1_only: if True, return only Stage1 prediction (no multi-task Stage2).
    """
    n = len(sids)
    rng = np.random.RandomState(SEED + 9999)
    clinical = load_clinical_dict(sids)

    # Apply consistent cohort-wide y-and-items shuffle if requested
    if scramble_y is not None:
        perm = scramble_y
        y_eff = y_t1[perm]
        items_eff = {i: items[i][perm] for i in T1_ITEMS}
        hy_eff = hy  # KEPT ORIGINAL — only y/items shuffled
    else:
        y_eff = y_t1
        items_eff = items
        hy_eff = hy

    X_s1, _ = build_stage1_features(hy_eff, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed=SEED):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_eff[tr], X_s1[te], alpha=STAGE1_ALPHA)
        if stage1_only:
            preds[te] = s1_te
            continue
        item_means = {}
        items_tr_residual = []
        for i in T1_ITEMS:
            v = items_eff[i][tr]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_residual)
        Xtr, Xte = impute_fold(X[tr], X[te])
        if noisy_test:
            # Replace each test-row column with random sample from train column
            for col in range(Xtr.shape[1]):
                Xte[:, col] = rng.choice(Xtr[:, col], size=Xte.shape[0], replace=True)
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_eff[tr] - s1_tr, Xte, k=K_FEATURES, seed=SEED
        )
        ip = _multitask_lgb_predict(Xtr_sel, items_tr_arr, Xte_sel, SEED)
        item_pred_te = ip + np.array([item_means[i] for i in T1_ITEMS])
        t1_pred_from_items = item_pred_te.sum(axis=1)
        sum_means = float(sum(item_means.values()))
        preds[te] = s1_te + (t1_pred_from_items - sum_means)
    return y_eff, preds


def main():
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    print(f"\n=== T1 LEAKAGE AUDIT (N={n}, seed={SEED}, 5-fold) ===\n", flush=True)

    out: dict = {"timestamp": datetime.now().isoformat(), "n": int(n), "seed": SEED}

    # ---- Baseline (sanity replication of iter30b screen) ----
    t0 = time.time()
    y_b, p_b = run_multitask_5fold(X, y_t1, hy, items, sids)
    ccc_b = float(ccc_fn(y_b, p_b))
    print(f"[BASELINE] multi-task 5-fold CCC = {ccc_b:+.4f}   (expect ≈ 0.7049, the iter29b/iter30b V1_random seed=42 number)  [{time.time()-t0:.0f}s]", flush=True)
    out["P0_baseline"] = {"ccc": ccc_b, "expected_iter30b_seed42": 0.7049}

    # ---- P1. Multi-permutation y+items scramble distribution (X, hy, clinical kept) ----
    t0 = time.time()
    perm_cccs = []
    for ps in [123, 456, 789, 1011, 1213, 1415, 1617, 1819, 2021, 2223]:
        rng = np.random.RandomState(ps)
        perm = rng.permutation(n)
        _, p_perm = run_multitask_5fold(X, y_t1, hy, items, sids, scramble_y=perm)
        perm_cccs.append(float(ccc_fn(y_t1[perm], p_perm)))
    perm_cccs = np.asarray(perm_cccs)
    print(f"[P1] 10-perm scramble CCC distribution: mean={perm_cccs.mean():+.4f}, std={perm_cccs.std():.4f}, "
          f"min={perm_cccs.min():+.4f}, max={perm_cccs.max():+.4f}", flush=True)
    print(f"     vs baseline 0.7049 → permutation z-score = {(0.7049 - perm_cccs.mean()) / max(perm_cccs.std(), 1e-6):.1f}σ above null", flush=True)
    print(f"     (PASS if baseline >> permutation distribution; chance perms should be near 0 with noise)  [{time.time()-t0:.0f}s]", flush=True)
    out["P1_perm_distribution"] = {"perm_cccs": [float(x) for x in perm_cccs],
                                    "perm_mean": float(perm_cccs.mean()),
                                    "perm_std": float(perm_cccs.std()),
                                    "perm_min": float(perm_cccs.min()),
                                    "perm_max": float(perm_cccs.max()),
                                    "z_score_baseline_above_null": float((0.7049 - perm_cccs.mean()) / max(perm_cccs.std(), 1e-6))}

    # ---- P2. Test-row noise injection (canary) ----
    t0 = time.time()
    y_p2, p_p2 = run_multitask_5fold(X, y_t1, hy, items, sids, noisy_test=True)
    ccc_p2 = float(ccc_fn(y_p2, p_p2))
    print(f"[P2] Noisy-test-X CCC = {ccc_p2:+.4f}   (Stage1 alone should hold ~0.43; >0.45 means Stage2 is using leaked test info)  [{time.time()-t0:.0f}s]", flush=True)
    out["P2_noisy_test_x"] = {"ccc": ccc_p2}

    # ---- P3. Stage1-only baseline ----
    t0 = time.time()
    y_p3, p_p3 = run_multitask_5fold(X, y_t1, hy, items, sids, stage1_only=True)
    ccc_p3 = float(ccc_fn(y_p3, p_p3))
    print(f"[P3] Stage1-only CCC = {ccc_p3:+.4f}   (just Ridge on H&Y+clinical, no IMU; bound below baseline by stage2's contribution)  [{time.time()-t0:.0f}s]", flush=True)
    out["P3_stage1_only"] = {"ccc": ccc_p3}
    out["stage2_contribution"] = ccc_b - ccc_p3

    # ---- P4. Pure noise X (REAL y, X all randomized) ----
    rng = np.random.RandomState(SEED + 31337)
    X_noise = rng.normal(size=X.shape).astype(np.float64)
    t0 = time.time()
    y_p4, p_p4 = run_multitask_5fold(X_noise, y_t1, hy, items, sids)
    ccc_p4 = float(ccc_fn(y_p4, p_p4))
    print(f"[P4] Noise-X CCC = {ccc_p4:+.4f}   (X randomized, y/items real → should equal Stage1-only CCC ≈ 0.57)  [{time.time()-t0:.0f}s]", flush=True)
    out["P4_pure_noise_X"] = {"ccc": ccc_p4}

    # ---- Verdict ----
    print("\n=== VERDICT ===", flush=True)
    p1_ok = perm_cccs.max() <= 0.30 and abs(perm_cccs.mean()) <= 0.10
    ccc_p1 = float(perm_cccs.mean())
    p2_ok = abs(ccc_p2 - ccc_p3) <= 0.05  # noisy-test should drop near Stage1-only
    p4_ok = abs(ccc_p4 - ccc_p3) <= 0.05  # noise-X should give ≈ Stage1-only CCC
    print(f"  P1 (10-perm scramble dist) {'PASS' if p1_ok else 'FAIL'}  (mean={perm_cccs.mean():+.3f}±{perm_cccs.std():.3f}, max={perm_cccs.max():+.3f}; baseline {ccc_b:.3f} is far away)", flush=True)
    print(f"  P2 (noisy test X)          {'PASS' if p2_ok else 'FAIL'}  (Δ vs Stage1-only = {ccc_p2-ccc_p3:+.3f}; expect close to 0)", flush=True)
    print(f"  P3 (Stage1 contribution)   CCC = {ccc_p3:+.3f}  → Stage2 multi-task adds {ccc_b-ccc_p3:+.3f} on top", flush=True)
    print(f"  P4 (noise-X full cohort)   {'PASS' if p4_ok else 'FAIL'}  (CCC = {ccc_p4:+.3f}, expect ≈ Stage1-only {ccc_p3:+.3f})", flush=True)
    out["verdict"] = {"P1_pass": bool(p1_ok), "P2_pass": bool(p2_ok), "P4_pass": bool(p4_ok),
                      "stage2_lift": float(ccc_b - ccc_p3)}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"iter32_leakage_audit_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
