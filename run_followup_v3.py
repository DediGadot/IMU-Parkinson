#!/usr/bin/env python3
"""run_followup_v3.py — IMU-only follow-up experiments for ablation v3.

Three experiments:
1. 10-split validation of stride_var features (primary result was single-split)
2. PD-only LOOCV WITHOUT obs_subscore (fair Hssayeni comparison)
3. Combined stride_var + adv_asym features (both IMU-only)
"""
import sys, os, json, time
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, save_json_artifact, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split, _updrs_bin, _get_valid_sids
from run_ablation_v3 import (
    v2_cols, is_new, gen_split, prep_arrays, train_lgb, train_xgb,
    run_eval, run_stack, feature_select, FEATURE_CACHE, N_CORES, SEEDS,
)

ensure_dir(RESULTS_DIR)


def load_features():
    if not os.path.exists(FEATURE_CACHE):
        raise FileNotFoundError(f"Feature cache missing: {FEATURE_CACHE}")
    return pd.read_csv(FEATURE_CACHE)


def exp1_stride_var_10split(df, subjects):
    """10-split validation of stride_var features (IMU-only)."""
    print("\n" + "=" * 70)
    print("EXP 1: 10-SPLIT STRIDE-VAR VALIDATION (IMU-only)")
    print("=" * 70)
    t0 = time.time()

    base_cols = v2_cols(df)
    sv_cols = [c for c in df.columns if c.startswith("sv_")]
    cols = base_cols + sv_cols
    cols = [c for c in cols if c in df.columns]
    print(f"  Features: {len(base_cols)} v2 + {len(sv_cols)} stride_var = {len(cols)} total")

    # Also run baseline v2 for direct comparison
    results_base = {"lgb": [], "stk": []}
    results_sv = {"lgb": [], "stk": []}

    for seed in range(1, 11):
        dev_s, test_s = gen_split(subjects, seed)

        # Baseline v2
        Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, base_cols)
        r_lgb = run_eval(f"base_s{seed}_lgb", Xd, yd, Xt, yt, base_cols, k=150)
        r_stk = run_stack(f"base_s{seed}_stk", Xd, yd, Xt, yt, base_cols, k=150)
        results_base["lgb"].append(r_lgb["ens_mae"])
        results_base["stk"].append(r_stk["ens_mae"])

        # Stride-var
        Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, cols)
        r_lgb = run_eval(f"sv_s{seed}_lgb", Xd, yd, Xt, yt, cols, k=150)
        r_stk = run_stack(f"sv_s{seed}_stk", Xd, yd, Xt, yt, cols, k=150)
        results_sv["lgb"].append(r_lgb["ens_mae"])
        results_sv["stk"].append(r_stk["ens_mae"])

        print(f"  [{seed}/10] base_stk={results_base['stk'][-1]:.2f}  sv_stk={results_sv['stk'][-1]:.2f}")

    # Wilcoxon paired test: stride_var vs baseline
    stat, pval = sp_stats.wilcoxon(results_base["stk"], results_sv["stk"])

    print(f"\n  Baseline v2 stack: {np.mean(results_base['stk']):.2f} +/- {np.std(results_base['stk']):.2f}")
    print(f"  Stride-var stack:  {np.mean(results_sv['stk']):.2f} +/- {np.std(results_sv['stk']):.2f}")
    print(f"  Delta:             {np.mean(results_base['stk']) - np.mean(results_sv['stk']):+.2f}")
    print(f"  Wilcoxon p-value:  {pval:.4f}")
    print(f"  EXP 1 done in {(time.time() - t0) / 60:.1f}m")

    return {
        "baseline_v2": {
            "lgb": {"mean": round(np.mean(results_base["lgb"]), 3), "std": round(np.std(results_base["lgb"]), 3),
                    "values": [round(v, 3) for v in results_base["lgb"]]},
            "stk": {"mean": round(np.mean(results_base["stk"]), 3), "std": round(np.std(results_base["stk"]), 3),
                    "values": [round(v, 3) for v in results_base["stk"]]},
        },
        "stride_var": {
            "lgb": {"mean": round(np.mean(results_sv["lgb"]), 3), "std": round(np.std(results_sv["lgb"]), 3),
                    "values": [round(v, 3) for v in results_sv["lgb"]]},
            "stk": {"mean": round(np.mean(results_sv["stk"]), 3), "std": round(np.std(results_sv["stk"]), 3),
                    "values": [round(v, 3) for v in results_sv["stk"]]},
        },
        "delta_stk_mean": round(np.mean(results_base["stk"]) - np.mean(results_sv["stk"]), 3),
        "wilcoxon_p": round(pval, 4),
        "n_splits": 10,
        "runtime_s": round(time.time() - t0, 1),
    }


