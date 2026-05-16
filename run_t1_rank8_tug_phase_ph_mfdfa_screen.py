#!/usr/bin/env python3
"""Screen `/tmp/pro-results.txt` rank #8: TUG phase-specific PH/MFDFA.

This is screen-only. It uses the target-free cache from
`cache_tug_phase_ph_mfdfa.py` and tests whether phase-localized topology /
fractal features can correct iter34 T1 item residuals enough to promote a
single future LOOCV lockbox.

Promotion policy:
  - 5-fold ensemble delta CCC >= +0.025
  - paired-bootstrap frac(delta>0) >= 0.95
  - seed delta std < 0.020
  - no material MAE degradation

No LOOCV is run by this script.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from eval_utils import lins_ccc as ccc
from inductive_lib import FoldImputer, FoldNormalizer


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
ITER34_OOF = RESULTS / "t1_iter34_per_item_oof_20260511_044242.npz"
PREREG_MASTER = RESULTS / "preregistration_t1t3_proresults_ablation_20260515T133800Z.json"

SEEDS = (42, 1337, 7)
N_SPLITS = 5
RIDGE_ALPHA = 100.0
N_BOOT = 2000
BOOT_SEED = 20260515

PROMOTION_DELTA = 0.025
PROMOTION_FRAC_POS = 0.95
PROMOTION_SEED_STD_MAX = 0.020
MAE_DEGRADATION_MAX = 0.025


@dataclass(frozen=True)
class ItemFeatureSpec:
    item: int
    family: str
    phases: tuple[str, ...]


@dataclass(frozen=True)
class ArmSpec:
    name: str
    item_specs: tuple[ItemFeatureSpec, ...]


PRIMARY_ARM = ArmSpec(
    name="primary_nonretracted_item12_mfdfa_item13_ph",
    item_specs=(
        ItemFeatureSpec(12, "mfdfa", ("turning", "turn_to_sit")),
        ItemFeatureSpec(13, "ph", ("sit_to_stand", "steady_walk")),
    ),
)

FULL_RANK8_ARM = ArmSpec(
    name="full_rank8_item10_12_mfdfa_item13_14_ph",
    item_specs=(
        ItemFeatureSpec(10, "mfdfa", ("steady_walk", "turning")),
        ItemFeatureSpec(12, "mfdfa", ("turning", "turn_to_sit")),
        ItemFeatureSpec(13, "ph", ("sit_to_stand", "steady_walk")),
        ItemFeatureSpec(14, "ph", ("sit_to_stand", "turning", "turn_to_sit")),
    ),
)

ARMS = (PRIMARY_ARM, FULL_RANK8_ARM)


def latest_phase_cache() -> Path:
    matches = sorted(RESULTS.glob("cache_tug_phase_ph_mfdfa_*.csv"), key=lambda p: p.stat().st_mtime)
    if not matches:
        raise FileNotFoundError("No results/cache_tug_phase_ph_mfdfa_*.csv found")
    return matches[-1]


def load_manifest(cache_path: Path) -> dict:
    manifest_path = cache_path.with_suffix(cache_path.suffix + ".manifest.json")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest for {cache_path}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("labels_used") is not False:
        raise ValueError(f"Phase cache labels_used is not false: {manifest_path}")
    if manifest.get("leakage_status") != "clean_by_construction":
        raise ValueError(f"Phase cache leakage_status is not clean: {manifest_path}")
    return manifest


def load_aligned() -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]], pd.DataFrame, Path, dict]:
    oof = dict(np.load(ITER34_OOF, allow_pickle=True))
    sids = oof["sids"].astype(str)
    y_t1 = oof["y_t1"].astype(float)
    pred = oof["t1_sum_pred"].astype(float)
    items: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for item in range(9, 15):
        items[item] = (
            oof[f"item_{item}_true"].astype(float),
            oof[f"item_{item}_pred"].astype(float),
        )

    cache = latest_phase_cache()
    manifest = load_manifest(cache)
    df = pd.read_csv(cache)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    missing = [str(s) for s in sids if s not in sid_to_row]
    rows = []
    for sid in sids:
        if sid in sid_to_row:
            rows.append(df.iloc[sid_to_row[sid]].to_dict())
        else:
            row = {c: np.nan for c in df.columns}
            row["sid"] = sid
            rows.append(row)
    df = pd.DataFrame(rows, columns=df.columns).reset_index(drop=True)
    if not np.array_equal(df["sid"].astype(str).values, sids):
        raise AssertionError("SID alignment failed")
    manifest = dict(manifest)
    manifest["screen_alignment_missing_sids_imputed_foldlocally"] = missing
    return sids, y_t1, pred, items, df, cache, manifest


def family_cols(df: pd.DataFrame, spec: ItemFeatureSpec) -> list[str]:
    cols: list[str] = []
    for phase in spec.phases:
        prefix = f"phase_{phase}_"
        for col in df.columns:
            if col == "sid" or not col.startswith(prefix):
                continue
            if spec.family == "ph" and "_ph_" in col:
                cols.append(col)
            elif spec.family == "mfdfa" and "_mfdfa_" in col:
                cols.append(col)
    return sorted(set(cols))


def fold_correct(
    X_raw: np.ndarray,
    resid: np.ndarray,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
) -> np.ndarray:
    imp = FoldImputer.fit(X_raw[train_idx])
    X_train = imp.transform(X_raw[train_idx])
    X_test = imp.transform(X_raw[test_idx])
    norm = FoldNormalizer.fit(X_train)
    X_train = norm.transform(X_train)
    X_test = norm.transform(X_test)
    model = Ridge(alpha=RIDGE_ALPHA)
    model.fit(X_train, resid[train_idx])
    return model.predict(X_test)


def metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    return {
        "ccc": float(ccc(y, pred)),
        "mae": float(np.mean(np.abs(y - pred))),
        "pred_std": float(np.std(pred)),
        "pred_mean": float(np.mean(pred)),
    }


def paired_bootstrap(y: np.ndarray, base: np.ndarray, candidate: np.ndarray) -> dict:
    rng = np.random.default_rng(BOOT_SEED)
    n = len(y)
    deltas = np.empty(N_BOOT, dtype=float)
    for i in range(N_BOOT):
        idx = rng.integers(0, n, size=n)
        deltas[i] = float(ccc(y[idx], candidate[idx]) - ccc(y[idx], base[idx]))
    return {
        "n_boot": N_BOOT,
        "median_delta": round(float(np.median(deltas)), 6),
        "ci95": [
            round(float(np.percentile(deltas, 2.5)), 6),
            round(float(np.percentile(deltas, 97.5)), 6),
        ],
        "frac_positive": round(float((deltas > 0).mean()), 4),
    }


def run_arm(
    arm: ArmSpec,
    y: np.ndarray,
    base_pred: np.ndarray,
    items: dict[int, tuple[np.ndarray, np.ndarray]],
    df: pd.DataFrame,
) -> dict:
    n = len(y)
    base = metrics(y, base_pred)
    feature_blocks: list[dict] = []
    for spec in arm.item_specs:
        cols = family_cols(df, spec)
        if not cols:
            raise ValueError(f"Arm {arm.name} has no columns for {spec}")
        true_item, pred_item = items[spec.item]
        feature_blocks.append(
            {
                "spec": spec,
                "cols": cols,
                "X": df[cols].to_numpy(dtype=float),
                "resid": true_item - pred_item,
            }
        )

    seed_preds: list[np.ndarray] = []
    seed_rows: list[dict] = []
    for seed in SEEDS:
        corrected = base_pred.copy()
        kf = KFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
        per_item_corr = {str(block["spec"].item): np.zeros(n, dtype=float) for block in feature_blocks}
        for train_idx, test_idx in kf.split(np.arange(n)):
            for block in feature_blocks:
                delta = fold_correct(block["X"], block["resid"], train_idx, test_idx)
                item_key = str(block["spec"].item)
                per_item_corr[item_key][test_idx] += delta
                corrected[test_idx] += delta
        cand = metrics(y, corrected)
        seed_preds.append(corrected)
        seed_rows.append(
            {
                "seed": int(seed),
                "candidate": {k: round(v, 6) for k, v in cand.items()},
                "delta_ccc": round(cand["ccc"] - base["ccc"], 6),
                "delta_mae": round(cand["mae"] - base["mae"], 6),
                "correction_std_by_item": {
                    item: round(float(np.std(vals)), 6)
                    for item, vals in per_item_corr.items()
                },
            }
        )
        print(
            f"[rank8] {arm.name} seed={seed} "
            f"CCC={cand['ccc']:.4f} delta={cand['ccc'] - base['ccc']:+.4f}"
        )

    ensemble_pred = np.mean(np.vstack(seed_preds), axis=0)
    ensemble = metrics(y, ensemble_pred)
    deltas = np.array([row["delta_ccc"] for row in seed_rows], dtype=float)
    boot = paired_bootstrap(y, base_pred, ensemble_pred)
    delta_ccc = ensemble["ccc"] - base["ccc"]
    delta_mae = ensemble["mae"] - base["mae"]
    gate_pass = (
        delta_ccc >= PROMOTION_DELTA
        and boot["frac_positive"] >= PROMOTION_FRAC_POS
        and float(np.std(deltas, ddof=1)) < PROMOTION_SEED_STD_MAX
        and delta_mae <= MAE_DEGRADATION_MAX
    )
    return {
        "arm": arm.name,
        "item_feature_specs": [
            {
                "item": spec.item,
                "family": spec.family,
                "phases": list(spec.phases),
                "n_cols": len(family_cols(df, spec)),
                "cols": family_cols(df, spec),
            }
            for spec in arm.item_specs
        ],
        "baseline": {k: round(v, 6) for k, v in base.items()},
        "seed_summaries": seed_rows,
        "seed_mean_delta_ccc": round(float(np.mean(deltas)), 6),
        "seed_delta_std": round(float(np.std(deltas, ddof=1)), 6),
        "ensemble": {
            "candidate": {k: round(v, 6) for k, v in ensemble.items()},
            "delta_ccc": round(delta_ccc, 6),
            "delta_mae": round(delta_mae, 6),
            "bootstrap": boot,
        },
        "promotion_gate_pass": bool(gate_pass),
    }


def apply_null(
    y: np.ndarray,
    base_pred: np.ndarray,
    items: dict[int, tuple[np.ndarray, np.ndarray]],
    df: pd.DataFrame,
    null_mode: str,
) -> tuple[np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]], pd.DataFrame]:
    if null_mode in ("", "real"):
        return y, base_pred, items, df
    n = len(y)
    if null_mode == "scrambled_y":
        perm = np.random.default_rng(20260515).permutation(n)
        return y[perm], base_pred[perm], {k: (v[0][perm], v[1][perm]) for k, v in items.items()}, df
    if null_mode == "sid_shuffle":
        perm = np.random.default_rng(20260516).permutation(n)
        shuffled = df.copy()
        cols = [c for c in df.columns if c != "sid"]
        shuffled[cols] = shuffled[cols].to_numpy()[perm]
        return y, base_pred, items, shuffled
    raise ValueError(f"unknown null mode {null_mode}")


def main() -> int:
    sids, y, base_pred, items, df, cache, manifest = load_aligned()
    print(f"[rank8] cache={cache} N={len(sids)} baseline={ccc(y, base_pred):.6f}")

    real_arms = [run_arm(arm, y, base_pred, items, df) for arm in ARMS]

    null_results: dict[str, list[dict]] = {}
    for null_mode in ("scrambled_y", "sid_shuffle"):
        yn, pn, itemsn, dfn = apply_null(y, base_pred, items, df, null_mode)
        null_results[null_mode] = [run_arm(arm, yn, pn, itemsn, dfn) for arm in ARMS]

    any_pass = any(arm["promotion_gate_pass"] for arm in real_arms)
    verdict = "SCREEN_PASS_PROMOTE_ONE_LOCKBOX" if any_pass else "SCREEN_FAIL_NO_LOOCV"
    out = {
        "name": "screen_t1_rank8_tug_phase_ph_mfdfa",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "proposal_source": "/tmp/pro-results.txt rank #8",
        "screen_only": True,
        "no_loocv_run": True,
        "cache_path": str(cache.relative_to(ROOT)),
        "cache_manifest": manifest,
        "preregistration_master": str(PREREG_MASTER.relative_to(ROOT)),
        "n": int(len(sids)),
        "baseline_iter34_ccc": round(float(ccc(y, base_pred)), 6),
        "arms": real_arms,
        "null_results": null_results,
        "promotion_gate": {
            "delta_ccc_min": PROMOTION_DELTA,
            "bootstrap_frac_positive_min": PROMOTION_FRAC_POS,
            "seed_delta_std_max": PROMOTION_SEED_STD_MAX,
            "mae_degradation_max": MAE_DEGRADATION_MAX,
        },
        "verdict": verdict,
    }
    ts = out["created_at_utc"]
    path = RESULTS / f"screen_t1_rank8_tug_phase_ph_mfdfa_{ts}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"[rank8] verdict={verdict}")
    print(f"[rank8] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
