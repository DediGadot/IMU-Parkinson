"""Probe A — site-aware intercept-only Stage-1 correction (post-hoc on iter34 OOF).

Hypothesis (from VIZ 2026-05-08 PM): WPD-site is structurally under-predicted by
~0.6 UPDRS-III points across iter34 / slot C / iter33b. Test a 1-DOF per-site
additive intercept correction, fitted on outer-train residuals per LOOCV fold,
applied at predict time.

Architecture:
  - Read iter34 OOF (results/lockbox_t1_iter34_hybrid_20260506_141720.json)
  - Per LOOCV fold (each subject = held-out test, train = other 92):
      r_train = y_true_train - y_pred_train (iter34 base predictions)
      offset_NLS = r_train[NLS subjects].mean()
      offset_WPD = r_train[WPD subjects].mean()
      y_pred_corrected[i] = y_pred_test[i] + (offset_NLS if SID startswith NLS else offset_WPD)
  - Strictly fold-local: each fold uses ONLY its 92 training residuals.
  - 1 DOF per site per fold (2 DOF total), zero hyperparameters.

Modes: probe / lockbox

Wall-orthogonality:
  - F49 used per-feature per-site centering (1751 x 2 = 3502 DOF). Probe A is 2 DOF.
  - F58 mixer-wall killed META-stacks. Probe A is additive, not a learned blend.
  - F35-A/B/C/D dealt with Stage 2 architecture; Probe A is post-Stage-2.

Usage:
  python run_t1_probeA_site_intercept.py --mode probe
  python run_t1_probeA_site_intercept.py --mode lockbox
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from eval_utils import lins_ccc, cal_slope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("probeA")

REPO_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = REPO_ROOT / "results"
ITER34_LOCKBOX = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.json"
ITER12_HONEST_COMPOSITE = RESULTS_DIR / "t1_iter12_honest_composite.json"

# Frozen formula (probe A, post-hoc). Bound into pre-reg via formula_sha256.
FORMULA = (
    "y_pred_corrected[i] = y_pred_iter34[i] + offset_site[site(sid_i)]"
    " where offset_site[s] = mean(y_true_train - y_pred_iter34_train) over train subjects with site(sid)==s,"
    " train = all 92 subjects except subject i (LOOCV);"
    " site(sid) = 'NLS' if sid.startswith('NLS') else 'WPD'."
    " 1 DOF per site per fold (2 DOF total). Strictly fold-local. No tuning across folds."
)
FORMULA_SHA256 = hashlib.sha256(FORMULA.encode("utf-8")).hexdigest()


def site_of(sid: str) -> str:
    if sid.startswith("NLS"):
        return "NLS"
    if sid.startswith("WPD"):
        return "WPD"
    raise ValueError(f"Unknown site for SID: {sid}")


def loocv_site_intercept(
    sids: list[str],
    y_true: np.ndarray,
    y_pred_base: np.ndarray,
    site_labels: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """Apply LOOCV per-site intercept correction.

    For each subject i (test), compute mean residual on the 92 OTHER subjects,
    grouped by site. Apply that site's offset to subject i's prediction.

    site_labels: optional override (used for null sanity with shuffled sites).
    """
    n = len(sids)
    if site_labels is None:
        site_labels = np.array([site_of(s) for s in sids])

    y_pred_corrected = np.empty(n, dtype=np.float64)
    offsets_per_fold = {"NLS": [], "WPD": []}
    n_per_fold = {"NLS": [], "WPD": []}

    for i in range(n):
        train_mask = np.ones(n, dtype=bool)
        train_mask[i] = False

        train_sites = site_labels[train_mask]
        train_residuals = y_true[train_mask] - y_pred_base[train_mask]

        offset_nls_mask = train_sites == "NLS"
        offset_wpd_mask = train_sites == "WPD"

        if not offset_nls_mask.any() or not offset_wpd_mask.any():
            raise RuntimeError(
                f"Fold {i} (sid={sids[i]}): one site has 0 train subjects — "
                "this should never happen at N=93."
            )

        off_nls = float(train_residuals[offset_nls_mask].mean())
        off_wpd = float(train_residuals[offset_wpd_mask].mean())

        offsets_per_fold["NLS"].append(off_nls)
        offsets_per_fold["WPD"].append(off_wpd)
        n_per_fold["NLS"].append(int(offset_nls_mask.sum()))
        n_per_fold["WPD"].append(int(offset_wpd_mask.sum()))

        test_site = site_labels[i]
        if test_site == "NLS":
            y_pred_corrected[i] = y_pred_base[i] + off_nls
        else:
            y_pred_corrected[i] = y_pred_base[i] + off_wpd

    diag = {
        "offset_NLS_mean": float(np.mean(offsets_per_fold["NLS"])),
        "offset_NLS_std": float(np.std(offsets_per_fold["NLS"])),
        "offset_WPD_mean": float(np.mean(offsets_per_fold["WPD"])),
        "offset_WPD_std": float(np.std(offsets_per_fold["WPD"])),
        "n_train_NLS_per_fold_mean": float(np.mean(n_per_fold["NLS"])),
        "n_train_WPD_per_fold_mean": float(np.mean(n_per_fold["WPD"])),
    }
    return y_pred_corrected, diag


def paired_bootstrap_delta_ccc(
    y_true: np.ndarray,
    y_pred_a: np.ndarray,
    y_pred_b: np.ndarray,
    n_boot: int = 5000,
    seed: int = 20260508,
) -> dict:
    """Paired subject-level bootstrap of Δ CCC = ccc(y_true, y_pred_a) - ccc(y_true, y_pred_b)."""
    rng = np.random.RandomState(seed)
    n = len(y_true)
    deltas = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        ccc_a = lins_ccc(y_true[idx], y_pred_a[idx])
        ccc_b = lins_ccc(y_true[idx], y_pred_b[idx])
        deltas[b] = ccc_a - ccc_b
    return {
        "n_boot": int(n_boot),
        "seed": int(seed),
        "delta_mean": float(np.mean(deltas)),
        "ci_low": float(np.percentile(deltas, 2.5)),
        "ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float(np.mean(deltas > 0)),
        "frac_above_0.025": float(np.mean(deltas > 0.025)),
        "frac_above_0.05": float(np.mean(deltas > 0.05)),
    }


def per_site_ccc(
    y_true: np.ndarray, y_pred: np.ndarray, site_labels: np.ndarray
) -> dict:
    out = {}
    for site in ["NLS", "WPD"]:
        mask = site_labels == site
        if mask.sum() < 3:
            out[site] = {"n": int(mask.sum()), "ccc": None, "mae": None}
        else:
            yt, yp = y_true[mask], y_pred[mask]
            out[site] = {
                "n": int(mask.sum()),
                "ccc": float(lins_ccc(yt, yp)),
                "mae": float(np.mean(np.abs(yt - yp))),
                "signed_mean_residual": float(np.mean(yt - yp)),
            }
    return out


def load_iter34_oof() -> tuple[list[str], np.ndarray, np.ndarray]:
    if not ITER34_LOCKBOX.exists():
        raise FileNotFoundError(f"Missing iter34 OOF: {ITER34_LOCKBOX}")
    d = json.loads(ITER34_LOCKBOX.read_text())
    ps = d["per_subject"]
    sids = list(ps["sids"])
    y_true = np.asarray(ps["y_true"], dtype=np.float64)
    y_pred = np.asarray(ps["y_pred"], dtype=np.float64)
    if not (len(sids) == len(y_true) == len(y_pred) == 93):
        raise RuntimeError(
            f"iter34 OOF length mismatch: sids={len(sids)} yt={len(y_true)} yp={len(y_pred)}"
        )
    return sids, y_true, y_pred


def load_iter12_honest_on_n93(
    target_sids: list[str],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return iter12 honest (y_true, y_pred) reordered to target_sids (N=93).

    iter12 is N=94; one SID present in iter12 will be absent from iter34's N=93
    cohort (WPD002 — confirmed below). Returns None if iter12 missing.
    """
    if not ITER12_HONEST_COMPOSITE.exists():
        return None
    d = json.loads(ITER12_HONEST_COMPOSITE.read_text())
    ps = d["per_subject"]
    sid_to_idx = {s: i for i, s in enumerate(ps["sids"])}
    y_true_94 = np.asarray(ps["y_true"], dtype=np.float64)
    y_pred_94 = np.asarray(ps["y_pred"], dtype=np.float64)

    yt = np.empty(len(target_sids), dtype=np.float64)
    yp = np.empty(len(target_sids), dtype=np.float64)
    missing = []
    for i, s in enumerate(target_sids):
        if s not in sid_to_idx:
            missing.append(s)
            continue
        j = sid_to_idx[s]
        yt[i] = y_true_94[j]
        yp[i] = y_pred_94[j]
    if missing:
        logger.warning("iter12 honest missing %d SIDs: %s", len(missing), missing[:5])
        return None
    return yt, yp


