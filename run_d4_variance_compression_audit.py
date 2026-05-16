"""D4 — Variance-compression audit (codex 2026-05-15T08:25Z follow-up).

Tests whether yesterday's per-item CCC lifts (+0.146/+0.111/+0.078 on items 13/14/10)
are REAL signal or just calibration/variance-compression artifacts from Ridge alpha=100
shrinkage.

For each corrected item j in {9, 10, 13, 14}:
  - Regenerate fold-local Ridge OOF corrected predictions (replicates yesterday's
    run_peritem_winner_stack.py logic).
  - delta_j  = pred_corrected_j - pred_iter34_j
  - resid_j  = y_j - pred_iter34_j  (iter34's per-item residual)
  - sum_resid = T1_sum_y - iter34_T1_sum_pred  (iter34's T1_sum residual)

Diagnostics (codex 2026-05-15):
  (1) corr(delta_j, resid_j) > 0   — does correction predict item's own residual?
  (2) corr(delta_j, sum_resid) > 0 — does correction predict T1_sum residual?
  (3) bootstrap P(cov(delta_j, sum_resid) > 0) >= 0.90
  (4) MAE_item old vs corrected (correction should NOT increase MAE)
  (5) RMSE_item old vs corrected
  (6) CCC decomposition: Pearson r, C_b (Lin's bias correction), mean bias,
      variance ratio. A real signal lifts BOTH r and C_b; a calibration artifact
      only lifts C_b.

Falsification rule (D4 hypothesis is FALSE iff signal is real):
  delta_j carries positive OOF covariance with item's residual AND with T1_sum
  residual, item MAE does not worsen, AND CCC lift includes Pearson-r lift
  (not just C_b lift).

Output: results/d4_variance_compression_audit_<UTC>.json + console table.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import align_features_to_oof
from inductive_lib import FoldImputer, FoldNormalizer


FAMILY_PREFIXES = {
    "spd": "spd_", "klc": "klc_", "crqa": "crqa_", "mfdfa": "mfdfa_", "ph": "ph_",
}
WINNERS = [
    ("item9", "ph", 100.0),
    ("item10", "mfdfa", 100.0),
    ("item13", "ph", 100.0),
    ("item14", "ph", 100.0),
]


def lins_ccc_decomp(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Lin's CCC + decomposition: r, C_b, mean bias, variance ratio."""
    mu_y, mu_p = y_true.mean(), y_pred.mean()
    sd_y, sd_p = y_true.std(ddof=0), y_pred.std(ddof=0)
    if sd_y < 1e-12 or sd_p < 1e-12:
        return {"ccc": 0.0, "r": 0.0, "C_b": 1.0, "mean_diff": float(mu_p - mu_y),
                "var_ratio": 0.0, "MAE": float(np.mean(np.abs(y_true - y_pred))),
                "RMSE": float(np.sqrt(np.mean((y_true - y_pred) ** 2)))}
    r = float(np.corrcoef(y_true, y_pred)[0, 1])
    # CCC = 2 * cov / (var_y + var_p + (mu_y - mu_p)^2)
    cov_yp = float(np.mean((y_true - mu_y) * (y_pred - mu_p)))
    ccc = 2 * cov_yp / (sd_y ** 2 + sd_p ** 2 + (mu_y - mu_p) ** 2 + 1e-12)
    # C_b = bias-correction factor
    v = sd_p / sd_y if sd_y > 0 else 0
    u = (mu_p - mu_y) / np.sqrt(sd_y * sd_p) if (sd_y > 0 and sd_p > 0) else 0
    C_b = 2 / (v + 1 / v + u ** 2 + 1e-12) if v > 0 else 0
    return {
        "ccc": float(ccc), "r": r, "C_b": float(C_b),
        "mean_diff": float(mu_p - mu_y), "var_ratio": float(v),
        "MAE": float(np.mean(np.abs(y_true - y_pred))),
        "RMSE": float(np.sqrt(np.mean((y_true - y_pred) ** 2))),
    }


