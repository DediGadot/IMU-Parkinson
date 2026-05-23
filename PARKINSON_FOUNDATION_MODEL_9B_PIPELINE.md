# Parkinson Foundation Model 9B Pipeline

Created: 2026-05-23

Purpose: design an end-to-end, 9B-class fine-tuning and evaluation pipeline for a Parkinson foundation model using WearGait-PD, PPMI, and the external datasets tracked in this repository.

This is a design artifact, not a preregistration, model result, protected-data probe, or canonical T1/T3 claim update.

## Executive Take

The right architecture is not "stuff IMU samples into a chatbot." It is a two-tower Parkinson foundation model:

1. A sensor-time-series foundation encoder for raw or derived motion, trained with self-supervised and multitask clinical objectives.
2. A Qwen3 8B-class language/reasoning backbone, adapter-tuned to explain, audit, retrieve, and reason over clinical context, dataset schemas, model provenance, and patient-visit summaries.

The language model should not be the sole regression mechanism for UPDRS. Final T1/T3 predictions should come from calibrated numeric heads over frozen or lightly tuned multimodal embeddings, with the LLM used for instruction following, report generation, retrieval, data-QC, and hypothesis generation.

The X post's useful idea is operational: autonomous fine-tuning can be made cheap and robust by using JSONL datasets, Unsloth/QLoRA, small trainable adapter fractions, checkpointing, validation-loss monitoring, error recovery, and sleep/resume orchestration. In this repo, that should be implemented as auditable scripts and job manifests, not browser-only Colab clicking. Google Drive is also not an acceptable default for DUA-controlled Parkinson datasets.

## Current Repo Truth

Do not let the foundation-model plan overwrite the current leakage audit:

- WearGait-only small-N modeling is saturated under the current gates.
- Current internal reference points live in `CLAUDE.md`: T1 canonical floor CCC 0.6550, T1 hygiene-corrected candidate CCC 0.7170, T3 corrected valid-range CCC 0.3784, and T3 LOSO mean CCC 0.150.
- PPMI is the priority external source. The current remote CSV bundle has labels and derived gait features, but not raw Verily/Opal/Axivity streams needed for strict raw-sensor replication.
- External public datasets already support transportability rows, not internal WearGait canonical updates.
- All future reportable work must keep subject/visit/time-grouped splits, fold-local preprocessing, manifest sidecars, null gates, and predeclared formulas.

## Model Choice

Use a 9B-class stack:

- `Qwen/Qwen3-8B` as the concrete language backbone. It is an official Apache-2.0 Qwen3 model with 8.2B parameters, 36 layers, and 32K native context.
- `Qwen/Qwen3-Embedding-8B` for retrieval and instruction-aware embeddings over papers, protocols, code, schema reports, and patient-visit summaries.
- A Parkinson Sensor Encoder, initially 50M-300M parameters, trained from scratch or adapted from a wearable foundation model. Do not assume generic HARNet/MOMENT-style frozen encoders will solve severity at N~100; this repo already falsified that for WearGait-only training.
- Lightweight projectors from sensor/tabular embeddings into Qwen token space for explanation tasks.
- Numeric heads for CCC-optimized regression, ordinal item scoring, uncertainty, and conformal retention.

If an official Qwen 3.5/3.6 9B checkpoint becomes available and passes license/tooling checks, it can replace Qwen3-8B. I did not find a verified official `Qwen 3.6 9B` source in the current pass, so the audited plan should name Qwen3-8B.

## Dataset Plan

### Tier A: Usable Now

These can support design, dry runs, or transportability work without new protected-data access:

- WearGait-PD: 13 body-worn IMUs at 100 Hz, N=178 total with 98 PD and 80 HC. Use as the internal benchmark and leakage discipline reference.
- PPMI downloaded CSV bundle on the remote: MDS-UPDRS Part III labels and clinical covariates, plus derived Opal and Axivity gait/activity tables. The derived Opal table is the immediate PPMI feature matrix; the raw sensor streams are still absent.
- Public external evaluation routes already represented in the repo: COPS, TLVMC/DeFOG, FoG-STAR, PDFE turning, and Parkinson@Home. Use them for external-validity probes, not for internal headline claims.
- CARE-PD: public 3D mesh gait archive with UPDRS gait-score labels. Use for motion-representation pretraining and gait-score transfer, not T1/T3 total UPDRS claims.
- Public subitem/context datasets: Monipar, BIOCLITE, Daphnet FoG, PADS, Papadopoulos phone-call tremor, and PD-BioStampRC21. Use as pretraining, stress tests, or task-specific side heads only.

