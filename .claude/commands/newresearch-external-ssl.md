---
description: Pretrain IMU encoders on large external HAR/gait datasets, then fine-tune or extract embeddings for WearGait-PD. Cross-dataset SSL.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [dataset-source]
---

# External Dataset SSL Pretraining

## Research Question
Can pretraining an IMU encoder on large external human activity/gait datasets produce transferable representations that improve UPDRS-III regression on the small WearGait-PD cohort?

## Arguments
$ARGUMENTS — one of: "survey" (find datasets), "pretrain" (run pretraining), "finetune" (fine-tune + eval), "all" (default: "survey")

## Hypothesis
In-domain SSL failed (+0.14 MAE improvement) because 10K windows from 142 subjects is insufficient.
External datasets can provide 100K-1M+ windows of diverse gait/activity data.

Transfer learning strategy:
1. Pretrain encoder on large external IMU data (self-supervised)
2. Fine-tune on WearGait-PD (supervised) OR extract frozen embeddings for booster fusion

This mirrors Shuqair 2024's approach (their SSL success on N=24 used external HAR data).

Expected: +0.3-1.0 MAE if external data is sufficiently large and relevant

## Literature Support
- Shuqair 2024: SSL pretraining on external HAR → fine-tune on PD data → r=0.89 (on N=24)
- Yuan 2022 (IMUGPT): GPT-style pretraining on multi-source IMU → strong transfer
- Tang 2022: Self-supervised contrastive on UK Biobank accelerometry → PD detection
- Deldari 2022 (COCOA): Cross-dataset contrastive on HAR → transfers to clinical tasks

## Instructions

### Phase 1: Dataset Survey ($ARGUMENTS == "survey")

Search for and evaluate external IMU datasets:

```python
CANDIDATE_DATASETS = {
    # Large-scale HAR
    "uk_biobank_accel": {
        "size": "100K+ subjects", "sensors": "wrist accelerometer",
        "relevance": "MEDIUM (wrist only, general activity)",
        "access": "Application required",
    },
    "capture24": {
        "size": "151 subjects, 24h each", "sensors": "wrist accelerometer",
        "relevance": "MEDIUM",
        "access": "Open (Oxford)",
    },
    "ucihar": {
        "size": "30 subjects", "sensors": "waist IMU 6-axis",
        "relevance": "LOW (too small, healthy only)",
        "access": "Open",
    },
    "opportunity": {
        "size": "4 subjects, dense sensors", "sensors": "12 IMUs + others",
        "relevance": "HIGH (multi-sensor, though small N)",
        "access": "Open",
    },

    # PD-specific
    "pads_smartwatch": {
        "size": "120 subjects", "sensors": "smartwatch IMU",
        "relevance": "HIGH (PD patients, gait tasks)",
        "access": "PhysioNet",
    },
    "gaitpd_goldstandard": {
        "size": "93 PD + 73 HC", "sensors": "lower back IMU",
        "relevance": "HIGH (PD gait, same body region)",
        "access": "PhysioNet",
    },
    "mjff_levodopa": {
        "size": "30 PD", "sensors": "wrist + ankle IMU",
        "relevance": "HIGH (PD, continuous monitoring)",
        "access": "Synapse (MJFF)",
    },

    # Gait-specific (non-PD)
    "marea": {
        "size": "20 subjects", "sensors": "5 IMUs, gait",
        "relevance": "MEDIUM (gait-specific but small)",
        "access": "Open",
    },
}
```

For each candidate:
1. Verify availability and download feasibility
2. Check sensor overlap with WearGait-PD (acc+gyr, body locations)
3. Estimate pretraining data volume (# windows)
4. Rank by: relevance × size × accessibility

### Phase 2: Pretraining ($ARGUMENTS == "pretrain")

```python
# Use the most available + relevant external dataset(s)
# Pretraining objective options:

SSL_OBJECTIVES = {
    "masked_autoencoder": {
        "mask_ratio": 0.5,
        "reconstruct": "masked patches of IMU signal",
        "advantage": "Learns temporal structure",
    },
    "contrastive_augmentation": {
        "positives": "augmentations of same window (jitter, crop, rotate)",
        "negatives": "different windows",
        "advantage": "Learns augmentation-invariant features",
    },
    "severity_contrastive": {
        "method": "RelCon (if labels available)",
        "positives": "subjects with similar clinical score",
        "negatives": "subjects with different clinical score",
        "advantage": "Directly severity-aware (requires labels)",
    },
}

# Architecture: reuse InceptionTime or Transformer from run_dl_experiments.py
# Match input shape to WearGait-PD: same window size, same channel ordering
# Handle sensor mismatch: use available sensors, zero-pad missing ones
```

### Phase 3: Transfer ($ARGUMENTS == "finetune")

```python
# Option A: Fine-tune entire network
# Unfreeze pretrained encoder, add regression head, train on WearGait-PD
# Risk: catastrophic forgetting at small N

# Option B: Frozen embedding + booster (PREFERRED)
# Freeze pretrained encoder, extract embeddings, feed to LightGBM
# Same as newresearch-dl-fusion but with externally pretrained encoder

# Option C: Gradual unfreezing
# Start frozen, gradually unfreeze from top layers
# Balance transfer vs task-specific learning
```

### 4. Experiment Design

| Config | Pretraining | Transfer | Expected MAE |
|--------|------------|----------|-------------|
| A | None (baseline features) | — | 7.97 |
| B | None (in-domain SSL) | Fine-tune | 10.46 (P3B) |
| C | External MAE | Fine-tune | 9.5-10.5 |
| D | External MAE | Frozen embed + LightGBM | 7.5-8.0 |
| E | External contrastive | Frozen embed + LightGBM | 7.4-7.9 |
| F | External + features_150 fused | LightGBM | 7.2-7.7 |

### 5. Analysis

```
EXTERNAL SSL RESULTS
======================
Pretraining Data:    [Dataset], N=[subjects], [windows] windows
Pretraining Loss:    [final loss] (converged: yes/no)
Sensor Overlap:      [X/13] sensors matched, [strategy for missing]

Transfer Results:
  Config    Method              MAE (3-seed)    r         Delta
  B         In-domain SSL       10.46±X.XX      0.436     —
  D         External frozen     X.XX±X.XX       0.XXX     +X.XX vs B
  F         External + feats    X.XX±X.XX       0.XXX     +X.XX vs A

KEY QUESTION ANSWERED:
  Does external pretraining close the DL-feature gap?
  Feature baseline: 7.97, External SSL + fusion: X.XX
  Gap closed: XX%
```

### Critical Rules
- External datasets MUST NOT contain WearGait-PD subjects (no data leakage)
- Sensor mapping between datasets must be explicit (which external sensor maps to which WearGait sensor)
- Handle sampling rate differences (resample to 100Hz to match WearGait-PD)
- Handle channel count differences (use available channels, zero-pad or skip missing)
- Pretraining should run on GPU slave — may need multiple hours for large datasets
- Download external datasets to slave only (don't waste master disk space)
- Verify data license/access requirements before downloading
- If no external dataset is accessible within a session, output a ranked list with download instructions
