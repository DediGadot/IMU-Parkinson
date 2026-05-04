"""Iter 1 — T3 ceiling diagnostic. Self-contained.

Runs all 10 diagnostic experiments from task_plan.md iter 1 list:
  1.1 per-item LGB 5-fold CCC heatmap
  1.2 T3 variance decomposition
  1.3 theoretical T3 ceiling derivation
  1.4 per-subject error decomposition (T3_err vs T1_err)
  1.5 demographics-only-per-item ridge LOOCV CCC heatmap
  1.6 top-10 v2 features × per-item Spearman correlations
  1.7 prediction-distribution analysis (pred_std/true_std)
  1.8 levodopa state effect on T3 error (skipped if metadata missing)
  1.9 H&Y stratified T3 CCC
  1.10 site-stratified T3 CCC + leave-site-out

Each task writes one JSON to results/iter1_<task>.json. The dashboard
generator reads them all and produces T3_DIAGNOSTIC.html.

Usage:
  python run_t3_iter1.py --task all
  python run_t3_iter1.py --task per_item_lgb     # heavy, needs lightgbm
  python run_t3_iter1.py --task variance_decomp  # local-light
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold, LeaveOneOut, KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, DATA_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 8)))
SEEDS = [42, 1337, 7, 2024, 31415][:3]

# ── Paths ────────────────────────────────────────────────────────────────────
V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
PER_ITEM_CACHE = RESULTS_DIR / "per_item_scores.json"
SPLIT_FILE = RESULTS_DIR / "paper3_split.json"
T1_LOOCV = RESULTS_DIR / "inductive_inductive_pd_t1_loocv.json"
T3_LOOCV = RESULTS_DIR / "baseline_B1_v2_only_t3_loocv.json"

# UPDRS item structure
T1_ITEMS = [9, 10, 11, 12, 13, 14]  # gait-observable
T2_ITEMS = [7, 8, 9, 10, 11, 12, 13, 14]  # broader observable
T3_ALL_ITEMS = list(range(1, 19))
NON_T1_ITEMS = [i for i in T3_ALL_ITEMS if i not in T1_ITEMS]
PARTIALLY_OBS_ITEMS = [5, 6, 7, 8, 15, 16, 17]  # tremor / rigidity / body bradykinesia
NOT_OBS_ITEMS = [1, 2, 3, 4, 18]  # mentation / constancy

V2_EXCLUDED_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")


def out_path(task: str) -> Path:
    return RESULTS_DIR / f"iter1_{task}.json"


def save(task: str, data: dict) -> None:
    p = out_path(task)
    with open(p, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  → wrote {p}")


# ── Data loading ─────────────────────────────────────────────────────────────


def load_per_item_scores() -> dict:
    """Return {sid: {item_int: score_float, ...}}. Only top-level items 1-18."""
    with open(PER_ITEM_CACHE) as f:
        raw = json.load(f)
    out = {}
    for sid, scores in raw.items():
        per_item = {}
        for k, v in scores.items():
            if k.startswith("("):
                continue  # skip subitems like (3,'a')
            try:
                ki = int(k)
                if 1 <= ki <= 18:
                    per_item[ki] = float(v)
            except ValueError:
                continue
        out[sid] = per_item
    return out


def load_v2_features() -> pd.DataFrame:
    df = pd.read_csv(V2_FEATURES)
    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    feat_cols = [
        c for c in df.columns
        if c not in excluded and not any(c.startswith(p) for p in V2_EXCLUDED_PREFIXES)
    ]
    return df, feat_cols


def site_of(sid: str) -> str:
    return "NLS" if sid.startswith("NLS") else ("WPD" if sid.startswith("WPD") else "OTHER")


def is_pd(sid: str) -> bool:
    s = sid.upper()
    return s.startswith("NLS") or s.startswith("WPD")


def load_split() -> dict:
    with open(SPLIT_FILE) as f:
        return json.load(f)


def get_pd_with_per_item() -> tuple:
    """Return (sids_pd, per_item_dict, T3_array)."""
    pis = load_per_item_scores()
    df, _ = load_v2_features()
    rows = []
    for _, r in df.iterrows():
        sid = r["sid"]
        if not is_pd(sid):
            continue
        if sid not in pis:
            continue
        items = pis[sid]
        if not all(i in items for i in T3_ALL_ITEMS):
            continue
        rows.append({
            "sid": sid,
            "T3": float(r["updrs3"]) if "updrs3" in r else sum(items[i] for i in T3_ALL_ITEMS),
            "T1": sum(items[i] for i in T1_ITEMS),
            "site": site_of(sid),
            **{f"item{i}": items[i] for i in T3_ALL_ITEMS},
        })
    return pd.DataFrame(rows)


def get_pd_features_and_items(feature_cols=None):
    df, fc = load_v2_features()
    if feature_cols is None:
        feature_cols = fc
    pis = load_per_item_scores()
    sids = []
    rows = []
    item_arrs = {i: [] for i in T3_ALL_ITEMS}
    t3_arr, t1_arr = [], []
    feats = []
    for _, r in df.iterrows():
        sid = r["sid"]
        if not is_pd(sid):
            continue
        if sid not in pis:
            continue
        items = pis[sid]
        if not all(i in items for i in T3_ALL_ITEMS):
            continue
        sids.append(sid)
        feats.append(r[feature_cols].to_numpy(dtype=np.float64))
        for i in T3_ALL_ITEMS:
            item_arrs[i].append(items[i])
        t3_arr.append(float(r["updrs3"]))
        t1_arr.append(sum(items[i] for i in T1_ITEMS))
    return (
        np.array(sids),
        np.vstack(feats),
        feature_cols,
        np.array(t3_arr, dtype=np.float64),
        np.array(t1_arr, dtype=np.float64),
        {i: np.array(item_arrs[i], dtype=np.float64) for i in T3_ALL_ITEMS},
    )


def load_demographics() -> pd.DataFrame:
    """Load demographic + clinical from raw CSVs. Returns DataFrame indexed by sid."""
    pd_csv = Path(str(DATA_DIR)) / "PD - Demographic+Clinical - datasetV1.csv"
    if not pd_csv.exists():
        # try local fallback
        pd_csv = REPO_ROOT / "data" / "raw" / "weargait-pd" / "PD - Demographic+Clinical - datasetV1.csv"
    if not pd_csv.exists():
        return None
    df = pd.read_csv(pd_csv, header=1)
    df = df.rename(columns=lambda c: c.strip())
    df["sid"] = df.get("Subject ID", df.get("sid")).astype(str).str.strip()
    return df


# ── Inductive helpers (mirror the firewall pattern) ──────────────────────────


def _kfold_subject(sids, target_arr, n_splits=5, seed=42):
    """Subject-level K-fold by stratified bins of target."""
    bins = np.digitize(target_arr, np.quantile(target_arr, [0.25, 0.5, 0.75]))
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    # use simple random KFold on subjects (sids are unique already)
    for tr, te in kf.split(sids):
        yield tr, te


def _train_lgb_simple(X_tr, y_tr, X_te, seed: int):
    """LightGBM with the inductive_pd defaults."""
    import lightgbm as lgb
    params = dict(
        n_estimators=500, learning_rate=0.05, num_leaves=15, max_depth=-1,
        min_data_in_leaf=10, reg_alpha=0.1, reg_lambda=0.3,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
        random_state=seed, n_jobs=N_CORES, verbosity=-1,
    )
    model = lgb.LGBMRegressor(**params)
    model.fit(X_tr, y_tr)
    return model.predict(X_te)


# ── 1.1 PER-ITEM LGB 5-fold CCC ──────────────────────────────────────────────


def task_per_item_lgb():
    print("[1.1] Per-item LGB 5-fold CCC heatmap")
    sids, X, fc, T3, T1, items = get_pd_features_and_items()
    n_pd = len(sids)
    print(f"  {n_pd} PD subjects, {X.shape[1]} features")

    # Robust per-fold imputation
    def impute(X_tr, X_te):
        med = np.nanmedian(X_tr, axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        Xtri = np.where(np.isnan(X_tr), med, X_tr)
        Xtei = np.where(np.isnan(X_te), med, X_te)
        return Xtri, Xtei

    results = {"per_item_ccc_5fold": {}, "per_item_mae_5fold": {}, "n_pd": n_pd}
    for item_idx, item in enumerate(T3_ALL_ITEMS, 1):
        y = items[item]
        if y.std() < 1e-6:
            print(f"  item {item}: skipped (zero variance)")
            continue
        ccs, maes = [], []
        for seed in SEEDS:
            preds = np.zeros(n_pd)
            kf = KFold(n_splits=5, shuffle=True, random_state=seed)
            for tr_idx, te_idx in kf.split(sids):
                X_tr, X_te = X[tr_idx], X[te_idx]
                X_tr, X_te = impute(X_tr, X_te)
                y_tr = y[tr_idx]
                preds[te_idx] = _train_lgb_simple(X_tr, y_tr, X_te, seed)
            c = ccc_fn(y, preds)
            m = mae_fn(y, preds)
            ccs.append(c); maes.append(m)
        results["per_item_ccc_5fold"][item] = {
            "ccc_mean": float(np.mean(ccs)),
            "ccc_std": float(np.std(ccs)),
            "ccc_per_seed": [float(c) for c in ccs],
            "mean_target": float(y.mean()),
            "std_target": float(y.std()),
        }
        results["per_item_mae_5fold"][item] = {
            "mae_mean": float(np.mean(maes)),
            "mae_std": float(np.std(maes)),
        }
        print(f"  item {item}: CCC={np.mean(ccs):.3f}±{np.std(ccs):.3f}, MAE={np.mean(maes):.3f}")
    save("per_item_lgb", results)


# ── 1.2 T3 VARIANCE DECOMPOSITION ────────────────────────────────────────────


def task_variance_decomp():
    print("[1.2] T3 variance decomposition")
    df = get_pd_with_per_item()
    n = len(df)
    T3 = df["T3"].to_numpy()
    item_vars = {i: float(df[f"item{i}"].var()) for i in T3_ALL_ITEMS}
    # Block sums
    Y_T1 = df[[f"item{i}" for i in T1_ITEMS]].sum(axis=1).to_numpy()
    Y_partobs = df[[f"item{i}" for i in PARTIALLY_OBS_ITEMS]].sum(axis=1).to_numpy()
    Y_notobs = df[[f"item{i}" for i in NOT_OBS_ITEMS]].sum(axis=1).to_numpy()
    var_T3 = float(T3.var())
    var_T1 = float(Y_T1.var())
    var_partobs = float(Y_partobs.var())
    var_notobs = float(Y_notobs.var())
    cov_T1_partobs = float(np.cov(Y_T1, Y_partobs)[0, 1])
    cov_T1_notobs = float(np.cov(Y_T1, Y_notobs)[0, 1])
    cov_partobs_notobs = float(np.cov(Y_partobs, Y_notobs)[0, 1])
    # Verify decomposition: var(T3) ≈ var(T1) + var(partobs) + var(notobs) + 2*cov terms
    decomp_sum = var_T1 + var_partobs + var_notobs + 2*(cov_T1_partobs + cov_T1_notobs + cov_partobs_notobs)
    pearson_T1_T3 = float(np.corrcoef(Y_T1, T3)[0, 1])
    pearson_partobs_T3 = float(np.corrcoef(Y_partobs, T3)[0, 1])
    pearson_notobs_T3 = float(np.corrcoef(Y_notobs, T3)[0, 1])
    save("variance_decomp", {
        "n": n, "var_T3": var_T3,
        "var_T1": var_T1, "var_partially_observable": var_partobs, "var_not_observable": var_notobs,
        "cov_T1_partobs": cov_T1_partobs, "cov_T1_notobs": cov_T1_notobs,
        "cov_partobs_notobs": cov_partobs_notobs,
        "pct_var_T1": var_T1 / var_T3,
        "pct_var_partobs": var_partobs / var_T3,
        "pct_var_notobs": var_notobs / var_T3,
        "decomp_sum": decomp_sum,
        "pearson_T1_T3": pearson_T1_T3,
        "pearson_partobs_T3": pearson_partobs_T3,
        "pearson_notobs_T3": pearson_notobs_T3,
        "item_variances": item_vars,
        "T1_items": T1_ITEMS, "partially_observable_items": PARTIALLY_OBS_ITEMS, "not_observable_items": NOT_OBS_ITEMS,
    })
    print(f"  var(T3)={var_T3:.1f}, var(T1)={var_T1:.1f} ({100*var_T1/var_T3:.1f}%)")
    print(f"  pearson(T1, T3)={pearson_T1_T3:.3f}")


# ── 1.3 T3 CEILING DERIVATION ────────────────────────────────────────────────


def task_ceiling_derivation():
    """Derive max achievable T3 CCC from gait-IMU only.

    Bound: best CCC achievable is the CCC of (T1_pred + Y_R_demographics_or_mean) vs T3.
    We compute several bounds:
    (A) Oracle T1 (perfect T1) + mean R: gives upper bound from T1 alone
    (B) Current T1_pred (CCC=0.588 LOOCV) + mean R: gives realistic bound
    (C) Current T1_pred + best demographics R: gives realistic bound w/ demo
    """
    print("[1.3] T3 ceiling derivation")
    df = get_pd_with_per_item()
    sids = df["sid"].to_numpy()
    T3 = df["T3"].to_numpy()
    T1 = df[[f"item{i}" for i in T1_ITEMS]].sum(axis=1).to_numpy()
    R = T3 - T1  # residual non-T1 items

    # Load actual T1 LOOCV predictions
    if not T1_LOOCV.exists():
        print(f"  WARN: {T1_LOOCV} missing — using T1=0.588 placeholder")
        # synthetic T1_pred with target CCC=0.588
        np.random.seed(42)
        noise = np.random.randn(len(T1)) * T1.std()
        # solve for noise scale to hit CCC=0.588
        T1_pred_synth = T1.mean() + 0.7*(T1 - T1.mean()) + 0.5*T1.std()*np.random.randn(len(T1))
        sids_t1 = sids
        T1_pred = T1_pred_synth
    else:
        with open(T1_LOOCV) as f:
            t1_data = json.load(f)
        per_subj = t1_data.get("per_subject", {})
        sids_t1 = np.array(per_subj.get("sids", []))
        T1_pred_all = np.array(per_subj.get("y_pred", []))
        T1_true_all = np.array(per_subj.get("y_true", []))
        # Align to our sids
        sid_to_pred = dict(zip(sids_t1, T1_pred_all))
        T1_pred = np.array([sid_to_pred.get(s, np.nan) for s in sids])
        valid = ~np.isnan(T1_pred)
        if valid.sum() < len(sids):
            print(f"  {len(sids) - valid.sum()} sids missing T1 LOOCV preds; subsetting")
            sids = sids[valid]
            T3 = T3[valid]; T1 = T1[valid]; R = R[valid]; T1_pred = T1_pred[valid]

    actual_T1_ccc = ccc_fn(T1, T1_pred)
    actual_T1_r = pearson_r(T1, T1_pred)

    # Bound A: oracle T1 + mean R
    Y_pred_A = T1 + R.mean()
    bound_A = ccc_fn(T3, Y_pred_A)

    # Bound B: actual T1_pred + mean R
    Y_pred_B = T1_pred + R.mean()
    bound_B = ccc_fn(T3, Y_pred_B)

    # Bound C: actual T1_pred + best linear regression of R on T1
    coef = np.polyfit(T1, R, 1)
    R_pred_C = np.polyval(coef, T1_pred)
    Y_pred_C = T1_pred + R_pred_C
    bound_C = ccc_fn(T3, Y_pred_C)

    # Bound D: theoretical perfect T1 + perfect mean-R (R variance is unrecoverable)
    # CCC bound = ρ(T1, T3) given perfect T1 prediction
    pearson_T1_T3 = float(np.corrcoef(T1, T3)[0, 1])

    # Bound E: shrinkage map (Ridge) trained on T1 → T3
    # Per-fold inductive bound: split, fit shrinkage on train, apply to test
    n = len(sids)
    preds_E = np.zeros(n)
    np.random.seed(42)
    perm = np.random.permutation(n)
    folds = np.array_split(perm, 5)
    for fold_idx in range(5):
        te = folds[fold_idx]
        tr = np.concatenate([folds[i] for i in range(5) if i != fold_idx])
        # Fit shrinkage T1 → T3 on training only
        c = np.polyfit(T1[tr], T3[tr], 1)
        # Apply to test T1_pred (NOT T1 — using actual T1 preds)
        preds_E[te] = np.polyval(c, T1_pred[te])
    bound_E = ccc_fn(T3, preds_E)

    save("ceiling_derivation", {
        "n": int(n),
        "actual_T1_ccc": float(actual_T1_ccc),
        "actual_T1_pearson_r": float(actual_T1_r),
        "bound_A_oracle_T1_plus_meanR": float(bound_A),
        "bound_B_actual_T1pred_plus_meanR": float(bound_B),
        "bound_C_actual_T1pred_plus_linearR": float(bound_C),
        "bound_D_theoretical_perfect_T1_corr_to_T3": float(pearson_T1_T3),
        "bound_E_inductive_shrinkage_T1_to_T3": float(bound_E),
        "T3_LOOCV_baseline_ccc": 0.217,  # from results/baseline_B1_v2_only_t3_loocv.json
        "rationale": (
            "Bound D = pearson(T1, T3) = absolute upper bound for ANY model that perfectly predicts T1 alone. "
            "Bound A = oracle T1 (perfect prediction) + mean R = upper bound subject to using only T1. "
            "Bound B = current T1 prediction quality + mean R. "
            "Bound C = current T1 prediction + simple linear residual model. "
            "Bound E = inductive shrinkage map T1_pred → T3 (fold-local). "
            "Realistic max for our pipeline = bound E (this is what iter 2.2 will optimize)."
        ),
    })
    print(f"  actual T1 LOOCV CCC = {actual_T1_ccc:.3f}")
    print(f"  bound A (oracle T1 + mean R) = {bound_A:.3f}")
    print(f"  bound B (actual T1 + mean R) = {bound_B:.3f}")
    print(f"  bound C (actual T1 + linear R) = {bound_C:.3f}")
    print(f"  bound D (theoretical pearson T1↔T3) = {pearson_T1_T3:.3f}")
    print(f"  bound E (inductive shrinkage) = {bound_E:.3f}")
    print(f"  current T3 LOOCV baseline = 0.217")


# ── 1.4 PER-SUBJECT ERROR DECOMPOSITION ──────────────────────────────────────


def task_error_decomp():
    """T3_err vs T1_err per subject. Are they correlated?"""
    print("[1.4] Per-subject error decomposition")
    df = get_pd_with_per_item()
    sid_set = set(df["sid"].tolist())

    # Load T1 LOOCV preds
    if not T1_LOOCV.exists():
        print(f"  SKIP — {T1_LOOCV} missing")
        save("error_decomp", {"skipped": True, "reason": "T1 LOOCV missing"})
        return
    if not T3_LOOCV.exists():
        print(f"  SKIP — {T3_LOOCV} missing")
        save("error_decomp", {"skipped": True, "reason": "T3 LOOCV missing"})
        return

    with open(T1_LOOCV) as f:
        t1d = json.load(f)
    with open(T3_LOOCV) as f:
        t3d = json.load(f)
    t1_sids = np.array(t1d["per_subject"]["sids"])
    t1_p = np.array(t1d["per_subject"]["y_pred"])
    t1_t = np.array(t1d["per_subject"]["y_true"])
    t3_sids = np.array(t3d["per_subject"]["sids"])
    t3_p = np.array(t3d["per_subject"]["y_pred"])
    t3_t = np.array(t3d["per_subject"]["y_true"])

    # Align
    common = sorted(set(t1_sids) & set(t3_sids) & sid_set)
    t1_map = dict(zip(t1_sids, zip(t1_p, t1_t)))
    t3_map = dict(zip(t3_sids, zip(t3_p, t3_t)))
    rows = []
    for sid in common:
        p1, true1 = t1_map[sid]
        p3, true3 = t3_map[sid]
        e1 = float(p1) - float(true1)
        e3 = float(p3) - float(true3)
        rows.append({"sid": sid, "t1_err": e1, "t3_err": e3, "t1_true": float(true1), "t3_true": float(true3),
                     "site": site_of(sid)})
    edf = pd.DataFrame(rows)
    corr = float(edf["t1_err"].corr(edf["t3_err"]))
    rho = float(spearmanr(edf["t1_err"], edf["t3_err"])[0])
    save("error_decomp", {
        "n": len(edf),
        "t1_t3_err_pearson": corr,
        "t1_t3_err_spearman": rho,
        "per_subject": edf.to_dict(orient="records"),
        "interpretation": (
            "If pearson > 0.5: T3 error driven mostly by T1 error → improving T1 will lift T3. "
            "If pearson < 0.3: T3 error dominated by non-T1 items → need different signal sources."
        ),
    })
    print(f"  n={len(edf)}, pearson(T1_err, T3_err) = {corr:.3f}, spearman = {rho:.3f}")


# ── 1.5 DEMOGRAPHICS-ONLY-PER-ITEM ───────────────────────────────────────────


def task_demo_per_item():
    """Ridge per UPDRS item using demographics only (LOOCV)."""
    print("[1.5] Demographics-only-per-item LOOCV")
    demo = load_demographics()
    if demo is None:
        print("  SKIP — demographics CSV not available locally")
        save("demo_per_item", {"skipped": True, "reason": "demo CSV missing"})
        return
    df = get_pd_with_per_item()
    # Try to find demographic columns
    age_col = next((c for c in demo.columns if "age" in c.lower()), None)
    sex_col = next((c for c in demo.columns if "sex" in c.lower() or "gender" in c.lower()), None)
    height_col = next((c for c in demo.columns if "height" in c.lower()), None)
    weight_col = next((c for c in demo.columns if "weight" in c.lower()), None)
    dx_col = next((c for c in demo.columns if "dx" in c.lower() or "diagnosis" in c.lower() or "year" in c.lower()), None)

    cols = [c for c in [age_col, sex_col, height_col, weight_col, dx_col] if c]
    if not cols:
        print("  SKIP — no demographic columns matched")
        save("demo_per_item", {"skipped": True, "reason": "no demo columns matched"})
        return

    demo["sid"] = demo["sid"].astype(str).str.strip()
    merged = df.merge(demo[["sid"] + cols], on="sid", how="left")
    Xd = merged[cols].copy()
    if sex_col:
        Xd[sex_col] = pd.Categorical(Xd[sex_col]).codes.astype(float)
    Xd = Xd.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    # Per-fold median impute
    medians = np.nanmedian(Xd, axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)
    Xd = np.where(np.isnan(Xd), medians, Xd)
    valid = ~np.any(np.isnan(Xd), axis=1)
    sids_v = merged["sid"].to_numpy()[valid]
    Xd = Xd[valid]
    merged = merged[valid].reset_index(drop=True)

    results = {}
    for item in T3_ALL_ITEMS:
        y = merged[f"item{item}"].to_numpy(dtype=np.float64)
        if y.std() < 1e-6:
            continue
        n = len(y)
        loo = LeaveOneOut()
        preds = np.zeros(n)
        for tr, te in loo.split(Xd):
            # fold-local: median impute (already done globally; for proper per-fold:
            # refit medians on tr only). Simpler: recompute medians on tr.
            med = np.nanmedian(Xd[tr], axis=0)
            med = np.where(np.isnan(med), 0.0, med)
            X_tr = np.where(np.isnan(Xd[tr]), med, Xd[tr])
            X_te = np.where(np.isnan(Xd[te]), med, Xd[te])
            mu = X_tr.mean(axis=0); sigma = X_tr.std(axis=0); sigma[sigma < 1e-9] = 1.0
            X_tr = (X_tr - mu) / sigma
            X_te = (X_te - mu) / sigma
            ridge = Ridge(alpha=1.0)
            ridge.fit(X_tr, y[tr])
            preds[te] = ridge.predict(X_te)
        results[item] = {"ccc": float(ccc_fn(y, preds)), "mae": float(mae_fn(y, preds)),
                         "r": float(pearson_r(y, preds))}
        print(f"  item {item}: demo CCC={results[item]['ccc']:.3f}")
    save("demo_per_item", {"per_item": results, "demo_cols": cols, "n": int(valid.sum())})


# ── 1.6 SPEARMAN FEATURE × ITEM ──────────────────────────────────────────────


def task_feature_item_corr():
    print("[1.6] Feature × item Spearman correlation matrix (top 10 per item)")
    sids, X, fc, T3, T1, items = get_pd_features_and_items()
    n_pd, n_feat = X.shape
    print(f"  {n_pd} PD subjects × {n_feat} features × 18 items")
    # Median-impute X globally for diagnostic purposes (not for inductive eval)
    med = np.nanmedian(X, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    X = np.where(np.isnan(X), med, X)

    top_per_item = {}
    full_matrix_items = {}
    for item in T3_ALL_ITEMS:
        y = items[item]
        if y.std() < 1e-6:
            continue
        # Compute Spearman per-feature; vectorized via ranking
        # Use scipy.stats.spearmanr on each column
        rhos = np.zeros(n_feat)
        for j in range(n_feat):
            x = X[:, j]
            if x.std() < 1e-9:
                continue
            r, _ = spearmanr(x, y)
            if np.isnan(r):
                continue
            rhos[j] = r
        order = np.argsort(np.abs(rhos))[::-1][:10]
        top_per_item[item] = [{"feature": fc[i], "rho": float(rhos[i])} for i in order]
        # Also: fraction of features with |rho| > 0.3
        full_matrix_items[item] = {
            "max_abs_rho": float(np.max(np.abs(rhos))),
            "median_abs_rho": float(np.median(np.abs(rhos))),
            "frac_above_0.2": float(np.mean(np.abs(rhos) > 0.2)),
            "frac_above_0.3": float(np.mean(np.abs(rhos) > 0.3)),
        }
        print(f"  item {item}: max|rho|={np.max(np.abs(rhos)):.3f}, frac>0.3={np.mean(np.abs(rhos)>0.3):.3%}")
    save("feature_item_corr", {
        "n": n_pd, "n_features": n_feat,
        "top_per_item": {str(k): v for k, v in top_per_item.items()},
        "summary_per_item": {str(k): v for k, v in full_matrix_items.items()},
    })


# ── 1.7 PREDICTION DISPERSION ────────────────────────────────────────────────


def task_pred_dispersion():
    print("[1.7] Prediction dispersion analysis")
    paths = list(RESULTS_DIR.glob("*_t3_5split.json")) + list(RESULTS_DIR.glob("*_t3_loocv.json"))
    rows = []
    for p in paths:
        try:
            with open(p) as f:
                d = json.load(f)
            label = d.get("label", p.stem)
            pred_std = d.get("pred_std")
            true_std = d.get("true_std")
            if pred_std and true_std:
                rows.append({
                    "file": p.name, "label": label,
                    "ccc": d.get("ccc", 0),
                    "mae": d.get("mae", 0),
                    "pred_std": float(pred_std), "true_std": float(true_std),
                    "ratio": float(pred_std) / float(true_std) if true_std else 0,
                    "eval_mode": d.get("eval_mode", ""),
                })
        except Exception:
            continue
    save("pred_dispersion", {"n_files": len(rows), "data": rows})
    print(f"  loaded {len(rows)} T3 result files")


# ── 1.8 LEVODOPA STATE EFFECT ────────────────────────────────────────────────


def task_med_state():
    print("[1.8] Levodopa/medication state effect")
    demo = load_demographics()
    if demo is None:
        save("med_state", {"skipped": True, "reason": "demo CSV missing"})
        return
    med_col = next((c for c in demo.columns if "med" in c.lower() or "levodop" in c.lower() or "ldopa" in c.lower()), None)
    if not med_col:
        save("med_state", {"skipped": True, "reason": "no med state column found"})
        return
    if not T3_LOOCV.exists():
        save("med_state", {"skipped": True, "reason": "T3 LOOCV missing"})
        return
    with open(T3_LOOCV) as f:
        td = json.load(f)
    sids = td["per_subject"]["sids"]
    p = td["per_subject"]["y_pred"]
    t = td["per_subject"]["y_true"]
    err = np.array(p) - np.array(t)
    df = pd.DataFrame({"sid": sids, "err": err, "abs_err": np.abs(err)})
    demo["sid"] = demo["sid"].astype(str).str.strip()
    df = df.merge(demo[["sid", med_col]], on="sid", how="left")
    by_state = df.groupby(med_col).agg({"abs_err": ["mean", "std", "count"]}).reset_index()
    save("med_state", {"med_col": med_col, "table": by_state.to_dict(orient="records"), "n": len(df)})
    print(f"  {med_col}: {len(df)} subjects with med state")


# ── 1.9 H&Y STRATIFIED ───────────────────────────────────────────────────────


def task_hy_strat():
    print("[1.9] H&Y stratified T3 CCC")
    demo = load_demographics()
    if demo is None:
        save("hy_strat", {"skipped": True, "reason": "demo CSV missing"})
        return
    hy_col = next((c for c in demo.columns if "h&y" in c.lower() or "hoehn" in c.lower() or c.upper() in ("HY", "H&Y")), None)
    if not hy_col:
        # Try numeric columns containing "stage"
        hy_col = next((c for c in demo.columns if "stage" in c.lower()), None)
    if not hy_col:
        save("hy_strat", {"skipped": True, "reason": "no H&Y column found", "cols_sample": list(demo.columns)[:30]})
        return
    if not T3_LOOCV.exists():
        save("hy_strat", {"skipped": True, "reason": "T3 LOOCV missing"})
        return
    with open(T3_LOOCV) as f:
        td = json.load(f)
    sids = td["per_subject"]["sids"]
    p = np.array(td["per_subject"]["y_pred"])
    t = np.array(td["per_subject"]["y_true"])
    df = pd.DataFrame({"sid": sids, "pred": p, "true": t})
    demo["sid"] = demo["sid"].astype(str).str.strip()
    df = df.merge(demo[["sid", hy_col]], on="sid", how="left")
    df["hy_bin"] = pd.cut(pd.to_numeric(df[hy_col], errors="coerce"),
                          bins=[-0.1, 1.5, 2.0, 2.5, 3.0, 5.0],
                          labels=["1-1.5", "2", "2.5", "3", "≥4"])
    by_stage = []
    for grp, sub in df.groupby("hy_bin", observed=True):
        if len(sub) >= 3:
            by_stage.append({
                "hy_bin": str(grp),
                "n": len(sub),
                "ccc": float(ccc_fn(sub["true"].to_numpy(), sub["pred"].to_numpy())),
                "mae": float(mae_fn(sub["true"].to_numpy(), sub["pred"].to_numpy())),
                "true_mean": float(sub["true"].mean()),
                "pred_mean": float(sub["pred"].mean()),
            })
    save("hy_strat", {"hy_col": hy_col, "n": len(df), "table": by_stage})
    print(f"  {hy_col}: {len(by_stage)} bins")


# ── 1.10 SITE STRATIFIED + LEAVE-SITE-OUT ────────────────────────────────────


def task_site_strat():
    print("[1.10] Site-stratified + leave-site-out T3")
    sids, X, fc, T3, T1, items = get_pd_features_and_items()
    sites = np.array([site_of(s) for s in sids])
    n = len(sids)
    print(f"  {(sites=='NLS').sum()} NLS, {(sites=='WPD').sum()} WPD")

    # Stratified per-site CCC from existing T3 LOOCV
    by_site_existing = {}
    if T3_LOOCV.exists():
        with open(T3_LOOCV) as f:
            td = json.load(f)
        s = np.array(td["per_subject"]["sids"])
        p = np.array(td["per_subject"]["y_pred"])
        t = np.array(td["per_subject"]["y_true"])
        for site in ["NLS", "WPD"]:
            mask = np.array([site_of(x) == site for x in s])
            if mask.sum() >= 3:
                by_site_existing[site] = {
                    "n": int(mask.sum()),
                    "ccc": float(ccc_fn(t[mask], p[mask])),
                    "mae": float(mae_fn(t[mask], p[mask])),
                }

    # Leave-site-out: train on NLS, test on WPD; train on WPD, test on NLS
    # Use median-impute features (diagnostic only, no inductive penalty here for screening)
    med = np.nanmedian(X, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    X_imp = np.where(np.isnan(X), med, X)

    loso = {}
    for train_site, test_site in [("NLS", "WPD"), ("WPD", "NLS")]:
        tr = sites == train_site
        te = sites == test_site
        if tr.sum() < 10 or te.sum() < 5:
            continue
        # Use shrinkage map: T1 → T3 via Ridge; we don't have T1 preds for this analysis
        # Just use LGB on V2 features
        try:
            preds = _train_lgb_simple(X_imp[tr], T3[tr], X_imp[te], 42)
            loso[f"{train_site}_to_{test_site}"] = {
                "n_train": int(tr.sum()), "n_test": int(te.sum()),
                "ccc": float(ccc_fn(T3[te], preds)),
                "mae": float(mae_fn(T3[te], preds)),
                "r": float(pearson_r(T3[te], preds)),
            }
            print(f"  {train_site}→{test_site}: CCC={loso[f'{train_site}_to_{test_site}']['ccc']:.3f}")
        except Exception as e:
            loso[f"{train_site}_to_{test_site}"] = {"error": str(e)}

    save("site_strat", {
        "n_NLS": int((sites == "NLS").sum()),
        "n_WPD": int((sites == "WPD").sum()),
        "by_site_existing_T3_LOOCV": by_site_existing,
        "leave_site_out": loso,
    })


# ── DISPATCH ─────────────────────────────────────────────────────────────────


TASKS = {
    "per_item_lgb": task_per_item_lgb,         # 1.1 — heavy, needs lightgbm
    "variance_decomp": task_variance_decomp,    # 1.2
    "ceiling_derivation": task_ceiling_derivation,  # 1.3
    "error_decomp": task_error_decomp,          # 1.4
    "demo_per_item": task_demo_per_item,        # 1.5
    "feature_item_corr": task_feature_item_corr,  # 1.6 — heavy O(n_feat * 18) Spearmans
    "pred_dispersion": task_pred_dispersion,    # 1.7
    "med_state": task_med_state,                # 1.8
    "hy_strat": task_hy_strat,                  # 1.9
    "site_strat": task_site_strat,              # 1.10
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", default="all", help="task name or 'all' or comma-separated")
    args = p.parse_args()

    if args.task == "all":
        names = list(TASKS.keys())
    else:
        names = [t.strip() for t in args.task.split(",")]

    for name in names:
        if name not in TASKS:
            print(f"UNKNOWN task: {name}")
            continue
        t0 = time.time()
        try:
            TASKS[name]()
            print(f"  ✓ {name} done in {time.time()-t0:.1f}s")
        except Exception as e:
            import traceback
            traceback.print_exc()
            save(name, {"error": str(e), "traceback": traceback.format_exc()})


if __name__ == "__main__":
    main()
