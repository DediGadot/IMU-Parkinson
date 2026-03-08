# Findings

## Current Baseline Analysis

### LightGBM (Best Deployable): MAE=7.97, r=0.821
- 150 XGBoost-selected features from 1400+ candidates
- Biomechanical features: time/freq domain, gait regularity, asymmetry, turns, covariates
- 5-seed ensemble, subject-level split (142 dev / 36 test)
- Feature selection was the biggest single gain (+1.67 MAE)

### Transformer (Best DL Attempt): MAE ~9.04, r=0.644
- 768d/10L (86M params) — massively overparameterized for N=142
- Per-window z-normalization destroys cross-subject amplitude differences
- Window-level mean aggregation at inference
- MIL variants (attention pooling): MAE ~8.85, marginal improvement
- Global normalization attempt: MAE ~10.5 (worse — BatchNorm incompatibility)

### Gap Analysis: Why DL Loses by 1-2 MAE Points
1. **Overfitting**: 86M params / 142 subjects = 600K params per subject. LightGBM ~10K effective params.
2. **Normalization dilemma**: Per-window norm helps optimization but kills severity signal. Global norm helps signal but kills optimization (BatchNorm mismatch).
3. **No pretraining**: Model sees only ~8K windows from 142 subjects. SSL could leverage ~15K+ windows from all 178 subjects without labels.
4. **Single temporal scale**: Patch_size=50 (0.5s). Gait has structure at 0.1s (foot contact), 0.5s (step), 1.0s (stride), 10-30s (bout).
5. **Flat channel treatment**: 78 channels treated as unstructured. No bilateral symmetry, no proximal-distal hierarchy.

## Prior DL Experiment Results

| Method | Ens MAE | Ens r | Params | Issue |
|--------|---------|-------|--------|-------|
| Transformer 768d/10L | ~9.04 | 0.644 | 86M | Overfitting |
| Transformer 256d/6L | ~9.5 | 0.62 | 12M | Still too many for N=142 |
| CNN+Transformer hybrid | ~9.2 | 0.68 | ~8M | Marginal arch improvement |
| MIL + per-window norm | 8.85 | 0.689 | ~15M | Better, but still overfit |
| MIL + covariates | ~9.1 | 0.65 | ~15M | Covariates didn't help DL path |
| MIL + global norm + InstNorm | ~10.0 | 0.55 | ~15M | InstanceNorm not enough |
| MIL + hybrid norm | ~9.0 | 0.68 | ~15M | Marginal vs vanilla MIL |
| MIL + 5 tasks | ~9.2 | 0.65 | ~15M | More windows didn't help |

## SSL Literature Survey (Relevant to This Domain)

### TS-TCC (Eldele et al., NeurIPS 2021)
- Temporal + contextual contrastive learning for time series
- Strong/weak augmentation pairs: jitter+scale vs permute+crop
- Consistently outperforms supervised baselines at small N
- Reference implementation available

### TS2Vec (Yue et al., AAAI 2022)
- Hierarchical contrastive learning at instance and temporal levels
- No augmentation needed — uses timestamp masking and random cropping
- SOTA on UEA multivariate time series benchmarks
- Very stable, good for small N

### Masked Autoencoder (He et al., CVPR 2022 adapted for time series)
- Mask 75% of patches, reconstruct from 25%
- Extremely sample-efficient — works well even with small datasets
- TimeMAE (Cheng et al., ICDE 2023) specifically for time series
- Decoupled masking of temporal and channel dimensions

### Shuqair et al. 2024 (Bioengineering) — CLOSEST PRIOR
- **Same task** (UPDRS-III regression from wearable IMU)
- Self-supervised CNN-LSTM on N=24 PD patients
- LOOCV: r=0.89, MAE~5.65
- Proves SSL works for this exact problem at even smaller N
- Their SSL: contrastive pretraining on activity recognition datasets (transfer)

### RelCon (Xu et al., ICLR 2025)
- Relative contrastive learning for regression
- Learns ordinal relationships (A > B in severity) not exact values
- Code: github.com/maxxu05/relcon
- Could work here: PD/HC gives natural severity ordering

### BENDR (Kostas et al., 2021) — EEG/biosignal SSL
- BERT-style pretraining for biosignals (EEG but applicable to IMU)
- Convolutional encoder + Transformer, masked token prediction
- Works at N<100 for downstream tasks

## Clinical/Biomechanical Domain Knowledge

### Why Amplitude Matters (from Youssef 2026 meta-analysis)
- Gait velocity (= stride length × cadence) is #1 UPDRS-III correlate
- PD patients have reduced acceleration amplitude (shuffling gait)
- Gyroscope amplitude reflects arm swing and trunk rotation deficits
- Any normalization that removes amplitude removes the primary severity signal

### Multi-Scale Structure of Gait (from clinical gait analysis)
- **10ms**: Foot contact impulse (heel strike, toe off)
- **500ms**: Step duration (single step)
- **1000ms**: Stride cycle (bilateral step pair)
- **2-5s**: Gait initiation / termination transients
- **10-30s**: Gait bout (sustained walking segment)
- **60-120s**: Task-level (full SelfPace or TUG recording)

### Sensor Topology (Anatomical Graph)
```
         Forehead
            |
         Xiphoid
         /     \
    R_Wrist   L_Wrist
         \     /
        LowerBack
        /       \
  R_MidLatThigh  L_MidLatThigh
      |              |
  R_LatShank    L_LatShank
      |              |
  R_Ankle       L_Ankle
      |              |
  R_DorsalFoot  L_DorsalFoot
```

## Feature-DL Hybrid Literature

### Ma et al. 2025 (Sensors)
- 225 PD patients, XGBoost on UPDRS sub-items from gait features
- Validates that handcrafted features + boosting is competitive
- Our approach is complementary: their features + our DL = fusion opportunity

### Tian et al. 2025 (TNSRE)
- Ordinal/anchor scoring beats plain MSE regression for clinical scales
- Discretize continuous score → ordinal classification → expected value
- Consistent 5-10% improvement across multiple datasets

## Data Available for Pretraining

| Source | Windows | Subjects | Labels Needed | Notes |
|--------|---------|----------|---------------|-------|
| Dev set (5 tasks) | ~8,800 | 142 | None for SSL | Current training data |
| Test set (5 tasks) | ~2,200 | 36 | None for SSL | Can use for pretraining (no label leak) |
| Mat files | ~3,000 | ~120 | None for SSL | Instrumented walkway variants |
| MatTURN files | ~1,500 | ~120 | None for SSL | Turn-specific recordings |
| **Total** | **~15,500** | **178** | **None** | **All available for SSL** |

## Prior Feature Engineering Results (for reference)

| Feature Block | Impact (MAE improvement) |
|---------------|------------------------|
| Feature selection 1400→150 | **+1.67** (biggest single gain) |
| Clinical covariates (age, yrs_dx, DBS) | +0.52 |
| Turn features (peak yaw, duration) | +0.35 |
| Walkway distillation | +0.32 |
| Task contrasts (hurried-selfpace) | +0.16 |
| Foot contact spatiotemporal | +0.04 |
| H&Y stage (ceiling only) | +1.25 |
