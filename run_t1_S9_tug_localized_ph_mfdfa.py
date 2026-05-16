"""T1 Slot S9: TUG-localized item-12 MFDFA + item-13 PH joint correction.

Variant of S8 restricting feature spaces to columns starting with
``task_TUG_`` only. Hypothesis: nuisance variance from non-TUG tasks
dilutes per-item Ridge corrections; TUG (sit-to-stand, turn, gait, sit)
is the most informative single task for items 12 (postural stability
during turn) and 13 (posture during stand). Expected feature counts:
PH ≈ 4 cols (trunk_pitch_h1_max/med + sacrum_ang_h1_max/med for TUG),
MFDFA ≈ 7 cols (trunk_pitch delta_alpha / asymmetry / hurst_q2 / h_q0 /
h_q_pos5 / h_q_neg5 / h_range for TUG). Aborts arm if fewer than 3
features for either intersection.

Arms (identical structure to S8):
  - item13_only       : iter34 + 1.0 * correction_13_TUG
  - item12_only       : iter34 + 1.0 * correction_12_TUG
  - JOINT_item12_13   : iter34 + 1.0 * correction_13_TUG + 1.0 * correction_12_TUG

Promotion gate: 5-fold × 3-seed mean Δ̄ >= +0.015 AND seed std < 0.020.
FWER n=7 (S1/S2/S3/S5/S6/S7/S8 + this S9). Bonferroni gate frac_pos
>= 1 - 0.05/7 = 0.992857. MCID +0.025.

Firewall: inductive_lib fold-local imputation/normalization; Ridge
α=100, λ=1.0 FROZEN. No outer-test contamination.
"""
from __future__ import annotations

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

ITER34_OOF_NPZ = "results/t1_iter34_per_item_oof_20260511_044242.npz"
STEPFN_CACHE = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"

SPLIT_SEED = 20260309
MODEL_SEEDS: tuple[int, ...] = (42, 1337, 7)
LAMBDA_FIXED = 1.0
ALPHA_FIXED = 100.0
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515

FWER_N = 7
BONFERRONI_GATE = 1.0 - 0.05 / FWER_N
MCID = 0.025

FIVEFOLD_SCREEN_GATE_MEAN = 0.015
FIVEFOLD_SCREEN_GATE_STD = 0.020

MIN_FEATURES_PER_ARM = 3
TUG_PREFIX = "task_TUG_"

PREREG_MASTER = (
    "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json"
)


@dataclass(frozen=True)
class CorrectionSpec:
    name: str
    item: int
    family_substr: str  # e.g. "_ph_" or "mfdfa_"


CORR_ITEM13_PH = CorrectionSpec("correction_13_PH_TUG", 13, "_ph_")
CORR_ITEM12_MFDFA = CorrectionSpec("correction_12_MFDFA_TUG", 12, "mfdfa_")


def load_aligned_data() -> tuple[
    np.ndarray, np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]],
    pd.DataFrame,
]:
    iter34 = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = iter34["sids"].astype(str)
    y_t1 = iter34["y_t1"].astype(float)
    yhat_iter34 = iter34["t1_sum_pred"].astype(float)
    items: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for j in range(9, 15):
        items[j] = (
            iter34[f"item_{j}_true"].astype(float),
            iter34[f"item_{j}_pred"].astype(float),
        )

    df = pd.read_csv(STEPFN_CACHE)
    df = df[df["sid"].isin(sids)].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all(), "sid alignment failed"
    return sids, y_t1, yhat_iter34, items, df


def select_tug_features(
    df: pd.DataFrame, family_substr: str,
) -> tuple[np.ndarray, list[str]]:
    cols = [
        c for c in df.columns
        if c != "sid" and c.startswith(TUG_PREFIX) and family_substr in c
    ]
    if not cols:
        raise ValueError(
            f"No TUG-localized columns matching family {family_substr!r}"
        )
    X = df[cols].values.astype(float)
    return X, cols


