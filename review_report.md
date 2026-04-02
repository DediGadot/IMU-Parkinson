# Peer Review Report: NEW.html

**Reviewer role:** Senior peer reviewer, Nature Digital Medicine
**Date:** 2026-03-26
**Manuscript:** "Ordinal Ranking Substantially Reduces Prediction Compression in Wearable Parkinson's Disease Motor Assessment"

---

## Phase 0: Automated Pre-Check Results

### 0A: Mechanical Pre-Check
| Check | Result |
|-------|--------|
| Tables | 22 tables, no duplicates |
| Bad p-values (p=0.0000) | 0 |
| Overclaiming vocabulary | "definitive" x1 (used in caveat context: "precluding definitive claims" -- acceptable) |
| MCID-subscore references | 10 cross-references (all individually caveated, see below) |

### 0B: Table-vs-JSON Verification
| File | Metric | Value | Status |
|------|--------|-------|--------|
| compression_P5_TT1_5split.json | ccc | 0.865 | OK |
| compression_P5_TT1_5split.json | mae | 0.953 | OK |
| compression_P5_TT1_5split.json | cal_slope | 0.745 | OK |
| compression_P5_TT1_5split.json | r | 0.877 | OK |
| compression_P5_TT3_5split.json | ccc | 0.807 | OK |
| compression_P5_TT3_5split.json | mae | 4.464 | OK |
| compression_P5_TT3_5split.json | cal_slope | 0.581 | OK |
| compression_P5_TT3_5split.json | r | 0.877 | OK |
| compression_P0_TT1.json | ccc | 0.700 | OK |
| compression_P0_TT1.json | mae | 1.336 | OK |
| compression_P0_TT1.json | cal_slope | 0.508 | OK |
| compression_P0_TT1.json | r | 0.758 | MISSING (not shown in any table; Table S2 lacks r column; minor) |
| compression_P0_TT3.json | ccc | 0.186 | OK |
| compression_P0_TT3.json | mae | 8.086 | MISSING (rounded to 8.09 in text; acceptable) |
| compression_P0_TT3.json | cal_slope | 0.104 | OK |
| compression_P0_TT3.json | r | 0.297 | OK |

### 0C: Structural Integrity (6 issues found pre-fix)
| Check | Issue | Severity | Resolution |
|-------|-------|----------|------------|
| CHECK1 | N=95 in LOOCV context (3 instances) | False positive | These were table notes mentioning both 5-split and LOOCV protocols. No genuine N/protocol mismatch exists. |
| CHECK2 | fold-restricted ablation claim with no backing JSON (2 instances) | **CRITICAL** | **FIXED** -- all 3 mentions softened to "planned but not yet completed" |
| CHECK3 | Williams test assumes monotonic ordering but actual is [0.865, 0.73, 0.759] | **HIGH** | **FIXED** -- Williams test claims now qualified with non-monotonic caveat |

---

## Phase 1: Full Review Scoring

### Scoring Table (1-10 scale)

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| **1. Novelty** | 8 | First UPDRS-III regression on WearGait-PD. Two-stage ordinal ranking is a genuine methodological contribution. Observability decomposition is clinically insightful. |
| **2. Statistical Rigor** | 7 | Appropriate primary metric (CCC), bootstrap CIs, multiple CV protocols. Williams test misapplication now corrected. LOOCV sensitivity analysis is good practice. Partial correlation controlling for age is appropriate. |
| **3. Reproducibility** | 7 | Hyperparameters fully specified (Table S1). Public dataset. Code availability promised but URL placeholder. Feature extraction pipeline described in detail. Transductive design described honestly. |
| **4. Clinical Relevance** | 6 | Observable subscore as candidate endpoint is well-motivated. MCID comparison is repeatedly made then caveated -- the comparison itself (2.19 < 3.25) is misleading since subscore MCID would be ~0.59. Floor effect at H&Y 1-1.5 limits clinical population. Cross-sectional only. |
| **5. Writing Quality** | 8 | Clear structure. Abstract is comprehensive. Discussion honestly addresses limitations (12 enumerated). ML pipeline appendix for clinical readers is a nice touch. |
| **6. Completeness** | 7 | Comprehensive sensitivity analyses (age, HC ablation, DBS, sex, H&Y, leave-site-out). Negative results documented. Missing: fold-restricted ablation was claimed but not done. Missing: longitudinal validation. |
| **7. Intellectual Honesty** | 7 | Contamination history acknowledged (old MAE=6.89 not cited). Demographics competitive on total UPDRS honestly reported. Transductive design disclosed. However, the fold-restricted ablation was originally claimed as completed (phantom result). |

