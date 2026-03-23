# Findings — Figure Generation Review for Nature Digital Medicine (2026-03-15)

## Initial Figure Review Notes

- `generate_paper.py` contains 10 main figure builders (`fig1_*` through `fig10_*`) and 6 appendix figure builders (`figA_*` through `figF_*`), all generated directly with matplotlib and embedded as base64 PNG.
- The file already claims a colorblind-safe palette, but several colors are not from viridis/cividis families and a few pairings rely on red/green or blue/light-blue distinctions that are weaker than ideal for print accessibility.
- Figure 2 and Figure 3 are the highest-risk main-panel figures because they support the headline SSL claim; both need careful checks on identity-line visibility, annotation completeness, and print-size text density.
- Figure 7 is likely the highest-impact comparison figure for the anti-compression story; it needs to communicate P5 dominance immediately, without readers having to parse mixed evaluation protocols or subtle color differences.
- Some appendix figures may be conceptually acceptable but still not at Nature-reviewer polish because their current styling appears more didactic than publication-ready.

## Final Visual Review Findings

- The main blocker is not styling but evidentiary integrity: Figures 2 and 3 synthesize scatter points from summary statistics instead of plotting real per-subject predictions. That is not acceptable for a flagship result figure.
- Figure 4 is both visually and structurally weak. The current three-panel bar layout wastes space, renders with large blank whitespace, and is a slower comparison than a compact dot-range matrix.
- Figure 6 is visually misleading as currently coded. The horizontal bar lengths encode ordinal positions `1..20`, not actual feature-importance magnitudes, so the chart looks quantitative while plotting rank only.
- Figure 7 does show that P5 is best, but not with enough immediacy for a Nature-style primary comparison figure. A sorted horizontal comparison with direct delta-to-baseline labels would communicate the result better.
- Figure 1 has a concrete layout bug in the rendered output: the T3 output box is clipped at the bottom edge.
- Appendix Figure A has a concrete directional bug: the input arrow is reversed in the schematic.
- The strongest figures after a palette pass are Figures 8 and 9. They already use appropriate chart types and are close to publication quality.
- Wrote the requested review and patch recommendations to `.paper_build/external_codex_visual.md`.

---

# Findings — Nature Digital Medicine Writing Review (2026-03-15)

## Initial Editorial Assessment

- The core scientific story is strong, but the manuscript currently presents two different narratives at once: a methodological breakthrough in calibration via SSL ranking, and a structural ceiling imposed by sensor observability. Those claims are both interesting, but they need cleaner sequencing so they reinforce rather than compete with each other.
- Tone is often closer to an internal project memo than a Nature-family paper. The most visible issues are assertive verbs (`solves`, `establish`, `demonstrate`) and conversational or absolute phrasing (`catastrophic`, `This is a physics constraint`, `"who is more severe?"`, `near chance`).
- The abstract is close to self-contained on the SSL pipeline, but it does not fully define the three-level observability decomposition for a reader who has not seen the full text. It also ends in language that is slightly too conclusive for a single-dataset study.
- Discussion section 3.1 does address mechanism, especially calibration anchors and N amplification, but it still reads as a short list of reasons rather than a deeper causal explanation of why PD-only regression compresses and why rank-based pretraining changes the geometry of the problem.
- The CCC framing is directionally right but can be made sharper. The paper explains that MAE can look acceptable under mean-shrunk predictions, yet it should define CCC more explicitly as an agreement metric combining correlation and calibration, and avoid chance-language that does not apply to CCC.
- High-risk overclaim locations include the title, the contribution statement in the introduction, the generalization claim in Discussion 3.1, the endpoint recommendation in Discussion 3.2, and the broad statement that compression is general to small-N clinical regression.

## Candidate High-Impact Sentences

- `Semi-Supervised Severity Ranking from Healthy Controls Solves Prediction Compression in Parkinson's Disease Motor Assessment`
- `These results establish WearGait-PD as a regression benchmark, demonstrate that healthy controls provide calibration anchors for clinical severity estimation, and identify the directly observable motor subdomain as a clinically actionable wearable endpoint with sub-MCID prediction error.`
- `We present four contributions: (1) the first regression benchmark on WearGait-PD with subject-level evaluation; (2) a two-stage semi-supervised ranking method that uses healthy controls as calibration anchors, solving prediction compression ...`
- `Per-item ordinal classification (P1) was catastrophic (CCC = 0.338).`
- `This is a physics constraint: rigidity (item 3.3), speech (3.1), and facial expression (3.2) cannot be measured by body-worn inertial sensors during gait.`
- `The mechanism is general: any clinical scale prediction with matched healthy controls could benefit from this approach.`
- `We propose that future wearable PD studies adopt modality-matched subscores as primary endpoints rather than the total composite score.`
- `We recommend that future UPDRS regression studies adopt CCC as the primary agreement metric, since r ignores calibration and MAE ignores discrimination.`
- `MAE = 8.086 appears reasonable, but CCC = 0.186 is near chance.`

