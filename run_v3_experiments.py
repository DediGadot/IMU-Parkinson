"""
V3 Experiments: Proven Feature Pipeline + New Analyses
======================================================
Uses the EXACT feature pipeline from run_ablation_v2 + run_hp_sensitivity
that achieved MAE=7.97. Adds:
  1. Baseline reproduction (5-seed ensemble with winning HP config)
  2. Observable-subtotal prediction
  3. PD-only LOOCV (for literature comparison)
  4. Stratified val splits (fix seed 456 pathology)
  5. Expanded feature counts (200, 300)
  6. XGBoost ceiling with H&Y
"""
import os, sys, json, time, gc, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import LeaveOneOut
from concurrent.futures import ProcessPoolExecutor

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

from run_ablation_v2 import (
    extract_recording, agg_task_preserving, compute_dist_feats,
    load_covariates, load_walkway, distill_walkway,
    agg_mean, TASKS, N_CORES, SEEDS,
)

RESULTS_FILE = "/root/pd-imu/v3_results.json"
FEATURE_CACHE = "/root/pd-imu/v3_features.csv"

# Observable UPDRS-III subitems (items assessable from gait IMU)
OBSERVABLE = [
    "MDSUPDRS_3-9",       # arising from chair
    "MDSUPDRS_3-10",      # gait
    "MDSUPDRS_3-11",      # freezing of gait
    "MDSUPDRS_3-12",      # postural stability
    "MDSUPDRS_3-13",      # posture
    "MDSUPDRS_3-14",      # body bradykinesia
    "MDSUPDRS_3-8-L",     # leg agility L
    "MDSUPDRS_3-8-R",     # leg agility R
]

# Partially observable (some signal from IMU but less direct)
PARTIAL_OBSERVABLE = [
    "MDSUPDRS_3-15-L",    # postural tremor L
    "MDSUPDRS_3-15-R",    # postural tremor R
    "MDSUPDRS_3-7-L",     # toe tapping L
    "MDSUPDRS_3-7-R",     # toe tapping R
]


def parse_clinical_with_subitems():
    """Parse clinical data with UPDRS-III subitems and covariates.

    Uses sum(skipna=True) for total — subjects with partially missing subitems
    get sum of available items (treating missing as 0).
    """
    subjects = {}
    for filename, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        u3cols = sorted([c for c in df.columns if c.startswith("MDSUPDRS_3-")])
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            vals = pd.to_numeric(row[u3cols], errors="coerce")
            updrs3 = vals.sum()  # skipna=True default
            if np.isnan(updrs3):
                continue
            updrs3 = float(updrs3)
            # Subitems
            subitems = {}
            for c in u3cols:
                v = pd.to_numeric(row[c], errors="coerce")
                subitems[c] = float(v) if pd.notna(v) else 0.0
            obs_score = sum(subitems.get(c, 0.0) for c in OBSERVABLE)
            part_score = sum(subitems.get(c, 0.0) for c in PARTIAL_OBSERVABLE)
            # Covariates
            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            sex = 1.0 if str(row.get("Sex", "")).strip().upper().startswith("M") else 0.0
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", 0)), errors="coerce")
            dbs_raw = str(row.get("DBS?", row.get("DBS", ""))).strip().upper()
            hy_raw = pd.to_numeric(row.get("H&Y", row.get("Hoehn & Yahr", np.nan)), errors="coerce")
            subjects[sid] = {
                "group": group, "label": 1 if group == "PD" else 0,
                "updrs3": updrs3,
                "observable_score": obs_score,
                "partial_score": part_score,
                "obs_plus_partial": obs_score + part_score,
                "subitems": subitems,
                "hy": float(hy_raw) if pd.notna(hy_raw) else 0.0,
            }
    return subjects


def feature_select(X, y, n_feats, feat_names):
    """Single-seed XGBoost importance-based feature selection (reproduces original)."""
    from xgboost import XGBRegressor
    rng = np.random.RandomState(42)
    idx = np.arange(len(X))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    m = XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6,
                     reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                     early_stopping_rounds=50, objective="reg:absoluteerror")
    m.fit(X[idx[nv:]], y[idx[nv:]], eval_set=[(X[idx[:nv]], y[idx[:nv]])], verbose=False)
    top = np.argsort(m.feature_importances_)[::-1][:n_feats]
    return top, [feat_names[i] for i in top]


