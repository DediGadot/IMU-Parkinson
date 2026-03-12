# Experiment Results

This file now tracks the clean post-audit state. Historical pre-audit experiment logs were removed because they repeatedly contradicted `CONT.md`.

## Canonical Sources

- `CONT.md`
- `results/paper3_split.json`
- `results/clean_benchmark_results.json`
- `results/stats_report.json`
- `results/sensor_ablation_results.json`

## Verified Clean Results

| Area | Result | Notes |
|------|--------|------|
| Fresh outer split | `142 dev / 36 test`, seed `20260309` | clean Paper 3 split |
| LGB baseline | `MAE 9.47`, `r 0.605` | clean benchmark |
| Primary deployable stack | `MAE 9.68`, `r 0.579` | pre-specified before test evaluation |
| Sensitivity stack | `MAE 9.40`, `r 0.605` | do not promote retroactively |
| H&Y ceiling | `MAE 8.22`, `r 0.705` | corrected stats report |
| `wrists_2` | `MAE 8.75`, `r 0.662` | clean sensor rerun, no privileged `dst_` |
| `no_LowerBack` | `MAE 9.25`, `r 0.609` | clean sensor rerun |
| `all_13` | `MAE 9.91`, `r 0.549` | clean sensor rerun |
| corrected DL `P3B` | `MAE 10.64`, `r 0.367` | partial five-task rerun |

## Interpretation

- The fresh split is much harder than the historical touched-test setup.
- The pre-specified stack is not currently better than the clean baseline.
- The sensitivity stack and wrist-centric sensor subsets are promising hypotheses for the next cycle, not settled deployment conclusions.
- The clean ceiling still leaves meaningful room above the IMU-only deployable models.

## Historical Results Policy

Historical values such as `6.89`, `7.97`, `7.22`, `7.58`, and `6.43` may still appear in `CONT.md` only as contamination history. They are not current experiment results.
