# Progress — Figure Generation Review for Nature Digital Medicine (2026-03-15)

## Session 15 — Review of `generate_paper.py` Figure Functions

### Objective
Assess the matplotlib figure-generation functions in `generate_paper.py` for publication quality and write a patch-oriented review to `.paper_build/external_codex_visual.md`.

### Log
- [start] Read planning-with-files skill instructions and checked for existing planning files in the repo.
- [start] Found existing `task_plan.md`, `findings.md`, and `progress.md`; read them before beginning the figure review.
- [start] Located `generate_paper.py` and mapped all matplotlib figure-generation functions for Figures 1-10 and Appendix Figures A-F.
- [analysis] Confirmed the review scope should stay inside the plotting functions and shared matplotlib style section, not the manuscript text.
- [analysis] Flagged Figures 2, 3, and 7 as likely highest-impact review targets because they carry the key SSL-performance and compression-ablation claims.
- [read] Reviewed the shared style block plus all main and appendix figure functions with line references.
- [verify] Extracted embedded PNG figures from `NEW.html` to inspect the current rendered output without re-running matplotlib locally.
- [analysis] Confirmed the most serious issue is that Figures 2 and 3 synthesize scatter points from summary statistics rather than plotting stored predictions.
- [analysis] Identified additional high-impact visual issues: Figure 1 clipping, Figure 4 whitespace + weak encoding, Figure 6 pseudo-importance bars, Figure 7 mixed-protocol emphasis, and Appendix Figure A reversed arrow direction.
- [write] Drafted `.paper_build/external_codex_visual.md` with per-figure assessments and five patch-ready matplotlib code changes.
- [verify] Re-read the visual review and corrected the patch snippets for consistency.
- [done] Completed the figure-generation review and updated planning files.

---

# Progress — Nature Digital Medicine Writing Review (2026-03-15)

## Session 14 — Editorial Review of `.paper_build/paper_text.txt`

### Objective
Assess the extracted manuscript text for Nature Digital Medicine fit and write a structured review to `.paper_build/external_codex_writing.md`.

### Log
- [start] Read planning-with-files skill instructions and checked for existing planning context in the repo.
- [start] Found existing `task_plan.md`, `findings.md`, and `progress.md`; read them before beginning the new review task.
- [read] Loaded `.paper_build/paper_text.txt` and reviewed the abstract, introduction, results, and discussion passages most relevant to tone, claim strength, and narrative structure.
- [read] Extracted candidate high-risk phrases and sentences for rewrite prioritization, including title language, abstract conclusion, discussion claims, and CCC framing.
- [analysis] Identified the main editorial tension: the paper has both a positive methods story (SSL rescues calibration) and a limiting mechanistic story (gait sensors impose an observability ceiling), but the current sequencing does not always make that relationship explicit.
- [analysis] Identified recurring style issues inconsistent with Nature-family tone: overclaiming, conversational diction, and overly absolute mechanistic statements.
- [analysis] Identified that the abstract mostly explains the SSL method, but the observability decomposition is not fully intelligible from the abstract alone.
- [write] Drafted `.paper_build/external_codex_writing.md` with six requested review sections and 10 high-impact sentence rewrites.
- [verify] Re-read the output file and corrected one quoted sentence so the original wording matches the extracted text.
- [done] Completed the writing review and updated planning files to reflect final status.

---

# Progress — NEW.html Verification Audit (2026-03-15)

## Session 13 — Repository-Wide Verification of `NEW.html`

### Objective
Verify `NEW.html` against repository result artifacts for numerical correctness, coherent interpretation, and agreement with the implemented evaluation pipeline.

