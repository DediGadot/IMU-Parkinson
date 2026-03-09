"""
Stacking Ceiling Model (LGB+XGB + H&Y)
=======================================
Re-runs the ceiling model using the exact stacking pipeline from run_proven_stack.py
instead of XGBoost alone. This ensures the ceiling uses the same methodology as our
best deployable model (MAE=6.89).

Uses cached features from proven_stack_features.csv + H&Y stage + interactions.
Pipeline: XGBoost importance selection K=150 → LGB+XGB stacking → Ridge L1.
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
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS
from run_ablation_v2 import load_hy, N_CORES, SEEDS
from run_proven_stack import load_extended_covariates

FEATURE_CACHE = "/root/pd-imu/proven_stack_features.csv"
RESULTS_FILE = "/root/pd-imu/ceiling_stack_results.json"

HY_INTERACTION_COLS = ["cv_yrs", "fc_L_cad", "LowerBack_g_cadence"]


def feature_select(X, y, names, k=150):
    from xgboost import XGBRegressor
    k = min(k, X.shape[1])
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                       reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                       objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def run_stacking(name, Xd, yd, Xt, yt, fnames, k=150):
    import lightgbm as lgb
    from xgboost import XGBRegressor

    k = min(k, Xd.shape[1])
    print(f"\n  {name} ({Xd.shape[1]} raw -> K={k}, L0: LGB+XGB -> L1: Ridge)")
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof_lgb = np.zeros(len(Xds))
        oof_xgb = np.zeros(len(Xds))
        test_lgb = np.zeros(len(Xts))
        test_xgb = np.zeros(len(Xts))

        for tr_i, val_i in kf.split(Xds):
            rng = np.random.RandomState(seed + len(tr_i))
            shuf = tr_i.copy(); rng.shuffle(shuf)
            nv = max(1, int(len(shuf) * 0.15))

            m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                    reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                    objective="mae", verbose=-1)
            m1.fit(Xds[shuf[nv:]], yd[shuf[nv:]], eval_set=[(Xds[shuf[:nv]], yd[shuf[:nv]])],
                   callbacks=[lgb.early_stopping(100, verbose=False)])
            oof_lgb[val_i] = m1.predict(Xds[val_i])
            test_lgb += m1.predict(Xts) / 5

            m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                               reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                               early_stopping_rounds=100, objective="reg:absoluteerror")
            m2.fit(Xds[shuf[nv:]], yd[shuf[nv:]], eval_set=[(Xds[shuf[:nv]], yd[shuf[:nv]])], verbose=False)
            oof_xgb[val_i] = m2.predict(Xds[val_i])
            test_xgb += m2.predict(Xts) / 5

        L0_train = np.column_stack([oof_lgb, oof_xgb])
        L0_test = np.column_stack([test_lgb, test_xgb])

        meta = Ridge(alpha=1.0)
        meta.fit(L0_train, yd)
        p = np.clip(meta.predict(L0_test), 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f} (w: {meta.coef_.round(3)})")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")
    return {"config": name, "n_raw": int(Xd.shape[1]), "n_sel": k,
            "mean_mae": round(float(np.mean(maes)), 3),
            "std_mae": round(float(np.std(maes)), 3),
            "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
            "seed_maes": [round(float(m), 3) for m in maes],
            "top10": sel_names[:10],
            "ens_preds": [float(x) for x in ep]}


def run_single_lgb(name, Xd, yd, Xt, yt, fnames, k=150):
    """Single LGB for comparison."""
    import lightgbm as lgb

    k = min(k, Xd.shape[1])
    print(f"\n  {name} ({Xd.shape[1]} raw -> K={k}, LGB only)")
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xds)); rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))

        m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                               reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                               objective="mae", verbose=-1)
        m.fit(Xds[idx[nv:]], yd[idx[nv:]], eval_set=[(Xds[idx[:nv]], yd[idx[:nv]])],
              callbacks=[lgb.early_stopping(100, verbose=False)])
        p = np.clip(m.predict(Xts), 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")
    return {"config": name, "n_raw": int(Xd.shape[1]), "n_sel": k,
            "mean_mae": round(float(np.mean(maes)), 3),
            "std_mae": round(float(np.std(maes)), 3),
            "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
            "seed_maes": [round(float(m), 3) for m in maes],
            "top10": sel_names[:10]}


def main():
    t0 = time.time()
    print("=" * 70)
    print("STACKING CEILING MODEL (LGB+XGB + H&Y)")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]

    if not os.path.exists(FEATURE_CACHE):
        print(f"ERROR: cached features not found at {FEATURE_CACHE}")
        print("Run run_proven_stack.py first to generate features.")
        sys.exit(1)

    df = pd.read_csv(FEATURE_CACHE)
    print(f"Loaded: {len(df)} subjects x {len(df.columns) - 2} features")

    # ── Add extended covariates ───────────────────────────────────────
    ext_cov = load_extended_covariates()
    ext_names = ["ext_height", "ext_weight", "ext_bmi", "ext_age_onset",
                 "ext_yrs_sq", "ext_yrs_log", "ext_early_pd", "ext_late_pd"]
    for col_name in ext_names:
        if col_name not in df.columns:
            df[col_name] = df["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0)).fillna(0.0)

    # ── Add H&Y stage ─────────────────────────────────────────────────
    hy = load_hy()
    df["hy"] = df["sid"].map(lambda s: hy.get(s, 0.0)).fillna(0.0)
    n_hy = sum(1 for s in (dev_sids + test_sids) if s in hy)
    print(f"H&Y: {n_hy}/{len(dev_sids) + len(test_sids)} subjects have H&Y stage")

    # ── Add H&Y interaction features ──────────────────────────────────
    for col in HY_INTERACTION_COLS:
        if col in df.columns:
            df[f"hy_x_{col}"] = df["hy"] * df[col]
            print(f"  Added interaction: hy_x_{col}")

    # ── Prepare arrays ────────────────────────────────────────────────
    all_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    for c in all_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    dm = df["sid"].isin(dev_sids)
    tm = df["sid"].isin(test_sids)
    X_dev = df.loc[dm, all_cols].values.astype(np.float32)
    X_test = df.loc[tm, all_cols].values.astype(np.float32)
    y_dev = df.loc[dm, "updrs3"].values.astype(np.float32)
    y_test = df.loc[tm, "updrs3"].values.astype(np.float32)
    print(f"Dev: {len(y_dev)}, Test: {len(y_test)}, Features: {len(all_cols)}")

    # ── Also prepare without H&Y for comparison ──────────────────────
    no_hy_cols = [c for c in all_cols if not c.startswith("hy")]
    X_dev_nohy = df.loc[dm, no_hy_cols].values.astype(np.float32)
    X_test_nohy = df.loc[tm, no_hy_cols].values.astype(np.float32)

    results = []

    # ── C0: Stacking without H&Y (reproduction of 6.89) ──────────────
    r = run_stacking("C0_stack_noHY", X_dev_nohy, y_dev, X_test_nohy, y_test, no_hy_cols, k=150)
    if r: results.append(r)

    # ── C1: Stacking + H&Y (main experiment) ─────────────────────────
    r = run_stacking("C1_stack_HY", X_dev, y_dev, X_test, y_test, all_cols, k=150)
    if r: results.append(r)

    # ── C2: Stacking + H&Y, K=160 ────────────────────────────────────
    r = run_stacking("C2_stack_HY_K160", X_dev, y_dev, X_test, y_test, all_cols, k=160)
    if r: results.append(r)

    # ── C3: LGB only + H&Y (old method, for comparison) ──────────────
    r = run_single_lgb("C3_lgb_HY", X_dev, y_dev, X_test, y_test, all_cols, k=150)
    if r: results.append(r)

    # ── C4: Stacking + H&Y, K=200 ────────────────────────────────────
    r = run_stacking("C4_stack_HY_K200", X_dev, y_dev, X_test, y_test, all_cols, k=200)
    if r: results.append(r)

    # ── Report ────────────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print("CEILING STACKING RESULTS (sorted by ENS MAE)")
    print(f"{'='*70}")
    print(f"  {'Config':<25s} {'Raw':>5s} {'K':>4s} {'MAE+/-std':>12s} {'ENS':>7s} {'r':>6s}")
    print(f"  {'-'*65}")
    for r in sorted(results, key=lambda x: x["ens_mae"]):
        print(f"  {r['config']:<25s} {r['n_raw']:>5d} {r['n_sel']:>4d} "
              f"{r['mean_mae']:>5.2f}+/-{r['std_mae']:.2f} {r['ens_mae']:>7.2f} {r['ens_r']:>6.3f}")

    best = min(results, key=lambda x: x["ens_mae"])
    nohy = next((r for r in results if r["config"] == "C0_stack_noHY"), None)
    print(f"\n  SUMMARY:")
    print(f"  Stacking no H&Y (C0):  {nohy['ens_mae']:.2f}" if nohy else "  Stacking no H&Y: N/A")
    print(f"  Best ceiling:          {best['ens_mae']:.2f} ({best['config']})")
    print(f"  Old ceiling (XGB):     6.72")
    print(f"  Delta vs old:          {6.72 - best['ens_mae']:+.2f}")
    print(f"\n  Top features ({best['config']}): {best.get('top10', [])[:5]}")
    print(f"  Runtime: {total:.0f}s ({total/60:.1f}m)")

    with open(RESULTS_FILE, "w") as f:
        json.dump({"results": results, "best_mae": float(best["ens_mae"]),
                   "best_config": best["config"], "runtime_s": round(total, 1)}, f, indent=2)
    print(f"  Saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
