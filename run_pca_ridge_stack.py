"""PCA-reduced Ridge meta-stack on the step-function feature cache.

Hypothesis: per-family Ridge meta-stacks fail downstream because of dimensionality
(80-480 features at N=92 overfit even at α=100). PCA-reduce to k=2..8 components
per family BEFORE Ridge — this should let metric-identified signal generalize.

For each family + k_pc combination:
  fold-local PCA fit on training fold → project both train + test
  fold-local Ridge α on (pca_train, residual_train) → predict correction

Outputs per (family, target, k_pc) the downstream ΔCCC + bootstrap CI.
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

from metric_lib import align_features_to_oof, load_t1_canonical_oof, load_t3_canonical_oof
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc


FAMILY_PREFIXES = {
    "spd": "spd_",
    "klc": "klc_",
    "crqa": "crqa_",
    "mfdfa": "mfdfa_",
    "ph": "ph_",
}


def stack_pca_ridge(F: np.ndarray, y: np.ndarray, yhat_oof: np.ndarray, n_pc: int, alpha: float = 10.0) -> dict:
    """Fold-local PCA + Ridge LOOCV stack."""
    n = len(y)
    residual = y - yhat_oof
    correction = np.zeros(n)
    for i in range(n):
        mask = np.arange(n) != i
        # Fold-local imputer + normalizer + PCA
        imp = FoldImputer.fit(F[mask])
        F_tr = imp.transform(F[mask])
        F_te = imp.transform(F[i:i+1])
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        try:
            pca = PCA(n_components=min(n_pc, F_tr.shape[1], F_tr.shape[0] - 1), random_state=42)
            Z_tr = pca.fit_transform(F_tr)
            Z_te = pca.transform(F_te)
        except Exception:
            continue
        ridge = Ridge(alpha=alpha, random_state=42)
        ridge.fit(Z_tr, residual[mask])
        correction[i] = float(ridge.predict(Z_te)[0])
    yhat_stacked = yhat_oof + correction
    baseline = full_metrics(y, yhat_oof, "")
    stacked = full_metrics(y, yhat_stacked, "")
    rng = np.random.RandomState(42)
    deltas = []
    for _ in range(1000):
        idx = rng.randint(0, n, n)
        d = lins_ccc(y[idx], yhat_stacked[idx]) - lins_ccc(y[idx], yhat_oof[idx])
        deltas.append(d)
    deltas = np.array(deltas)
    return {
        "n_pc": int(n_pc),
        "baseline_ccc": baseline["ccc"],
        "stacked_ccc": stacked["ccc"],
        "delta_ccc": float(stacked["ccc"] - baseline["ccc"]),
        "delta_ccc_median": float(np.median(deltas)),
        "delta_ccc_ci_lo": float(np.quantile(deltas, 0.025)),
        "delta_ccc_ci_hi": float(np.quantile(deltas, 0.975)),
        "delta_ccc_frac_pos": float((deltas > 0).mean()),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", required=True)
    ap.add_argument("--n-pcs", default="2,4,6,8", help="Comma-separated PCA dims to try")
    ap.add_argument("--alphas", default="1,10,100", help="Comma-separated Ridge alphas")
    args = ap.parse_args()

    n_pcs = [int(x) for x in args.n_pcs.split(",")]
    alphas = [float(x) for x in args.alphas.split(",")]
    df = pd.read_csv(args.feature)

    fam_cols = {fam: [c for c in df.columns if prefix in c]
                for fam, prefix in FAMILY_PREFIXES.items()}
    fam_cols = {k: v for k, v in fam_cols.items() if v}

    # Load OOF
    sids_t1, y_t1, yhat_t1 = load_t1_canonical_oof()
    sids_t3, y_t3, yhat_t3 = load_t3_canonical_oof()
    d_t1_peritem = np.load("results/t1_iter34_per_item_oof_20260511_044242.npz", allow_pickle=True)
    sids_t1_peritem = np.asarray(d_t1_peritem["sids"])
    t1_items = {item: (np.asarray(d_t1_peritem[f"item_{item}_true"], np.float64),
                       np.asarray(d_t1_peritem[f"item_{item}_pred"], np.float64))
                for item in range(9, 15)}

    targets = {
        "t1_sum": (sids_t1, y_t1, yhat_t1),
        "t3": (sids_t3, y_t3, yhat_t3),
    }
    for it in range(9, 15):
        targets[f"t1_item{it}"] = (sids_t1_peritem, *t1_items[it])

    results = []
    for fam, cols in fam_cols.items():
        for tgt_name, (sids, y, yhat) in targets.items():
            F, mask = align_features_to_oof(df[["sid"] + cols], sids, sid_col="sid")
            if mask.sum() < 80 or F.shape[1] < 2:
                continue
            for n_pc in n_pcs:
                for a in alphas:
                    r = stack_pca_ridge(F, y, yhat, n_pc, a)
                    r["family"] = fam
                    r["target"] = tgt_name
                    r["alpha"] = a
                    r["d_F"] = int(F.shape[1])
                    results.append(r)
                    if r["delta_ccc_frac_pos"] > 0.6 or r["delta_ccc"] > 0.005:
                        print(f"  {fam:>6} k={n_pc} a={int(a):>3} → {tgt_name:>12}: ΔCCC={r['delta_ccc']:+.4f} CI=[{r['delta_ccc_ci_lo']:+.4f},{r['delta_ccc_ci_hi']:+.4f}] frac+={r['delta_ccc_frac_pos']:.3f}", flush=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_csv = Path(f"results/pca_ridge_stack_{ts}.csv")
    df_out = pd.DataFrame(results).sort_values("delta_ccc", ascending=False)
    df_out.to_csv(out_csv, index=False)

    # Print top
    print("\n=== TOP 15 BY ΔCCC ===")
    print(df_out.head(15)[["family", "target", "n_pc", "alpha", "delta_ccc", "delta_ccc_ci_lo", "delta_ccc_ci_hi", "delta_ccc_frac_pos"]].to_string(index=False))
    print(f"\n→ wrote {out_csv}")


if __name__ == "__main__":
    main()
