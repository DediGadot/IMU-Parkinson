"""T1 iter40 — Slot D-distill: self-distillation against iter34 in-sample teacher predictions.

Mechanism: student LightGBM trained on V2-K500 features with TARGET = iter34
chain predictions on the OUTER-TRAIN subjects (in-sample for the teacher,
held-out for the student's test).

Per outer fold i:
  tr = all subjects except i; te = {i}.
  Teacher = iter34 chain (3-base ensemble) trained on tr.
  teacher_in_sample[j] = teacher.predict(V2[j]) for j in tr.  (in-sample, overfit)
  Student LGB trained on (V2[tr]-K500, teacher_in_sample[tr] residual).
  Student predicts T1 sum for subject i.

LEAKAGE-SAFETY argument: the teacher trained on tr never saw subject i. Its
in-sample predictions on tr depend only on (V2[tr], y_t1[tr]). The student
learns from these soft labels on tr and predicts i using V2[i] alone. Subject
i's labels never enter the student's training data.

This is mechanistically distinct from:
  - F61 (sample-weighted retraining): F61 reweighted training subjects by
    inverse-error. Distillation here uses teacher predictions as a softer
    target distribution.
  - F66 (chain-order avg): averaged correlated chain OOFs. Distillation here
    trains a DIFFERENT model (student LGB) on the teacher's surface.
  - F58 / F70 (convex blends): blended at prediction time. Distillation
    learns the compression at training time.

Family-wise: slot D-distill of expanded master pre-reg n=8 (iter34_anchor +
slots A/B/C + slot D-distill + 3 single-base candidates from iter41). Per-test
Bonferroni gate frac>0 ≥ 1 - 0.05/8 = 0.99375.

Modes:
  --mode write_prereg
  --mode smoke
  --mode screen
  --mode lockbox
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS, K_FEATURES, SEEDS_DEFAULT, STAGE1_ALPHA, _multitask_predict,
)
from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items, T1_SUM_ITEMS
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features, fit_stage1, load_clinical_dict,
)

ensure_dir(RESULTS_DIR)


def _student_one_fold(args):
    """Outer fold worker for distillation student.

    Steps:
      1. Fit Stage-1 Ridge on outer-train.
      2. Fit iter34 chain (3-base ensemble) on outer-train V2-K500.
      3. Compute teacher's in-sample predictions on outer-train subjects.
      4. Fit student LGB on (V2-K500 outer-train, teacher_in_sample residual).
         Optionally blend in hard target via alpha_blend.
      5. Student predicts outer-test subjects.

    Args: (fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases,
            alpha_blend).

    Returns: (te_idx, t1_pred_te) where t1_pred_te has shape (len(te),).
    """
    (fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases,
     alpha_blend) = args

    # Stage-1
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Item residuals on outer-train (with per-fold means)
    item_means = {}
    items_tr_residual = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    # Feature select fold-locally on outer-train
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    # === Teacher: iter34 chain (3 bases avg) ===
    # Compute teacher predictions on outer-TRAIN (in-sample) AND outer-TEST
    teacher_train_ip = None
    teacher_te_ip = None
    for b in bases:
        # Predict outer-train
        from sklearn.multioutput import RegressorChain
        from run_t1_iter34_hybrid_8item_multibase import _make_regr
        regr = _make_regr(b, seed)
        chain = RegressorChain(regr, order="random", random_state=seed)
        chain.fit(Xtr_sel, items_tr_arr)
        ip_train = chain.predict(Xtr_sel)  # in-sample on outer-train
        ip_te = chain.predict(Xte_sel)
        teacher_train_ip = ip_train if teacher_train_ip is None else teacher_train_ip + ip_train
        teacher_te_ip = ip_te if teacher_te_ip is None else teacher_te_ip + ip_te
    teacher_train_ip = teacher_train_ip / len(bases)
    teacher_te_ip = teacher_te_ip / len(bases)

    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    teacher_train_t1 = (teacher_train_ip[:, t1_sum_idx]
                         + np.array([item_means[i] for i in T1_SUM_ITEMS])
                         ).sum(axis=1) - sum_means_t1  # = T1 sum residual on train
    teacher_te_t1 = (teacher_te_ip[:, t1_sum_idx]
                      + np.array([item_means[i] for i in T1_SUM_ITEMS])
                      ).sum(axis=1) - sum_means_t1  # = T1 sum residual on test

    # === Student: LGB on (V2-K500, soft target = teacher_train_t1) ===
    hard_resid = y_t1[tr] - s1_tr
    soft_target = (alpha_blend * teacher_train_t1
                   + (1 - alpha_blend) * hard_resid)
    student_resid = train_lgb(Xtr_sel, soft_target, Xte_sel, seed)

    return te, s1_te + student_resid, s1_te + teacher_te_t1


def _drive_loocv(seed, X, y_t1, X_s1, items, item_order, bases, n_workers,
                  alpha_blend):
    n = len(y_t1)
    student_preds = np.zeros(n)
    teacher_preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases,
             alpha_blend)
            for fid, (tr, te) in enumerate(splits)]
    ctx = mp.get_context("spawn")
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_student_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, stu_pred, tea_pred = fut.result()
            student_preds[te_idx] = stu_pred
            teacher_preds[te_idx] = tea_pred
            done += 1
            if done % 20 == 0 or done == n:
                print(f"    seed={seed} {done}/{n} folds "
                      f"elapsed={time.time()-t0:.0f}s", flush=True)
    return student_preds, teacher_preds


def _drive_5fold(seed, X, y_t1, X_s1, items, item_order, bases, n_workers,
                  alpha_blend):
    n = len(y_t1)
    student_preds = np.zeros(n)
    teacher_preds = np.zeros(n)
    splits = list(KFold(n_splits=5, shuffle=True,
                         random_state=seed).split(np.arange(n)))
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases,
             alpha_blend)
            for fid, (tr, te) in enumerate(splits)]
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_student_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, stu_pred, tea_pred = fut.result()
            student_preds[te_idx] = stu_pred
            teacher_preds[te_idx] = tea_pred
    return student_preds, teacher_preds


def paired_bootstrap(y, p_a, p_b, n_boot=5000, seed=42):
    rng = np.random.RandomState(seed)
    n = len(y); deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {
        "delta_mean": float(deltas.mean()),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float((deltas > 0).mean()),
    }


def _formula_payload(alpha_blend):
    return {
        "experiment": "T1 iter40 Slot-D-distill — self-distillation, in-sample teacher labels",
        "cohort": {
            "filter": "PD with full items 9-14, 15, 18 (validated loader)",
            "expected_n_subjects": 92,
        },
        "teacher": {
            "config": "iter34 hybrid 8-item chain × 3 base learners",
            "trained_on": "outer-train subjects",
            "labels_used": "y_t1 - s1 residual",
        },
        "student": {
            "model": "LightGBM",
            "k_features": K_FEATURES,
            "target_blend_alpha": alpha_blend,
            "target": "alpha * teacher_in_sample_resid + (1-alpha) * y_t1_resid",
        },
        "leakage_argument": (
            "Teacher trained on outer-train sees only outer-train labels. "
            "Teacher's in-sample predictions on outer-train depend only on "
            "outer-train data. Student trained on (V2[outer-train], teacher_in_sample). "
            "No outer-test labels enter student training. Student predicts "
            "outer-test using V2[outer-test] alone."
        ),
        "screen_gate": {
            "delta_mean_vs_iter34_n92": 0.025,
            "frac_above_zero_paired_bootstrap": 0.95,
        },
        "fwer_family_n8": True,
        "loocv_gate_frac_above_zero": 1 - 0.05/8,
        "seeds": [42, 1337, 7],
    }


def _formula_sha256(payload):
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def write_prereg(alpha_blend):
    payload = _formula_payload(alpha_blend)
    sha = _formula_sha256(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = {
        "preregistration_id": f"t1_iter40_distillation_slotD_{stamp}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": sha,
        "formula": payload,
        "alpha_blend": alpha_blend,
    }
    path = RESULTS_DIR / f"preregistration_t1_iter40_distillation_slotD_{stamp}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {path}\n  formula_sha256 = {sha}", flush=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                    choices=["smoke", "screen", "lockbox", "write_prereg"])
    ap.add_argument("--alpha_blend", type=float, default=1.0)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--n_workers", type=int, default=5)
    ap.add_argument("--preregistration_file", type=Path)
    args = ap.parse_args()

    if args.mode == "write_prereg":
        write_prereg(args.alpha_blend)
        return

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}, alpha={args.alpha_blend}",
          flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[args.feature_set])

    if args.mode == "smoke":
        print("=== SLOT D-DISTILL SMOKE: 1 fold × 1 seed ===", flush=True)
        seed = args.seeds[0]
        splits = list(LeaveOneOut().split(np.arange(n)))
        tr, te = splits[0]
        t0 = time.time()
        job = (0, tr, te, X, y_t1, X_s1, items, item_order, seed,
               BASE_LEARNERS, args.alpha_blend)
        te_idx, stu_pred, tea_pred = _student_one_fold(job)
        print(f"  fold 0/{n}: sid={sids[te_idx[0]]}, y_true={y_t1[te_idx[0]]:.2f}, "
              f"student_pred={stu_pred[0]:.2f}, teacher_pred={tea_pred[0]:.2f}, "
              f"wall={time.time()-t0:.1f}s", flush=True)
        print("  SMOKE PASS", flush=True)
        return

    if args.mode == "screen":
        print(f"=== SLOT D-DISTILL 5-FOLD SCREEN (3 seeds, alpha={args.alpha_blend}) ===",
              flush=True)
        per_seed = []
        for seed in args.seeds:
            t0 = time.time()
            stu, tea = _drive_5fold(seed, X, y_t1, X_s1, items, item_order,
                                     BASE_LEARNERS, args.n_workers, args.alpha_blend)
            ccc_s = ccc_fn(y_t1, stu); ccc_t = ccc_fn(y_t1, tea)
            print(f"  seed={seed}: STUDENT={ccc_s:.4f} | TEACHER_in_sample={ccc_t:.4f} "
                  f"| Δ={ccc_s-ccc_t:+.4f} | wall={time.time()-t0:.0f}s", flush=True)
            per_seed.append({"seed": seed, "student": float(ccc_s),
                             "teacher": float(ccc_t),
                             "student_preds": stu.tolist(),
                             "teacher_preds": tea.tolist()})
        deltas = np.array([s["student"] - s["teacher"] for s in per_seed])
        delta_mean = float(deltas.mean())
        stu_mean = np.mean(np.array([s["student_preds"] for s in per_seed]), axis=0)
        tea_mean = np.mean(np.array([s["teacher_preds"] for s in per_seed]), axis=0)
        bs = paired_bootstrap(y_t1, stu_mean, tea_mean, n_boot=5000)
        print(f"\n  Δ̄ mean-of-seeds: {delta_mean:+.4f}", flush=True)
        print(f"  paired-bootstrap frac>0 vs teacher: {bs['frac_above_zero']}",
              flush=True)
        print(f"  bootstrap 95% CI: [{bs['delta_ci_low']:+.4f}, {bs['delta_ci_high']:+.4f}]",
              flush=True)
        gate_pass = (delta_mean >= 0.025) and (bs["frac_above_zero"] >= 0.95)
        print(f"  GATE: Δ̄ ≥ +0.025 AND frac>0 ≥ 0.95 = {gate_pass}", flush=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"screen_t1_iter40_slotD_distill_{stamp}.json"
        with open(out_path, "w") as f:
            json.dump({
                "n_subjects": n, "alpha_blend": args.alpha_blend,
                "per_seed": [{"seed": s["seed"], "student": s["student"],
                              "teacher": s["teacher"]} for s in per_seed],
                "delta_mean": delta_mean,
                "bootstrap": bs, "gate_pass": gate_pass,
            }, f, indent=2)
        print(f"\nWrote {out_path}", flush=True)
        return

    if args.mode == "lockbox":
        if not args.preregistration_file or not args.preregistration_file.exists():
            print("ERROR: --preregistration_file required and must exist", flush=True)
            sys.exit(1)
        with open(args.preregistration_file) as f:
            prereg = json.load(f)
        expected = _formula_sha256(_formula_payload(args.alpha_blend))
        if prereg["formula_sha256"] != expected:
            print(f"ERROR: prereg sha {prereg['formula_sha256']!r} != current {expected!r}",
                  flush=True)
            sys.exit(1)
        print(f"=== SLOT D-DISTILL LOOCV (3 seeds, alpha={args.alpha_blend}) ===",
              flush=True)
        per_seed = []
        overall_t0 = time.time()
        for seed in args.seeds:
            t0 = time.time()
            stu, tea = _drive_loocv(seed, X, y_t1, X_s1, items, item_order,
                                     BASE_LEARNERS, args.n_workers, args.alpha_blend)
            ccc_s = ccc_fn(y_t1, stu); ccc_t = ccc_fn(y_t1, tea)
            print(f"  seed={seed}: STUDENT_CCC={ccc_s:.4f} | TEACHER_in_sample={ccc_t:.4f} "
                  f"| wall={time.time()-t0:.0f}s", flush=True)
            per_seed.append({"seed": seed, "student": float(ccc_s),
                             "teacher": float(ccc_t),
                             "preds": stu.tolist()})

        stu_mean = np.mean(np.array([s["preds"] for s in per_seed]), axis=0)
        m = full_metrics(y_t1, stu_mean)
        teacher_oof = np.load(
            RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
        )
        bs_vs_iter34 = paired_bootstrap(y_t1, stu_mean, teacher_oof, n_boot=5000)
        gate = bs_vs_iter34["frac_above_zero"] >= (1 - 0.05/8)
        print(f"\n=== HEADLINE: CCC={m['ccc']:.4f}, MAE={m['mae']:.4f}, "
              f"r={m['r']:.4f}, slope={m['cal_slope']:.4f} ===", flush=True)
        print(f"  vs iter34-N=92 LOOCV: Δ={m['ccc']-0.7170:+.4f}, "
              f"paired-bootstrap frac>0={bs_vs_iter34['frac_above_zero']}", flush=True)
        print(f"  Bonferroni n=8 gate (frac>0 ≥ {1-0.05/8:.4f}) = {gate}", flush=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"lockbox_t1_iter40_slotD_distill_{stamp}.json"
        with open(out_path, "w") as f:
            json.dump({
                "n_subjects": n, "alpha_blend": args.alpha_blend,
                "ccc": m["ccc"], "mae": m["mae"], "r": m["r"],
                "cal_slope": m["cal_slope"],
                "per_seed": [{"seed": s["seed"], "student": s["student"],
                              "teacher": s["teacher"]} for s in per_seed],
                "bootstrap_vs_iter34_n92": bs_vs_iter34,
                "fwer_gate_pass": gate,
                "wall_s_total": time.time() - overall_t0,
            }, f, indent=2)
        np.save(out_path.with_suffix(".oof.npy"), stu_mean)
        print(f"\nWrote {out_path}", flush=True)
        return


if __name__ == "__main__":
    main()
