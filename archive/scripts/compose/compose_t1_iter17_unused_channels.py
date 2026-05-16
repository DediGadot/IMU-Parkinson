"""T1 iter17 — Mag/VelInc/OriInc unused-channel features as Stage-2 augmentation.

Phase A1 of the 100x researcher CCC-push (2026-05-03 PM, see task_plan.md ACTIVE MISSION).

Hypothesis: ~255 features extracted from the entirely-unused IMU channels
(Mag_XYZ + VelInc_XYZ + OriInc_q0..q3 — see cache_unused_channels.py for the
recipe and feature-safety argument), when concatenated to the V2 feature pool
inside each per-item iter8 variant, raise the T1-sum 5-fold CCC by ≥ +0.025
across 5 seeds with sum-level seed std < 0.020. Sum-level gate (vs per-item)
because at N=94 with 3 seeds the per-item seed std is intrinsically ~0.06
(F44 lesson); summing across 6 items averages out per-item noise.

Items modified (UNUSED-channel augmentation): {9, 10, 11, 12, 13, 14}
  All six iter8 variants get V2 ⊕ unused-channel features in their incoming
  X-matrix, with the same per-fold K=500 LGB-importance selection.
Items kept fixed (no change vs iter12 honest): none.

Pre-registration discipline:
  - Pre-registration is written ONLY when --mode=lockbox, BEFORE the LOOCV runs.
  - The screen mode is exploratory and does not write a pre-registration.
  - The lockbox runs ONCE and reports regardless of outcome.

Promotion gate (screen → lockbox):
  T1-sum 5-fold mean(unused) - mean(control) ≥ +0.025 AND
  T1-sum 5-fold std(unused) < 0.020 across 5 seeds [42, 1337, 7, 2024, 9001].
  ALTERNATIVE per-item gate: any single item with Δ ≥ +0.05 AND seed std < 0.02
  promotes that single-item augmented variant (per-item lockbox replaces only
  that item's iter8 OOF in the composite). Both gates are evaluated; the
  composite includes ONLY the items that pass.

Two modes:

    python3 compose_t1_iter17_unused_channels.py --mode screen
        5-fold (5 seeds) on items {9..14} × {control, unused_aug}.
        Writes results/peritem_iter17_unused_5fold_screen.csv.
        Exit 0 if any gate passes; 2 otherwise.

    python3 compose_t1_iter17_unused_channels.py --mode lockbox --gated_items 10,12
        Pre-registers + runs LOOCV (3 seeds, mean preds) on the items that
        passed the screen gate; reuses iter8 OOFs for the rest.
        Writes results/preregistration_t1_iter17_unused_<ts>.json + lockbox files.
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
from run_per_item_v2 import get_item_features, load_data

UNUSED_CACHE = RESULTS_DIR / "unused_channels_features.csv"
UNUSED_MANIFEST = RESULTS_DIR / "unused_channels_features.csv.manifest.json"
ITER8_TS = "20260430_143044"
T1_ITEMS = [9, 10, 11, 12, 13, 14]
SEEDS = [42, 1337, 7, 2024, 9001]   # 5 seeds for tighter sum-level std estimate
LOCKBOX_SEEDS = [42, 1337, 7]       # canonical 3-seed mean for headline

# Variant rules per item: control = iter12 honest selections.
CONTROL_VARIANTS: dict[int, str] = {
    9:  "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
}

# Promotion gate constants
GATE_SUM_DELTA = 0.025
GATE_SUM_STD = 0.020
GATE_PERITEM_DELTA = 0.05
GATE_PERITEM_STD = 0.02


def _verify_manifest() -> dict:
    if not UNUSED_MANIFEST.exists():
        raise FileNotFoundError(
            f"Missing manifest sidecar: {UNUSED_MANIFEST}. "
            "Per skill rule, caches without manifests cannot feed inductive headlines. "
            "Run cache_unused_channels.py first (the manifest is written automatically)."
        )
    with open(UNUSED_MANIFEST) as f:
        m = json.load(f)
    if m.get("labels_used", True):
        raise RuntimeError("Manifest reports labels_used=True; cache is not feature-safe.")
    if m.get("leakage_status") != "clean_by_construction":
        raise RuntimeError(
            f"Manifest leakage_status={m.get('leakage_status')!r} != 'clean_by_construction'."
        )
    return m


def load_unused_features(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Return aligned unused-channel features (n, n_features) for the given SID order."""
    _verify_manifest()
    if not UNUSED_CACHE.exists():
        raise FileNotFoundError(f"Missing {UNUSED_CACHE}; run cache_unused_channels.py")
    df = pd.read_csv(UNUSED_CACHE).set_index("sid")
    feat_cols = [c for c in df.columns if c.startswith("um_")]
    if len(feat_cols) < 50:
        raise RuntimeError(
            f"Unused-channel cache too sparse: {len(feat_cols)} features (expected 200+)."
        )
    n = len(sids)
    X = np.full((n, len(feat_cols)), np.nan)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(
        f"  Unused-channel features matched for {matched}/{n} subjects ({len(feat_cols)} cols)",
        flush=True,
    )
    return X, feat_cols


