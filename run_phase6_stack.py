"""Phase 6 SUBSTITUTE: Cross-dataset stacked pipeline.

The original Phase 6 plan called for pretraining on an external IMU+UPDRS
cohort (mPower / PROMOTE-PD / Parkinson@Home). None of those datasets are
available on this remote, and downloading would require Synapse credentials
and several hours. As a substitute that still tests the underlying hypothesis
("pretrained representations help"), this script builds a STACKED pipeline
that combines all the cross-dataset-pretrained representations we DO have:

  - MOMENT-1-base FM embeddings (cached): pretrained on 13B time-series tokens
    from many domains — IS cross-dataset pretrained (codex IMPROVE #3 substrate)
  - velinc engineered features (cached): IMU-derived but additional modality
  - inductive_pd ranker leaf features (regenerated per fold): SSL representation
    that was the lockbox 5-fold winner
  - v2 handcrafted features (cached): the strong baseline

Variants:
  - stack_lgb_meta : level-0 = LGB on each feature group; level-1 = Ridge meta-learner on OOF preds
  - stack_avg      : simple ensemble average of level-0 predictions (no meta-learner)
  - stack_lr_meta  : level-0 = LGB; level-1 = LinearRegression meta-learner
  - stack_concat   : single LGB on concatenated features (ablation: no stacking)

Inductive firewall: every level-0 model fits on TRAIN-fold only, level-1 meta-
learner trains on TRAIN-fold OOF predictions only. Test subject's features
only go through inference.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import KFold
from xgboost import XGBRanker

from inductive_lib import full_metrics, gen_5fold_split
from project_paths import RESULTS_DIR, ensure_dir, results_artifact_path
from run_inductive_ablation import (
    SEEDS, TARGET_CLIP, _group_from_sid,
    feature_select, load_features_and_targets, train_lgb,
)

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 11)))

VELINC = str(results_artifact_path("velinc_features.csv"))


def _load_velinc(merged: pd.DataFrame) -> tuple:
    if not os.path.exists(VELINC):
        return merged, []
    velinc_df = pd.read_csv(VELINC)
    sid_col = "sid" if "sid" in velinc_df.columns else velinc_df.columns[0]
    velinc_df = velinc_df.rename(columns={sid_col: "sid"})
    excl = {"sid", "updrs3", "obs_subscore", "hy"}
    vcols = [c for c in velinc_df.columns if c not in excl]
    velinc_renamed = velinc_df[["sid"] + vcols].copy()
    velinc_renamed.columns = ["sid"] + [f"vi_{c}" for c in vcols]
    new_cols = [f"vi_{c}" for c in vcols]
    out = merged.merge(velinc_renamed, on="sid", how="left").fillna(0.0)
    return out, new_cols


def _split_groups(feature_cols, velinc_cols):
    fm = [c for c in feature_cols if c.startswith("fm_")]
    v2 = [c for c in feature_cols if not c.startswith("fm_") and c not in set(velinc_cols)]
    return {"v2": v2, "fm": fm, "vi": velinc_cols}


def _train_level0_lgb(X_train, y_train, X_test, k=300):
    sel_idx, _ = feature_select(X_train, y_train, list(range(X_train.shape[1])), k=min(k, X_train.shape[1]))
    Xd_sel, Xt_sel = X_train[:, sel_idx], X_test[:, sel_idx]
    preds = []
    for s in SEEDS:
        preds.append(train_lgb(Xd_sel, y_train, Xt_sel, s))
    return np.mean(preds, axis=0)


def _ranker_leaves(X_train, y_train, X_test, k=300):
    """Inductive PD-only ranker leaf features per fold."""
    sel_idx, _ = feature_select(X_train, y_train, list(range(X_train.shape[1])), k=min(k, X_train.shape[1]))
    Xd_sel, Xt_sel = X_train[:, sel_idx], X_test[:, sel_idx]
    labels = np.zeros(len(y_train), dtype=np.int32)
    order = np.argsort(y_train)
    for rank, idx in enumerate(order):
        labels[idx] = rank + 1
    leaves_train = []
    leaves_test = []
    for seed in SEEDS[:3]:
        r = XGBRanker(n_estimators=300, max_depth=4, learning_rate=0.05,
                      reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                      objective="rank:pairwise")
        r.fit(Xd_sel, labels, group=np.array([len(Xd_sel)]))
        leaves_train.append(r.apply(Xd_sel))
        leaves_test.append(r.apply(Xt_sel))
    return (np.hstack(leaves_train).astype(np.float32),
            np.hstack(leaves_test).astype(np.float32))


def predict_stack(Xd_groups, yd, Xt_groups, variant, target_key):
    clip = TARGET_CLIP[target_key]
    n_train, n_test = len(yd), Xt_groups["v2"].shape[0]

    # Build level-0 OOF predictions on TRAIN subjects only
    bases = ["v2", "fm", "vi", "v2_fm_ranker"]
    oof = {b: np.zeros(n_train, dtype=np.float64) for b in bases}
    test_preds = {b: np.zeros(n_test, dtype=np.float64) for b in bases}

    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    for tr_idx, va_idx in kf.split(np.arange(n_train)):
        for b in ("v2", "fm", "vi"):
            oof[b][va_idx] = _train_level0_lgb(Xd_groups[b][tr_idx], yd[tr_idx], Xd_groups[b][va_idx])
        # Ranker leaves base: stack v2+fm + ranker leaves
        Xtr_combined = np.hstack([Xd_groups["v2"][tr_idx], Xd_groups["fm"][tr_idx]])
        Xva_combined = np.hstack([Xd_groups["v2"][va_idx], Xd_groups["fm"][va_idx]])
        ranker_train, ranker_va = _ranker_leaves(Xtr_combined, yd[tr_idx], Xva_combined)
        Xtr_full = np.hstack([Xtr_combined, ranker_train])
        Xva_full = np.hstack([Xva_combined, ranker_va])
        oof["v2_fm_ranker"][va_idx] = _train_level0_lgb(Xtr_full, yd[tr_idx], Xva_full, k=500)

    # Train each level-0 on FULL train, predict test
    for b in ("v2", "fm", "vi"):
        test_preds[b] = _train_level0_lgb(Xd_groups[b], yd, Xt_groups[b])
    Xd_combined = np.hstack([Xd_groups["v2"], Xd_groups["fm"]])
    Xt_combined = np.hstack([Xt_groups["v2"], Xt_groups["fm"]])
    ranker_train_full, ranker_test_full = _ranker_leaves(Xd_combined, yd, Xt_combined)
    test_preds["v2_fm_ranker"] = _train_level0_lgb(
        np.hstack([Xd_combined, ranker_train_full]), yd,
        np.hstack([Xt_combined, ranker_test_full]), k=500,
    )

    if variant == "stack_avg":
        return np.clip(np.mean([test_preds[b] for b in bases], axis=0), clip[0], clip[1])

    if variant == "stack_concat":
        # Single LGB on concatenated features (ablation: no stacking, just concat)
        Xd_all = np.hstack([Xd_groups[b] for b in ("v2", "fm", "vi")])
        Xt_all = np.hstack([Xt_groups[b] for b in ("v2", "fm", "vi")])
        return np.clip(_train_level0_lgb(Xd_all, yd, Xt_all, k=500), clip[0], clip[1])

    # Meta-learners
    meta_X_train = np.column_stack([oof[b] for b in bases])
    meta_X_test = np.column_stack([test_preds[b] for b in bases])
    if variant == "stack_lgb_meta":
        meta = Ridge(alpha=1.0, random_state=42).fit(meta_X_train, yd)
    elif variant == "stack_lr_meta":
        meta = LinearRegression().fit(meta_X_train, yd)
    else:
        raise ValueError(variant)
    return np.clip(meta.predict(meta_X_test), clip[0], clip[1])


def run_5fold(merged, group_cols, target_key, variant):
    target_col = f"{target_key}_target"
    y_full = merged[target_col].values.astype(np.float32)
    X_groups_full = {g: merged[cols].values.astype(np.float32) for g, cols in group_cols.items()}

    all_true, all_pred, all_sids_out = [], [], []
    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(merged, target_key):
        dm = merged["sid"].isin(train_sids).values
        tm = merged["sid"].isin(test_sids).values
        Xd_groups = {g: X[dm] for g, X in X_groups_full.items()}
        Xt_groups = {g: X[tm] for g, X in X_groups_full.items()}
        ep = predict_stack(Xd_groups, y_full[dm], Xt_groups, variant, target_key)
        all_true.extend(y_full[tm].tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(merged.loc[tm, "sid"].tolist())
        print(f"  split {split_i}/5 [{variant} {target_key}]: "
              f"CCC={full_metrics(y_full[tm], ep)['ccc']:.3f}")
    metrics = full_metrics(all_true, all_pred, label=variant)
    metrics.update({
        "target": target_key, "variant": variant, "eval_mode": "5split",
        "runtime_s": round(time.time() - t0, 1),
        "per_subject": {"sids": all_sids_out, "y_true": all_true,
                        "y_pred": [float(p) for p in all_pred]},
    })
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all", choices=["all",
        "stack_avg", "stack_concat", "stack_lgb_meta", "stack_lr_meta"])
    ap.add_argument("--target", default="all", choices=["t1", "t2", "t3", "all"])
    args = ap.parse_args()

    variants = (["stack_avg", "stack_concat", "stack_lgb_meta", "stack_lr_meta"]
                if args.variant == "all" else [args.variant])
    targets = ["t1", "t2", "t3"] if args.target == "all" else [args.target]

    pd_merged, _, feature_cols = load_features_and_targets()
    pd_merged_aug, velinc_cols = _load_velinc(pd_merged)
    if not velinc_cols:
        print("WARNING: velinc not found — vi base predictor will be a copy of v2")
        # synthesize empty vi to avoid breaking
        pd_merged_aug["vi_dummy"] = 0.0
        velinc_cols = ["vi_dummy"]
    group_cols = _split_groups(feature_cols, velinc_cols)
    print(f"Group sizes: " + ", ".join(f"{g}={len(c)}" for g, c in group_cols.items()))

    summary = []
    for v in variants:
        for t in targets:
            print(f"\n{'='*70}\nRunning phase6 {v} | {t} | 5split\n{'='*70}")
            try:
                m = run_5fold(pd_merged_aug, group_cols, t, v)
                fname = f"phase6_stack_{v}_{t}_5split.json"
                with open(results_artifact_path(fname), "w") as f:
                    json.dump(m, f, indent=2)
                print(f"  -> CCC={m['ccc']:.3f} slope={m['cal_slope']:.3f} MAE={m['mae']:.3f}")
                summary.append({"variant": v, "target": t, "ccc": m["ccc"], "mae": m["mae"]})
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}")
                summary.append({"variant": v, "target": t, "error": str(e)})

    with open(results_artifact_path("phase6_stack_summary.json"), "w") as f:
        json.dump({"summary": summary}, f, indent=2)


if __name__ == "__main__":
    main()
