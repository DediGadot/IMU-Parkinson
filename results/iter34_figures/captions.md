# iter34 figure captions (paper-ready)

Generated 2026-05-06. Source: `visualize_iter34.py`.
Underlying lockbox JSON: `results/lockbox_t1_iter34_hybrid_20260506_141720.json`
(LOOCV n=93, mean of 3 seeds {42, 1337, 7}, headline CCC = 0.7366).

---

## Figure 1 — `fig1_oof_calibration_iter34.png`

**Caption.** Out-of-fold calibration of the iter34 hybrid T1 pipeline (8-item
multi-task RegressorChain over UPDRS-III items 9–14 plus auxiliary items 15
and 18, with a 3-base lgb / xgb / et stack). Each point is one of n = 93 PD
subjects (the iter34 lockbox cohort, common to iter33-B); the predicted score
is the mean across 3 seeds of LOOCV out-of-fold predictions. The dashed grey
line is the y = x identity; the solid orange line is the empirical least-
squares fit (predicted on true) with slope a = 0.821, and the dotted purple
line shows the calibration slope reported in the lockbox JSON
(cal_slope = 0.8215). Headline LOOCV metrics: CCC = 0.7366, MAE = 1.731 UPDRS,
Pearson r = 0.7406. Under-prediction at the high tail and slight over-
prediction at the low tail are visible — typical regression-to-mean shrinkage
discussed in Figure 2.

## Figure 2 — `fig2_residual_by_quartile_iter34.png`

**Caption.** Residual (predicted − true) distribution for the iter34 hybrid,
stratified by true-T1 quartile (Q1: T1 ≤ 2, n = 27; Q2: 2 < T1 ≤ 4, n = 33;
Q3: 4 < T1 ≤ 5, n = 12; Q4: T1 > 5, n = 21). Boxes show the IQR with the
median; jittered points are individual subjects. Per-quartile mean ± SD
(annotated above each box) reveals a systematic tail asymmetry: Q1 is
over-predicted by +0.93 ± 1.74 UPDRS and Q4 is under-predicted by
−0.72 ± 2.87 UPDRS, with corr(y_true, residual) = −0.233. This shrinkage is
characteristic of LightGBM-tree-leaf prediction at N = 93 and matches the
F61/F54 finding for T3: iter34 inherits the same structural tail compression
as the rest of the family. Q3 (n = 12) is the smallest bin and its statistics
should be read with corresponding caution.

## Figure 3 — `fig3_per_subject_delta_iter34.png`

**Caption.** Per-subject change in absolute LOOCV error, |err iter12 honest|
− |err iter34|, on the n = 93 cohort common to both pipelines (iter12 honest
canonical CCC = 0.6550 on n = 94; restricted-to-93 CCC = 0.6553 — see
`results/iter34_vs_iter12_honest_n93_paired_2026_05_06.json`). Subjects are
sorted by improvement; green bars indicate iter34 reduced absolute error;
red bars indicate iter12 honest was closer. Counter-intuitively, iter34 is
strictly worse on a per-subject majority (50/93 subjects, 54%) and the net
sum of |Δ error| is −15.06 UPDRS in iter12's favour, **yet** iter34's
LOOCV CCC is +0.081 higher. The reason — visible in the bar shape — is that
iter34's wins are concentrated at a small number of high-impact tail
subjects (top three: NLS196, NLS154, NLS185, each ≥ +2.5 UPDRS error
reduction), while its losses are individually smaller. CCC weights these
correctly because it penalises large absolute residuals quadratically. This
pattern is a clean argument for reporting CCC alongside MAE in PD-IMU
benchmarks rather than relying on subject-level error fractions.

## Figure 4 — `fig4_seed_consistency_iter34.png`

**Caption.** Per-seed LOOCV CCC across the iter33 family and iter34. Coloured
circles are individual seeds; diamonds with black outlines are the run mean
(numeric value annotated to the right). iter33-A is the F65 reanchor with
n = 7 seeds at n = 94 cohort (CCC = 0.7089, seed range 0.706–0.711);
iter33-B is the 8-item chain at n = 93 (CCC = 0.7219, seed range 0.7213–
0.7219); iter33-C is the multi-base lgb+xgb+et stack at n = 94 (CCC = 0.7231,
seed range 0.7225–0.7236); iter34 is the hybrid at n = 93 (CCC = 0.7366,
seed range 0.7359–0.7371). The orange band on the iter34 column is the
95% paired-bootstrap confidence interval on Δ vs iter5-direct (CCC ∈
[0.6676, 0.8148] when mapped to absolute CCC). iter34's per-seed cluster
sits at the top of the entire family with seed std ≈ 0.0006 — by far the
tightest seed dispersion of the four lockboxes. Reference lines: iter12
honest canonical (CCC = 0.6550, dashed purple) and iter5-direct LOOCV
baseline (CCC = 0.6496, dotted grey).

## Figure 5 — `fig5_iter_progression.png`

**Caption.** LOOCV CCC progression across the iter12 honest baseline, the
iter33-A/B/C family, and the iter34 hybrid. Bar widths are zoomed to the
[0.62, 0.76] CCC interval to make the differences visible; numeric CCCs are
printed at each bar tip. The right-side panel reports paired-bootstrap
fractions vs the iter5-direct LOOCV baseline (frac > 0 and frac > +0.025)
together with which gate each run clears: strict α = 0.05 (frac > 0 ≥ 0.95);
Bonferroni-corrected for the iter33 family of 3 (≥ 0.9833), the all-iter33
+ per-item family of 8 (≥ 0.9938), and 9 (≥ 0.9944). iter12 honest
(reference, no bootstrap-vs-iter5 row in this lockbox set) sits at 0.6550;
iter33-A clears no gate (frac > 0 = 0.915); iter33-B clears strict only
(0.979); iter33-C clears strict and Bonf-n=3 (0.937 vs 0.95 fails strict —
labelled "fail" because we follow the JSON's stored 5000-bootstrap value
0.937 rather than 0.95); iter34 clears all four gates (frac > 0 = 0.996,
frac > +0.025 = 0.964) with strict, Bonf-n=3, Bonf-n=8, and Bonf-n=9 all
PASS. Per the lockbox JSON's own protocol note, iter34 is registered as a
single post-publication replication target (n_tests = 1 → Bonferroni
adjustment is trivial); the family-wise gates are shown for transparency
only.

---

## Notes for the methods text

- All figures use a deuteranopia-safe Okabe-Ito palette (sky-blue / orange /
  green / vermilion / purple / yellow / grey / black).
- All PNGs are saved at 300 dpi.
- Font is Arial-equivalent (Arial → DejaVu Sans → Liberation Sans).
- Source script `visualize_iter34.py` reads only the four lockbox JSONs and
  the iter12 honest composite JSON; no remote data, no model retraining.
- Sanity check: recomputed CCC from `per_subject.y_true / y_pred` matches
  the reported lockbox CCC to within 1e-4 (0.7366 vs 0.7366).
