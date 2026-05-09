# PROPOSALS

> **Archive status, 2026-05-09:** historical proposal list only. Current canonical numbers and manuscript routing are in `CLAUDE.md`, `paper.md`, `CURRENT_PAPER.html`, and `render_current_paper.py`; current T3 valid-range headline is iter47 CCC `0.3784` / LOSO `0.150`, while old observable-subdomain, Paper3, and iter5 T3 values here are not current deployment results.

## Purpose

This document turns the current research recommendations into an execution plan
for this repo. It is based on:

- `new-paper.html`
- the current experiment runners and artifact layout
- the validated result artifacts already in `results/`
- recent external work on time-series foundation models, item-level PD scoring,
  and freezing-of-gait transfer learning

The goal is not to propose another generic model sweep. The goal is to identify
the few directions that could plausibly create a real step change in prediction
quality, while being explicit about what is and is not possible with the
current dataset.


## Current Readout From The Repo And Paper

### What is already true

- Pure IMU-only total UPDRS-III is currently bounded around `MAE ~8.21 +- 0.41`
  across 10 splits.
- The observable gait subdomain is much stronger at `MAE ~3.21 +- 0.43`.
- The best observable items are already clinically coherent:
  toe tapping, arising from chair, gait, posture-related components.
- The hardest item is freezing of gait, which is effectively unsolved in the
  current lab setup.
- Scratch DL is not competitive. The paper reports `InceptionTime MAE=10.64`,
  and the current `results/dl_experiment_results.json` is still far behind the
  feature stack.
- Single-split feature wins do not survive 10-split validation. The repo has
  already demonstrated this for stride variability in
  `results/followup_v3_results.json`.

### What this means

- Another plain total-score regressor is unlikely to produce a real gain.
- Another hand-crafted feature fishing expedition is unlikely to produce a real
  gain.
- The strongest remaining signal lives in:
  1. better target formulation
  2. better use of task structure
  3. transfer-pretrained hybrid models
  4. dedicated modeling of rare phenomena such as FoG
  5. new modalities, if the objective is true total-score improvement


## Baseline Artifacts To Anchor Every New Experiment

Every new proposal should compare against these existing artifacts first.

| Area | Current runner | Current artifact | Role |
|---|---|---|---|
| Clean held-out benchmark | `run_clean_benchmark.py` | `results/clean_benchmark_results.json` | deployable total-score baseline |
| Main 10-split ablation | `run_ablation_v3.py` | `results/ablation_v3_results.json` | official IMU-only and clinician-augmented totals |
| Follow-up validation | `run_followup_v3.py` | `results/followup_v3_results.json` | negative controls, PD-only LOOCV sanity |
| Item and subdomain models | `run_subdomain_v3.py` | `results/subdomain_v3_results.json` | observable vs unobservable, item-level behavior |
| DL reference | `run_dl_experiments.py`, `run_dl_rebenchmark.py` | `results/dl_experiment_results.json`, `results/dl_rebenchmark_results.json` | corrected DL baseline |
| Sensor reduction | `run_sensor_ablation.py` | `results/sensor_ablation_results.json` | deployment subsets and sensor-specific signal |
| Stats/manuscript tables | `run_stats_report.py`, `generate_html_paper3.py` | `results/stats_report.json`, `paper3.html` | reporting layer |


## Proposal 1: Structured Item/Subitem Ordinal Modeling

### Why this is the highest-priority proposal

The repo already shows that the signal is not uniform across items. The paper
also shows that the total score is partly structurally unobservable from gait
IMU. The cleanest way to exploit what is learnable is to stop training only on
one scalar total and instead predict clinically coherent item or subitem scores.

This is the most likely path to a real gain within the current dataset.

### Core idea

Build one structured model that:

1. predicts item or subitem scores as ordinal targets
2. respects bilateral structure where present
3. enforces sum consistency to:
   - observable subtotal
   - unobservable subtotal
   - total score
