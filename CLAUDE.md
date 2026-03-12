# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# PD-IMU

## Objective

**First published UPDRS-III regression on WearGait-PD.** No one has done this. We own the benchmark.

Domain: predicting Parkinson's Disease motor severity (MDS-UPDRS Part III total score, range 0-132) from body-worn IMU sensors during gait/balance tasks. The dataset has 178 subjects total, 13 IMUs at 100Hz, and full clinical UPDRS scores.

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

None of the published work uses our dataset, our cohort size, or our evaluation rigor. Comparisons are necessarily cross-dataset.

| Tier | Overall MAE | PD-only MAE | What it means |
|------|-------------|-------------|---------------|
| **Publishable** | any | any | First WearGait-PD regression with proper eval is novel by itself |
| **Cross-dataset SOTA** | < 7.0 | < 5.95 | Beats Hssayeni PD-only MAE on 7x subjects with held-out test |
| **Clinical SOTA** | < 3.25 | < 3.25 | Within MCID (Horvath 2015) — errors below clinical noise |

Reality check: total UPDRS-III has unobservable items (rigidity, speech, facial expression). Ceiling from gait IMU alone is likely MAE ~8-10 on a clean evaluation. Observable axial subdomain (gait+posture+lower limb items) may reach MAE ~2-3 but needs revalidation.

## Current Results

### Best: FM Stack (10-split CV, 2026-03-11)

| Model | 10-split Mean ± Std | p vs v2 |
|-------|--------------------|---------|
| **FM Stack (v2+MOMENT)** | **7.775 ± 0.439** | **0.0039** |
| Ultimate (v2+RK+FM+coord) | 7.897 ± 0.529 | 0.020 |
| Triple (v2+RK+FM) | 7.940 ± 0.559 | 0.037 |
| v2 LGB baseline | 8.485 ± 0.497 | — |
| PD-only LOOCV (FM) | 8.147 (N=98) | 0.042 |

Observable subdomain (items 7-14): FM+v2 stack **3.015 ± 0.443** (below MCID 3.25).

### Clean held-out test (post-contamination audit, 2026-03-09)

Outer split: `results/paper3_split.json` — 142 dev + 36 test, seed=20260309. See CONT.md for full audit.

| Model | MAE | r | Role |
|-------|-----|---|------|
| LGB baseline (S0_K150) | 9.47 | 0.605 | clean baseline |
| **Deployable stack (S6_K150)** | **9.68** | **0.579** | **pre-specified primary** |
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
# Environment
uv sync                                    # install deps (local, for tests/paper gen)

# Run experiments (on GPU slave)
./gpu.sh run_rocket_ablation.py --phase 2  # deploy code + run on remote GPU
./gpu.sh --pull                            # fetch results back to ./results/
./gpu.sh --status                          # check GPU + running jobs

# Tests (local)
uv run pytest tests/ -v                    # all tests
uv run pytest tests/test_data_split.py -v  # single test file

# Paper generation (local, reads from results/)
uv run python generate_paper.py            # generate paper HTML
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

Cross-import exception: `run_clean_benchmark.py` imports from `run_ablation_v2.py` and `run_proven_stack.py` for feature extraction functions. No other cross-imports between `run_*.py` files.

**Execution model:** Code lives on this machine (MASTER). `gpu.sh` rsyncs to the remote GPU slave, runs there, and `--pull` fetches results back. The remote has the 52GB dataset at `data/raw/weargait-pd/`.

**Feature extraction tiers:** v2 handcrafted (statistical, spectral) → MiniRocket (5000 temporal kernels) → MOMENT-1-base (frozen 768-dim FM embeddings). FM beats all others — adding ROCKET to FM actually hurts (dilutes signal at K=400).

## Infrastructure

**This machine = MASTER** (code, git). **Remote = disposable GPU slave.**

```bash
./gpu.sh run_something.py       # deploy + run
./gpu.sh --pull                  # fetch results
./gpu.sh --status                # GPU + jobs
./gpu.sh --log                   # tail log
./gpu.sh --ssh                   # shell in
./gpu.sh --setup                 # provision new slave
./gpu.sh --nuke                  # kill jobs
```

Swap servers: `export GPU_REMOTE=root@x.x.x.x GPU_PORT=22 && ./gpu.sh --setup`

Current slave: `root@46.228.83.78:40005`, RTX 5060 Ti 16GB, PyTorch cu128.

## Files

**Shared modules:**
```
data_split.py           # Clinical parsing, windowing, split creation (ONLY shared data module)
project_paths.py        # Centralized artifact paths with env overrides (WEARGAIT_DATA_DIR, etc.)
updrs_columns.py        # Robust UPDRS subitem column resolution across naming variants
```

**Primary experiment scripts:**
```
run_rocket_ablation.py  # ROCKET + FM + coordination ablation (phases 0-9, current best)
run_clean_benchmark.py  # Clean eval on fresh split (primary for Paper3)
run_proven_stack.py     # Stack variants (exploratory, test set NOT pristine)
run_ablation_v2.py      # v2 feature extraction baseline (imported by run_clean_benchmark)
run_ablation_v3.py      # v3 ablation (5 phases)
```

**Supplementary experiment scripts:**
```
run_sensor_ablation.py  # Corrected sensor ablation (no dst_ by default)
run_loocv_stack.py      # Corrected nested LOOCV (feature selection inside loop)
run_stats_report.py     # Corrected stats (uses actual stack, dynamic best model)
run_dl_experiments.py   # DL experiments (TEST_TASKS = ALL_TASKS)
run_dl_rebenchmark.py   # DL rebenchmark on fresh split
run_subdomain.py        # Subdomain analysis (corrected UPDRS resolution)
run_subdomain_v3.py     # v3 subdomain prediction (obs vs unobs)
run_v3_experiments.py   # Exploratory experiments (corrected UPDRS resolution)
run_followup_v3.py      # Follow-up experiments
run_biomechanics.py     # Biomechanical feature extraction
run_shap_explain.py     # SHAP feature importance analysis
run_transfer.py         # Cross-dataset transfer validation
run_pads_varghese.py    # PADS benchmark reproduction
run_paper_supplements.py # Supplementary analyses for paper
```

**Paper generation:**
```
generate_paper.py       # Main paper HTML generator
generate_html_paper3.py # Paper3 HTML generator
paper3_data.py          # Paper data artifact preparation
paper_figures_v2.py     # Figure generation
paper_refs.py           # Reference management
paper2_renderer.py      # Alternate renderer
```

**Infra:**
```
gpu.sh                  # Master/slave deploy, pull results, manage remote jobs
synapse_download.py     # Download WearGait-PD from Synapse
```

## Rules

- **NEVER per-subject z-normalize for regression** — amplitude IS severity
- **NEVER amplitude-scale augmentation** — destroys severity signal
- **ALWAYS subject-level splits** — window-level leaks
- **ALWAYS multi-seed** (3-5 seeds) — single seed is noise at N=178
- **ALWAYS report PD-only MAE alongside overall** — HC inflates metrics
- **NEVER reuse clean test split for model search** — this caused the original 6.89 contamination
- **NEVER promote a sensitivity-check winner as new primary** — recreates contamination cycle