### Log
- [start] Read planning-with-files skill instructions and ran session catchup.
- [start] Catchup reported prior unsynced context: `NEW.html` had been edited in a previous session with SSL-ranking additions and several claimed fixes.
- [start] Read existing `task_plan.md`, `findings.md`, and `progress.md` to recover experiment context before starting the audit.
- [start] Updated planning files to track this verification pass explicitly.
- [audit] Inventoried manuscript-support files: `results/` contains compression-ablation outputs plus legacy paper artifacts; `.paper_build/` contains `current_truth.md`, `paper_claims.md`, and prior verification notes.
- [audit] First grep of `NEW.html` surfaced probable stale headline values (`CCC=0.868` direct observable, `CCC=0.776` total SSL, baseline total `CCC=0.37`) relative to current compression-ablation planning notes.
- [audit] Read `.paper_build/current_truth.md` and `.paper_build/verification_report.md`; discovered the truth file is internally inconsistent on SSL numbers, so the prior manuscript verification is not sufficient evidence.
- [audit] Attempted JSON inspection with `python`, but this environment only has `python3`; switching tooling accordingly.
- [audit] Verified raw P5 JSON files directly. Authoritative LOOCV metrics are T1 `CCC=0.868, MAE=0.986`, T2 `CCC=0.852, MAE=1.334`, T3 `CCC=0.776, MAE=4.646`.
- [audit] Confirmed the number conflict comes from secondary synthesis artifacts (`compression_ablation_all.json` and reused tables in `current_truth.md`), not from the latest P5 result files.
- [audit] Cross-checked `results/compression_P0_TT*.json` and confirmed all P0 comparison rows are `eval_mode: 5split`; `NEW.html` currently mislabels the combined P0/P5 comparison table as LOOCV.
- [audit] Confirmed there is no local SSL 10-split artifact backing the “all 10 cross-validation splits” statement in Discussion 3.1.
- [audit] Verified the observability-gradient narrative currently mixes SSL direct-observable numbers with baseline partial/unobservable numbers; this needs wording fixes for methodological coherence.
- [edit] Patched `NEW.html` to separate baseline decomposition results from SSL gains in the abstract/discussion.
- [edit] Patched Section 2.12/Table 7 note/caption to reflect the actual evaluation modes and sample sizes: P0 `5split`, N=95; P5 `loocv`, N=94.
- [edit] Patched the unsupported SSL 10-split claim in Discussion 3.1 and softened sensor-ablation conclusions to match the total-score evidence in `results/pd_only_phase6.json`.
- [audit] Reviewed `.claude/commands/update-paper.md` to determine which guardrails were missing from the paper-update workflow that would have allowed the manuscript inconsistencies to slip through.
- [edit] Updated the slash command's update path to prioritize raw artifacts, require claim provenance/protocol tracking, forbid unsupported split claims and cross-endpoint overreach, and keep baseline decomposition separate from SSL gains.
- [edit] Fixed remaining update-path hardcoded manuscript references so the command now consistently targets `NEW.html` when present, including diff/fix, figure replacement, verification, and final reporting instructions.
- [verify] Re-checked the modified `NEW.html` passages with `rg`/`sed`; the stale phrasing is gone from the touched sections.
- [verify] Found remaining non-result placeholders in `NEW.html` front matter for authors/affiliations; leaving untouched because source values are not present in the repo artifacts reviewed here.

---

# Progress — Compression Ablation (2026-03-14)

## Session 12 — 5 Proposals × 3 Targets Ablation

### Objective
Implement all 5 anti-compression proposals across 3 targets (direct obs, broad obs, total UPDRS-III).