4. reports uncertainty or confidence per item

This is not the same as the previously failed two-stage scalar pipeline
(`observable -> total`). That approach compressed the problem into one
intermediate scalar too early. The proposed model uses many more supervised
constraints.

### Recommended implementation path

#### First ML version

- Train ordinal boosted models per item or subitem.
- Use classifier-chain style dependencies or a meta-level reconciliation step to
  capture between-item structure without leakage.
- Aggregate expected item scores exactly to observable and total scores.
- Use the current validated feature matrix as input first. Do not add new
  feature groups in v1 of this experiment.

#### Second DL version

- Replace the input representation with raw-sequence embeddings, but keep the
  same structured item-level target formulation.
- Shared encoder, multiple ordinal heads, one sum-consistency penalty.

### Success criteria

- Observable subdomain improvement over `results/subdomain_v3_results.json`
  across 10 splits.
- PD-only improvement on observable and axial composites.
- Better calibration and lower per-item error for items 9-14.
- Modest total-score gain is acceptable; major observable gain is the main goal.

### Repo mapping

Best anchors:

- `run_subdomain_v3.py`
- `run_ablation_v3.py`
- `updrs_columns.py`
- `data_split.py`

Recommended new runner:

- `run_structured_items.py`

Recommended artifacts:

- `results/structured_items_results.json`
- `results/structured_items_oof.csv`
- `results/structured_items_error_breakdown.json`

Recommended comparisons:

- `results/subdomain_v3_results.json`
- `results/ablation_v3_results.json`
- `results/followup_v3_results.json`


## Proposal 2: Task-Aware Subject Bag Modeling

### Why this matters

The current feature pipeline is very strong, but the learned path still has a
representation problem: clinically distinct tasks are being collapsed too early.
Chair rise, turning, balance, tandem gait, and steady walking should not all be
treated as interchangeable evidence for every item.

### Core idea

Represent each subject as a bag of task segments or recording segments with:

- task ID
- segment type or event mask
- missing-sensor mask
- duration and quality metadata

Use attention or gated pooling so the model can learn:

- chair-rise evidence for item 9
- turning evidence for item 11 and item 12
- posture and sway evidence for items 12-14
- steady walking evidence for gait and bradykinesia items

### Why this is different from current DL

`run_dl_experiments.py` already contains MIL and task-conditioned variants, but
they still target the total score and are not paired with structured item-level
supervision. The proposed change is the combination:

- task-aware bags
- structured item targets
- hybrid fusion back into the tabular baseline

### Success criteria

- Gains on items 9-14 and on axial/lower-limb composites
- More interpretable task attention patterns
- Better PD-only observable correlation

### Repo mapping

Best anchors:

- `run_dl_experiments.py`
- `run_dl_rebenchmark.py`
- `run_subdomain_v3.py`

Recommended new runner:

- `run_task_bag_dl.py`

Recommended artifacts:

- `results/task_bag_dl_results.json`
- `results/task_attention_summary.json`
- `results/task_bag_error_breakdown.json`

Recommended comparisons:

- `results/dl_experiment_results.json`
- `results/dl_rebenchmark_results.json`
- `results/subdomain_v3_results.json`


## Proposal 3: Pretrained Hybrid Encoder Plus Residual Fusion

### Why this is the best DL bet

Scratch DL has already lost. That does not mean representation learning is dead.
It means raw end-to-end DL should not replace the hand-crafted feature stack at
this sample size. The better bet is:

- pretrain a sequence encoder
- extract per-task embeddings
- fuse those embeddings with validated hand-crafted features in GBDT
- optionally train DL only on residual error left by the stack

### Core idea

Use a pretrained or self-supervised encoder to produce extra features, not the
final prediction directly.

Two practical variants:

1. Late fusion:
   handcrafted features + learned embeddings -> LightGBM/CatBoost/XGBoost stack

