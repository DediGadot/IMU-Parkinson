## Findings: CCC Definition Lookup (2026-03-26)

### F1: CCC is Lin's concordance correlation coefficient in both code and manuscript
- Canonical implementation is `lins_ccc(y_true, y_pred)` in `eval_utils.py`.
- The formula used is `2 * cov / (var_true + var_pred + (mean_true - mean_pred)^2)`, which penalizes both poor correlation and mismatch in spread/mean.

### F2: The paper uses CCC specifically to detect prediction compression
- `generate_paper.py` states that small-N regression can collapse predictions toward the population mean, producing reasonable MAE but poor concordance.
- The manuscript explicitly contrasts CCC with MAE by arguing that a mean-predicting model may have tolerable error yet be clinically useless because it cannot separate mild from severe patients.

### F3: Verified headline artifact values match the paper narrative
- T1 baseline 5-fold: CCC=0.700, MAE=1.336, r=0.758, slope=0.508 (`results/compression_P0_TT1.json`)
- T1 SSL LOOCV: CCC=0.868, MAE=0.986, r=0.899, slope=0.689 (`results/compression_P5_TT1_loocv.json`)
- T1 SSL 5-fold: CCC=0.865, MAE=0.953, r=0.877, slope=0.745 (`results/compression_P5_TT1_5split.json`)
- T3 SSL LOOCV: CCC=0.776, MAE=4.646, r=0.827, slope=0.576 (`results/compression_P5_TT3_loocv.json`)

---

## Findings: Paper Innovations + Result Impact (2026-03-26)

### F1: The paper's novelty is split between target design and learning strategy
- From the paper framing, the main innovations are not just "a better regressor" but: (a) an observability-aware decomposition of UPDRS-III and (b) a semi-supervised ordinal ranking/calibration stage that uses healthy controls as anchors.
- Need manuscript anchors for exact wording and equation/table references.

### F2: The current manuscript explicitly names four contributions, but two dominate scientifically
- `NEW.html` states four contributions: first WearGait-PD regression benchmark, two-stage ordinal ranking, three-level observability decomposition, and sensitivity analyses on age/HC inclusion.
- The largest scientific contributions are clearly the ordinal-ranking anti-compression method and the observability framework; the benchmark/sensitivity analyses support those claims.

### F3: Code confirms the ranking method is exactly a 2-stage XGBRanker -> leaf-features -> LightGBM pipeline
- `run_compression_ablation.py` defines T1/T2/T3 targets as items 9-14, 7-14, and 1-18 respectively.
- P5 labels HC as rank 0 and PD as ordinal ranks 1..N, trains `XGBRanker(objective="rank:pairwise")`, extracts leaf indices, concatenates them to selected features, and trains a PD-only LightGBM ensemble.

### F4: The ranking method has the largest quantitative effect in the repo
- 5-fold P0 -> P5:
  - T1: CCC 0.700 -> 0.865, MAE 1.336 -> 0.953, slope 0.508 -> 0.745
  - T2: CCC 0.554 -> 0.831, MAE 1.851 -> 1.162, slope 0.425 -> 0.707
  - T3: CCC 0.186 -> 0.807, MAE 8.086 -> 4.464, slope 0.104 -> 0.581
- This is the clearest evidence that the paper is primarily about reducing prediction compression, not only lowering error.

### F5: Observability changes the interpretation of the entire task
- `NEW.html` Table 2 shows the 5-fold tier-wise pattern:
  - Direct: baseline CCC 0.700, ranking CCC 0.865
  - Partial: baseline CCC 0.055, ranking CCC 0.730
  - Unobservable: baseline CCC 0.176, ranking CCC 0.759
- The manuscript argues that total UPDRS is structurally limited because 82% of the score range comes from partially or non-observable items.

### F6: Reviewer sensitivity analyses weaken the strongest possible "HC anchors are the key" interpretation
- In the HC ablation, PD-only ranking and PD+HC ranking are nearly identical on T1 (CCC 0.857 vs 0.858), with PD-only slightly better on T3 (0.789 vs 0.763).
- The code + current paper text therefore support: ranking-to-leaf transformation is the main engine; HC anchors are incremental calibration support, not the only source of improvement.

