# Continuity Memo

> **Archive status, 2026-05-09:** historical Paper3/contamination handoff only. Current canonical numbers and manuscript routing are in `CLAUDE.md`, `paper.md`, `CURRENT_PAPER.html`, and `render_current_paper.py`; current T3 valid-range headline is iter47 CCC `0.3784` / LOSO `0.150`, while old Paper3 MAE/r and iter5 T3 `0.5227` values are not current deployment results.

This file documents the full current understanding of the repository state after the contamination audit, code fixes, remote reruns, and `paper3.html` rebuild.

It is written as an operational handoff, not a polished manuscript section.

## 1. Executive Summary

The original repository had multiple distinct contamination and protocol-integrity failures:

1. The historical 36-subject held-out test split was adaptively reused for model search.
2. The sensor ablation inherited privileged `dst_` walkway-distillation features learned from the full-sensor matrix.
3. The stats report did not evaluate the best saved stack; it evaluated LightGBM and called that the best model.
4. The reported "exact pipeline" for the 6.89 stack omitted `_mat` and `_matTURN` recordings even though the real proven pipeline used them.
5. The PD-only LOOCV runner selected features outside the leave-one-out loop.
6. The DL runner used all 5 tasks for development but only 2 tasks for the held-out test.
7. Subdomain parsing/composite logic was incomplete and did not robustly support UPDRS naming variants.
8. Artifact provenance was muddy because root-level JSONs and `results/` JSONs diverged.

I fixed the code paths for all of those issues. Then I reran the most important analyses on the remote GPU/data host:

- Fresh outer split: `/root/pd-imu/results/paper3_split.json`
- Clean benchmark: `results/clean_benchmark_results.json`
- Clean stats: `results/stats_report.json`
- Corrected targeted sensor ablation: `results/sensor_ablation_results.json`

I also rebuilt [paper3.html](/home/fiod/medical/paper3.html) from those fresh artifacts.

The most important bottom line is that the clean rerun is materially harder than the historical contaminated story:

- Historical touched-test headline: stack `MAE 6.89`, `r 0.860`
- New fresh outer split, pre-specified deployable stack: `MAE 9.68`, `r 0.579`
- New clean LightGBM baseline: `MAE 9.47`, `r 0.605`
- New clean H&Y ceiling: `MAE 8.22`, `r 0.705`

That is the central correction.

## 2. What "Contamination" Meant Here

There was no single leak. There were several different failure modes, and they matter for different reasons.

### 2.1 Adaptive Test-Set Reuse

The old manuscript said the 36-subject test set was frozen and never used for model selection. That was false.

What actually happened:

- `run_ablation_v2.py` repeatedly evaluated development choices on the same held-out test set.
- `run_proven_stack.py` searched stack variants on that same test set.
- `run_v3_experiments.py` also used the held-out test for exploratory comparisons.
- `findings.md` and the manuscript then promoted the best observed result.

This is contamination because the reported "best test MAE" is not a clean out-of-sample estimate anymore. It is a best-of-many estimate after human-guided search on that exact test set.

### 2.2 Sensor-Ablation Privileged Feature Contamination

The old sensor ablation did not truly isolate sensor subsets.

What actually happened:

- `run_sensor_ablation.py` loaded a full-sensor cached feature matrix.
- It then filtered columns by sensor name.
- It still kept `dst_` distilled walkway features by default.
- Those `dst_` features had been learned upstream from the full-sensor feature matrix.

That means the old `wrists_2` and `no_LowerBack` results were not purely wrist-only or lower-back-free evaluations.

### 2.3 Stats-Report Model Mismatch

The old stats report produced polished figures and CIs, but for the wrong model.

What actually happened:

- `run_stats_report.py` trained/evaluated `lgb`, `xgb`, `cat`, and a ceiling model.
- It hard-coded `best_name = "lgb"` for the figures.
- It never ran the actual best saved stack.

So the old `stats_report.json`, scatter plots, Bland-Altman, CI tables, and MCID statements did not validate the 6.89 stack.

### 2.4 Feature-Pipeline Mismatch

The old stack runner claimed it used the same pipeline as `run_ablation_v2.py`. That was not true.

What actually happened:

- `run_ablation_v2.py` uses main tasks plus `_mat` and `_matTURN` recordings.
- Old `run_proven_stack.py` iterated only `TASKS`.
- That means it omitted insole-related blocks and was not truly the same feature universe.

