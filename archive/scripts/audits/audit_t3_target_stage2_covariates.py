#!/usr/bin/env python3
"""Audit T3 target construction and hidden Stage-2 clinical covariates.

This is an evidence-producing audit, not a new headline experiment. It checks:

1. Whether `results/ablation_v3_features.csv:updrs3` matches the raw
   33-subitem MDS-UPDRS Part III sum.
2. How the cached 18-item target decomposition differs from the canonical T3
   target. This matters for per-item composite interpretation.
3. Whether the current iter5 Stage-2 feature pool contains `cv_*` clinical
   covariates, how often they are selected, and what happens in a 5-fold screen
   when Stage 2 is forced to IMU-only by dropping `cv_*` columns.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import DATA_DIR, RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter3 import get_hy_features, load_full_pd_data
from run_t3_iter5_clinical import fit_stage1

ensure_dir(RESULTS_DIR)

V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
PER_ITEM_CACHE = RESULTS_DIR / "per_item_scores.json"
SEEDS = [42, 1337, 7]
CURRENT_A3_COLS = ["cv_yrs", "cv_sex", "cv_dbs"]
ALL_CV_COLS = ["cv_age", "cv_dbs", "cv_ht", "cv_sex", "cv_wt", "cv_yrs"]


def _is_pd(sid: str) -> bool:
    sid = str(sid).upper()
    return sid.startswith("NLS") or sid.startswith("WPD")


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if np.isfinite(val) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _clinical_candidates() -> list[Path]:
    return [
        DATA_DIR / "PD - Demographic+Clinical - datasetV1.csv",
        RESULTS_DIR / "pd_demographic_clinical_v1.csv",
        RESULTS_DIR / "results" / "pd_demographic_clinical_v1.csv",
    ]


def _load_pd_clinical() -> tuple[pd.DataFrame, Path]:
    for path in _clinical_candidates():
        if not path.exists():
            continue
        df = pd.read_csv(path, header=1)
        if "Subject ID" in df.columns:
            return df, path
    raise FileNotFoundError(
        "Could not find PD clinical CSV in DATA_DIR or results/pd_demographic_clinical_v1.csv"
    )


def audit_target() -> tuple[dict, pd.DataFrame]:
    v2 = pd.read_csv(V2_FEATURES)
    v2_pd = v2[v2["sid"].astype(str).map(_is_pd)].copy()
    v2_pd["sid"] = v2_pd["sid"].astype(str)
    v2_pd = v2_pd.set_index("sid")

    clinical, clinical_path = _load_pd_clinical()
    clinical["sid"] = clinical["Subject ID"].astype(str).str.strip()
    clinical = clinical[clinical["sid"].map(_is_pd)].copy()
    u3_cols = [c for c in clinical.columns if str(c).startswith("MDSUPDRS_3-")]
    u3 = clinical[u3_cols].apply(pd.to_numeric, errors="coerce")
    clinical["raw_part3_sum33"] = u3.sum(axis=1, skipna=True)
    clinical["raw_part3_nonmissing"] = u3.notna().sum(axis=1)
    clinical["raw_part3_missing"] = len(u3_cols) - clinical["raw_part3_nonmissing"]

    per_item = json.loads(PER_ITEM_CACHE.read_text())
    rows = []
    for sid, row in v2_pd.iterrows():
        raw_match = clinical[clinical["sid"] == sid]
        raw_sum = np.nan
        raw_nonmissing = np.nan
        raw_missing = np.nan
        if not raw_match.empty:
            raw_sum = float(raw_match.iloc[0]["raw_part3_sum33"])
            raw_nonmissing = int(raw_match.iloc[0]["raw_part3_nonmissing"])
            raw_missing = int(raw_match.iloc[0]["raw_part3_missing"])

        scores = per_item.get(sid, {})
        item_sum18 = float(
            sum(float(scores[str(i)]) for i in range(1, 19) if str(i) in scores)
        ) if scores else np.nan
        n_items18 = int(sum(1 for i in range(1, 19) if str(i) in scores)) if scores else 0

        y = float(row["updrs3"])
        rows.append(
            {
                "sid": sid,
                "feature_updrs3": y,
                "raw_part3_sum33": raw_sum,
                "feature_minus_raw33": y - raw_sum if np.isfinite(raw_sum) else np.nan,
                "raw_part3_nonmissing": raw_nonmissing,
                "raw_part3_missing": raw_missing,
                "cache_item_sum18": item_sum18,
                "feature_minus_cache18": y - item_sum18 if np.isfinite(item_sum18) else np.nan,
                "cache_items_present": n_items18,
            }
        )

    detail = pd.DataFrame(rows).sort_values("sid")
    diff_raw = detail["feature_minus_raw33"].dropna()
    diff_cache = detail["feature_minus_cache18"].dropna()
    summary = {
        "clinical_source": str(clinical_path),
        "n_v2_pd": int(len(v2_pd)),
        "n_raw_clinical_pd": int(len(clinical)),
        "n_part3_raw_columns": int(len(u3_cols)),
        "feature_vs_raw33": {
            "n_compared": int(len(diff_raw)),
            "max_abs_diff": float(np.max(np.abs(diff_raw))) if len(diff_raw) else None,
            "n_nonzero_gt_1e_9": int((np.abs(diff_raw) > 1e-9).sum()),
            "diff_describe": diff_raw.describe().to_dict() if len(diff_raw) else {},
        },
        "missing_raw_part3_subitems_among_v2_pd": {
            "max_missing": int(detail["raw_part3_missing"].max()),
            "subjects_with_any_missing": int((detail["raw_part3_missing"] > 0).sum()),
            "missing_count_hist": {
                str(int(k)): int(v)
                for k, v in detail["raw_part3_missing"].value_counts(dropna=False).sort_index().items()
            },
        },
        "feature_vs_cached_18_item_sum": {
            "n_compared": int(len(diff_cache)),
            "mean_diff": float(diff_cache.mean()) if len(diff_cache) else None,
            "std_diff": float(diff_cache.std()) if len(diff_cache) else None,
            "min_diff": float(diff_cache.min()) if len(diff_cache) else None,
            "max_diff": float(diff_cache.max()) if len(diff_cache) else None,
            "n_nonzero_gt_1e_9": int((np.abs(diff_cache) > 1e-9).sum()),
            "diff_describe": diff_cache.describe().to_dict() if len(diff_cache) else {},
        },
    }
    return summary, detail


def _stage1_matrix(sids: np.ndarray, hy: np.ndarray, extra_cols: list[str]) -> np.ndarray:
    v2 = pd.read_csv(V2_FEATURES).set_index("sid")
    parts = [get_hy_features(hy)]
    for col in extra_cols:
        if col not in v2.columns:
            raise KeyError(f"Missing requested Stage-1 column: {col}")
        parts.append(np.array([v2.loc[s, col] for s in sids], dtype=np.float64).reshape(-1, 1))
    return np.column_stack(parts)


def _filter_stage2(X: np.ndarray, feat_cols: list[str], drop_cv: bool) -> tuple[np.ndarray, list[str]]:
    keep = [
        i for i, col in enumerate(feat_cols)
        if not (drop_cv and str(col).startswith("cv_"))
    ]
    return X[:, keep], [feat_cols[i] for i in keep]


def _kfold_predictions(
    *,
    seed: int,
    stage1_cols: list[str],
    drop_cv_stage2: bool,
) -> tuple[np.ndarray, dict]:
    sids, X_current, feat_cols_current, y_t3, hy, _obs = load_full_pd_data()
    X_s1 = _stage1_matrix(sids, hy, stage1_cols)
    X_s2, feat_cols_s2 = _filter_stage2(X_current, feat_cols_current, drop_cv_stage2)

    preds = np.zeros(len(sids), dtype=np.float64)
    selected_counts: Counter[str] = Counter()
    cv_selected_counts: Counter[str] = Counter()
    splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(len(sids))))
    for tr, te in splits:
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=1.0)
        residual_tr = y_t3[tr] - s1_tr
        Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, idx = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        for j in idx:
            name = feat_cols_s2[int(j)]
            selected_counts[name] += 1
            if name.startswith("cv_"):
                cv_selected_counts[name] += 1
        preds[te] = s1_te + train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)

    selection_summary = {
        "stage2_n_features": int(len(feat_cols_s2)),
        "stage2_cv_features_present": [c for c in feat_cols_s2 if c.startswith("cv_")],
        "selected_cv_feature_counts": dict(sorted(cv_selected_counts.items())),
        "top_selected_features": selected_counts.most_common(20),
    }
    return preds, selection_summary


def audit_stage2_covariates() -> tuple[dict, pd.DataFrame]:
    sids, _X, feat_cols, y_t3, _hy, _obs = load_full_pd_data()
    stage2_cv_cols = [c for c in feat_cols if c.startswith("cv_")]

    variants = {
        "hy_only_stage2_current": {
            "stage1_cols": [],
            "drop_cv_stage2": False,
        },
        "hy_only_stage2_no_cv": {
            "stage1_cols": [],
            "drop_cv_stage2": True,
        },
        "A3_stage1_stage2_current": {
            "stage1_cols": CURRENT_A3_COLS,
            "drop_cv_stage2": False,
        },
        "A3_stage1_stage2_no_cv": {
            "stage1_cols": CURRENT_A3_COLS,
            "drop_cv_stage2": True,
        },
        "all_cv_stage1_stage2_current": {
            "stage1_cols": ALL_CV_COLS,
            "drop_cv_stage2": False,
        },
        "all_cv_stage1_stage2_no_cv": {
            "stage1_cols": ALL_CV_COLS,
            "drop_cv_stage2": True,
        },
    }

    rows = []
    variant_preds: dict[str, list[np.ndarray]] = {name: [] for name in variants}
    selection_by_variant: dict[str, list[dict]] = {name: [] for name in variants}
    for variant_name, cfg in variants.items():
        for seed in SEEDS:
            t0 = time.time()
            preds, sel = _kfold_predictions(seed=seed, **cfg)
            variant_preds[variant_name].append(preds)
            selection_by_variant[variant_name].append(sel)
            rows.append(
                {
                    "variant": variant_name,
                    "seed": seed,
                    "stage1_cols": "+".join(cfg["stage1_cols"]) or "(hy_only)",
                    "drop_cv_stage2": bool(cfg["drop_cv_stage2"]),
                    "ccc": float(ccc_fn(y_t3, preds)),
                    "mae": float(mae_fn(y_t3, preds)),
                    "r": float(pearson_r(y_t3, preds)),
                    "stage2_n_features": sel["stage2_n_features"],
                    "selected_cv_total": int(sum(sel["selected_cv_feature_counts"].values())),
                    "wall_s": round(time.time() - t0, 1),
                }
            )
            print(
                f"  {variant_name:30s} seed={seed} "
                f"CCC={rows[-1]['ccc']:+.4f} MAE={rows[-1]['mae']:.3f} "
                f"selected_cv_total={rows[-1]['selected_cv_total']} "
                f"({rows[-1]['wall_s']}s)",
                flush=True,
            )

    row_df = pd.DataFrame(rows)
    summary_rows = []
    mean_preds_summary = {}
    for variant_name in variants:
        df_v = row_df[row_df["variant"] == variant_name]
        mean_preds = np.mean(np.column_stack(variant_preds[variant_name]), axis=1)
        mean_preds_summary[variant_name] = {
            "ccc_mean_of_seed_preds": float(ccc_fn(y_t3, mean_preds)),
            "mae_mean_of_seed_preds": float(mae_fn(y_t3, mean_preds)),
            "r_mean_of_seed_preds": float(pearson_r(y_t3, mean_preds)),
        }
        cv_counts = Counter()
        for sel in selection_by_variant[variant_name]:
            cv_counts.update(sel["selected_cv_feature_counts"])
        summary_rows.append(
            {
                "variant": variant_name,
                "ccc_mean": float(df_v["ccc"].mean()),
                "ccc_std": float(df_v["ccc"].std(ddof=0)),
                "mae_mean": float(df_v["mae"].mean()),
                "r_mean": float(df_v["r"].mean()),
                "mean_pred_ccc": mean_preds_summary[variant_name]["ccc_mean_of_seed_preds"],
                "selected_cv_counts_all_seeds": dict(sorted(cv_counts.items())),
            }
        )

    summary = {
        "n_subjects": int(len(sids)),
        "stage2_current_n_features": int(len(feat_cols)),
        "stage2_current_cv_columns": stage2_cv_cols,
        "seeds": SEEDS,
        "variants": variants,
        "per_variant": summary_rows,
        "mean_prediction_metrics": mean_preds_summary,
        "interpretation_guardrails": [
            "This is a 5-fold audit screen, not a lockbox headline.",
            "Dropping cv_* from Stage 2 tests whether the current 'V2 residual' pool hides clinical covariates.",
            "If current > no_cv, the canonical iter5 number remains fold-clean but should be described as clinical+IMU with duplicated clinical access, not a pure IMU residual Stage 2.",
            "If no_cv >= current by the promotion gate, a separate pre-registration would be required before any LOOCV claim.",
        ],
    }
    return summary, row_df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip_models", action="store_true", help="Only run target/feature-pool audit.")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=== T3 target + Stage-2 covariate audit ===", flush=True)
    target_summary, target_detail = audit_target()

    stage2_summary = None
    stage2_rows = None
    if not args.skip_models:
        print("\n=== 5-fold Stage-2 covariate screen ===", flush=True)
        stage2_summary, stage2_rows = audit_stage2_covariates()

    out = {
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "audit": "t3_target_stage2_covariates",
        "target_summary": target_summary,
        "stage2_covariate_summary": stage2_summary,
    }
    out_json = RESULTS_DIR / f"t3_target_stage2_covariate_audit_{ts}.json"
    out_target_csv = RESULTS_DIR / f"t3_target_stage2_covariate_audit_target_rows_{ts}.csv"
    target_detail.to_csv(out_target_csv, index=False)
    if stage2_rows is not None:
        out_rows_csv = RESULTS_DIR / f"t3_target_stage2_covariate_audit_stage2_rows_{ts}.csv"
        stage2_rows.to_csv(out_rows_csv, index=False)
        out["stage2_rows_csv"] = str(out_rows_csv)
    else:
        out_rows_csv = None
    out["target_rows_csv"] = str(out_target_csv)
    out_json.write_text(json.dumps(_jsonable(out), indent=2) + "\n")

    print(f"\nWrote {out_json}", flush=True)
    print(f"Wrote {out_target_csv}", flush=True)
    if out_rows_csv is not None:
        print(f"Wrote {out_rows_csv}", flush=True)


if __name__ == "__main__":
    main()
