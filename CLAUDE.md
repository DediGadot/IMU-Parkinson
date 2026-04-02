# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# PD-IMU

## Objective

**First published UPDRS-III regression on WearGait-PD.** No one has done this. We own the benchmark.

Domain: predicting Parkinson's Disease motor severity (MDS-UPDRS Part III total score, range 0-132) from body-worn IMU sensors during gait/balance tasks. The dataset has 178 subjects (98 PD + 80 HC), 13 IMUs at 100Hz, and full clinical UPDRS scores.

**Paper's core contribution:** 3-level observability gradient. IMU predicts gait-observable items well (CCC=0.87), partially observable items poorly (CCC=0.12), unobservable items not at all (CCC=0.18). The SSL ranking method (using HC as calibration anchors) is the key methodological innovation.

## SOTA Landscape

No published UPDRS-III regression exists on WearGait-PD. Cross-dataset comparisons:

**Hssayeni et al. 2021 (BioMed Eng OnLine)** — best reported MAE
- 24 PD patients, wrist+ankle gyro, free-body ADL, ensemble of 3 DL models
- LOOCV: **MAE=5.95, r=0.79**
- Limitation: N=24 PD-only, LOOCV (not held-out test), free-body ADL (not controlled gait)

**Shuqair et al. 2024 (Bioengineering)** — best reported correlation
- Same 24 PD patients/dataset as Hssayeni, self-supervised CNN-LSTM
- LOOCV: **r=0.89, MAE~5.65**
- Limitation: same N=24 PD-only dataset, LOOCV, benefits from SSL on tiny data

**Disqualified results:**
- IS22 (Sotirakis 2022): MAE=4.26 — **confirmed window-level data leakage** (same group got RMSE=10.02 with subject-level CV in Sotirakis 2023)
- Sotirakis 2023 (npj PD): RMSE=10.02 — 74 PD, 7 visits, 5-fold CV over visit-level rows leaks within-subject data across folds
- He 2024 (JNER): predicts **levodopa response** (medication effect), NOT UPDRS-III total — GPT-5.4/Codex hallucinated this as a UPDRS regression paper; manually verified via web search 2026-03-08
- Park 2025 (JNER): MAE=0.76 on z-normalized targets — meaningless raw-point units, subject leakage likely (2 visits, split over "samples")

**WearGait-PD prior art:** TRIP (arXiv 2025) is the only published use — classification only (80.07% IMU accuracy), no regression.

**Sources (verified 2026-03-08):**
- Hssayeni 2021: https://pubmed.ncbi.nlm.nih.gov/33789666/
- Shuqair 2024: https://www.mdpi.com/2306-5354/11/7/689
- Sotirakis 2023: https://www.nature.com/articles/s41531-023-00581-2
- He 2024 (levodopa, NOT UPDRS): https://link.springer.com/article/10.1186/s12984-024-01452-4
- WearGait-PD dataset: https://www.nature.com/articles/s41597-026-06806-2
- TRIP 2025 (classification only): https://arxiv.org/html/2510.15748v1

## The Bar

| Tier | Overall MAE | PD-only MAE | What it means |
|------|-------------|-------------|---------------|
| **Publishable** | any | any | First WearGait-PD regression with proper eval is novel by itself |
| **Cross-dataset SOTA** | < 7.0 | < 5.95 | Beats Hssayeni PD-only MAE on 7x subjects with held-out test |
| **Clinical SOTA** | < 3.25 | < 3.25 | Within MCID (Horvath 2015) — errors below clinical noise |

Reality check: total UPDRS-III has unobservable items (rigidity, speech, facial expression). Ceiling from gait IMU alone is likely MAE ~8-10 on clean evaluation. Observable axial subdomain (gait+posture+lower limb items) can reach MAE ~1.0 with SSL ranking.

## Current Results (2026-03-15)

### Best: P5 SSL Ranking (PD-only LOOCV, N=94)

XGBRanker trained on ALL subjects (PD+HC, N=178) → leaf indices as features → LightGBM on PD-only. HC subjects serve as "known-zero" calibration anchors. Script: `run_compression_ablation.py --phase 5`.

| Target | Items | CCC | slope | MAE | r |
|--------|-------|-----|-------|-----|---|
| **T1 (direct obs)** | 9-14 | **0.868** | 0.689 | 0.986 | 0.899 |
| **T2 (broad obs)** | 7-14 | **0.852** | 0.699 | 1.334 | 0.873 |
| **T3 (total UPDRS)** | all | **0.776** | 0.576 | 4.646 | 0.827 |

### 3-Level Observability Gradient (paper's core table)