def exp2_pdonly_loocv_imu(df, subjects):
    """PD-only LOOCV without obs_subscore or hy (fair Hssayeni comparison)."""
    print("\n" + "=" * 70)
    print("EXP 2: PD-ONLY LOOCV — IMU-ONLY (no obs_subscore, no hy)")
    print("=" * 70)
    t0 = time.time()

    # IMU-only columns: exclude obs_subscore, hy, and any ground-truth clinical items
    imu_cols = [c for c in df.columns if c not in ("sid", "updrs3", "obs_subscore", "hy")]
    # Also try with stride_var specifically
    base_cols = v2_cols(df)
    sv_cols = [c for c in df.columns if c.startswith("sv_")]
    pa_cols = [c for c in df.columns if c.startswith("pa_")]
    sv_pa_cols = base_cols + sv_cols + pa_cols
    sv_pa_cols = [c for c in sv_pa_cols if c in df.columns]

    pd_sids = [s for s in df["sid"] if subjects.get(s, {}).get("group") == "PD"]
    pd_df = df[df["sid"].isin(pd_sids)].reset_index(drop=True)
    n_pd = len(pd_df)
    print(f"  PD subjects: {n_pd}")
    print(f"  IMU-only features (v2): {len(base_cols)}")
    print(f"  IMU + stride_var + adv_asym: {len(sv_pa_cols)}")

    configs = [
        ("imu_v2", base_cols, 150),
        ("imu_sv_pa", sv_pa_cols, 150),
    ]

    all_results = {}
    for config_name, cols, k in configs:
        cols = [c for c in cols if c in df.columns]
        print(f"\n  --- {config_name} (K={k}, {len(cols)} features) ---")
        loocv_preds, loocv_true = [], []
        for i, sid in enumerate(pd_df["sid"]):
            train_mask = pd_df["sid"] != sid
            Xtr = pd_df.loc[train_mask, cols].values.astype(np.float32)
            ytr = pd_df.loc[train_mask, "updrs3"].values.astype(np.float32)
            Xte = pd_df.loc[~train_mask, cols].values.astype(np.float32)
            yte = pd_df.loc[~train_mask, "updrs3"].values.astype(np.float32)
            k_loo = min(k, Xtr.shape[1])
            si, _ = feature_select(Xtr, ytr, cols, k_loo)
            preds_i = []
            for seed in SEEDS:
                p, _ = train_lgb(Xtr[:, si], ytr, Xte[:, si], seed)
                preds_i.append(np.clip(p, 0, 132))
            loocv_preds.append(float(np.mean(preds_i)))
            loocv_true.append(float(yte[0]))
            if (i + 1) % 20 == 0:
                print(f"    LOOCV {i + 1}/{n_pd}")

        mae = mean_absolute_error(loocv_true, loocv_preds)
        r, _ = sp_stats.pearsonr(loocv_true, loocv_preds)
        print(f"  {config_name}: MAE={mae:.2f} r={r:.3f} (N={n_pd})")

        all_results[config_name] = {
            "mae": round(mae, 3), "r": round(r, 3), "n": n_pd, "k": k,
            "n_features": len(cols),
        }

    print(f"\n  Hssayeni target: MAE=5.95, r=0.74 (N=24, PD-only)")
    print(f"  EXP 2 done in {(time.time() - t0) / 60:.1f}m")

    all_results["runtime_s"] = round(time.time() - t0, 1)
    return all_results


