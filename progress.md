## Session Log: CCC Definition Lookup (2026-03-26)

### 09:55 — Context + source check
- Read planning skill instructions and existing planning files
- Searched repo for `CCC`, `concordance`, and `Lin's`
- Located the canonical metric implementation in `eval_utils.py`

### 09:58 — Manuscript verification
- Read the CCC formula in `generate_paper.py`
- Read the introduction/results text explaining CCC as the metric that penalizes both correlation and calibration failure under prediction compression

### 10:00 — Artifact verification
- Loaded stored JSON outputs for baseline and SSL T1/T3 runs
- Confirmed headline values used in the answer: T1 baseline CCC=0.700, T1 SSL LOOCV CCC=0.868, T3 SSL LOOCV CCC=0.776

---

## Session Log: Paper Innovations + Result Impact (2026-03-26)

### 10:05 — Task setup
- Read planning skill instructions and checked for carry-over session context
- Read existing `task_plan.md`, `findings.md`, and `progress.md`
- Added a new planning section for the current question on the paper's main innovations and their empirical impact

### 10:15 — Manuscript + code alignment
- Located the manuscript contribution statement in `NEW.html` / `generate_paper.py`
- Verified target definitions and P5 method in `run_compression_ablation.py`
- Verified reviewer sensitivity implementations for HC ablation and 5-fold observability in `run_reviewer_experiments.py`

### 10:20 — Numeric verification
- Confirmed P0 vs P5 5-fold metrics from stored JSONs for T1/T2/T3
- Confirmed 5-fold observability table values and the T3 structural-ceiling numbers in `NEW.html`
- Confirmed age-confound and HC-ablation sensitivity numbers from `NEW.html` and reviewer JSON artifacts

### 10:25 — Synthesis ready
- Ranked the main innovations by scientific impact: ordinal ranking, observability framework, benchmark/sensitivity validation
- Prepared final answer with explicit manuscript-vs-code distinction on the role of HC anchors

---

## Session Log: Codebase Audit (2026-03-25)

### 00:00 — Task Setup
- Read planning skill instructions and session catchup
- Confirmed existing `task_plan.md`, `findings.md`, and `progress.md`
- Captured `git diff --stat` to understand active repo churn

### 00:05 — Inventory
- Enumerated repository files with `rg --files` and `find`
- Confirmed broad surface area: many standalone experiment runners, multiple paper generators, tests, HTML outputs, and planning/docs markdowns
- Began structured audit with docs/HTML first, code second

### 00:20 — Documentation Pass (partial)
- Read smaller Markdown files fully: `AGENTS.md`, `EXP.md`, `FIXES.md`, `LEARNINGS.md`, `literature_review.md`, `VNEXT.md`, `GPU.md`, `TOKEN.md`
- Read `README.md` first half and `autoresearch_program.md`
- Extracted heading maps for large docs plus `NEW.html` to guide deeper reading
- Key pattern: evaluation/provenance cleanup is the dominant organizing concern across the repo

### 00:40 — Documentation Pass (major docs)
- Read `CONT.md`, `README.md`, `CLAUDE.md`, `CODEX-PROPOSALS.md`, `PROPOSALS.md`, and review summaries
- Inspected the current manuscript output `NEW.html` and confirmed its main section structure and headline claims
- Main emerging issue: the repo contains multiple overlapping “current truth” documents and multiple candidate primary pipelines

### 01:05 — Code Pass
- Mapped all Python/shell/test files by size and top-level signatures
- Read the core shared modules: `project_paths.py`, `data_split.py`, `updrs_columns.py`
- Read the clean-path orchestration layer: `run_clean_benchmark.py`, `run_sensor_ablation.py`, `run_loocv_stack.py`, `run_stats_report.py`, `paper3_data.py`, `generate_html_paper3.py`, `gpu.sh`
- Read central legacy-but-still-imported builders: `run_ablation_v2.py`, `run_proven_stack.py`, `run_compression_ablation.py`, `run_pd_only_experiments.py`, `run_dl_experiments.py`, `run_dl_rebenchmark.py`

### 01:20 — Validation
- Ran `pytest -q tests`
- Result: `129 passed, 4 skipped in 18.53s`
- Confirms helper-layer invariants are guarded, but major experiment runners remain largely untested end-to-end

---

## Session Log: Reviewer Response (2026-03-24)

### 14:45 — Session Start
- Read all 11 reviewer comments, articulated each clearly
- Read PAPER.html structure (683 lines, 11 Results subsections, SM tables)
- Read key scripts: generate_paper.py, run_compression_ablation.py, gpu.sh

### 14:50 — External CLI Consultation
- Gemini: age confound sensitivity strategies (4 concrete analyses)
- Gemini: paper restructuring advice (5 main + 5 SM sections)
- Codex: 5-fold CV implementation for SSL pipeline (leakage rules, expected degradation)
- Gemini had 429 rate limit but delivered full responses before error