## Deliverable Summary

- Wrote the requested review to `.paper_build/external_codex_writing.md`.
- The review concludes that the paper is close to Nature-ready in substance but needs one deliberate writing pass to reduce overclaiming, formalize tone, and clarify the hierarchy between the SSL breakthrough and the observability-ceiling result.
- The review finds that the abstract mostly explains the SSL mechanism, but not the observability decomposition, and recommends adding one concise definitional clause.
- The review judges the CCC framing as fundamentally correct but in need of tighter statistical language, especially around agreement, calibration slope, and removal of `near chance`.
- The review includes 10 sentence-level rewrites targeting the title, abstract conclusion, introduction, discussion, and metric framing.

---

# Findings — NEW.html Verification Audit (2026-03-15)

## Initial Audit Notes

- Prior session catchup indicates `NEW.html` was recently updated with SSL-ranking sections and multiple consistency fixes.
- Existing planning files are centered on experiment execution, so this audit must independently validate the manuscript against repository artifacts rather than assume prior edits are correct.
- Need to identify which files are authoritative for manuscript numbers: likely `results/` JSON outputs plus any `.paper_build/current_truth.md` style synthesis files if still present locally.
- Initial grep of `NEW.html` shows headline SSL metrics in the abstract and benchmark table as Direct observable `CCC=0.868, MAE=0.986` and Total `CCC=0.776, MAE=4.646`, plus a baseline total `CCC=0.37, MAE=8.15`.
- Those values already appear inconsistent with the current compression-ablation planning state, which records P5 SSL results around `0.865 / 0.831 / 0.807` and a much weaker total baseline (`CCC≈0.186`, `MAE≈8.09`) under the newer 3-target decomposition.
- Need to determine whether `NEW.html` is intentionally mixing an older paper storyline with newer ablation results, or whether the manuscript has stale numbers after the recent edits.
- `.paper_build/current_truth.md` is internally inconsistent: its headline "P5 Results" table uses `T1/T2/T3 = 0.868/0.852/0.776` with LOOCV labels, while its own `P5 vs Baseline` and `Full 5-Proposal x 3-Target` tables still cite `0.865/0.831/0.807`.
- `.paper_build/verification_report.md` only validates `NEW.html` against the first set of values from `current_truth.md`, so a prior "PASS" verdict cannot be taken as ground truth until the raw result JSON files are checked directly.
- Raw result files resolve the conflict: `results/compression_P5_TT1.json`, `results/compression_P5_TT2.json`, and `results/compression_P5_TT3.json` are all LOOCV outputs with `CCC=0.868/0.852/0.776`, `MAE=0.986/1.334/4.646`, and `r=0.899/0.873/0.827`.
- Therefore the P5 headline values used in `NEW.html` appear to match the authoritative JSON files. The stale numbers are in the planning/synthesis layer (`compression_ablation_all.json`, parts of `current_truth.md`, older notes), not in the raw P5 outputs.
- `NEW.html` has a real evaluation-mode error in Section 2.12/Table 7: the P5 rows are LOOCV (`results/compression_P5_TT*.json`), but the P0 rows come from 5-split files (`results/compression_P0_TT*.json`). The current caption/note says the entire table is PD-only LOOCV, which is false.
- The observability-gradient wording is methodologically mixed in several places. The paper cites `direct = 0.868` (SSL) alongside `partial = 0.12` and `not observable = 0.18` (baseline LOOCV from `results/pd_only_experiments.json`) as if they were one coherent decomposition result. They are not the same model/evaluation setup.
- Discussion Section 3.1 claims that “with SSL ranking, all 10 cross-validation splits produce MAE well below 3.25,” but no 10-split SSL artifact was found in the repo. The only split-based observable result in local artifacts is the baseline 10-split summary (`1.72 ± 0.33`, 7/10 below MCID), while SSL files are LOOCV-only.
- Sensor-ablation prose in Section 2.9 overreaches slightly: Table 5 metrics (`~7.7` MAE) are total-score-style results from `results/pd_only_phase6.json`, yet the text concludes that a wrist-based wearable may suffice for continuous monitoring of the observable subdomain. That inference is not directly supported by the sensor-ablation artifact itself.

## Fixes Applied to `NEW.html`

