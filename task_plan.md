# Task Plan: PD-Only Prediction Power Experiments (v2)

**Objective:** Comprehensively prove the prediction power of the FM Stack pipeline on the PD population (N=98) with rigorous statistical evidence suitable for Nature Digital Medicine.

**Date:** 2026-03-12 (v2 — revised after Codex + Gemini peer review)
**Current best (PD-only):** FM LOOCV MAE=8.147, r=0.429 | Observable LOOCV (v2): 3.32, r=0.460

---

## Executive Summary

All current results include HC subjects (UPDRS≈0), which inflates correlation and compresses MAE. Reviewers will demand PD-only evidence: if a model can only tell PD from HC, it has zero clinical value.

**Medication state:** WearGait-PD does not systematically control ON/OFF dopaminergic state. All subjects assessed in their habitual medication state. This is a documented limitation — UPDRS-III varies with medication, introducing unquantified within-subject variability. We report this honestly.

**Revised plan:** 7 phases, incorporating critical feedback from GPT-5.4 (Codex) and Gemini 3.1-pro:

| Phase | What | Priority | Time |
|-------|------|----------|------|
| **1** | PD-only 10-split: PD-train vs PD+HC-train comparison | ESSENTIAL | ~90 min |
| **2** | FM LOOCV enhanced stats + demographic baseline | ESSENTIAL | ~10 min |
| **3** | Observable vs Partially-Observable vs Unobservable decomposition | ESSENTIAL | ~120 min |
| **4** | Severity-stratified error + confound analysis | HIGH | ~10 min |
| **5** | Locked held-out test (Track A) — PD-subset report | HIGH | ~15 min |
| **6** | PD-only sensor ablation (FM re-extracted per config) | MEDIUM | ~120 min |
| **7** | Consolidated report + publication figures | FORMATTING | ~5 min |

---

## Split Protocol (IMMUTABLE)

### Track A: Locked Held-Out Test (paper3_split.json)
- **Split:** seed=20260309, 142 dev / 36 test
- **Dev:** 77 PD + 65 HC | **Test:** 21 PD + 15 HC
- **Usage:** Primary pre-specified result. Report full test MAE + PD-subset MAE as secondary.
- **Full test stays primary; PD-subset is secondary** (N=21 is too small for primary PD claim)
- **Never touched for model selection**

### Track B: 10-Split Internal Validation
- **Two sub-tracks run in parallel:**
  - **B1 (PD-only train):** Split 98 PD into 80/20. Train on ~78 PD ONLY. Test on ~20 PD. **This is the primary PD analysis.**
  - **B2 (HC-augmented):** Same PD 80/20 split. Train on ~78 PD + ALL 80 HC. Test on same ~20 PD. **This is a sensitivity analysis.**
- Stratification: UPDRS bins AND age terciles (multi-label stratification to avoid covariate shift)
- **Statistical tests:** Subject-level paired bootstrap on out-of-fold errors (NOT split-level Wilcoxon on overlapping folds — Codex correctly flags this as optimistic)

### Track C: PD-Only LOOCV (N=98)
- **Split:** Leave-one-out on 98 PD subjects
- **Training set per fold:** All 177 remaining subjects (97 PD + 80 HC) — standard protocol, not the primary PD claim
- **Sensitivity:** Also report PD-only LOO where training uses 97 PD only (no HC)
- **Feature selection:** INSIDE each LOO fold
- **All preprocessing, scaling, feature selection, stack fitting are fold-internal**

All tracks enforce:
- Subject-level splits (never window-level)
- 5-seed ensemble (42, 123, 456, 789, 2024)
- No per-subject z-normalization for regression targets

---

## Phase 1: PD-Only 10-Split with FM [GPU+CPU, ~90 min]

**Rationale:** Current 10-split FM Stack 7.775±0.439 includes HC. We need pure PD-train/PD-test (primary) AND HC-augmented training (sensitivity) to prove severity discrimination AND quantify HC contribution.

**Split protocol:** Track B. Two sub-tracks run for each of 10 seeds.

