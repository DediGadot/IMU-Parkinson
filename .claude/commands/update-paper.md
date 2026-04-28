---
description: Generate or update the academic paper targeting Nature journals. Asks whether to start from scratch or update the existing manuscript. Reads memory files and all experiment results, generates publication-quality figures with deep statistical analysis, writes self-contained HTML manuscript, and runs 3 peer-review improvement cycles. ALWAYS use this skill when the user asks to update the paper, regenerate the paper, improve the paper, work on the manuscript, prepare for submission, or mentions the paper in any context requiring manuscript work. This is the primary paper generation pipeline — use it proactively even if the user just says something like "paper" or "let's work on the write-up".
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob, Agent, AskUserQuestion]
---

# Update Paper — Subagent-Orchestrated Manuscript Generator

You are the ORCHESTRATOR. You do NOT do the heavy lifting yourself. You spawn focused subagents for each phase, collect their outputs, and chain them together. This prevents token exhaustion.

The paper's core contributions:
1. **First published UPDRS-III regression on WearGait-PD** — novel benchmark on the largest controlled-gait PD dataset (N=178, 13 IMUs) with full clinical scores.
2. **Three-stage pipeline: ordinal ranking + LightGBM + temperature scaling** — ordinal ranking (XGBRanker leaf features) is the core innovation (NOT HC anchoring — ΔCCC=0.001). Temperature scaling T=1.4 is an INTEGRAL part of the pipeline (not post-hoc), fixing calibration slope to 0.967. The full pipeline achieves CCC=0.882, slope=0.967 on T1.
3. **Two-level observability decomposition** — direct observable (CCC=0.865) >> rest (CCC=0.730-0.759). The ordering test is NS (p=0.69) — present as two-level, NOT monotonic three-level.
4. **Sensor reduction feasibility** — 22 configs × 3 targets, 10×5-fold repeated CV, Nadeau-Bengio corrected: 5-sensor non-inferior across all targets, 4-sensor extremity SUPERIOR for total UPDRS (ΔCCC=+0.030, p=0.006).

**CRITICAL: Temperature scaling is PART OF THE PIPELINE, not a post-hoc add-on.** Per-target temperature tuning achieves slope≈1.0 for all targets. However, primary 5-fold results report Stages 1-2 (without temperature) for clean cross-target comparison. Per-target calibrated results are reported under LOOCV in a supplementary table.

**Per-target temperature (LOOCV, canonical):**
- T1: T=1.45, CCC 0.868→0.893, slope→1.000, MAE 0.986→1.091
- T2: T=1.45, CCC 0.852→0.863, slope→1.014, MAE 1.334→1.717
- T3: T=1.75, CCC 0.776→0.811, slope→1.008, MAE 4.646→5.579
- Monotonicity: 0.893 > 0.863 > 0.811 (HOLDS under LOOCV)

**Why per-target not single T:** Targets have different compression levels (T1 slope=0.69, T3 slope=0.58). A single T either under-corrects T3 or over-corrects T1. Per-target tuning is the correct approach.

**Why Stages 1-2 as primary 5-fold:** Per-target temperature on 5-fold breaks CCC monotonicity (T3=0.871 > T1=0.869) because T3 benefits disproportionately from strong stretching. Stages 1-2 provides clean, comparable cross-target results. Temperature results are canonical under LOOCV where monotonicity holds.

**Source:** `results/temperature_per_target.json`

**Manuscript file: `/home/fiod/medical/NEW.html`** — this is the authoritative manuscript. Always read and edit this file.

## ORCHESTRATION PLAN

Execute these steps in order. Use the Agent tool for each subagent. Each subagent writes its output to a temp file that the next subagent reads.

---

## Step -1: Choose Mode — Scratch or Update

**This step is MANDATORY. Do it FIRST before anything else.**

Use AskUserQuestion to ask the user:

> **Paper generation mode:**
>
> **A) From Scratch** — Full regeneration. Rebuilds narrative alignment, data collection, generate_paper.py script, and all review cycles from zero. Use when the paper structure needs fundamental changes, the narrative framing is wrong, or major new experiment categories have been added.
>
> **B) Update Existing** — Incremental update. Reads the current NEW.html, diffs it against the latest results from findings.md and memory files, identifies stale/missing/incorrect content, and surgically fixes it. Preserves working prose and structure. Use when you have new experiment results, corrected numbers, or incremental improvements to incorporate.
>
> Which mode?

Based on the user's choice:
- **If A (Scratch):** Proceed to Step 0 (full pipeline below).
- **If B (Update):** Jump to the UPDATE PATH section at the bottom of this document.

---

## Step 0: Align on Paper Narrative (BEFORE any generation) — SCRATCH MODE ONLY

Before launching any subagents or writing any code, you must align with the user on the paper's key takeaways and narrative framing. This step is MANDATORY — do not skip it.

### 0A: Quick Data Scan

Read these files yourself (lightweight — no subagents needed):
- `/home/fiod/.claude/projects/-home-fiod-medical/memory/MEMORY.md` — current best results, key learnings
- `/home/fiod/medical/CLAUDE.md` — SOTA landscape, current results section
- `/home/fiod/medical/findings.md` — experimental findings (if exists)

Extract: the top 3-5 reportable results with exact numbers (MAE, CCC, slope, r, p-values).

### 0B: Present Narrative Alternatives

Using the data you just read, present **2-3 alternative narrative framings** to the user via AskUserQuestion. Each framing should propose:
- **Lead takeaway** — the single headline finding that opens the abstract
- **Core insight** — the conceptual contribution (what changes how people think)
- **Supporting evidence hierarchy** — which results go in what order
- **Tone/positioning** — how aggressive vs conservative the claims are

Example framings (adapt based on actual current results):

**Framing A: "SSL Ranking Breakthrough"** — Lead with the methodological innovation: semi-supervised ranking from healthy controls as calibration anchors solves the prediction compression problem. HC subjects (N=80) provide "known-zero" calibration, boosting direct-observable CCC from 0.59 to 0.87 with LOOCV validation. The observability decomposition explains why this works for observable items but residual error remains for unobservable items. Positions as ML methods + clinical insight.

**Framing B: "Observability Ceiling + SSL Solution"** — Lead with the insight that gait IMU has a fundamental ceiling for total UPDRS-III because many items are unobservable from gait. Then show SSL ranking as the path to reaching the ceiling for observable items. The observable subdomain achieves MAE=0.99, well below MCID (3.25). Reframes "modest total MAE" as a physics constraint, not a methods failure. More clinically grounded.

**Framing C: "First Benchmark + Clinical Roadmap"** — Lead with novelty: first UPDRS-III regression on WearGait-PD, 7x more subjects than prior work. Present the observability decomposition as a roadmap for what wearable sensors can and cannot assess. SSL ranking is one technique that proves the observable subscore is clinically actionable. More conservative, broader appeal.

Use AskUserQuestion with these framings as options. Include a description for each that summarizes the lead takeaway, what goes in the abstract, and what the Discussion emphasizes.

### 0C: Confirm Key Takeaways

After the user picks a framing direction, use AskUserQuestion one more time to confirm the **specific claims and numbers** that will anchor the paper. Present a bulleted list of 4-6 key claims (each with the exact number) and ask the user to confirm or adjust. Example:

1. "Full pipeline (ranking + LGB + temp scaling T=1.4) achieves CCC=0.882, slope=0.967, MAE=1.162 on T1 (LOOCV). Without temp: CCC=0.868, slope=0.689"
2. "3-level observability gradient: direct CCC=0.56, partial CCC=0.12, unobs CCC=0.18 (baseline)"
3. "SSL boosts all 3 targets: T1 CCC 0.59→0.87, T2 0.56→0.85, T3 0.37→0.78"
4. "5-sensor minimal_5 is NON-INFERIOR across all 3 targets (10×5-fold, Nadeau-Bengio, p<0.003)"
5. "4-sensor wrists_ankles_4 is SUPERIOR to 13-sensor for T3 total UPDRS (ΔCCC=+0.030, p=0.006)"
6. "Single lumbar sensor NON-INFERIOR for T1/T2 but FAILS for T3 (ΔCCC=-0.039)"
7. "FM embeddings are target-specific: useless alone but +0.058 CCC for wrists_ankles_4 on T3"
8. "FM embeddings beat handcrafted features (MAE 8.49→7.78, p=0.004)"
9. etc.

### 0D: Save Alignment

Write the agreed narrative framing and confirmed claims to `/home/fiod/medical/.paper_build/narrative_alignment.md`. This file is read by ALL downstream subagents to ensure consistency.

Only proceed to Step 1 after the user has confirmed both the narrative framing AND the key claims.

---

## Step 1: Data Collection (3 PARALLEL subagents)

Launch ALL THREE subagents simultaneously in a single message using the Agent tool. They write their outputs to `/home/fiod/medical/.paper_build/`.

First, create the output directory:
```bash
mkdir -p /home/fiod/medical/.paper_build
```

### Subagent 1A: Memory & Context Collector

```
Agent(description="Collect paper context data",
      prompt=<see SUBAGENT_1A below>,
      mode="bypassPermissions")
```

**SUBAGENT_1A prompt:**
> You are a data collector for an academic paper generator. Your job is to read context files and produce a structured summary.
>
> Read these files:
> 1. `/home/fiod/.claude/projects/-home-fiod-medical/memory/MEMORY.md` — then read every file it links to
> 2. `/home/fiod/medical/CLAUDE.md` — SOTA landscape, dataset specs, rules
> 3. `/home/fiod/medical/findings.md` — experimental findings
> 4. `/home/fiod/medical/literature_review.md` — related work (if exists)
> 5. `/home/fiod/medical/autoresearch_results.tsv` — MAE autoresearch log
> 6. `/home/fiod/medical/autoresearch_ccc_results.tsv` — CCC autoresearch log
>
> Write a structured summary to `/home/fiod/medical/.paper_build/context_summary.md` containing:
> - Current best results for ALL 3 targets (T1 items 9-14, T2 items 7-14, T3 total UPDRS):
>   - Both BASELINE and SSL (P5) results with CCC, slope, MAE, r
>   - Evaluation protocol for each (LOOCV vs 5-split — NEVER mix)
> - SOTA comparison table (Hssayeni MAE=5.95 r=0.79, Shuqair r=0.89 MAE~5.65, disqualified papers with reasons)
> - Dataset specs (N=178: 98 PD + 80 HC, 13 IMUs at 100Hz, tasks, channels)
> - Key technical learnings (what worked, what failed)
> - 3-level observability results (direct/partial/unobs CCC and MAE) — from BASELINE model, NOT SSL
> - SSL ranking mechanism (HC as calibration anchors, XGBRanker → leaf features → LGB)
> - Quartile bias analysis (Q1-Q4 before/after SSL)
> - PD-only vs mixed results (demographics baseline competitive on total UPDRS)
> - Critical rules for the paper (from CLAUDE.md)
> - Literature citations needed
> - Compression problem explanation — why CCC matters more than MAE
>
> **CRITICAL**: For every metric, record the evaluation protocol (LOOCV vs 5-split vs 10-split vs held-out), the N, and the source file. NEVER present metrics from different protocols as if they are directly comparable.
>
> Be exhaustive with numbers — the script writer needs exact values. Do NOT summarize loosely.

