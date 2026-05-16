"""Bootstrap S13/S15 retained-CCC against Slot F reference + full-cohort iter47.

Inputs
------
- iter47 baseline preds at N=95 cohort
- S13 LOOCV correction vector (PH+MFDFA Ridge fit on T3 residual)
- Slot F retained reference values 0.4237 (@70%) / 0.5370 (@50%) — point references
  (Slot F lockbox at results/lockbox_t3_slotF_cqr_width_conformal_20260515T091224Z.json)

For each coverage in {0.70, 0.50}:
- compute retained-CCC for (a) iter47 retained, (b) S13 JOINT-corrected retained,
  (c) S13 PH-only corrected retained, using |correction_magnitude| as the y-free
  retention score
- bootstrap retained-CCC vs full-cohort iter47 (frac>full)
- bootstrap retained-CCC vs Slot F reference (point estimate, not bootstrap-able
  without Slot F's per-subject vector, so we just note the delta)

Output: results/audit_t3_S13_S15_retained_bootstrap_<UTC>.json
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

ITER47_PREDS = "results/iter47_invalidcode_subject_preds_20260508_194605.csv"
STEPFN_CACHE = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
SLOTF_LOCKBOX = "results/lockbox_t3_slotF_cqr_width_conformal_20260515T091224Z.json"
ALPHA_FIXED = 100.0
MODEL_SEEDS = (42, 1337, 7)
N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260515
SLOTF_REF_70 = 0.4237
SLOTF_REF_50 = 0.5370


def load_data():
    iter47 = pd.read_csv(ITER47_PREDS)
    iter47 = iter47[
        (iter47["cohort"] == "drop_allmissing_validrange")
        & (iter47["stage2_policy"] == "stage2_current")
    ].reset_index(drop=True)
    sids = iter47["sid"].astype(str).values
    y_t3 = iter47["y_true_validrange"].astype(float).values
    yhat47 = iter47["y_pred"].astype(float).values
    sf = pd.read_csv(STEPFN_CACHE)
    sf = sf[sf["sid"].isin(sids)].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(sf["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    sf = sf.iloc[order].reset_index(drop=True)
    ph_cols = sorted([c for c in sf.columns if "_ph_" in c])
    mfdfa_cols = sorted([c for c in sf.columns if "mfdfa_" in c])
    X_ph = sf[ph_cols].values.astype(float)
    X_md = sf[mfdfa_cols].values.astype(float)
    return sids, y_t3, yhat47, X_ph, X_md


def loocv_correction(X, target_resid, alpha, model_seeds):
    n = len(target_resid)
    corr = np.zeros(n, dtype=float)
    for i in range(n):
        tr = np.arange(n) != i
        imp = FoldImputer.fit(X[tr])
        X_tr = imp.transform(X[tr])
        X_te = imp.transform(X[i:i + 1])
        nrm = FoldNormalizer.fit(X_tr)
        X_tr = nrm.transform(X_tr)
        X_te = nrm.transform(X_te)
        preds = []
        for seed in model_seeds:
            m = Ridge(alpha=alpha, random_state=seed).fit(X_tr, target_resid[tr])
            preds.append(float(m.predict(X_te)[0]))
        corr[i] = float(np.mean(preds))
    return corr


def bootstrap_retained_vs_full(y, yhat_full, yhat_ret, risk, coverage,
                               n_boot, seed):
    """Paired-bootstrap: P(retained_ccc > full_ccc) over resamples.

    On each bootstrap resample, we recompute retention threshold using the
    resampled |risk| quantile to keep the retention rule self-consistent.
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        y_b = y[idx]
        f_b = yhat_full[idx]
        r_b = yhat_ret[idx]
        risk_b = risk[idx]
        thr = float(np.quantile(risk_b, coverage))
        mask = risk_b <= thr
        if mask.sum() < 3:
            deltas[b] = 0.0
            continue
        ccc_full = float(ccc(y_b, f_b))
        ccc_ret = float(ccc(y_b[mask], r_b[mask]))
        deltas[b] = ccc_ret - ccc_full
    frac_pos = float((deltas > 0).mean())
    ci = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    return frac_pos, ci, float(np.median(deltas))


def main():
    sids, y_t3, yhat47, X_ph, X_md = load_data()
    n = len(y_t3)
    base_ccc = float(ccc(y_t3, yhat47))

    target_resid = y_t3 - yhat47
    corr_ph = loocv_correction(X_ph, target_resid, ALPHA_FIXED, MODEL_SEEDS)
    corr_md = loocv_correction(X_md, target_resid, ALPHA_FIXED, MODEL_SEEDS)

    out: dict = {
        "name": "audit_t3_S13_S15_retained_bootstrap",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "n_cohort": n,
        "iter47_full_ccc": round(base_ccc, 6),
        "slotF_ref_70": SLOTF_REF_70,
        "slotF_ref_50": SLOTF_REF_50,
        "n_bootstrap": N_BOOTSTRAP,
        "results": {},
    }

    # Retention scores and predictors
    configs = {
        "iter47_retain_by_corrPH_mag": (yhat47, np.abs(corr_ph)),
        "iter47_retain_by_corrJOINT_mag": (yhat47, np.abs(corr_ph + corr_md)),
        "s13PH_retain_by_corrPH_mag": (yhat47 + corr_ph, np.abs(corr_ph)),
        "s13JOINT_retain_by_corrJOINT_mag": (yhat47 + corr_ph + corr_md,
                                              np.abs(corr_ph + corr_md)),
    }

    for cov in (0.70, 0.50):
        cov_key = f"cov_{int(cov*100)}"
        out["results"][cov_key] = {}
        slotF_ref = SLOTF_REF_70 if cov == 0.70 else SLOTF_REF_50
        for cfg_name, (yhat_ret, risk) in configs.items():
            thr = float(np.quantile(risk, cov))
            mask = risk <= thr
            n_ret = int(mask.sum())
            ccc_full = float(ccc(y_t3, yhat47))
            ccc_ret = float(ccc(y_t3[mask], yhat_ret[mask]))
            delta_full = ccc_ret - ccc_full
            delta_slotF = ccc_ret - slotF_ref

            frac_pos, ci, median = bootstrap_retained_vs_full(
                y_t3, yhat47, yhat_ret, risk, cov, N_BOOTSTRAP, BOOTSTRAP_SEED
            )
            out["results"][cov_key][cfg_name] = {
                "n_retained": n_ret,
                "actual_coverage": round(n_ret / n, 4),
                "ccc_retained": round(ccc_ret, 4),
                "delta_vs_full_cohort_iter47": round(delta_full, 4),
                "delta_vs_slotF_ref": round(delta_slotF, 4),
                "bootstrap_frac_pos_vs_full": round(frac_pos, 4),
                "bootstrap_ci95_vs_full": [round(ci[0], 4), round(ci[1], 4)],
                "bootstrap_median_vs_full": round(median, 4),
                "beats_full_iter47_uncorrected": frac_pos >= 0.95 and delta_full > 0,
            }
            print(
                f"[S15.bootstrap] cov={cov:.0%} {cfg_name:36s}: "
                f"CCC={ccc_ret:.4f} Δfull={delta_full:+.4f} ΔSlotF={delta_slotF:+.4f} "
                f"frac>full={frac_pos:.4f}"
            )

    ts = out["created_at_utc"]
    fname = f"results/audit_t3_S13_S15_retained_bootstrap_{ts}.json"
    Path(fname).write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {fname}")


if __name__ == "__main__":
    main()
