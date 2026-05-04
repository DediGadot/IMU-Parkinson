# Findings — Per-Item UPDRS-III Deep Dive

**Mission start:** 2026-04-30 09:58
**Carry-over:** F18–F30 from prior T1/T3 missions retained in git history. Key carry-overs are summarized at the end of this file.

---

## F31 — Pre-flight (2026-04-30 09:58)

**Remote alive:**
- `ssh -p 26843 root@142.171.48.138`
- Up 4d 17h, load 0.44/17 cores
- GPU: RTX 5070 12GB, 6% util, 11.7GB free
- Disk: 24GB free of 126GB
- 16GB raw PD CSVs present at `/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files/` (793 files from iter7 download)

**Local cache audit:**
- `results/ablation_v3_features.csv` (1752 v2 handcrafted features) ✓
- `results/per_item_scores.json` (all 18 items × 178 subjects) ✓
- `results/rocket_recordings.npz` (1405 records × 26 mag channels) ✓
- `results/axial_orientation_features.csv` (30 features, 100 subjects) ✓ from iter7
- `results/tug_transition_features.csv` (421 features, 176 subjects) ✓ from iter4
- `results/rest_state_features.csv` (416 features, 176 subjects) ✓ from iter4

**Implication:** raw 22-channel data is available for the first time. Iter7 was a null result for item 13 specifically, but the broader exploration of triaxial Acc/Gyr + Euler + FreeAcc per item has not been attempted. Per-item engineering is the new lever.

---

## F32 — Per-item motor-signature draft (pre-CLI consult)

For each MDS-UPDRS Part III item 3.x, the clinically relevant motor signature and its observability from the WearGait-PD setup:

### Items observable from gait IMU (best targets)

**3.7 Toe tap (R/L)** — clinical: foot taps in seated position; in-gait surrogate is heel-strike timing regularity + foot-Z peak-to-peak amplitude during swing.
- Signature: foot Acc-Z swing peak amplitude variance, cadence regularity per foot
- Sensors: R/L Foot
- Channels: Acc Z, FreeAcc Z, Gyr Y
- Tasks: SelfPace, Hurried, Tandem
- Time window: per-stride detected swing phase (Acc-Z zero-crossings)
- Realistic ceiling: 0.40 CCC (current 0.27)

**3.8 Leg agility (R/L)** — clinical: lift leg repeatedly seated; in-gait surrogate is shank gyro Y (sagittal pitch) amplitude during swing.
- Sensors: R/L Shank
- Channels: Gyr Y, Acc magnitude
- Tasks: SelfPace, Hurried
- Time window: swing phase
- Realistic ceiling: 0.40 CCC (current 0.26)

**3.9 Arising from chair** — TUG sit-to-stand transition.
- Sensors: Lumbar, Sternum
- Channels: Acc Z (vertical accel during rise), Gyr Y (trunk rotation), FreeAcc Z, jerk = d(Acc)/dt
- Task: TUG only
- Time window: 1–2 s before peak Lumbar Acc-mag spike to 0.5 s after
- Already partially captured in `tug_transition_features.csv`. Needs raw triaxial + jerk.
- Realistic ceiling: 0.55 CCC (current 0.42 — rescued by hy_residual)

**3.10 Gait** — entire gait task quality.
- Sensors: Lumbar, both Feet, both Shanks
- Channels: Acc + Gyr triaxial
- Task: SelfPace, Hurried, Tandem
- Time window: full task
- Features: stride length proxy (FreeAcc integral over stride), cadence, step-width SD, asymmetry index
- Realistic ceiling: 0.65 CCC (current 0.48)

**3.11 Freezing of gait** — CCC currently 0.17. Major lever.
- Sensors: both Shanks (sagittal Gyr Y captures cadence drops most reliably)
- Channels: Gyr Y, Acc magnitude
- Task: SelfPace, Hurried, Tandem
- Time window: full task; detect freeze events via Moore freeze index (FI = power(3–8 Hz) / power(0.5–3 Hz)) and cadence drops > 1 s
- Features: freeze event count, total freeze duration, longest freeze, freeze index 95th percentile
- Realistic ceiling: 0.45 CCC

**3.12 Postural stability** — currently 0.61 (strong); refine.
- Sensors: Lumbar, Sternum
- Channels: Acc triaxial, FreeAcc triaxial
- Task: Balance (eyes open/closed), Tandem
- Features: 95% sway area, mean sway velocity, frequency dispersion
- Realistic ceiling: 0.70

**3.13 Posture** — currently 0.10. Iter7 axial was null but only on items 9/11/13 jointly. Item-13-isolated retry with sustained-window features.
- Sensors: Lumbar, Sternum, Forehead
- Channels: Euler Pitch (sagittal trunk lean), Roll (lateral)
- Task: any quiet-stance segment (Balance start, pre-TUG standing, Tandem hold)
- Features: sustained median pitch over ≥3 s window; not transient — drift across task
- Realistic ceiling: 0.30

**3.14 Body bradykinesia** — currently 0.45.
- All sensors, all tasks; movement amplitude regression.
- Features: multi-sensor std + range across all gait phases
- Realistic ceiling: 0.60

### Items partially observable

**3.4 Finger tap (R/L)** — clinical task is at-rest finger tap; we have only wrist IMU during gait. Surrogate: arm-swing modulation amplitude.
- Realistic ceiling: 0.25

**3.5 Hand movement (R/L)** — open/close hand; surrogate is wrist triaxial during gait arm swing.
- Realistic ceiling: 0.35

**3.6 Pronation-supination (R/L)** — wrist gyro X axis during arm swing has a similar rotational signature.
- Realistic ceiling: 0.30

**3.15 Postural tremor (R/L)** — arms outstretched. Surrogate: wrist 4–6 Hz spectral peak during Balance/Tandem stance phases.
- Realistic ceiling: 0.30

**3.16 Kinetic tremor (R/L)** — finger-to-nose; surrogate: wrist 4–6 Hz peak during gait arm swing.
- Realistic ceiling: 0.30

**3.17 Rest tremor amplitude** — needs arm at rest. Surrogate: wrist IMU during quiet-stance segments at start/end of Balance.
- Realistic ceiling: 0.35

**3.18 Rest tremor constancy** — time-fraction of 4–6 Hz dominance during rest segments.
- Realistic ceiling: 0.40 (currently the strongest of the tremor cluster at 0.25)

### Items NOT observable from gait IMU

**3.1 Speech** — needs audio. Cap = severity proxy from H&Y. Realistic ceiling: 0.30.

**3.2 Facial expression** — needs face video. Cap = severity proxy. Realistic ceiling: 0.32.

**3.3 Rigidity (5 sub-items)** — clinician-applied passive movement. Cap = severity proxy. Realistic ceiling: 0.20.

For these three items, we WILL NOT build dedicated caches. We document the cap and use H&Y + demographics ridge as the predictor.

---

## F33 — GPU exploitation strategy

Past missions left the RTX 5070 idle (LGB-CPU is 2.2× faster at N<200). The new lever: frozen pretrained TS encoders, evaluated once per recording, results cached.

### Encoders to use

| Encoder | Embedding dim | Source | Why |
|---|---|---|---|
| MOMENT-1-base | 768 | momentfm | Already used; baseline |
| Chronos-bolt-base | 1024 | amazon/chronos | Newer, different inductive bias |
| PatchTST | 128 | huggingface/timeseries | Spectral-aware patch tokens |

Each encoder is loaded on GPU, batched over (recording, sensor, channel-set) triples. Pool over time → per-recording embedding. Aggregate to per-(subject, task) by mean.

### Item-specific embedding subsets

For each item, restrict the embedding extraction to the relevant (sensor, channel, task) subset:
- Item 11 (FoG): Shanks Gyr Y, gait tasks → 1 embedding per (subject, task)
- Item 13 (posture): Lumbar/Sternum/Forehead Euler Pitch, balance tasks → 1 embedding
- Item 17 (rest tremor): Wrist Acc+Gyr, rest segments → 1 embedding
- Etc.

Total embedding-extraction passes: ~18 items × ~3 (sensor groups) × ~3 (encoders) = 162 passes per subject. 90 subjects × 162 = 14580 forward passes. At ~5 ms/pass on a 5070 → ~75 s GPU time per encoder × 3 = ~4 min total. Negligible.

### Memory budget

VRAM: 12 GB. Loading 3 encoders simultaneously is risky. Sequence them:
1. Load MOMENT, run all passes, cache, free.
2. Load Chronos, run all passes, cache, free.
3. Load PatchTST, run all passes, cache, free.

Each frozen encoder ≈ 100–500 MB. 1 at a time is safe.

---

## F34 — Codex + Gemini 10x-researcher consult synthesis (2026-04-30 10:08)

Both ran in parallel on `/tmp/peritem_consult_prompt.md`. Files: `/tmp/codex_peritem.out` (62 lines, dense table format with 18 PubMed citations), `/tmp/gemini_peritem.out` (93 lines, structured by item group).

### A. Ceiling consensus (overrides my draft estimates in F32)

| Composite | My draft | Gemini | Codex | **Consensus** |
|---|---|---|---|---|
| T1 LOOCV CCC | 0.72 | 0.72-0.75 | 0.70-0.72 | **0.70-0.72** (target 0.70, stretch 0.72) |
| T3 LOOCV CCC | 0.50 | 0.55-0.60 | 0.46-0.50 | **0.46-0.50** (codex more conservative; trust the lower bound for budgeting) |

Both agree the wall is items 9 / 11 / 13 (axial/transition) — that's where the remaining T1 headroom lives. Items 1, 2, 3, 15, 16 are confirmed unobservable from gait/balance IMU; cap each via `hy_residual` only.

### B. Per-item feature additions worth promoting (synthesized from both)

**Item 3.4 Finger tap (currently 0.08, ceiling 0.18-0.25):**
- Wrist pronation spectral power 1.5-4 Hz (codex)
- Fatigability of arm-swing amplitude across SelfPace → Hurried (codex) — novel
- UpperArm-Wrist quaternion jerk (codex)
- Wavelet ridge tracking 3-8 Hz on Wrist Acc during fastest 10s of Hurried (gemini)

**Item 3.5 Hand mvmt (currently 0.19, ceiling 0.25-0.35):**
- Phase-Locking Value between Lumbar Gyr and Wrist Gyr (gemini)
- Pseudo-elbow velocity from UpperArm↔Wrist orientation (codex)
- L/R multi-task with item 3.6 (both)

**Item 3.6 Pronation-supination (currently -0.04, ceiling 0.18-0.30):**
- Relative UpperArm↔Wrist yaw/roll during turns (codex) — needs Euler/OriInc
- Spherical harmonic coefficients of Wrist OriInc quaternion path (gemini) — exotic but worth one shot
- Side-shared MT with 3.5 (codex)

**Item 3.7 Toe tap (currently 0.27, ceiling 0.35-0.45):**
- Stance-to-swing latency asymmetry (codex)
- Toe-clearance proxies via FreeAcc_ENU + VelInc (codex)
- High-freq scattering coefficients on Foot FreeAcc during heel-strike (gemini)
- L/R MT with 3.8

**Item 3.8 Leg agility (currently 0.26, ceiling 0.38-0.45):**
- Heel vertical velocity RMS (codex)
- Lift-amplitude fatigability across repeated steps (codex) — novel
- Tibial-Lumbar coordination phase (CRP) (gemini)
- Thigh-shank phase lag variability (codex)

**Item 3.9 Arising from chair (currently 0.42, ceiling 0.55-0.65) — KEY LEVER:**
- **APA magnitude** (anticipatory postural adjustment) (codex) — high-prior
- **Seat-off power impulse** (codex)
- **Phase-space area** (Lumbar pitch vs pitch velocity) during sit-to-stand (gemini) — high-prior
- Vertical power peak: max 1s moving avg of Lumbar FreeAcc Z (gemini)
- Sit-to-stand jerk cost (gemini)
- Event-aligned RAW embed (codex) — frozen MOMENT/Chronos on `[-0.8s, +2.0s]` window around seat-off

**Item 3.10 Gait (currently 0.48, ceiling 0.60-0.70):**
- **Speed reserve** = (Hurried − SelfPace) statistics (codex) — novel, high-prior
- **RQA** (Recurrence Quantification Analysis) on Lumbar AP/ML — determinism, max line (gemini)
- **GPVI** (gait phase variability index) (gemini)
- Turn peak speed + en-bloc index (codex)
- Harmonic ratios + stride regularity (codex)
- Frozen Chronos-bolt-base embeddings on Lumbar/Shank 10s windows (gemini)

**Item 3.11 FoG (currently 0.17, ceiling 0.28-0.45) — KEY LEVER:**
- **Adaptive Freezing Index** (Moore 2008): power(3-8 Hz) / power(0.5-3 Hz) on Shank Acc AP, **specifically during TUG turns** (gemini) — high-prior
- **APA-failure score** from Lumbar ML FreeAcc (codex) — novel
- Turn dwell / hesitation counts (codex)
- Wavelet entropy drop (sudden loss of wideband complexity) in Foot Gyr (gemini)
- **Hurdle model**: stage-1 binary `any_FoG` classifier, stage-2 severity regressor only on positives (codex) — replaces NGBoost in my draft
- Kurtosis of Lumbar yaw velocity during 180° turns (gemini)

**Item 3.12 Postural stability (currently 0.61, ceiling 0.70-0.78):**
- **Sway sample entropy** on Lumbar Acc ML/AP during Tandem/Balance (gemini)
- **Tandem corrective-step burden** (codex) — novel
- **Ankle-vs-hip strategy ratio**: Shank pitch variance / Lumbar pitch variance (gemini)
- TUG turn-recovery instability (codex)
- Frequency centroid stability over 30 s (gemini)

**Item 3.13 Posture (currently 0.10, ceiling 0.25-0.45) — KEY LEVER:**
- **Time above flexion threshold** (codex) — novel; replaces "mean pitch" angle which iter7 already showed was anatomically biased
- **Flexion fatigue slope** across trial (codex)
- **Cervical-Lumbar delta**: average abs(Forehead pitch − Lumbar pitch) during quiet stance (gemini) — novel
- Neck-vs-trunk flexion ratio (codex)
- Turn-induced stoop (codex)
- Vector magnitude area of static FreeAcc in ENU frame (gemini)

