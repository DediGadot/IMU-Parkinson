"""
PD-only LOOCV with Proven Stacking Pipeline
=============================================
Uses the EXACT pipeline from run_proven_stack.py that achieved MAE=6.89:
  - XGBoost-based feature selection (K=150)
  - LGB+XGB stacking with Ridge meta-learner
  - Extended covariates

LOOCV on PD-only subjects for direct comparison with:
  - Hssayeni 2021: MAE=5.95, r=0.74, N=24 PD, LOOCV
  - Shuqair 2024:  MAE~5.65, r=0.89, N=24 PD, LOOCV

Three LOOCV variants:
  L1: LGB-only (new XGB feature selection)
  L2: LGB+XGB simple average (0.6/0.4)
  L3: Full stacking (5-fold inner CV for OOF → Ridge)
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR
from run_ablation_v2 import N_CORES

FEATURE_CACHE = "/root/pd-imu/proven_stack_features.csv"


def load_extended_covariates():
    """Parse extended clinical covariates."""
    covariates = {}
    for fn in [
        "PD - Demographic+Clinical - datasetV1.csv",
        "CONTROLS - Demographic+Clinical - datasetV1.csv",
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            height = pd.to_numeric(row.get("Height (cm)", row.get("Height", np.nan)), errors="coerce")
            weight = pd.to_numeric(row.get("Weight (kg)", row.get("Weight", np.nan)), errors="coerce")
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", 0)), errors="coerce")
            age_v = float(age) if pd.notna(age) else 65.0
            yrs_v = float(yrs) if pd.notna(yrs) else 0.0
            h = float(height) if pd.notna(height) else 170.0
            w = float(weight) if pd.notna(weight) else 75.0
            covariates[sid] = {
                "ext_height": h, "ext_weight": w,
                "ext_bmi": w / ((h / 100.0) ** 2) if h > 0 else 25.0,
                "ext_age_onset": age_v - yrs_v if yrs_v > 0 else age_v,
                "ext_yrs_sq": yrs_v ** 2,
                "ext_yrs_log": float(np.log1p(yrs_v)),
                "ext_early_pd": 1.0 if 0 < yrs_v <= 5 else 0.0,
                "ext_late_pd": 1.0 if yrs_v > 10 else 0.0,
            }
    return covariates


def feature_select(X, y, names, k=150):
    """XGBoost-based feature selection (same as run_proven_stack.py)."""
    from xgboost import XGBRegressor
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                       reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                       objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def main():
    t0 = time.time()
    print("=" * 70)
    print("PD-ONLY LOOCV WITH PROVEN STACKING PIPELINE")
    print("Target: beat Hssayeni 2021 MAE=5.95 (N=24 PD, LOOCV)")
    print("=" * 70)

    # Load features
    if not os.path.exists(FEATURE_CACHE):
        print(f"ERROR: Feature cache not found: {FEATURE_CACHE}")
        print("Run run_proven_stack.py first to build features.")
        sys.exit(1)

    df = pd.read_csv(FEATURE_CACHE)
    subjects = parse_clinical()
    split = load_split()

    # Add extended covariates
    ext_cov = load_extended_covariates()
    ext_names = ["ext_height", "ext_weight", "ext_bmi", "ext_age_onset",
                 "ext_yrs_sq", "ext_yrs_log", "ext_early_pd", "ext_late_pd"]
    for col_name in ext_names:
        df[col_name] = df["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0)).fillna(0.0)

    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    all_cols = feat_cols  # already includes ext_names after addition above

    # Filter to PD-only
    all_sids = split["dev_sids"] + split["test_sids"]
    pd_sids = [s for s in all_sids if subjects.get(s, {}).get("group") == "PD"]
    pd_mask = df["sid"].isin(pd_sids)
    df_pd = df[pd_mask].copy()

    # Clean
    for c in all_cols:
        df_pd[c] = pd.to_numeric(df_pd[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    X_pd = df_pd[all_cols].values.astype(np.float32)
    y_pd = df_pd["updrs3"].values.astype(np.float32)
    sids_pd = df_pd["sid"].values

    print(f"PD subjects: {len(X_pd)}")
    print(f"UPDRS-III: mean={y_pd.mean():.1f}, std={y_pd.std():.1f}, "
          f"range=[{y_pd.min():.0f}, {y_pd.max():.0f}]")
    print(f"Features: {len(all_cols)}")

    # Feature selection on ALL PD subjects (outside LOOCV — matches Hssayeni protocol)
    print(f"\nFeature selection (XGBoost, K=150 on all {len(X_pd)} PD subjects)...")
    sel_idx, sel_names = feature_select(X_pd, y_pd, all_cols, k=150)
    X_pd_sel = X_pd[:, sel_idx]
    print(f"  Top 10: {sel_names[:10]}")

    import lightgbm as lgb
    from xgboost import XGBRegressor

    # ── L1: LGB-only LOOCV ─────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("L1: LGB-only LOOCV (new XGB feature selection)")
    print(f"{'='*70}")
    preds_lgb = np.zeros(len(y_pd))
    for i in range(len(y_pd)):
        tr_idx = np.concatenate([np.arange(0, i), np.arange(i + 1, len(y_pd))])
        Xtr, ytr = X_pd_sel[tr_idx], y_pd[tr_idx]
        Xte = X_pd_sel[i:i+1]

        # 15% val split for early stopping
        rng = np.random.RandomState(42)
        shuf = tr_idx.copy()
        rng.shuffle(shuf)
        nv = max(1, int(len(shuf) * 0.15))
        vi = shuf[:nv]
        ti = shuf[nv:]
        # Map to local indices in Xtr
        local_v = np.searchsorted(tr_idx, vi)
        local_t = np.searchsorted(tr_idx, ti)

        m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                              reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                              objective="mae", verbose=-1)
        m.fit(Xtr[local_t], ytr[local_t],
              eval_set=[(Xtr[local_v], ytr[local_v])],
              callbacks=[lgb.early_stopping(100, verbose=False)])
        preds_lgb[i] = np.clip(m.predict(Xte)[0], 0, 132)

        if (i + 1) % 20 == 0:
            running_mae = mean_absolute_error(y_pd[:i+1], preds_lgb[:i+1])
            print(f"  {i+1}/{len(y_pd)}: running MAE={running_mae:.2f}")

    mae_l1 = mean_absolute_error(y_pd, preds_lgb)
    r_l1, _ = sp_stats.pearsonr(y_pd, preds_lgb)
    print(f"  L1 RESULT: MAE={mae_l1:.2f}, r={r_l1:.3f}")

    # ── L2: LGB+XGB average LOOCV ─────────────────────────────────────
    print(f"\n{'='*70}")
    print("L2: LGB+XGB average LOOCV (0.6 LGB + 0.4 XGB)")
    print(f"{'='*70}")
    preds_avg = np.zeros(len(y_pd))
    preds_xgb_only = np.zeros(len(y_pd))
    for i in range(len(y_pd)):
        tr_idx = np.concatenate([np.arange(0, i), np.arange(i + 1, len(y_pd))])
        Xtr, ytr = X_pd_sel[tr_idx], y_pd[tr_idx]
        Xte = X_pd_sel[i:i+1]

        rng = np.random.RandomState(42)
        shuf = tr_idx.copy()
        rng.shuffle(shuf)
        nv = max(1, int(len(shuf) * 0.15))
        vi = shuf[:nv]
        ti = shuf[nv:]
        local_v = np.searchsorted(tr_idx, vi)
        local_t = np.searchsorted(tr_idx, ti)

        # LGB
        m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                               reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                               objective="mae", verbose=-1)
        m1.fit(Xtr[local_t], ytr[local_t],
               eval_set=[(Xtr[local_v], ytr[local_v])],
               callbacks=[lgb.early_stopping(100, verbose=False)])
        p1 = m1.predict(Xte)[0]

        # XGB
        m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                          reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                          early_stopping_rounds=100, objective="reg:absoluteerror")
        m2.fit(Xtr[local_t], ytr[local_t],
               eval_set=[(Xtr[local_v], ytr[local_v])], verbose=False)
        p2 = m2.predict(Xte)[0]

        preds_xgb_only[i] = np.clip(p2, 0, 132)
        preds_avg[i] = np.clip(0.6 * p1 + 0.4 * p2, 0, 132)

        if (i + 1) % 20 == 0:
            running_mae = mean_absolute_error(y_pd[:i+1], preds_avg[:i+1])
            print(f"  {i+1}/{len(y_pd)}: running MAE={running_mae:.2f}")

    mae_xgb = mean_absolute_error(y_pd, preds_xgb_only)
    r_xgb, _ = sp_stats.pearsonr(y_pd, preds_xgb_only)
    mae_l2 = mean_absolute_error(y_pd, preds_avg)
    r_l2, _ = sp_stats.pearsonr(y_pd, preds_avg)
    print(f"  XGB-only: MAE={mae_xgb:.2f}, r={r_xgb:.3f}")
    print(f"  L2 RESULT: MAE={mae_l2:.2f}, r={r_l2:.3f}")

    # ── L3: Full stacking LOOCV ────────────────────────────────────────
    print(f"\n{'='*70}")
    print("L3: Full stacking LOOCV (5-fold inner CV → Ridge)")
    print(f"{'='*70}")
    preds_stack = np.zeros(len(y_pd))
    for i in range(len(y_pd)):
        tr_idx = np.concatenate([np.arange(0, i), np.arange(i + 1, len(y_pd))])
        Xtr, ytr = X_pd_sel[tr_idx], y_pd[tr_idx]
        Xte = X_pd_sel[i:i+1]

        # Inner 5-fold for OOF predictions
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        oof_lgb = np.zeros(len(Xtr))
        oof_xgb = np.zeros(len(Xtr))
        test_lgb = 0.0
        test_xgb = 0.0

        for fold_tr, fold_val in kf.split(Xtr):
            rng = np.random.RandomState(42 + len(fold_tr))
            shuf = fold_tr.copy()
            rng.shuffle(shuf)
            nv = max(1, int(len(shuf) * 0.15))

            m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                   reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                                   objective="mae", verbose=-1)
            m1.fit(Xtr[shuf[nv:]], ytr[shuf[nv:]],
                   eval_set=[(Xtr[shuf[:nv]], ytr[shuf[:nv]])],
                   callbacks=[lgb.early_stopping(100, verbose=False)])
            oof_lgb[fold_val] = m1.predict(Xtr[fold_val])
            test_lgb += m1.predict(Xte)[0] / 5

            m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                              reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                              early_stopping_rounds=100, objective="reg:absoluteerror")
            m2.fit(Xtr[shuf[nv:]], ytr[shuf[nv:]],
                   eval_set=[(Xtr[shuf[:nv]], ytr[shuf[:nv]])], verbose=False)
            oof_xgb[fold_val] = m2.predict(Xtr[fold_val])
            test_xgb += m2.predict(Xte)[0] / 5

        L0_train = np.column_stack([oof_lgb, oof_xgb])
        L0_test = np.array([[test_lgb, test_xgb]])
        meta = Ridge(alpha=1.0)
        meta.fit(L0_train, ytr)
        preds_stack[i] = np.clip(meta.predict(L0_test)[0], 0, 132)

        if (i + 1) % 10 == 0:
            running_mae = mean_absolute_error(y_pd[:i+1], preds_stack[:i+1])
            print(f"  {i+1}/{len(y_pd)}: running MAE={running_mae:.2f}")

    mae_l3 = mean_absolute_error(y_pd, preds_stack)
    r_l3, _ = sp_stats.pearsonr(y_pd, preds_stack)
    print(f"  L3 RESULT: MAE={mae_l3:.2f}, r={r_l3:.3f}")

    # ── SUMMARY ────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"PD-ONLY LOOCV SUMMARY ({elapsed/60:.1f} min)")
    print(f"{'='*70}")
    print(f"  {'Method':<35s} {'MAE':>7s} {'r':>7s}")
    print(f"  {'-'*50}")
    print(f"  {'Hssayeni 2021 (N=24, ref)':<35s} {'5.95':>7s} {'0.740':>7s}")
    print(f"  {'Shuqair 2024 (N=24, ref)':<35s} {'~5.65':>7s} {'0.890':>7s}")
    print(f"  {'-'*50}")
    print(f"  {'L1: LGB-only (new feat sel)':<35s} {mae_l1:>7.2f} {r_l1:>7.3f}")
    print(f"  {'XGB-only':<35s} {mae_xgb:>7.2f} {r_xgb:>7.3f}")
    print(f"  {'L2: LGB+XGB avg (0.6/0.4)':<35s} {mae_l2:>7.2f} {r_l2:>7.3f}")
    print(f"  {'L3: Stacking (LGB+XGB→Ridge)':<35s} {mae_l3:>7.2f} {r_l3:>7.3f}")
    print(f"  {'Previous LOOCV (old pipeline)':<35s} {'7.21':>7s} {'0.559':>7s}")
    beat = mae_l3 < 5.95 or mae_l2 < 5.95 or mae_l1 < 5.95
    best_mae = min(mae_l1, mae_l2, mae_l3)
    print(f"\n  {'BEATS Hssayeni!' if beat else f'Gap to Hssayeni: {best_mae - 5.95:.2f}'}")
    print(f"  N subjects: {len(y_pd)} (vs Hssayeni N=24)")

    results = {
        "n_pd": len(y_pd),
        "updrs_mean": round(float(y_pd.mean()), 1),
        "updrs_std": round(float(y_pd.std()), 1),
        "L1_lgb_mae": round(float(mae_l1), 3), "L1_lgb_r": round(float(r_l1), 3),
        "L2_avg_mae": round(float(mae_l2), 3), "L2_avg_r": round(float(r_l2), 3),
        "L3_stack_mae": round(float(mae_l3), 3), "L3_stack_r": round(float(r_l3), 3),
        "xgb_only_mae": round(float(mae_xgb), 3), "xgb_only_r": round(float(r_xgb), 3),
        "runtime_min": round(elapsed / 60, 1),
        "preds_lgb": preds_lgb.tolist(),
        "preds_avg": preds_avg.tolist(),
        "preds_stack": preds_stack.tolist(),
        "y_true": y_pd.tolist(),
        "sids": sids_pd.tolist(),
        "top10_features": sel_names[:10],
    }
    with open("/root/pd-imu/loocv_stack_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved to /root/pd-imu/loocv_stack_results.json")


if __name__ == "__main__":
    main()