def loocv_ridge_correction(
    X: np.ndarray, item_resid: np.ndarray, alpha: float,
    model_seeds: Sequence[int],
) -> np.ndarray:
    n = len(item_resid)
    correction = np.zeros(n, dtype=float)
    for i in range(n):
        tr = np.arange(n) != i
        X_tr_raw, X_te_raw = X[tr], X[i : i + 1]
        y_tr = item_resid[tr]
        imp = FoldImputer.fit(X_tr_raw)
        X_tr = imp.transform(X_tr_raw)
        X_te = imp.transform(X_te_raw)
        nrm = FoldNormalizer.fit(X_tr)
        X_tr = nrm.transform(X_tr)
        X_te = nrm.transform(X_te)
        preds = []
        for seed in model_seeds:
            m = Ridge(alpha=alpha, random_state=seed).fit(X_tr, y_tr)
            preds.append(float(m.predict(X_te)[0]))
        correction[i] = float(np.mean(preds))
    return correction


def fivefold_screen_joint(
    X_ph: np.ndarray, X_md: np.ndarray, y_t1: np.ndarray,
    yhat_iter34: np.ndarray, resid_13: np.ndarray, resid_12: np.ndarray,
    seeds: Sequence[int],
) -> tuple[float, float, list[float]]:
    n = len(y_t1)
    deltas: list[float] = []
    for seed in seeds:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        corr_13 = np.zeros(n, dtype=float)
        corr_12 = np.zeros(n, dtype=float)
        for tr_idx, te_idx in kf.split(np.arange(n)):
            imp_ph = FoldImputer.fit(X_ph[tr_idx])
            X_ph_tr = imp_ph.transform(X_ph[tr_idx])
            X_ph_te = imp_ph.transform(X_ph[te_idx])
            nrm_ph = FoldNormalizer.fit(X_ph_tr)
            X_ph_tr = nrm_ph.transform(X_ph_tr)
            X_ph_te = nrm_ph.transform(X_ph_te)

            imp_md = FoldImputer.fit(X_md[tr_idx])
            X_md_tr = imp_md.transform(X_md[tr_idx])
            X_md_te = imp_md.transform(X_md[te_idx])
            nrm_md = FoldNormalizer.fit(X_md_tr)
            X_md_tr = nrm_md.transform(X_md_tr)
            X_md_te = nrm_md.transform(X_md_te)

            preds_ph: list[np.ndarray] = []
            preds_md: list[np.ndarray] = []
            for m_seed in MODEL_SEEDS:
                m_ph = Ridge(alpha=ALPHA_FIXED, random_state=m_seed).fit(
                    X_ph_tr, resid_13[tr_idx]
                )
                preds_ph.append(m_ph.predict(X_ph_te))
                m_md = Ridge(alpha=ALPHA_FIXED, random_state=m_seed).fit(
                    X_md_tr, resid_12[tr_idx]
                )
                preds_md.append(m_md.predict(X_md_te))
            corr_13[te_idx] = np.mean(preds_ph, axis=0)
            corr_12[te_idx] = np.mean(preds_md, axis=0)

        ccc_base = float(ccc(y_t1, yhat_iter34))
        ccc_joint = float(
            ccc(y_t1, yhat_iter34 + LAMBDA_FIXED * corr_13 + LAMBDA_FIXED * corr_12)
        )
        deltas.append(ccc_joint - ccc_base)
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


def evaluate_metrics(
    name: str, y_t1: np.ndarray, yhat_iter34: np.ndarray, yhat_corrected: np.ndarray,
    correction_total: np.ndarray,
) -> dict:
    sum_resid = y_t1 - yhat_iter34
    ccc_base = float(ccc(y_t1, yhat_iter34))
    ccc_corr = float(ccc(y_t1, yhat_corrected))
    r_base = float(pearsonr(y_t1, yhat_iter34)[0])
    r_corr = float(pearsonr(y_t1, yhat_corrected)[0])
    mae_base = float(np.mean(np.abs(y_t1 - yhat_iter34)))
    mae_corr = float(np.mean(np.abs(y_t1 - yhat_corrected)))
    corr_sum = float(pearsonr(correction_total, sum_resid)[0])
    delta_ccc = ccc_corr - ccc_base
    delta_r = r_corr - r_base
    delta_mae = mae_corr - mae_base
    frac_pos, ci, median = paired_bootstrap_frac_pos(
        y_t1, yhat_iter34, yhat_corrected, N_BOOTSTRAP, BOOTSTRAP_SEED
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
        "corr_correction_sum_residual": round(corr_sum, 6),
        "frac_pos_bootstrap": round(frac_pos, 4),
        "bootstrap_median": round(median, 6),
        "ci95": [round(ci[0], 6), round(ci[1], 6)],
        "verdict": verdict,
    }