2. Residual modeling:
   stack prediction -> DL predicts residual correction for item or total scores

### Why this is scientifically defensible

- The repo already shows that tabular ML is the right final estimator at this N.
- Recent time-series foundation-model work suggests that pretraining can still
  produce useful downstream features.
- This direction is much lower-risk than replacing the whole stack.

### Success criteria

- Improvement over the current total-score stack without degrading observable
  performance
- Embeddings add information that survives 10-split validation
- Stable performance, not just single-split wins

### Repo mapping

Best anchors:

- `run_dl_experiments.py`
- `run_dl_rebenchmark.py`
- `run_clean_benchmark.py`
- `run_ablation_v3.py`

Recommended new runners:

- `run_ssl_pretrain.py`
- `run_hybrid_fusion.py`

Recommended artifacts:

- `results/ssl_pretrain_results.json`
- `results/hybrid_fusion_results.json`
- `results/hybrid_fusion_ablation.json`

Recommended comparisons:

- `results/clean_benchmark_results.json`
- `results/dl_rebenchmark_results.json`
- `results/ablation_v3_results.json`


## Proposal 4: Freezing Of Gait As A Separate Transfer-Learning Program

### Why this needs its own track

The paper's freezing item is effectively flatlined. This is not a normal
regression failure. It is a rarity and task-mismatch problem.

FoG should be treated as:

- a rare-event problem
- a transfer-learning problem
- potentially a detection-plus-severity problem

### Core idea

Train a dedicated FoG pipeline with:

- external FoG datasets for pretraining
- binary event detection head
- patient-level FoG propensity or burden head
- mapping from propensity/burden to item 11 severity

For evaluation, use both event-level and patient-level metrics.

### Success criteria

- Item 11 `r` materially above 0
- better discrimination for subjects with non-zero FoG scores
- improved lower-limb and observable subtotal performance when the FoG head is
  integrated back into the structured item model

### Repo mapping

Best anchors:

- `run_transfer.py`
- `run_subdomain_v3.py`

Recommended new runner:

- `run_fog_transfer.py`

Recommended artifacts:

- `results/fog_transfer_results.json`
- `results/fog_transfer_eval.json`
- `results/fog_patient_level_predictions.csv`

Recommended comparisons:

- `results/subdomain_v3_results.json`
- `results/transfer_results.json` if regenerated

External-data prerequisite:

- requires an explicit external FoG dataset ingest path


## Proposal 5: Phenotype-Aware Experts And PD-Only Optimization

### Why this matters

The paper shows that healthy controls inflate mixed-cohort metrics and that
unobservable items can appear correlated because they ride on global disease
severity. A single global model may be blurring separable regimes:

- HC vs PD
- mild vs advanced PD
- axial-dominant vs limb-dominant presentation
- DBS/non-DBS or disease-duration strata

### Core idea

Use mixture-of-experts or gated ensembles so different submodels specialize in
different severity or phenotype regimes. The primary selection target should be:

- PD-only total performance
- PD-only observable performance
- phenotype-stratified calibration

### Success criteria

- higher PD-only `r`
- lower PD-only MAE
- smaller performance collapse after removing HC subjects

### Repo mapping

Best anchors:

- `run_clean_benchmark.py`
- `run_loocv_stack.py`
- `run_subdomain_v3.py`

Recommended new runner:

- `run_moe_benchmark.py`

Recommended artifacts:

- `results/moe_benchmark_results.json`
- `results/moe_pdonly_results.json`
- `results/moe_slice_report.json`

Recommended comparisons:

- `results/clean_benchmark_results.json`
- `results/followup_v3_results.json`
- `results/subdomain_v3_results.json`


## Proposal 6: Multimodal Total-Score Modeling

### Why this is the only believable route to a major total-score jump

