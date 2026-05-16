"""T3 conformal abstention LOCKBOX (deployment-mode secondary, parallel to T1).

Pre-registered design (post tri-CLI consensus, 2026-05-12):
  Same LOO-quantile split-conformal architecture as T1 lockbox, applied to
  iter47 (clinical+IMU, CCC=0.3784) vs IMU-only (CCC=0.3102) predictor pair.
  This is the orthogonal pair needed for meaningful disagreement; the
  stage2_current vs stage2_no_cv pair was rejected (predictors too correlated,
  monotonicity violated at 50% coverage).

Inputs:
  Predictor 1: iter47 stage2_current (clinical+IMU)
               results/iter47_invalidcode_subject_preds_20260508_194605.csv
               (cohort=drop_allmissing_validrange, N=95, CCC=0.3784).
  Predictor 2: IMU-only T3 LGB (no clinical)
               results/lockbox_t3_imu_only_20260512_211900.oof.npy
               (N=95, CCC=0.3102).

Disagreement: |p_iter47 - p_imu_only|.

LOO-quantile threshold per subject; same coverage targets {100, 90, ..., 50}.

Kill criteria:
  - Monotonicity violated (50% coverage CCC < 70% coverage CCC).
  - Threshold CV > 0.20 at any coverage.
  - r(disagreement, |error|) < 0.10 (mechanism weak).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc

ITER47_CSV = REPO_ROOT / "results" / "iter47_invalidcode_subject_preds_20260508_194605.csv"
IMU_ONLY_LOCKBOX = REPO_ROOT / "results" / "lockbox_t3_imu_only_20260512_211900.json"
IMU_ONLY_OOF = REPO_ROOT / "results" / "lockbox_t3_imu_only_20260512_211900.oof.npy"

COVERAGE_TARGETS = (1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50)
SEEDS = (42, 1337, 7)
N_BOOT = 5000
PREDICTOR_VARIANTS = ("iter47_only", "blend_50_50_iter47_imu")


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def _load_iter47():
    df = pd.read_csv(ITER47_CSV)
    target = df[(df["cohort"] == "drop_allmissing_validrange") &
                (df["stage2_policy"] == "stage2_current")]
    return target.set_index("sid")


def _load_imu_only():
    j = json.loads(IMU_ONLY_LOCKBOX.read_text())
    sids = j["per_subject"]["sids"]
    y_true = np.array(j["per_subject"]["y_true"])
    p = np.array(j["per_subject"]["y_pred"])
    return pd.DataFrame({"sid": sids, "y_true": y_true, "y_pred_imu": p}).set_index("sid")


def main():
    print("=" * 72)
    print("T3 CONFORMAL LOCKBOX — clinical+IMU vs IMU-only disagreement")
    print("=" * 72)

    iter47 = _load_iter47()
    imu = _load_imu_only()
    common = iter47.index.intersection(imu.index)
    print(f"  Common SIDs: {len(common)}")

    y_true = iter47.loc[common, "y_true_validrange"].to_numpy()
    p_iter47 = iter47.loc[common, "y_pred"].to_numpy()
    p_imu = imu.loc[common, "y_pred_imu"].to_numpy()
    p_blend = 0.5 * (p_iter47 + p_imu)

    print(f"  iter47 CCC = {ccc(y_true, p_iter47):.4f}")
    print(f"  IMU-only CCC = {ccc(y_true, p_imu):.4f}")
    print(f"  50/50 blend CCC = {ccc(y_true, p_blend):.4f}")

    disagreement = np.abs(p_iter47 - p_imu)
    print(f"  disagreement mean={disagreement.mean():.3f} std={disagreement.std():.3f} max={disagreement.max():.3f}")

    abs_err_iter47 = np.abs(y_true - p_iter47)
    abs_err_blend = np.abs(y_true - p_blend)
    r_d_iter47 = float(np.corrcoef(disagreement, abs_err_iter47)[0, 1])
    r_d_blend = float(np.corrcoef(disagreement, abs_err_blend)[0, 1])
    print(f"  r(disagreement, |error_iter47|) = {r_d_iter47:.3f}")
    print(f"  r(disagreement, |error_blend|) = {r_d_blend:.3f}")

    formula_sha = hashlib.sha256(
        json.dumps(
            {
                "coverage_targets": list(COVERAGE_TARGETS),
                "seeds": list(SEEDS),
                "design": "loo_quantile",
                "iter47_csv_sha": hashlib.sha256(ITER47_CSV.read_bytes()).hexdigest()[:16],
                "imu_only_oof_sha": hashlib.sha256(IMU_ONLY_OOF.read_bytes()).hexdigest()[:16],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    prereg = {
        "name": "t3_conformal_lockbox",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": "64edc2a90ab11beed8b0bdb30a69c6c49a8809fc",
        "status": "locked",
        "master_prereg": "results/preregistration_goalv2_master_20260512.json",
        "design": "split_conformal_leave_one_out_quantile",
        "predictor_1_iter47": str(ITER47_CSV),
        "predictor_2_imu_only": str(IMU_ONLY_OOF),
        "disagreement_score": "absolute_difference_p_iter47_p_imu",
        "coverage_targets": list(COVERAGE_TARGETS),
        "seeds_for_bootstrap_rng": list(SEEDS),
        "predictor_variants": list(PREDICTOR_VARIANTS),
        "n_bootstrap": N_BOOT,
        "estimand": "retained_subset_ccc_per_coverage",
        "kill_criteria": [
            "Monotonicity violated: CCC at 50% < CCC at 70%",
            "LOO threshold variance > 20% of mean threshold at any coverage",
            "Disagreement-error correlation r < 0.10",
        ],
        "out_of_fwer_family": True,
        "rationale": "Different estimand (retained-subset CCC at coverage). Deployment-mode publication parallel to T1 conformal lockbox.",
        "formula_sha256": formula_sha,
    }
    prereg_path = REPO_ROOT / "results" / "preregistration_goalv2_t3_conformal_lockbox_20260512.json"
    prereg_path.write_text(json.dumps(prereg, indent=2))
    print(f"\n  Pre-reg written: {prereg_path}")

    n = len(y_true)
    abstention_table = {}
    for variant in PREDICTOR_VARIANTS:
        p_eval = p_iter47 if variant == "iter47_only" else p_blend
        rows = []
        for tau in COVERAGE_TARGETS:
            retained_mask = np.zeros(n, dtype=bool)
            thresholds = np.zeros(n)
            for i in range(n):
                calib_mask = np.ones(n, dtype=bool)
                calib_mask[i] = False
                calib_d = disagreement[calib_mask]
                thresholds[i] = np.quantile(calib_d, tau)
                retained_mask[i] = disagreement[i] <= thresholds[i]
            retained_n = int(retained_mask.sum())
            thr_mean = float(thresholds.mean())
            thr_std = float(thresholds.std())
            thr_cv = thr_std / max(thr_mean, 1e-9)

            y_ret = y_true[retained_mask]
            p_ret = p_eval[retained_mask]
            if retained_n >= 3 and y_ret.std() > 1e-6:
                ret_ccc = float(ccc(y_ret, p_ret))
                ret_mae = mae(y_ret, p_ret)
            else:
                ret_ccc = float("nan")
                ret_mae = float("nan")

            rng = np.random.RandomState(SEEDS[0])
            boot_ccc = np.zeros(N_BOOT)
            for b in range(N_BOOT):
                idx = rng.randint(0, n, n)
                d_b = disagreement[idx]
                p_b = p_eval[idx]
                y_b = y_true[idx]
                thr_b = np.quantile(d_b, tau)
                m_b = d_b <= thr_b
                if m_b.sum() >= 3 and y_b[m_b].std() > 1e-6:
                    boot_ccc[b] = ccc(y_b[m_b], p_b[m_b])
                else:
                    boot_ccc[b] = float("nan")
            valid = ~np.isnan(boot_ccc)
            ci_lo = float(np.nanpercentile(boot_ccc[valid], 2.5)) if valid.sum() else float("nan")
            ci_hi = float(np.nanpercentile(boot_ccc[valid], 97.5)) if valid.sum() else float("nan")

            rows.append({
                "coverage_target": tau,
                "retained_n": retained_n,
                "retained_ccc": round(ret_ccc, 4),
                "retained_mae": round(ret_mae, 4),
                "retained_ccc_ci_low": round(ci_lo, 4),
                "retained_ccc_ci_high": round(ci_hi, 4),
                "threshold_mean": round(thr_mean, 4),
                "threshold_std": round(thr_std, 4),
                "threshold_cv": round(thr_cv, 4),
                "kill_threshold_cv_violated": thr_cv > 0.20,
            })
        abstention_table[variant] = rows

    def _monotonicity(rows):
        cccs = [r["retained_ccc"] for r in rows]
        covs = [r["coverage_target"] for r in rows]
        sorted_pairs = sorted(zip(covs, cccs), reverse=True)
        cccs_sorted = [c for _, c in sorted_pairs]
        violations = sum(
            1 for i in range(len(cccs_sorted) - 1)
            if cccs_sorted[i + 1] < cccs_sorted[i] - 0.005
        )
        return {
            "n_violations": violations,
            "ccc_at_full": cccs_sorted[0],
            "ccc_at_min": cccs_sorted[-1],
            "cccs_sorted_by_coverage_desc": cccs_sorted,
        }

    monot = {v: _monotonicity(abstention_table[v]) for v in PREDICTOR_VARIANTS}

    kill_any = any(r["kill_threshold_cv_violated"] for v in abstention_table.values() for r in v)
    mono_violated = any(m["n_violations"] > 0 for m in monot.values())
    weak_r = abs(r_d_iter47) < 0.10 and abs(r_d_blend) < 0.10

    if kill_any:
        verdict = "FAIL_KILL_CRITERIA_THRESHOLD_INSTABILITY"
    elif weak_r:
        verdict = "FAIL_WEAK_DISAGREEMENT_ERROR_CORRELATION"
    elif mono_violated:
        verdict = "PARTIAL_PASS_MONOTONICITY_VIOLATIONS"
    else:
        verdict = "PASS_DEPLOYABLE_SECONDARY"

    summary = {
        "name": "t3_conformal_lockbox",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "preregistration": str(prereg_path),
        "n": int(n),
        "iter47_full_ccc": round(float(ccc(y_true, p_iter47)), 4),
        "imu_only_full_ccc": round(float(ccc(y_true, p_imu)), 4),
        "blend_full_ccc": round(float(ccc(y_true, p_blend)), 4),
        "disagreement_mean": round(float(disagreement.mean()), 4),
        "disagreement_std": round(float(disagreement.std()), 4),
        "r_disagreement_abs_err_iter47": round(r_d_iter47, 4),
        "r_disagreement_abs_err_blend": round(r_d_blend, 4),
        "abstention_table_by_predictor": abstention_table,
        "monotonicity": monot,
        "kill_violated_any_coverage": kill_any,
        "weak_r": weak_r,
        "verdict": verdict,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_conformal_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  === RESULTS ===")
    for variant in PREDICTOR_VARIANTS:
        print(f"\n  Variant: {variant}")
        print(f"  {'coverage':>10} {'retained_N':>11} {'CCC':>8} {'MAE':>8} {'CI_low':>8} {'CI_high':>8} {'thr_CV':>8}")
        for r in abstention_table[variant]:
            print(f"  {r['coverage_target']:>10.2f} {r['retained_n']:>11d} "
                  f"{r['retained_ccc']:>8.4f} {r['retained_mae']:>8.4f} "
                  f"{r['retained_ccc_ci_low']:>8.4f} {r['retained_ccc_ci_high']:>8.4f} "
                  f"{r['threshold_cv']:>8.4f}")
    print(f"\n  Verdict: {verdict}")
    print(f"  Wrote: {out_path}")


if __name__ == "__main__":
    main()
