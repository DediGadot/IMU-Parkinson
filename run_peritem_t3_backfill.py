"""Per-item OOF backfill for items {1, 2, 3} (T3 push Phase A1, 2026-05-04).

The iter8 batch 20260430_143044 explicitly skipped items 1, 2, 3 ("severity-proxy
only"). For the per-item gated T3 composite (Phase B), each of the 18 items needs
an OOF prediction; using zero would bias the T3 sum downward.

Items 1 (speech), 2 (facial expression), 3 (rigidity) have NO IMU signature.
Their best architecture is hy_residual_item: Stage-1 Ridge(H&Y + clinical)
predicts most of the variance via severity proxy; Stage-2 LGB on V2 fits the
small residual. Equivalent to iter5 architecture per-item.

Standalone implementation using inductive_lib FoldImputer/FoldNormalizer + LGB,
matching the iter5 / iter12 per-fold pipeline bit-equivalently.

Usage:
    python3 run_peritem_t3_backfill.py --mode screen
        5-fold (5 seeds) screen across 3 architectures.
    python3 run_peritem_t3_backfill.py --mode lockbox
        Pre-register + LOOCV (3 seeds) for screen winner per item.
    python3 run_peritem_t3_backfill.py --mode both
        Run both sequentially (default).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    feature_select_fold,
    get_hy_features,
    impute_fold,
    train_lgb,
)
from run_per_item_v2 import load_data

TARGET_ITEMS = [1, 2, 3]
SCREEN_SEEDS = [42, 1337, 7, 2024, 9001]
LOCKBOX_SEEDS = [42, 1337, 7]
ARCHITECTURES = ["v2_baseline", "hy_only_ridge", "hy_residual_v2"]


def _formula_sha256(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


# ── Per-item architectures ───────────────────────────────────────────────────


def _v2_baseline_oof(X: np.ndarray, y: np.ndarray, splits, seed: int) -> np.ndarray:
    """LGB on V2 with per-fold K=500 selector. Pure IMU baseline."""
    n = len(y)
    oof = np.full(n, np.nan, dtype=np.float64)
    valid = ~np.isnan(y)
    for tr, te in splits:
        tr_v = tr[valid[tr]]
        te_v = te[valid[te]]
        if len(tr_v) < 5 or len(te_v) == 0:
            continue
        Xtr, Xte = impute_fold(X[tr_v], X[te_v])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=500, seed=seed)
        oof[te_v] = train_lgb(Xtr_s, y[tr_v], Xte_s, seed)
    return oof


def _hy_only_ridge_oof(hy: np.ndarray, y: np.ndarray, splits, seed: int) -> np.ndarray:
    """Stage-1 Ridge on H&Y features only. No IMU. Floor predictor."""
    hy_feat = get_hy_features(hy)
    n = len(y)
    oof = np.full(n, np.nan, dtype=np.float64)
    valid = ~np.isnan(y)
    for tr, te in splits:
        tr_v = tr[valid[tr]]
        te_v = te[valid[te]]
        if len(tr_v) < 5 or len(te_v) == 0:
            continue
        ridge = Ridge(alpha=1.0)
        ridge.fit(hy_feat[tr_v], y[tr_v])
        oof[te_v] = ridge.predict(hy_feat[te_v])
    return oof


def _hy_residual_v2_oof(X: np.ndarray, hy: np.ndarray, y: np.ndarray, splits, seed: int) -> np.ndarray:
    """Stage-1 Ridge(H&Y) + Stage-2 LGB(V2 residual). Same arch as iter5/iter12."""
    hy_feat = get_hy_features(hy)
    n = len(y)
    oof = np.full(n, np.nan, dtype=np.float64)
    valid = ~np.isnan(y)
    for tr, te in splits:
        tr_v = tr[valid[tr]]
        te_v = te[valid[te]]
        if len(tr_v) < 5 or len(te_v) == 0:
            continue
        ridge = Ridge(alpha=1.0)
        ridge.fit(hy_feat[tr_v], y[tr_v])
        s1_tr = ridge.predict(hy_feat[tr_v])
        s1_te = ridge.predict(hy_feat[te_v])
        residual_tr = y[tr_v] - s1_tr
        Xtr, Xte = impute_fold(X[tr_v], X[te_v])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr_s, residual_tr, Xte_s, seed)
        oof[te_v] = s1_te + s2_te
    return oof


def _run_arch(d: dict, item: int, arch: str, seeds: list[int], cv: str) -> dict:
    """Run a single architecture across seeds with either 5-fold or LOOCV."""
    y = d["items"][item]
    X = d["X_v2"]
    hy = d["hy"]
    n = len(y)
    valid = ~np.isnan(y)
    n_valid = int(valid.sum())
    seed_oofs: list[np.ndarray] = []
    seed_cccs: list[float] = []
    seed_maes: list[float] = []
    for s in seeds:
        if cv == "5fold":
            kf = KFold(n_splits=5, shuffle=True, random_state=s)
            splits = list(kf.split(np.arange(n)))
        elif cv == "loocv":
            splits = [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]
        else:
            raise ValueError(f"Unknown cv={cv}")
        if arch == "v2_baseline":
            oof = _v2_baseline_oof(X, y, splits, s)
        elif arch == "hy_only_ridge":
            oof = _hy_only_ridge_oof(hy, y, splits, s)
        elif arch == "hy_residual_v2":
            oof = _hy_residual_v2_oof(X, hy, y, splits, s)
        else:
            raise ValueError(f"Unknown arch={arch}")
        seed_oofs.append(oof)
        # Score on valid subset
        ccc_v = ccc_fn(y[valid], oof[valid])
        mae_v = mae_fn(y[valid], oof[valid])
        seed_cccs.append(float(ccc_v))
        seed_maes.append(float(mae_v))
    return {
        "item": item, "arch": arch, "cv": cv,
        "seeds": list(seeds),
        "n_valid": n_valid,
        "ccc_per_seed": seed_cccs,
        "mae_per_seed": seed_maes,
        "ccc_mean": float(np.mean(seed_cccs)),
        "ccc_std": float(np.std(seed_cccs)),
        "mae_mean": float(np.mean(seed_maes)),
        "mean_oof": np.nanmean(np.stack(seed_oofs, axis=0), axis=0),
    }


def screen(d: dict, out_csv: Path) -> tuple[pd.DataFrame, dict[int, str]]:
    print(f"\n=== Phase A1 SCREEN: items {TARGET_ITEMS} × archs {ARCHITECTURES} × {len(SCREEN_SEEDS)} seeds × 5-fold ===", flush=True)
    rows = []
    for item in TARGET_ITEMS:
        for arch in ARCHITECTURES:
            t0 = time.time()
            try:
                r = _run_arch(d, item, arch, SCREEN_SEEDS, cv="5fold")
                rows.append({
                    "item": item, "arch": arch,
                    "ccc_mean": r["ccc_mean"], "ccc_std": r["ccc_std"], "mae_mean": r["mae_mean"],
                    "n_valid": r["n_valid"],
                    "wall_s": round(time.time() - t0, 1),
                    "ccc_per_seed": r["ccc_per_seed"],
                })
                print(f"  item={item} arch={arch:18s}  CCC={r['ccc_mean']:+.4f} ± {r['ccc_std']:.4f}  MAE={r['mae_mean']:.3f}  n={r['n_valid']}  ({rows[-1]['wall_s']}s)", flush=True)
            except Exception as e:
                rows.append({"item": item, "arch": arch, "error": str(e)[:200], "wall_s": round(time.time() - t0, 1)})
                print(f"  item={item} arch={arch} ERROR: {e}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}", flush=True)
    # Pick winner per item
    winners = {}
    for item in TARGET_ITEMS:
        df_i = df[(df["item"] == item) & df["ccc_mean"].notna()]
        if df_i.empty:
            print(f"  item {item}: ALL FAILED — defaulting to hy_only_ridge", flush=True)
            winners[item] = "hy_only_ridge"
            continue
        df_i = df_i.sort_values(by=["ccc_mean", "ccc_std", "mae_mean"], ascending=[False, True, True])
        winners[item] = df_i.iloc[0]["arch"]
        print(f"  item {item}: winner = {winners[item]:18s} (CCC={df_i.iloc[0]['ccc_mean']:+.4f})", flush=True)
    return df, winners


def lockbox(d: dict, winners: dict[int, str]) -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    formula_payload = {
        "experiment": "T3 push Phase A1 — per-item OOF backfill for items {1, 2, 3}",
        "target_items": TARGET_ITEMS,
        "architecture_choices": ARCHITECTURES,
        "winners": {str(k): v for k, v in winners.items()},
        "loocv_seeds": LOCKBOX_SEEDS,
        "selection_protocol": (
            "5-fold across 5 seeds; pick highest CCC, tiebreak std then MAE. "
            "Locked BEFORE LOOCV is run."
        ),
        "5null_inheritance": (
            "Architectures use inductive_lib FoldImputer + per-fold standardisation + "
            "per-fold K=500 selector — bit-identical to iter5/iter12, which passed the "
            "5-null gate. Ridge Stage-1 + LGB Stage-2 = canonical hy_residual."
        ),
        "purpose": (
            "Items 1, 2, 3 have no IMU signature. The hy_residual or hy_only winners "
            "produce per-subject OOFs that are essentially Ridge-on-H&Y predictions — "
            "informative for the T3 composite, not biased to the population mean."
        ),
    }
    formula_sha = _formula_sha256(formula_payload)
    git_sha = _git_sha()

    prereg = {
        **formula_payload,
        "formula_sha256": formula_sha,
        "git_sha": git_sha,
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "created_at_local": datetime.now().isoformat(),
        "timestamp": ts,
        "lockbox_rules": [
            "Architecture per item locked BEFORE any LOOCV is observed.",
            "ONE LOOCV per item × architecture pair; mean of 3 seeds = headline.",
            "5-null gate inheritance from iter5/iter12 architectures.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_peritem_t3_backfill_{ts}.json"
    with open(pre_path, "w") as f:
        json.dump(prereg, f, indent=2, default=float)
    print(f"\nPre-registration: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula_sha[:16]}...", flush=True)
    print(f"  git_sha = {git_sha[:12]}", flush=True)

    headlines = {}
    for item, arch in winners.items():
        print(f"\n--- LOOCV: item={item} arch={arch} ---", flush=True)
        t0 = time.time()
        r = _run_arch(d, item, arch, LOCKBOX_SEEDS, cv="loocv")
        sids = d["sids"]
        y = d["items"][item]
        valid = ~np.isnan(y)
        # Headline = mean preds across seeds (already in r["mean_oof"])
        mean_oof = r["mean_oof"]
        # Filter to valid subjects only for metric
        h = full_metrics(y[valid], mean_oof[valid], label=f"peritem_t3bf_{item}_{arch}")
        h["item"] = item
        h["arch"] = arch
        h["per_seed_ccc"] = r["ccc_per_seed"]
        h["per_seed_std"] = r["ccc_std"]
        h["seeds"] = LOCKBOX_SEEDS
        h["n_valid"] = int(valid.sum())
        h["wall_s"] = round(time.time() - t0, 1)
        headlines[item] = h
        # Save aligned to 94-subject SID array (NaN for invalid)
        out_npy = RESULTS_DIR / f"lockbox_peritem_{item}_{arch}_t3bf_{ts}.oof.npy"
        np.save(out_npy, mean_oof)
        out_sids_npy = RESULTS_DIR / f"lockbox_peritem_{item}_{arch}_t3bf_{ts}.sids.npy"
        np.save(out_sids_npy, sids)
        out_json = RESULTS_DIR / f"lockbox_peritem_{item}_{arch}_t3bf_{ts}.json"
        with open(out_json, "w") as f:
            json.dump({
                "item": item, "arch": arch,
                "ccc": h["ccc"], "mae": h["mae"], "r": h["r"],
                "per_seed_ccc": h["per_seed_ccc"], "per_seed_std": h["per_seed_std"],
                "n_valid": h["n_valid"], "seeds": LOCKBOX_SEEDS,
                "wall_s": h["wall_s"], "preregistration": pre_path.name,
            }, f, indent=2, default=float)
        print(f"  LOOCV CCC = {h['ccc']:+.4f}  MAE = {h['mae']:.3f}  per-seed std = {h['per_seed_std']:.4f}  n_valid={h['n_valid']}  ({h['wall_s']}s)", flush=True)

    summary_path = RESULTS_DIR / f"lockbox_peritem_t3_backfill_combined_{ts}.json"
    with open(summary_path, "w") as f:
        json.dump({
            "preregistration": pre_path.name,
            "winners": {str(k): v for k, v in winners.items()},
            "headlines": {str(k): h for k, h in headlines.items()},
            "ts": ts,
        }, f, indent=2, default=float)
    print(f"\nCombined: {summary_path.name}", flush=True)
    return {"preregistration": str(pre_path), "headlines": headlines, "ts": ts}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen", "lockbox", "both"], default="both")
    args = p.parse_args()

    print("Loading data...", flush=True)
    d = load_data()
    print(f"  N = {len(d['sids'])} PD subjects, V2 = {d['X_v2'].shape[1]} features", flush=True)
    # Verify items 1, 2, 3 are loaded
    for i in TARGET_ITEMS:
        if i not in d["items"]:
            raise SystemExit(f"item {i} not in d['items']")
        y = d["items"][i]
        valid = ~np.isnan(y)
        print(f"  item {i}: n_valid={valid.sum()}, range=[{np.nanmin(y):.0f}, {np.nanmax(y):.0f}], mean={np.nanmean(y):.2f}", flush=True)

    if args.mode in ("screen", "both"):
        out_csv = RESULTS_DIR / "peritem_t3_backfill_5fold_screen.csv"
        df, winners = screen(d, out_csv)
        winners_path = RESULTS_DIR / "peritem_t3_backfill_winners.json"
        with open(winners_path, "w") as f:
            json.dump({str(k): v for k, v in winners.items()}, f, indent=2)

    if args.mode in ("lockbox", "both"):
        if args.mode == "lockbox":
            winners_path = RESULTS_DIR / "peritem_t3_backfill_winners.json"
            if not winners_path.exists():
                raise SystemExit(f"Run --mode screen first; missing {winners_path}")
            winners = {int(k): v for k, v in json.load(open(winners_path)).items()}
        lockbox(d, winners)


if __name__ == "__main__":
    main()