**Implementation:**
1. Filter to PD subjects (N=98), compute UPDRS bins + age terciles for multi-label stratification
2. For each seed 1-10: split 98 PD into ~78 dev / ~20 test
3. **Sub-track B1 (primary):** Train on 78 PD only → predict 20 PD test
4. **Sub-track B2 (sensitivity):** Train on 78 PD + 80 HC → predict same 20 PD test
5. **Demographic baseline:** Ridge regression on [Age, Sex, Years_Since_Diagnosis, Height, Weight] → predict same 20 PD test. **IMU model must beat this to prove sensors add value.**
6. Models: v2 LGB baseline, v2+FM LGB, v2+FM stack (for each sub-track)
7. **Statistical tests:**
   - Subject-level paired bootstrap (10000 samples) for MAE difference: FM vs v2, FM vs demographic baseline
   - Cohen's d effect size
   - Lin's concordance correlation coefficient (CCC) — not just Pearson r
   - Calibration slope/intercept (regression of predicted on true)

**Runner:** `run_pd_only_experiments.py --phase 1`
**Compute:** GPU+CPU, ~90 min (2 sub-tracks × 10 seeds × 3 models)

| # | Task | Status |
|---|------|--------|
| 1.1 | Filter PD sids, multi-label stratification (UPDRS bins × age terciles) | DONE |
| 1.2 | Demographic baseline (Ridge on covariates) per split | DONE |
| 1.3 | B1: PD-only train → v2, v2+FM LGB, v2+FM stack | DONE |
| 1.4 | B2: PD+HC train → same models, same PD test set | DONE |
| 1.5 | Subject-level paired bootstrap for all comparisons | DONE |
| 1.6 | CCC, calibration slope, Cohen's d | DONE |
| 1.7 | Compare B1 vs B2: does HC training help or hurt? | DONE |

---

## Phase 2: FM LOOCV Enhanced Statistics + Demographic Baseline [CPU, ~10 min]

**Rationale:** Phase 8 FM LOOCV got MAE=8.147, r=0.429 (N=98 PD). Statistics are minimal. Need full battery + a demographic-only baseline to prove IMU adds value beyond age/disease-duration.

**Split protocol:** Track C. Reuse cached predictions from `rocket_phase8_fm_loocv.json`.

**Implementation:**
1. Load Phase 8 FM LOOCV predictions (98 subjects, cached)
2. **Demographic baseline:** For each LOO fold, train Ridge on [Age, Sex, Disease_Duration, Height, Weight] → predict left-out PD subject. Compare to FM.
3. **Permutation test:** 10000 permutations, H0: MAE(FM model) ≥ MAE(mean predictor)
4. **Bland-Altman:** mean bias, 95% limits of agreement, proportional bias regression (slope of residuals on mean)
5. **Lin's CCC** — measures both precision and accuracy, more informative than Pearson r
6. **Calibration slope/intercept** (regression of predicted on true, ideal = slope 1, intercept 0)
7. **R², MAE/SD(y), NRMSE** — standardized skill metrics (Codex recommendation)
8. **Clinical significance (contextual, not pass/fail — per Codex):**
   - % predictions within ±3.25 (MCID), ±5, ±10 points
   - Frame as "the proportion of PD patients whose prediction error is within clinical noise"
9. **Partial correlation** controlling for age and disease duration — proves IMU signal beyond demographics
10. Error stratification by UPDRS severity quartile
11. Diagnostic plots: scatter with identity line, Bland-Altman, quartile error bars

**Runner:** `run_pd_only_experiments.py --phase 2`
**Compute:** CPU-only, ~10 min (all FM predictions cached)

| # | Task | Status |
|---|------|--------|
| 2.1 | Load FM LOOCV predictions + clinical covariates | DONE |
| 2.2 | Demographic-only LOO baseline | DONE |
| 2.3 | Permutation test (10000) | DONE |
| 2.4 | Bland-Altman + proportional bias | DONE |
| 2.5 | Lin's CCC, R², MAE/SD, NRMSE | DONE |
| 2.6 | Calibration slope/intercept | DONE |
| 2.7 | Partial correlation controlling age + disease duration | DONE |
| 2.8 | Clinical significance (contextual framing) | DONE |
| 2.9 | Severity quartile error stratification | DONE |
| 2.10 | Diagnostic plots | DONE |