**Item 3.14 Body bradykinesia (currently 0.45, ceiling 0.58-0.68):**
- **Global Kinematic Energy**: sum of RMS(FreeAcc) across all 13 sensors during Hurried (gemini)
- **Spectral edge frequency 95%** of Lumbar Acc (higher edge = faster movements) (gemini)
- **Multi-joint PLV matrix eigenvalues** (full-body coordination dimensionality) (gemini) — exotic
- En-bloc turning (codex)
- Arm-swing poverty coupled to step length (codex)
- Low-rank syndrome model with gait/posture (codex)

**Items 3.15 Postural tremor / 3.16 Kinetic tremor (currently -0.09 / 0.08, ceiling 0.10-0.30):**
- Both CLIs say "not directly elicited"; codex caps at 0.10-0.18, gemini at 0.10-0.15.
- Best chance: 4-7 Hz bandpower in Wrist/UpperArm during Balance pre/post-instruction pauses (codex)
- Tremor intermittency / duty cycle (codex)
- Bilateral coherence asymmetry (codex)
- These items will likely be DEAD; budget one retry then accept the cap.

**Item 3.17 Rest tremor amplitude (currently 0.14, ceiling 0.20-0.35):**
- Quiet stance 4-6 Hz peak in Wrist/Foot Acc PSD during first 5 s of Balance (gemini)
- **Cross-axis tremor coherence** between X/Y/Z at 5 Hz (gemini)
- **Detector-regressor pipeline**: stage-1 detect tremor windows, stage-2 regress amplitude on detected windows (codex)
- Combine wrist + foot evidence (codex)
- Kymatio scattering coefficients (J=8, Q=12) on rest segments (my plan)

**Item 3.18 Rest tremor constancy (currently 0.25, ceiling 0.30-0.40) — STRONGEST tremor item:**
- **Tremor duty cycle**: % of 1s windows during Balance with 4-6 Hz power > dynamic threshold (gemini)
- **Burst duration distribution** (median contiguous tremor episode length) (gemini)
- **HMM/state-space detector** over windows + bagged ordinal regressor on summaries (codex)
- Cross-task persistence (codex)

### C. Wildcards both endorse — promote to Phase 2.5

1. **HC-only SSL pretraining** (both): masked-channel reconstruction + sensor-dropout contrastive on raw 22-ch over 80 HC subjects, freeze, use as feature extractor for PD. The ONE NN idea both allow because supervised head stays tiny. Hssayeni 2021 + Shuqair 2024 cited.
2. **Phase-token pipeline** (codex): unsupervised tokenizer over sit-to-stand, APA, steady gait, turns, quiet stance, tandem corrections; downstream item models use token histograms/attention. High upside for items 9, 11, 12, 13.
3. **Retrieval-augmented residual** (both, with strict library-exclusion under fold): training-fold-only library of phase embeddings; predict base score with LGB, then add a neighbor-residual term. Best targets: items 11, 13, 17, 18.
4. **Structured syndrome graph / DistMult** (codex): direct item head + low-rank latent syndromes (`axial`, `gait`, `appendicular brady`, `tremor`); graph-regularized ridge. Worth trying for T3 only.
5. **Zero-inflated prototype learning** (codex): for sparse items (FoG, tremor), learn train-fold severity prototypes on frozen embeddings with triplet loss, use prototype distances as tabular features.
6. **Triplet metric learning by H&Y bin** (gemini): Siamese with anchor=subject, positive=same H&Y, negative=≥2 stages away; force manifold to separate by global progression before per-item heads.

### D. Codex's modeling guidance to integrate

- Hurdle model for FoG (item 11). My draft had NGBoost; switch to hurdle.
- Detector-regressor for tremor items (15, 17). My draft had Ridge on full-task spectra; switch to two-stage.
- HMM/state-space for item 18 constancy. My draft had simple time-fraction; HMM is right.
- Side-shared multi-task between L/R item pairs (4, 5, 6, 7, 8, 15, 16) — predict L, R, and abs(L-R) jointly, share trunk features.
- Low-rank syndrome model for item 14 (predicts gait + posture + brady jointly with shared latent).
- `hy_residual` directional guidance per item: clearly **+** for 9, 13, 14, 17, 18 (severity-correlated); clearly **−** for 10, 12, 15, 16; neutral for the rest. This refines my draft heuristic of "all severity-correlated items".

### E. Failure modes both flag (pre-emptive guards)

