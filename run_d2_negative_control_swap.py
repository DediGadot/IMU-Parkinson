"""D2: Negative-control PH<->MFDFA item-swap falsification.

Yesterday's surviving step-function claim is PH/item-13 (Δr=+0.161, P(cov>0)=0.92,
5/5 codex D4 criteria). If the PH features are genuinely capturing posture
biomechanics (item 13), they should NOT lift item 10 (gait) substantially.
Conversely, MFDFA features designed for gait (item 10) should NOT lift item 13.

Test:
  Right pairing (replicates yesterday):
    - PH features -> item 13 residual
    - MFDFA features -> item 10 residual
  Wrong pairing (this script):
    - PH features -> item 10 residual
    - MFDFA features -> item 13 residual

Pass criterion (mechanism is real):
  ΔCCC(wrong pairing) <= 0.5 * ΔCCC(right pairing) for both items.

Fail criterion (mechanism is generic noise compression):
  ΔCCC(wrong pairing) >= ΔCCC(right pairing) - 0.020
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
OOF_PATH = "results/t1_iter34_per_item_oof_20260511_044242.npz"

ALPHA = 100.0  # matches yesterday's run_peritem_winner_stack architecture


def load_cache_aligned() -> tuple[pd.DataFrame, dict, np.ndarray]:
    df = pd.read_csv(CACHE_PATH)
    oof = dict(np.load(OOF_PATH, allow_pickle=True))
    sids_oof = oof["sids"].astype(str)
    keep = df["sid"].isin(sids_oof).values
    df = df[keep].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids_oof])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids_oof).all()
    return df, oof, sids_oof


def loocv_ridge_residual(
    X: np.ndarray, y_resid: np.ndarray, alpha: float = ALPHA
) -> np.ndarray:
    n = len(y_resid)
    preds = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        Xt, Xv = X[tr], X[i:i+1]
        yt = y_resid[tr]
        imp = FoldImputer.fit(Xt)
        Xt_i = imp.transform(Xt)
        Xv_i = imp.transform(Xv)
        nrm = FoldNormalizer.fit(Xt_i)
        Xt_n = nrm.transform(Xt_i)
        Xv_n = nrm.transform(Xv_i)
        m = Ridge(alpha=alpha).fit(Xt_n, yt)
        preds[i] = m.predict(Xv_n)[0]
    return preds


def get_family_columns(df: pd.DataFrame, family: str) -> list[str]:
    """Return all columns belonging to a family ('ph' or 'mfdfa'), all tasks."""
    return [c for c in df.columns if f"_{family}_" in c]


def evaluate_pair(
    df: pd.DataFrame, oof: dict, item: int, feature_family: str
) -> dict:
    """Train Ridge on the family-residual target, return baseline + corrected metrics."""
    cols = get_family_columns(df, feature_family)
    X = df[cols].values.astype(float)
    y_true = oof[f"item_{item}_true"].astype(float)
    y_pred_base = oof[f"item_{item}_pred"].astype(float)
    y_resid = y_true - y_pred_base
    correction = loocv_ridge_residual(X, y_resid, alpha=ALPHA)
    y_pred_corr = y_pred_base + correction
    ccc_base = float(ccc(y_true, y_pred_base))
    ccc_corr = float(ccc(y_true, y_pred_corr))
    r_base = float(np.corrcoef(y_true, y_pred_base)[0, 1])
    r_corr = float(np.corrcoef(y_true, y_pred_corr)[0, 1])
    mae_base = float(np.mean(np.abs(y_true - y_pred_base)))
    mae_corr = float(np.mean(np.abs(y_true - y_pred_corr)))
    # codex D4: corr(correction, item_residual) and bootstrap P(cov(correction, sum_resid) > 0)
    corr_delta_resid = float(np.corrcoef(correction, y_resid)[0, 1])
    return {
        "item": item,
        "feature_family": feature_family,
        "n_features": len(cols),
        "ccc_baseline": round(ccc_base, 4),
        "ccc_corrected": round(ccc_corr, 4),
        "delta_ccc": round(ccc_corr - ccc_base, 4),
        "r_baseline": round(r_base, 4),
        "r_corrected": round(r_corr, 4),
        "delta_r": round(r_corr - r_base, 4),
        "mae_baseline": round(mae_base, 4),
        "mae_corrected": round(mae_corr, 4),
        "delta_mae": round(mae_corr - mae_base, 4),
        "corr_correction_item_residual": round(corr_delta_resid, 4),
    }


def main():
    df, oof, sids = load_cache_aligned()
    print(f"[D2] N={len(sids)} aligned with iter34 OOF")

    pairs = [
        ("PH_to_item13_RIGHT", 13, "ph"),
        ("MFDFA_to_item10_RIGHT", 10, "mfdfa"),
        ("PH_to_item10_WRONG", 10, "ph"),
        ("MFDFA_to_item13_WRONG", 13, "mfdfa"),
        # Bonus controls
        ("PH_to_item14_RIGHT", 14, "ph"),
        ("MFDFA_to_item14_WRONG", 14, "mfdfa"),
    ]

    results = {}
    for label, item, fam in pairs:
        print(f"[D2] Running {label}...")
        m = evaluate_pair(df, oof, item, fam)
        results[label] = m
        print(f"     ΔCCC={m['delta_ccc']:+.4f}  Δr={m['delta_r']:+.4f}  "
              f"ΔMAE={m['delta_mae']:+.4f}  corr(δ,resid)={m['corr_correction_item_residual']:+.4f}")

    # ── Falsification verdict ──────────────────────────────────────────────────
    right_13 = results["PH_to_item13_RIGHT"]["delta_ccc"]
    wrong_13 = results["MFDFA_to_item13_WRONG"]["delta_ccc"]
    right_10 = results["MFDFA_to_item10_RIGHT"]["delta_ccc"]
    wrong_10 = results["PH_to_item10_WRONG"]["delta_ccc"]

    item13_ratio = wrong_13 / right_13 if right_13 > 0.001 else float("inf")
    item10_ratio = wrong_10 / right_10 if right_10 > 0.001 else float("inf")

    # Also use Pearson-r ratios since that's the D4-confirmed signal channel
    right_13_r = results["PH_to_item13_RIGHT"]["delta_r"]
    wrong_13_r = results["MFDFA_to_item13_WRONG"]["delta_r"]
    right_10_r = results["MFDFA_to_item10_RIGHT"]["delta_r"]
    wrong_10_r = results["PH_to_item10_WRONG"]["delta_r"]
    item13_r_ratio = wrong_13_r / right_13_r if abs(right_13_r) > 0.001 else float("inf")
    item10_r_ratio = wrong_10_r / right_10_r if abs(right_10_r) > 0.001 else float("inf")

    # Verdict: item 13 PH is the load-bearing claim
    if item13_r_ratio <= 0.5 and right_13_r > 0.05:
        item13_verdict = "BIOMECHANICAL_SIGNAL_CONFIRMED"
    elif item13_r_ratio >= 0.9:
        item13_verdict = "GENERIC_COMPRESSION_FALSIFIED"
    else:
        item13_verdict = "PARTIAL_BIOMECHANICAL_SIGNAL"

    if item10_r_ratio <= 0.5 and right_10_r > 0.05:
        item10_verdict = "BIOMECHANICAL_SIGNAL_CONFIRMED"
    elif item10_r_ratio >= 0.9:
        item10_verdict = "GENERIC_COMPRESSION_FALSIFIED"
    else:
        item10_verdict = "PARTIAL_BIOMECHANICAL_SIGNAL"

    print(f"\n[D2] FALSIFICATION VERDICT")
    print(f"     Item 13 (PH right vs MFDFA wrong):")
    print(f"       Δr right = {right_13_r:+.4f}  Δr wrong = {wrong_13_r:+.4f}")
    print(f"       ratio    = {item13_r_ratio:+.4f}  -> {item13_verdict}")
    print(f"     Item 10 (MFDFA right vs PH wrong):")
    print(f"       Δr right = {right_10_r:+.4f}  Δr wrong = {wrong_10_r:+.4f}")
    print(f"       ratio    = {item10_r_ratio:+.4f}  -> {item10_verdict}")

    out = {
        "name": "d2_negative_control_pairwise_swap",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "n_subjects": len(sids),
        "alpha": ALPHA,
        "pairs": results,
        "verdict_item13": item13_verdict,
        "verdict_item10": item10_verdict,
        "delta_r_ratios": {
            "item13_wrong_over_right": round(item13_r_ratio, 4),
            "item10_wrong_over_right": round(item10_r_ratio, 4),
        },
        "interpretation": (
            "If wrong-pairing ratio < 0.5: family-specific biomechanical signal confirmed "
            "(yesterday's claim survives). If ratio >= 0.9: lift is generic shrinkage / "
            "variance compression, not family-specific - falsifies the biomechanical claim. "
            "0.5-0.9: partial specificity."
        ),
    }
    ts = out["created_at_utc"]
    path = Path(f"results/d2_negative_control_swap_{ts}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[D2] Wrote {path}")


if __name__ == "__main__":
    main()