Gait IMU does not observe speech, facial expression, rigidity, and most explicit
upper-limb examination tasks. If the true objective is a materially better total
UPDRS-III estimate, more modeling alone is not enough. The system needs more
modalities.

### Candidate modalities

- voice or speech features for item 1
- face/video for item 2 and posture-related cues
- explicit upper-limb task data or hand IMUs for items 4-6
- EMG or richer biosignals for rigidity proxies

### Repo status

This cannot be executed with the current data alone. It is a future-data
proposal, not a next-command proposal.

### Repo mapping

Closest current anchors:

- `run_clean_benchmark.py`
- `run_transfer.py`
- `data_split.py`

Recommended future runner:

- `run_multimodal_total.py`

Recommended future artifacts:

- `results/multimodal_total_results.json`
- `results/multimodal_ablation_results.json`


## What Not To Spend Time On

The following directions currently look low-yield:

- another plain total-score CNN/Transformer from scratch
- another large feature-group sweep without a change in target formulation
- single-split optimization
- selecting models on mixed-cohort total `r` alone
- claiming major total-score progress without addressing the observability
  ceiling


## Concrete Experiment Roadmap

### Phase 0: Lock Baselines And Promote The Right Metrics

#### Goal

Make sure every future experiment is compared against the correct artifacts and
selected on the right endpoints.

#### Actions

- Reuse `run_clean_benchmark.py` for clean total-score held-out comparison.
- Reuse `run_subdomain_v3.py` for observable/unobservable/item-level anchors.
- Reuse `run_followup_v3.py` to keep PD-only LOOCV and negative controls alive.
- Reuse `run_stats_report.py` only after a model is finalized, not for model
  selection.

#### Primary metrics for new work

- PD-only observable MAE and `r`
- observable 10-split MAE
- axial/lower-limb composite performance
- total-score MAE only after the above

#### Artifacts to refresh if needed

- `results/clean_benchmark_results.json`
- `results/subdomain_v3_results.json`
- `results/followup_v3_results.json`


### Phase 1: Structured Item ML Baseline

#### Goal

Get the highest-probability pure-ML win before touching large DL work.

#### Recommended work

- Create `run_structured_items.py`.
- Reuse the feature cache and split logic from `run_ablation_v3.py` and
  `run_subdomain_v3.py`.
- Train ordinal item/subitem models.
- Aggregate predicted items exactly into observable and total scores.
- Run:
  - primary split
  - 10-split validation
  - PD-only LOOCV on the aggregated outputs

#### Expected outputs

- `results/structured_items_results.json`
- `results/structured_items_oof.csv`
- `results/structured_items_error_breakdown.json`

#### Go/no-go gate

Continue only if:

- observable 10-split improves over `results/subdomain_v3_results.json`, or
- PD-only observable and axial metrics improve materially even if total changes
  are modest


### Phase 2: Task-Aware Bag Model

#### Goal

Test whether preserving task identity improves the learned representation on the
clinically meaningful items.

#### Recommended work

- Create `run_task_bag_dl.py`.
- Reuse raw window loading, bag construction, and encoders from
  `run_dl_experiments.py`.
- Change target from total-only to structured item or composite targets.
- Add task IDs and event/query pooling.
- Evaluate late fusion into the structured item baseline.

#### Expected outputs

- `results/task_bag_dl_results.json`
- `results/task_attention_summary.json`

#### Go/no-go gate

Continue only if:

- items 9-14 improve, or
- the bag embeddings improve the fused GBDT model over Phase 1


### Phase 3: SSL/Pretrained Hybrid Fusion

#### Goal

Use representation learning without discarding the validated stack.

#### Recommended work

- Create `run_ssl_pretrain.py` for pretraining or encoder export.
- Create `run_hybrid_fusion.py` for embedding + feature fusion.
- Reuse:
  - `run_dl_experiments.py` data loading
  - `run_clean_benchmark.py` evaluation protocol
  - `run_ablation_v3.py` feature selection and stack logic
