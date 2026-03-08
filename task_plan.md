# Deep Learning Step-Function Ablation Plan

## Objective
Beat current baseline (LightGBM 150 features, MAE=7.97, r=0.821) with deep learning approaches that unlock step-function improvements. Target: MAE < 7.0 (cross-dataset SOTA territory).

## Why Current DL Fails (Root Cause Analysis)

| Problem | Impact | Evidence |
|---------|--------|----------|
| 86M params for N=142 subjects | Catastrophic overfitting | Transformer MAE ~9-11 vs LightGBM 7.97 |
| Per-window z-norm | Destroys severity-correlated amplitude | CLAUDE.md: "amplitude IS severity" |
| No pretraining | Encoder learns from scratch on tiny data | Shuqair 2024 got r=0.89 with SSL on N=24 |
| Single-scale patching (0.5s) | Misses multi-scale gait structure | Steps=0.5s, strides=1s, bouts=10-30s |
| Flat 78ch input | Ignores anatomical sensor topology | 13 sensors with known bilateral/proximal-distal structure |
| No feature-DL fusion | Best features never meet best representations | Handcrafted=7.97, DL=~9-11, never combined |
| Window-level training | Subject-level regression needs subject-level aggregation during training | MIL explored but with overly large models |

## Architecture Constraint (CRITICAL)
ALL DL models MUST be small: <=128d/4L for pretraining, <=256d/6L for supervised. The 768d/10L (86M params) is proven to catastrophically overfit at N=142. Use inductive biases instead of scale.

## Phases (Priority-Ordered by Expected Impact)

### Phase 1: Self-Supervised Pretraining → Fine-tuning [HIGHEST IMPACT] ★★★
**The single biggest lever.** SSL is THE established solution for small-N DL.

| ID | Variant | Description | Architecture | Expected Gain |
|----|---------|-------------|--------------|---------------|
| P1A | Masked Autoencoder | Mask 75% of patches, reconstruct from visible 25%. Pretrain on ALL windows (~15K from all tasks, both PD+HC) | Encoder: 128d/4L, Decoder: 64d/2L | 1.5-3.0 MAE |
| P1B | TS-TCC Contrastive | Strong/weak augmentation pairs, temporal contrasting + contextual contrasting | Same encoder, projection head | 1.0-2.5 MAE |
| P1C | Sensor Masking | Mask entire sensor groups (e.g., all left-side), reconstruct from remaining. Learns cross-sensor relationships | Same encoder, sensor-aware masking | 1.0-2.0 MAE |
| P1D | Multi-task SSL | Combine masking + contrastive + sensor masking objectives | Same encoder, 3 heads | 1.5-3.0 MAE |

**Pretraining data**: ALL available windows from ALL 178 subjects × ALL 5+ tasks × ALL sensor configs. No labels needed. ~15-20K windows.
**Fine-tuning**: Freeze encoder, train regression head on dev set (142 subjects). Then gradually unfreeze.
**Status**: [ ] Not started

### Phase 2: Feature-DL Hybrid (Two-Stream Fusion) [HIGH IMPACT] ★★★
**Don't make DL re-discover what features already know. DL models the residual.**

| ID | Variant | Description | Expected Gain |
|----|---------|-------------|---------------|
| P2A | Concat Fusion | 150 handcrafted features ‖ DL embedding → MLP head | 0.5-1.5 MAE |
| P2B | Residual Fusion | LightGBM predicts UPDRS → DL predicts residual (y - y_hat_lgb) from raw windows → sum | 0.5-2.0 MAE |
| P2C | Cross-Attention | Feature tokens attend to temporal DL tokens and vice versa (Perceiver-style) | 0.5-1.5 MAE |
| P2D | Stacked Generalization | DL embeddings as new features fed into gradient boosting | 0.5-1.5 MAE |

**Key**: Stream 1 (features) is frozen. Only Stream 2 (DL) trains. This prevents gradient corruption of proven features.
**Status**: [ ] Not started

### Phase 3: Multi-Scale InceptionTime [HIGH IMPACT] ★★☆
**The right architecture for small-N time series. Parameter-efficient multi-scale convolutions.**

| ID | Variant | Description | Params | Expected Gain |
|----|---------|-------------|--------|---------------|
| P3A | InceptionTime + MIL | 6 Inception modules, parallel kernels {10,25,50,100,200}, MIL attention pooling | ~2M | 0.5-1.5 MAE |
| P3B | InceptionTime + Ordinal | Same + CORN/CORAL ordinal loss instead of Huber | ~2M | 0.5-1.5 MAE |
| P3C | InceptionTime + Covariates | Same + clinical covariates (age, sex, yrs_dx, DBS) as side input | ~2M | 0.5-1.5 MAE |
| P3D | ROCKET/MiniRocket | Random convolutional kernels (10K), linear classifier. Near-zero overfitting risk | <100K | 0.3-1.0 MAE |

**Why not Transformer**: InceptionTime consistently beats Transformers on tabular-scale N (Donie 2025). Multi-scale kernels are the right inductive bias for gait signals.
**Status**: [ ] Not started

