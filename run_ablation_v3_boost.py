"""
Ablation v3: Multi-booster sweep on best feature config from v2.
Tests: XGBoost, LightGBM, CatBoost at feature counts 100/200/300/400.
Also tests cross-booster ensemble.
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

# Reuse all feature extraction from v2
from run_ablation_v2 import (extract_recording, agg_task_preserving, compute_dist_feats,
                              load_covariates, load_walkway, load_hy, distill_walkway,
                              agg_mean, TASKS, N_CORES, SEEDS, E0_EXCLUDE)

RESULTS_FILE = "/root/pd-imu/ablation_v3_results.json"


def train_xgb(Xtr, ytr, Xva, yva, seed):
    from xgboost import XGBRegressor
    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                     reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                     early_stopping_rounds=100, objective="reg:absoluteerror")
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    return m


def train_lgb(Xtr, ytr, Xva, yva, seed):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                          reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                          objective="mae", verbosity=-1)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
          callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    return m


def train_cat(Xtr, ytr, Xva, yva, seed):
    from catboost import CatBoostRegressor
    m = CatBoostRegressor(iterations=2000, learning_rate=0.03, depth=6,
                          l2_leaf_reg=3.0, random_seed=seed, verbose=0,
                          early_stopping_rounds=100, task_type="CPU",
                          thread_count=N_CORES, loss_function="MAE")
    m.fit(Xtr, ytr, eval_set=(Xva, yva), verbose=0)
    return m


def feature_select(X, y, n_feats, feat_names):
    """Select top n_feats using XGBoost importance on a quick split."""
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


def run_sweep(df_feats, dev_sids, test_sids, name):
    """Run multi-booster sweep at multiple feature counts."""
    feat_cols = [c for c in df_feats.columns if c not in ("sid", "updrs3")]
    dev = df_feats[df_feats["sid"].isin(dev_sids)].copy()
    test = df_feats[df_feats["sid"].isin(test_sids)].copy()
    for c in feat_cols:
        dev[c] = dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        test[c] = test[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    Xd = dev[feat_cols].values.astype(np.float32)
    yd = dev["updrs3"].values.astype(np.float32)
    Xt = test[feat_cols].values.astype(np.float32)
    yt = test["updrs3"].values.astype(np.float32)

    boosters = {"xgb": train_xgb, "lgb": train_lgb, "cat": train_cat}
    feat_counts = [100, 150, 200, 300]
    if len(feat_cols) < 300:
        feat_counts = [min(fc, len(feat_cols)) for fc in feat_counts]
        feat_counts = sorted(set(feat_counts))

    all_res = []
    all_test_preds = {}  # (booster, n_feats, seed) -> pred

    for nf in feat_counts:
        if nf >= len(feat_cols):
            top_idx = np.arange(len(feat_cols))
            sel_names = feat_cols
        else:
            top_idx, sel_names = feature_select(Xd, yd, nf, feat_cols)

        Xd_sel = Xd[:, top_idx]
        Xt_sel = Xt[:, top_idx]

        for bname, bfn in boosters.items():
            maes, rs, preds = [], [], []
            for seed in SEEDS:
                rng = np.random.RandomState(seed)
                idx = np.arange(len(Xd_sel))
                rng.shuffle(idx)
                nv = max(1, int(len(idx) * 0.15))
                try:
                    m = bfn(Xd_sel[idx[nv:]], yd[idx[nv:]],
                            Xd_sel[idx[:nv]], yd[idx[:nv]], seed)
                    p = m.predict(Xt_sel)
                    mae = mean_absolute_error(yt, p)
                    r, _ = sp_stats.pearsonr(yt, p)
                    maes.append(mae)
                    rs.append(r)
                    preds.append(p)
                    all_test_preds[(bname, nf, seed)] = p
                except Exception as e:
                    print(f"    {bname} nf={nf} seed={seed}: FAILED {e}")
                    continue

            if preds:
                ep = np.mean(preds, axis=0)
                em = mean_absolute_error(yt, ep)
                er, _ = sp_stats.pearsonr(yt, ep)
                res = {
                    "config": f"{bname}_f{nf}",
                    "booster": bname, "n_feats": nf,
                    "mean_mae": round(float(np.mean(maes)), 3),
                    "std_mae": round(float(np.std(maes)), 3),
                    "ens_mae": round(float(em), 3),
                    "ens_r": round(float(er), 3),
                }
                all_res.append(res)
                print(f"  {res['config']:<15} mean={res['mean_mae']:.2f}+/-{res['std_mae']:.2f} "
                      f"ens={res['ens_mae']:.2f} r={res['ens_r']:.3f}")

    # Cross-booster ensemble: average all predictions across boosters and feature counts
    if all_test_preds:
        # Per feature count: ensemble across boosters
        for nf in feat_counts:
            cross_preds = []
            for bname in boosters:
                for seed in SEEDS:
                    key = (bname, nf, seed)
                    if key in all_test_preds:
                        cross_preds.append(all_test_preds[key])
            if cross_preds:
                ep = np.mean(cross_preds, axis=0)
                em = mean_absolute_error(yt, ep)
                er, _ = sp_stats.pearsonr(yt, ep)
                res = {"config": f"cross_f{nf}", "booster": "cross", "n_feats": nf,
                       "mean_mae": 0, "std_mae": 0,
                       "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3)}
                all_res.append(res)
                print(f"  {'cross_f'+str(nf):<15} ens={res['ens_mae']:.2f} r={res['ens_r']:.3f}")

        # Grand ensemble: all boosters, all feature counts, all seeds
        grand_preds = list(all_test_preds.values())
        ep = np.mean(grand_preds, axis=0)
        em = mean_absolute_error(yt, ep)
        er, _ = sp_stats.pearsonr(yt, ep)
        res = {"config": "grand_ensemble", "booster": "grand", "n_feats": 0,
               "mean_mae": 0, "std_mae": 0,
               "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3)}
        all_res.append(res)
        print(f"  {'grand_ensemble':<15} ens={res['ens_mae']:.2f} r={res['ens_r']:.3f}")

    return all_res, yt


def main():
    t0 = time.time()
    print("=" * 70)
    print("ABLATION v3: MULTI-BOOSTER SWEEP")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    all_sids = dev_sids + test_sids

    # Feature extraction (same as v2)
    print("\nFeature extraction...")
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    jobs = []
    all_tasks = TASKS + [f"{t}_mat" for t in TASKS] + \
                [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
    for task in all_tasks:
        for sid in all_sids:
            if sid not in subjects:
                continue
            d = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
            p = os.path.join(d, f"{sid}_{task}.csv")
            if os.path.exists(p):
                jobs.append((p, sid, task))

    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        all_recs = [r for r in pool.map(extract_recording, jobs) if r is not None]
    main_recs = [r for r in all_recs if "_mat" not in r["task"]]
    mat_recs = [r for r in all_recs if "_mat" in r["task"]]
    print(f"  {len(all_recs)} recordings extracted")

    # Build E12-equivalent feature set (all blocks)
    covs = load_covariates()
    wk = load_walkway()
    hy = load_hy()
    dist = compute_dist_feats(main_recs, subjects)

    # Start from task-preserving aggregation
    df = agg_task_preserving(main_recs, subjects)

    # Add distribution features
    for sid, df_dict in dist.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in df_dict.items():
                if k not in df.columns:
                    df[k] = 0.0
                df.loc[mask, k] = v

    # Add covariates
    for cn in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
        df[cn] = 0.0
    for sid, cv in covs.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in cv.items():
                df.loc[mask, k] = v

    # Add distilled walkway
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

    # Add insole from mat files
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

    n_feats = len([c for c in df.columns if c not in ("sid", "updrs3")])
    print(f"\nFull feature set: {n_feats} features, {len(df)} subjects")

    # === Sweep without H&Y (deployable model) ===
    print(f"\n{'='*70}")
    print("SWEEP: DEPLOYABLE MODEL (no H&Y)")
    print(f"{'='*70}")
    res_deploy, yt = run_sweep(df, dev_sids, test_sids, "deployable")

    # === Sweep with H&Y (ceiling model) ===
    print(f"\n{'='*70}")
    print("SWEEP: CEILING MODEL (+ H&Y)")
    print(f"{'='*70}")
    df_hy = df.copy()
    df_hy["hy"] = 0.0
    for sid, h in hy.items():
        mask = df_hy["sid"] == sid
        if mask.any():
            df_hy.loc[mask, "hy"] = h
    for col in ["cv_yrs", "fc_L_cad", "LowerBack_g_cadence"]:
        if col in df_hy.columns:
            df_hy[f"hy_x_{col}"] = df_hy["hy"] * df_hy[col]
    res_ceiling, _ = run_sweep(df_hy, dev_sids, test_sids, "ceiling")

    # === Summary ===
    all_results = {"deployable": res_deploy, "ceiling": res_ceiling}
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"SWEEP COMPLETE ({elapsed/60:.1f} min)")
    print(f"{'='*70}")
    print("\nDEPLOYABLE (top 5):")
    for r in sorted(res_deploy, key=lambda x: x["ens_mae"])[:5]:
        print(f"  {r['config']:<20} ens={r['ens_mae']:.2f} r={r['ens_r']:.3f}")
    print("\nCEILING (top 5):")
    for r in sorted(res_ceiling, key=lambda x: x["ens_mae"])[:5]:
        print(f"  {r['config']:<20} ens={r['ens_mae']:.2f} r={r['ens_r']:.3f}")

    print(f"\nResults: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