### 2.5 Optimistic LOOCV

The old PD-only LOOCV runner selected features once on all PD subjects before leave-one-out prediction.

That is optimistic because the left-out subject still influenced feature selection.

### 2.6 DL Protocol Mismatch

The old DL comparison was not apples-to-apples.

What actually happened:

- Development used `ALL_TASKS = ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")`
- Held-out test used only `("SelfPace", "HurriedPace")`

So the old "DL loses to handcrafted features" conclusion was directionally plausible, but not protocol-matched.

### 2.7 Subdomain Parsing / Composite Coverage Failure

The old subdomain logic did not robustly resolve all UPDRS column naming variants, and the saved artifact did not actually contain the intended observable-vs-unobservable comparison.

What was visible:

- `subdomain_results.json` only retained `axial` as a composite.
- `observable_vs_unobservable` was all `null`.

### 2.8 Provenance Drift

There were duplicate artifacts in repo root and `results/`, and some of them diverged.

That made it unclear which JSON the manuscript was actually summarizing.

## 3. Code Fixes Implemented

These are the relevant code changes now in the repo.

### 3.1 Shared Path / Artifact Layer

Added:

- [project_paths.py](/home/fiod/medical/project_paths.py)

Purpose:

- centralize repo-root vs `results/` artifact paths
- support env-overridden split/data/cache locations
- mirror JSON outputs into `results/` and optionally repo root
- avoid hard-coding `/root/pd-imu` throughout active code

### 3.2 Split Writer Bug Fix

Patched:

- [data_split.py](/home/fiod/medical/data_split.py)

Important subtlety:

When I first moved path handling into `project_paths.py`, `create_split()` still wrote via `save_json_artifact("data_split.json", ...)` instead of honoring the env-selected `SPLIT_FILE`.

That caused a real bug during remote reruns: a command using

`WEARGAIT_SPLIT_FILE=/root/pd-imu/results/paper3_split.json`

still wrote the split to the default compatibility location.

I fixed that by writing directly to `Path(SPLIT_FILE)` and ensuring its parent exists.

### 3.3 Proven Pipeline Alignment

Patched:

- [run_proven_stack.py](/home/fiod/medical/run_proven_stack.py)

Changes:

- includes the same recording universe as `run_ablation_v2.py`
- uses main tasks plus `_mat` and `_matTURN`
- labels the old test-set search behavior honestly in the output protocol metadata
- writes artifacts through the shared path layer

### 3.4 Clean Benchmark Runner

Added:

- [run_clean_benchmark.py](/home/fiod/medical/run_clean_benchmark.py)

Purpose:

- evaluate a fresh outer split once
- pre-specify the primary deployable architecture
- avoid re-running an architecture sweep on the new test set

Design:

- primary model: `S6_stack_orig_K150`
- comparators: `S0_baseline_K150` and `S4_stack_ext_K160`
- `S4` is included as a sensitivity check, not as a new selection winner

Important note:

The clean benchmark artifact intentionally sets:

- `best_config = S6_stack_orig_K150`
- `best_mae = 9.682`

even though `S4_stack_ext_K160` numerically came in lower (`9.398`).

That is intentional. The file is not reporting "lowest observed among these three." It is reporting the pre-specified primary model and the sensitivity checks alongside it.

### 3.5 Sensor Ablation Fix

Patched:

- [run_sensor_ablation.py](/home/fiod/medical/run_sensor_ablation.py)

Changes:

- excludes `dst_` features by default
- supports explicit opt-in if someone really wants the old privileged behavior
- records protocol flags in the output JSON
- writes via shared artifact paths

### 3.6 Nested LOOCV Fix

Replaced:

- [run_loocv_stack.py](/home/fiod/medical/run_loocv_stack.py)

Changes:

- feature selection now occurs inside each LOOCV fold
- top-feature reporting uses frequency across folds instead of a misleading single top-10 list

This runner is correct, but the full rerun was too slow to complete end-to-end in one pass.

### 3.7 DL Protocol Fix

Patched:

- [run_dl_experiments.py](/home/fiod/medical/run_dl_experiments.py)

Changes:

- `TEST_TASKS = ALL_TASKS`
- cache tags updated accordingly
- artifact save/load now goes through shared path helpers

Added:

- [run_dl_rebenchmark.py](/home/fiod/medical/run_dl_rebenchmark.py)

Purpose:

- rerun only the strongest historical DL candidates on the corrected five-task test protocol

### 3.8 Stats Report Fix

Patched:

- [run_stats_report.py](/home/fiod/medical/run_stats_report.py)

Changes:

- injects the saved stack predictions into the CI/permutation/clinical workflow
- chooses the best plotted model dynamically
- writes artifact through the shared path layer

Important nuance:

The stack artifact only stores ensemble predictions, not full per-seed prediction arrays.
So for stack seed-stability, the script now reports the ensemble-only limitation honestly instead of fabricating perfect inter-seed correlation from duplicated predictions.

### 3.9 UPDRS Column Resolution Fix

Added:

- [updrs_columns.py](/home/fiod/medical/updrs_columns.py)

Patched:

- [run_subdomain.py](/home/fiod/medical/run_subdomain.py)
- [run_v3_experiments.py](/home/fiod/medical/run_v3_experiments.py)

Changes:

- robust resolution of `MDSUPDRS_3-*` subitem naming variants
- supports letter-based and side-labelled conventions

### 3.10 Paper3 Generator

Added:

- [paper3_data.py](/home/fiod/medical/paper3_data.py)
- [generate_html_paper3.py](/home/fiod/medical/generate_html_paper3.py)

Purpose:

- build the manuscript from validated artifacts instead of a giant static HTML string
- let the paper explicitly distinguish:
  - clean rerun results
  - still-valid legacy results
  - unresolved / unrerun claims

## 4. Remote Rerun Environment

The raw-data reruns were executed on:

- host: `root@46.228.83.78`
- port: `40005`
- repo: `/root/pd-imu`
- GPU: `NVIDIA GeForce RTX 5060 Ti` with ~16 GB VRAM

The dataset is present remotely under:

- `/root/pd-imu/data/raw/weargait-pd`

One operational issue occurred at the start:

- Git on the remote repo complained about dubious ownership.
- I fixed it with:
  - `git config --global --add safe.directory /root/pd-imu`

## 5. Fresh Split Protocol

The new outer split is:

- artifact: [results/paper3_split.json](/home/fiod/medical/results/paper3_split.json)
- seed: `20260309`
- size: `142 dev / 36 test`

Generated remotely with:

- `WEARGAIT_SPLIT_FILE=/root/pd-imu/results/paper3_split.json`
- `create_split(seed=20260309)`

Observed summary:

- Dev mean: `16.4`, std `13.3`, range `[0, 59]`
- Test mean: `17.4`, std `13.9`, range `[0, 46]`

This split is now the clean reference split for Paper3.

## 6. Fresh Reruns Completed

### 6.1 Clean Benchmark

Artifact:

- [results/clean_benchmark_results.json](/home/fiod/medical/results/clean_benchmark_results.json)

Protocol:

- fresh outer hold-out
- pristine test set
- pre-specified primary model = `S6_stack_orig_K150`
- sensitivity models = `S0_baseline_K150`, `S4_stack_ext_K160`

Results:

| Config | MAE | r | Interpretation |
| --- | ---: | ---: | --- |
| `S0_baseline_K150` | 9.47 | 0.605 | clean LightGBM baseline |
| `S6_stack_orig_K150` | 9.682 | 0.579 | pre-specified deployable stack |
| `S4_stack_ext_K160` | 9.398 | 0.605 | sensitivity only, not used for selection |

Key point:

The old 6.89 story does not survive clean rerun. On the fresh split the deployable stack is much worse, and even underperforms the baseline.

### 6.2 Clean Stats Report

Artifact:

- [results/stats_report.json](/home/fiod/medical/results/stats_report.json)

Headline verified numbers:

| Model | MAE | r |
| --- | ---: | ---: |
| stack | 9.682 | 0.579 |
| lgb | 9.605 | 0.592 |
| xgb | 10.171 | 0.553 |
| cat | 9.903 | 0.579 |
| ceiling | 8.223 | 0.705 |

Important CI results:

- stack MAE CI: `7.93 to 11.83`
- stack r CI: `0.290 to 0.751`
- ceiling MAE CI: `6.58 to 10.37`
- ceiling r CI: `0.422 to 0.836`

Important permutation results:

- stack vs lgb: negative delta, not significant
- stack vs ceiling: ceiling clearly better

Interpretation:

- The clean rerun does not support a deployable-stack improvement over the clean LGB baseline.
- The ceiling still shows that useful signal exists and there is room above the deployable models.