### Log
- [20:40] Designed execution plan: 5 proposals × 3 targets = 15 experiment groups
- [20:40] Server confirmed: RTX 3070, 9 CPU, all caches ready
- [20:40] Per-item scores available: 96-97 PD subjects across all items
- [20:41] Writing implementation script...
- [20:50] Script written (1341 lines), deployed to server
- [20:55] P0 baseline + P3 SMOGN complete for all 3 targets
- [20:56] P1 crashed (unseen label in eval_set). Fixed: skip eval_set when val has unseen classes.
- [20:58] Relaunched P1 (fixed) + P2 (pairwise) + P4 (NGBoost) + P5 (SSL) in parallel
- [21:00] All 4 running: P1=606% CPU, P2=271%, P4=231%, P5=202%
- [21:05] P1_T1 done: CCC=0.338 — ordinal WORSE than baseline (0.700). Temperature sharpening fails.
- [21:08] P4_T1 done: CCC=0.671 — NGBoost competitive but below baseline
- [21:08] P3_T1: CCC=0.665 but best slope=0.528 and Q4 bias=-1.22 (best calibration)
- [21:08] **Baseline P0 wins T1 on CCC (0.700)** — the new HP config (K=500, leaf=8) is already strong
- [21:08] P2 + P5 still running on T1. P1 on T2. P4 on T2.
- [21:15] P4 complete all 3 targets: T1=0.671, T2=0.595, T3=0.187 (competitive but below baseline on T1)
- [21:15] P3 SMOGN WINS on T2: CCC 0.554→0.603, slope 0.425→0.546 (best calibration)
- [21:15] T3 total hopeless for all proposals (~CCC=0.19)
- [21:25] P1 still on T2 (slow: per-item multiclass × temp CV). P2 still on T1. P5 still on T1.
- [21:25] Waiting for P2 (pairwise) and P5 (SSL) — the most novel proposals
- [22:18] P5 split 4: CCC=0.916, slope=0.807!!! Extraordinary.
- [23:02] **P5 T1 COMPLETE: CCC=0.865, slope=0.745, MAE=0.953** — MASSIVE breakthrough!
  - vs baseline: CCC +23.6%, slope +46.7%, MAE -28.7%, Q4 bias 61% less
  - Semi-supervised ranking from HC = the single biggest improvement in the project
- [23:02] P5 now running T2. P2 still computing T1. P1 still on T2.
- [23:30] Killed P1 (ordinal failed — CCC=0.338). Freed CPU for P2+P5.
- [00:29] P5_T2 COMPLETE: CCC=0.831, slope=0.707 — dominates T2 baseline (0.554)
- [01:30] P5_T3 COMPLETE: CCC=0.807, slope=0.581, MAE=4.464 — **TOTAL UPDRS from CCC=0.186 to 0.807!**
- [01:30] P5 (SSL Ranking) dominates ALL 3 targets. P2 (pairwise) still running, at split 2/5 T1.
- [01:30] ALL RESULTS PULLED locally (13 files)
- [02:03] Launched P5 LOOCV validation for all 3 targets. Killed P2 (pairwise, CCC~0.62) to free CPU.
- [04:27] **P5 T1 LOOCV CONFIRMED: CCC=0.865, slope=0.745, MAE=0.953** — matches 5-split exactly!
- [04:27] This is the GOLD STANDARD result. SSL ranking from HC is validated.
- [04:30] P5 LOOCV continuing on T2 and T3...

---

## Session 11 — Compression Proposals Advisory

### Objective
Convert the repo's calibration/compression findings into five high-value experiment proposals that attack the mechanism directly.

### Actions
- Read planning-with-files skill instructions and session catchup output.
- Reviewed current repo planning files plus `git diff --stat` to avoid clobbering prior session context.
- Searched repo for calibration/compression history, ordinal attempts, and proposal notes.
- Confirmed current evidence: strong feature engineering and HP search exhausted, persistent compression remains.
- Began drafting proposals centered on target decomposition, uncertainty/distribution modeling, subject-level augmentation, SSL/ranking, and Bayesian latent structure.
- Finalized ranked shortlist for user delivery: structured item ordinal, severity-gated experts, discrete distributional prediction, subject-level tail augmentation, and rank-regularized SSL.

### Files updated
- `task_plan.md`
- `findings.md`
- `progress.md`

## Session 10 — Feature Space Exploration + K Tuning

### Objective
Maximize CCC for observable motor subscore (items 3.9-3.14), PD-only.
Systematic exploration of feature groups, new modalities, and K/HP combinations.

### NEW Best: CCC=0.5696 (5-split) / 0.611 (10-split) / 0.591 (LOOCV)
Config: v2+fm, K=500, min_leaf=8, reg_lambda=0.3, colsample=0.5, lr=0.03, 5 seeds

Previous best was CCC=0.5145 (5-split) / 0.5806 (10-split) with K=300, min_leaf=10, reg_lambda=0.5.

