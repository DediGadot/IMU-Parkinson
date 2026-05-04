"""Per-item screening + lockbox runner with insole-pressure / CoP / GRF features.

Targets the 3 items with measurable headroom whose ceilings depend on
ground-reaction information that is NOT in the body-worn IMU cache:

    item 7  (toe tap)             — current 5-fold best 0.3032, ceiling ≈ 0.40-0.45
    item 12 (postural stability)  — current 5-fold best 0.5550, ceiling ≈ 0.70-0.78
    item 14 (body bradykinesia)   — current 5-fold best 0.2969, ceiling ≈ 0.58-0.68

Pipeline:
1. Load PD data via run_t1_iter4.load_pd_data()
2. Load existing per-item cache (peritem_subj_features.csv) used by run_per_item_v2.
3. Load NEW insole cache (insole_subj_features.csv) built by cache_insole_features.py.
4. Run two new variants per target item:
     item_plus_v2_plus_insole       — LGB on v2 ∪ item ∪ insole
     hy_residual_plus_insole        — Stage-1 Ridge(H&Y) + Stage-2 LGB on v2 ∪ item ∪ insole residual
5. Reference variants (re-screened on the same N for fair comparison):
     v2_baseline, item_plus_v2, hy_residual_item, insole_only
6. 5-fold CCC × 3 seeds for each. If any insole variant beats the prior best
   per-item by ≥ +0.015 5-fold CCC, run a single LOOCV lockbox on that variant
   and save preregistration_peritem_<item>_<variant>_insole.json + OOF .npy.
7. 5-null gate (scrambled-label + canary feature) on every variant.

Output:
   results/peritem_insole_screening_5split.json
   results/peritem_insole_screening_5split.csv
   results/lockbox_peritem_<item>_<variant>_insole_<ts>.json     (only on wins)
   results/lockbox_peritem_<item>_<variant>_insole_<ts>_oof.npy

Usage:
   python3 run_peritem_insole.py                 — full screen + lockbox decisions
   python3 run_peritem_insole.py --skip_lockbox  — screen only, no LOOCV
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn  # noqa: E402
from project_paths import RESULTS_DIR, ensure_dir  # noqa: E402
from run_t1_iter4 import (  # noqa: E402
    load_pd_data,
    kfold_split_stratified,
    impute_fold,
    feature_select_fold,
    train_lgb,
    get_hy_features,
    SEEDS,
)

PERITEM_CACHE = REPO_ROOT / "results" / "peritem_subj_features.csv"
INSOLE_CACHE = REPO_ROOT / "results" / "insole_subj_features.csv"

TARGET_ITEMS = [7, 12, 14]

# Prior-best baseline per item (from existing run_per_item_v2.py 5-fold sweep)
PRIOR_BEST = {7: 0.3032, 12: 0.5550, 14: 0.2969}
LOCKBOX_DELTA = 0.015  # promote-to-LOOCV margin


# ── Data loading ─────────────────────────────────────────────────────────────


def load_data() -> dict:
    """Load v2 + per-item + insole features, all aligned by sid."""
    d = load_pd_data()
    n = len(d["sids"])

    if not PERITEM_CACHE.exists():
        raise FileNotFoundError(f"Missing {PERITEM_CACHE}")
    df_pi = pd.read_csv(PERITEM_CACHE).set_index("sid")
    pi_cols = list(df_pi.columns)
    X_pi = np.full((n, len(pi_cols)), np.nan)
    matched_pi = 0
    for i, sid in enumerate(d["sids"]):
        if sid in df_pi.index:
            X_pi[i] = df_pi.loc[sid, pi_cols].to_numpy(dtype=np.float64)
            matched_pi += 1
    print(f"  Per-item features matched: {matched_pi}/{n} ({len(pi_cols)} features)", flush=True)
    d["X_peritem"] = X_pi
    d["peritem_cols"] = pi_cols

    if not INSOLE_CACHE.exists():
        raise FileNotFoundError(f"Missing {INSOLE_CACHE}")
    df_in = pd.read_csv(INSOLE_CACHE).set_index("sid")
    in_cols = list(df_in.columns)
    X_in = np.full((n, len(in_cols)), np.nan)
    matched_in = 0
    for i, sid in enumerate(d["sids"]):
        if sid in df_in.index:
            X_in[i] = df_in.loc[sid, in_cols].to_numpy(dtype=np.float64)
            matched_in += 1
    print(f"  Insole features matched: {matched_in}/{n} ({len(in_cols)} features)", flush=True)
    d["X_insole"] = X_in
    d["insole_cols"] = in_cols
    return d


def get_item_peritem(d: dict, item: int) -> tuple[np.ndarray, list[str]]:
    """Subset peritem (body-worn IMU) cache to the item's prefix."""
    prefix = "i1718_" if item in (17, 18) else f"i{item}_"
    cols = d["peritem_cols"]
    idx = [i for i, c in enumerate(cols) if c.startswith(prefix)]
    if not idx:
        return np.zeros((len(d["sids"]), 1)), []
    return d["X_peritem"][:, idx], [cols[i] for i in idx]