### 6.3 Corrected Sensor Ablation

Artifact:

- [results/sensor_ablation_results.json](/home/fiod/medical/results/sensor_ablation_results.json)

Protocol flags:

- `allow_privileged_distilled_walkway_features = false`
- `sensor_isolation_valid_for_dst = true`

This was a targeted rerun, not the full 17-config map. I ran the clinically important disputed configs:

| Config | Sensors | MAE | r |
| --- | ---: | ---: | ---: |
| `all_13` | 13 | 9.914 | 0.549 |
| `no_LowerBack` | 12 | 9.249 | 0.609 |
| `wrists_2` | 2 | 8.749 | 0.662 |
| `back_wrists_3` | 3 | 8.989 | 0.601 |
| `back_ankles_3` | 3 | 9.349 | 0.564 |
| `lower_back_1` | 1 | 9.500 | 0.562 |
| `minimal_5` | 5 | 8.917 | 0.621 |

Interpretation:

- The old contaminated deployment claim was not a pure artifact of the privileged `dst_` leak.
- On the clean split, wrist-centric subsets still perform extremely well.
- In fact, they perform better than the full 13-sensor configuration on this split.

Important caution:

This does **not** mean we should immediately conclude "wrists are truly superior to all 13 sensors."

Why caution is still warranted:

1. This is one split.
2. The same `K=150` selection policy is being applied across very different feature counts.
3. Full-sensor models may be more exposed to small-sample selection instability.
4. Confidence intervals / repeated splits are still needed before making a strong deployment recommendation.

Still, the corrected rerun now supports the directional claim:

- wrists-only is genuinely competitive
- lower-back removal is not obviously harmful

and it supports it **without** the old privileged-feature contamination.

## 7. Remote Jobs Started But Not Fully Carried Through

### 7.1 Nested PD-Only LOOCV

Runner:

- [run_loocv_stack.py](/home/fiod/medical/run_loocv_stack.py)

Status:

- started on remote
- aborted due runtime

Observed partial progress only:

- at 10/98 subjects, running MAE was `5.99`
- at 20/98 subjects, running MAE was `6.44`
- at 30/98 subjects, running MAE was `8.00`

These are **not** valid final results and should not be cited.

Current status:

- runner logic is corrected
- full nested LOOCV still needs a full uninterrupted remote run

### 7.2 Corrected DL Rebenchmark

Runner:

- [run_dl_rebenchmark.py](/home/fiod/medical/run_dl_rebenchmark.py)

Purpose:

- rerun strongest historical DL candidates on the corrected five-task test protocol

What completed before I stopped it:

- `P3B: InceptionTime 3blk + ordinal (five-task test)`
  - completed all 5 seeds
  - mean MAE `11.60 +/- 0.70`
  - ensemble MAE `10.64`
  - ensemble r `0.367`

What had started but not completed:

- `P1A: MAE->Transformer 128d/4L + MIL (five-task test)`
  - seed 42 completed: `MAE 9.90`, `r 0.458`
  - remaining seeds were still in progress when I terminated the job

Interpretation:

- The corrected five-task DL comparison is already strongly unfavorable for `P3B`.
- It is very unlikely that the final DL story overturns the clean feature baseline.
- Still, the full corrected DL comparison is not yet complete, so Paper3 keeps the DL section conservative.

## 8. What Paper3 Currently Uses vs Does Not Use

### 8.1 What Paper3 Now Uses

Paper3 currently uses:

- clean outer split
- clean benchmark
- clean stats report
- corrected targeted sensor ablation
- legacy axial composite result from `subdomain_results.json`

### 8.2 What Paper3 Does Not Yet Rebuild From Fresh Reruns

Paper3 does **not** yet have fresh reruns for:

- nested PD-only LOOCV
- corrected subdomain/composite analysis
- full apples-to-apples DL comparison

So those sections are still conservative.

## 9. Provenance / Artifact Notes

Historically, the repo had both root-level JSONs and `results/` JSONs, and some diverged.

The new active convention is:

- canonical run outputs should be written into `results/`
- repo-root mirrors can exist for compatibility
- manuscript code should prefer the validated artifact loader

Fresh artifacts created in this pass:

- [results/paper3_split.json](/home/fiod/medical/results/paper3_split.json)
- [results/clean_benchmark_results.json](/home/fiod/medical/results/clean_benchmark_results.json)
- [results/stats_report.json](/home/fiod/medical/results/stats_report.json)
- [results/sensor_ablation_results.json](/home/fiod/medical/results/sensor_ablation_results.json)
- [paper3.html](/home/fiod/medical/paper3.html)

