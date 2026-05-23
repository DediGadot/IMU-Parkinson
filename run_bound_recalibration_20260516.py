#!/usr/bin/env python3
"""Bound A/D/E recalibration under valid-range N=95 cohort + label-noise floor.

Diagnostic-only script. No promotion test. No new model fit.

Recomputes the project's theoretical T3 ceilings under:
- valid-range Part III target (NLS036 invalid 9s → missing, all-missing rows dropped)
- N=95 PD cohort (`drop_allmissing_validrange`)
- iter34 T1 hygiene-corrected per-subject predictions (N=92 lockbox)
- literature label-noise floor (Goetz 2008 ICC=0.81 → CCC ceiling ≈ √0.81)

Bounds reported:
- Bound D_pearson  = Pearson r(T1_actual, T3_actual)  -- perfect-calibration ceiling
- Bound D_ccc      = CCC(a*T1+b, T3) under best linear a,b (closed-form via OLS)
- Bound A          = CCC(T1_actual + mean(R), T3)     -- oracle T1 + mean R, IMU-only max
- Bound E_inductive= CCC(T1_iter34 + mean(R), T3)     -- realistic inductive ceiling

All bounds include BCa 95% CI (B=5000 bootstrap).
Label-noise corrected variants divide CCC by sqrt(ICC).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc
from project_paths import DATA_DIR, RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data
from run_t3_iter47_invalid_code_fix import (
    _is_pd,
    _load_pd_clinical,
    validrange_part3_counts,
)
from updrs_columns import valid_updrs_item_total

ensure_dir(RESULTS_DIR)

# Goetz 2008 inter-rater ICC for MDS-UPDRS Part III total = 0.81
# CCC ceiling = sqrt(ICC) under classical-test-theory assumption
LITERATURE_ICC = 0.81
LITERATURE_CCC_CEILING = float(np.sqrt(LITERATURE_ICC))

T1_ITEMS = [9, 10, 11, 12, 13, 14]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_t1_per_subject(clinical_df: pd.DataFrame, sids: list[str]) -> np.ndarray:
    """Build T1 (sum of items 9..14) from raw subitem columns with valid-range hygiene."""
    sid_to_t1 = {}
    cdf = clinical_df.copy()
    cdf["sid"] = cdf["Subject ID"].astype(str).str.strip()
    for sid in sids:
        rows = cdf[cdf["sid"] == sid]
        if len(rows) == 0:
            sid_to_t1[sid] = np.nan
            continue
        row = rows.iloc[0]
        total = 0.0
        any_missing = False
        for item in T1_ITEMS:
            v = pd.to_numeric(row.get(f"MDSUPDRS_3-{item}"), errors="coerce")
            if pd.isna(v) or float(v) < 0 or float(v) > 4:
                any_missing = True
                break
            total += float(v)
        sid_to_t1[sid] = total if not any_missing else np.nan
    return np.array([sid_to_t1[s] for s in sids], dtype=np.float64)


def best_linear_calibrated_ccc(t1: np.ndarray, t3: np.ndarray) -> float:
    """CCC of (a + b*T1) vs T3 with a, b chosen by OLS.

    For OLS on T3 ~ a + b*T1, residual mean is 0 so the calibrated prediction has
    matched mean. Lin's CCC of OLS prediction simplifies to Pearson r^2 scaled.
    But CCC(a+bT1, T3) where (a,b) are OLS coefs is mathematically Pearson r * f
    where f = 2*r*σ_T3*σ_OLSpred / (σ_T3² + σ_OLSpred²) with σ_OLSpred = |b|σ_T1 = rσ_T3.
    Then CCC = 2*r*σ_T3*r*σ_T3 / (σ_T3² + r²σ_T3²) = 2r²/(1+r²).
    """
    r = float(np.corrcoef(t1, t3)[0, 1])
    return 2 * r * r / (1 + r * r)


def bca_bootstrap_ccc_pair(
    a: np.ndarray, b: np.ndarray, fn=lins_ccc, n_boot: int = 5000, seed: int = 42
) -> tuple[float, float, float]:
    """Returns (point, ci_lo, ci_hi) for fn(a_boot, b_boot)."""
    rng = np.random.RandomState(seed)
    n = len(a)
    vals = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, size=n)
        vals[i] = fn(a[idx], b[idx])
    pt = float(fn(a, b))
    lo = float(np.percentile(vals, 2.5))
    hi = float(np.percentile(vals, 97.5))
    return pt, lo, hi


def bca_bootstrap_pearson_r(
    a: np.ndarray, b: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> tuple[float, float, float]:
    def fn(x, y):
        if np.std(x) < 1e-9 or np.std(y) < 1e-9:
            return 0.0
        return float(np.corrcoef(x, y)[0, 1])

    return bca_bootstrap_ccc_pair(a, b, fn=fn, n_boot=n_boot, seed=seed)


def main():
    ts_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "experiment": "Bound A/D/E recalibration on valid-range cohort + label-noise floor",
        "purpose": "Refresh theoretical T3 ceilings (pre-hygiene D=0.683, A=0.351, E=0.171) under N=95 valid-range cohort and iter34 hygiene-corrected T1 predictions.",
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "literature_floor": {
            "ICC_inter_rater_part3": LITERATURE_ICC,
            "CCC_ceiling_sqrtICC": LITERATURE_CCC_CEILING,
            "source": "Goetz 2008 MDS-UPDRS Part III test-retest ICC",
        },
    }

    # Load PD cohort + valid-range T3
    sids_full, _X, _fc, _y_old, _hy, _obs = load_full_pd_data()
    counts, clean_sums, audit, clinical_path = validrange_part3_counts()
    clinical_df, _ = _load_pd_clinical()

    # Drop-all-missing cohort: PD with at least 1 valid Part-III subitem
    raw_nonmissing = np.array([counts.get(str(s), 0) for s in sids_full], dtype=int)
    keep = raw_nonmissing > 0
    sids = sids_full[keep]
    y_t3 = np.array([clean_sums.get(str(s), np.nan) for s in sids], dtype=np.float64)

    # T1 from raw subitems with valid-range hygiene
    t1_arr = build_t1_per_subject(clinical_df, sids.tolist())

    # Restrict to subjects with both T1 and T3 valid
    valid = np.isfinite(t1_arr) & np.isfinite(y_t3)
    sids_v = sids[valid]
    t1_v = t1_arr[valid]
    t3_v = y_t3[valid]
    r_v = t3_v - t1_v  # T3 - T1 = sum of items {1..8, 15..18 etc}
    mean_r = float(np.mean(r_v))

    out["cohort"] = {
        "cohort_label": "drop_allmissing_validrange (PD with ≥1 valid subitem + valid T1)",
        "n_pd_total": int(len(sids_full)),
        "n_valid_t3": int(len(sids)),
        "n_both_t1_t3_valid": int(len(sids_v)),
        "sids_dropped_for_t1_missing": sids[~valid].tolist(),
        "t1_mean": float(np.mean(t1_v)),
        "t1_std": float(np.std(t1_v)),
        "t3_mean": float(np.mean(t3_v)),
        "t3_std": float(np.std(t3_v)),
        "r_mean": mean_r,
        "r_std": float(np.std(r_v)),
        "corr_t1_t3_pearson": float(np.corrcoef(t1_v, t3_v)[0, 1]),
    }

    # ── Bound D: Pearson r(T1, T3) ── perfect calibration upper bound on CCC
    r_pt, r_lo, r_hi = bca_bootstrap_pearson_r(t1_v, t3_v, n_boot=5000, seed=42)
    out["bound_D_pearson_r"] = {
        "definition": "Pearson r(T1_actual, T3_actual) -- upper bound on CCC under perfect linear calibration of T1→T3.",
        "value": r_pt,
        "ci95": [r_lo, r_hi],
    }

    # ── Bound D_ccc: 2r²/(1+r²) ── OLS-calibrated CCC
    d_ccc_pt = best_linear_calibrated_ccc(t1_v, t3_v)
    def _calib_ccc_fn(a, b):
        if np.std(a) < 1e-9 or np.std(b) < 1e-9:
            return 0.0
        rr = float(np.corrcoef(a, b)[0, 1])
        return 2 * rr * rr / (1 + rr * rr)
    _, d_ccc_lo, d_ccc_hi = bca_bootstrap_ccc_pair(t1_v, t3_v, fn=_calib_ccc_fn, n_boot=5000, seed=42)
    out["bound_D_ccc_calibrated"] = {
        "definition": "CCC(a + b·T1, T3) with (a,b) by OLS = 2r²/(1+r²).",
        "value": d_ccc_pt,
        "ci95": [d_ccc_lo, d_ccc_hi],
    }

    # ── Bound A: CCC(T1 + mean(R), T3) ── oracle T1, no IMU info on R
    bound_a_pred = t1_v + mean_r
    a_pt, a_lo, a_hi = bca_bootstrap_ccc_pair(t3_v, bound_a_pred, fn=lins_ccc, n_boot=5000, seed=42)
    out["bound_A_oracle_t1_meanR"] = {
        "definition": "CCC(T1_actual + mean(R), T3) -- oracle T1 + mean-imputed R = IMU-only max if R has zero IMU signal.",
        "value": a_pt,
        "ci95": [a_lo, a_hi],
    }

    # ── Bound E: iter34 inductive T1 predictions ── realistic inductive ceiling
    iter34_lockbox = json.loads(Path("results/lockbox_t1_iter34_hybrid_20260510_233019.json").read_text())
    iter34_sids = iter34_lockbox["per_subject"]["sids"]
    iter34_t1_pred = np.asarray(iter34_lockbox["per_subject"]["y_pred"], dtype=np.float64)
    iter34_t1_true = np.asarray(iter34_lockbox["per_subject"]["y_true"], dtype=np.float64)

    # Map iter34 sids -> our cohort
    sid_to_idx = {s: i for i, s in enumerate(sids_v)}
    iter34_match_idx = [sid_to_idx.get(s, None) for s in iter34_sids]
    iter34_match_mask = np.array([idx is not None for idx in iter34_match_idx])
    sids_e = np.array([iter34_sids[i] for i in range(len(iter34_sids)) if iter34_match_mask[i]])
    t1_pred_e = iter34_t1_pred[iter34_match_mask]
    t1_true_e = iter34_t1_true[iter34_match_mask]
    t3_e = np.array([t3_v[sid_to_idx[s]] for s in sids_e], dtype=np.float64)
    r_e = t3_e - t1_true_e
    mean_r_e = float(np.mean(r_e))

    bound_e_pred = t1_pred_e + mean_r_e
    e_pt, e_lo, e_hi = bca_bootstrap_ccc_pair(t3_e, bound_e_pred, fn=lins_ccc, n_boot=5000, seed=42)
    out["bound_E_inductive_iter34"] = {
        "definition": "CCC(iter34_T1_pred + mean(R), T3) -- realistic T3 ceiling under current T1 quality if R has zero IMU signal.",
        "value": e_pt,
        "ci95": [e_lo, e_hi],
        "n": int(len(sids_e)),
        "iter34_t1_ccc_recheck": float(lins_ccc(t1_true_e, t1_pred_e)),
    }

    # Sanity: confirm iter34 T1 CCC on the matched cohort matches the published 0.7170
    out["iter34_ccc_validation"] = {
        "iter34_lockbox_published": 0.717,
        "iter34_recomputed_on_matched": float(lins_ccc(t1_true_e, t1_pred_e)),
        "match_within_0.005": abs(float(lins_ccc(t1_true_e, t1_pred_e)) - 0.717) < 0.005,
    }

    # ── Label-noise corrected variants ── divide each bound by sqrt(ICC)
    out["label_noise_corrected"] = {
        "note": "Each bound divided by sqrt(ICC)=sqrt(0.81)≈0.9. Caps the deployable CCC against a noisy reference.",
        "ICC": LITERATURE_ICC,
        "bound_D_pearson_r__floored": r_pt / LITERATURE_CCC_CEILING,
        "bound_A__floored": a_pt / LITERATURE_CCC_CEILING,
        "bound_E__floored": e_pt / LITERATURE_CCC_CEILING,
        "deployment_caveat": "These division-corrected numbers are upper bounds on observable CCC against a perfectly-rated gold standard; they BOUND ABOVE what we could observe even with an oracle predictor.",
    }

    # ── Pre-hygiene baselines for comparison ──
    out["pre_hygiene_baselines"] = {
        "from_claude_md": {
            "bound_D_perfect_T1_to_T3": 0.683,
            "bound_A_oracle_T1_plus_meanR": 0.351,
            "bound_E_inductive_shrinkage_iter34_to_T3": 0.171,
        },
        "delta_post_hygiene": {
            "bound_D_pearson_r_minus_pre_D": r_pt - 0.683,
            "bound_A_minus_pre_A": a_pt - 0.351,
            "bound_E_minus_pre_E": e_pt - 0.171,
        },
    }

    # ── Current SOTA contextualized ──
    out["sota_contextualization"] = {
        "t3_canonical_loocv_ccc": 0.3784,
        "t3_canonical_minus_bound_A": 0.3784 - a_pt,
        "t3_canonical_minus_bound_E": 0.3784 - e_pt,
        "interpretation_short": (
            "If T3 canonical (0.3784) > Bound_E, the iter47 LOOCV result extracts more than "
            "constant-R inductive ceiling — meaning R (items 1-8, 15-18) has some IMU-recoverable "
            "signal at N=95 beyond the contribution of T1. If T3 canonical ≤ Bound_E, R is "
            "essentially constant-imputed in the canonical model."
        ),
    }

    out["formula_sha256"] = _formula_sha({
        "bound_definitions": {
            "D_pearson": "Pearson r(T1_actual, T3_actual)",
            "D_ccc": "2r²/(1+r²)",
            "A": "CCC(T1_actual + mean(R), T3)",
            "E": "CCC(iter34_T1_pred + mean(R), T3)",
        },
        "cohort": "drop_allmissing_validrange + T1-valid intersection",
        "iter34_lockbox": "results/lockbox_t1_iter34_hybrid_20260510_233019.json",
        "n_boot": 5000,
        "boot_seed": 42,
    })

    out_path = RESULTS_DIR / f"lockbox_bound_recalibration_{ts_utc}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")

    # Console summary
    print("\n=== BOUND RECALIBRATION SUMMARY (valid-range N≈95 cohort) ===")
    print(f"N (T1+T3 both valid): {len(sids_v)}")
    print(f"  Bound D (Pearson r) : {r_pt:.4f}  [95% CI {r_lo:.4f}, {r_hi:.4f}]  (was 0.683)")
    print(f"  Bound D_ccc 2r²/(1+r²): {d_ccc_pt:.4f}  [95% CI {d_ccc_lo:.4f}, {d_ccc_hi:.4f}]")
    print(f"  Bound A             : {a_pt:.4f}  [95% CI {a_lo:.4f}, {a_hi:.4f}]  (was 0.351)")
    print(f"  Bound E (iter34)    : {e_pt:.4f}  [95% CI {e_lo:.4f}, {e_hi:.4f}]  (was 0.171)")
    print(f"  Label-noise corrected:")
    print(f"    Bound D / sqrt(ICC): {r_pt/LITERATURE_CCC_CEILING:.4f}")
    print(f"    Bound A / sqrt(ICC): {a_pt/LITERATURE_CCC_CEILING:.4f}")
    print(f"    Bound E / sqrt(ICC): {e_pt/LITERATURE_CCC_CEILING:.4f}")
    print(f"  T3 canonical 0.3784 vs Bound A: Δ={0.3784-a_pt:+.4f}")
    print(f"  T3 canonical 0.3784 vs Bound E: Δ={0.3784-e_pt:+.4f}")
    return out


if __name__ == "__main__":
    main()