def apply_null(
    null_mode: str, y_t1: np.ndarray, yhat_iter34: np.ndarray,
    items: dict[int, tuple[np.ndarray, np.ndarray]], df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]], pd.DataFrame]:
    n = len(y_t1)
    if null_mode == "scrambled_y":
        rng = np.random.default_rng(20260515)
        perm = rng.permutation(n)
        y_t1 = y_t1[perm]
        yhat_iter34 = yhat_iter34[perm]
        items = {j: (t[perm], p[perm]) for j, (t, p) in items.items()}
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(20260515 + 1)
        perm = rng.permutation(n)
        feat_cols = [c for c in df.columns if c != "sid"]
        df = df.copy()
        df[feat_cols] = df[feat_cols].values[perm]
    return y_t1, yhat_iter34, items, df


def main(null_mode: str = "") -> None:
    sids, y_t1, yhat_iter34, items, df = load_aligned_data()
    if null_mode:
        y_t1, yhat_iter34, items, df = apply_null(
            null_mode, y_t1, yhat_iter34, items, df
        )
    n = len(sids)
    print(f"[S9] N={n}, null_mode={null_mode or 'real'}")
    print(f"[S9] Baseline LOOCV iter34 CCC={float(ccc(y_t1, yhat_iter34)):.6f}")

    X_ph, cols_ph = select_tug_features(df, CORR_ITEM13_PH.family_substr)
    X_md, cols_md = select_tug_features(df, CORR_ITEM12_MFDFA.family_substr)
    print(f"[S9] TUG-localized n_features PH={len(cols_ph)} cols={cols_ph}")
    print(f"[S9] TUG-localized n_features MFDFA={len(cols_md)} cols={cols_md}")

    if len(cols_ph) < MIN_FEATURES_PER_ARM:
        raise RuntimeError(
            f"PH TUG arm under minimum: {len(cols_ph)} < {MIN_FEATURES_PER_ARM}"
        )
    if len(cols_md) < MIN_FEATURES_PER_ARM:
        raise RuntimeError(
            f"MFDFA TUG arm under minimum: {len(cols_md)} < {MIN_FEATURES_PER_ARM}"
        )

    item13_true, item13_pred = items[13]
    item12_true, item12_pred = items[12]
    resid_13 = item13_true - item13_pred
    resid_12 = item12_true - item12_pred

    corr_13 = loocv_ridge_correction(X_ph, resid_13, ALPHA_FIXED, MODEL_SEEDS)
    corr_12 = loocv_ridge_correction(X_md, resid_12, ALPHA_FIXED, MODEL_SEEDS)

    yhat_item13 = yhat_iter34 + LAMBDA_FIXED * corr_13
    yhat_item12 = yhat_iter34 + LAMBDA_FIXED * corr_12
    yhat_joint = yhat_iter34 + LAMBDA_FIXED * corr_13 + LAMBDA_FIXED * corr_12

    arm_item13 = evaluate_metrics(
        "item13_only_TUG", y_t1, yhat_iter34, yhat_item13, corr_13
    )
    arm_item12 = evaluate_metrics(
        "item12_only_TUG", y_t1, yhat_iter34, yhat_item12, corr_12
    )
    arm_joint = evaluate_metrics(
        "JOINT_item12_item13_TUG", y_t1, yhat_iter34, yhat_joint, corr_13 + corr_12
    )

    for r in (arm_item13, arm_item12, arm_joint):
        print(
            f"[S9] {r['arm']}: Δccc={r['delta_ccc']:+.4f}, "
            f"Δr={r['delta_pearson_r']:+.4f}, ΔMAE={r['delta_mae']:+.4f}, "
            f"corr(c,sum_resid)={r['corr_correction_sum_residual']:+.4f}, "
            f"frac>0={r['frac_pos_bootstrap']:.4f} -> {r['verdict']}"
        )

    if not null_mode:
        screen_mean, screen_std, screen_deltas = fivefold_screen_joint(
            X_ph, X_md, y_t1, yhat_iter34, resid_13, resid_12, MODEL_SEEDS
        )
        screen_pass = (
            screen_mean >= FIVEFOLD_SCREEN_GATE_MEAN
            and screen_std < FIVEFOLD_SCREEN_GATE_STD
        )
        print(
            f"[S9] 5-fold screen (JOINT_TUG): Δ̄={screen_mean:+.4f}, "
            f"std={screen_std:.4f}, "
            f"deltas={[round(d, 4) for d in screen_deltas]} -> "
            f"{'PROMOTE' if screen_pass else 'BELOW_SCREEN'}"
        )
    else:
        screen_mean = float("nan")
        screen_std = float("nan")
        screen_deltas = []
        screen_pass = False

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "name": "lockbox_t1_S9_tug_localized_ph_mfdfa",
        "created_at_utc": ts,
        "preregistration_master": PREREG_MASTER,
        "session": "2026-05-15-PM-microbatch-S9",
        "null_mode": null_mode or "real",
        "n_cohort": n,
        "split_seed": SPLIT_SEED,
        "model_seeds": list(MODEL_SEEDS),
        "alpha_fixed": ALPHA_FIXED,
        "lambda_fixed": LAMBDA_FIXED,
        "n_bootstrap": N_BOOTSTRAP,
        "fwer_n": FWER_N,
        "bonferroni_gate": round(BONFERRONI_GATE, 6),
        "mcid": MCID,
        "estimand_label": "full_cohort_t1_loocv_ccc_post_correction",
        "iter34_baseline_canonical_ccc": 0.7170,
        "iter34_loocv_ccc_recomputed": round(float(ccc(y_t1, yhat_iter34)), 6),
        "tug_prefix": TUG_PREFIX,
        "n_features_ph_tug": len(cols_ph),
        "n_features_mfdfa_tug": len(cols_md),
        "feature_cols_ph_tug": cols_ph,
        "feature_cols_mfdfa_tug": cols_md,
        "arms": {
            "item13_only_TUG": arm_item13,
            "item12_only_TUG": arm_item12,
            "JOINT_TUG": arm_joint,
        },
        "fivefold_mean_delta_3seeds_JOINT": (
            round(screen_mean, 6) if screen_deltas else None
        ),
        "fivefold_seed_std": (
            round(screen_std, 6) if screen_deltas else None
        ),
        "fivefold_deltas_per_seed": [round(d, 6) for d in screen_deltas],
        "fivefold_screen_gate_mean": FIVEFOLD_SCREEN_GATE_MEAN,
        "fivefold_screen_gate_std": FIVEFOLD_SCREEN_GATE_STD,
        "fivefold_promotion": "PROMOTE" if screen_pass else "BELOW_SCREEN",
        "verdict_JOINT": arm_joint["verdict"],
    }

    suffix = f"_{null_mode}" if null_mode else ""
    path = Path(
        f"results/lockbox_t1_S9_tug_localized_ph_mfdfa_{ts}{suffix}.json"
    )
    path.write_text(json.dumps(out, indent=2))

    oof_path = Path(
        f"results/oof_t1_S9_tug_localized_ph_mfdfa_{ts}{suffix}.npz"
    )
    np.savez(
        oof_path,
        sids=sids,
        y_t1=y_t1,
        yhat_iter34=yhat_iter34,
        correction_13_TUG=corr_13,
        correction_12_TUG=corr_12,
        yhat_item13_only_TUG=yhat_item13,
        yhat_item12_only_TUG=yhat_item12,
        yhat_JOINT_TUG=yhat_joint,
    )
    print(f"\n[S9] Wrote {path}")
    print(f"[S9] Wrote {oof_path}")


if __name__ == "__main__":
    mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        mode = sys.argv[1].split("=", 1)[1]
    main(null_mode=mode)
