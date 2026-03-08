"""
Generate predicted vs actual scatter plot for the paper.
Trains the best model (LightGBM, 150 features) and saves predictions.
"""
import os, sys, json, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS
from run_ablation_v2 import (extract_recording, agg_task_preserving, compute_dist_feats,
                              load_covariates, load_walkway, distill_walkway,
                              agg_mean, TASKS, N_CORES, SEEDS)
from concurrent.futures import ProcessPoolExecutor

plt.rcParams.update({
    'font.size': 10, 'font.family': 'serif', 'axes.labelsize': 11,
    'axes.titlesize': 12, 'figure.dpi': 300, 'savefig.dpi': 300,
    'savefig.bbox': 'tight',
})

OUT_DIR = "/root/pd-imu/figures"


def main():
    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    all_sids = dev_sids + test_sids

    # Feature extraction
    print("Extracting features...")
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    jobs = []
    all_tasks = TASKS + [f"{t}_mat" for t in TASKS] + \
                [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
    for task in all_tasks:
        for sid in all_sids:
            if sid not in subjects: continue
            d = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
            p = os.path.join(d, f"{sid}_{task}.csv")
            if os.path.exists(p): jobs.append((p, sid, task))

    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        all_recs = [r for r in pool.map(extract_recording, jobs) if r is not None]
    main_recs = [r for r in all_recs if "_mat" not in r["task"]]
    mat_recs = [r for r in all_recs if "_mat" in r["task"]]

    # Build full feature set
    covs = load_covariates()
    wk = load_walkway()
    dist = compute_dist_feats(main_recs, subjects)

    df = agg_task_preserving(main_recs, subjects)
    for sid, d in dist.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in d.items():
                if k not in df.columns: df[k] = 0.0
                df.loc[mask, k] = v
    for cn in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
        df[cn] = 0.0
    for sid, cv in covs.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in cv.items(): df.loc[mask, k] = v
    if wk:
        dst = distill_walkway(df, wk, dev_sids)
        if dst:
            for dc in sorted(set().union(*[set(v.keys()) for v in dst.values()])):
                df[dc] = 0.0
            for sid, dm in dst.items():
                mask = df["sid"] == sid
                if mask.any():
                    for k, v in dm.items(): df.loc[mask, k] = v
    if mat_recs:
        df_mat = agg_mean(mat_recs, subjects)
        for ic in [c for c in df_mat.columns if c.startswith("ins_")]:
            df[ic] = 0.0
            for _, row in df_mat.iterrows():
                mask = df["sid"] == row["sid"]
                if mask.any() and ic in row and np.isfinite(row[ic]):
                    df.loc[mask, ic] = row[ic]

    # Prepare data
    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    dev = df[df["sid"].isin(dev_sids)].copy()
    test = df[df["sid"].isin(test_sids)].copy()
    for c in feat_cols:
        dev[c] = dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        test[c] = test[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    Xd = dev[feat_cols].values.astype(np.float32)
    yd = dev["updrs3"].values.astype(np.float32)
    Xt = test[feat_cols].values.astype(np.float32)
    yt = test["updrs3"].values.astype(np.float32)
    test_groups = [subjects[s]["group"] for s in test["sid"].values]

    # Feature selection to 150
    from xgboost import XGBRegressor
    rng = np.random.RandomState(42)
    idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    sel_m = XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6,
                         reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                         early_stopping_rounds=50, objective="reg:absoluteerror")
    sel_m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])], verbose=False)
    top = np.argsort(sel_m.feature_importances_)[::-1][:150]
    sel_names = [feat_cols[i] for i in top]
    Xd = dev[sel_names].values.astype(np.float32)
    Xt = test[sel_names].values.astype(np.float32)

    # Train LightGBM ensemble
    import lightgbm as lgb
    all_preds = []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd)); rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                              reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                              objective="mae", verbosity=-1)
        m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
        all_preds.append(m.predict(Xt))

    ens_pred = np.mean(all_preds, axis=0)
    mae = mean_absolute_error(yt, ens_pred)
    r, p = sp_stats.pearsonr(yt, ens_pred)
    print(f"Ensemble: MAE={mae:.2f}, r={r:.3f}")

    # === Scatter plot ===
    fig, ax = plt.subplots(figsize=(6, 6))
    pd_mask = np.array([g == "PD" for g in test_groups])
    hc_mask = ~pd_mask

    ax.scatter(yt[hc_mask], ens_pred[hc_mask], c='#2196F3', s=60, alpha=0.7,
              edgecolors='black', linewidth=0.5, label=f'HC (N={hc_mask.sum()})', zorder=3)
    ax.scatter(yt[pd_mask], ens_pred[pd_mask], c='#F44336', s=60, alpha=0.7,
              edgecolors='black', linewidth=0.5, label=f'PD (N={pd_mask.sum()})', zorder=3)

    # Identity line
    lims = [min(yt.min(), ens_pred.min()) - 2, max(yt.max(), ens_pred.max()) + 2]
    ax.plot(lims, lims, 'k--', alpha=0.3, linewidth=1.5, label='Perfect prediction')

    # ±MCID band
    x_line = np.linspace(lims[0], lims[1], 100)
    ax.fill_between(x_line, x_line - 4.63, x_line + 4.63, alpha=0.08, color='green',
                    label='±MCID (4.63)')

    ax.set_xlabel('Actual UPDRS-III Score')
    ax.set_ylabel('Predicted UPDRS-III Score')
    ax.set_title(f'Predicted vs. Actual UPDRS-III (MAE={mae:.2f}, r={r:.3f})')
    ax.set_xlim(lims)
    ax.set_ylim(lims)
    ax.set_aspect('equal')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)

    # Annotation
    ax.text(0.95, 0.05, f'N = 36 held-out\nMAE = {mae:.2f}\nr = {r:.3f}\np < 0.001',
            transform=ax.transAxes, ha='right', va='bottom', fontsize=9,
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig(f'{OUT_DIR}/fig8_scatter.pdf')
    plt.savefig(f'{OUT_DIR}/fig8_scatter.png')
    plt.close()
    print("  Fig 8: Scatter plot saved")

    # === Residual plot ===
    residuals = ens_pred - yt
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.scatter(yt[hc_mask], residuals[hc_mask], c='#2196F3', s=50, alpha=0.7,
              edgecolors='black', linewidth=0.5, label='HC')
    ax.scatter(yt[pd_mask], residuals[pd_mask], c='#F44336', s=50, alpha=0.7,
              edgecolors='black', linewidth=0.5, label='PD')
    ax.axhline(0, color='black', linestyle='--', alpha=0.3)
    ax.axhline(4.63, color='green', linestyle=':', alpha=0.4, label='+MCID')
    ax.axhline(-4.63, color='green', linestyle=':', alpha=0.4, label='-MCID')
    ax.set_xlabel('Actual UPDRS-III Score')
    ax.set_ylabel('Prediction Residual (Predicted - Actual)')
    ax.set_title('Residual Analysis')
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{OUT_DIR}/fig9_residuals.pdf')
    plt.savefig(f'{OUT_DIR}/fig9_residuals.png')
    plt.close()
    print("  Fig 9: Residual plot saved")

    # === UPDRS distribution ===
    fig, ax = plt.subplots(figsize=(8, 4))
    bins = np.arange(0, 65, 5)
    dev_scores = [subjects[s]["updrs3"] for s in dev_sids if s in subjects]
    test_scores_all = [subjects[s]["updrs3"] for s in test_sids if s in subjects]
    ax.hist(dev_scores, bins=bins, alpha=0.5, color='#2196F3', label=f'Dev (N={len(dev_scores)})',
            edgecolor='black', linewidth=0.5)
    ax.hist(test_scores_all, bins=bins, alpha=0.5, color='#F44336', label=f'Test (N={len(test_scores_all)})',
            edgecolor='black', linewidth=0.5)
    ax.set_xlabel('UPDRS-III Total Score')
    ax.set_ylabel('Number of Subjects')
    ax.set_title('UPDRS-III Score Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{OUT_DIR}/fig10_updrs_dist.pdf')
    plt.savefig(f'{OUT_DIR}/fig10_updrs_dist.png')
    plt.close()
    print("  Fig 10: UPDRS distribution saved")

    # Save predictions for supplementary
    pred_df = pd.DataFrame({
        "sid": test["sid"].values,
        "group": test_groups,
        "actual": yt,
        "predicted": ens_pred,
        "residual": residuals,
    })
    pred_df.to_csv("/root/pd-imu/test_predictions.csv", index=False)
    print("  Predictions saved to test_predictions.csv")


if __name__ == "__main__":
    main()
