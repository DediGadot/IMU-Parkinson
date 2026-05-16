"""Conformal abstention for T1 — secondary high-confidence operating mode.

Codex's final suggestion (2026-05-12): "Conformal abstention can raise CCC on
a retained subset. At 70-80% coverage, retained-subset CCC may improve by
+0.03 to +0.08." Useful as a secondary deployment mode, not a ceiling breaker.

Algorithm:
1. Use V2+V3-GSP stacked prediction (50/50, the best simple-stack).
2. Per-subject CREDIBILITY = |V2_pred - V3-GSP_pred| (disagreement).
   High disagreement = uncertain prediction. Low = confident.
3. For coverage τ ∈ {1.0, 0.9, 0.8, 0.7, 0.6, 0.5}:
   - Sort subjects by credibility (low disagreement → high confidence)
   - Keep top τ% most-confident subjects
   - Compute CCC over retained set
4. Report retained-CCC + retained-N per coverage level.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path('/home/fiod/medical/results')


def ccc(y, p):
    if len(y) < 3:
        return float('nan')
    yb, pb = y.mean(), p.mean()
    denom = y.var() + p.var() + (yb-pb)**2
    if denom < 1e-12:
        return float('nan')
    return 2 * ((y-yb)*(p-pb)).mean() / denom


def main():
    print("=" * 72)
    print("CONFORMAL ABSTENTION — high-confidence operating mode")
    print("=" * 72)

    # Load OOF predictions
    with open(R / 'lockbox_t1_iter34_hybrid_20260510_233019.json') as f:
        j_v2 = json.load(f)
    p_v2 = np.load(R / 'lockbox_t1_iter34_hybrid_20260510_233019.oof.npy')
    sids = [str(s) for s in j_v2['per_subject']['sids']]
    y_true = np.array(j_v2['per_subject']['y_true'])

    with open(R / 'lockbox_t1_v3_gsp_v3_only_20260512_195152.json') as f:
        j_gsp = json.load(f)
    p_gsp_all = np.load(R / 'lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy')
    sid_gsp = dict(zip([str(s) for s in j_gsp['per_subject']['sids']], p_gsp_all.tolist()))
    p_gsp = np.array([sid_gsp[s] for s in sids])

    p_stack = 0.5 * p_v2 + 0.5 * p_gsp
    n = len(y_true)
    print(f"\nCohort: N={n}")
    print(f"Base predictions: V2 CCC={ccc(y_true, p_v2):.4f}  GSP CCC={ccc(y_true, p_gsp):.4f}")
    print(f"  Stacked (50/50) CCC = {ccc(y_true, p_stack):.4f}  Δ = {ccc(y_true,p_stack)-0.7170:+.4f}")

    # Credibility = |V2 - V3GSP| disagreement
    disagreement = np.abs(p_v2 - p_gsp)
    print(f"\nDisagreement (|V2-V3GSP|) distribution:")
    print(f"  min={disagreement.min():.3f}  median={np.median(disagreement):.3f}  max={disagreement.max():.3f}  mean={disagreement.mean():.3f}")

    # Per coverage τ
    print(f"\n{'coverage':>9s}  {'retained N':>11s}  {'CCC':>7s}  {'Δ vs iter34':>11s}  {'MAE':>6s}")
    print("=" * 60)
    rows = []
    for tau in [1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]:
        # Keep top-tau% most-confident (lowest disagreement)
        k = max(int(np.floor(tau * n)), 5)
        # Indices of lowest-disagreement subjects
        sorted_idx = np.argsort(disagreement)
        keep_idx = sorted_idx[:k]
        y_keep = y_true[keep_idx]
        p_keep = p_stack[keep_idx]
        c = ccc(y_keep, p_keep)
        mae = float(np.mean(np.abs(y_keep - p_keep)))
        delta_vs_iter34 = c - 0.7170  # absolute Δ — note: comparing different cohorts!
        # Per-subject coverage of disagreement
        threshold = disagreement[sorted_idx[k-1]]
        print(f"  {tau:>7.2f}  {k:>10d}  {c:>6.4f}  {delta_vs_iter34:>+11.4f}  {mae:>5.3f}")
        rows.append({
            'coverage': tau, 'retained_n': k,
            'ccc_retained': c, 'mae_retained': mae,
            'disagreement_threshold': float(threshold),
        })

    # Also: same analysis using V2 chain's per-seed standard deviation as uncertainty
    print(f"\n{'=' * 72}\nAlternative credibility: V2-V3GSP variance bound\n{'=' * 72}")
    # Squared deviation from stacked mean
    variance_proxy = 0.25 * (p_v2 - p_stack)**2 + 0.25 * (p_gsp - p_stack)**2 + 0.5 * np.abs(p_v2 - p_gsp)
    print(f"\n{'coverage':>9s}  {'retained N':>11s}  {'CCC':>7s}  {'Δ vs iter34 retained':>20s}  {'MAE':>6s}")
    rows2 = []
    for tau in [1.0, 0.90, 0.80, 0.70, 0.60, 0.50]:
        k = max(int(np.floor(tau * n)), 5)
        sorted_idx = np.argsort(variance_proxy)
        keep_idx = sorted_idx[:k]
        y_keep = y_true[keep_idx]
        p_keep = p_stack[keep_idx]
        c = ccc(y_keep, p_keep)
        mae = float(np.mean(np.abs(y_keep - p_keep)))
        # For comparison, V2 retained on same subjects:
        c_v2_retained = ccc(y_keep, p_v2[keep_idx])
        print(f"  {tau:>7.2f}  {k:>10d}  {c:>6.4f}  Stack vs V2 retained: {c-c_v2_retained:>+10.4f}  {mae:>5.3f}")
        rows2.append({
            'coverage': tau, 'retained_n': k,
            'ccc_retained': c, 'ccc_v2_same_subset': c_v2_retained,
        })

    # Also assess: do the abstained subjects have systematically higher residuals?
    print(f"\n{'=' * 72}\nDiagnostic: who gets abstained?\n{'=' * 72}")
    sorted_idx = np.argsort(disagreement)
    top_confident_20 = sorted_idx[:20]
    bottom_uncertain_20 = sorted_idx[-20:]
    print(f"Most confident 20: y_true range = [{y_true[top_confident_20].min():.1f}, {y_true[top_confident_20].max():.1f}], mean={y_true[top_confident_20].mean():.2f}")
    print(f"Most uncertain 20: y_true range = [{y_true[bottom_uncertain_20].min():.1f}, {y_true[bottom_uncertain_20].max():.1f}], mean={y_true[bottom_uncertain_20].mean():.2f}")
    print(f"Most confident SE_stack = {((y_true[top_confident_20]-p_stack[top_confident_20])**2).mean():.3f}")
    print(f"Most uncertain SE_stack = {((y_true[bottom_uncertain_20]-p_stack[bottom_uncertain_20])**2).mean():.3f}")

    # Save outputs
    out = {
        'method': 'conformal abstention via V2-V3GSP disagreement',
        'full_cohort_ccc': ccc(y_true, p_stack),
        'full_cohort_delta_vs_v2': ccc(y_true, p_stack) - 0.7170,
        'abstention_table_disagreement': rows,
        'abstention_table_variance': rows2,
    }
    with open(R / 'conformal_abstention_summary.json', 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {R / 'conformal_abstention_summary.json'}")


if __name__ == "__main__":
    main()