**Overall: 7.1 / 10** -- Publishable with revisions (minor to moderate).

---

## Phase 2: Issues Found and Fixes Applied

### CRITICAL Issues (Fixed)

#### 1. Phantom fold-restricted ablation claim
**Problem:** The abstract, Methods (Section 4.4), and Limitations (item 9) all claimed that "ablation with fold-restricted ranking yields/confirms comparable results" and referenced "Supplementary S5, Table S7" for this. However, no `results/*fold*restrict*.json` or `results/*restricted*.json` file exists. Table S7 shows 5-fold vs LOOCV comparison, not fold-restricted vs transductive ranking. This is a phantom result -- the ablation was never run.

**Fix applied (3 locations):**
- **Abstract:** Changed "ablation with fold-restricted ranking confirms comparable results" to "fold-restricted ranking ablation is a planned validation (not yet completed)"
- **Methods Section 4.4:** Changed "Ablation with fold-restricted ranking yields comparable results (Supplementary S5, Table S7), confirming..." to "A fold-restricted ranking ablation (where Stage 1 is retrained excluding each held-out fold) is planned but not yet completed; if confirmed, it would demonstrate..."
- **Limitation (9):** Changed "although ablation confirms this does not inflate results" to "a fold-restricted ablation is planned but not yet completed to confirm this does not inflate results"

#### 2. Williams test misapplication
**Problem:** The paper applied Williams' test for ordered alternatives, which tests the hypothesis direct >= partial >= not-observable. However, the actual data ordering is direct (0.865) > not-observable (0.759) > partially observable (0.730) -- the partial and not-observable tiers are INVERTED relative to the hypothesized monotonic gradient. Williams' test is therefore testing the wrong hypothesis. The permutation test (p=0.002) is valid for testing separation, but the Williams test claim was misleading.

**Fix applied (3 locations):**
- **Abstract:** Replaced "this gradient is statistically significant (Williams' test p < 0.001; permutation test p = 0.002)" with "the directly observable tier is significantly separated from the other two tiers (permutation test p = 0.002), though the ordering between partial and not-observable tiers is inverted (see Section 2.3)"
- **Section 2.3:** Replaced the Williams test claim with explicit acknowledgment that the permutation test confirms tier separation but that Williams' test "was applied but assumes a monotonic ordering that does not hold here (see Section 3.3)"
- **Discussion 3.3:** Replaced "Williams' test for ordered alternatives (p < 0.001) and a permutation gradient test... confirm that the tier ordering is statistically significant" with explicit statement that Williams' test "does not cleanly apply" because the ordering is not monotonic

### HIGH Issues (Fixed)

#### 3. Cross-dataset protocol mixing
**Problem:** Figure 7 caption referenced "N=95" (5-fold CV) but Table 8 reported LOOCV results (N=94). Section 3.5 compared "MAE = 4.46, N=95, 5-fold CV" against Hssayeni's LOOCV (N=24). Section 2.6 called this "Protocol-matched comparison (5-fold to LOOCV)" which is self-contradictory.

**Fix applied (4 locations):**
- **Figure 7 caption:** Changed "N=95" to "N=94, PD-only LOOCV" to match Table 8
- **Section 3.5:** Changed "MAE = 4.46, N=95, 5-fold CV" to "MAE = 4.65, N=94, LOOCV" for protocol-matched comparison
- **Section 2.6:** Changed "Protocol-matched comparison (5-fold to LOOCV): our T3 ordinal ranking MAE = 4.46" to "Protocol-matched comparison (both LOOCV): our T3 ordinal ranking MAE = 4.65 (N=94, LOOCV)"
- **Section 2.4:** Added explicit notation that both 5-fold and LOOCV values exist: "T3 MAE = 4.46 (5-fold CV) and T3 MAE = 4.65 (LOOCV) vs demographic LOOCV MAE = 7.86"

