# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

PD-IMU: Predicting Parkinson's Disease severity (MDS-UPDRS-III) from body-worn IMU sensors. Primary dataset is WearGait-PD (178 subjects, 13 IMUs @ 100Hz). Secondary benchmark on PADS (469 subjects, wrist smartwatch). Goal: beat published SOTA while maintaining honest evaluation (proper train/test split, multi-seed reporting).

**Current best:** cross-config ensemble MAE=8.72, r=0.680 on 36 held-out test subjects.

## Remote Server

```bash
ssh -p 40005 root@46.228.83.78 -L 8080:localhost:8080
```

- GPU: RTX 5060 Ti (Blackwell sm_120), 16.6GB VRAM, PyTorch 2.10.0+cu128
- Server project path: `/root/pd-imu/`
- 49GB RAM, 11 cores, 126GB disk
- Dependencies installed globally (no venv)

## Workflow

Files are written locally in `/home/fiod/medical/`, then SCP'd to server for execution:
```bash
scp -P 40005 <script>.py root@46.228.83.78:/root/pd-imu/
ssh -p 40005 root@46.228.83.78 "cd /root/pd-imu && python <script>.py"
```

## Repository Layout

### Local (`/home/fiod/medical/`)
```
# Core modules (flat naming, mapped to server src/ tree)
src_data_dataset.py          # IMUSegment dataclass, load_gaitpdb(), load_pads(), window_segments()
src_data_pads_loader.py      # PADSRecord/PADSSubject dataclasses, JSON+CSV PADS loader
src_data_gait_features.py    # 15 clinical gait features
src_models_imu_encoder.py    # Patch-embedded Transformer + multi-task heads (1.64M params)
src_models_neural_ekf.py     # Differentiable EKF (26.5K params)
src_models_pretrain.py       # MIM (75% mask, MAE-style) + ContrastiveIMU (1.80M params)
src_models_cnn1d.py          # ResBlock1D CNN + InceptionTime1D (5.67M params)
src_models_baseline.py       # XGBoost/RF with LOSO CV

# Experiment runners (each is self-contained end-to-end)
run_weargait_baseline.py     # RF on 68 handcrafted features (SelfPace, wrist+lback)
run_weargait_cnn.py          # 1D-CNN on raw wrist IMU
run_weargait_transformer.py  # Multi-task Transformer (classification + regression)
run_weargait_regressor.py    # Dedicated UPDRS-III regression Transformer
run_mim_pretrain.py          # MIM self-supervised pretraining
run_mim_regressor.py         # MIM pretrained → fine-tune for regression
run_neural_ekf.py            # Neural EKF for UPDRS regression
run_experiments.py           # Combined experiments with proper 3-way split
run_ablation.py              # 23-experiment ablation (sensors, scale, data, patch, arch)
run_robust.py                # Multi-seed evaluation (5 configs x 5 seeds)
run_ultimate.py              # Best config multi-seed
run_subitem.py               # UPDRS subitem decomposition (negative result)
run_pads_varghese.py         # PADS Varghese et al. 2024 benchmark reproduction
run_pads_experiment.py       # PADS classification (XGBoost + CNN baselines)
run_gaitpd_baseline.py       # Gait-PD foot force baselines
data_split.py                # Stratified train/val/test split → data_split.json
synapse_download.py          # WearGait-PD download from Synapse
```

### Server (`/root/pd-imu/`)
```
src/data/                    # dataset.py, pads_loader.py, gait_features.py
src/models/                  # imu_encoder.py, neural_ekf.py, pretrain.py, cnn1d.py, baseline.py
src/training/                # train.py
data/raw/gait-pd/            # 166 subjects, foot force sensors
data/raw/pads/               # 469 subjects, wrist smartwatch IMU
data/raw/weargait-pd/        # 52GB, 101 PD + 86 HC, 13 IMUs @ 100Hz
data_split.json              # 142 dev + 36 test, stratified by UPDRS bins
```

## Architecture

Four model tiers:

1. **Feature baselines** (`baseline.py`): XGBoost/RF on handcrafted gait features, LOSO CV
2. **CNN** (`cnn1d.py`): ResBlock1D on raw 6-axis windows
3. **Transformer** (`imu_encoder.py`): Patch-embedded CLS-token Transformer, multi-task heads (H&Y, UPDRS, PD/HC, medication). Scalable from medium (256d/6L, 6.5M) to xxl (768d/10L, 86M)
4. **Neural EKF** (`neural_ekf.py`): Differentiable EKF tracking [gait_phase, tremor, bradykinesia, asymmetry]

Self-supervised pretraining (`pretrain.py`): MIM (reconstruct masked patches) or contrastive (InfoNCE).

## Datasets