def build_features(subjects, dev_sids, test_sids):
    """Build full feature set (EXACT same pipeline as run_hp_sensitivity.py)."""
    if os.path.exists(FEATURE_CACHE):
        print(f"  Loading cached features from {FEATURE_CACHE}")
        df = pd.read_csv(FEATURE_CACHE)
        return df

    all_sids = dev_sids + test_sids
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    all_tasks = TASKS + [f"{t}_mat" for t in TASKS] + \
                [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
    jobs = []
    for task in all_tasks:
        for sid in all_sids:
            if sid not in subjects:
                continue
            d = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
            p = os.path.join(d, f"{sid}_{task}.csv")
            if os.path.exists(p):
                jobs.append((p, sid, task))

    print(f"  Extracting features from {len(jobs)} recordings using {N_CORES} cores...")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        all_recs = [r for r in pool.map(extract_recording, jobs) if r is not None]
    print(f"  Done: {len(all_recs)} recordings in {time.time()-t0:.0f}s")

    main_recs = [r for r in all_recs if "_mat" not in r["task"]]
    mat_recs = [r for r in all_recs if "_mat" in r["task"]]

    covs = load_covariates()
    wk = load_walkway()
    dist = compute_dist_feats(main_recs, subjects)
    df = agg_task_preserving(main_recs, subjects)

    for sid, df_dict in dist.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in df_dict.items():
                if k not in df.columns:
                    df[k] = 0.0
                df.loc[mask, k] = v

    for cn in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
        df[cn] = 0.0
    for sid, cv in covs.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in cv.items():
                df.loc[mask, k] = v

    if wk:
        dst = distill_walkway(df, wk, dev_sids)
        if dst:
            for dc in sorted(set().union(*[set(v.keys()) for v in dst.values()])):
                df[dc] = 0.0
            for sid, dm in dst.items():
                mask = df["sid"] == sid
                if mask.any():
                    for k, v in dm.items():
                        df.loc[mask, k] = v

    if mat_recs:
        df_mat = agg_mean(mat_recs, subjects)
        ins_cols = [c for c in df_mat.columns if c.startswith("ins_")]
        for ic in ins_cols:
            df[ic] = 0.0
        for _, row in df_mat.iterrows():
            sid = row["sid"]
            mask = df["sid"] == sid
            if mask.any():
                for ic in ins_cols:
                    if ic in row and np.isfinite(row[ic]):
                        df.loc[mask, ic] = row[ic]

    df.to_csv(FEATURE_CACHE, index=False)
    print(f"  Saved {len(df)} subjects × {len(df.columns)} columns to {FEATURE_CACHE}")
    return df


def run_lgb_experiment(name, X_dev, y_dev, X_test, y_test, config, seeds=SEEDS):
    """Run LightGBM with given config, multi-seed ensemble."""
    import lightgbm as lgb
    print(f"\n--- {name} ---")
    print(f"  Features: {X_dev.shape[1]}, Dev: {X_dev.shape[0]}, Test: {X_test.shape[0]}")
    seed_maes, seed_rs, seed_preds = [], [], []
    for seed in seeds:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(X_dev))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        Xtr, ytr = X_dev[idx[nv:]], y_dev[idx[nv:]]
        Xva, yva = X_dev[idx[:nv]], y_dev[idx[:nv]]
        m = lgb.LGBMRegressor(**config, random_state=seed, n_jobs=N_CORES,
                              objective="mae", verbose=-1)
        m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
              callbacks=[lgb.early_stopping(100, verbose=False)])
        pred = m.predict(X_test)
        mae = mean_absolute_error(y_test, pred)
        r, _ = sp_stats.pearsonr(y_test, pred) if len(y_test) > 2 else (0.0, 1.0)
        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}")
        seed_maes.append(mae)
        seed_rs.append(r)
        seed_preds.append(pred.tolist())
    ens_pred = np.mean([np.array(p) for p in seed_preds], axis=0)
    ens_mae = mean_absolute_error(y_test, ens_pred)
    ens_r, _ = sp_stats.pearsonr(y_test, ens_pred) if len(y_test) > 2 else (0.0, 1.0)
    print(f"  MEAN: MAE={np.mean(seed_maes):.2f}+/-{np.std(seed_maes):.2f}, r={np.mean(seed_rs):.3f}")
    print(f"  ENS:  MAE={ens_mae:.2f}, r={ens_r:.3f}")
    return {
        "name": name,
        "mean_mae": round(np.mean(seed_maes), 3),
        "std_mae": round(np.std(seed_maes), 3),
        "ens_mae": round(ens_mae, 3),
        "ens_r": round(ens_r, 3),
        "individual_mae": [round(m, 3) for m in seed_maes],
        "individual_r": [round(r, 3) for r in seed_rs],
        "test_true": y_test.tolist(),
        "test_preds": seed_preds,
    }