def get_item_insole(d: dict, item: int) -> tuple[np.ndarray, list[str]]:
    """Subset insole cache to the item's prefix."""
    prefix = f"i{item}_"
    cols = d["insole_cols"]
    idx = [i for i, c in enumerate(cols) if c.startswith(prefix)]
    if not idx:
        return np.zeros((len(d["sids"]), 1)), []
    return d["X_insole"][:, idx], [cols[i] for i in idx]


# ── Variants (all fold-local; mirror inductive contract from run_per_item_v2) ─


def _filter_nan_target(d: dict, item: int) -> tuple[dict, np.ndarray]:
    """Filter subjects with NaN target. Returns filtered d and target y."""
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if not nan_mask.any():
        return d, y
    valid = np.where(~nan_mask)[0]
    d_f = {
        "sids": d["sids"][valid],
        "X_v2": d["X_v2"][valid],
        "X_peritem": d["X_peritem"][valid],
        "peritem_cols": d["peritem_cols"],
        "X_insole": d["X_insole"][valid],
        "insole_cols": d["insole_cols"],
        "hy": d["hy"][valid],
        "items": {k: v[valid] if isinstance(v, np.ndarray) else v for k, v in d["items"].items()},
        "feat_cols": d.get("feat_cols"),
        "t1": d["t1"][valid] if "t1" in d else None,
    }
    return d_f, d_f["items"][item]


def _build_X(d: dict, item: int, parts: list[str]) -> np.ndarray:
    """Concatenate the named feature blocks horizontally.
    Parts: any of "v2", "item_imu", "item_insole".
    """
    blocks = []
    for p in parts:
        if p == "v2":
            blocks.append(d["X_v2"])
        elif p == "item_imu":
            X, cols = get_item_peritem(d, item)
            if cols:
                blocks.append(X)
        elif p == "item_insole":
            X, cols = get_item_insole(d, item)
            if cols:
                blocks.append(X)
        else:
            raise ValueError(p)
    if not blocks:
        raise ValueError("No feature blocks")
    return np.hstack(blocks)