- Abstract now states the observability gradient using the baseline three-tier decomposition (`0.56 / 0.12 / 0.18`) and then separately describes the SSL gains (`0.868` direct, `0.776` total).
- Section 2.9 and Table 5 now identify the sensor ablation as a total-UPDRS benchmark and soften the conclusion to reduced-config feasibility for gait-based monitoring, with explicit caveat that observable-subdomain sensor ablations remain untested.
- Section 2.12 and Table 7 now distinguish P5 LOOCV (`N=94`) from P0 5-split (`N=95`) and note that the P0 compression-ablation baseline is a separate model family from the earlier baseline pipeline in Tables 2-3.
- Discussion 3.1 now uses the supported baseline 10-split statement (`7/10` below MCID) and contrasts it with the SSL LOOCV MAE, instead of claiming unsupported SSL 10-split coverage.
- Discussion 3.2 and the summary now refer to the baseline observability gradient separately from the SSL gains, removing the apples-to-oranges gradient wording.

## Residual Caveats

- `NEW.html` still contains front-matter placeholders for authors and affiliations (`[Author names to be added]`, `[Affiliations to be added]`); these are completeness issues rather than result-consistency issues.
- This audit did not regenerate the embedded base64 figures; captions and searchable numeric claims were checked against local result artifacts, but the bitmap contents themselves were not independently recomputed during this pass.

## `update-paper` Slash Command Updates Needed

- The update path must treat raw result artifacts in `results/` as higher priority than memory files, findings summaries, or prior `.paper_build` truth files, because those synthesis layers were internally inconsistent on the P5 numbers.
- Every reportable claim needs provenance tracking: endpoint, metric, value, model/config, evaluation protocol, sample size `N`, and exact source file. This is necessary to stop mixed-protocol tables and apples-to-oranges narrative claims.
- The command must distinguish baseline observability decomposition from later SSL gains. It should explicitly forbid constructing a single "observability gradient" from baseline partial/unobservable results plus SSL direct-observable results unless the text says those are separate analyses.
- The diff/fix stage must detect and rewrite unsupported split claims. In this repo, there is no SSL 10-split artifact, so claims like "all 10 splits" must be blocked unless a supporting split artifact exists.
- Sensor-ablation handling must be endpoint-aware. Total-score ablation artifacts cannot be used to justify observable-subdomain deployment claims unless a matching observable-endpoint ablation exists.
- Mixed-protocol tables must carry explicit per-row or per-block protocol labels and `N` values. This specifically addresses the P0 `5split` versus P5 `loocv` issue in Table 7.
- The update path must consistently target the real manuscript under review: prefer `NEW.html` if it exists, otherwise `paper.html`. Hardcoded `paper.html` references in the update flow risk editing or verifying the wrong file.
- Figure verification must enforce baseline-versus-current-best consistency. A baseline scatter/decomposition figure is acceptable only if labeled as baseline and not paired with SSL/current-best text.
- Verification/report stages must surface unresolved placeholders for authors, affiliations, funding, ethics, COI, or data availability as human-attention items instead of silently passing them through.

---

# Findings — Compression Ablation Study (2026-03-15)

## BREAKTHROUGH: P5 Semi-Supervised Ranking from HC

### Result (LOOCV-validated for T1)

| Target | Baseline CCC | **P5 SSL CCC** | Baseline slope | **P5 slope** | Baseline MAE | **P5 MAE** |
|--------|-------------|---------------|----------------|-------------|-------------|-----------|
| **T1 (items 9-14)** | 0.700 | **0.865** ✓LOOCV | 0.508 | **0.745** | 1.336 | **0.953** |
| **T2 (items 7-14)** | 0.554 | **0.831** (5-split) | 0.425 | **0.707** | 1.851 | **1.162** |
| **T3 (total UPDRS)** | 0.186 | **0.807** (5-split) | 0.104 | **0.581** | 8.086 | **4.464** |

T1 LOOCV validation confirms 5-split result exactly (CCC=0.865). T2/T3 LOOCV running.

### Quartile Bias (T1, LOOCV)

| Quartile | Baseline bias | P5 SSL bias | Improvement |
|---|---|---|---|
| Q1 (<2, n=16) | +2.25 | +1.65 | -27% |
| Q2 (2-4, n=31) | +0.67 | +0.13 | -81% |
| Q3 (4-5, n=19) | -0.29 | -0.74 | worse |
| Q4 (>=5, n=29) | -1.34 | -0.53 | -61% |

The compression is dramatically reduced: Q4 underprediction cut by 61%, Q2 overprediction nearly eliminated.

### Mechanism: Why P5 Works

1. **N amplification:** Pure PD-only regression has N=94. P5 uses ALL 178 subjects (98 PD + 80 HC) for ranking representation learning, effectively doubling the sample for the most critical step.

2. **HC as calibration anchors:** HC subjects (UPDRS ≈ 0-3) provide dense "ground truth zero" reference points. The XGBRanker learns that HC → 0 severity, which anchors the low end of the prediction range. Without HC, the model has no confident reference for "definitely low severity."

