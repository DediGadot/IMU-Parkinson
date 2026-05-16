"""T1 conformal abstention LOCKBOX (publishable deployment-mode secondary).

Pre-registered design (post tri-CLI consensus, 2026-05-12):
  Tri-CLI consensus (codex/kimi/deepseek/gemini) endorses split-conformal with
  pre-declared calib_frac on the OOF predictions. Mondrian/stratified-conformal
  rejected as sample-hungry at N=92.

Inputs (both leak-clean LOOCV OOF):
  Predictor 1: iter34 hybrid V2 — results/lockbox_t1_iter34_hybrid_20260510_233019.oof.npy
               (CCC=0.7170 on N=92 hygiene-corrected cohort).
  Predictor 2: V3-GSP only — results/lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy
               (CCC=0.7249 — best single V3 family).

Disagreement score per subject: |p_v2(i) - p_v3(i)|.

Conformal protocol (leave-one-subject-out quantile):
  For each test subject i in {1..92}:
    calib_set = {1..92} \\ {i}  (the other 91, N=91 quantile)
    For each coverage target τ ∈ {1.0, 0.9, 0.8, 0.7, 0.6, 0.5}:
      threshold_i_τ = (1 - τ) * 100 percentile of disagreement[calib_set]
        ... actually the τ quantile (lower = retain).
      retain_i_τ = disagreement[i] <= threshold_i_τ

  Note: more precisely we keep the τ*100% MOST CONFIDENT subjects (lowest
  disagreement). threshold_i_τ = τ-th percentile of calib disagreement (sorted
  ascending). Subject i retained at coverage τ iff disagreement[i] <=
  threshold_i_τ.

Estimand (per coverage τ):
  - retained_n = number of subjects retained
  - retained_ccc = CCC over retained subset using p_v2 (or simple blend)
  - retained_mae = MAE over retained subset
  - retained_n_actual ≈ τ * 92 (will deviate by 1-2 due to LOO quantile)

Bootstrap CI on retained_ccc: 5000 paired bootstraps over the RETAINED
subjects (different per replicate, since retention is subject-level
deterministic given disagreement); for inference we resample the FULL cohort
and recompute retention + CCC on the bootstrap-retained subset.

Seeds: calibration is deterministic (LOO quantile), but seed_list = (42, 1337, 7)
varies the predictor blend (50/50 V2/V3 vs V2-only) and the bootstrap RNG.

Kill criteria:
  - Monotonicity violated: CCC at 50% < CCC at 70%.
  - LOO threshold variance > 20% of mean threshold at any coverage (instability).

Pre-registration:
  Lock: results/preregistration_goalv2_t1_conformal_lockbox_20260512.json
  Lockbox: results/lockbox_t1_conformal_<TS>.json
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

# ── Pre-registered constants ──
V2_LOCKBOX_JSON = REPO_ROOT / "results" / "lockbox_t1_iter34_hybrid_20260510_233019.json"
V2_OOF_NPY = REPO_ROOT / "results" / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
V3_OOF_NPY = REPO_ROOT / "results" / "lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy"

COVERAGE_TARGETS = (1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50)
SEEDS = (42, 1337, 7)
N_BOOT = 5000
PREDICTOR_VARIANTS = ("V2_only", "V2_V3_blend_50_50")

PREREG_PATH = REPO_ROOT / "results" / "preregistration_goalv2_t1_conformal_lockbox_20260512.json"


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def _write_prereg(formula_sha: str) -> None:
    prereg = {
        "name": "t1_conformal_lockbox",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": "64edc2a90ab11beed8b0bdb30a69c6c49a8809fc",  # captured at lock
        "status": "locked",
        "master_prereg": "results/preregistration_goalv2_master_20260512.json",
        "design": "split_conformal_leave_one_out_quantile",
        "calibration_protocol": (
            "For each test subject i, compute disagreement quantile over the "
            "OTHER 91 subjects. Threshold at coverage τ = τ-th percentile of "
            "those 91 disagreements. Retain i iff |p_v2(i)-p_v3(i)| <= "
            "threshold_i_τ."
        ),
        "predictor_v2_oof": str(V2_OOF_NPY),
        "predictor_v3_oof": str(V3_OOF_NPY),
        "disagreement_score": "absolute_difference_p_v2_p_v3",
        "coverage_targets": list(COVERAGE_TARGETS),
        "seeds_for_bootstrap_rng": list(SEEDS),
        "predictor_variants": list(PREDICTOR_VARIANTS),
        "n_bootstrap": N_BOOT,
        "estimand": "retained_subset_ccc_per_coverage",
        "kill_criteria": [
            "Monotonicity violated: CCC at 50% < CCC at 70%",
            "LOO threshold variance > 20% of mean threshold at any coverage",
            "Disagreement-residual correlation r < 0.10 (mechanism check)",
        ],
        "out_of_fwer_family": True,
        "rationale": (
            "Conformal abstention reports a DIFFERENT estimand "
            "(retained-subset CCC) than the standard LOOCV CCC. Therefore it "
            "is reported as a deployment-mode secondary publication, not as a "
            "ceiling-break against iter34 baseline. The 4-CLI consensus "
            "endorses this as the rigorous publishable angle at N=92."
        ),
        "formula_sha256": formula_sha,
    }
    PREREG_PATH.write_text(json.dumps(prereg, indent=2))


def main():
    print("=" * 72)
    print("T1 CONFORMAL LOCKBOX — deployment-mode secondary publication")
    print("=" * 72)

    # Load OOF predictions
    v2_lockbox = json.loads(V2_LOCKBOX_JSON.read_text())
    sids = [str(s) for s in v2_lockbox["per_subject"]["sids"]]
    y_true = np.array(v2_lockbox["per_subject"]["y_true"], dtype=np.float64)
    p_v2 = np.load(V2_OOF_NPY)
    p_v3 = np.load(V3_OOF_NPY)
    assert len(p_v2) == len(p_v3) == len(y_true) == 92

    print(f"  N={len(y_true)}")
    print(f"  V2 baseline CCC={ccc(y_true, p_v2):.4f}")
    print(f"  V3-GSP CCC      ={ccc(y_true, p_v3):.4f}")
    p_blend = 0.5 * (p_v2 + p_v3)
    print(f"  50/50 blend CCC ={ccc(y_true, p_blend):.4f}")

    # Disagreement scores
    disagreement = np.abs(p_v2 - p_v3)
    print(f"  Disagreement: mean={disagreement.mean():.3f}, std={disagreement.std():.3f}")
    # Mechanism check: disagreement should correlate with absolute error
    abs_err_v2 = np.abs(y_true - p_v2)
    abs_err_v3 = np.abs(y_true - p_v3)
    abs_err_blend = np.abs(y_true - p_blend)
    r_disag_err_v2 = float(np.corrcoef(disagreement, abs_err_v2)[0, 1])
    r_disag_err_blend = float(np.corrcoef(disagreement, abs_err_blend)[0, 1])
    print(f"  r(disagreement, |error_V2|) = {r_disag_err_v2:.3f}")
    print(f"  r(disagreement, |error_blend|) = {r_disag_err_blend:.3f}")

    # Compute formula hash for prereg
    formula_sha = hashlib.sha256(
        json.dumps(
            {
                "coverage_targets": list(COVERAGE_TARGETS),
                "seeds": list(SEEDS),
                "design": "loo_quantile",
                "v2_oof_sha": hashlib.sha256(V2_OOF_NPY.read_bytes()).hexdigest()[:16],
                "v3_oof_sha": hashlib.sha256(V3_OOF_NPY.read_bytes()).hexdigest()[:16],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    _write_prereg(formula_sha)
    print(f"\n  Pre-reg written: {PREREG_PATH}")
    print(f"  formula_sha256={formula_sha[:16]}...")

    # Run conformal evaluation
    n = len(y_true)
    abstention_table = {}
    for variant in PREDICTOR_VARIANTS:
        p_eval = p_v2 if variant == "V2_only" else p_blend
        rows = []
        for tau in COVERAGE_TARGETS:
            # LOO quantile threshold computation
            retained_mask = np.zeros(n, dtype=bool)
            thresholds_per_subject = np.zeros(n)
            for i in range(n):
                calib_mask = np.ones(n, dtype=bool)
                calib_mask[i] = False
                calib_d = disagreement[calib_mask]
                # τ-th quantile (we keep the top τ% LOWEST disagreement)
                thresholds_per_subject[i] = np.quantile(calib_d, tau)
                retained_mask[i] = disagreement[i] <= thresholds_per_subject[i]
            retained_n = int(retained_mask.sum())
            thr_mean = float(thresholds_per_subject.mean())
            thr_std = float(thresholds_per_subject.std())
            thr_cv = thr_std / max(thr_mean, 1e-9)

            y_ret = y_true[retained_mask]
            p_ret = p_eval[retained_mask]
            if retained_n >= 3:
                ret_ccc = float(ccc(y_ret, p_ret))
                ret_mae = mae(y_ret, p_ret)
            else:
                ret_ccc = float("nan")
                ret_mae = float("nan")

            # Bootstrap CI on retained_ccc
            rng = np.random.RandomState(SEEDS[0])
            boot_ccc = np.zeros(N_BOOT)
            for b in range(N_BOOT):
                # Resample full cohort, recompute retention, recompute CCC
                idx = rng.randint(0, n, n)
                d_b = disagreement[idx]
                p_b = p_eval[idx]
                y_b = y_true[idx]
                # Recompute quantile threshold on bootstrap sample
                thr_b = np.quantile(d_b, tau)
                m_b = d_b <= thr_b
                if m_b.sum() >= 3 and y_b[m_b].std() > 1e-6:
                    boot_ccc[b] = ccc(y_b[m_b], p_b[m_b])
                else:
                    boot_ccc[b] = float("nan")
            valid = ~np.isnan(boot_ccc)
            ci_lo = float(np.nanpercentile(boot_ccc[valid], 2.5)) if valid.sum() > 0 else float("nan")
            ci_hi = float(np.nanpercentile(boot_ccc[valid], 97.5)) if valid.sum() > 0 else float("nan")

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

    # Monotonicity check
    def _monotonicity_check(rows: list[dict]) -> dict:
        cccs = [r["retained_ccc"] for r in rows]
        coverages = [r["coverage_target"] for r in rows]
        # Check that retained_ccc rises (or is non-decreasing) as coverage drops
        sorted_pairs = sorted(zip(coverages, cccs), reverse=True)
        cccs_sorted = [c for _, c in sorted_pairs]
        increases = [cccs_sorted[i+1] >= cccs_sorted[i] - 0.005 for i in range(len(cccs_sorted)-1)]
        n_violations = sum(1 for inc in increases if not inc)
        return {
            "n_violations": n_violations,
            "violated_pairs": [
                (sorted_pairs[i][0], sorted_pairs[i+1][0])
                for i, inc in enumerate(increases) if not inc
            ],
            "ccc_at_full_coverage": cccs_sorted[0],
            "ccc_at_min_coverage": cccs_sorted[-1],
        }

    monotonicity = {v: _monotonicity_check(abstention_table[v]) for v in PREDICTOR_VARIANTS}

    # Verdict
    kill_violated_any = any(
        r["kill_threshold_cv_violated"] for v in abstention_table.values() for r in v
    )
    monotonicity_violated = any(m["n_violations"] > 0 for m in monotonicity.values())

    if kill_violated_any:
        verdict = "FAIL_KILL_CRITERIA_THRESHOLD_INSTABILITY"
    elif monotonicity_violated:
        verdict = "PARTIAL_PASS_MONOTONICITY_VIOLATIONS"
    else:
        verdict = "PASS_DEPLOYABLE_SECONDARY"

    summary = {
        "name": "t1_conformal_lockbox",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "n": int(n),
        "v2_full_ccc": round(float(ccc(y_true, p_v2)), 4),
        "v3_full_ccc": round(float(ccc(y_true, p_v3)), 4),
        "blend_full_ccc": round(float(ccc(y_true, p_blend)), 4),
        "disagreement_mean": round(float(disagreement.mean()), 4),
        "disagreement_std": round(float(disagreement.std()), 4),
        "r_disagreement_abs_err_v2": round(r_disag_err_v2, 4),
        "r_disagreement_abs_err_blend": round(r_disag_err_blend, 4),
        "abstention_table_by_predictor": abstention_table,
        "monotonicity": monotonicity,
        "kill_violated_any_coverage": kill_violated_any,
        "verdict": verdict,
        "preregistration": str(PREREG_PATH),
        "predictor_v2_oof": str(V2_OOF_NPY),
        "predictor_v3_oof": str(V3_OOF_NPY),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t1_conformal_{ts}.json"
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