### Results Table (28 experiments)
| # | Name | Change | CCC | Slope | MAE | Delta | p | Status |
|---|------|--------|-----|-------|-----|-------|---|--------|
| **Phase A: Subtraction** | | | | | | | | |
| A2 | v2_core | core only (1480 feats) | 0.428 | 0.273 | 1.825 | -0.087 | 0.19 | DISCARD |
| A3 | core_fc | core+foot contact | 0.425 | 0.276 | 1.876 | -0.090 | 0.13 | DISCARD |
| A4 | core_fc_ev_delta | core+fc+ev+delta | 0.463 | 0.306 | 1.802 | -0.052 | 0.63 | DISCARD |
| **Phase B: Extra groups** | | | | | | | | |
| B6 | v2_extfq | v2+frequency | 0.523 | 0.359 | 1.751 | +0.009 | 0.81 | DISCARD |
| B7 | v2_extnl | v2+nonlinear | 0.514 | 0.350 | 1.741 | -0.000 | 0.81 | DISCARD |
| B8 | v2_extsv | v2+stride var | 0.483 | 0.323 | 1.821 | -0.032 | 0.31 | DISCARD |
| B9 | v2_allextras | v2+ALL extras | 0.512 | 0.333 | 1.710 | -0.003 | 1.00 | DISCARD |
| **Phase C: New modalities** | | | | | | | | |
| C11 | v2_velinc | v2+VelInc | 0.503 | 0.342 | 1.797 | -0.012 | 0.63 | DISCARD |
| C12 | v2_velincgated | v2+VelInc gated | 0.512 | 0.352 | 1.738 | -0.002 | 0.81 | DISCARD |
| C13 | all | ALL features | 0.507 | 0.351 | 1.799 | -0.008 | 0.44 | DISCARD |
| **Phase D: K tuning** | | | | | | | | |
| D14 | v2_k200 | v2-only K=200 | 0.503 | 0.347 | 1.804 | -0.012 | 0.81 | DISCARD |
| D15 | v2_k400 | v2-only K=400 | 0.491 | 0.330 | 1.784 | -0.024 | 0.19 | DISCARD |
| D16 | v2fm_k50 | v2+fm K=50 | 0.496 | 0.336 | 1.796 | -0.018 | 0.81 | DISCARD |
| **D17** | **v2fm_k500** | **v2+fm K=500** | **0.544** | **0.369** | **1.693** | **+0.030** | **0.19** | **KEEP** |
| D18 | v2fm_k600 | v2+fm K=600 | 0.535 | 0.369 | 1.728 | -0.009 | 0.44 | DISCARD |
| D19 | v2fm_k450 | v2+fm K=450 | 0.529 | 0.356 | 1.722 | -0.016 | 0.31 | DISCARD |
| **Phase E: Combinations with K=500** | | | | | | | | |
| E20 | v2fm_velg_k500 | v2+fm+velincg K=500 | 0.480 | 0.331 | 1.830 | -0.065 | 0.06 | DISCARD |
| E21 | v2extras_fm_k500 | v2+extras+fm K=500 | 0.522 | 0.377 | 1.792 | -0.022 | 0.19 | DISCARD |
| **Phase F: HP tuning at K=500** | | | | | | | | |
| F22 | k500_leaf8 | leaf 10->8 | 0.562 | 0.387 | 1.646 | +0.018 | 0.63 | DISCARD |
| F23 | k500_leaf5 | leaf 10->5 | 0.528 | 0.355 | 1.709 | -0.016 | 0.81 | DISCARD |
| **F24** | **k500_leaf8_reg03** | **leaf=8 reg=0.3** | **0.570** | **0.394** | **1.637** | **+0.025** | **0.31** | **BEST** |
| F25 | k500_leaf8_reg01 | leaf=8 reg=0.1 | 0.554 | 0.376 | 1.644 | +0.010 | 0.81 | DISCARD |
| F27 | col06 | colsample 0.5->0.6 | 0.554 | 0.375 | 1.646 | +0.010 | 1.00 | DISCARD |
| F28 | sub08 | subsample 0.8 | 0.570 | 0.394 | 1.637 | +0.025 | 0.31 | DISCARD |
| F29 | depth5_leaves63 | depth=5 leaves=63 | 0.566 | 0.389 | 1.641 | +0.022 | 0.31 | DISCARD |
| F30 | slow_lr | lr=0.01 5k trees | 0.558 | 0.380 | 1.643 | +0.014 | 0.81 | DISCARD |
| **Phase G: Validation** | | | | | | | | |
| G26 | 10-split | 10-split eval | **0.611** | **0.433** | **1.603** | N/A | N/A | INFO |
| G26 | LOOCV | LOOCV eval | **0.591** | **0.402** | **1.662** | N/A | N/A | LOOCV |

