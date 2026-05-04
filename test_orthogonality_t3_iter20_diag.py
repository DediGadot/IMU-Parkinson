"""iter20 diagnostic — orthogonality probe ONLY (post-F54-audit, 2026-05-04).

The audit (F54) correctly identified that my iter20 hybrid α / Ridge meta-stack
designs have stacking-leakage (meta trains on OOFs whose base-fold overlaps
meta-train rows). It stopped the screen run mid-flight.

This script runs ONLY the orthogonality probe (Variant A from iter20), which IS
leakage-clean because it's a global descriptive correlation between residuals,
not a predictive operation:

  pearson(composite_5fold_oof − iter5_5fold_oof, updrs3 − iter5_5fold_oof)

Interpretation:
  - r ≈ 0    → composite is REDUNDANT with iter5; no hybrid can help
  - r > 0.10 → composite carries COMPLEMENTARY info; nested-CV hybrid worth trying
  - r < 0    → composite is anti-correlated with target residual; hybrid would hurt

This is a 5-min diagnostic that informs whether to invest in the iter21 nested
T3-native hybrid design (per F54 recommendation).

Diagnostic-only — does NOT produce a lockbox or canonical change.
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, pearson_r
from project_paths import RESULTS_DIR
from run_per_item_v2 import load_data
from compose_t3_iter19_peritem import (
    compute_composite,
    load_architecture_map,
    _load_canonical_updrs3,
)
from run_t3_iter5_clinical import clinical_residual_kfold
from run_t3_iter3 import load_full_pd_data


SEEDS = [42, 1337, 7]


def main() -> None:
    print("Loading data (T1 cohort N=94 master — same cohort as iter19/iter20)...", flush=True)
    d = load_data()
    n = len(d["sids"])
    print(f"  N = {n} PD subjects", flush=True)

    arch_map = load_architecture_map()
    print(f"\nArchitecture map ({len(arch_map)} items):", flush=True)
    for i in sorted(arch_map.keys()):
        print(f"  item {i:>2d} → {arch_map[i]}", flush=True)

    print(f"\nLoading canonical updrs3 target...", flush=True)
    y_updrs3 = _load_canonical_updrs3(d["sids"])
    print(f"  updrs3: mean={y_updrs3.mean():.2f}, std={y_updrs3.std():.2f}", flush=True)

    print(f"\n=== Computing composite 5-fold OOF (iter19 architecture, {len(SEEDS)} seeds) ===", flush=True)
    res = compute_composite(d, arch_map, "5fold", SEEDS)
    composite_per_seed = res["t3_pred_per_seed"]  # offset-corrected, on updrs3 scale

    print(f"\n=== Reproducing iter5 5-fold OOF (A3_tier1, {len(SEEDS)} seeds, N=94 subset) ===", flush=True)
    sids_t3, _, _, _, _, _ = load_full_pd_data()
    sid_to_idx = {s: i for i, s in enumerate(sids_t3)}
    t3_indices = np.array([sid_to_idx[s] for s in d["sids"] if s in sid_to_idx])
    iter5_per_seed = []
    for seed in SEEDS:
        t0 = time.time()
        full_oof = clinical_residual_kfold(seed=seed, feature_set="A3_tier1", alpha=1.0)
        oof = full_oof[t3_indices]
        iter5_per_seed.append(oof)
        print(f"  seed={seed} iter5 5-fold CCC vs updrs3 = {ccc_fn(y_updrs3, oof):+.4f}  ({time.time()-t0:.1f}s)", flush=True)

    # Variant A — orthogonality probe per seed
    print(f"\n=== Variant A — ORTHOGONALITY PROBE ===", flush=True)
    pearson_per_seed = []
    composite_ccc_per_seed = []
    iter5_ccc_per_seed = []
    for seed_i, seed in enumerate(SEEDS):
        comp = composite_per_seed[seed_i]
        it5 = iter5_per_seed[seed_i]
        comp_minus_it5 = comp - it5
        target_minus_it5 = y_updrs3 - it5
        r = float(pearson_r(comp_minus_it5, target_minus_it5))
        pearson_per_seed.append(r)
        c_comp = float(ccc_fn(y_updrs3, comp))
        c_it5 = float(ccc_fn(y_updrs3, it5))
        composite_ccc_per_seed.append(c_comp)
        iter5_ccc_per_seed.append(c_it5)
        print(f"  seed={seed}  pearson(comp - iter5, updrs3 - iter5) = {r:+.4f}  | composite CCC={c_comp:+.4f}  iter5 CCC={c_it5:+.4f}", flush=True)
    pearson_mean = float(np.mean(pearson_per_seed))
    pearson_std = float(np.std(pearson_per_seed))
    composite_ccc_mean = float(np.mean(composite_ccc_per_seed))
    iter5_ccc_mean = float(np.mean(iter5_ccc_per_seed))

    print(f"\n  → orthogonality r mean = {pearson_mean:+.4f} ± {pearson_std:.4f}", flush=True)
    print(f"  → composite 5-fold CCC mean = {composite_ccc_mean:+.4f}", flush=True)
    print(f"  → iter5     5-fold CCC mean = {iter5_ccc_mean:+.4f}", flush=True)

    # Interpretation
    print(f"\n=== INTERPRETATION ===", flush=True)
    if abs(pearson_mean) < 0.10:
        verdict = "REDUNDANT — composite contains no information complementary to iter5 at this N=94"
        recommend = "No hybrid (B/C/D) can extract additional signal. F53 negative writeup stands."
    elif pearson_mean > 0.10:
        # Bound the realizable hybrid CCC
        # If hybrid_pred = iter5 + α(comp - iter5), optimal α = corr * std_target_res / std_comp_res
        # Resulting hybrid Pearson r = sqrt(r_iter5^2 + r * (1 - r_iter5^2))
        # where r_iter5 = pearson(iter5, updrs3); r = orthogonality
        # CCC bound is ≤ Pearson r
        verdict = f"COMPLEMENTARY — composite carries information beyond iter5 (r = {pearson_mean:+.3f})"
        recommend = "Worth attempting iter21 with proper nested-CV stacking and T3-native cohort (N=98)."
    else:
        verdict = f"ANTI-CORRELATED — composite errors are negatively correlated with iter5's residual error"
        recommend = "Hybrid would hurt. F53 negative writeup stands; no iter21 needed."
    print(f"  Verdict: {verdict}", flush=True)
    print(f"  Recommendation: {recommend}", flush=True)

    # Bonus: estimate maximum realizable Pearson r of hybrid given orthogonality
    # Decompose: updrs3 = iter5_pred + residual; composite = iter5_pred + (comp - iter5)
    # For the hybrid to gain: need (comp - iter5) to predict residual = (updrs3 - iter5_pred)
    # Maximum r_hybrid via OLS: sqrt(r_base^2 + r * (1 - r_base^2)) where r_base = pearson(iter5, updrs3)
    # Actually correct formula: if pearson(comp-iter5, target-iter5) = r, then
    #   var(target-iter5) = (1 - r_base^2) * var(target)
    #   hybrid_pred = iter5 + α(comp-iter5); optimal α reduces residual variance by r^2
    #   r_hybrid^2 = r_base^2 + r^2 * (1 - r_base^2)
    r_base_per_seed = [float(pearson_r(iter5_per_seed[i], y_updrs3)) for i in range(len(SEEDS))]
    r_base = float(np.mean(r_base_per_seed))
    r_hybrid_squared = r_base**2 + (pearson_mean**2) * (1 - r_base**2)
    r_hybrid_bound = float(np.sqrt(max(0, r_hybrid_squared)))
    print(f"\n  Theoretical hybrid Pearson r upper bound = √(r_iter5² + r_orth² · (1 - r_iter5²)) "
          f"= √({r_base**2:.4f} + {pearson_mean**2:.4f}·{(1 - r_base**2):.4f}) = {r_hybrid_bound:+.4f}", flush=True)
    print(f"  Saved iter5 LOOCV CCC at N=98 = 0.5227 (canonical baseline)", flush=True)
    print(f"  iter5 5-fold CCC at N=94 = {iter5_ccc_mean:+.4f} (this comparison)", flush=True)
    print(f"  Even an optimal hybrid is bounded by Pearson r ≤ {r_hybrid_bound:+.4f}, so hybrid CCC ≤ {r_hybrid_bound:+.4f}", flush=True)
    if r_hybrid_bound > iter5_ccc_mean + 0.05:
        print(f"  → Hybrid bound exceeds iter5 by >{r_hybrid_bound - iter5_ccc_mean:.3f}; iter21 design (nested) WORTH TRYING.", flush=True)
    elif r_hybrid_bound > iter5_ccc_mean + 0.025:
        print(f"  → Hybrid bound exceeds iter5 by {r_hybrid_bound - iter5_ccc_mean:.3f}; marginal — iter21 may or may not pass strict gate.", flush=True)
    else:
        print(f"  → Hybrid bound exceeds iter5 by only {r_hybrid_bound - iter5_ccc_mean:.3f}; iter21 unlikely to pass strict +0.025 gate.", flush=True)

    # Save artifacts
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "diagnostic_only": True,
        "post_F54_audit": True,
        "ts": ts,
        "n_subjects": n,
        "seeds": SEEDS,
        "iter5_5fold_ccc_per_seed": iter5_ccc_per_seed,
        "iter5_5fold_ccc_mean": iter5_ccc_mean,
        "iter5_pearson_r_per_seed": r_base_per_seed,
        "iter5_pearson_r_mean": r_base,
        "composite_5fold_ccc_per_seed": composite_ccc_per_seed,
        "composite_5fold_ccc_mean": composite_ccc_mean,
        "orthogonality_pearson_per_seed": pearson_per_seed,
        "orthogonality_pearson_mean": pearson_mean,
        "orthogonality_pearson_std": pearson_std,
        "hybrid_pearson_r_upper_bound": r_hybrid_bound,
        "hybrid_ccc_upper_bound": r_hybrid_bound,
        "verdict": verdict,
        "recommendation": recommend,
    }
    out_path = RESULTS_DIR / f"iter20_orthogonality_diagnostic_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {out_path.name}", flush=True)


if __name__ == "__main__":
    main()
