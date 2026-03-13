# Paper Review Report — WearGait-PD UPDRS-III Regression

**Date:** 2026-03-13
**Manuscript:** "Wearable gait sensors predict observable but not unobservable motor severity in Parkinson's disease"
**Output:** `/home/fiod/medical/NEW.html` (2.1 MB, 8 embedded figures)

---

## Final Quality Score: 90/100

**Interpretation:** npj Parkinson's Disease ready. Approaching Nature Digital Medicine territory.

### Score Progression

| Cycle | Focus | Weighted Score | Key Improvements |
|-------|-------|---------------|-----------------|
| **1** | Accuracy & Completeness | **7.85/10** | 7 factual corrections (Hssayeni r, task count, H&Y 1.5, missing table refs) |
| **2** | Narrative & Insight | **8.05/10** | Abstract/intro restructured around observability hypothesis, Discussion deepened, tone corrected 8 locations |
| **3** | Polish & Reviewer-Proofing | **9.0/10** | Wilcoxon two-sided fix, Bland-Altman reported, MCID asymmetry, 6 Tufte visual improvements, all 9 reviewer objections pre-addressed |

### Per-Dimension Breakdown (Final)

| Dimension | Weight | Score | Notes |
|-----------|--------|-------|-------|
| Scientific Rigor | 25% | 9/10 | 3 eval protocols, subject-level splits, Holm-Bonferroni, demographic baseline |
| Novelty & Significance | 15% | 9/10 | First WearGait-PD regression, 3-level observability decomposition, hypothesis-driven |
| Methods Reproducibility | 15% | 9/10 | All HPs verified against source code, feature selection inside CV |
| Results Clarity | 15% | 9/10 | All numbers trace to JSON artifacts, 8 figures + 6 tables all referenced |
| Discussion Depth | 10% | 9/10 | 7 subsections, calibration barrier, field recommendations |
| Writing Quality | 10% | 9/10 | Hypothesis-driven framing, analytical tone, hedging appropriate |
| Visual Excellence | 10% | 8.5/10 | Tufte improvements applied; Fig 7 functional not insightful |

---

## External LLM Feedback Summary

### Writing Reviews (Step 3.5)
- **Codex (GPT-5.4):** 10 suggestions. 9 accepted (tone corrections, observability elevation, abstract restructure). 1 rejected ("to our knowledge" hedge — claim is verified).
- **Gemini (3.1-pro):** 5 suggestions. 4 accepted (clinical framing, cross-dataset caveats, limitation depth). 1 rejected (formal "Digital Motor Subscore" naming — premature).

### Visual Reviews (Step 4.5)
- **Gemini (Tufte review):** 6 patches applied — borderless stat boxes, chartjunk removal, forest plot spine removal, reduced grid alpha/linewidth.
- **Codex:** Review did not complete in time — proceeded with Gemini feedback only.

---

## Remaining Issues Requiring Human Attention

### Must-Fix Before Submission
1. Author names and affiliations
2. Corresponding author email
3. Code/data availability statement — needs repository URL
4. Ethics approval — IRB/ethics committee reference
5. Funding statement — grant numbers
6. Conflict of interest declaration
7. Author contributions (CRediT)

### Consider Before Submission
8. Replace Fig 7 (multi-split stability) with Bland-Altman plot showing calibration compression
9. Demographics table uses N=100 enrolled vs N=98 analysis — minor discrepancy
10. Observable tier ordering test p=0.17 (NS) — could strengthen with bootstrap
11. Table 4 placement — consider moving to Supplementary
12. Abstract density — could streamline further

---

## All 9 Anticipated Reviewer Objections Pre-Addressed

| # | Objection | Status |
|---|-----------|--------|
| 1 | "Why not deep learning?" | Section 2.10 + Table S1 |
| 2 | "N=178 is small" | Intro (field standard N=24) |
| 3 | "Single dataset" | Discussion 3.1, 3.6, 3.7 |
| 4 | "HC inflate metrics" | PD-only throughout |
| 5 | "No longitudinal" | Discussion 3.6, 3.7 |
| 6 | "Feature selection overfits" | Methods 4.4, 4.6 |
| 7 | "Observable classification subjective" | Methods 4.7, Discussion 3.1 |
| 8 | "FM may not generalize" | Section 2.6, Discussion 3.4 |
| 9 | "MCID claim too strong" | Discussion 3.3, Methods 4.8 |

---

## Key Strengths
- Hypothesis-driven framing (not just a benchmark paper)
- Three-level observability decomposition — genuine conceptual contribution
- Honest reporting — demographics beating IMU, calibration failure, DL failure as evidence
- Statistical rigor — 3 evaluation protocols, Holm-Bonferroni, bootstrap CIs
- 8 publication-quality figures with Tufte improvements
- All numbers verified against source JSON artifacts

## Risks for Submission
- Observable tier ordering p=0.17 could draw reviewer skepticism
- Calibration slope=0.26 limits clinical deployment claims (framed as translational barrier)
- Single-dataset limitation (mitigated by largest controlled-gait PD cohort with full UPDRS)