3. **Severity ordering is easier than severity estimation:** Ranking "who is more severe?" is a simpler task than predicting exact scores. The ranking model captures this ordering in its leaf structure, which the downstream regression model uses to calibrate its predictions.

4. **Leaf features encode nonlinear severity:** XGBRanker leaf indices create a categorical embedding of severity position. This embedding is invariant to feature scaling and captures nonlinear severity boundaries that raw features miss.

5. **No leakage:** HC subjects are used for REPRESENTATION learning only. The final regression evaluation is strictly PD-only LOOCV. HC subjects never appear in the test fold. Per-subject UPDRS scores are only used as ranking labels in stage 1, not as features.

### Why Other Proposals Failed

| Proposal | CCC (T1) | Why it failed |
|---|---|---|
| P1 Ordinal + temp | 0.338 | Per-item classification loses inter-item correlation. Rare classes (score 3,4) crash training. Temperature sharpening amplifies noise on sparse ordinal distributions. |
| P2 Pairwise | ~0.62* | Pair generation creates 4300 training points but each pair is noisy. Anchor reconstruction averages over diverse references, re-introducing compression. |
| P3 SMOGN | 0.665 | Synthetic tail patients help calibration slope (+0.02) but don't add real signal. The interpolated features are linear combinations that trees don't exploit well. |
| P4 NGBoost | 0.671 | Poisson distribution fits poorly (score is a sum of ordinals, not a count). CCC-tuned percentile extraction is a post-hoc trick that doesn't address root cause. |

*P2 incomplete (3/5 splits)

## Full 5-Proposal × 3-Target Results Table

| | T1 (items 9-14) | T2 (items 7-14) | T3 (total UPDRS) |
|---|---|---|---|
| **P0 baseline** | CCC=0.700 s=0.508 MAE=1.34 | CCC=0.554 s=0.425 MAE=1.85 | CCC=0.186 s=0.104 MAE=8.09 |
| P1 ordinal | CCC=0.338 s=0.184 MAE=1.59 | — | — |
| P3 SMOGN | CCC=0.665 s=0.528 MAE=1.49 | CCC=0.603 s=0.546 MAE=1.85 | CCC=0.195 s=0.115 MAE=8.38 |
| P4 NGBoost | CCC=0.671 s=0.484 MAE=1.39 | CCC=0.595 s=0.492 MAE=1.75 | CCC=0.187 s=0.109 MAE=8.20 |
| **P5 SSL** | **CCC=0.865 s=0.745 MAE=0.95** | **CCC=0.831 s=0.707 MAE=1.16** | **CCC=0.807 s=0.581 MAE=4.46** |

P5 is the only proposal that materially improves CCC on ANY target. It dominates on ALL targets.

## Prior Ablation Results (Sessions 8-10)

### Feature Space (Session 8)
- Walkway metrics: redundant with v2 features (zero improvement)
- Task-specific ensemble: worse than all-task pooling
- Phase-gated VelInc: modest win (CCC 0.610→0.620, slope 0.446→0.461)

### HP Optimization (Session 9)
- min_data_in_leaf 20→10: +0.105 CCC (dominant knob)
- reg_lambda 3.0→0.5: +0.017 CCC
- All other HPs: plateau at CCC≈0.515 (5-split)

### Feature Group Exploration (Session 10)
- K=500 (up from 300): +0.030 CCC
- No extra feature groups help (nl_, fq_, sv_, velinc, walkway all neutral)
- v2 handcrafted features dominate for obs subscore; FM adds near-zero
- Best HP config: K=500, min_leaf=8, reg_lambda=0.3

## Key Learnings

1. **The compression problem was NOT a feature problem — it was a representation problem.** Adding features, tuning HPs, changing loss functions, augmenting tails — none of these addressed the fundamental issue that N=94 PD subjects don't provide enough information for well-calibrated severity estimation. P5 solved this by bringing in N=80 HC as calibration anchors.

2. **Semi-supervised representation learning > supervised regression tuning.** The XGBRanker on N=178 learns a severity axis that the downstream regressor can use. This is the same insight behind foundation models (learn representations on large data, fine-tune on small data), but applied at the study level rather than the model level.

3. **LightGBM device='gpu' is 2.2x SLOWER than CPU for N<200.** GPU overhead dominates for small tabular datasets. Always use CPU for this project.

4. **Per-item ordinal classification fails dramatically.** Despite being the highest-ranked proposal theoretically (70% predicted success), it produced the worst result (CCC=0.338). The failure mode: sparse ordinal classes (most items score 0-1), eval_set label mismatch crashes, and loss of inter-item correlation.

5. **5-split CCC has high variance but P5 is remarkably stable.** The T1 5-split CCC (0.865) matched LOOCV exactly — unusual stability for N=94. This suggests the SSL ranking features create a fundamentally more stable representation.
