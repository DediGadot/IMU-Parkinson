"""
Paper Supplements: Figure 4 regeneration + H&Y demographics + Supplementary tables
==================================================================================
Generates:
1. v3 total UPDRS-III test predictions (for Figure 4 scatter) — uses EXACT
   ablation pipeline functions for reproducibility
2. H&Y stage distribution from clinical data
3. Supplementary tables (per-seed 10-split, full feature list, residual analysis)
4. Updated Figure 4 as base64 PNG

Outputs: results/paper_supplements.json
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error

warnings.filterwarnings("ignore")
from project_paths import REPO_ROOT, save_json_artifact, load_json_artifact

sys.path.insert(0, str(REPO_ROOT))
from data_split import DATA_DIR

# Import the EXACT ablation pipeline
from run_ablation_v3 import (
    v2_cols, prep_arrays, feature_select, run_stack, train_lgb, train_xgb,
    SEEDS, N_CORES,
)
from run_proven_stack import feature_select

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
import base64

SPLIT_SEED = 20260309
K_SELECT = 150


# =====================================================================
# 1. CLINICAL DEMOGRAPHICS (H&Y, age, sex, etc.)
# =====================================================================

def extract_demographics():
    """Extract full demographics including H&Y distribution."""
    demos = {"PD": [], "HC": []}

    for filename, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Clinical CSV not found: {path}")

        df = pd.read_csv(path, header=1)
        u3cols = sorted([c for c in df.columns if c.startswith("MDSUPDRS_3-")])

        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue

            updrs3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
            if np.isnan(updrs3):
                continue

            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            sex_raw = str(row.get("Sex", row.get("Gender", ""))).strip().upper()
            sex = "M" if sex_raw.startswith("M") else ("F" if sex_raw.startswith("F") else "Unknown")
            hy = pd.to_numeric(
                row.get("Modified Hoehn & Yahr Score",
                         row.get("H&Y", row.get("Hoehn & Yahr", np.nan))),
                errors="coerce"
            )
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", np.nan)), errors="coerce")
            dbs_raw = str(row.get("DBS?", row.get("DBS", ""))).strip().upper()
            dbs = True if dbs_raw in ("YES", "Y", "1", "TRUE") else False
            height_in = pd.to_numeric(row.get("Height (in)", row.get("Height (cm)", np.nan)), errors="coerce")
            weight = pd.to_numeric(row.get("Weight (kg)", row.get("Weight", np.nan)), errors="coerce")
            # Convert inches to cm if needed
            height_cm = float(height_in * 2.54) if pd.notna(height_in) and height_in > 50 else (
                float(height_in) if pd.notna(height_in) else None)

            demos[group].append({
                "sid": sid, "age": float(age) if pd.notna(age) else None,
                "sex": sex, "hy": float(hy) if pd.notna(hy) else None,
                "years_dx": float(yrs) if pd.notna(yrs) else None,
                "dbs": dbs, "updrs3": float(updrs3),
                "height_cm": height_cm,
                "weight_kg": float(weight) if pd.notna(weight) else None,
            })

    # Compute summaries
    summary = {}
    for group in ["PD", "HC"]:
        data = demos[group]
        n = len(data)
        ages = [d["age"] for d in data if d["age"] is not None]
        updrs = [d["updrs3"] for d in data]
        males = sum(1 for d in data if d["sex"] == "M")
        females = sum(1 for d in data if d["sex"] == "F")
        heights = [d["height_cm"] for d in data if d["height_cm"] is not None]
        weights = [d["weight_kg"] for d in data if d["weight_kg"] is not None]

        summary[group] = {
            "n": n,
            "age_mean": round(float(np.mean(ages)), 1) if ages else None,
            "age_std": round(float(np.std(ages)), 1) if ages else None,
            "age_range": [round(min(ages), 1), round(max(ages), 1)] if ages else None,
            "sex_m_f": [males, females],
            "updrs3_mean": round(float(np.mean(updrs)), 1),
            "updrs3_std": round(float(np.std(updrs)), 1),
            "updrs3_median": round(float(np.median(updrs)), 1),
            "updrs3_range": [round(min(updrs), 1), round(max(updrs), 1)],
            "height_cm_mean": round(float(np.mean(heights)), 1) if heights else None,
            "height_cm_std": round(float(np.std(heights)), 1) if heights else None,
            "weight_kg_mean": round(float(np.mean(weights)), 1) if weights else None,
            "weight_kg_std": round(float(np.std(weights)), 1) if weights else None,
        }

    # H&Y specific for PD
    hy_vals = [d["hy"] for d in demos["PD"] if d["hy"] is not None]
    hy_distribution = {}
    for v in sorted(set(hy_vals)):
        hy_distribution[str(v)] = hy_vals.count(v)

    dbs_count = sum(1 for d in demos["PD"] if d["dbs"])
    yrs_dx = [d["years_dx"] for d in demos["PD"] if d["years_dx"] is not None]

    summary["PD"]["hy_distribution"] = hy_distribution
    summary["PD"]["hy_n_available"] = len(hy_vals)
    summary["PD"]["hy_mean"] = round(float(np.mean(hy_vals)), 2) if hy_vals else None
    summary["PD"]["hy_std"] = round(float(np.std(hy_vals)), 2) if hy_vals else None
    summary["PD"]["dbs_count"] = dbs_count
    summary["PD"]["years_dx_mean"] = round(float(np.mean(yrs_dx)), 1) if yrs_dx else None
    summary["PD"]["years_dx_std"] = round(float(np.std(yrs_dx)), 1) if yrs_dx else None
    summary["PD"]["years_dx_range"] = [round(min(yrs_dx), 1), round(max(yrs_dx), 1)] if yrs_dx else None

    print(f"\n=== Demographics ===")
    print(f"PD: N={summary['PD']['n']}, Age={summary['PD']['age_mean']}±{summary['PD']['age_std']}, "
          f"Sex(M/F)={summary['PD']['sex_m_f']}, UPDRS-III={summary['PD']['updrs3_mean']}±{summary['PD']['updrs3_std']}")
    print(f"HC: N={summary['HC']['n']}, Age={summary['HC']['age_mean']}±{summary['HC']['age_std']}, "
          f"Sex(M/F)={summary['HC']['sex_m_f']}, UPDRS-III={summary['HC']['updrs3_mean']}±{summary['HC']['updrs3_std']}")
    print(f"H&Y distribution: {hy_distribution} (N={len(hy_vals)})")
    print(f"DBS: {dbs_count}/{summary['PD']['n']} PD subjects")
    if yrs_dx:
        print(f"Years since dx: {np.mean(yrs_dx):.1f}±{np.std(yrs_dx):.1f}, range={min(yrs_dx):.0f}-{max(yrs_dx):.0f}")

    return summary, demos


# =====================================================================
# 2. V3 TOTAL UPDRS-III PREDICTIONS (using exact ablation pipeline)
# =====================================================================

def run_total_predictions():
    """Run the EXACT ablation pipeline for total UPDRS-III and capture test predictions."""
    # Load feature cache
    cache_path = os.path.join(str(REPO_ROOT), "results", "ablation_v3_features.csv")
    if not os.path.exists(cache_path):
        cache_path = os.path.join(str(REPO_ROOT), "ablation_v3_features.csv")
    if not os.path.exists(cache_path):
        raise FileNotFoundError(f"Feature cache not found")

    print(f"Loading features from {cache_path}")
    df = pd.read_csv(cache_path, index_col=0)
    df = df.reset_index().rename(columns={"index": "sid"})
    print(f"  {df.shape[0]} subjects x {df.shape[1]-1} features")

    # Load split — use data_split.json (seed=42) which is what all v3 experiments used
    split, _ = load_json_artifact("data_split.json")
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]
    print(f"Split: {len(dev_sids)} dev + {len(test_sids)} test (seed={split['seed']})")

    # Get v2 base columns (exact same as ablation)
    base_cols = v2_cols(df)
    print(f"V2 base features: {len(base_cols)}")

    # Prep arrays
    Xd, yd, Xt, yt = prep_arrays(df, dev_sids, test_sids, base_cols)
    print(f"Xd: {Xd.shape}, Xt: {Xt.shape}")

    # Feature selection (exact same function)
    k = K_SELECT
    sel_idx, sel_names = feature_select(Xd, yd, base_cols, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    print(f"Selected K={k} features. Top 5: {sel_names[:5]}")

    # Run stack with test prediction capture
    from sklearn.model_selection import KFold
    from sklearn.linear_model import Ridge
    import lightgbm as lgb
    from xgboost import XGBRegressor

    base_fns = [train_lgb, train_xgb]
    nb = len(base_fns)
    all_preds = []
    seed_results = []

    for seed in SEEDS:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof = [np.zeros(len(Xds)) for _ in range(nb)]
        tp = [np.zeros(len(Xts)) for _ in range(nb)]

        for tr_i, val_i in kf.split(Xds):
            rng = np.random.RandomState(seed + len(tr_i))
            shuf = tr_i.copy()
            rng.shuffle(shuf)
            nv = max(1, int(len(shuf) * 0.15))
            Xtr, ytr = Xds[shuf[nv:]], yd[shuf[nv:]]
            Xval, yval = Xds[shuf[:nv]], yd[shuf[:nv]]

            for bi, bfn in enumerate(base_fns):
                if bfn == train_lgb:
                    m = lgb.LGBMRegressor(
                        n_estimators=2000, learning_rate=0.03, max_depth=6,
                        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                        objective="mae", verbose=-1,
                    )
                    m.fit(Xtr, ytr, eval_set=[(Xval, yval)],
                          callbacks=[lgb.early_stopping(100, verbose=False)])
                elif bfn == train_xgb:
                    m = XGBRegressor(
                        n_estimators=2000, learning_rate=0.03, max_depth=6,
                        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                        early_stopping_rounds=100, objective="reg:absoluteerror",
                    )
                    m.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)

                oof[bi][val_i] = m.predict(Xds[val_i])
                tp[bi] += m.predict(Xts) / 5

        L0tr = np.column_stack(oof)
        L0te = np.column_stack(tp)
        meta = Ridge(alpha=1.0)
        meta.fit(L0tr, yd)
        p = np.clip(meta.predict(L0te), 0, 132)

        mae = mean_absolute_error(yt, p)
        r_val, _ = sp_stats.pearsonr(yt, p)
        all_preds.append(p)
        seed_results.append({"seed": seed, "mae": round(mae, 3), "r": round(r_val, 3)})
        print(f"  Seed {seed}: MAE={mae:.3f}, r={r_val:.3f}")

    # Ensemble
    ens_pred = np.mean(all_preds, axis=0)
    ens_mae = mean_absolute_error(yt, ens_pred)
    ens_r, _ = sp_stats.pearsonr(yt, ens_pred)

    # Groups
    dm = df["sid"].isin(dev_sids)
    tm = df["sid"].isin(test_sids)
    test_df = df.loc[tm]
    # Determine groups from UPDRS (HC = score ~0)
    # Actually need clinical data for group labels
    from data_split import parse_clinical
    subjects = parse_clinical()
    test_groups = []
    for sid in test_sids:
        if sid in subjects:
            test_groups.append(subjects[sid]["group"])
        else:
            test_groups.append("Unknown")
    test_groups = np.array(test_groups)

    pd_mask = test_groups == "PD"
    pd_mae = float(mean_absolute_error(yt[pd_mask], ens_pred[pd_mask])) if pd_mask.sum() > 0 else None
    pd_r = float(np.corrcoef(yt[pd_mask], ens_pred[pd_mask])[0, 1]) if pd_mask.sum() > 2 else None

    print(f"\n  Ensemble: MAE={ens_mae:.3f}, r={ens_r:.3f}")
    if pd_mae:
        print(f"  PD-only: MAE={pd_mae:.3f}, r={pd_r:.3f}")

    return {
        "test_sids": test_sids,
        "test_true": yt.tolist(),
        "test_pred": ens_pred.tolist(),
        "test_groups": test_groups.tolist(),
        "ens_mae": round(ens_mae, 3),
        "ens_r": round(ens_r, 3),
        "pd_mae": round(pd_mae, 3) if pd_mae else None,
        "pd_r": round(pd_r, 3) if pd_r else None,
        "seed_results": seed_results,
        "n_features": k,
        "top10_features": sel_names[:10],
    }


# =====================================================================
# 3. FIGURE GENERATION
# =====================================================================

def generate_figure4(total_preds):
    """Generate Figure 4: total UPDRS-III scatter with v3 pipeline."""
    y_true = np.array(total_preds["test_true"])
    y_pred = np.array(total_preds["test_pred"])
    groups = np.array(total_preds["test_groups"])
    mae = total_preds["ens_mae"]
    r = total_preds["ens_r"]

    fig, ax = plt.subplots(1, 1, figsize=(7, 6))

    lims = [0, max(y_true.max(), y_pred.max()) + 5]
    ax.plot(lims, lims, "k--", alpha=0.3, lw=1, zorder=1)

    pd_mask = groups == "PD"
    hc_mask = groups == "HC"
    ax.scatter(y_true[hc_mask], y_pred[hc_mask], c="#3498db", s=80, alpha=0.7,
               edgecolors="white", linewidth=0.5, label=f"HC (n={hc_mask.sum()})", zorder=3)
    ax.scatter(y_true[pd_mask], y_pred[pd_mask], c="#e74c3c", s=80, alpha=0.7,
               edgecolors="white", linewidth=0.5, label=f"PD (n={pd_mask.sum()})", zorder=3)

    ax.set_xlabel("Actual UPDRS-III Total", fontsize=13)
    ax.set_ylabel("Predicted UPDRS-III Total", fontsize=13)
    ax.set_title(f"Total UPDRS-III (IMU-Only, Held-Out Test)\nMAE = {mae:.2f}  |  r = {r:.3f}", fontsize=14)
    ax.legend(loc="upper left", fontsize=11)
    ax.set_xlim(lims)
    ax.set_ylim(lims)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# =====================================================================
# 4. SUPPLEMENTARY TABLES
# =====================================================================

def generate_supplementary_tables():
    """Generate supplementary data from existing results."""
    supp = {}

    # S1: Per-seed 10-split results
    try:
        followup, _ = load_json_artifact("followup_v3_results.json")
        if "exp1_stride_var_10split" in followup:
            bv2 = followup["exp1_stride_var_10split"].get("baseline_v2", {})
            supp["table_s1_10split_detail"] = {
                "description": "Per-seed MAE for 10-split validation (baseline features, K=150)",
                "data": bv2,
            }
    except FileNotFoundError:
        print("  followup_v3_results.json not found, skipping S1")

    # S2: Feature ablation detail from phase2
    try:
        phase2, _ = load_json_artifact("ablation_v3_phase2.json")
        results = phase2.get("results", [])
        supp["table_s2_feature_ablation"] = {
            "description": "Complete feature group ablation (all metrics)",
            "groups": []
        }
        for r in results:
            entry = {
                "group": r["group"],
                "n_cols": r["n_cols"],
                "lgb_mae": r["lgb"]["ens_mae"],
                "lgb_r": r["lgb"]["ens_r"],
                "lgb_pd_mae": r["lgb"].get("pd_mae"),
                "stack_mae": r["stack"]["ens_mae"],
                "stack_r": r["stack"]["ens_r"],
                "stack_pd_mae": r["stack"].get("pd_mae"),
                "top10": r["lgb"]["top10"],
            }
            supp["table_s2_feature_ablation"]["groups"].append(entry)
    except FileNotFoundError:
        print("  ablation_v3_phase2.json not found, skipping S2")

    # S3: Per-item detail from subdomain results
    try:
        subdomain, _ = load_json_artifact("subdomain_v3_results.json")
        items = subdomain.get("individual", [])
        supp["table_s3_item_detail"] = {
            "description": "Full per-item prediction detail (all 18 items)",
            "items": []
        }
        for item in items:
            supp["table_s3_item_detail"]["items"].append({
                "item": item.get("item_num"),
                "name": item.get("item_name"),
                "observability": item.get("observability"),
                "max_score": item.get("max_score"),
                "mae": item.get("ens_mae"),
                "r": item.get("ens_r"),
                "within_1pt_pct": item.get("within_1pt_pct"),
                "pd_mae": item.get("pd_mae"),
                "k": item.get("k"),
                "top5_features": item.get("top10_features", [])[:5],
            })
    except FileNotFoundError:
        print("  subdomain_v3_results.json not found, skipping S3")

    # S4: K-sweep from phase0
    try:
        phase0, _ = load_json_artifact("ablation_v3_phase0.json")
        k_results = phase0.get("k_results", [])
        supp["table_s4_k_sweep"] = {
            "description": "Feature selection K sweep (IMU-only, primary split)",
            "results": k_results,
        }
    except FileNotFoundError:
        print("  ablation_v3_phase0.json not found, skipping S4")

    return supp


# =====================================================================
# MAIN
# =====================================================================

def main():
    t0 = time.time()
    results = {}

    # --- Step 1: Demographics ---
    print("=" * 60)
    print("STEP 1: Extract demographics")
    print("=" * 60)
    summary, demos = extract_demographics()
    results["demographics"] = summary

    # --- Step 2: V3 total UPDRS-III predictions ---
    print("\n" + "=" * 60)
    print("STEP 2: V3 total UPDRS-III stack (for Figure 4)")
    print("=" * 60)
    total_preds = run_total_predictions()
    results["v3_total_predictions"] = total_preds

    # --- Step 3: Generate Figure 4 ---
    print("\n" + "=" * 60)
    print("STEP 3: Generate Figure 4")
    print("=" * 60)
    fig4_b64 = generate_figure4(total_preds)
    results["figure4_base64"] = fig4_b64
    print(f"  Figure 4: {len(fig4_b64) // 1024} KB base64")

    # --- Step 4: Supplementary tables ---
    print("\n" + "=" * 60)
    print("STEP 4: Supplementary tables")
    print("=" * 60)
    supp = generate_supplementary_tables()
    results["supplementary"] = supp

    # --- Save ---
    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("paper_supplements.json", results)
    print(f"\nDone in {results['runtime_s']:.0f}s. Saved to results/paper_supplements.json")


if __name__ == "__main__":
    main()