| Subscore | Items | MAE | CCC | r |
|----------|-------|-----|-----|---|
| **Direct observable** | 9-14 | **1.77** | **0.56** | **0.667** |
| Partially observable | 5-8, 15-17 | 4.89 | 0.12 | 0.169 |
| Not observable | 1-4, 18 | 3.94 | 0.18 | 0.290 |

### Pre-SSL baselines (10-split CV, 2026-03-11)

| Model | 10-split Mean ± Std | p vs v2 |
|-------|--------------------|---------|
| FM Stack (v2+MOMENT) | 7.775 ± 0.439 | 0.0039 |
| v2 LGB baseline | 8.485 ± 0.497 | — |

### Clean held-out test (post-contamination audit, 2026-03-09)

Split: `results/paper3_split.json` — 142 dev + 36 test, seed=20260309. See CONT.md for full audit.

| Model | MAE | r | Role |
|-------|-----|---|------|
| LGB baseline (S0_K150) | 9.47 | 0.605 | clean baseline |
| Deployable stack (S6_K150) | 9.68 | 0.579 | pre-specified primary |
| H&Y ceiling | 8.22 | 0.705 | upper bound with clinical staging |

**The old MAE=6.89 result was contaminated by adaptive test-set reuse (~2.8 MAE inflation). Do not cite it.**

## Data: WearGait-PD

On remote at `data/raw/weargait-pd/` (52GB). Clean split: `results/paper3_split.json` (seed=20260309).

**Per sensor (13 sensors, 22 channels each = 286 IMU channels):**

| Channels | Count | Used | Priority |
|----------|-------|------|----------|
| Acc_XYZ, Gyr_XYZ | 78 | YES | — |
| FreeAcc_E/N/U (gravity-removed, global frame) | 39 | NO | HIGH — clinical standard |
| Roll/Pitch/Yaw (Euler angles) | 39 | NO | HIGH — trunk lean, arm swing |
| Mag_XYZ, VelInc_XYZ, OriInc_q0123 | 130 | NO | LOW |

**Additional modalities (already downloaded):**
- Foot Contact events (binary heel-strike/toe-off) — ALL non-mat files
- GeneralEvent annotations (Walk/Turn/Sitting/SitToStand) — ALL files
- Walkway gait metrics (196 pre-computed params) — 135/178 subjects
- Clinical covariates: Age, Sex, Height, Weight, Years since PD dx, Medications, DBS, H&Y, full UPDRS items

**Tasks:** SelfPace, HurriedPace, TUG, Balance, TandemGait + _mat/_matTURN variants.

## Commands

```bash
# Environment (local — only matplotlib, numpy, pandas, scipy)
uv sync                                    # install deps (local, for tests/paper gen)

# Run experiments (on GPU slave — has torch, lightgbm, xgboost, momentfm, etc.)
./gpu.sh run_compression_ablation.py --phase 5  # deploy code + run on remote GPU
./gpu.sh --pull                            # fetch results back to ./results/
./gpu.sh --status                          # check GPU + running jobs
./gpu.sh --push-cache                      # upload cached features to remote

# Autoresearch (autonomous HP search loop)
./gpu.sh autoresearch_eval.py --baseline   # compute MAE baseline (once)
./gpu.sh autoresearch_eval.py              # run current config from autoresearch_config.py
./gpu.sh autoresearch_ccc_eval.py --baseline  # compute CCC baseline (once)
./gpu.sh autoresearch_ccc_eval.py          # run CCC-optimized config

# Tests (local)
uv run pytest tests/ -v                    # all tests
uv run pytest tests/test_data_split.py -v  # single test file

# Paper generation (local, reads from results/)
uv run python generate_paper.py            # generate paper HTML → NEW.html
uv run python paper3_data.py               # prepare paper data artifacts
```

## Architecture

**Pattern: shared modules + self-contained experiment scripts.**

Three shared modules provide data/paths/UPDRS resolution — everything else is a standalone `run_*.py` script that does its own feature extraction, model training, and evaluation end-to-end:

```
data_split.py       ← shared: clinical parsing, windowing, split creation
project_paths.py    ← shared: all artifact paths, env overrides (WEARGAIT_*)
updrs_columns.py    ← shared: UPDRS subitem column name resolution

run_*.py            ← self-contained experiments (import only the 3 above)
```

**Cross-import exceptions:** `run_clean_benchmark.py`, `run_ablation_v3.py`, and `run_paper_supplements.py` import feature extraction functions from `run_ablation_v2.py` and `run_proven_stack.py`. No other cross-imports between `run_*.py` files.

**Execution model:** Code lives on this machine (MASTER). `gpu.sh` rsyncs to the remote GPU slave, runs there, and `--pull` fetches results back. The remote has the 52GB dataset at `data/raw/weargait-pd/`.

**Feature extraction tiers:**

