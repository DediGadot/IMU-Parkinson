"""Phase 4 SUBSTITUTE: Privileged distillation with what's actually available.

The walkway feature cache (135/178 subjects) is not available locally or on
the GPU server — Synapse data download was not run in this environment.
As a substitute that still tests the privileged-distillation hypothesis:

  Teacher: trained on v2 + FM + velinc features (the "richest" feature set we
           do have cached) — velinc is derived from IMU but represents an
           additional engineered modality not in v2.
  Student: IMU-only with restricted feature set (v2 alone, or v2+FM).
  Distillation: teacher's per-fold predictions on TRAIN subjects act as soft
                targets for the student; student loss = α·MSE(y_student, y_true)
                + (1-α)·MSE(y_student, y_teacher).

Inductive firewall:
  - Teacher fits on TRAIN-fold subjects only.
  - Teacher predicts on TRAIN-fold subjects (out-of-fold via inner KFold) for
    the soft-target signal — never on outer-test.
  - Student fits on TRAIN-fold + soft targets, predicts test subject.

Variants:
  - student_v2_no_kd      : student v2-only, no distillation (CONTROL — codex #6)
  - student_v2_kd_a05     : student v2-only, α=0.5
  - student_v2_kd_a02     : student v2-only, α=0.2 (more weight to teacher)
  - teacher_only          : teacher reported directly on test (multi-modal upper bound)
  - student_vfm_kd_a05    : student v2+FM, α=0.5 (sanity)
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

from sklearn.model_selection import KFold

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


def _split_feature_groups(feature_cols: list, velinc_cols: list) -> dict:
    fm = [c for c in feature_cols if c.startswith("fm_")]
    v2 = [c for c in feature_cols if not c.startswith("fm_") and c not in set(velinc_cols)]
    return {"v2": v2, "fm": fm, "vi": velinc_cols, "v2_fm": v2 + fm,
            "v2_fm_vi": v2 + fm + velinc_cols, "v2_only": v2, "v2_vi": v2 + velinc_cols}


def _train_predict(X_train, y_train, X_test, k=300, soft_y=None, alpha=1.0):
    """LGB ensemble. If soft_y given, train on alpha*y_true + (1-alpha)*soft_y."""
    sel_idx, _ = feature_select(X_train, y_train, list(range(X_train.shape[1])), k=min(k, X_train.shape[1]))
    Xd_sel = X_train[:, sel_idx]
    Xt_sel = X_test[:, sel_idx]
    target = y_train if soft_y is None else (alpha * y_train + (1 - alpha) * soft_y)
    preds = []
    for s in SEEDS:
        preds.append(train_lgb(Xd_sel, target, Xt_sel, s))
    return np.mean(preds, axis=0)


def _fit_teacher_inner_oof(Xd_full, yd, n_splits=5):
    """Out-of-fold teacher predictions on TRAIN subjects for distillation soft targets."""
    n = len(yd)
    soft = np.zeros(n, dtype=np.float64)
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    for tr_idx, va_idx in kf.split(np.arange(n)):
        soft[va_idx] = _train_predict(Xd_full[tr_idx], yd[tr_idx], Xd_full[va_idx], k=500)
    return soft


def predict_distill(
    Xd_groups: dict, yd: np.ndarray, Xt_groups: dict, variant: str, target_key: str,
):
    clip = TARGET_CLIP[target_key]

    if variant == "teacher_only":
        # Multi-modal upper bound — codex #6 control
        Xd = np.hstack([Xd_groups[g] for g in ("v2", "fm", "vi")])
        Xt = np.hstack([Xt_groups[g] for g in ("v2", "fm", "vi")])
        return np.clip(_train_predict(Xd, yd, Xt, k=500), clip[0], clip[1])

    if variant == "student_v2_no_kd":
        # Student-without-KD — codex #6 control
        return np.clip(_train_predict(Xd_groups["v2"], yd, Xt_groups["v2"], k=300), clip[0], clip[1])

    if variant == "student_vfm_no_kd":
        # Sanity control: same as B3
        return np.clip(_train_predict(Xd_groups["v2_fm"], yd, Xt_groups["v2_fm"], k=500), clip[0], clip[1])

    # KD variants
    alpha = {"student_v2_kd_a05": 0.5, "student_v2_kd_a02": 0.2,
             "student_vfm_kd_a05": 0.5, "student_vfm_kd_a02": 0.2}[variant]

    Xd_teacher = np.hstack([Xd_groups[g] for g in ("v2", "fm", "vi")])
    soft = _fit_teacher_inner_oof(Xd_teacher, yd, n_splits=5)

    student_feat = "v2" if variant.startswith("student_v2_") else "v2_fm"
    Xd_student = Xd_groups[student_feat]
    Xt_student = Xt_groups[student_feat]
    return np.clip(_train_predict(Xd_student, yd, Xt_student,
                                   k=300 if student_feat == "v2" else 500,
                                   soft_y=soft, alpha=alpha), clip[0], clip[1])


def run_5fold(merged: pd.DataFrame, group_cols: dict, target_key: str, variant: str) -> dict:
    target_col = f"{target_key}_target"
    y_full = merged[target_col].values.astype(np.float32)
    sids = merged["sid"].values

    # Pre-extract group matrices
    X_groups_full = {g: merged[cols].values.astype(np.float32) for g, cols in group_cols.items()}

    all_true, all_pred, all_sids_out = [], [], []
    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(merged, target_key):
        dm = merged["sid"].isin(train_sids).values
        tm = merged["sid"].isin(test_sids).values
        Xd_groups = {g: X[dm] for g, X in X_groups_full.items()}
        Xt_groups = {g: X[tm] for g, X in X_groups_full.items()}
        ep = predict_distill(Xd_groups, y_full[dm], Xt_groups, variant, target_key)
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
        "teacher_only", "student_v2_no_kd", "student_vfm_no_kd",
        "student_v2_kd_a05", "student_v2_kd_a02",
        "student_vfm_kd_a05", "student_vfm_kd_a02",
    ])
    ap.add_argument("--target", default="all", choices=["t1", "t2", "t3", "all"])
    args = ap.parse_args()

    variants = (["teacher_only", "student_v2_no_kd", "student_vfm_no_kd",
                 "student_v2_kd_a05", "student_v2_kd_a02",
                 "student_vfm_kd_a05", "student_vfm_kd_a02"]
                if args.variant == "all" else [args.variant])
    targets = ["t1", "t2", "t3"] if args.target == "all" else [args.target]

    pd_merged, _, feature_cols = load_features_and_targets()
    pd_merged_aug, velinc_cols = _load_velinc(pd_merged)
    if not velinc_cols:
        print("WARNING: velinc features not found — distillation collapses to base model")
    group_cols = _split_feature_groups(feature_cols, velinc_cols)
    print(f"Group sizes: " + ", ".join(f"{g}={len(c)}" for g, c in group_cols.items()))

    summary = []
    for v in variants:
        for t in targets:
            print(f"\n{'='*70}\nRunning phase4 {v} | {t} | 5split\n{'='*70}")
            try:
                m = run_5fold(pd_merged_aug, group_cols, t, v)
                fname = f"phase4_distill_{v}_{t}_5split.json"
                with open(results_artifact_path(fname), "w") as f:
                    json.dump(m, f, indent=2)
                print(f"  -> CCC={m['ccc']:.3f} slope={m['cal_slope']:.3f} MAE={m['mae']:.3f}")
                summary.append({"variant": v, "target": t, "ccc": m["ccc"], "mae": m["mae"]})
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}")
                summary.append({"variant": v, "target": t, "error": str(e)})

    with open(results_artifact_path("phase4_distill_summary.json"), "w") as f:
        json.dump({"summary": summary}, f, indent=2)


if __name__ == "__main__":
    main()
