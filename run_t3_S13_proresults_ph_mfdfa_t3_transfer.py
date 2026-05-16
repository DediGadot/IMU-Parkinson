"""T3 Slot S13: transfer of validated S8 PH+MFDFA item-12/13 correction to T3 estimand.

Mechanistic question
--------------------
S8 (today, 2026-05-15) validated PH item-13 + MFDFA item-12 fold-local Ridge
correction lifts T1 LOOCV by Delta=+0.0088 (sub-MCID, frac>0=0.925, all D4
diagnostics clean). Since items 12 and 13 are subsets of T3, the same
correction added to iter47's T3 LOOCV baseline should produce a smaller but
non-zero lift IF the signal is real. Magnitude prediction by std-ratio
scaling: T1 std~3, T3 std~9.9, so expected T3 Delta is ~ +0.0088 * 3/9.9 ~ +0.003.

Three arms, three model seeds, full firewall, screen + LOOCV + bootstrap +
5-null pattern.

Arms
----
- ph_only       : iter47 + Ridge_alpha=100(PH features -> T3 residual)
- mfdfa_only    : iter47 + Ridge_alpha=100(MFDFA features -> T3 residual)
- JOINT         : iter47 + Ridge(PH -> T3 resid) + Ridge(MFDFA -> T3 resid)

FWER family extends today's S1-S12 by adding S13 = n=8 unique mechanism slots
under the T1T3 ablation pre-reg; the strict Bonferroni gate for this slot is
1 - 0.05/8 = 0.9938. Sub-MCID is +0.025 against iter47 baseline 0.3784.

5-fold promotion gate (per project standard, post-2026-05-02):
  Delta_bar >= +0.025 AND seed std < 0.020 across 3 seeds.

Firewall: inductive_lib FoldImputer / FoldNormalizer, fold-local only. No
test-fold leak. Mandatory --null modes: scrambled_y, sid_shuffle. y-free
correction (uses only PH/MFDFA features); --sanity-y-nan supported for the
S15 abstention sub-pipeline launched after this run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

ITER47_PREDS = "results/iter47_invalidcode_subject_preds_20260508_194605.csv"
STEPFN_CACHE = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
SLOTF_LOCKBOX = "results/lockbox_t3_slotF_cqr_width_conformal_20260515T091224Z.json"
PREREG_MASTER = "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json"

SPLIT_SEED = 20260309
MODEL_SEEDS: tuple[int, ...] = (42, 1337, 7)
ALPHA_FIXED = 100.0
LAMBDA_FIXED = 1.0
N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260515

FWER_N = 8
BONFERRONI_GATE = 1.0 - 0.05 / FWER_N
MCID = 0.025
FIVEFOLD_SCREEN_GATE_MEAN = 0.025
FIVEFOLD_SCREEN_GATE_STD = 0.020

COHORT = "drop_allmissing_validrange"
STAGE2_POLICY = "stage2_current"


@dataclass(frozen=True)
class Arm:
    name: str
    ph: bool
    mfdfa: bool


ARMS: tuple[Arm, ...] = (
    Arm("ph_only", ph=True, mfdfa=False),
    Arm("mfdfa_only", ph=False, mfdfa=True),
    Arm("JOINT", ph=True, mfdfa=True),
)


def load_aligned_data() -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], list[str]
]:
    iter47 = pd.read_csv(ITER47_PREDS)
    iter47 = iter47[
        (iter47["cohort"] == COHORT) & (iter47["stage2_policy"] == STAGE2_POLICY)
    ].reset_index(drop=True)
    sids = iter47["sid"].astype(str).values
    y_t3 = iter47["y_true_validrange"].astype(float).values
    yhat47 = iter47["y_pred"].astype(float).values
    n = len(sids)
    assert n == 95, f"Expected N=95, got {n}"

    sf = pd.read_csv(STEPFN_CACHE)
    sf = sf[sf["sid"].isin(sids)].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(sf["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    sf = sf.iloc[order].reset_index(drop=True)
    assert (sf["sid"].astype(str).values == sids).all(), "sid alignment mismatch"

    ph_cols = sorted([c for c in sf.columns if "_ph_" in c])
    mfdfa_cols = sorted([c for c in sf.columns if "mfdfa_" in c])
    assert ph_cols, "no PH columns found"
    assert mfdfa_cols, "no MFDFA columns found"
    X_ph = sf[ph_cols].values.astype(float)
    X_md = sf[mfdfa_cols].values.astype(float)
    return sids, y_t3, yhat47, X_ph, X_md, ph_cols, mfdfa_cols


def fit_correction_loocv(
    X: np.ndarray, target_resid: np.ndarray, alpha: float,
    model_seeds: Sequence[int],
) -> np.ndarray:
    """LOOCV fold-local Ridge correction averaged across model seeds."""
    n = len(target_resid)
    correction = np.zeros(n, dtype=float)
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
        correction[i] = float(np.mean(preds))
    return correction


def fivefold_screen(
    y_t3: np.ndarray, yhat47: np.ndarray, X_ph: np.ndarray, X_md: np.ndarray,
    arm: Arm, seeds: Sequence[int],
) -> tuple[float, float, list[float]]:
    n = len(y_t3)
    deltas: list[float] = []
    for seed in seeds:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        corr_total = np.zeros(n, dtype=float)
        for tr_idx, te_idx in kf.split(np.arange(n)):
            resid_tr = (y_t3 - yhat47)[tr_idx]
            corr_te = np.zeros(len(te_idx), dtype=float)
            if arm.ph:
                imp_p = FoldImputer.fit(X_ph[tr_idx])
                X_p_tr = imp_p.transform(X_ph[tr_idx])
                X_p_te = imp_p.transform(X_ph[te_idx])
                nrm_p = FoldNormalizer.fit(X_p_tr)
                X_p_tr = nrm_p.transform(X_p_tr)
                X_p_te = nrm_p.transform(X_p_te)
                preds = []
                for m_seed in MODEL_SEEDS:
                    m = Ridge(alpha=ALPHA_FIXED, random_state=m_seed).fit(
                        X_p_tr, resid_tr
                    )
                    preds.append(m.predict(X_p_te))
                corr_te = corr_te + np.mean(preds, axis=0)
            if arm.mfdfa:
                imp_m = FoldImputer.fit(X_md[tr_idx])
                X_m_tr = imp_m.transform(X_md[tr_idx])
                X_m_te = imp_m.transform(X_md[te_idx])
                nrm_m = FoldNormalizer.fit(X_m_tr)
                X_m_tr = nrm_m.transform(X_m_tr)
                X_m_te = nrm_m.transform(X_m_te)
                preds = []
                for m_seed in MODEL_SEEDS:
                    m = Ridge(alpha=ALPHA_FIXED, random_state=m_seed).fit(
                        X_m_tr, resid_tr
                    )
                    preds.append(m.predict(X_m_te))
                corr_te = corr_te + np.mean(preds, axis=0)
            corr_total[te_idx] = corr_te
        ccc_base = float(ccc(y_t3, yhat47))
        ccc_arm = float(ccc(y_t3, yhat47 + LAMBDA_FIXED * corr_total))
        deltas.append(ccc_arm - ccc_base)
    return float(np.mean(deltas)), float(np.std(deltas, ddof=1)), deltas


def paired_bootstrap_frac_pos(
    y: np.ndarray, yhat_a: np.ndarray, yhat_b: np.ndarray,
    n_boot: int, seed: int,
) -> tuple[float, tuple[float, float], float]:
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[b] = float(ccc(y[idx], yhat_b[idx]) - ccc(y[idx], yhat_a[idx]))
    frac_pos = float((deltas > 0).mean())
    ci = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    median = float(np.median(deltas))
    return frac_pos, ci, median


def evaluate_arm(
    name: str, y_t3: np.ndarray, yhat47: np.ndarray, yhat_corr: np.ndarray,
    correction: np.ndarray,
) -> dict:
    sum_resid = y_t3 - yhat47
    ccc_base = float(ccc(y_t3, yhat47))
    ccc_corr = float(ccc(y_t3, yhat_corr))
    r_base = float(pearsonr(y_t3, yhat47)[0])
    r_corr = float(pearsonr(y_t3, yhat_corr)[0])
    mae_base = float(np.mean(np.abs(y_t3 - yhat47)))
    mae_corr = float(np.mean(np.abs(y_t3 - yhat_corr)))
    corr_sum = float(pearsonr(correction, sum_resid)[0]) if correction.std() > 0 else 0.0
    delta_ccc = ccc_corr - ccc_base
    delta_r = r_corr - r_base
    delta_mae = mae_corr - mae_base
    frac_pos, ci, median = paired_bootstrap_frac_pos(
        y_t3, yhat47, yhat_corr, N_BOOTSTRAP, BOOTSTRAP_SEED
    )
    if frac_pos >= BONFERRONI_GATE and delta_ccc >= MCID:
        verdict = "PASS_FWER"
    elif frac_pos >= 0.95 and delta_ccc >= MCID:
        verdict = "PASS_UNCORRECTED"
    elif delta_ccc > 0:
        verdict = "SUB_MCID"
    else:
        verdict = "FAIL"
    return {
        "arm": name,
        "loocv_ccc_baseline": round(ccc_base, 6),
        "loocv_ccc_corrected": round(ccc_corr, 6),
        "delta_ccc": round(delta_ccc, 6),
        "delta_pearson_r": round(delta_r, 6),
        "delta_mae": round(delta_mae, 6),
        "corr_correction_t3_residual": round(corr_sum, 6),
        "frac_pos_bootstrap": round(frac_pos, 4),
        "bootstrap_median": round(median, 6),
        "ci95": [round(ci[0], 6), round(ci[1], 6)],
        "verdict": verdict,
    }


def apply_null(
    null_mode: str, y_t3: np.ndarray, yhat47: np.ndarray,
    X_ph: np.ndarray, X_md: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(y_t3)
    if null_mode == "scrambled_y":
        rng = np.random.default_rng(20260515)
        perm = rng.permutation(n)
        return y_t3[perm], yhat47[perm], X_ph, X_md
    if null_mode == "sid_shuffle":
        rng = np.random.default_rng(20260516)
        perm = rng.permutation(n)
        return y_t3, yhat47, X_ph[perm], X_md[perm]
    if null_mode == "canary":
        rng = np.random.default_rng(20260517)
        canary = rng.standard_normal((n, 1))
        X_ph = np.hstack([X_ph, canary])
        X_md = np.hstack([X_md, canary])
        return y_t3, yhat47, X_ph, X_md
    raise ValueError(f"Unknown null mode: {null_mode}")


def s15_abstention_check(
    y_t3: np.ndarray, yhat47: np.ndarray, correction_joint: np.ndarray,
    slotf_ref_70: float, slotf_ref_50: float, sanity_y_nan: bool,
) -> dict:
    """Y-free abstention using |correction_magnitude| as retention score.

    Lower |correction| = more confident iter47 prediction is sufficient -> retain.
    For sanity_y_nan mode, y is replaced by NaN to confirm retention decision is
    y-free.
    """
    n = len(y_t3)
    risk = np.abs(correction_joint)
    if sanity_y_nan:
        y_eval = np.full(n, np.nan)
    else:
        y_eval = y_t3.copy()

    out: dict = {"sanity_y_nan": sanity_y_nan, "n_total": n}
    for cov in (0.70, 0.50):
        thr = float(np.quantile(risk, cov))
        retain_mask = risk <= thr
        n_ret = int(retain_mask.sum())
        actual_cov = float(n_ret / n)
        if sanity_y_nan:
            out[f"cov_{int(cov*100)}"] = {
                "n_retained": n_ret,
                "actual_coverage": actual_cov,
                "risk_threshold_max_retained": thr,
                "decision_is_y_free": True,
            }
            continue
        ccc_iter47 = float(ccc(y_eval[retain_mask], yhat47[retain_mask]))
        ccc_s13 = float(
            ccc(y_eval[retain_mask], (yhat47 + LAMBDA_FIXED * correction_joint)[retain_mask])
        )
        out[f"cov_{int(cov*100)}"] = {
            "n_retained": n_ret,
            "actual_coverage": actual_cov,
            "risk_threshold_max_retained": thr,
            "iter47_retained_ccc": round(ccc_iter47, 4),
            "s13_corrected_retained_ccc": round(ccc_s13, 4),
            "slotF_reference_retained_ccc": slotf_ref_70 if cov == 0.70 else slotf_ref_50,
            "beats_slotF_iter47": ccc_iter47 > (slotf_ref_70 if cov == 0.70 else slotf_ref_50),
            "beats_slotF_s13": ccc_s13 > (slotf_ref_70 if cov == 0.70 else slotf_ref_50),
        }
    return out


def main(null_mode: str = "", sanity_y_nan: bool = False) -> None:
    sids, y_t3, yhat47, X_ph, X_md, ph_cols, mfdfa_cols = load_aligned_data()
    if null_mode:
        y_t3, yhat47, X_ph, X_md = apply_null(null_mode, y_t3, yhat47, X_ph, X_md)
    n = len(y_t3)
    label = null_mode or "real"
    print(f"[S13] N={n}, mode={label}, sanity_y_nan={sanity_y_nan}")
    base_ccc = float(ccc(y_t3, yhat47))
    print(f"[S13] iter47 baseline CCC={base_ccc:.6f} MAE={np.mean(np.abs(y_t3-yhat47)):.4f}")
    print(f"[S13] PH features: {len(ph_cols)} | MFDFA features: {len(mfdfa_cols)}")

    target_resid = y_t3 - yhat47
    corr_ph = fit_correction_loocv(X_ph, target_resid, ALPHA_FIXED, MODEL_SEEDS)
    corr_md = fit_correction_loocv(X_md, target_resid, ALPHA_FIXED, MODEL_SEEDS)

    yhat_ph = yhat47 + LAMBDA_FIXED * corr_ph
    yhat_md = yhat47 + LAMBDA_FIXED * corr_md
    yhat_joint = yhat47 + LAMBDA_FIXED * corr_ph + LAMBDA_FIXED * corr_md

    arm_ph = evaluate_arm("ph_only", y_t3, yhat47, yhat_ph, corr_ph)
    arm_md = evaluate_arm("mfdfa_only", y_t3, yhat47, yhat_md, corr_md)
    arm_joint = evaluate_arm("JOINT", y_t3, yhat47, yhat_joint, corr_ph + corr_md)

    for r in (arm_ph, arm_md, arm_joint):
        print(
            f"[S13] {r['arm']:12s}: Δccc={r['delta_ccc']:+.4f}, "
            f"Δr={r['delta_pearson_r']:+.4f}, ΔMAE={r['delta_mae']:+.4f}, "
            f"corr(c,resid)={r['corr_correction_t3_residual']:+.4f}, "
            f"frac>0={r['frac_pos_bootstrap']:.4f} -> {r['verdict']}"
        )

    out: dict = {
        "name": "lockbox_t3_S13_ph_mfdfa_t3_transfer",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "session": "2026-05-15-PM-T3-S13-transfer",
        "null_mode": label,
        "n_cohort": n,
        "cohort": COHORT,
        "stage2_policy": STAGE2_POLICY,
        "split_seed": SPLIT_SEED,
        "model_seeds": list(MODEL_SEEDS),
        "alpha_fixed": ALPHA_FIXED,
        "lambda_fixed": LAMBDA_FIXED,
        "n_bootstrap": N_BOOTSTRAP,
        "preregistration_master": PREREG_MASTER,
        "fwer_n": FWER_N,
        "bonferroni_gate": round(BONFERRONI_GATE, 6),
        "mcid": MCID,
        "iter47_baseline_canonical_ccc": 0.3784,
        "iter47_baseline_loocv_recomputed_ccc": round(base_ccc, 6),
        "n_features_ph": len(ph_cols),
        "n_features_mfdfa": len(mfdfa_cols),
        "arms": {"ph_only": arm_ph, "mfdfa_only": arm_md, "JOINT": arm_joint},
        "s8_t1_reference_delta": 0.0088,
        "expected_t3_lift_from_t1_t3_std_scaling": round(0.0088 * 3.0 / 9.9, 6),
    }

    # 5-fold screen on JOINT only, real mode only
    if not null_mode:
        screen_mean, screen_std, deltas = fivefold_screen(
            y_t3, yhat47, X_ph, X_md, ARMS[2], MODEL_SEEDS
        )
        promo = (
            "PROMOTE"
            if screen_mean >= FIVEFOLD_SCREEN_GATE_MEAN
            and screen_std < FIVEFOLD_SCREEN_GATE_STD
            else "BELOW_SCREEN"
        )
        out["fivefold_screen_JOINT_mean"] = round(screen_mean, 6)
        out["fivefold_screen_JOINT_std"] = round(screen_std, 6)
        out["fivefold_screen_JOINT_per_seed"] = [round(x, 6) for x in deltas]
        out["fivefold_screen_gate_mean"] = FIVEFOLD_SCREEN_GATE_MEAN
        out["fivefold_screen_gate_std"] = FIVEFOLD_SCREEN_GATE_STD
        out["fivefold_promotion"] = promo
        print(
            f"[S13] 5-fold JOINT: Δ̄={screen_mean:+.6f} ± {screen_std:.6f} "
            f"per-seed {deltas} -> {promo}"
        )

        # S15 abstention sub-pipeline
        slotf70 = 0.4237
        slotf50 = 0.5370
        if sanity_y_nan:
            s15 = s15_abstention_check(
                y_t3, yhat47, corr_ph + corr_md, slotf70, slotf50, sanity_y_nan=True
            )
        else:
            s15 = s15_abstention_check(
                y_t3, yhat47, corr_ph + corr_md, slotf70, slotf50, sanity_y_nan=False
            )
        out["s15_abstention"] = s15
        print(f"[S13.S15] abstention: {json.dumps(s15, indent=2)[:600]}")

    # formula_sha256
    formula_payload = json.dumps({
        "arms": [a.__dict__ for a in ARMS],
        "alpha": ALPHA_FIXED, "lambda": LAMBDA_FIXED, "seeds": list(MODEL_SEEDS),
        "n_boot": N_BOOTSTRAP, "ph_cols": ph_cols, "mfdfa_cols": mfdfa_cols,
        "cohort": COHORT, "stage2": STAGE2_POLICY, "alpha_fix": ALPHA_FIXED,
    }, sort_keys=True).encode()
    out["formula_sha256"] = hashlib.sha256(formula_payload).hexdigest()

    suffix = "" if not null_mode else f"_{null_mode}"
    if sanity_y_nan:
        suffix = suffix + "_sanityYnan"
    ts = out["created_at_utc"]
    fname = f"results/lockbox_t3_S13_ph_mfdfa_t3_transfer_{ts}{suffix}.json"
    Path(fname).write_text(json.dumps(out, indent=2, default=str))
    print(f"[S13] wrote {fname}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--null", default="", choices=("", "scrambled_y", "sid_shuffle", "canary"))
    ap.add_argument("--sanity-y-nan", action="store_true",
                    help="Replace y_test with NaN to verify abstention rule is y-free")
    args = ap.parse_args()
    main(null_mode=args.null, sanity_y_nan=args.sanity_y_nan)
