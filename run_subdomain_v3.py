#!/usr/bin/env python3
"""run_subdomain_v3.py — UPDRS-III subdomain prediction from IMU-only features.

Predicts observable vs unobservable UPDRS-III subdomains using v3 feature cache.
Key result: observable_gait composite (items 7-14) with 10-split validation.

IMU-ONLY: no obs_subscore, no hy. Pure sensor prediction.
"""
import sys, os, json, time
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, save_json_artifact
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split, DATA_DIR
from updrs_columns import find_updrs_value
from run_ablation_v3 import (
    v2_cols, gen_split, prep_arrays, train_lgb, train_xgb,
    run_eval, run_stack, feature_select, FEATURE_CACHE, N_CORES, SEEDS,
)

ensure_dir(RESULTS_DIR)

# =====================================================================
# UPDRS-III ITEM AND SUBDOMAIN DEFINITIONS
# =====================================================================

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

SUBITEMS = {
    1: None, 2: None,
    3: ["a", "b", "c", "d", "e"],
    4: ["a", "b"], 5: ["a", "b"], 6: ["a", "b"],
    7: ["a", "b"], 8: ["a", "b"],
    9: None, 10: None, 11: None, 12: None, 13: None, 14: None,
    15: ["a", "b"], 16: ["a", "b"],
    17: ["a", "b", "c", "d", "e"],
    18: None,
}

ITEM_MAX_SCORE = {
    1: 4, 2: 4, 3: 20, 4: 8, 5: 8, 6: 8,
    7: 8, 8: 8, 9: 4, 10: 4, 11: 4, 12: 4,
    13: 4, 14: 4, 15: 8, 16: 8, 17: 20, 18: 4,
}

# Which items are observable from gait IMU
OBSERVABLE_ITEMS = {7, 8, 9, 10, 11, 12, 13, 14}
UNOBSERVABLE_ITEMS = {1, 2, 3, 4, 5, 6, 15, 16, 17, 18}

COMPOSITES = {
    "observable_gait": [7, 8, 9, 10, 11, 12, 13, 14],
    "unobservable": [1, 2, 3, 4, 5, 6, 15, 16, 17, 18],
    "axial": [1, 2, 9, 10, 11, 12, 13, 14],
    "lower_limb": [7, 8, 10, 11],
    "upper_limb": [4, 5, 6],
    "tremor": [15, 16, 17, 18],
    "rigidity_total": [3],
}


# =====================================================================
# ITEM-LEVEL SCORE PARSING (verified: 181/185 subjects have observable)
# =====================================================================

