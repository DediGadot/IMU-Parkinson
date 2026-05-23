# Parkinson Foundation Model — Unified 9B Pipeline Plan

> **This plan merges two sources:** (a) the end-to-end pipeline + parallel codex/gemini red-team
> designed in-session, and (b) the in-repo `PARKINSON_FOUNDATION_MODEL_9B_PIPELINE.md` design
> artifact (its `pfm_events.parquet` data product, tokenizers, 6-stage training, milestones, red
> lines). Data facts are **verified live on the remote 2026-05-23**, not quoted from docs.

## Context

**Request.** Act as a 100x ML + 100x PD researcher. Using the X-post idea (agentic
orchestration driving **Colab/cloud + Unsloth QLoRA** on a **~145 MB JSONL** corpus to fine-tune
**Qwen 3.5** — 4B in the post, 9B-class for us), design an end-to-end pipeline for a **Parkinson
foundation model** from PPMI + the project's datasets. Propose more datasets, success criteria,
and a synthetic-data strategy.

**Locked decisions.** Product = *multimodal severity predictor*. Compute = *cloud A100/H100
80 GB* (the 8–16 GB slave is CPU-eval/feature-cache only). North star = *leakage-strict inductive
UPDRS-III CCC* (T1 items 9–14, T3 total), beating honest ceilings (T1 0.717 / T3 0.378) with
MAE/calibration/conformal alongside.

**Honest verdict (codex + gemini convergent red-team, `/tmp/pd_imu_consult/{codex,gemini}_20260523T120139.txt`).**
A 9B LLM as the *primary numeric regressor* on dense gait/APDM features at N≈94 is a near
**category error** — it will likely *lose* to tuned GBDT and is *more* N-wall-prone (HARNet
fine-tune collapsed to CCC≈0.13; MOMENT/HC-SSL/KD null; the wall is cohort size, not the encoder).
LIFT/TabLLM wins only with semantic text, categorical priors, or **large paired data**.

**The reframe both the red-team and the in-repo plan demand → the spine of this plan.** The
9B model is **not** the regressor. It is a two-tower system: a **sensor/multimodal representation
+ calibrated numeric heads** produce the UPDRS numbers; the **Qwen3-8B LLM** does reasoning,
explanation, data-QC, retrieval, provenance, and report/model-card generation. The 9B earns its
cost by (1) **pooling cohorts/modalities GBDT cannot fuse** to change effective N, and (2) the
auditing/explanation layer. A **cheap 4B PoC with hard kill-gates** decides whether the 9B spend
happens. Publishable whether the model wins (real lift) or plateaus (honest negative + deployable
conformal/clinical-reasoning artifact).

---

## Verified data facts (live remote, 2026-05-23 — corrects prior docs)

**PPMI** — `fiod@165.22.71.91:2243:/home/fiod/PPMI`, 4.8 GB, **flat dir, 315 files = 309 CSV + 6 PDF**
(docs said "315 CSVs + 5 PDFs"). **Extensions are exclusively `csv` + `pdf`.**
- `MDS-UPDRS_Part_III_21May2026.csv` = **38,017 data rows** (12 MB, largest single file). ✓
- `Gait_Data___Arm_swing__Opals__21May2026.csv` = **60 cols × 291 assessments** (≈199 subj: 76 PD
  + 5 HC + 118 prodromal per prior subject-level inventory). ✓
- `Gait_Data___Arm_swing__Axivity__21May2026.csv` = **99 rows**. ✓
- 6 methods PDFs (gait `AM0180319`, Roche v1.1, + 4 genetics: APOE, PD-Variants, Project-9001, Risk-SNP-PGS).
- File suffixes: 193 `_20May2026` + 115 `_21May2026` → **some files are duplicated across the two pulls**; de-dup by latest suffix.
- **CONFIRMED ABSENT: raw IMU streams** (no `.h5/.cwa/.parquet/.npy/.edf/.mat`).
- **NEW CORRECTION: no image files at all.** PPMI imaging (DAT-SPECT/MRI/DTI/PET) and -omics exist
  here only as **derived tabular scalars inside CSVs — not DICOM/NIfTI/images**. → A Qwen-VL
  *vision* phase over actual scans needs a **separate LONI IDA imaging download**, exactly like
  raw IMU. **The multimodal that is executable now is *tabular* fusion, not vision.**

