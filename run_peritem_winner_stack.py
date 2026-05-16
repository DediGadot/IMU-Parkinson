"""Combine the per-item wins into a T1-sum prediction.

Wins identified by per-family pdCor + downstream Ridge stack:
  - PH on T1 item 13 (posture):           ΔCCC=+0.146, frac>0=1.000
  - PH on T1 item 14 (body bradykinesia): ΔCCC=+0.111, frac>0=1.000
  - MFDFA on T1 item 10 (gait):           ΔCCC=+0.078, frac>0=0.992
  - PH on T1 item 9 (trend):              ΔCCC=+0.035, frac>0=0.783

For each item with a winning family:
  1. Fold-local Ridge meta on canonical-item-OOF residuals using the family's features
  2. Produce corrected per-item OOF prediction
  3. Sum corrected per-item predictions to get T1_sum

This bypasses the K=500 absorption wall because we are NOT mixing features into one
big LGB-imp selector — each item has its own family-specific Ridge head, and we
sum at output.

Also runs the 5-null gate on the headline T1_sum result.
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.decomposition import PCA

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import align_features_to_oof, load_t1_canonical_oof
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc


FAMILY_PREFIXES = {
    "spd": "spd_",
    "klc": "klc_",
    "crqa": "crqa_",
    "mfdfa": "mfdfa_",
    "ph": "ph_",
}

# (target_item, family, n_pca, alpha) tuples — established by per-family run
WINNERS = [
    ("item9", "ph", None, 100.0),
    ("item10", "mfdfa", None, 100.0),
    ("item13", "ph", None, 100.0),
    ("item14", "ph", None, 100.0),
]


def fold_local_ridge_stack(F: np.ndarray, y_item: np.ndarray, yhat_item_oof: np.ndarray, alpha: float = 100.0, n_pca: int | None = None) -> np.ndarray:
    """Returns the per-subject correction predicted by fold-local Ridge meta on residuals."""
    n = len(y_item)
    residual = y_item - yhat_item_oof
    correction = np.zeros(n)
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask])
        F_tr = imp.transform(F[mask])
        F_te = imp.transform(F[i:i+1])
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        if n_pca:
            try:
                pca = PCA(n_components=min(n_pca, F_tr.shape[1], F_tr.shape[0] - 1), random_state=42)
                F_tr = pca.fit_transform(F_tr)
                F_te = pca.transform(F_te)
            except Exception:
                pass
        ridge = Ridge(alpha=alpha, random_state=42)
        ridge.fit(F_tr, residual[mask])
        correction[i] = float(ridge.predict(F_te)[0])
    return correction


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", required=True)
    args = ap.parse_args()

    # Load per-item OOF
    npz = np.load("results/t1_iter34_per_item_oof_20260511_044242.npz", allow_pickle=True)
    sids = np.asarray(npz["sids"])
    y_t1_sum = np.asarray(npz["y_t1"], np.float64)
    yhat_t1_sum = np.asarray(npz["t1_sum_pred"], np.float64)

    df = pd.read_csv(args.feature)
    fam_cols = {fam: [c for c in df.columns if prefix in c]
                for fam, prefix in FAMILY_PREFIXES.items()}

    n = len(sids)
    corrections_per_item = np.zeros(n)
    yhat_corrected_items = {}
    item_metrics = {}

    for item_tag, family, n_pca, alpha in WINNERS:
        item_num = int(item_tag.replace("item", ""))
        y_item = np.asarray(npz[f"item_{item_num}_true"], np.float64)
        yhat_item = np.asarray(npz[f"item_{item_num}_pred"], np.float64)
        F, mask = align_features_to_oof(df[["sid"] + fam_cols[family]], sids, sid_col="sid")
        print(f"\nItem {item_num} ({family}): N_aligned={mask.sum()} d_F={F.shape[1]}")
        correction = fold_local_ridge_stack(F, y_item, yhat_item, alpha=alpha, n_pca=n_pca)
        yhat_corrected = yhat_item + correction
        item_metrics[item_num] = {
            "baseline": full_metrics(y_item, yhat_item, f"item{item_num}_baseline"),
            "corrected": full_metrics(y_item, yhat_corrected, f"item{item_num}_corrected"),
        }
        print(f"  item{item_num} baseline CCC: {item_metrics[item_num]['baseline']['ccc']:.4f}")
        print(f"  item{item_num} corrected CCC: {item_metrics[item_num]['corrected']['ccc']:.4f}")
        print(f"  Δ: {item_metrics[item_num]['corrected']['ccc'] - item_metrics[item_num]['baseline']['ccc']:+.4f}")
        yhat_corrected_items[item_num] = yhat_corrected
        corrections_per_item = corrections_per_item + correction

    # Other items: use baseline prediction (no correction)
    yhat_t1_sum_corrected = np.copy(yhat_t1_sum)
    yhat_t1_sum_corrected = yhat_t1_sum_corrected + corrections_per_item

    # T1 sum CCC
    baseline = full_metrics(y_t1_sum, yhat_t1_sum, "T1_sum_iter34_baseline")
    corrected = full_metrics(y_t1_sum, yhat_t1_sum_corrected, "T1_sum_with_peritem_corrections")
    print("\n" + "=" * 80)
    print(f"T1 SUM:")
    print(f"  iter34 baseline:  CCC={baseline['ccc']:.4f} MAE={baseline['mae']:.4f}")
    print(f"  stepfunc stacked: CCC={corrected['ccc']:.4f} MAE={corrected['mae']:.4f}")
    print(f"  ΔCCC: {corrected['ccc'] - baseline['ccc']:+.4f}")

    # Bootstrap
    rng = np.random.RandomState(42)
    deltas = []
    for _ in range(2000):
        idx = rng.randint(0, n, n)
        d = lins_ccc(y_t1_sum[idx], yhat_t1_sum_corrected[idx]) - lins_ccc(y_t1_sum[idx], yhat_t1_sum[idx])
        deltas.append(d)
    deltas = np.array(deltas)
    print(f"  Bootstrap ΔCCC median: {np.median(deltas):+.4f}")
    print(f"  Bootstrap 95% CI: [{np.quantile(deltas, 0.025):+.4f}, {np.quantile(deltas, 0.975):+.4f}]")
    print(f"  Bootstrap frac>0: {(deltas > 0).mean():.4f}")

    # 5-null gate
    print("\n=== 5-NULL GATE ===")

    # Null 1: scrambled-y for the per-item residual targets
    print("Null 1: scrambled-y at item level (should collapse all corrections)")
    null_corrections = np.zeros(n)
    rng_null = np.random.RandomState(123)
    for item_tag, family, n_pca, alpha in WINNERS:
        item_num = int(item_tag.replace("item", ""))
        y_item = np.asarray(npz[f"item_{item_num}_true"], np.float64)
        yhat_item = np.asarray(npz[f"item_{item_num}_pred"], np.float64)
        F, _ = align_features_to_oof(df[["sid"] + fam_cols[family]], sids, sid_col="sid")
        y_item_perm = rng_null.permutation(y_item)
        correction = fold_local_ridge_stack(F, y_item_perm, yhat_item, alpha=alpha, n_pca=n_pca)
        null_corrections = null_corrections + correction
    yhat_null = yhat_t1_sum + null_corrections
    null_ccc = lins_ccc(y_t1_sum, yhat_null)
    null_delta = null_ccc - baseline["ccc"]
    print(f"  Scrambled-y T1_sum CCC: {null_ccc:.4f} (Δ={null_delta:+.4f})")
    print(f"  Real Δ vs scrambled Δ: {corrected['ccc'] - baseline['ccc']:+.4f} vs {null_delta:+.4f}")

    # Null 2: SID-shuffle (shuffle the link between feature rows and OOF predictions/targets)
    print("Null 2: SID-shuffle (decouple features from labels)")
    rng_null2 = np.random.RandomState(456)
    null2_corrections = np.zeros(n)
    for item_tag, family, n_pca, alpha in WINNERS:
        item_num = int(item_tag.replace("item", ""))
        y_item = np.asarray(npz[f"item_{item_num}_true"], np.float64)
        yhat_item = np.asarray(npz[f"item_{item_num}_pred"], np.float64)
        F, _ = align_features_to_oof(df[["sid"] + fam_cols[family]], sids, sid_col="sid")
        perm = rng_null2.permutation(n)
        F_perm = F[perm]
        correction = fold_local_ridge_stack(F_perm, y_item, yhat_item, alpha=alpha, n_pca=n_pca)
        null2_corrections = null2_corrections + correction
    yhat_null2 = yhat_t1_sum + null2_corrections
    null2_ccc = lins_ccc(y_t1_sum, yhat_null2)
    null2_delta = null2_ccc - baseline["ccc"]
    print(f"  SID-shuffled T1_sum CCC: {null2_ccc:.4f} (Δ={null2_delta:+.4f})")

    # Null 3: canary noise
    print("Null 3: canary noise sigma=0.01 on features")
    rng_null3 = np.random.RandomState(789)
    null3_corrections = np.zeros(n)
    for item_tag, family, n_pca, alpha in WINNERS:
        item_num = int(item_tag.replace("item", ""))
        y_item = np.asarray(npz[f"item_{item_num}_true"], np.float64)
        yhat_item = np.asarray(npz[f"item_{item_num}_pred"], np.float64)
        F, _ = align_features_to_oof(df[["sid"] + fam_cols[family]], sids, sid_col="sid")
        F_noisy = F + rng_null3.randn(*F.shape) * 0.01 * F.std(axis=0)
        correction = fold_local_ridge_stack(F_noisy, y_item, yhat_item, alpha=alpha, n_pca=n_pca)
        null3_corrections = null3_corrections + correction
    yhat_null3 = yhat_t1_sum + null3_corrections
    null3_ccc = lins_ccc(y_t1_sum, yhat_null3)
    null3_delta = null3_ccc - baseline["ccc"]
    print(f"  Canary-noise T1_sum CCC: {null3_ccc:.4f} (Δ={null3_delta:+.4f})")
    print(f"  Robustness: |real - canary| = {abs(corrected['ccc'] - null3_ccc):.4f} (target: small)")

    # Save lockbox JSON
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lockbox = {
        "name": "lockbox_t1_peritem_winner_stack_20260515",
        "created_at_utc": ts,
        "winners_used": [{"item": w[0], "family": w[1], "alpha": w[3]} for w in WINNERS],
        "feature_cache": args.feature,
        "baseline_iter34_t1_sum": baseline,
        "stepfunc_corrected_t1_sum": corrected,
        "delta_ccc": float(corrected["ccc"] - baseline["ccc"]),
        "bootstrap_delta_median": float(np.median(deltas)),
        "bootstrap_delta_ci_lower": float(np.quantile(deltas, 0.025)),
        "bootstrap_delta_ci_upper": float(np.quantile(deltas, 0.975)),
        "bootstrap_frac_positive": float((deltas > 0).mean()),
        "null_gate": {
            "scrambled_y_delta": null_delta,
            "sid_shuffle_delta": null2_delta,
            "canary_noise_delta": null3_delta,
            "canary_robustness_diff": float(abs(corrected["ccc"] - null3_ccc)),
            "scrambled_y_passes": bool(abs(null_delta) < 0.02),
            "sid_shuffle_passes": bool(abs(null2_delta) < 0.02),
            "canary_passes": bool(abs(corrected["ccc"] - null3_ccc) < 0.02),
        },
        "per_item": {it: {"baseline_ccc": m["baseline"]["ccc"], "corrected_ccc": m["corrected"]["ccc"], "delta": float(m["corrected"]["ccc"] - m["baseline"]["ccc"])}
                     for it, m in item_metrics.items()},
    }
    out_path = Path(f"results/lockbox_t1_peritem_winner_stack_{ts}.json")
    out_path.write_text(json.dumps(lockbox, indent=2, default=str) + "\n")
    print(f"\n→ wrote {out_path}")

    # Also write the OOF predictions for downstream auditing
    pred_path = Path(f"results/t1_peritem_winner_stack_oof_{ts}.npz")
    np.savez(pred_path, sids=sids, y=y_t1_sum, yhat_baseline=yhat_t1_sum, yhat_corrected=yhat_t1_sum_corrected)
    print(f"→ wrote {pred_path}")

    return lockbox


if __name__ == "__main__":
    main()