def run_probe(args) -> dict:
    """Probe mode: post-hoc apply LOOCV per-site intercept to iter34 OOF, report."""
    sids, y_true, y_pred_iter34 = load_iter34_oof()
    site_labels = np.array([site_of(s) for s in sids])

    n = len(sids)
    n_nls = int((site_labels == "NLS").sum())
    n_wpd = int((site_labels == "WPD").sum())
    logger.info("Loaded iter34 OOF: N=%d (NLS=%d, WPD=%d)", n, n_nls, n_wpd)

    # Baseline metrics (iter34 unchanged)
    ccc_baseline = lins_ccc(y_true, y_pred_iter34)
    persite_baseline = per_site_ccc(y_true, y_pred_iter34, site_labels)
    logger.info(
        "Baseline (iter34): CCC=%.4f, NLS-CCC=%.4f (signed_resid=%+.3f), "
        "WPD-CCC=%.4f (signed_resid=%+.3f)",
        ccc_baseline,
        persite_baseline["NLS"]["ccc"],
        persite_baseline["NLS"]["signed_mean_residual"],
        persite_baseline["WPD"]["ccc"],
        persite_baseline["WPD"]["signed_mean_residual"],
    )

    # Apply LOOCV per-site intercept correction
    y_pred_corrected, diag = loocv_site_intercept(sids, y_true, y_pred_iter34)
    ccc_corrected = lins_ccc(y_true, y_pred_corrected)
    persite_corrected = per_site_ccc(y_true, y_pred_corrected, site_labels)

    delta = ccc_corrected - ccc_baseline
    logger.info(
        "Corrected: CCC=%.4f (Δ vs iter34 = %+.4f); NLS=%.4f, WPD=%.4f",
        ccc_corrected,
        delta,
        persite_corrected["NLS"]["ccc"],
        persite_corrected["WPD"]["ccc"],
    )
    logger.info(
        "Per-fold offsets: NLS mean=%+.3f std=%.3f, WPD mean=%+.3f std=%.3f",
        diag["offset_NLS_mean"],
        diag["offset_NLS_std"],
        diag["offset_WPD_mean"],
        diag["offset_WPD_std"],
    )

    # Paired bootstrap vs iter34
    bs_vs_iter34 = paired_bootstrap_delta_ccc(
        y_true, y_pred_corrected, y_pred_iter34, n_boot=args.n_boot, seed=20260508
    )
    logger.info(
        "Paired bootstrap vs iter34: Δ̄=%.4f, CI=[%.4f,%.4f], frac>0=%.3f, frac>0.025=%.3f",
        bs_vs_iter34["delta_mean"],
        bs_vs_iter34["ci_low"],
        bs_vs_iter34["ci_high"],
        bs_vs_iter34["frac_above_zero"],
        bs_vs_iter34["frac_above_0.025"],
    )

    # Paired bootstrap vs iter12-honest-N=93 (skip 1 missing SID iter34→iter12)
    bs_vs_iter12 = None
    iter12_pair = load_iter12_honest_on_n93(sids)
    if iter12_pair is not None:
        yt12, yp12 = iter12_pair
        if not np.allclose(yt12, y_true, atol=1e-6):
            logger.warning(
                "iter12 y_true differs from iter34 y_true; using iter34's "
                "y_true for paired bootstrap (subject-paired regardless)."
            )
        bs_vs_iter12 = paired_bootstrap_delta_ccc(
            y_true, y_pred_corrected, yp12, n_boot=args.n_boot, seed=20260508
        )
        logger.info(
            "Paired bootstrap vs iter12-honest-N=93: Δ̄=%.4f, CI=[%.4f,%.4f], "
            "frac>0=%.3f",
            bs_vs_iter12["delta_mean"],
            bs_vs_iter12["ci_low"],
            bs_vs_iter12["ci_high"],
            bs_vs_iter12["frac_above_zero"],
        )

    # 5-null sanity: shuffle site labels, expect lift to vanish
    null_results = []
    for null_seed in [42, 1337, 7]:
        rng = np.random.RandomState(null_seed)
        shuffled_sites = site_labels.copy()
        rng.shuffle(shuffled_sites)
        y_pred_null, _ = loocv_site_intercept(
            sids, y_true, y_pred_iter34, site_labels=shuffled_sites
        )
        ccc_null = lins_ccc(y_true, y_pred_null)
        null_results.append(
            {
                "seed": int(null_seed),
                "ccc_null": float(ccc_null),
                "delta_vs_iter34": float(ccc_null - ccc_baseline),
            }
        )
    null_delta_mean = float(np.mean([r["delta_vs_iter34"] for r in null_results]))
    logger.info(
        "5-null shuffled-site sanity: mean Δ across 3 seeds = %+.4f (expect ~0)",
        null_delta_mean,
    )

    # Most-corrected subjects
    correction = y_pred_corrected - y_pred_iter34
    abs_corr_idx = np.argsort(-np.abs(correction))[:8]
    most_corrected = [
        {
            "sid": sids[i],
            "site": site_labels[i],
            "y_true": float(y_true[i]),
            "y_pred_iter34": float(y_pred_iter34[i]),
            "y_pred_corrected": float(y_pred_corrected[i]),
            "correction": float(correction[i]),
            "abs_resid_iter34": float(abs(y_true[i] - y_pred_iter34[i])),
            "abs_resid_corrected": float(abs(y_true[i] - y_pred_corrected[i])),
        }
        for i in abs_corr_idx
    ]

    # Severity-binned residual analysis (post-correction monotonicity)
    quartiles = np.quantile(y_true, [0.25, 0.5, 0.75])
    bins = np.digitize(y_true, quartiles)
    by_q = {}
    for q in range(4):
        m = bins == q
        if m.any():
            by_q[f"Q{q + 1}"] = {
                "n": int(m.sum()),
                "y_true_mean": float(y_true[m].mean()),
                "abs_resid_iter34_mean": float(np.abs(y_true[m] - y_pred_iter34[m]).mean()),
                "abs_resid_corrected_mean": float(np.abs(y_true[m] - y_pred_corrected[m]).mean()),
                "signed_resid_iter34_mean": float((y_true[m] - y_pred_iter34[m]).mean()),
                "signed_resid_corrected_mean": float(
                    (y_true[m] - y_pred_corrected[m]).mean()
                ),
            }

    # Verdict logic
    pass_strict = (
        delta >= 0.025
        and bs_vs_iter34["frac_above_zero"] >= 0.99
        and abs(null_delta_mean) < 0.01
    )
    pass_candidate = (
        delta > 0
        and bs_vs_iter34["frac_above_zero"] >= 0.95
        and abs(null_delta_mean) < 0.01
    )
    if pass_strict:
        verdict = "PASS-canonical"
    elif pass_candidate:
        verdict = "PASS-candidate"
    else:
        verdict = "FAIL"

    out = {
        "label": "t1_probeA_site_intercept",
        "mode": "probe",
        "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "n": int(n),
        "n_nls": n_nls,
        "n_wpd": n_wpd,
        "iter34_baseline_ccc": float(ccc_baseline),
        "iter34_per_site_ccc": persite_baseline,
        "probeA_corrected_ccc": float(ccc_corrected),
        "probeA_per_site_ccc": persite_corrected,
        "delta_vs_iter34": float(delta),
        "delta_NLS": float(persite_corrected["NLS"]["ccc"] - persite_baseline["NLS"]["ccc"]),
        "delta_WPD": float(persite_corrected["WPD"]["ccc"] - persite_baseline["WPD"]["ccc"]),
        "fold_local_offsets_summary": diag,
        "paired_bootstrap_vs_iter34": bs_vs_iter34,
        "paired_bootstrap_vs_iter12_honest_n93": bs_vs_iter12,
        "null_sanity_shuffled_site": {
            "per_seed": null_results,
            "mean_delta_vs_iter34": null_delta_mean,
            "expectation": "~0 (site labels carry no info after shuffle)",
        },
        "most_corrected_subjects_top8": most_corrected,
        "severity_quartile_residuals": by_q,
        "formula": FORMULA,
        "formula_sha256": FORMULA_SHA256,
        "verdict": verdict,
        "gate_definitions": {
            "PASS-canonical": "Δ≥0.025 AND frac>0≥0.99 vs iter34 AND |null|<0.01",
            "PASS-candidate": "Δ>0 AND frac>0≥0.95 vs iter34 AND |null|<0.01",
            "FAIL": "otherwise",
        },
    }
    return out


