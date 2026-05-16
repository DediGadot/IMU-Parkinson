"""Score candidate feature blocks via pdCor + ΔI_imb against canonical OOF.

Loads:
  - T1 iter34 OOF (per-item NPZ) — t1_sum_pred, items 9-14 (each leak-clean)
  - T3 iter47 OOF (subject-preds CSV, filter stage2_current + drop_allmissing_validrange)
  - V2 baseline (ablation_v3_features.csv)
  - One or more candidate caches via --feature path1.csv,path2.csv,...

Computes:
  - Per-fold pdCor(F; y | yhat_canonical_OOF)
  - Per-fold ΔI_imb(V2 → y) − I_imb(V2+F → y)
  - Bootstrap CIs + cohort permutation p-value

Outputs:
  - results/metric_score_<target>_<feature_tag>_<UTC>.json
  - One row added to results/metric_score_index.csv

Also runs a secondary downstream sanity check via fold-local Ridge meta-stack
on canonical-OOF residuals — purely diagnostic, NOT the headline.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import (
    align_features_to_oof,
    bootstrap_ci,
    distance_correlation,
    information_imbalance,
    euclidean_distances,
    load_t1_canonical_oof,
    load_t3_canonical_oof,
    partial_distance_correlation,
    permutation_pvalue_pdcor,
    score_feature_block,
)
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from sklearn.linear_model import Ridge


RESULTS_DIR = REPO_ROOT / "results"


def load_v2_baseline(sids_target: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Load V2 features aligned to OOF sids. NaN-safe."""
    df = pd.read_csv("results/ablation_v3_features.csv")
    drop_cols = {"sid", "updrs3", "hy", "obs_subscore"}
    feat_cols = [c for c in df.columns if c not in drop_cols]
    df_idx = df.set_index(df["sid"].astype(str))
    rows = []
    for sid in sids_target:
        sid = str(sid)
        if sid in df_idx.index:
            rows.append(df_idx.loc[sid, feat_cols].to_numpy(np.float64))
        else:
            rows.append(np.full(len(feat_cols), np.nan))
    X = np.vstack(rows)
    # NaN-safe column-median fill (using ALL rows for the median — diagnostic baseline only)
    col_med = np.nanmedian(X, axis=0)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(col_med, inds[1])
    return X, feat_cols


def downstream_ridge_sanity(F: np.ndarray, y: np.ndarray, yhat_oof: np.ndarray, alpha: float = 10.0) -> dict:
    """Diagnostic only: leave-one-out Ridge regression on canonical-OOF residuals.

    For each i, train Ridge on (F[~i], residual[~i]) where residual = y - yhat_oof,
    then predict residual[i]. Add to yhat_oof[i]. Returns CCC of (yhat_oof + corrections) vs y.
    """
    n = len(y)
    residual = y - yhat_oof
    correction = np.zeros(n)
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask])
        F_tr = imp.transform(F[mask])
        F_te = imp.transform(F[i:i+1])
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        ridge = Ridge(alpha=alpha, random_state=42)
        ridge.fit(F_tr, residual[mask])
        correction[i] = float(ridge.predict(F_te)[0])
    yhat_stacked = yhat_oof + correction
    return {
        "baseline_metrics": full_metrics(y, yhat_oof, "canonical_oof"),
        "stacked_metrics": full_metrics(y, yhat_stacked, "canonical_oof_plus_F_ridge"),
        "delta_ccc": float(full_metrics(y, yhat_stacked, "")["ccc"] - full_metrics(y, yhat_oof, "")["ccc"]),
    }


