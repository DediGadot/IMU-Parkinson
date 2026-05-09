# CODEX Proposals

> **Archive status, 2026-05-09:** historical proposal list only. Current canonical numbers and manuscript routing are in `CLAUDE.md`, `paper.md`, `CURRENT_PAPER.html`, and `render_current_paper.py`; current T3 valid-range headline is iter47 CCC `0.3784` / LOSO `0.150`, while old direct-observable, Paper3, and iter5 T3 values here are not current deployment results.

This file is the current execution plan for follow-up work in this repo. It is
based on:

- `NEW.html`
- `findings.md`
- the validated artifacts in `results/`
- the live remote runner at `root@46.228.83.78:40005` in `/root/pd-imu`

The goal is not to propose another broad model sweep. The goal is to rank only
the next steps that still have real upside after the March 12-13 PD-only and
calibration-ablation runs.

## Current Ground Truth

These points are already established by the repo artifacts and should be treated
as fixed context, not hypotheses:

1. The direct observable endpoint is the best result in the repo.
   Evidence: `results/pd_only_phase3.json` gives PD-only LOOCV `MAE=1.769`,
   `CCC=0.56` for items 3.9-3.14, with `1.717 +/- 0.331` in PD-only 10-split.

2. Total UPDRS-III is limited by both observability mismatch and calibration
   collapse.
   Evidence: `NEW.html` and `results/pd_only_phase2.json` /
   `results/pd_only_phase5.json` show total-score compression toward the mean;
   `NEW.html` reports PD-only LOOCV `MAE=8.15`, `CCC=0.37`, `cal_slope=0.256`.

3. Demographics-first residual modeling is the best total-score fix already run.
   Evidence: `results/calibration_ablation_phase2.json` improves total score
   from control `MAE=8.128`, `CCC=0.159` to residual `MAE=7.699`,
   `CCC=0.396`.

4. Generic observable-target ablations do not beat the purpose-built direct
   observable pipeline.
   Evidence: `results/calibration_obs_ablation_phase2.json` and
   `results/calibration_obs_ablation_phase5.json` top out around
   `CCC=0.363-0.370`, well below the dedicated direct-observable model
   (`CCC=0.56`).

5. Post-hoc calibration is not the answer.
   Evidence: `findings.md` and `results/calibration_ablation_phase4.json` show
   only marginal agreement gains, often with worse MAE.

6. The previous Euler and FreeAcc negative result is not decisive.
   Evidence: `findings.md` notes that the run used a simpler fresh extractor,
   so it was not a clean additive test on top of the full v2 feature bank.

7. More sensor-reduction work is low priority.
   Evidence: `NEW.html` and `results/pd_only_phase6.json` already show that the
   5-sensor minimal set matches all 13 sensors and wrists-only is competitive.

## Remote Execution Reality

New runs should be treated as remote-first:

- Host: `ssh -p 40005 root@46.228.83.78`
- Repo on host: `/root/pd-imu`
- Preferred workflow: `./gpu.sh <script.py> [args]`
- Pull artifacts back with: `./gpu.sh --pull`
- Check remote jobs with: `./gpu.sh --status`
- Open a shell with: `./gpu.sh --ssh`

The local `gpu.sh` already targets the same host and path. Use it instead of
ad hoc rsync unless a run truly needs manual SSH inspection.

## Priority Order

### Priority 0: Update the paper narrative around what is already true

This is the highest-value near-term task because the strongest results already
exist.

Do:

- Make the direct observable endpoint the primary positive result.
- Present residual modeling as the main total-score sensitivity analysis.
- Treat held-out total-score results as contextual, not a pure PD claim.
- Keep the 5-sensor finding as a deployment note, not the paper's center.

Why now:

- The repo already has enough evidence for a sharper paper without more compute.
- The current proposal work should not pretend the best next move is another
  generic total-score model.

Likely files:

- `generate_html_paper3.py`
- `NEW.html` source pipeline
- `findings.md`

### Priority 1: Structured direct-observable item modeling

This is the best remaining algorithmic bet.

Hypothesis:

- The model should predict the directly observable items or subitems
  individually, then sum them, instead of training only on one scalar
  observable total.

Why this is first:

- The direct observable family is already the strongest target in the repo.
- Generic observable regressors underperform the dedicated direct model.
- Bounded and ordinal structure matters more here than for the total score.

Minimum experiment:

- Predict items 3.9-3.14 or their subitems with bounded or ordinal tree models.
- Enforce exact sum-consistency back to the direct observable subtotal.
- Compare against the current direct-observable baseline on the same PD-only
  splits.

Suggested implementation:

- New runner: `run_structured_items.py`
- Inputs: existing validated feature matrix first; no new feature groups in v1
- Outputs:
  - `results/structured_items_results.json`
  - `results/structured_items_oof.csv`
  - `results/structured_items_error_breakdown.json`

Success bar:

- Beat `results/pd_only_phase3.json` on direct observable MAE or CCC, or show a
  materially better calibration profile with comparable MAE.

### Priority 2: FM protocol hardening plus task-aware FM pooling

This is the best remaining representation-level experiment.

Hypothesis:

- The FM path still leaves PD-only signal on the table because it uses fragile
  normalization and overly simple subject-level mean pooling across recordings.

Why this stays high:

- The current FM story is weaker for within-PD grading than for PD-vs-HC
  separation.
- The local and remote proposal drafts both point to the same bottleneck:
  task structure is being collapsed too early.

Minimum experiment:

- Replace global-like FM normalization with split-safe or per-recording
  normalization.
- Compare plain subject mean against per-task mean/variance blocks or a small
  late-fusion set aggregator.
- Evaluate on PD-only total and direct observable endpoints.

Suggested implementation:

- Extend `run_rocket_ablation.py` or add `run_task_aware_fm.py`
- Outputs:
  - `results/task_aware_fm_results.json`
  - `results/task_aware_fm_oof.csv`

Success bar:

- A real PD-only gain beyond noise on either direct observable or residualized
  total score.

### Priority 3: Clean additive `v2 + Euler + FreeAcc`

This should be run once, correctly, then either kept or killed.

Hypothesis:

- Euler and FreeAcc may help, but only if they are added on top of the full v2
  cache rather than tested through a simplified re-extraction path.

Why it is not higher:

- The current evidence is negative-to-neutral.
- Even a clean positive is more likely to produce a modest gain than a step
  change.

Minimum experiment:

- Start from the full cached v2 feature bank.
- Add Euler and FreeAcc columns without replacing the existing extractor.
- Evaluate first on the direct observable endpoint, then on total score.

Suggested implementation:

- Extend `run_calibration_ablation.py --phase 1`
- Output: `results/calibration_ablation_phase1_additive.json`

Success bar:

- Clear improvement on the direct observable target. If the gain is trivial,
  stop here.

### Priority 4: Lock exactly one winner on the held-out split

Do not keep producing cross-validation-only wins.

Rule:

- Once Priority 1-3 produce a clear winner, run it once on Track A
  (`results/paper3_split.json`) and update the paper.

Why:

- The held-out split is already defined.
- The repo does not need more disconnected CV improvements that never reach the
  locked test.

## Deprioritized Paths

Do not spend more time here unless a higher-priority path unexpectedly fails:

- More post-hoc calibration variants
- More HC-augmented training for PD-only claims
- Another scratch end-to-end DL sweep on raw IMU
- More sensor-count ablation
- Repeating the previous non-additive Euler/FreeAcc comparison
- Generic total-score regressors that do not change the target formulation

## Suggested Execution Sequence

1. Tighten the paper and reporting around the current artifact-backed wins.
2. Run structured direct-observable item modeling on the remote server.
3. If that stalls, run FM protocol hardening plus task-aware pooling.
4. Run one clean additive `v2 + Euler + FreeAcc` test.
5. Promote exactly one winner to the locked held-out split.

## Notes Against Overreach

- The strongest near-term story in this repo is not "we solved total
  UPDRS-III."
- The strongest story is "wearable gait IMUs robustly predict the directly
  observable motor subdomain, and residual modeling is the best correction when
  total score must still be reported."
- `PROPOSALS.md` on the remote server is still useful background, but this file
  should be treated as the newer plan because it incorporates the March 12-13
  residual and observable-ablation results.