### F7: Age-confound checks support robustness rather than novelty
- Age-matched HC slightly improves T1 CCC (0.868 vs 0.858 full HC), and partial correlation controlling age remains strong (r=0.849; age+dx r=0.823).
- These analyses are important for credibility, but they are validation/support contributions rather than core methodological innovations.

---

## Findings: Codebase Audit (2026-03-25)

### F1: Repo shape is experiment-first, not package-first
- The root contains many standalone `run_*.py` scripts, multiple paper generators, and several manuscript/output variants.
- Shared logic exists, but it is fragmented across utility modules and large runner scripts rather than a clean package boundary.

### F2: Prior session context is about reviewer-response paper work
- Existing planning files and diffs show the repo is currently mid-stream on reviewer-driven manuscript revision, not a clean greenfield state.
- Current audit needs to separate durable architecture issues from temporary paper-edit churn.

### F3: Docs repeatedly frame the project around contamination recovery
- `CONT.md`, `EXP.md`, `LEARNINGS.md`, `VNEXT.md`, and `README.md` all center evaluation hygiene, protocol matching, and provenance control.
- This is not just a model-development repo; a large share of the intellectual work is audit/remediation of prior experimental mistakes.

### F4: There are multiple overlapping “source of truth” layers
- `AGENTS.md` says the clean path centers on `data_split.py`, selected `run_*` scripts, and `generate_html_paper3.py`.
- `README.md` still highlights older primary scripts like `run_compression_ablation.py` and `generate_paper.py`.
- Large planning docs (`PROPOSALS.md`, `NEXTNEXT.md`, `CODEX-PROPOSALS.md`) describe additional future tracks not clearly separated from active production paths.

### F5: Security hygiene is weak in repo-local docs
- `TOKEN.md` contains a raw Synapse token in plain text.
- `GPU.md` contains direct server access information.
- Repo guidance says not to commit credentials, but the repo state currently violates that rule.

### F6: The repo has a documented “clean path,” but multiple overlapping control planes remain
- `CONT.md` defines the post-audit truth: fixed contamination bugs, fresh split protocol, canonical `results/` artifacts, and `paper3.html`.
- `README.md` and `CLAUDE.md` still foreground older primary paths like `run_compression_ablation.py` and `generate_paper.py` / `NEW.html`.
- This suggests the codebase lacks one unambiguous current entrypoint for “what to run now.”

### F7: Proposal/planning documents duplicate and partially diverge
- `NEXTNEXT.md`, `PROPOSALS.md`, `CODEX-PROPOSALS.md`, `VNEXT.md`, and `autoresearch_program.md` all prescribe future work, but with different target priorities and benchmark assumptions.
- Several ideas repeat across files: structured item modeling, task-aware bags, hybrid fusion, repeated-split validation, phenotype-aware experts.
- The duplication itself is now a maintenance burden and likely to confuse future agents or collaborators.

### F8: Review artifacts show strong numerical discipline but unresolved narrative issues
- `review_report.md` and `review_report_numbers.md` indicate the current manuscript is numerically consistent with stored JSON artifacts.
- The remaining gaps are mostly framing/analysis issues: ambiguous “SSL” naming, mixed evaluation protocols in main tables, missing DBS stratification, missing headline CIs, and subject-count flow clarity.

### F9: `NEW.html` is current-paper heavy and self-contained, but generated output is carrying too much project truth
- The manuscript embeds a large amount of final narrative and even figure assets directly in HTML.
- Critical project knowledge is split between source scripts, Markdown memos, and generated HTML outputs instead of being cleanly separated into source-of-truth data + renderer.

### F10: Code architecture is “small helper core + many large runners”
- The true shared core is narrow: `project_paths.py`, `data_split.py`, `updrs_columns.py`, plus newer paper helpers like `paper3_data.py` and `paper2_renderer.py`.
- Most other behavior lives in large standalone `run_*.py` scripts, several in the 800–1800+ line range, with one extreme `generate_paper.py` monolith at ~3900 lines.

