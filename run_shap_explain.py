"""
SHAP Feature Importance Analysis for WearGait-PD UPDRS-III Regression
=====================================================================
Generates clinically interpretable SHAP-based feature importance:
1. Top 20 features (bar + beeswarm plots)
2. Category-level aggregated importance
3. Body-location sensor map
4. SHAP dependence plots for top features
5. Clinical interpretation report
"""
import os, sys, json, time, warnings, subprocess
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from concurrent.futures import ProcessPoolExecutor

# Install shap if not available
try:
    import shap
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "shap", "-q"])
    import shap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

from run_ablation_v2 import (extract_recording, agg_task_preserving, compute_dist_feats,
                              load_covariates, load_walkway, distill_walkway,
                              agg_mean, TASKS, N_CORES, SEEDS)

FIGURES_DIR = "/root/pd-imu/figures"
os.makedirs(FIGURES_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════
# FEATURE CATEGORY MAPPING
# ═══════════════════════════════════════════════════════════════════

def categorize_feature(name):
    """Map feature name to clinical category."""
    if name.startswith("cv_"):
        return "Clinical Covariates"
    if name.startswith("dst_"):
        return "Walkway Distillation"
    if name.startswith(("d_", "r_")):
        # Task contrast/ratio
        return "Task Contrasts"
    if name.startswith("dv_"):
        return "Cross-Task Variability"
    if name.startswith("ins_"):
        return "Insole Pressure"
    if name.startswith("fc_"):
        return "Foot Contact"
    if name.startswith("k_"):
        return "Kinematics"
    if name.startswith("bal_"):
        return "Balance/Postural"
    if name.startswith("turn_") or name.startswith("trn_"):
        return "Turns"
    if name.startswith("sts_"):
        return "Transitions"
    if name.startswith("ix_"):
        return "Feature Interactions"
    # Sensor-based features
    for suffix in ["_cadence", "_step_t", "_stride_t", "_step_reg", "_stride_reg"]:
        if suffix in name:
            return "Gait Rhythm"
    for suffix in ["_loco", "_trem", "_high", "_dom", "_se"]:
        if suffix in name:
            return "Frequency Content"
    for suffix in ["_jerk", "_zcr"]:
        if suffix in name:
            return "Movement Quality"
    for suffix in ["_rms", "_range", "_iqr", "_std"]:
        if suffix in name:
            return "Movement Amplitude"
    for suffix in ["_skew", "_kurt"]:
        if suffix in name:
            return "Signal Shape"
    return "Other"


def get_sensor_location(name):
    """Map feature name to body sensor location."""
    sensor_map = {
        "LowerBack": "Lower Back",
        "R_Wrist": "Right Wrist", "L_Wrist": "Left Wrist",
        "R_MidLatThigh": "Right Thigh", "L_MidLatThigh": "Left Thigh",
        "R_LatShank": "Right Shank", "L_LatShank": "Left Shank",
        "R_DorsalFoot": "Right Foot", "L_DorsalFoot": "Left Foot",
        "R_Ankle": "Right Ankle", "L_Ankle": "Left Ankle",
        "Xiphoid": "Chest", "Forehead": "Head",
    }
    for prefix, loc in sensor_map.items():
        if name.startswith(f"{prefix}_"):
            return loc
    # Task contrasts and other compound features
    for prefix, loc in sensor_map.items():
        if prefix in name:
            return loc
    if name.startswith("cv_"):
        return "Clinical"
    if name.startswith("dst_"):
        return "Walkway (distilled)"
    if name.startswith("fc_"):
        return "Feet (bilateral)"
    if name.startswith("bal_"):
        return "Lower Back"
    if name.startswith("ins_"):
        return "Feet (insole)"
    return "Other"


CLINICAL_DESCRIPTIONS = {
    "cv_yrs": "Years since PD diagnosis — strongest single severity correlate",
    "cv_age": "Age — age-related motor decline compounds PD effects",
    "cv_sex": "Sex — male PD patients tend to show different gait patterns",
    "cv_wt": "Body weight — affects movement dynamics and force generation",
    "cv_dbs": "DBS status — indicates advanced disease, modulates gait",
    "cv_ht": "Height — affects stride length and gait kinematics",
}


CATEGORY_COLORS = {
    "Clinical Covariates": "#e74c3c",
    "Movement Amplitude": "#3498db",
    "Gait Rhythm": "#2ecc71",
    "Frequency Content": "#9b59b6",
    "Movement Quality": "#f39c12",
    "Walkway Distillation": "#1abc9c",
    "Task Contrasts": "#e67e22",
    "Cross-Task Variability": "#34495e",
    "Foot Contact": "#16a085",
    "Kinematics": "#c0392b",
    "Balance/Postural": "#2980b9",
    "Turns": "#8e44ad",
    "Signal Shape": "#7f8c8d",
    "Insole Pressure": "#d35400",
    "Feature Interactions": "#95a5a6",
    "Other": "#bdc3c7",
    "Transitions": "#27ae60",
}


# ═══════════════════════════════════════════════════════════════════
# MODEL TRAINING + SHAP
# ═══════════════════════════════════════════════════════════════════

def train_lgb(Xtr, ytr, Xva, yva, seed):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                          reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                          objective="mae", verbosity=-1)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
          callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
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
    """Build full feature set (same as stats report)."""
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
# PLOTTING
# ═══════════════════════════════════════════════════════════════════

