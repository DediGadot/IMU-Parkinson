"""iter20 — Hybrid iter5 + composite-residual hypothesis test (2026-05-04).

Origin: F53 owl review identified that the per-item gated T3 composite (iter19)
underperformed iter5 by Δ=−0.107 5-fold not because it lacked signal but because
of (a) variance compounding, (b) shrinkage compounding, (c) H&Y double-counting,
and (d) no orthogonality test. This script runs four candidate fixes in a single
batch with a single pre-registration:

  Variant A — orthogonality probe:
      pearson(composite_pred − iter5_pred, updrs3 − iter5_pred)
      If r ≈ 0, composite is redundant with iter5 (no hope for hybrid).
      If r > 0.1, composite carries complementary information.

  Variant B — OLS α-hybrid (the headline hypothesis):
      For each fold: fit α via OLS on training rows:
          (composite_pred_tr − iter5_pred_tr) → (updrs3_tr − iter5_pred_tr)
      Predict: hybrid_pred_te = iter5_pred_te + α × (composite_pred_te − iter5_pred_te)
      Equivalent to convex mixing iter5 and composite at fold-optimal α.

  Variant C — Ridge meta-stack:
      For each fold: fit Ridge(α=1.0) on training (iter5_pred, composite_pred) → updrs3.
      Predict on test fold. 2-feature meta-learner with shrinkage.

  Variant D — per-fold linear calibration of composite alone:
      For each fold: fit OLS on (composite_pred_tr) → updrs3_tr (slope+intercept).
      Predict on test. Tests whether range-correction alone closes the gap.

All variants use 3 seeds × 5-fold KFold splits. iter5 reproduction is bit-identical
to run_t3_iter5_clinical.clinical_residual_kfold(seed, "A3_tier1", 1.0). Composite
reproduction is bit-identical to compose_t3_iter19_peritem.compute_composite under
the iter19 architecture map (already pre-registered, formula_sha256 5d2185f19c1abb58).

5null gate inheritance: iter5 and per-item architectures both pre-passed; the
hybrid α / meta-stack / calibration are leakage-clean by per-fold fit on training
rows only.

Pre-registration: results/preregistration_t3_iter20_hybrid_<ts>.json — written
BEFORE any composite or hybrid CCC is computed.

Gate (sum-level): hybrid 5-fold CCC ≥ iter5 5-fold + 0.025 with seed std < 0.02.

Usage:
    python3 test_hybrid_t3_iter20.py --mode screen [--seeds 42 1337 7]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_per_item_v2 import load_data
from compose_t3_iter19_peritem import (
    compute_composite,
    load_architecture_map,
    _load_canonical_updrs3,
    _make_kfold_splits,
)
from run_t3_iter5_clinical import clinical_residual_kfold


SCREEN_SEEDS = [42, 1337, 7]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def _iter5_5fold_oof_n94(d: dict, seed: int) -> np.ndarray:
    """Reproduce iter5 5-fold OOF on the full N=98 cohort then subset to N=94 (T1 cohort)."""
    from run_t3_iter3 import load_full_pd_data
    sids_t3, _, _, _, _, _ = load_full_pd_data()
    sid_to_idx = {s: i for i, s in enumerate(sids_t3)}
    t3_indices = np.array([sid_to_idx[s] for s in d["sids"] if s in sid_to_idx])
    full_oof = clinical_residual_kfold(seed=seed, feature_set="A3_tier1", alpha=1.0)
    return full_oof[t3_indices]


def write_preregistration(arch_map: dict, seeds: list) -> tuple[Path, str]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "experiment": "T3 push iter20 — hybrid iter5 + composite-residual + Ridge meta + calibration",
        "origin": "F53 owl review (2026-05-04 14:00) — addresses variance compounding, shrinkage, H&Y double-count.",
        "variants": [
            "A — orthogonality probe (pearson(composite-iter5, updrs3-iter5))",
            "B — OLS α-hybrid (per-fold convex mix iter5 + α*(composite-iter5))",
            "C — Ridge meta-stack (per-fold Ridge on (iter5, composite) → updrs3)",
            "D — calibrated composite (per-fold OLS slope+intercept, composite alone)",
        ],
        "architecture_map": {str(k): v for k, v in arch_map.items()},
        "iter19_composite_formula_sha256_inherited": "5d2185f19c1abb58 (compose_t3_iter19 architecture map, single batch)",
        "seeds": list(seeds),
        "cv": "5fold (KFold shuffle=True)",
        "n_subjects": "load_data() T1 cohort (N=94 PD)",
        "5null_inheritance": (
            "iter5 architecture pre-passed; per-item architectures inherited from iter19 "
            "(pre-passed via iter8/iter17/A1 backfill). Hybrid α / Ridge meta / calibration "
            "are leakage-clean by per-fold fit on training rows only — no global fitting."
        ),
        "purpose": (
            "Test whether per-item composite carries information complementary to iter5. "
            "If pearson(composite-iter5, updrs3-iter5) ≈ 0, the per-item composition is "
            "redundant. If > 0.1, mixing should improve CCC. The hybrid variants quantify "
            "the realizable gain under per-fold leakage-clean mixing."
        ),
    }
    formula_sha = _formula_sha256(payload)
    git_sha = _git_sha()
    pre = {
        **payload,
        "formula_sha256": formula_sha,
        "git_sha": git_sha,
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "created_at_local": datetime.now().isoformat(),
        "timestamp": ts,
        "lockbox_rules": [
            "Architecture map locked BEFORE any hybrid CCC is computed (inherits iter19).",
            "Variants A-D evaluated in one batch; reported regardless of outcome.",
            "Hybrid 5-fold gate: Δ ≥ +0.025 vs iter5 5-fold AND hybrid std < 0.020 across 3 seeds.",
            "Lockbox LOOCV ONLY if a variant passes the 5-fold gate.",
            "If no variant passes, F54 negative writeup; canonical numbers UNCHANGED.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_t3_iter20_hybrid_{ts}.json"
    with open(pre_path, "w") as f:
        json.dump(pre, f, indent=2, default=float)
    print(f"\nPre-registration: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula_sha[:16]}...", flush=True)
    print(f"  git_sha = {git_sha[:12]}", flush=True)
    return pre_path, ts


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen"], default="screen")
    p.add_argument("--seeds", type=int, nargs="+", default=SCREEN_SEEDS)
    args = p.parse_args()

    print("Loading data (T1 cohort N=94 master)...", flush=True)
    d = load_data()
    n = len(d["sids"])
    print(f"  N = {n} PD subjects", flush=True)

    arch_map = load_architecture_map()
    pre_path, ts = write_preregistration(arch_map, args.seeds)

    print(f"\nLoading canonical updrs3 target...", flush=True)
    y_updrs3 = _load_canonical_updrs3(d["sids"])
    print(f"  updrs3: mean={y_updrs3.mean():.2f}, std={y_updrs3.std():.2f}", flush=True)

    print(f"\n=== Computing composite (iter19 architecture, 3 seeds × 5-fold) ===", flush=True)
    res = compute_composite(d, arch_map, "5fold", args.seeds)
    composite_raw_per_seed = res["t3_pred_per_seed"]
    composite_offset_per_seed = res["t3_pred_per_seed"]  # already offset-corrected in compute_composite
    # Note: compute_composite returns offset-corrected predictions in t3_pred_per_seed
    # Raw is in t3_pred_raw_mean (only mean across seeds, not per-seed)
    # For variants that need raw composite, use offset-corrected — equivalent up to constant
    # which doesn't affect Pearson r (orthogonality) or fold-local α (constant absorbed)

    # ── Reproduce iter5 5-fold OOF per seed ──
    print(f"\n=== Reproducing iter5 5-fold (3 seeds, A3_tier1) ===", flush=True)
    iter5_per_seed = []
    for seed in args.seeds:
        t0 = time.time()
        oof = _iter5_5fold_oof_n94(d, seed)
        iter5_per_seed.append(oof)
        print(f"  seed={seed} iter5 5-fold CCC vs updrs3 = {ccc_fn(y_updrs3, oof):+.4f}  ({time.time()-t0:.1f}s)", flush=True)

    # ── Variant A: orthogonality probe ──
    print(f"\n=== Variant A — orthogonality probe (per-seed) ===", flush=True)
    pearson_orth_per_seed = []
    for seed_i, seed in enumerate(args.seeds):
        comp = composite_offset_per_seed[seed_i]
        it5 = iter5_per_seed[seed_i]
        comp_res = comp - it5
        target_res = y_updrs3 - it5
        r = float(pearson_r(comp_res, target_res))
        pearson_orth_per_seed.append(r)
        print(f"  seed={seed}  pearson(comp-iter5, updrs3-iter5) = {r:+.4f}", flush=True)
    pearson_orth_mean = float(np.mean(pearson_orth_per_seed))
    print(f"  → mean orthogonality r = {pearson_orth_mean:+.4f}", flush=True)
    if abs(pearson_orth_mean) < 0.10:
        print(f"  → composite is approximately REDUNDANT with iter5 (|r| < 0.10)", flush=True)
    elif pearson_orth_mean > 0.10:
        print(f"  → composite carries COMPLEMENTARY info (r > +0.10)", flush=True)
    else:
        print(f"  → composite is ANTI-correlated with target residual (r < −0.10)", flush=True)

    # ── Variant B — OLS α-hybrid ──
    print(f"\n=== Variant B — OLS α-hybrid (per-fold, per-seed) ===", flush=True)
    hybrid_b_ccc_per_seed = []
    hybrid_b_alpha_means = []
    for seed_i, seed in enumerate(args.seeds):
        comp = composite_offset_per_seed[seed_i]
        it5 = iter5_per_seed[seed_i]
        splits = _make_kfold_splits(n, seed)
        hybrid_pred = np.zeros(n)
        alphas = []
        for tr, te in splits:
            comp_res_tr = comp[tr] - it5[tr]
            tgt_res_tr = y_updrs3[tr] - it5[tr]
            denom = float(np.var(comp_res_tr) * len(tr))
            if denom < 1e-9:
                alpha = 0.0
            else:
                alpha = float(np.sum((comp_res_tr - comp_res_tr.mean()) *
                                       (tgt_res_tr - tgt_res_tr.mean())) /
                              max(np.sum((comp_res_tr - comp_res_tr.mean())**2), 1e-9))
            alphas.append(alpha)
            comp_res_te = comp[te] - it5[te]
            hybrid_pred[te] = it5[te] + alpha * comp_res_te
        c = float(ccc_fn(y_updrs3, hybrid_pred))
        hybrid_b_ccc_per_seed.append(c)
        hybrid_b_alpha_means.append(float(np.mean(alphas)))
        print(f"  seed={seed}  hybrid CCC = {c:+.4f}  mean α = {np.mean(alphas):+.3f}  (folds: {[f'{a:+.3f}' for a in alphas]})", flush=True)
    hybrid_b_ccc_mean = float(np.mean(hybrid_b_ccc_per_seed))
    hybrid_b_ccc_std = float(np.std(hybrid_b_ccc_per_seed))
    print(f"  → hybrid (OLS α) CCC = {hybrid_b_ccc_mean:+.4f} ± {hybrid_b_ccc_std:.4f}", flush=True)

    # ── Variant C — Ridge meta-stack ──
    print(f"\n=== Variant C — Ridge meta-stack (per-fold, per-seed) ===", flush=True)
    hybrid_c_ccc_per_seed = []
    for seed_i, seed in enumerate(args.seeds):
        comp = composite_offset_per_seed[seed_i]
        it5 = iter5_per_seed[seed_i]
        splits = _make_kfold_splits(n, seed)
        meta_pred = np.zeros(n)
        for tr, te in splits:
            X_tr = np.column_stack([it5[tr], comp[tr]])
            X_te = np.column_stack([it5[te], comp[te]])
            ridge = Ridge(alpha=1.0)
            ridge.fit(X_tr, y_updrs3[tr])
            meta_pred[te] = ridge.predict(X_te)
        c = float(ccc_fn(y_updrs3, meta_pred))
        hybrid_c_ccc_per_seed.append(c)
        print(f"  seed={seed}  Ridge meta CCC = {c:+.4f}", flush=True)
    hybrid_c_ccc_mean = float(np.mean(hybrid_c_ccc_per_seed))
    hybrid_c_ccc_std = float(np.std(hybrid_c_ccc_per_seed))
    print(f"  → Ridge meta CCC = {hybrid_c_ccc_mean:+.4f} ± {hybrid_c_ccc_std:.4f}", flush=True)

    # ── Variant D — composite alone with linear calibration ──
    print(f"\n=== Variant D — composite alone with per-fold OLS slope+intercept ===", flush=True)
    hybrid_d_ccc_per_seed = []
    for seed_i, seed in enumerate(args.seeds):
        comp = composite_offset_per_seed[seed_i]
        splits = _make_kfold_splits(n, seed)
        cal_pred = np.zeros(n)
        for tr, te in splits:
            ols = LinearRegression()
            ols.fit(comp[tr].reshape(-1, 1), y_updrs3[tr])
            cal_pred[te] = ols.predict(comp[te].reshape(-1, 1))
        c = float(ccc_fn(y_updrs3, cal_pred))
        hybrid_d_ccc_per_seed.append(c)
        print(f"  seed={seed}  calibrated composite CCC = {c:+.4f}", flush=True)
    hybrid_d_ccc_mean = float(np.mean(hybrid_d_ccc_per_seed))
    hybrid_d_ccc_std = float(np.std(hybrid_d_ccc_per_seed))
    print(f"  → calibrated composite CCC = {hybrid_d_ccc_mean:+.4f} ± {hybrid_d_ccc_std:.4f}", flush=True)

    # ── Reference numbers ──
    iter5_cccs = [float(ccc_fn(y_updrs3, oof)) for oof in iter5_per_seed]
    iter5_ccc_mean = float(np.mean(iter5_cccs))
    iter5_ccc_std = float(np.std(iter5_cccs))
    composite_cccs = [float(ccc_fn(y_updrs3, p)) for p in composite_offset_per_seed]
    composite_ccc_mean = float(np.mean(composite_cccs))

    # ── Gate decisions ──
    GATE_DELTA = 0.025
    GATE_STD = 0.020
    print(f"\n=== iter20 GATE SUMMARY (vs iter5 5-fold {iter5_ccc_mean:+.4f} ± {iter5_ccc_std:.4f}) ===", flush=True)
    print(f"  Variant A (orthogonality probe):      r = {pearson_orth_mean:+.4f}  (informative only)", flush=True)
    rows = [
        ("B", "OLS α-hybrid",         hybrid_b_ccc_mean, hybrid_b_ccc_std),
        ("C", "Ridge meta-stack",     hybrid_c_ccc_mean, hybrid_c_ccc_std),
        ("D", "calibrated composite", hybrid_d_ccc_mean, hybrid_d_ccc_std),
    ]
    gate_pass_any = False
    gate_results = {}
    for name, desc, mean_, std_ in rows:
        delta = mean_ - iter5_ccc_mean
        passes = (delta >= GATE_DELTA) and (std_ < GATE_STD)
        gate_pass_any |= passes
        gate_results[name] = {"ccc": mean_, "std": std_, "delta_vs_iter5": delta, "passes": passes}
        flag = "PASS" if passes else ("std fail" if delta >= GATE_DELTA else "Δ fail")
        print(f"  Variant {name} ({desc:20s}):  CCC = {mean_:+.4f} ± {std_:.4f}  Δ vs iter5 = {delta:+.4f}  → {flag}", flush=True)
    print(f"\n  GATE: {'PASS — proceed to LOOCV lockbox' if gate_pass_any else 'FAIL — F54 negative writeup'}", flush=True)

    # ── Save artifacts ──
    out = {
        "preregistration": pre_path.name,
        "ts": ts,
        "n_subjects": n,
        "seeds": list(args.seeds),
        "iter5_5fold_ccc_mean": iter5_ccc_mean,
        "iter5_5fold_ccc_std": iter5_ccc_std,
        "iter5_seed_cccs": iter5_cccs,
        "composite_5fold_ccc_mean": composite_ccc_mean,
        "composite_seed_cccs": composite_cccs,
        "variant_A_orthogonality_pearson_per_seed": pearson_orth_per_seed,
        "variant_A_orthogonality_pearson_mean": pearson_orth_mean,
        "variant_B_OLS_alpha_hybrid_ccc_per_seed": hybrid_b_ccc_per_seed,
        "variant_B_OLS_alpha_hybrid_ccc_mean": hybrid_b_ccc_mean,
        "variant_B_OLS_alpha_hybrid_ccc_std": hybrid_b_ccc_std,
        "variant_B_alpha_per_seed_means": hybrid_b_alpha_means,
        "variant_C_ridge_meta_ccc_per_seed": hybrid_c_ccc_per_seed,
        "variant_C_ridge_meta_ccc_mean": hybrid_c_ccc_mean,
        "variant_C_ridge_meta_ccc_std": hybrid_c_ccc_std,
        "variant_D_calibrated_composite_ccc_per_seed": hybrid_d_ccc_per_seed,
        "variant_D_calibrated_composite_ccc_mean": hybrid_d_ccc_mean,
        "variant_D_calibrated_composite_ccc_std": hybrid_d_ccc_std,
        "gate_results": gate_results,
        "gate_pass_any": gate_pass_any,
    }
    out_path = RESULTS_DIR / f"test_hybrid_t3_iter20_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {out_path.name}", flush=True)


if __name__ == "__main__":
    main()