### Subagent 1B: Result Artifact Collector

```
Agent(description="Extract result artifacts",
      prompt=<see SUBAGENT_1B below>,
      mode="bypassPermissions")
```

**SUBAGENT_1B prompt:**
> You are a data collector for an academic paper generator. Your job is to read all experiment result JSON files and produce a structured summary of every reportable metric.
>
> First, run: `ls -la /home/fiod/medical/results/*.json` to see all available result files (expect ~88 files).
>
> Then read the KEY result files (prioritized — read these first):
>
> **SSL / Compression ablation (PRIMARY — the paper's lead results):**
> - `compression_P5_TT1.json` — P5 SSL LOOCV on T1 (direct observable, items 9-14) ← HEADLINE RESULT
> - `compression_P5_TT2.json` — P5 SSL LOOCV on T2 (broad observable, items 7-14)
> - `compression_P5_TT3.json` — P5 SSL LOOCV on T3 (total UPDRS-III)
> - `compression_P0_TT1.json` — P0 baseline on T1 (NOTE: 5-split, NOT LOOCV)
> - `compression_P0_TT2.json` — P0 baseline on T2 (5-split)
> - `compression_P0_TT3.json` — P0 baseline on T3 (5-split)
> - `compression_P1_TT1.json` — P1 ordinal (failed)
> - `compression_P3_TT*.json` — P3 SMOGN (modest)
> - `compression_P4_TT*.json` — P4 NGBoost (competitive but no improvement)
> - `compression_ablation_all.json` — summary (NOTE: may have stale 5-split numbers; prefer individual P5 files)
>
> **PD-only experiments (7 phases):**
> - `pd_only_experiments.json` — main PD-only results
> - `pd_only_phase1.json` through `pd_only_phase7.json` — per-phase
>
> **FM / ROCKET ablation:**
> - `rocket_phase0.json` through `rocket_phase9_fm_observable.json`
> - `rocket_loocv.json`, `rocket_loocv_results.json`
> - `rocket_ablation_results.json`
>
> **Calibration ablation:**
> - `calibration_ablation_phase*.json` — total UPDRS calibration
> - `calibration_obs_ablation_phase*.json` — observable subscore calibration
>
> **Other key files:**
> - `clean_benchmark_results.json` — held-out test (contamination-audited)
> - `paper3_split.json` — split definition
> - `sensor_ablation_results.json` — old sensor reduction study (v2 features only, superseded)
> - `sensor_span_*_5split.json` — **NEW: 22-config sensor span screening under SSL ranking (5-fold)**
> - `sensor_span_repeated_cv.json` — **NEW: 10×5-fold repeated CV for 4 key configs with Nadeau-Bengio corrected non-inferiority tests**
> - `sensor_span_k_sweep.json` — **NEW: K sweep confound test (4 configs × 5 K values × 3 targets)**
> - `sensor_span_fm_decomposition.json` — **NEW: v2-only vs FM-only vs combined (4 configs × 2 targets)**
> - `dl_experiment_results.json` — DL comparison (5 architectures)
> - `stats_report.json` — bootstrap CIs, permutation tests
> - `paper_supplements.json` — supplementary tables
> - `obs_bias_ablation_phase*.json` — walkway/task/VelInc ablation
> - `subdomain_v3_results.json` — subdomain decomposition
> - `hp_sensitivity_results.json` — HP sensitivity
> - `followup_v3_results.json` — 10-split validation
>
> Also catalog `/home/fiod/medical/figures/` — list what figure files exist.
>
> Write output to `/home/fiod/medical/.paper_build/results_summary.md` containing:
> - For EACH result file: filename, what it contains, key metrics extracted, **evaluation protocol**, **N**
> - ALL per-model results: MAE, CCC, slope, r, p-values, per-split arrays
> - SSL P5 results for all 3 targets with LOOCV per-subject predictions
> - Compression ablation comparison (5 proposals × 3 targets)
> - Quartile bias arrays (Q1-Q4 mean bias, before/after SSL)
> - Bootstrap CIs for primary results
> - 3-level observability decomposition numbers (from baseline, NOT SSL)
> - Sensor ablation comparison table
> - DL experiment results (architectures and why they failed)
> - Demographics if available in any result file
> - Per-subject predictions arrays (for scatter plots)
> - Available figure files listed
>
> **CRITICAL**: For every metric, tag it with its evaluation protocol and N. The paper must never present LOOCV and 5-split results as if they are directly comparable without noting the difference.
>
> Extract EXACT numbers — no rounding, no approximation. Include raw arrays where they exist.

### Subagent 1C: Source Code Collector

```
Agent(description="Extract code parameters",
      prompt=<see SUBAGENT_1C below>,
      mode="bypassPermissions")
```

**SUBAGENT_1C prompt:**
> You are a data collector for an academic paper generator. Your job is to read source code files and extract exact hyperparameters, pipeline steps, and method details for the Methods section.
>
> Read these files and extract exact parameters:
> 1. `data_split.py` — windowing params (window size, stride, overlap), channel selection, split logic, clinical data parsing, z-normalization details
> 2. `run_rocket_ablation.py` — FM embedding extraction (MOMENT model name, embedding dim, truncation length), LightGBM hyperparameters (ALL of them), XGBoost hyperparameters, feature selection method and K values, stacking architecture, seed values
> 3. `run_compression_ablation.py` — **SSL ranking pipeline**: XGBRanker hyperparameters, leaf feature extraction, 2-stage architecture (Stage 1: XGBRanker on ALL subjects N=178, Stage 2: LGB on PD-only with leaf features), target definitions (T1/T2/T3), LOOCV implementation, quartile bias computation
> 4. `run_clean_benchmark.py` — evaluation protocol, primary model specification
> 5. `run_stats_report.py` — bootstrap N, permutation test N, CI method (BCa vs percentile)
> 6. `updrs_columns.py` — exact UPDRS item definitions, 3-level observable/partial/unobs classification
> 7. `project_paths.py` — artifact paths
> 8. `run_pd_only_experiments.py` — PD-only evaluation protocol, LOOCV details, 7-phase structure
> 9. `run_calibration_ablation.py` — residual modeling approach, calibration methods tried
> 10. `autoresearch_config.py` — current best HP config (K, leaf size, reg_lambda, colsample, etc.)
> 11. `autoresearch_ccc_eval.py` — CCC evaluation harness, feature group definitions
> 12. `cache_extra_features.py` — VelInc, VelInc-gated, walkway feature caching
>
> Write output to `/home/fiod/medical/.paper_build/methods_summary.md` containing:
> - **Baseline pipeline** LightGBM hyperparameters (learning_rate, n_estimators, max_depth, num_leaves, subsample, colsample_bytree, reg_alpha, reg_lambda, min_child_samples, etc.)
> - **CCC-optimized** hyperparameters from autoresearch (K=500, min_leaf=8, reg_lambda=0.3, colsample=0.5 — verify from code)
> - **SSL ranking pipeline**: XGBRanker params (n_estimators, max_depth, learning_rate, objective), leaf feature dimensionality, how leaf indices are extracted, how ranking labels are constructed from HC+PD
> - EXACT XGBoost hyperparameters if used in stacking
> - Feature extraction: window size in seconds, stride, overlap percentage
> - MOMENT model: exact model name string, embedding dimension, input truncation
> - Feature selection: method (XGBoost importance), K values tested, K selected per pipeline
> - Split strategy: seed, dev/test sizes, stratification method
> - Bootstrap: N iterations, CI method
> - Permutation test: N iterations
> - UPDRS item list with 3-level classification (direct observable 9-14, partially observable 5-8+15-17, not observable 1-4+18)
> - Multi-seed ensemble: how many seeds, how predictions are averaged
> - Early stopping: patience, metric
> - Any preprocessing: normalization, missing data handling, channel selection
> - T1/T2/T3 target definitions (exact item lists for each)
>
> Be EXACT — copy numbers directly from the code. No approximations.

---

## Step 2: Write generate_paper.py (1 subagent)

Wait for all 3 Step 1 subagents to complete. Then launch this subagent.

```
Agent(description="Write paper generation script",
      prompt=<see SUBAGENT_2 below>,
      mode="bypassPermissions")
```

**SUBAGENT_2 prompt:**
> You are a scientific paper script writer. Your job is to write `/home/fiod/medical/generate_paper.py` — a single, self-contained Python script that generates a complete Nature-quality HTML manuscript.
>
> First, read these data files that were collected for you:
> - `/home/fiod/medical/.paper_build/narrative_alignment.md` — **READ FIRST** — user-approved narrative framing, lead takeaway, claim hierarchy, and tone. The ENTIRE paper must be structured around this agreed direction.
> - `/home/fiod/medical/.paper_build/context_summary.md` — SOTA, dataset, learnings, rules
> - `/home/fiod/medical/.paper_build/results_summary.md` — all metrics and per-subject predictions
> - `/home/fiod/medical/.paper_build/methods_summary.md` — exact hyperparameters and pipeline
>
> Also check if a previous version exists: `/home/fiod/medical/generate_paper.py` — if it does, read it and reuse working code blocks (figure generation, HTML template structure, statistical computations).
>
> Write the script at `/home/fiod/medical/generate_paper.py`. It must:
>
> 1. **Load all result artifacts** from `results/` directory (JSON files)
> 2. **Recompute and verify** every reported metric from per-subject predictions
> 3. **Generate all main figures** (matplotlib, Agg backend, 300 DPI, base64-encoded PNG):
>    - **Fig 1**: Study Design & Pipeline schematic — show the 2-stage SSL architecture: 13 IMU sensors → tasks → features (v2+FM) → Stage 1: XGBRanker (ALL N=178 subjects, HC as anchors) → leaf features → Stage 2: LGB regressor (PD-only) → UPDRS subscore
>    - **Fig 2**: SSL scatter plot — predicted vs actual for T1 (direct observable, LOOCV), PD subjects colored by severity quartile, identity line, MCID band, marginal histograms, CCC/slope/MAE text box
>    - **Fig 3**: Three-target SSL comparison — 3-panel scatter (T1/T2/T3 side by side, same axis scales), showing CCC degradation from direct → broad → total
>    - **Fig 4**: Three-level observability decomposition — grouped bar chart or heatmap: direct/partial/unobs × CCC/slope/MAE (baseline model, NOT SSL)
>    - **Fig 5**: Item-level predictability — lollipop chart (per-item CCC or r, colored by 3-level observability tier, sorted within tier)
>    - **Fig 6**: Feature importance — top 20 features by SHAP or XGB importance, color by category (v2 handcrafted, FM embedding, demographic)
>    - **Fig 7**: Compression ablation comparison — 5 proposals × T1 CCC as grouped bar chart or dot plot (P0 baseline, P1 ordinal, P3 SMOGN, P4 NGBoost, P5 SSL)
>    - **Fig 8**: Quartile bias reduction — paired bar chart: Q1-Q4 bias before (baseline) and after (SSL), showing Q4 underprediction cut by 61%
>    - **Fig 9**: Foundation Model impact — paired comparison across 10 splits (v2 vs v2+FM), showing FM drops total UPDRS MAE from 8.49→7.78
>    - **Fig 10**: Cross-dataset forest plot — our CCC/MAE vs Hssayeni (MAE=5.95, r=0.79), Shuqair (r=0.89, MAE~5.65), with N and eval protocol annotations
>    - **Fig 11**: Sensor reduction — 22 configs × CCC for T1/T2/T3 (Pareto frontier: CCC vs sensor count, 3 targets overlaid), from `sensor_span_*_5split.json`
>    - **Fig 12**: Sensor non-inferiority forest plot — ΔCCC with 95% CI for 3 key configs vs all_13 per target, from `sensor_span_repeated_cv.json` (10×5-fold). Non-inferiority margin δ=0.05 shown as shaded region
>    - **Fig 13**: FM decomposition — grouped bars showing v2-only vs FM-only vs combined CCC for 4 key configs × T1/T3, from `sensor_span_fm_decomposition.json`. Highlights FM=useless alone but +0.058 for wrists_ankles_4 T3
> 4. **Generate appendix figures** (Section 5: The ML Pipeline — educational):
>    - **Fig A**: Decision tree ensemble diagram
>    - **Fig B**: MSE vs MAE loss comparison
>    - **Fig C**: Feature selection / column subsampling visualization
>    - **Fig D**: Multi-seed ensemble averaging
>    - **Fig E**: Foundation model embedding extraction (MOMENT architecture)
>    - **Fig F**: Hyperparameter interaction heatmap
> 5. **Compute all statistics**: BCa bootstrap CIs (N=10000), permutation tests, Cohen's d, Bland-Altman, Lin's CCC with CIs
> 6. **Build all tables** as HTML:
>    - **Table 1**: Cohort demographics (PD vs HC: N, age, sex, H&Y, disease duration, UPDRS-III range)
>    - **Table 2**: Total UPDRS-III prediction (PD-only eval, multiple models: baseline, FM stack, SSL)
>    - **Table 3**: Three-level observability decomposition (baseline: direct/partial/unobs × CCC/slope/MAE/r)
>    - **Table 4**: Severity-stratified prediction (per-quartile MAE and bias, PD-only FM LOOCV)
>    - **Table 5**: Sensor ablation (total UPDRS, PD-only 10-split, FM re-extracted per config)
>    - **Table 6**: Cross-dataset SOTA comparison (our results vs Hssayeni, Shuqair, with N, eval protocol, dataset)
>    - **Table 7**: SSL ranking results — 5 proposals × 3 targets (CCC/slope/MAE), with eval protocol column (P0=5-split, P5=LOOCV, clearly labeled)
>    - **Table 8**: Quartile bias analysis (Q1-Q4 bias before/after SSL for T1 LOOCV)
>    - **Table P1**: Hyperparameter specification (all pipelines: mixed-cohort baseline, PD-only, SSL ranking)
>    - **Table S1**: Deep learning comparison (5 architectures, all MAE > 10)
>    - **Table S2**: Holm-Bonferroni corrected p-values
> 7. **Assemble complete HTML** manuscript in Nature Article format with:
>    - Self-contained CSS (Georgia body, Helvetica Neue headings, 11pt, 1.6 line height, print-ready)
>    - All figures as base64 data URIs
>    - Sections: Title, Abstract (<=300 words), Introduction (<=800 words), Results (<=2000 words), Discussion (<=1500 words), Methods (<=2500 words), References, Appendix (Section 5: ML Pipeline), Supplementary Information
>    - All tables inline at appropriate locations
>    - Colorblind-safe palette (viridis/cividis families), all text >=8pt
> 8. **Validate**: no placeholder text, sequential fig/table numbering, all numbers verified
> 9. **Save** to `/home/fiod/medical/NEW.html`
>
> ### Manuscript Content Guidelines
>
> **Core narrative**: Follow the user-approved framing from `narrative_alignment.md`. The paper must present ALL of these contributions:
> 1. First UPDRS-III regression on WearGait-PD (N=178, 13 IMUs, controlled gait)
> 2. SSL ranking from healthy controls — the breakthrough (CCC 0.59→0.87 on direct observable)
> 3. Three-level observability decomposition — what gait IMU can vs cannot predict
> 4. Foundation model embeddings (MOMENT) beat handcrafted features
>
> **Abstract** (<=300 words): Context → WearGait-PD novelty → Observability insight → SSL ranking breakthrough (key CCC/slope numbers with CIs) → Clinical utility of observable subscore → Implications
>
> **Introduction** (<=800 words): PD assessment burden → wearable IMU opportunity → prior work (Hssayeni MAE=5.95 N=24, Shuqair r=0.89 N=24, disqualified: IS22 leakage, He 2024 levodopa not UPDRS) → WearGait-PD description → observability problem → our contribution (SSL ranking, 3-level decomposition, FM impact)
>
> **Results** (<=2500 words): Cohort demographics → **Full pipeline headline** (3-stage: ranking + LGB + temperature T=1.4 achieves CCC=0.882, slope=0.967, MAE=1.162 on T1 LOOCV — these are the PRIMARY reported numbers) → Two-level observability decomposition (baseline, NOT SSL: direct >> rest, ordering test NS p=0.69) → Item-level analysis → Feature importance → Total UPDRS as context (demographics competitive) → FM impact → **Sensor reduction** (22 configs × 3 targets, 10×5-fold repeated CV: minimal_5 non-inferior, wrists_ankles_4 SUPERIOR T3 p=0.006) → **FM decomposition** (FM useless alone CCC≈-0.01, only helps wrists_ankles_4×T3 +0.058) → Cross-dataset context → Calibration ablation (7 methods tested, temperature wins; isotonic/Platt/CCC-loss/Ridge failed) → Negative results (DL, ordinal, pairwise — evidence for ceiling)
>
> **Temperature scaling approach:** Primary 5-fold results use Stages 1-2 (no temperature) for clean cross-target comparison: T1 CCC=0.865, T2 CCC=0.831, T3 CCC=0.807 (monotonic). Per-target temperature scaling is reported in LOOCV supplementary table: T1 CCC=0.893, T2 CCC=0.863, T3 CCC=0.811 (monotonic, slope≈1.0 for all). Temperature is Stage 3 of the pipeline but applied per-target with T tuned on LOOCV. Source: `results/temperature_per_target.json`
>
> **Discussion** (<=1800 words): Summary → **Three-stage pipeline mechanism** (ordinal ranking is the core — NOT HC anchoring (ΔCCC=0.001); temperature scaling as integral Stage 3 fixing ensemble compression; the full pipeline achieves near-perfect calibration slope=0.967) → Observable subscore as clinical endpoint → Two-level observability ceiling (physics not statistics) → **Sensor reduction for deployment** (minimal_5 non-inferior; wrists_ankles_4 SUPERIOR T3; practical guidance) → **FM as target-specific representation** (useless alone, +0.058 for wrists_ankles_4×T3 only) → Comparison with prior art (7x subjects, held-out vs LOOCV, CCC not just r) → **Why temperature scaling works and prior calibration failed** (ensemble averaging compresses; T is a single scalar counteracting that specific mechanism; isotonic/Platt failed because they lack the variance to stretch) → Limitations (single dataset, T tuned on LOOCV may need recalibration, sensor confounds) → Future work
>
> **Methods** (<=2500 words): Dataset (WearGait-PD, 178 subjects, 13 IMUs, 100Hz, controlled gait tasks) → Preprocessing (windowing, channel selection) → Feature extraction (v2 handcrafted + MOMENT FM) → Feature selection (XGB importance, K values per pipeline) → Baseline model training (EXACT hyperparams from methods_summary) → SSL ranking pipeline (Stage 1: XGBRanker on N=178, Stage 2: LGB on PD-only with leaf features, EXACT params) → Target definitions (T1 items 9-14, T2 items 7-14, T3 total) → Evaluation protocol (LOOCV for SSL, 5-split for baseline, explain why different) → 3-level observability classification (justify with clinical literature) → Statistical analysis (CCC, bootstrap CIs, permutation tests) → Code/data availability
>
> **Section 5: The ML Pipeline** (Appendix — educational, ~2000 words): Self-contained explanation of GBDT theory, MSE vs MAE loss, feature selection, multi-seed ensemble, FM embedding extraction, hyperparameter choices. Include Figs A-F. This section helps clinical readers understand the ML methodology without needing external references.
>
> **Supplementary Information**: Table S1 (DL comparison), Table S2 (Holm-Bonferroni p-values), any additional supplementary figures or analyses.
>
> **References**: Nature numbered format. Include: WearGait-PD paper, MDS-UPDRS guidelines, MCID (Horvath 2015: -3.25 improvement, +4.63 worsening), LightGBM, XGBoost, MOMENT, Hssayeni 2021, Shuqair 2024, Lin's CCC (Lin 1989), TRIP 2025 (classification only)
>
> ### Critical Rules
> - NEVER fabricate numbers — use exact values from the summary files
> - NEVER hallucinate hyperparameters — use exact values from methods_summary
> - NEVER mix evaluation protocols — P0 baseline (5-split) and P5 SSL (LOOCV) must be clearly labeled in every table/figure/text reference
> - NEVER present the observability gradient using SSL direct-obs alongside baseline partial/unobs — they are different models/protocols
> - Use CCC and slope as PRIMARY metrics for observable subscores; MAE secondary
> - Use hedging ("suggests", "indicates") for interpretive claims
> - Use definitive ("achieves", "demonstrates") only for direct measurements
> - Include 95% CIs with all point estimates where available
> - Report PD-only metrics alongside overall throughout
> - Acknowledge medication state, H&Y distribution, controlled vs free-living
> - Feature selection inside CV folds
> - Subject-level metrics only (never window-level)
> - If a metric cannot be verified, flag it with a FIXME comment
>
> ### Generation Script Integrity Rules (for `generate_paper.py`)
> These prevent hardcoded-value bugs that cause text-table-figure inconsistencies:
> - **G1: ZERO hardcoded results** — every number from experiment JSONs must use `d.xxx.get("metric")`, never literal values. This includes table footnotes, cross-dataset rows, inline demographics, figure annotation boxes, and pipeline schematic labels.
> - **G2: One data source per context** — all rows in a table, all bars in a figure, and all numbers in a paragraph must come from the same analysis pipeline. If mixing is unavoidable, add a footnote explaining the source difference.
> - **G3: Figure annotations match their data source** — if a figure function selects `d.ssl_5split_t1 if d.ssl_5split_t1 else d.ssl_t1`, the protocol label in the stats box must branch the same way (not hardcoded "LOOCV").
> - **G4: No fabricated figure data** — any synthetic/illustrative data must be labeled "Illustrative" in figure title AND HTML caption.
> - **G5: Fallback defaults current** — every `.get("metric", fallback)` default must match the most recent JSON value.

---

## Step 3: Run the Script

After Subagent 2 completes, run:
```bash
cd /home/fiod/medical && uv run python generate_paper.py
```

If it fails, fix the script yourself (you're the orchestrator, small fixes are fine) and rerun. No fallbacks.

---

## Step 3.5: External LLM Writing Panel (2 PARALLEL bash commands)

After the HTML is generated, get independent writing feedback from codex and gemini. Run BOTH in parallel (two Bash tool calls in a single message). They review the prose, narrative, and academic tone — things where diverse LLM perspectives improve quality.

First, extract plain text from the HTML for the prompts:
```bash
cd /home/fiod/medical && python3 -c "
import re, html
with open('NEW.html') as f: raw = f.read()
text = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL)
text = re.sub(r'<[^>]+>', ' ', text)
text = html.unescape(text)
text = re.sub(r'\s+', ' ', text).strip()
with open('.paper_build/paper_text.txt', 'w') as f: f.write(text[:60000])
"
```

Then run both reviewers in parallel:

**Codex — Academic Writing Review:**
```bash
cd /home/fiod/medical && codex exec -m gpt-5.4 -c model_reasoning_effort="xhigh" --full-auto "You are reviewing an academic paper targeting Nature Digital Medicine. Read .paper_build/paper_text.txt which contains the extracted text. Evaluate: (1) Academic writing quality — is the tone appropriate for Nature? Flag any informal language, hedging failures, or overclaiming. (2) Narrative flow — does the story build logically? Is the SSL ranking breakthrough presented compellingly alongside the observability ceiling insight? (3) Abstract quality — does it stand alone? Does a reader understand the SSL mechanism and 3-level decomposition from the abstract alone? (4) Discussion depth — does it go beyond restating results? Does it explain WHY SSL ranking from HC works (calibration anchors, N amplification)? (5) CCC vs MAE framing — is CCC properly motivated as a better metric for regression calibration? (6) Specific prose improvements — quote the original sentence, provide your rewrite. Focus on the 10 highest-impact improvements. Write your review to .paper_build/external_codex_writing.md" > /dev/null 2>&1
```

**Gemini — Scientific Narrative Review:**
```bash
cd /home/fiod/medical && gemini -m gemini-3.1-pro-preview -y "You are a senior neuroscience researcher reviewing a paper on predicting Parkinson's disease motor severity from wearable IMU sensors. Read .paper_build/paper_text.txt. Evaluate: (1) Clinical framing — would a neurologist find the SSL ranking mechanism compelling and the observable subscore clinically actionable? (2) Related work fairness — are comparisons with prior work (Hssayeni MAE=5.95, Shuqair r=0.89) presented honestly with protocol caveats (LOOCV N=24 vs our protocol)? (3) Limitations honesty — are the key limitations (single dataset, controlled tasks, no longitudinal, P0 baseline is 5-split not LOOCV, observability classification is our own) adequately addressed? (4) SSL mechanism — is the explanation of HC as calibration anchors convincing? Would a reviewer accept this as a genuine methodological contribution? (5) Protocol mixing — are there any places where LOOCV and 5-split results are presented as directly comparable without caveat? (6) Specific suggestions for strengthening clinical relevance. Write your review to .paper_build/external_gemini_writing.md" > /dev/null 2>&1
```

Both commands write to `.paper_build/`. If either fails (CLI not available, timeout), retry ONCE. If it fails again, STOP and report the failure to the user — do not proceed without external feedback.

---

## Step 4: Peer Review Cycles (3 SEQUENTIAL subagents + external visual pass)

After the HTML is generated and external writing feedback is collected, run 3 review subagents. Each one reads the current HTML, makes targeted improvements, and logs its review. They MUST run sequentially — each builds on the previous.

### Review Scoring Dimensions (shared across all 3 cycles)

| Dimension | Weight | Focus |
|-----------|--------|-------|
| Scientific Rigor | 25% | Claims supported? Stats correct? No leakage? CIs reported? Protocol mixing caught? |
| Novelty & Significance | 15% | Clear contribution? SSL mechanism compelling? Observability insight advances field? |
| Methods Reproducibility | 15% | Exact hyperparameters? Both pipelines (baseline + SSL) described fully? |
| Results Clarity | 15% | Tables/figures clear? CCC/slope/MAE all reported? Eval protocol labeled? No redundancy? |
| Discussion Depth | 10% | Beyond restating results? SSL mechanism explained? Honest limitations? Clinical insight? |
| Writing Quality | 10% | Concise? Academic tone? Jargon defined? CCC motivated? Consistent? |
| Visual Excellence | 10% | Figures insightful? Publication-quality? Colorblind-safe? Appendix Figs A-F clear? |

### Subagent 4A: Review Cycle 1 — Accuracy & Completeness

```
Agent(description="Peer review cycle 1",
      prompt=<see SUBAGENT_4A below>,
      mode="bypassPermissions")
```

**SUBAGENT_4A prompt:**
> You are a senior peer reviewer performing Cycle 1 (Accuracy & Completeness) on an academic paper.
>
> Read the manuscript: `/home/fiod/medical/NEW.html`
> Read the source data for verification: `/home/fiod/medical/.paper_build/results_summary.md`
> Read the methods reference: `/home/fiod/medical/.paper_build/methods_summary.md`
>
> **Focus**: Every number traces to a source artifact. Every method parameter matches actual code. Every statistical test is correctly described. Every figure is referenced in text. Missing information is added. Factual errors are corrected.
>
> **Domain Checklist** — verify ALL of these:
> - [ ] Medication state (ON/OFF) reported or acknowledged
> - [ ] H&Y stage distribution in demographics
> - [ ] PD-only metrics reported alongside overall throughout
> - [ ] UPDRS items numbered correctly (MDS-UPDRS Part III, 3.1-3.18)
> - [ ] MCID cited correctly (Horvath 2015: -3.25 improvement, +4.63 worsening)
> - [ ] Sensor locations anatomically described (not just "IMU 1, IMU 2")
> - [ ] Window-level vs subject-level evaluation clearly stated
> - [ ] Feature selection inside CV (not outside)
> - [ ] Controlled gait vs free-living explicitly stated
> - [ ] Observable item classification justified (3-level: direct/partial/unobs)
> - [ ] No amplitude normalization that destroys severity signal
> - [ ] Split contamination risk discussed (why 10-split, why paper3_split)
> - [ ] **SSL eval protocol (LOOCV) vs baseline (5-split) clearly labeled in EVERY table and text reference**
> - [ ] **P0 and P5 rows in Table 7 show different eval protocols — caption/note reflects this**
> - [ ] **Observability gradient uses consistent model/protocol (baseline LOOCV from pd_only_experiments.json, NOT mixing SSL direct with baseline partial/unobs)**
> - [ ] **HC used for representation only (Stage 1) — eval is PD-only LOOCV — stated explicitly**
> - [ ] **No claims about SSL "10-split" results unless a 10-split SSL artifact exists**
> - [ ] **CCC and slope reported as primary metrics for observable subscores**
> - [ ] **Quartile bias analysis present for T1 SSL LOOCV**
> - [ ] **T1/T2/T3 target definitions explicitly listed (items 9-14, 7-14, all)**
> - [ ] All tables have correct N values matching the evaluation protocol
> - [ ] Appendix (Section 5) figures A-F referenced correctly and have captions
> - [ ] Supplementary tables S1, S2 present and complete
>
> **Protocol**:
> 1. Read the ENTIRE manuscript carefully
> 2. Score each of 7 dimensions (Scientific Rigor 25%, Novelty 15%, Methods 15%, Results 15%, Discussion 10%, Writing 10%, Visual 10%) on 1-10 scale
> 3. Identify top 3 highest-impact issues
> 4. Fix them by editing `/home/fiod/medical/NEW.html` directly (use Edit tool)
> 5. Write your review to `/home/fiod/medical/.paper_build/review_cycle1.md` with: per-dimension scores, issues found, fixes applied, remaining concerns

### Subagent 4B: Review Cycle 2 — Narrative & Insight

```
Agent(description="Peer review cycle 2",
      prompt=<see SUBAGENT_4B below>,
      mode="bypassPermissions")
```

**SUBAGENT_4B prompt:**
> You are a senior peer reviewer performing Cycle 2 (Narrative & Insight) on an academic paper that has already been through one accuracy review.
>
> Read the manuscript: `/home/fiod/medical/NEW.html`
> Read the previous review: `/home/fiod/medical/.paper_build/review_cycle1.md`
> Read the context: `/home/fiod/medical/.paper_build/context_summary.md`
>
> **IMPORTANT**: Also read external LLM feedback if available (files may not exist if CLIs were unavailable — skip gracefully):
> - `/home/fiod/medical/.paper_build/external_codex_writing.md` — GPT-5.4 writing review
> - `/home/fiod/medical/.paper_build/external_gemini_writing.md` — Gemini scientific narrative review
>
> Treat external feedback as advisory input from additional reviewers. Apply suggestions that genuinely improve the paper. Reject suggestions that conflict with the data, weaken the narrative, or add unnecessary hedging. Note in your review which external suggestions you accepted/rejected and why.
>
> Also read the user-approved narrative alignment: `/home/fiod/medical/.paper_build/narrative_alignment.md` — this defines the agreed lead takeaway, core insight, and claim hierarchy. The paper MUST follow this framing.
>
> **Focus**: Does the paper tell a compelling story? Is the agreed lead takeaway front and center? Does the Discussion go deeper than restating results? Are figures genuinely insightful — does each one change how the reader thinks? Would a Nature reviewer find this interesting and broadly relevant?
>
> Key narrative elements to verify/strengthen:
> 1. **SSL ranking from HC** is presented as a genuine methodological contribution — the mechanism (HC as calibration anchors, N amplification from 94→178 for representation learning) is clearly explained
> 2. The **compression problem** in small-N clinical regression is properly motivated before the SSL solution is introduced
> 3. The **observability ceiling** is the CORE structural insight — gait IMU physically cannot assess rigidity, speech, facial expression
> 4. **CCC over r** is motivated — r doesn't penalize systematic bias, CCC does, which matters for clinical deployment
> 5. What failed (DL, ordinal, pairwise, NGBoost) is EVIDENCE for the ceiling, not just negative results
> 6. **Foundation model** success is a paradigm shift for small clinical datasets
> 7. **Clinical utility** of observable subdomain — MAE=0.99 on items 9-14 is actionable even without total UPDRS
> 8. 7x more subjects + proper validation vs prior N=24 LOOCV work
> 9. **Appendix** (Section 5) genuinely helps clinical readers understand the ML pipeline
>
> **Protocol**:
> 1. Read the full manuscript
> 2. Read and triage external LLM feedback (accept/reject each suggestion)
> 3. Score each dimension 1-10
> 4. Identify top 3 narrative improvements (combining your analysis + external feedback)
> 5. Fix them by editing `/home/fiod/medical/NEW.html` directly
> 6. Write review to `/home/fiod/medical/.paper_build/review_cycle2.md` — include section on external feedback triage

### Step 4.5: External Visual Quality Pass (2 PARALLEL bash commands)

Between review cycles 2 and 3, get targeted feedback on figure quality and visual presentation from codex and gemini. Run BOTH in parallel. They review the figure generation code in `generate_paper.py` and suggest matplotlib improvements.

**Codex — Figure & Visual Review:**
```bash
cd /home/fiod/medical && codex exec -m gpt-5.4 -c model_reasoning_effort="xhigh" --full-auto "You are reviewing the figure generation code in generate_paper.py for an academic paper targeting Nature Digital Medicine. Read generate_paper.py and focus ONLY on the matplotlib figure-generation functions. For each figure (Figs 1-10 main + Figs A-F appendix), evaluate: (1) Is the chart type optimal for the data being shown? (2) Are colors colorblind-safe (use viridis/cividis families or verified safe palettes)? (3) Is text readable at print size (>=8pt)? (4) Are axis labels, legends, and annotations clear and complete? (5) For scatter plots (Figs 2, 3): are CCC, slope, and MAE annotated? Is the identity line visible? (6) For the compression comparison (Fig 7): does it clearly show P5 SSL dominance? (7) Would a Nature reviewer consider this publication-quality? Provide SPECIFIC matplotlib code patches — not vague suggestions. Focus on the 5 highest-impact visual improvements. Write to .paper_build/external_codex_visual.md" > /dev/null 2>&1
```

**Gemini — Data Visualization Review:**
```bash
cd /home/fiod/medical && gemini -m gemini-3.1-pro-preview -y "You are a data visualization expert reviewing figure code in generate_paper.py for a medical research paper. Read generate_paper.py. For each figure: (1) Does it tell a story at a glance without reading the caption? (2) Is the data-ink ratio good (no chartjunk, no unnecessary gridlines/borders)? (3) Are statistical annotations (CIs, CCC, slope, p-values, effect sizes) shown appropriately? (4) Would Tufte approve? (5) For the SSL scatter plots (Figs 2, 3): do they clearly communicate the breakthrough (CCC=0.868)? (6) For the quartile bias plot (Fig 8): is the before/after improvement immediately visible? (7) For the appendix pipeline figures (Figs A-F): are they educational and accessible to clinical readers? Suggest specific improvements as concrete matplotlib code changes. Write to .paper_build/external_gemini_visual.md" > /dev/null 2>&1
```

Both commands MUST produce output. If either fails (CLI not available, timeout), retry ONCE. If it fails again, STOP and report the failure to the user — do not proceed without external visual feedback. The Cycle 3 subagent will apply the best patches from both reviewers.

---

### Subagent 4C: Review Cycle 3 — Polish & Reviewer-Proofing

```
Agent(description="Peer review cycle 3",
      prompt=<see SUBAGENT_4C below>,
      mode="bypassPermissions")
```

**SUBAGENT_4C prompt:**
> You are a senior peer reviewer performing the FINAL review cycle (Polish & Reviewer-Proofing) on an academic paper that has been through accuracy and narrative reviews.
>
> Read the manuscript: `/home/fiod/medical/NEW.html`
> Read previous reviews: `/home/fiod/medical/.paper_build/review_cycle1.md` and `/home/fiod/medical/.paper_build/review_cycle2.md`
>
> **IMPORTANT**: Also read external visual feedback if available (files may not exist — skip gracefully):
> - `/home/fiod/medical/.paper_build/external_codex_visual.md` — GPT-5.4 figure quality review
> - `/home/fiod/medical/.paper_build/external_gemini_visual.md` — Gemini data visualization review
>
> If the external visual reviewers provided concrete matplotlib code patches that would improve figure quality, apply the best ones by editing `generate_paper.py`, then rerun: `cd /home/fiod/medical && uv run python generate_paper.py`. Only apply patches that are clearly correct and improve publication quality. Reject patches that change data presentation or could mislead.
>
> **Focus**: Anticipate and pre-address every likely reviewer objection. Check writing for consistency, flow, and precision. Final data verification pass. Ensure abstract faithfully reflects the paper. Check all cross-references. Apply visual improvements from external feedback.
>
> **Reviewer Objections to Pre-Address** (verify each is addressed in the paper):
> 1. "Why not deep learning?" — DL comparison table (Table S1) showing 5 architectures fail at N=178
> 2. "N=178 is small" — Field standard is N=24; we have 7x more
> 3. "Single dataset" — Acknowledged, cross-dataset transfer proposed as future work
> 4. "HC inflate metrics" — PD-only metrics reported throughout; SSL uses HC for representation only
> 5. "No longitudinal" — Acknowledged, controlled tasks give clean cross-sectional benchmark
> 6. "Feature selection overfits" — Selection inside CV folds
> 7. "Observable classification subjective" — Justified with clinical literature; 3-level is conservative
> 8. "FM may not generalize" — Frozen, deterministic, discussed in limitations
> 9. "MCID claim too strong" — "comparable to" not "below" for borderline results
> 10. **"SSL uses HC labels — isn't that leakage?"** — HC used for RANKING representation (Stage 1) only. Final regression eval is strict PD-only LOOCV. HC subjects never appear in test folds. Per-subject UPDRS labels used only as ranking targets in Stage 1, not as features. Stated explicitly in Methods.
> 11. **"P0 and P5 use different protocols — not a fair comparison"** — P0 is 5-split (N=95), P5 is LOOCV (N=94). Table 7 labels both clearly. Discussed as limitation. LOOCV is stricter — P5's advantage is DESPITE the harder eval.
> 12. **"CCC is an unusual primary metric"** — CCC penalizes compression bias that r ignores. Clinically important: a model that predicts everyone as average (r=0, CCC=0) would have decent MAE but terrible CCC. Cited: Lin 1989.
> 13. **"Quartile bias — is it cherry-picked?"** — Pre-specified analysis; quartile boundaries from target distribution, not post-hoc.
> 14. **"The observability gradient mixes models"** — If baseline is used for gradient AND SSL results are reported separately, verify these are never combined into one "gradient" claim.
> 15. **"13 sensors is impractical"** — Addressed: sensor reduction study shows minimal_5 (LB+wrists+ankles) is non-inferior across all targets; wrists_ankles_4 is SUPERIOR on T3 (p=0.006). Clinical deployment with 4-5 sensors is validated. Source: `sensor_span_repeated_cv.json` with 10×5-fold Nadeau-Bengio corrected tests.
> 16. **"Sensor ablation is confounded by feature count"** — Addressed: K-sweep shows fixed K=500 is NOT the primary confound. FM decomposition shows paradox lives in v2 handcrafted features. 10×5-fold repeated CV resolves winner's curse from initial 5-split screening. Sources: `sensor_span_k_sweep.json`, `sensor_span_fm_decomposition.json`.
> 17. **"FM embeddings — do they actually help?"** — Addressed: FM-only gives CCC≈-0.01 (useless alone). FM only adds value for wrists_ankles_4 on T3 (+0.058 CCC). For most configs/targets, v2 handcrafted features drive all predictive power. Source: `sensor_span_fm_decomposition.json`.
>
> **Protocol**:
> 1. Read the full manuscript one final time
> 2. Review and triage external visual feedback — apply best patches to generate_paper.py and rerun if warranted
> 3. Score each dimension 1-10
> 4. Fix any remaining issues by editing the HTML directly
> 5. Verify all figures are present and render correctly (check base64 strings are valid)
> 6. Verify all tables have correct values
> 7. Verify appendix (Section 5) is complete with Figs A-F and all subsections
> 8. Verify supplementary information (Tables S1, S2) is present
> 9. Write final review to `/home/fiod/medical/.paper_build/review_cycle3.md` with:
>    - Final per-dimension scores and weighted total (target >=90/100)
>    - Score interpretation: 92+ Nature Digital Medicine ready, 88-91 npj PD ready, 84-87 needs human review, <84 not ready
>    - Remaining issues requiring HUMAN attention (author names, affiliations, funding, COI)
>    - External feedback triage: which visual suggestions were applied/rejected and why
>    - Key strengths
>    - Any risks for submission

---

## Step 5: Final Report

After all review subagents complete, read the three review files:
- `/home/fiod/medical/.paper_build/review_cycle1.md`
- `/home/fiod/medical/.paper_build/review_cycle2.md`
- `/home/fiod/medical/.paper_build/review_cycle3.md`

Also check for external feedback files (may not all exist):
- `/home/fiod/medical/.paper_build/external_codex_writing.md`
- `/home/fiod/medical/.paper_build/external_gemini_writing.md`
- `/home/fiod/medical/.paper_build/external_codex_visual.md`
- `/home/fiod/medical/.paper_build/external_gemini_visual.md`

Compile `review_report.md` at `/home/fiod/medical/review_report.md` combining all three cycles.

Report to user:
- Final quality score (X/100) with per-dimension breakdown
- Score progression across 3 cycles
- External LLM feedback summary: which codex/gemini suggestions were integrated, which were rejected
- Remaining issues requiring human attention
- Key strengths and any remaining risks for submission
- Location of outputs: `NEW.html` and `review_report.md`
- **Figure inventory**: confirm all 10 main figures + 6 appendix figures are embedded
- **Table inventory**: confirm all tables (1-8, P1, S1, S2) are present and verified

---

## Critical Rules for Orchestrator

- NEVER try to read all result files yourself — that's what the subagents are for
- NEVER try to write the generate_paper.py script yourself — delegate to subagent 2
- DO fix small script execution errors in Step 3 (syntax errors, missing imports) — that's orchestrator work
- DO combine review reports in Step 5 — that's orchestrator work
- Launch Step 1 subagents IN PARALLEL (single message, 3 Agent tool calls)
- Launch Step 3.5 CLI commands IN PARALLEL (single message, 2 Bash tool calls)
- Launch Step 4.5 CLI commands IN PARALLEL (single message, 2 Bash tool calls)
- Launch Step 4 subagents SEQUENTIALLY (each needs the previous review)
- If a subagent fails or produces poor output, retry it ONCE with additional guidance
- If codex or gemini CLI fails (not installed, timeout, rate limit), retry ONCE. If it fails again, STOP and report the failure to the user — do not proceed without external feedback
- External LLM feedback is REQUIRED — review subagents decide what to accept/reject, but the feedback itself must be collected before proceeding
- NEVER let external LLMs override data-verified facts (they don't have access to result artifacts)
- Clean up `.paper_build/` at the end: `rm -rf /home/fiod/medical/.paper_build/`

## Generation Script Integrity Rules (`generate_paper.py`)

These rules prevent the class of numerical inconsistencies where hardcoded values, mixed data sources, or stale annotations silently diverge from the actual result JSON files. Every paper update MUST enforce them.

### Rule G1: ZERO hardcoded result values
Every number that originates from an experiment result JSON file MUST be loaded from that JSON and formatted via f-string or `.format()`. **Never write a literal number when a `d.xxx.get("metric")` call is available.** This includes:
- Table footnotes referencing computed values (e.g., quartile bias)
- Cross-dataset "this work" comparison rows
- Inline prose demographics (age, sex, UPDRS)
- Figure annotation boxes (CCC, MAE, slope, N, protocol label)
- Pipeline schematic labels (N subjects, feature counts, output CCC)

Fallback defaults (second arg to `.get()`) are acceptable ONLY as emergency values when JSON is missing, and they should match the most recent known value. Stale fallbacks are silent bugs.

### Rule G2: One data source per context
When a table, figure, or text paragraph presents results, ALL numbers in that context MUST come from the same analysis pipeline and evaluation protocol. Specifically:
- A table row mixing P0 baseline (from `compression_P0_TT1`) with reviewer experiment results (from `reviewer_obs_5fold`) is a **protocol mismatch**, even if both use 5-fold CV — they may differ in N, fold splits, or feature selection.
- If mixed sources are unavoidable (e.g., Table 2 observability decomposition where direct uses the primary pipeline N=95 but partial/unobs use restricted N=90), the table MUST have a footnote explaining exactly which rows use which source and why N differs.
- The abstract and discussion MUST use the same values as the corresponding tables they reference. If Table 2 shows direct CCC=0.865, the abstract's observability gradient sentence MUST also say 0.865, not a different value from a different analysis.

### Rule G3: Figure annotations match their data source
Every figure function MUST derive its text annotations (stats boxes, bar labels, axis annotations) from the SAME data dict used to generate the visual data. Specifically:
- If `fig2_ssl_scatter` uses `d.ssl_5split_t1` for scatter points, the stats box MUST say the 5-fold protocol label, not "LOOCV"
- If `fig1_study_design` output boxes show CCC values, they MUST use the primary evaluation data (5-fold), not LOOCV, to match the paper's primary results
- Figure titles/suptitles MUST reflect the actual data shown (e.g., "5-fold CV" when 5-fold data is used, not "LOOCV")
- Detect mismatch pattern: if the code selects data with `d.ssl_5split_t1 if d.ssl_5split_t1 else d.ssl_t1`, the protocol label must branch the same way

### Rule G4: No fabricated or synthetic result data in figures
Figures that show experimental results MUST use actual data from JSON artifacts. If data is unavailable, the figure MUST either:
- Skip the panel with a "data not available" placeholder, OR
- Be clearly labeled as "Illustrative" or "Schematic" in both the figure title and HTML caption

Fabricated interaction heatmaps, synthetic scatter points, or made-up ablation values presented without "illustrative" labels are scientific integrity violations.

### Rule G5: Automated cross-check after every regeneration
After running `generate_paper.py`, extract ALL numbers from the generated HTML (tables, text, figure captions) and cross-check against the source JSON files. The verification script should:
1. Parse every `<td>` cell in every table → compare against the JSON field that produced it
2. Search for inline metric patterns (CCC = X.XXX, MAE = X.XX, r = X.XXX, N = XX) → verify each
3. Flag any number that appears with two different values in different locations
4. Flag any metric presented without an evaluation protocol label

This check is performed by U-Step 4 (verification) or Scratch Step 4 (review cycle 1).

---
---

# UPDATE PATH — Incremental Paper Update

**This path is used when the user chooses mode B (Update Existing).** It preserves working prose and structure while surgically fixing stale/missing/incorrect content.

The goal: bring the existing `NEW.html` into perfect alignment with the latest results from findings.md and memory files. Zero stale numbers, zero leftover text from old experiments, zero inconsistencies, zero mixed-protocol comparisons.

---

## U-Step 1: Comprehensive Audit (2 PARALLEL subagents)

Launch BOTH subagents simultaneously. They produce the audit materials.

First, create the output directory:
```bash
mkdir -p /home/fiod/medical/.paper_build
```

### Subagent U-1A: Truth Extractor

```
Agent(description="Extract latest truth for paper audit",
      prompt=<see below>,
      mode="bypassPermissions")
```

**Prompt:**
> You are a data auditor for an academic paper update. Your job is to extract the COMPLETE current ground truth from all authoritative sources, so that a downstream agent can diff it against the existing paper.
>
> Read these files EXHAUSTIVELY — every linked memory file, every section:
> 1. `/home/fiod/.claude/projects/-home-fiod-medical/memory/MEMORY.md` — read this FIRST, then read EVERY file it links to (follow all `[filename](filename)` links)
> 2. `/home/fiod/medical/CLAUDE.md` — the "Current Results", "SOTA Landscape", and "The Bar" sections are authoritative
> 3. `/home/fiod/medical/findings.md` — ALL experimental findings, especially compression ablation and SSL results
> 4. `/home/fiod/medical/autoresearch_results.tsv` — full MAE experiment log
> 5. `/home/fiod/medical/autoresearch_ccc_results.tsv` — full CCC experiment log
>
> Also run: `ls -la /home/fiod/medical/results/*.json` and read the key result JSON files for exact numbers:
> - `compression_P5_TT1.json`, `compression_P5_TT2.json`, `compression_P5_TT3.json` — **AUTHORITATIVE SSL LOOCV results**
> - `compression_P0_TT*.json` — baseline (5-split, NOT LOOCV)
> - `compression_P1_TT1.json`, `compression_P3_TT*.json`, `compression_P4_TT*.json` — other proposals
> - `pd_only_experiments.json` — 3-level observability (baseline)
> - `rocket_phase*.json` — FM ablation
> - `sensor_ablation_results.json` — sensor reduction
> - `clean_benchmark_results.json` — held-out test
> - `compression_ablation_all.json` — summary (WARNING: may have stale 5-split numbers — always prefer individual P5 files)
>
> Write to `/home/fiod/medical/.paper_build/current_truth.md` a COMPLETE specification of what the paper SHOULD say:
>
> ### Section: Results to Report
> For EVERY reportable result, provide:
> - Exact metric values (CCC, slope, MAE, r, RMSE, p-values) with full precision
> - Which evaluation protocol produced them (LOOCV vs 5-split vs 10-split vs held-out)
> - Which target (T1 items 9-14, T2 items 7-14, T3 total UPDRS)
> - N (PD-only or mixed)
> - Which model/config produced them
> - Whether 95% CIs are available and what they are
> - Source JSON file
>
> ### Section: SOTA Comparison
> - Exact numbers for Hssayeni (MAE=5.95, r=0.79, N=24, LOOCV), Shuqair (r=0.89, MAE~5.65, N=24, LOOCV)
> - Why each disqualified paper is disqualified (exact reasons)
> - Verified citation URLs
>
> ### Section: Key Claims & Narrative Points
> - SSL ranking results for all 3 targets (T1/T2/T3) with CCC, slope, MAE
> - Compression ablation comparison (5 proposals × 3 targets)
> - Quartile bias (Q1-Q4 before/after SSL on T1)
> - Observable subdomain results (3-level: direct/partial/unobs from BASELINE, separately from SSL)
> - FM vs baseline improvement (exact delta, p-value)
> - Sensor ablation (minimal vs full, p-value)
> - Demographics baseline comparison
> - What failed and why (DL, ordinal, pairwise, NGBoost, calibration)
> - Autoresearch HP optimization results (improvement path, total gain)
>
> ### Section: Methods Parameters
> - Current best model hyperparameters for each pipeline (baseline, CCC-optimized, SSL)
> - Feature selection K value per pipeline
> - Number of seeds
> - SSL Stage 1 XGBRanker params
> - SSL Stage 2 LGB params
> - Any other params that may have changed
>
> ### Section: Things That Changed Recently
> - List ANYTHING that changed since the paper was last generated
> - New experiments, new best results, corrected numbers, new insights
> - Flag items that are likely NOT yet in the paper
> - Flag any places where old summary files appear internally inconsistent or mix evaluation modes
>
> ### Section: Claim Provenance Matrix (TYPED EVIDENCE LEDGER)
> For every number likely to appear in the paper, record a **structured claim tuple**:
> - `claim_id`: unique identifier (e.g., "ssl_5fold_t1_ccc")
> - `target`: T1/T2/T3/total/overall
> - `metric`: CCC/slope/MAE/r
> - `value`: exact number
> - `model`: which pipeline (baseline/SSL/FM_stack/demographics)
> - `protocol`: LOOCV/5-split/10-split/held-out
> - `N`: exact sample size for THIS evaluation
> - `source_file`: path to results/*.json
> - `role`: primary/sensitivity/supplementary/negative
> - `artifact_exists`: YES/NO (verify the file actually exists and contains the metric)
>
> **CRITICAL RULES:**
> - Every claim with `artifact_exists: NO` must be flagged as PHANTOM — the diff agent MUST either find the artifact or DELETE the claim from the paper.
> - Every claim must have a SINGLE canonical (protocol, N) pair. If the same metric appears under two protocols, they are TWO DIFFERENT claims with different claim_ids.
> - The downstream diff agent receives this ledger and MUST verify that every instance of a claim_id in the paper uses the SAME (value, protocol, N) tuple.
>
> Be EXHAUSTIVE. The diff agent downstream will compare every claim in the paper against this ledger. Missing items here = missed updates in the paper.

### Subagent U-1B: Paper Content Extractor

```
Agent(description="Extract current paper content",
      prompt=<see below>,
      mode="bypassPermissions")
```

**Prompt:**
> You are a paper content auditor. Your job is to extract every factual claim, number, and parameter from the existing paper so it can be diffed against the latest results.
>
> Read `/home/fiod/medical/NEW.html` completely.
>
> Write to `/home/fiod/medical/.paper_build/paper_claims.md` a structured extraction:
>
> ### Abstract Claims
> List every quantitative claim in the abstract with its exact number.
>
> ### Results Section Claims
> For each result mentioned:
> - The exact metric value stated
> - Which model/config it's attributed to
> - Which evaluation protocol is described
> - What target (T1/T2/T3/total) it refers to
> - What sample size N it implies or states
> - Any CIs or p-values cited
>
> ### Methods Parameters
> Every hyperparameter, dataset size, split detail, feature count mentioned.
>
> ### SOTA Comparisons
> Every comparison with prior work — the numbers cited and how they're framed.
>
> ### Discussion Claims
> Key interpretive claims and the numbers backing them.
>
> ### Tables
> For each table (Tables 1-8, P1, S1, S2): reproduce the exact values in markdown table format.
>
> ### Figures
> For each figure (Figs 1-10, Figs A-F): what data it claims to show, any numbers in annotations/text boxes.
>
> ### Potential Issues Spotted
> Flag anything that looks suspicious: round numbers that should be precise, vague claims without backing numbers, placeholder-like text, inconsistent numbers across sections (same metric cited differently in abstract vs results), old experimental setups described that may no longer be current.
> Also flag:
> - Mixed-protocol comparisons presented as apples-to-apples (LOOCV vs 5-split in same table without labels)
> - Baseline/SSL endpoint mixing inside a single "gradient" or decomposition claim
> - Claims about split distributions with no visible supporting artifact (e.g., "all 10 splits below MCID" for SSL when no SSL 10-split artifact exists)
> - Endpoint overreach (e.g., sensor-ablation result on total score used to justify observable-subdomain deployment)
> - Missing N values in table headers or captions
> - Appendix completeness (all Figs A-F present? All subsections in Section 5?)
>
> Be EXACT — copy numbers character-for-character. This is a forensic extraction.

---

## U-Step 2: Diff & Fix (1 subagent)

Wait for both U-Step 1 subagents to complete. Then launch:

```
Agent(description="Diff and fix paper content",
      prompt=<see below>,
      mode="bypassPermissions")
```

**Prompt:**
> You are a meticulous paper updater. Your job is to bring an existing academic paper into perfect alignment with the latest experimental results. You have two reference documents:
>
> 1. `/home/fiod/medical/.paper_build/current_truth.md` — what the paper SHOULD say (ground truth)
> 2. `/home/fiod/medical/.paper_build/paper_claims.md` — what the paper CURRENTLY says
>
> Also read the narrative alignment file if it exists: `/home/fiod/medical/.paper_build/narrative_alignment.md`
> If it doesn't exist, read the paper's existing structure and preserve its narrative direction.
>
> Read both documents carefully and produce a COMPLETE diff. Then fix every discrepancy.
>
> ### MANDATORY PRE-FIX GATES (run BEFORE any edits)
>
> Before making ANY changes to the HTML, run these 4 structural checks. Any failure is a BLOCKER — fix the issue first.
>
> **GATE 1: Artifact-Existence Check.**
> For every ablation, sensitivity, or "comparable results" claim in the paper, verify a corresponding `results/*.json` file exists. Run:
> ```bash
> grep -oiP '(?:ablation|sensitivity|robustness|fold-restricted|age-matched|comparable)[^.]*\.' NEW.html | head -20
> ```
> For each match, verify a backing JSON exists. If a claim has NO backing artifact, either DELETE the claim or flag it as FIXME.
>
> **GATE 2: Protocol-N Consistency Check.**
> Extract every (N=XX, protocol) pair from the paper. Verify N=95 always pairs with 5-fold and N=94 always pairs with LOOCV. Run:
> ```python
> # Check N-protocol alignment
> import re
> text = re.sub(r'<[^>]+>', ' ', open('NEW.html').read())
> for m in re.finditer(r'(5-fold|LOOCV)[^.]{0,80}N\s*=\s*(\d+)', text, re.I):
>     proto, n = m.group(1), int(m.group(2))
>     if '5-fold' in proto.lower() and n == 94: print(f'FAIL: N=94 in 5-fold context')
>     if 'loocv' in proto.lower() and n == 95: print(f'FAIL: N=95 in LOOCV context')
> ```
>
> **GATE 3: Statistical Test Hypothesis Check.**
> If the paper cites a Williams test or similar ordered-alternatives test, verify the claimed ordering matches the test's hypothesis. Load the test JSON and compare `tier_cccs_input` ordering against the prose claim.
>
> **GATE 4: Cross-Table Protocol Match.**
> If inline text and a table present the SAME metric (e.g., T3 MAE), they must use the SAME protocol and N. Any mismatch where one is 5-fold and the other is LOOCV without explicit labeling is a FAIL.
>
> Only proceed to edits after ALL 4 gates pass (or their failures are logged as the FIRST items to fix).
>
> ### Diff Protocol
>
> For EVERY claim in paper_claims.md, compare against current_truth.md:
>
> 1. **STALE NUMBER** — paper says X but truth says Y → fix to Y
> 2. **MISSING RESULT** — truth has a result not mentioned in paper → add it in the appropriate section
> 3. **REMOVED RESULT** — paper mentions a result that's been superseded or invalidated → remove or update
> 4. **WRONG ATTRIBUTION** — paper attributes a result to wrong model/config → fix attribution
> 5. **INCONSISTENT** — same metric appears with different values in different sections → unify to truth value
> 6. **STALE METHOD** — paper describes old hyperparameters/config that changed → update to current
> 7. **LEFTOVER TEXT** — prose references old experiments, old configs, or old results that no longer exist → remove or rewrite
> 8. **PLACEHOLDER** — any text that looks like a placeholder, TODO, FIXME, or template → fill with real data or flag
> 9. **PROTOCOL MISMATCH** — a table/text presents LOOCV and 5-split results without labeling the difference → add explicit protocol labels
> 10. **MIXED GRADIENT** — observability gradient combines SSL direct with baseline partial/unobs → separate into consistent-model gradient
>
> ### Fix Protocol
>
> Read `/home/fiod/medical/NEW.html` and apply ALL fixes using the Edit tool.
>
> **Rules:**
> - Fix EVERY discrepancy found in the diff, not just the top 3
> - Preserve the existing prose style and structure — don't rewrite paragraphs that are correct
> - When adding new results, write them in the same style as surrounding text
> - Update ALL instances of a stale number (abstract, results, discussion, tables)
> - If a table needs updating, update the entire table consistently
> - If a figure caption references stale numbers, update the caption
> - After all fixes, do one final consistency pass: search NEW.html for any remaining instances of old/stale values
> - Cross-check: every number in the abstract must match its occurrence in the Results section
> - Every table must have the correct evaluation protocol in its caption
> - Every comparison between P0 and P5 must note the protocol difference
>
> ### Quality Checklist (MUST pass before finishing)
> - [ ] Every metric in the abstract matches the Results section
> - [ ] Every table value matches the corresponding text
> - [ ] No stale model names or configs referenced
> - [ ] No leftover text about experiments that were superseded
> - [ ] No placeholder text (FIXME, TODO, TBD, XXX, etc.)
> - [ ] PD-only metrics reported alongside overall where applicable
> - [ ] SOTA comparison table is current with latest numbers
> - [ ] Methods section hyperparameters match current best config for each pipeline
> - [ ] All p-values and CIs are from the correct comparison
> - [ ] Discussion limitations section is current
> - [ ] Table 7 has eval protocol column or caption note (P0=5-split, P5=LOOCV)
> - [ ] Table 8 quartile bias values match source JSON
> - [ ] Observability gradient uses baseline numbers consistently (NOT mixed with SSL)
> - [ ] CCC and slope are primary metrics for observable subscores
> - [ ] All N values in table captions are correct
> - [ ] Appendix Section 5 is complete (all subsections, Table P1, Figs A-F referenced)
>
> ### Generation Script Integrity Checklist (`generate_paper.py`)
> These checks prevent hardcoded-value bugs. Apply them to every table builder, figure function, and HTML builder:
> - [ ] **G1 — Zero hardcoded results**: Grep `generate_paper.py` for literal metric values (e.g., `0.868`, `8.146`, `5.95`). Every "our result" number must come from a `.get()` call on loaded JSON data. External study numbers (Hssayeni, Shuqair) may be hardcoded since they come from papers.
> - [ ] **G2 — One source per context**: For each table function, verify ALL rows in the same table use the same analysis pipeline. If mixing is unavoidable, verify the footnote explains the source difference.
> - [ ] **G3 — Figure annotations match data source**: For each `fig*()` function, verify the stats box / bar label / text annotation uses the SAME variable as the visual data. Check that protocol labels ("LOOCV" vs "5-fold CV") branch based on which data dict was selected.
> - [ ] **G4 — No fabricated data**: Search for `rng.`, `random`, synthetic arrays in figure functions. Any synthetic data must be labeled "Illustrative" in both the figure title and HTML caption.
> - [ ] **G5 — Fallback values current**: Grep for `.get("ccc",` `.get("mae",` etc. Verify every fallback default matches the most recent known value from the corresponding JSON file.
> - [ ] **Inline demographics data-driven**: The cohort description prose (age, sex, UPDRS) must use `dp.get('age_mean')` etc., not hardcoded literal strings.
> - [ ] **Cross-dataset table data-driven**: The `_table6_cross_dataset()` function must accept `d` parameter and use `d.ssl_t1`, `d.ssl_t3`, `d.pd_only` for "our" rows.
>
> Write your diff report to `/home/fiod/medical/.paper_build/update_diff.md` with:
> - Total discrepancies found (categorized by type)
> - Each fix applied (old value → new value, location)
> - Any items you could NOT fix (missing data, ambiguous truth)
> - Confidence level: HIGH (all fixes verified), MEDIUM (some items uncertain), LOW (significant gaps)

---

## ORCHESTRATOR GATE: U-Steps 3, 3B, 3C are NON-NEGOTIABLE

**STOP. Before proceeding to U-Step 4, you MUST execute U-Step 3, 3B, AND 3C.** These steps regenerate figures, verify tables, and audit the generation script. Skipping them is the #1 cause of table-figure-text number disagreements. If you skip them, the paper WILL have inconsistencies.

**Enforcement**: After U-Step 2 completes, immediately launch U-Step 3 and U-Step 3B as PARALLEL subagents. Then launch U-Step 3C. Only after ALL THREE complete may you proceed to U-Step 4.

---

## U-Step 3: Regenerate ALL Figures (MANDATORY)

**This step is ALWAYS required.** Figures embed data as base64 PNGs and become stale whenever results change. Never skip this step.

Launch a subagent to regenerate all figures:

```
Agent(description="Regenerate paper figures",
      prompt=<see below>,
      mode="bypassPermissions")
```

**Prompt:**
> You are a figure regeneration specialist. Your job is to update ALL data-driven figures in the paper to reflect the latest results.
>
> Read these files:
> 1. `/home/fiod/medical/.paper_build/current_truth.md` — latest results (P5 SSL, baselines, SOTA, quartile bias)
> 2. `/home/fiod/medical/generate_paper.py` — existing figure generation code
> 3. `/home/fiod/medical/NEW.html` — the current manuscript (to find which figures exist)
>
> **Complete figure inventory** (verify ALL are present in NEW.html):
>
> **Main figures (Figs 1-10):**
> - **Fig 1** (Pipeline schematic): Must show the 2-stage SSL architecture (XGBRanker on N=178 → leaf features → LGB on PD-only)
> - **Fig 2** (SSL scatter): Must show CURRENT BEST T1 per-subject predictions (CCC=0.868 LOOCV), with CCC/slope/MAE in text box
> - **Fig 3** (Three-target comparison): 3-panel scatter T1/T2/T3 side by side, same axis scales
> - **Fig 4** (Observability decomposition): 3-level grouped bars (direct/partial/unobs × CCC/slope/MAE), BASELINE model only
> - **Fig 5** (Item-level predictability): Lollipop chart, colored by 3-level observability tier
> - **Fig 6** (Feature importance): Top 20 features by importance
> - **Fig 7** (Compression ablation): 5 proposals × T1 CCC comparison
> - **Fig 8** (Quartile bias): Q1-Q4 before/after SSL, showing compression reduction
> - **Fig 9** (FM impact): Paired 10-split comparison v2 vs v2+FM
> - **Fig 10** (Cross-dataset forest plot): Our CCC/MAE vs Hssayeni, Shuqair
>
> **Appendix figures (Figs A-F in Section 5):**
> - **Fig A**: Decision tree ensemble diagram
> - **Fig B**: MSE vs MAE loss comparison
> - **Fig C**: Feature selection / column subsampling
> - **Fig D**: Multi-seed ensemble averaging
> - **Fig E**: Foundation model embedding extraction (MOMENT)
> - **Fig F**: Hyperparameter interaction or summary
>
> For EACH figure:
> 1. Determine if the data it shows has changed since last generation
> 2. If YES: update the figure generation code in `generate_paper.py` or write a standalone figure updater script
> 3. Generate the updated figure as base64 PNG (300 DPI, colorblind-safe palette)
> 4. Replace the old base64 image in `NEW.html`
>
> After updating, verify each new figure's base64 string is properly embedded in NEW.html. Run the generation script:
> ```bash
> cd /home/fiod/medical && uv run python generate_paper.py
> ```
>
> **CRITICAL:** Never leave stale figures in the paper. A figure showing CCC=0.56 scatter when the text says CCC=0.868 is a fatal inconsistency. Every figure annotation must match every in-text reference.

---

## U-Step 3B: Regenerate ALL Tables (MANDATORY)

**This step is ALWAYS required.** Tables are hardcoded HTML in NEW.html, not generated by a script. Hand-editing table cells is error-prone. This step ensures every table cell matches the ground truth.

Launch a subagent to audit and fix every table:

```
Agent(description="Regenerate paper tables",
      prompt=<see below>,
      mode="bypassPermissions")
```

**Prompt:**
> You are a table verification and regeneration specialist. Your job is to ensure EVERY table in `/home/fiod/medical/NEW.html` has correct, up-to-date values matching the ground truth.
>
> Read:
> 1. `/home/fiod/medical/.paper_build/current_truth.md` — authoritative numbers
> 2. `/home/fiod/medical/NEW.html` — the manuscript (read table sections only)
>
> **Complete table inventory** (verify ALL are present):
>
> | Table | Content | Key verification points |
> |-------|---------|------------------------|
> | **Table 1** | Cohort demographics | N=178 (98 PD + 80 HC), age, sex, H&Y, dx years |
> | **Table 2** | Total UPDRS-III prediction | CCC, slope, MAE, r for each model, PD-only eval |
> | **Table 3** | 3-level observability decomposition | Baseline direct/partial/unobs CCC, slope, MAE |
> | **Table 4** | Severity-stratified prediction | Per-quartile metrics from FM LOOCV |
> | **Table 5** | Sensor reduction — 22-config screening | 5-split CCC/MAE/slope per config × T1/T2/T3, from `sensor_span_*_5split.json` |
> | **Table 5b** | Sensor reduction — definitive repeated CV | 10×5-fold mean±SD CCC for 4 key configs × 3 targets, non-inferiority verdicts (Nadeau-Bengio corrected), from `sensor_span_repeated_cv.json` |
> | **Table 5c** | FM decomposition | v2-only vs FM-only vs combined CCC for 4 configs × T1/T3, from `sensor_span_fm_decomposition.json` |
> | **Table 6** | Cross-dataset SOTA comparison | Our vs Hssayeni vs Shuqair, with N and eval protocol |
> | **Table 7** | SSL ranking results | 5 proposals × 3 targets, **eval protocol column (P0=5-split, P5=LOOCV)** |
> | **Table 8** | Quartile bias analysis | Q1-Q4 bias before/after SSL for T1 LOOCV |
> | **Table P1** | Hyperparameter specification | All pipeline configs (baseline, PD-only, SSL) |
> | **Table S1** | DL comparison | 5 architectures, all MAE > 10 |
> | **Table S2** | Holm-Bonferroni p-values | Corrected p-values for model comparisons |
>
> For EACH `<table>` in the HTML:
> 1. Extract every numeric cell value
> 2. Cross-check against current_truth.md
> 3. If ANY cell is stale or wrong, rewrite the ENTIRE table HTML using the Edit tool
> 4. Verify table captions reference the correct evaluation protocol (LOOCV vs 5-split vs 10-split)
> 5. Ensure column headers match the metrics actually shown
> 6. Verify N values in captions match the evaluation protocol
> 7. For Table 7: verify P0 and P5 rows have different eval protocol labels
> 8. For Table P1: verify hyperparameters match current code for ALL pipelines (not just one)
>
> **CRITICAL:** A table showing CCC=0.56 when the text says CCC=0.868 is a fatal inconsistency. Every cell must match every in-text reference to the same metric.

---

## U-Step 3C: Generation Script Integrity Audit (MANDATORY)

**This step is ALWAYS required.** The root cause of most paper inconsistencies is not in the HTML but in `generate_paper.py` itself — hardcoded values, mixed data sources, stale figure annotations. Fixing the HTML without fixing the script means the bugs return on the next regeneration.

Launch a subagent to audit the generation script:

```
Agent(description="Audit generate_paper.py for hardcoded values",
      prompt=<see below>,
      mode="bypassPermissions")
```

**Prompt:**
> You are a code auditor for `generate_paper.py`. Your job is to find and fix every instance where the script uses hardcoded result values instead of loading from JSON, every figure annotation that doesn't match its data source, and every mixed-source context.
>
> Read `/home/fiod/medical/generate_paper.py` completely.
>
> **Audit 1 — Hardcoded result values (Rule G1):**
> Search for literal numbers in the script that should come from JSON:
> - Grep for common metric values: `0.868`, `0.865`, `0.834`, `0.776`, `0.807`, `8.146`, `8.086`, `5.95`, `0.986`, `4.646`, `14.09`, `14.30`
> - Check every `_table*()` function — are table cells formatted from `d.xxx.get()` or hardcoded strings?
> - Check every `_draw_box()` call — are box labels data-driven?
> - Check every figure stats box / text annotation — does it use the same variable as the plot data?
> - Check inline prose in build_html_v2 — are demographics, bias values, etc. formatted from `dp`/`dc`/`p0_t3` dicts?
>
> **Audit 2 — Data source consistency (Rule G2):**
> For each table builder, verify all rows use the same analysis:
> - `_table_obs_5fold()` — does the direct row use the same source as partial/unobs rows? If not, is the footnote clear?
> - `_table6_cross_dataset()` — does it accept `d` parameter and use data-driven values for "our" rows?
> - `_table8_quartile_bias()` — do P0 and P5 rows use the same evaluation protocol?
>
> **Audit 3 — Figure annotation correctness (Rule G3):**
> For each `fig*()` function:
> - If the function selects data with `d.ssl_5split_t1 if d.ssl_5split_t1 else d.ssl_t1`, verify the protocol label also branches accordingly
> - Verify stats box text uses the same dict variables as the scatter/bar data
> - Verify figure suptitle protocol label matches the data shown
>
> **Audit 4 — Fabricated data (Rule G4):**
> Search for `rng.`, `random`, `np.random`, `synthetic` in figure functions. For each:
> - If used for synthetic scatter points when real data is unavailable → OK if labeled
> - If used to create fake result values → FAIL unless clearly labeled "Illustrative"
>
> **Audit 5 — Fallback defaults (Rule G5):**
> Grep for `.get("ccc",`, `.get("mae",`, `.get("r",`, `.get("cal_slope",`, `.get("n",` throughout the script. For each fallback default, verify it matches the most recent value in the corresponding JSON file.
>
> **Fix Protocol:**
> For every issue found, fix it directly in `generate_paper.py` using the Edit tool. Then re-run:
> ```bash
> cd /home/fiod/medical && uv run python generate_paper.py
> ```
> Verify it completes without errors.
>
> Write your audit report to `/home/fiod/medical/.paper_build/script_integrity_report.md` with:
> - Issues found per category (G1-G5)
> - Each fix applied (old code → new code, line number)
> - Any issues you could NOT fix (require new JSON data, ambiguous source)
> - Final status: CLEAN / ISSUES_REMAINING

---

## U-Step 4: Verification Review (1 subagent)

After all fixes are applied:

```
Agent(description="Verify paper update completeness",
      prompt=<see below>,
      mode="bypassPermissions")
```

**Prompt:**
> You are a final verification reviewer for an academic paper that was just updated incrementally. Your job is to ensure ZERO mistakes, ZERO leftovers, and ZERO inconsistencies remain.
>
> Read these files:
> 1. `/home/fiod/medical/NEW.html` — the updated manuscript
> 2. `/home/fiod/medical/.paper_build/current_truth.md` — ground truth
> 3. `/home/fiod/medical/.paper_build/update_diff.md` — changes that were made
>
> **Verification Protocol:**
>
> 1. **Number Consistency Scan**: Extract EVERY number from the HTML (CCC, slope, MAE, r, p-values, N, percentages). For each, verify it matches current_truth.md. Flag ANY mismatch.
>
> 2. **Protocol Consistency Scan**: For every result cited, verify the evaluation protocol is stated. Check that no LOOCV and 5-split results are presented as directly comparable without noting the difference. Check Table 7 specifically.
>
> 3. **Leftover Detection**: Search for:
>    - Old model names or configs that were replaced
>    - References to experiments that no longer exist
>    - Sentences that don't make sense given the updated numbers
>    - Orphaned figure/table references
>    - Broken cross-references (e.g., "as shown in Table X" where Table X was removed)
>    - Placeholder text (FIXME, TODO, TBD, XXX, "INSERT", "[CITATION]", "[Author names")
>    - Mixed-gradient claims (SSL direct + baseline partial in one gradient)
>
> 4. **Narrative Coherence**: After number updates, does the story still flow? Do conclusions still follow from the (now-updated) results? Does the abstract accurately summarize the (now-updated) paper?
>
> 5. **Table Audit**: For each table (1-8, P1, S1, S2), verify every cell value against current_truth.md. Verify eval protocol labels.
>
> 6. **Figure Audit**: For each figure (1-10, A-F), verify:
>    - The base64 image is valid (non-empty, starts with correct header)
>    - The caption matches the current data
>    - Any text-box annotations (CCC=, MAE=) in figures match the latest values
>    - The figure is referenced in the body text
>
> 7. **Cross-Section Consistency**: The same metric MUST have the same value everywhere it appears (abstract, results text, tables, figure captions, discussion).
>
> 8. **Appendix Completeness**: Verify Section 5 has all subsections (5.1-5.6), Table P1, and Figs A-F.
>
> 9. **Supplementary Completeness**: Verify Tables S1 and S2 are present and correct.
>
> **If issues found**: Fix them by editing NEW.html directly. Then do another scan.
> **If clean**: Report "VERIFIED: 0 issues remaining."
>
> Write verification report to `/home/fiod/medical/.paper_build/verification_report.md` with:
> - Total items checked
> - Issues found and fixed (categorized: numbers, protocol labels, leftovers, narrative, figures, tables, appendix)
> - Final status: CLEAN / ISSUES_REMAINING
> - Any items requiring HUMAN attention (author names, affiliations, funding, COI, IRB)

---

## U-Step 5: External Review Panel (MANDATORY — same as Scratch Step 3.5)

Run codex and gemini in parallel for writing/narrative review on the updated paper. Same commands as Step 3.5 above (extract text from `NEW.html`, run both CLIs). This step is REQUIRED — if either CLI fails, retry ONCE, then STOP and report to the user.

---

## U-Step 6: Final Polish Review (1 subagent)

Same as Scratch Subagent 4C (Review Cycle 3 — Polish & Reviewer-Proofing). Read the verification report AND any external feedback, apply final improvements. Use NEW.html as the manuscript file.

---

## U-Step 7: Report

Read:
- `/home/fiod/medical/.paper_build/update_diff.md`
- `/home/fiod/medical/.paper_build/verification_report.md`
- Any review/external feedback files

Report to user:
- Total changes made (categorized: stale numbers, missing results, leftovers removed, methods updated, protocol labels fixed, mixed-gradient fixes, figure updates, table updates)
- Verification result (CLEAN or remaining issues)
- External feedback summary
- Confidence level
- **Figure inventory**: all 10 main + 6 appendix figures confirmed present and current
- **Table inventory**: all 11 tables (1-8, P1, S1, S2) confirmed present and verified
- Location: `NEW.html`

Clean up: `rm -rf /home/fiod/medical/.paper_build/`
