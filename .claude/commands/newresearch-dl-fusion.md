---
description: Extract DL encoder embeddings and fuse with handcrafted features in a booster. DL as feature extractor, not regressor.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [encoder-source]
---

# Deep Learning Embedding Fusion

## Research Question
Can DL encoders trained on raw IMU signals extract complementary representations that, when fused with handcrafted features in a gradient booster, beat either alone?

## Arguments
$ARGUMENTS — one of: "p3b" (InceptionTime), "p1a" (MAE Transformer), "both", "retrain" (default: "both")

## Hypothesis
DL failed as end-to-end regressors (MAE 10.46-13.68 vs 7.97) because:
1. N=142 insufficient for the regression head to generalize
2. The encoder may still learn useful temporal patterns not captured by handcrafted features

By replacing the regression head with a gradient booster:
- Booster provides the right inductive bias for small N
- DL embedding provides complementary signal (temporal dynamics, cross-sensor interactions)
- Concat(handcrafted_150 + embedding_64) → LightGBM should beat either alone

Expected: +0.2-0.5 MAE over pure feature baseline

## Literature Support
- Shuqair 2024: SSL encoder → linear regressor beat handcrafted on same data (but N=24, LOOCV)
- Rajotte 2021: CNN embedding + clinical features → XGBoost beat both alone for ICU mortality
- Common pattern in tabular+signal fusion: learned embeddings capture what features miss

## Instructions

Write and deploy `run_dl_fusion.py` via `./gpu.sh`.

### 1. Extract Embeddings from Trained Encoders

**From P3B (InceptionTime, best DL):**
```python
# Load trained P3B model checkpoint
# Forward pass all subjects through encoder (before regression head)
# Extract: subject_embedding = MIL_attention_pool(window_embeddings)
# Shape: (N_subjects, embed_dim)  # embed_dim likely 64-128
```

**From P1A (MAE-pretrained Transformer):**
```python
# Load trained P1A model checkpoint
# Forward pass through Transformer encoder only
# Pool: CLS token or mean-pool across window positions
# Shape: (N_subjects, embed_dim)
```

### 2. Embedding Quality Check

Before fusion, verify embeddings carry signal:
```python
# Sanity check 1: embedding-only regression
lgb_embed_only = LightGBM(embed_features_only)  # MAE should be < 12 (better than random)

# Sanity check 2: t-SNE/UMAP of embeddings colored by UPDRS
# Should show gradient from low→high UPDRS, not random scatter

# Sanity check 3: Pearson r of each embedding dimension with UPDRS
# At least a few dims should have |r| > 0.3
```

### 3. Fusion Strategies

| Config | Input | #Features | Expected MAE |
|--------|-------|-----------|-------------|
| A | Handcrafted 150 (baseline) | 150 | 7.97 |
| B | P3B embedding only | 64-128 | 9.5-11.0 |
| C | P1A embedding only | 64-128 | 9.5-11.0 |
| D | Handcrafted + P3B embed (early fusion) | 214-278 | 7.5-7.8 |
| E | Handcrafted + P1A embed (early fusion) | 214-278 | 7.5-7.8 |
| F | Handcrafted + P3B + P1A (all) | 278-406 | 7.3-7.7 |
| G | Late fusion: avg(booster_pred, embed_pred) | — | 7.6-8.0 |

### 4. Preventing Embedding Leakage

CRITICAL: Embeddings must be extracted using proper train/test protocol:
```python
# Train encoder on dev set (142 subjects) only
# Extract embeddings for ALL subjects (train + test) using frozen encoder
# The embedding extraction itself doesn't leak — it's a fixed transformation
# But: if encoder was trained with any test data → embeddings are contaminated
# Verify: check that encoder training used ONLY dev set subjects
```

### 5. Retrain Option (if $ARGUMENTS == "retrain")

If existing checkpoints are stale or unavailable:
```python
# Retrain encoder specifically for embedding extraction
# Use contrastive loss with SEVERITY-AWARE sampling (NOT standard InfoNCE)
# RelCon-style: positive pairs = similar UPDRS, negative pairs = different UPDRS
# This should produce embeddings where distance ∝ severity difference
```

### 6. Analysis

```
DL FUSION RESULTS
==================
Config    Input              #Feats  MAE (3-seed)    Delta
A         Features only      150     7.97±X.XX       —
B         P3B embed only     64      X.XX±X.XX       —
D         Features + P3B     214     X.XX±X.XX       +X.XX
F         Features + all DL  278     X.XX±X.XX       +X.XX

EMBEDDING QUALITY:
  P3B embedding-only MAE: X.XX (sanity: should be < 12)
  P1A embedding-only MAE: X.XX

  Top embedding dims correlated with UPDRS:
    P3B dim 23: r=0.XX
    P1A dim 7:  r=0.XX

  t-SNE shows [clear gradient / no structure] (save figure)
```

### 7. Visualization

- t-SNE of embeddings colored by UPDRS-III score
- Feature importance comparison: handcrafted vs embedding dims in fused model
- Scatter: fused prediction vs handcrafted-only prediction (show cases where fusion helps)

### Critical Rules
- MUST verify encoder was trained without test subjects — check data_split.json against training logs
- Embedding extraction = deterministic forward pass, no randomness (set eval mode, fix seeds)
- Feature selection on fused features must include BOTH types in the selection pool — don't pre-select
- If embedding-only MAE > 12: embeddings carry no signal, skip fusion (fail fast)
- Use same LightGBM HPs as baseline for fair comparison
- 3 seeds minimum, report mean±std