def fold_local_ridge_correction(F: np.ndarray, y_item: np.ndarray,
                                 yhat_item_oof: np.ndarray, alpha: float = 100.0) -> np.ndarray:
    """Replicates run_peritem_winner_stack.py fold_local_ridge_stack."""
    n = len(y_item)
    correction = np.zeros(n)
    residual = y_item - yhat_item_oof
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask])
        F_tr = imp.transform(F[mask])
        F_te = imp.transform(F[i:i + 1])
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        ridge = Ridge(alpha=alpha, random_state=42)
        ridge.fit(F_tr, residual[mask])
        correction[i] = float(ridge.predict(F_te)[0])
    return correction


def bootstrap_cov_pos_prob(x: np.ndarray, y: np.ndarray, n_boot: int = 2000, seed: int = 42) -> float:
    rng = np.random.RandomState(seed)
    n = len(x)
    positives = 0
    for _ in range(n_boot):
        idx = rng.randint(0, n, n)
        if np.cov(x[idx], y[idx], ddof=0)[0, 1] > 0:
            positives += 1
    return positives / n_boot


def main():
    feature_path = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
    oof_path = "results/t1_iter34_per_item_oof_20260511_044242.npz"

    print("=" * 80)
    print("D4 VARIANCE-COMPRESSION AUDIT (codex 2026-05-15T08:25Z follow-up)")
    print("=" * 80)

    npz = np.load(oof_path, allow_pickle=True)
    sids = np.asarray(npz["sids"])
    y_t1_sum = np.asarray(npz["y_t1"], np.float64)
    yhat_t1_sum = np.asarray(npz["t1_sum_pred"], np.float64)

    df = pd.read_csv(feature_path)
    fam_cols = {fam: [c for c in df.columns if prefix in c] for fam, prefix in FAMILY_PREFIXES.items()}

    n = len(sids)
    sum_resid = y_t1_sum - yhat_t1_sum
    print(f"\n  iter34 T1_sum CCC = {lins_ccc_decomp(y_t1_sum, yhat_t1_sum)['ccc']:.4f}")
    print(f"  T1_sum residual std = {sum_resid.std():.4f}")
    print(f"  T1_sum residual range = [{sum_resid.min():.2f}, {sum_resid.max():.2f}]")
    print()

    audit = {"items": {}, "sum_resid_stats": {"std": float(sum_resid.std()), "mean": float(sum_resid.mean())}}

    for item_tag, family, alpha in WINNERS:
        item_num = int(item_tag.replace("item", ""))
        y_item = np.asarray(npz[f"item_{item_num}_true"], np.float64)
        yhat_iter34_item = np.asarray(npz[f"item_{item_num}_pred"], np.float64)
        F, mask = align_features_to_oof(df[["sid"] + fam_cols[family]], sids, sid_col="sid")
        if mask.sum() < n:
            print(f"  warning: only {mask.sum()}/{n} subjects aligned for item {item_num}")

        # Regenerate corrected predictions
        correction = fold_local_ridge_correction(F, y_item, yhat_iter34_item, alpha=alpha)
        yhat_corrected_item = yhat_iter34_item + correction

        # Diagnostics
        decomp_base = lins_ccc_decomp(y_item, yhat_iter34_item)
        decomp_corr = lins_ccc_decomp(y_item, yhat_corrected_item)

        resid_item = y_item - yhat_iter34_item
        corr_delta_resid_item = float(np.corrcoef(correction, resid_item)[0, 1])
        corr_delta_sum_resid = float(np.corrcoef(correction, sum_resid)[0, 1])
        cov_delta_sum_resid_pos_prob = bootstrap_cov_pos_prob(correction, sum_resid)

        print(f"\n--- Item {item_num} ({family}, alpha={alpha}) ---")
        print(f"  baseline:  CCC={decomp_base['ccc']:.4f}  r={decomp_base['r']:.4f}  C_b={decomp_base['C_b']:.4f}  MAE={decomp_base['MAE']:.4f}  RMSE={decomp_base['RMSE']:.4f}  var_ratio={decomp_base['var_ratio']:.4f}")
        print(f"  corrected: CCC={decomp_corr['ccc']:.4f}  r={decomp_corr['r']:.4f}  C_b={decomp_corr['C_b']:.4f}  MAE={decomp_corr['MAE']:.4f}  RMSE={decomp_corr['RMSE']:.4f}  var_ratio={decomp_corr['var_ratio']:.4f}")
        print(f"  Δ:         CCC={decomp_corr['ccc']-decomp_base['ccc']:+.4f}  Δr={decomp_corr['r']-decomp_base['r']:+.4f}  ΔC_b={decomp_corr['C_b']-decomp_base['C_b']:+.4f}  ΔMAE={decomp_corr['MAE']-decomp_base['MAE']:+.4f}  ΔRMSE={decomp_corr['RMSE']-decomp_base['RMSE']:+.4f}")
        print(f"  corr(delta_j, resid_item_j) = {corr_delta_resid_item:+.4f}")
        print(f"  corr(delta_j, sum_resid)    = {corr_delta_sum_resid:+.4f}")
        print(f"  P(cov(delta_j, sum_resid) > 0) = {cov_delta_sum_resid_pos_prob:.4f}")

        # Codex's falsification criteria
        passes = {
            "corr_delta_resid_pos": corr_delta_resid_item > 0,
            "corr_delta_sumresid_pos": corr_delta_sum_resid > 0,
            "cov_sum_pos_prob_90": cov_delta_sum_resid_pos_prob >= 0.90,
            "MAE_not_worse": decomp_corr['MAE'] <= decomp_base['MAE'] + 0.01,
            "r_lift_positive": (decomp_corr['r'] - decomp_base['r']) > 0,
        }
        verdict = "REAL_SIGNAL" if all(passes.values()) else "CALIBRATION_ARTIFACT_OR_PARTIAL"
        n_passes = sum(passes.values())
        print(f"  Codex criteria: {n_passes}/5 pass  → {verdict}")
        for k, v in passes.items():
            print(f"    {'✓' if v else '✗'} {k}")

        audit["items"][item_num] = {
            "family": family, "alpha": alpha,
            "baseline": decomp_base, "corrected": decomp_corr,
            "delta_ccc": float(decomp_corr['ccc'] - decomp_base['ccc']),
            "delta_r": float(decomp_corr['r'] - decomp_base['r']),
            "delta_C_b": float(decomp_corr['C_b'] - decomp_base['C_b']),
            "delta_MAE": float(decomp_corr['MAE'] - decomp_base['MAE']),
            "delta_RMSE": float(decomp_corr['RMSE'] - decomp_base['RMSE']),
            "corr_delta_resid_item": corr_delta_resid_item,
            "corr_delta_sum_resid": corr_delta_sum_resid,
            "cov_delta_sum_resid_pos_prob": cov_delta_sum_resid_pos_prob,
            "codex_falsification_passes": passes,
            "n_passes": n_passes,
            "verdict": verdict,
        }

    # Save
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(f"results/d4_variance_compression_audit_{ts}.json")
    out.write_text(json.dumps(audit, indent=2, default=float) + "\n")
    print(f"\n→ wrote {out}")

    # Summary
    print("\n" + "=" * 80)
    print("D4 VERDICT SUMMARY")
    print("=" * 80)
    for item_num, m in audit["items"].items():
        print(f"  item {item_num}: ΔCCC={m['delta_ccc']:+.4f}  Δr={m['delta_r']:+.4f}  ΔC_b={m['delta_C_b']:+.4f}  ΔMAE={m['delta_MAE']:+.4f}  →  {m['verdict']}  ({m['n_passes']}/5)")

    return audit


if __name__ == "__main__":
    main()