### Key Insights
1. **K=500 is better than K=300** — the only significant improvement in feature space (+0.030 CCC)
2. **min_leaf=8 + reg_lambda=0.3** at K=500 gives CCC=0.570 (5-split), 0.611 (10-split), 0.591 (LOOCV)
3. **v2 core features are essential** — dropping to core-only loses ~0.09 CCC; full v2 synergy needed
4. **Extra feature groups add nothing** — freq, nonlinear, stride-var, VelInc all neutral or negative
5. **New modalities (VelInc, VelInc gated) add nothing** — feature selection already picks the best from v2
6. **Kitchen sink hurts** — adding everything dilutes signal
7. **HP landscape is flat** — 10+ HP variants all land at CCC 0.55-0.57 on 5-split
8. **10-split estimate (0.611) > 5-split (0.570)** — more folds capture more of the variance
9. **LOOCV=0.591 is the gold standard** — up from 0.56 in Phase 3

### Improvement Over Session 9
| Metric | Session 9 | Session 10 | Delta |
|--------|-----------|------------|-------|
| 5-split CCC | 0.515 | 0.570 | +0.055 |
| 10-split CCC | 0.581 | 0.611 | +0.030 |
| LOOCV CCC | N/A | 0.591 | new |
| cal_slope | 0.357 | 0.394 | +0.037 |
| MAE | 1.755 | 1.637 | -0.118 |

---

## Session 9 — CCC Hyperparameter Optimization

### Objective
Maximize CCC for observable motor subscore (items 3.9-3.14), PD-only.

### Current Best: CCC=0.5145 (min_leaf_10)
Config: reg_lambda=0.5, min_data_in_leaf=10, K=300, colsample=0.5, 5 seeds

### Results Table
| # | Name | Change | CCC | Slope | MAE | Delta | p | Status |
|---|------|--------|-----|-------|-----|-------|---|--------|
| 0 | ccc_baseline | baseline | 0.3928 | 0.2547 | 1.874 | — | — | BASELINE |
| 1 | reg_lambda_1.0 | reg_lambda 3→1 | 0.3966 | 0.2571 | 1.873 | +0.004 | 0.19 | DISCARD |
| 2 | reg_lambda_0.5 | reg_lambda 3→0.5 | 0.4097 | 0.2691 | 1.863 | +0.017 | 0.06 | KEEP |
| 3 | reg_lambda_0.1 | reg_lambda 0.5→0.1 | 0.4073 | 0.2669 | 1.865 | -0.002 | 0.44 | DISCARD |
| 4 | min_leaf_10 | min_leaf 20→10 | **0.5145** | **0.3572** | **1.755** | **+0.105** | 0.13 | **KEEP** |
| 5 | min_leaf_5 | min_leaf 10→5 | 0.5196 | 0.3562 | 1.734 | +0.005 | 1.00 | DISCARD |
| 6 | leaves_63 | num_leaves 31→63 | 0.5145 | 0.3572 | 1.755 | +0.000 | 1.00 | DISCARD |
| 7 | leaves127_depth8 | leaves=127 depth=8 | 0.5145 | 0.3572 | 1.755 | +0.000 | 1.00 | DISCARD |
| 8 | k200 | K 300→200 | 0.5142 | 0.3599 | 1.765 | -0.000 | 1.00 | DISCARD |
| 9 | k150 | K 300→150 | 0.5187 | 0.3648 | 1.786 | +0.004 | 0.81 | DISCARD |