### Tier B: Access-Gated Priority Queue

The current repo queue has six submit-ready but not compute-ready routes:

1. PPMI / Verily Study Watch: first priority because it is wrist-native, longitudinal, and has MDS-UPDRS linkage.
2. Personalized Parkinson Project / PD Virtual Motor Exam: Verily Study Watch peer route with in-clinic Part III motor-exam context.
3. WATCH-PD: Apple Watch/iPhone/APDM route with MDS-UPDRS Parts I-III and longitudinal early-PD design.
4. CNS Portugal / Lobo AX3 gait: structured 10-meter walk, wrist plus lower-back AX3, Part III labels.
5. MJFF Levodopa Response / Hssayeni: raw multi-placement wearable data with MDS-UPDRS and symptom labels, Synapse DUA gated.
6. ICICLE-GAIT: lower-back AX3 free-living gait with longitudinal MDS-UPDRS Part III.

No schema probe, download, cache extraction, preregistration, or model run is allowed for these until approval and the repo's post-approval schema gates pass.

### Tier C: More Datasets To Add Or Request

Prioritize datasets by raw-sensor availability, clinician-rated Part III linkage, repeated visits, and sensor-placement overlap:

- UK Biobank accelerometry: broad unlabeled/pretraining signal, not Parkinson-specific severity labels. Use for activity/motion priors only.
- NHANES / public accelerometry cohorts: broad motion pretraining and fairness/stress testing, not Parkinson severity labels.
- ProPark AX6 home monitoring: larger PD wrist route with total Part III and tremor subitems reported in the route audit, but request-only and not yet top queue.
- Mobilise-D CVS if row-level MDS-UPDRS plus lower-back wearable data become accessible. The public TVS is algorithm-validation oriented, not a severity target.
- OPDC/OxQUIP wearable progression if DPUK/data-owner access confirms aligned APDM/clinical files.
- Luxembourg upper-limb subitem and Pre-QuantiPark ActiMyo only as narrow subitem/pharmacodynamic context; they are not broad T1/T3 model builders.

## Data Product

Build one canonical data product before model training:

`pfm_events.parquet`

Required fields:

- `dataset_id`, `subject_id`, `visit_id`, `session_id`, `recording_id`
- `grouping_subject_key`, `grouping_visit_key`, `site`, `cohort`
- `sensor_modality`, `sensor_placement`, `laterality`, `sampling_rate_hz`, `units`
- `task`, `task_phase`, `start_time`, `end_time`, `duration_s`
- `med_state`, `dbs_state`, `levodopa_equivalent`, `days_since_diagnosis`
- `target_name`, `target_value`, `target_source`, `target_time`, `target_valid_range_passed`
- `feature_source`: `raw_window`, `derived_feature`, `clinical_table`, `text_protocol`, `synthetic`
- `leakage_scope`: `target_free`, `train_fold_only`, `external_eval_only`, `protected_access_only`

Each artifact must have a manifest with script, git SHA, command, creation time, input hashes, labels-used flag, fold scope, normalization scope, leakage status, and rationale.

## Tokenization And Representation

### Raw IMU Tokenizer

For raw streams:

- Segment into fixed windows: 2 s, 5 s, 10 s, 30 s, and task-full windows where applicable.
- Preserve physical amplitude. Do not use amplitude-scaling augmentation because amplitude carries severity signal in this codebase.
- Use placement-aware channels: axes, magnitude, gravity/linear split if available, gyroscope, and metadata tokens for placement/laterality/sampling rate.
- Convert each window to patch embeddings through a small Conv1D/Transformer stem.
- Optionally use a vector-quantized codebook for discrete motion tokens, but keep continuous embeddings for regression heads.

### Derived Feature Tokenizer

