# Task Plan: Step-Function MAE Improvement (V3)

## Objective
Beat MAE=7.97 → target MAE ≤ 7.0 using 14 new research directions. Maximize GPU utilization on RTX 5060 Ti 16GB. All experiments use existing 142 dev / 36 test split.

## Strategy: Parallel Feature Manufacturing + Staged Model Innovation

The plan has 5 waves. Each wave maximizes CPU/GPU parallelism by overlapping CPU-bound feature extraction with GPU-bound model training.

**Critical insight**: Feature extraction (CSV parsing, statistics, spectral analysis) is 100% CPU. Model training (LightGBM/XGBoost) is CPU+GPU. DL embedding extraction is GPU. We have 11 CPU cores + 1 GPU. The bottleneck is almost always CPU (parsing 700+ CSVs × 13 sensors × 5 tasks), not GPU.

**Step function thesis**: The biggest gain comes from combining 6-8 orthogonal feature families (channels, stride, asymmetry, phase, nonlinear, frequency, covariates) into a single expanded feature set, then re-running feature selection. Each adds +0.1-0.5 independently, but combined they should add +0.5-1.5.

---

## Wave 1: Feature Manufacturing Blitz [~90 min total]

**Goal**: Extract ALL new feature families in parallel. One mega-script that combines all feature extraction, runs on CPU while GPU sits idle (or extracts DL embeddings).

### GPU Track (5 min):
- **E1-GPU**: `/newresearch-dl-fusion` — extract embeddings from P3B (InceptionTime) and P1A (MAE Transformer) checkpoints. Forward pass only, ~2.5 min per model.

### CPU Track (11 cores, ~60-90 min):
All feature extractions run in parallel using ProcessPoolExecutor. One unified `run_v3_features.py` script that:

- **E1-A**: `/newresearch-channel-expansion all` — FreeAcc_E/N/U + Roll/Pitch/Yaw + Mag_XYZ features (~39+39+39 new channels)
- **E1-B**: `/newresearch-stride-tokenize annotation` — stride-aligned features from foot contact events (stride time, stance%, variability, asymmetry)
- **E1-C**: `/newresearch-phase-features all` — Walk/Turn/SitToStand phase-specific features from GeneralEvent annotations
- **E1-D**: `/newresearch-asymmetry all-pairs` — L-R asymmetry indices for all 5 bilateral sensor pairs
- **E1-E**: `/newresearch-nonlinear-dynamics entropy,dfa` — sample entropy + DFA alpha (skip slow Lyapunov/RQA in first pass)
- **E1-F**: `/newresearch-frequency-expansion wavelet,spectral` — wavelet energy/entropy + spectral complexity (skip slow coupling)
- **E1-G**: `/newresearch-covariate-mining all` — full clinical covariates + interaction features

### CPU Track (analysis, parallel):
- **E1-H**: `/newresearch-ceiling-analysis oracle` — oracle experiments to quantify theoretical ceiling

### Expected output:
```
features_baseline.parquet        # 150 features (existing)
features_channels.parquet        # +200 from FreeAcc/Euler/Mag
features_stride.parquet          # +80 stride-level features
features_phase.parquet           # +120 phase-specific features
features_asymmetry.parquet       # +60 L-R asymmetry features
features_nonlinear.parquet       # +40 entropy/DFA features
features_frequency.parquet       # +100 wavelet/spectral features
features_covariates.parquet      # +30 clinical interaction features
embeddings_p3b.npy               # 128d per subject
embeddings_p1a.npy               # 128d per subject
```

Total raw features: ~1400 (existing) + ~630 (new) + 256 (embeddings) ≈ **2300 features**

Status: [ ] E1-GPU  [ ] E1-A  [ ] E1-B  [ ] E1-C  [ ] E1-D  [ ] E1-E  [ ] E1-F  [ ] E1-G  [ ] E1-H

---

## Wave 2: Quick Ablation + Feature Selection [~30 min]

**Goal**: Test each new feature family individually against baseline. Identify which families improve MAE. Then combine winners and re-optimize feature selection K.

### Single-family ablation (3 seeds each, LightGBM, parallel on GPU):