**WearGait-PD** — `fiod@165.22.71.91:2243:/home/fiod/pd-imu/data/raw/weargait-pd`, **16 GB**.
- **794 CSVs = 793 IMU task-recordings** under `PD PARTICIPANTS/CSV files/` + 1
  `PD - Demographic+Clinical - datasetV1.csv` (96 cols, 1004 rows).
- **PD-ONLY on the slave — there is NO `CONTROL PARTICIPANTS` dir; the 80 HC raw streams are not
  present on this remote.** (HC is diagnostic-only per project rules; but SSL pretraining cannot
  use HC raw from this box without a separate HC download.)
- Tasks present: **SelfPace 298, HurriedPace 200, Balance 99, TUG 99, TandemGait 97** (793 ≈ 98 PD
  × ~8 recordings). 100 Hz, 13 sensors × 6 ch = 78 IMU channels (per `data_split.py`).
- Derived feature caches + labels live **locally** in `results/` (`cache_*.csv`,
  `ablation_v3_features.csv`, `per_item_scores.json`, `paper3_split.json`) — gitignored raw stays
  remote.

**Implication for the plan:** the only data with *both* paired gait and clinician Part III, on
disk today, is WG-PD PD raw (98 PD) + PPMI Opal-derived (76 PD). Everything richer (PPMI raw IMU,
PPMI images, HC raw, externals) is a separate acquisition. This bounds what is executable now vs
gated.

---

## Architecture — Two-tower PD-FM

```
 raw IMU (WG-PD PD) ─┐
 derived gait (PPMI  │   ┌──────────────────────────────────────────────┐
   Opal, externals) ─┼──►│ TOWER A — REPRESENTATION + NUMERIC HEADS       │
 clinical/imaging-   │   │  • sensor encoder (50–300M, SSL) OR canonical  │─► ŷ items 9–14, T1, T3
   derived tabular ──┘   │    GBDT anchor (compose_t1_iter12 / iter47)    │   + ordinal heads
                         │  • CCC-optimized + conformal/uncertainty heads │   + conformal interval
                         │  • fold-local, leakage-firewalled              │
                         └──────────────────────────────────────────────┘
                                          │ embeddings + numeric-head ŷ injected as context
                                          ▼
 serialized JSONL ──────►┌──────────────────────────────────────────────┐
 (events, manifests,     │ TOWER B — Qwen3-8B (Unsloth QLoRA) + projector │─► reasoning, QC,
  schema, visit summary) │  • NOT the severity regressor                  │   leakage-audit,
                         │  • explain / retrieve / data-QC / provenance / │   model-card,
                         │    report + model-card generation              │   structured rationale
                         └──────────────────────────────────────────────┘
```

- **GBDT anchor stays in Tower A** as the number-to-beat *and* the deployable safety net.
- An **audited language-interfaced regression (LIFT) variant** is kept only as a *negative-control
  baseline* (red-team expects it to lose) — never the headline path.
- **Multi-endpoint** by design (what makes it a "foundation model"): diagnosis (PD/HC/prodromal),
  H&Y staging, T1/T3 severity, item-level ordinals, FoG/tremor, med-state ON/OFF, short-horizon
  progression. Big-N endpoints (from PPMI clinical/labels) regularize the shared representation;
  severity is reported on its own honest split.

## Model choice

- **`Qwen/Qwen3-8B`** (Apache-2.0, 8.2B, 36 layers, 32K ctx) as the concrete backbone — "Qwen 3.6
  9B" is **not a verified release**; if an official Qwen 3.5/3.6 9B passes license/tooling checks
  it can swap in. `Qwen/Qwen3-Embedding-8B` for the RAG/retrieval corpus.
- **Parkinson sensor encoder** 50–300M, SSL-pretrained on raw windows where available, derived-
  feature sequences elsewhere. *Do not* assume frozen HARNet/MOMENT solves severity at N~100 —
  already falsified for WG-PD-only.
