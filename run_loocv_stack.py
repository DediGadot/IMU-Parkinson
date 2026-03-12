"""
PD-only nested LOOCV with the deployable stacking pipeline
==========================================================
This runner exists for literature comparison, but unlike the legacy version it
performs feature selection inside each leave-one-out fold.

Experiments:
  L1: LightGBM only
  L2: LightGBM + XGBoost weighted average
  L3: LightGBM + XGBoost stack with ridge meta-learner
"""
import os
import sys
import time
import warnings
from collections import Counter

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

from project_paths import REPO_ROOT, repo_artifact_path, save_json_artifact

sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split
from run_ablation_v2 import N_CORES


FEATURE_CACHE = str(repo_artifact_path("proven_stack_features.csv"))
SEEDS = [42, 123, 456, 789, 2024]


def load_extended_covariates():
    from run_proven_stack import load_extended_covariates as _load_extended_covariates
    return _load_extended_covariates()


def feature_select(X, y, names, k=150):
    from xgboost import XGBRegressor

    k = min(k, X.shape[1])
    sel = XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        reg_lambda=2.0,
        random_state=42,
        n_jobs=N_CORES,
        objective="reg:absoluteerror",
    )
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def split_train_val(X, y, seed, val_frac=0.15):
    rng = np.random.RandomState(seed)
    idx = np.arange(len(X))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * val_frac))
    return X[idx[nv:]], y[idx[nv:]], X[idx[:nv]], y[idx[:nv]]


