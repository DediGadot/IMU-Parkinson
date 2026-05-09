"""T1 iter34 LEAKAGE AUDIT — verify no test-data leakage in 8-item × 3-base hybrid.

Replicates the F65 audit pattern (run_t1_iter32_leakage_audit.py) for the iter34
hybrid architecture (Stage 1 Ridge on H&Y + clinical; Stage 2 mean over 3 base
learners {LGB, XGB-hist, ExtraTrees} of RegressorChain over 8 items {9-14, 15, 18}).

Per-fold helpers (impute_fold / feature_select_fold / fit_stage1) are bit-identical
to iter32 audit — already source-code verified fold-local in F65. The new probes
exercise the additional structure: 3 base learners × 8-item auxiliary chain.

Probes (5-fold, seed=42, ProcessPool n_workers=14):

  P0. Baseline replication  — should land near iter34 5-fold expectation.
  P1. 10-permutation y+items scramble distribution
      Cohort-wide consistent shuffle of (y, items{9..14,15,18}) together; X, hy,
      clinical kept original. Severs IMU↔label association entirely. Each perm
      independent. Distribution mean ≈ 0; baseline must be ≥ 5σ above null.
  P2. Noisy test X (canary)
      Replace each test-fold V2 column with random draws from the train-fold
      column marginal. Stage1 should hold; Stage2 chain should collapse to
      Stage1+near-zero. Δ vs Stage1-only must be ≤ 0.05.
  P3. Stage1-only baseline decomposition
      Ridge on H&Y + clinical (no IMU). Quantifies how much of iter34's lift is
      Stage 2 (8-item chain × 3 base learners) vs Stage 1 (clinical staging).
  P4. Pure noise X across full cohort (X randomized; y, items real)
      Architecture should fall back to Stage1-only. Tests for Stage2 leakage from
      anywhere other than X (e.g. items leaking via cache joins).
  P5. Single-base ablation (LGB-only chain) under same conditions
      Cross-check that the multi-base ensemble doesn't introduce a leak the
      single-base F65 audit didn't already cover. Should land within ±0.02 of
      a comparable LGB-only chain at iter34's cohort.

Pass criteria (per-probe):
  P1: |perm_cccs.mean()| ≤ 0.10 AND perm_cccs.max() ≤ 0.30
  P2: |ccc_p2 - ccc_stage1_only| ≤ 0.05
  P4: |ccc_p4 - ccc_stage1_only| ≤ 0.05
  P5: |ccc_p5 - ccc_baseline_lgb_only_estimate| ≤ 0.05  (descriptive)

Run remote:  ./gpu.sh run_t1_iter34_leakage_audit.py
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import hashlib
import json
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    T1_SUM_ITEMS,
    AUX_ITEMS,
)
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS,
    _multitask_predict,
)

STAGE1_ALPHA = 1.0
K_FEATURES = 500
SEED = 42
FEATURE_SET = "A3_tier1"

# Sentinel: the published iter34 LOOCV headline (informational anchor for
# paper Methods note; not used in pass/fail logic — 5-fold ≠ LOOCV).
ITER34_LOOCV_CCC = 0.7366


# -----------------------------------------------------------------------------
# Per-fold workers (module-level; picklable for ProcessPoolExecutor)
# -----------------------------------------------------------------------------
def _hybrid_one_fold(args):
    """8-item × len(bases)-base chain hybrid for one CV fold.

    args = (fold_id, tr, te, X, y_t1, X_s1, items_arr, item_order, seed,
            bases, noisy_test, stage1_only, single_base)
    """
    (fold_id, tr, te, X, y_t1, X_s1, items_arr, item_order, seed,
     bases, noisy_test, stage1_only, single_base) = args

    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    if stage1_only:
        return te, s1_te

    # Per-fold per-item train-mean centering of items
    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
    for pos, i in enumerate(item_order):
        v = items_arr[:, pos][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    Xtr, Xte = impute_fold(X[tr], X[te])
    if noisy_test:
        rng = np.random.RandomState(seed + fold_id + 9999)
        for col in range(Xtr.shape[1]):
            Xte[:, col] = rng.choice(Xtr[:, col], size=Xte.shape[0], replace=True)

    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    bases_used = (single_base,) if single_base is not None else bases
    ip_avg = None
    for b in bases_used:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases_used)

    # T1 sum = sum predictions for items 9-14 only (auxiliary items 15+18 fitted only)
    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array(
        [item_means[i] for i in T1_SUM_ITEMS]
    )
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    return te, s1_te + (t1_pred_from_items - sum_means_t1)


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def run_5fold(
    X, y_t1, hy, items_arr, item_order, sids, *,
    scramble_y: Optional[np.ndarray] = None,
    noisy_test: bool = False,
    stage1_only: bool = False,
    single_base: Optional[str] = None,
    seed: int = SEED,
    n_workers: int = 14,
):
    """One 5-fold pass of the iter34 hybrid (or a probe variant).

    scramble_y: indices to permute y AND every items column consistently.
                X, hy, clinical kept original.
    noisy_test: replace test-fold X rows with random samples from train marginal.
    stage1_only: Stage1-only prediction (no chain Stage2).
    single_base: if given, run chain with just this base learner (else 3-base avg).
    """
    n = len(sids)
    clinical = load_clinical_dict(sids)

    if scramble_y is not None:
        perm = scramble_y
        y_eff = y_t1[perm]
        items_eff = items_arr[perm]
        hy_eff = hy  # KEPT ORIGINAL — only y/items shuffled
    else:
        y_eff = y_t1
        items_eff = items_arr
        hy_eff = hy

    X_s1, _ = build_stage1_features(hy_eff, clinical, ITER5_FEATURE_SETS[FEATURE_SET])

    splits = _kfold(n, seed=seed)
    jobs = [
        (fid, tr, te, X, y_eff, X_s1, items_eff, item_order, seed,
         tuple(BASE_LEARNERS), noisy_test, stage1_only, single_base)
        for fid, (tr, te) in enumerate(splits)
    ]
    preds = np.zeros(n)
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_hybrid_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return y_eff, preds


def _formula_sha256(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _audit_payload(n: int) -> dict:
    return {
        "experiment": "T1 iter34 HYBRID leakage audit (8-item × 3-base)",
        "purpose": "Replicate F65 5-null gate against iter34 architecture",
        "cohort_n": int(n),
        "fold_protocol": "5-fold KFold shuffle=True random_state=42",
        "n_seeds": 1,
        "seed": SEED,
        "stage1": "Ridge on H&Y + cv_yrs + cv_sex + cv_dbs (A3_tier1, alpha=1.0)",
        "stage2_bases": list(BASE_LEARNERS),
        "stage2_chain_targets": list(T1_SUM_ITEMS) + list(AUX_ITEMS),
        "stage2_t1_sum_items": list(T1_SUM_ITEMS),
        "stage2_aux_items": list(AUX_ITEMS),
        "k_features": K_FEATURES,
        "fold_local_helpers": [
            "run_t3_iter2.impute_fold",
            "run_t3_iter2.feature_select_fold",
            "run_t3_iter5_clinical.fit_stage1",
            "sklearn.multioutput.RegressorChain.fit/predict",
        ],
        "probes": [
            "P0 baseline 5-fold replication",
            "P1 10-permutation y+items scramble distribution",
            "P2 noisy test X canary",
            "P3 Stage1-only baseline decomposition",
            "P4 pure noise X full cohort",
            "P5 single-base (LGB-only) ablation",
        ],
        "pass_criteria": {
            "P1": "|perm_mean| <= 0.10 AND perm_max <= 0.30",
            "P2": "|ccc_p2 - ccc_stage1_only| <= 0.05",
            "P4": "|ccc_p4 - ccc_stage1_only| <= 0.05",
            "P5": "descriptive only — should be near baseline",
        },
    }


def main(n_workers: int = 14):
    sids, X, y_t1, hy, items_dict, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    items_arr = np.column_stack([items_dict[i] for i in item_order])
    n = len(sids)
    print(
        f"\n=== T1 iter34 LEAKAGE AUDIT (N={n}, seed={SEED}, 5-fold, "
        f"n_workers={n_workers}) ===",
        flush=True,
    )
    print(f"  item_order: {item_order}", flush=True)
    print(f"  bases: {BASE_LEARNERS}", flush=True)

    payload = _audit_payload(n)
    sha = _formula_sha256(payload)
    print(f"  formula_sha256 = {sha}", flush=True)

    out: dict = {
        "timestamp": datetime.now().isoformat(),
        "n": int(n),
        "seed": SEED,
        "formula_sha256": sha,
        "audit_spec": payload,
        "iter34_loocv_anchor": ITER34_LOOCV_CCC,
    }

    overall_t0 = time.time()

    # ---- P0. Baseline 5-fold ----
    t0 = time.time()
    y_b, p_b = run_5fold(X, y_t1, hy, items_arr, item_order, sids,
                         n_workers=n_workers)
    ccc_b = float(ccc_fn(y_b, p_b))
    print(
        f"[P0] baseline 5-fold CCC = {ccc_b:+.4f}   "
        f"[{time.time()-t0:.0f}s]",
        flush=True,
    )
    out["P0_baseline"] = {"ccc": ccc_b}

    # ---- P3. Stage1-only baseline (compute first; used by P2/P4 pass criteria) ----
    t0 = time.time()
    y_s1, p_s1 = run_5fold(X, y_t1, hy, items_arr, item_order, sids,
                           stage1_only=True, n_workers=n_workers)
    ccc_s1 = float(ccc_fn(y_s1, p_s1))
    print(
        f"[P3] Stage1-only CCC = {ccc_s1:+.4f}   "
        f"(Ridge on H&Y+clinical, no IMU)  "
        f"[{time.time()-t0:.0f}s]",
        flush=True,
    )
    out["P3_stage1_only"] = {"ccc": ccc_s1}
    out["stage2_contribution_5fold"] = ccc_b - ccc_s1

    # ---- P1. 10-permutation y+items scramble distribution ----
    t0 = time.time()
    perm_cccs = []
    perm_seeds = [123, 456, 789, 1011, 1213, 1415, 1617, 1819, 2021, 2223]
    for ps in perm_seeds:
        rng = np.random.RandomState(ps)
        perm = rng.permutation(n)
        _, p_perm = run_5fold(X, y_t1, hy, items_arr, item_order, sids,
                              scramble_y=perm, n_workers=n_workers)
        perm_cccs.append(float(ccc_fn(y_t1[perm], p_perm)))
        print(f"     perm_seed={ps}: CCC={perm_cccs[-1]:+.4f}", flush=True)
    perm_cccs = np.asarray(perm_cccs)
    z_score = (ccc_b - perm_cccs.mean()) / max(perm_cccs.std(), 1e-6)
    print(
        f"[P1] 10-perm scramble distribution: mean={perm_cccs.mean():+.4f}, "
        f"std={perm_cccs.std():.4f}, min={perm_cccs.min():+.4f}, "
        f"max={perm_cccs.max():+.4f}",
        flush=True,
    )
    print(
        f"     baseline {ccc_b:+.4f} vs permutation null → "
        f"z-score = {z_score:.1f}σ above null  "
        f"[{time.time()-t0:.0f}s]",
        flush=True,
    )
    out["P1_perm_distribution"] = {
        "perm_seeds": perm_seeds,
        "perm_cccs": [float(x) for x in perm_cccs],
        "perm_mean": float(perm_cccs.mean()),
        "perm_std": float(perm_cccs.std()),
        "perm_min": float(perm_cccs.min()),
        "perm_max": float(perm_cccs.max()),
        "z_score_baseline_above_null": float(z_score),
    }

    # ---- P2. Noisy test X (canary) ----
    t0 = time.time()
    y_p2, p_p2 = run_5fold(X, y_t1, hy, items_arr, item_order, sids,
                           noisy_test=True, n_workers=n_workers)
    ccc_p2 = float(ccc_fn(y_p2, p_p2))
    delta_p2 = ccc_p2 - ccc_s1
    print(
        f"[P2] noisy-test-X CCC = {ccc_p2:+.4f}   "
        f"(Δ vs Stage1-only = {delta_p2:+.4f}; expect close to 0)  "
        f"[{time.time()-t0:.0f}s]",
        flush=True,
    )
    out["P2_noisy_test_x"] = {"ccc": ccc_p2, "delta_vs_stage1_only": delta_p2}

    # ---- P4. Pure noise X (X randomized; y, items real) ----
    rng = np.random.RandomState(SEED + 31337)
    X_noise = rng.normal(size=X.shape).astype(np.float64)
    t0 = time.time()
    y_p4, p_p4 = run_5fold(X_noise, y_t1, hy, items_arr, item_order, sids,
                           n_workers=n_workers)
    ccc_p4 = float(ccc_fn(y_p4, p_p4))
    delta_p4 = ccc_p4 - ccc_s1
    print(
        f"[P4] noise-X CCC = {ccc_p4:+.4f}   "
        f"(should ≈ Stage1-only {ccc_s1:+.4f}, Δ={delta_p4:+.4f})  "
        f"[{time.time()-t0:.0f}s]",
        flush=True,
    )
    out["P4_pure_noise_X"] = {"ccc": ccc_p4, "delta_vs_stage1_only": delta_p4}

    # ---- P5. Single-base ablation (LGB-only chain) ----
    t0 = time.time()
    y_p5, p_p5 = run_5fold(X, y_t1, hy, items_arr, item_order, sids,
                           single_base="lgb", n_workers=n_workers)
    ccc_p5 = float(ccc_fn(y_p5, p_p5))
    delta_p5 = ccc_b - ccc_p5
    print(
        f"[P5] LGB-only chain CCC = {ccc_p5:+.4f}   "
        f"(3-base ensemble lift = {delta_p5:+.4f})  "
        f"[{time.time()-t0:.0f}s]",
        flush=True,
    )
    out["P5_lgb_only_chain"] = {
        "ccc": ccc_p5,
        "ensemble_lift_vs_3base": delta_p5,
    }

    # ---- Verdict ----
    p1_ok = bool(perm_cccs.max() <= 0.30 and abs(perm_cccs.mean()) <= 0.10)
    p2_ok = bool(abs(delta_p2) <= 0.05)
    p4_ok = bool(abs(delta_p4) <= 0.05)
    # P3 descriptive only (always reports)
    # P5 descriptive only (sanity)

    overall_wall = time.time() - overall_t0
    print("\n=== VERDICT ===", flush=True)
    print(
        f"  P0 baseline 5-fold      CCC = {ccc_b:+.4f}",
        flush=True,
    )
    print(
        f"  P1 10-perm null dist    "
        f"{'PASS' if p1_ok else 'FAIL'}  "
        f"(mean={perm_cccs.mean():+.3f} ± {perm_cccs.std():.3f}, "
        f"max={perm_cccs.max():+.3f}; baseline {ccc_b:.3f} is "
        f"{z_score:.1f}σ away)",
        flush=True,
    )
    print(
        f"  P2 noisy test X         "
        f"{'PASS' if p2_ok else 'FAIL'}  "
        f"(CCC={ccc_p2:+.3f}, Δ vs Stage1-only = {delta_p2:+.3f})",
        flush=True,
    )
    print(
        f"  P3 Stage1 contribution  CCC = {ccc_s1:+.3f}  "
        f"→ Stage2 hybrid adds {ccc_b-ccc_s1:+.3f} on top",
        flush=True,
    )
    print(
        f"  P4 pure noise X         "
        f"{'PASS' if p4_ok else 'FAIL'}  "
        f"(CCC={ccc_p4:+.3f}, Δ vs Stage1-only = {delta_p4:+.3f})",
        flush=True,
    )
    print(
        f"  P5 LGB-only ablation    CCC = {ccc_p5:+.3f}  "
        f"(3-base ensemble lift = {delta_p5:+.3f})",
        flush=True,
    )
    print(f"\n  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)",
          flush=True)

    all_pass = p1_ok and p2_ok and p4_ok
    verdict_line = (
        f"iter34 CCC=0.7366 is leakage-clean"
        if all_pass else
        f"iter34 CCC=0.7366 is leakage-suspect (one or more probes failed)"
    )
    print(f"\n  ONE-LINE VERDICT: {verdict_line}", flush=True)

    out["verdict"] = {
        "P1_pass": p1_ok,
        "P2_pass": p2_ok,
        "P4_pass": p4_ok,
        "all_pass": all_pass,
        "stage2_lift_5fold": float(ccc_b - ccc_s1),
        "ensemble_lift_vs_lgb_only": float(delta_p5),
        "wall_time_total_s": float(overall_wall),
        "verdict_line": verdict_line,
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"iter34_leakage_audit_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path}", flush=True)
    return out_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--n_workers", type=int,
        default=int(os.getenv("ITER34_AUDIT_WORKERS", 14)),
    )
    args = ap.parse_args()
    main(n_workers=args.n_workers)