---

## Phase 3: Observable vs Partially-Observable vs Unobservable Decomposition [GPU+CPU, ~120 min]

**Rationale:** This is the mechanistic core of the paper. Both Codex and Gemini flagged that a binary observable/unobservable split is too coarse. The revised plan uses a **3-level clinical taxonomy:**

### Item Taxonomy (clinician-defensible)

| Category | Items | Max score | Rationale |
|----------|-------|-----------|-----------|
| **Directly observable** | 3.9 Arising, 3.10 Gait, 3.11 FoG, 3.12 Postural stability, 3.13 Posture, 3.14 Body bradykinesia | 24 | Fully manifest during gait tasks, directly captured by body-worn IMU |
| **Partially observable** | 3.7a/b Toe tapping, 3.8a/b Leg agility, 3.15a/b Postural tremor, 3.16a/b Kinetic tremor, 3.17a-e Rest tremor, 3.5a/b Hand movements, 3.6a/b Pronation-supination | 68 | Some signal from IMU but not the primary test condition (e.g., toe tapping assessed seated, tremor during stillness) |
| **Not observable** | 3.1 Speech, 3.2 Facial expression, 3.3a-e Rigidity, 3.4a/b Finger tapping, 3.18 Constancy of rest tremor | 40 | Requires clinician examination, auditory/visual assessment, or seated finger tasks — zero IMU signal |

**Sensitivity analysis:** Also run the original binary split (items 7-14 vs rest) for backward compatibility.

**Split protocol:** Track C (LOOCV) for PD-only. Track B (10-split) for stability.

**Implementation:**
1. Parse per-item UPDRS scores for all subjects
2. Compute three subscores per subject: directly_observable, partially_observable, not_observable
3. For each subscore:
   a. **PD-only LOOCV with FM:** Train on remaining PD+HC, predict left-out PD's subscore
   b. **PD-only 10-split (B1 track):** PD-train only, test on held-out PD
4. **Key comparison table:**
   - MAE, CCC, R² for each of the 3 subscores (PD-only)
   - **Standardized metric:** MAE / SD(subscore) — makes cross-subscore comparison fair despite different score ranges (Codex: raw MAE alone is unfair)
   - **NRMSE** = RMSE / range for each subscore
5. **Permutation test:** r_direct > r_partial > r_unobservable (one-sided, ordered)
6. **Residualization test** (Codex): Residualize each subscore against total severity, test whether directly_observable remains more predictable after removing shared disease-severity variance
7. **Feature importance alignment** (Gemini): Do leg/foot sensors rank higher for gait subscore? Do wrist sensors rank higher for upper-limb? This proves the model learns the right anatomy.
8. **Decomposition analysis:** total_predicted ≈ obs_predicted + partial_predicted + unobs_predicted — assess reconstruction error
9. Sensitivity: binary split (items 7-14 vs rest) for backward compatibility with existing results

**Deliverables:**
- Table: 3-level prediction quality (PD-only LOOCV + 10-split)
- Figure: 3 scatter plots side-by-side (direct/partial/unobservable)
- Feature importance × sensor location heatmap
- Statistical test: prediction quality degrades monotonically with observability

**Runner:** `run_pd_only_experiments.py --phase 3`
**Compute:** GPU+CPU, ~120 min (3× LOOCV tracks + 10-split)

| # | Task | Status |
|---|------|--------|
| 3.1 | Parse 3-level subscores (direct/partial/unobs) per subject | DONE |
| 3.2 | FM LOOCV on each subscore (PD-only, N=98) | DONE |
| 3.3 | 10-split PD-only on each subscore | DONE |
| 3.4 | Standardized metrics: MAE/SD, NRMSE, CCC per subscore | DONE |
| 3.5 | Permutation test: r_direct > r_partial > r_unobs | DONE |
| 3.6 | Residualization against total severity | DONE |
| 3.7 | Feature importance × sensor location alignment | DONE |
| 3.8 | Decomposition: direct + partial + unobs → total | DONE |
| 3.9 | Sensitivity: binary split (items 7-14 vs rest) | DONE |

