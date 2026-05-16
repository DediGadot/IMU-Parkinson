"""T1 Slot S7: Multi-item topology abstention (deployable-secondary).

Hypothesis: A y-free composite abstention score combining per-item
disagreement (iter34 vs PH/MFDFA heads) and Mahalanobis distance in a
TopoFractal subspace yields retained-T1 CCC at 70%/50% coverage that
EXCEEDS slot-D AM baseline (cov_70=0.7876, cov_50=0.8338) by MCID 0.025
with lifetime-FWER frac>0 >= 0.995 (n=10).

Estimand: retained-T1 CCC at fixed coverage (DEPLOYABLE SECONDARY).
NOT full-cohort T1 CCC.

y-free at deployment:
  - Disagreements |p_iter34_j - p_AltHead_j| are feature-derived.
  - Mahalanobis distance in TopoFractal-6 space is feature-derived.
  - Inner-5-fold weight arm uses y_train_inner only; never y_test.

Pre-reg: preregistration_t1t3_proresults_ablation_20260515T133800Z.json (slot S7).
Lifetime FWER n=10 -> Bonferroni frac>0 gate = 1 - 0.05/10 = 0.995.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.covariance import EmpiricalCovariance
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from eval_utils import lins_ccc as ccc
from inductive_lib import FoldImputer, FoldNormalizer

ITER34_OOF_NPZ: str = "results/t1_iter34_per_item_oof_20260511_044242.npz"
STEPFUNC_CACHE: str = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"

COVERAGES: list[float] = [0.70, 0.50]
ALPHA_RIDGE: float = 100.0
N_BOOTSTRAP: int = 2000
BOOTSTRAP_SEED: int = 20260515
INNER_FOLDS: int = 5
INNER_SEED: int = 20260515

BASELINE_SLOTD_COV_70: float = 0.7876
BASELINE_SLOTD_COV_50: float = 0.8338
MCID: float = 0.025
LIFETIME_FWER_N: int = 10
BONF_FRAC_POS_GATE: float = 1.0 - 0.05 / LIFETIME_FWER_N  # 0.995


def _select_cols(df: pd.DataFrame, contains: str) -> list[str]:
    return [c for c in df.columns if contains in c and c != "sid"]


def load_aligned_data() -> tuple[np.ndarray, ...]:
    iter34 = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = iter34["sids"].astype(str)
    y_t1 = iter34["y_t1"].astype(float)
    yhat_iter34 = iter34["t1_sum_pred"].astype(float)
    item_13_true = iter34["item_13_true"].astype(float)
    item_13_pred = iter34["item_13_pred"].astype(float)
    item_14_true = iter34["item_14_true"].astype(float)
    item_14_pred = iter34["item_14_pred"].astype(float)
    item_10_true = iter34["item_10_true"].astype(float)
    item_10_pred = iter34["item_10_pred"].astype(float)

    df = pd.read_csv(STEPFUNC_CACHE)
    df = df[df["sid"].isin(sids)].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all()

    ph_cols = _select_cols(df, "_ph_")
    mfdfa_cols = _select_cols(df, "mfdfa_")
    X_ph = df[ph_cols].values.astype(float)
    X_mfdfa = df[mfdfa_cols].values.astype(float)

    # TopoFractal-6 (y-free): aggregate PH max/med + MFDFA delta_alpha across two tasks.
    topo_cols: list[str] = []
    for c in df.columns:
        cl = c.lower()
        if ("ph_" in cl and ("_h1_max" in cl or "_h1_med" in cl)) or (
            "mfdfa_" in cl and ("delta_alpha" in cl or "asymmetry" in cl or "h_range" in cl)
        ):
            topo_cols.append(c)
    Z_topo = df[topo_cols].values.astype(float)
    return (
        sids,
        y_t1,
        yhat_iter34,
        item_13_true,
        item_13_pred,
        item_14_true,
        item_14_pred,
        item_10_true,
        item_10_pred,
        X_ph,
        X_mfdfa,
        Z_topo,
        np.array(ph_cols),
        np.array(mfdfa_cols),
        np.array(topo_cols),
    )


def loocv_ridge_head(X: np.ndarray, y_item: np.ndarray) -> np.ndarray:
    """LOOCV Ridge alt-head; FoldImputer+FoldNormalizer + Ridge(alpha=100)."""
    n = len(y_item)
    out = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        X_tr_raw, X_te_raw = X[tr], X[i:i + 1]
        imp = FoldImputer.fit(X_tr_raw)
        X_tr = imp.transform(X_tr_raw)
        X_te = imp.transform(X_te_raw)
        nrm = FoldNormalizer.fit(X_tr)
        X_tr = nrm.transform(X_tr)
        X_te = nrm.transform(X_te)
        m = Ridge(alpha=ALPHA_RIDGE).fit(X_tr, y_item[tr])
        out[i] = float(m.predict(X_te)[0])
    return out


def loocv_mahalanobis(Z: np.ndarray) -> np.ndarray:
    """LOOCV Mahalanobis distance in TopoFractal feature space (y-free)."""
    n = Z.shape[0]
    out = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        Z_tr_raw, Z_te_raw = Z[tr], Z[i:i + 1]
        imp = FoldImputer.fit(Z_tr_raw)
        Z_tr = imp.transform(Z_tr_raw)
        Z_te = imp.transform(Z_te_raw)
        nrm = FoldNormalizer.fit(Z_tr)
        Z_tr = nrm.transform(Z_tr)
        Z_te = nrm.transform(Z_te)
        cov = EmpiricalCovariance().fit(Z_tr)
        out[i] = float(cov.mahalanobis(Z_te)[0])
    return out


def _zscore(x: np.ndarray) -> np.ndarray:
    mu = float(np.nanmean(x))
    sd = float(np.nanstd(x))
    if sd < 1e-12:
        return x - mu
    return (x - mu) / sd


def inner_5fold_weights(
    d13: np.ndarray,
    d14: np.ndarray,
    d10: np.ndarray,
    mahal: np.ndarray,
    y_t1: np.ndarray,
    yhat_iter34: np.ndarray,
) -> np.ndarray:
    """Inner-5-fold OOF: correlation(disagreement, |y_train - yhat_train|).

    Uses y_train_inner only — never y_test. Returns weights summing to 1.
    """
    n = len(y_t1)
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=INNER_SEED)
    corrs = np.zeros((INNER_FOLDS, 4), dtype=float)
    for fi, (tr, _) in enumerate(kf.split(np.arange(n))):
        resid_mag = np.abs(y_t1[tr] - yhat_iter34[tr])
        for k, src in enumerate([d13[tr], d14[tr], d10[tr], mahal[tr]]):
            s = src - np.nanmean(src)
            r = resid_mag - np.nanmean(resid_mag)
            denom = float(np.sqrt(np.nansum(s * s) * np.nansum(r * r)))
            corrs[fi, k] = float(np.nansum(s * r) / denom) if denom > 1e-12 else 0.0
    mean_corr = np.clip(corrs.mean(axis=0), 0.0, None)
    if mean_corr.sum() < 1e-12:
        return np.full(4, 0.25)
    return mean_corr / mean_corr.sum()


def retained_ccc_at_coverage(
    y: np.ndarray, yhat: np.ndarray, score: np.ndarray, coverage: float
) -> tuple[float, np.ndarray, int]:
    n = len(y)
    k = int(round(coverage * n))
    if k < 5:
        return float("nan"), np.zeros(n, dtype=bool), 0
    order = np.argsort(score, kind="stable")
    mask = np.zeros(n, dtype=bool)
    mask[order[:k]] = True
    return float(ccc(y[mask], yhat[mask])), mask, int(mask.sum())


def _bootstrap_frac_pos(
    y: np.ndarray,
    yhat_s7: np.ndarray,
    yhat_base: np.ndarray,
    mask: np.ndarray,
    rng: np.random.Generator,
) -> tuple[float, tuple[float, float]]:
    idx = np.where(mask)[0]
    deltas = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        rs = rng.choice(idx, size=len(idx), replace=True)
        deltas[b] = float(ccc(y[rs], yhat_s7[rs]) - ccc(y[rs], yhat_base[rs]))
    frac = float((deltas > 0).mean())
    ci = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    return frac, ci


def main(null_mode: str = "") -> None:
    (
        sids, y_t1, yhat_iter34,
        item_13_true, item_13_pred,
        item_14_true, item_14_pred,
        item_10_true, item_10_pred,
        X_ph, X_mfdfa, Z_topo,
        _, _, topo_cols,
    ) = load_aligned_data()
    n = len(sids)
    print(f"[S7] N={n}, PH cols={X_ph.shape[1]}, MFDFA cols={X_mfdfa.shape[1]}, "
          f"TopoFractal dims={Z_topo.shape[1]}, null_mode={null_mode or 'none'}")

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(13579)
        perm = rng.permutation(n)
        y_t1 = y_t1[perm]
        yhat_iter34 = yhat_iter34[perm]
        item_13_true = item_13_true[perm]
        item_13_pred = item_13_pred[perm]
        item_14_true = item_14_true[perm]
        item_14_pred = item_14_pred[perm]
        item_10_true = item_10_true[perm]
        item_10_pred = item_10_pred[perm]
        print("[S7 NULL=scrambled_y] permuted y_t1 + per-item truth/pred + iter34 jointly")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(24680)
        perm = rng.permutation(n)
        X_ph = X_ph[perm]
        X_mfdfa = X_mfdfa[perm]
        Z_topo = Z_topo[perm]
        print("[S7 NULL=sid_shuffle] permuted feature rows post-align")

    # Alt-head LOOCV predictions
    p_PH_13 = loocv_ridge_head(X_ph, item_13_true)
    p_PH_14 = loocv_ridge_head(X_ph, item_14_true)
    p_MFDFA_10 = loocv_ridge_head(X_mfdfa, item_10_true)

    # Item-13 PH correction layer (same recipe as slot-D for apples-to-apples)
    item_13_resid = item_13_true - item_13_pred
    correction_13 = loocv_ridge_head(X_ph, item_13_resid)
    t1_corrected = yhat_iter34 + 1.0 * correction_13

    # Disagreements (y-free at deployment)
    d13 = np.abs(item_13_pred - p_PH_13)
    d14 = np.abs(item_14_pred - p_PH_14)
    d10 = np.abs(item_10_pred - p_MFDFA_10)
    mahal = loocv_mahalanobis(Z_topo)

    # z-score each disagreement source (cohort-wide; y-free)
    z_d13, z_d14, z_d10, z_m = _zscore(d13), _zscore(d14), _zscore(d10), _zscore(mahal)

    # Two arms
    w_equal = np.array([0.25, 0.25, 0.25, 0.25])
    w_inner = inner_5fold_weights(d13, d14, d10, mahal, y_t1, yhat_iter34)
    print(f"[S7] arm weights equal={w_equal.tolist()}, inner5fold={w_inner.round(4).tolist()}")

    score_equal = (
        w_equal[0] * z_d13 + w_equal[1] * z_d14 + w_equal[2] * z_d10 + w_equal[3] * z_m
    )
    score_inner = (
        w_inner[0] * z_d13 + w_inner[1] * z_d14 + w_inner[2] * z_d10 + w_inner[3] * z_m
    )

    rng_boot = np.random.default_rng(BOOTSTRAP_SEED)
    per_coverage: dict[str, dict] = {}
    verdicts: dict[str, str] = {}

    for cov in COVERAGES:
        cov_key = f"cov_{int(cov * 100)}"
        baseline_slotD = BASELINE_SLOTD_COV_70 if cov == 0.70 else BASELINE_SLOTD_COV_50
        arm_results: dict[str, dict] = {}
        for arm_name, score in (("equal_weights_arm", score_equal),
                                ("inner_5fold_oof_weights_arm", score_inner)):
            base_ccc, mask, n_ret = retained_ccc_at_coverage(y_t1, yhat_iter34, score, cov)
            s7_unc = float(ccc(y_t1[mask], yhat_iter34[mask]))
            s7_corr = float(ccc(y_t1[mask], t1_corrected[mask]))
            delta_vs_slotD = s7_corr - baseline_slotD
            frac_pos, ci95 = _bootstrap_frac_pos(
                y_t1, t1_corrected, yhat_iter34, mask, rng_boot
            )
            arm_results[arm_name] = {
                "n_retained": n_ret,
                "baseline_iter34_retained_ccc": round(base_ccc, 4),
                "S7_retained_ccc_uncorrected": round(s7_unc, 4),
                "S7_retained_ccc_with_item13_PH_correction": round(s7_corr, 4),
                "delta_vs_slotD": round(delta_vs_slotD, 4),
                "frac_pos_bootstrap": round(frac_pos, 4),
                "ci95": [round(ci95[0], 4), round(ci95[1], 4)],
            }
            print(f"[S7] cov={int(cov*100)}% arm={arm_name}: "
                  f"S7_corr={s7_corr:.4f} vs slotD={baseline_slotD:.4f} "
                  f"Δ={delta_vs_slotD:+.4f} frac>0={frac_pos:.4f}")

        # Verdict: PASS if ANY arm clears MCID + Bonferroni
        passed = any(
            r["delta_vs_slotD"] >= MCID and r["frac_pos_bootstrap"] >= BONF_FRAC_POS_GATE
            for r in arm_results.values()
        )
        verdicts[cov_key] = "PASS_DEPLOYABLE_SECONDARY" if passed else "FAIL"
        per_coverage[cov_key] = {"coverage": cov, "arms": arm_results}

    out = {
        "name": "lockbox_t1_S7_multiitem_topology_abstention",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration_master":
            "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json",
        "estimand_label": "deployable_secondary_retained_ccc_at_coverage",
        "null_mode": null_mode or "real",
        "n_full_cohort": n,
        "baseline_slotD_retained_ccc_cov_70": BASELINE_SLOTD_COV_70,
        "baseline_slotD_retained_ccc_cov_50": BASELINE_SLOTD_COV_50,
        "y_free_score":
            "w1*z|p34_13-p_PH_13|+w2*z|p34_14-p_PH_14|+w3*z|p34_10-p_MFDFA_10|+w4*z*Mahal_TopoFractal",
        "z_score_note":
            "Disagreement-source z-normalization is y-free — uses only x-derived predictions, not y_test.",
        "arm_weights": {
            "equal_weights_arm": w_equal.tolist(),
            "inner_5fold_oof_weights_arm": w_inner.tolist(),
        },
        "topo_cols_used": topo_cols.tolist(),
        "per_coverage_results": per_coverage,
        "verdict_per_coverage": verdicts,
        "lifetime_fwer_n": LIFETIME_FWER_N,
        "bonferroni_frac_pos_gate": round(BONF_FRAC_POS_GATE, 5),
        "mcid_delta_ccc": MCID,
    }
    ts = out["created_at_utc"]
    suffix = f"_{null_mode}" if null_mode else ""
    path = Path(f"results/lockbox_t1_S7_multiitem_topology_abstention_{ts}{suffix}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[S7] Verdicts: {verdicts}")
    print(f"[S7] Wrote {path}")


def sanity_y_nan() -> bool:
    """Firewall law #9: replace y_t1 with NaN, prove retention masks unchanged."""
    (
        sids, y_t1, yhat_iter34,
        item_13_true, item_13_pred,
        item_14_true, item_14_pred,
        item_10_true, item_10_pred,
        X_ph, X_mfdfa, Z_topo, *_,
    ) = load_aligned_data()
    n = len(sids)

    p_PH_13 = loocv_ridge_head(X_ph, item_13_true)
    p_PH_14 = loocv_ridge_head(X_ph, item_14_true)
    p_MFDFA_10 = loocv_ridge_head(X_mfdfa, item_10_true)
    d13 = np.abs(item_13_pred - p_PH_13)
    d14 = np.abs(item_14_pred - p_PH_14)
    d10 = np.abs(item_10_pred - p_MFDFA_10)
    mahal = loocv_mahalanobis(Z_topo)
    z_d13, z_d14, z_d10, z_m = _zscore(d13), _zscore(d14), _zscore(d10), _zscore(mahal)
    score_equal = 0.25 * (z_d13 + z_d14 + z_d10 + z_m)

    # Real-y masks (retention rule never references y).
    y_nan = np.full(n, np.nan)
    masks_real: dict[str, list[bool]] = {}
    masks_nan: dict[str, list[bool]] = {}
    for cov in COVERAGES:
        _, m_real, _ = retained_ccc_at_coverage(y_t1, yhat_iter34, score_equal, cov)
        _, m_nan, _ = retained_ccc_at_coverage(y_nan, yhat_iter34, score_equal, cov)
        masks_real[f"cov_{int(cov*100)}"] = m_real.tolist()
        masks_nan[f"cov_{int(cov*100)}"] = m_nan.tolist()

    all_match = all(masks_real[k] == masks_nan[k] for k in masks_real)
    receipt = {
        "name": "abstention_sanity_t1_S7_multiitem_topology",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "lockbox_target": "lockbox_t1_S7_multiitem_topology_abstention",
        "retention_rule_form":
            "g(x) = w·z(|p34_j - p_AltHead_j|) + w·z(Mahal_TopoFractal(x)) <= q_cov (y-free)",
        "correction_rule_form":
            f"c(x) = lambda * Ridge_alpha={ALPHA_RIDGE}(PH(x))_train_fold (y-free at deployment)",
        "n_subjects": n,
        "coverages": COVERAGES,
        "masks_identical_with_y_nan": all_match,
        "test_passes": all_match,
    }
    ts = receipt["created_at_utc"]
    path = Path(f"results/abstention_sanity_{ts}.json")
    path.write_text(json.dumps(receipt, indent=2))
    print(f"[Sanity y_nan] all_match={all_match}")
    print(f"[Sanity y_nan] Wrote {path}")
    return all_match


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sanity-y-nan":
        ok = sanity_y_nan()
        sys.exit(0 if ok else 1)
    null_arg = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        null_arg = sys.argv[1].split("=", 1)[1]
    main(null_mode=null_arg)
