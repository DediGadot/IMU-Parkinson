"""
PD-Only LOOCV with Best Pipeline
=================================
For apples-to-apples comparison with Hssayeni (MAE=5.95, N=24, LOOCV).

Experiments:
  L1: PD-only train, LGB, XGB-selection K=150, 5-seed ensemble LOOCV
  L2: PD-only train, LGB+XGB stacking, XGB-selection K=150, 5-seed ensemble
  L3: Full-cohort train (PD+HC), stacking, PD-only LOOCV eval

Uses cached features from run_proven_stack.py (proven_stack_features.csv).
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
from data_split import parse_clinical, load_split, SENSORS

FEATURE_CACHE = "/root/pd-imu/proven_stack_features.csv"
RESULTS_FILE = "/root/pd-imu/pdonly_loocv_results.json"
N_CORES = 11
SEEDS = [42, 123, 456, 789, 2024]


def feature_select(X, y, names, k=150):
    from xgboost import XGBRegressor
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                       reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                       objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgbm(Xtr, ytr, Xval, yval, Xte, seed=42):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                           reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                           objective="mae", verbose=-1)
    m.fit(Xtr, ytr, eval_set=[(Xval, yval)],
          callbacks=[lgb.early_stopping(100, verbose=False)])
    return m.predict(Xte), m


def train_xgb(Xtr, ytr, Xval, yval, Xte, seed=42):
    from xgboost import XGBRegressor
    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                     reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                     early_stopping_rounds=100, objective="reg:absoluteerror")
    m.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)
    return m.predict(Xte), m


def split_train_val(X, y, seed, val_frac=0.15):
    rng = np.random.RandomState(seed)
    idx = np.arange(len(X)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * val_frac))
    return X[idx[nv:]], y[idx[nv:]], X[idx[:nv]], y[idx[:nv]]


def loocv_lgb(X_all, y_all, sids_all, feat_cols, k=150):
    """LOOCV with LGB + XGB selection, 5-seed ensemble per fold."""
    n = len(sids_all)
    preds = np.zeros(n)
    true = np.zeros(n)

    for i in range(n):
        mask = np.ones(n, dtype=bool); mask[i] = False
        X_train, y_train = X_all[mask], y_all[mask]
        X_test = X_all[i:i+1]
        true[i] = y_all[i]

        sel_idx, _ = feature_select(X_train, y_train, feat_cols, k)
        X_tr_sel = X_train[:, sel_idx]
        X_te_sel = X_test[:, sel_idx]

        seed_preds = []
        for seed in SEEDS:
            Xtr, ytr, Xv, yv = split_train_val(X_tr_sel, y_train, seed)
            p, _ = train_lgbm(Xtr, ytr, Xv, yv, X_te_sel, seed)
            seed_preds.append(p[0])
        preds[i] = np.clip(np.mean(seed_preds), 0, 132)

        if (i + 1) % 10 == 0 or i == n - 1:
            mae_so_far = mean_absolute_error(true[:i+1], preds[:i+1])
            print(f"    [{i+1}/{n}] running MAE={mae_so_far:.2f} (sid={sids_all[i]}, pred={preds[i]:.1f}, true={true[i]:.0f})")

    mae = mean_absolute_error(true, preds)
    r, _ = sp_stats.pearsonr(true, preds)
    return mae, r, preds, true


def loocv_stacking(X_all, y_all, sids_all, feat_cols, k=150):
    """LOOCV with LGB+XGB stacking (5-fold OOF → Ridge), 5-seed ensemble."""
    n = len(sids_all)
    preds = np.zeros(n)
    true = np.zeros(n)

    for i in range(n):
        mask = np.ones(n, dtype=bool); mask[i] = False
        X_train, y_train = X_all[mask], y_all[mask]
        X_test = X_all[i:i+1]
        true[i] = y_all[i]

        sel_idx, _ = feature_select(X_train, y_train, feat_cols, k)
        X_tr_sel = X_train[:, sel_idx]
        X_te_sel = X_test[:, sel_idx]

        seed_preds = []
        for seed in SEEDS:
            kf = KFold(n_splits=5, shuffle=True, random_state=seed)
            oof_lgb = np.zeros(len(X_tr_sel))
            oof_xgb = np.zeros(len(X_tr_sel))
            test_lgb = np.zeros(1)
            test_xgb = np.zeros(1)

            for tr_i, val_i in kf.split(X_tr_sel):
                Xtr, ytr, Xv, yv = split_train_val(X_tr_sel[tr_i], y_train[tr_i], seed + len(tr_i))

                p_l, _ = train_lgbm(Xtr, ytr, Xv, yv, X_tr_sel[val_i], seed)
                oof_lgb[val_i] = p_l
                p_lt, _ = train_lgbm(Xtr, ytr, Xv, yv, X_te_sel, seed)
                test_lgb += p_lt / 5

                p_x, _ = train_xgb(Xtr, ytr, Xv, yv, X_tr_sel[val_i], seed)
                oof_xgb[val_i] = p_x
                p_xt, _ = train_xgb(Xtr, ytr, Xv, yv, X_te_sel, seed)
                test_xgb += p_xt / 5

            L0_train = np.column_stack([oof_lgb, oof_xgb])
            L0_test = np.column_stack([test_lgb, test_xgb])
            meta = Ridge(alpha=1.0)
            meta.fit(L0_train, y_train)
            seed_preds.append(meta.predict(L0_test)[0])

        preds[i] = np.clip(np.mean(seed_preds), 0, 132)

        if (i + 1) % 10 == 0 or i == n - 1:
            mae_so_far = mean_absolute_error(true[:i+1], preds[:i+1])
            print(f"    [{i+1}/{n}] running MAE={mae_so_far:.2f} (sid={sids_all[i]}, pred={preds[i]:.1f}, true={true[i]:.0f})")

    mae = mean_absolute_error(true, preds)
    r, _ = sp_stats.pearsonr(true, preds)
    return mae, r, preds, true


def main():
    t0 = time.time()
    print("=" * 70)
    print("PD-ONLY LOOCV — BEST PIPELINE")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()

    if not os.path.exists(FEATURE_CACHE):
        print(f"ERROR: cached features not found at {FEATURE_CACHE}")
        print("Run run_proven_stack.py first to generate features.")
        sys.exit(1)

    df = pd.read_csv(FEATURE_CACHE)
    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    print(f"Loaded: {len(df)} subjects × {len(feat_cols)} features")

    # Add extended covariates
    from run_proven_stack import load_extended_covariates
    ext_cov = load_extended_covariates()
    ext_names = ["ext_height", "ext_weight", "ext_bmi", "ext_age_onset",
                 "ext_yrs_sq", "ext_yrs_log", "ext_early_pd", "ext_late_pd"]
    for col_name in ext_names:
        if col_name not in df.columns:
            df[col_name] = df["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0)).fillna(0.0)
    all_cols = [c for c in df.columns if c not in ("sid", "updrs3")]

    # Identify PD subjects
    pd_sids = sorted([sid for sid in df["sid"].values if sid in subjects and subjects[sid]["group"] == "PD"])
    all_sids = sorted(df["sid"].values.tolist())
    print(f"PD subjects: {len(pd_sids)}")
    print(f"All subjects: {len(all_sids)}")

    # Clean
    for c in all_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    pd_mask = df["sid"].isin(pd_sids)
    X_pd = df.loc[pd_mask, all_cols].values.astype(np.float32)
    y_pd = df.loc[pd_mask, "updrs3"].values.astype(np.float32)
    sids_pd = df.loc[pd_mask, "sid"].values.tolist()

    X_all = df[all_cols].values.astype(np.float32)
    y_all = df["updrs3"].values.astype(np.float32)
    sids_all_arr = df["sid"].values.tolist()

    results = []

    # ── L1: PD-only LOOCV, LGB only ──────────────────────────────────
    print(f"\n{'='*70}")
    print("L1: PD-only LOOCV — LGB + XGB selection")
    print(f"{'='*70}")
    t1 = time.time()
    mae, r, preds, true = loocv_lgb(X_pd, y_pd, sids_pd, all_cols, k=150)
    rt1 = time.time() - t1
    print(f"  L1 RESULT: MAE={mae:.3f}, r={r:.3f} ({rt1:.0f}s)")
    results.append({"config": "L1_pdonly_lgb", "mae": round(float(mae), 3),
                    "r": round(float(r), 3), "n_subjects": len(sids_pd),
                    "runtime_s": round(rt1, 1),
                    "predictions": {s: round(float(p), 2) for s, p in zip(sids_pd, preds)},
                    "true_values": {s: round(float(t), 1) for s, t in zip(sids_pd, true)}})

    # ── L2: PD-only LOOCV, stacking ──────────────────────────────────
    print(f"\n{'='*70}")
    print("L2: PD-only LOOCV — LGB+XGB stacking")
    print(f"{'='*70}")
    t2 = time.time()
    mae, r, preds, true = loocv_stacking(X_pd, y_pd, sids_pd, all_cols, k=150)
    rt2 = time.time() - t2
    print(f"  L2 RESULT: MAE={mae:.3f}, r={r:.3f} ({rt2:.0f}s)")
    results.append({"config": "L2_pdonly_stacking", "mae": round(float(mae), 3),
                    "r": round(float(r), 3), "n_subjects": len(sids_pd),
                    "runtime_s": round(rt2, 1),
                    "predictions": {s: round(float(p), 2) for s, p in zip(sids_pd, preds)},
                    "true_values": {s: round(float(t), 1) for s, t in zip(sids_pd, true)}})

    # ── L3: Full-cohort train, PD-only eval, stacking ─────────────────
    print(f"\n{'='*70}")
    print("L3: Full-cohort train, PD-only LOOCV eval — stacking")
    print(f"{'='*70}")
    t3 = time.time()
    # For each PD left-out: train on ALL other subjects (PD+HC), predict left-out
    n_pd = len(sids_pd)
    preds_l3 = np.zeros(n_pd)
    true_l3 = y_pd.copy()

    for i in range(n_pd):
        test_sid = sids_pd[i]
        # Training set: all subjects EXCEPT the left-out PD subject
        train_mask = np.array([s != test_sid for s in sids_all_arr])
        X_train = X_all[train_mask]
        y_train = y_all[train_mask]
        X_test = X_pd[i:i+1]

        sel_idx, _ = feature_select(X_train, y_train, all_cols, k=150)
        X_tr_sel = X_train[:, sel_idx]
        X_te_sel = X_test[:, sel_idx]

        seed_preds = []
        for seed in SEEDS:
            kf = KFold(n_splits=5, shuffle=True, random_state=seed)
            oof_lgb = np.zeros(len(X_tr_sel))
            oof_xgb = np.zeros(len(X_tr_sel))
            test_lgb = np.zeros(1)
            test_xgb = np.zeros(1)

            for tr_i, val_i in kf.split(X_tr_sel):
                Xtr, ytr, Xv, yv = split_train_val(X_tr_sel[tr_i], y_train[tr_i], seed + len(tr_i))
                p_l, _ = train_lgbm(Xtr, ytr, Xv, yv, X_tr_sel[val_i], seed)
                oof_lgb[val_i] = p_l
                p_lt, _ = train_lgbm(Xtr, ytr, Xv, yv, X_te_sel, seed)
                test_lgb += p_lt / 5

                p_x, _ = train_xgb(Xtr, ytr, Xv, yv, X_tr_sel[val_i], seed)
                oof_xgb[val_i] = p_x
                p_xt, _ = train_xgb(Xtr, ytr, Xv, yv, X_te_sel, seed)
                test_xgb += p_xt / 5

            L0_train = np.column_stack([oof_lgb, oof_xgb])
            L0_test = np.column_stack([test_lgb, test_xgb])
            meta = Ridge(alpha=1.0)
            meta.fit(L0_train, y_train)
            seed_preds.append(meta.predict(L0_test)[0])

        preds_l3[i] = np.clip(np.mean(seed_preds), 0, 132)

        if (i + 1) % 10 == 0 or i == n_pd - 1:
            mae_so_far = mean_absolute_error(true_l3[:i+1], preds_l3[:i+1])
            print(f"    [{i+1}/{n_pd}] running MAE={mae_so_far:.2f}")

    mae = mean_absolute_error(true_l3, preds_l3)
    r, _ = sp_stats.pearsonr(true_l3, preds_l3)
    rt3 = time.time() - t3
    print(f"  L3 RESULT: MAE={mae:.3f}, r={r:.3f} ({rt3:.0f}s)")
    results.append({"config": "L3_fullcohort_stacking", "mae": round(float(mae), 3),
                    "r": round(float(r), 3), "n_subjects": n_pd,
                    "n_train_per_fold": len(sids_all_arr) - 1,
                    "runtime_s": round(rt3, 1),
                    "predictions": {s: round(float(p), 2) for s, p in zip(sids_pd, preds_l3)},
                    "true_values": {s: round(float(t), 1) for s, t in zip(sids_pd, true_l3)}})

    # ── Summary ───────────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print("PD-ONLY LOOCV RESULTS")
    print(f"{'='*70}")
    print(f"  Hssayeni et al. 2021: MAE=5.95, r=0.74 (N=24 PD, LOOCV)")
    print(f"  Shuqair et al. 2024:  MAE~5.65, r=0.89 (N=24 PD, LOOCV)")
    print()
    print(f"  {'Config':<30s} {'N':>4s} {'MAE':>7s} {'r':>6s} {'Time':>8s}")
    print(f"  {'-'*60}")
    for r in results:
        print(f"  {r['config']:<30s} {r['n_subjects']:>4d} {r['mae']:>7.3f} {r['r']:>6.3f} {r['runtime_s']:>7.0f}s")

    best = min(results, key=lambda x: x["mae"])
    print(f"\n  BEST: {best['config']} MAE={best['mae']:.3f} r={best['r']:.3f}")
    if best["mae"] < 5.95:
        print(f"  *** BEATS Hssayeni (5.95) by {5.95 - best['mae']:.3f} ***")
    else:
        print(f"  Gap to Hssayeni: {best['mae'] - 5.95:.3f}")
    print(f"\n  Total runtime: {total:.0f}s ({total/60:.1f}m)")

    with open(RESULTS_FILE, "w") as f:
        json.dump({"results": results, "runtime_s": round(total, 1)}, f, indent=2)
    print(f"  Saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