For PPMI Opal/Axivity and existing WearGait feature tables:

- Encode each feature as `feature_name`, `value_bin`, `unit`, `task`, `placement`, and missingness.
- Normalize inside train folds only for supervised evaluation.
- Keep raw units available to the language model for audit/explanation.

### Clinical Event Tokenizer

Encode each visit as a temporal event sequence:

- demographics, cohort, diagnosis duration, medication/DBS state
- H&Y and MDS-UPDRS parts/items where allowed by the task
- non-motor scales, cognitive batteries, MoCA, SCOPA-AUT, GDS, RBD, UPSIT
- omics/imaging summary availability flags, not raw high-dimensional omics until a separate governance path exists

Clinical labels used as targets must not leak into deployable inputs. Separate "clinical-augmented" from "sensor-only" and "future deployment" tracks.

### Text/RAG Corpus

Build a retrieval corpus with Qwen3-Embedding-8B:

- local code and manifests
- PPMI methods PDFs and data dictionaries after allowed access
- MDS-UPDRS item definitions and valid ranges
- dataset protocols and sensor-placement specs
- current paper/audit files
- peer-reviewed Parkinson wearable literature

Do not let retrieval include held-out test labels, row-level predictions, or schema-probe protected snippets.

## Training Stages

### Stage 0: Governance And Split Freezing

Deliverables:

- dataset registry
- subject/visit/site split manifest
- protected-data boundary map
- source licenses and DUA flags
- leakage-null test fixtures

Hard stop if any target field is globally joined before split assignment, or if any synthetic sample lacks provenance.

### Stage 1: Sensor Encoder Pretraining

Train on raw windows where available and on derived-feature sequences where raw is unavailable.

Objectives:

- masked time/frequency patch reconstruction
- future-window prediction
- task/placement/laterality prediction
- cross-window consistency within subject and visit
- cross-sensor alignment when multiple sensors record the same task
- sensor-to-derived-feature distillation for PPMI Opal/Axivity where only derived features are available

Avoid subject-identity objectives that reward memorizing participants.

### Stage 2: Multimodal Clinical Alignment

Align motion embeddings to clinical events:

- contrastive retrieval: motion window or visit summary -> matching clinical visit summary
- visit-level item/subscore prediction on train folds only
- ordinal MDS-UPDRS item heads
- medication ON/OFF and DBS-state heads
- missingness-aware reconstruction of clinical context

This stage creates the "Parkinson representation"; it is not yet a deployment model.

### Stage 3: Qwen Adapter Tuning

Use QLoRA/LoRA through Unsloth or an equivalent auditable trainer:

- Base: Qwen3-8B 4-bit.
- Trainable modules: LoRA adapters plus multimodal projector, not full 8B weights at first.
- Data: JSONL messages built from allowed train-fold events, schema summaries, audit tasks, and synthetic instruction examples.
- Targets: dataset-QC assistant, clinical-summary assistant, feature/provenance explainer, error triage assistant, and model-card writer.
- Do not train the LLM to memorize row-level labels from held-out datasets.

Example JSONL shape:

```json
{
  "messages": [
    {"role": "system", "content": "You are ParkinsonFM. Separate sensor-only, clinical-augmented, and external-validity claims."},
    {"role": "user", "content": "Given this visit summary and feature manifest, identify leakage risks before scoring."},
    {"role": "assistant", "content": "The target column is excluded from features; normalization is train-fold-only; subject grouping is ..."}
  ],
  "metadata": {
    "dataset_id": "weargait_pd",
    "fold_id": "screen_seed_42_fold_3",
    "contains_targets": false,
    "synthetic": false
  }
}
```

### Stage 4: Supervised Numeric Heads

Train numeric heads over frozen or lightly tuned embeddings:

- T1 item heads and T1 sum
- T3 total
- item-level ordinal heads
- H&Y, medication state, ON/OFF response
- uncertainty and conformal-width heads

Use CCC, MAE, Pearson r, calibration slope, and conformal coverage. Use current repo bootstrap gates and null gates. Keep LOOCV lockboxes single-shot after pre-registration.

### Stage 5: External Validation And Continual Adaptation

Order:

1. Zero-shot external validation with no target tuning.
2. Linear-probe or low-df calibration using train folds only within the external cohort.
3. Pooled multi-dataset training with leave-dataset-out validation.
4. Only after zero-shot evidence, pre-register augmentation into WearGait training.

Never update internal WearGait canonical numbers from external-only metrics.

## Synthetic Data Strategy

Synthetic data is useful for robustness and instruction tuning; it must not manufacture primary clinical evidence.

Allowed synthetic use:

- Instruction examples from protocols, data dictionaries, and known leakage cases.
- Schema-QC examples: invalid codes, all-missing rows, target leakage, SID-shuffle bugs, global scaler bugs.
- Sensor corruption: dropout, missing channels, timestamp gaps, sampling-rate mismatch, clipping, unit conversion errors.
- Label-preserving window masking, crop/stride jitter, mild sensor-noise injection from measured device noise.
- Placement/laterality simulation only when physically justified and marked synthetic.
- Rare-event FoG/tremor simulations for representation pretraining and detector stress tests, not for primary T1/T3 regression metrics.
- Counterfactual clinical summaries for LLM calibration: "what can be claimed from sensor-only vs clinical-augmented inputs?"

Forbidden or restricted:

- Synthetic UPDRS labels counted as ground truth in evaluation.
- Target-conditioned generated windows mixed into the lockbox without fold-local generation.
- Amplitude scaling for regression-input augmentation.
- Synthetic external results, row-level predictions, or approval/schema records.
- Training the model to produce clinical advice or medication changes as an output objective.

Every synthetic row needs:

- generator script and git SHA
- source cohort and fold scope
- exact transformation
- synthetic flag
- target-free or target-conditioned flag
- allowed downstream uses

## Success Criteria

### Infrastructure Success

Pass when:

- all source datasets have manifests and license/DUA flags
- protected-data boundaries are enforced
- subject/visit/site split manifests exist
- raw and derived sensor schemas are normalized into `pfm_events.parquet`
- leakage-null fixtures pass in CI

### Representation Success

Pass when frozen embeddings improve over simple handcrafted baselines on at least three held-out tasks without using target labels for selection:

- task/placement recognition
- medication state or ON/OFF response where available
- FoG/tremor external task
- PPMI derived-gait target-free retrieval
- WearGait item-level linear probes

### Internal WearGait Success

Full-cohort internal success requires current repo gates, not vibes:

- T1: beat the hygiene-corrected iter34 candidate CCC 0.7170 by at least the current MCID/gate threshold and pass paired-bootstrap/null gates.
- T3: beat iter47 corrected valid-range CCC 0.3784 under the same discipline.
- LOSO: improve T3 two-way mean CCC from 0.150 to at least 0.25 with no collapse in either direction.
- MAE, Pearson r, calibration slope, and clinical claim labels must be reported alongside CCC.

### PPMI Transportability Success

Immediate PPMI-derived-feature path:

- PD-only Opal-derived feature transportability result with subject/visit grouping.
- T1 and T3 target construction audited from valid NP3 items.
- No raw-sensor claims.
- Success floor: positive CCC with CI excluding zero for T1 or T3, and performance above a demographics/clinical-only baseline.

Raw PPMI/Verily path after approval:

- zero-shot or train-PPMI/test-WearGait and train-WearGait/test-PPMI evaluations
- raw wrist model predeclared before seeing held-out labels
- success target: T3 CCC >= 0.40 external and T1 CCC >= 0.55 external, with MAE and calibration not worse than clinical-only baselines

### External Generalization Success

A real foundation model should not only win one split:

- positive, non-null zero-shot signal on at least two external cohorts
- leave-dataset-out mean CCC higher than the current tabular/feature baselines
- no single cohort contributing more than half the aggregate lift
- no degradation on the already known public external routes

### Clinical Utility Success

Keep this as a research benchmark, not medical advice:

- calibrated uncertainty and conformal retained-subset reporting
- error stratification by site, sex, age, severity, medication state, DBS, and cohort
- explicit "sensor-only" vs "clinical-augmented" labels
- no treatment recommendations generated by the model
- all generated patient-facing text disabled unless reviewed in a separate clinical-safety track