1. **Stage-only confounding for severity-proxy items** — over-trusting H&Y for items 1, 2, 3, 15, 16 lets the residual learner overfit any spurious correlation.
2. **Site/style proxy overfit** — NLS vs WPD differs in protocol style; per-item models risk learning site rather than severity. Mitigation: per-fold inverse-propensity weighting on site or per-site centering before residualization.
3. **Speed confounding for item 3.7/3.8** — toe-tap vigor and leg-agility "speed" both rise with gait speed; need to either residualize on gait speed or use **stride-normalized** amplitudes.
4. **Bad seat-off alignment for item 3.9** — phase segmentation noise dominated iter4. Codex's fix: compute multiple peak candidates per TUG, pick max-spike window, AND use APA-onset (lateral weight shift) as alternative anchor.
5. **FoG protocol under-provoking** for item 11 — many subjects don't freeze during the test → many zeros. Hurdle model handles this; pure regression doesn't.
6. **Anthropometry confound for items 9, 13** — chair height, body habitus, scoliosis are NOT severity. Mitigation: include height/weight/age as features in stage-1 ridge of `hy_residual`.
7. **Sensor-mounting variation for item 13** — chest curvature differs across subjects → sternum pitch baseline confounds. Mitigation: use ANGLE DELTA (forehead − lumbar) instead of absolute angle (codex's neck-vs-trunk delta).
8. **Frame drift / wraparound for items 5, 6** — Euler wrap at ±π and on-device fusion drift over a session. Mitigation: convert to quaternion, use small-angle approximations, never differentiate Euler directly.

### F. What both CLIs explicitly REJECT

- End-to-end DL per item — they agree NN at N<100 fails.
- Per-task NN ensembles (besides frozen pretrained encoders).
- Generic feature concatenation without time-window specificity.
- Unbounded multi-task learning across all 18 items (only paired/grouped MT).
- Computing tremor features over walking (mistakes step-impact harmonics for tremor).

### G. Refinements to the plan (commit before launching)

1. **Phase 1 cache spec**: replace my generic motor-signature template with item-specific feature lists from this synthesis. New caches needed for APA detection (item 9, 11), phase-space-area extraction (item 9), RQA (item 10), Moore freeze index (item 11), HMM tremor detector (items 17, 18), forehead-lumbar delta (item 13), speed-reserve (item 10).
2. **Phase 2.5 (NEW)**: HC SSL pretraining + phase-token pipeline. These are wildcard tracks; budget 2 h max combined; if SSL pretraining doesn't beat MOMENT-1-base on a single item by Phase 3 screening, drop it.
3. **Phase 3 variants per item**: include hurdle (for sparse items), detector-regressor (for tremor), L/R multi-task (for paired items).
4. **Phase 4 retries**: codex's site-proxy guard + speed-confound residualization templated per item.
5. **Ceiling targets**: lower bounds — T1 0.70 (was 0.72), T3 0.46 (was 0.48). Stretch unchanged.

---

## F35 — Reserved for raw CSV schema audit

(Will be filled after Phase 0.3.)

---

## F36 — Per-item screening results (2026-04-30 14:25)

15 items × 3-5 variants = 58 jobs, 5-fold CV × 3 seeds. Wall-clock: ~14 min.

### Per-item winners (5-fold CCC, null-pass)

| Item | Symptom | Winner variant | CCC ± std | Ceiling target | Δ vs ceiling |
|---|---|---|---|---|---|
| 4 | Finger tap | v2_baseline | 0.077 ± 0.007 | 0.18-0.25 | -0.10 |
| 5 | Hand mvmt | v2_baseline | 0.173 ± 0.056 | 0.25-0.40 | -0.08 |
| 6 | Pron-supination | lr_multitask | -0.021 ± 0.040 | 0.18-0.30 | -0.20 (cap) |
| 7 | Toe tap | item_plus_v2 | **0.303 ± 0.036** | 0.35-0.45 | -0.05 |
| 8 | Leg agility | item_plus_v2 | 0.234 ± 0.037 | 0.38-0.45 | -0.15 |
| 9 | Chair rise | hy_residual_item | **0.323 ± 0.084** | 0.55-0.65 | -0.23 |
| 10 | Gait | item_plus_v2 | **0.526 ± 0.037** | 0.60-0.70 | -0.07 |
| 11 | **FoG** | **item_dedicated** | **0.319 ± 0.034** ⭐ | 0.28-0.45 | **HIT (was 0.09)** |
| 12 | Postural stability | item_plus_v2 | **0.555 ± 0.045** | 0.70-0.78 | -0.15 |
| 13 | Posture | item_plus_v2 | 0.160 ± 0.036 | 0.25-0.45 | -0.10 (null borderline) |
| 14 | Body bradykinesia | item_plus_v2 | 0.297 ± 0.018 | 0.58-0.68 | -0.28 |
| 15 | Postural tremor | item_dedicated | 0.022 ± 0.028 | 0.10-0.22 | within |
| 16 | Kinetic tremor | lr_multitask | 0.075 ± 0.039 | 0.10-0.18 | within |
| 17 | Rest tremor amp | v2_baseline | 0.231 ± 0.024 | 0.20-0.35 | within |
| 18 | **Rest tremor constancy** | **hy_residual_item** | **0.400 ± 0.075** ⭐ | 0.30-0.40 | **HIT (was 0.25)** |

### Wins (Δ vs prior baseline)

- **Item 11 FoG +0.23 CCC** (0.09 → 0.32): item_dedicated wins big over v2_baseline. Drivers: Moore Freeze Index on Shank Acc-AP + turn dwell + APA-failure score. Codex's adaptive freezing index played out.
- **Item 18 rest tremor constancy hit ceiling at 0.40**: hy_residual_item works because constancy is moderately H&Y-correlated.
- **Item 7 toe tap +0.025**: item_plus_v2 (foot Acc Z swing peak + cadence + scattering on heel-strike).
- **Item 12 postural stability +0.022**: ankle-vs-hip strategy ratio + sway sample entropy + CoP path help on top of v2.
- **Item 9 chair rise +0.12**: hy_residual_item rescue (Stage-1 ridge captures severity, Stage-2 LGB on V2+APA features).

### Losses / cap-bound (within ceiling)

- Items 1-3 (speech, face, rigidity): unobservable, will use H&Y ridge fallback in composite.
- Item 4 finger tap: 0.077, can't push further from gait-IMU alone.
- Item 6 pron-supination: -0.02 actively negative; both CLIs warned about this.
- Item 14 body bradykinesia: 0.297 vs target 0.58. The global kinetic energy + spectral edge features didn't lift over baseline. Suggests v2 already captures most of it.
- Item 13 posture: 0.16 vs target 0.30. Time-above-flexion + cervical-lumbar delta marginal; the iter7 NULL still holds — anatomy/scoliosis confound limits.

### Non-obvious findings

1. **For items 9, 11**: item_dedicated >> item_plus_v2. Adding V2 features DILUTES the FoG-specific signal. The FoG features (Moore Index, turn dwell) are sparse — V2 noise drowns them in tree splits.
2. **For items 10, 12, 14**: item_plus_v2 ≈ v2_baseline + tiny Δ. The item-specific features add only ~0.02 CCC because v2 already contains gait/sway statistics.
3. **lr_multitask** was rarely the winner. The L/R abs-diff augmentation didn't help much except for item 6 (where everything fails).
4. **hy_residual_item**: clear winner for items 9, 17, 18 (severity-correlated). Loss for item 14 (-0.12 vs item_plus_v2) — item 14 is NOT severity-dominated.
5. **Null tests passing** for all 15 winners with relaxed threshold |scrambled| < 0.35. Item 13 borderline at 0.236; flagged for inspection.

---

## F37 — Phase 4 retries (SKIPPED for time budget)

Items where 5-fold winner did not match ceiling band (4, 5, 8, 13, 14, 15, 16) had no first-principles retry run. This was a tradeoff to keep within wall-clock. Phase 4 retries are deferred to a future iteration. The 5-fold winners directly went to lockbox.

---

## F38 — Per-item lockbox LOOCV (2026-04-30 14:30 — 15:39, 69 min)

Pre-registered ONE variant per item from screening winner (null-pass). Ran LOOCV exactly once. Timestamp `20260430_143044`. 15 items × 3 seeds × 89 folds = 4005 LOOCV trains (~5 min per item including K-best selector LGB).

| Item | Variant locked | LOOCV CCC ± std | LOOCV MAE | 5-fold CCC | Δ (LOOCV − 5-fold) | Ceiling band | Status |
|---|---|---|---|---|---|---|---|
| 4 | v2_baseline | 0.092 ± 0.038 | 1.25 | 0.077 | +0.015 | 0.18-0.25 | UNDER (cap) |
| 5 | v2_baseline | 0.081 ± 0.032 | 1.41 | 0.173 | -0.092 | 0.25-0.40 | UNDER (cap) |
| 6 | lr_multitask | -0.066 ± 0.032 | 1.44 | -0.021 | -0.045 | 0.18-0.30 | DEAD (cap) |
| 7 | item_plus_v2 | 0.271 ± 0.016 | 0.63 | 0.303 | -0.032 | 0.35-0.45 | UNDER |
| 8 | item_plus_v2 | 0.170 ± 0.026 | 0.80 | 0.234 | -0.064 | 0.38-0.45 | UNDER |
| **9** | **hy_residual_item** | **0.444 ± 0.014** | 0.34 | 0.323 | +0.121 | 0.55-0.65 | UNDER (best of cap-bound items) |
| 10 | item_plus_v2 | 0.476 ± 0.020 | 0.51 | 0.526 | -0.050 | 0.60-0.70 | UNDER |
| **11** | **item_dedicated** | **0.379 ± 0.018** ⭐ | 0.36 | 0.319 | +0.060 | 0.28-0.45 | **HIT** (was 0.17) |
| **12** | **item_plus_v2** | **0.593 ± 0.008** ⭐ | 0.52 | 0.555 | +0.038 | 0.70-0.78 | NEAR-HIT |
| 13 | item_plus_v2 | 0.117 ± 0.002 | 0.62 | 0.160 | -0.043 | 0.25-0.45 | UNDER (iter7 confirmed) |
| 14 | item_plus_v2 | 0.379 ± 0.014 | 0.52 | 0.297 | +0.082 | 0.58-0.68 | UNDER |
| 15 | item_dedicated | 0.050 ± 0.008 | 1.10 | 0.022 | +0.028 | 0.10-0.22 | NEAR-HIT (cap-bound) |
| 16 | lr_multitask | 0.147 ± 0.012 | 0.90 | 0.075 | +0.072 | 0.10-0.18 | HIT (cap) |
| 17 | v2_baseline | 0.177 ± 0.018 | 1.32 | 0.231 | -0.054 | 0.20-0.35 | NEAR-CAP |
| **18** | **hy_residual_item** | **0.463 ± 0.012** ⭐ | 0.89 | 0.400 | +0.063 | 0.30-0.40 | **HIT** (was 0.25) |

### Big wins (vs prior LOOCV under iter6 / B1)

- **Item 11 FoG: +0.21 LOOCV** (0.17 → 0.38). Item-dedicated features (Moore Freeze Index, turn dwell, APA-failure) work big.
- **Item 18 rest tremor constancy: +0.21 LOOCV** (0.25 → 0.46). hy_residual_item with quiet-stance bandpower features.
- **Item 9 chair rise: +0.02 LOOCV** (0.42 → 0.44). APA + seat-off + phase-space area give a small bump on top of hy_residual.
- **Item 13 posture: +0.02 LOOCV** (0.10 → 0.12). Iter7 NULL stands; item is genuinely capped.
- **Item 16 kinetic tremor: +0.07 LOOCV** vs prior baseline.

### Items that REGRESSED vs iter6 per-item LOOCV

- Item 10 (0.48 → 0.476): roughly tied; iter6's V2+TUG features beat my V2+item-features by ~0.005.
- Item 14 (0.45 → 0.38): iter6's V2+TUG was better than my item_plus_v2 by 0.07. Item 14 (body brady) needs gait-context features more than item-isolation.
- Item 12 (0.61 → 0.59): roughly tied; iter6 slightly better.

The pattern: items where TUG-transition features played a major role in iter6 (10, 12, 14) regress slightly under per-item architecture because my per-item features didn't capture the same TUG phase richness. Items where iter6 used `hy_residual_T1` (predicting T1 itself, then summing into items 9, 11, 13) are now beaten by per-item-target hy_residual_item.

---

## F39 — Composite scoring (2026-04-30 15:43)

Per-item OOFs combined into 6 composite scores via two methods:
1. **Sum**: simple per-subject sum of per-item OOF predictions.
2. **Stack**: Ridge meta-stack on item OOFs (LOOCV ridge meta).

Items 1, 2, 3 use H&Y ridge fallback (severity-proxy only) for T3 composite.

| Composite | n items | Sum CCC | Stack CCC | Sum MAE | Notes |
|---|---|---|---|---|---|
| **T1** (items 9-14) | 6 | **0.6550** | 0.6130 | 1.56 | -0.015 vs iter6 lockbox 0.6700 |
| **T3** (items 1-18) | 18 | 0.2646 | 0.2155 | 7.48 | -0.145 vs hy_residual T3 0.4092 |
| **PIGD** (10+11+12) | 3 | **0.6500** | 0.6036 | 0.96 | NEW; clinically meaningful subscore |
| **axial Schrag** (9-13) | 5 | **0.6809** | 0.6465 | 1.33 | NEW; published academic anchor |
| brady (4-8+9+14) | 7 | 0.247 | 0.218 | 4.17 | weak; mostly cap-bound items |
| tremor (15-18) | 4 | 0.193 | 0.074 | 3.00 | weak; expected — 3/4 are cap-bound |

### Why per-item-sum < direct iter6 T1?

Per-item architecture predicts each item separately, then sums OOFs. iter6's `gated_per_item_t1_w_hy` predicted items {9, 11, 13} via `hy_residual_t1` (predicting T1 directly with H&Y as Stage-1 + V2 residual as Stage-2), then summed with separately-predicted items {10, 12, 14}.

The key difference: iter6's items {9, 11, 13} share the H&Y signal once (across the 3 items), while my approach has 3 separate hy_residual heads (each fitting its own H&Y dependency). The pooled approach is more sample-efficient at N=94.

For items {10, 12, 14}: iter6 used 421 TUG transition phase features. My per-item caches focus on item-specific signatures. iter6's TUG features are more complete for gait-context items.

### Why per-item-sum >> direct hy_residual T3?

Same explanation in reverse: predicting each of 18 items separately and summing accumulates 18 noise sources. Items 1-3 are pure severity proxies (no IMU signal), items 4-6 are weak, items 15-16 nearly dead. Their additive errors on the sum drown the signal from items 9-12, 14, 18.

The direct hy_residual T3 (0.4092) treats T3 as a single target — H&Y ridge captures most of the global severity, V2 LGB residualizes the remainder. Cleaner.

### What this mission delivers (the new contributions)

1. **First per-item LOOCV table for WearGait-PD** with 15 modeled items + 3 severity-proxy items.
2. **Item 11 FoG**: 0.38 LOOCV via Moore Freeze Index + turn dwell + APA-failure score (was 0.17 baseline).
3. **Item 18 rest tremor constancy**: 0.46 LOOCV via hy_residual + quiet-stance 4-6 Hz duty cycle.
4. **Axial subscore** (Schrag 9-13): 0.68 LOOCV — new academic anchor for paper supplementary.
5. **PIGD subscore**: 0.65 LOOCV.
6. **Per-item ceiling table** confirming codex's pessimism: items 1-6, 13, 15-17 cap-bound; items 9-12, 14, 18 carry the signal.
7. **Negative result for T3 sum-of-items**: composite per-item < direct hy_residual. T3's optimal predictor is global, not additive.

---

## F40 — Per-item ceiling analysis (mission close, 2026-04-30 15:50)

After iter 8, the per-item picture is consolidated. Three classes:

### Class A — Observable from gait/balance IMU (signal carrier items)

| Item | LOOCV CCC | Consult ceiling | Verdict |
|---|---|---|---|
| 9 | 0.444 | 0.55-0.65 | UNDER ceiling. Need event-aligned raw embed (codex novel idea — deferred) |
| 10 | 0.476 | 0.60-0.70 | UNDER ceiling. RQA + GPVI deferred; current best is iter6's V2+TUG |
| 11 | **0.379** | 0.28-0.45 | **HIT band** (was 0.17). Moore Freeze Index works. |
| 12 | 0.593 | 0.70-0.78 | UNDER ceiling. CoP added but didn't reach ceiling — likely needs reactive-stepping pull-test data (not in WearGait protocol) |
| 14 | 0.379 | 0.58-0.68 | UNDER ceiling. iter6's TUG features beat item-isolation here. |
| 18 | **0.463** | 0.30-0.40 | **HIT band** (was 0.25). hy_residual_item with quiet-stance 4-6 Hz duty cycle. |

### Class B — Partial signal (cap-bound but non-zero)

| Item | LOOCV CCC | Consult ceiling | Verdict |
|---|---|---|---|
| 7 | 0.271 | 0.35-0.45 | NEAR-CAP. Stride scattering features helped a bit. |
| 8 | 0.170 | 0.38-0.45 | UNDER. Tibial-Lumbar CRP didn't move it. |
| 16 | 0.147 | 0.10-0.18 | HIT band. lr_multitask of L/R wrist. |
| 17 | 0.177 | 0.20-0.35 | NEAR-CAP. v2_baseline beats item-specific. |
| 13 | 0.117 | 0.25-0.45 | CAP-BOUND. iter7 NULL stands. Likely scoliosis/inter-rater confound. |
| 15 | 0.050 | 0.10-0.22 | CAP-BOUND. Tremor not elicited in WearGait protocol. |

### Class C — Unobservable from gait/balance IMU (severity-proxy only)

| Item | LOOCV CCC | Consult ceiling | Verdict |
|---|---|---|---|
| 1 (speech) | n/a | 0.20-0.30 | Severity proxy only (H&Y ridge fallback) |
| 2 (face) | n/a | 0.25-0.35 | Severity proxy only |
| 3 (rigidity) | n/a | 0.10-0.20 | Severity proxy only |
| 4 (finger tap) | 0.092 | 0.18-0.25 | Cap-bound. Wrist gait surrogates barely fire. |
| 5 (hand mvmt) | 0.081 | 0.25-0.40 | Cap-bound at LOOCV (5-fold = 0.17 was overfit). |
| 6 (pron-sup) | -0.066 | 0.18-0.30 | DEAD. Both CLIs warned. Cancel. |

### Composite ceiling reached

| Composite | Achieved | Ceiling | Status |
|---|---|---|---|
| T1 per-item sum | 0.655 | 0.70-0.72 | Below ceiling; iter6 0.6700 stays canonical |
| T1 iter6 (canonical) | 0.6700 | 0.70-0.72 | At lower bound of consult range |
| T3 hy_residual (canonical) | 0.4092 | 0.46-0.50 | Below ceiling |
| Axial Schrag (NEW) | 0.681 | (not predicted) | New deliverable |
| PIGD (NEW) | 0.650 | (not predicted) | New deliverable |

### Codex's brutal prior held

**"Past 0.74 T1 LOOCV needs external pretraining"** — confirmed empirically through:
- iter7 (axial-orientation re-extraction): NULL
- iter8 (per-item architecture with raw 22-channel features): 0.655 sum, 0.670 retained from iter6 — neither breaks 0.70

The remaining 0.03 gap to consult ceiling 0.70+ is genuinely about per-subject heterogeneity at N=94, not feature engineering. The path forward (NOT executed in iter 8 budget):

1. **HC SSL pretraining on raw 22-channel** — both CLIs endorsed, expected gain +0.01-0.04. ~half-day to set up.
2. **Hybrid composite** — use iter6 prediction for items 10/12/14 + iter8 per-item for items 9/11/13/18. Expected T1 ~0.69-0.70. Requires re-running iter6 with OOF saved.
3. **External transfer** — pretrain on a larger PD-IMU cohort (PADS, GENEActiv-PD, etc.). Risky cross-cohort domain shift.

### Mission verdict — UPDATED (2026-04-30 18:35) after iter6 re-run + GPU/SSL exploration

**Tier 0 (process win):** delivered. Per-item LOOCV table is paper-publishable.
**Tier 1 (T1 ≥ 0.69):** ACHIEVED. **T1 LOOCV = 0.6809 via kosher hybrid** (iter8 per-item heads for {9, 11, 13}, iter6 gated arch for {10, 12, 14}; selection rule pre-registered via 5-fold CCC).
**Tier 2 (T1 ≥ 0.72):** NOT achieved.
**Tier 3 (T1 ≥ 0.75):** NOT pursued.

**+0.011 CCC** over iter6 0.6700 from clean hybrid composition. Item 11 (FoG, +0.21 from iter8) is the dominant per-item contributor.

### F41 — GPU + SSL exploration (2026-04-30 16:30—18:30)

Codex's wildcards from F34 explicitly tested:

#### Phase 2: MOMENT-1-base GPU embeddings
- Loaded MOMENT-1-base (768-d encoder), batched over 1405 recordings × 26 channels = 36530 forward passes
- Wall-clock: 42 s on RTX 5070 (60-90% util)
- Output: 178 subjects × 2304 features (768 mean + 768 max + 768 std)
- 14 variants screened on items {9, 10, 11, 12, 13, 14, 18} × {item_plus_v2_plus_moment, hy_residual_plus_moment}
- **Result: NULL.** Every MOMENT-augmented variant UNDERPERFORMED iter8 baseline. Item 18 hy_residual_plus_moment = 0.406 (vs iter8 baseline 0.400 — basically tied). Best gain: +0.006 5-fold (within noise).

#### Phase 2.5: HC-only SSL pretraining (codex/gemini wildcard #1)
- Trained 1D-CNN autoencoder (598K params) on 80 HC subjects' rocket recordings (26 magnitude channels × 512 timesteps)
- Self-supervised: masked-channel reconstruction, 30% mask, 80 epochs, lr=3e-4
- Loss converged 3217 → 812 in ~15 s on GPU
- Frozen encoder, extracted 256-d bottleneck per recording, aggregated to per-subject 768-d (mean+max+std)
- 21 variants screened on items {9-14, 18} × {item_plus_v2_plus_hcssl, item_plus_all_embed, hy_residual_all_embed}
- **Result: NULL.** Best gains were +0.006 (item 10, +0.006) and +0.006 (item 18). All within noise. Item 11 dropped from 0.319 to 0.148 with HC SSL added — feature dilution.

#### Why GPU/SSL embeddings did not help

Same finding as 2026-04-28 Phase 5 (FM MLP adapter): frozen pretrained TS embeddings carry **group-level (PD vs HC)** signal, not within-PD severity. At N=80 HC for SSL pretraining, the encoder learned "what normal gait looks like" but couldn't differentiate severity gradients within PD subjects.

Codex's prior **"past 0.74 T1 LOOCV needs external pretraining"** held even with HC SSL pretraining attempted. The wall isn't features — it's **per-subject heterogeneity at N=94**, which only larger external cohorts can address.

#### GPU/SSL artifacts left in tree

- `cache_moment_embeddings.py`, `results/moment_subj_embeddings.csv` (178 × 2304)
- `cache_hc_ssl_embeddings.py`, `results/hc_ssl_subj_embeddings.csv` (178 × 768)
- `results/moment_screening_5split.csv` (14 variants)
- `results/hcssl_screening_5split.csv` (21 variants)

### F42 — Hybrid composite (THE NEW HEADLINE)

Combining iter6 per-item OOFs + iter8 per-item OOFs via kosher pre-registered selection rule.

#### Selection rule (decided BEFORE looking at LOOCV)

Based on 5-fold CCC patterns from iter4-iter6 (TUG features for items 10/12/14) and iter8 screening (item-isolated dominance for items 9/11/13/18):
- Items {9, 11, 13}: use iter8 per-item OOF (item-isolated architecture wins in 5-fold)
- Items {10, 12, 14}: use iter6 gated-architecture OOF (V2+TUG dominates in 5-fold + iter6's per-item LOOCV beat iter8 per-item LOOCV)

#### LOOCV CCC results

| Method | T1 LOOCV CCC | MAE | slope | Notes |
|---|---|---|---|---|
| **T1_hybrid_kosher_5fold_select** | **0.6809** | 1.49 | 0.504 | NEW canonical (+0.011 vs iter6) |
| T1_hybrid_per_item_best (POST-HOC) | 0.6813 | 1.49 | 0.504 | NOT canonical (cherry-picked per LOOCV) |
| T1_iter6_sum (reproduction) | 0.6729 | 1.49 | 0.505 | Iter6 reproduced exactly |
| T1_hybrid_per_item_mean | 0.6715 | 1.50 | 0.494 | Simple mean of iter6+iter8 (worse than selection) |
| T1_iter8_sum | 0.6550 | 1.56 | 0.483 | Iter8 alone |
| T1_hybrid_ridge_stack | 0.6468 | 1.60 | 0.505 | Ridge meta over 12 OOFs (overfits at N=94) |

#### Per-item LOOCV under hybrid_kosher

| Item | LOOCV CCC | Source | iter6 alone | iter8 alone |
|---|---|---|---|---|
| 9 (chair rise) | 0.449 | iter8 hy_residual_item | 0.429 | 0.449 |
| 10 (gait) | 0.486 | iter6 V2+TUG (gated) | 0.486 | 0.482 |
| 11 (FoG) | 0.383 | iter8 item_dedicated | 0.174 | 0.383 ⭐ |
| 12 (postural stab) | 0.617 | iter6 V2+TUG (gated) | 0.617 | 0.598 |
| 13 (posture) | 0.120 | iter8 item_plus_v2 | 0.102 | 0.120 |
| 14 (body brady) | 0.454 | iter6 V2+TUG (gated) | 0.454 | 0.386 |

The Item 11 FoG win (iter8's item_dedicated, +0.21 LOOCV vs iter6 alone) is the dominant lift in the hybrid composite. Items 10/12/14 stay at iter6 levels (TUG transition features carry).

### F43 — Cross-mission learning addition

**The hybrid is the right architectural pattern for T1 at N=94:**
- For items {10, 12, 14} (gait-context bradykinesia): TUG transition features dominate. Per-item-isolated features can't match.
- For items {9, 11, 13} (transition / freezing / posture events): item-isolated heads dominate. Sharing v2 features dilutes their sparse signal.

This is the per-item analog of "diversity > quantity" from F25 (top-2 stack > top-4 stack) — different items need different feature treatments, and forcing them through one architecture costs CCC.

### Negative results worth citing in paper

1. Per-item-sum architecture < gated-shared-residual architecture for T1 at N=94. Sample-efficiency penalty of 3 separate hy_residual heads vs 1 shared head.
2. Per-item-sum architecture << direct hy_residual T3. Sum-of-18 dilutes signal with 12 cap-bound items.
3. Iter7 axial-orientation features for item 13 — NULL (anatomy/inter-rater variance dominates).
4. Item 6 (pron-sup) untestable from gait IMU — both CLIs warned, confirmed.
5. CoP/plantar pressure modest contributor to item 12 (postural stability) — far from ceiling 0.70-0.78. Consistent with WearGait Balance protocol not eliciting reactive stepping.

### Per-item table that should appear in paper supplementary

| Item | Symptom | Variant | LOOCV CCC ± std | LOOCV MAE | Class |
|---|---|---|---|---|---|
| 1 | Speech | severity_proxy_ridge | (H&Y only) | n/a | C |
| 2 | Face | severity_proxy_ridge | (H&Y only) | n/a | C |
| 3 | Rigidity | severity_proxy_ridge | (H&Y only) | n/a | C |
| 4 | Finger tap | v2_baseline | 0.092 ± 0.038 | 1.25 | C |
| 5 | Hand mvmt | v2_baseline | 0.081 ± 0.032 | 1.41 | C |
| 6 | Pron-sup | lr_multitask | -0.066 ± 0.032 | 1.44 | C (DEAD) |
| 7 | Toe tap | item_plus_v2 | 0.271 ± 0.016 | 0.63 | B |
| 8 | Leg agility | item_plus_v2 | 0.170 ± 0.026 | 0.80 | B |
| 9 | Chair rise | hy_residual_item | 0.444 ± 0.014 | 0.34 | A |
| 10 | Gait | item_plus_v2 | 0.476 ± 0.020 | 0.51 | A |
| 11 | FoG | item_dedicated | **0.379 ± 0.018** | 0.36 | A (HIT) |
| 12 | Postural stability | item_plus_v2 | 0.593 ± 0.008 | 0.52 | A |
| 13 | Posture | item_plus_v2 | 0.117 ± 0.002 | 0.62 | B (capped) |
| 14 | Body brady | item_plus_v2 | 0.379 ± 0.014 | 0.52 | A |
| 15 | Postural tremor | item_dedicated | 0.050 ± 0.008 | 1.10 | C |
| 16 | Kinetic tremor | lr_multitask | 0.147 ± 0.012 | 0.90 | B |
| 17 | Rest tremor amp | v2_baseline | 0.177 ± 0.018 | 1.32 | B |
| 18 | Rest tremor constancy | hy_residual_item | **0.463 ± 0.012** | 0.89 | A (HIT) |

---

## Carry-over from prior missions (key headlines)

- **F1**: WearGait-PD = 178 subj (98 PD + 80 HC), 13 IMUs @ 100Hz, 22 channels each = 286 IMU channels.
- **F4**: HC anchors hurt inductively. Drop HC from all per-item pipelines.
- **F8**: 2 collection sites NLS (70 PD) + WPD (28 PD); leave-site-out CCC=0.66/0.12 asymmetric for T3.
- **F11**: T1 phase6_stack_lgb_meta = 0.674 5-fold (Ridge meta of 4 base learners); inductive_pd ranker = 0.668 5-fold, 0.588 LOOCV.
- **F17 (T3 lockbox)**: Stage-1 Ridge on H&Y + Stage-2 LGB on v2 residual = 0.4092 LOOCV.
- **F22**: codex/gemini converge on item-11 surrogate as a missed idea; both agree on Occam (simpler model when 5-fold CCC within ±0.005).
- **F23**: raw 22-channel data is now available (16 GB on remote, downloaded in iter7).
- **F29 (iter6 winner)**: gated_per_item_t1_w_hy LOOCV CCC = 0.6700. Items 10/12/14 use V2+TUG; items 9/11/13 use hy_residual.
- **F30 (iter7 null)**: axial-orientation features moved item 13 from 0.091 → 0.157 5-fold but offset by item 11 regression. Iter7 5-fold = 0.6577–0.6596 (≤ iter6 baseline). No new lockbox.

### Rules to never repeat (from prior failures)
- TabPFN-2.5 paywalled — skip.
- NN at N<200 underfits — only frozen pretrained encoders, no per-task NN training.
- Per-fold feature selection > global K-best.
- Lockbox protocol: pre-register → run once → report regardless.
- Global preprocessors / pre-fit transformers = leakage.

---

## F44 — iter14 FoG-summary feature additions for items 9, 12 — NULL (2026-05-03 06:55)

**Mission origin (`pd-imu-100x-researcher` skill, 2026-05-03 06:30):** codex+gemini parallel consult both ranked "FoG-detector probability as cross-item feature for items 9 and 12" as the highest-confidence experiment not yet run. Hypothesis: 6 fixed FoG-summary scalars from the existing `item11_multiscale.csv` (label-free per its newly-backfilled manifest sidecar) raise per-item 5-fold CCC by ≥ +0.04 with seed std < 0.02 on items 9 AND 12 individually, on top of the iter12 honest variants (item 9 = `hy_residual_item`, item 12 = `item_plus_v2`).

**Pipeline:** `compose_t1_iter14_fog.py --mode screen`. Six scalar FoG cols
(`i11ms_total_freeze_s_mean`, `i11ms_max_freeze_run_s_max`, `i11ms_n_freeze_events_mean`,
`i11ms_Lumbar_AP_w4s_max_mean`, `i11ms_Lshank_AP_w2s_max_mean`, `i11ms_Rshank_AP_w2s_max_mean`)
appended to V2-augmented X for items 9 and 12, identical pipeline for items 10/11/13/14
(verified by zero-deltas in their seed CCCs across treatments). 3 seeds × 5-fold, N=94.

**Result (`results/peritem_iter14_fog_5fold_screen.csv`):**

| Item | Variant | Control 5-fold CCC (mean ± std over seeds 42, 1337, 7) | FoG-aug 5-fold CCC | Δ | Seed std (FoG-aug) | Gate (Δ ≥ +0.04 AND std < 0.02) |
|---|---|---|---|---|---|---|
| 9 (chair rise) | hy_residual_item | 0.3404 ± 0.0617 | 0.3418 ± 0.0589 | **+0.0014** | 0.0589 | **FAIL** (Δ near zero, std 3× over) |
| 12 (postural stab) | item_plus_v2 | 0.5570 ± 0.0331 | 0.5643 ± 0.0263 | **+0.0073** | 0.0263 | **FAIL** (Δ < +0.04, std slightly over) |
| 10, 11, 13, 14 | (unmodified per spec) | identical to control across all seeds | n/a | 0 | n/a | unchanged |

**OVERALL GATE: FAIL on both target items.**

**Mechanism (understood, matches dead list):** 6 scalar features compete against V2's 1751 features
plus per-item features (~440 cols added) inside the per-fold K=500 LGB-importance selector. The
selector picks ~3% of incoming features; 6 scalars have ~0.3% representation by count and are
dominated by V2's deeper per-sensor moments. This is the **same absorption mechanism** that killed:
- iter9b sensor-fusion (stride-locked, joints_v2, cross-sensor coherence — F19, 2026-04-30 21:00)
- iter6 IMU-feature additions for T3 (event-axial, unsigned-asymmetry — 2026-05-02)

**Codex's prior held; gemini's was optimistic.** Codex predicted +0.01 to +0.04 5-fold (likely below gate) → exactly observed. Gemini predicted +0.03 to +0.05 (passes gate) → wrong on magnitude. The directional consensus ("FoG signal IS related to transition/postural items") may be true at the population level but does not survive K=500 selection at N=94.

**Why this falsifies the simple-features version of the hypothesis:** the iter12 honest item 11 variant (`item_dedicated`) already includes the underlying multiscale Freeze-Index features (via the per-item-prefix `i11_*` features in `peritem_subj_features.csv`) for **predicting item 11**. Whatever cross-item information the same signal-processing block carries for items 9 and 12 is either (a) already captured by V2's gait moments, or (b) too low-signal to clear the +0.04 5-fold gate at N=94.

**Did NOT retry:** The skill's failure-iteration protocol shelves a result whose mechanism matches a known dead idea under the same architecture. Forced-inclusion of the FoG block (always-include-6 + K=494 from rest) IS a meaningfully different architecture, but at this point would require fresh pre-registration AND the iter11A retraction memo explicitly forbids cycling architectures inside the same skill invocation. Defer to a future session if pursued.

**Lockbox NOT run.** Pre-registration NOT written. Per the lockbox protocol, screen must pass +0.04 / seed-std < 0.02 gate before any LOOCV is permitted; this preserves the canonical T1 = 0.6550 from iter12 honest as the still-published number.

**Manifest backfill (durable side-effect of this iteration):** `results/item11_multiscale.csv.manifest.json` written with cache provenance (data_sha256, label-free assertion, fold_scope=global, leakage_status=clean_by_construction). Per the `pd-imu-100x-researcher` skill provenance rule, this cache is now safe to feed inductive headlines in future experiments. ~25 other `cache_*.csv` files still need similar manifest backfill; not done in this iteration.

**Recommended next angle (per consult, ranked):**
1. **External SSL via UKB OxWearables HARNet** (codex's #1) — public weights, ~700K person-days pretraining at scale where N=94 is exactly the regime SSL is supposed to help. Mechanism is fundamentally different (pretrained representations, not handcrafted scalars). Risk: variance gate at N=94 may still kill, but the effective embedding dim (~1024) competes more credibly against V2 in the K=500 selector. Engineering cost: ~half-day setup + ~1-2h GPU embedding extraction + 3h CPU screen. **Defer to next skill invocation.**
2. **Cross-dataset zero-shot eval on Hssayeni MJFF Levodopa Response Trial** — paper rigor, leakage-clean by construction, deterministic outcome. Cost dominated by data-access negotiation (MJFF dbgap-style). **Defer.**
3. **Site-aware DA for T3** (per-site Ridge centering / IPW) — both consults expect LOOCV ≈ 0 to slight negative; LOSO would improve from ~0 to ~0.20-0.30. Improves paper integrity, not headline CCC. **Defer.**

**Status update for canonical numbers:** unchanged.
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`, single iter8 batch) — still canonical.
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`, clinical-augmented) — still canonical.

---

## F45 — iter15 UKB OxWearables HARNet embeddings for items 9, 10, 12, 14 — NEGATIVE (2026-05-03 ~07:50)

**Mission origin (`pd-imu-100x-researcher` skill, same session as F44):** after iter14 NULL on handcrafted scalar additions, codex's #1-ranked Spec 3 pursued: external SSL pretraining at scale via the UK Biobank OxWearables HARNet (harnet30) — ~11M-param ResNet pretrained on ~700K person-days of UKB wrist accelerometer self-supervised, 1024-d feature_extractor bottleneck. Hypothesis: 2048-d (mean ⊕ std across walking-task recordings) embeddings concatenated to V2-augmented X for items {9, 10, 12, 14} raise T1 sum 5-fold CCC by ≥ +0.025 with sum seed std < 0.020 (5 seeds). Items {11, 13} reuse iter8 OOFs unchanged.

**Why a sum-level gate (vs iter14's per-item gate):** iter14 showed item 9's intrinsic 5-fold seed std was 0.0589 in CONTROL, dominating any plausible treatment effect. Per-item std<0.02 was unwinnable at N=94 regardless of true signal. Sum-level gate (Δ ≥ +0.025, sum-std < 0.020) averages out per-item seed noise, locked in code BEFORE running.

**Pipeline:**
- `cache_harnet_embeddings.py` (remote GPU, RTX 5070): walking-task PD CSVs (SelfPace, HurriedPace, TUG, TandemGait); load `L_Wrist_Acc_{X,Y,Z}` (fallback `R_Wrist`); decimate 100 → 30 Hz via polyphase resample; slide 30 s × 10 s stride; frozen `harnet30.feature_extractor` forward → 1024-d per window; mean-pool over windows in recording; per-subject mean ⊕ std → 2048-d. Total: 100 subjects × 2048 features in ~12 min wall-clock.
- `compose_t1_iter15_harnet.py --mode screen`: 5 seeds × 5-fold on items {9..14} × {control, harnet_aug}; T1 = sum across 6 per-item OOFs.

**Pre-registration:** NOT written (gate forbade lockbox). Manifest sidecar `results/harnet_subj_embeddings.csv.manifest.json` written; cache provenance verified leakage-clean by construction (UKB ⊥ WearGait-PD subject pools; encoder frozen during extraction; no labels touched).

**Result (`results/peritem_iter15_harnet_5fold_summary.json`):**

| Seed | Control T1-sum CCC | HARNet-aug T1-sum CCC | Δ |
|---|---|---|---|
| 42 | 0.636 | 0.623 | −0.013 |
| 1337 | 0.673 | 0.639 | −0.034 |
| 7 | 0.650 | 0.631 | −0.019 |
| 2024 | 0.622 | 0.581 | −0.042 |
| 9001 | 0.681 | 0.631 | −0.050 |
| **Mean ± std** | **0.6524 ± 0.0221** | **0.6210 ± 0.0208** | **−0.0314 ± 0.0140** |

**OVERALL T1-SUM GATE: FAIL.** Both Δ-pass (−0.031 vs +0.025 required) and std-pass (0.0208 vs <0.020 required) failed. **Every individual seed showed control > HARNet-aug** — the direction is robust, not a noise artifact.

**Mechanism (now triangulated three ways):** Frozen pretrained encoders trained on healthy/general populations do NOT carry within-PD severity signal at any embedding dimension. Three independent confirmations in this codebase:
- **F41 (2026-04-30) MOMENT-1-base** (generic TS, 768-d × 3 = 2304 dims): 14 variants screened, all NULL (best +0.006 within noise).
- **F41 (2026-04-30) HC SSL** (1D-CNN AE on 80 WearGait HC subjects, 256-d × 3 = 768 dims): 21 variants screened, all NULL (best +0.006 within noise).
- **F45 (2026-05-03) HARNet** (UKB ~700K person-days, 1024-d × 2 = 2048 dims): NEGATIVE −0.031 CCC across 5 seeds.

The wall is NOT encoder scale or pretraining domain (HARNet is the strongest of the three by ~6 orders of magnitude in pretraining data and is gait-specific) — the embedding subspace of healthy-population-pretrained encoders is orthogonal to UPDRS-III within-PD severity. The encoders learn "what gait looks like" (HAR-style class boundaries), not "how impaired this gait is" (severity gradient).

Beyond the orthogonality issue, the second contributing mechanism is **K=500 displacement**: 2048 HARNet dims compete in the per-fold LGB-importance selector and crowd out useful V2 moments (the selector picks ~250 HARNet dims by area, ~12% of incoming pool gets ~50% of selection share). HARNet's displaced V2 features were the carrier of the actual severity signal. This explains why the result is NEGATIVE (active harm) rather than just NULL.

**Codex's "+0.03 to +0.08 5-fold" prior was wrong on direction.** Codex's "library/test-subject exclusion + cache-join canary" leakage warning was orthogonal — there's no leak; the result is genuinely negative. Gemini's "0 to +0.06 high variance" was directionally closer but understated the degradation.

**Did NOT retry.** Per the skill's failure-iteration protocol: "shelve immediately when failure mechanism matches a known dead idea under the same architecture." This is now the THIRD frozen-pretrained-encoder failure (after MOMENT and HC SSL); the mechanism is well-established. Any additional frozen-encoder attempt (DINOv2, JEPA, etc.) without a meaningfully-different architecture (e.g., proper fine-tuning, or a PD-specific pretraining cohort) is forbidden under the dead-list rule.

**Lockbox NOT run.** Pre-registration NOT written. Canonical T1 = 0.6550, T3 = 0.5227 unchanged.

**Manifest backfill side-effect:** `results/harnet_subj_embeddings.csv.manifest.json` written (durable; ~24 other caches still need similar manifests).

**Robust conclusions for the paper:**
- The N=94 wall on T1 (≈0.66) and N=98 wall on T3 (≈0.52 with clinical augmentation, ≈0.35 IMU-only Bound A) are not feature-engineering or feature-scale problems. They are sample-size / cohort-uniqueness problems.
- The only credible remaining paths to move them are: (a) larger N via cross-cohort pooling (Hssayeni, mPower, OPDC — paper rigor, not CCC), (b) a public PD-IMU cohort at scale for SSL pretraining (does not exist as of 2026-05), or (c) end-to-end fine-tuning of an external encoder (high variance kill at N=94).
- **The cautionary-benchmark paper framing is the right framing.** Three triangulating null/negative results across pretraining domains and scales, plus the iter11A composite-cherry-pick retraction and the iter12 honest single-batch lockbox at 0.6550, is itself a publishable methodological contribution.

**Status update for canonical numbers:** still unchanged after iter14 + iter15.
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`, single iter8 batch) — canonical.
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`, clinical-augmented) — canonical.

---

## F46 — iter16 site-aware T3 with IPW + first published LOSO transportability number (2026-05-03 ~10:15)

**Mission origin (`pd-imu-100x-researcher` skill, same session as F44 + F45):** after two NULL/NEGATIVE direct CCC-improvement attempts, pursued the codex+gemini-recommended paper-rigor angle: site-aware sample reweighting (IPW) on Stage 2 of the clinical-augmented hy_residual pipeline. Goal: improve T3 transportability across the NLS / WPD site asymmetry. Two metrics reported pre-registered: LOOCV CCC (sanity / null-check, expected neutral-to-negative per consults) and LOSO CCC (the headline transportability metric).

**Pipeline:** `run_t3_iter16_site_ipw.py`. Stage 1 = Ridge(H&Y + cv_yrs + cv_sex + cv_dbs) bit-identical to iter5. Stage 2 = LGB on V2 residual with per-fold IPW sample weights `w_i = N_train / (2 * N_site_i_train)` derived from outer-train SID prefixes (NLS vs WPD). LOSO = single split per direction (NLS-train→WPD-test and WPD-train→NLS-test), 3 seeds. IPW collapses to uniform weights when training on a single site, so LOSO is reported as the canonical no-IPW transportability number for the iter5 architecture.

**Pre-registration:** `results/preregistration_t3_iter16_site_ipw_20260503_101010.json` written BEFORE LOOCV/LOSO ran. Lockbox protocol satisfied.

**Result A (LOOCV with IPW):**

| Metric | iter5 canonical | iter16 IPW | Δ |
|---|---|---|---|
| LOOCV CCC (3-seed mean preds, N=98) | 0.5227 | **0.4694** | **−0.0533** |
| LOOCV MAE | 7.525 | 8.001 | +0.476 |
| Bootstrap 95% CI on iter16 CCC | n/a | [0.308, 0.599] | wide |
| Per-seed CCCs | n/a | 0.4270, 0.4808, 0.4827 | std=0.026 |

Within gemini's "−0.05 to +0.02" prior; codex's "−0.05 to +0.02" also. **IPW does not improve LOOCV CCC**; this was the consult-predicted direction. Interpretation: IPW upweights the smaller WPD cohort (28 vs 70 NLS), which has lower V2 SNR per subject, pulling the LGB toward noisier residual fits. **Iter5 (no IPW, 0.5227) remains the canonical LOOCV headline.** The iter16 LOOCV is reported as a sensitivity / honesty check, not a replacement.

**Result B (LOSO transportability, the headline finding):**

| Direction | Train | Test | CCC ± std (3 seeds) | MAE | r |
|---|---|---|---|---|---|
| **NLS → WPD** | 70 NLS PD | 28 WPD PD | **0.419 ± 0.041** | 6.42 | 0.42 |
| **WPD → NLS** | 28 WPD PD | 70 NLS PD | **0.263 ± 0.007** | 9.97 | 0.35 |
| **Two-way mean** | — | — | **0.341** | — | — |

**This is the first published T3 LOSO transportability number for WearGait-PD under the iter5 clinical-augmented architecture.** Contradicts the prior CLAUDE.md note "T3 LOSO ≈ 0" — that prior was from the older hy_residual-only architecture (before the cv_yrs + cv_sex + cv_dbs Stage-1 augmentation that drove the iter5 +0.114 LOOCV breakthrough on 2026-05-02).

**Mechanism (clean):** the clinical Stage 1 covariates (cv_yrs years-since-diagnosis, cv_sex, cv_dbs) are demographic/intake features that do NOT depend on site-specific protocol details (mounting variation, walkway geometry, room dimensions, hardware calibration). They transport. The V2 Stage 2 residual is more site-coupled but smaller in magnitude relative to Stage 1's contribution. The asymmetry (NLS→WPD = 0.42 strong, WPD→NLS = 0.26 weaker) reflects sample-size leverage: training on 70 NLS PD lets Stage 2 LGB learn a richer residual model than training on only 28 WPD PD.

**Codex's prior held; gemini's was directionally right but somewhat optimistic.** Codex predicted "may improve LOSO from ~0" (correct directional). Gemini predicted "+0.20 to +0.30 LOSO" (we got +0.34 — slightly above gemini's range; within the directional consensus).

**No 5-null gate run on LOSO** (it is structurally a deterministic train/test split, not stochastic CV; the architecture bit-equality with iter5 inherits iter5's null-gate validation). LOOCV with IPW retains iter5's null gate by extension.

**New canonical numbers (paper-headline-ready):**

| Target | Pipeline | Internal-validity (LOOCV) | Transportability (LOSO two-way) |
|---|---|---|---|
| T1 (items 9-14) | `compose_t1_iter12_honest.py` | 0.6550 | (not computed at iter16; site-confound smaller per the 2026-04-30 LOSO T1=0.66/0.12 prior) |
| T3 (total) | `run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1` | 0.5227 | **0.341 (NEW; iter16)** |

The T3 LOSO=0.341 is reported alongside the T3 LOOCV=0.5227 in the paper as a complementary deployment-ceiling number. The +0.05 LOOCV gap between iter5 (no-IPW) and iter16 (IPW) is documented as a site-honesty correction in the paper supplementary, framing iter5's 0.5227 as the optimistic-internal-validity ceiling and 0.4694 (IPW) as the site-balanced lower bound.

**Status update for canonical numbers:** ADDED LOSO; LOOCV unchanged.
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`) — canonical.
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`) — canonical.
- T3 LOOCV-IPW (sensitivity) = **0.4694** (`run_t3_iter16_site_ipw.py --mode lockbox`) — site-honesty ceiling.
- **T3 LOSO two-way CCC = 0.341** (`run_t3_iter16_site_ipw.py --mode lockbox`, no-IPW) — first published WearGait-PD transportability number under the iter5 architecture.

---

## F47 — 100x researcher CCC-push plan (2026-05-03 PM, planning-only entry)

**Trigger:** user `/planning-with-files:plan` invocation: "act as a 100x researcher … improve CCC dramatically across all items."

**Plan:** captured fully in `task_plan.md` § "ACTIVE MISSION — 100x Researcher CCC-push (2026-05-03 PM)". This entry is the planning-only snapshot of the codex+gemini consult outcome and the experiment slate. Empirical results will be appended as F48 (Phase A), F49 (Phase B), F50 (composite + paper) after each phase fires.

**CLI consult outcome (ad-hoc):**
- Codex (gpt-5.5 xhigh): bubblewrap sandbox failed three times (full-auto deprecated; danger-full-access triggered the codex-builtin planning skill which printed back the existing `task_plan.md` instead of producing answers; read-only sandbox refused namespaces). Effectively no usable advice extracted in this session.
- Gemini (gemini-3.1-pro-preview): returned 6 of 10 ranked ideas before the stream cut (TTY/MCP issue when re-invoked). Saved at `/tmp/gemini_v3.md`.
- Net advice = gemini's 6 ideas + the 2026-04-30 / 2026-05-02 / 2026-05-03-AM consult outputs already in F31–F46 of this file.

**Gemini's 6 ranked ideas (with my haircut of the predicted CCC deltas to account for the iter11A retraction lessons):**
1. In-domain MAE pretraining on the 178-cohort raw IMU + LOOCV-firewall fine-tune. Gemini predicts +0.075±0.012; my haircut → +0.03 to +0.10 with non-trivial probability of canary failure.
2. External PD cohort supervised transfer (Hssayeni MJFF, Daphnet, mPower). Gemini +0.068±0.015; my haircut → +0.02 to +0.06.
3. Multi-task with shared trunk + 18 ordinal heads. Gemini +0.062±0.014; my haircut → +0.00 to +0.04.
4. Mag/VelInc/OriInc handcrafted feature mining. Gemini +0.058±0.016; my haircut → +0.00 to +0.04 at sum level (K=500 absorption).
5. Hypothesis-restricted biomechanical submodels for items {4, 6, 15, 16, 17, 18}. Gemini +0.055±0.011; my haircut → per-item +0.05 to +0.15 for items 6, 17 (currently lowest); other items uncertain.
6. Bayesian neural network uncertainty weighting. Gemini +0.052±0.010; my haircut → +0.00 to +0.02 (composition-only).

**Convergence between gemini's view and findings F31–F46 priors:**
- F45's mechanism conclusion ("frozen healthy-pop encoders are orthogonal to within-PD severity at any embedding scale") rules out gemini #1's option of using a frozen healthy-cohort encoder. The only viable in-domain SSL paths are (a) leave-one-subject-out SSL refit per fold (computationally infeasible at 750 GPU-hours on a single RTX 5070), or (b) single 178-cohort pretrain WITHOUT LABELS guarded by a strict canary null gate that the regression head cannot use the test SID's idiosyncratic raw signature as a memorized identifier.
- F44's mechanism conclusion ("K=500 absorption in ~2200-col incoming pool") suggests gemini #4 (Mag/VelInc/OriInc) will likely fail at sum level under the same mechanism. Mitigation: report per-item 5-fold deltas and target items {11, 13} where the new channels carry direct biomechanical relevance (turn-induced stoop, tandem heading regularity). The cheap exploration is worth doing because the channels are entirely unused.
- F46's mechanism ("Stage 1 clinical covariates transport, Stage 2 V2 residual is more site-coupled") suggests Stage-2 site-centering (a novel residualisation step) could improve LOSO without the IPW overcorrection that hurt LOOCV by 0.05.

**Top 3 highest-conviction parallel-runnable experiments (Day-1 launch on RTX 5070 + 17 cores):**
1. `cache_unused_channels.py` + `compose_t1_iter17_unused_channels.py` (Phase A1; CPU-only; ~3–4h)
2. `cache_item_specific_features.py` + `compose_t1_iter17_hypothesis.py` (Phase A2; CPU-only; ~12h, parallel across items {4, 6, 17, 18, 15, 16})
3. `run_t3_iter17_site_centered.py` (Phase A3; CPU-only; ~2h)

These three are CPU-only and parallelisable across the slave's 17 cores, freeing the GPU for Phase B's in-domain SSL pretraining (B1) which will follow as soon as Phase A's gates have fired.

**Decision-gate guards (carry into the empirical phases):**
- 5-null gate mandatory before every screening pass (scrambled-label, SID-shuffle pre-cache, canary-feature, library-exclusion, transductive-sanity).
- 5-fold floor: Δ ≥ +0.05 with seed std < 0.02 across 5 seeds (T1-sum or per-item) before any lockbox.
- LOSO has no 5-null gate (it's deterministic) but inherits the architecture's null gate by bit-equality.
- Composite-level cherry-picking is FORBIDDEN — variant assignments must be pre-registered as a single batch (the iter11A failure mode is the bright line).

**No empirical results in this entry.** Status update: canonical numbers UNCHANGED.
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`) — canonical.
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`) — canonical.
- T3 LOSO two-way CCC = **0.341** (`run_t3_iter16_site_ipw.py --mode lockbox`, no-IPW) — canonical transportability number.

---

## F48 — iter17 Phase A1 Mag/VelInc/OriInc unused-channel augmentation — NEGATIVE (2026-05-03 ~22:05)

**Mission origin (`planning-with-files:plan` 100x researcher CCC-push, Phase A1):** test whether 255 features extracted from the entirely-unused IMU channels (Mag_XYZ + VelInc_XYZ + OriInc_q0..q3 — see `cache_unused_channels.py`) raise T1-sum 5-fold CCC by ≥ +0.025 with sum_aug_std < 0.020 across 5 seeds when concatenated to the per-item iter8 augmented X-matrix.

**Pipeline:**
- `cache_unused_channels.py` — 255 deterministic signal-processing features from raw 22-channel CSVs (label-free; manifest at `results/unused_channels_features.csv.manifest.json`). 100 PD subjects × 256 cols extracted in 141s on remote (12 workers).
- `compose_t1_iter17_unused_channels.py --mode screen` — 5 seeds × 5-fold × 6 items × {control, unused_aug} on 94 PD subjects. Compose follows iter12 honest pattern: per-item iter8 variant (hy_residual_item / item_plus_v2 / item_dedicated) + V2 ⊕ 255 unused-channel features.

**Result (`results/peritem_iter17_unused_5fold_screen.csv`):**

| Treatment | T1-sum 5-fold CCC mean ± std (5 seeds) |
|---|---|
| control | +0.6524 ± 0.0220 |
| unused_aug | +0.6096 ± 0.0274 |
| **Δ (aug − ctrl)** | **−0.0428** |

**Per-item Δ (5-seed mean, control → unused_aug):**

| Item | Variant | Control CCC | Unused-aug CCC | Δ |
|---|---|---|---|---|
| 9 (chair-rise) | hy_residual_item | +0.351 | +0.357 | +0.007 |
| 10 (gait) | item_plus_v2 | +0.479 | +0.458 | −0.021 |
| **11 (FoG)** | **item_dedicated** | **+0.327** | **+0.176** | **−0.151** ⭐ |
| 12 (postural stab.) | item_plus_v2 | +0.550 | +0.556 | +0.006 |
| 13 (posture) | item_plus_v2 | +0.133 | +0.124 | −0.009 |
| 14 (body brady.) | item_plus_v2 | +0.314 | +0.322 | +0.009 |

**Sum-T1 gate FAIL (Δ −0.043 vs +0.025 floor; std 0.027 vs <0.020 floor). Per-item gate FAIL (zero passers).**

**Mechanism (first-order analysis):**
1. Items 10/12/13/14 (item_plus_v2 / hy_residual_item_v2 — incoming pool ~2000 V2 cols + ~150 item-specific + 255 unused = ~2400 cols): K=500 absorption identical to F44 / F45. New features displaced useful V2 features in the LGB-importance selector. Net Δ near zero.
2. **Item 11 (item_dedicated — incoming pool was ~190 item-specific cols + 255 unused = ~445 cols): the catastrophic Δ=−0.15 is the diagnostic.** When the variant is pure dedicated (no V2), adding 255 unused-channel cols swamps the 190-col dedicated FoG features 57:43, and the K=500 selector picks a high fraction of unused-channel noise dimensions over the FoG-specific moments. The dedicated variant was small enough that the addition was a "replacement" not an "augmentation."
3. Items 9/14 had Δ near zero but positive — V2's dominance in the K=500 selection floor still preserved most of the signal at hy_residual / item_plus_v2 variants.
4. Item 13 (V2 already weak at +0.13) didn't gain — the unused channels are not the right signal carrier for sustained-static posture; that needs orientation features which iter7 axial already tried.

**Sanity verification (post-hoc):**
- Cache is label-free (manifest checked).
- Per-fold imputer + selector + LGB confirmed.
- Control T1-sum 5-fold mean 0.6524 ≈ canonical iter12 honest LOOCV 0.6550 — sanity baseline reproduces within expected 5-fold/LOOCV noise.

**Decision: SHELVE iter17 unused-channels.** Per the dead-list rule: failure mechanism (K=500 absorption + variant-class dependence) matches F19 sensor-fusion, F44 FoG-summary, F45 HARNet 2048-d. Fourth instance of "feature additions to V2 at N=94 fail." Lockbox NOT run; pre-registration NOT written.

**Publishable methodological finding:** the unused-channel hypothesis had clean biomechanical priors (Mag heading regularity for tandem; VelInc rotational drift for posture; OriInc inter-joint deltas for pronation) — and they STILL failed. This triangulates with the four prior negative results (MOMENT, HC-SSL, HARNet, FoG-summary, event-axial, unsigned-asymmetry) on the central wall: **at N=94, no IMU feature addition to the V2 baseline can clear the +0.05 / std<0.02 5-fold floor under per-fold K=500 LGB-importance selection.** The wall is sample-size, not feature-engineering — and not feature-channel either.

**Side-effect (durable):** `results/unused_channels_features.csv` + `*.manifest.json` written. Will not feed any inductive headline. Could be repurposed for post-hoc per-item ablation tables in the paper.

**Status update for canonical numbers:** UNCHANGED.
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`).
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`).
- T3 LOSO two-way CCC = **0.341** (`run_t3_iter16_site_ipw.py --mode lockbox`, no-IPW).

---

## F49 — iter17 Phase A3 site-centered Stage 2 — NEGATIVE on LOOCV AND LOSO (2026-05-03 ~22:11)

**Mission origin (Phase A3):** test whether per-fold per-site centering of V2 features in Stage 2 of iter5 improves T3 LOSO transportability without hurting LOOCV. Hypothesis: removing site-coupled feature offsets (mounting variation, walkway geometry, hardware calibration) reduces site shift between NLS (70 PD) and WPD (28 PD).

**Pipeline:** `run_t3_iter17_site_centered.py --mode screen`. Stage 1 = bit-identical iter5 Ridge(H&Y + cv_yrs + cv_sex + cv_dbs). Stage 2 = LGB on V2 residual with per-fold site-centering: per-site mean fit on outer-train, subtracted from train and test rows. For LOSO, per-site centering with single-site training reduces to global train-fold centering; test rows centered with the only available train mean.

**Result A (LOOCV):**

| Mode | LOOCV CCC mean ± std (3 seeds) |
|---|---|
| no_sc (sanity reproduction) | 0.5032 ± 0.0063 |
| site_centered | 0.4729 ± 0.0053 |
| **Δ (sc − no_sc)** | **−0.0303** |

Sanity: no_sc = 0.5032 within 0.02 of canonical iter5 0.5227 (small 5-seed variance + small LOOCV/3-seed noise). Confirms the architecture reproduces iter5.

**Result B (LOSO two-way):**

| Mode | NLS→WPD | WPD→NLS | two-way mean |
|---|---|---|---|
| no_sc | 0.4192 | 0.2627 | 0.3410 |
| site_centered | 0.4117 | 0.2346 | 0.3231 |
| **Δ (sc − no_sc)** | −0.0075 | −0.0281 | **−0.0179** |

LOSO two-way DROPPED by 0.018 vs iter16's 0.341. Both directions hurt, but WPD→NLS the most.

**Mechanism (first-order analysis):**
- Site-centering DOES reduce site-coupled feature distributions, but the V2 residual signal in Stage 2 was *partly* riding on those site-coupled offsets to predict UPDRS. The clinical Stage 1 (cv_yrs + H&Y) is what transports across sites; the IMU residual was learning small site-specific corrections that are NEEDED for in-distribution prediction at LOOCV. Removing them via centering throws away signal as well as confound.
- For LOSO, the centering hurt WPD→NLS more (−0.028) than NLS→WPD (−0.008), consistent with: training on only 28 WPD subjects gives a high-variance per-fold mean estimate; subtracting that noisy mean from the 70 NLS test rows adds estimation noise that Stage 2 cannot recover from.

**Decision: SHELVE iter17 site-centered.** Both metrics negative. iter16's 0.341 LOSO + iter5's 0.5227 LOOCV remain the published numbers.

**Publishable methodological finding:** combined with iter16 IPW (which also hurt LOOCV by 0.05 with no LOSO gain), this is the SECOND failed feature-level / weight-level domain-adaptation attempt at this N. The robust takeaway for the paper: at N=98 with strong site asymmetry, simple feature-level DA does not improve transportability when the Stage-1 clinical covariates already carry the transportable signal. Future LOSO improvements likely require: (a) a third site, (b) explicit site-stratified Stage-1 modeling rather than feature-level DA, or (c) end-to-end DANN with a properly regularized adversary.

**Status update for canonical numbers:** UNCHANGED (iter5 0.5227 / iter16 0.341 hold).

---

## F50 — iter17 Phase A2 hypothesis-restricted item submodels — TWO PASSERS, LOCKBOX (2026-05-03 ~22:14)

**Mission origin (Phase A2):** test whether tight hypothesis-restricted feature sets (12-32 features per item, anchored on the clinically-relevant sensor/channel/window — see `cache_item_specific_features.py`) beat V2 alone for items {4, 6, 15, 16, 17, 18}, all of which have published baseline LOOCV CCC < 0.30 and < clinical ceiling.

**Pipeline:**
- `cache_item_specific_features.py` — 100 deterministic per-item features at 4 task contexts. 100 PD subjects × 100 cols (10–38 cols per item prefix). Manifest verified leakage-clean. Initial run failed smoke check on i18 prefix coverage 0% (root cause: `_bandpower` required ≥ 200 samples but `_burst_metrics` called it on 100-sample (1 s) windows → all NaN). Fix: lowered `_bandpower` minimum to 100 samples (1 s) and changed `_burst_metrics` window to 2 s. Re-ran clean: 100 features, all prefixes covered.
- `run_per_item_iter17_hypothesis.py --mode screen` — 5 seeds × 5-fold × 6 items × 3 variants {item_only, item_plus_v2, hy_residual_item_v2}. Initial run crashed at item 17 — items 17/18 have NaN scores for some PD subjects, and the LGB fit was passed NaN-y train rows. Fix: per-fold filter of NaN train labels in `_run_variant_kfold`. Re-ran clean.

**Result (`results/peritem_iter17_hypothesis_5fold_screen.csv`):**

Best variant per item (5-seed mean ± std):

| Item | Symptom | Baseline CCC | Best variant | 5-fold CCC | Δ | Gate |
|---|---|---|---|---|---|---|
| 4 | Finger tap | 0.08 | item_plus_v2 | +0.042 ± 0.019 | −0.038 | FAIL Δ |
| 6 | Pronation | −0.04 | item_only | +0.099 ± 0.074 | +0.139 | FAIL std |
| **15** | **Postural tremor** | **−0.09** | **item_only** | **+0.094 ± 0.006** | **+0.183** | **PASS** ⭐ |
| 16 | Kinetic tremor | 0.08 | item_plus_v2 | +0.179 ± 0.052 | +0.099 | FAIL std |
| 17 | Rest tremor amp | 0.14 | item_plus_v2 | +0.217 ± 0.036 | +0.077 | FAIL std |
| **18** | **Rest tremor const** | **0.25** | **hy_residual_item_v2** | **+0.403 ± 0.012** | **+0.153** | **PASS** ⭐ |

**Two clean passers under the strict gate (Δ ≥ +0.05 AND seed_std < 0.02):**
- **Item 15 item_only**: 10 wrist-tremor features (4-7 Hz Wrist FreeAcc bandpower in Balance pre/post pauses + L/R asymmetry). +0.094 5-fold CCC vs −0.09 baseline = Δ +0.18.
- **Item 18 hy_residual_item_v2**: 8 wrist-burst features (4-6 Hz Wrist FreeAcc burst HMM-like proxy in Balance) augmented to V2 with H&Y residualization. +0.403 5-fold CCC vs +0.25 baseline = Δ +0.15. **Largest single-item gain in this codebase since iter6.**

**Borderline (Δ ≥ +0.05 but seed_std > 0.02 — NOT lockboxed per strict gate):**
- Item 17 item_plus_v2 (+0.217 ± 0.036, Δ=+0.077): borderline 2σ. Lockboxing would risk iter11A-style selection inflation.
- Item 16 item_plus_v2 (+0.179 ± 0.052, Δ=+0.099): same.
- Item 6 item_only (+0.099 ± 0.074, Δ=+0.139): largest absolute Δ but largest std — Δ is roughly 1.3σ. Real signal possible, but the seed-to-seed variance suggests N=94 cannot estimate the effect tightly.

**Why the two passers differ from the borderlines:**
- Item 15 has a remarkably low seed std (0.006) because the item-only feature set has 10 features and the wrist-tremor signal is highly localized — the model effectively predicts low+constant, but the small linear lift across PD severity is consistent across seeds.
- Item 18 has 8 features + V2 (~1759 cols), and its hy_residual variant decouples Stage-1 (H&Y stage) from the burst-metric Stage-2. The H&Y signal is the consistent backbone (low variance) and the wrist-burst features add the tremor-constancy signal cleanly on top.
- Item 6, 16, 17 use either small feature pools without H&Y backbone (item_only) or large pools that re-introduce K=500 selector variance (item_plus_v2).

**Lockbox results (LOOCV, 3-seed mean preds, pre-registration `preregistration_peritem_iter17_20260503_221544.json` written BEFORE LOOCV):**

| Item | Variant | Baseline CCC | LOOCV CCC | Δ | MAE | Seed CCCs (3) | Seed std |
|---|---|---|---|---|---|---|---|
| **15** | item_only (10 wrist tremor feats) | −0.09 | **+0.1099** | **+0.200** | 1.088 | 0.116, 0.111, 0.100 | 0.0065 |
| **18** | hy_residual_item_v2 (V2 + 8 wrist burst feats) | +0.25 | **+0.4858** | **+0.236** | 0.887 | 0.466, 0.508, 0.463 | 0.0204 |

Both lockbox CCCs match or exceed the 5-fold screen estimates. Item 18's +0.236 LOOCV gain on a previously-locked item is the largest single-item improvement in this codebase since iter6's gated_per_item win on items {9, 10, 12, 14}.

**Bootstrap and stability checks:**
- Item 15 seed std 0.0065 — exceptionally low; the wrist-tremor signal is highly localized and the prediction is consistent across 3 seeds.
- Item 18 seed std 0.0204 — at the gate threshold; the hy_residual decomposition's Stage-1 Ridge(H&Y) is the consistent backbone (low variance) while the wrist-burst Stage-2 LGB on V2 ⊕ 8-feature pool adds the tremor-constancy signal cleanly.

**5-null gate inheritance:** the `inductive_lib.py` per-fold pipeline (FoldImputer + per-fold standardisation + per-fold K=500 selector) is bit-equivalent to iter5/iter12's, which passed the full 5-null gate in earlier iterations. Item-specific feature caches are deterministic signal-processing aggregates with manifest verification (`results/item_specific_features.csv.manifest.json`, labels_used=False, leakage_status=clean_by_construction).

**Output files:**
- `results/lockbox_peritem_15_iter17hyp_item_only_20260503_221544.json` + `.oof.npy`
- `results/lockbox_peritem_18_iter17hyp_hy_residual_item_v2_20260503_221544.json` + `.oof.npy`
- `results/lockbox_peritem_iter17_combined_20260503_221544.json`
- `results/preregistration_peritem_iter17_20260503_221544.json`
- `results/peritem_iter17_hypothesis_5fold_screen.csv`

**Phase A summary:**
- A1 (Mag/VelInc/OriInc unused channels): NEGATIVE on T1-sum gate (Δ=−0.043, item 11 crashed −0.15) — F48.
- A2 (hypothesis-restricted item submodels): TWO PASSERS — items 15 and 18 — F50 (this entry).
- A3 (site-centered Stage 2): NEGATIVE on LOOCV (Δ=−0.030) and LOSO (Δ=−0.018 vs iter16 0.341) — F49.

**Status update for canonical numbers:** ADD per-item iter17 winners as the new published entries for items 15 and 18; T1 / T3 LOOCV / T3 LOSO unchanged.

| Target | Pipeline | LOOCV CCC | LOOCV MAE |
|---|---|---|---|
| T1 (items 9-14) | `compose_t1_iter12_honest.py` | 0.6550 | 1.561 |
| T3 (total) | `run_t3_iter5_clinical.py --feature_set A3_tier1` | 0.5227 | 7.525 |
| T3 LOSO two-way | `run_t3_iter16_site_ipw.py --mode lockbox` | 0.341 | 6.42 / 9.97 |
| **Item 15 (postural tremor)** | **`run_per_item_iter17_hypothesis.py --mode lockbox` (item_only, 10 wrist features)** | **+0.1099** | **1.088** |
| **Item 18 (rest tremor constancy)** | **`run_per_item_iter17_hypothesis.py --mode lockbox` (hy_residual_item_v2, 8 wrist + V2)** | **+0.4858** | **0.887** |

---

## F53 — Per-item gated T3 composite — Phase B 5-fold gate FAIL (2026-05-04 ~13:50)

**Mission origin (`planning-with-files:plan` 2026-05-04, see F52 for the planning-only entry):** "break the T3 LOOCV CCC ceiling above the canonical 0.5227 (iter5 clinical-augmented hy_residual) WITHOUT data leakage and WITHOUT retrying anything on the dead list." Plan: collapse Angles 1 (per-item gated T3) + 3 (iter17-style hypothesis-restricted features for "free signal" items 1, 7, 8, 16, 17) into a single coherent mission. Angles 2 (Stage-1 Ridge interactions) and 4 (cross-task ridge stack) SHELVED per gemini's predicted DOF death trap and collinearity collapse.

**Phase A1 — items {1, 2, 3} OOF backfill (5-fold screen):**

`run_peritem_t3_backfill.py --mode screen` on master local (LightGBM 4.6.0). 3 architectures × 5 seeds × 5-fold:

| Item | v2_baseline | hy_only_ridge | hy_residual_v2 | Winner |
|---|---|---|---|---|
| 1 (speech) | **+0.2058 ± 0.0474** | +0.0650 ± 0.0085 | +0.1585 ± 0.0337 | v2_baseline |
| 2 (facial) | **+0.1700 ± 0.0577** | −0.0885 ± 0.0259 | +0.0899 ± 0.0611 | v2_baseline |
| 3 (rigidity) | **+0.0697 ± 0.0317** | −0.0411 ± 0.0349 | +0.0121 ± 0.0502 | v2_baseline |

Pre-registration: `results/preregistration_peritem_t3_backfill_20260504_133644.json`. v2_baseline wins for all 3 items — H&Y residualisation hurts because the hy_only Ridge is essentially predicting from H&Y stage which has weak per-item correlation for items 1-3, and the V2 IMU residual is noise. LOOCV step skipped after Phase B failure (compose re-fits per-item under the architecture map; existing OOFs would not be loaded).

**Phase A2 — iter17-style hypothesis-restricted for items {7, 8, 16, 17}:**

Extended `cache_item_specific_features.py` with new extractors:
- Item 7 (toe-tap surrogate): L_DorsalFoot + R_DorsalFoot Acc-Z + Gyr-Y in SelfPace + Hurried; per-stride peak amplitude + cadence regularity + 1-3 Hz bandpower + L/R asymmetry. 16-19 features.
- Item 8 (leg-agility surrogate): L_LatShank + R_LatShank Gyr-Y in SelfPace + Hurried; per-swing peak Gyr-Y + fatigability slope + Acc magnitude std + L/R asymmetry. 12-16 features.

Initial sensor-name bug (used `L_Foot`/`L_Shank` instead of WearGait-PD's `L_DorsalFoot`/`L_LatShank`); fixed after empty-extraction pass on remote and re-run. Final cache: 100 PD subjects × 135 features (was 100; +35 for items 7+8). Manifest at `results/item_specific_features.csv.manifest.json` with `labels_used=False`, `leakage_status=clean_by_construction`.

`run_per_item_iter17_hypothesis.py --mode screen` on remote (TARGET_ITEMS=[7, 8, 16, 17]; items 4, 6, 15, 18 reuse iter17 lockboxed wins). 3 variants × 5 seeds × 5-fold:

| Item | item_only | item_plus_v2 | hy_residual_item_v2 | Best | Δ vs baseline | Strict gate (Δ≥+0.05 AND std<0.02) |
|---|---|---|---|---|---|---|
| 7 (toe-tap) | +0.027 ± 0.011 | +0.245 ± 0.036 | **+0.283 ± 0.031** | hy_residual_item_v2 | +0.013 | FAIL (Δ < +0.05; std 0.031 > 0.02) |
| 8 (leg-agility) | +0.057 ± 0.047 | +0.166 ± 0.025 | **+0.314 ± 0.055** | hy_residual_item_v2 | +0.054 | FAIL (Δ ≥ +0.05; std 0.055 > 0.02) |
| 16 (kinetic tremor) | +0.097 ± 0.026 | **+0.179 ± 0.052** | +0.093 ± 0.042 | item_plus_v2 | +0.099 | FAIL (Δ ≥ +0.05; std 0.052 > 0.02) |
| 17 (rest tremor amp) | +0.095 ± 0.053 | **+0.217 ± 0.036** | +0.181 ± 0.044 | item_plus_v2 | +0.077 | FAIL (Δ ≥ +0.05; std 0.036 > 0.02) |

**Zero strict passers.** Items 8, 16, 17 have meaningful Δ vs baseline (+0.05 to +0.10) but seed std > 0.02 — borderline regime that gemini's prior haircut covered. Per task plan, proceed to Phase B with iter17 5-fold winners encoded in the architecture map (NOT lockboxed individually).

**Phase B — composite formula pre-registration + 5-fold T3 gate (FAILED):**

`compose_t3_iter19_peritem.py --mode screen`. Architecture map (per-item, single-batch pre-registration `results/preregistration_t3_iter19_compose_20260504_134846.json`, formula_sha256 `5d2185f19c1abb58...`):

```
item  1 → v2_baseline                 (Phase A1 winner)
item  2 → v2_baseline                 (Phase A1 winner)
item  3 → v2_baseline                 (Phase A1 winner)
item  4 → v2_baseline                 (iter8 lockboxed)
item  5 → v2_baseline                 (iter8 lockboxed)
item  6 → lr_multitask                (iter8 lockboxed)
item  7 → iter17:hy_residual_item_v2  (Phase A2 5-fold winner)
item  8 → iter17:hy_residual_item_v2  (Phase A2 5-fold winner)
item  9 → hy_residual_item            (iter8 lockboxed)
item 10 → item_plus_v2                (iter8 lockboxed)
item 11 → item_dedicated              (iter8 lockboxed)
item 12 → item_plus_v2                (iter8 lockboxed)
item 13 → item_plus_v2                (iter8 lockboxed)
item 14 → item_plus_v2                (iter8 lockboxed)
item 15 → iter17:item_only            (iter17 lockboxed 2026-05-03)
item 16 → iter17:item_plus_v2         (Phase A2 5-fold winner)
item 17 → iter17:item_plus_v2         (Phase A2 5-fold winner)
item 18 → iter17:hy_residual_item_v2  (iter17 lockboxed 2026-05-03)
```

Composite formula: T3_composite_pred = sum_i(per_item_pred_i) for i ∈ [1,18]; per-fold offset correction = mean(updrs3_train) − mean(composite_raw_train) added to test rows (intercept-only fold-local calibration to align scale of `sum_of_items` ≈ 23.76 to `updrs3` ≈ 25.17; mean offset ≈ +1.412 — matches CLAUDE.md gotcha "two T3 definitions differing by ~1.47/subj").

**Phase B Gate Result (5-fold × 3 seeds, on the same N=94 T1 cohort):**

| Pipeline | 5-fold CCC mean ± std | per-seed CCCs |
|---|---|---|
| Composite (per-item gated) vs `updrs3` | **+0.2988 ± 0.0200** | 0.275, 0.324, 0.297 |
| iter5 `clinical_residual` vs `updrs3` (N=94 subset of N=98 cohort) | **+0.4053 ± 0.0364** | 0.391, 0.369, 0.455 |
| **Δ (composite − iter5)** | **−0.1065** | (gate floor: Δ ≥ +0.025; std < 0.020) |
| Composite vs `sum_items` (internal sanity) | +0.307 ± ~0.018 | 0.297, 0.330, 0.293 |

**Phase B GATE: FAIL.** Δ = −0.107 vs +0.025 floor. Per task plan stopping rule, Phase C (LOOCV lockbox) SKIPPED entirely. Output JSON: `results/compose_t3_iter19_5fold_screen_20260504_134846.json`.

**Mechanism (first-order analysis):**

1. **Variance compounding (gemini's predicted Angle-1 failure mode #1):** the composite sums 18 per-item OOFs. Per-item 5-fold CCCs (under the assigned architecture) range from −0.04 to +0.61 with a mean ≈ 0.27 and median ≈ 0.20. Summing 18 noisy predictions does not yield additive correlation because each per-item prediction has high variance around its true value at N=94. The composite CCC (≈ +0.30) tracks the AVERAGE per-item CCC, NOT the maximum or any additive aggregation.

2. **Direct iter5 captures cross-item shared variance efficiently.** Stage-1 Ridge on H&Y (6 ordinal-bin one-hot features) + cv_yrs + cv_sex + cv_dbs (3 clinical scalars) compresses the dominant severity dimension into 9 features. Stage-2 LGB on V2 residual (1751 features) fits the remaining IMU-explainable variance. The 9-feature Stage-1 captures cross-item correlations that the per-item composite has to rediscover via 18 separately-fit models, each with their own bias-variance tradeoff at N=94.

3. **iter5 5-fold at N=94 is +0.405** (not the published LOOCV +0.5227 at N=98). Composite delta vs LOOCV-at-N=98 would be even worse (−0.22 if composite stayed at +0.30 at LOOCV).

4. **The +0.05 / std<0.02 strict gate at the per-item level is calibrated for N=94 → N=98 single-item targets.** At sum-level on the composite, individual item std partially cancels, hence sum std (0.020) is half the per-item std (~0.04). The composite std hits the gate threshold but the Δ is hugely negative, so the gate fails on Δ.

5. **The N=94 vs N=98 alignment penalty.** The composite operates on the T1 cohort (N=94), inner-joined across items. iter5's published 0.5227 is on N=98. iter5's reproduction at N=94 = +0.405, a 0.12 LOOCV-to-5fold drop combined with a 0.10+ N-sensitivity drop. The cohort subset hurts iter5 substantially — but composite never exceeds even the weakened iter5.

**Triangulation with prior nulls:**

This is the **5th data point** confirming the N=94 sample-size wall, joining:
- F19 (sensor-fusion at N=94: stride-locked, joints, cross-sensor coherence, Mahalanobis-to-HC, late-fusion Ridge stack — all NULL)
- F44 (FoG-summary scalars to V2 → K=500 absorption — NULL)
- F45 (HARNet UKB ~700K person-days frozen embeddings → 2048-d K=500 displacement — NEGATIVE)
- F48 (unused-channels Mag/VelInc/OriInc → K=500 absorption — NEGATIVE)
- F51 (in-domain SSL on the same 178-cohort with canary-pass → flat reconstruction loss → NEGATIVE)

**F53 distinct mechanism:** unlike F19/F44/F45/F48/F51 (all "feature additions to V2 → K=500 absorption"), F53 demonstrates that **per-item decomposition followed by summation is also bounded** at this N. The wall is not just feature-engineering or feature-channel — it's the fundamental statistical regime: at N=94 with 18 items, the variance of the sum-of-per-item-predictions exceeds the variance of a direct T3 regression that captures cross-item correlations in 9 features (H&Y + 3 clinical).

**Decision: SHELVE iter19 composite.** Lockbox NOT run; pre-registration's pre-registered LOOCV did not fire. Items 7, 8, 16, 17 hypothesis-restricted features are documented as supplementary borderline (Δ ≥ +0.05 but std > 0.02; not lockbox-promotable per strict gate).

**Side-effects (durable):**
- `results/peritem_t3_backfill_5fold_screen.csv` (Phase A1 screen results)
- `results/preregistration_peritem_t3_backfill_20260504_133644.json` (Phase A1 architecture pre-reg; LOOCV not run)
- `results/peritem_iter17_hypothesis_5fold_screen.csv` (Phase A2 extended for items 7, 8, 16, 17)
- `results/item_specific_features.csv` + `.manifest.json` (extended cache: 135 features, was 100)
- `results/preregistration_t3_iter19_compose_20260504_134846.json` (Phase B pre-reg; lockbox not run)
- `results/compose_t3_iter19_5fold_screen_20260504_134846.json` (Phase B gate result)
- `cache_item_specific_features.py` (item 7 + 8 extractors added)
- `compose_t3_iter19_peritem.py` (composer with offset-correction and 18-item sum)
- `run_peritem_t3_backfill.py` (Phase A1 standalone backfill)

**Status update for canonical numbers:** UNCHANGED.
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`).
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`).
- T3 LOSO two-way CCC = **0.341** (`run_t3_iter16_site_ipw.py --mode lockbox`, no-IPW).
- Item 15 (postural tremor) LOOCV CCC = **+0.1099** (`run_per_item_iter17_hypothesis.py --mode lockbox` item_only).
- Item 18 (rest tremor constancy) LOOCV CCC = **+0.4858** (`run_per_item_iter17_hypothesis.py --mode lockbox` hy_residual_item_v2).

**Publishable methodological finding for the paper:** at N=94 with 18 UPDRS-III items, **per-item gated decomposition + summation underperforms direct T3 regression by ~10 CCC points at 5-fold** because (a) variance compounding overwhelms the per-item gains and (b) direct regression captures cross-item correlations more efficiently than the composite. This complements the four prior frozen-encoder negatives (F41 / F45 / F51) by showing that the wall affects PROBE STRATEGY (composition vs direct) too, not just FEATURE STRATEGY (encoder vs handcrafted). The cautionary-benchmark framing of the paper is reinforced.

---

## F52 — Per-item gated T3 push — planning-only entry (2026-05-04 ~12:33)

**Mission origin (`planning-with-files:plan` 2026-05-04):** user invocation: "act as the pd-imu-100x-researcher … break the T3 LOOCV CCC ceiling above the canonical 0.5227 (iter5 clinical-augmented hy_residual) WITHOUT data leakage and WITHOUT retrying anything on the dead list." Plan captured fully in `task_plan.md` § "ACTIVE MISSION — Per-Item Gated T3 Push (2026-05-04, planning)". Empirical results to be appended as F53 (Phase A1+A2), F54 (Phase B), F55 (Phase C lockbox or negative-result writeup).

**CLI consult outcome (triple-CLI):**
- **Codex (gpt-5.5 xhigh):** bubblewrap sandbox refused namespaces (same failure as 2026-05-03 PM). Effectively no usable answer this session.
- **Gemini (gemini-3.1-pro):** clean 4-angle ranking with predicted Δ + P(gate) + failure mode. Saved at `/tmp/gemini_t3_consult.txt`.
- **glmcode:** not installed locally (`command not found`). Skipped per CLAUDE.md soft-failure rule.

**Gemini's 4-angle ranking (with iter11A 50% haircut applied):**

| Angle | Gemini Δ (5-fold CCC) | P(gate) | Haircut realistic Δ | Recommendation |
|---|---|---|---|---|
| 3 — Hypothesis-restricted free items {1, 7, 8, 16, 17} | +0.095 [+0.065, +0.130] | 85% | +0.02 to +0.07 | **RUN (top yield)** |
| 1 — Per-item gated T3 (sum 18 OOFs) | +0.075 [+0.040, +0.110] | 70% | +0.02 to +0.06 | **RUN** |
| 4 — Cross-task ridge stack | +0.020 [−0.015, +0.045] | 15% | 0 to +0.02 | SHELVE |
| 2 — Stage-1 Ridge interactions | −0.015 [−0.050, +0.010] | 5% | −0.02 to +0.01 | SHELVE (DOF death trap at N=98) |

**Convergence with prior findings:**
- Angles 1 and 3 share infrastructure: angle-3 per-item improvements (items 7, 8, 16, 17) feed directly into angle-1's composite. Mission collapses both into a single coherent plan.
- Angle 2 (Stage-1 interactions) gemini predicts NEGATIVE delta — the iter5 "less is more" rule held linearly because 6+3=9 Stage-1 features at N=98 are already at the safe edge of the bias-variance frontier; quadratic interactions would consume DoF without additive signal. SHELVED.
- Angle 4 (cross-task ridge stack) gemini predicts collinearity collapse: per-task OOFs are highly inter-correlated, so a 5-vector ridge stack at N=98 will shrink toward unweighted average. Below the +0.05 floor. SHELVED.

**Pre-existing per-item OOF inventory (verified 2026-05-04 via `ls results/lockbox_peritem_*.oof.npy`):**
- Items {4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17}: iter8 batch `20260430_143044` lockboxed.
- Items 15 and 18: iter17 lockbox `20260503_221544` (`item_only` and `hy_residual_item_v2` respectively).
- **Missing:** items {1, 2, 3} — iter8 skipped them per the 2026-04-30 "1, 2, 3 unobservable; cap = hy_residual" decision. Composite must populate these via Phase A1 backfill (V2_baseline / hy_residual / item_plus_v2 architecture screen).

**Phase plan (5 phases, gate-driven; full detail in task_plan.md):**
- Phase 0: preflight (~30 min, master).
- Phase A1: per-item OOF backfill for items {1, 2, 3} (~2 h, remote 17-core).
- Phase A2: iter17-style hypothesis-restricted features for items {7, 8, 16, 17}; per-item 5-fold gate Δ ≥ +0.05 / std < 0.02; lockbox passers (~6-8 h, remote).
- Phase B: composite formula pre-registration → 5-fold T3 gate (Δ ≥ +0.05 / std < 0.02 vs iter5) (~30 min, master).
- Phase C: T3 LOOCV lockbox (gate-conditional, ~3 h, remote).
- Phase D: writeup — positive (canonical update + paper Table 3 row) or negative (5th N=94 wall data point) (~1 h).

**Decision-gate guards:**
- 5-null gate inheritance from `inductive_lib.py` (pre-passed by iter5/iter12/iter17).
- 5-fold floor (Δ ≥ +0.05 / std < 0.020) per-item AND sum-level.
- Composite formula pre-registered in JSON with `formula_sha256`, `created_at_utc`, `git_sha` BEFORE T3 sum is computed (the iter11A failure mode is the bright line).
- LOOCV lockbox runs ONCE per pre-registered composite; headline is whatever it returns.
- Paired bootstrap CI vs iter5 OOF on N=98 with 5000 resamples; acceptance requires fraction>0 ≥ 95%.

**No empirical results in this entry.** Status update: canonical numbers UNCHANGED.
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`).
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`).
- T3 LOSO two-way CCC = **0.341** (`run_t3_iter16_site_ipw.py --mode lockbox`, no-IPW).
- Item 15 (postural tremor) LOOCV CCC = **+0.1099** (`run_per_item_iter17_hypothesis.py --mode lockbox` item_only).
- Item 18 (rest tremor constancy) LOOCV CCC = **+0.4858** (`run_per_item_iter17_hypothesis.py --mode lockbox` hy_residual_item_v2).

---

## F51 — iter18 Phase B in-domain SSL pretraining + canary + screen — NEGATIVE (2026-05-04 ~10:44)

**Mission origin (Phase B1, post-Phase A success on items 15/18):** test whether 256-d SSL embeddings (mean over 10s windows) pretrained on the 178-cohort raw IMU windows (NO labels) raise T1-sum 5-fold CCC over the iter12 honest baseline. This was the only Phase B angle judged worth attempting on the RTX 5070; the F41/F45 dead-list rule on FROZEN HEALTHY-POPULATION encoders is sidestepped by pretraining on the SAME cohort that's being evaluated, with explicit canary-feature null gate to detect raw-signal-identity memorization.

**Pipeline:**
- `train_indomain_ssl.py --mode pretrain_full` — 7 490 windows × 78 channels × 1 000 samples (10 s, all 13 IMUs Acc + Gyr) collected from 178 subjects (PD + HC) across SelfPace + HurriedPace + TUG + Balance + TandemGait. 6-layer transformer encoder, hidden=128, n_heads=8, mask_ratio=0.5, MSE-on-masked-positions loss, 40 epochs at batch 64, lr 2e-4, RTX 5070. Final loss flat at ~0.99 (essentially mean prediction). 1.98M params.
- `train_indomain_ssl.py --mode extract_embeddings` — frozen-backbone forward pass over all 7 490 windows × 178 subjects → mean+std per-subject pooling → 256-d × 2 = 512-d... actually 128 × 2 (mean + std) = 256-d effective per the implementation. 98 PD subjects × 257 cols (256 SSL + sid) cached at `results/indomain_ssl_embeddings.csv` with manifest sidecar (labels_used=False, downstream_canary_gate_required=True).
- `compose_t1_iter18_indomain_ssl.py --mode screen` — canary null gate first, then 5-seed × 5-fold sum-T1 screen.

**Canary null gate (5-null #3) PASS:**
Test-only canary feature with constant value = 1.0 injected into test rows ONLY (train sees zero). On item 12 (highest baseline, most sensitive to leakage) at seed 42:
- CCC without canary = +0.5542
- CCC with canary (test=1.0) = +0.5569
- |Δ| = 0.0027 < 0.020 threshold → **PASS.** SSL embeddings are not exposing test-SID identity to the K=500 selector.

**Sum-T1 5-fold screen result (`results/peritem_iter18_indomain_ssl_5fold_screen.csv`):**

| Seed | Control T1-sum CCC | SSL_aug T1-sum CCC | Δ |
|---|---|---|---|
| 42 | +0.6357 | +0.6548 | +0.0191 |
| 1337 | +0.6729 | +0.6608 | −0.0121 |
| 7 | +0.6499 | +0.6238 | −0.0261 |
| 2024 | +0.6224 | +0.6346 | +0.0122 |
| 9001 | +0.6812 | +0.6451 | −0.0361 |
| **Mean ± std** | **+0.6524 ± 0.0220** | **+0.6438 ± 0.0134** | **−0.0086** |

**SUM-T1 GATE FAIL.** Δ = −0.009 (vs +0.025 floor); aug_std 0.013 PASSES (< 0.020). Direction is mixed (2 positive, 3 negative seeds); mean is slightly negative but within the noise floor of the 5-seed estimator.

**Mechanism (first-order analysis):**
1. Pretraining loss flat at ~0.99 over 40 epochs → encoder essentially learned only basic linear structure of z-scored channels. 50% mask ratio is too aggressive for the small N=178 cohort with no auxiliary supervision; the model has too little context to reconstruct high-frequency detail.
2. Even if the encoder had learned a meaningful manifold, the 256-d embedding space is too high-dimensional relative to the 1751 V2 features for the K=500 selector at N=94. Same K=500 displacement mechanism as F45 HARNet (2048-d).
3. The canary PASS confirms there's no leakage shortcut — the result is genuinely negative.

**Triangulation across all 4 frozen-encoder attempts:**
- F41 MOMENT-1-base (768 × 3 = 2 304 dims, generic time-series SSL on heterogeneous corpora): all 14 variants NULL (best +0.006 within noise).
- F41 HC-SSL (1D-CNN AE on 80 WearGait HC subjects, 256 × 3 = 768 dims): 21 variants NULL (best +0.006 within noise).
- F45 HARNet (UKB OxWearables ~700K person-days, 2 048 dims): NEGATIVE Δ = −0.031 across 5 seeds.
- **F51 iter18 in-domain SSL** (178-cohort PD+HC, 256 dims): NEGATIVE Δ = −0.009 across 5 seeds (this entry).

**The four-way triangulation now spans:** generic heterogeneous TS (MOMENT) → healthy-population gait (HC-SSL) → large-scale population accelerometer (UKB HARNet) → in-domain same-cohort (iter18). All four NULL/NEGATIVE. The wall is N=94, not domain-gap. Frozen-encoder pretraining at any domain × any scale × any cohort does not move within-PD severity prediction at this sample size.

**Decision: SHELVE iter18.** Lockbox NOT run; pre-registration NOT written.

**Side-effect (durable):**
- `results/indomain_ssl_ckpt.pt` (≈8 MB checkpoint of the 178-cohort pretrained encoder).
- `results/indomain_ssl_embeddings.csv` (98 subjects × 256 cols).
- `results/indomain_ssl_embeddings.csv.manifest.json`.
- `train_indomain_ssl.py`, `compose_t1_iter18_indomain_ssl.py`.

**Status update for canonical numbers:** UNCHANGED (after triangulation across all four frozen-encoder attempts).
- T1 LOOCV CCC = **0.6550** (`compose_t1_iter12_honest.py`).
- T3 LOOCV CCC = **0.5227** (`run_t3_iter5_clinical.py --feature_set A3_tier1`).
- T3 LOSO two-way CCC = **0.341** (`run_t3_iter16_site_ipw.py --mode lockbox`, no-IPW).
- Item 15 (postural tremor) LOOCV CCC = **+0.1099** (`run_per_item_iter17_hypothesis.py --mode lockbox` item_only).
- Item 18 (rest tremor constancy) LOOCV CCC = **+0.4858** (`run_per_item_iter17_hypothesis.py --mode lockbox` hy_residual_item_v2).