---

## Phase 4: Severity-Stratified Error + Confound Analysis [CPU, ~10 min]

**Rationale:** Proves the model discriminates severity, not just PD vs HC. Also addresses confound concerns (age, disease duration, medication).

**Split protocol:** Reuses LOOCV predictions from Phases 2 and 3.

**Implementation:**
1. **Severity quartile stratification:** Q1 (<12), Q2 (12-20), Q3 (20-35), Q4 (>35)
2. Per-quartile: MAE, CCC, mean predicted vs mean true, bias direction
3. **Calibration plot:** predicted vs true by decile, with 45° line and calibration slope
4. **Spearman rank correlation** — nonparametric severity ranking proof
5. **Weighted kappa** at clinically meaningful UPDRS bins — severity-category agreement
6. **Proportional bias:** regression of |error| on true score (slope should be ≈ 0)
7. **Confound analysis:**
   - Partial correlation of predicted UPDRS vs true UPDRS, controlling for Age + Disease Duration
   - Correlation of prediction errors with Age, Sex, Disease Duration, Height, Weight
   - If any confound correlation |r| > 0.3: flag and discuss
8. **Missing-data sensitivity:** Exclude subjects with partially missing UPDRS items. Compare results with vs without. (Our parsing sums available items; reviewers will ask about this.)

**Runner:** `run_pd_only_experiments.py --phase 4`
**Compute:** CPU-only, ~10 min

| # | Task | Status |
|---|------|--------|
| 4.1 | Severity quartile stratification | DONE |
| 4.2 | Per-quartile MAE, CCC, bias | DONE |
| 4.3 | Calibration plot by decile | DONE |
| 4.4 | Spearman + weighted kappa | DONE |
| 4.5 | Proportional bias regression | DONE |
| 4.6 | Partial correlation controlling confounds | DONE |
| 4.7 | Error correlation with demographics | DONE |
| 4.8 | Missing-data sensitivity | DONE |

---

## Phase 5: Locked Held-Out Test — PD Subset Report [GPU+CPU, ~15 min]

**Rationale:** Codex: "Track A is labeled primary but the plan never centers the paper on it." This phase runs the frozen FM Stack pipeline on the untouched clean test set (paper3_split.json) and reports:
- Full test result (all 36 subjects) — **primary**
- PD-subset result (21 PD subjects) — **secondary**

**Split protocol:** Track A. 142 dev → 36 test. No model selection. Pipeline frozen.

**Implementation:**
1. Load paper3_split.json, build v2+FM feature matrix
2. Feature select on 142 dev, train FM stack, predict 36 test
3. Report:
   - Full test: MAE, CCC, R², calibration slope
   - PD-subset: MAE, CCC (N=21, with caveats about small N)
   - Demographic baseline on same test set
4. This is a one-shot locked result — no iteration
5. Also report observable subscore on test PD subjects

**Runner:** `run_pd_only_experiments.py --phase 5`
**Compute:** GPU+CPU, ~15 min

| # | Task | Status |
|---|------|--------|
| 5.1 | Load clean split, build features | DONE |
| 5.2 | Train FM stack on 142 dev, predict 36 test | DONE |
| 5.3 | Full test metrics (MAE, CCC, R², calibration) | DONE |
| 5.4 | PD-subset metrics (N=21, with caveats) | DONE |
| 5.5 | Demographic baseline on same test set | DONE |
| 5.6 | Observable subscore on test PD | DONE |

---

## Phase 6: PD-Only Sensor Ablation — FM Re-Extracted Per Config [GPU+CPU, ~120 min]

**Rationale:** Both Codex and Gemini flagged a fatal flaw: using FM embeddings from all 13 sensors in a "wrist-only" ablation is data leakage. The FM branch must be sensor-consistent.

**Fix:** Re-extract MOMENT embeddings for each sensor config, passing ONLY the ablated sensor channels to the encoder. This means re-running FM inference (GPU-bound) for each config.

