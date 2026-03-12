"""
UPDRS-III Subdomain Prediction from WearGait-PD IMU Features
=============================================================
Trains per-subdomain LightGBM models to predict individual UPDRS-III items
and composite subdomains. Key analysis: observable (gait-related) vs
unobservable (non-gait) subdomain predictability.

This is a SEPARATE publishable result from the total score regression.
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error, mean_squared_error
from concurrent.futures import ProcessPoolExecutor

warnings.filterwarnings("ignore")
from project_paths import FIGURES_DIR as FIGURES_DIR_PATH, REPO_ROOT, save_json_artifact
from updrs_columns import find_updrs_value

sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

from run_ablation_v2 import (extract_recording, agg_task_preserving, compute_dist_feats,
                              load_covariates, load_walkway, distill_walkway,
                              agg_mean, TASKS, N_CORES, SEEDS)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FIGURES_DIR = str(FIGURES_DIR_PATH)
os.makedirs(FIGURES_DIR, exist_ok=True)


# =====================================================================
# UPDRS-III SUBDOMAIN DEFINITIONS
# =====================================================================

# Individual items (item number -> clinical name)
ITEM_NAMES = {
    1: "Speech", 2: "Facial expression",
    3: "Rigidity (5 sites)", 4: "Finger tapping (R/L)",
    5: "Hand movements (R/L)", 6: "Pronation-supination (R/L)",
    7: "Toe tapping (R/L)", 8: "Leg agility (R/L)",
    9: "Arising from chair", 10: "Gait",
    11: "Freezing of gait", 12: "Postural stability",
    13: "Posture", 14: "Body bradykinesia",
    15: "Postural tremor (R/L)", 16: "Kinetic tremor (R/L)",
    17: "Rest tremor amplitude (5 sites)", 18: "Constancy of rest tremor",
}

# Individual item subdomains (each maps to a list of UPDRS item numbers)
SUBDOMAINS = {
    "speech": [1],
    "facial": [2],
    "rigidity": [3],
    "finger_tap": [4],
    "hand_mvmt": [5],
    "pronation": [6],
    "toe_tap": [7],
    "leg_agility": [8],
    "arising": [9],
    "gait": [10],
    "freezing": [11],
    "postural_stability": [12],
    "posture": [13],
    "body_bradykinesia": [14],
    "postural_tremor": [15],
    "kinetic_tremor": [16],
    "rest_tremor_amp": [17],
    "constancy_tremor": [18],
}

# Composite subdomains
COMPOSITES = {
    "axial": [1, 2, 9, 10, 11, 12, 13, 14],
    "lower_limb": [7, 8, 10, 11],
    "upper_limb": [4, 5, 6],
    "tremor": [15, 16, 17, 18],
    "rigidity_total": [3],
    "observable_gait": [7, 8, 9, 10, 11, 12, 13, 14],
    "unobservable": [1, 2, 3, 4, 5, 6, 15, 16, 17, 18],
}

# Which subdomains are observable from gait IMU
OBSERVABLE_ITEMS = {7, 8, 9, 10, 11, 12, 13, 14}
UNOBSERVABLE_ITEMS = {1, 2, 3, 4, 5, 6, 15, 16, 17, 18}

# Sub-items within each UPDRS item (item -> list of column suffixes in the CSV)
# Items with sub-items: 3 (a-e), 4 (a-b), 5 (a-b), 6 (a-b), 7 (a-b), 8 (a-b),
# 15 (a-b), 16 (a-b), 17 (a-e)
# Items WITHOUT sub-items: 1, 2, 9, 10, 11, 12, 13, 14, 18
SUBITEMS = {
    1: None, 2: None,
    3: ["a", "b", "c", "d", "e"],   # Neck, RUE, LUE, RLE, LLE
    4: ["a", "b"],                    # R, L
    5: ["a", "b"],                    # R, L
    6: ["a", "b"],                    # R, L
    7: ["a", "b"],                    # R, L
    8: ["a", "b"],                    # R, L
    9: None, 10: None, 11: None, 12: None, 13: None, 14: None,
    15: ["a", "b"],                   # R, L
    16: ["a", "b"],                   # R, L
    17: ["a", "b", "c", "d", "e"],   # RUE, LUE, RLE, LLE, Lip/Jaw
    18: None,
}

# Maximum possible score for each item
ITEM_MAX_SCORE = {
    1: 4, 2: 4,
    3: 20,   # 5 sub-items x 4
    4: 8,    # 2 sub-items x 4
    5: 8, 6: 8,
    7: 8, 8: 8,
    9: 4, 10: 4, 11: 4, 12: 4, 13: 4, 14: 4,
    15: 8, 16: 8,
    17: 20,  # 5 sub-items x 4
    18: 4,
}


# =====================================================================
# ITEM-LEVEL SCORE PARSING
# =====================================================================

def parse_item_scores():
    """Parse per-item UPDRS-III scores from clinical CSVs.

    Returns dict: sid -> {item_number: score, ...}
    Each item score is the sum of its sub-items (if any).
    """
    item_scores = {}

    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Clinical CSV not found: {path}")

        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue

            scores = {}
            for item_num in range(1, 19):
                sub = SUBITEMS[item_num]
                if sub is None:
                    val = _score_single_item(row, df.columns, item_num, group)
                    if val is not None:
                        scores[item_num] = val
                else:
                    total = _score_multi_item(row, df.columns, item_num, sub, group)
                    if total is not None:
                        scores[item_num] = total

            if scores:
                item_scores[sid] = scores

    return item_scores


def _score_single_item(row, columns, item_num, group):
    val = find_updrs_value(row, columns, item_num)
    if val is not None:
        return val
    if group == "HC":
        return 0.0
    return None


def _score_multi_item(row, columns, item_num, suffixes, group):
    values = []
    for suffix in suffixes:
        val = find_updrs_value(row, columns, item_num, suffix)
        if val is None:
            if values:
                return None
            continue
        values.append(val)
    if len(values) == len(suffixes):
        return float(sum(values))
    if len(values) == 0 and group == "HC":
        return 0.0
    return None


def compute_subdomain_scores(item_scores, items_list):
    """Compute a composite subdomain score by summing constituent items.

    Args:
        item_scores: dict {item_number: score} for one subject
        items_list: list of item numbers to sum

    Returns:
        float score if all items present, None if any missing
    """
    total = 0.0
    for item in items_list:
        if item not in item_scores:
            return None
        total += item_scores[item]
    return total


# =====================================================================
# FEATURE BUILDING (reused from run_shap_explain.py pattern)
# =====================================================================

def build_features(subjects, dev_sids, test_sids):
    """Build full feature set (same pipeline as run_shap_explain.py)."""
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

    print(f"  {len(jobs)} recordings, {N_CORES} cores...")
    t1 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        all_recs = [r for r in pool.map(extract_recording, jobs) if r is not None]
    print(f"  {len(all_recs)} done in {time.time()-t1:.0f}s")

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


# =====================================================================
# MODEL TRAINING
# =====================================================================

def train_lgb(Xtr, ytr, Xva, yva, seed):
    """Train LightGBM with same HPs as best deployable config."""
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                          reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                          objective="mae", verbosity=-1)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
          callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    return m


def feature_select(X, y, n_feats, feat_names):
    """XGBoost-based feature selection."""
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


def adaptive_n_feats(target_range):
    """Adapt number of selected features to subdomain score range."""
    if target_range > 20:
        return 150
    elif target_range >= 8:
        return 100
    else:
        return 50


# =====================================================================
# BOOTSTRAP + PERMUTATION TESTS
# =====================================================================

def bootstrap_ci(y_true, y_pred, metric_fn, n_boot=2000, alpha=0.05):
    """Bootstrap 95% CI for a metric."""
    rng = np.random.RandomState(42)
    n = len(y_true)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        vals[b] = metric_fn(y_true[idx], y_pred[idx])
    lo = np.percentile(vals, 100 * alpha / 2)
    hi = np.percentile(vals, 100 * (1 - alpha / 2))
    return float(lo), float(hi)


def bootstrap_r_ci(y_true, y_pred, n_boot=2000, alpha=0.05):
    """Bootstrap 95% CI for Pearson r."""
    rng = np.random.RandomState(42)
    n = len(y_true)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        yt_b, yp_b = y_true[idx], y_pred[idx]
        if np.std(yt_b) < 1e-8 or np.std(yp_b) < 1e-8:
            vals[b] = 0.0
        else:
            vals[b], _ = sp_stats.pearsonr(yt_b, yp_b)
    lo = np.percentile(vals, 100 * alpha / 2)
    hi = np.percentile(vals, 100 * (1 - alpha / 2))
    return float(lo), float(hi)


def permutation_test_r(y_true_obs, y_pred_obs, y_true_unobs, y_pred_unobs,
                       n_perm=10000):
    """Permutation test: is the difference in r between observable and
    unobservable subdomains significant?

    H0: r_observable == r_unobservable
    Returns observed difference and p-value.
    """
    r_obs, _ = sp_stats.pearsonr(y_true_obs, y_pred_obs)
    r_unobs, _ = sp_stats.pearsonr(y_true_unobs, y_pred_unobs)
    observed_diff = r_obs - r_unobs

    # Pool all predictions and true values, then randomly assign to groups
    all_true = np.concatenate([y_true_obs, y_true_unobs])
    all_pred = np.concatenate([y_pred_obs, y_pred_unobs])
    n_obs = len(y_true_obs)
    n_total = len(all_true)

    rng = np.random.RandomState(42)
    count_ge = 0
    for _ in range(n_perm):
        perm = rng.permutation(n_total)
        perm_obs_idx = perm[:n_obs]
        perm_unobs_idx = perm[n_obs:]

        yt_o, yp_o = all_true[perm_obs_idx], all_pred[perm_obs_idx]
        yt_u, yp_u = all_true[perm_unobs_idx], all_pred[perm_unobs_idx]

        if np.std(yt_o) < 1e-8 or np.std(yp_o) < 1e-8:
            r_o = 0.0
        else:
            r_o, _ = sp_stats.pearsonr(yt_o, yp_o)
        if np.std(yt_u) < 1e-8 or np.std(yp_u) < 1e-8:
            r_u = 0.0
        else:
            r_u, _ = sp_stats.pearsonr(yt_u, yp_u)

        if (r_o - r_u) >= observed_diff:
            count_ge += 1

    p_value = (count_ge + 1) / (n_perm + 1)
    return float(observed_diff), float(p_value)


# =====================================================================
# TRAIN AND EVALUATE ONE SUBDOMAIN
# =====================================================================

def train_subdomain(df_feats, dev_sids, test_sids, item_scores,
                    subdomain_name, items_list):
    """Train a per-subdomain model. Returns results dict or None if
    insufficient data."""

    # Compute subdomain target for each subject
    sid_targets = {}
    for sid in dev_sids + test_sids:
        if sid not in item_scores:
            continue
        score = compute_subdomain_scores(item_scores[sid], items_list)
        if score is not None:
            sid_targets[sid] = score

    dev_valid = [s for s in dev_sids if s in sid_targets]
    test_valid = [s for s in test_sids if s in sid_targets]

    if len(dev_valid) < 20:
        print(f"  SKIP {subdomain_name}: only {len(dev_valid)} dev subjects with scores")
        return None
    if len(test_valid) < 5:
        print(f"  SKIP {subdomain_name}: only {len(test_valid)} test subjects with scores")
        return None

    # Prepare feature matrices
    feat_cols = [c for c in df_feats.columns if c not in ("sid", "updrs3")]

    dev_mask = df_feats["sid"].isin(dev_valid)
    test_mask = df_feats["sid"].isin(test_valid)
    dev = df_feats[dev_mask].copy()
    test = df_feats[test_mask].copy()

    # Map subdomain target
    dev["target"] = dev["sid"].map(sid_targets).astype(np.float32)
    test["target"] = test["sid"].map(sid_targets).astype(np.float32)

    for c in feat_cols:
        dev[c] = dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        test[c] = test[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    Xd = dev[feat_cols].values.astype(np.float32)
    yd = dev["target"].values.astype(np.float32)
    Xt = test[feat_cols].values.astype(np.float32)
    yt = test["target"].values.astype(np.float32)

    # Compute target range for adaptive feature selection
    target_range = sum(ITEM_MAX_SCORE[i] for i in items_list)
    n_feats = adaptive_n_feats(target_range)

    # Feature selection
    if len(feat_cols) > n_feats:
        top_idx, sel_names = feature_select(Xd, yd, n_feats, feat_cols)
        Xd = Xd[:, top_idx]
        Xt = Xt[:, top_idx]
    else:
        sel_names = feat_cols

    # Train 5-seed ensemble
    all_preds = []
    seed_maes = []
    seed_rs = []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = train_lgb(Xd[idx[nv:]], yd[idx[nv:]],
                      Xd[idx[:nv]], yd[idx[:nv]], seed)
        p = m.predict(Xt)
        mae = mean_absolute_error(yt, p)
        if np.std(yt) > 1e-8 and np.std(p) > 1e-8:
            r, _ = sp_stats.pearsonr(yt, p)
        else:
            r = 0.0
        seed_maes.append(mae)
        seed_rs.append(r)
        all_preds.append(p)

    # Ensemble prediction (mean of 5 seeds)
    ens_pred = np.mean(all_preds, axis=0)
    ens_mae = mean_absolute_error(yt, ens_pred)
    ens_rmse = float(np.sqrt(mean_squared_error(yt, ens_pred)))
    if np.std(yt) > 1e-8 and np.std(ens_pred) > 1e-8:
        ens_r, _ = sp_stats.pearsonr(yt, ens_pred)
    else:
        ens_r = 0.0

    # % within 1 point (for individual items with small range)
    within_1pt = float(np.mean(np.abs(yt - ens_pred) <= 1.0) * 100)

    # Bootstrap CIs
    mae_ci = bootstrap_ci(yt, ens_pred, mean_absolute_error)
    r_ci = bootstrap_r_ci(yt, ens_pred)

    # Is this observable from gait IMU?
    is_observable = all(i in OBSERVABLE_ITEMS for i in items_list)
    is_unobservable = all(i in UNOBSERVABLE_ITEMS for i in items_list)
    if is_observable:
        obs_label = "OBSERVABLE"
    elif is_unobservable:
        obs_label = "UNOBSERVABLE"
    else:
        obs_label = "MIXED"

    result = {
        "subdomain": subdomain_name,
        "items": items_list,
        "item_names": [ITEM_NAMES[i] for i in items_list],
        "target_range": f"0-{target_range}",
        "observability": obs_label,
        "n_dev": len(dev_valid),
        "n_test": len(test_valid),
        "n_features_selected": len(sel_names),
        "ens_mae": round(float(ens_mae), 3),
        "ens_rmse": round(float(ens_rmse), 3),
        "ens_r": round(float(ens_r), 3),
        "within_1pt_pct": round(within_1pt, 1),
        "mae_95ci": [round(mae_ci[0], 3), round(mae_ci[1], 3)],
        "r_95ci": [round(r_ci[0], 3), round(r_ci[1], 3)],
        "seed_maes": [round(m, 3) for m in seed_maes],
        "seed_rs": [round(r, 3) for r in seed_rs],
        "test_true": yt.tolist(),
        "test_pred": ens_pred.tolist(),
        "test_sids": test_valid,
    }

    print(f"  {subdomain_name:<25s} range=0-{target_range:<4d} "
          f"MAE={ens_mae:.2f} [{mae_ci[0]:.2f},{mae_ci[1]:.2f}] "
          f"r={ens_r:.3f} [{r_ci[0]:.3f},{r_ci[1]:.3f}] "
          f"<=1pt={within_1pt:.0f}% "
          f"[{obs_label}]")

    return result


# =====================================================================
# VISUALIZATIONS
# =====================================================================

def plot_subdomain_predictability(results, path):
    """Bar chart: subdomains on x-axis, Pearson r on y-axis,
    colored by observable (green) vs unobservable (red)."""

    # Filter to composites + individual items, sorted by r descending
    items_to_plot = []
    for r in results:
        items_to_plot.append(r)

    # Sort by r descending
    items_to_plot.sort(key=lambda x: x["ens_r"], reverse=True)

    names = [r["subdomain"] for r in items_to_plot]
    rs = [r["ens_r"] for r in items_to_plot]
    r_lo = [r["r_95ci"][0] for r in items_to_plot]
    r_hi = [r["r_95ci"][1] for r in items_to_plot]
    errs_lo = [r_val - lo for r_val, lo in zip(rs, r_lo)]
    errs_hi = [hi - r_val for r_val, hi in zip(rs, r_hi)]

    colors = []
    for r in items_to_plot:
        if r["observability"] == "OBSERVABLE":
            colors.append("#27ae60")
        elif r["observability"] == "UNOBSERVABLE":
            colors.append("#c0392b")
        else:
            colors.append("#2980b9")

    fig, ax = plt.subplots(figsize=(14, 7))
    x = np.arange(len(names))
    bars = ax.bar(x, rs, color=colors, edgecolor="k", linewidth=0.5, alpha=0.85)
    ax.errorbar(x, rs, yerr=[errs_lo, errs_hi], fmt="none", ecolor="k",
                capsize=3, capthick=1, linewidth=1)

    # Horizontal line at r=0.5 (practical significance)
    ax.axhline(y=0.5, color="gray", linestyle="--", linewidth=1, alpha=0.7,
               label="r = 0.5 (practical significance)")

    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Pearson r (ensemble, 5 seeds)", fontsize=12)
    ax.set_title("UPDRS-III Subdomain Predictability from Gait IMU", fontsize=14,
                 fontweight="bold")
    ax.set_ylim(-0.1, 1.0)

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#27ae60", edgecolor="k", label="Observable from gait"),
        Patch(facecolor="#c0392b", edgecolor="k", label="Unobservable from gait"),
        Patch(facecolor="#2980b9", edgecolor="k", label="Mixed"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=10)

    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_observable_vs_unobservable_scatter(results, path):
    """Two scatter plots side-by-side: observable vs unobservable composite
    subscores, true vs predicted."""

    obs_result = None
    unobs_result = None
    for r in results:
        if r["subdomain"] == "observable_gait":
            obs_result = r
        elif r["subdomain"] == "unobservable":
            unobs_result = r

    if obs_result is None or unobs_result is None:
        print("  WARNING: Cannot plot scatter — missing observable/unobservable composites")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Observable
    yt_obs = np.array(obs_result["test_true"])
    yp_obs = np.array(obs_result["test_pred"])
    ax1.scatter(yt_obs, yp_obs, c="#27ae60", edgecolors="k", linewidths=0.5,
                s=60, alpha=0.8, zorder=5)
    lims_obs = [min(yt_obs.min(), yp_obs.min()) - 1,
                max(yt_obs.max(), yp_obs.max()) + 1]
    ax1.plot(lims_obs, lims_obs, "k--", alpha=0.5, linewidth=1)
    ax1.set_xlabel("True Score", fontsize=11)
    ax1.set_ylabel("Predicted Score", fontsize=11)
    ax1.set_title(f"Observable Gait Subscore\n"
                  f"MAE={obs_result['ens_mae']:.2f}, r={obs_result['ens_r']:.3f}",
                  fontsize=12, fontweight="bold")
    ax1.set_xlim(lims_obs)
    ax1.set_ylim(lims_obs)
    ax1.set_aspect("equal")

    # Unobservable
    yt_unobs = np.array(unobs_result["test_true"])
    yp_unobs = np.array(unobs_result["test_pred"])
    ax2.scatter(yt_unobs, yp_unobs, c="#c0392b", edgecolors="k", linewidths=0.5,
                s=60, alpha=0.8, zorder=5)
    lims_unobs = [min(yt_unobs.min(), yp_unobs.min()) - 1,
                  max(yt_unobs.max(), yp_unobs.max()) + 1]
    ax2.plot(lims_unobs, lims_unobs, "k--", alpha=0.5, linewidth=1)
    ax2.set_xlabel("True Score", fontsize=11)
    ax2.set_ylabel("Predicted Score", fontsize=11)
    ax2.set_title(f"Unobservable Subscore\n"
                  f"MAE={unobs_result['ens_mae']:.2f}, r={unobs_result['ens_r']:.3f}",
                  fontsize=12, fontweight="bold")
    ax2.set_xlim(lims_unobs)
    ax2.set_ylim(lims_unobs)
    ax2.set_aspect("equal")

    plt.suptitle("Observable vs Unobservable UPDRS-III Subdomains",
                 fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# =====================================================================
# MAIN
# =====================================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("UPDRS-III SUBDOMAIN PREDICTION")
    print("=" * 70)

    # ── Step 1: Parse clinical data and item-level scores ──
    print("\n[1/6] Parsing clinical data + item-level UPDRS scores...")
    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    item_scores = parse_item_scores()

    print(f"  {len(item_scores)} subjects with item-level scores")
    n_items_per_subj = [len(v) for v in item_scores.values()]
    print(f"  Items per subject: min={min(n_items_per_subj)}, "
          f"max={max(n_items_per_subj)}, "
          f"mean={np.mean(n_items_per_subj):.1f}")

    # Verify HC subjects have reasonable scores (should be ~0 for most items)
    hc_sids = [s for s in item_scores if s in subjects and subjects[s]["group"] == "HC"]
    pd_sids = [s for s in item_scores if s in subjects and subjects[s]["group"] == "PD"]
    if hc_sids:
        hc_totals = [sum(item_scores[s].values()) for s in hc_sids]
        print(f"  HC total UPDRS-III: mean={np.mean(hc_totals):.1f}, "
              f"max={max(hc_totals):.0f}, n={len(hc_sids)}")
    if pd_sids:
        pd_totals = [sum(item_scores[s].values()) for s in pd_sids]
        print(f"  PD total UPDRS-III: mean={np.mean(pd_totals):.1f}, "
              f"max={max(pd_totals):.0f}, n={len(pd_sids)}")

    # ── Step 2: Feature extraction ──
    print("\n[2/6] Feature extraction...")
    df = build_features(subjects, dev_sids, test_sids)
    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    print(f"  {len(feat_cols)} features, {len(df)} subjects")

    # ── Step 3: Train individual item models ──
    print(f"\n[3/6] Training individual item models (18 items x 5 seeds)...")
    print(f"  {'Subdomain':<25s} {'Range':<10s} {'MAE':>8s} {'95% CI':>18s} "
          f"{'r':>7s} {'95% CI':>18s} {'<=1pt':>6s} {'Obs':>12s}")
    print(f"  {'-'*110}")

    individual_results = []
    for name, items in SUBDOMAINS.items():
        r = train_subdomain(df, dev_sids, test_sids, item_scores, name, items)
        if r is not None:
            individual_results.append(r)

    # ── Step 4: Train composite subdomain models ──
    print(f"\n[4/6] Training composite subdomain models (7 composites x 5 seeds)...")
    print(f"  {'Subdomain':<25s} {'Range':<10s} {'MAE':>8s} {'95% CI':>18s} "
          f"{'r':>7s} {'95% CI':>18s} {'<=1pt':>6s} {'Obs':>12s}")
    print(f"  {'-'*110}")

    composite_results = []
    for name, items in COMPOSITES.items():
        r = train_subdomain(df, dev_sids, test_sids, item_scores, name, items)
        if r is not None:
            composite_results.append(r)

    all_results = individual_results + composite_results

    # ── Step 5: Statistical comparison: observable vs unobservable ──
    print(f"\n[5/6] Observable vs Unobservable comparison...")

    obs_result = None
    unobs_result = None
    for r in composite_results:
        if r["subdomain"] == "observable_gait":
            obs_result = r
        elif r["subdomain"] == "unobservable":
            unobs_result = r

    perm_diff = None
    perm_p = None
    if obs_result is not None and unobs_result is not None:
        yt_obs = np.array(obs_result["test_true"])
        yp_obs = np.array(obs_result["test_pred"])
        yt_unobs = np.array(unobs_result["test_true"])
        yp_unobs = np.array(unobs_result["test_pred"])

        perm_diff, perm_p = permutation_test_r(yt_obs, yp_obs, yt_unobs, yp_unobs)
        print(f"  Observable r:   {obs_result['ens_r']:.3f} "
              f"[{obs_result['r_95ci'][0]:.3f}, {obs_result['r_95ci'][1]:.3f}]")
        print(f"  Unobservable r: {unobs_result['ens_r']:.3f} "
              f"[{unobs_result['r_95ci'][0]:.3f}, {unobs_result['r_95ci'][1]:.3f}]")
        print(f"  Difference:     {perm_diff:.3f}")
        print(f"  Permutation p:  {perm_p:.4f} "
              f"({'SIGNIFICANT' if perm_p < 0.05 else 'not significant'} at alpha=0.05)")
    else:
        print("  WARNING: Could not compute permutation test — missing composite results")

    # Observable vs unobservable individual items comparison
    obs_item_rs = [r["ens_r"] for r in individual_results
                   if r["observability"] == "OBSERVABLE"]
    unobs_item_rs = [r["ens_r"] for r in individual_results
                     if r["observability"] == "UNOBSERVABLE"]
    if obs_item_rs and unobs_item_rs:
        print(f"\n  Individual items (mean r):")
        print(f"    Observable items:   {np.mean(obs_item_rs):.3f} "
              f"(n={len(obs_item_rs)}, range [{min(obs_item_rs):.3f}, {max(obs_item_rs):.3f}])")
        print(f"    Unobservable items: {np.mean(unobs_item_rs):.3f} "
              f"(n={len(unobs_item_rs)}, range [{min(unobs_item_rs):.3f}, {max(unobs_item_rs):.3f}])")

    # ── Step 6: Visualizations ──
    print(f"\n[6/6] Generating figures...")

    # Plot all results (individual + composite) on the predictability bar chart
    plot_subdomain_predictability(all_results,
                                  os.path.join(FIGURES_DIR, "subdomain_predictability.png"))
    plot_observable_vs_unobservable_scatter(composite_results,
                                            os.path.join(FIGURES_DIR, "subdomain_scatter.png"))

    # ── Summary table ──
    print(f"\n{'='*70}")
    print("SUBDOMAIN PREDICTION RESULTS")
    print(f"{'='*70}")

    # Group by observability
    print(f"\n{'Subdomain':<25s} {'Range':>6s} {'MAE':>7s} {'r':>7s} "
          f"{'<=1pt':>6s} {'Observability':>14s}")
    print(f"{'-'*70}")

    print("\nOBSERVABLE (from gait IMU):")
    for r in sorted(composite_results, key=lambda x: x["ens_r"], reverse=True):
        if r["observability"] == "OBSERVABLE":
            print(f"  {r['subdomain']:<23s} {r['target_range']:>6s} "
                  f"{r['ens_mae']:>7.2f} {r['ens_r']:>7.3f} "
                  f"{r['within_1pt_pct']:>5.0f}% {'OBSERVABLE':>14s}")

    print("\nUNOBSERVABLE (from gait IMU):")
    for r in sorted(composite_results, key=lambda x: x["ens_r"], reverse=True):
        if r["observability"] == "UNOBSERVABLE":
            print(f"  {r['subdomain']:<23s} {r['target_range']:>6s} "
                  f"{r['ens_mae']:>7.2f} {r['ens_r']:>7.3f} "
                  f"{r['within_1pt_pct']:>5.0f}% {'UNOBSERVABLE':>14s}")

    print("\nMIXED:")
    for r in sorted(composite_results, key=lambda x: x["ens_r"], reverse=True):
        if r["observability"] == "MIXED":
            print(f"  {r['subdomain']:<23s} {r['target_range']:>6s} "
                  f"{r['ens_mae']:>7.2f} {r['ens_r']:>7.3f} "
                  f"{r['within_1pt_pct']:>5.0f}% {'MIXED':>14s}")

    print(f"\nINDIVIDUAL ITEMS:")
    for r in sorted(individual_results, key=lambda x: x["ens_r"], reverse=True):
        print(f"  {r['subdomain']:<23s} {r['target_range']:>6s} "
              f"{r['ens_mae']:>7.2f} {r['ens_r']:>7.3f} "
              f"{r['within_1pt_pct']:>5.0f}% {r['observability']:>14s}")

    # ── Save results ──
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_dev": len(dev_sids),
        "n_test": len(test_sids),
        "n_subjects_with_items": len(item_scores),
        "seeds": SEEDS,
        "individual_results": [
            {k: v for k, v in r.items() if k not in ("test_true", "test_pred", "test_sids")}
            for r in individual_results
        ],
        "composite_results": [
            {k: v for k, v in r.items() if k not in ("test_true", "test_pred", "test_sids")}
            for r in composite_results
        ],
        "observable_vs_unobservable": {
            "comparison_available": obs_result is not None and unobs_result is not None,
            "observable_r": obs_result["ens_r"] if obs_result else None,
            "observable_mae": obs_result["ens_mae"] if obs_result else None,
            "unobservable_r": unobs_result["ens_r"] if unobs_result else None,
            "unobservable_mae": unobs_result["ens_mae"] if unobs_result else None,
            "r_difference": perm_diff,
            "permutation_p_value": perm_p,
        },
        # Full predictions for reproducibility
        "full_predictions": {
            r["subdomain"]: {
                "test_sids": r["test_sids"],
                "test_true": r["test_true"],
                "test_pred": r["test_pred"],
            }
            for r in all_results
        },
    }

    save_json_artifact("subdomain_results.json", output)
    print("\nResults saved: results/subdomain_results.json")

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