- Compare:
  - features only
  - embeddings only
  - features + embeddings
  - residual-correction variant

#### Expected outputs

- `results/ssl_pretrain_results.json`
- `results/hybrid_fusion_results.json`
- `results/hybrid_fusion_ablation.json`

#### Go/no-go gate

Continue only if:

- the fused model beats the clean benchmark on held-out MAE and does not lose
  observable/item-level accuracy, or
- the embeddings clearly improve Phase 1 item models


### Phase 4: FoG Transfer Track

#### Goal

Stop item 11 from being the permanent blind spot.

#### Recommended work

- Create `run_fog_transfer.py`.
- Extend `run_transfer.py` style logic to external FoG datasets.
- Export patient-level FoG outputs.
- Plug those outputs into the Phase 1 structured item model as an additional
  feature or auxiliary prediction.

#### Expected outputs

- `results/fog_transfer_results.json`
- `results/fog_transfer_eval.json`
- `results/fog_patient_level_predictions.csv`

#### Go/no-go gate

Continue only if item 11 ceases to be degenerate.


### Phase 5: Phenotype-Aware Experts

#### Goal

Recover PD-only performance and reduce mixed-cohort shortcut learning.

#### Recommended work

- Create `run_moe_benchmark.py`.
- Start with simple expert partitions:
  - HC vs PD
  - low vs medium/high UPDRS bins
  - DBS vs non-DBS if counts permit
- Then try learned gating.
- Evaluate slice stability and calibration, not just pooled MAE.

#### Expected outputs

- `results/moe_benchmark_results.json`
- `results/moe_pdonly_results.json`
- `results/moe_slice_report.json`

#### Go/no-go gate

Keep only if PD-only metrics improve and slice-wise calibration remains sane.


### Phase 6: Reporting And Paper Integration

#### Goal

Move only validated wins into the manuscript layer.

#### Recommended work

- Update `run_stats_report.py` after locking the winning config.
- Extend `run_paper_supplements.py` if a new item-level or FoG section is added.
- Update `generate_html_paper3.py` only after the primary artifact names are
  finalized.

#### Expected outputs

- refreshed `results/stats_report.json`
- refreshed figures in `figures/`
- regenerated `paper3.html`


## Recommended Order Of Attack

If time is limited, run the roadmap in this order:

1. Phase 1 structured item ML baseline
2. Phase 3 hybrid fusion
3. Phase 2 task-aware bag modeling
4. Phase 4 FoG transfer
5. Phase 5 phenotype-aware experts
6. Phase 6 reporting

If new modalities become available, start a separate multimodal track rather
than mixing that work into the current pure-IMU benchmark.


## Practical Notes For Future Implementation

- Keep new experiment runners self-contained where possible.
- Reuse `project_paths.py` artifact helpers so outputs always land in `results/`.
- Do not promote any new result without:
  - primary split
  - 10-split validation when applicable
  - PD-only analysis where clinically relevant
- Treat observable/item-level gains as first-class wins, not just supporting
  analyses.


## External References Behind These Proposals

- MOMENT, ICML 2024:
  https://proceedings.mlr.press/v235/goswami24a.html
- Scaling Wearable Foundation Models, ICLR 2025:
  https://proceedings.iclr.cc/paper_files/paper/2025/hash/94b25992757a549470c8f8dfe73d8df6-Abstract-Conference.html
- HiMAE, arXiv 2025:
  https://arxiv.org/abs/2510.25785
- Gait/posture item scoring in 225 PD, Frontiers 2025:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12370646/
- MDS-UPDRS subitem quantification with 2 IMUs, Sensors 2024:
  https://pubmed.ncbi.nlm.nih.gov/38610406/
- Leg-agility continuous scoring from smartphone IMU:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC8975117/
- DeepFoG:
  https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2021.537384/full
- FoG bias and transfer:
  https://arxiv.org/abs/2502.09626
