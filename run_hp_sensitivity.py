"""
Hyperparameter Sensitivity Analysis for WearGait-PD UPDRS-III Regression
========================================================================
Systematically analyzes how sensitive MAE is to each hyperparameter using:
1. Latin Hypercube Sampling (~100 configs per booster)
2. One-at-a-time (OAT) sensitivity around best config
3. Global sensitivity (correlations, partial correlations, RF importance)
4. Robustness analysis (what % of configs are "good enough")

Produces 4 figures + JSON results.
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.stats.qmc import LatinHypercube
from sklearn.metrics import mean_absolute_error
from sklearn.ensemble import RandomForestRegressor
from concurrent.futures import ProcessPoolExecutor

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib import cm

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

from run_ablation_v2 import (extract_recording, agg_task_preserving, compute_dist_feats,
                              load_covariates, load_walkway, distill_walkway,
                              agg_mean, TASKS, N_CORES, SEEDS)

FIGURES_DIR = "/root/pd-imu/figures"
RESULTS_FILE = "/root/pd-imu/hp_sensitivity_results.json"
os.makedirs(FIGURES_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════
# HP SEARCH SPACE
# ═══════════════════════════════════════════════════════════════════

HP_SPACE = {
    "lightgbm": {
        "n_estimators": [500, 1000, 1500, 2000, 3000],
        "learning_rate": [0.005, 0.01, 0.03, 0.05, 0.1],
        "max_depth": [3, 4, 5, 6, 8, 10],
        "reg_lambda": [0.1, 0.5, 1.0, 3.0, 5.0, 10.0],
        "num_leaves": [15, 31, 63, 127],
        "min_child_samples": [5, 10, 20, 50],
        "subsample": [0.5, 0.7, 0.8, 0.9, 1.0],
        "colsample_bytree": [0.5, 0.7, 0.8, 0.9, 1.0],
    },
    "xgboost": {
        "n_estimators": [500, 1000, 1500, 2000, 3000],
        "learning_rate": [0.005, 0.01, 0.03, 0.05, 0.1],
        "max_depth": [3, 4, 5, 6, 8, 10],
        "reg_lambda": [0.1, 0.5, 1.0, 3.0, 5.0, 10.0],
        "reg_alpha": [0.0, 0.1, 0.5, 1.0],
        "subsample": [0.5, 0.7, 0.8, 0.9, 1.0],
        "colsample_bytree": [0.5, 0.7, 0.8, 0.9, 1.0],
    },
}

BEST_CONFIG = {
    "lightgbm": {
        "n_estimators": 2000,
        "learning_rate": 0.03,
        "max_depth": 6,
        "reg_lambda": 3.0,
        "num_leaves": 31,
        "min_child_samples": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
    },
    "xgboost": {
        "n_estimators": 2000,
        "learning_rate": 0.03,
        "max_depth": 6,
        "reg_lambda": 3.0,
        "reg_alpha": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
    },
}


# ═══════════════════════════════════════════════════════════════════
# FEATURE BUILDING (same as run_shap_explain.py)
# ═══════════════════════════════════════════════════════════════════

def feature_select(X, y, n_feats, feat_names):
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
    """Build full feature set (same as run_shap_explain.py)."""
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

    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        all_recs = [r for r in pool.map(extract_recording, jobs) if r is not None]
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

    return df


# ═══════════════════════════════════════════════════════════════════
# LATIN HYPERCUBE SAMPLING
# ═══════════════════════════════════════════════════════════════════

def generate_lhs_configs(booster, n_configs=100, seed=42):
    """Generate n_configs HP configurations via Latin Hypercube Sampling."""
    hp_ranges = HP_SPACE[booster]
    hp_names = sorted(hp_ranges.keys())
    d = len(hp_names)

    sampler = LatinHypercube(d=d, seed=seed)
    samples = sampler.random(n=n_configs)

    configs = []
    for i in range(n_configs):
        cfg = {}
        for j, hp_name in enumerate(hp_names):
            values = hp_ranges[hp_name]
            # Map [0,1) to index in the discrete values list
            idx = int(samples[i, j] * len(values))
            idx = min(idx, len(values) - 1)  # clamp
            cfg[hp_name] = values[idx]
        configs.append(cfg)

    return configs, hp_names


# ═══════════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════════

def train_eval_config(booster, config, Xtr, ytr, Xva, yva, Xt, yt):
    """Train a model with given HP config and return test MAE, r, and training time."""
    t0 = time.time()

    if booster == "lightgbm":
        import lightgbm as lgb
        m = lgb.LGBMRegressor(
            n_estimators=config["n_estimators"],
            learning_rate=config["learning_rate"],
            max_depth=config["max_depth"],
            reg_lambda=config["reg_lambda"],
            num_leaves=config["num_leaves"],
            min_child_samples=config["min_child_samples"],
            subsample=config["subsample"],
            colsample_bytree=config["colsample_bytree"],
            subsample_freq=1,
            random_state=42,
            n_jobs=N_CORES,
            objective="mae",
            verbosity=-1,
        )
        m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    elif booster == "xgboost":
        from xgboost import XGBRegressor
        m = XGBRegressor(
            n_estimators=config["n_estimators"],
            learning_rate=config["learning_rate"],
            max_depth=config["max_depth"],
            reg_lambda=config["reg_lambda"],
            reg_alpha=config["reg_alpha"],
            subsample=config["subsample"],
            colsample_bytree=config["colsample_bytree"],
            random_state=42,
            n_jobs=N_CORES,
            early_stopping_rounds=100,
            objective="reg:absoluteerror",
        )
        m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    else:
        raise ValueError(f"Unknown booster: {booster}")

    elapsed = time.time() - t0
    preds = m.predict(Xt)
    mae = float(mean_absolute_error(yt, preds))
    r_val = float(sp_stats.pearsonr(yt, preds)[0])
    return mae, r_val, elapsed


# ═══════════════════════════════════════════════════════════════════
# SENSITIVITY ANALYSIS
# ═══════════════════════════════════════════════════════════════════

def compute_partial_correlation(X_df, y_series, target_col):
    """Partial correlation between target_col and y, controlling for all other cols."""
    other_cols = [c for c in X_df.columns if c != target_col]
    if len(other_cols) == 0:
        return sp_stats.pearsonr(X_df[target_col].values, y_series.values)[0]

    # Regress target_col on others, get residual
    from numpy.linalg import lstsq
    Z = X_df[other_cols].values.astype(np.float64)
    Z = np.column_stack([Z, np.ones(len(Z))])

    x_target = X_df[target_col].values.astype(np.float64)
    coef_x, _, _, _ = lstsq(Z, x_target, rcond=None)
    resid_x = x_target - Z @ coef_x

    y_arr = y_series.values.astype(np.float64)
    coef_y, _, _, _ = lstsq(Z, y_arr, rcond=None)
    resid_y = y_arr - Z @ coef_y

    if np.std(resid_x) < 1e-12 or np.std(resid_y) < 1e-12:
        return 0.0
    return float(sp_stats.pearsonr(resid_x, resid_y)[0])


def run_sensitivity_analysis(results_df, hp_names):
    """Compute first-order, partial correlations, and RF importance."""
    mae_values = results_df["mae"].values

    # First-order: Pearson correlation
    pearson_corrs = {}
    for hp in hp_names:
        r, p = sp_stats.pearsonr(results_df[hp].values, mae_values)
        pearson_corrs[hp] = {"r": float(r), "p": float(p)}

    # Partial correlations
    partial_corrs = {}
    hp_df = results_df[hp_names].copy()
    mae_series = results_df["mae"]
    for hp in hp_names:
        pc = compute_partial_correlation(hp_df, mae_series, hp)
        partial_corrs[hp] = float(pc)

    # RF feature importance: predict MAE from HPs
    X_rf = results_df[hp_names].values.astype(np.float64)
    y_rf = mae_values.astype(np.float64)
    rf = RandomForestRegressor(n_estimators=500, max_depth=8, random_state=42, n_jobs=N_CORES)
    rf.fit(X_rf, y_rf)
    rf_importance = {hp: float(imp) for hp, imp in zip(hp_names, rf.feature_importances_)}
    rf_r2 = float(rf.score(X_rf, y_rf))

    return pearson_corrs, partial_corrs, rf_importance, rf_r2


def run_oat_analysis(booster, hp_names, Xtr, ytr, Xva, yva, Xt, yt):
    """One-at-a-time: vary each HP while holding others at best config."""
    best = BEST_CONFIG[booster]
    oat_results = {}

    for hp in hp_names:
        values = HP_SPACE[booster][hp]
        maes = []
        for val in values:
            cfg = dict(best)
            cfg[hp] = val
            mae, r_val, elapsed = train_eval_config(booster, cfg, Xtr, ytr, Xva, yva, Xt, yt)
            maes.append({"value": val, "mae": mae, "r": r_val, "time_s": elapsed})
            print(f"    OAT {hp}={val}: MAE={mae:.2f} r={r_val:.3f} ({elapsed:.1f}s)")
        oat_results[hp] = maes

    return oat_results


# ═══════════════════════════════════════════════════════════════════
# VISUALIZATIONS
# ═══════════════════════════════════════════════════════════════════

def plot_sensitivity_matrix(pearson_corrs, partial_corrs, rf_importance, hp_names, booster, path):
    """Heatmap: HP vs sensitivity metric."""
    methods = ["Pearson r", "Partial r", "RF Importance"]
    data = np.zeros((len(hp_names), 3))

    for i, hp in enumerate(hp_names):
        data[i, 0] = pearson_corrs[hp]["r"]
        data[i, 1] = partial_corrs[hp]
        data[i, 2] = rf_importance[hp]

    fig, ax = plt.subplots(figsize=(8, max(5, len(hp_names) * 0.6)))
    im = ax.imshow(data, cmap="RdYlBu_r", aspect="auto", vmin=-1, vmax=1)
    # RF importance is [0,1], so override that column color
    # Use a separate normalization for display clarity
    ax.set_xticks(range(3))
    ax.set_xticklabels(methods, fontsize=11)
    ax.set_yticks(range(len(hp_names)))
    ax.set_yticklabels(hp_names, fontsize=11)

    for i in range(len(hp_names)):
        for j in range(3):
            val = data[i, j]
            color = "white" if abs(val) > 0.5 else "black"
            ax.text(j, i, f"{val:.3f}", ha="center", va="center", fontsize=10, color=color)

    plt.colorbar(im, ax=ax, label="Correlation / Importance", shrink=0.8)
    ax.set_title(f"HP Sensitivity Matrix ({booster.upper()})", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_marginal_effects(results_df, hp_names, booster, path):
    """2x4 subplot: HP value vs MAE with LOESS smoother."""
    n_plots = len(hp_names)
    ncols = 4
    nrows = (n_plots + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 4 * nrows))
    axes = axes.flatten() if n_plots > 1 else [axes]

    for i, hp in enumerate(hp_names):
        ax = axes[i]
        x = results_df[hp].values.astype(np.float64)
        y = results_df["mae"].values.astype(np.float64)

        ax.scatter(x, y, alpha=0.4, s=15, c="#3498db", edgecolors="none")

        # LOESS smoother via sorted binned means
        unique_vals = np.sort(np.unique(x))
        if len(unique_vals) >= 3:
            bin_means_x = []
            bin_means_y = []
            for uv in unique_vals:
                mask = x == uv
                if mask.sum() > 0:
                    bin_means_x.append(uv)
                    bin_means_y.append(np.mean(y[mask]))
            ax.plot(bin_means_x, bin_means_y, "r-o", linewidth=2, markersize=5, label="Mean MAE")

        # Annotate best value
        best_val = BEST_CONFIG[booster][hp]
        ax.axvline(best_val, color="green", linestyle="--", alpha=0.7, label=f"Best={best_val}")

        # Acceptable range: values where mean MAE < best_mean + 0.5
        if len(unique_vals) >= 3 and bin_means_y:
            best_mae = min(bin_means_y)
            acceptable = [bx for bx, by in zip(bin_means_x, bin_means_y) if by < best_mae + 0.5]
            if len(acceptable) >= 2:
                ax.axvspan(min(acceptable), max(acceptable), alpha=0.1, color="green")

        ax.set_xlabel(hp, fontsize=10)
        ax.set_ylabel("Test MAE", fontsize=10)
        ax.legend(fontsize=7, loc="upper right")
        ax.set_title(hp, fontsize=11, fontweight="bold")

    # Hide unused subplots
    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    fig.suptitle(f"Marginal Effects of Hyperparameters ({booster.upper()})", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_interactions(results_df, hp_names, rf_importance, booster, path):
    """Top 3 HP pairs: pairwise scatter colored by MAE."""
    # Rank HPs by RF importance
    ranked = sorted(hp_names, key=lambda h: rf_importance[h], reverse=True)
    top3 = ranked[:3]

    pairs = [(top3[0], top3[1]), (top3[0], top3[2]), (top3[1], top3[2])]
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    mae_vals = results_df["mae"].values
    norm = Normalize(vmin=np.percentile(mae_vals, 5), vmax=np.percentile(mae_vals, 95))
    cmap_obj = cm.RdYlGn_r

    for idx, (hp1, hp2) in enumerate(pairs):
        ax = axes[idx]
        x = results_df[hp1].values.astype(np.float64)
        y = results_df[hp2].values.astype(np.float64)
        sc = ax.scatter(x, y, c=mae_vals, cmap=cmap_obj, norm=norm, s=30, alpha=0.7, edgecolors="k", linewidths=0.3)
        ax.set_xlabel(hp1, fontsize=11)
        ax.set_ylabel(hp2, fontsize=11)
        ax.set_title(f"{hp1} vs {hp2}", fontsize=11, fontweight="bold")
        plt.colorbar(sc, ax=ax, label="MAE", shrink=0.8)

    fig.suptitle(f"HP Interaction Heatmaps ({booster.upper()})", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_robustness(all_maes, booster, path):
    """CDF of MAE across all configs."""
    sorted_maes = np.sort(all_maes)
    cdf = np.arange(1, len(sorted_maes) + 1) / len(sorted_maes)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(sorted_maes, cdf * 100, "b-", linewidth=2)
    ax.fill_between(sorted_maes, 0, cdf * 100, alpha=0.1, color="blue")

    # Annotate thresholds
    thresholds = [8.5, 9.0, 10.0]
    colors = ["green", "orange", "red"]
    for thr, col in zip(thresholds, colors):
        pct = float(np.mean(sorted_maes < thr) * 100)
        ax.axvline(thr, color=col, linestyle="--", alpha=0.7)
        ax.annotate(f"MAE<{thr}: {pct:.0f}%", xy=(thr, pct),
                   xytext=(thr + 0.3, max(pct - 10, 5)),
                   fontsize=10, color=col, fontweight="bold",
                   arrowprops=dict(arrowstyle="->", color=col, alpha=0.7))

    ax.set_xlabel("Test MAE", fontsize=12)
    ax.set_ylabel("% of Configurations", fontsize=12)
    ax.set_title(f"HP Robustness Curve ({booster.upper()})", fontsize=14, fontweight="bold")
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    print("=" * 70)
    print("HYPERPARAMETER SENSITIVITY ANALYSIS")
    print("=" * 70)

    # ── Step 1: Feature extraction ──────────────────────────────────
    print("\n[1/6] Feature extraction...")
    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    df = build_features(subjects, dev_sids, test_sids)

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

    # Feature selection
    top_idx, sel_names = feature_select(Xd, yd, 150, feat_cols)
    Xd_sel = Xd[:, top_idx]
    Xt_sel = Xt[:, top_idx]
    print(f"  {len(sel_names)} features selected, {len(dev)} dev, {len(test)} test subjects")

    # Fixed train/val split (seed=42, 15% val)
    rng = np.random.RandomState(42)
    idx = np.arange(len(Xd_sel))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    Xtr = Xd_sel[idx[nv:]]
    ytr = yd[idx[nv:]]
    Xva = Xd_sel[idx[:nv]]
    yva = yd[idx[:nv]]
    print(f"  Train: {len(Xtr)}, Val: {len(Xva)}, Test: {len(Xt_sel)}")

    all_results = {}

    # ── Step 2-5: Run per booster ───────────────────────────────────
    for booster in ["lightgbm", "xgboost"]:
        print(f"\n{'='*70}")
        print(f"BOOSTER: {booster.upper()}")
        print(f"{'='*70}")

        hp_names = sorted(HP_SPACE[booster].keys())

        # ── Step 2: LHS sweep ──────────────────────────────────────
        print(f"\n[2/6] Latin Hypercube Sampling ({booster})...")
        configs, _ = generate_lhs_configs(booster, n_configs=100, seed=42)
        print(f"  Generated {len(configs)} configs across {len(hp_names)} HPs")

        sweep_results = []
        for ci, cfg in enumerate(configs):
            mae, r_val, elapsed = train_eval_config(
                booster, cfg, Xtr, ytr, Xva, yva, Xt_sel, yt)
            row = dict(cfg)
            row["mae"] = mae
            row["r"] = r_val
            row["time_s"] = elapsed
            sweep_results.append(row)

            if (ci + 1) % 10 == 0:
                best_so_far = min(sweep_results, key=lambda x: x["mae"])
                print(f"  [{ci+1:3d}/100] MAE={mae:.2f} r={r_val:.3f} "
                      f"({elapsed:.1f}s) | Best so far: {best_so_far['mae']:.2f}")

        results_df = pd.DataFrame(sweep_results)
        best_lhs = results_df.loc[results_df["mae"].idxmin()]
        worst_lhs = results_df.loc[results_df["mae"].idxmax()]
        print(f"\n  LHS Best:  MAE={best_lhs['mae']:.2f} r={best_lhs['r']:.3f}")
        print(f"  LHS Worst: MAE={worst_lhs['mae']:.2f} r={worst_lhs['r']:.3f}")
        print(f"  LHS Mean:  MAE={results_df['mae'].mean():.2f} +/- {results_df['mae'].std():.2f}")

        # ── Step 3: OAT analysis ───────────────────────────────────
        print(f"\n[3/6] One-at-a-time sensitivity ({booster})...")
        oat_results = run_oat_analysis(booster, hp_names, Xtr, ytr, Xva, yva, Xt_sel, yt)

        # ── Step 4: Global sensitivity ─────────────────────────────
        print(f"\n[4/6] Global sensitivity analysis ({booster})...")
        pearson_corrs, partial_corrs, rf_importance, rf_r2 = run_sensitivity_analysis(results_df, hp_names)
        print(f"  RF R2 (predicting MAE from HPs): {rf_r2:.3f}")

        # Rank by absolute Pearson r
        ranked = sorted(hp_names, key=lambda h: abs(pearson_corrs[h]["r"]), reverse=True)
        print(f"\n  SENSITIVITY RANKING (Pearson |r| with MAE):")
        for rank, hp in enumerate(ranked):
            pc = pearson_corrs[hp]
            pr = partial_corrs[hp]
            ri = rf_importance[hp]
            print(f"    {rank+1}. {hp:<22s} Pearson={pc['r']:+.3f} (p={pc['p']:.3f})  "
                  f"Partial={pr:+.3f}  RF={ri:.3f}")

        # ── Step 4b: Robustness analysis ───────────────────────────
        all_maes = results_df["mae"].values
        pct_lt_85 = float(np.mean(all_maes < 8.5) * 100)
        pct_lt_90 = float(np.mean(all_maes < 9.0) * 100)
        pct_gt_100 = float(np.mean(all_maes > 10.0) * 100)
        print(f"\n  ROBUSTNESS:")
        print(f"    MAE < 8.5 (within ~0.5 of best):  {pct_lt_85:.0f}%")
        print(f"    MAE < 9.0 (reasonable):            {pct_lt_90:.0f}%")
        print(f"    MAE > 10.0 (bad):                  {pct_gt_100:.0f}%")

        # ── Step 5: Visualizations ─────────────────────────────────
        print(f"\n[5/6] Generating figures ({booster})...")
        suffix = f"_{booster}" if booster != "lightgbm" else ""

        plot_sensitivity_matrix(
            pearson_corrs, partial_corrs, rf_importance, hp_names, booster,
            os.path.join(FIGURES_DIR, f"hp_sensitivity_matrix{suffix}.png"))

        plot_marginal_effects(
            results_df, hp_names, booster,
            os.path.join(FIGURES_DIR, f"hp_marginal_effects{suffix}.png"))

        plot_interactions(
            results_df, hp_names, rf_importance, booster,
            os.path.join(FIGURES_DIR, f"hp_interactions{suffix}.png"))

        plot_robustness(
            all_maes, booster,
            os.path.join(FIGURES_DIR, f"hp_robustness{suffix}.png"))

        # ── Store results ──────────────────────────────────────────
        # Determine recommendation
        sensitive_hps = [hp for hp in ranked if abs(pearson_corrs[hp]["r"]) > 0.2]
        robust_hps = [hp for hp in ranked if abs(pearson_corrs[hp]["r"]) <= 0.2]

        # Compute safe ranges from OAT
        safe_ranges = {}
        for hp in hp_names:
            oat_vals = oat_results[hp]
            oat_maes = [v["mae"] for v in oat_vals]
            best_oat_mae = min(oat_maes)
            acceptable = [v["value"] for v in oat_vals if v["mae"] < best_oat_mae + 0.5]
            safe_ranges[hp] = {"min": min(acceptable), "max": max(acceptable),
                               "best": BEST_CONFIG[booster][hp]}

        all_results[booster] = {
            "n_configs": len(configs),
            "best_mae": float(best_lhs["mae"]),
            "worst_mae": float(worst_lhs["mae"]),
            "mean_mae": float(results_df["mae"].mean()),
            "std_mae": float(results_df["mae"].std()),
            "best_config": {k: float(v) if isinstance(v, (np.floating, float)) else int(v)
                           for k, v in best_lhs.items() if k in hp_names},
            "sensitivity_ranking": [
                {
                    "hp": hp,
                    "pearson_r": pearson_corrs[hp]["r"],
                    "pearson_p": pearson_corrs[hp]["p"],
                    "partial_r": partial_corrs[hp],
                    "rf_importance": rf_importance[hp],
                } for hp in ranked
            ],
            "robustness": {
                "pct_lt_8.5": pct_lt_85,
                "pct_lt_9.0": pct_lt_90,
                "pct_gt_10.0": pct_gt_100,
            },
            "oat": {hp: oat_results[hp] for hp in hp_names},
            "safe_ranges": safe_ranges,
            "rf_r2": rf_r2,
            "sensitive_hps": sensitive_hps,
            "robust_hps": robust_hps,
            "sweep_results": [
                {k: (float(v) if isinstance(v, (np.floating, float)) else int(v) if isinstance(v, (np.integer, int)) else v)
                 for k, v in row.items()}
                for row in sweep_results
            ],
        }

    # ── Step 6: Save + Report ──────────────────────────────────────
    print(f"\n[6/6] Saving results...")
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Saved: {RESULTS_FILE}")

    # Print final report
    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"HP SENSITIVITY ANALYSIS COMPLETE ({elapsed/60:.1f} min)")
    print(f"{'='*70}")

    for booster in ["lightgbm", "xgboost"]:
        res = all_results[booster]
        print(f"\n--- {booster.upper()} ---")
        print(f"Configs tested: {res['n_configs']} (Latin Hypercube)")
        print(f"Best MAE:  {res['best_mae']:.2f}")
        print(f"Worst MAE: {res['worst_mae']:.2f}")
        print(f"Mean MAE:  {res['mean_mae']:.2f} +/- {res['std_mae']:.2f}")

        print(f"\nSENSITIVITY RANKING (most to least sensitive):")
        for i, entry in enumerate(res["sensitivity_ranking"]):
            hp = entry["hp"]
            sr = res["safe_ranges"][hp]
            print(f"  {i+1}. {hp:<22s} Corr={entry['pearson_r']:+.3f}  "
                  f"Best={sr['best']}  Range=[{sr['min']}, {sr['max']}]")

        print(f"\nROBUSTNESS:")
        rob = res["robustness"]
        print(f"  MAE < 8.5 (within ~0.5 of best): {rob['pct_lt_8.5']:.0f}% of configs")
        print(f"  MAE < 9.0 (reasonable):           {rob['pct_lt_9.0']:.0f}% of configs")
        print(f"  MAE > 10.0 (bad):                 {rob['pct_gt_10.0']:.0f}% of configs")

        if res["sensitive_hps"]:
            is_robust = len(res["sensitive_hps"]) <= 2
            status = "ROBUST" if is_robust else "SENSITIVE"
            print(f"\nRECOMMENDATION:")
            print(f"  The model is {status} to HP choices.")
            print(f"  Critical HPs: {', '.join(res['sensitive_hps'])}")
            print(f"  Safe HPs:     {', '.join(res['robust_hps'])}")
        else:
            print(f"\nRECOMMENDATION:")
            print(f"  The model is ROBUST to HP choices. No HP has |r| > 0.2 with MAE.")

    print(f"\nResults: {RESULTS_FILE}")
    print(f"Figures: {FIGURES_DIR}/hp_*.png")


if __name__ == "__main__":
    main()