def variant_v2_baseline(d: dict, item: int, splits, seed: int) -> np.ndarray:
    y = d["items"][item]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_v2(d: dict, item: int, splits, seed: int) -> np.ndarray:
    y = d["items"][item]
    X = _build_X(d, item, ["v2", "item_imu"])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_insole_only(d: dict, item: int, splits, seed: int) -> np.ndarray:
    """LGB on insole features only (sanity check for additional signal)."""
    y = d["items"][item]
    X_in, cols = get_item_insole(d, item)
    if not cols:
        return np.full(len(y), np.nan)
    n = len(y)
    oof = np.zeros(n)
    k = min(500, X_in.shape[1])
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_in[tr], X_in[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=k, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_v2_plus_insole(d: dict, item: int, splits, seed: int) -> np.ndarray:
    y = d["items"][item]
    X = _build_X(d, item, ["v2", "item_imu", "item_insole"])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_item(d: dict, item: int, splits, seed: int) -> np.ndarray:
    """Stage-1 Ridge(H&Y) + Stage-2 LGB on (v2 ∪ item-imu) residual."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X = _build_X(d, item, ["v2", "item_imu"])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        oof[te] = s1_te + train_lgb(Xtr, resid_tr, Xte, seed)
    return oof


def variant_hy_residual_plus_insole(d: dict, item: int, splits, seed: int) -> np.ndarray:
    """Stage-1 Ridge(H&Y) + Stage-2 LGB on (v2 ∪ item-imu ∪ item-insole) residual."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X = _build_X(d, item, ["v2", "item_imu", "item_insole"])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        oof[te] = s1_te + train_lgb(Xtr, resid_tr, Xte, seed)
    return oof


VARIANTS = {
    "v2_baseline": variant_v2_baseline,
    "item_plus_v2": variant_item_plus_v2,
    "insole_only": variant_insole_only,
    "item_plus_v2_plus_insole": variant_item_plus_v2_plus_insole,
    "hy_residual_item": variant_hy_residual_item,
    "hy_residual_plus_insole": variant_hy_residual_plus_insole,
}


# ── 5-null gate ──────────────────────────────────────────────────────────────


def run_null_gate(d: dict, item: int, variant: str, seed: int = 42) -> dict:
    """Scrambled-label + canary feature null tests. Both should give CCC ≈ 0."""
    fn = VARIANTS[variant]
    y = d["items"][item]
    splits = kfold_split_stratified(y, 5, seed=seed)
    rng = np.random.RandomState(seed)
    null = {}

    # 1. Scrambled-label
    y_scram = rng.permutation(y)
    d_scram = {**d, "items": {**d["items"], item: y_scram}}
    try:
        oof = fn(d_scram, item, splits, seed)
        null["scrambled_label_ccc"] = float(ccc_fn(y_scram, oof))
    except Exception as e:
        null["scrambled_label_error"] = str(e)

    # 2. Canary feature inserted into V2 block
    canary = rng.randn(len(y))
    d_canary = {**d, "X_v2": np.hstack([d["X_v2"], canary[:, None]])}
    try:
        oof = fn(d_canary, item, splits, seed)
        null["canary_feature_ccc"] = float(ccc_fn(y, oof))
    except Exception as e:
        null["canary_feature_error"] = str(e)

    # 3. SID-shuffle (shuffle insole rows, keep item-imu rows aligned to original SID)
    if "item" in variant or "insole" in variant:
        perm = rng.permutation(len(y))
        d_sid = {**d, "X_insole": d["X_insole"][perm]}
        try:
            oof = fn(d_sid, item, splits, seed)
            null["sid_shuffle_insole_ccc"] = float(ccc_fn(y, oof))
        except Exception as e:
            null["sid_shuffle_insole_error"] = str(e)
    return null


# ── Driver ───────────────────────────────────────────────────────────────────


def run_5fold(d: dict, item: int, variant: str, seeds: list[int]) -> dict:
    d_f, y = _filter_nan_target(d, item)
    fn = VARIANTS[variant]
    per_seed = []
    for s in seeds:
        splits = kfold_split_stratified(y, 5, seed=s)
        oof = fn(d_f, item, splits, s)
        per_seed.append(full_metrics(y, oof))
    nulls = run_null_gate(d_f, item, variant, seed=seeds[0])
    return {
        "item": item, "variant": variant, "eval": "5split",
        "n_subjects": int(len(y)), "seeds": list(seeds),
        "ccc_mean": float(np.mean([m["ccc"] for m in per_seed])),
        "ccc_std": float(np.std([m["ccc"] for m in per_seed])),
        "mae_mean": float(np.mean([m["mae"] for m in per_seed])),
        "per_seed": per_seed,
        "null_tests": nulls,
    }


def run_loocv_one_seed(args) -> tuple[int, np.ndarray]:
    """ProcessPool-friendly LOOCV worker. Refits at one seed, returns (seed, oof)."""
    d, item, variant, seed = args
    d_f, y = _filter_nan_target(d, item)
    n = len(y)
    splits = [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]
    fn = VARIANTS[variant]
    oof = fn(d_f, item, splits, seed)
    return seed, oof


def run_loocv_lockbox(d: dict, item: int, variant: str, seeds: list[int],
                      out_dir: Path) -> dict:
    d_f, y = _filter_nan_target(d, item)
    n = len(y)
    print(f"  Lockbox LOOCV  item={item} variant={variant}  N={n}  seeds={seeds}", flush=True)
    t0 = time.time()
    per_seed = []
    oof_acc = np.zeros(n)
    # Run seeds in parallel — outer loop is too cheap to bother fanning per-fold here.
    args_list = [(d, item, variant, s) for s in seeds]
    with ProcessPoolExecutor(max_workers=min(len(seeds), 4)) as ex:
        for seed, oof in ex.map(run_loocv_one_seed, args_list):
            per_seed.append({"seed": seed, **full_metrics(d_f["items"][item], oof)})
            oof_acc = oof_acc + oof
            print(f"    seed={seed} ccc={per_seed[-1]['ccc']:.4f} elapsed={time.time()-t0:.1f}s", flush=True)
    oof_mean = oof_acc / len(seeds)
    nulls = run_null_gate(d_f, item, variant, seed=seeds[0])
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "preregistration_id": f"peritem_{item}_{variant}_insole_{ts}",
        "item": item, "variant": variant, "eval": "loocv",
        "n_subjects": int(n), "seeds": list(seeds),
        "ccc_mean": float(np.mean([m["ccc"] for m in per_seed])),
        "ccc_std": float(np.std([m["ccc"] for m in per_seed])),
        "mae_mean": float(np.mean([m["mae"] for m in per_seed])),
        "per_seed": per_seed,
        "oof_mean": oof_mean.tolist(),
        "y_true": y.tolist(),
        "null_tests": nulls,
        "wall_clock_s": float(time.time() - t0),
    }
    out_path = out_dir / f"lockbox_peritem_{item}_{variant}_insole_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    np.save(out_dir / f"lockbox_peritem_{item}_{variant}_insole_{ts}_oof.npy", oof_mean)
    print(f"  → wrote {out_path}", flush=True)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--items", type=int, nargs="+", default=TARGET_ITEMS)
    p.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    p.add_argument("--skip_lockbox", action="store_true")
    p.add_argument("--out_dir", type=str, default=str(RESULTS_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    print("Loading data...", flush=True)
    d = load_data()
    print(
        f"  N = {len(d['sids'])} PD subjects, "
        f"{d['X_v2'].shape[1]} V2 features, "
        f"{d['X_peritem'].shape[1]} per-item IMU features, "
        f"{d['X_insole'].shape[1]} insole features",
        flush=True,
    )

    rows = []
    t_total = time.time()
    for item in args.items:
        prior = PRIOR_BEST.get(item, 0.0)
        print(f"\n=== item {item} (prior best 5-fold CCC = {prior:.4f}) ===", flush=True)
        for variant in VARIANTS:
            t0 = time.time()
            r = run_5fold(d, item, variant, args.seeds)
            scram = r["null_tests"].get("scrambled_label_ccc", float("nan"))
            canary = r["null_tests"].get("canary_feature_ccc", float("nan"))
            print(
                f"  [{time.time()-t0:5.1f}s] {variant:30s} "
                f"ccc={r['ccc_mean']:+.4f} ± {r['ccc_std']:.4f}  "
                f"mae={r['mae_mean']:5.3f}  "
                f"scram={scram:+.3f} canary={canary:+.3f}",
                flush=True,
            )
            rows.append(r)

    # Save screening table
    df = pd.DataFrame([
        {
            "item": r["item"],
            "variant": r["variant"],
            "ccc_mean": r["ccc_mean"],
            "ccc_std": r["ccc_std"],
            "mae_mean": r["mae_mean"],
            "scrambled_label_ccc": r["null_tests"].get("scrambled_label_ccc", np.nan),
            "canary_feature_ccc": r["null_tests"].get("canary_feature_ccc", np.nan),
            "sid_shuffle_insole_ccc": r["null_tests"].get("sid_shuffle_insole_ccc", np.nan),
        }
        for r in rows
    ])
    csv_path = out_dir / "peritem_insole_screening_5split.csv"
    json_path = out_dir / "peritem_insole_screening_5split.json"
    df.to_csv(csv_path, index=False)
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2, default=float)
    print(f"\nWrote {csv_path}", flush=True)

    # Promotion decisions: per item, find the best insole variant; if it beats prior best by ≥ delta, lockbox.
    if args.skip_lockbox:
        print("\n--skip_lockbox set; not running LOOCV.", flush=True)
        return

    print("\n=== Lockbox decisions ===", flush=True)
    for item in args.items:
        prior = PRIOR_BEST.get(item, 0.0)
        # Best of the new (insole) variants
        item_rows = [r for r in rows if r["item"] == item]
        insole_variants = ["item_plus_v2_plus_insole", "hy_residual_plus_insole", "insole_only"]
        cand = [r for r in item_rows if r["variant"] in insole_variants]
        if not cand:
            continue
        best = max(cand, key=lambda r: r["ccc_mean"])
        delta = best["ccc_mean"] - prior
        promote = delta >= LOCKBOX_DELTA
        # Sanity: scrambled-label and canary CCC must be near zero (|x| < 0.15)
        nulls = best["null_tests"]
        scram_ok = abs(nulls.get("scrambled_label_ccc", 1.0)) < 0.15
        canary_ok = abs(nulls.get("canary_feature_ccc", 1.0)) < 0.15
        print(
            f"  item {item}: best_5fold={best['ccc_mean']:.4f} ({best['variant']}) "
            f"prior={prior:.4f} Δ={delta:+.4f}  "
            f"scram_ok={scram_ok} canary_ok={canary_ok}  "
            f"→ {'PROMOTE' if (promote and scram_ok and canary_ok) else 'HOLD'}",
            flush=True,
        )
        if promote and scram_ok and canary_ok:
            run_loocv_lockbox(d, item, best["variant"], args.seeds, out_dir)

    print(f"\nTotal wall clock: {time.time()-t_total:.1f}s", flush=True)


if __name__ == "__main__":
    main()