def write_prereg(args) -> Path:
    """Write the pre-registration JSON (formula_sha256-bound) before lockbox."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"preregistration_t1_probeA_site_intercept_{ts}.json"
    prereg = {
        "label": "t1_probeA_site_intercept",
        "registered_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "formula": FORMULA,
        "formula_sha256": FORMULA_SHA256,
        "cohort": "iter34 LOOCV cohort, N=93",
        "iter34_oof_source": str(ITER34_LOCKBOX.relative_to(REPO_ROOT)),
        "comparator_a_iter34_canonical": {
            "ccc": 0.7366,
            "source": str(ITER34_LOCKBOX.relative_to(REPO_ROOT)),
        },
        "comparator_b_iter12_honest_n93": {
            "ccc": 0.6554,
            "source": "results/iter34_vs_iter12_honest_n93_paired_2026_05_06.json",
        },
        "n_dof_per_fold": 2,
        "n_dof_total": "2 sites × 92 LOOCV folds = 184 site-offset estimates "
        "(but each fold's 2 offsets are computed independently from "
        "92 train residuals — fold-local).",
        "evaluation_protocol": "LOOCV per-site intercept correction post-hoc on "
        "iter34 OOF; correct each held-out subject's prediction by adding "
        "their site's mean training residual.",
        "primary_metric": "Lin's CCC of (y_true, y_pred_corrected) on N=93.",
        "primary_comparator": "iter34 CCC=0.7366 on same N=93.",
        "secondary_comparator": "iter12-honest-on-N=93 CCC≈0.6554.",
        "gate_canonical_update": {
            "Delta_vs_iter34": ">= 0.025",
            "paired_bootstrap_frac_above_zero_vs_iter34": ">= 0.99",
            "null_shuffled_site_mean_delta_abs": "< 0.01",
        },
        "gate_candidate": {
            "Delta_vs_iter34": "> 0",
            "paired_bootstrap_frac_above_zero_vs_iter34": ">= 0.95",
            "null_shuffled_site_mean_delta_abs": "< 0.01",
        },
        "n_bootstrap": int(args.n_boot),
        "site_definition": "site(sid) = 'NLS' if sid.startswith('NLS') else 'WPD'.",
        "wall_orthogonality_claim": (
            "Probe A is mechanistically distinct from F49 (1751×2=3502-DOF "
            "feature-level per-site centering), F58 (k=1/k=2/k=19 META-mixers "
            "of base predictions), and F35-A/B/C/D (Stage-2 architecture). "
            "It is a 2-DOF additive bias correction post-Stage-2."
        ),
        "is_post_publication_replication_target": False,
        "is_canonical_update_pending_lockbox": True,
        "family_wise_independence_claim": (
            "Single pre-registered probe today (2026-05-08), comparing against "
            "iter34 0.7366 (n_tests=1, no Bonferroni adjustment needed)."
        ),
    }
    out_path.write_text(json.dumps(prereg, indent=2))
    logger.info("Pre-registration written: %s (sha256=%s)", out_path, FORMULA_SHA256)
    return out_path


def run_lockbox(args) -> dict:
    """Lockbox mode: write pre-reg, run probe, write lockbox JSON, decide canonical-update."""
    prereg_path = write_prereg(args)

    # Validate the formula in the pre-reg matches the in-script FORMULA
    prereg = json.loads(prereg_path.read_text())
    if prereg["formula_sha256"] != FORMULA_SHA256:
        raise RuntimeError(
            f"Pre-reg formula_sha256 ({prereg['formula_sha256']}) "
            f"!= in-script ({FORMULA_SHA256}). ABORT."
        )
    logger.info("Pre-reg sha256 validated: %s", FORMULA_SHA256)

    # Run probe (this re-applies LOOCV per-site intercept and computes everything)
    probe_out = run_probe(args)

    # Decide canonical update
    delta = probe_out["delta_vs_iter34"]
    frac_above_0 = probe_out["paired_bootstrap_vs_iter34"]["frac_above_zero"]
    null_delta_abs = abs(probe_out["null_sanity_shuffled_site"]["mean_delta_vs_iter34"])

    is_canonical_update = (
        delta >= 0.025 and frac_above_0 >= 0.99 and null_delta_abs < 0.01
    )
    is_candidate = (
        delta > 0 and frac_above_0 >= 0.95 and null_delta_abs < 0.01
    )

    lockbox = {
        **probe_out,
        "mode": "lockbox",
        "preregistration_file": str(prereg_path.relative_to(REPO_ROOT)),
        "preregistration_sha256": FORMULA_SHA256,
        "is_canonical_update": bool(is_canonical_update),
        "is_candidate": bool(is_candidate and not is_canonical_update),
        "verdict_lockbox": probe_out["verdict"],
    }

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"lockbox_t1_probeA_site_intercept_{ts}.json"
    out_path.write_text(json.dumps(lockbox, indent=2))
    logger.info("Lockbox written: %s", out_path)
    logger.info(
        "Final verdict: %s (Δ=%+.4f, frac>0=%.3f, |null|=%.4f)",
        probe_out["verdict"],
        delta,
        frac_above_0,
        null_delta_abs,
    )
    return lockbox


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe A — site-aware intercept-only correction")
    parser.add_argument(
        "--mode", choices=["probe", "lockbox"], default="probe",
        help="probe = post-hoc report only; lockbox = write pre-reg + lockbox artifacts",
    )
    parser.add_argument("--n_boot", type=int, default=5000, help="Paired bootstrap iterations")
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("Probe A — site-aware intercept-only Stage-1 correction")
    logger.info("Mode: %s", args.mode)
    logger.info("formula_sha256: %s", FORMULA_SHA256)
    logger.info("=" * 80)

    if args.mode == "probe":
        out = run_probe(args)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = RESULTS_DIR / f"probeA_site_intercept_report_{ts}.json"
        report_path.write_text(json.dumps(out, indent=2))
        logger.info("Probe report: %s", report_path)
        print("\n" + "=" * 80)
        print(f"VERDICT: {out['verdict']}")
        print(f"Δ vs iter34: {out['delta_vs_iter34']:+.4f}  (corrected={out['probeA_corrected_ccc']:.4f}, baseline={out['iter34_baseline_ccc']:.4f})")
        print(f"frac>0 vs iter34: {out['paired_bootstrap_vs_iter34']['frac_above_zero']:.3f}")
        print(f"null shuffled-site mean Δ: {out['null_sanity_shuffled_site']['mean_delta_vs_iter34']:+.4f}")
        print("=" * 80)
    else:
        out = run_lockbox(args)
        print("\n" + "=" * 80)
        print(f"LOCKBOX VERDICT: {out['verdict_lockbox']}")
        print(f"is_canonical_update: {out['is_canonical_update']}")
        print(f"is_candidate: {out['is_candidate']}")
        print(f"Δ vs iter34: {out['delta_vs_iter34']:+.4f}")
        print(f"frac>0 vs iter34: {out['paired_bootstrap_vs_iter34']['frac_above_zero']:.3f}")
        print("=" * 80)


if __name__ == "__main__":
    main()
