# Peer Review: "Ordinal ranking reaches the observability ceiling for wearable Parkinson's disease motor assessment"

**Journal:** Nature Digital Medicine (target)
**Review round:** Final (post-R3)
**Reviewer role:** Senior peer reviewer, internal consistency focus
**Date:** 2026-04-02

---

## Dimension Scores (1--10)

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Novelty** | 8 | First UPDRS-III regression on WearGait-PD; ordinal ranking-to-leaf-feature pipeline is genuinely novel; two-level observability decomposition provides new clinical insight |
| **Methodological rigor** | 8 | Subject-level CV, multi-seed, LOOCV sensitivity, Nadeau-Bengio non-inferiority, comprehensive ablations. Transductive Stage 1 is honestly disclosed and ablated. Temperature T tuned on T1 only; T2/T3 report Stages 1--2 |
| **Clarity** | 7 | Well-organized; three-stage pipeline clearly explained; ML appendix is helpful for clinicians. Abstract was verbose and had number mismatches (now fixed). Some redundancy between Section 2.2, Table 2, and Table S2 |
| **Statistical soundness** | 8 | CCC as primary metric is appropriate; BCa CIs reported; Holm-Bonferroni correction applied; Williams test for observability ordering; non-inferiority with pre-specified delta. p-values consistent across text and tables |
| **Clinical relevance** | 7 | Observable subscore is clinically meaningful for axial motor monitoring. Correctly notes MCID does not apply to subscores. Sensor reduction study provides a practical deployment roadmap. Limitation: single-dataset, cross-sectional only |
| **Internal consistency** | 8 | After fixes: all key numbers trace to source tables. Minor acceptable variation across analyses with different subsets (N=90--98) is well explained in Methods 4.6 |
| **Completeness** | 8 | Comprehensive negative results section, FM decomposition, age confound analysis, HC ablation, 22-config sensor study. Missing: leave-site-out analysis (two sites NLS/WPD exist), DBS subgroup analysis (N=23 acknowledged but not stratified) |

**Overall: 7.7 / 10 -- Suitable for publication after minor revisions**

---

## Issues Identified and Fixed

### Critical Issues (fixed in this review)

**C1. Abstract LOOCV CCC = 0.896 was an orphan number.**
The abstract claimed "under LOOCV, the full pipeline achieves CCC = 0.896 with slope = 0.965." Neither number appeared in any table. Table S11 shows T1 LOOCV per-target temperature CCC = 0.893 (slope = 1.000); Table S8 shows T=1.4 temperature CCC = 0.882 (slope = 0.967). The 0.896 and 0.965 were likely from a prior analysis version.
**Fix:** Replaced with per-target LOOCV results from Table S11: "per-target temperature tuning achieves CCC = 0.893 with slope = 1.000 (T1), CCC = 0.863 (T2), and CCC = 0.811 (T3)."

**C2. Abstract mixed pre-temperature and post-temperature numbers.**
The abstract presented "CCC = 0.865 (calibration slope = 0.745, MAE = 0.953)" -- all Stages 1--2 (pre-temperature) values -- for a "three-stage pipeline" that includes temperature scaling. The body (Section 2.2) consistently uses the with-temperature result (CCC = 0.864, slope = 1.043, MAE = 1.156) as the primary number.
**Fix:** Abstract now leads with the full-pipeline result (CCC = 0.864, slope = 1.043, MAE = 1.156), then explicitly notes Stages 1--2 values (CCC = 0.865, slope = 0.745, MAE = 0.953) for context.

**C3. Section 2.3 baseline direct CCC = 0.545 was incorrect.**
The text stated "Ordinal ranking improves all three tiers substantially over baseline: direct CCC 0.545 -> 0.864." Table 2 shows the 5-fold baseline CCC for directly observable = 0.700. Table S10 (LOOCV baseline) shows 0.560. The value 0.545 matched neither.
**Fix:** Changed to 0.700 to match Table 2 (the table in the same section).

### Major Issues (fixed in this review)

**M1. "Less than 4%" of subscore range was arithmetically wrong.**
Section 2.2 and Discussion 3.2 both stated MAE of 1.156 "represents less than 4% of the subscore range." Actual: 1.156/24 = 4.8%. The 4% claim held for the pre-temperature MAE (0.953/24 = 4.0%) but not after temperature scaling increased MAE to 1.156.
**Fix:** Changed to "less than 5%" in both occurrences.

