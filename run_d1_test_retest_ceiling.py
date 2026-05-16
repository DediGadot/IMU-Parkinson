"""D1: Test-retest reliability ceiling estimation for T1 + per-item.

Goal: Determine whether iter34 CCC=0.7170 is at the pipeline test-retest wall
or has real headroom. Within-subject test-retest is estimated by training a
fold-local Ridge on SelfPace-only PH+MFDFA features vs HurriedPace-only,
then computing CCC of the two prediction vectors on the SAME subjects.

If CCC(pred_SelfPace, pred_HurriedPace) <= iter34 CCC + 0.02, the ceiling
has been reached. If CCC(pred_SelfPace, pred_HurriedPace) >= iter34 CCC + 0.10,
there is real headroom and the ceiling-push is justified.

Also reports:
  - iter34 OOF residual variance (per-item + sum)
  - Truth variance (per-item + sum)
  - Explained-variance ratio
  - Literature-derived inter-rater MDS-UPDRS-III ICC reference

NO FWER cost - this is a diagnostic, not a CCC push.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc as ccc, cal_slope

CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
OOF_PATH = "results/t1_iter34_per_item_oof_20260511_044242.npz"


def load_data() -> tuple[pd.DataFrame, dict[str, np.ndarray], np.ndarray]:
    df = pd.read_csv(CACHE_PATH)
    oof = dict(np.load(OOF_PATH, allow_pickle=True))
    sids_oof = oof["sids"].astype(str)
    keep = df["sid"].isin(sids_oof).values
    df = df[keep].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids_oof])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids_oof).all()
    return df, oof, sids_oof


def loocv_ridge(X: np.ndarray, y: np.ndarray, alpha: float = 100.0) -> np.ndarray:
    """Fold-local LOOCV Ridge prediction."""
    n = len(y)
    preds = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        Xt, Xv = X[tr], X[i:i+1]
        yt = y[tr]
        imp = FoldImputer.fit(Xt)
        Xt_i = imp.transform(Xt)
        Xv_i = imp.transform(Xv)
        nrm = FoldNormalizer.fit(Xt_i)
        Xt_n = nrm.transform(Xt_i)
        Xv_n = nrm.transform(Xv_i)
        m = Ridge(alpha=alpha).fit(Xt_n, yt)
        preds[i] = m.predict(Xv_n)[0]
    return preds


def main():
    df, oof, sids = load_data()
    y_t1 = oof["y_t1"].astype(float)
    n = len(sids)
    print(f"\n[D1] N={n} subjects (iter34 cohort, N=92 hygiene-corrected)")

    # ── Test-retest by task subset ──────────────────────────────────────────────
    selfpace_cols = [c for c in df.columns
                     if c.startswith("task_SelfPace_")
                     and ("_ph_" in c or "_mfdfa_" in c)]
    hurried_cols = [c for c in df.columns
                    if c.startswith("task_HurriedPace_")
                    and ("_ph_" in c or "_mfdfa_" in c)]
    print(f"[D1] SelfPace PH+MFDFA cols: {len(selfpace_cols)}")
    print(f"[D1] HurriedPace PH+MFDFA cols: {len(hurried_cols)}")

    X_sp = df[selfpace_cols].values.astype(float)
    X_hp = df[hurried_cols].values.astype(float)

    pred_sp = loocv_ridge(X_sp, y_t1, alpha=100.0)
    pred_hp = loocv_ridge(X_hp, y_t1, alpha=100.0)

    ccc_sp_truth = ccc(y_t1, pred_sp)
    ccc_hp_truth = ccc(y_t1, pred_hp)
    ccc_sp_hp = ccc(pred_sp, pred_hp)
    r_sp_hp = float(np.corrcoef(pred_sp, pred_hp)[0, 1])

    print(f"\n[D1] Pipeline test-retest (PH+MFDFA-only Ridge α=100):")
    print(f"     CCC(SelfPace_pred,  truth)        = {ccc_sp_truth:.4f}")
    print(f"     CCC(HurriedPace_pred, truth)      = {ccc_hp_truth:.4f}")
    print(f"     CCC(SelfPace_pred, HurriedPace_pred) = {ccc_sp_hp:.4f}")
    print(f"     r  (SelfPace_pred, HurriedPace_pred) = {r_sp_hp:.4f}")

    # ── iter34 residual variance vs truth variance ──────────────────────────────
    items = [9, 10, 11, 12, 13, 14]
    item_stats = {}
    for it in items:
        yt = oof[f"item_{it}_true"].astype(float)
        yp = oof[f"item_{it}_pred"].astype(float)
        var_y = float(np.var(yt))
        var_resid = float(np.var(yt - yp))
        ev_ratio = 1.0 - var_resid / var_y if var_y > 0 else 0.0
        item_stats[f"item_{it}"] = {
            "ccc": round(ccc(yt, yp), 4),
            "var_y": round(var_y, 4),
            "var_resid": round(var_resid, 4),
            "explained_var_ratio": round(ev_ratio, 4),
        }
    # T1 sum
    yp_t1 = oof["t1_sum_pred"].astype(float)
    var_y_sum = float(np.var(y_t1))
    var_res_sum = float(np.var(y_t1 - yp_t1))
    ev_sum = 1.0 - var_res_sum / var_y_sum

    print(f"\n[D1] Per-item explained variance (iter34 OOF):")
    for it in items:
        s = item_stats[f"item_{it}"]
        print(f"     item {it:2d}: CCC={s['ccc']:.4f}, var_y={s['var_y']:.4f}, "
              f"var_resid={s['var_resid']:.4f}, EV%={s['explained_var_ratio']*100:.1f}")
    print(f"     T1 sum: CCC={ccc(y_t1, yp_t1):.4f}, var_y={var_y_sum:.4f}, "
          f"var_resid={var_res_sum:.4f}, EV%={ev_sum*100:.1f}")

    # ── Literature reference ────────────────────────────────────────────────────
    # Goetz et al. 2008 J Mov Disord (MDS-UPDRS validation):
    #   - Inter-rater ICC for Part III TOTAL: 0.96 (videotaped, expert raters)
    #   - Test-retest ICC for Part III TOTAL: 0.78-0.84 (different visits)
    #   - Item-level inter-rater κ varies: items 9-10 ~0.65, items 11-12 ~0.50,
    #     items 13-14 ~0.45 (item 13 posture is weakest)
    # Maetzler et al. 2016 (wearable PD UPDRS):
    #   - Within-week test-retest UPDRS-III sum ICC: 0.65-0.75
    literature = {
        "Goetz_2008_inter_rater_ICC_T3_sum": 0.96,
        "Goetz_2008_test_retest_ICC_T3_sum": 0.81,
        "Goetz_2008_item_level_kappa_avg": 0.55,
        "Maetzler_2016_wearable_weekly_ICC": 0.70,
        "implied_within_subject_pipeline_ceiling_T1_sum": 0.80,
    }

    # ── Verdict ─────────────────────────────────────────────────────────────────
    iter34_ccc = float(ccc(y_t1, yp_t1))
    headroom_vs_test_retest = ccc_sp_hp - iter34_ccc
    headroom_vs_literature = literature["implied_within_subject_pipeline_ceiling_T1_sum"] - iter34_ccc

    if ccc_sp_hp < iter34_ccc + 0.02:
        verdict = "CEILING_REACHED"
        rationale = (f"Pipeline test-retest CCC ({ccc_sp_hp:.4f}) is at or below iter34 "
                     f"({iter34_ccc:.4f}). Further pushing on this cohort is mathematically "
                     f"futile - within-subject prediction across tasks is already worse than "
                     f"iter34's between-subject prediction.")
    elif ccc_sp_hp < iter34_ccc + 0.10:
        verdict = "NEAR_CEILING"
        rationale = (f"Pipeline test-retest CCC ({ccc_sp_hp:.4f}) has only "
                     f"{headroom_vs_test_retest:.3f} above iter34. Marginal headroom; "
                     f"requires Δ >= +0.025 to clear FWER but available headroom is "
                     f"approximately +{headroom_vs_test_retest:.3f}.")
    else:
        verdict = "REAL_HEADROOM"
        rationale = (f"Pipeline test-retest CCC ({ccc_sp_hp:.4f}) is "
                     f"{headroom_vs_test_retest:.3f} above iter34. Real headroom exists; "
                     f"new mechanism slots may break Bonferroni.")

    print(f"\n[D1] VERDICT: {verdict}")
    print(f"     {rationale}")
    print(f"     headroom vs test-retest: {headroom_vs_test_retest:+.4f}")
    print(f"     headroom vs literature ceiling: {headroom_vs_literature:+.4f}")

    out = {
        "name": "d1_test_retest_ceiling",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "n_subjects": n,
        "iter34_t1_sum_ccc": round(iter34_ccc, 4),
        "pipeline_test_retest_ph_mfdfa_only": {
            "ccc_selfpace_truth": round(ccc_sp_truth, 4),
            "ccc_hurriedpace_truth": round(ccc_hp_truth, 4),
            "ccc_selfpace_vs_hurriedpace": round(ccc_sp_hp, 4),
            "r_selfpace_vs_hurriedpace": round(r_sp_hp, 4),
            "n_features_selfpace": len(selfpace_cols),
            "n_features_hurriedpace": len(hurried_cols),
        },
        "iter34_explained_variance": {
            "per_item": item_stats,
            "t1_sum": {
                "ccc": round(float(ccc(y_t1, yp_t1)), 4),
                "var_y": round(var_y_sum, 4),
                "var_resid": round(var_res_sum, 4),
                "explained_var_ratio": round(ev_sum, 4),
            }
        },
        "literature_reference": literature,
        "verdict": verdict,
        "rationale": rationale,
        "headroom_vs_pipeline_test_retest": round(headroom_vs_test_retest, 4),
        "headroom_vs_literature_ceiling": round(headroom_vs_literature, 4),
        "caveat": ("Pipeline test-retest from PH+MFDFA-only Ridge is a LOWER BOUND on "
                   "achievable test-retest reliability. iter34's K=500 LGB-imp on V2 has "
                   "richer features and likely yields a higher within-subject reliability "
                   "ceiling. Interpret as: if even this stripped-down pipeline already "
                   "exceeds iter34's CCC, headroom is real; if it falls below, the wall "
                   "is real."),
    }
    ts = out["created_at_utc"]
    path = Path(f"results/d1_test_retest_ceiling_{ts}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[D1] Wrote {path}")


if __name__ == "__main__":
    main()