def run_xgb_experiment(name, X_dev, y_dev, X_test, y_test, config, seeds=SEEDS):
    """Run XGBoost with given config, multi-seed ensemble."""
    from xgboost import XGBRegressor
    print(f"\n--- {name} ---")
    print(f"  Features: {X_dev.shape[1]}, Dev: {X_dev.shape[0]}, Test: {X_test.shape[0]}")
    seed_maes, seed_rs, seed_preds = [], [], []
    for seed in seeds:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(X_dev))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        Xtr, ytr = X_dev[idx[nv:]], y_dev[idx[nv:]]
        Xva, yva = X_dev[idx[:nv]], y_dev[idx[:nv]]
        m = XGBRegressor(**config, random_state=seed, n_jobs=N_CORES,
                         objective="reg:absoluteerror", early_stopping_rounds=100)
        m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
        pred = m.predict(X_test)
        mae = mean_absolute_error(y_test, pred)
        r, _ = sp_stats.pearsonr(y_test, pred) if len(y_test) > 2 else (0.0, 1.0)
        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}")
        seed_maes.append(mae)
        seed_rs.append(r)
        seed_preds.append(pred.tolist())
    ens_pred = np.mean([np.array(p) for p in seed_preds], axis=0)
    ens_mae = mean_absolute_error(y_test, ens_pred)
    ens_r, _ = sp_stats.pearsonr(y_test, ens_pred) if len(y_test) > 2 else (0.0, 1.0)
    print(f"  MEAN: MAE={np.mean(seed_maes):.2f}+/-{np.std(seed_maes):.2f}, r={np.mean(seed_rs):.3f}")
    print(f"  ENS:  MAE={ens_mae:.2f}, r={ens_r:.3f}")
    return {
        "name": name,
        "mean_mae": round(np.mean(seed_maes), 3),
        "std_mae": round(np.std(seed_maes), 3),
        "ens_mae": round(ens_mae, 3),
        "ens_r": round(ens_r, 3),
        "individual_mae": [round(m, 3) for m in seed_maes],
        "individual_r": [round(r, 3) for r in seed_rs],
        "test_true": y_test.tolist(),
        "test_preds": seed_preds,
    }