def _run_variant_kfold(
    d: dict,
    item: int,
    unused_features: np.ndarray | None,
    splits,
    seed: int,
) -> np.ndarray:
    """Run one item's variant across given (tr, te) splits. Returns OOF (n,).
    unused_features: (n, k_unused) array (or None for control).
    """
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

    if unused_features is not None:
        X_aug_full = np.hstack([X_base, unused_features])
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

        Xtr, Xte = impute_fold(X_aug_full[tr], X_aug_full[te])
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


# ── Screen mode (5-fold, 5 seeds) ────────────────────────────────────────────


def screen(d: dict, X_unused: np.ndarray, out_csv: Path) -> dict:
    """5-fold × 5 seeds, items {9..14} × {control, unused_aug}.
    Computes both per-item and sum-T1 gates."""
    rows = []
    per_item_seed_ccc: dict[tuple[int, str], list[float]] = {}
    sum_seed_ccc: dict[str, list[float]] = {"control": [], "unused_aug": []}

    # Pre-load full LOO indices once per seed
    for treatment in ("control", "unused_aug"):
        unused = X_unused if treatment == "unused_aug" else None
        # We need OOF arrays per (item, seed) to compute T1 sum
        for seed in SEEDS:
            splits = list(kfold_split_stratified(d["t1"], n_splits=5, seed=seed))
            oofs_seed: dict[int, np.ndarray] = {}
            for item in T1_ITEMS:
                oof = _run_variant_kfold(d, item, unused, splits, seed)
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
                per_item_seed_ccc.setdefault((item, treatment), []).append(c)
            # Sum-T1 CCC for this (treatment, seed)
            t1_pred = np.sum(np.column_stack([oofs_seed[it] for it in T1_ITEMS]), axis=1)
            t1_true = d["t1"]
            valid = ~np.isnan(t1_true)
            c_sum = float(ccc_fn(t1_true[valid], t1_pred[valid]))
            rows.append(
                {
                    "item": "T1_SUM",
                    "treatment": treatment,
                    "seed": seed,
                    "ccc": round(c_sum, 4),
                    "variant": "sum_OOF",
                }
            )
            sum_seed_ccc[treatment].append(c_sum)
            print(
                f"  {treatment:11s} seed={seed:5d}: T1-sum 5-fold CCC = {c_sum:+.4f}",
                flush=True,
            )

    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"\nScreen CSV: {out_csv}", flush=True)

    # Per-item summaries
    per_item_summaries = []
    for item in T1_ITEMS:
        c_ctrl = per_item_seed_ccc.get((item, "control"), [])
        c_aug  = per_item_seed_ccc.get((item, "unused_aug"), [])
        ctrl_mean, ctrl_std = float(np.mean(c_ctrl)), float(np.std(c_ctrl))
        aug_mean, aug_std = float(np.mean(c_aug)), float(np.std(c_aug))
        delta = aug_mean - ctrl_mean
        peritem_pass = (delta >= GATE_PERITEM_DELTA) and (aug_std < GATE_PERITEM_STD)
        per_item_summaries.append(
            {
                "item": item,
                "ccc_control_mean": round(ctrl_mean, 4),
                "ccc_control_std": round(ctrl_std, 4),
                "ccc_aug_mean": round(aug_mean, 4),
                "ccc_aug_std": round(aug_std, 4),
                "delta": round(delta, 4),
                "peritem_pass": bool(peritem_pass),
            }
        )

    # Sum-T1 gate
    ctrl_mean = float(np.mean(sum_seed_ccc["control"]))
    aug_mean = float(np.mean(sum_seed_ccc["unused_aug"]))
    aug_std = float(np.std(sum_seed_ccc["unused_aug"]))
    sum_delta = aug_mean - ctrl_mean
    sum_pass = (sum_delta >= GATE_SUM_DELTA) and (aug_std < GATE_SUM_STD)

    print("\n--- PER-ITEM SUMMARY ---", flush=True)
    for s in per_item_summaries:
        marker = "  PASS" if s["peritem_pass"] else "  --  "
        print(
            f"  item {s['item']:2d}: ctrl={s['ccc_control_mean']:+.4f}±{s['ccc_control_std']:.4f}  "
            f"aug={s['ccc_aug_mean']:+.4f}±{s['ccc_aug_std']:.4f}  Δ={s['delta']:+.4f}  {marker}",
            flush=True,
        )
    print(
        f"\n--- SUM-T1 GATE (require Δ≥{GATE_SUM_DELTA} AND aug_std<{GATE_SUM_STD}) ---",
        flush=True,
    )
    print(
        f"  ctrl T1-sum: {ctrl_mean:+.4f}  aug T1-sum: {aug_mean:+.4f}  "
        f"Δ={sum_delta:+.4f}  aug_std={aug_std:.4f}  → SUM_PASS={sum_pass}",
        flush=True,
    )
    print(
        f"\n--- PER-ITEM GATES (require Δ≥{GATE_PERITEM_DELTA} AND aug_std<{GATE_PERITEM_STD}) ---",
        flush=True,
    )
    peritem_passers = [s["item"] for s in per_item_summaries if s["peritem_pass"]]
    print(f"  per-item passers: {peritem_passers}", flush=True)

    overall_pass = bool(sum_pass) or bool(peritem_passers)
    print(f"\nOVERALL GATE: {'PASS' if overall_pass else 'FAIL'}", flush=True)
    return {
        "sum_pass": bool(sum_pass),
        "sum_delta": sum_delta,
        "sum_aug_std": aug_std,
        "peritem_passers": peritem_passers,
        "per_item_summaries": per_item_summaries,
        "overall_pass": overall_pass,
    }


