"""
Sensor Ablation Study
=====================
Systematic sensor reduction for clinical deployment recommendation.
16 configurations from all-13 to single-sensor.

Uses cached features from run_proven_stack.py (proven_stack_features.csv).
Column filtering by sensor name simulates only having certain sensors.
Distilled walkway proxies are excluded by default because they were learned
from the full-sensor feature matrix and would contaminate reduced-sensor claims.

Pipeline: XGBoost importance selection K=150 → LGB+XGB stacking → Ridge L1.
"""
import os, sys, json, time, warnings
from collections import OrderedDict
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
warnings.filterwarnings("ignore")

from project_paths import REPO_ROOT, repo_artifact_path, save_json_artifact

sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split, SENSORS

FEATURE_CACHE = str(repo_artifact_path("proven_stack_features.csv"))
ALLOW_PRIVILEGED_DST = os.getenv("WEARGAIT_ALLOW_PRIVILEGED_DISTILLATION", "").strip() == "1"
N_CORES = 11
SEEDS = [42, 123, 456, 789, 2024]

# ── Sensor configurations ────────────────────────────────────────────
SENSOR_CONFIGS = OrderedDict([
    # Full set
    ("all_13", SENSORS),
    # Leave-group-out
    ("no_LowerBack", [s for s in SENSORS if s != "LowerBack"]),
    ("no_Wrists", [s for s in SENSORS if "Wrist" not in s]),
    ("no_Feet", [s for s in SENSORS if "DorsalFoot" not in s]),
    ("no_Ankles", [s for s in SENSORS if "Ankle" not in s]),
    ("no_Shanks", [s for s in SENSORS if "LatShank" not in s]),
    ("no_Thighs", [s for s in SENSORS if "MidLatThigh" not in s]),
    ("no_Xiphoid", [s for s in SENSORS if s != "Xiphoid"]),
    ("no_Forehead", [s for s in SENSORS if s != "Forehead"]),
    # Clinical deployment subsets
    ("lower_back_1", ["LowerBack"]),
    ("wrists_2", ["R_Wrist", "L_Wrist"]),
    ("back_wrists_3", ["LowerBack", "R_Wrist", "L_Wrist"]),
    ("back_ankles_3", ["LowerBack", "R_Ankle", "L_Ankle"]),
    ("feet_ankles_4", ["R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"]),
    ("minimal_5", ["LowerBack", "R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle"]),
    ("lower_body_9", [s for s in SENSORS if s not in ("R_Wrist", "L_Wrist", "Xiphoid", "Forehead")]),
    ("upper_body_4", ["R_Wrist", "L_Wrist", "Xiphoid", "Forehead"]),
])


def filter_features_for_sensors(all_cols, sensor_set, allow_privileged_dst=False):
    """Return columns available if only sensor_set sensors are worn.

    Rules:
    - Sensor-prefixed features: keep if sensor is in set
    - Asymmetry (asy_*): keep if both L and R of the pair are in set
    - Event/turn/balance/STS: keep if LowerBack is in set
    - Foot contact (fc_*): keep if any foot/ankle sensor in set
    - Kinematics (k_*): keep if relevant ankle/shank in set
    - Distribution (dv_*) and contrasts (d_*, r_*): keep if source sensor in set
    - Covariates and metadata: always keep
    - Distilled walkway features: excluded unless explicitly requested
    """
    sensor_set = set(sensor_set)
    keep = []

    for col in all_cols:
        # Direct sensor-prefixed features
        matched_sensor = None
        for s in SENSORS:
            if col.startswith(s + "_"):
                matched_sensor = s
                break

        if matched_sensor is not None:
            if matched_sensor in sensor_set:
                keep.append(col)
            continue

        # Asymmetry features: asy_{PairName}_{stat}
        if col.startswith("asy_"):
            parts = col.split("_")
            if len(parts) >= 2:
                pair_name = parts[1]
                if f"R_{pair_name}" in sensor_set and f"L_{pair_name}" in sensor_set:
                    keep.append(col)
            continue

        # Event/turn/balance/STS: derived from LowerBack
        if col.startswith(("ev_", "trn_", "sts_", "bal_")):
            if "LowerBack" in sensor_set:
                keep.append(col)
            continue

        # Foot contact: derived from foot/ankle sensors
        if col.startswith("fc_"):
            foot_sensors = {"R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"}
            if sensor_set & foot_sensors:
                keep.append(col)
            continue

        # Kinematics: k_{side}_{stat}
        if col.startswith("k_"):
            side = col[2] if len(col) > 2 else ""
            ankle = f"{side}_Ankle"
            shank = f"{side}_LatShank"
            if ankle in sensor_set or shank in sensor_set:
                keep.append(col)
            continue

        # Distribution/contrast features: check if source sensor in set
        if col.startswith(("dv_", "d_", "r_")):
            found = any(s in col for s in sensor_set)
            # Keep if matching sensor found, or if no sensor referenced at all
            if found or not any(s in col for s in SENSORS):
                keep.append(col)
            continue

        # Covariates and metadata: always keep
        if col.startswith(("cv_", "ext_", "n_")) or col in ("duration_s",):
            keep.append(col)
            continue

        # Distilled walkway proxies were learned from the full-sensor matrix.
        if col.startswith("dst_"):
            if allow_privileged_dst:
                keep.append(col)
            continue

        # Unknown column — keep
        keep.append(col)

    return keep