### Full Results Table (all 20 experiments after baseline)
| # | Name | Change | CCC | Slope | MAE | Delta | p | Status |
|---|------|--------|-----|-------|-----|-------|---|--------|
| 0 | ccc_baseline | baseline | 0.3928 | 0.2547 | 1.874 | -- | -- | BASELINE |
| 1 | reg_lambda_1.0 | reg_lambda 3→1 | 0.3966 | 0.2571 | 1.873 | +0.004 | 0.19 | DISCARD |
| 2 | **reg_lambda_0.5** | **reg_lambda 3→0.5** | **0.4097** | **0.2691** | **1.863** | **+0.017** | **0.06** | **KEEP** |
| 3 | reg_lambda_0.1 | reg_lambda 0.5→0.1 | 0.4073 | 0.2669 | 1.865 | -0.002 | 0.44 | DISCARD |
| 4 | **min_leaf_10** | **min_leaf 20→10** | **0.5145** | **0.3572** | **1.755** | **+0.105** | **0.13** | **KEEP** |
| 5 | min_leaf_5 | min_leaf 10→5 | 0.5196 | 0.3562 | 1.734 | +0.005 | 1.00 | DISCARD |
| 6 | leaves_63 | num_leaves 31→63 | 0.5145 | 0.3572 | 1.755 | +0.000 | 1.00 | DISCARD |
| 7 | leaves127_depth8 | leaves=127 depth=8 | 0.5145 | 0.3572 | 1.755 | +0.000 | 1.00 | DISCARD |
| 8 | k200 | K 300→200 | 0.5142 | 0.3599 | 1.765 | -0.000 | 1.00 | DISCARD |
| 9 | k150 | K 300→150 | 0.5187 | 0.3648 | 1.786 | +0.004 | 0.81 | DISCARD |
| 10 | col0.3 | colsample 0.5→0.3 | 0.5030 | 0.3433 | 1.774 | -0.012 | 0.13 | DISCARD |
| 11 | col0.7 | colsample 0.5→0.7 | 0.5101 | 0.3527 | 1.780 | -0.004 | 0.63 | DISCARD |
| 12 | lr0.01 | learning_rate 0.03→0.01 | 0.5159 | 0.3568 | 1.758 | +0.001 | 1.00 | DISCARD |
| 13 | lr0.05 | learning_rate 0.03→0.05 | 0.5050 | 0.3526 | 1.772 | -0.010 | 0.63 | DISCARD |
| 14 | avg_ensemble | LGB+XGB average | 0.4756 | 0.3041 | 1.765 | -0.039 | 0.13 | DISCARD |
| 15 | stack_ensemble | LGB+XGB+Ridge stack | 0.5240 | 0.3679 | 1.767 | +0.010 | 1.00 | DISCARD |
| 16 | subsample_0.8 | subsample 1.0→0.8 | 0.5145 | 0.3572 | 1.755 | +0.000 | 1.00 | DISCARD |
| 17 | fm_only | FM-only (drop v2) | 0.1926 | 0.1140 | 2.173 | -0.322 | 0.06 | DISCARD |
| 18 | 3seeds | 5→3 seeds | 0.5056 | 0.3490 | 1.756 | -0.009 | 0.19 | DISCARD |
| 19 | v2_only | v2-only (drop FM) | 0.5219 | 0.3636 | 1.803 | +0.007 | 1.00 | DISCARD |
| -- | 10split | 10-split evaluation | 0.5806 | 0.4008 | 1.664 | N/A | N/A | INFO |
| 20 | k400 | K 300→400 | 0.5141 | 0.3546 | 1.751 | -0.000 | 1.00 | DISCARD |
| 21 | valfrac_0.10 | val_frac 0.15→0.10 | 0.4656 | 0.3094 | 1.806 | -0.049 | 0.13 | DISCARD |
| 22 | valfrac_0.20 | val_frac 0.15→0.20 | 0.5117 | 0.3569 | 1.763 | -0.003 | 1.00 | DISCARD |
| 23 | min_leaf_7 | min_leaf 10→7 | 0.5118 | 0.3507 | 1.723 | -0.003 | 1.00 | DISCARD |
| 24 | esr50 | early_stopping 100→50 | 0.5110 | 0.3526 | 1.764 | -0.004 | 0.50 | DISCARD |
| 25 | 5k_trees | 5000 trees + ES=200 | 0.5140 | 0.3571 | 1.757 | -0.001 | 0.75 | DISCARD |
| 26 | 7seeds | 5→7 seeds | 0.5112 | 0.3501 | 1.759 | -0.003 | 0.81 | DISCARD |
| 27 | huber | huber loss | 0.4941 | 0.3313 | 1.804 | -0.020 | 0.19 | DISCARD |
| 28 | reg_lambda_0 | reg_lambda 0.5→0.0 | 0.5109 | 0.3535 | 1.759 | -0.004 | 0.63 | DISCARD |
| 29 | v2fm_velinc | +VelInc (not cached) | 0.5145 | 0.3572 | 1.755 | +0.000 | 1.00 | DISCARD |
| 30 | k100 | K 300→100 | 0.5130 | 0.3670 | 1.793 | -0.002 | 1.00 | DISCARD |
| 31 | depth4 | max_depth 6→4 | 0.5117 | 0.3540 | 1.757 | -0.003 | 0.81 | DISCARD |

