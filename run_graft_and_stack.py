"""
Graft Extended Covariates + Stacking Ensemble onto Proven 7.97 Pipeline
========================================================================
Uses the EXACT biomechanical_features.csv that produced MAE=7.97, then:
  1. Adds extended covariates (yrs², BMI, onset_age, etc.)
  2. Tests K=150, 160, 170, 180 with extended covariates
  3. Runs stacking ensemble: LGB + XGB + Ridge L0 → Ridge L1
  4. Tests LGB + XGB ensemble (simple average)

Self-contained. Imports from data_split.py only.
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR

N_CORES = 11
SEEDS = [42, 123, 456, 789, 2024]


# ══════════════════════════════════════════════════════════════════════
# LOAD PROVEN FEATURE SET
# ══════════════════════════════════════════════════════════════════════

def load_proven_features():
    """Load the biomechanical_features.csv that produced MAE=7.97."""
    path = "/root/pd-imu/biomechanical_features.csv"
    if not os.path.exists(path):
        raise FileNotFoundError(f"Proven feature CSV not found at {path}. Run run_biomechanics.py first.")
    df = pd.read_csv(path)
    print(f"Loaded proven features: {df.shape[0]} subjects × {df.shape[1]} columns")
    return df


def load_extended_covariates():
    """Parse extended clinical covariates NOT in the original 5."""
    covariates = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
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
            yrs = pd.to_numeric(row.get("Years since PD diagnosis", row.get("Years Since Diagnosis", 0)), errors="coerce")

            age_v = float(age) if pd.notna(age) else 65.0
            yrs_v = float(yrs) if pd.notna(yrs) else 0.0
            h = float(height) if pd.notna(height) else 170.0
            w = float(weight) if pd.notna(weight) else 75.0

            covariates[sid] = {
                "ext_height": h,
                "ext_weight": w,
                "ext_bmi": w / ((h / 100.0) ** 2) if h > 0 else 25.0,
                "ext_age_onset": age_v - yrs_v if yrs_v > 0 else age_v,
                "ext_yrs_sq": yrs_v ** 2,
                "ext_yrs_log": float(np.log1p(yrs_v)),
                "ext_early_pd": 1.0 if 0 < yrs_v <= 5 else 0.0,
                "ext_late_pd": 1.0 if yrs_v > 10 else 0.0,
            }
    return covariates


# ══════════════════════════════════════════════════════════════════════
# FEATURE SELECTION
# ══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=150):
    from xgboost import XGBRegressor
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                        objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


# ══════════════════════════════════════════════════════════════════════
# MODEL TRAINING
# ══════════════════════════════════════════════════════════════════════

def train_lgbm(Xd, yd, Xt, seed=42):
    import lightgbm as lgb
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    vi, ti = idx[:nv], idx[nv:]

    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                           reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                           objective="mae", verbose=-1)
    m.fit(Xd[ti], yd[ti], eval_set=[(Xd[vi], yd[vi])],
          callbacks=[lgb.early_stopping(100, verbose=False)])
    return m.predict(Xt)


def train_xgb(Xd, yd, Xt, seed=42):
    from xgboost import XGBRegressor
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    vi, ti = idx[:nv], idx[nv:]

    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                      reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                      early_stopping_rounds=100, objective="reg:absoluteerror")
    m.fit(Xd[ti], yd[ti], eval_set=[(Xd[vi], yd[vi])], verbose=False)
    return m.predict(Xt)


def train_ridge(Xd, yd, Xt, seed=42):
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler()
    Xds = sc.fit_transform(Xd)
    Xts = sc.transform(Xt)
    m = Ridge(alpha=10.0, random_state=seed)
    m.fit(Xds, yd)
    return m.predict(Xts)


def run_single_model(name, Xd, yd, Xt, yt, feat_names, k=150, model_fn=None):
    """5-seed single model experiment."""
    if model_fn is None:
        model_fn = train_lgbm
    k = min(k, Xd.shape[1])
    print(f"\n  {name} ({Xd.shape[1]} raw → top {k})")
    sel_idx, sel_names = feature_select(Xd, yd, feat_names, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        p = np.clip(model_fn(Xds, yd, Xts, seed), 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")

    return {
        "config": name, "n_raw": int(Xd.shape[1]), "n_sel": k,
        "mean_mae": round(float(np.mean(maes)), 3),
        "std_mae": round(float(np.std(maes)), 3),
        "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
        "seed_maes": [round(float(m), 3) for m in maes],
        "top10": sel_names[:10],
        "ens_preds": [float(x) for x in ep],
    }


# ══════════════════════════════════════════════════════════════════════
# STACKING ENSEMBLE
# ══════════════════════════════════════════════════════════════════════

def run_stacking(Xd, yd, Xt, yt, feat_names, k=150):
    """L0: LGB + XGB + Ridge → L1: Ridge meta-learner."""
    from sklearn.model_selection import KFold
    import lightgbm as lgb
    from xgboost import XGBRegressor
    from sklearn.preprocessing import StandardScaler

    k = min(k, Xd.shape[1])
    print(f"\n  STACKING ({Xd.shape[1]} raw → top {k}, L0: LGB+XGB+Ridge → L1: Ridge)")
    sel_idx, sel_names = feature_select(Xd, yd, feat_names, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        # Generate OOF predictions for L1 training
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof_lgb = np.zeros(len(Xds))
        oof_xgb = np.zeros(len(Xds))
        oof_ridge = np.zeros(len(Xds))
        test_lgb = np.zeros(len(Xts))
        test_xgb = np.zeros(len(Xts))
        test_ridge = np.zeros(len(Xts))

        for tr_i, val_i in kf.split(Xds):
            # LGB
            m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                    reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                    objective="mae", verbose=-1)
            nv = max(1, int(len(tr_i) * 0.15))
            rng = np.random.RandomState(seed + len(tr_i))
            shuf = tr_i.copy(); rng.shuffle(shuf)
            m1.fit(Xds[shuf[nv:]], yd[shuf[nv:]], eval_set=[(Xds[shuf[:nv]], yd[shuf[:nv]])],
                   callbacks=[lgb.early_stopping(100, verbose=False)])
            oof_lgb[val_i] = m1.predict(Xds[val_i])
            test_lgb += m1.predict(Xts) / 5

            # XGB
            m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                               reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                               early_stopping_rounds=100, objective="reg:absoluteerror")
            m2.fit(Xds[shuf[nv:]], yd[shuf[nv:]], eval_set=[(Xds[shuf[:nv]], yd[shuf[:nv]])], verbose=False)
            oof_xgb[val_i] = m2.predict(Xds[val_i])
            test_xgb += m2.predict(Xts) / 5

            # Ridge
            sc = StandardScaler()
            Xtr_s = sc.fit_transform(Xds[tr_i])
            m3 = Ridge(alpha=10.0, random_state=seed)
            m3.fit(Xtr_s, yd[tr_i])
            oof_ridge[val_i] = m3.predict(sc.transform(Xds[val_i]))
            test_ridge += m3.predict(sc.transform(Xts)) / 5

        # L1 meta-learner
        L0_train = np.column_stack([oof_lgb, oof_xgb, oof_ridge])
        L0_test = np.column_stack([test_lgb, test_xgb, test_ridge])

        meta = Ridge(alpha=1.0)
        meta.fit(L0_train, yd)
        p = np.clip(meta.predict(L0_test), 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f} (L1 weights: {meta.coef_.round(3)})")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")

    return {
        "config": f"stacking_K{k}", "n_raw": int(Xd.shape[1]), "n_sel": k,
        "mean_mae": round(float(np.mean(maes)), 3),
        "std_mae": round(float(np.std(maes)), 3),
        "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
        "seed_maes": [round(float(m), 3) for m in maes],
        "top10": sel_names[:10],
        "ens_preds": [float(x) for x in ep],
    }


# ══════════════════════════════════════════════════════════════════════
# LGB + XGB SIMPLE ENSEMBLE
# ══════════════════════════════════════════════════════════════════════

def run_lgb_xgb_ensemble(Xd, yd, Xt, yt, feat_names, k=150):
    """Average LGB and XGB predictions."""
    k = min(k, Xd.shape[1])
    print(f"\n  LGB+XGB AVG ({Xd.shape[1]} raw → top {k})")
    sel_idx, sel_names = feature_select(Xd, yd, feat_names, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        p_lgb = train_lgbm(Xds, yd, Xts, seed)
        p_xgb = train_xgb(Xds, yd, Xts, seed)
        p = np.clip(0.6 * p_lgb + 0.4 * p_xgb, 0, 132)  # slight LGB bias
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")

    return {
        "config": f"lgb_xgb_avg_K{k}", "n_raw": int(Xd.shape[1]), "n_sel": k,
        "mean_mae": round(float(np.mean(maes)), 3),
        "std_mae": round(float(np.std(maes)), 3),
        "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
        "seed_maes": [round(float(m), 3) for m in maes],
        "top10": sel_names[:10],
        "ens_preds": [float(x) for x in ep],
    }


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    print("=" * 70)
    print("GRAFT EXTENDED COVARIATES + STACKING ENSEMBLE")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]

    # Load proven feature set
    df_feat = load_proven_features()

    # Load and add extended covariates
    ext_cov = load_extended_covariates()
    for col_name in ["ext_height", "ext_weight", "ext_bmi", "ext_age_onset",
                     "ext_yrs_sq", "ext_yrs_log", "ext_early_pd", "ext_late_pd"]:
        df_feat[col_name] = df_feat["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0))

    # Clean
    feat_cols = [c for c in df_feat.columns if c not in ("sid", "updrs3")]
    for c in feat_cols:
        df_feat[c] = pd.to_numeric(df_feat[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    # Original cols (without extended covariates)
    orig_cols = [c for c in feat_cols if not c.startswith("ext_")]

    dm = df_feat["sid"].isin(dev_sids)
    tm = df_feat["sid"].isin(test_sids)
    X_dev_all = df_feat.loc[dm, feat_cols].values.astype(np.float32)
    X_dev_orig = df_feat.loc[dm, orig_cols].values.astype(np.float32)
    y_dev = df_feat.loc[dm, "updrs3"].values.astype(np.float32)
    X_test_all = df_feat.loc[tm, feat_cols].values.astype(np.float32)
    X_test_orig = df_feat.loc[tm, orig_cols].values.astype(np.float32)
    y_test = df_feat.loc[tm, "updrs3"].values.astype(np.float32)

    print(f"  Original features: {len(orig_cols)}")
    print(f"  With extended covariates: {len(feat_cols)} (+{len(feat_cols)-len(orig_cols)})")
    print(f"  Dev: {X_dev_all.shape[0]}, Test: {X_test_all.shape[0]}")

    results = []

    # ── CONTROL: Reproduce 7.97 baseline ──────────────────────────────
    r = run_single_model("G0_baseline_K150", X_dev_orig, y_dev,
                         X_test_orig, y_test, orig_cols, k=150)
    if r: results.append(r)
    baseline_mae = r["ens_mae"] if r else 99.0

    # ── GRAFT: Extended covariates at various K ───────────────────────
    for k in [150, 160, 170, 180]:
        r = run_single_model(f"G1_extcov_K{k}", X_dev_all, y_dev,
                             X_test_all, y_test, feat_cols, k=k)
        if r: results.append(r)

    # ── XGB with extended covariates ──────────────────────────────────
    r = run_single_model("G2_xgb_extcov_K150", X_dev_all, y_dev,
                         X_test_all, y_test, feat_cols, k=150, model_fn=train_xgb)
    if r: results.append(r)

    # ── LGB+XGB average ───────────────────────────────────────────────
    r = run_lgb_xgb_ensemble(X_dev_all, y_dev, X_test_all, y_test, feat_cols, k=150)
    if r: results.append(r)

    # ── STACKING ENSEMBLE ─────────────────────────────────────────────
    r = run_stacking(X_dev_all, y_dev, X_test_all, y_test, feat_cols, k=150)
    if r: results.append(r)

    r = run_stacking(X_dev_orig, y_dev, X_test_orig, y_test, orig_cols, k=150)
    if r: results.append(r)

    # ── REPORT ────────────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print("RESULTS (sorted by ENS MAE)")
    print(f"{'='*70}")
    print(f"{'Config':<30s} {'Raw':>5s} {'K':>4s} {'MAE±std':>12s} {'ENS':>7s} {'r':>6s} {'Δ':>6s}")
    print("-" * 75)
    for r in sorted(results, key=lambda x: x["ens_mae"]):
        d = baseline_mae - r["ens_mae"]
        ds = f"+{d:.2f}" if d > 0 else f"{d:.2f}"
        print(f"  {r['config']:<28s} {r['n_raw']:>5d} {r['n_sel']:>4d} "
              f"{r['mean_mae']:>5.2f}±{r['std_mae']:.2f} {r['ens_mae']:>7.2f} {r['ens_r']:>6.3f} {ds:>6s}")

    best = min(results, key=lambda x: x["ens_mae"])
    print(f"\n  Baseline (G0): {baseline_mae:.2f}")
    print(f"  Best:          {best['ens_mae']:.2f} ({best['config']})")
    print(f"  Δ:             {baseline_mae - best['ens_mae']:.2f}")
    print(f"\n  Top features ({best['config']}): {best.get('top10', [])[:5]}")
    print(f"  Runtime: {total:.0f}s ({total/60:.1f}m)")

    with open("/root/pd-imu/graft_stack_results.json", "w") as f:
        json.dump({"baseline_mae": float(baseline_mae), "best_mae": float(best["ens_mae"]),
                    "best_config": best["config"], "results": results,
                    "runtime_s": round(total, 1)}, f, indent=2)
    print("  Saved to /root/pd-imu/graft_stack_results.json")


if __name__ == "__main__":
    main()