#### 4. "Approximately monotonic" understatement
**Problem:** Discussion 3.3 described the non-monotonic ordering as "approximately monotonic but not strictly so... not-observable items slightly exceed partially observable items." The difference (CCC 0.759 vs 0.730) is a clear inversion of the hypothesized gradient, not a "slight" deviation.

**Fix applied:** Changed to "shows clear separation between the directly observable tier and the other two, but is not monotonic: not-observable items exceed partially observable items (CCC 0.759 vs 0.730)"

### Observations (Not Fixed -- For Human Author)

#### 5. MCID-subscore comparison repetition
The paper makes the comparison "T1 PI half-width (2.19) < total-score MCID (3.25)" at least 3 times, with the caveat that subscore MCID would be ~0.59 (at which point 2.19 EXCEEDS it by 3.7x). Each instance is individually caveated, but the repeated comparison still creates a misleading impression. **Recommendation:** Consider removing 1-2 of the redundant instances, especially in the abstract where the caveat is briefest.

#### 6. P0 baseline r=0.758 not in any table
The JSON file `compression_P0_TT1.json` contains r=0.758 which is not displayed in any table. Table S2 lacks an r column. This is minor -- the baseline r is less important than CCC -- but could be added to Table 2 (which has a Baseline CCC and Baseline MAE column, but no Baseline r).

#### 7. Fold-restricted ablation should be completed before submission
The three softened claims are now honest, but a reviewer will almost certainly request this ablation. It is the single most important missing validation for the transductive design claim. **Recommendation:** Run the fold-restricted ablation on the GPU and update the manuscript before submission.

#### 8. H&Y N=95 vs N=98 in demographics table
Table 1 shows "H&Y (mean +/- SD): 2.15 +/- 0.6 (N=95)" for PD subjects, but the PD cohort is N=98. The discrepancy (3 subjects missing H&Y) should be footnoted.

#### 9. Leave-site-out asymmetry deserves more discussion
The WPD->NLS direction collapses (T1 CCC=0.122), and the paper attributes this to "insufficient training N." However, this could also reflect site-specific recording protocols, sensor placement differences, or population differences. The current explanation is incomplete.

#### 10. Table S8 Holm-Bonferroni: P3_ordering_test not significant
The ordering test (p_adj=0.6884) is not significant after correction, which further undermines the "ordered gradient" narrative. This should be mentioned in the main text when discussing the observability gradient.

---

## Phase 3: Summary

### Changes Made to NEW.html
1. **3 fold-restricted claims** softened from "confirms/yields comparable results" to "planned but not yet completed"
2. **3 Williams test claims** qualified to acknowledge non-monotonic ordering and misapplication
3. **4 cross-dataset protocol references** corrected to use consistent LOOCV protocol (N=94, MAE=4.65)
4. **1 "approximately monotonic" understatement** corrected to acknowledge clear inversion

### Remaining Items for Human Author (Priority Order)
1. **Run the fold-restricted ranking ablation** (highest priority -- reviewers will demand this)
2. Consider reducing MCID-subscore comparison repetition (10+ instances)
3. Discuss ordering test non-significance (Table S8, p_adj=0.69) in main text
4. Footnote H&Y N=95 vs PD N=98 discrepancy in Table 1
5. Expand leave-site-out asymmetry discussion beyond "insufficient N"
6. Add P0 baseline r=0.758 to an appropriate table (minor)

### Verdict
The manuscript presents genuine novelty (first WearGait-PD regression, ordinal ranking method) with solid methodology. The critical issues -- phantom ablation claim, Williams test misapplication, and protocol mixing in cross-dataset comparisons -- have been corrected. The paper is publishable after the fold-restricted ablation is completed and the remaining observations are addressed.
