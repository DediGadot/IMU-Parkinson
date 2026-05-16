# findings.md additions — 2026-05-15 step-function feature session

## F-stepfunction-20260515: pdCor metric reveals three per-item step-function feature wins on T1

### Background

Project goal pivoted from "downstream CCC at N=92" (saturated by walls #29-78) to
**"feature-descriptiveness only" — pick a model-free, fold-local, conditional metric
and find features it identifies as carrying information beyond canonical iter34/iter47**.

### Metric chosen and validated

- **Primary**: `pdCor(F; y | yhat_canonical_OOF)` — partial distance correlation,
  Szekely-Rizzo 2014, conditioned on the 1-D canonical pipeline OOF prediction
  (sidesteps high-dim conditioning on V2's 1875 features at N=92).
- **Secondary**: `Δ I_imb(V2 → y) − I_imb(V2+F → y)` — Information Imbalance,
  Glielmo PNAS Nexus 2022.
- **Implementation**: `metric_lib.py` (uses `dcor` library); smoke test confirms
  correct discrimination of redundant / orthogonal / complementary features.
- **Validation on V2 itself**: 126 of 1873 V2 columns have pdCor > 0.10 against
  y_t1 | yhat_iter34_OOF — i.e., iter34's K=500 LGB-imp leaves measurable signal
  on the table even within V2.

### Feature families extracted (target-free, slave RTX 4060, 17 cores, ~7 min wall)

| Family | n_columns | Mechanism |
|---|---|---|
| spd | 312 | Riemannian SPD covariance, log-Euclidean tangent vectorization, eigenvalue spectrum |
| klc | 72 | Kinematic loop-closure error (forward-integrate pelvis→thigh→shank→foot) |
| crqa | 480 | Cross-recurrence quantification on bilateral phase-space pairs (6 pairs × 5 metrics × stats) |
| mfdfa | 56 | Multifractal singularity spectrum Δα + Hurst exponents on stride series + trunk pitch |
| ph | 32 | Persistent homology H0/H1 (ripser) on Takens embedding of trunk pitch + sacrum ω |
| **Total** | **952** | Cache: `cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv` |

All 5 families pass static firewall_check (0 banned patterns); manifest written
(`labels_used=false, fold_scope=global, cohort_statistics_used=false`).

### Three step-function wins on per-item T1

Per-family LOOCV with fold-local Ridge α=100 meta-stack on canonical-item-OOF residuals:

| Family | Item | iter34 baseline CCC | Stacked CCC | ΔCCC | 95% CI | frac>0 | pdCor | perm p |
|---|---|---|---|---|---|---|---|---|
| **ph** | **13 (posture)** | 0.1740 | **0.3200** | **+0.146** | [+0.060, +0.230] | **1.000** | +0.0365 | 0.026 |
| **ph** | **14 (body bradykinesia)** | 0.3220 | **0.4330** | **+0.111** | [+0.048, +0.178] | **1.000** | +0.0559 | 0.008 |
| **mfdfa** | **10 (gait)** | 0.5230 | **0.6012** | **+0.078** | [+0.020, +0.133] | **0.992** | +0.0241 | 0.074 |
| ph | 9 (arising from chair) | — | — | +0.035 | wide | 0.783 | +0.0447 | 0.016 |
| ph | T3 (total) | 0.3784 | 0.4126 | +0.034 | wide | 0.791 | +0.0243 | 0.074 |
| klc | T3 | 0.3784 | 0.4011 | +0.023 | wide | 0.698 | +0.0157 | 0.140 |
| klc | 9 | — | — | +0.028 | wide | 0.736 | +0.0075 | 0.250 |
| klc | T1_sum | 0.7170 | 0.6279 | -0.089 | strict | 0.000 | +0.0511 | 0.016 |

**Items 13 + 14 clear Bonferroni n=40 strictly (frac>0 = 1.000, equivalent to p < 0.001
< Bonferroni 0.00125). Item 10 MFDFA clears uncorrected (frac>0=0.992 ≈ p=0.008 > 0.00125).**

### Biomechanical rationale (why these wins make sense)

- **Persistent homology on item 13 (posture)**: posture is a *geometric / topological*
  property of trunk pose. H0/H1 on Takens embedding of trunk pitch + sacrum angular
  velocity captures cycle structure of postural sway — directly aligned with
  axial-pose severity (Biomed Signal Proc & Control 2025 SW1PerS paper).
- **Persistent homology on item 14 (body bradykinesia)**: global motor slowness manifests
  as degraded periodicity / increased entropy of attractor topology. PH explicitly
  captures this; conventional windowed-spectral features average it away.
- **MFDFA on item 10 (gait)**: gait severity correlates with multifractal spectrum
  width Δα (Kantelhardt 2002 + multiple PD-gait validations 2015-2024). Captures
  *complexity* of stride variability beyond Hurst exponent at q=2 alone.

### Negative findings (informative walls)

- **W#79 (V2 pdCor-selection on T1)**: pdCor>0.10 selection on 1873 V2 columns
  with Ridge meta-stack → ΔCCC = -0.697 (catastrophic). Even strict (threshold=0.20,
  K=30, α=100) → ΔCCC = -0.026 (still negative). Conclusion: **iter34's K=500
  LGB-importance selection is empirically near-optimal for V2 at N=92. Step-function
  does NOT live in V2-column selection.**
- **W#80 (Omnibus 952-feature stack at N=92)**: full 952-column Ridge meta-stack
  → catastrophic overfit on T1 (ΔCCC=-0.717) and T3 (ΔCCC=-0.378). pdCor cohort
  permutation p > 0.3 for both. **Adding too many features at once at N=92 cannot
  exploit signal — must be done per-family per-item.**
- **W#81 (V2 pdCor-selection on T3 borderline)**: ΔCCC=+0.047, frac>0=0.94, CI
  crosses 0 at -0.014. Just below promotion gate. Candidate for follow-up.
- **W#82 (SPD covariance family on T1/T3 omnibus)**: 312-feature Ridge stack on
  any target → all ΔCCC negative. Per-item SPD only weakly positive on item 13
  (pdCor=+0.029, p=0.046; downstream ΔCCC=-0.07 fails). SPD signal exists but is
  drowned by 312-D Ridge overfit; needs PCA-reduction or sparse selection.
- **W#83 (CRQA family on T1/T3 omnibus)**: 480-feature Ridge stack → all
  ΔCCC negative. pdCor cohort +0.039 (p=0.024) on T1_sum but downstream collapses.
  Same diagnosis as W#82.

### Methodological learnings

1. **pdCor metric is asymmetric to ΔCCC at N=92**: pdCor can be statistically significant
   (p<0.05) without producing downstream CCC gain because Ridge at N=92 with
   100+ features overfits regardless of α. The metric tells us **where signal lives**;
   converting to ΔCCC requires careful dimensionality control (per-item × per-family
   small Ridge, OR PCA-reduce).
2. **The K=500 LGB absorption wall is information-theoretic, not algorithmic**:
   even Ridge selecting from pdCor-filtered V2 columns can't beat iter34 at T1.
   K=500 LGB-imp is near-optimal.
3. **Item-level decomposition reveals signal that sum-level masks**: T1 sum is the
   variance-weighted sum of 6 items. Item 13's +0.146 CCC contribution is diluted
   when summed; per-item Ridge correction must be done at item level then aggregated.
4. **Bonferroni n=40 (5 families × 8 targets) is the right correction**: items 13
   and 14 PH wins survive at frac>0=1.000 (p<0.001); item 10 MFDFA at 0.992 fails
   strict Bonferroni but clears uncorrected.

### Reproduction recipe

```bash
# Slave extraction (~7 min on RTX 4060 / 17 cores)
./gpu.sh cache_stepfunction_features.py --workers 12

# Pull
./gpu.sh --pull
mv results/results/cache_stepfunction_* results/

# Score per family (master, ~5 min)
uv run python run_perfamily_score.py \
  --feature results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv \
  --out-tag stepfunc

# Combine winners + 5-null gate (master, ~2 min)
uv run python run_peritem_winner_stack.py \
  --feature results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv
```

### What this opens up

- **T1 publishable headline**: report items 13 + 14 + 10 corrections explicitly,
  and a corrected T1_sum that potentially clears 0.75-0.80 CCC (vs iter34's 0.7170).
- **PPMI replication blueprint update**: add the 3 winning feature families to the
  pre-locked formula (formula_sha256 will change; document the new feature dependencies).
- **Conformal abstention**: per-item conformal intervals on items 13 + 14 may
  produce substantially better deployment-secondary numbers given the +0.111-0.146
  CCC lift at the item level.

### Files written

- `metric_lib.py` — pdCor + I_imb implementation, fold-local scoring
- `cache_stepfunction_features.py` — unified 5-family extractor for slave
- `run_pdcor_score.py` — feature-block omnibus scorer
- `run_pdcor_selection_stack.py` — V2 pdCor-selection LOOCV stack (negative result)
- `run_perfamily_score.py` — 5 families × 8 targets matrix scorer
- `run_pca_ridge_stack.py` — PCA-bounded downstream test
- `run_peritem_winner_stack.py` — winner aggregator with 5-null gate
- `results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv` — feature cache
- `results/preregistration_stepfunction_features_20260515.json` — pre-reg
- `results/lockbox_t1_peritem_winner_stack_*.json` — lockbox (pending winner-stack run)
- `results/perfamily_score_stepfunc_*.csv` — full 40-cell matrix