def feature_select(X, y, names, k=150):
    from xgboost import XGBRegressor
    k = min(k, X.shape[1])
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                       reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                       objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def split_train_val(X, y, seed, val_frac=0.15):
    rng = np.random.RandomState(seed)
    idx = np.arange(len(X)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * val_frac))
    return X[idx[nv:]], y[idx[nv:]], X[idx[:nv]], y[idx[:nv]]


def run_stacking(name, Xd, yd, Xt, yt, fnames, k=150):
    import lightgbm as lgb
    from xgboost import XGBRegressor

    k = min(k, Xd.shape[1])
    if k < 5:
        print(f"  {name}: only {k} features, skipping")
        return None

    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof_lgb = np.zeros(len(Xds))
        oof_xgb = np.zeros(len(Xds))
        test_lgb = np.zeros(len(Xts))
        test_xgb = np.zeros(len(Xts))

        for tr_i, val_i in kf.split(Xds):
            Xtr, ytr, Xv, yv = split_train_val(Xds[tr_i], yd[tr_i], seed + len(tr_i))

            m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                    reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                    objective="mae", verbose=-1)
            m1.fit(Xtr, ytr, eval_set=[(Xv, yv)],
                   callbacks=[lgb.early_stopping(100, verbose=False)])
            oof_lgb[val_i] = m1.predict(Xds[val_i])
            test_lgb += m1.predict(Xts) / 5

            m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                              reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                              early_stopping_rounds=100, objective="reg:absoluteerror")
            m2.fit(Xtr, ytr, eval_set=[(Xv, yv)], verbose=False)
            oof_xgb[val_i] = m2.predict(Xds[val_i])
            test_xgb += m2.predict(Xts) / 5

        L0_train = np.column_stack([oof_lgb, oof_xgb])
        L0_test = np.column_stack([test_lgb, test_xgb])
        meta = Ridge(alpha=1.0)
        meta.fit(L0_train, yd)
        p = np.clip(meta.predict(L0_test), 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    return {"config": name, "n_sensors": len([s for s in SENSORS if s in set(SENSOR_CONFIGS.get(name, SENSORS))]),
            "n_features_available": int(Xd.shape[1]), "n_selected": k,
            "mean_mae": round(float(np.mean(maes)), 3),
            "std_mae": round(float(np.std(maes)), 3),
            "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
            "seed_maes": [round(float(m), 3) for m in maes],
            "top5_features": sel_names[:5]}


def main():
    t0 = time.time()
    print("=" * 70)
    print("SENSOR ABLATION STUDY")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]

    if not os.path.exists(FEATURE_CACHE):
        print(f"ERROR: cached features not found at {FEATURE_CACHE}")
        sys.exit(1)

    df = pd.read_csv(FEATURE_CACHE)
    print(f"Loaded: {len(df)} subjects × {len(df.columns) - 2} features")

    # Add extended covariates
    from run_proven_stack import load_extended_covariates
    ext_cov = load_extended_covariates()
    ext_names = ["ext_height", "ext_weight", "ext_bmi", "ext_age_onset",
                 "ext_yrs_sq", "ext_yrs_log", "ext_early_pd", "ext_late_pd"]
    for col_name in ext_names:
        if col_name not in df.columns:
            df[col_name] = df["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0)).fillna(0.0)

    all_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    for c in all_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    dm = df["sid"].isin(dev_sids)
    tm = df["sid"].isin(test_sids)
    y_dev = df.loc[dm, "updrs3"].values.astype(np.float32)
    y_test = df.loc[tm, "updrs3"].values.astype(np.float32)

    results = []

    for cfg_name, sensor_list in SENSOR_CONFIGS.items():
        print(f"\n{'='*70}")
        print(f"{cfg_name}: {len(sensor_list)} sensors — {sensor_list}")
        print(f"{'='*70}")

        # Filter features for this sensor set
        avail_cols = filter_features_for_sensors(
            all_cols,
            sensor_list,
            allow_privileged_dst=ALLOW_PRIVILEGED_DST,
        )
        print(f"  Features available: {len(avail_cols)} / {len(all_cols)}")

        if len(avail_cols) < 10:
            print(f"  SKIP: too few features ({len(avail_cols)})")
            results.append({"config": cfg_name, "n_sensors": len(sensor_list),
                           "n_features_available": len(avail_cols),
                           "ens_mae": 99.0, "ens_r": 0.0, "skipped": True})
            continue

        X_dev = df.loc[dm, avail_cols].values.astype(np.float32)
        X_test = df.loc[tm, avail_cols].values.astype(np.float32)

        k = min(150, len(avail_cols))
        r = run_stacking(cfg_name, X_dev, y_dev, X_test, y_test, avail_cols, k=k)
        if r:
            r["n_sensors"] = len(sensor_list)
            r["sensors"] = sensor_list
            results.append(r)
            print(f"  → ENS MAE={r['ens_mae']:.2f}, r={r['ens_r']:.3f} ({len(avail_cols)} feats → K={k})")

    # ── Summary ───────────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print("SENSOR ABLATION RESULTS (sorted by ENS MAE)")
    print(f"{'='*70}")

    valid = [r for r in results if not r.get("skipped")]
    baseline = next((r for r in valid if r["config"] == "all_13"), None)
    baseline_mae = baseline["ens_mae"] if baseline else 99.0

    print(f"  {'Config':<20s} {'#Sen':>4s} {'#Feat':>6s} {'K':>4s} {'MAE±std':>12s} {'ENS':>7s} {'r':>6s} {'Δ':>7s}")
    print(f"  {'-'*70}")
    for r in sorted(valid, key=lambda x: x["ens_mae"]):
        d = baseline_mae - r["ens_mae"]
        ds = f"+{d:.2f}" if d > 0 else f"{d:.2f}"
        ns = r.get("n_sensors", "?")
        nf = r.get("n_features_available", "?")
        k = r.get("n_selected", "?")
        print(f"  {r['config']:<20s} {ns:>4} {nf:>6} {k:>4} "
              f"{r['mean_mae']:>5.2f}±{r['std_mae']:.2f} {r['ens_mae']:>7.2f} {r['ens_r']:>6.3f} {ds:>7s}")

    # Clinical deployment summary
    print(f"\n  CLINICAL DEPLOYMENT SUMMARY:")
    for cfg in ["all_13", "minimal_5", "back_wrists_3", "back_ankles_3", "lower_back_1", "wrists_2"]:
        r = next((x for x in valid if x["config"] == cfg), None)
        if r:
            pct = (r["ens_mae"] - baseline_mae) / baseline_mae * 100
            print(f"    {cfg:<20s}: MAE={r['ens_mae']:.2f} ({pct:+.1f}% vs full)")

    print(f"\n  Runtime: {total:.0f}s ({total/60:.1f}m)")

    payload = {
        "results": results,
        "baseline_mae": float(baseline_mae),
        "runtime_s": round(total, 1),
        "protocol": {
            "allow_privileged_distilled_walkway_features": ALLOW_PRIVILEGED_DST,
            "sensor_isolation_valid_for_dst": not ALLOW_PRIVILEGED_DST,
        },
    }
    save_json_artifact("sensor_ablation_results.json", payload)
    print("  Saved to results/sensor_ablation_results.json")


if __name__ == "__main__":
    main()
