"""T1 Slot D: Item-13-PH correction on conformal-retained subset.

Combines two CONFIRMED y-free deployable mechanisms:
  1. V2-vs-V3-GSP disagreement retention (canonical T1 conformal lockbox
     2026-05-12: 70% cov CCC=0.7777, 50% cov CCC=0.8338, formula_sha256=bd4858...)
  2. Item-13 PH biomechanical correction (D2-confirmed 2026-05-15, Δr=+0.161
     right vs Δr=-0.044 wrong)

Both are y-free at deployment time:
  - Retention score s(x) = |yhat_v2(x) - yhat_v3(x)|, no y_test
  - Correction c(x) = λ × Ridge_α(PH_features(x) → item_13_resid_trained_on_train_fold)
    fold-local, computed from features alone at test time

Lifts the DEPLOYABLE SECONDARY ceiling 0.7777/0.8338 if corrected retained CCC
strictly exceeds baseline retained CCC by MCID 0.025 with frac>0 above
Bonferroni gate.

Pre-reg gate: lifetime FWER family = 9 (yesterday 4 + Slot A + A2 + C + D)
Bonferroni: frac>0 ≥ 0.9944 vs baseline retained CCC for deployable-secondary
breakthrough.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

V2_OOF_PATH = "results/lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
V3_OOF_PATH = "results/lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy"
ITER34_OOF_NPZ = "results/t1_iter34_per_item_oof_20260511_044242.npz"
PH_CACHE = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
CONFORMAL_LOCKBOX = "results/lockbox_t1_conformal_20260512_211440.json"

COVERAGES = [0.70, 0.50]
ALPHA = 100.0  # matches yesterday's item-13 winner stack
LAMBDA_FIXED = 1.0  # yesterday's λ=1 gave frac>0=0.986 (closest to Bonferroni)
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 91011


def load_aligned_data():
    iter34 = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = iter34["sids"].astype(str)
    y_t1 = iter34["y_t1"].astype(float)
    yhat_iter34 = iter34["t1_sum_pred"].astype(float)
    item13_true = iter34["item_13_true"].astype(float)
    item13_pred = iter34["item_13_pred"].astype(float)
    n = len(sids)

    v2 = np.load(V2_OOF_PATH, allow_pickle=True).astype(float)
    v3 = np.load(V3_OOF_PATH, allow_pickle=True).astype(float)
    assert len(v2) == n and len(v3) == n

    # Conformal lockbox confirms ordering (predictor_v2_oof = iter34_hybrid, so v2 == yhat_iter34 up to seed averaging)
    print(f"[Slot D] v2 vs iter34 yhat: corr={np.corrcoef(v2, yhat_iter34)[0,1]:.4f}, mean diff={float((v2-yhat_iter34).mean()):.3f}")

    df = pd.read_csv(PH_CACHE)
    keep = df["sid"].isin(sids).values
    df = df[keep].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all()
    ph_cols = [c for c in df.columns if "_ph_" in c]
    X_ph = df[ph_cols].values.astype(float)

    return sids, y_t1, yhat_iter34, item13_true, item13_pred, v2, v3, X_ph, ph_cols


def loocv_ridge_correction(X: np.ndarray, item13_resid: np.ndarray) -> np.ndarray:
    n = len(item13_resid)
    correction = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        Xt_raw, Xv_raw = X[tr], X[i:i+1]
        yt = item13_resid[tr]
        imp = FoldImputer.fit(Xt_raw)
        Xt = imp.transform(Xt_raw)
        Xv = imp.transform(Xv_raw)
        nrm = FoldNormalizer.fit(Xt)
        Xt = nrm.transform(Xt)
        Xv = nrm.transform(Xv)
        m = Ridge(alpha=ALPHA).fit(Xt, yt)
        correction[i] = m.predict(Xv)[0]
    return correction


def retained_ccc_at_coverage(
    y: np.ndarray, yhat: np.ndarray, score: np.ndarray, coverage: float
) -> tuple[float, np.ndarray, int]:
    """Retain subjects with score below the coverage-quantile of score."""
    n = len(y)
    k = int(round(coverage * n))
    if k < 5:
        return float("nan"), np.zeros(n, dtype=bool), 0
    threshold = np.partition(score, k - 1)[k - 1]
    mask = score <= threshold
    if mask.sum() > k:
        # tie-break: keep first k by score order
        order = np.argsort(score, kind="stable")
        mask = np.zeros(n, dtype=bool)
        mask[order[:k]] = True
    return float(ccc(y[mask], yhat[mask])), mask, int(mask.sum())


def main(null_mode: str = ""):
    sids, y_t1, yhat_iter34, item13_true, item13_pred, v2, v3, X_ph, ph_cols = load_aligned_data()
    n = len(sids)
    print(f"[Slot D] N={n}, PH cols={len(ph_cols)}, null_mode={null_mode or 'none'}")
    print(f"[Slot D] Full-cohort iter34 CCC={float(ccc(y_t1, yhat_iter34)):.4f}")

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        # Scramble both y_t1 and item13_true (preserve correlation structure of features)
        perm = rng.permutation(n)
        y_t1 = y_t1[perm]
        item13_true = item13_true[perm]
        item13_pred = item13_pred[perm]
        yhat_iter34 = yhat_iter34[perm]  # iter34 was fit jointly with item13, so move together
        print(f"[Slot D NULL] permuted y, item13, iter34 preds together")

    # Item-13 PH correction (D2-confirmed biomechanical)
    item13_resid = item13_true - item13_pred
    correction = loocv_ridge_correction(X_ph, item13_resid)
    t1_corrected = yhat_iter34 + LAMBDA_FIXED * correction

    # Disagreement score (y-free deployable retention)
    score = np.abs(v2 - v3)

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    results_per_coverage = {}
    for cov in COVERAGES:
        baseline_ccc, mask, n_ret = retained_ccc_at_coverage(y_t1, yhat_iter34, score, cov)
        corrected_ccc = float(ccc(y_t1[mask], t1_corrected[mask]))
        delta = corrected_ccc - baseline_ccc
        baseline_mae = float(np.mean(np.abs(y_t1[mask] - yhat_iter34[mask])))
        corrected_mae = float(np.mean(np.abs(y_t1[mask] - t1_corrected[mask])))

        # Paired-bootstrap of delta on retained subset
        retained_idx = np.where(mask)[0]
        n_retained = len(retained_idx)
        deltas_boot = np.empty(N_BOOTSTRAP)
        for b in range(N_BOOTSTRAP):
            idx_resampled = rng.choice(retained_idx, size=n_retained, replace=True)
            d = float(ccc(y_t1[idx_resampled], t1_corrected[idx_resampled])
                      - ccc(y_t1[idx_resampled], yhat_iter34[idx_resampled]))
            deltas_boot[b] = d
        boot_ci = (float(np.percentile(deltas_boot, 2.5)),
                   float(np.percentile(deltas_boot, 97.5)))
        frac_pos = float((deltas_boot > 0).mean())

        results_per_coverage[f"cov_{int(cov*100)}"] = {
            "coverage": cov,
            "n_retained": n_ret,
            "baseline_iter34_retained_ccc": round(baseline_ccc, 4),
            "corrected_retained_ccc": round(corrected_ccc, 4),
            "delta_ccc": round(delta, 4),
            "baseline_iter34_retained_mae": round(baseline_mae, 4),
            "corrected_retained_mae": round(corrected_mae, 4),
            "delta_mae": round(corrected_mae - baseline_mae, 4),
            "bootstrap_median": round(float(np.median(deltas_boot)), 4),
            "bootstrap_ci95": [round(boot_ci[0], 4), round(boot_ci[1], 4)],
            "frac_positive": round(frac_pos, 4),
        }
        print(f"[Slot D] coverage={int(cov*100)}%, n_retained={n_ret}: "
              f"baseline_retained_CCC={baseline_ccc:.4f}, corrected_retained_CCC={corrected_ccc:.4f}, "
              f"Δ={delta:+.4f}, frac>0={frac_pos:.4f}")

    # Lifetime FWER n=9
    LIFETIME_FWER = 9
    bonf_gate = 1.0 - 0.05 / LIFETIME_FWER

    # Verdict: any coverage that lifts retained CCC by MCID with Bonferroni frac>0
    verdicts = {}
    for k, v in results_per_coverage.items():
        if v["frac_positive"] >= bonf_gate and v["delta_ccc"] >= 0.025:
            verdicts[k] = "PASS_LIFETIME_BONFERRONI_DEPLOYABLE_SECONDARY"
        elif v["frac_positive"] >= 0.95 and v["delta_ccc"] >= 0.025:
            verdicts[k] = "PASS_UNCORRECTED_FAILS_FWER"
        elif v["frac_positive"] >= 0.95:
            verdicts[k] = "PASS_UNCORRECTED_DELTA_BELOW_MCID"
        else:
            verdicts[k] = "FAIL"

    out = {
        "name": "lockbox_t1_slotDrep_conformal_ph_correction",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "session": "2026-05-15-PM-extended",
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_master.json",
        "null_mode": null_mode or "real",
        "estimand_label": "deployable_secondary_retained_ccc_at_coverage",
        "y_free_score": "abs(v2_oof - v3_gsp_oof)",
        "y_free_correction": f"Ridge alpha={ALPHA} on item-13 PH features, lambda={LAMBDA_FIXED} fixed",
        "n_full_cohort": n,
        "results_per_coverage": results_per_coverage,
        "verdicts_per_coverage": verdicts,
        "gates": {
            "lifetime_n9_bonferroni_gate": round(bonf_gate, 5),
            "mcid_delta_ccc": 0.025,
        },
        "deployable_secondary_baselines_from_conformal_lockbox_20260512": {
            "cov_70": 0.7777,
            "cov_50": 0.8338,
        },
    }
    ts = out["created_at_utc"]
    suffix = f"_{null_mode}" if null_mode else ""
    path = Path(f"results/lockbox_t1_slotDrep_conformal_ph_correction_{ts}{suffix}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[Slot D] Per-coverage verdicts: {verdicts}")
    print(f"[Slot D] Wrote {path}")


def sanity_y_nan():
    """Firewall law #9 contract: run retention with y_test=nan; verify identical decisions.

    The retention rule s(x) = |v2(x) - v3(x)| <= threshold is by construction y-free.
    This proves it operationally: replace y with nan, recompute retention masks,
    confirm masks are bit-identical to the real run.
    """
    sids, y_t1, yhat_iter34, item13_true, item13_pred, v2, v3, X_ph, ph_cols = load_aligned_data()
    n = len(sids)
    score = np.abs(v2 - v3)

    masks_real = {}
    masks_nan = {}
    y_nan = np.full(n, np.nan)
    for cov in COVERAGES:
        _, mask_real, _ = retained_ccc_at_coverage(y_t1, yhat_iter34, score, cov)
        _, mask_nan, _ = retained_ccc_at_coverage(y_nan, yhat_iter34, score, cov)
        masks_real[f"cov_{int(cov*100)}"] = mask_real.tolist()
        masks_nan[f"cov_{int(cov*100)}"] = mask_nan.tolist()

    all_match = all(masks_real[k] == masks_nan[k] for k in masks_real)
    receipt = {
        "name": "abstention_sanity_slotDrep_t1_slotD_conformal_ph_correction",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "lockbox_target": "lockbox_t1_slotD_conformal_ph_correction",
        "retention_rule_form": "g(x) = |v2(x) - v3(x)| <= quantile_threshold (y-free)",
        "correction_rule_form": f"c(x) = lambda * Ridge_alpha={ALPHA}(PH(x))_train_fold (y-free at deployment)",
        "n_subjects": n,
        "coverages": COVERAGES,
        "masks_identical_with_y_nan": all_match,
        "test_passes": all_match,
    }
    ts = receipt["created_at_utc"]
    path = Path(f"results/abstention_sanity_slotDrep_{ts}.json")
    path.write_text(json.dumps(receipt, indent=2))
    print(f"\n[Sanity y_nan] all_match={all_match}")
    print(f"[Sanity y_nan] Wrote {path}")
    return all_match


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sanity-y-nan":
        ok = sanity_y_nan()
        sys.exit(0 if ok else 1)
    null_mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        null_mode = sys.argv[1].split("=", 1)[1]
    main(null_mode=null_mode)