**Sensor configs:**
- `all_13`: All 13 sensors (26 channels) → baseline
- `wrists_2`: R_Wrist + L_Wrist (4 channels)
- `lower_back_1`: LowerBack only (2 channels)
- `wrists_back_3`: R_Wrist + L_Wrist + LowerBack (6 channels)
- `minimal_5`: LowerBack + R_Wrist + L_Wrist + R_Ankle + L_Ankle (10 channels)

**Split protocol:** Track B1 (PD-only train, 10-split).

**Implementation:**
1. For each sensor config:
   a. Re-extract FM embeddings from ONLY that config's sensor channels (GPU)
   b. Filter v2 features to that config's sensor columns
   c. Run 10-split PD-only evaluation (B1 track)
2. Subject-level paired bootstrap: wrists_2 vs all_13
3. Report MAE, CCC per config

**Runner:** `run_pd_only_experiments.py --phase 6`
**Compute:** GPU+CPU, ~120 min (5 configs × FM re-extraction + 10-split)

| # | Task | Status |
|---|------|--------|
| 6.1 | FM re-extraction per sensor config (GPU) | DONE |
| 6.2 | Filter v2 features per config | DONE |
| 6.3 | 10-split PD-only per config (B1 track) | DONE |
| 6.4 | Paired bootstrap: wrists_2 vs all_13 | DONE |
| 6.5 | Summary table | DONE |

---

## Phase 7: Consolidated Statistical Report + Figures [CPU, ~5 min]

**Implementation:**
1. Load all Phase 1-6 results
2. **Table 1:** Demographics (Age, Sex, Disease Duration, H&Y, UPDRS-III) for PD vs HC, dev vs test
3. **Master results table:**
   - Total UPDRS-III: PD-only 10-split (B1 primary + B2 sensitivity), LOOCV, locked held-out
   - 3-level subdomain: direct/partial/unobs MAE, CCC, MAE/SD
   - Sensor ablation: per-config MAE, CCC
   - Demographic baseline in all tracks
4. **Effect sizes:** Cohen's d for FM vs v2, FM vs demographic baseline
5. **Multiple comparison correction:** Holm-Bonferroni across all paired tests
6. **Publication figures:**
   - Fig 1: Scatter (PD-only LOOCV, predicted vs true) with calibration line
   - Fig 2: 3-panel scatter (direct/partial/unobs predicted vs true)
   - Fig 3: Bland-Altman (PD-only LOOCV)
   - Fig 4: Severity quartile error bars with demographic baseline comparison
   - Fig 5: Sensor ablation forest plot (PD-only)
   - Fig S1: Feature importance × sensor location heatmap
7. Summary JSON artifact: `results/pd_only_experiments.json`

**Runner:** `run_pd_only_experiments.py --phase 7`
**Compute:** CPU-only, ~5 min

| # | Task | Status |
|---|------|--------|
| 7.1 | Demographics Table 1 | DONE |
| 7.2 | Master results table | DONE |
| 7.3 | Effect sizes + multiple comparison correction | DONE |
| 7.4 | Publication figures (5 main + supplements) | DONE |
| 7.5 | Summary JSON artifact | DONE |

---

## GPU/CPU Scheduling Strategy

Remote: RTX 5060 Ti 16GB + 11 CPU cores, currently idle.

```
Timeline:
t=0:     [GPU+CPU] Phase 1 — PD-only 10-split (B1+B2+demographic)  ~90 min
t=90m:   [CPU]     Phase 2 — LOOCV stats + demographic baseline     ~10 min
t=100m:  [GPU+CPU] Phase 3 — Obs/Partial/Unobs LOOCV + 10-split    ~120 min
t=220m:  [CPU]     Phase 4 — Severity strat + confounds              ~10 min
t=230m:  [GPU+CPU] Phase 5 — Locked held-out test                    ~15 min
t=245m:  [GPU+CPU] Phase 6 — Sensor ablation (FM re-extraction)     ~120 min
t=365m:  [CPU]     Phase 7 — Consolidate + figures                   ~5 min
t=370m:  Done. Pull results.

Total estimated: ~6 hours
```