### Phase 4: Knowledge Distillation (LightGBM → DL) [MEDIUM-HIGH IMPACT] ★★☆

| ID | Variant | Description | Expected Gain |
|----|---------|-------------|---------------|
| P4A | Standard KD | DL minimizes α·L_hard(y, ŷ_dl) + (1-α)·L_soft(ŷ_lgb, ŷ_dl) | 0.5-1.5 MAE |
| P4B | Feature Hint KD | DL intermediate features supervised to predict handcrafted feature values | 0.5-1.0 MAE |
| P4C | Relational KD | DL matches subject-subject similarity structure from LightGBM | 0.3-1.0 MAE |

**Status**: [ ] Not started

### Phase 5: Ordinal + Multi-Task Loss [MEDIUM IMPACT] ★☆☆
**UPDRS-III is ordinal. Model it as such.**

| ID | Variant | Description | Expected Gain |
|----|---------|-------------|---------------|
| P5A | CORN Ordinal | Conditional ordinal regression on 10-bin UPDRS discretization | 0.3-0.8 MAE |
| P5B | Multi-Task | Joint: UPDRS regression + PD/HC classification + H&Y ordinal | 0.3-0.8 MAE |
| P5C | Soft Bins | 20-bin soft classification with label smoothing, convert to expected value | 0.2-0.5 MAE |

**Status**: [ ] Not started

### Phase 6: Sensor Graph Neural Network [MEDIUM IMPACT] ★☆☆
**Exploit known body topology as inductive bias.**

| ID | Variant | Description | Expected Gain |
|----|---------|-------------|---------------|
| P6A | Static Graph | Fixed adjacency: bilateral pairs + proximal-distal chains. ST-GCN-like | 0.3-1.0 MAE |
| P6B | Learned Graph | Attention-based adaptive adjacency (discover latent sensor relationships) | 0.3-1.0 MAE |
| P6C | Hierarchical | Sensor → limb → body aggregation. Body-part-level predictions + fusion | 0.3-0.8 MAE |

**Status**: [ ] Not started

### Phase 7: Task-Conditioned Architecture [MEDIUM IMPACT] ★☆☆

| ID | Variant | Description | Expected Gain |
|----|---------|-------------|---------------|
| P7A | Task Embedding | Learned task token appended to input. Subject prediction = attention over task predictions | 0.3-1.0 MAE |
| P7B | AdaBN | Task-specific batch normalization, shared backbone | 0.2-0.5 MAE |
| P7C | Difficulty Weighting | Hurried-SelfPace delta as auxiliary loss, weight tasks by discriminability | 0.2-0.5 MAE |

**Status**: [ ] Not started

### Phase 8: Grand Ensemble [FINAL] ★★★
Ensemble top DL models from Phases 1-7 with LightGBM baseline. Options:
- Simple averaging (robust)
- Stacked generalization (learn weights on val set)
- Threshold: only include models that contribute >0.1 MAE via ablation

**Expected gain**: 0.3-0.5 MAE on top of best individual
**Status**: [ ] Not started

## Execution Strategy

### Ordering Rationale
Phase 1 first because:
1. SSL is THE solution for small-N DL — every DL lab doing clinical IMU does this
2. All 15K+ unlabeled windows are free data
3. Pretrained encoder improves ALL downstream phases (2-7)
4. If SSL works, Phases 2-4 compose on top; if not, we know DL won't beat features

### Compose-ability Matrix
| Phase | Builds on | Composes with |
|-------|-----------|---------------|
| P1 (SSL) | Nothing (standalone) | All downstream (P2-P8) |
| P2 (Hybrid) | P1 encoder | P3, P5, P6 |
| P3 (Inception) | Standalone or P1 | P2, P5, P7 |
| P4 (KD) | P1 encoder | P2, P5 |
| P5 (Ordinal) | Any model | P1-P4, P6-P7 |
| P6 (Graph) | Standalone or P1 | P2, P5, P7 |
| P7 (Task-cond) | Any model | P1-P6 |
| P8 (Ensemble) | Best of P1-P7 | LightGBM baseline |

### Evaluation Protocol (unchanged)
- 5-seed ensemble (42, 123, 456, 789, 2024)
- Subject-level split: 142 dev + 36 test
- Report both overall MAE and PD-only MAE
- Multi-seed variance for significance

### Critical Rules
- NEVER per-subject z-normalize for regression
- NEVER amplitude-scale augmentation (destroys severity signal)
- ALWAYS subject-level splits
- ALWAYS multi-seed (5 seeds minimum)
- Model size cap: 256d/6L max (~15M params)

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-08 | Cap at 256d/6L max | 86M params catastrophically overfits at N=142 |
| 2026-03-08 | SSL pretraining first | Highest expected impact, improves all downstream |
| 2026-03-08 | Keep LightGBM as ensemble anchor | Proven baseline, complementary to DL |
| 2026-03-08 | Per-window norm BAD for DL regression | Amplitude IS severity; use global norm with InstanceNorm |
| 2026-03-08 | InceptionTime > Transformer at small N | Literature consensus (Donie 2025) |