| Config | Features | K_select | Expected MAE |
|--------|----------|----------|-------------|
| B0 | Baseline 150 | 150 | 7.97 (reference) |
| B1 | Baseline + channels | 200 | 7.4-7.8 |
| B2 | Baseline + stride | 180 | 7.5-7.9 |
| B3 | Baseline + phase | 180 | 7.6-7.9 |
| B4 | Baseline + asymmetry | 170 | 7.6-7.9 |
| B5 | Baseline + nonlinear | 160 | 7.6-8.0 |
| B6 | Baseline + frequency | 180 | 7.6-8.0 |
| B7 | Baseline + covariates | 160 | 7.5-7.9 |
| B8 | Baseline + P3B embed | 278 | 7.5-8.0 |
| B9 | Baseline + P1A embed | 278 | 7.5-8.0 |

### Combined winners (after ablation):

| Config | Features | K_sweep | Expected MAE |
|--------|----------|---------|-------------|
| C1 | All winners (concat) | [150,200,300,400] | 7.0-7.5 |
| C2 | All winners + embeddings | [200,300,400,500] | 6.8-7.3 |
| C3 | C2 + XGBoost (not just LGB) | best K from C2 | 6.8-7.3 |

**Kill criterion**: If NO single family beats 7.97 → skip that family from combined set.

Status: [ ] B0-B9  [ ] C1-C3

---

## Wave 3: Model Architecture Innovation [~45 min]

**Goal**: Apply model-level improvements USING the best feature set from Wave 2. Run 3 experiments in parallel.

### GPU/CPU Track 1:
- **M1**: `/newresearch-two-stage all` — predict observable subitems (items 7-14) → map to total
  - Use Wave 2 best features for both stages
  - OOF predictions for Stage 2 training (no leakage)
  - Expected: MAE 6.8-7.3

### GPU/CPU Track 2:
- **M2**: `/newresearch-target-transform all` — test log1p, sqrt, Huber loss, weighted MAE, ordinal bins
  - Use Wave 2 best features
  - 3 seeds per transform
  - Expected: MAE 7.0-7.7 (transform may help with skewed distribution)

### GPU/CPU Track 3:
- **M3**: `/newresearch-task-specialist ensemble` — per-task models + weighted ensemble
  - Separate feature selection per task
  - Learn task weights from OOF performance
  - Expected: MAE 7.2-7.7

Status: [ ] M1  [ ] M2  [ ] M3

---

## Wave 4: Grand Stacking + Pipeline [~30 min]

**Goal**: Combine all winning approaches into stacking ensemble. This is where step-function happens.

### Grand ensemble:
- **S1**: `/newresearch-stacking-ensemble full` — stack all winners from Waves 2-3
  - L0 pool: best_lgb_expanded, best_xgb_expanded, ridge, two_stage_pred, task_ensemble_pred, target_transform_winner
  - L1: Ridge (safest at N=142) or shallow LightGBM
  - OOF predictions for L1 training
  - Expected: MAE 6.5-7.0

### Grand pipeline validation:
- **S2**: `/newresearch-grand-pipeline phase3` — ablate back from grand pipeline
  - Remove each feature family / model one at a time
  - Identify which components actually contribute vs add noise
  - Produce final optimized pipeline

Status: [ ] S1  [ ] S2

---

## Wave 5: Publication-Ready Validation [~90 min, CPU-heavy]

**Goal**: Validate best model for publication. Run after Wave 4 produces best MAE.

### CPU Track (embarrassingly parallel):
- **V1**: `/newresearch-pdonly-loocv best` — PD-only LOOCV (101 models)
  - Target: PD-only MAE < 5.95 (beat Hssayeni cross-dataset SOTA)
  - ~101 sequential model fits, ~60-90 min on CPU

### CPU Track (parallel with V1 if server has capacity):
- **V2**: `/newresearch-sensor-ablation greedy-addition` — find minimal sensor set
  - 13 rounds × 3 seeds = ~40 model fits
  - Produces clinical deployment recommendation

### Analysis:
- **V3**: `/newresearch-ceiling-analysis decompose` — error decomposition with best model
  - Quantify: model_gap, unobservable_gap, noise_floor
  - For paper discussion section

Status: [ ] V1  [ ] V2  [ ] V3

---

## GPU Utilization Timeline

