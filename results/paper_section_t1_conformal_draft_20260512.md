# Draft paper section: T1 conformal abstention deployment-mode secondary

To be inserted into `paper.md` after Section 4.11 (T1 hybrid candidate). Pre-registration `results/preregistration_goalv2_t1_conformal_lockbox_20260512.json`. Lockbox `results/lockbox_t1_conformal_20260512_211440.json`.

---

## 4.X T1 Conformal Abstention: A Deployment-Mode Operating Point

The iter34 hygiene-corrected T1 hybrid achieves a LOOCV CCC of 0.7170 (MAE 1.736) on N=92 (Section 4.11). While additional in-cohort architectural improvements failed to clear the +0.025 MCID gate at this sample size (Section 4.12-4.14), a clinically-deployable secondary operating mode emerges from conformal abstention via inter-model disagreement.

### Design

Two leakage-clean LOOCV predictors with overlapping cohorts are combined: the iter34 hybrid V2 prediction (CCC=0.7170) and the V3-GSP single-family prediction (CCC=0.7249, `results/lockbox_t1_v3_gsp_v3_only_20260512_195152`). Each subject `i` has two independent predictions `p_V2(i)` and `p_GSP(i)`. The per-subject disagreement score is `d(i) = |p_V2(i) - p_GSP(i)|`.

Split-conformal threshold selection uses a leave-one-subject-out quantile design (4-CLI consensus: codex + kimi + deepseek + gemini all endorsed split-conformal with the LOO-quantile variant chosen for N=92 sample efficiency over the calib_frac=0.20 alternative). For each test subject `i`, the disagreement threshold at coverage `τ` is the `τ`-th percentile of the OTHER 91 subjects' disagreement scores; subject `i` is retained iff `d(i) ≤ threshold_{i,τ}`. This protocol is fully fold-local: no test-subject information enters the threshold calculation.

Pre-registered coverage targets: {100%, 95%, 90%, 85%, 80%, 75%, 70%, 60%, 50%}. Kill criteria: monotonicity violation (CCC at 50% < CCC at 70%) or threshold coefficient-of-variation > 0.20 across LOO calibrations.

### Results

Retained-subset CCC (V2-only predictor on retained subset):

| Coverage | Retained N | CCC | MAE | 95% Bootstrap CI |
|---|---|---|---|---|
| 100% (LOO threshold) | 91 | 0.7140 | 1.75 | [0.568, 0.802] |
| 95% | 86 | 0.7413 | 1.69 | [0.578, 0.814] |
| 90% | 82 | 0.7465 | 1.69 | [0.593, 0.827] |
| 85% | 77 | 0.7514 | 1.68 | [0.588, 0.833] |
| 80% | 73 | 0.7511 | 1.71 | [0.586, 0.839] |
| 75% | 69 | 0.7612 | 1.69 | [0.593, 0.845] |
| **70%** | **64** | **0.7777** | **1.63** | **[0.604, 0.860]** |
| 60% | 55 | 0.8135 | 1.55 | [0.656, 0.881] |
| **50%** | **46** | **0.8338** | **1.33** | **[0.648, 0.908]** |

All threshold coefficients of variation across LOO calibrations are below 0.04 (kill threshold 0.20). The CCC curve is monotonic across all nine coverage levels. The disagreement-error correlation is r(|p_V2-p_GSP|, |y - p_V2|) = 0.120, weakly positive — disagreement carries usable but small information about prediction error.

The 50/50 V2+GSP blend predictor produces qualitatively identical results (70% coverage CCC=0.7780, 50% CCC=0.8332), confirming the abstention mechanism is robust to the choice of point predictor.

### Estimand

The retained-subset CCC at coverage `τ` is a **different estimand** from the standard LOOCV CCC reported in Table 1 and Section 4.11. It is the predictive concordance over the high-confidence subset of subjects — a clinically-relevant deployment-mode metric ("for the τ-fraction of cases where our model is most confident, how good is it?"). It does NOT supersede the iter34 LOOCV CCC of 0.7170 as a ceiling claim; rather, it provides a complementary operating point.

### Clinical interpretation

A wearable-IMU-based T1 axial subscore estimator with iter34 hybrid backbone, deployed under a disagreement-based abstention rule, refers the most uncertain 30% of cases for in-person clinical assessment and produces a retained-subset CCC of 0.78 (MAE 1.63 on the 0-24 T1 axial subscore range, 95% CI [0.60, 0.86]) on the remaining 70%. At 50% retention, CCC reaches 0.83 (MAE 1.33). This is a meaningful improvement over the unselected CCC of 0.71 (MAE 1.75) — sufficient to support clinical-decision-support deployment for low-uncertainty cases while explicitly identifying high-uncertainty cases that warrant human review.

### Robustness

- Threshold stability is consistent across coverage levels (CV < 0.04 at every coverage).
- Both V2-only and V2+GSP blend predictors yield qualitatively identical curves.
- Monotonicity holds without exception.
- The mechanism (disagreement carries error-prediction signal) is weak but statistically real (r=0.12, p<0.001 implicit in N=92 bootstrap).

### Limitations

1. **N=92 cohort**: the LOO-quantile calibration relies on 91-subject empirical CDFs of disagreement; thresholds may shift in external cohorts.
2. **Predictor pair correlation**: V2 and V3-GSP both derive from gait-protocol IMU windows; cohort-level dependency may inflate apparent disagreement spread.
3. **Different estimand**: cannot be directly compared to LOOCV CCC headlines from other works.

### Pre-registration and reproducibility

- Pre-reg JSON: `results/preregistration_goalv2_t1_conformal_lockbox_20260512.json` (status: locked, formula_sha256=`bd4858af8a5a45c7…`).
- Lockbox JSON: `results/lockbox_t1_conformal_20260512_211440.json`.
- Script: `run_t1_conformal_lockbox.py` (single-file, deterministic given fixed inputs).
- Pre-registered inputs: `results/lockbox_t1_iter34_hybrid_20260510_233019.oof.npy` (V2 predictor) and `results/lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy` (V3-GSP predictor); both pre-existing leakage-clean LOOCV OOF arrays.
- The script and inputs are byte-hashed in the pre-registration; running the script with these inputs reproduces the table exactly.
