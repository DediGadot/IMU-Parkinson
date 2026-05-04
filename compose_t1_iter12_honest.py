"""T1 iter12 — Honest composite, no cherry-pick.

Fix for the inflation findings of iter11A's composite (`compose_hybrid_v5_iter11.py`):
- HIGH: Multi-layer adaptive variant selection (v3/v4/v5 chain compares LOOCV CCCs
  across multiple iter11/interaction variants per item).
- HIGH: Item 10 swap rests on borderline null gate (scram=0.099, threshold 0.15).
- MEDIUM: Item 13 v4 swap pulled from `interaction_*_loocv_winners.oof.npy` which
  is a screen-script output, not a pre-registered lockbox.

This iter12_honest composite eliminates ALL three issues by using ONLY the
pre-registered iter8-batch lockboxes (timestamp 20260430_143044) for each of
items 9-14. No swaps, no LOOCV-based selection, no interaction screen pulls.
A single coherent pre-registration event covered all 15 items at that timestamp.

Headline = CCC(sum_OOFs, sum_y_items_9_14) on N=94 PD subjects.

Pre-registration is written BEFORE the composite is computed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir

ITER8_TS = "20260430_143044"
T1_ITEMS = [9, 10, 11, 12, 13, 14]

# The pre-registered iter8 winners per item (single batch).
ITER8_VARIANTS: dict[int, str] = {
    9: "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(RESULTS_DIR / "t1_iter12_honest_composite.json"))
    args = p.parse_args()
    ensure_dir(RESULTS_DIR)

    # ── Pre-registration (BEFORE composite) ─────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T1 iter12 — honest composite (no cherry-pick)",
        "rationale": (
            "iter11A's composite (CCC=0.7241) had ~+0.010 to +0.025 selection inflation per "
            "independent leakage review (multi-layer LOOCV-based variant swaps + borderline "
            "null gate on item 10's iter11 swap + non-pre-registered interaction screen used "
            "for item 13 v4 swap). iter12 uses ONLY the pre-registered iter8-batch lockboxes."
        ),
        "method": "Sum 6 per-item LOOCV OOF arrays from the 20260430_143044 batch; CCC vs sum-of-items-9-14.",
        "selections": {str(it): ITER8_VARIANTS[it] for it in T1_ITEMS},
        "source_files": {
            str(it): f"lockbox_peritem_{it}_{ITER8_VARIANTS[it]}_{ITER8_TS}.oof.npy"
            for it in T1_ITEMS
        },
        "pre_reg_files": {
            str(it): f"preregistration_peritem_{it}_{ITER8_TS}.json" for it in T1_ITEMS
        },
        "n_subjects": 94,
        "eval_protocol": (
            "Single-shot composite computation. No swaps, no LOOCV-based variant comparison, "
            "no interaction screen, no iter11 self-norm-cross. The 6 per-item lockboxes were "
            "pre-registered together as one coherent event (timestamp 20260430_143044)."
        ),
        "headline_metric": "CCC(sum_per_item_OOFs, sum_per_item_true) over N=94",
        "comparator_iter11A_ccc_inflated": 0.7241,
        "lockbox_rules": [
            "ONE composite pre-registered. ONE evaluation. Headline = result, no cherry-picking.",
            "No variant comparison; iter8 batch winners are fixed.",
            "If composite CCC < iter11A by more than +0.025, that confirms the upper bound of the inflation estimate.",
        ],
    }
    prereg_path = RESULTS_DIR / f"preregistration_t1_iter12_honest_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    # ── Load per-item OOFs + true scores via canonical SID order ──────────────
    from run_per_item_v2 import load_data as load_peritem_data

    print("\nLoading per-item canonical data (SID order from V2_FEATURES PD filter)...", flush=True)
    d = load_peritem_data()
    sids = d["sids"]
    n = len(sids)
    print(f"  N = {n} PD subjects", flush=True)

    # Verify all 6 OOF files exist with shape (94,) — fail fast if not
    print("\nLoading 6 pre-registered iter8-batch OOFs:", flush=True)
    oofs: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        variant = ITER8_VARIANTS[it]
        path = RESULTS_DIR / f"lockbox_peritem_{it}_{variant}_{ITER8_TS}.oof.npy"
        if not path.exists():
            raise FileNotFoundError(f"Missing pre-registered OOF: {path}")
        arr = np.load(path)
        if arr.shape != (n,):
            raise ValueError(f"Item {it} OOF shape {arr.shape} != expected ({n},)")
        oofs[it] = arr
        # Spot-check per-item CCC vs target
        y_item = np.asarray(d["items"][it], dtype=float)
        valid = ~np.isnan(y_item)
        per_ccc = float(ccc_fn(y_item[valid], arr[valid]))
        print(f"  Item {it} ({variant}): per-item LOOCV CCC = {per_ccc:+.4f}", flush=True)

    # Sum to T1
    t1_pred = np.sum(np.column_stack([oofs[it] for it in T1_ITEMS]), axis=1)
    t1_true = d["t1"]  # sum of items 9-14, already aligned

    # NaN-safe: drop subjects with any NaN in target
    valid = ~np.isnan(t1_true)
    n_valid = int(valid.sum())
    print(
        f"\nComposite: N_valid = {n_valid}/{n} subjects with valid summed T1",
        flush=True,
    )

    # Headline metrics
    headline = full_metrics(t1_true[valid], t1_pred[valid], label="t1_iter12_honest")

    # Bootstrap CI of headline CCC (paired self-bootstrap; not vs iter11A)
    rng = np.random.RandomState(42)
    n_boot = 2000
    boot_ccc = []
    yt = t1_true[valid]
    yp = t1_pred[valid]
    for _ in range(n_boot):
        idx = rng.randint(0, len(yt), size=len(yt))
        boot_ccc.append(ccc_fn(yt[idx], yp[idx]))
    boot_ccc = np.array(boot_ccc)
    bootstrap_summary = {
        "n_boot": n_boot,
        "ccc_mean": round(float(boot_ccc.mean()), 4),
        "ccc_ci_low": round(float(np.percentile(boot_ccc, 2.5)), 4),
        "ccc_ci_high": round(float(np.percentile(boot_ccc, 97.5)), 4),
    }

    headline.update(
        {
            "iteration": "iter12_honest",
            "selections": {str(it): ITER8_VARIANTS[it] for it in T1_ITEMS},
            "n_subjects_valid": n_valid,
            "preregistration_file": prereg_path.name,
            "is_lockbox_headline": True,
            "comparator_iter11A_inflated_ccc": 0.7241,
            "delta_vs_iter11A_inflated": round(float(headline["ccc"]) - 0.7241, 4),
            "bootstrap_ccc": bootstrap_summary,
            "per_subject": {
                "sids": [str(s) for s in sids[valid]],
                "y_true": t1_true[valid].tolist(),
                "y_pred": t1_pred[valid].tolist(),
            },
        }
    )

    out_path = Path(args.out)
    with open(out_path, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    out_npy = out_path.with_suffix("").as_posix() + ".oof.npy"
    np.save(out_npy, t1_pred[valid])

    print(f"\n=== HEADLINE (T1 iter12 honest, no cherry-pick): ===", flush=True)
    print(
        f"  CCC = {headline['ccc']:.4f}  MAE = {headline['mae']:.3f}  "
        f"r = {headline['r']:.4f}  slope = {headline['cal_slope']:.3f}",
        flush=True,
    )
    print(
        f"  Bootstrap (n={n_boot}): CCC mean = {bootstrap_summary['ccc_mean']}, "
        f"95% CI = [{bootstrap_summary['ccc_ci_low']}, {bootstrap_summary['ccc_ci_high']}]",
        flush=True,
    )
    print(
        f"  Δ vs iter11A inflated 0.7241: {headline['delta_vs_iter11A_inflated']:+.4f} "
        f"(reviewer estimated −0.010 to −0.025 inflation correction)",
        flush=True,
    )
    print(f"\nWrote {out_path}", flush=True)
    print(f"Wrote {out_npy}", flush=True)


if __name__ == "__main__":
    main()
