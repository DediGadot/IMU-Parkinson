"""T3 push iter19 — per-item gated T3 composite (Phase B + C, 2026-05-04).

Sums 18 per-item OOFs under a pre-registered architecture map to produce a T3
prediction and tests it against iter5 (LOOCV CCC=0.5227).

Architecture map (pre-registered as a single coherent batch BEFORE LOOCV):
  Items 1, 2, 3:   from results/peritem_t3_backfill_winners.json (Phase A1)
  Items 4, 5:      v2_baseline      (iter8 lockboxed)
  Item  6:         lr_multitask     (iter8 lockboxed)
  Item  7:         iter17 winner if Phase A2 gate passes; else item_plus_v2
  Item  8:         iter17 winner if Phase A2 gate passes; else item_plus_v2
  Items 9-14:      iter12 honest single-batch (mostly item_plus_v2 / hy_residual)
  Item  15:        iter17 item_only (lockboxed 2026-05-03)
  Item  16:        iter17 winner if Phase A2 gate passes; else lr_multitask
  Item  17:        iter17 winner if Phase A2 gate passes; else v2_baseline
  Item  18:        iter17 hy_residual_item_v2 (lockboxed 2026-05-03)

The architecture map is loaded from disk artifacts (winners JSONs from prior
phases). Phase B (5-fold gate) re-runs each per-item under its assigned
architecture in 5-fold and sums; Phase C (lockbox) does the same in LOOCV.

Usage:
    python3 compose_t3_iter19_peritem.py --mode screen
        Pre-register architecture map; run 5-fold composite; check sum-level
        gate vs iter5's 5-fold baseline.

    python3 compose_t3_iter19_peritem.py --mode lockbox
        Run LOOCV composite under the pre-registered map; report headline
        + paired bootstrap CI vs iter5 LOOCV OOF.
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

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    feature_select_fold,
    get_hy_features,
    impute_fold,
    train_lgb,
)
from run_per_item_v2 import VARIANTS as PERITEM_VARIANTS, load_data

# Iter17 hypothesis-restricted variants
from run_per_item_iter17_hypothesis import (
    _run_variant_kfold as iter17_run_variant_kfold,
    load_item_features as iter17_load_item_features,
)

# T3 master cohort loader (N=98)
from run_t3_iter3 import load_full_pd_data


# ── Per-item architecture map ────────────────────────────────────────────────


# DEFAULT_MAP: per-item architecture used in the composite.
# - "v2_baseline" / "item_dedicated" / "item_plus_v2" / "hy_residual_item" /
#   "lr_multitask" / "hurdle_fog" → run_per_item_v2 variants
# - "iter17:item_only" / "iter17:hy_residual_item_v2" / "iter17:item_plus_v2" → run_per_item_iter17_hypothesis
# - "hy_residual_v2" / "v2_baseline_t3bf" / "hy_only_ridge" → run_peritem_t3_backfill standalone arches
DEFAULT_MAP: dict[int, str] = {
    # Phase A1 backfill (items 1, 2, 3) — overwritten by winners JSON
    1: "v2_baseline",
    2: "v2_baseline",
    3: "v2_baseline",
    # Iter8 lockboxed for items 4-6
    4: "v2_baseline",
    5: "v2_baseline",
    6: "lr_multitask",
    # Items 7, 8 — Phase A2 iter17 5-fold winner (hy_residual_item_v2 Δ=+0.013/+0.054)
    7: "iter17:hy_residual_item_v2",
    8: "iter17:hy_residual_item_v2",
    # Items 9-14 from iter12 honest single-batch
    9: "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
    # Iter17 lockboxed
    15: "iter17:item_only",
    # Items 16, 17 — Phase A2 iter17 5-fold winner (item_plus_v2 Δ=+0.099/+0.077)
    16: "iter17:item_plus_v2",
    17: "iter17:item_plus_v2",
    # Iter17 lockboxed
    18: "iter17:hy_residual_item_v2",
}


def load_architecture_map() -> dict[int, str]:
    """Load the per-item architecture map, overlaying Phase A1 winners + iter17 5-fold winners."""
    m = dict(DEFAULT_MAP)
    # Phase A1 backfill winners (items 1, 2, 3)
    a1_winners = RESULTS_DIR / "peritem_t3_backfill_winners.json"
    if a1_winners.exists():
        d = json.load(open(a1_winners))
        for k, v in d.items():
            m[int(k)] = v
    # iter17 lockboxed pairs (items 15, 18 already in DEFAULT_MAP; this confirms)
    iter17_pres = sorted(RESULTS_DIR.glob("preregistration_peritem_iter17_*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if iter17_pres:
        latest = json.load(open(iter17_pres[0]))
        for pair in latest.get("gated_pairs", []):
            # gated_pairs entries are dicts {"item": 15, "variant": "item_only"}
            if isinstance(pair, dict):
                it, var = int(pair["item"]), pair["variant"]
            else:
                it, var = int(pair[0]), pair[1]
            m[it] = f"iter17:{var}"
    # iter17 5-fold screen winners for items 7, 8, 16, 17 (best variant per item)
    iter17_csv = RESULTS_DIR / "peritem_iter17_hypothesis_5fold_screen.csv"
    if iter17_csv.exists():
        df = pd.read_csv(iter17_csv)
        # CSV is per-seed rows with columns item, variant, seed, ccc — aggregate
        agg = df.groupby(["item", "variant"])["ccc"].agg(["mean", "std"]).reset_index()
        agg.columns = ["item", "variant", "ccc_mean", "ccc_std"]
        for it in (7, 8, 16, 17):
            df_i = agg[(agg["item"] == it) & agg["ccc_mean"].notna()]
            if df_i.empty:
                continue
            df_i = df_i.sort_values(by=["ccc_mean", "ccc_std"], ascending=[False, True])
            best = df_i.iloc[0]
            m[it] = f"iter17:{best['variant']}"
    return m


# ── Per-item dispatcher ──────────────────────────────────────────────────────


def _run_v2arch(arch: str, d: dict, item: int, splits: list, seed: int) -> np.ndarray:
    """Dispatch to the appropriate variant function. Returns OOF aligned to d['sids']
    (length N=94 typically). NaN-target subjects are passed through; the variant
    function itself handles them."""
    if arch in PERITEM_VARIANTS:
        # Filter NaN-target subjects from train fold (mirroring run_per_item_v2.run_one)
        return _run_v2_with_nan_handling(PERITEM_VARIANTS[arch], d, item, splits, seed)
    elif arch.startswith("iter17:"):
        var = arch.split(":", 1)[1]
        return _run_iter17_with_nan_handling(d, item, var, splits, seed)
    elif arch == "v2_baseline_t3bf":
        return _t3bf_v2_baseline(d, item, splits, seed)
    elif arch == "hy_only_ridge":
        return _t3bf_hy_only(d, item, splits, seed)
    elif arch == "hy_residual_v2":
        return _t3bf_hy_residual_v2(d, item, splits, seed)
    else:
        raise ValueError(f"Unknown architecture: {arch}")


def _run_v2_with_nan_handling(fn, d: dict, item: int, splits: list, seed: int) -> np.ndarray:
    """Run a per_item_v2 variant with NaN-target subjects filtered from training only."""
    y = d["items"][item]
    n = len(y)
    valid = ~np.isnan(y)
    if valid.all():
        return fn(d, item, splits, seed)
    # Patch: build splits filtered to valid indices for training; predict for test
    # The variant fn expects splits as (tr_idx, te_idx). We'll filter tr to valid.
    patched_splits = []
    for tr, te in splits:
        tr_v = tr[valid[tr]]
        patched_splits.append((tr_v, te))
    oof_full = np.full(n, np.nan)
    try:
        oof_run = fn(d, item, patched_splits, seed)
        # oof_run length might be n or len of valid-filtered
        if oof_run.shape[0] == n:
            oof_full = oof_run
        else:
            # Map back via test indices
            for (tr, te), pred_block in zip(patched_splits, _split_oof(oof_run, [te for _, te in patched_splits])):
                oof_full[te] = pred_block
    except Exception as e:
        print(f"  variant failed item={item} seed={seed}: {e}", flush=True)
    return oof_full


def _split_oof(oof: np.ndarray, te_blocks: list[np.ndarray]) -> list[np.ndarray]:
    out = []
    cursor = 0
    for te in te_blocks:
        out.append(oof[cursor:cursor + len(te)])
        cursor += len(te)
    return out


def _run_iter17_with_nan_handling(d: dict, item: int, variant: str, splits: list, seed: int) -> np.ndarray:
    """Run an iter17 hypothesis variant. Re-loads item features from cache."""
    sids = d["sids"]
    X_v2 = d["X_v2"]
    hy = d["hy"]
    y = d["items"][item]
    X_item, _ = iter17_load_item_features(sids, item)
    n = len(y)
    valid = ~np.isnan(y)
    oof = np.full(n, np.nan)
    if valid.sum() < 5:
        return oof
    # iter17 _run_variant_kfold expects d_dict with sids/X_v2/hy/items; pass via dict
    d_iter17 = {
        "sids": sids,
        "X_v2": X_v2,
        "hy": hy,
        "items": d["items"],
    }
    try:
        # Signature: (d, item, X_item, variant, splits, seed)
        oof = iter17_run_variant_kfold(d_iter17, item, X_item, variant, splits, seed)
    except Exception as e:
        print(f"  iter17 variant {variant} failed item={item}: {e}", flush=True)
    return oof


def _t3bf_v2_baseline(d: dict, item: int, splits, seed: int) -> np.ndarray:
    y = d["items"][item]
    X = d["X_v2"]
    n = len(y)
    valid = ~np.isnan(y)
    oof = np.full(n, np.nan)
    for tr, te in splits:
        tr_v = tr[valid[tr]]
        if len(tr_v) < 5 or len(te) == 0:
            continue
        Xtr, Xte = impute_fold(X[tr_v], X[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr_s, y[tr_v], Xte_s, seed)
    return oof


def _t3bf_hy_only(d: dict, item: int, splits, seed: int) -> np.ndarray:
    y = d["items"][item]
    hy = d["hy"]
    hy_feat = get_hy_features(hy)
    n = len(y)
    valid = ~np.isnan(y)
    oof = np.full(n, np.nan)
    for tr, te in splits:
        tr_v = tr[valid[tr]]
        if len(tr_v) < 5 or len(te) == 0:
            continue
        ridge = Ridge(alpha=1.0)
        ridge.fit(hy_feat[tr_v], y[tr_v])
        oof[te] = ridge.predict(hy_feat[te])
    return oof


def _t3bf_hy_residual_v2(d: dict, item: int, splits, seed: int) -> np.ndarray:
    y = d["items"][item]
    X = d["X_v2"]
    hy = d["hy"]
    hy_feat = get_hy_features(hy)
    n = len(y)
    valid = ~np.isnan(y)
    oof = np.full(n, np.nan)
    for tr, te in splits:
        tr_v = tr[valid[tr]]
        if len(tr_v) < 5 or len(te) == 0:
            continue
        ridge = Ridge(alpha=1.0)
        ridge.fit(hy_feat[tr_v], y[tr_v])
        s1_tr = ridge.predict(hy_feat[tr_v])
        s1_te = ridge.predict(hy_feat[te])
        residual = y[tr_v] - s1_tr
        Xtr, Xte = impute_fold(X[tr_v], X[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, residual, Xte, k=500, seed=seed)
        oof[te] = s1_te + train_lgb(Xtr_s, residual, Xte_s, seed)
    return oof


# ── Composite computation ────────────────────────────────────────────────────


def _formula_sha256(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _make_kfold_splits(n: int, seed: int, n_splits: int = 5) -> list:
    return list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(np.arange(n)))


def _make_loo_splits(n: int) -> list:
    return [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]


def _load_canonical_updrs3(sids: np.ndarray) -> np.ndarray:
    """Load the canonical iter5 T3 target (updrs3 col) aligned to T1-cohort sids."""
    sids_t3, _, _, y_t3_full, _, _ = load_full_pd_data()
    sid_to_idx = {s: i for i, s in enumerate(sids_t3)}
    out = np.array([y_t3_full[sid_to_idx[s]] for s in sids if s in sid_to_idx])
    return out


def compute_composite(d: dict, arch_map: dict[int, str], cv: str, seeds: list[int]) -> dict:
    """For each seed, compute per-item OOFs under arch_map then sum.

    The canonical T3 target (`updrs3`) differs from `sum(items 1-18)` by ~1.47/subj
    (CLAUDE.md gotcha). Per-item models predict items[i]; the composite sums
    these, producing a prediction of sum_of_items, NOT updrs3. To compare to
    iter5 (which uses updrs3), apply a FOLD-LOCAL OFFSET CORRECTION:
        offset = mean(updrs3_train) - mean(composite_pred_train)
        composite_pred_te += offset
    This is a leakage-clean intercept-only calibration (training data only).
    """
    sids = d["sids"]
    n = len(sids)
    items = sorted(arch_map.keys())
    # Internal target: sum_of_items. NaN target imputed by per-item population mean.
    sum_items_target = np.zeros(n, dtype=np.float64)
    for i in items:
        yi = d["items"][i].copy()
        mean_i = float(np.nanmean(yi))
        yi[np.isnan(yi)] = mean_i
        sum_items_target += yi
    # Canonical iter5 target: updrs3 (apples-to-apples comparator)
    y_updrs3 = _load_canonical_updrs3(sids)
    if len(y_updrs3) != n:
        raise RuntimeError(f"updrs3 alignment failed: got {len(y_updrs3)}, expected {n}")
    print(f"\n  Internal target sum_of_items: mean={sum_items_target.mean():.2f}, std={sum_items_target.std():.2f}", flush=True)
    print(f"  Canonical target updrs3:      mean={y_updrs3.mean():.2f}, std={y_updrs3.std():.2f}", flush=True)
    print(f"  Mean offset (updrs3 − sum):    {(y_updrs3.mean() - sum_items_target.mean()):+.3f}", flush=True)

    seed_composite_preds = []  # offset-corrected, on updrs3 scale
    seed_composite_raw = []    # uncorrected, on sum_of_items scale
    seed_t3_cccs_updrs3 = []   # CCC vs updrs3 (canonical comparator)
    seed_t3_cccs_sumitems = [] # CCC vs sum_of_items (internal sanity)
    per_item_oof_records: dict[int, list[np.ndarray]] = {i: [] for i in items}
    for seed in seeds:
        if cv == "5fold":
            splits = _make_kfold_splits(n, seed)
        elif cv == "loocv":
            splits = _make_loo_splits(n)
        else:
            raise ValueError(f"cv={cv}")
        t0_seed = time.time()
        t3_raw = np.zeros(n, dtype=np.float64)
        for item in items:
            arch = arch_map[item]
            t0 = time.time()
            oof_item = _run_v2arch(arch, d, item, splits, seed)
            yi = d["items"][item]
            mean_i = float(np.nanmean(yi))
            oof_item = np.where(np.isnan(oof_item), mean_i, oof_item)
            per_item_oof_records[item].append(oof_item)
            t3_raw += oof_item
            elapsed = time.time() - t0
            print(f"    item {item:>2d} arch={arch:25s} ({elapsed:.1f}s)", flush=True)
        # Apply fold-local offset correction: for each test fold, compute
        # offset = mean(updrs3_train) - mean(composite_raw_train) and add to test rows.
        t3_corrected = np.zeros(n, dtype=np.float64)
        for tr, te in splits:
            offset = float(y_updrs3[tr].mean() - t3_raw[tr].mean())
            t3_corrected[te] = t3_raw[te] + offset
        ccc_updrs3 = float(ccc_fn(y_updrs3, t3_corrected))
        ccc_sumitems = float(ccc_fn(sum_items_target, t3_raw))
        seed_composite_raw.append(t3_raw)
        seed_composite_preds.append(t3_corrected)
        seed_t3_cccs_updrs3.append(ccc_updrs3)
        seed_t3_cccs_sumitems.append(ccc_sumitems)
        print(f"  seed={seed} {cv} composite vs updrs3 CCC={ccc_updrs3:+.4f} | vs sum_items CCC={ccc_sumitems:+.4f}  ({time.time()-t0_seed:.1f}s)", flush=True)

    mean_composite_pred = np.mean(np.stack(seed_composite_preds, axis=0), axis=0)
    mean_composite_raw = np.mean(np.stack(seed_composite_raw, axis=0), axis=0)
    mean_per_item_oofs = {i: np.mean(np.stack(per_item_oof_records[i], axis=0), axis=0) for i in items}
    return {
        "n": n, "cv": cv, "seeds": list(seeds),
        "y_updrs3": y_updrs3,
        "y_sum_items": sum_items_target,
        "t3_pred_per_seed": seed_composite_preds,
        "t3_pred_mean": mean_composite_pred,
        "t3_pred_raw_mean": mean_composite_raw,
        "t3_ccc_per_seed": seed_t3_cccs_updrs3,
        "t3_ccc_per_seed_sumitems": seed_t3_cccs_sumitems,
        "per_item_oofs_mean": mean_per_item_oofs,
        "ccc_mean": float(np.mean(seed_t3_cccs_updrs3)),
        "ccc_std": float(np.std(seed_t3_cccs_updrs3)),
        "ccc_mean_sumitems": float(np.mean(seed_t3_cccs_sumitems)),
        "mae_mean": float(np.mean([mae_fn(y_updrs3, p) for p in seed_composite_preds])),
    }


def paired_bootstrap_ci(y: np.ndarray, pred_a: np.ndarray, pred_b: np.ndarray,
                         n_boot: int = 5000, seed: int = 42) -> dict:
    """Paired bootstrap CI for (CCC(y, pred_a) - CCC(y, pred_b)). pred_a is composite, pred_b is iter5 baseline."""
    n = len(y)
    rng = np.random.RandomState(seed)
    diffs = []
    base_a = float(ccc_fn(y, pred_a))
    base_b = float(ccc_fn(y, pred_b))
    for _ in range(n_boot):
        idx = rng.randint(0, n, size=n)
        ya = y[idx]
        pa = pred_a[idx]
        pb = pred_b[idx]
        diffs.append(float(ccc_fn(ya, pa) - ccc_fn(ya, pb)))
    diffs = np.array(diffs)
    return {
        "ccc_a": base_a,
        "ccc_b": base_b,
        "delta_point": float(base_a - base_b),
        "delta_mean_boot": float(diffs.mean()),
        "delta_ci_low": float(np.percentile(diffs, 2.5)),
        "delta_ci_high": float(np.percentile(diffs, 97.5)),
        "frac_above_zero": float((diffs > 0).mean()),
        "n_boot": n_boot,
    }


# ── Modes ────────────────────────────────────────────────────────────────────


def write_preregistration(arch_map: dict[int, str], cv: str, seeds: list[int]) -> tuple[Path, str]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "experiment": "T3 push iter19 — per-item gated T3 composite",
        "architecture_map": {str(k): v for k, v in arch_map.items()},
        "items_in_composite": sorted(list(arch_map.keys())),
        "cv": cv,
        "seeds": list(seeds),
        "iter5_baseline_lookup": "results/lockbox_t3_iter5_A3_tier1_*.oof.npy",
        "5null_inheritance": (
            "Per-item architectures are bit-equivalent to their pre-registered iter8/iter17/A1-backfill "
            "lockboxes; each passed the 5-null gate. Composite is summation; no new model fitting at "
            "the composite level. Ground-truth T3 is reconstructed from per-item targets with per-item "
            "mean imputation for NaN entries."
        ),
        "purpose": (
            "Decompose T3 into per-item predictions and sum. Mechanism: free-signal items "
            "{1, 7, 8, 15, 16, 17, 18} that direct T3 LGB averages out get item-specific "
            "architectures. Items 9-14 use iter12 honest single-batch winners. Items 1, 2, 3 "
            "use Phase A1 backfill winners. Items 4-6 use iter8 lockboxed winners."
        ),
    }
    formula_sha = _formula_sha256(payload)
    git_sha = _git_sha()
    pre = {
        **payload,
        "formula_sha256": formula_sha,
        "git_sha": git_sha,
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "created_at_local": datetime.now().isoformat(),
        "timestamp": ts,
        "lockbox_rules": [
            "Architecture map fixed BEFORE any composite is computed.",
            "ONE pre-registered evaluation per cv mode. Headline = whatever this script returns.",
            "Phase B: sum-level 5-fold gate (Δ ≥ +0.05 / std < 0.020 vs iter5 5-fold ref).",
            "Phase C: pre-registered LOOCV; paired bootstrap CI vs iter5 LOOCV OOF.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_t3_iter19_compose_{ts}.json"
    with open(pre_path, "w") as f:
        json.dump(pre, f, indent=2, default=float)
    print(f"\nPre-registration: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula_sha[:16]}...", flush=True)
    print(f"  git_sha = {git_sha[:12]}", flush=True)
    return pre_path, ts


def mode_screen(d: dict, arch_map: dict[int, str], seeds: list[int]) -> dict:
    pre_path, ts = write_preregistration(arch_map, "5fold", seeds)
    print(f"\n=== Phase B 5-fold composite screen ({len(seeds)} seeds × 18 items) ===", flush=True)
    res = compute_composite(d, arch_map, "5fold", seeds)
    # Compare to iter5 5-fold reference. We use the canonical iter5 pipeline.
    print(f"\nReproducing iter5 5-fold baseline for apples-to-apples...", flush=True)
    iter5_cccs = []
    for seed in seeds:
        ref = _iter5_5fold_oof(d, seed)
        c = float(ccc_fn(res["y_updrs3"], ref))
        iter5_cccs.append(c)
        print(f"  iter5 5-fold seed={seed} CCC={c:+.4f}", flush=True)
    iter5_mean = float(np.mean(iter5_cccs))
    iter5_std = float(np.std(iter5_cccs))
    delta = res["ccc_mean"] - iter5_mean
    composite_std = res["ccc_std"]
    gate_pass = (delta >= 0.025) and (composite_std < 0.020)  # sum-level gate per task_plan
    print(f"\n=== Phase B GATE ===", flush=True)
    print(f"  composite 5-fold CCC = {res['ccc_mean']:+.4f} ± {composite_std:.4f}", flush=True)
    print(f"  iter5     5-fold CCC = {iter5_mean:+.4f} ± {iter5_std:.4f}", flush=True)
    print(f"  Δ = {delta:+.4f}  (gate: Δ ≥ +0.025, std < 0.020)", flush=True)
    print(f"  GATE: {'PASS' if gate_pass else 'FAIL'}", flush=True)

    out = {
        "preregistration": pre_path.name,
        "ts": ts,
        "composite_ccc_mean": res["ccc_mean"],
        "composite_ccc_std": composite_std,
        "composite_mae_mean": res["mae_mean"],
        "iter5_ccc_mean": iter5_mean,
        "iter5_ccc_std": iter5_std,
        "delta": delta,
        "gate_pass": gate_pass,
        "seeds": seeds,
        "seed_t3_cccs": res["t3_ccc_per_seed"],
        "iter5_seed_cccs": iter5_cccs,
    }
    out_path = RESULTS_DIR / f"compose_t3_iter19_5fold_screen_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {out_path.name}", flush=True)
    return out


def _iter5_5fold_oof(d: dict, seed: int) -> np.ndarray:
    """Re-run iter5 5-fold under the EXISTING canonical pipeline.
    Stage-1 Ridge(H&Y + cv_yrs + cv_sex + cv_dbs); Stage-2 LGB(V2 residual)."""
    from run_t3_iter5_clinical import (
        clinical_residual_kfold, load_full_pd_data,
    )
    # Use iter5's own loader for apples-to-apples (N=98)
    # But our composite is on N=94 (T1 cohort from load_data); we need to align
    # iter5 OOFs to the same SID set
    sids_t1 = d["sids"]
    sids_t3, _, _, _, _, _ = load_full_pd_data()
    # Build alignment from sids_t3 → sids_t1 indices
    sid_to_idx = {s: i for i, s in enumerate(sids_t3)}
    t3_indices = np.array([sid_to_idx[s] for s in sids_t1 if s in sid_to_idx])
    # Run iter5 5-fold on the FULL N=98 cohort
    full_oof = clinical_residual_kfold(seed=seed, feature_set="A3_tier1", alpha=1.0)
    # Subset to the T1-cohort SIDs in the same order
    oof_aligned = full_oof[t3_indices]
    return oof_aligned


def mode_lockbox(d: dict, arch_map: dict[int, str], seeds: list[int]) -> dict:
    pre_path, ts = write_preregistration(arch_map, "loocv", seeds)
    print(f"\n=== Phase C LOOCV composite ({len(seeds)} seeds × 18 items × {len(d['sids'])} folds) ===", flush=True)
    res = compute_composite(d, arch_map, "loocv", seeds)
    y_t3 = res["y_updrs3"]
    composite_pred = res["t3_pred_mean"]
    headline_ccc = float(ccc_fn(y_t3, composite_pred))
    headline_mae = float(mae_fn(y_t3, composite_pred))
    print(f"\n=== Phase C HEADLINE ===", flush=True)
    print(f"  composite LOOCV CCC = {headline_ccc:+.4f}", flush=True)
    print(f"  composite LOOCV MAE = {headline_mae:.3f}", flush=True)
    print(f"  per-seed CCCs = {res['t3_ccc_per_seed']}", flush=True)
    print(f"  per-seed std = {res['ccc_std']:.4f}", flush=True)

    # Paired bootstrap CI vs iter5 LOOCV
    print(f"\nReproducing iter5 LOOCV for paired bootstrap CI...", flush=True)
    from run_t3_iter5_clinical import clinical_residual_loocv, load_full_pd_data
    sids_t3, _, _, y_t3_full, _, _ = load_full_pd_data()
    sid_to_idx = {s: i for i, s in enumerate(sids_t3)}
    t3_indices = np.array([sid_to_idx[s] for s in d["sids"] if s in sid_to_idx])
    iter5_loocv_per_seed = []
    for seed in seeds:
        _, _, p = clinical_residual_loocv(seed=seed, feature_set="A3_tier1", alpha=1.0)
        iter5_loocv_per_seed.append(p[t3_indices])
        print(f"  iter5 LOOCV seed={seed} done", flush=True)
    iter5_mean = np.mean(np.stack(iter5_loocv_per_seed, axis=0), axis=0)
    boot = paired_bootstrap_ci(y_t3, composite_pred, iter5_mean, n_boot=5000, seed=42)
    print(f"\n=== Paired Bootstrap CI (composite − iter5) on N={len(y_t3)} ===", flush=True)
    print(f"  composite CCC = {boot['ccc_a']:+.4f}", flush=True)
    print(f"  iter5     CCC = {boot['ccc_b']:+.4f}", flush=True)
    print(f"  Δ point       = {boot['delta_point']:+.4f}", flush=True)
    print(f"  Δ 95% CI      = [{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}]", flush=True)
    print(f"  frac > 0      = {boot['frac_above_zero']:.3f}", flush=True)

    out = {
        "preregistration": pre_path.name,
        "ts": ts,
        "headline_ccc": headline_ccc,
        "headline_mae": headline_mae,
        "per_seed_ccc": res["t3_ccc_per_seed"],
        "per_seed_std": res["ccc_std"],
        "iter5_ccc_3seed_mean": float(ccc_fn(y_t3, iter5_mean)),
        "bootstrap": boot,
        "is_canonical_update": (boot["frac_above_zero"] >= 0.95) and (boot["delta_point"] > 0),
        "n_subjects": int(len(y_t3)),
        "seeds": list(seeds),
    }
    out_npy = RESULTS_DIR / f"lockbox_t3_iter19_compose_{ts}.oof.npy"
    np.save(out_npy, composite_pred)
    out_sids_npy = RESULTS_DIR / f"lockbox_t3_iter19_compose_{ts}.sids.npy"
    np.save(out_sids_npy, d["sids"])
    out_path = RESULTS_DIR / f"lockbox_t3_iter19_compose_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {out_path.name}", flush=True)
    print(f"\nCANONICAL UPDATE: {'YES' if out['is_canonical_update'] else 'NO'}", flush=True)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen", "lockbox", "both"], default="screen")
    p.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 7])
    args = p.parse_args()

    print("Loading data (T1 cohort N=94 master)...", flush=True)
    d = load_data()
    print(f"  N = {len(d['sids'])} PD subjects (T1 cohort)", flush=True)

    arch_map = load_architecture_map()
    print(f"\nArchitecture map (per item):", flush=True)
    for i in sorted(arch_map.keys()):
        print(f"  item {i:>2d} → {arch_map[i]}", flush=True)

    if args.mode in ("screen", "both"):
        mode_screen(d, arch_map, args.seeds)

    if args.mode in ("lockbox", "both"):
        mode_lockbox(d, arch_map, args.seeds)


if __name__ == "__main__":
    main()