def exp3_combined_sv_pa(df, subjects):
    """Combined stride_var + adv_asym on primary split and 10-split (IMU-only)."""
    print("\n" + "=" * 70)
    print("EXP 3: COMBINED STRIDE_VAR + ADV_ASYM (IMU-only)")
    print("=" * 70)
    t0 = time.time()

    base_cols = v2_cols(df)
    sv_cols = [c for c in df.columns if c.startswith("sv_")]
    pa_cols = [c for c in df.columns if c.startswith("pa_")]
    combined_cols = base_cols + sv_cols + pa_cols
    combined_cols = [c for c in combined_cols if c in df.columns]
    print(f"  Features: {len(base_cols)} v2 + {len(sv_cols)} sv + {len(pa_cols)} pa = {len(combined_cols)} total")

    # Primary split
    split = load_split()
    dev_s, test_s = split["dev_sids"], split["test_sids"]

    print("\n  --- Primary split ---")
    Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, combined_cols)
    primary_lgb = run_eval("comb_lgb", Xd, yd, Xt, yt, combined_cols, k=150)
    primary_stk = run_stack("comb_stk", Xd, yd, Xt, yt, combined_cols, k=150)

    # K sweep
    print("\n  --- K sweep ---")
    k_results = []
    for k in [100, 125, 150, 175, 200]:
        r = run_eval(f"comb_K{k}", Xd, yd, Xt, yt, combined_cols, k=k)
        k_results.append(r)
        r_s = run_stack(f"comb_K{k}_stk", Xd, yd, Xt, yt, combined_cols, k=k)
        k_results.append(r_s)
    best_k_r = min(k_results, key=lambda x: x["ens_mae"])
    print(f"  Best K config: {best_k_r['config']} -> MAE={best_k_r['ens_mae']:.2f}")

    # 10-split validation
    print("\n  --- 10-split validation ---")
    split_maes = {"lgb": [], "stk": []}
    for seed in range(1, 11):
        ds, ts = gen_split(subjects, seed)
        Xd_, yd_, Xt_, yt_ = prep_arrays(df, ds, ts, combined_cols)
        r1 = run_eval(f"comb_val{seed}_lgb", Xd_, yd_, Xt_, yt_, combined_cols, k=150)
        r2 = run_stack(f"comb_val{seed}_stk", Xd_, yd_, Xt_, yt_, combined_cols, k=150)
        split_maes["lgb"].append(r1["ens_mae"])
        split_maes["stk"].append(r2["ens_mae"])
        print(f"  [{seed}/10] lgb={r1['ens_mae']:.2f} stk={r2['ens_mae']:.2f}")

    print(f"\n  10-split LGB: {np.mean(split_maes['lgb']):.2f} +/- {np.std(split_maes['lgb']):.2f}")
    print(f"  10-split STK: {np.mean(split_maes['stk']):.2f} +/- {np.std(split_maes['stk']):.2f}")
    print(f"  EXP 3 done in {(time.time() - t0) / 60:.1f}m")

    return {
        "primary": {"lgb": primary_lgb, "stk": primary_stk},
        "k_results": k_results,
        "split_validation": {
            k: {"mean": round(np.mean(v), 3), "std": round(np.std(v), 3),
                "values": [round(x, 3) for x in v]}
            for k, v in split_maes.items()
        },
        "runtime_s": round(time.time() - t0, 1),
    }


def main():
    t0 = time.time()
    subjects = parse_clinical()
    df = load_features()
    print(f"Loaded features: {df.shape[0]} subjects x {df.shape[1]} columns")

    results = {}

    results["exp1_stride_var_10split"] = exp1_stride_var_10split(df, subjects)
    results["exp2_pdonly_loocv_imu"] = exp2_pdonly_loocv_imu(df, subjects)
    results["exp3_combined_sv_pa"] = exp3_combined_sv_pa(df, subjects)

    results["total_runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("followup_v3_results.json", results)

    print("\n" + "=" * 70)
    print("ALL FOLLOW-UP EXPERIMENTS COMPLETE")
    print("=" * 70)
    print(f"Total runtime: {(time.time() - t0) / 60:.1f}m")
    print(f"Results: results/followup_v3_results.json")

    # Summary
    e1 = results["exp1_stride_var_10split"]
    e2 = results["exp2_pdonly_loocv_imu"]
    e3 = results["exp3_combined_sv_pa"]
    print(f"\n  EXP 1: stride_var 10-split stack = {e1['stride_var']['stk']['mean']:.2f} +/- {e1['stride_var']['stk']['std']:.2f}"
          f" (baseline {e1['baseline_v2']['stk']['mean']:.2f} +/- {e1['baseline_v2']['stk']['std']:.2f})"
          f" delta={e1['delta_stk_mean']:+.2f} p={e1['wilcoxon_p']:.4f}")
    for k, v in e2.items():
        if isinstance(v, dict) and "mae" in v:
            print(f"  EXP 2: {k} LOOCV MAE={v['mae']:.2f} r={v['r']:.3f} (Hssayeni: 5.95)")
    print(f"  EXP 3: combined sv+pa 10-split stack = {e3['split_validation']['stk']['mean']:.2f}"
          f" +/- {e3['split_validation']['stk']['std']:.2f}")


if __name__ == "__main__":
    main()
