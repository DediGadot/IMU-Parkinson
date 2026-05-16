#!/usr/bin/env python3
"""Feasible strict 5-fold null checks for high-impact T1 v5 components.

This is a retraining audit, but intentionally limited to 5-fold / one seed so it is
tractable locally. It implements stricter variants than several historical scripts:

- Scrambled labels: train on permuted training labels, score against the ORIGINAL
  held-out labels.
- True test-only canary: append a feature that is 0 in training rows and 999 in
  held-out rows inside each fold; record whether Pearson top-K selected it.
- Feature/SID shuffle: shuffle source feature rows before fold training and score
  against original labels. This is a proxy for cache-join sensitivity; it is not a
  full pre-cache reload audit.

Output: results/iter13_t1_v5_component_strict_nulls_5fold.json
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR
from run_per_item_v2 import load_data, get_item_features, kfold_split_stratified, impute_fold, train_lgb
from run_per_item_ccc_v2 import train_lgb_ccc_v2
from lgb_ccc_objective_v2 import pearson_select_features
from run_t1_iter6_lockbox_loocv import load_tug_features_for_fold
from run_t1_iter4 import get_hy_features
from run_self_norm_cross import SELFNORM_CACHE, load_subject_aligned_cache
from sklearn.linear_model import Ridge

OUT = RESULTS_DIR / "iter13_t1_v5_component_strict_nulls_5fold.json"
DEFAULT_SEEDS = (42,)
K = 500


def configured_seeds() -> list[int]:
    raw = os.environ.get("PD_IMU_STRICT_NULL_SEEDS", "")
    if not raw.strip():
        return list(DEFAULT_SEEDS)
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def sha_array(a: np.ndarray) -> str:
    aa = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(aa.shape).encode())
    h.update(str(aa.dtype).encode())
    h.update(aa.tobytes())
    return h.hexdigest()


def select_with_canary_tracking(Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray, *, canary_col: int | None) -> tuple[np.ndarray, np.ndarray, bool]:
    if Xtr.shape[1] <= K:
        selected = np.arange(Xtr.shape[1])
    else:
        selected = pearson_select_features(Xtr, ytr, k=K)
    return Xtr[:, selected], Xte[:, selected], bool(canary_col is not None and canary_col in set(selected.tolist()))


def item12_item_plus_v2_cccv2(d: dict[str, Any], *, mode: str, seed: int, rng: np.random.Generator) -> dict[str, Any]:
    item = 12
    y = np.asarray(d["items"][item], dtype=float)
    X_item, cols = get_item_features(d, item)
    X_aug = np.hstack([d["X_v2"], X_item]) if cols else d["X_v2"]
    if mode == "feature_row_shuffle":
        X_aug = X_aug[rng.permutation(len(y))]
    y_train_base = y.copy()
    if mode == "scrambled_train_labels":
        y_train_base = rng.permutation(y_train_base)
    splits = kfold_split_stratified(y, 5, seed=seed)
    oof = np.zeros(len(y), dtype=float)
    canary_selected = []
    for tr, te in splits:
        Xtr_raw, Xte_raw = X_aug[tr], X_aug[te]
        canary_col = None
        if mode == "true_test_only_canary":
            canary_col = Xtr_raw.shape[1]
            Xtr_raw = np.hstack([Xtr_raw, np.zeros((len(tr), 1))])
            Xte_raw = np.hstack([Xte_raw, np.full((len(te), 1), 999.0)])
        Xtr, Xte = impute_fold(Xtr_raw, Xte_raw)
        Xtr, Xte, selected = select_with_canary_tracking(Xtr, y_train_base[tr], Xte, canary_col=canary_col)
        canary_selected.append(selected)
        oof[te] = train_lgb_ccc_v2(Xtr, y_train_base[tr], Xte, seed)
    return {
        "item": item,
        "variant": "item_plus_v2_cccv2",
        "mode": mode,
        "metric_vs_original_labels": full_metrics(y, oof),
        "prediction_sha256": sha_array(oof),
        "canary_selected_any_fold": bool(any(canary_selected)),
        "canary_selected_by_fold": canary_selected,
    }


def item14_iter6_v2_tug(d: dict[str, Any], *, mode: str, seed: int, rng: np.random.Generator) -> dict[str, Any]:
    item = 14
    y = np.asarray(d["items"][item], dtype=float)
    X_tug = load_tug_features_for_fold(d["sids"])
    X_aug = np.hstack([d["X_v2"], X_tug])
    if mode == "feature_row_shuffle":
        X_aug = X_aug[rng.permutation(len(y))]
    y_train_base = y.copy()
    if mode == "scrambled_train_labels":
        y_train_base = rng.permutation(y_train_base)
    splits = kfold_split_stratified(y, 5, seed=seed)
    oof = np.zeros(len(y), dtype=float)
    canary_selected = []
    for tr, te in splits:
        Xtr_raw, Xte_raw = X_aug[tr], X_aug[te]
        canary_col = None
        if mode == "true_test_only_canary":
            canary_col = Xtr_raw.shape[1]
            Xtr_raw = np.hstack([Xtr_raw, np.zeros((len(tr), 1))])
            Xte_raw = np.hstack([Xte_raw, np.full((len(te), 1), 999.0)])
        Xtr, Xte = impute_fold(Xtr_raw, Xte_raw)
        Xtr, Xte, selected = select_with_canary_tracking(Xtr, y_train_base[tr], Xte, canary_col=canary_col)
        canary_selected.append(selected)
        oof[te] = train_lgb(Xtr, y_train_base[tr], Xte, seed)
    return {
        "item": item,
        "variant": "iter6_v2_plus_tug",
        "mode": mode,
        "metric_vs_original_labels": full_metrics(y, oof),
        "prediction_sha256": sha_array(oof),
        "canary_selected_any_fold": bool(any(canary_selected)),
        "canary_selected_by_fold": canary_selected,
    }


def item10_self_norm_hy_residual(d: dict[str, Any], *, mode: str, seed: int, rng: np.random.Generator) -> dict[str, Any]:
    """Strict 5-fold audit for the new high-impact iter11 item-10 T1 v5 component.

    Historical self-norm nulls used a random canary and scored scrambled-label runs
    against scrambled labels. This mirrors the locked self_norm_hy_residual shape but
    uses stricter controls: train-label permutation scored against original held-out
    labels, a true test-only canary, and feature-row shuffle of the V2+selfnorm block
    while leaving the clinical H&Y stage-1 baseline aligned and labelled as such.
    """
    item = 10
    y = np.asarray(d["items"][item], dtype=float)
    X_selfnorm, _ = load_subject_aligned_cache(SELFNORM_CACHE, [str(s) for s in d["sids"]])
    X_aug = np.hstack([d["X_v2"], X_selfnorm])
    if mode == "feature_row_shuffle":
        X_aug = X_aug[rng.permutation(len(y))]
    y_train_base = y.copy()
    if mode == "scrambled_train_labels":
        y_train_base = rng.permutation(y_train_base)
    hy_feat = get_hy_features(d["hy"])
    splits = kfold_split_stratified(y, 5, seed=seed)
    oof = np.zeros(len(y), dtype=float)
    canary_selected = []
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y_train_base[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        residual_tr = y_train_base[tr] - s1_tr
        Xtr_raw, Xte_raw = X_aug[tr], X_aug[te]
        canary_col = None
        if mode == "true_test_only_canary":
            canary_col = Xtr_raw.shape[1]
            Xtr_raw = np.hstack([Xtr_raw, np.zeros((len(tr), 1))])
            Xte_raw = np.hstack([Xte_raw, np.full((len(te), 1), 999.0)])
        Xtr, Xte = impute_fold(Xtr_raw, Xte_raw)
        Xtr, Xte, selected = select_with_canary_tracking(Xtr, residual_tr, Xte, canary_col=canary_col)
        canary_selected.append(selected)
        oof[te] = s1_te + train_lgb(Xtr, residual_tr, Xte, seed)
    return {
        "item": item,
        "variant": "self_norm_hy_residual",
        "mode": mode,
        "metric_vs_original_labels": full_metrics(y, oof),
        "prediction_sha256": sha_array(oof),
        "canary_selected_any_fold": bool(any(canary_selected)),
        "canary_selected_by_fold": canary_selected,
        "feature_row_shuffle_note": "H&Y stage-1 baseline remains aligned; pass criterion is no improvement over baseline, not full collapse.",
    }


def summarize_pass_fail(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for r in rows:
        key = f"seed{r['seed']}_item{r['item']}_{r['mode']}"
        ccc = r["metric_vs_original_labels"]["ccc"]
        if r["mode"] == "baseline_retrain_5fold":
            passed = ccc > 0.20  # sanity only, should retain some signal in 5-fold
        elif r["mode"] == "true_test_only_canary":
            passed = (not r["canary_selected_any_fold"])  # performance may match baseline if ignored
        elif r["mode"] == "feature_row_shuffle" and r["variant"] == "self_norm_hy_residual":
            baseline = next(
                x["metric_vs_original_labels"]["ccc"]
                for x in rows
                if x["seed"] == r["seed"] and x["item"] == r["item"] and x["mode"] == "baseline_retrain_5fold"
            )
            passed = ccc <= baseline + 0.01  # aligned H&Y stage-1 may preserve signal; shuffled IMU/selfnorm must not improve
        else:
            passed = abs(ccc) < 0.20
        out[key] = {"passed": bool(passed), "ccc": ccc, "note": "5-fold strict retraining audit; not LOOCV final certification"}
    return out


def summarize_repeated_seed_nulls(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for item in sorted({r["item"] for r in rows}):
        for mode in sorted({r["mode"] for r in rows if r["item"] == item}):
            vals = [r["metric_vs_original_labels"]["ccc"] for r in rows if r["item"] == item and r["mode"] == mode]
            summary[f"item{item}_{mode}"] = {
                "n_seeds": len(vals),
                "mean_ccc": float(np.mean(vals)),
                "max_abs_ccc": float(np.max(np.abs(vals))),
                "min_ccc": float(np.min(vals)),
                "max_ccc": float(np.max(vals)),
            }
    return summary


def main() -> None:
    d = load_data()
    rows = []
    seeds = configured_seeds()
    for seed in seeds:
        for fn in [item10_self_norm_hy_residual, item12_item_plus_v2_cccv2, item14_iter6_v2_tug]:
            for mode in ["baseline_retrain_5fold", "scrambled_train_labels", "true_test_only_canary", "feature_row_shuffle"]:
                print(f"Running seed={seed} {fn.__name__} mode={mode}", flush=True)
                row = fn(d, mode=mode, seed=seed, rng=np.random.default_rng(seed))
                row["seed"] = seed
                rows.append(row)
    out = {
        "audit_version": "strict_component_nulls_5fold_v2_repeated_seed_optional",
        "seeds": seeds,
        "scope": "Feasible retraining null checks for high-impact T1 v5 components item10, item12, and item14.",
        "limitations": [
            "5-fold audit, not final LOOCV.",
            "feature_row_shuffle is a proxy for cache/SID-join sensitivity, not a full raw-cache reload with SID permutation.",
            "Item10 self_norm_hy_residual is now included because it is a high-impact T1 v5 component and historical self-norm nulls were weaker.",
        ],
        "results": rows,
        "pass_fail_summary": summarize_pass_fail(rows),
        "repeated_seed_summary": summarize_repeated_seed_nulls(rows),
    }
    with OUT.open("w") as f:
        json.dump(out, f, indent=2, default=lambda o: float(o) if isinstance(o, np.floating) else int(o) if isinstance(o, np.integer) else str(o))
    print(json.dumps({"wrote": str(OUT), "repeated_seed_summary": out["repeated_seed_summary"], "pass_fail_summary": out["pass_fail_summary"]}, indent=2))


if __name__ == "__main__":
    main()
