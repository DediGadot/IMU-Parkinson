# VNext: Actionable Research Proposals

## Goal
Improve on the current honest benchmark for held-out-subject UPDRS-III regression:

- Best feature model: `MAE 7.97`, `r 0.821`
- Best deep model: `MAE 8.85`, `r 0.689`

The next phase should focus on problem formulation, supervision, and fusion, not larger raw-signal architectures.

## Priority 1: Observable-First Two-Stage Modeling
Train models on the gait-observable subtotal first, then map to total UPDRS-III.

- Use the subdomain setup in `run_subdomain.py`
- Predict gait/posture and lower-limb scores from IMU
- Feed those predictions, biomechanical features, and covariates into LightGBM/XGBoost for total-score prediction

Why:
- Total UPDRS includes rigidity, speech, facial expression, and rest tremor, which gait IMU cannot observe well
- Current subitem results show gait/posture is the most learnable block

Success bar:
- Total-score `MAE < 8.3` without H&Y

Kill criterion:
- If total `MAE` stays `> 8.7` after 5 seeds

## Priority 2: Deep Embedding + Booster Fusion
Use DL as a representation extractor, not the final regressor.

- Start from the best MIL encoder in `run_recipe_fix_v2.py`
- Export one subject embedding per subject
- Concatenate embeddings with the 150 biomechanical features from `run_biomechanics.py`
- Train LightGBM/XGBoost on the fused table

Why:
- Boosters already have the right bias for small-`N`, subject-level prediction
- DL may still contribute useful latent structure if the head is not forced to solve the full problem

Success bar:
- Beat pure feature baseline by at least `0.3 MAE`

Kill criterion:
- No improvement across 5 seeds

## Priority 3: Align Train Tasks With Test Tasks
Stop mixing all five tasks into the main raw-signal model.

- Train separate `SelfPace`, `HurriedPace`, and `SelfPace+HurriedPace` models
- Ensemble those subject-level predictions
- Use other tasks only as auxiliary inputs or feature sources

Why:
- Current results show all-task pooling hurts held-out performance

## Priority 4: Replace Fixed Windows With Stride Tokens
Move from arbitrary 10 s windows to gait-aligned units.

- Detect steps/strides from foot/shank signals or foot-contact annotations
- Build subject bags of stride-level tokens
- Preserve stride amplitude, cadence, asymmetry, and variability
- Use a small TCN or MIL encoder instead of a large Transformer

Why:
- The label is subject-level, but the current training units are weakly aligned windows

## Priority 5: External Transfer Only
Do not spend more time on SSL using only this cohort.

- If pretraining is attempted, use external IMU/HAR/Parkinson datasets
- Fine-tune only on observable subdomains or use frozen embeddings for booster fusion

Why:
- In-dataset MIM/contrastive pretraining has not transferred reliably

## Priority 6: Stabilize Model Selection
Tighten the evaluation recipe before interpreting small gains.

- Stratify validation subjects by UPDRS bins and PD/HC status
- Keep 5-seed reporting mandatory
- Report mean, std, and ensemble metrics for every experiment

Why:
- Small validation folds are currently too noisy for trustworthy early stopping

## Priority 7: Add a Literature-Comparable Track
Maintain the honest held-out test as primary, but add a secondary protocol for apples-to-apples comparison.

- Add PD-only LOOCV evaluation
- Report both `MAE` and `r`
- Keep the held-out 142/36 split as the main benchmark

Why:
- Published SOTA papers mostly use smaller, easier PD-only CV protocols

## Stop Doing
- Larger raw-signal models
- Amplitude scaling augmentation
- In-dataset SSL as the main strategy
- Naive all-task raw pooling
- Adding channels before they help the booster baseline
