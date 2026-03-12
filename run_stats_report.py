"""
Statistical Rigor Report for WearGait-PD UPDRS-III Regression
=============================================================
Generates publication-ready statistical analysis:
1. BCa bootstrap CIs for MAE, r, RMSE, median AE
2. Paired permutation tests between models
3. Clinical significance analysis (MCID, Bland-Altman)
4. Score-range breakdown (mild/moderate/severe)
5. Seed stability analysis
6. LaTeX output table
7. Scatter + Bland-Altman plots
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error, mean_squared_error
from concurrent.futures import ProcessPoolExecutor

warnings.filterwarnings("ignore")
from project_paths import (
    FIGURES_DIR as FIGURES_DIR_PATH,
    REPO_ROOT,
    load_json_artifact,
    save_json_artifact,
)

sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

from run_ablation_v2 import (extract_recording, agg_task_preserving, compute_dist_feats,
                              load_covariates, load_walkway, load_hy, distill_walkway,
                              agg_mean, TASKS, N_CORES, SEEDS, E0_EXCLUDE)

MCID_IMPROVE = 3.25
MCID_WORSEN = 4.63
N_BOOTSTRAP = 10000
RESULTS_DIR = "/root/pd-imu"
FIGURES_DIR = str(FIGURES_DIR_PATH)

os.makedirs(FIGURES_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# 1. FEATURE EXTRACTION + MODEL TRAINING (re-use v3 pipeline)
# ═══════════════════════════════════════════════════════════════════

def train_lgb(Xtr, ytr, Xva, yva, seed):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                          reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                          objective="mae", verbosity=-1)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
          callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    return m


def train_xgb(Xtr, ytr, Xva, yva, seed):
    from xgboost import XGBRegressor
    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                     reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                     early_stopping_rounds=100, objective="reg:absoluteerror")
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
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
    """Build E12-equivalent feature set (all blocks, no H&Y)."""
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
    print(f"  {len(all_recs)} recordings extracted")

    covs = load_covariates()
    wk = load_walkway()
    dist = compute_dist_feats(main_recs, subjects)

    df = agg_task_preserving(main_recs, subjects)

    # Distribution features
    for sid, df_dict in dist.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in df_dict.items():
                if k not in df.columns:
                    df[k] = 0.0
                df.loc[mask, k] = v

    # Covariates
    for cn in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
        df[cn] = 0.0
    for sid, cv in covs.items():
        mask = df["sid"] == sid
        if mask.any():
            for k, v in cv.items():
                df.loc[mask, k] = v

    # Walkway distillation
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

    # Insole from mat files
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


def train_all_models(df, dev_sids, test_sids, subjects):
    """Train LGB/XGB/CAT at 150 features, return per-subject predictions."""
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
    test_sids_ordered = test["sid"].values.tolist()
    test_groups = [subjects[s]["group"] for s in test_sids_ordered]

    top_idx, sel_names = feature_select(Xd, yd, 150, feat_cols)
    Xd_sel = Xd[:, top_idx]
    Xt_sel = Xt[:, top_idx]

    boosters = {"lgb": train_lgb, "xgb": train_xgb, "cat": train_cat}
    results = {}

    for bname, bfn in boosters.items():
        seed_preds = []
        seed_maes = []
        seed_rs = []
        for seed in SEEDS:
            rng = np.random.RandomState(seed)
            idx = np.arange(len(Xd_sel))
            rng.shuffle(idx)
            nv = max(1, int(len(idx) * 0.15))
            m = bfn(Xd_sel[idx[nv:]], yd[idx[nv:]],
                     Xd_sel[idx[:nv]], yd[idx[:nv]], seed)
            p = m.predict(Xt_sel)
            mae = mean_absolute_error(yt, p)
            r, _ = sp_stats.pearsonr(yt, p)
            seed_preds.append(p)
            seed_maes.append(mae)
            seed_rs.append(r)
            print(f"  {bname} seed={seed}: MAE={mae:.3f} r={r:.3f}")

        ens_pred = np.mean(seed_preds, axis=0)
        ens_mae = mean_absolute_error(yt, ens_pred)
        ens_r, _ = sp_stats.pearsonr(yt, ens_pred)
        print(f"  {bname} ENSEMBLE: MAE={ens_mae:.3f} r={ens_r:.3f}")

        results[bname] = {
            "seed_preds": [p.tolist() for p in seed_preds],
            "seed_maes": seed_maes,
            "seed_rs": seed_rs,
            "ens_pred": ens_pred.tolist(),
            "ens_mae": float(ens_mae),
            "ens_r": float(ens_r),
        }

    # Also add ceiling (LGB + H&Y)
    hy = load_hy()
    df_hy = df.copy()
    df_hy["hy"] = 0.0
    for sid, h in hy.items():
        mask = df_hy["sid"] == sid
        if mask.any():
            df_hy.loc[mask, "hy"] = h
    for col in ["cv_yrs", "fc_L_cad", "LowerBack_g_cadence"]:
        if col in df_hy.columns:
            df_hy[f"hy_x_{col}"] = df_hy["hy"] * df_hy[col]

    feat_cols_hy = [c for c in df_hy.columns if c not in ("sid", "updrs3")]
    dev_hy = df_hy[df_hy["sid"].isin(dev_sids)].copy()
    test_hy = df_hy[df_hy["sid"].isin(test_sids)].copy()
    for c in feat_cols_hy:
        dev_hy[c] = dev_hy[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        test_hy[c] = test_hy[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    Xd_hy = dev_hy[feat_cols_hy].values.astype(np.float32)
    yd_hy = dev_hy["updrs3"].values.astype(np.float32)
    Xt_hy = test_hy[feat_cols_hy].values.astype(np.float32)
    top_hy, _ = feature_select(Xd_hy, yd_hy, 150, feat_cols_hy)
    Xd_hy_sel = Xd_hy[:, top_hy]
    Xt_hy_sel = Xt_hy[:, top_hy]

    ceiling_preds = []
    ceiling_maes = []
    ceiling_rs = []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd_hy_sel))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = train_xgb(Xd_hy_sel[idx[nv:]], yd_hy[idx[nv:]],
                       Xd_hy_sel[idx[:nv]], yd_hy[idx[:nv]], seed)
        p = m.predict(Xt_hy_sel)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        ceiling_preds.append(p)
        ceiling_maes.append(mae)
        ceiling_rs.append(r)
        print(f"  ceiling seed={seed}: MAE={mae:.3f} r={r:.3f}")

    ens_pred_c = np.mean(ceiling_preds, axis=0)
    ens_mae_c = mean_absolute_error(yt, ens_pred_c)
    ens_r_c, _ = sp_stats.pearsonr(yt, ens_pred_c)
    print(f"  ceiling ENSEMBLE: MAE={ens_mae_c:.3f} r={ens_r_c:.3f}")

    results["ceiling"] = {
        "seed_preds": [p.tolist() for p in ceiling_preds],
        "seed_maes": ceiling_maes,
        "seed_rs": ceiling_rs,
        "ens_pred": ens_pred_c.tolist(),
        "ens_mae": float(ens_mae_c),
        "ens_r": float(ens_r_c),
    }

    meta = {
        "test_sids": test_sids_ordered,
        "test_true": yt.tolist(),
        "test_groups": test_groups,
        "selected_features": sel_names,
    }
    return results, meta


def load_stack_predictions(meta):
    """Load the best stack predictions from the saved artifact for stats/reporting."""
    benchmark, source = load_json_artifact("clean_benchmark_results.json")
    results = {row["config"]: row for row in benchmark.get("results", [])}
    stack = results.get("S6_stack_orig_K150")
    if stack is None:
        raise KeyError("S6_stack_orig_K150 not found in clean_benchmark_results.json")

    preds = stack["ens_preds"]
    if len(preds) != len(meta["test_true"]):
        raise ValueError("Stack prediction length does not match current held-out test set")

    return {
        "seed_preds": [preds],
        "seed_maes": [float(stack["ens_mae"])],
        "seed_rs": [float(stack["ens_r"])],
        "ens_pred": preds,
        "ens_mae": float(stack["ens_mae"]),
        "ens_r": float(stack["ens_r"]),
        "source_artifact": str(source),
        "seed_source": "ensemble_only",
    }


# ═══════════════════════════════════════════════════════════════════
# 2. BOOTSTRAP CONFIDENCE INTERVALS (BCa)
# ═══════════════════════════════════════════════════════════════════

def bca_ci(data_func, y_true, y_pred, groups, n_boot=N_BOOTSTRAP, alpha=0.05):
    """Bias-corrected accelerated bootstrap CI.

    data_func: callable(y_true, y_pred) -> scalar metric
    Returns: (point_estimate, ci_low, ci_high)
    """
    rng = np.random.RandomState(42)
    n = len(y_true)
    theta_hat = data_func(y_true, y_pred)

    # Bootstrap distribution (stratified by group)
    pd_idx = np.where(np.array(groups) == "PD")[0]
    hc_idx = np.where(np.array(groups) == "HC")[0]
    boot_thetas = np.empty(n_boot)
    for b in range(n_boot):
        if len(pd_idx) > 0 and len(hc_idx) > 0:
            bi_pd = rng.choice(pd_idx, size=len(pd_idx), replace=True)
            bi_hc = rng.choice(hc_idx, size=len(hc_idx), replace=True)
            bi = np.concatenate([bi_pd, bi_hc])
        else:
            bi = rng.choice(n, size=n, replace=True)
        boot_thetas[b] = data_func(y_true[bi], y_pred[bi])

    # Bias correction
    z0 = sp_stats.norm.ppf(np.mean(boot_thetas < theta_hat))

    # Acceleration (jackknife)
    jack_thetas = np.empty(n)
    for i in range(n):
        idx = np.concatenate([np.arange(i), np.arange(i+1, n)])
        jack_thetas[i] = data_func(y_true[idx], y_pred[idx])
    jack_mean = jack_thetas.mean()
    num = np.sum((jack_mean - jack_thetas)**3)
    den = 6.0 * (np.sum((jack_mean - jack_thetas)**2))**1.5
    a = num / den if abs(den) > 1e-12 else 0.0

    # BCa adjusted percentiles
    z_alpha = sp_stats.norm.ppf(alpha / 2)
    z_1alpha = sp_stats.norm.ppf(1 - alpha / 2)

    p_low = sp_stats.norm.cdf(z0 + (z0 + z_alpha) / (1 - a * (z0 + z_alpha)))
    p_high = sp_stats.norm.cdf(z0 + (z0 + z_1alpha) / (1 - a * (z0 + z_1alpha)))

    # Clamp to [0.5/n_boot, 1 - 0.5/n_boot] for safety
    p_low = np.clip(p_low, 0.5 / n_boot, 1 - 0.5 / n_boot)
    p_high = np.clip(p_high, 0.5 / n_boot, 1 - 0.5 / n_boot)

    sorted_boot = np.sort(boot_thetas)
    ci_low = sorted_boot[int(np.floor(p_low * n_boot))]
    ci_high = sorted_boot[min(int(np.floor(p_high * n_boot)), n_boot - 1)]

    return float(theta_hat), float(ci_low), float(ci_high)


def compute_bootstrap_cis(y_true, y_pred, groups):
    """Compute BCa CIs for all key metrics."""
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    def mae_func(yt, yp): return np.mean(np.abs(yt - yp))
    def rmse_func(yt, yp): return np.sqrt(np.mean((yt - yp)**2))
    def med_ae_func(yt, yp): return np.median(np.abs(yt - yp))
    def r_func(yt, yp):
        if np.std(yt) < 1e-8 or np.std(yp) < 1e-8:
            return 0.0
        return float(sp_stats.pearsonr(yt, yp)[0])

    results = {}

    # Overall
    results["mae"] = bca_ci(mae_func, y_true, y_pred, groups)
    results["rmse"] = bca_ci(rmse_func, y_true, y_pred, groups)
    results["median_ae"] = bca_ci(med_ae_func, y_true, y_pred, groups)
    results["r"] = bca_ci(r_func, y_true, y_pred, groups)

    # PD-only
    pd_mask = np.array(groups) == "PD"
    if pd_mask.sum() > 2:
        pd_groups = [g for g in np.array(groups)[pd_mask]]
        results["mae_pd"] = bca_ci(mae_func, y_true[pd_mask], y_pred[pd_mask], pd_groups)
        results["r_pd"] = bca_ci(r_func, y_true[pd_mask], y_pred[pd_mask], pd_groups)

    # HC-only
    hc_mask = np.array(groups) == "HC"
    if hc_mask.sum() > 2:
        hc_groups = [g for g in np.array(groups)[hc_mask]]
        results["mae_hc"] = bca_ci(mae_func, y_true[hc_mask], y_pred[hc_mask], hc_groups)

    return results


# ═══════════════════════════════════════════════════════════════════
# 3. PERMUTATION TESTS
# ═══════════════════════════════════════════════════════════════════

def paired_permutation_test(y_true, pred_a, pred_b, n_perm=N_BOOTSTRAP):
    """One-sided permutation test: is model A significantly better (lower MAE) than B?"""
    rng = np.random.RandomState(42)
    y_true = np.array(y_true)
    pred_a = np.array(pred_a)
    pred_b = np.array(pred_b)

    abs_err_a = np.abs(y_true - pred_a)
    abs_err_b = np.abs(y_true - pred_b)
    obs_diff = abs_err_b.mean() - abs_err_a.mean()  # positive = A is better

    perm_diffs = np.empty(n_perm)
    for i in range(n_perm):
        swap = rng.random(len(y_true)) < 0.5
        ea = np.where(swap, abs_err_b, abs_err_a)
        eb = np.where(swap, abs_err_a, abs_err_b)
        perm_diffs[i] = eb.mean() - ea.mean()

    p_value = float(np.mean(perm_diffs >= obs_diff))

    # Cohen's d
    diff = abs_err_b - abs_err_a
    d = float(diff.mean() / (diff.std() + 1e-12))

    # Paired bootstrap CI for the difference
    boot_diffs = np.empty(n_perm)
    for i in range(n_perm):
        bi = rng.choice(len(y_true), size=len(y_true), replace=True)
        boot_diffs[i] = abs_err_b[bi].mean() - abs_err_a[bi].mean()
    ci_low = float(np.percentile(boot_diffs, 2.5))
    ci_high = float(np.percentile(boot_diffs, 97.5))

    return {
        "obs_diff_mae": float(obs_diff),
        "p_value": p_value,
        "cohens_d": d,
        "diff_ci_95": [ci_low, ci_high],
    }


# ═══════════════════════════════════════════════════════════════════
# 4. CLINICAL SIGNIFICANCE
# ═══════════════════════════════════════════════════════════════════

def clinical_analysis(y_true, y_pred, groups):
    """Comprehensive clinical significance analysis."""
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    residuals = y_pred - y_true
    abs_err = np.abs(residuals)

    # MCID analysis
    within_mcid_improve = float(np.mean(abs_err <= MCID_IMPROVE))
    within_mcid_worsen = float(np.mean(abs_err <= MCID_WORSEN))

    # Bland-Altman
    mean_scores = (y_true + y_pred) / 2
    bias = float(residuals.mean())
    loa_std = float(residuals.std())
    loa_lower = bias - 1.96 * loa_std
    loa_upper = bias + 1.96 * loa_std

    # Score-range breakdown
    ranges = {
        "mild_0_10": (0, 10),
        "moderate_10_20": (10, 20),
        "mod_severe_20_35": (20, 35),
        "severe_35plus": (35, 100),
    }
    range_results = {}
    for rname, (lo, hi) in ranges.items():
        if rname == "severe_35plus":
            mask = y_true >= lo
        else:
            mask = (y_true >= lo) & (y_true < hi)
        n_range = int(mask.sum())
        if n_range > 0:
            range_results[rname] = {
                "n": n_range,
                "mae": float(abs_err[mask].mean()),
                "median_ae": float(np.median(abs_err[mask])),
                "bias": float(residuals[mask].mean()),
            }

    # Residual diagnostics
    _, normality_p = sp_stats.shapiro(residuals) if len(residuals) < 5000 else (0, 0)
    spearman_r, spearman_p = sp_stats.spearmanr(y_true, residuals)

    # Heteroscedasticity: Breusch-Pagan-like (correlation of squared residuals with true)
    _, hetero_p = sp_stats.spearmanr(y_true, residuals**2)

    return {
        "within_mcid_3.25": within_mcid_improve,
        "within_mcid_4.63": within_mcid_worsen,
        "bland_altman": {
            "bias": bias,
            "loa_lower": float(loa_lower),
            "loa_upper": float(loa_upper),
            "loa_std": loa_std,
        },
        "score_range_breakdown": range_results,
        "residual_diagnostics": {
            "mean_residual": bias,
            "std_residual": loa_std,
            "skewness": float(sp_stats.skew(residuals)),
            "kurtosis": float(sp_stats.kurtosis(residuals)),
            "shapiro_p": float(normality_p),
            "spearman_bias_rho": float(spearman_r),
            "spearman_bias_p": float(spearman_p),
            "heteroscedasticity_p": float(hetero_p),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 5. SEED STABILITY
# ═══════════════════════════════════════════════════════════════════

def seed_stability(y_true, seed_preds, seed_maes, seed_rs):
    """Analyze prediction stability across seeds."""
    y_true = np.array(y_true)
    seed_preds = [np.array(p) for p in seed_preds]
    n_seeds = len(seed_preds)

    # Per-seed metrics
    per_seed = []
    for i, (mae, r) in enumerate(zip(seed_maes, seed_rs)):
        per_seed.append({"seed": SEEDS[i], "mae": float(mae), "r": float(r)})

    # Ensemble vs mean of individuals
    ens_pred = np.mean(seed_preds, axis=0)
    ens_mae = float(mean_absolute_error(y_true, ens_pred))
    mean_individual_mae = float(np.mean(seed_maes))
    ens_benefit = mean_individual_mae - ens_mae

    # CV of MAE across seeds
    cv_mae = float(np.std(seed_maes) / (np.mean(seed_maes) + 1e-12))

    # Prediction correlation across seeds (how consistent are they?)
    pred_corrs = []
    for i in range(n_seeds):
        for j in range(i + 1, n_seeds):
            r, _ = sp_stats.pearsonr(seed_preds[i], seed_preds[j])
            pred_corrs.append(float(r))

    mean_inter_seed_r = float(np.mean(pred_corrs)) if pred_corrs else None

    return {
        "per_seed": per_seed,
        "ens_mae": ens_mae,
        "mean_individual_mae": mean_individual_mae,
        "ens_benefit": float(ens_benefit),
        "cv_mae": cv_mae,
        "std_mae": float(np.std(seed_maes)),
        "mean_inter_seed_r": mean_inter_seed_r,
    }


# ═══════════════════════════════════════════════════════════════════
# 6. PLOTTING
# ═══════════════════════════════════════════════════════════════════

def plot_scatter(y_true, y_pred, groups, title, path):
    """Predicted vs actual scatter with identity line, CI band, and MCID."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    groups = np.array(groups)

    fig, ax = plt.subplots(1, 1, figsize=(7, 6))

    # Identity line
    mn, mx = min(y_true.min(), y_pred.min()) - 2, max(y_true.max(), y_pred.max()) + 2
    ax.plot([mn, mx], [mn, mx], "k--", alpha=0.5, linewidth=1, label="Identity")

    # MCID band
    ax.fill_between([mn, mx], [mn - MCID_WORSEN, mx - MCID_WORSEN],
                    [mn + MCID_WORSEN, mx + MCID_WORSEN],
                    alpha=0.08, color="green", label=f"±MCID ({MCID_WORSEN})")

    # Scatter by group
    pd_mask = groups == "PD"
    hc_mask = groups == "HC"
    ax.scatter(y_true[pd_mask], y_pred[pd_mask], c="#d62728", s=50, alpha=0.8,
              edgecolors="k", linewidths=0.5, label=f"PD (n={pd_mask.sum()})", zorder=5)
    ax.scatter(y_true[hc_mask], y_pred[hc_mask], c="#1f77b4", s=50, alpha=0.8,
              edgecolors="k", linewidths=0.5, label=f"HC (n={hc_mask.sum()})", zorder=5)

    # Regression line
    slope, intercept = np.polyfit(y_true, y_pred, 1)
    x_line = np.linspace(mn, mx, 100)
    ax.plot(x_line, slope * x_line + intercept, "r-", alpha=0.6, linewidth=1.5,
            label=f"Regression (slope={slope:.2f})")

    # Regression CI band (bootstrap)
    rng = np.random.RandomState(42)
    n = len(y_true)
    boot_lines = []
    for _ in range(200):
        bi = rng.choice(n, size=n, replace=True)
        s, i_ = np.polyfit(y_true[bi], y_pred[bi], 1)
        boot_lines.append(s * x_line + i_)
    boot_lines = np.array(boot_lines)
    ax.fill_between(x_line, np.percentile(boot_lines, 2.5, axis=0),
                    np.percentile(boot_lines, 97.5, axis=0),
                    alpha=0.15, color="red")

    mae = mean_absolute_error(y_true, y_pred)
    r, p = sp_stats.pearsonr(y_true, y_pred)
    ax.text(0.05, 0.95, f"MAE = {mae:.2f}\nr = {r:.3f} (p = {p:.2e})",
            transform=ax.transAxes, fontsize=11, verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.8))

    ax.set_xlabel("Actual UPDRS-III", fontsize=12)
    ax.set_ylabel("Predicted UPDRS-III", fontsize=12)
    ax.set_title(title, fontsize=13)
    ax.legend(loc="lower right", fontsize=9)
    ax.set_xlim(mn, mx)
    ax.set_ylim(mn, mx)
    ax.set_aspect("equal")
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_bland_altman(y_true, y_pred, groups, title, path):
    """Bland-Altman plot with bias line and limits of agreement."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    groups = np.array(groups)

    means = (y_true + y_pred) / 2
    diffs = y_pred - y_true
    bias = diffs.mean()
    sd = diffs.std()
    loa_lo = bias - 1.96 * sd
    loa_hi = bias + 1.96 * sd

    fig, ax = plt.subplots(1, 1, figsize=(7, 5))

    pd_mask = groups == "PD"
    hc_mask = groups == "HC"
    ax.scatter(means[pd_mask], diffs[pd_mask], c="#d62728", s=50, alpha=0.8,
              edgecolors="k", linewidths=0.5, label="PD", zorder=5)
    ax.scatter(means[hc_mask], diffs[hc_mask], c="#1f77b4", s=50, alpha=0.8,
              edgecolors="k", linewidths=0.5, label="HC", zorder=5)

    ax.axhline(bias, color="k", linestyle="-", linewidth=1,
              label=f"Bias = {bias:.2f}")
    ax.axhline(loa_lo, color="gray", linestyle="--", linewidth=1,
              label=f"LoA = [{loa_lo:.1f}, {loa_hi:.1f}]")
    ax.axhline(loa_hi, color="gray", linestyle="--", linewidth=1)

    # MCID bands
    ax.axhline(MCID_WORSEN, color="green", linestyle=":", alpha=0.5,
              label=f"±MCID ({MCID_WORSEN})")
    ax.axhline(-MCID_WORSEN, color="green", linestyle=":", alpha=0.5)

    ax.axhline(0, color="k", alpha=0.2, linewidth=0.5)

    ax.set_xlabel("Mean of Actual and Predicted UPDRS-III", fontsize=12)
    ax.set_ylabel("Predicted − Actual (Residual)", fontsize=12)
    ax.set_title(title, fontsize=13)
    ax.legend(loc="upper left", fontsize=9)
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ═══════════════════════════════════════════════════════════════════
# 7. LATEX OUTPUT
# ═══════════════════════════════════════════════════════════════════

def generate_latex(all_stats):
    """Generate LaTeX table for paper."""
    lines = []
    lines.append(r"\begin{table}[ht]")
    lines.append(r"\centering")
    lines.append(r"\caption{Model performance with 95\% BCa bootstrap confidence intervals (N=10,000 resamples).}")
    lines.append(r"\label{tab:stats}")
    lines.append(r"\begin{tabular}{lcccccc}")
    lines.append(r"\toprule")
    lines.append(r"Method & N & MAE [95\% CI] & $r$ [95\% CI] & PD MAE & HC MAE & Within MCID \\")
    lines.append(r"\midrule")

    model_labels = {
        "stack": "Stack (artifact-backed)",
        "lgb": "LightGBM (150 feat)",
        "xgb": "XGBoost (150 feat)",
        "cat": "CatBoost (150 feat)",
        "ceiling": "XGBoost + H\\&Y (ceiling)",
    }

    for mname in ["stack", "lgb", "xgb", "cat", "ceiling"]:
        if mname not in all_stats:
            continue
        s = all_stats[mname]
        ci = s["bootstrap_cis"]
        clin = s["clinical"]

        mae_str = f"{ci['mae'][0]:.2f} [{ci['mae'][1]:.2f}, {ci['mae'][2]:.2f}]"
        r_str = f"{ci['r'][0]:.3f} [{ci['r'][1]:.3f}, {ci['r'][2]:.3f}]"
        pd_mae = f"{ci['mae_pd'][0]:.2f}" if "mae_pd" in ci else "—"
        hc_mae = f"{ci['mae_hc'][0]:.2f}" if "mae_hc" in ci else "—"
        mcid_str = f"{clin['within_mcid_4.63']*100:.0f}\\%"

        label = model_labels.get(mname, mname)
        lines.append(f"{label} & 36 & {mae_str} & {r_str} & {pd_mae} & {hc_mae} & {mcid_str} \\\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    print("=" * 70)
    print("STATISTICAL RIGOR REPORT")
    print("=" * 70)

    # 1. Build features
    print("\n[1/7] Feature extraction...")
    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    df = build_features(subjects, dev_sids, test_sids)
    n_feats = len([c for c in df.columns if c not in ("sid", "updrs3")])
    print(f"  {n_feats} features, {len(df)} subjects")

    # 2. Train models and get per-subject predictions
    print("\n[2/7] Training models (LGB/XGB/CAT + ceiling)...")
    model_results, meta = train_all_models(df, dev_sids, test_sids, subjects)
    model_results["stack"] = load_stack_predictions(meta)
    print(
        "  stack artifact: "
        f"MAE={model_results['stack']['ens_mae']:.3f} "
        f"r={model_results['stack']['ens_r']:.3f}"
    )

    y_true = np.array(meta["test_true"])
    groups = meta["test_groups"]

    # 3. Bootstrap CIs
    print("\n[3/7] Bootstrap confidence intervals (BCa, N=10000)...")
    all_stats = {}
    for mname, mres in model_results.items():
        y_pred = np.array(mres["ens_pred"])
        cis = compute_bootstrap_cis(y_true, y_pred, groups)
        all_stats[mname] = {"bootstrap_cis": cis}
        mae_ci = cis["mae"]
        r_ci = cis["r"]
        print(f"  {mname}: MAE={mae_ci[0]:.2f} [{mae_ci[1]:.2f}, {mae_ci[2]:.2f}]  "
              f"r={r_ci[0]:.3f} [{r_ci[1]:.3f}, {r_ci[2]:.3f}]")

    # 4. Permutation tests
    print("\n[4/7] Paired permutation tests...")
    comparisons = [
        ("stack", "lgb"),
        ("stack", "xgb"),
        ("stack", "cat"),
        ("stack", "ceiling"),
        ("lgb", "xgb"),
        ("lgb", "cat"),
        ("lgb", "ceiling"),
    ]
    perm_results = {}
    for a, b in comparisons:
        if a in model_results and b in model_results:
            pred_a = np.array(model_results[a]["ens_pred"])
            pred_b = np.array(model_results[b]["ens_pred"])
            res = paired_permutation_test(y_true, pred_a, pred_b)
            perm_results[f"{a}_vs_{b}"] = res
            direction = "better" if res["obs_diff_mae"] > 0 else "worse"
            print(f"  {a} vs {b}: Δ={res['obs_diff_mae']:.3f} ({direction}), "
                  f"p={res['p_value']:.4f}, d={res['cohens_d']:.3f}")

    # 5. Clinical significance
    print("\n[5/7] Clinical significance analysis...")
    for mname, mres in model_results.items():
        y_pred = np.array(mres["ens_pred"])
        clin = clinical_analysis(y_true, y_pred, groups)
        all_stats[mname]["clinical"] = clin
        ba = clin["bland_altman"]
        rd = clin["residual_diagnostics"]
        print(f"  {mname}: within MCID={clin['within_mcid_4.63']*100:.0f}%, "
              f"bias={ba['bias']:.2f}, LoA=[{ba['loa_lower']:.1f}, {ba['loa_upper']:.1f}]")
        print(f"    residual skew={rd['skewness']:.2f}, kurtosis={rd['kurtosis']:.2f}, "
              f"heteroscedasticity p={rd['heteroscedasticity_p']:.3f}")

    # 6. Seed stability
    print("\n[6/7] Seed stability analysis...")
    for mname, mres in model_results.items():
        stab = seed_stability(y_true, mres["seed_preds"], mres["seed_maes"], mres["seed_rs"])
        all_stats[mname]["seed_stability"] = stab
        inter_seed = "n/a" if stab["mean_inter_seed_r"] is None else f"{stab['mean_inter_seed_r']:.3f}"
        print(f"  {mname}: ens_mae={stab['ens_mae']:.3f}, "
              f"mean_indiv={stab['mean_individual_mae']:.3f}, "
              f"benefit={stab['ens_benefit']:.3f}, "
              f"cv_mae={stab['cv_mae']:.3f}, "
              f"inter_seed_r={inter_seed}")

    # 7. Plots
    print("\n[7/7] Generating figures...")
    best_name = min(model_results, key=lambda name: model_results[name]["ens_mae"])
    best_pred = np.array(model_results[best_name]["ens_pred"])
    plot_scatter(y_true, best_pred, groups,
                f"{best_name.upper()} : Predicted vs Actual UPDRS-III",
                os.path.join(FIGURES_DIR, "stats_scatter.png"))
    plot_bland_altman(y_true, best_pred, groups,
                     f"{best_name.upper()} : Bland-Altman Plot",
                     os.path.join(FIGURES_DIR, "stats_bland_altman.png"))

    # Also plot ceiling
    ceil_pred = np.array(model_results["ceiling"]["ens_pred"])
    plot_scatter(y_true, ceil_pred, groups,
                "Ceiling (XGBoost + H&Y): Predicted vs Actual UPDRS-III",
                os.path.join(FIGURES_DIR, "stats_scatter_ceiling.png"))

    # LaTeX table
    print("\n" + "=" * 70)
    print("LATEX TABLE")
    print("=" * 70)
    latex = generate_latex(all_stats)
    print(latex)

    # Save everything
    report = {
        "meta": meta,
        "model_predictions": {k: {"ens_pred": v["ens_pred"], "ens_mae": v["ens_mae"],
                                   "ens_r": v["ens_r"], "seed_maes": v["seed_maes"],
                                   "seed_rs": v["seed_rs"]}
                              for k, v in model_results.items()},
        "stats": all_stats,
        "permutation_tests": perm_results,
        "latex_table": latex,
        "config": {
            "n_bootstrap": N_BOOTSTRAP,
            "n_features": 150,
            "seeds": SEEDS,
            "mcid_improve": MCID_IMPROVE,
            "mcid_worsen": MCID_WORSEN,
        },
    }

    save_json_artifact("stats_report.json", report)
    print("\nFull report saved: results/stats_report.json")

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed/60:.1f} min")

    # Print summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Model':<25} {'MAE [95% CI]':<30} {'r [95% CI]':<30} {'MCID%':<8}")
    print("-" * 95)
    for mname in ["stack", "lgb", "xgb", "cat", "ceiling"]:
        if mname not in all_stats:
            continue
        s = all_stats[mname]
        ci = s["bootstrap_cis"]
        clin = s["clinical"]
        label = {"stack": "Stack (artifact)", "lgb": "LightGBM", "xgb": "XGBoost", "cat": "CatBoost",
                 "ceiling": "Ceiling (XGB+H&Y)"}[mname]
        mae_str = f"{ci['mae'][0]:.2f} [{ci['mae'][1]:.2f}, {ci['mae'][2]:.2f}]"
        r_str = f"{ci['r'][0]:.3f} [{ci['r'][1]:.3f}, {ci['r'][2]:.3f}]"
        mcid_str = f"{clin['within_mcid_4.63']*100:.0f}%"
        print(f"{label:<25} {mae_str:<30} {r_str:<30} {mcid_str:<8}")


if __name__ == "__main__":
    main()