def score_feature_file(feature_csv: str, target: str, feature_tag: str | None = None) -> dict:
    """Main scoring entrypoint. Returns a result dict and writes a JSON."""
    feature_csv = Path(feature_csv)
    if not feature_csv.exists():
        return {"error": f"feature_csv not found: {feature_csv}"}

    # Load canonical OOF
    if target == "t1":
        sids_oof, y, yhat_oof = load_t1_canonical_oof()
    elif target == "t3":
        sids_oof, y, yhat_oof = load_t3_canonical_oof()
    else:
        return {"error": f"unknown target {target}"}

    # Align features to OOF
    feat_df = pd.read_csv(feature_csv)
    sid_col = "sid" if "sid" in feat_df.columns else feat_df.columns[0]
    feat_df = feat_df.sort_values(sid_col).drop_duplicates(subset=[sid_col])
    # Keep only numeric columns
    drop_cols = {sid_col, "n_tasks"}
    feat_cols = [c for c in feat_df.columns if c not in drop_cols and pd.api.types.is_numeric_dtype(feat_df[c])]
    feat_df = feat_df[[sid_col] + feat_cols]
    F, mask = align_features_to_oof(feat_df, sids_oof, sid_col=sid_col)

    # Load V2 baseline aligned to same sids
    V2, v2_cols = load_v2_baseline(sids_oof)

    # Score: pdCor + ΔI_imb fold-locally
    print(f"[score] target={target} feature={feature_csv.name} N={len(sids_oof)} d_F={F.shape[1]} d_V2={V2.shape[1]}", flush=True)
    t0 = time.time()
    metric_result = score_feature_block(F=F, y=y, yhat_canonical_oof=yhat_oof, V2=V2, n_folds=len(sids_oof))
    metric_result["scoring_seconds"] = float(time.time() - t0)
    metric_result["n_subjects_aligned"] = int(mask.sum())
    metric_result["n_subjects_missing_features"] = int((~mask).sum())
    metric_result["feature_dim"] = int(F.shape[1])
    metric_result["v2_dim"] = int(V2.shape[1])

    # Secondary diagnostic: downstream Ridge sanity stack
    print(f"[score] running downstream Ridge sanity (alpha=10)...", flush=True)
    sanity = downstream_ridge_sanity(F, y, yhat_oof, alpha=10.0)
    metric_result["downstream_ridge_sanity"] = sanity

    # Per-feature marginal pdCor (rank individual columns)
    print(f"[score] computing per-column marginal dCor for ranking...", flush=True)
    marginal_dcor = []
    for j, name in enumerate(feat_cols):
        try:
            dc = distance_correlation(F[:, j], y)
            pdc = partial_distance_correlation(F[:, j], y, yhat_oof)
            marginal_dcor.append({"col": name, "dcor": dc, "pdcor_cond_oof": pdc})
        except Exception:
            marginal_dcor.append({"col": name, "dcor": None, "pdcor_cond_oof": None})
    marginal_dcor.sort(key=lambda x: (x["pdcor_cond_oof"] or 0), reverse=True)
    metric_result["top_columns_by_pdcor"] = marginal_dcor[:20]
    metric_result["bottom_columns_by_pdcor"] = marginal_dcor[-10:]

    return metric_result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", required=True, help="Path(s) to feature CSV (comma-separated for stack)")
    ap.add_argument("--target", required=True, choices=["t1", "t3"])
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    feature_paths = [p.strip() for p in args.feature.split(",") if p.strip()]
    if len(feature_paths) == 1:
        result = score_feature_file(feature_paths[0], args.target, feature_tag=args.tag)
        tag = args.tag or Path(feature_paths[0]).stem
    else:
        # Stack: concat all features after aligning to oof sids
        result = {"stacked": True, "members": []}
        # Implement stack by concat
        if args.target == "t1":
            sids_oof, y, yhat_oof = load_t1_canonical_oof()
        else:
            sids_oof, y, yhat_oof = load_t3_canonical_oof()
        V2, _ = load_v2_baseline(sids_oof)
        F_list = []
        for fp in feature_paths:
            feat_df = pd.read_csv(fp)
            sid_col = "sid" if "sid" in feat_df.columns else feat_df.columns[0]
            feat_df = feat_df.sort_values(sid_col).drop_duplicates(subset=[sid_col])
            drop_cols = {sid_col, "n_tasks"}
            feat_cols = [c for c in feat_df.columns if c not in drop_cols and pd.api.types.is_numeric_dtype(feat_df[c])]
            feat_df = feat_df[[sid_col] + feat_cols]
            F, _ = align_features_to_oof(feat_df, sids_oof, sid_col=sid_col)
            F_list.append(F)
            result["members"].append({"path": fp, "d": F.shape[1]})
        F_all = np.hstack(F_list)
        r = score_feature_block(F_all, y, yhat_oof, V2, n_folds=len(sids_oof))
        r["downstream_ridge_sanity"] = downstream_ridge_sanity(F_all, y, yhat_oof, alpha=10.0)
        r["stacked_feature_dim"] = F_all.shape[1]
        result.update(r)
        tag = args.tag or "stacked_" + "_".join(Path(fp).stem for fp in feature_paths)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"metric_score_{args.target}_{tag}_{ts}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str) + "\n")

    # Append to index
    index_path = RESULTS_DIR / "metric_score_index.csv"
    row = {
        "ts": ts,
        "target": args.target,
        "tag": tag,
        "feature_file": ",".join(feature_paths),
        "n": result.get("n_subjects_aligned", result.get("n_folds")),
        "pdcor_median": result.get("pdcor_median"),
        "pdcor_ci_lo": result.get("pdcor_ci_lower"),
        "pdcor_ci_hi": result.get("pdcor_ci_upper"),
        "delta_iimb_median": result.get("delta_iimb_median"),
        "delta_iimb_ci_lo": result.get("delta_iimb_ci_lower"),
        "cohort_pdcor": result.get("cohort_pdcor"),
        "cohort_perm_p": result.get("cohort_perm_pvalue"),
        "pdcor_passes": result.get("decision_pdcor_ci_excludes_zero"),
        "perm_passes": result.get("decision_perm_p_lt_001"),
        "delta_iimb_passes": result.get("decision_delta_iimb_ci_excludes_zero"),
        "downstream_baseline_ccc": result.get("downstream_ridge_sanity", {}).get("baseline_metrics", {}).get("ccc"),
        "downstream_stacked_ccc": result.get("downstream_ridge_sanity", {}).get("stacked_metrics", {}).get("ccc"),
        "downstream_delta_ccc": result.get("downstream_ridge_sanity", {}).get("delta_ccc"),
    }
    if index_path.exists():
        idx_df = pd.read_csv(index_path)
        idx_df = pd.concat([idx_df, pd.DataFrame([row])], ignore_index=True)
    else:
        idx_df = pd.DataFrame([row])
    idx_df.to_csv(index_path, index=False)

    # Pretty-print headline
    print("\n" + "=" * 80)
    print(f"RESULT: {tag} @ {args.target}")
    print(f"  pdCor median: {result.get('pdcor_median', 'NA'):+.4f}  95% CI [{result.get('pdcor_ci_lower','NA'):+.4f}, {result.get('pdcor_ci_upper','NA'):+.4f}]")
    print(f"  cohort pdCor: {result.get('cohort_pdcor', 'NA'):+.4f}  perm p={result.get('cohort_perm_pvalue', 'NA'):.4f}")
    print(f"  ΔI_imb median: {result.get('delta_iimb_median', 'NA'):+.4f}  95% CI [{result.get('delta_iimb_ci_lower','NA'):+.4f}, {result.get('delta_iimb_ci_upper','NA'):+.4f}]")
    sanity = result.get("downstream_ridge_sanity", {})
    print(f"  Downstream ΔCCC (Ridge α=10): {sanity.get('delta_ccc', 'NA'):+.4f}")
    print(f"  PASS criteria: pdCor={result.get('decision_pdcor_ci_excludes_zero')}, perm_p<0.01={result.get('decision_perm_p_lt_001')}, ΔI_imb={result.get('decision_delta_iimb_ci_excludes_zero')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