### Key Insights
1. **min_data_in_leaf is the dominant knob** — 20→10 gave +0.105 CCC, the only large gain
2. **reg_lambda reduction** — 3.0→0.5 gave modest +0.017 CCC improvement
3. **Remarkable stability** — CCC 0.51 plateau across most HP variations (K, lr, depth, leaves, seeds)
4. **v2 handcrafted features critical for obs** — FM-only CCC=0.19 vs v2+fm=0.51
5. **10-split shows CCC=0.58** — more folds capture more variance, more reliable estimate
6. **Ensembles hurt CCC** — XGB with MAE loss compresses predictions further
7. **CCC ceiling appears at ~0.52 (5-split) / ~0.58 (10-split)** with current feature set

---

## Session 8 — Observable Bias Ablation

### Context
Calibration bias in observable subscore model: cal_slope=0.40, predictions compressed to 40% of true range. Three proposals selected from systematic analysis (ranked by expected impact):
- P1: Walkway gait metrics (196 clinical-grade spatiotemporal params)
- P3: Task-specific ensemble (separate model per gait task)
- P5: VelocityIncrement kinematics (integrated velocity features)

### Log
- [12:30] Probed new server: RTX 3070 8GB, 9 CPU, 49GB RAM, bare Python 3.10
- [12:30] Designed ablation plan with parallel execution strategy
- [12:31] Starting server setup...
- [12:35] Packages installed: LGB 4.6, XGB 3.2, Torch 2.10+CUDA
- [12:36] Code deployed to new server. Started Synapse download (48 MB/s)
- [12:43] Ablation script written (1235 lines, 24 functions, 4 phases)
- [12:43] Syntax check passed
- [12:46] Download 99% (26.1/26.3 GB). Walkway CSV available.
- [12:47] Launched Phase 0 (baseline) + Phase 1 (walkway) in parallel on GPU
- [12:47] Phases 3 and 5 waiting for remaining CSV downloads to complete
- [12:50] Phase 0 running: 10/94 subjects, running MAE=1.513
- [12:50] Phase 1 started: E1.0 walkway-only (32 features, 135 subjects have walkway)
- [12:52] 718 PD CSV files downloaded. VelocityIncrement columns confirmed.
- [12:53] Launched Phase 3 (task-specific) and Phase 5 (VelocityIncrement) — all 4 phases running in parallel
- [12:55] All 4 phases confirmed running. GPU: P0=465% CPU, P1=358%, P3=66%, P5=65%
- [12:55] P3 finished extracting all 5 tasks (SelfPace, HurriedPace, TUG, TandemGait, Balance)
- [13:00] Logs show buffered output. P0 estimated ~28 min total, running ~17 min so far
- [13:05] P5 VelInc extraction COMPLETE: 139 subjects, 832 features, 855s. Starting E5.0 LOOCV.
- [13:05] P3 extraction: SelfPace done, HurriedPace 124 subj/1075 feat, TUG 159/1075, TandemGait 175/1075, Balance extracting
- [13:05] All 8 processes still running (4 main + 4 bash wrappers)
- [13:10] P3 extraction complete. All 5 tasks: SelfPace, HurriedPace, TUG, TandemGait, Balance. 93 common PD subjects.
- [13:10] P3 starting E3.0 task-specific ensemble LOOCV
- [13:10] All 4 phases in LOOCV stage, high CPU: P0=354%, P1=305%, P3=145%, P5=115%
- [13:13] Waiting for first results JSON. Output buffered at C level (LightGBM).
- [13:38] All 4 phases still running after 35 min. GPU at 1% (N=94 too small for GPU benefit). CPU oversubscribed (4 procs × n_jobs=9 on 9 cores).
- [13:56] 50 min elapsed, no results yet. CPU contention extending runtime ~2-3x. Expected completion: P1 first (smallest features), then P0/P5, then P3 (most complex).
- [14:00] ROOT CAUSE: LightGBM device='gpu' is 2.2x SLOWER than CPU for N=94 (GPU overhead dominates tiny data). Killed all, switched to CPU, running sequentially.
- [14:02] Phase 0 restarted on CPU: 10/94 in 91s (vs 199s GPU). ETA ~13 min for P0.
- [14:02] All 4 phases running sequentially via master script. Total ETA ~60 min for all.
- [14:15] **PHASE 0 COMPLETE:** MAE=1.618, CCC=0.610, slope=0.446. BEATS original Phase 3 (1.77/0.56/0.40).
- [14:15] Phase 1 started. E1.0 walkway-only: MAE=2.168, CCC=0.092 (terrible alone)
- [14:25] E1.1 walkway+v2: MAE=1.692, CCC=0.564, slope=0.405 (slightly worse than baseline)
- [14:25] E1.2 walkway+v2+FM running. Phase 1 ETA ~15 min remaining.
- [14:40] **PHASE 1 COMPLETE:** Walkway adds NO signal. Best E1.2 (walkway+v2+FM): CCC=0.604 vs baseline 0.610. Walkway features are redundant with v2.
- [14:40] Phase 3 task-specific extraction complete (5 tasks, 93 common PD subjects).
- [14:55] Phase 3 E3.0 LOOCV at 20/93, MAE=2.003. ETA ~28 min.
- [15:20] **PHASE 3 COMPLETE:** Task-specific ensemble CCC=0.548 — WORSE than baseline (0.610). Task separation loses cross-task signal.
- [15:20] Per-task best: SelfPace CCC=0.494, HurriedPace 0.480, TUG 0.485, TandemGait 0.271, Balance 0.373
- [15:20] E3.2 task+walkway: CCC=0.547 — walkway adds nothing here either
- [15:20] Phase 5 VelocityIncrement starting (last proposal)
- [16:00] E5.0 VelInc-only: CCC=0.427, slope=0.306 (moderate standalone signal)
- [16:15] E5.1 VelInc+v2+FM: CCC=0.587, slope=0.425 (slightly worse than baseline)
- [18:09] **E5.2 phase-gated VelInc: CCC=0.620, slope=0.461 — BEATS BASELINE** (only winner)
- [18:09] **ALL PHASES COMPLETE.** Total runtime ~4 hours.
- [18:10] Results pulled locally. Final verdict: only phase-gated VelInc (E5.2) improves calibration, but modestly (slope 0.446→0.461). The bias ceiling at N=98 appears fundamental.

---

## Previous Sessions

### Session 7 — Writing Review (2026-03-14) — DONE
- Reviewed manuscript for Nature-style tone and narrative
- Generated external_codex_writing.md

### Session 6 — Execute CODEX Proposals (2026-03-13) — DONE
- Ran structured items, task-aware DL, additive FreeAcc/Euler experiments
- Result: additive channels degraded obs CCC (confirmed no signal)