def plot_shap_bar(shap_importance, feat_names, categories, path):
    """Top 20 features horizontal bar chart colored by category."""
    top_n = min(20, len(shap_importance))
    idx = np.argsort(shap_importance)[::-1][:top_n]

    fig, ax = plt.subplots(figsize=(10, 8))
    y_pos = np.arange(top_n)[::-1]

    colors = [CATEGORY_COLORS.get(categories[i], "#bdc3c7") for i in idx]
    bars = ax.barh(y_pos, shap_importance[idx], color=colors, edgecolor="k", linewidth=0.3)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([feat_names[i] for i in idx], fontsize=9)
    ax.set_xlabel("Mean |SHAP value|", fontsize=12)
    ax.set_title("Top 20 Features by SHAP Importance", fontsize=14, fontweight="bold")

    # Legend
    seen = set()
    patches = []
    for i in idx:
        cat = categories[i]
        if cat not in seen:
            seen.add(cat)
            patches.append(mpatches.Patch(color=CATEGORY_COLORS.get(cat, "#bdc3c7"), label=cat))
    ax.legend(handles=patches, loc="lower right", fontsize=8, ncol=2)
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_shap_categories(cat_importance, path):
    """Category-level aggregated importance."""
    cats = sorted(cat_importance.keys(), key=lambda c: cat_importance[c], reverse=True)
    vals = [cat_importance[c] for c in cats]
    colors = [CATEGORY_COLORS.get(c, "#bdc3c7") for c in cats]
    total = sum(vals)
    pcts = [v / total * 100 for v in vals]

    fig, ax = plt.subplots(figsize=(10, 6))
    y_pos = np.arange(len(cats))[::-1]
    bars = ax.barh(y_pos, pcts, color=colors, edgecolor="k", linewidth=0.3)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(cats, fontsize=10)
    ax.set_xlabel("% of Total SHAP Importance", fontsize=12)
    ax.set_title("Feature Category Importance (SHAP)", fontsize=14, fontweight="bold")

    for i, (bar, pct) in enumerate(zip(bars, pcts[::-1])):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", fontsize=9)

    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_body_map(sensor_importance, path):
    """Schematic body diagram showing sensor contribution."""
    fig, ax = plt.subplots(figsize=(6, 10))
    ax.set_xlim(-3, 3)
    ax.set_ylim(0, 18)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Sensor Location Importance (SHAP)", fontsize=14, fontweight="bold", pad=20)

    # Body outline (simplified)
    body_x = [0, -0.5, -0.5, -1.5, -1.5, -0.5, -0.5, -0.7, -0.7, -0.3, -0.3,
              0.3, 0.3, 0.7, 0.7, 0.5, 0.5, 1.5, 1.5, 0.5, 0.5, 0]
    body_y = [17, 16, 14, 14, 13, 13, 10, 10, 5, 5, 1,
              1, 5, 5, 10, 10, 13, 13, 14, 14, 16, 17]
    ax.plot(body_x, body_y, "k-", linewidth=1.5, alpha=0.3)
    ax.fill(body_x, body_y, alpha=0.05, color="gray")

    # Head circle
    head = plt.Circle((0, 17.5), 0.5, fill=False, linewidth=1.5, alpha=0.3)
    ax.add_patch(head)

    # Sensor positions (x, y)
    positions = {
        "Head": (0, 17.5),
        "Chest": (0, 14.5),
        "Lower Back": (0, 12),
        "Right Wrist": (-1.8, 11),
        "Left Wrist": (1.8, 11),
        "Right Thigh": (-0.5, 9),
        "Left Thigh": (0.5, 9),
        "Right Shank": (-0.5, 7),
        "Left Shank": (0.5, 7),
        "Right Ankle": (-0.5, 5.5),
        "Left Ankle": (0.5, 5.5),
        "Right Foot": (-0.5, 4),
        "Left Foot": (0.5, 4),
    }

    max_imp = max(sensor_importance.values()) if sensor_importance else 1
    for loc, (x, y) in positions.items():
        imp = sensor_importance.get(loc, 0)
        size = max(80, 500 * (imp / max_imp))
        alpha = max(0.3, imp / max_imp)
        ax.scatter(x, y, s=size, c="#e74c3c", alpha=alpha, edgecolors="k", linewidths=0.5, zorder=5)
        pct = imp / sum(sensor_importance.values()) * 100 if sum(sensor_importance.values()) > 0 else 0
        label_x = x + (1.2 if x >= 0 else -1.2)
        ha = "left" if x >= 0 else "right"
        if loc in ["Lower Back", "Chest", "Head"]:
            label_x = x + 1.2
            ha = "left"
        ax.annotate(f"{loc}\n{pct:.1f}%", (x, y), (label_x, y),
                   fontsize=8, ha=ha, va="center",
                   arrowprops=dict(arrowstyle="-", color="gray", alpha=0.5))

    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_beeswarm(shap_values_matrix, X_test, feat_names, path):
    """SHAP beeswarm plot for top 20 features."""
    top_n = 20
    mean_abs = np.mean(np.abs(shap_values_matrix), axis=0)
    idx = np.argsort(mean_abs)[::-1][:top_n]

    fig, ax = plt.subplots(figsize=(10, 8))
    shap.summary_plot(shap_values_matrix[:, idx],
                     X_test[:, idx],
                     feature_names=[feat_names[i] for i in idx],
                     show=False, max_display=top_n)
    plt.title("SHAP Beeswarm: Feature Value vs. SHAP Impact", fontsize=13, fontweight="bold")
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
    print("SHAP FEATURE IMPORTANCE ANALYSIS")
    print("=" * 70)

    # Build features
    print("\n[1/5] Feature extraction...")
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
    n_feats = len(sel_names)
    print(f"  {n_feats} features selected")

    # Train models and compute SHAP
    print("\n[2/5] Training models + computing SHAP values...")
    all_shap = []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd_sel))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = train_lgb(Xd_sel[idx[nv:]], yd[idx[nv:]],
                      Xd_sel[idx[:nv]], yd[idx[:nv]], seed)

        explainer = shap.TreeExplainer(m)
        sv = explainer.shap_values(Xt_sel)
        all_shap.append(sv)
        print(f"  seed={seed}: SHAP computed for {len(Xt_sel)} test subjects")

    # Average SHAP across seeds
    shap_avg = np.mean(all_shap, axis=0)  # (36, 150)
    mean_abs_shap = np.mean(np.abs(shap_avg), axis=0)  # (150,)

    # Categorize features
    categories = [categorize_feature(n) for n in sel_names]
    sensors = [get_sensor_location(n) for n in sel_names]

    # Category-level importance
    cat_importance = {}
    for i, cat in enumerate(categories):
        cat_importance[cat] = cat_importance.get(cat, 0) + mean_abs_shap[i]

    # Sensor-level importance
    sensor_importance = {}
    for i, sen in enumerate(sensors):
        sensor_importance[sen] = sensor_importance.get(sen, 0) + mean_abs_shap[i]

    # Plots
    print("\n[3/5] Generating figures...")
    plot_shap_bar(mean_abs_shap, sel_names, categories,
                 os.path.join(FIGURES_DIR, "shap_top20.png"))
    plot_shap_categories(cat_importance,
                        os.path.join(FIGURES_DIR, "shap_categories.png"))
    plot_body_map(sensor_importance,
                 os.path.join(FIGURES_DIR, "shap_bodymap.png"))
    plot_beeswarm(shap_avg, Xt_sel, sel_names,
                 os.path.join(FIGURES_DIR, "shap_beeswarm.png"))

    # Top 5 dependence plots
    top5_idx = np.argsort(mean_abs_shap)[::-1][:5]
    for rank, fi in enumerate(top5_idx):
        fig, ax = plt.subplots(figsize=(7, 5))
        shap.dependence_plot(fi, shap_avg, Xt_sel,
                            feature_names=sel_names, show=False, ax=ax)
        ax.set_title(f"SHAP Dependence: {sel_names[fi]}", fontsize=12, fontweight="bold")
        plt.tight_layout()
        dep_path = os.path.join(FIGURES_DIR, f"shap_dep_{rank+1}_{sel_names[fi][:30]}.png")
        plt.savefig(dep_path, dpi=200, bbox_inches="tight")
        plt.close()
        print(f"  Saved: {dep_path}")

    # Clinical report
    print("\n[4/5] Generating clinical interpretation report...")
    total_shap = mean_abs_shap.sum()
    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append("FEATURE IMPORTANCE ANALYSIS (SHAP)")
    report_lines.append("=" * 70)
    report_lines.append(f"\nModel: LightGBM, 150 features, 5-seed ensemble")
    report_lines.append(f"SHAP: TreeExplainer, averaged over {len(SEEDS)} seeds")
    report_lines.append(f"Test subjects: {len(Xt_sel)}")
    report_lines.append(f"\nNote: SHAP values explain the MODEL's predictions,")
    report_lines.append(f"not causal relationships. Feature importance reflects")
    report_lines.append(f"predictive utility, not clinical causation.")

    report_lines.append(f"\n{'='*70}")
    report_lines.append(f"TOP 20 PREDICTORS")
    report_lines.append(f"{'='*70}")
    top20 = np.argsort(mean_abs_shap)[::-1][:20]
    for rank, i in enumerate(top20):
        name = sel_names[i]
        shap_val = mean_abs_shap[i]
        pct = shap_val / total_shap * 100
        cat = categories[i]
        loc = sensors[i]
        desc = CLINICAL_DESCRIPTIONS.get(name, "")
        report_lines.append(f"\n{rank+1:2d}. {name}")
        report_lines.append(f"    SHAP = {shap_val:.4f} ({pct:.1f}% of total)")
        report_lines.append(f"    Category: {cat} | Location: {loc}")
        if desc:
            report_lines.append(f"    Clinical: {desc}")

    report_lines.append(f"\n{'='*70}")
    report_lines.append(f"CATEGORY BREAKDOWN")
    report_lines.append(f"{'='*70}")
    for cat in sorted(cat_importance, key=lambda c: cat_importance[c], reverse=True):
        pct = cat_importance[cat] / total_shap * 100
        report_lines.append(f"  {cat:<30s} {pct:5.1f}%")

    report_lines.append(f"\n{'='*70}")
    report_lines.append(f"SENSOR LOCATION BREAKDOWN")
    report_lines.append(f"{'='*70}")
    for loc in sorted(sensor_importance, key=lambda s: sensor_importance[s], reverse=True):
        pct = sensor_importance[loc] / total_shap * 100
        report_lines.append(f"  {loc:<25s} {pct:5.1f}%")

    report_text = "\n".join(report_lines)
    print(report_text)

    # Save results
    print(f"\n[5/5] Saving results...")
    np.savez(os.path.join("/root/pd-imu", "shap_values.npz"),
             shap_values=shap_avg, feature_names=sel_names,
             test_features=Xt_sel)

    importance_df = pd.DataFrame({
        "feature": sel_names,
        "mean_abs_shap": mean_abs_shap,
        "category": categories,
        "sensor_location": sensors,
        "pct_importance": mean_abs_shap / total_shap * 100,
    }).sort_values("mean_abs_shap", ascending=False)
    importance_df.to_csv(os.path.join("/root/pd-imu", "feature_importance_shap.csv"), index=False)

    with open(os.path.join("/root/pd-imu", "feature_importance_report.txt"), "w") as f:
        f.write(report_text)

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
