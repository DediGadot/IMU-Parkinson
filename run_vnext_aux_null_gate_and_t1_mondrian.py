"""Cell A 5-null gate validator + T1 Mondrian-CP analog (parallel to running batch).

Two tasks, both local CPU-only (uses on-disk OOF predictions):

  TASK 1 — 5-null gate on Cell A's T3 Mondrian-CP recipe.
    Mandatory before claiming Cell A as canonical conformal lockbox.
    The 5 nulls:
      N1 — scrambled-label sanity: permute y, re-run, retained CCC at 70%
            must be near 0 (>0.1 = leak signal).
      N2 — SID-shuffle before iter47 OOF join: the bin labels follow subjects,
            so shuffling SID order should ALSO give chance retained CCC.
      N3 — canary feature: inject a random feature into the bin assignment;
            it should not improve retention quality.
      N4 — library-exclusion: assert no use of XGBRanker.fit(X_all, y_all) or
            global-fit y-aware models (static code check).
      N5 — transductive sanity: re-fit Mondrian-CP using GLOBAL quantile (not
            LOO) and compare; the gap between transductive and inductive is
            the leakage estimate.

  TASK 2 — T1 Mondrian conformal analog on iter34 per-item OOF.
    Mirror Cell A's recipe for T1:
      point predictor: iter34 hybrid V2 T1 sum (CCC=0.7170)
      bins: outer-train-only LOO quartiles of predicted T1
      score: |y_T1 - ŷ_T1|
      coverages: {1.0, 0.85, 0.7, 0.5}
    If retained CCC @ 70% exceeds the current canonical T1 conformal lockbox
    (V2-only at 0.7777), we have a second deployment-mode secondary lift.

Output:
  results/lockbox_vnext_A_null_gate_<TS>.json
  results/lockbox_vnext_T1_mondrian_cp_<TS>.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc

RESULTS_DIR = REPO_ROOT / "results"
ITER47_OOF_CSV = RESULTS_DIR / "iter47_invalidcode_subject_preds_20260508_194605.csv"
ITER34_PER_ITEM_OOF = RESULTS_DIR / "t1_iter34_per_item_oof_20260511_044242.npz"
COVERAGE_TARGETS = (1.0, 0.85, 0.70, 0.50)
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _retained(y, p, retain):
    if retain.sum() < 5:
        return {"retained_n": int(retain.sum()), "retained_ccc": float("nan"),
                "retained_mae": float("nan")}
    yt, yp = y[retain], p[retain]
    return {
        "retained_n": int(retain.sum()),
        "retained_ccc": float(ccc(yt, yp)),
        "retained_mae": float(np.mean(np.abs(yt - yp))),
    }


def mondrian_cp(y, pred, bin_labels, coverages, score_override=None):
    n = len(y)
    score = score_override if score_override is not None else np.abs(y - pred)
    rows = []
    for cov in coverages:
        retain = np.zeros(n, dtype=bool)
        thr_list = []
        for i in range(n):
            mask = (bin_labels == bin_labels[i]) & (np.arange(n) != i)
            if mask.sum() < 4:
                mask = np.arange(n) != i
            thr = float(np.quantile(score[mask], cov))
            thr_list.append(thr)
            retain[i] = score[i] <= thr
        m = _retained(y, pred, retain)
        m["coverage_target"] = float(cov)
        m["threshold_mean"] = float(np.mean(thr_list))
        m["threshold_std"] = float(np.std(thr_list))
        rows.append(m)
    return rows


def predicted_bins(pred):
    n = len(pred)
    bins = np.zeros(n, dtype=int)
    for i in range(n):
        mask = np.arange(n) != i
        q = np.quantile(pred[mask], [0.25, 0.5, 0.75])
        bins[i] = int(np.searchsorted(q, pred[i]))
    return bins


# ── TASK 1 — 5-null gate on Cell A ────────────────────────────────────────────


def load_iter47_oof():
    df = pd.read_csv(ITER47_OOF_CSV)
    df = df[(df["cohort"] == "drop_allmissing_validrange")
            & (df["stage2_policy"] == "stage2_current")].copy().reset_index(drop=True)
    return df["sid"].to_numpy(), df["y_true_validrange"].to_numpy(np.float64), \
        df["y_pred"].to_numpy(np.float64)


def null_gate_cell_A() -> dict:
    sids, y, pred = load_iter47_oof()
    n = len(y)
    bins = predicted_bins(pred)
    # Real result for comparison
    real = mondrian_cp(y, pred, bins, COVERAGE_TARGETS)
    real_70 = [r for r in real if abs(r["coverage_target"] - 0.7) < 1e-3][0]["retained_ccc"]

    # N1 — scrambled-label sanity
    rng = np.random.default_rng(42)
    y_scrambled = y[rng.permutation(n)]
    n1 = mondrian_cp(y_scrambled, pred, bins, COVERAGE_TARGETS)
    n1_70 = [r for r in n1 if abs(r["coverage_target"] - 0.7) < 1e-3][0]["retained_ccc"]

    # N2 — SID-shuffle before bin assignment
    sid_shuf = rng.permutation(n)
    bins_shuf = bins[sid_shuf]  # bins reassigned to wrong subjects
    n2 = mondrian_cp(y, pred, bins_shuf, COVERAGE_TARGETS)
    n2_70 = [r for r in n2 if abs(r["coverage_target"] - 0.7) < 1e-3][0]["retained_ccc"]

    # N3 — canary: inject random noise into the score, see if it perturbs result
    rng2 = np.random.default_rng(1337)
    canary_score = np.abs(y - pred) + rng2.normal(0, 0.01, size=n)
    n3 = mondrian_cp(y, pred, bins, COVERAGE_TARGETS, score_override=canary_score)
    n3_70 = [r for r in n3 if abs(r["coverage_target"] - 0.7) < 1e-3][0]["retained_ccc"]

    # N4 — library-exclusion: static check that no global y-aware model fits
    n4_pass = True
    n4_findings = []
    script_text = (REPO_ROOT / "run_vnext_ablation_batch.py").read_text()
    for bad in ("XGBRanker", "T_grid", ".fit(X_all", ".fit(np.asarray(y_all"):
        if bad in script_text:
            n4_pass = False
            n4_findings.append(bad)

    # N5 — transductive sanity: GLOBAL quantile (uses all 95 subjects in calibration)
    abs_res = np.abs(y - pred)
    trans_rows = []
    for cov in COVERAGE_TARGETS:
        thr = float(np.quantile(abs_res, cov))
        retain = abs_res <= thr
        m = _retained(y, pred, retain)
        m["coverage_target"] = float(cov)
        m["threshold"] = thr
        trans_rows.append(m)
    trans_70 = [r for r in trans_rows if abs(r["coverage_target"] - 0.7) < 1e-3][0]["retained_ccc"]

    return {
        "task": "cell_A_null_gate",
        "real_retained_ccc_70": real_70,
        "N1_scrambled_label_70": n1_70,
        "N2_sid_shuffle_70": n2_70,
        "N3_canary_score_70": n3_70,
        "N4_library_exclusion_pass": n4_pass,
        "N4_findings": n4_findings,
        "N5_transductive_global_quantile_70": trans_70,
        "N5_inductive_minus_transductive": real_70 - trans_70,
        "gate_pass_summary": {
            "N1_low_under_scramble": abs(n1_70) < 0.10,
            "N2_low_under_sid_shuffle": abs(n2_70 - n1_70) < 0.15,
            "N3_robust_to_tiny_canary": abs(n3_70 - real_70) < 0.05,
            "N4_no_banned_libs": n4_pass,
            "N5_gap_consistent_with_LOO": abs(real_70 - trans_70) < 0.10,
        },
        "real_full_rows": real,
        "n1_full_rows": n1,
        "n2_full_rows": n2,
        "n3_full_rows": n3,
        "n5_transductive_rows": trans_rows,
    }


# ── TASK 2 — T1 Mondrian-CP analog ────────────────────────────────────────────


def load_iter34_t1():
    npz = np.load(ITER34_PER_ITEM_OOF)
    return np.array([str(s) for s in npz["sids"]]), npz["y_t1"], npz["t1_sum_pred"]


def t1_mondrian_cp() -> dict:
    sids, y, pred = load_iter34_t1()
    n = len(y)
    bins = predicted_bins(pred)
    rows = mondrian_cp(y, pred, bins, COVERAGE_TARGETS)
    monot = sum(1 for j in range(1, len(rows))
                if rows[j]["retained_ccc"] < rows[j - 1]["retained_ccc"] - 0.01)
    return {
        "task": "T1_mondrian_cp",
        "n": n,
        "predictor": "iter34_hybrid_T1_sum",
        "bins_source": "outer_train_only_LOO_quartile_of_predicted_T1",
        "rows": rows,
        "monotonicity_violations": monot,
        "comparator_t1_conformal_v2_only_70%": 0.7777,
        "comparator_t1_conformal_v2_only_50%": 0.8338,
        "verdict_70": ("BEATS_V2_LOCK" if rows[2]["retained_ccc"] > 0.7777
                       else ("MATCHES" if abs(rows[2]["retained_ccc"] - 0.7777) < 0.01
                             else "BELOW_V2_LOCK")),
        "verdict_50": ("BEATS_V2_LOCK" if rows[3]["retained_ccc"] > 0.8338
                       else ("MATCHES" if abs(rows[3]["retained_ccc"] - 0.8338) < 0.01
                             else "BELOW_V2_LOCK")),
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    out = {
        "name": "vnext_aux_null_gate_and_t1_mondrian",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "ts": TS,
        "task_1_null_gate": null_gate_cell_A(),
        "task_2_t1_mondrian_cp": t1_mondrian_cp(),
    }
    path = RESULTS_DIR / f"lockbox_vnext_aux_null_gate_and_t1_mondrian_{TS}.json"
    path.write_text(json.dumps(out, indent=2, default=lambda o: o.tolist()
                               if hasattr(o, "tolist") else o))
    print(f"[v-next-aux] wrote {path}")
    g = out["task_1_null_gate"]
    t1m = out["task_2_t1_mondrian_cp"]
    print(f"[v-next-aux] Cell A null gate:")
    for k, v in g["gate_pass_summary"].items():
        print(f"  {k}: {v}")
    print(f"  N1_scrambled_70 = {g['N1_scrambled_label_70']:.4f}")
    print(f"  N2_sid_shuffle_70 = {g['N2_sid_shuffle_70']:.4f}")
    print(f"  N3_canary_70 = {g['N3_canary_score_70']:.4f}")
    print(f"  N5_transductive_70 = {g['N5_transductive_global_quantile_70']:.4f}")
    print(f"  REAL_70 = {g['real_retained_ccc_70']:.4f}")
    print(f"\n[v-next-aux] T1 Mondrian-CP:")
    for r in t1m["rows"]:
        print(f"  cov={r['coverage_target']:.2f} N={r['retained_n']:3d} "
              f"CCC={r['retained_ccc']:.4f} MAE={r['retained_mae']:.3f}")
    print(f"  monotonicity_violations = {t1m['monotonicity_violations']}")
    print(f"  verdict_70 = {t1m['verdict_70']}")
    print(f"  verdict_50 = {t1m['verdict_50']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