```
Time     GPU                              CPU (11 cores)
─────────────────────────────────────────────────────────────
0-5m     E1-GPU: DL embed extraction      E1-A through E1-G: feature extraction
5-90m    IDLE (all Wave 1 is CPU)          E1-A through E1-H: feature extraction
         → FILL with B0-B9 as features      (process features as they complete)
         finish extracting

90-120m  B0-B9 ablation + C1-C3 combos    Feature selection sweeps
120-165m M1+M2+M3 in parallel             Two-stage OOF, task splits
165-195m S1 stacking + S2 ablation        Diversity analysis
195-285m V2 sensor ablation               V1 PD-only LOOCV (101 models)
```

**Key GPU optimization**:
1. Don't wait for ALL features to extract. Start B1 ablation as soon as E1-A (channels) finishes
2. LightGBM trains on GPU via `device='gpu'` — set `gpu_use_dp=False, gpu_platform_id=0`
3. Run multiple seed evaluations simultaneously (each seed uses <1GB VRAM for boosting)
4. Pipeline: while model N trains, prepare features for model N+1

**Estimated total wall time: ~4.5 hours** (vs ~12 hours sequential)

---

## Implementation: Single Script Per Wave

Each wave produces ONE self-contained `run_v3_wave{N}.py` that:
1. Imports from `data_split.py` only
2. Caches intermediate results as .parquet/.npy
3. Prints clear progress and results
4. Saves summary JSON for next wave to consume

```
run_v3_wave1_features.py    # All feature extraction (CPU-heavy)
run_v3_wave2_ablation.py    # Single-family ablation + combination
run_v3_wave3_models.py      # Two-stage + target transform + task specialist
run_v3_wave4_stacking.py    # Grand stacking ensemble
run_v3_wave5_validate.py    # LOOCV + sensor ablation + ceiling
```

Alternatively, ONE script `run_v3_grand.py` with `--wave {1,2,3,4,5}` argument for sequential deployment.

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Combine ALL feature families first, then model innovations | Features are the highest-leverage intervention (ablation showed +1.67 from selection alone) |
| Skip Lyapunov/RQA in Wave 1 | O(n²) computation, marginal expected gain, can add later if entropy/DFA show signal |
| Skip external SSL in main plan | Requires dataset download + multi-hour pretraining; ROI uncertain. Run independently if time permits |
| Use LightGBM `device='gpu'` | LightGBM GPU mode is 2-5x faster for boosting at our feature/sample count |
| Ridge for L1 meta-learner | At N=142 with 6-8 L0 models, Ridge is the safest against overfitting |
| Single script per wave | Avoids module dependency hell; each wave is independently deployable |
| Kill criterion per family | If a feature family doesn't beat 7.97 solo, it may still help in combination — include it in C1/C2 but flag it |

## Success Criteria

| Outcome | MAE | Verdict |
|---------|-----|---------|
| No improvement | > 7.97 | Publish baseline (still first WearGait-PD regression) |
| Incremental | 7.5-7.97 | Moderate paper upgrade |
| **Step function** | **< 7.0** | **Strong publication** |
| Cross-dataset SOTA | PD-only LOOCV < 5.95 | Headline result |
| Clinical significance | < 4.63 | Within worsening MCID (aspirational) |

## Slash Command → Experiment Mapping

| Slash Command | Wave | Experiment | Compute |
|---------------|------|------------|---------|
| `/newresearch-channel-expansion` | 1 | E1-A | CPU |
| `/newresearch-stride-tokenize` | 1 | E1-B | CPU |
| `/newresearch-phase-features` | 1 | E1-C | CPU |
| `/newresearch-asymmetry` | 1 | E1-D | CPU |
| `/newresearch-nonlinear-dynamics` | 1 | E1-E | CPU |
| `/newresearch-frequency-expansion` | 1 | E1-F | CPU |
| `/newresearch-covariate-mining` | 1 | E1-G | CPU |
| `/newresearch-dl-fusion` | 1 | E1-GPU | GPU |
| `/newresearch-ceiling-analysis` | 1+5 | E1-H, V3 | CPU |
| `/newresearch-two-stage` | 3 | M1 | CPU+GPU |
| `/newresearch-target-transform` | 3 | M2 | CPU+GPU |
| `/newresearch-task-specialist` | 3 | M3 | CPU+GPU |
| `/newresearch-stacking-ensemble` | 4 | S1 | CPU+GPU |
| `/newresearch-grand-pipeline` | 4 | S2 | CPU+GPU |
| `/newresearch-pdonly-loocv` | 5 | V1 | CPU |
| `/newresearch-sensor-ablation` | 5 | V2 | CPU |
