"""
Apply Stacking + Extended Covariates to the PROVEN 7.97 Pipeline
================================================================
Imports exact feature extraction from run_ablation_v2.py (the pipeline
that achieved MAE=7.97 with 1752 features + K=150 selection).

Experiments:
  S0: Baseline reproduction (LGB K=150)
  S1: + Extended covariates (LGB K=150)
  S2: + Extended covariates (LGB K=160)
  S3: LGB+XGB stacking + extended covariates (K=150)
  S4: LGB+XGB stacking + extended covariates (K=160)
  S5: LGB+XGB simple average + extended covariates (K=150)

Self-contained imports from run_ablation_v2.py + data_split.py.
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
from concurrent.futures import ProcessPoolExecutor
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

from run_ablation_v2 import (
    extract_recording, agg_task_preserving, compute_dist_feats,
    load_covariates, load_walkway, distill_walkway,
    agg_mean, TASKS, N_CORES, SEEDS,
)

FEATURE_CACHE = "/root/pd-imu/proven_stack_features.csv"


def load_extended_covariates():
    """Parse extended clinical covariates NOT in original 5."""
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
            yrs = pd.to_numeric(row.get("Years since PD diagnosis", row.get("Years Since Diagnosis", 0)), errors="coerce")

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
    from xgboost import XGBRegressor
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                        objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgbm(Xd, yd, Xt, seed=42):
    import lightgbm as lgb
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                           reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                           objective="mae", verbose=-1)
    m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
          callbacks=[lgb.early_stopping(100, verbose=False)])
    return m.predict(Xt), m


def train_xgb(Xd, yd, Xt, seed=42):
    from xgboost import XGBRegressor
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                      reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                      early_stopping_rounds=100, objective="reg:absoluteerror")
    m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])], verbose=False)
    return m.predict(Xt), m


def run_single(name, Xd, yd, Xt, yt, fnames, k=150, model_fn=None):
    if model_fn is None:
        model_fn = lambda x, y, t, s: train_lgbm(x, y, t, s)
    k = min(k, Xd.shape[1])
    print(f"\n  {name} ({Xd.shape[1]} raw → K={k})")
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        p, _ = model_fn(Xds, yd, Xts, seed)
        p = np.clip(p, 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")
    return {"config": name, "n_raw": int(Xd.shape[1]), "n_sel": k,
            "mean_mae": round(float(np.mean(maes)), 3), "std_mae": round(float(np.std(maes)), 3),
            "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
            "seed_maes": [round(float(m), 3) for m in maes], "top10": sel_names[:10],
            "ens_preds": [float(x) for x in ep]}


def run_stacking(name, Xd, yd, Xt, yt, fnames, k=150):
    import lightgbm as lgb
    from xgboost import XGBRegressor

    k = min(k, Xd.shape[1])
    print(f"\n  {name} ({Xd.shape[1]} raw → K={k}, L0: LGB+XGB → L1: Ridge)")
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
            "mean_mae": round(float(np.mean(maes)), 3), "std_mae": round(float(np.std(maes)), 3),
            "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
            "seed_maes": [round(float(m), 3) for m in maes], "top10": sel_names[:10],
            "ens_preds": [float(x) for x in ep]}


def run_lgb_xgb_avg(name, Xd, yd, Xt, yt, fnames, k=150):
    k = min(k, Xd.shape[1])
    print(f"\n  {name} ({Xd.shape[1]} raw → K={k}, LGB+XGB avg)")
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        p_l, _ = train_lgbm(Xds, yd, Xts, seed)
        p_x, _ = train_xgb(Xds, yd, Xts, seed)
        p = np.clip(0.6 * p_l + 0.4 * p_x, 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")
    return {"config": name, "n_raw": int(Xd.shape[1]), "n_sel": k,
            "mean_mae": round(float(np.mean(maes)), 3), "std_mae": round(float(np.std(maes)), 3),
            "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
            "seed_maes": [round(float(m), 3) for m in maes], "top10": sel_names[:10],
            "ens_preds": [float(x) for x in ep]}


def main():
    t0 = time.time()
    print("=" * 70)
    print("PROVEN PIPELINE + STACKING + EXTENDED COVARIATES")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    all_sids = dev_sids + test_sids

    # ── Build proven feature matrix (from run_ablation_v2) ────────────
    if os.path.exists(FEATURE_CACHE):
        print(f"Loading cached features from {FEATURE_CACHE}")
        df = pd.read_csv(FEATURE_CACHE)
    else:
        print("Building proven feature matrix (run_ablation_v2 pipeline)...")
        jobs = []
        for task in TASKS:
            for sid in all_sids:
                if sid not in subjects:
                    continue
                info = subjects[sid]
                base = "PD PARTICIPANTS" if info["group"] == "PD" else "CONTROL PARTICIPANTS"
                csv_path = os.path.join(DATA_DIR, base, "CSV files", f"{sid}_{task}.csv")
                if os.path.exists(csv_path):
                    jobs.append((csv_path, sid, task))

        print(f"  Extracting {len(jobs)} recordings on {N_CORES} cores...")
        with ProcessPoolExecutor(max_workers=N_CORES) as pool:
            records = [r for r in pool.map(extract_recording, jobs, chunksize=4) if r is not None]
        print(f"  Done: {len(records)} recordings in {time.time()-t0:.0f}s")

        # Aggregate: mean across tasks
        df = agg_mean(records, subjects)

        # Task-preserving features (contrasts) — returns DataFrame
        df_tp = agg_task_preserving(records, subjects)
        for col in df_tp.columns:
            if col not in ("sid", "updrs3") and col not in df.columns:
                df[col] = df["sid"].map(dict(zip(df_tp["sid"], df_tp[col]))).fillna(0.0)

        # Cross-task variability — returns dict[sid -> dict]
        dist = compute_dist_feats(records, subjects)
        if dist:
            all_dist_keys = set()
            for feats in dist.values():
                all_dist_keys.update(feats.keys())
            for k in sorted(all_dist_keys):
                df[k] = df["sid"].map(lambda s: dist.get(s, {}).get(k, 0.0)).fillna(0.0)

        # Covariates (original) — returns dict[sid -> dict]
        cov = load_covariates()
        if cov:
            all_cov_keys = set()
            for feats in cov.values():
                all_cov_keys.update(feats.keys())
            for k in sorted(all_cov_keys):
                if k not in df.columns:
                    df[k] = df["sid"].map(lambda s, kk=k: cov.get(s, {}).get(kk, 0.0)).fillna(0.0)

        # Walkway distillation — returns dict[sid -> dict] or empty dict
        try:
            wk = load_walkway()
            dist_feats = distill_walkway(df, wk, dev_sids)
            if dist_feats and isinstance(dist_feats, dict):
                all_wk_keys = set()
                for feats in dist_feats.values():
                    if isinstance(feats, dict):
                        all_wk_keys.update(feats.keys())
                for k in sorted(all_wk_keys):
                    if k not in df.columns:
                        df[k] = df["sid"].map(lambda s, kk=k: dist_feats.get(s, {}).get(kk, 0.0)).fillna(0.0)
        except Exception as e:
            print(f"  Walkway distillation skipped: {e}")

        # Clean
        for c in df.columns:
            if c not in ("sid",):
                df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

        df.to_csv(FEATURE_CACHE, index=False)
        print(f"  Cached to {FEATURE_CACHE}")

    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    print(f"Proven features: {len(df)} subjects × {len(feat_cols)} features")

    # ── Add extended covariates ───────────────────────────────────────
    ext_cov = load_extended_covariates()
    ext_names = ["ext_height", "ext_weight", "ext_bmi", "ext_age_onset",
                 "ext_yrs_sq", "ext_yrs_log", "ext_early_pd", "ext_late_pd"]
    for col_name in ext_names:
        df[col_name] = df["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0))
        df[col_name] = df[col_name].fillna(0.0)

    all_cols = feat_cols + ext_names
    print(f"With extended covariates: {len(all_cols)} features (+{len(ext_names)})")

    # ── Prepare arrays ────────────────────────────────────────────────
    dm = df["sid"].isin(dev_sids)
    tm = df["sid"].isin(test_sids)
    X_dev_orig = df.loc[dm, feat_cols].values.astype(np.float32)
    X_dev_ext = df.loc[dm, all_cols].values.astype(np.float32)
    y_dev = df.loc[dm, "updrs3"].values.astype(np.float32)
    X_test_orig = df.loc[tm, feat_cols].values.astype(np.float32)
    X_test_ext = df.loc[tm, all_cols].values.astype(np.float32)
    y_test = df.loc[tm, "updrs3"].values.astype(np.float32)
    print(f"Dev: {len(y_dev)}, Test: {len(y_test)}")

    results = []

    # ── S0: Baseline reproduction ─────────────────────────────────────
    r = run_single("S0_baseline_K150", X_dev_orig, y_dev, X_test_orig, y_test, feat_cols, k=150)
    if r: results.append(r)
    baseline_mae = r["ens_mae"] if r else 99.0

    # ── S1: + Extended covariates, K=150 ──────────────────────────────
    r = run_single("S1_extcov_K150", X_dev_ext, y_dev, X_test_ext, y_test, all_cols, k=150)
    if r: results.append(r)

    # ── S2: + Extended covariates, K=160 ──────────────────────────────
    r = run_single("S2_extcov_K160", X_dev_ext, y_dev, X_test_ext, y_test, all_cols, k=160)
    if r: results.append(r)

    # ── S3: Stacking + extended covariates, K=150 ─────────────────────
    r = run_stacking("S3_stack_ext_K150", X_dev_ext, y_dev, X_test_ext, y_test, all_cols, k=150)
    if r: results.append(r)

    # ── S4: Stacking + extended covariates, K=160 ─────────────────────
    r = run_stacking("S4_stack_ext_K160", X_dev_ext, y_dev, X_test_ext, y_test, all_cols, k=160)
    if r: results.append(r)

    # ── S5: LGB+XGB avg + extended covariates, K=150 ──────────────────
    r = run_lgb_xgb_avg("S5_lgbxgb_ext_K150", X_dev_ext, y_dev, X_test_ext, y_test, all_cols, k=150)
    if r: results.append(r)

    # ── S6: Stacking on original features, K=150 ─────────────────────
    r = run_stacking("S6_stack_orig_K150", X_dev_orig, y_dev, X_test_orig, y_test, feat_cols, k=150)
    if r: results.append(r)

    # ── REPORT ────────────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print("RESULTS (sorted by ENS MAE)")
    print(f"{'='*70}")
    print(f"{'Config':<25s} {'Raw':>5s} {'K':>4s} {'MAE±std':>12s} {'ENS':>7s} {'r':>6s} {'Δ':>6s}")
    print("-" * 70)
    for r in sorted(results, key=lambda x: x["ens_mae"]):
        d = baseline_mae - r["ens_mae"]
        ds = f"+{d:.2f}" if d > 0 else f"{d:.2f}"
        print(f"  {r['config']:<23s} {r['n_raw']:>5d} {r['n_sel']:>4d} "
              f"{r['mean_mae']:>5.2f}±{r['std_mae']:.2f} {r['ens_mae']:>7.2f} {r['ens_r']:>6.3f} {ds:>6s}")

    best = min(results, key=lambda x: x["ens_mae"])
    print(f"\n  Baseline (S0): {baseline_mae:.2f}")
    print(f"  Best:          {best['ens_mae']:.2f} ({best['config']})")
    print(f"  Δ:             {baseline_mae - best['ens_mae']:.2f}")
    print(f"  Established:   7.97")
    print(f"  vs Established:{7.97 - best['ens_mae']:.2f}")
    print(f"\n  Top features ({best['config']}): {best.get('top10', [])[:5]}")
    print(f"  Runtime: {total:.0f}s ({total/60:.1f}m)")

    with open("/root/pd-imu/proven_stack_results.json", "w") as f:
        json.dump({"baseline_mae": float(baseline_mae), "best_mae": float(best["ens_mae"]),
                    "best_config": best["config"], "results": results,
                    "runtime_s": round(total, 1)}, f, indent=2)
    print("  Saved to /root/pd-imu/proven_stack_results.json")


if __name__ == "__main__":
    main()