### F11: Clean-path scripts still depend directly on legacy builders
- `run_clean_benchmark.py`, `run_stats_report.py`, `run_sensor_ablation.py`, and other newer scripts import feature-building pieces from `run_ablation_v2.py` and model helpers from `run_proven_stack.py`.
- This means the repo has improved orchestration and artifact hygiene, but not yet true isolation of shared feature/model libraries.

### F12: Testing is real but concentrated on invariants, not end-to-end experiment health
- Local suite passes: `129 passed, 4 skipped`.
- Tests strongly cover path helpers, split integrity, sensor-filter logic, and UPDRS column resolution.
- There is little direct automated coverage for major experiment runners, artifact schemas, or manuscript-generation consistency beyond the ad hoc review markdowns.

### F13: Historical code and current code coexist in the same flat namespace
- The root contains old exploratory runners (`run_ablation.py`, `run_experiments.py`, `run_ultimate.py`, etc.), current clean-path runners, manuscript generators old and new, and various one-off fixes.
- Because everything lives together at top level, “active vs legacy vs prototype” status is mostly encoded in human memory and markdown, not repo structure.

### F14: The repo’s strongest engineering improvement so far is artifact discipline
- `project_paths.py`, `save_json_artifact`, and artifact-backed consumers like `paper3_data.py` are the clearest step toward reproducibility.
- The biggest remaining gap is schema discipline: many scripts still hand-roll JSON payloads, and manuscript/render layers rely on implicit field contracts.

---

## Findings: Reviewer Response (2026-03-24)

### F1: 5-fold SSL results are STRONGER than LOOCV on T3
- T3 5-fold: CCC=0.807, MAE=4.464, r=0.877
- T3 LOOCV: CCC=0.776, MAE=4.646, r=0.827
- **Implication:** Switching to 5-fold as primary is painless — results improve

### F2: 5-fold results already exist for all SSL targets
- Files: `compression_P5_TT{1,2,3}_5split.json`
- P0 baselines also already 5-fold: `compression_P0_TT{1,2,3}.json`
- No new experiment needed for C1/C5

### F3: Partial correlation already computed
- Phase 4 results: partial_r=0.36, p=0.0003 (controlling age + disease duration)
- This is for FM predictions, need same for P5 SSL predictions
- Per-subject predictions ARE saved in compression JSON per_subject field

### F4: Sensor ablation already has lower_back_1 and wrists_2
- lower_back_1: MAE=9.50, r=0.562
- wrists_2: MAE=8.75, r=0.662
- Missing: single right wrist, single left wrist

### F5: Gemini advice on age confound (4 analyses)
1. Age-matched subgroup (threshold HC < 75y, re-run SSL)
2. Partial correlation controlling age (residualize both pred and true on age)
3. Age-stratified within-PD eval (tertiles)
4. Feature importance divergence (SHAP for UPDRS vs age-prediction model)

### F6: Codex advice on 5-fold CV for SSL
- HC can stay in Stage 1 for all folds (auxiliary anchors, no target leakage)
- Expected ~5-12% degradation from reduced training N → ACTUALLY got improvement
- Present 5-fold as primary, LOOCV as supplementary sensitivity
- Add sensitivity row: "SSL 5-fold, HC fold-restricted" to show robustness

### F7: Paper restructuring advice (Gemini)
- Main text: 5-6 Results subsections (cohort, primary obs, gradient, secondary total, sensitivity, cross-dataset)
- SM: compression ablation, FM, sensor ablation, quartile bias, negative results, LOOCV

### F8: HC age difference is REAL and must be addressed head-on
- HC: 74.6 +/- 8.5 years
- PD: 66.9 +/- 8.3 years
- Difference: ~7.7 years, highly significant
- The age-matched analysis is essential for publication credibility

### F9: run_compression_ablation.py already supports --eval 5split|loocv
- Phase 5 (SSL) can run both modes
- All phases support both evaluation modes
- Script is 1341 lines, well-structured

### F10: Synapse download uses TOKEN env var
- `synapse_download.py` reads `SYNAPSE_TOKEN` from env
- Downloads to `/root/pd-imu/data/raw/weargait-pd/`
- Token in `TOKEN.md`

---

## Archived: Figure Generation Review (2026-03-15)
(Previous session findings archived — see git history)