| Tier | Approach | Dim | Best for |
|------|----------|-----|----------|
| v2 | Handcrafted (statistical + spectral) | ~1752 | Observable subscore |
| ROCKET | MiniRocket (5000 temporal kernels) | 5000 | Hurts when added to FM |
| FM | MOMENT-1-base (frozen 768-dim) | 768 | Total UPDRS |
| SSL Ranking | XGBRanker leaf indices (PD+HC) | ~200 | All targets (breakthrough) |

**Cached artifacts on remote** (reused across experiments):
- `results/ablation_v3_features.csv` — pre-computed v2 handcrafted features
- `results/fm_embeddings.npz` — MOMENT-1-base frozen embeddings (deterministic, no SIDs)
- `results/rocket_recordings.npz` — recording-level SIDs (use this for SID lookup, not FM cache)
- `results/velinc_features.csv`, `results/velinc_gated_features.csv` — VelInc channel features
- `results/per_item_scores.json` — all 18 UPDRS items per subject
- `results/obs_direct_subscores.json` — ground truth items 9-14

## Infrastructure

**This machine = MASTER** (code, git). **Remote = disposable GPU slave.**

```bash
./gpu.sh run_something.py       # deploy + run
./gpu.sh --pull                  # fetch results
./gpu.sh --push-cache            # upload cached features
./gpu.sh --status                # GPU + jobs
./gpu.sh --log                   # tail log
./gpu.sh --ssh                   # shell in
./gpu.sh --setup                 # provision new slave
./gpu.sh --nuke                  # kill jobs
```

Swap servers: `export GPU_REMOTE=root@x.x.x.x GPU_PORT=22 && ./gpu.sh --setup`

Current slave: `root@142.170.89.112:37397`, PyTorch cu128.

## Files

**Shared modules:**
```
data_split.py           # Clinical parsing, windowing, split creation (ONLY shared data module)
project_paths.py        # Centralized artifact paths with env overrides (WEARGAIT_DATA_DIR, etc.)
eval_utils.py           # Shared metrics (lins_ccc, cal_slope), feature selection, bootstrap CIs
updrs_columns.py        # Robust UPDRS subitem column resolution across naming variants
```

**Primary experiment scripts:**
```
run_compression_ablation.py # Anti-compression proposals × 3 targets: ordinal, pairwise, SMOGN, NGBoost, SSL ranking
run_pd_only_experiments.py  # 7-phase PD-only experiments (10-split, LOOCV, 3-level observability, held-out)
run_calibration_ablation.py # Calibration-fix ablation (--target total|obs, residual modeling)
run_rocket_ablation.py      # ROCKET + FM + coordination ablation (phases 0-9)
run_obs_bias_ablation.py    # Walkway/task-specific/VelInc ablation for observable subscore
run_clean_benchmark.py      # Clean eval on fresh split (primary for Paper3)
run_proven_stack.py         # Stack variants (exploratory, test set NOT pristine)
run_ablation_v2.py          # v2 feature extraction baseline (imported by other scripts)
run_ablation_v3.py          # v3 ablation (5 phases)
run_step_function.py        # Step-function analysis
```

**Autoresearch (autonomous HP search):**
```
autoresearch_config.py      # ONLY file the agent modifies — knobs for features, HP, ensemble strategy
autoresearch_eval.py        # Fixed MAE evaluation harness — DO NOT MODIFY
autoresearch_ccc_eval.py    # Fixed CCC evaluation harness with feature group selection — DO NOT MODIFY
autoresearch_program.md     # Agent instructions for the autoresearch loop
autoresearch_results.tsv    # Append-only log of MAE experiment outcomes
autoresearch_ccc_results.tsv # Append-only log of CCC experiment outcomes
```

**Paper generation:**
```
generate_paper.py       # Main paper HTML generator (182 KB) → outputs NEW.html
paper.tex               # LaTeX version of the manuscript
paper_figures_v2.py     # Figure generation
paper_refs.py           # Reference management
paper3_data.py          # Paper data artifact preparation
```

**Supplementary experiment scripts:**
```
run_sensor_ablation.py  # Corrected sensor ablation (FM re-extracted per config, no leakage)
run_loocv_stack.py      # Corrected nested LOOCV (feature selection inside loop)
run_stats_report.py     # Corrected stats (uses actual stack, dynamic best model)
run_dl_experiments.py   # DL experiments (all architectures failed, see What Failed)
run_subdomain.py        # Subdomain analysis (corrected UPDRS resolution)
run_subdomain_v3.py     # v3 subdomain prediction (obs vs unobs)
run_shap_explain.py     # SHAP feature importance analysis
run_transfer.py         # Cross-dataset transfer validation
run_biomechanics.py     # Biomechanical feature extraction
run_paper_supplements.py # Supplementary analyses for paper
cache_extra_features.py # Caches VelInc, VelInc-gated, walkway features
```

