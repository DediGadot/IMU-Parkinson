---
description: Evaluate WearGait-PD trained model on external PD-IMU datasets for cross-dataset transfer validation.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch]
argument-hint: [dataset-name]
---

# Cross-Dataset Validation

Test whether models trained on WearGait-PD transfer to other PD-IMU datasets.

## Arguments

The user may specify: $ARGUMENTS (a specific dataset name, or blank for all available).

## Context

- Our model: LightGBM on 150 biomechanical features, trained on WearGait-PD (142 dev subjects)
- WearGait-PD: 13 IMUs, 100Hz, controlled gait tasks (SelfPace, HurriedPace, TUG, etc.)
- Feature extraction: `run_ablation_v2.py` functions
- Known external PD-IMU datasets with UPDRS:
  1. **Hssayeni/Dafna (PhysioNet)**: N=24 PD, wrist+ankle gyro, free-body ADL, UPDRS-III total
  2. **mPower (Synapse)**: N=~8000, smartphone accel only, self-reported UPDRS (noisy)
  3. **Daphnet (UCI)**: N=10 PD, 3 accel sensors, freeze-of-gait only (no UPDRS — classification only)
  4. **Gait-PD (Physionet)**: N=93 PD + 73 HC, vertical force, no IMU (force plate)
  5. **CIS-PD (BEAT-PD)**: N=28 PD, smartphone+smartwatch, MDS-UPDRS Part III

## Instructions

Write and deploy a self-contained `run_transfer.py` script via `./gpu.sh` that evaluates cross-dataset transfer.

### Phase 1: Identify Available Datasets

Check which external datasets are already downloaded on the slave:
```bash
ls /root/pd-imu/data/external/ 2>/dev/null
```

If none exist, create the directory structure and provide download instructions for each dataset. For PhysioNet datasets, use `wget` with the PhysioNet URLs. For Synapse, note the login requirement.

### Phase 2: Feature Space Alignment

The key challenge is that external datasets have DIFFERENT sensors than WearGait-PD.

Strategy for each dataset:

**Hssayeni (wrist+ankle gyro):**
- WearGait-PD has R_Wrist, L_Wrist, R_Ankle, L_Ankle with both acc+gyro
- Extract the SAME feature types but only for the overlapping sensors
- Retrain WearGait-PD model on just the overlapping features
- Evaluate on Hssayeni test subjects

**mPower (smartphone accel):**
- Map smartphone accel to nearest WearGait-PD sensor (likely hand/wrist or pocket = thigh)
- Extract time/frequency domain features (shared feature space)
- Note: self-reported UPDRS is noisy — correlation ceiling is lower

**CIS-PD (smartphone+watch):**
- Map smartwatch to wrist sensor, smartphone to pocket/thigh
- Similar feature alignment as above

### Phase 3: Transfer Experiments

For each available external dataset:

**Experiment A: Zero-shot transfer**
1. Train on WearGait-PD (full 142 dev) using only overlapping features
2. Extract same features from external dataset
3. Predict external subjects' UPDRS scores
4. Report MAE, r vs external ground truth

**Experiment B: Feature-space transfer**
1. Extract features from external dataset using the same pipeline
2. Normalize features using WearGait-PD training statistics
3. Apply trained model directly
4. Report metrics

**Experiment C: Fine-tuned transfer (if N is sufficient)**
1. Train on WearGait-PD
2. Fine-tune on 80% of external data (if N >= 20)
3. Evaluate on held-out 20% of external data
4. Compare to training from scratch on external data alone

### Phase 4: Results

```
CROSS-DATASET TRANSFER RESULTS
================================
                            N_PD  Sensors   Zero-Shot    Fine-Tuned   From-Scratch
                                  Overlap   MAE    r     MAE    r     MAE    r
WearGait-PD (internal)       101  100%     7.97  0.821    —     —      —     —
Hssayeni (wrist+ankle gyro)   24   4/13     ?.??  ?.???  ?.??  ?.???  5.95  0.74
CIS-PD (phone+watch)          28   2/13     ?.??  ?.???  ?.??  ?.???   —     —
mPower (phone accel)         ~1k   1/13     ?.??  ?.???   —     —      —     —
```

### Phase 5: Analysis

Even NEGATIVE transfer results are valuable for the paper:
- "Model trained on controlled gait doesn't transfer to free-living ADL" → argues for task-specific models
- "Transfer degrades with fewer overlapping sensors" → quantifies sensor importance for deployment
- "Fine-tuning recovers performance" → shows feature representations are useful even if raw predictions don't transfer

### Implementation Requirements

- Self-contained `run_transfer.py`
- Import from `data_split.py` for WearGait-PD loading
- Reuse feature extraction from `run_ablation_v2.py`
- Handle missing sensors gracefully (compute features only for available sensors)
- 5 seeds for all experiments
- Save results to `/root/pd-imu/transfer_results.json`

### Critical Rules

- Subject-level splits ALWAYS — no window-level leakage even in external datasets
- Feature normalization: use WearGait-PD training set statistics for zero-shot, retrain normalizer for fine-tuned
- mPower UPDRS is self-reported — note this limitation prominently
- Don't compare MAE directly across datasets with different UPDRS distributions
- Report dataset characteristics (N, sensor count, task type, UPDRS range) for context