### 14:55 — Key Discovery: 5-fold SSL results already exist
- compression_P5_TT{1,2,3}_5split.json all present
- T3 5-fold CCC=0.807 BETTER than LOOCV CCC=0.776
- This eliminates the need for new experiments for C1/C5

### 15:00 — Results Inventory
- P0 baseline: 5-fold, all 3 targets ✓
- P5 SSL: 5-fold AND LOOCV, all 3 targets ✓
- Sensor ablation: lower_back_1, wrists_2 ✓ (missing single wrist)
- Confound analysis: partial_r=0.36, p=0.0003 ✓ (needs SSL-specific version)
- Per-subject predictions: saved in compression JSONs ✓

### 15:05 — Plan Created
- 6 phases (P0-P5), 3 new experiments needed
- Script: `run_reviewer_experiments.py` (consolidates C2, C3, C11)
- Waiting for user to provide GPU server credentials

### 15:15 — Phase 0 Complete: Experiment Script Written
- Created `run_reviewer_experiments.py` (730 lines)
  - `--age-sensitivity`: C2 — age-matched HC, partial correlation, age-stratified eval
  - `--hc-ablation`: C3 — P0 vs P5-no-HC vs P5-with-HC for T1 and T3
  - `--single-sensor`: C11 — R_Wrist_1, L_Wrist_1, LowerBack_1, wrists_2, all_13 with SSL
  - `--obs-5fold`: C1 — 3-level observability decomposition under 5-fold
- Syntax verified, shared imports confirmed working
- Reuses core functions from run_compression_ablation.py: feature_select, train_lgb, gen_split
- run_ssl_5fold() supports hc_sids_subset parameter for age-matching and HC ablation

### 15:30 — Phase 1: GPU Server Setup
- New server: root@212.93.107.107:41013 (RTX 3090 24GB, 126GB disk)
- PyTorch cu128 + requirements-gpu.txt installed via ./gpu.sh --setup
- WearGait-PD downloaded from Synapse (47GB total, all 178 subjects confirmed)
- rocket_recordings.npz regenerated (1405 recordings, 178 subjects)
- FM embeddings regenerated via MOMENT-1-base embed() (1405x768, 36s on GPU)
- Issue: momentfm 0.1.4 API changed — forward() → embed() for embedding extraction

### 16:30 — Phase 2: Running Experiments
- All 4 experiments launched in parallel
- HC ablation: completed in 4 min
- Obs 5-fold: completed in 8 min
- Single sensor: completed in 5 min
- Age sensitivity: completed in 3.5 min (after 2 bug fixes: np.isnan type, lstsq rcond)

### 17:10 — Phase 2 Complete: ALL RESULTS

**C2: Age Sensitivity** — AGE IS NOT DRIVING THE RESULTS
| Condition | T1 CCC | T1 MAE | T3 CCC | T3 MAE |
|-----------|--------|--------|--------|--------|
| Full HC (80) | 0.858 | 0.986 | 0.763 | 4.968 |
| Age-matched HC (46) | 0.868 | 0.978 | 0.751 | 4.998 |
Partial r (age only): 0.849 (p<1e-6)
Partial r (age+dx): 0.823 (p<1e-6)
Age strata: young CCC=0.730, middle=0.706, older=0.911

**C3: HC Ablation** — RANKING ITSELF HELPS, HC ADDS CALIBRATION
| Method | T1 CCC | T1 MAE | T3 CCC | T3 MAE |
|--------|--------|--------|--------|--------|
| P0 Baseline | 0.673 | 1.380 | 0.209 | 8.032 |
| P5 no HC | 0.857 | 1.013 | 0.789 | 4.591 |
| P5 with HC | 0.858 | 0.986 | 0.763 | 4.968 |

**C1: Obs 5-fold** — GRADIENT CONFIRMED UNDER UNIFIED EVAL
| Tier | SSL CCC | SSL MAE | Baseline CCC |
|------|---------|---------|--------------|
| Direct | 0.834 | 1.100 | 0.545 |
| Partial | 0.730 | 2.590 | 0.055 |
| Unobs | 0.759 | 2.097 | 0.176 |

**C11: Single Sensor** — SINGLE WRIST ACHIEVES CCC>0.78
| Config | CCC | MAE | r |
|--------|-----|-----|---|
| LowerBack (1) | 0.867 | 0.962 | 0.884 |
| R_Wrist (1) | 0.784 | 1.202 | 0.806 |
| L_Wrist (1) | 0.791 | 1.187 | 0.806 |
| All 13 | 0.857 | 1.001 | 0.873 |

### 17:20 — Phase 4 Start: Paper Rewrite
- Added 4 new fields to PaperData + load_all_data (reviewer JSONs)
- Added 4 new table functions: _table_age_sensitivity, _table_hc_ablation, _table_obs_5fold, _table_single_sensor
- Launched subagent to write complete build_html_v2 function (restructured Results, 5-fold primary)
- Will do 3 rounds of codex+gemini review after paper generation

---

## Archived: Previous Sessions
(See git history for figure review, writing review, and verification audit sessions)