def parse_item_scores():
    """Parse per-item UPDRS-III scores from clinical CSVs.

    Returns dict: sid -> {item_number: float_score}
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
                    val = find_updrs_value(row, df.columns, item_num)
                    if val is not None:
                        scores[item_num] = val
                    elif group == "HC":
                        scores[item_num] = 0.0
                else:
                    vals = []
                    for s in sub:
                        v = find_updrs_value(row, df.columns, item_num, s)
                        if v is not None:
                            vals.append(v)
                    if len(vals) == len(sub):
                        scores[item_num] = float(sum(vals))
                    elif len(vals) == 0 and group == "HC":
                        scores[item_num] = 0.0

            if scores:
                item_scores[sid] = scores

    return item_scores


def subdomain_target(item_scores, items_list):
    """Sum constituent items. Returns float or None if any missing."""
    total = 0.0
    for item in items_list:
        if item not in item_scores:
            return None
        total += item_scores[item]
    return total


# =====================================================================
# ADAPTIVE K SELECTION
# =====================================================================

def adaptive_k(target_range):
    """Adapt feature selection K to subdomain target range."""
    if target_range > 30:
        return 150
    elif target_range >= 12:
        return 100
    elif target_range >= 4:
        return 75
    else:
        return 50


# =====================================================================
# SINGLE SUBDOMAIN EVALUATION (primary split)
# =====================================================================

def eval_subdomain(df, dev_sids, test_sids, item_scores, name, items, feat_cols):
    """Train and evaluate one subdomain model on a single split.

    Returns results dict or None if insufficient data.
    """
    max_score = sum(ITEM_MAX_SCORE[i] for i in items)
    k = adaptive_k(max_score)

    # Build targets
    sid_targets = {}
    for sid in dev_sids + test_sids:
        if sid not in item_scores:
            continue
        score = subdomain_target(item_scores[sid], items)
        if score is not None:
            sid_targets[sid] = score

    dev_valid = [s for s in dev_sids if s in sid_targets]
    test_valid = [s for s in test_sids if s in sid_targets]

    if len(dev_valid) < 20 or len(test_valid) < 5:
        print(f"  SKIP {name}: dev={len(dev_valid)} test={len(test_valid)}")
        return None

    # Prepare arrays
    dev_mask = df["sid"].isin(dev_valid)
    test_mask = df["sid"].isin(test_valid)

    Xd = df.loc[dev_mask, feat_cols].values.astype(np.float32)
    yd = np.array([sid_targets[s] for s in df.loc[dev_mask, "sid"]], dtype=np.float32)
    Xt = df.loc[test_mask, feat_cols].values.astype(np.float32)
    yt = np.array([sid_targets[s] for s in df.loc[test_mask, "sid"]], dtype=np.float32)

    # Feature selection
    k_use = min(k, Xd.shape[1])
    si, sel_names = feature_select(Xd, yd, feat_cols, k_use)
    Xd_sel = Xd[:, si]
    Xt_sel = Xt[:, si]

    # 5-seed LGB ensemble
    all_preds = []
    for seed in SEEDS:
        p, _ = train_lgb(Xd_sel, yd, Xt_sel, seed)
        p = np.clip(p, 0, max_score)
        all_preds.append(p)

    ens_pred = np.mean(all_preds, axis=0)
    ens_mae = float(mean_absolute_error(yt, ens_pred))
    if np.std(yt) > 1e-8 and np.std(ens_pred) > 1e-8:
        ens_r, _ = sp_stats.pearsonr(yt, ens_pred)
    else:
        ens_r = 0.0
    within_1pt = float(np.mean(np.abs(yt - ens_pred) <= 1.0) * 100)

    # Bootstrap CIs
    mae_lo, mae_hi = _bootstrap_ci(yt, ens_pred, mean_absolute_error)
    r_lo, r_hi = _bootstrap_r_ci(yt, ens_pred)

    # Observability label
    if all(i in OBSERVABLE_ITEMS for i in items):
        obs = "OBSERVABLE"
    elif all(i in UNOBSERVABLE_ITEMS for i in items):
        obs = "UNOBSERVABLE"
    else:
        obs = "MIXED"

    # PD-only MAE
    pd_sids_in_test = [s for s in test_valid if "NLS" in s or "WPD" in s]
    pd_mask_test = df.loc[test_mask, "sid"].isin(pd_sids_in_test).values
    pd_mae = float(mean_absolute_error(yt[pd_mask_test], ens_pred[pd_mask_test])) if pd_mask_test.sum() > 0 else None

    print(f"  {name:<25s} 0-{max_score:<4d} MAE={ens_mae:.2f} [{mae_lo:.2f},{mae_hi:.2f}] "
          f"r={ens_r:.3f} [{r_lo:.3f},{r_hi:.3f}] <=1pt={within_1pt:.0f}% [{obs}]")

    return {
        "subdomain": name,
        "items": items,
        "item_names": [ITEM_NAMES[i] for i in items],
        "target_range": f"0-{max_score}",
        "observability": obs,
        "n_dev": len(dev_valid),
        "n_test": len(test_valid),
        "k": k_use,
        "ens_mae": round(ens_mae, 3),
        "ens_r": round(float(ens_r), 3),
        "within_1pt_pct": round(within_1pt, 1),
        "mae_95ci": [round(mae_lo, 3), round(mae_hi, 3)],
        "r_95ci": [round(r_lo, 3), round(r_hi, 3)],
        "pd_mae": round(pd_mae, 3) if pd_mae is not None else None,
        "top10_features": sel_names[:10],
        "test_true": yt.tolist(),
        "test_pred": ens_pred.tolist(),
        "test_sids": test_valid,
    }


# =====================================================================
# 10-SPLIT VALIDATION FOR A SUBDOMAIN
# =====================================================================

def validate_subdomain_10split(df, subjects, item_scores, name, items, feat_cols):
    """10-split validation for a subdomain. Returns dict with per-split MAEs."""
    max_score = sum(ITEM_MAX_SCORE[i] for i in items)
    k = adaptive_k(max_score)

    print(f"\n  --- 10-split validation: {name} (K={k}) ---")

    # Build targets for all subjects
    sid_targets = {}
    for sid in df["sid"]:
        if sid not in item_scores:
            continue
        score = subdomain_target(item_scores[sid], items)
        if score is not None:
            sid_targets[sid] = score

    lgb_maes = []
    stk_maes = []

    for seed in range(1, 11):
        dev_s, test_s = gen_split(subjects, seed)

        # Filter to subjects with valid subdomain targets
        dev_valid = [s for s in dev_s if s in sid_targets]
        test_valid = [s for s in test_s if s in sid_targets]

        if len(dev_valid) < 20 or len(test_valid) < 5:
            print(f"    [{seed}/10] SKIP: dev={len(dev_valid)} test={len(test_valid)}")
            continue

        dev_mask = df["sid"].isin(dev_valid)
        test_mask = df["sid"].isin(test_valid)

        Xd = df.loc[dev_mask, feat_cols].values.astype(np.float32)
        yd = np.array([sid_targets[s] for s in df.loc[dev_mask, "sid"]], dtype=np.float32)
        Xt = df.loc[test_mask, feat_cols].values.astype(np.float32)
        yt = np.array([sid_targets[s] for s in df.loc[test_mask, "sid"]], dtype=np.float32)

        k_use = min(k, Xd.shape[1])
        si, _ = feature_select(Xd, yd, feat_cols, k_use)
        Xd_sel = Xd[:, si]
        Xt_sel = Xt[:, si]

        # LGB ensemble
        lgb_preds = []
        for s in SEEDS:
            p, _ = train_lgb(Xd_sel, yd, Xt_sel, s)
            lgb_preds.append(np.clip(p, 0, max_score))
        lgb_ens = np.mean(lgb_preds, axis=0)
        lgb_mae = float(mean_absolute_error(yt, lgb_ens))
        lgb_maes.append(lgb_mae)

        # Stack (LGB+XGB → Ridge)
        from sklearn.model_selection import KFold
        from sklearn.linear_model import Ridge
        stk_preds_all = []
        for s in SEEDS:
            kf = KFold(n_splits=5, shuffle=True, random_state=s)
            oof_lgb = np.zeros(len(yd))
            oof_xgb = np.zeros(len(yd))
            test_lgb_folds = []
            test_xgb_folds = []
            for tr_idx, va_idx in kf.split(Xd_sel):
                p_lgb, _ = train_lgb(Xd_sel[tr_idx], yd[tr_idx], Xd_sel[va_idx], s)
                p_xgb, _ = train_xgb(Xd_sel[tr_idx], yd[tr_idx], Xd_sel[va_idx], s)
                oof_lgb[va_idx] = p_lgb
                oof_xgb[va_idx] = p_xgb
                tp_lgb, _ = train_lgb(Xd_sel[tr_idx], yd[tr_idx], Xt_sel, s)
                tp_xgb, _ = train_xgb(Xd_sel[tr_idx], yd[tr_idx], Xt_sel, s)
                test_lgb_folds.append(tp_lgb)
                test_xgb_folds.append(tp_xgb)
            meta_X = np.column_stack([oof_lgb, oof_xgb])
            meta_test = np.column_stack([np.mean(test_lgb_folds, axis=0),
                                         np.mean(test_xgb_folds, axis=0)])
            ridge = Ridge(alpha=1.0)
            ridge.fit(meta_X, yd)
            stk_preds_all.append(np.clip(ridge.predict(meta_test), 0, max_score))

        stk_ens = np.mean(stk_preds_all, axis=0)
        stk_mae = float(mean_absolute_error(yt, stk_ens))
        stk_maes.append(stk_mae)

        print(f"    [{seed}/10] lgb={lgb_mae:.2f} stk={stk_mae:.2f}")

    if not lgb_maes:
        print(f"    NO VALID SPLITS for {name}")
        return None

    # Wilcoxon test: stack vs lgb
    if len(stk_maes) >= 6:
        _, wilcoxon_p = sp_stats.wilcoxon(lgb_maes, stk_maes)
    else:
        wilcoxon_p = None

    print(f"    LGB 10-split: {np.mean(lgb_maes):.2f} +/- {np.std(lgb_maes):.2f}")
    print(f"    STK 10-split: {np.mean(stk_maes):.2f} +/- {np.std(stk_maes):.2f}")
    if wilcoxon_p is not None:
        print(f"    Wilcoxon stk vs lgb: p={wilcoxon_p:.4f}")

    return {
        "subdomain": name,
        "n_splits": len(lgb_maes),
        "lgb": {"mean": round(np.mean(lgb_maes), 3), "std": round(np.std(lgb_maes), 3),
                "values": [round(v, 3) for v in lgb_maes]},
        "stk": {"mean": round(np.mean(stk_maes), 3), "std": round(np.std(stk_maes), 3),
                "values": [round(v, 3) for v in stk_maes]},
        "wilcoxon_p": round(wilcoxon_p, 4) if wilcoxon_p is not None else None,
    }


# =====================================================================
# PERMUTATION TEST: OBSERVABLE vs UNOBSERVABLE
# =====================================================================

def permutation_test_r(yt_obs, yp_obs, yt_unobs, yp_unobs, n_perm=10000):
    """Test if r_observable > r_unobservable significantly."""
    r_obs, _ = sp_stats.pearsonr(yt_obs, yp_obs)
    r_unobs, _ = sp_stats.pearsonr(yt_unobs, yp_unobs)
    observed_diff = r_obs - r_unobs

    all_true = np.concatenate([yt_obs, yt_unobs])
    all_pred = np.concatenate([yp_obs, yp_unobs])
    n_obs = len(yt_obs)

    rng = np.random.RandomState(42)
    count_ge = 0
    for _ in range(n_perm):
        perm = rng.permutation(len(all_true))
        yt_o, yp_o = all_true[perm[:n_obs]], all_pred[perm[:n_obs]]
        yt_u, yp_u = all_true[perm[n_obs:]], all_pred[perm[n_obs:]]
        r_o = sp_stats.pearsonr(yt_o, yp_o)[0] if np.std(yt_o) > 1e-8 and np.std(yp_o) > 1e-8 else 0.0
        r_u = sp_stats.pearsonr(yt_u, yp_u)[0] if np.std(yt_u) > 1e-8 and np.std(yp_u) > 1e-8 else 0.0
        if (r_o - r_u) >= observed_diff:
            count_ge += 1

    return float(observed_diff), (count_ge + 1) / (n_perm + 1)


# =====================================================================
# BOOTSTRAP CIs
# =====================================================================

def _bootstrap_ci(y_true, y_pred, metric_fn, n_boot=2000, alpha=0.05):
    rng = np.random.RandomState(42)
    n = len(y_true)
    vals = np.array([metric_fn(y_true[rng.randint(0, n, n)], y_pred[rng.randint(0, n, n)])
                     for _ in range(n_boot)])
    return float(np.percentile(vals, 100 * alpha / 2)), float(np.percentile(vals, 100 * (1 - alpha / 2)))


def _bootstrap_r_ci(y_true, y_pred, n_boot=2000, alpha=0.05):
    rng = np.random.RandomState(42)
    n = len(y_true)
    vals = []
    for _ in range(n_boot):
        idx = rng.randint(0, n, n)
        yt, yp = y_true[idx], y_pred[idx]
        if np.std(yt) < 1e-8 or np.std(yp) < 1e-8:
            vals.append(0.0)
        else:
            vals.append(sp_stats.pearsonr(yt, yp)[0])
    vals = np.array(vals)
    return float(np.percentile(vals, 100 * alpha / 2)), float(np.percentile(vals, 100 * (1 - alpha / 2)))


# =====================================================================
# PD-ONLY LOOCV FOR OBSERVABLE SUBDOMAIN
# =====================================================================

def pdonly_loocv_subdomain(df, subjects, item_scores, name, items, feat_cols):
    """PD-only LOOCV for a subdomain. Fair comparison with Hssayeni."""
    max_score = sum(ITEM_MAX_SCORE[i] for i in items)
    k = adaptive_k(max_score)

    print(f"\n  --- PD-only LOOCV: {name} (K={k}) ---")

    # Filter to PD subjects with valid targets
    sid_targets = {}
    for sid in df["sid"]:
        if sid not in item_scores:
            continue
        if subjects.get(sid, {}).get("group") != "PD":
            continue
        score = subdomain_target(item_scores[sid], items)
        if score is not None:
            sid_targets[sid] = score

    pd_sids = list(sid_targets.keys())
    n_pd = len(pd_sids)
    print(f"    PD subjects with valid {name}: {n_pd}")

    pd_df = df[df["sid"].isin(pd_sids)].reset_index(drop=True)
    loocv_preds, loocv_true = [], []

    for i, sid in enumerate(pd_df["sid"]):
        train_mask = pd_df["sid"] != sid
        Xtr = pd_df.loc[train_mask, feat_cols].values.astype(np.float32)
        ytr = np.array([sid_targets[s] for s in pd_df.loc[train_mask, "sid"]], dtype=np.float32)
        Xte = pd_df.loc[~train_mask, feat_cols].values.astype(np.float32)
        yte = sid_targets[sid]

        k_use = min(k, Xtr.shape[1])
        si, _ = feature_select(Xtr, ytr, feat_cols, k_use)

        preds_i = []
        for seed in SEEDS:
            p, _ = train_lgb(Xtr[:, si], ytr, Xte[:, si], seed)
            preds_i.append(float(np.clip(p[0], 0, max_score)))
        loocv_preds.append(np.mean(preds_i))
        loocv_true.append(yte)

        if (i + 1) % 20 == 0:
            print(f"    LOOCV {i+1}/{n_pd}")

    mae = mean_absolute_error(loocv_true, loocv_preds)
    r, _ = sp_stats.pearsonr(loocv_true, loocv_preds)
    print(f"    {name} PD-only LOOCV: MAE={mae:.2f} r={r:.3f} (N={n_pd})")

    return {
        "subdomain": name,
        "n_pd": n_pd,
        "mae": round(float(mae), 3),
        "r": round(float(r), 3),
        "k": k,
    }


# =====================================================================
# MAIN
# =====================================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("UPDRS-III SUBDOMAIN PREDICTION (v3 features, IMU-only)")
    print("=" * 70)

    # ── Load data ──
    print("\n[1/6] Loading data...")
    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    item_scores = parse_item_scores()

    # Load v3 feature cache
    if not os.path.exists(FEATURE_CACHE):
        raise FileNotFoundError(f"Feature cache missing: {FEATURE_CACHE}")
    df = pd.read_csv(FEATURE_CACHE)
    print(f"  Feature cache: {df.shape[0]} subjects x {df.shape[1]} columns")

    # IMU-only features (no obs_subscore, no hy)
    feat_cols = v2_cols(df)
    print(f"  IMU-only features: {len(feat_cols)}")

    # Verify item coverage
    obs_items = [7, 8, 9, 10, 11, 12, 13, 14]
    n_obs_valid = sum(1 for sid in df["sid"]
                      if sid in item_scores
                      and subdomain_target(item_scores[sid], obs_items) is not None)
    print(f"  Subjects with complete observable scores: {n_obs_valid}")
    print(f"  Item scores parsed: {len(item_scores)} subjects")

    results = {}

    # ── Individual items (primary split) ──
    print(f"\n[2/6] Individual item models (18 items, primary split)...")
    individual_results = []
    for item_num in range(1, 19):
        name = [k for k, v in {
            "speech": [1], "facial": [2], "rigidity": [3],
            "finger_tap": [4], "hand_mvmt": [5], "pronation": [6],
            "toe_tap": [7], "leg_agility": [8], "arising": [9],
            "gait": [10], "freezing": [11], "postural_stability": [12],
            "posture": [13], "body_bradykinesia": [14],
            "postural_tremor": [15], "kinetic_tremor": [16],
            "rest_tremor_amp": [17], "constancy_tremor": [18],
        }.items() if v == [item_num]][0]
        r = eval_subdomain(df, dev_sids, test_sids, item_scores, name, [item_num], feat_cols)
        if r is not None:
            individual_results.append(r)
    results["individual"] = individual_results

    # ── Composite subdomains (primary split) ──
    print(f"\n[3/6] Composite subdomain models (primary split)...")
    composite_results = []
    for name, items in COMPOSITES.items():
        r = eval_subdomain(df, dev_sids, test_sids, item_scores, name, items, feat_cols)
        if r is not None:
            composite_results.append(r)
    results["composites"] = composite_results

    # ── Observable vs Unobservable comparison ──
    print(f"\n[4/6] Observable vs Unobservable permutation test...")
    obs_r = next((r for r in composite_results if r["subdomain"] == "observable_gait"), None)
    unobs_r = next((r for r in composite_results if r["subdomain"] == "unobservable"), None)

    obs_vs_unobs = {"comparison_available": False}
    if obs_r is not None and unobs_r is not None:
        diff, pval = permutation_test_r(
            np.array(obs_r["test_true"]), np.array(obs_r["test_pred"]),
            np.array(unobs_r["test_true"]), np.array(unobs_r["test_pred"]),
        )
        obs_vs_unobs = {
            "comparison_available": True,
            "observable_mae": obs_r["ens_mae"],
            "observable_r": obs_r["ens_r"],
            "unobservable_mae": unobs_r["ens_mae"],
            "unobservable_r": unobs_r["ens_r"],
            "r_difference": round(diff, 4),
            "permutation_p": round(pval, 4),
        }
        print(f"  Observable r:   {obs_r['ens_r']:.3f}")
        print(f"  Unobservable r: {unobs_r['ens_r']:.3f}")
        print(f"  Difference:     {diff:.3f}")
        print(f"  Permutation p:  {pval:.4f} ({'SIGNIFICANT' if pval < 0.05 else 'n.s.'})")
    else:
        print("  WARNING: missing observable or unobservable composite")
    results["observable_vs_unobservable"] = obs_vs_unobs

    # ── 10-split validation for key composites ──
    print(f"\n[5/6] 10-split validation...")
    split_results = {}
    for name in ["observable_gait", "unobservable"]:
        items = COMPOSITES[name]
        r = validate_subdomain_10split(df, subjects, item_scores, name, items, feat_cols)
        if r is not None:
            split_results[name] = r
    results["split_validation"] = split_results

    # ── PD-only LOOCV for observable subdomain ──
    print(f"\n[6/6] PD-only LOOCV for observable subdomain...")
    loocv_results = {}
    for name in ["observable_gait", "unobservable"]:
        items = COMPOSITES[name]
        r = pdonly_loocv_subdomain(df, subjects, item_scores, name, items, feat_cols)
        if r is not None:
            loocv_results[name] = r
    results["pdonly_loocv"] = loocv_results

    # ── Summary ──
    elapsed = time.time() - t0
    results["runtime_s"] = round(elapsed, 1)

    print(f"\n{'='*70}")
    print("SUBDOMAIN RESULTS SUMMARY")
    print(f"{'='*70}")

    print(f"\n  OBSERVABLE COMPOSITES:")
    for r in composite_results:
        if r["observability"] == "OBSERVABLE":
            print(f"    {r['subdomain']:<25s} MAE={r['ens_mae']:.2f} r={r['ens_r']:.3f} range={r['target_range']}")

    print(f"\n  UNOBSERVABLE COMPOSITES:")
    for r in composite_results:
        if r["observability"] == "UNOBSERVABLE":
            print(f"    {r['subdomain']:<25s} MAE={r['ens_mae']:.2f} r={r['ens_r']:.3f} range={r['target_range']}")

    if "observable_gait" in split_results:
        sv = split_results["observable_gait"]
        print(f"\n  OBSERVABLE 10-SPLIT STK: {sv['stk']['mean']:.2f} +/- {sv['stk']['std']:.2f}")
    if "unobservable" in split_results:
        sv = split_results["unobservable"]
        print(f"  UNOBSERVABLE 10-SPLIT STK: {sv['stk']['mean']:.2f} +/- {sv['stk']['std']:.2f}")

    if "observable_gait" in loocv_results:
        lv = loocv_results["observable_gait"]
        print(f"\n  OBSERVABLE PD-ONLY LOOCV: MAE={lv['mae']:.2f} r={lv['r']:.3f} (N={lv['n_pd']})")

    print(f"\n  Total runtime: {elapsed/60:.1f}m")

    # Save
    save_json_artifact("subdomain_v3_results.json", results)
    print(f"  Saved: results/subdomain_v3_results.json")


if __name__ == "__main__":
    main()
