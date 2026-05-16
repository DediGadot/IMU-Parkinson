"""Combined T3 lift analysis: my-arch + stride vs iter47 canonical.

Question: does my-arch (univariate-corr K=500) + stride aug produce a real
lift over iter47 canonical (LGB-importance K=500, no stride)?

Inputs:
  iter47 canonical: results/iter47_invalidcode_subject_preds_20260508_194605.csv
                    (drop_allmissing_validrange, stage2_current, N=95, CCC=0.3784)
  my-arch + stride: results/lockbox_t3_b_stride_30seed_20260512_215835.json
                    (30-seed mean of aug predictions, CCC=0.4209)

Direct paired-bootstrap test of the combined lift.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc


def main():
    print("=" * 72)
    print("Combined T3 lift analysis")
    print("=" * 72)

    # Load iter47 canonical
    iter47 = pd.read_csv(REPO_ROOT / "results" / "iter47_invalidcode_subject_preds_20260508_194605.csv")
    target = iter47[(iter47["cohort"] == "drop_allmissing_validrange") &
                    (iter47["stage2_policy"] == "stage2_current")]
    target = target.set_index("sid")

    # Load 30-seed stride aug
    j = json.loads((REPO_ROOT / "results" / "lockbox_t3_b_stride_30seed_20260512_215835.json").read_text())
    sids = j["per_subject"]["sids"]
    y_30 = np.array(j["per_subject"]["y_true"])
    p_base_30 = np.array(j["per_subject"]["y_pred_baseline_mean"])
    p_aug_30 = np.array(j["per_subject"]["y_pred_augmented_mean"])

    # Align
    common = target.index.intersection(sids)
    common_in_30 = [s for s in sids if s in common]
    common_in_47 = list(common)
    print(f"  Common SIDs: {len(common)}")

    sid_to_30 = {s: i for i, s in enumerate(sids)}
    sid_to_47_y = target["y_true_validrange"].to_dict()
    sid_to_47_p = target["y_pred"].to_dict()

    y_aligned = np.array([sid_to_47_y[s] for s in common_in_30])
    p_iter47_aligned = np.array([sid_to_47_p[s] for s in common_in_30])
    p_my_base = np.array([p_base_30[sid_to_30[s]] for s in common_in_30])
    p_my_aug = np.array([p_aug_30[sid_to_30[s]] for s in common_in_30])

    # Compute CCCs
    ccc_iter47 = ccc(y_aligned, p_iter47_aligned)
    ccc_my_base = ccc(y_aligned, p_my_base)
    ccc_my_aug = ccc(y_aligned, p_my_aug)
    print(f"  iter47 canonical (LGB-imp K-best, no stride) CCC: {ccc_iter47:.4f}")
    print(f"  my-arch base (univ-corr K-best, no stride) CCC: {ccc_my_base:.4f}")
    print(f"  my-arch aug (univ-corr K-best + stride) CCC: {ccc_my_aug:.4f}")

    delta_arch = ccc_my_base - ccc_iter47
    delta_stride = ccc_my_aug - ccc_my_base
    delta_combined = ccc_my_aug - ccc_iter47
    print(f"\n  Δ from arch (K-selector): {delta_arch:+.4f}")
    print(f"  Δ from stride (within my-arch): {delta_stride:+.4f}")
    print(f"  Δ COMBINED (my-arch+stride vs iter47): {delta_combined:+.4f}")

    # Paired bootstrap: my-arch+stride vs iter47
    rng = np.random.RandomState(42)
    n = len(y_aligned)
    n_boot = 10000
    deltas_combined = np.zeros(n_boot)
    deltas_arch = np.zeros(n_boot)
    deltas_stride = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas_combined[b] = ccc(y_aligned[idx], p_my_aug[idx]) - ccc(y_aligned[idx], p_iter47_aligned[idx])
        deltas_arch[b] = ccc(y_aligned[idx], p_my_base[idx]) - ccc(y_aligned[idx], p_iter47_aligned[idx])
        deltas_stride[b] = ccc(y_aligned[idx], p_my_aug[idx]) - ccc(y_aligned[idx], p_my_base[idx])

    print(f"\n  Paired bootstrap (10k iterations):")
    for name, deltas, mcid in [
        ("Δ_arch (K-selector)", deltas_arch, 0.025),
        ("Δ_stride (within my-arch)", deltas_stride, 0.025),
        ("Δ_combined (my-arch+stride vs iter47)", deltas_combined, 0.025),
    ]:
        ci_lo = np.percentile(deltas, 2.5)
        ci_hi = np.percentile(deltas, 97.5)
        frac_gt = (deltas > 0).mean()
        frac_above_mcid = (deltas >= mcid).mean()
        print(f"    {name}: mean={deltas.mean():+.4f}, "
              f"CI[{ci_lo:+.4f}, {ci_hi:+.4f}], frac>0={frac_gt:.4f}, frac≥MCID={frac_above_mcid:.4f}")

    # Sign-flip permutation
    se_iter47 = (y_aligned - p_iter47_aligned) ** 2
    se_my_aug = (y_aligned - p_my_aug) ** 2
    diffs = se_iter47 - se_my_aug  # positive if aug has lower error
    obs = diffs.mean()
    n_perm = 10000
    perm_stat = np.empty(n_perm)
    for i in range(n_perm):
        flips = rng.choice([-1.0, 1.0], size=n)
        perm_stat[i] = (diffs * flips).mean()
    sf_p = (perm_stat >= obs).mean()
    print(f"\n  Sign-flip permutation p-value (combined): {sf_p:.4f}")

    out = {
        "name": "combined_t3_lift_analysis",
        "n": int(n),
        "ccc_iter47_canonical": round(float(ccc_iter47), 4),
        "ccc_my_arch_base": round(float(ccc_my_base), 4),
        "ccc_my_arch_aug_stride": round(float(ccc_my_aug), 4),
        "delta_arch": round(float(delta_arch), 4),
        "delta_stride": round(float(delta_stride), 4),
        "delta_combined": round(float(delta_combined), 4),
        "bootstrap_combined": {
            "n_iter": 10000,
            "mean": round(float(deltas_combined.mean()), 4),
            "ci_low": round(float(np.percentile(deltas_combined, 2.5)), 4),
            "ci_high": round(float(np.percentile(deltas_combined, 97.5)), 4),
            "frac_gt_zero": round(float((deltas_combined > 0).mean()), 4),
            "frac_above_mcid": round(float((deltas_combined >= 0.025).mean()), 4),
        },
        "bootstrap_arch_only": {
            "mean": round(float(deltas_arch.mean()), 4),
            "ci_low": round(float(np.percentile(deltas_arch, 2.5)), 4),
            "ci_high": round(float(np.percentile(deltas_arch, 97.5)), 4),
            "frac_gt_zero": round(float((deltas_arch > 0).mean()), 4),
        },
        "bootstrap_stride_within_arch": {
            "mean": round(float(deltas_stride.mean()), 4),
            "ci_low": round(float(np.percentile(deltas_stride, 2.5)), 4),
            "ci_high": round(float(np.percentile(deltas_stride, 97.5)), 4),
            "frac_gt_zero": round(float((deltas_stride > 0).mean()), 4),
        },
        "sign_flip_p_combined": round(float(sf_p), 4),
        "bonferroni_n3_threshold_frac_gt": 0.9833,
        "combined_clears_bonferroni": bool((deltas_combined > 0).mean() >= 0.9833),
    }
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"combined_t3_lift_analysis_{ts}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\n  Wrote {out_path}")
    print(f"\n  Combined clears Bonferroni n=3 (frac>0 ≥ 0.9833): {out['combined_clears_bonferroni']}")


if __name__ == "__main__":
    main()