# ── Lockbox mode (LOOCV, 3 seeds, mean preds, ONE pre-reg) ───────────────────


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


def lockbox(d: dict, X_unused: np.ndarray, gated_items: list[int], out_json: Path) -> None:
    """LOOCV (3 seeds, mean preds) on items in gated_items with unused-channel aug;
    reuse iter8 OOFs for items not in gated_items."""
    sids = d["sids"]
    n = len(sids)

    if not gated_items:
        raise ValueError(
            "lockbox called with no gated_items — screen mode must produce passers first"
        )
    invalid = [it for it in gated_items if it not in T1_ITEMS]
    if invalid:
        raise ValueError(f"Invalid gated_items {invalid}; must be in {T1_ITEMS}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha256(),
        "experiment": "T1 iter17 — unused-channel features (Mag/VelInc/OriInc) for gated items",
        "rationale": (
            "Phase A1 of the 100x researcher CCC-push (2026-05-03 PM). The V2 feature set "
            "(1751 cols) draws ONLY from Acc + Gyr + partial FreeAcc + Roll/Pitch/Yaw — Mag_XYZ, "
            "VelInc_XYZ, and OriInc_q0..q3 are entirely unmined. This iteration tests whether the "
            "gated item(s) gain from concatenating ~255 unused-channel-derived features (label-free, "
            "manifest-tracked) to the per-item augmented X-matrix. Lockbox is run ONLY on items that "
            "passed the screen gate (per-item Δ ≥ +0.05 with std < 0.02 OR sum-T1 Δ ≥ +0.025)."
        ),
        "unused_cache_path": str(UNUSED_CACHE),
        "unused_cache_sha256": json.load(open(UNUSED_MANIFEST))["data_sha256"],
        "unused_manifest_path": str(UNUSED_MANIFEST),
        "items_modified": gated_items,
        "items_kept_from_iter8": [it for it in T1_ITEMS if it not in gated_items],
        "iter8_batch_ts": ITER8_TS,
        "iter8_variants": {str(it): CONTROL_VARIANTS[it] for it in T1_ITEMS},
        "split_seed": 0,
        "model_seed_list": LOCKBOX_SEEDS,
        "feature_seed_locked_to_model_seed": True,
        "augmentation_seed": "n/a — deterministic feature concat",
        "n_subjects": int(n),
        "eval_protocol": (
            "LOOCV (n=94), 3 seeds, per-fold standardisation/imputation via inductive_lib. "
            "Gated items: identical to iter8 variant + ~255 unused-channel cols appended. "
            "Non-gated items: reuse iter8-batch OOFs from 20260430_143044 unchanged. "
            "T1 = sum across 6 per-item LOOCV OOFs. 3-seed mean preds = headline."
        ),
        "headline_metric": "CCC of mean-of-3-seed T1 predictions vs sum of items 9-14 truth (N=94)",
        "comparator_iter12_honest_ccc": 0.6550,
        "lockbox_rules": [
            "ONE composite pre-registered. ONE LOOCV evaluation. Headline = result, no cherry-picking.",
            "If LOOCV ΔCCC ≤ +0.005 vs iter12 honest, report as null result; do not select runner-up.",
            "Bootstrap 95% CI of (iter17_unused - iter12) on the same N=94 must straddle zero LESS "
            "than 30% to claim significance.",
        ],
        "feature_safety_argument": (
            "Unused-channel features are deterministic signal-processing aggregates (Mag/VelInc/OriInc "
            "channels reduced via mean/std/IQR/spectral-edge/sample-entropy/quaternion-delta to ~255 "
            "scalars per subject). UPDRS-III labels never enter cache_unused_channels.py. "
            "Manifest verified leakage-clean by construction."
        ),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t1_iter17_unused_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    # Reuse iter8 OOFs for unmodified items.
    oofs: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        if it in gated_items:
            continue
        variant = CONTROL_VARIANTS[it]
        path = RESULTS_DIR / f"lockbox_peritem_{it}_{variant}_{ITER8_TS}.oof.npy"
        if not path.exists():
            raise FileNotFoundError(f"Missing iter8 OOF: {path}")
        oofs[it] = np.load(path)
        if oofs[it].shape != (n,):
            raise ValueError(f"Iter8 OOF shape mismatch for item {it}: {oofs[it].shape} != ({n},)")
        y = d["items"][it].astype(np.float64)
        valid = ~np.isnan(y)
        per_ccc = float(ccc_fn(y[valid], oofs[it][valid]))
        print(f"  item {it} ({variant}, REUSED iter8 OOF): per-item LOOCV CCC = {per_ccc:+.4f}", flush=True)

    # LOOCV for gated items with unused-channel aug.
    splits = _build_loo_splits(n)
    for it in gated_items:
        seed_oofs = []
        for seed in LOCKBOX_SEEDS:
            t0 = time.time()
            oof = _run_variant_kfold(d, it, X_unused, splits, seed)
            seed_oofs.append(oof)
            print(
                f"  item {it} seed={seed}: LOOCV done in {time.time()-t0:.1f}s",
                flush=True,
            )
        mean_oof = np.mean(np.stack(seed_oofs, axis=0), axis=0)
        oofs[it] = mean_oof
        np.save(RESULTS_DIR / f"lockbox_peritem_{it}_unused_aug_{ts}.oof.npy", mean_oof)
        y = d["items"][it].astype(np.float64)
        valid = ~np.isnan(y)
        per_ccc = float(ccc_fn(y[valid], mean_oof[valid]))
        per_std = float(np.std([
            ccc_fn(y[valid], so[valid]) for so in seed_oofs
        ]))
        print(
            f"  item {it} ({CONTROL_VARIANTS[it]} + unused_aug, fresh LOOCV): per-item CCC = "
            f"{per_ccc:+.4f}  seed_std = {per_std:.4f}",
            flush=True,
        )

    # Sum to T1.
    t1_pred = np.sum(np.column_stack([oofs[it] for it in T1_ITEMS]), axis=1)
    t1_true = d["t1"]
    valid = ~np.isnan(t1_true)
    n_valid = int(valid.sum())
    print(f"\nComposite: N_valid = {n_valid}/{n}", flush=True)

    headline = full_metrics(t1_true[valid], t1_pred[valid], label="t1_iter17_unused")

    iter12_oof_path = RESULTS_DIR / "t1_iter12_honest_composite.oof.npy"
    rng = np.random.RandomState(42)
    n_boot = 2000
    boot_ccc = []
    yt = t1_true[valid]
    yp = t1_pred[valid]
    for _ in range(n_boot):
        idx = rng.randint(0, len(yt), size=len(yt))
        boot_ccc.append(ccc_fn(yt[idx], yp[idx]))
    boot_ccc = np.array(boot_ccc)

    paired_ci_block = None
    if iter12_oof_path.exists():
        prev = np.load(iter12_oof_path)
        if len(prev) == len(yt):
            rng2 = np.random.RandomState(43)
            paired_d = []
            for _ in range(n_boot):
                idx = rng2.randint(0, len(yt), size=len(yt))
                paired_d.append(ccc_fn(yt[idx], yp[idx]) - ccc_fn(yt[idx], prev[idx]))
            paired_d = np.array(paired_d)
            paired_ci_block = {
                "delta_mean": round(float(paired_d.mean()), 4),
                "delta_ci_low": round(float(np.percentile(paired_d, 2.5)), 4),
                "delta_ci_high": round(float(np.percentile(paired_d, 97.5)), 4),
                "frac_delta_gt0": round(float((paired_d > 0).mean()), 4),
            }

    headline.update(
        {
            "iteration": "iter17_unused",
            "n_subjects_valid": n_valid,
            "preregistration_file": prereg_path.name,
            "is_lockbox_headline": True,
            "comparator_iter12_honest_ccc": 0.6550,
            "delta_vs_iter12_honest": round(float(headline["ccc"]) - 0.6550, 4),
            "gated_items": gated_items,
            "bootstrap_ccc": {
                "n_boot": n_boot,
                "ccc_mean": round(float(boot_ccc.mean()), 4),
                "ccc_ci_low": round(float(np.percentile(boot_ccc, 2.5)), 4),
                "ccc_ci_high": round(float(np.percentile(boot_ccc, 97.5)), 4),
            },
            "paired_bootstrap_vs_iter12": paired_ci_block,
            "per_subject": {
                "sids": [str(s) for s in sids[valid]],
                "y_true": yt.tolist(),
                "y_pred": yp.tolist(),
            },
        }
    )

    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    np.save(out_json.with_suffix("").as_posix() + ".oof.npy", yp)

    print(f"\n=== HEADLINE (T1 iter17 unused-channels): ===", flush=True)
    print(
        f"  CCC = {headline['ccc']:.4f}  MAE = {headline['mae']:.3f}  "
        f"r = {headline['r']:.4f}  slope = {headline['cal_slope']:.3f}",
        flush=True,
    )
    print(
        f"  Δ vs iter12 honest 0.6550: {headline['delta_vs_iter12_honest']:+.4f}",
        flush=True,
    )
    if paired_ci_block:
        print(
            f"  Paired bootstrap (n={n_boot}): mean Δ={paired_ci_block['delta_mean']:+.4f}, "
            f"95% CI=[{paired_ci_block['delta_ci_low']:+.4f}, {paired_ci_block['delta_ci_high']:+.4f}], "
            f"frac > 0 = {paired_ci_block['frac_delta_gt0']}",
            flush=True,
        )


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen", "lockbox"], required=True)
    ap.add_argument(
        "--gated_items",
        type=str,
        default="",
        help="comma-separated item IDs (lockbox mode only); items that passed the screen gate",
    )
    args = ap.parse_args()
    ensure_dir(RESULTS_DIR)

    print("Loading per-item data + V2 features...", flush=True)
    d = load_data()
    sids = d["sids"]
    print(f"  N = {len(sids)} PD subjects", flush=True)

    print("\nLoading unused-channel features...", flush=True)
    X_unused, feat_cols = load_unused_features(sids)
    print(f"  unused_features shape = {X_unused.shape}", flush=True)

    if args.mode == "screen":
        out_csv = RESULTS_DIR / "peritem_iter17_unused_5fold_screen.csv"
        result = screen(d, X_unused, out_csv)
        if not result["overall_pass"]:
            sys.exit(2)
    else:
        if not args.gated_items:
            raise ValueError(
                "--gated_items required for lockbox mode (e.g. --gated_items 10,12). "
                "Determined from the screen gate output."
            )
        gated_items = [int(x) for x in args.gated_items.split(",") if x.strip()]
        out_json = RESULTS_DIR / f"lockbox_t1_iter17_unused_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        lockbox(d, X_unused, gated_items, out_json)


if __name__ == "__main__":
    main()