Fresh stats figures pulled locally:

- [results/stats_scatter.png](/home/fiod/medical/results/stats_scatter.png)
- [results/stats_bland_altman.png](/home/fiod/medical/results/stats_bland_altman.png)
- [results/stats_scatter_ceiling.png](/home/fiod/medical/results/stats_scatter_ceiling.png)

## 10. Important Interpretive Takeaways

### 10.1 The Historical 6.89 Result Was Optimistic

This is now settled.

The clean rerun on a fresh split came back around `9.4 to 9.7`, not `6.9`.

### 10.2 The Best Deployable Architecture Family Is Still Feature-Based Boosting

Even after correction:

- LGB baseline remains strong
- the deployable stack remains plausible
- the H&Y ceiling shows more signal is available

The family survives. The old headline magnitude does not.

### 10.3 Sensor Redundancy / Wrist Sufficiency May Be Real

This is the most surprising part of the clean rerun.

Even after removing the privileged `dst_` contamination:

- `wrists_2` outperformed `all_13`
- `no_LowerBack` outperformed `all_13`

This is now a real empirical result on the fresh split.

But it still needs repeated-split or nested-evaluation confirmation before becoming a strong deployment claim.

### 10.4 The Ceiling Matters

The clean ceiling at `8.22` is meaningfully better than the clean deployable models.

This suggests:

- the target is still learnable to some degree
- the deployable stack is not saturating the task
- covariates / latent clinical information still matter

### 10.5 DL Still Looks Weak Relative to the Clean Feature Baselines

The corrected DL rerun that completed (`P3B`) was clearly worse than the clean feature baselines.

There is no current evidence that DL rescues the task under the corrected protocol.

## 11. Recommended Next Steps

These are the practical next steps in priority order.

### 11.1 Finish the Corrected Long-Running Reruns

Priority:

1. full nested LOOCV
2. corrected subdomain rerun
3. finish the corrected DL rebenchmark

These are now mainly compute/time issues, not code-design issues.

### 11.2 Freeze the New Outer Split

Do not reintroduce the original mistake.

Rules:

- `results/paper3_split.json` is now the clean outer test split
- no architecture sweep on that test set
- all future selection inside dev only

### 11.3 Investigate the Wrist Result Seriously

Now that it survived contamination cleanup, the right next study is not "celebrate wrists."

It is:

1. rerun on multiple fresh outer splits
2. bootstrap subset comparisons
3. test whether K-selection is biasing against full-sensor models
4. test subset-specific raw feature extraction and subset-specific distillation

### 11.4 Do Not Let `S4` Quietly Become the New Contaminated Winner

On the clean split:

- `S4_stack_ext_K160` numerically beat the pre-specified `S6`

That is interesting, but if we now promote `S4` as the new winner based on this one fresh test split, we simply recreate the old mistake with a new split.

Correct response:

- treat `S4` as a hypothesis for the next development cycle
- validate it on a future untouched split or nested CV

### 11.5 Improve the Stack Where the Error Really Lives

Now that the outer split is clean, the next meaningful work is:

- better out-of-fold distillation
- repeated-split evaluation
- residual models / quantile models for the severe tail
- potentially multi-view stacks rather than larger monolithic DL models

## 12. Operational Notes For the Next Agent

If continuing this work:

1. Use the remote host:
   - `ssh -p 40005 root@46.228.83.78`
2. Repo:
   - `/root/pd-imu`
3. Clean split artifact:
   - `/root/pd-imu/results/paper3_split.json`
4. Keep `WEARGAIT_SPLIT_FILE=/root/pd-imu/results/paper3_split.json` for all fresh reruns tied to Paper3.
5. Do not overwrite Paper3 with old root-level legacy artifacts.
6. If rerunning LOOCV or DL, budget substantial uninterrupted time.

## 13. Final Current State

As of this memo:

- contamination taxonomy is understood
- active code paths are fixed
- clean benchmark rerun is complete
- clean stats rerun is complete
- corrected targeted sensor ablation rerun is complete
- paper3 is rebuilt from those clean results
- nested LOOCV and corrected subdomain reruns still remain
- DL rebenchmark is partially completed and already unfavorable to DL

That is the current truthful state of the project.