def main():
    T0 = time.time()
    print("=" * 80)
    print("V3 EXPERIMENTS: PROVEN PIPELINE + NEW ANALYSES")
    print("Baseline: LightGBM 150 features -> MAE=7.97, r=0.821")
    print("=" * 80)

    # ── Load data ─────────────────────────────────────────────────────
    subjects = parse_clinical_with_subitems()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    print(f"Subjects: {len(subjects)}, Dev: {len(dev_sids)}, Test: {len(test_sids)}")

    # Resume logic
    all_results = []
    done_names = set()
    if os.path.exists(RESULTS_FILE):
        all_results = json.load(open(RESULTS_FILE))
        done_names = {r["name"] for r in all_results}
        print(f"  Resuming: {len(done_names)} experiments done")

    def save():
        with open(RESULTS_FILE, "w") as f:
            json.dump(all_results, f, indent=2, default=str)

    # ── Build features (proven pipeline) ──────────────────────────────
    print("\n" + "=" * 80)
    print("FEATURE EXTRACTION (proven pipeline from run_ablation_v2)")
    print("=" * 80)
    df = build_features(subjects, dev_sids, test_sids)

    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    dev_mask = df["sid"].isin(dev_sids)
    test_mask = df["sid"].isin(test_sids)
    df_dev = df[dev_mask].copy()
    df_test = df[test_mask].copy()
    for c in feat_cols:
        df_dev[c] = df_dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        df_test[c] = df_test[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    X_dev_all = df_dev[feat_cols].values.astype(np.float32)
    y_dev = df_dev["updrs3"].values.astype(np.float32)
    X_test_all = df_test[feat_cols].values.astype(np.float32)
    y_test = df_test["updrs3"].values.astype(np.float32)
    dev_sids_feat = df_dev["sid"].values
    test_sids_feat = df_test["sid"].values
    print(f"Total features: {len(feat_cols)}, Dev: {len(df_dev)}, Test: {len(df_test)}")

    # ── Feature selection ─────────────────────────────────────────────
    print("\n  Feature selection (single-seed XGBoost)...")
    top150, sel150 = feature_select(X_dev_all, y_dev, 150, feat_cols)
    top200, sel200 = feature_select(X_dev_all, y_dev, 200, feat_cols)
    top300, sel300 = feature_select(X_dev_all, y_dev, 300, feat_cols)
    print(f"  Selected 150/200/300 features")

    Xd150, Xt150 = X_dev_all[:, top150], X_test_all[:, top150]
    Xd200, Xt200 = X_dev_all[:, top200], X_test_all[:, top200]
    Xd300, Xt300 = X_dev_all[:, top300], X_test_all[:, top300]

    # Winning LightGBM config from HP sensitivity sweep
    LGB_BEST = {
        "n_estimators": 1000,
        "learning_rate": 0.1,
        "max_depth": 6,
        "reg_lambda": 5.0,
        "num_leaves": 15,
        "min_child_samples": 5,
        "subsample": 0.5,
        "colsample_bytree": 1.0,
    }

    # Default LightGBM config (from run_biomechanics.py)
    LGB_DEFAULT = {
        "n_estimators": 2000,
        "learning_rate": 0.03,
        "max_depth": 6,
        "reg_lambda": 3.0,
    }

    # XGBoost best config
    XGB_BEST = {
        "n_estimators": 1000,
        "learning_rate": 0.05,
        "max_depth": 8,
        "reg_lambda": 10.0,
        "reg_alpha": 1.0,
        "subsample": 0.8,
        "colsample_bytree": 0.9,
    }

    # ══════════════════════════════════════════════════════════════════
    # EXPERIMENT 1: BASELINE REPRODUCTION
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("EXP 1: BASELINE REPRODUCTION")
    print("=" * 80)

    exp_name = "E1: LGB best-HP 150 feats"
    if exp_name not in done_names:
        r = run_lgb_experiment(exp_name, Xd150, y_dev, Xt150, y_test, LGB_BEST)
        all_results.append(r)
        save()

    exp_name = "E2: LGB default 150 feats"
    if exp_name not in done_names:
        r = run_lgb_experiment(exp_name, Xd150, y_dev, Xt150, y_test, LGB_DEFAULT)
        all_results.append(r)
        save()

    exp_name = "E3: LGB best-HP 200 feats"
    if exp_name not in done_names:
        r = run_lgb_experiment(exp_name, Xd200, y_dev, Xt200, y_test, LGB_BEST)
        all_results.append(r)
        save()

    exp_name = "E4: LGB best-HP 300 feats"
    if exp_name not in done_names:
        r = run_lgb_experiment(exp_name, Xd300, y_dev, Xt300, y_test, LGB_BEST)
        all_results.append(r)
        save()

    # ══════════════════════════════════════════════════════════════════
    # EXPERIMENT 2: XGB CEILING WITH H&Y
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("EXP 2: XGB CEILING WITH H&Y")
    print("=" * 80)

    exp_name = "E5: XGB best-HP 150 feats"
    if exp_name not in done_names:
        r = run_xgb_experiment(exp_name, Xd150, y_dev, Xt150, y_test, XGB_BEST)
        all_results.append(r)
        save()

    # Add H&Y as feature
    hy_dev = np.array([subjects.get(s, {}).get("hy", 0.0) for s in dev_sids_feat]).reshape(-1, 1)
    hy_test = np.array([subjects.get(s, {}).get("hy", 0.0) for s in test_sids_feat]).reshape(-1, 1)
    Xd150_hy = np.hstack([Xd150, hy_dev.astype(np.float32)])
    Xt150_hy = np.hstack([Xt150, hy_test.astype(np.float32)])

    exp_name = "E6: XGB 150 feats + H&Y (ceiling)"
    if exp_name not in done_names:
        r = run_xgb_experiment(exp_name, Xd150_hy, y_dev, Xt150_hy, y_test, XGB_BEST)
        all_results.append(r)
        save()

    # ══════════════════════════════════════════════════════════════════
    # EXPERIMENT 3: OBSERVABLE SUBTOTAL
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("EXP 3: OBSERVABLE SUBTOTAL PREDICTION")
    print("=" * 80)

    # Build observable subtotal targets
    y_dev_obs = np.array([subjects.get(s, {}).get("observable_score", 0.0) for s in dev_sids_feat], dtype=np.float32)
    y_test_obs = np.array([subjects.get(s, {}).get("observable_score", 0.0) for s in test_sids_feat], dtype=np.float32)
    print(f"  Observable subtotal: dev mean={y_dev_obs.mean():.1f}, test mean={y_test_obs.mean():.1f}")

    exp_name = "E7: LGB observable subtotal 150 feats"
    if exp_name not in done_names:
        r = run_lgb_experiment(exp_name, Xd150, y_dev_obs, Xt150, y_test_obs, LGB_BEST)
        all_results.append(r)
        save()

    # Observable + partial
    y_dev_obsp = np.array([subjects.get(s, {}).get("obs_plus_partial", 0.0) for s in dev_sids_feat], dtype=np.float32)
    y_test_obsp = np.array([subjects.get(s, {}).get("obs_plus_partial", 0.0) for s in test_sids_feat], dtype=np.float32)

    exp_name = "E8: LGB obs+partial subtotal 150 feats"
    if exp_name not in done_names:
        r = run_lgb_experiment(exp_name, Xd150, y_dev_obsp, Xt150, y_test_obsp, LGB_BEST)
        all_results.append(r)
        save()

    # Two-stage: predict observable -> predict total
    exp_name = "E9: Two-stage obs->total"
    if exp_name not in done_names:
        import lightgbm as lgb
        print(f"\n--- {exp_name} ---")
        # Stage 1: predict observable subtotal for all subjects
        obs_preds_dev = np.zeros(len(y_dev))
        obs_preds_test = np.zeros(len(y_test))
        for seed in SEEDS:
            rng = np.random.RandomState(seed)
            idx = np.arange(len(Xd150))
            rng.shuffle(idx)
            nv = max(1, int(len(idx) * 0.15))
            m = lgb.LGBMRegressor(**LGB_BEST, random_state=seed, n_jobs=N_CORES,
                                      objective="mae", verbose=-1)
            m.fit(Xd150[idx[nv:]], y_dev_obs[idx[nv:]],
                  eval_set=[(Xd150[idx[:nv]], y_dev_obs[idx[:nv]])],
                  callbacks=[lgb.early_stopping(100, verbose=False)])
            obs_preds_dev += m.predict(Xd150)
            obs_preds_test += m.predict(Xt150)
        obs_preds_dev /= len(SEEDS)
        obs_preds_test /= len(SEEDS)
        # Stage 2: predict total from features + predicted observable
        Xd_s2 = np.hstack([Xd150, obs_preds_dev.reshape(-1, 1)])
        Xt_s2 = np.hstack([Xt150, obs_preds_test.reshape(-1, 1)])
        r = run_lgb_experiment(exp_name, Xd_s2, y_dev, Xt_s2, y_test, LGB_BEST)
        all_results.append(r)
        save()

    # ══════════════════════════════════════════════════════════════════
    # EXPERIMENT 4: PD-ONLY LOOCV
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("EXP 4: PD-ONLY LOOCV (literature comparison)")
    print("=" * 80)

    exp_name = "E10: PD-only LOOCV"
    if exp_name not in done_names:
        import lightgbm as lgb
        # Use ALL PD subjects (both dev and test)
        pd_mask = np.array([subjects.get(s, {}).get("group") == "PD" for s in
                           list(dev_sids_feat) + list(test_sids_feat)])
        X_all = np.vstack([X_dev_all, X_test_all])
        y_all = np.concatenate([y_dev, y_test])
        sids_all = np.concatenate([dev_sids_feat, test_sids_feat])

        X_pd = X_all[pd_mask]
        y_pd = y_all[pd_mask]
        sids_pd = sids_all[pd_mask]
        print(f"  PD subjects: {len(X_pd)}, UPDRS mean={y_pd.mean():.1f}")

        # Feature selection on PD-only
        top_pd, _ = feature_select(X_pd, y_pd, 150, feat_cols)
        X_pd_sel = X_pd[:, top_pd]

        loo = LeaveOneOut()
        preds = np.zeros(len(y_pd))
        for i, (tr_idx, te_idx) in enumerate(loo.split(X_pd_sel)):
            m = lgb.LGBMRegressor(**LGB_BEST, random_state=42, n_jobs=N_CORES,
                                  objective="mae", verbose=-1)
            # Use 15% of training for validation
            rng = np.random.RandomState(42)
            shuf = tr_idx.copy()
            rng.shuffle(shuf)
            nv = max(1, int(len(shuf) * 0.15))
            m.fit(X_pd_sel[shuf[nv:]], y_pd[shuf[nv:]],
                  eval_set=[(X_pd_sel[shuf[:nv]], y_pd[shuf[:nv]])],
                  callbacks=[lgb.early_stopping(100, verbose=False)])
            preds[te_idx] = m.predict(X_pd_sel[te_idx])
            if (i + 1) % 20 == 0:
                print(f"  LOOCV: {i+1}/{len(y_pd)}")

        loocv_mae = mean_absolute_error(y_pd, preds)
        loocv_r, _ = sp_stats.pearsonr(y_pd, preds)
        print(f"  PD-only LOOCV: MAE={loocv_mae:.2f}, r={loocv_r:.3f}")
        all_results.append({
            "name": exp_name,
            "ens_mae": round(loocv_mae, 3),
            "ens_r": round(loocv_r, 3),
            "n_subjects": len(y_pd),
            "method": "LOOCV",
        })
        save()

    # ══════════════════════════════════════════════════════════════════
    # EXPERIMENT 5: STRATIFIED VAL SPLITS
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("EXP 5: STRATIFIED VAL SPLITS")
    print("=" * 80)

    exp_name = "E11: LGB stratified-val 150 feats"
    if exp_name not in done_names:
        import lightgbm as lgb
        from sklearn.model_selection import StratifiedShuffleSplit
        print(f"\n--- {exp_name} ---")
        # Bin dev UPDRS for stratification
        bins = np.digitize(y_dev, [0, 5, 15, 25, 40, 80]) - 1
        seed_maes, seed_rs, seed_preds = [], [], []
        for seed in SEEDS:
            sss = StratifiedShuffleSplit(n_splits=1, test_size=0.15, random_state=seed)
            tr_idx, va_idx = next(sss.split(Xd150, bins))
            m = lgb.LGBMRegressor(**LGB_BEST, random_state=seed, n_jobs=N_CORES,
                                  objective="mae", verbose=-1)
            m.fit(Xd150[tr_idx], y_dev[tr_idx],
                  eval_set=[(Xd150[va_idx], y_dev[va_idx])],
                  callbacks=[lgb.early_stopping(100, verbose=False)])
            pred = m.predict(Xt150)
            mae = mean_absolute_error(y_test, pred)
            r, _ = sp_stats.pearsonr(y_test, pred)
            print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}")
            seed_maes.append(mae)
            seed_rs.append(r)
            seed_preds.append(pred.tolist())
        ens_pred = np.mean([np.array(p) for p in seed_preds], axis=0)
        ens_mae = mean_absolute_error(y_test, ens_pred)
        ens_r, _ = sp_stats.pearsonr(y_test, ens_pred)
        print(f"  MEAN: MAE={np.mean(seed_maes):.2f}+/-{np.std(seed_maes):.2f}")
        print(f"  ENS:  MAE={ens_mae:.2f}, r={ens_r:.3f}")
        all_results.append({
            "name": exp_name,
            "mean_mae": round(np.mean(seed_maes), 3),
            "std_mae": round(np.std(seed_maes), 3),
            "ens_mae": round(ens_mae, 3),
            "ens_r": round(ens_r, 3),
            "individual_mae": [round(m, 3) for m in seed_maes],
            "individual_r": [round(r, 3) for r in seed_rs],
        })
        save()

    # ══════════════════════════════════════════════════════════════════
    # EXPERIMENT 6: ALL FEATURES (NO SELECTION)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("EXP 6: ALL FEATURES (NO SELECTION)")
    print("=" * 80)

    exp_name = "E12: LGB all features (no selection)"
    if exp_name not in done_names:
        r = run_lgb_experiment(exp_name, X_dev_all, y_dev, X_test_all, y_test, LGB_BEST)
        all_results.append(r)
        save()

    # ══════════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════════════
    elapsed = (time.time() - T0) / 60
    print(f"\n{'='*80}")
    print(f"FINAL SUMMARY ({elapsed:.1f} min)")
    print(f"{'='*80}")
    print(f"  Baseline: LightGBM 150 features -> MAE=7.97, r=0.821\n")
    print(f"  {'#':>3} {'Model':<45} {'ENS MAE':>8} {'ENS r':>7}")
    print(f"  {'-'*65}")
    for i, r in enumerate(sorted(all_results, key=lambda x: x.get("ens_mae", 999))):
        flag = " ***" if r.get("ens_mae", 999) < 7.97 else ""
        print(f"  {i+1:3d} {r['name']:<45} {r.get('ens_mae','?'):>8} {r.get('ens_r','?'):>7}{flag}")

    print(f"\nResults: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
