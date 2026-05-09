# Learnings

> **Archive status, 2026-05-09:** historical clean Paper3 lesson log only. Current canonical numbers and manuscript routing are in `CLAUDE.md`, `paper.md`, `CURRENT_PAPER.html`, and `render_current_paper.py`; current T3 valid-range headline is iter47 CCC `0.3784` / LOSO `0.150`, while old Paper3 MAE/r and iter5 T3 `0.5227` values are not current deployment results.

This file captures the lessons that still hold after the contamination audit in `CONT.md`.

## 1. Evaluation hygiene is the main result

The single biggest lesson is that repeated use of a 36-subject outer test set for model search can manufacture a false breakthrough. The old `6.89` headline overstated performance by roughly `2.8 MAE`.

Rule:
- never search on the held-out test set
- never promote a sensitivity winner as the new primary on the same split
- prefer repeated fresh splits or nested CV over one-shot benchmarking

## 2. Clean held-out performance is materially worse than the old story

On the fresh split (`seed=20260309`):

- baseline: `MAE 9.47`, `r 0.605`
- pre-specified stack: `MAE 9.68`, `r 0.579`
- sensitivity stack: `MAE 9.40`, `r 0.605`
- ceiling with H&Y: `MAE 8.22`, `r 0.705`

The corrected story is harder, but believable.

## 3. Engineered features plus boosters remain the best family

Even after cleanup, the strongest direction remains:

- engineered gait features
- careful feature selection
- LightGBM / XGBoost / CatBoost
- simple linear meta-learning on OOF predictions

Large raw-signal DL models still have not shown a convincing advantage in this sample regime.

## 4. Corrected DL is still below the clean feature baselines

The first completed corrected five-task rerun (`P3B`) finished at `MAE 10.64`, `r 0.367`, clearly below the feature-based baselines. This does not close the DL question completely, but it reinforces the practical lesson that model family is not the bottleneck yet.

## 5. The sensor story survived cleanup, but only partially

The old mechanism was wrong: the historical sensor ablation leaked privileged full-sensor `dst_` features into reduced-sensor settings.

After fixing that, the clean split still showed:

- `wrists_2`: `MAE 8.75`
- `no_LowerBack`: `MAE 9.25`
- `all_13`: `MAE 9.91`

That means the direction survived, but only as a one-split finding. It still needs repeated-split and `K`-sensitivity validation.

## 6. Total UPDRS-III has a real observability ceiling

Gait IMUs cannot directly observe:

- rigidity
- speech
- facial expression
- several fine upper-limb items

The clean H&Y-assisted model at `MAE 8.22` supports the view that useful signal exists, but the total-score target still contains irreducibly unobserved components.

## 7. Strict protocol matching matters for every comparison

Three examples from this repo:

- old LOOCV was optimistic because feature selection happened outside the fold
- old DL comparison was mismatched because train and test task sets differed from the feature baseline protocol
- old stats report validated the wrong model family

If protocols differ, the comparison is descriptive at best.

## 8. Small-N clinical modeling amplifies variance everywhere

At this scale:

- validation splits are noisy
- feature selection is unstable
- seed effects matter
- sensor conclusions can flip with dimensionality

That is why repeated-split evaluation is the next priority, not more architecture churn.

## 9. The best next gains are architectural, but within the booster regime

The most credible next steps are:

- multi-view booster stacking
- per-task experts
- per-sensor-group experts
- auxiliary observable-subscore modeling
- tail-aware residual modeling for high-severity subjects

Those changes directly target the current weaknesses without requiring much larger sample sizes.

## 10. Honest documentation is part of the research stack

Once the audit was done, every manuscript and note file needed to be updated. Leaving contradictory markdown behind would have recreated the contamination at the documentation layer even after the code was fixed.