| Dataset | N | Sensors | Labels | Status |
|---------|---|---------|--------|--------|
| **WearGait-PD** | 187 (101 PD + 86 HC) | 13 body IMUs @ 100Hz | Full UPDRS Parts 1-4, H&Y | Downloaded (52GB) |
| **PADS** | 469 (276 PD + 79 HC + 114 DD) | Wrist smartwatch 6-axis @ 100Hz | ICD-10 diagnosis only | Downloaded (1.4GB) |
| **Gait-PD** | 166 | Foot force sensors | PD/HC/neuro | Downloaded |
| **mPower** | 9.5K | Phone accelerometer | PD self-report | Requires Synapse access |
| **PPMI** | — | Longitudinal clinical | Gold-standard | Requires application |

### WearGait-PD Details
- **Sensor locations**: LowerBack, R/L_Wrist, R/L_MidLatThigh, R/L_LatShank, R/L_DorsalFoot, R/L_Ankle, Xiphoid, Forehead
- **Channels per sensor (22 each)**: Acc_XYZ, FreeAcc_ENU (global frame), Gyr_XYZ, Mag_XYZ, VelInc_XYZ, OriInc_q0123, Roll/Pitch/Yaw
- **Total columns**: 347 (286 IMU + 2 foot contact + 5 walkway + 50 insole + 4 events)
- **Currently using**: 78/347 (Acc_XYZ + Gyr_XYZ only). FreeAcc, Euler, Mag, VelInc, OriInc all unused.
- **Key unused data**: FreeAcc_E/N/U (gravity-removed global-frame accel), Roll/Pitch/Yaw (Euler angles), L/R Foot Contact (binary gait events), GeneralEvent (Walk/Turn/Sitting/SitToStand/TurnToSit)
- **Walkway metrics**: 135 subjects, 196 pre-computed gait parameters (step/stride length, velocity, cadence, stance/swing %, double support, COP, eGVI)
- **Insole data**: 174/185 subjects in _mat files, sparse within files
- **Tasks**: Balance, SelfPace, HurriedPace, TUG, TandemGait + _mat (on walkway) + _matTURN variants
- **File naming**: `{SubjectID}_{Task}.csv`
- **Clinical CSVs**: `PD - Demographic+Clinical - datasetV1.csv`, `CONTROLS - Demographic+Clinical - datasetV1.csv`
- **Clinical covariates**: Age, Sex, Height, Weight, Years since PD dx, Medications, DBS, H&Y, full UPDRS items 3-1 through 3-18

### PADS Details
- **Excluded tasks** (from official code): LiftHold, PointFinger, TouchIndex
- **Split tasks**: Relaxed, RelaxedTask, Entrainment split into halves (11 segments total)
- **Features**: 31 per channel (19 log10-PSD via Welch + 4 std + 4 abs_energy + 4 abs_max)
- **Vibration artifact removal**: 48 samples (not 50)
- **Two SEPARATE binary classifiers**: PD/HC and PD/DD (not 3-class)

## Key Results

| Experiment | MAE | r | Notes |
|-----------|-----|---|-------|
| Cross-config ensemble | **8.72** | **0.680** | Honest best (5 configs, 5 seeds each) |
| Medium Transformer (ens) | 9.35 | 0.602 | Most reliable single config |
| xxl Transformer (ens) | 9.39 | 0.602 | Best mean r but high variance |
| xxl lucky seed | 8.44 | 0.723 | NOT reproducible (seed dependent) |
| PADS Varghese stacked | — | — | 90.86% PD/HC, 73.67% PD/DD bal. acc. |

## Critical Rules

- **NEVER per-subject z-normalize for regression** -- amplitude IS severity signal
- **NEVER use amplitude scaling augmentation** -- destroys severity-correlated info
- **ALWAYS 3-way split**: train (early stop val) / test (final metrics only)
- **ALWAYS report multi-seed results** -- single seed is unreliable at N=178
- **Subject-level splits only** -- window-level leaks same-subject data
- RTX 5060 Ti needs PyTorch 2.8+ with cu128 (sm_120 Blackwell)
- WearGait-PD MAT files are unusable -- always use CSVs
- PADS PhysioNet slug: `parkinsons-disease-smartwatch`

## Current Phase: 4 (Recipe & Methodology Fixes)

Priority order (from GPT-5.4/Codex analysis):
1. **Global normalization** -- train-set stats, not per-subject (expected ~1-2 MAE)
2. **Subject-level MIL** -- attention pooling, subject-level loss (fixes seed variance)
3. **Hybrid features + CatBoost** -- handcrafted + learned + covariates
4. **Two-stage model** -- PD/HC gate then PD-only regressor (fair SOTA comparison)
5. **Task-aware features** -- TUG subphases, balance sway, cadence reserve

See `task_plan.md` for detailed phase breakdown, `findings.md` for literature review, `progress.md` for session logs.
