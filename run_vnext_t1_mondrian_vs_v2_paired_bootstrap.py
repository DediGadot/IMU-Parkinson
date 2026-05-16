"""Paired-bootstrap: T1 Mondrian-CP candidate vs V2-only conformal lockbox.

Pre-reg (locked BEFORE this script's first execution, see formula_sha256 below):
  Predictor (Mondrian-CP candidate):
    - point prediction: iter34 hybrid 8-item × 3-base T1 sum (CCC=0.7170, N=92)
    - bins: outer-train-only LOO quartiles of the predicted T1 sum
    - score: |y_T1 - ŷ_T1|
    - calibration: per-bin LOO quantile of |residual|
  Comparator (V2-only conformal lockbox, 2026-05-12):
    - point prediction: V2-only LOOCV predictor
    - score: |p_v2 - p_v3| disagreement
    - calibration: LOO quantile of disagreement
    - both from results/lockbox_t1_conformal_20260512_211440.json
  Bootstrap protocol:
    - B = 5000 paired resamples of the FULL N=92 cohort
    - For each resample b: compute retained-CCC at coverage τ ∈ {1.0, 0.85, 0.7, 0.5}
      for BOTH methods on the resample
    - Δ_τ(b) = CCC_Mondrian(b) - CCC_V2only(b)
    - frac>0 = fraction of bootstraps with Δ > 0
  Gate: frac>0 ≥ 0.95 (uncorrected, n=1 family — this is a single planned
       comparison versus the prior lockbox)
  Decision rule:
    - if frac>0 ≥ 0.95 at coverage 70%: T1 Mondrian-CP is the candidate
      supersession of V2-only conformal
    - else: keep V2-only as the canonical T1 conformal lockbox
  Cohort note:
    - V2-only lock used N=92 (iter34 cohort).
    - T1 Mondrian-CP uses N=92 (same cohort, iter34 OOF).
    - Sids should match. If they don't, restrict to common subjects.

Output: results/lockbox_vnext_t1_mondrian_vs_v2_paired_bootstrap_<TS>.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc

RESULTS_DIR = REPO_ROOT / "results"
ITER34_PER_ITEM_OOF = RESULTS_DIR / "t1_iter34_per_item_oof_20260511_044242.npz"
T1_V2_LOCKBOX = RESULTS_DIR / "lockbox_t1_conformal_20260512_211440.json"
ITER34_V2_OOF = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"

COVERAGES = (1.0, 0.85, 0.70, 0.50)
N_BOOT = 5000
SEED = 42
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha_of(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def predicted_bins(pred):
    n = len(pred)
    bins = np.zeros(n, dtype=int)
    for i in range(n):
        mask = np.arange(n) != i
        q = np.quantile(pred[mask], [0.25, 0.5, 0.75])
        bins[i] = int(np.searchsorted(q, pred[i]))
    return bins


def retained_mondrian(y, pred, bins, coverages):
    """Return dict {cov: (retained_mask, ccc, mae)} for Mondrian-CP recipe."""
    abs_res = np.abs(y - pred)
    n = len(y)
    out = {}
    for cov in coverages:
        retain = np.zeros(n, dtype=bool)
        for i in range(n):
            mask = (bins == bins[i]) & (np.arange(n) != i)
            if mask.sum() < 4:
                mask = np.arange(n) != i
            thr = float(np.quantile(abs_res[mask], cov))
            retain[i] = abs_res[i] <= thr
        out[cov] = retain
    return out


def retained_v2_disagreement(pred_v2, pred_v3, coverages):
    """V2-only lockbox: retention via leave-one-out quantile of |p_v2-p_v3|."""
    disagreement = np.abs(pred_v2 - pred_v3)
    n = len(pred_v2)
    out = {}
    for cov in coverages:
        retain = np.zeros(n, dtype=bool)
        for i in range(n):
            mask = np.arange(n) != i
            thr = float(np.quantile(disagreement[mask], cov))
            retain[i] = disagreement[i] <= thr
        out[cov] = retain
    return out


def _ccc_on_retain(y, p, retain):
    if retain.sum() < 5:
        return np.nan
    yt, yp = y[retain], p[retain]
    return float(ccc(yt, yp))


def main() -> int:
    # ── Load data ──
    npz = np.load(ITER34_PER_ITEM_OOF)
    sids = np.array([str(s) for s in npz["sids"]])
    y_t1 = npz["y_t1"]
    pred_iter34 = npz["t1_sum_pred"]
    n = len(y_t1)
    print(f"[paired-boot] N_iter34 = {n}")

    # V2-only conformal lockbox: load V2 LOOCV OOF + V3 OOF
    v2_lockbox = json.loads(T1_V2_LOCKBOX.read_text())
    v2_oof = np.load(ITER34_V2_OOF)
    # iter34_hybrid is the V2 used in the lockbox - load it
    # V3 OOF path from the lockbox prereg
    prereg_v2 = RESULTS_DIR / "preregistration_goalv2_t1_conformal_lockbox_20260512.json"
    v2_pr = json.loads(prereg_v2.read_text())
    v3_oof_path = REPO_ROOT / v2_pr["predictor_v3_oof"].replace(str(REPO_ROOT) + "/", "")
    if not v3_oof_path.exists():
        v3_oof_path = RESULTS_DIR / "lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy"
    pred_v2 = np.load(ITER34_V2_OOF)  # iter34 V2 OOF (same as iter34_hybrid for now)
    pred_v3 = np.load(v3_oof_path) if v3_oof_path.exists() else None
    print(f"[paired-boot] V2 OOF len = {len(pred_v2)}")
    if pred_v3 is None:
        print(f"[paired-boot] WARNING: V3 OOF not found at {v3_oof_path}; will skip V2-only conformal arm")
    else:
        print(f"[paired-boot] V3 OOF len = {len(pred_v3)}")

    # The V2-only conformal lockbox uses the SAME iter34 cohort (N=92), per the
    # lockbox JSON. Confirm:
    assert len(pred_v2) == n == 92, f"Cohort mismatch: pred_v2 {len(pred_v2)} vs y_t1 {n}"

    # Lock the pre-registration formula
    formula = {
        "predictor_mondrian": "iter34_hybrid_T1_sum",
        "score_mondrian": "abs_residual_y_minus_iter34",
        "bins_mondrian": "outer_train_only_LOO_quartile_of_predicted_T1",
        "predictor_v2only": "iter34_hybrid_T1_sum (point_pred)",
        "score_v2only": "abs_p_v2_minus_p_v3_disagreement",
        "bootstrap_n": N_BOOT,
        "coverages": list(COVERAGES),
        "seed": SEED,
    }
    fsha = _sha_of(formula)
    print(f"[paired-boot] formula_sha256={fsha[:16]}...")

    # ── Real retained metrics ──
    bins_mond = predicted_bins(pred_iter34)
    retain_mond = retained_mondrian(y_t1, pred_iter34, bins_mond, COVERAGES)
    if pred_v3 is not None:
        retain_v2 = retained_v2_disagreement(pred_v2, pred_v3, COVERAGES)
    else:
        retain_v2 = None

    real_table = []
    for cov in COVERAGES:
        ccc_mond = _ccc_on_retain(y_t1, pred_iter34, retain_mond[cov])
        ccc_v2 = (_ccc_on_retain(y_t1, pred_v2, retain_v2[cov])
                  if retain_v2 is not None else np.nan)
        real_table.append({
            "coverage": float(cov),
            "n_retained_mond": int(retain_mond[cov].sum()),
            "ccc_mond": ccc_mond,
            "n_retained_v2": (int(retain_v2[cov].sum())
                              if retain_v2 is not None else None),
            "ccc_v2": ccc_v2,
            "delta_mond_minus_v2": (ccc_mond - ccc_v2)
                                    if retain_v2 is not None else None,
        })
        print(f"  cov={cov:.2f}  Mond_CCC={ccc_mond:.4f}  V2_CCC={ccc_v2}  "
              f"Δ={(ccc_mond-ccc_v2) if retain_v2 else 'NA'}")

    # ── Bootstrap ──
    if retain_v2 is None:
        print("[paired-boot] no V2 baseline; skipping bootstrap")
        boot_rows = None
    else:
        rng = np.random.default_rng(SEED)
        boot_deltas = {cov: [] for cov in COVERAGES}
        for b in range(N_BOOT):
            idx = rng.integers(0, n, size=n)
            yt_b = y_t1[idx]
            pred_iter34_b = pred_iter34[idx]
            pred_v2_b = pred_v2[idx]
            pred_v3_b = pred_v3[idx]
            # Recompute bins ON the bootstrap (since LOO quartile changes with cohort)
            bins_b = predicted_bins(pred_iter34_b)
            retain_mond_b = retained_mondrian(yt_b, pred_iter34_b, bins_b, COVERAGES)
            retain_v2_b = retained_v2_disagreement(pred_v2_b, pred_v3_b, COVERAGES)
            for cov in COVERAGES:
                cm = _ccc_on_retain(yt_b, pred_iter34_b, retain_mond_b[cov])
                cv = _ccc_on_retain(yt_b, pred_v2_b, retain_v2_b[cov])
                if not (np.isnan(cm) or np.isnan(cv)):
                    boot_deltas[cov].append(cm - cv)
            if (b + 1) % 500 == 0:
                print(f"  bootstrap {b+1}/{N_BOOT}", flush=True)
        boot_rows = []
        for cov in COVERAGES:
            deltas = np.array(boot_deltas[cov])
            if len(deltas) < 100:
                boot_rows.append({"coverage": cov, "n_valid": len(deltas),
                                  "verdict": "INSUFFICIENT"})
                continue
            boot_rows.append({
                "coverage": float(cov),
                "n_valid": int(len(deltas)),
                "delta_mean": float(np.mean(deltas)),
                "delta_median": float(np.median(deltas)),
                "delta_ci_low": float(np.quantile(deltas, 0.025)),
                "delta_ci_high": float(np.quantile(deltas, 0.975)),
                "frac_pos": float((deltas > 0).mean()),
                "frac_ge_mcid": float((deltas >= 0.025).mean()),
                "gate_pass_uncorrected_0_95": bool((deltas > 0).mean() >= 0.95),
            })
            print(f"  cov={cov:.2f} Δ̄={np.mean(deltas):+.4f} "
                  f"CI=[{np.quantile(deltas,0.025):+.4f}, {np.quantile(deltas,0.975):+.4f}] "
                  f"frac>0={float((deltas>0).mean()):.4f}")

    out = {
        "name": "vnext_t1_mondrian_vs_v2_paired_bootstrap",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "ts": TS,
        "formula": formula,
        "formula_sha256": fsha,
        "n_subjects": n,
        "real_table": real_table,
        "bootstrap_rows": boot_rows,
        "n_bootstrap": N_BOOT,
        "seed": SEED,
        "verdict": (
            "T1_MONDRIAN_SUPERSEDES_V2_ONLY"
            if boot_rows and any(
                r.get("gate_pass_uncorrected_0_95", False) and abs(r["coverage"] - 0.7) < 1e-3
                for r in boot_rows
            )
            else "NO_SUPERSESSION_YET"
        ),
    }
    path = RESULTS_DIR / f"lockbox_vnext_t1_mondrian_vs_v2_paired_bootstrap_{TS}.json"
    path.write_text(json.dumps(out, indent=2,
                                default=lambda o: o.tolist() if hasattr(o, "tolist") else o))
    print(f"[paired-boot] wrote {path.name}; verdict={out['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
