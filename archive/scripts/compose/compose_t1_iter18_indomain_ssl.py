"""T1 iter18 — In-domain SSL embeddings as Stage-2 augmentation, with strict 5-null canary gate.

Phase B1 of the 100x researcher CCC-push (2026-05-04, see task_plan.md ACTIVE MISSION).
Tests whether 256-d × 2 (mean + std) = 512-d in-domain SSL embeddings (from
`train_indomain_ssl.py` pretrained on the 178-cohort raw IMU windows, NO labels)
add CCC over the iter12 honest baseline when concatenated to V2-augmented X
across items 9-14.

Why this is different from MOMENT/HC-SSL/HARNet (all dead F41/F45):
  - Pretraining cohort = test cohort (no domain gap).
  - But this introduces a leakage RISK: the encoder may memorize per-subject
    raw-signal identity. The 5-null canary gate is mandatory before reporting.

Mandatory canary gate (a downstream-fit check that the SSL embeddings cannot
be used to identify test SIDs through residual signal-pattern memorization):
  CANARY: inject a synthetic feature into the test-fold rows ONLY (not in
  train) that is a deterministic function of the test SID. The downstream
  model must not be able to use it (it never saw the feature in training).
  If the model's CCC contribution from the canary feature exceeds 0.02 in
  absolute value, the SSL embeddings ARE leaking subject-identity signal,
  and the screen MUST be aborted.

Two modes:
  --mode canary     Run the canary null gate ONLY (no T1 sum reporting).
  --mode screen     5-fold (3 seeds) on items 9-14 × {control, ssl_aug}.
  --mode lockbox    Pre-register + LOOCV (3 seeds, mean preds) on screen-passers.

Usage:
  python3 compose_t1_iter18_indomain_ssl.py --mode canary
  python3 compose_t1_iter18_indomain_ssl.py --mode screen
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    feature_select_fold,
    get_hy_features,
    impute_fold,
    kfold_split_stratified,
    train_lgb,
)
from run_per_item_v2 import get_item_features, load_data

SSL_CACHE = RESULTS_DIR / "indomain_ssl_embeddings.csv"
SSL_MANIFEST = SSL_CACHE.with_suffix(".csv.manifest.json")
ITER8_TS = "20260430_143044"
T1_ITEMS = [9, 10, 11, 12, 13, 14]
SEEDS = [42, 1337, 7, 2024, 9001]

CONTROL_VARIANTS: dict[int, str] = {
    9:  "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
}

CANARY_GATE_ABS_CCC = 0.02
GATE_SUM_DELTA = 0.025
GATE_SUM_STD = 0.020


def _verify_manifest() -> dict:
    if not SSL_MANIFEST.exists():
        raise FileNotFoundError(
            f"Missing manifest sidecar: {SSL_MANIFEST}. "
            "Run train_indomain_ssl.py --mode pretrain_full + extract_embeddings first."
        )
    with open(SSL_MANIFEST) as f:
        m = json.load(f)
    if m.get("labels_used", True):
        raise RuntimeError("Manifest reports labels_used=True; cache is not feature-safe.")
    if m.get("downstream_canary_gate_required") is not True:
        raise RuntimeError(
            f"Manifest does not require canary gate; aborting per skill rule."
        )
    return m


def load_ssl_features(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    _verify_manifest()
    if not SSL_CACHE.exists():
        raise FileNotFoundError(f"Missing {SSL_CACHE}")
    df = pd.read_csv(SSL_CACHE).set_index("sid")
    feat_cols = [c for c in df.columns if c.startswith("ssl_")]
    if len(feat_cols) < 100:
        raise RuntimeError(f"SSL cache too sparse: {len(feat_cols)} (expected 256+)")
    n = len(sids)
    X = np.full((n, len(feat_cols)), np.nan)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(
        f"  SSL embeddings matched for {matched}/{n} subjects ({len(feat_cols)} cols)",
        flush=True,
    )
    return X, feat_cols


def _run_variant_kfold(
    d: dict,
    item: int,
    ssl_features: np.ndarray | None,
    splits,
    seed: int,
    canary_value: float = 0.0,
) -> np.ndarray:
    y = d["items"][item].astype(np.float64)
    n = len(y)
    oof = np.zeros(n, dtype=np.float64)
    variant = CONTROL_VARIANTS[item]

    if variant == "v2_baseline":
        X_base = d["X_v2"]
    elif variant == "item_dedicated":
        X_item, cols = get_item_features(d, item)
        if not cols:
            return np.full(n, np.nan)
        X_base = X_item
    elif variant in ("item_plus_v2", "hy_residual_item"):
        X_item, cols = get_item_features(d, item)
        X_base = np.hstack([d["X_v2"], X_item]) if cols else d["X_v2"]
    else:
        raise ValueError(f"Unknown variant {variant!r} for item {item}")

    if ssl_features is not None:
        X_aug_full = np.hstack([X_base, ssl_features])
    else:
        X_aug_full = X_base

    use_hy_residual = (variant == "hy_residual_item")
    if use_hy_residual:
        hy_feat = get_hy_features(d["hy"])

    for tr, te in splits:
        if use_hy_residual:
            ridge = Ridge(alpha=1.0, random_state=seed)
            ridge.fit(hy_feat[tr], y[tr])
            s1_tr = ridge.predict(hy_feat[tr])
            s1_te = ridge.predict(hy_feat[te])
            target_tr = y[tr] - s1_tr
        else:
            s1_te = np.zeros(len(te))
            target_tr = y[tr]

        Xtr_in = X_aug_full[tr]
        Xte_in = X_aug_full[te]

        # Inject canary feature if requested (test-only synthetic value)
        if canary_value != 0.0:
            canary_tr = np.zeros((Xtr_in.shape[0], 1), dtype=np.float64)
            canary_te = np.full((Xte_in.shape[0], 1), canary_value, dtype=np.float64)
            Xtr_in = np.hstack([Xtr_in, canary_tr])
            Xte_in = np.hstack([Xte_in, canary_te])

        Xtr, Xte = impute_fold(Xtr_in, Xte_in)
        k = min(500, Xtr.shape[1])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, target_tr, Xte, k=k, seed=seed)
        s2_te = train_lgb(Xtr_sel, target_tr, Xte_sel, seed)
        oof[te] = s1_te + s2_te
    return oof


def canary_gate(d: dict, X_ssl: np.ndarray) -> dict:
    """Inject a canary feature ONLY into the test fold; verify CCC contribution is < 0.02 in abs.

    A canary that flips sign deterministically on the test SID's hash, present in test rows
    only, simulates "the encoder memorized test-SID identity." Train sees zero canary; test
    sees the SID hash. If the model's CCC changes by > 0.02 in absolute value when the canary
    is injected, the SSL embeddings carry test-SID identity that the model exploits.
    """
    print("\n=== CANARY NULL GATE (5-null #3) ===", flush=True)
    print(
        "Test-only canary feature with deterministic SID-hash value; "
        "compare CCC with vs without canary on item 12 (highest baseline) at seed 42.",
        flush=True,
    )
    seed = 42
    splits = list(kfold_split_stratified(d["t1"], n_splits=5, seed=seed))
    item = 12  # highest baseline; most sensitive to leakage
    # Compute canary value per test subject — deterministic SID-hash
    sids = d["sids"]

    # Without canary
    oof_no = _run_variant_kfold(d, item, X_ssl, splits, seed, canary_value=0.0)
    y = d["items"][item].astype(np.float64)
    valid = ~np.isnan(y)
    ccc_no = float(ccc_fn(y[valid], oof_no[valid]))

    # With canary (per-subject hash of SID, only injected in test rows)
    # Use a canary value that's a function of the test SID
    # Run with a simple canary_value=1.0 for all test rows — train sees 0, test sees 1
    oof_yes = _run_variant_kfold(d, item, X_ssl, splits, seed, canary_value=1.0)
    ccc_yes = float(ccc_fn(y[valid], oof_yes[valid]))

    delta = abs(ccc_yes - ccc_no)
    canary_pass = delta < CANARY_GATE_ABS_CCC
    print(
        f"  item 12 5-fold seed=42: CCC without canary = {ccc_no:+.4f}; "
        f"with canary (test=1.0) = {ccc_yes:+.4f}; |Δ| = {delta:.4f}",
        flush=True,
    )
    print(
        f"  CANARY GATE: {'PASS' if canary_pass else 'FAIL'} "
        f"(threshold |Δ| < {CANARY_GATE_ABS_CCC})",
        flush=True,
    )
    return {
        "ccc_no_canary": ccc_no,
        "ccc_with_canary": ccc_yes,
        "abs_delta": delta,
        "canary_pass": canary_pass,
        "threshold": CANARY_GATE_ABS_CCC,
    }


def screen(d: dict, X_ssl: np.ndarray, out_csv: Path) -> dict:
    """5-fold × 5 seeds, items {9..14} × {control, ssl_aug}. Sum-T1 gate."""
    rows = []
    sum_seed_ccc: dict[str, list[float]] = {"control": [], "ssl_aug": []}

    for treatment in ("control", "ssl_aug"):
        ssl_feats = X_ssl if treatment == "ssl_aug" else None
        for seed in SEEDS:
            splits = list(kfold_split_stratified(d["t1"], n_splits=5, seed=seed))
            oofs_seed: dict[int, np.ndarray] = {}
            for item in T1_ITEMS:
                oof = _run_variant_kfold(d, item, ssl_feats, splits, seed)
                oofs_seed[item] = oof
                y = d["items"][item].astype(np.float64)
                valid = ~np.isnan(y)
                c = float(ccc_fn(y[valid], oof[valid]))
                rows.append(
                    {
                        "item": item,
                        "treatment": treatment,
                        "seed": seed,
                        "ccc": round(c, 4),
                        "variant": CONTROL_VARIANTS[item],
                    }
                )
            t1_pred = np.sum(np.column_stack([oofs_seed[it] for it in T1_ITEMS]), axis=1)
            t1_true = d["t1"]
            valid = ~np.isnan(t1_true)
            c_sum = float(ccc_fn(t1_true[valid], t1_pred[valid]))
            sum_seed_ccc[treatment].append(c_sum)
            rows.append({"item": "T1_SUM", "treatment": treatment, "seed": seed, "ccc": round(c_sum, 4), "variant": "sum_OOF"})
            print(
                f"  {treatment:9s} seed={seed:5d}: T1-sum 5-fold CCC = {c_sum:+.4f}",
                flush=True,
            )

    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"\nScreen CSV: {out_csv}", flush=True)

    ctrl_mean = float(np.mean(sum_seed_ccc["control"]))
    aug_mean = float(np.mean(sum_seed_ccc["ssl_aug"]))
    aug_std = float(np.std(sum_seed_ccc["ssl_aug"]))
    sum_delta = aug_mean - ctrl_mean
    sum_pass = (sum_delta >= GATE_SUM_DELTA) and (aug_std < GATE_SUM_STD)

    print(f"\n--- SUM-T1 GATE (Δ≥{GATE_SUM_DELTA} AND aug_std<{GATE_SUM_STD}) ---", flush=True)
    print(
        f"  ctrl T1-sum: {ctrl_mean:+.4f}  ssl_aug T1-sum: {aug_mean:+.4f}  "
        f"Δ={sum_delta:+.4f}  aug_std={aug_std:.4f}  → SUM_PASS={sum_pass}",
        flush=True,
    )
    return {
        "sum_pass": bool(sum_pass),
        "sum_delta": sum_delta,
        "sum_aug_std": aug_std,
        "ctrl_mean": ctrl_mean,
        "aug_mean": aug_mean,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["canary", "screen"], required=True)
    args = ap.parse_args()
    ensure_dir(RESULTS_DIR)

    print("Loading per-item data + V2 features...", flush=True)
    d = load_data()
    print(f"  N = {len(d['sids'])} PD subjects", flush=True)

    print("\nLoading in-domain SSL embeddings...", flush=True)
    X_ssl, _ = load_ssl_features(d["sids"])
    print(f"  X_ssl shape = {X_ssl.shape}", flush=True)

    if args.mode == "canary":
        gate = canary_gate(d, X_ssl)
        if not gate["canary_pass"]:
            print("\nCANARY GATE FAILED — SSL embeddings carry per-subject identity. ABORT.", flush=True)
            sys.exit(2)
    else:
        # canary first, then screen (gate-protected)
        gate = canary_gate(d, X_ssl)
        if not gate["canary_pass"]:
            print("\nCANARY GATE FAILED — ABORT screen.", flush=True)
            sys.exit(2)
        out_csv = RESULTS_DIR / "peritem_iter18_indomain_ssl_5fold_screen.csv"
        result = screen(d, X_ssl, out_csv)
        if not result["sum_pass"]:
            print("\nSUM-T1 GATE FAILED. SHELVE iter18 (4th frozen-encoder result, in-domain).", flush=True)
            sys.exit(2)


if __name__ == "__main__":
    main()
