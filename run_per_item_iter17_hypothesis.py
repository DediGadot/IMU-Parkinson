"""Per-item iter17 — Hypothesis-restricted submodels for items {4, 6, 15, 16, 17, 18}.

Phase A2 of the 100x researcher CCC-push (2026-05-03 PM, see task_plan.md ACTIVE MISSION).

These six items currently have CCC ∈ {-0.04, 0.08, -0.09, 0.08, 0.14, 0.25}, all
< 0.30 — well below their clinically plausible ceilings (0.18–0.40 per the
2026-04-30 codex+gemini consensus). The V2 feature pool dilutes their narrow
clinical signal under K=500 selection. This iteration tests whether tight
hypothesis-restricted feature sets (12-32 features per item, anchored on the
clinically-relevant sensor/channel/window — see cache_item_specific_features.py)
beat the V2-only baseline.

Variants screened per item:
  item_only             — LGB on the ~12-32 item-specific features ONLY.
  item_plus_v2          — LGB on (item-specific ⊕ V2) — same K=500 selector.
  hy_residual_item_v2   — Stage-1 Ridge(H&Y) + Stage-2 LGB on (item-specific ⊕ V2).

Per-item promotion gate (screen → lockbox):
  ΔCCC ≥ +0.05 over the published baseline for that item AND
  best-variant seed std < 0.02 across 5 seeds [42, 1337, 7, 2024, 9001].
Items that pass get a per-item LOOCV lockbox with 3-seed mean preds.

Usage:

    python3 run_per_item_iter17_hypothesis.py --mode screen
        5-fold (5 seeds) on items × variants. Writes
        results/peritem_iter17_hypothesis_5fold_screen.csv.

    python3 run_per_item_iter17_hypothesis.py --mode lockbox \\
        --gated_items 6,17 --gated_variants item_only,hy_residual_item_v2
        Pre-registers + runs LOOCV (3 seeds, mean preds) on the gated
        (item, variant) pairs. Writes lockbox files per item.
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
from run_per_item_v2 import load_data

ITEM_CACHE = RESULTS_DIR / "item_specific_features.csv"
ITEM_MANIFEST = RESULTS_DIR / "item_specific_features.csv.manifest.json"
# Items 4, 6, 15, 18 already screened in iter17 (2026-05-03); items 7, 8 new in
# T3 push 2026-05-04 (iter19). Items 16, 17 retried in case extended cache shifts
# behavior. Items 15 and 18 wins preserved in existing OOF .npy files (not re-run).
TARGET_ITEMS = [7, 8, 16, 17]
SEEDS = [42, 1337, 7, 2024, 9001]
LOCKBOX_SEEDS = [42, 1337, 7]

# Published per-item baselines (mean across 3 seeds under iter8/iter12 best variant).
# These are the pre-registered comparators; gate is ΔCCC ≥ +0.05 vs these.
BASELINE_CCC: dict[int, float] = {
    4: 0.08,
    6: -0.04,
    7: 0.27,   # toe-tap surrogate; iter5 5-fold mean from CLAUDE.md per-item table
    8: 0.26,   # leg-agility surrogate; iter5 5-fold mean
    15: -0.09,
    16: 0.08,
    17: 0.14,
    18: 0.25,
}
GATE_DELTA = 0.05
GATE_STD = 0.02

VARIANTS = ["item_only", "item_plus_v2", "hy_residual_item_v2"]


def _verify_manifest() -> dict:
    if not ITEM_MANIFEST.exists():
        raise FileNotFoundError(
            f"Missing manifest sidecar: {ITEM_MANIFEST}. Run cache_item_specific_features.py first."
        )
    with open(ITEM_MANIFEST) as f:
        m = json.load(f)
    if m.get("labels_used", True):
        raise RuntimeError("Manifest reports labels_used=True; cache is not feature-safe.")
    if m.get("leakage_status") != "clean_by_construction":
        raise RuntimeError(
            f"Manifest leakage_status={m.get('leakage_status')!r} != 'clean_by_construction'."
        )
    return m


def load_item_features(sids: np.ndarray, item: int) -> tuple[np.ndarray, list[str]]:
    """Return aligned item-specific features (n, k_item) for the given SID order."""
    _verify_manifest()
    if not ITEM_CACHE.exists():
        raise FileNotFoundError(f"Missing {ITEM_CACHE}; run cache_item_specific_features.py")
    df = pd.read_csv(ITEM_CACHE).set_index("sid")
    prefix = f"i{item}_"
    feat_cols = [c for c in df.columns if c.startswith(prefix)]
    if not feat_cols:
        raise RuntimeError(f"No item {item} features found (prefix={prefix!r})")
    n = len(sids)
    X = np.full((n, len(feat_cols)), np.nan)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(
        f"  item {item} features matched for {matched}/{n} subjects ({len(feat_cols)} cols)",
        flush=True,
    )
    return X, feat_cols


def _run_variant_kfold(
    d: dict,
    item: int,
    X_item: np.ndarray,
    variant: str,
    splits,
    seed: int,
) -> np.ndarray:
    y = d["items"][item].astype(np.float64)
    n = len(y)
    oof = np.zeros(n, dtype=np.float64)

    if variant == "item_only":
        X_base = X_item
        use_hy = False
    elif variant == "item_plus_v2":
        X_base = np.hstack([d["X_v2"], X_item])
        use_hy = False
    elif variant == "hy_residual_item_v2":
        X_base = np.hstack([d["X_v2"], X_item])
        use_hy = True
    else:
        raise ValueError(f"Unknown variant {variant!r}")

    if use_hy:
        hy_feat = get_hy_features(d["hy"])

    for tr, te in splits:
        # Filter NaN train labels (items 17, 18 have partial coverage among PD).
        y_tr_full = y[tr]
        valid_tr_mask = ~np.isnan(y_tr_full)
        if valid_tr_mask.sum() < 10:
            # Not enough training data; mark fold as NaN
            oof[te] = np.nan
            continue
        tr_valid = tr[valid_tr_mask]
        if use_hy:
            ridge = Ridge(alpha=1.0, random_state=seed)
            ridge.fit(hy_feat[tr_valid], y[tr_valid])
            s1_tr = ridge.predict(hy_feat[tr_valid])
            s1_te = ridge.predict(hy_feat[te])
            target_tr = y[tr_valid] - s1_tr
        else:
            s1_te = np.zeros(len(te))
            target_tr = y[tr_valid]
        Xtr, Xte = impute_fold(X_base[tr_valid], X_base[te])
        k = min(500, Xtr.shape[1])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, target_tr, Xte, k=k, seed=seed)
        s2_te = train_lgb(Xtr_sel, target_tr, Xte_sel, seed)
        oof[te] = s1_te + s2_te
    return oof


def _build_loo_splits(n: int) -> list[tuple[np.ndarray, np.ndarray]]:
    splits = []
    all_idx = np.arange(n)
    for i in range(n):
        tr = np.delete(all_idx, i)
        te = np.array([i])
        splits.append((tr, te))
    return splits


def screen(d: dict, out_csv: Path) -> dict:
    rows = []
    per_item_variant_seed_ccc: dict[tuple[int, str], list[float]] = {}

    for item in TARGET_ITEMS:
        X_item, _ = load_item_features(d["sids"], item)
        for variant in VARIANTS:
            seed_cccs = []
            for seed in SEEDS:
                splits = list(kfold_split_stratified(d["t1"], n_splits=5, seed=seed))
                # Use item target for stratification only via t1 binning (proxy);
                # the actual prediction target is the item score below.
                oof = _run_variant_kfold(d, item, X_item, variant, splits, seed)
                y = d["items"][item].astype(np.float64)
                valid = ~np.isnan(y)
                c = float(ccc_fn(y[valid], oof[valid]))
                seed_cccs.append(c)
                rows.append(
                    {
                        "item": item,
                        "variant": variant,
                        "seed": seed,
                        "ccc": round(c, 4),
                    }
                )
            per_item_variant_seed_ccc[(item, variant)] = seed_cccs
            mn, sd = float(np.mean(seed_cccs)), float(np.std(seed_cccs))
            print(
                f"  item {item:2d}  {variant:24s}: 5-fold CCC = {mn:+.4f} ± {sd:.4f}",
                flush=True,
            )

    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"\nScreen CSV: {out_csv}", flush=True)

    # Per-item promotion gate
    print(
        f"\n--- PROMOTION GATE (require ΔCCC ≥ {GATE_DELTA} vs published baseline AND seed_std < {GATE_STD}) ---",
        flush=True,
    )
    summaries = []
    passers: list[tuple[int, str]] = []
    for item in TARGET_ITEMS:
        baseline = BASELINE_CCC[item]
        best_variant = None
        best_mean = -1e9
        best_std = 0.0
        for variant in VARIANTS:
            cccs = per_item_variant_seed_ccc[(item, variant)]
            mn, sd = float(np.mean(cccs)), float(np.std(cccs))
            if mn > best_mean:
                best_mean = mn
                best_std = sd
                best_variant = variant
        delta = best_mean - baseline
        passes = (delta >= GATE_DELTA) and (best_std < GATE_STD)
        marker = "  PASS" if passes else "  --  "
        print(
            f"  item {item:2d}: best variant = {best_variant:24s}  "
            f"CCC = {best_mean:+.4f} ± {best_std:.4f}  "
            f"baseline = {baseline:+.4f}  Δ = {delta:+.4f}  {marker}",
            flush=True,
        )
        summaries.append(
            {
                "item": item,
                "best_variant": best_variant,
                "best_mean": round(best_mean, 4),
                "best_std": round(best_std, 4),
                "baseline": baseline,
                "delta": round(delta, 4),
                "passes": bool(passes),
            }
        )
        if passes:
            passers.append((item, best_variant))

    print(f"\nPassers: {passers}", flush=True)
    overall_pass = bool(passers)
    return {
        "summaries": summaries,
        "passers": passers,
        "overall_pass": overall_pass,
    }


def _formula_sha256() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def lockbox_one(d: dict, item: int, variant: str, X_item: np.ndarray, ts: str) -> dict:
    """LOOCV (3 seeds, mean preds) for one (item, variant) pair."""
    n = len(d["sids"])
    splits = _build_loo_splits(n)
    seed_oofs = []
    for seed in LOCKBOX_SEEDS:
        t0 = time.time()
        oof = _run_variant_kfold(d, item, X_item, variant, splits, seed)
        seed_oofs.append(oof)
        print(
            f"  item {item} {variant} seed={seed}: LOOCV done in {time.time()-t0:.1f}s",
            flush=True,
        )
    mean_oof = np.mean(np.stack(seed_oofs, axis=0), axis=0)
    out_npy = RESULTS_DIR / f"lockbox_peritem_{item}_iter17hyp_{variant}_{ts}.oof.npy"
    np.save(out_npy, mean_oof)
    y = d["items"][item].astype(np.float64)
    valid = ~np.isnan(y)
    headline = full_metrics(y[valid], mean_oof[valid], label=f"peritem_{item}_iter17hyp")
    seed_cccs = [float(ccc_fn(y[valid], so[valid])) for so in seed_oofs]
    headline.update(
        {
            "item": item,
            "variant": variant,
            "n_subjects_valid": int(valid.sum()),
            "seed_cccs": seed_cccs,
            "seed_std": round(float(np.std(seed_cccs)), 4),
            "baseline_ccc": BASELINE_CCC[item],
            "delta_vs_baseline": round(float(headline["ccc"]) - BASELINE_CCC[item], 4),
            "is_lockbox_headline": True,
        }
    )
    out_json = RESULTS_DIR / f"lockbox_peritem_{item}_iter17hyp_{variant}_{ts}.json"
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(
        f"  item {item} ({variant}) LOOCV: CCC={headline['ccc']:.4f}  "
        f"baseline={BASELINE_CCC[item]:.4f}  Δ={headline['delta_vs_baseline']:+.4f}",
        flush=True,
    )
    return headline


def lockbox(d: dict, gated_pairs: list[tuple[int, str]]) -> None:
    n = len(d["sids"])
    if not gated_pairs:
        raise ValueError("lockbox called with no gated pairs")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha256(),
        "experiment": "Per-item iter17 — Hypothesis-restricted submodels, gated lockbox",
        "rationale": (
            "Phase A2 of 100x researcher CCC-push. The V2 feature pool dilutes the narrow "
            "clinical signal of items {4, 6, 15, 16, 17, 18}; this iteration tests whether "
            "tight hypothesis-restricted feature sets (~12-32 features per item, anchored on "
            "clinically relevant sensors/channels/windows) beat V2 alone. Lockbox is run ONLY "
            "on (item, variant) pairs that passed the screen gate "
            "(ΔCCC ≥ +0.05 vs published baseline AND seed_std < 0.02)."
        ),
        "item_cache_path": str(ITEM_CACHE),
        "item_cache_sha256": json.load(open(ITEM_MANIFEST))["data_sha256"],
        "item_manifest_path": str(ITEM_MANIFEST),
        "gated_pairs": [{"item": it, "variant": v} for it, v in gated_pairs],
        "split_seed": 0,
        "model_seed_list": LOCKBOX_SEEDS,
        "feature_seed_locked_to_model_seed": True,
        "augmentation_seed": "n/a — deterministic feature concat",
        "n_subjects": int(n),
        "eval_protocol": (
            "LOOCV (n=94), 3 seeds, per-fold standardisation/imputation via inductive_lib; "
            "per-fold K=min(500, X.shape[1]) LGB-importance feature selection."
        ),
        "headline_metric": "Per-item CCC of mean-of-3-seed LOOCV preds vs item score (N=94)",
        "comparator_baselines": BASELINE_CCC,
        "lockbox_rules": [
            "ONE config pre-registered per (item, variant) pair. ONE LOOCV evaluation per pair. Headline = result, no cherry-picking.",
            "If LOOCV ΔCCC vs baseline ≤ +0.02, report as null result; do not select runner-up variant.",
            "Bootstrap 95% CI of (iter17_lockbox_ccc - baseline) reported.",
        ],
        "feature_safety_argument": (
            "Item-specific features are deterministic signal-processing aggregates of raw IMU "
            "channels in the clinically-relevant time window for each item. UPDRS-III labels "
            "never enter cache_item_specific_features.py. Manifest verified leakage-clean by "
            "construction."
        ),
    }
    prereg_path = RESULTS_DIR / f"preregistration_peritem_iter17_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    # Run each gated pair
    headlines = {}
    for item, variant in gated_pairs:
        X_item, _ = load_item_features(d["sids"], item)
        h = lockbox_one(d, item, variant, X_item, ts)
        headlines[f"item{item}_{variant}"] = h

    # Combined headline manifest
    out_combined = RESULTS_DIR / f"lockbox_peritem_iter17_combined_{ts}.json"
    with open(out_combined, "w") as f:
        json.dump(
            {
                "preregistration_file": prereg_path.name,
                "headlines": headlines,
                "ts": ts,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nWrote combined headlines: {out_combined}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen", "lockbox"], required=True)
    ap.add_argument("--gated_items", default="", help="comma-separated items (lockbox)")
    ap.add_argument(
        "--gated_variants",
        default="",
        help="comma-separated variants matching --gated_items (lockbox)",
    )
    args = ap.parse_args()
    ensure_dir(RESULTS_DIR)

    print("Loading per-item data + V2 features...", flush=True)
    d = load_data()
    print(f"  N = {len(d['sids'])} PD subjects", flush=True)

    if args.mode == "screen":
        out_csv = RESULTS_DIR / "peritem_iter17_hypothesis_5fold_screen.csv"
        result = screen(d, out_csv)
        if not result["overall_pass"]:
            sys.exit(2)
    else:
        if not args.gated_items or not args.gated_variants:
            raise ValueError("--gated_items and --gated_variants required for lockbox")
        items = [int(x) for x in args.gated_items.split(",") if x.strip()]
        variants = [v.strip() for v in args.gated_variants.split(",") if v.strip()]
        if len(items) != len(variants):
            raise ValueError("--gated_items and --gated_variants must have same length")
        gated_pairs = list(zip(items, variants))
        lockbox(d, gated_pairs)


if __name__ == "__main__":
    main()