- Lightweight **projectors** sensor/tabular→Qwen token space; **numeric heads** for regression,
  ordinal scoring, uncertainty, conformal width.

---

## Dataset plan

**Tier A — usable now (no new access).**
- WG-PD **PD raw** (98 PD, 16 GB, 793 task-CSVs) — internal benchmark + leakage reference. *HC raw
  absent on slave.*
- PPMI **CSV bundle** — Part III labels + clinical covariates + derived Opal/Axivity tables (the
  Opal table is the immediate PPMI feature matrix; **no raw, no images**).
- Public external eval routes already in repo: COPS, TLVMC/DeFOG, FoG-STAR, PDFE, PADS (within-
  cohort only), CARE-PD (gait-score transfer, not T1/T3) — **external-validity probes, not headline**.

**Tier B — access-gated priority queue (submit-ready, not compute-ready; runbooks in `scripts/`).**
1. **PPMI/Verily raw** (LONI IDA sensor-data + imaging requests) — *the lever both red-teams say
   matters*; unlocks raw streams AND scans, enables locked Slot D/F verbatim.
2. **PPP / PD-VME** (Verily watch, ~388–517 PD, in-clinic Part III).
3. **WATCH-PD** (82 PD + 50 HC, APDM Opal worn *during* Part III — ideal contemporaneous T3).
4. **CNS-Portugal** (74 PD, wrist+lower-back AX3). 5. **Hssayeni/MJFF** (~30 PD, Synapse `syn20681023`).
6. **ICICLE-GAIT** (89 PD, lower-back AX3, longitudinal).

**Tier C — propose to add/request.**
- **UK Biobank accelerometry / NHANES** — label-free SSL pretraining of the sensor encoder only.
- **ProPark AX6**, **Mobilise-D CVS** (if row-level Part III + lower-back becomes accessible),
  **OPDC/OxQUIP** (DPUK), upper-limb/subitem sets — narrow context, not T1/T3 builders.
- **Do NOT add:** mPower (self-reported labels), PADS cross-protocol transfer (stationary ⊥ gait).

---

## Canonical data product — `pfm_events.parquet`

One row per (dataset, subject, visit, session, recording). Fields:
`dataset_id, subject_id, visit_id, session_id, recording_id; grouping_subject_key,
grouping_visit_key, site, cohort; sensor_modality, sensor_placement, laterality, sampling_rate_hz,
units; task, task_phase, start/end_time, duration_s; med_state, dbs_state, levodopa_equivalent,
days_since_diagnosis; target_name, target_value, target_source, target_time,
target_valid_range_passed; feature_source ∈ {raw_window, derived_feature, clinical_table,
text_protocol, synthetic}; leakage_scope ∈ {target_free, train_fold_only, external_eval_only,
protected_access_only}.` Every artifact carries a **manifest** (script, git SHA, command, ctime,
input hashes, labels-used, fold scope, normalization scope, leakage status, rationale).

## Tokenization

- **Raw IMU** — fixed windows {2,5,10,30 s + task-full}; **preserve physical amplitude (no
  amplitude-scaling aug — amplitude carries severity)**; placement-aware channels + metadata
  tokens; Conv1D/Transformer stem → patch embeddings; optional VQ codebook for discrete tokens but
  keep continuous embeddings for regression.
- **Derived features** — `feature_name, value_bin, unit, task, placement, missingness`; **train-
  fold-only normalization**; raw units kept for LLM audit. (Prefer the repo's already
  self-normalized features; **prompt-level cohort z-score is BANNED** — leaks test-fold μ/σ.)
