# VNext

> **Archive status, 2026-05-09:** historical next-cycle planning only. Current canonical numbers and manuscript routing are in `CLAUDE.md`, `paper.md`, `CURRENT_PAPER.html`, and `render_current_paper.py`; current T3 valid-range headline is iter47 CCC `0.3784` / LOSO `0.150`, while old Paper3 MAE/r and iter5 T3 `0.5227` values are not current deployment results.

The next cycle should build on the clean post-audit benchmark, not the historical touched-test results.

## Current Honest Benchmark

- LightGBM baseline: `MAE 9.47`, `r 0.605`
- Pre-specified deployable stack: `MAE 9.68`, `r 0.579`
- Sensitivity stack: `MAE 9.40`, `r 0.605`
- H&Y ceiling: `MAE 8.22`, `r 0.705`
- Clean wrist subset on one split: `MAE 8.75`, `r 0.662`

## Priority 1: Repeated-Split Validation

Before chasing small gains, establish whether the ranking of:

- baseline
- primary stack
- sensitivity stack
- wrist-centric subsets

is stable across repeated fresh outer splits.

If a gain does not survive repeated splits, it is not a real advance.

## Priority 2: Multi-View Booster Stack

The best architecture family remains engineered features plus boosters. The next serious variant should be a strict out-of-fold stack combining:

- full-feature LightGBM / XGBoost / CatBoost
- per-task experts
- per-sensor-group experts
- an auxiliary observable-subscore model

Use a simple linear meta-learner trained only on development OOF predictions.

## Priority 3: Tail-Aware Modeling

The clean models still shrink high-severity subjects toward the mean. Add:

- quantile objectives
- residual experts for high-UPDRS subjects
- weighted training focused on the severe tail

Only keep changes that help both overall MAE and high-severity calibration.

## Priority 4: Sensor Claims That Can Survive Review

The clean one-split rerun suggests wrists may be genuinely competitive, but that is still not enough for a hard deployment claim.

Next sensor study requirements:
- rebuild from raw allowed sensors only
- repeat across multiple fresh splits
- sweep feature-selection `K` per subset
- compare equal-capacity and equal-dimensionality settings

## Priority 5: Finish the Missing Corrected Benchmarks

- complete nested PD-only LOOCV
- complete the five-task DL rebenchmark
- complete corrected subdomain analysis

These are needed to close the remaining caveats from `CONT.md`.

## Stop Doing

- using the outer test set as an exploration loop
- promoting sensitivity winners as primary results
- framing old `6.89` / `7.97` numbers as current
- scaling larger DL models before the tabular evaluation stack is stable
