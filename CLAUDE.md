# PD-IMU

## Objective

**First published UPDRS-III regression on WearGait-PD.** No one has done this. We own the benchmark.

Domain: predicting Parkinson's Disease motor severity (MDS-UPDRS Part III total score, range 0-132) from body-worn IMU sensors during gait/balance tasks. The dataset has 178 subjects (101 PD + 86 HC), 13 IMUs at 100Hz, full clinical UPDRS scores.

## SOTA Landscape

No published UPDRS-III regression exists on WearGait-PD. Cross-dataset comparisons:

**Hssayeni et al. 2021 (BioMed Eng OnLine)** — best reported MAE
- 24 PD patients, wrist+ankle gyro, free-body ADL, ensemble of 3 DL models
- LOOCV: **MAE=5.95, r=0.74**
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

Reality check: total UPDRS-III has unobservable items (rigidity, speech, facial expression). Ceiling from gait IMU alone is MAE ~6-7. Observable axial subdomain (gait+posture+lower limb items) can reach MAE ~2-3.

**Current best: MAE=6.89, r=0.860** (LGB+XGB stacking on 150 features, XGBoost importance selection, 5-seed ensemble, 36 held-out test subjects). Ceiling with H&Y: MAE=6.43, r=0.848 (stacking + H&Y, K=160).

## Data: WearGait-PD

On remote at `data/raw/weargait-pd/` (52GB). Split: `data_split.json` — 142 dev + 36 test, stratified by UPDRS bins.

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

```
data_split.py           # Shared data loading (ONLY shared module)
run_ablation.py         # 23-config ablation reference
run_ultimate.py         # Best config multi-seed eval
run_recipe_fix_v2.py    # Global norm + recipe fixes
run_biomechanics.py     # Biomechanical feature extraction
run_pads_varghese.py    # PADS benchmark reproduction
run_pads_experiment.py  # PADS classification
run_gaitpd_baseline.py  # Gait-PD benchmarks
synapse_download.py     # Dataset download
gpu.sh                  # Master/slave deploy
```

Each `run_*.py` is self-contained. No cross-imports. Only `data_split.py` is shared.

## Rules

- **NEVER per-subject z-normalize for regression** — amplitude IS severity
- **NEVER amplitude-scale augmentation** — destroys severity signal
- **ALWAYS subject-level splits** — window-level leaks
- **ALWAYS multi-seed** (3-5 seeds) — single seed is noise at N=178
- **ALWAYS report PD-only MAE alongside overall** — HC inflates metrics