**M2. Abstract observability CCC said 0.865 instead of 0.864.**
The abstract's observability sentence said "directly observable items (CCC = 0.865)" while the body consistently uses 0.864 (with temperature). Since the primary result is now 0.864, the abstract should match.
**Fix:** Changed to 0.864.

---

## Minor Issues (not fixed -- flagged for authors)

**m1. Table 7 HC ablation baseline CCC = 0.673 differs from Table 2 baseline CCC = 0.700.**
The table note explains this as "a different random split." While technically correct, the magnitude of the difference (0.027 CCC) between two ostensibly equivalent baselines with the same protocol is notable and may invite reviewer skepticism. Consider mentioning the range of baseline variability.

**m2. Two different temperature values for T1 LOOCV.**
Table S8 uses T=1.4 (CCC = 0.882, slope = 0.967) and Table S11 uses T=1.45 (CCC = 0.893, slope = 1.000). Both are legitimate (T=1.4 is a fixed value from the primary 5-fold tuning; T=1.45 is independently optimized per-target). But having two LOOCV T1 temperature-calibrated results may confuse readers. Consider adding a sentence in Section 2.4 explicitly distinguishing the two.

**m3. Subscore-specific MCID mentioned three times as "not established."**
Sections 2.2, 3.2, and Limitations all note the absence of a subscore-specific MCID. This repetition is appropriate for a final paper but could be consolidated.

**m4. Cross-dataset comparison limitations understated.**
Section 2.8 says "Protocol-matched comparison (5-fold to LOOCV)" -- comparing 5-fold to LOOCV is not truly protocol-matched. While this caveat is acknowledged later, the initial phrase could mislead.

**m5. DBS subgroup analysis missing.**
With 23/98 PD subjects having DBS (24%), the potential confound deserves stratified analysis. Limitation (10) acknowledges this but says "small subgroup size precluded meaningful stratified analysis." At N=23 vs N=75, a point estimate with CI would still be informative.

**m6. No leave-site-out analysis.**
WearGait-PD has two collection sites (NLS and WPD). Site effects are a common concern for generalizability. A leave-site-out analysis would strengthen the single-dataset limitation.

**m7. Negative reference numbering for Hssayeni (ref 3).**
The reference characterizes the Hssayeni paper as "Wearable sensors for estimation of Parkinsonian tremor severity during free body movement." The CLAUDE.md notes describe this as "estimation of UPDRS severity." Verify the exact title -- this paper may be about UPDRS estimation, not tremor estimation specifically.

---

## Verified Consistent (no action needed)

- T3 MAE: 4.46 (5-fold) / 4.65 (LOOCV) consistent across text, Table 3, Table S2, Table S7, Table S11, Discussion 3.7, cross-dataset Table 11
- Per-target temperatures: T1=1.45, T2=1.45, T3=1.75 consistent across Table S11, Section 2.4, Discussion 3.4
- Per-target LOOCV CCC with temperature: 0.893 > 0.863 > 0.811 consistent across Table S11 and Section 2.4
- Subject counts: N=95 (5-fold), N=94 (LOOCV), N=98 (10-split), N=90 (observability partial/unobs) -- all explained in Methods 4.6
- Baseline T3: CCC = 0.186, MAE = 8.09 consistent across Section 2.5, Table 3, Table S2
- Sensor non-inferiority p-values: match between text and Table 9 continuation
- "25% lower" MAE claim: 4.46/5.95 = 25.0% reduction -- correct
- "82% of total score range": (132-24)/132 = 81.8% -- correct
- Williams test p = 0.69 consistent across Sections 2.3, 3.3, Figure 4 caption

---

## Summary

This is a well-executed study that makes a genuine contribution: the first regression benchmark on WearGait-PD with a novel ordinal ranking method and honest observability analysis. The three critical and two major numerical consistency issues (orphan LOOCV number, mixed pre/post-temperature abstract, incorrect baseline CCC, wrong percentage claim, abstract CCC mismatch) have been fixed. The paper is now internally consistent across all key numbers.

The primary remaining concerns are: (1) single-dataset limitation with no leave-site-out or cross-dataset transfer, and (2) absence of DBS subgroup analysis. Both are acknowledged as limitations. The paper is suitable for publication at Nature Digital Medicine with the minor issues addressed.