**Infra:**
```
gpu.sh                  # Master/slave deploy, pull results, manage remote jobs
synapse_download.py     # Download WearGait-PD from Synapse
```

**Remote-only dependencies** (installed via `gpu.sh --setup`, NOT in pyproject.toml):
torch, torchvision, lightgbm, xgboost, momentfm, sktime (MiniRocket), tslearn

## Gotchas

- **FM embedding aggregation:** `fm_embeddings.npz` has recording-level data with no SIDs. Must use `rocket_recordings.npz["sids"]` as the subject mapping to aggregate per-subject.
- **Two split files:** `data_split.json` (old, seed=42, CONTAMINATED) vs `paper3_split.json` (clean, seed=20260309). Always use `paper3_split.json`.
- **Feature selection inside folds:** XGB importance-based selection (K=500) must be computed per fold, not once on all data, to prevent leakage.
- **LightGBM device='gpu' is 2.2x SLOWER than CPU** for N<200. Always use CPU.
- **Demographics are competitive on total UPDRS:** Ridge on age/sex/dx_yrs beats IMU (7.44 vs 8.37). IMU signal is real but partial (r=0.36, p=0.0003 after partialing out demographics).
- **SSL ranking uses HC for representation, NOT evaluation.** Final eval must always be PD-only.

## What Failed (DO NOT RETRY)

- All handcrafted feature groups (stride-var, asymmetry, nonlinear, frequency, interactions)
- End-to-end DL (5 architectures), item decomposition (52% worse)
- MoE/severity stratification, cross-sensor coordination, two-stage, HP sweeps
- FoG transfer (AUC=0.500, only 14/182 FoG+)
- Post-hoc calibration (isotonic/Platt/linear/polynomial) — predictions lack variance
- Euler/FreeAcc channel expansion — marginal, not worth complexity
- Severity-weighted + residual combination — no additive effect
- Embedded demographics as features — tree model ignores them
- Walkway metrics for obs subscore — redundant with v2 features
- Task-specific ensemble for obs — worse than all-task pooling
- Per-item ordinal + temperature sharpening — CCC=0.338, catastrophic
- NGBoost Poisson distributional — CCC=0.671, no improvement over tuned LGB
- Pairwise contrastive boosting — slow and mediocre (CCC~0.62)

## Memento-Skills (GLM-5 Agent)

Self-evolving agent framework at `~/memento/Memento-Skills/`. Uses GLM-5 via `api.z.ai`. Config: `~/memento_s/config.json`.

**Setup:**
```bash
cd ~/memento/Memento-Skills && source .venv/bin/activate
```

**Commands:**
```bash
memento doctor                                    # verify environment
memento agent                                     # interactive chat
memento agent -m "prompt"                         # single-shot query
memento agent -s <session_id>                     # resume session
```

**Built-in skills (9):** filesystem, web-search, pdf, docx, xlsx, pptx, image-analysis, skill-creator, uv-pip-install.

**How it works:** Intent classification (DIRECT/AGENTIC) → skill retrieval → sandboxed execution via `uv` → reflection → skill rewrite. Skills are `SKILL.md` files in `~/memento_s/skills/`. The `skill-creator` meta-skill generates new skills from scratch with automated test gates.

**Using with this codebase:**
```bash
# Read and analyze code
memento agent -m "Read /home/fiod/medical/run_compression_ablation.py and explain the SSL ranking"

# Create a custom skill for recurring tasks
memento agent -m "Create a skill that reads results/*.json and summarizes experiment metrics"
```

**Key paths:**
- Skills: `~/memento_s/skills/`
- Database: `~/memento_s/db/memento_s.db`
- Workspace: `~/memento_s/workspace/`
- Config: `~/memento_s/config.json` (model=`anthropic/glm-5`, base_url=`https://api.z.ai/api/anthropic`)

**Fix applied:** `litellm.modify_params = True` in `~/memento/Memento-Skills/middleware/llm/client.py` — required for tool-calling to work with the Anthropic provider adapter.

## Rules

- **NEVER per-subject z-normalize for regression** — amplitude IS severity
- **NEVER amplitude-scale augmentation** — destroys severity signal
- **ALWAYS subject-level splits** — window-level leaks
- **ALWAYS multi-seed** (3-5 seeds) — single seed is noise at N=178
- **ALWAYS report PD-only MAE alongside overall** — HC inflates metrics
- **NEVER reuse clean test split for model search** — this caused the original 6.89 contamination
- **NEVER promote a sensitivity-check winner as new primary** — recreates contamination cycle
- **ALWAYS verify SOTA claims from LLMs against actual papers** — multiple hallucinated citations found