If time-constrained: cut Phase 6 first (Codex + Gemini agree it's lowest priority). Phases 1-3 are essential and can run in ~3.5 hours.

---

## Anti-Contamination Rules (IMMUTABLE)

1. **NEVER** use clean test split (paper3_split.json) for model search
2. **ALWAYS** subject-level splits
3. **ALWAYS** feature selection + all preprocessing INSIDE CV/LOOCV loops
4. **NEVER** promote sensitivity results as primary
5. **Full test stays primary for Track A; PD-subset is secondary** (N=21 too small for primary)
6. **PD-only train (B1) is primary for Track B; HC-augmented (B2) is sensitivity**
7. For sensor ablation: FM embeddings re-extracted per sensor config (NO data leakage)
8. **MCID used as contextual heuristic only, not as pass/fail threshold**

---

## Success Criteria

| Metric | Target | Why |
|--------|--------|-----|
| PD-only 10-split MAE (B1) | < 9.5 | Proves model works with PD-only training |
| PD-only 10-split CCC | > 0.30 | Concordance, not just correlation |
| FM beats demographic baseline | p < 0.05 | Proves IMU adds value beyond demographics |
| LOOCV permutation p | < 0.05 | Better than mean predictor |
| Direct-obs MAE/SD < Partial MAE/SD < Unobs MAE/SD | monotonic | Mechanistic argument holds |
| r_direct > r_unobs (permutation) | p < 0.05 | Observable items genuinely predicted |
| Partial correlation (controlling age+disease_dur) | > 0.25 | IMU signal beyond confounds |
| Spearman rank (PD-only) | > 0.30 | Severity ranking without parametric assumptions |

---

## What NOT To Do

- DO NOT retrain on clean test set for model selection
- DO NOT add new feature groups — use FM+v2 as established
- DO NOT run HP sweeps — use existing hyperparameters
- DO NOT use MCID as formal pass/fail (it's a change threshold, not cross-sectional error threshold)
- DO NOT compare PD-only numbers to Hssayeni without noting: N=98 vs N=24, controlled gait vs free ADL, 13 sensors vs wrist+ankle, habitual medication vs uncontrolled
- DO NOT use 13-sensor FM embeddings in sensor ablation — re-extract per config
- DO NOT present HC-augmented training as "PD-only" — label honestly
- DO NOT use SEM = SD/sqrt(N) for clinimetric agreement — use calibration slope, CCC
- DO NOT claim significance from split-level Wilcoxon on overlapping folds — use subject-level paired bootstrap

---

## Reviewer Feedback Integration Log

| Source | Issue | Resolution |
|--------|-------|------------|
| Codex + Gemini | FM leakage in sensor ablation | Re-extract FM per sensor config (Phase 6 rewritten) |
| Codex | PD+HC training ≠ pure PD claim | Added B1 (PD-only train, primary) + B2 (HC-augmented, sensitivity) |
| Codex | Overlapping splits → optimistic Wilcoxon | Switched to subject-level paired bootstrap |
| Codex + Gemini | Binary obs/unobs too coarse | 3-level taxonomy: direct/partial/unobservable |
| Codex | SEM/ICC misapplied | Replaced with calibration slope, CCC, R², MAE/SD |
| Codex | MCID framing too aggressive | Reframed as contextual heuristic, not pass/fail |
| Codex | Track A underused | Added Phase 5: locked held-out test |
| Codex | Missing confound checks | Added Phase 4: partial correlation, demographic correlations |
| Codex | Missing standardized metrics | Added MAE/SD, NRMSE, CCC, calibration slope throughout |
| Codex | Missing covariate baseline | Added demographic Ridge baseline in Phases 1, 2, 5 |
| Codex | Missing missing-data sensitivity | Added to Phase 4 |
| Gemini | Medication state undocumented | Added to Executive Summary |
| Gemini | Zero-inflation from HC training | B1 vs B2 comparison directly tests this |
| Gemini | Missing demographic baseline | Added Ridge on Age+Sex+Disease_Duration throughout |
| Gemini | Multi-label stratification needed | Added UPDRS bins × age terciles |
| Gemini | Feature importance × anatomy alignment | Added to Phase 3 |
| Gemini | Partial correlation for confounds | Added to Phase 2 and Phase 4 |