## Compute Plan

### Phase 1: Colab-Style Reproducible Pilot

Inspired by the X post, but with auditability:

- one notebook or script generated from repo templates
- synthetic/public JSONL only
- Qwen3-8B 4-bit LoRA via Unsloth
- 20K-50K instruction examples
- checkpoint every 30 minutes
- validation loss plus exact held-out task metrics
- auto-resume, but all commands logged to a manifest

Target hardware: one L4/A10/A100 class GPU.

### Phase 2: Repo-Native Remote Training

- no browser automation
- no Google Drive for protected datasets
- train via `gpu.sh` or a controlled SLURM/Kubernetes runner
- encrypted object storage for DUA data
- immutable run manifests
- model cards and eval reports generated after every run

Target hardware:

- Qwen LoRA: one 24-80 GB GPU
- sensor encoder pretraining: 4-8 A100/H100 GPUs depending on raw-stream volume
- external eval: CPU plus one GPU for embedding extraction

### Phase 3: Foundation Pretraining

Only after raw sensor access:

- pretrain sensor encoder on all allowed raw streams
- align with Qwen through projector adapters
- freeze most Qwen weights
- train small task heads under grouped CV
- publish only aggregate, DUA-compliant metrics

## Implementation Milestones

1. `pfm_dataset_registry.yaml`: every dataset, access state, license, modality, labels, and allowed uses.
2. `build_pfm_events.py`: converts WearGait and allowed external/public data into `pfm_events.parquet`.
3. `validate_pfm_events.py`: valid ranges, missingness, unit checks, grouping keys, leakage flags.
4. `train_sensor_encoder.py`: raw/derived sensor pretraining with manifests.
5. `build_pfm_jsonl.py`: creates instruction and audit examples from allowed training data.
6. `finetune_qwen_pfm.py`: Qwen3-8B QLoRA/Unsloth adapter training.
7. `train_pfm_heads.py`: numeric heads and conformal/uncertainty heads.
8. `eval_pfm_internal.py`: WearGait LOOCV/LOSO with null gates.
9. `eval_pfm_external.py`: COPS/TLVMC/FoG-STAR/PDFE/PPMI transportability.
10. `render_pfm_model_card.py`: produces a claim-labeled model card and data card.

## Red Lines

- Do not run protected PPMI/Verily raw probes before approval.
- Do not cite original SSL/ranking breakthrough numbers as deployment results.
- Do not use true clinical labels as deployable inputs unless the track is explicitly clinical-augmented.
- Do not let Qwen text generation be the only source of numeric severity predictions.
- Do not report synthetic-data gains on the same synthetic distribution as clinical performance.
- Do not use global preprocessing, global feature selection, or window-level splits.
- Do not claim clinical deployment from external-validity rows.

## Source Notes

- X status: https://x.com/i/status/2054268350910578911
- Qwen3-8B: https://huggingface.co/Qwen/Qwen3-8B
- Qwen3-Embedding-8B: https://huggingface.co/Qwen/Qwen3-Embedding-8B
- Unsloth docs: https://unsloth.ai/docs
- QLoRA: https://arxiv.org/abs/2305.14314
- PPMI data access: https://www.ppmi-info.org/access-data-specimens/download-data
- PPMI FAQ: https://www.ppmi-info.org/help-and-resources/faqs
- PPMI Verily wrist accelerometry paper: https://www.nature.com/articles/s41531-025-01034-8
- WATCH-PD longitudinal paper: https://www.nature.com/articles/s41531-024-00721-2
- COPS Scientific Data paper: https://www.nature.com/articles/s41597-026-06999-6
- FoG-STAR Zenodo: https://zenodo.org/records/17838806
- TLVMC/DeFOG source data: https://zenodo.org/records/10959560
- CARE-PD project: https://neurips2025.care-pd.ca/
- MJFF Levodopa Response Synapse page: https://www.synapse.org/Synapse:syn20681023/wiki/597164
- Apple wearable accelerometer foundation model: https://machinelearning.apple.com/research/wearable-accelerometer-foundation-models
- Scaling wearable foundation models / LSM: https://arxiv.org/abs/2410.13638