- **Clinical event** — per-visit temporal sequence (demographics, cohort, duration, med/DBS, H&Y +
  parts/items *where the task allows*, non-motor scales, **imaging/omics availability flags only**
  until governance). Targets must not leak into deployable inputs; separate sensor-only /
  clinical-augmented / future-deployment tracks (firewall law #7).
- **Text/RAG** (Qwen3-Embedding-8B) — code+manifests, PPMI methods PDFs (post-access), MDS-UPDRS
  item defs + valid ranges, protocols, paper/audit files, literature. **No held-out labels /
  row-level preds / protected snippets in the index.**

---

## Training stages (with the kill-gates baked in)

**Stage 0 — governance + split freezing.** dataset registry; subject/visit/site split manifest
(WG-PD test = `paper3_split.json` PD subset, held out from train/val/prompt/synthetic; **PPMI split
by `PATNO`, train-only, no backward-time leakage**); protected-data boundary map; leakage-null
fixtures. **Hard stop** if any target globally joined pre-split or any synthetic lacks provenance.
`inductive_lib._check_subject_disjoint` across all modalities.

**Stage 1 — sensor-encoder SSL.** raw windows (WG-PD PD; externals when unlocked) + derived-feature
sequences (PPMI Opal). Objectives: masked time/freq patch reconstruction, future-window prediction,
task/placement/laterality, within-subject/visit consistency, cross-sensor alignment,
sensor→derived-feature distillation for PPMI. **No subject-identity objectives** (memorization).

**Stage 2 — multimodal clinical alignment (tabular).** contrastive: motion/visit ↔ matching clinical
visit summary; train-fold ordinal item heads; med/DBS heads; missingness-aware reconstruction.
Creates the representation; not yet deployable. *(Vision over scans deferred — no images on disk;
gated on IDA imaging request.)*

**Stage 2.5 — 4B PoC HARD GATE (1×A100, ~$30).** Qwen 3.5/Qwen3-4B QLoRA on WG-PD dev + PPMI slice;
run full adapted 5-null + contamination gate. **Go/No-Go to spend 9B money:** scrambled-label test
CCC ≈ 0 (>0.10 → KILL); base-model contamination below floor; held-out T1 CCC ≥ 0.55 *or* positive
PPMI-in/out Δ. Fail both → **stop, report negative; the N-wall holds.**

**Stage 3 — Qwen3-8B adapter tuning.** Unsloth QLoRA, 4-bit, LoRA r=32–64 (+ projector), `train_on_
responses_only`, ctx 2048–4096, packing. Targets: **dataset-QC, clinical-summary, provenance/leakage
explainer, error-triage, model-card writer** — *not* row-label memorization. JSONL `messages` schema
with `metadata.contains_targets/synthetic`. ~12–24 h / 3 epochs on 1×A100-80GB, ~$60–180.

**Stage 4 — supervised numeric heads.** over frozen/lightly-tuned embeddings: T1 item heads + sum,
T3 total, item ordinals, H&Y, med-state, uncertainty/conformal-width. Metrics: CCC, MAE, r,
calibration slope, conformal coverage. Repo bootstrap + null gates; **single-shot pre-registered
LOOCV lockbox**. **FWER-corrected paired-Δ vs the locked GBDT on identical test subjects**
(`subject_paired_bootstrap`) — promote only if CI excludes 0.

**Stage 5 — external validation + continual adaptation.** (1) zero-shot, (2) train-fold linear-probe
calibration within external cohort, (3) pooled leave-dataset-out, (4) pre-register before any
augmentation into WG-PD training. **Never** update WG-PD canonicals from external-only metrics.

**Stage 6 (gated) — conformal deployable secondary + multimodal vision.** If the headline doesn't
clear FWER (the N-wall's likely verdict), ship the proven pattern: pre-registered conformal-abstention
secondary with a **y-free** retention score (CQR width / ensemble disagreement / Mahalanobis — never
`|y−ŷ|`), monotonicity + `--sanity-y-nan` receipt. Vision-token fusion (DAT-SPECT/MRI) only after the
IDA imaging download.

---

## Synthetic-data strategy (leakage-clean, validated)

**Validation rule (gold standard):** train on `real+synthetic`, **test on a locked real-only
holdout**; keep synthetic only if real-only-holdout CCC *improves* vs real-only training. Generators
are **fit inside the outer training fold only**, never see test subjects.

**Allowed:** label-independent sensor augmentation (dropout, missing channels, timestamp gaps,
sampling-rate mismatch, clipping, label-preserving window-mask/crop/stride-jitter, measured-device-
noise injection); serialization paraphrase aug for the LLM; train-fold-only generative TS
(diffusion/VAE) for *representation pretraining* (expect modest — won't escape the N≈94 hull; require
NN/DTW/MMD/membership checks); physics/MSK sim with **pre-specified or train-fold-fit** severity→
parameter mapping; instruction/schema-QC examples (invalid codes, all-missing rows, target-leakage,
SID-shuffle, global-scaler bugs); counterfactual "sensor-only vs clinical-augmented" calibration text.

**Banned (inject leakage/lies):** severity-conditioned generative synthesis (generator artifacts →
fatal holdout inflation); SMOTE/feature-mixup pre-CV (inflation + impossible biomechanics);
**amplitude-scaling aug for regression inputs**; LLM clinical vignettes as gait-severity training;
any all-data (non-fold-local) generation or synthetic derived from test subjects; synthetic UPDRS
labels counted as ground truth. Every synthetic row: generator+SHA, source cohort, fold scope,
exact transform, synthetic flag, target-free/conditioned flag, allowed uses.

---

## Success criteria

**Infrastructure** — all sources manifested + license/DUA-flagged; protected boundaries enforced;
split manifests exist; schemas normalized into `pfm_events.parquet`; leakage-null fixtures pass CI.

**Representation** — frozen embeddings beat handcrafted baselines on ≥3 held-out tasks *without
target-label selection*: task/placement recognition, med-state/ON-OFF, FoG/tremor external, PPMI
derived-gait target-free retrieval, WG-PD item-level linear probes.

**Internal WG-PD (gate-bearing)** — **T1 beat 0.7170**, **T3 beat 0.3784** by ≥ MCID under paired-
bootstrap + null gates + **FWER correction vs locked GBDT**; **LOSO T3 0.150→≥0.25** with no
directional collapse; MAE/r/calibration-slope + IMU-only-vs-clinical-augmented labels reported.
**Mandatory null gates:** demographics-only baseline must be beaten; **feature-blanking** (mask all
`cv_*`) must not collapse IMU-only CCC to ≈0; scrambled-label + canary + contamination probe pass;
small transductive-inductive gap.

**PPMI transportability (now)** — PD-only Opal-derived result with subject grouping; T1/T3 audited
from valid NP3 items; **no raw-sensor claims**; floor = positive CCC, CI excludes 0, above
demographics/clinical-only baseline. **After IDA raw access:** predeclared train↔test PPMI/WG-PD,
target T3 ≥ 0.40 / T1 ≥ 0.55 external with calibration ≤ clinical-only.

**External generalization** — positive zero-shot on ≥2 external cohorts; leave-dataset-out mean CCC
> tabular baselines; no single cohort > half the lift; no regression on known public routes.

**Clinical utility (research, not advice)** — conformal coverage = nominal; error stratified by
site/sex/age/severity/med/DBS/cohort; QWK on item ordinals; explicit sensor-only vs clinical-
augmented labels; **no treatment recommendations / patient-facing text** outside a separate clinical-
safety track.

---

## Compute plan

- **Phase 1 — reproducible pilot** (X-post-inspired, *auditable, not browser-clicking*): one
  repo-templated script, **synthetic/public JSONL only**, Qwen3-4B/3.5-4B 4-bit LoRA via Unsloth,
  20–50K instruction examples, checkpoint/30 min, val-loss + held-out metrics, auto-resume with
  logged manifest. 1× L4/A10/A100. **No Google Drive for DUA data.**
- **Phase 2 — repo-native remote training**: via `gpu.sh`/SLURM, encrypted object storage for DUA,
  immutable run manifests, auto model-card. Qwen LoRA on 1× 24–80 GB; sensor-encoder SSL on 4–8×
  A100/H100 (raw-volume dependent); external eval CPU + 1 GPU.
- **Phase 3 — foundation pretraining**: only after raw-sensor access — pretrain sensor encoder on
  all allowed raw, align via projector, freeze most Qwen, train task heads under grouped CV; publish
  aggregate DUA-compliant metrics only.

## Implementation milestones (reuse firewall, don't reinvent)

1. `pfm_dataset_registry.yaml` — every dataset: access state, license, modality, labels, allowed uses.
2. `build_pfm_events.py` — WG-PD + allowed external/public → `pfm_events.parquet`.
3. `validate_pfm_events.py` — valid ranges, missingness, units, grouping keys, leakage flags + the
   serialization linter (reject `NP3*/UPDRS/NHY/LEDD` in sensor-only inputs).
4. `train_sensor_encoder.py` — raw/derived SSL with manifests.
5. `build_pfm_jsonl.py` — instruction/audit examples from allowed train-fold events.
6. `finetune_qwen_pfm.py` — Qwen3-8B QLoRA/Unsloth adapter + projector.
7. `train_pfm_heads.py` — numeric + conformal/uncertainty heads.
8. `eval_pfm_internal.py` — WG-PD LOOCV/LOSO + adapted 5-null + contamination probe + FWER GBDT Δ.
9. `eval_pfm_external.py` — COPS/TLVMC/FoG-STAR/PDFE/PPMI transportability.
10. `render_pfm_model_card.py` — claim-labeled model + data card.

**Reuse:** `inductive_lib.py` (FoldImputer/Normalizer/SeverityBins, `run_null_test_gate`,
`_check_subject_disjoint`, `gen_5fold_split`, `write_preregistration`); `eval_utils.py` (`lins_ccc`,
`cal_slope`, `subject_paired_bootstrap`, `bootstrap_ci`); `results/paper3_split.json`,
`per_item_scores.json`, `updrs_columns.py`, `compose_t1_iter12_honest.py`,
`run_t3_iter47_invalid_code_fix.py`; `gpu.sh` (slave = CPU-eval/cache only).

## Red lines

No protected PPMI/Verily raw probes before approval · don't cite the retracted SSL/ranking numbers
as deployment · clinical labels never deployable inputs unless the track is explicitly
clinical-augmented · **Qwen text is never the sole source of a numeric severity prediction** · no
synthetic-distribution gains reported as clinical performance · no global preprocessing / global
feature selection / window-level splits · no clinical-deployment claims from external-validity rows.

---

## Verification

1. **Corpus/data-product audit** — `validate_pfm_events.py` + serialization linter exit clean;
   `_check_subject_disjoint` across all modalities incl. synthetic provenance; PPMI split by PATNO;
   spot-check 10 records (sensor-only has no `cv_*`/`NP3*`).
2. **Reproduce anchors first** — `./gpu.sh compose_t1_iter12_honest.py` (T1 0.6550),
   `./gpu.sh run_t3_iter47_invalid_code_fix.py --mode run` (T3 0.3784) — confirm the comparison
   baselines before any LLM spend.
3. **4B PoC kill-gate (Stage 2.5)** decision recorded before any 9B run.
4. **9B headline** — held-out + 5-fold CCC vs GBDT via `subject_paired_bootstrap`; demographics-null
   + feature-blanking + 5-null + contamination all pass; conformal coverage in tolerance; QWK +
   subgroup tables produced.
5. **Synthetic** — real-only-holdout CCC with-vs-without synthetic; promote only on FWER-clean +Δ.

**Stop rule.** If WG-PD-only 9B reproduces the HARNet collapse and PPMI pooling does not lift it
above the floor with a positive FWER-corrected Δ vs GBDT, **stop, report the negative**, ship the
Stage-6 deployable secondary. The honest closure is the contribution.

## Sources
codex/gemini red-team `/tmp/pd_imu_consult/{codex,gemini}_20260523T120139.txt` · Qwen3-8B
(huggingface.co/Qwen/Qwen3-8B) · Unsloth · QLoRA (arXiv:2305.14314) · TabLLM (arXiv:2210.10723) ·
LIFT (arXiv:2206.06565) · Apple wearable-accel FM · LSM (arXiv:2410.13638) · PPMI Verily
(nature.com/articles/s41531-025-01034-8) · in-repo `PARKINSON_FOUNDATION_MODEL_9B_PIPELINE.md`.