def train_lgbm(Xtr, ytr, Xval, yval, Xte, seed=42):
    import lightgbm as lgb

    model = lgb.LGBMRegressor(
        n_estimators=2000,
        learning_rate=0.03,
        max_depth=6,
        reg_lambda=3.0,
        random_state=seed,
        n_jobs=N_CORES,
        objective="mae",
        verbose=-1,
    )
    model.fit(
        Xtr,
        ytr,
        eval_set=[(Xval, yval)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return model.predict(Xte), model


def train_xgb(Xtr, ytr, Xval, yval, Xte, seed=42):
    from xgboost import XGBRegressor

    model = XGBRegressor(
        n_estimators=2000,
        learning_rate=0.03,
        max_depth=6,
        reg_lambda=3.0,
        random_state=seed,
        n_jobs=N_CORES,
        early_stopping_rounds=100,
        objective="reg:absoluteerror",
    )
    model.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)
    return model.predict(Xte), model


def nested_lgb(X_all, y_all, feat_cols, k=150):
    preds = np.zeros(len(y_all))
    feature_counter = Counter()

    for i in range(len(y_all)):
        mask = np.ones(len(y_all), dtype=bool)
        mask[i] = False
        X_train, y_train = X_all[mask], y_all[mask]
        X_test = X_all[i:i + 1]

        sel_idx, sel_names = feature_select(X_train, y_train, feat_cols, k)
        feature_counter.update(sel_names)
        X_train_sel = X_train[:, sel_idx]
        X_test_sel = X_test[:, sel_idx]

        seed_preds = []
        for seed in SEEDS:
            Xtr, ytr, Xv, yv = split_train_val(X_train_sel, y_train, seed)
            pred, _ = train_lgbm(Xtr, ytr, Xv, yv, X_test_sel, seed)
            seed_preds.append(pred[0])
        preds[i] = np.clip(np.mean(seed_preds), 0, 132)

        if (i + 1) % 10 == 0 or i == len(y_all) - 1:
            running_mae = mean_absolute_error(y_all[:i + 1], preds[:i + 1])
            print(f"  L1 {i+1}/{len(y_all)}: running MAE={running_mae:.2f}")

    mae = mean_absolute_error(y_all, preds)
    r, _ = sp_stats.pearsonr(y_all, preds)
    return mae, r, preds, feature_counter


def nested_average(X_all, y_all, feat_cols, k=150):
    preds_avg = np.zeros(len(y_all))
    preds_xgb = np.zeros(len(y_all))
    feature_counter = Counter()

    for i in range(len(y_all)):
        mask = np.ones(len(y_all), dtype=bool)
        mask[i] = False
        X_train, y_train = X_all[mask], y_all[mask]
        X_test = X_all[i:i + 1]

        sel_idx, sel_names = feature_select(X_train, y_train, feat_cols, k)
        feature_counter.update(sel_names)
        X_train_sel = X_train[:, sel_idx]
        X_test_sel = X_test[:, sel_idx]

        seed_avg = []
        seed_xgb = []
        for seed in SEEDS:
            Xtr, ytr, Xv, yv = split_train_val(X_train_sel, y_train, seed)
            p_l, _ = train_lgbm(Xtr, ytr, Xv, yv, X_test_sel, seed)
            p_x, _ = train_xgb(Xtr, ytr, Xv, yv, X_test_sel, seed)
            seed_xgb.append(p_x[0])
            seed_avg.append(0.6 * p_l[0] + 0.4 * p_x[0])

        preds_xgb[i] = np.clip(np.mean(seed_xgb), 0, 132)
        preds_avg[i] = np.clip(np.mean(seed_avg), 0, 132)

        if (i + 1) % 10 == 0 or i == len(y_all) - 1:
            running_mae = mean_absolute_error(y_all[:i + 1], preds_avg[:i + 1])
            print(f"  L2 {i+1}/{len(y_all)}: running MAE={running_mae:.2f}")

    mae_avg = mean_absolute_error(y_all, preds_avg)
    r_avg, _ = sp_stats.pearsonr(y_all, preds_avg)
    mae_xgb = mean_absolute_error(y_all, preds_xgb)
    r_xgb, _ = sp_stats.pearsonr(y_all, preds_xgb)
    return mae_avg, r_avg, preds_avg, mae_xgb, r_xgb, preds_xgb, feature_counter


def nested_stacking(X_all, y_all, feat_cols, k=150):
    preds = np.zeros(len(y_all))
    feature_counter = Counter()

    for i in range(len(y_all)):
        mask = np.ones(len(y_all), dtype=bool)
        mask[i] = False
        X_train, y_train = X_all[mask], y_all[mask]
        X_test = X_all[i:i + 1]

        sel_idx, sel_names = feature_select(X_train, y_train, feat_cols, k)
        feature_counter.update(sel_names)
        X_train_sel = X_train[:, sel_idx]
        X_test_sel = X_test[:, sel_idx]

        seed_preds = []
        for seed in SEEDS:
            inner_folds = min(5, len(X_train_sel))
            kf = KFold(n_splits=inner_folds, shuffle=True, random_state=seed)
            oof_lgb = np.zeros(len(X_train_sel))
            oof_xgb = np.zeros(len(X_train_sel))
            test_lgb = np.zeros(1)
            test_xgb = np.zeros(1)

            for tr_i, val_i in kf.split(X_train_sel):
                Xtr, ytr, Xv, yv = split_train_val(X_train_sel[tr_i], y_train[tr_i], seed + len(tr_i))

                p_l_val, _ = train_lgbm(Xtr, ytr, Xv, yv, X_train_sel[val_i], seed)
                p_l_test, _ = train_lgbm(Xtr, ytr, Xv, yv, X_test_sel, seed)
                oof_lgb[val_i] = p_l_val
                test_lgb += p_l_test / inner_folds

                p_x_val, _ = train_xgb(Xtr, ytr, Xv, yv, X_train_sel[val_i], seed)
                p_x_test, _ = train_xgb(Xtr, ytr, Xv, yv, X_test_sel, seed)
                oof_xgb[val_i] = p_x_val
                test_xgb += p_x_test / inner_folds

            meta = Ridge(alpha=1.0)
            meta.fit(np.column_stack([oof_lgb, oof_xgb]), y_train)
            seed_preds.append(meta.predict(np.column_stack([test_lgb, test_xgb]))[0])

        preds[i] = np.clip(np.mean(seed_preds), 0, 132)

        if (i + 1) % 10 == 0 or i == len(y_all) - 1:
            running_mae = mean_absolute_error(y_all[:i + 1], preds[:i + 1])
            print(f"  L3 {i+1}/{len(y_all)}: running MAE={running_mae:.2f}")

    mae = mean_absolute_error(y_all, preds)
    r, _ = sp_stats.pearsonr(y_all, preds)
    return mae, r, preds, feature_counter


def summarize_feature_counter(counter):
    return [{"feature": name, "count": int(count)} for name, count in counter.most_common(10)]


def main():
    t0 = time.time()
    print("=" * 70)
    print("PD-ONLY NESTED LOOCV WITH STACKING PIPELINE")
    print("=" * 70)

    if not os.path.exists(FEATURE_CACHE):
        print(f"ERROR: feature cache not found: {FEATURE_CACHE}")
        print("Run run_proven_stack.py first.")
        sys.exit(1)

    df = pd.read_csv(FEATURE_CACHE)
    subjects = parse_clinical()
    split = load_split()

    ext_cov = load_extended_covariates()
    ext_names = [
        "ext_height",
        "ext_weight",
        "ext_bmi",
        "ext_age_onset",
        "ext_yrs_sq",
        "ext_yrs_log",
        "ext_early_pd",
        "ext_late_pd",
    ]
    for col_name in ext_names:
        df[col_name] = df["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0)).fillna(0.0)

    all_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    for col in all_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    all_sids = split["dev_sids"] + split["test_sids"]
    pd_sids = [sid for sid in all_sids if subjects.get(sid, {}).get("group") == "PD"]
    df_pd = df[df["sid"].isin(pd_sids)].copy()

    X_pd = df_pd[all_cols].values.astype(np.float32)
    y_pd = df_pd["updrs3"].values.astype(np.float32)
    sids_pd = df_pd["sid"].values.tolist()

    print(f"PD subjects: {len(X_pd)}")
    print(f"UPDRS-III: mean={y_pd.mean():.1f}, std={y_pd.std():.1f}, range=[{y_pd.min():.0f}, {y_pd.max():.0f}]")
    print(f"Features available: {len(all_cols)}")

    print(f"\n{'='*70}")
    print("L1: LightGBM nested LOOCV")
    print(f"{'='*70}")
    mae_l1, r_l1, preds_l1, feat_l1 = nested_lgb(X_pd, y_pd, all_cols, k=150)
    print(f"  L1 RESULT: MAE={mae_l1:.2f}, r={r_l1:.3f}")

    print(f"\n{'='*70}")
    print("L2: LightGBM + XGBoost average nested LOOCV")
    print(f"{'='*70}")
    mae_l2, r_l2, preds_l2, mae_xgb, r_xgb, preds_xgb, feat_l2 = nested_average(X_pd, y_pd, all_cols, k=150)
    print(f"  XGB-only: MAE={mae_xgb:.2f}, r={r_xgb:.3f}")
    print(f"  L2 RESULT: MAE={mae_l2:.2f}, r={r_l2:.3f}")

    print(f"\n{'='*70}")
    print("L3: Stacking nested LOOCV")
    print(f"{'='*70}")
    mae_l3, r_l3, preds_l3, feat_l3 = nested_stacking(X_pd, y_pd, all_cols, k=150)
    print(f"  L3 RESULT: MAE={mae_l3:.2f}, r={r_l3:.3f}")

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"PD-ONLY NESTED LOOCV SUMMARY ({elapsed/60:.1f} min)")
    print(f"{'='*70}")
    print(f"  {'Method':<35s} {'MAE':>7s} {'r':>7s}")
    print(f"  {'-'*50}")
    print(f"  {'Hssayeni 2021 (N=24, ref)':<35s} {'5.95':>7s} {'0.740':>7s}")
    print(f"  {'Shuqair 2024 (N=24, ref)':<35s} {'~5.65':>7s} {'0.890':>7s}")
    print(f"  {'-'*50}")
    print(f"  {'L1: LGB nested LOOCV':<35s} {mae_l1:>7.2f} {r_l1:>7.3f}")
    print(f"  {'XGB-only nested LOOCV':<35s} {mae_xgb:>7.2f} {r_xgb:>7.3f}")
    print(f"  {'L2: Avg nested LOOCV':<35s} {mae_l2:>7.2f} {r_l2:>7.3f}")
    print(f"  {'L3: Stack nested LOOCV':<35s} {mae_l3:>7.2f} {r_l3:>7.3f}")

    payload = {
        "n_pd": len(y_pd),
        "updrs_mean": round(float(y_pd.mean()), 1),
        "updrs_std": round(float(y_pd.std()), 1),
        "L1_lgb_mae": round(float(mae_l1), 3),
        "L1_lgb_r": round(float(r_l1), 3),
        "L2_avg_mae": round(float(mae_l2), 3),
        "L2_avg_r": round(float(r_l2), 3),
        "L3_stack_mae": round(float(mae_l3), 3),
        "L3_stack_r": round(float(r_l3), 3),
        "xgb_only_mae": round(float(mae_xgb), 3),
        "xgb_only_r": round(float(r_xgb), 3),
        "runtime_min": round(elapsed / 60, 1),
        "preds_lgb": preds_l1.tolist(),
        "preds_avg": preds_l2.tolist(),
        "preds_stack": preds_l3.tolist(),
        "preds_xgb": preds_xgb.tolist(),
        "y_true": y_pd.tolist(),
        "sids": sids_pd,
        "top10_feature_frequency": {
            "lgb": summarize_feature_counter(feat_l1),
            "avg": summarize_feature_counter(feat_l2),
            "stack": summarize_feature_counter(feat_l3),
        },
        "protocol": {
            "nested_feature_selection": True,
            "selection_scope": "within_each_loocv_fold",
            "legacy_optimistic_runner_replaced": True,
        },
    }
    save_json_artifact("loocv_stack_results.json", payload)
    print("  Saved to results/loocv_stack_results.json")


if __name__ == "__main__":
    main()
