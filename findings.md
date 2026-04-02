# Findings — CCC Explanation and Caveats

**Audit date:** 2026-03-30
**Scope:** What CCC means in the current manuscript and repository, plus the main interpretation caveats.

## Verification Log

- The canonical code definition is `lins_ccc` in [eval_utils.py](/home/fiod/medical/eval_utils.py):14. It computes Lin's concordance correlation coefficient as `2 * cov / (var_true + var_pred + (mean_true - mean_pred)^2)`, after filtering non-finite values and returning `0.0` for degenerate inputs.
- The paper explicitly makes CCC the primary metric because it is intended to penalize both discrimination failure and calibration failure in small-N regression with prediction compression; see [NEW.html](/home/fiod/medical/NEW.html) and the generated methods text in [generate_paper.py](/home/fiod/medical/generate_paper.py):2281.
- Reported experiment JSONs confirm the manuscript's use of CCC together with slope rather than alone:
  - `results/compression_P5_TT1_5split.json`: CCC=0.865, MAE=0.953, r=0.877, slope=0.745, N=95.
  - `results/compression_P5_TT3_5split.json`: CCC=0.807, MAE=4.464, r=0.877, slope=0.581, N=95.
  - `results/compression_P0_TT3.json`: CCC=0.186, MAE=8.086, r=0.297, slope=0.104, N=95.
- Implementation detail: the reported CV CCC is computed on pooled out-of-fold predictions, not as the arithmetic mean of per-fold CCCs; see [run_compression_ablation.py](/home/fiod/medical/run_compression_ablation.py):1146 and [run_compression_ablation.py](/home/fiod/medical/run_compression_ablation.py):1153.
- The paper itself encodes an important caveat: a seemingly strong CCC can still coexist with notable compression. Example: T3 5-fold CCC=0.807 but calibration slope is only 0.581; T1 5-fold CCC=0.865 but slope is still 0.745.
- Another concrete caveat from the manuscript tables: pooled CCC can overstate usefulness within narrow severity strata. In [NEW.html](/home/fiod/medical/NEW.html), Table 3 gives baseline LOOCV T3 CCC=0.369, while Table 4 shows quartile-specific CCCs only 0.141, 0.068, 0.152, and 0.138, with strong regression-to-the-mean bias.
- The manuscript's broader argument is therefore consistent with using CCC as a primary agreement metric, but not as a sufficient standalone metric. The code and paper both rely on MAE, Pearson r, calibration slope, BCa CIs, Bland-Altman bias, and conformal intervals to contextualize CCC.

# Findings — NEW.html Verification Audit

**Audit date:** 2026-03-27
**Scope:** Quantitative claims and material factual statements in `NEW.html`

## Verification Log

- Repository contains an already-edited `NEW.html` plus multiple modified planning/report files; prior session catchup indicates earlier discrepancy-fixing work that may not be fully reflected in current docs.
- `results/*.json` appears to hold the main experiment outputs needed for manuscript verification, but some claims may rely on generated Markdown summaries or prior review reports.
- The audit will treat JSON metrics as primary evidence and prose summaries as secondary unless no machine-readable artifact exists.
- The existing `review_report_numbers.md` audit is stale for the current manuscript. At minimum, the observability section has been rewritten: current `NEW.html` uses the primary T1 pipeline values (`CCC=0.865`, `MAE=0.953`, `N=95`) for the direct tier, whereas the older audit expected restricted-subset values from `results/reviewer_obs_5fold.json` (`CCC=0.834`, `MAE=1.100`, `N=90`).
- Current Table 2 mixes sources: direct tier matches `results/compression_P5_TT1_5split.json` / `results/compression_P0_TT1.json`, while partial and not-observable tiers match `results/reviewer_obs_5fold.json`. This is acceptable only if the surrounding note explicitly discloses the different sample counts and protocols.
- Recomputed the paper-generator BCa confidence interval for the headline T1 CCC directly from `results/compression_P5_TT1_5split.json` per-subject predictions. The stored manuscript value `95% BCa CI [0.795, 0.914]` is reproducible (`0.7954365, 0.9138043` before rounding).
- Core internal quantitative claims appear numerically consistent with repository artifacts: T1/T2/T3 primary results, demographics, age sensitivity, HC ablation, conformal/Bland-Altman values, subgroup tables, FM ablation summary, single-sensor results, and supplementary ablation tables.
- Real remaining issues are integrity/interpretation issues:
  - Cross-dataset section mixes 5-fold and LOOCV metrics. `NEW.html` text uses `T3 MAE=4.46, N=95, 5-fold` while Table 8 uses `T3 MAE=4.65, N=94, LOOCV`; Figure 7 caption also says `N=95` despite Table 8 being LOOCV-based.
  - The stored Williams test in `results/obs_formal_and_conformal.json` is defined on the ordered alternative `direct >= partial >= not`, but the manuscript repeatedly claims significance for the observed ordering `direct > not > partial`. The permutation test supports a non-random gradient; the Williams-test wording overstates what is directly supported.
  - No JSON or markdown artifact in the repository documents the claimed fold-restricted-ranking ablation. The statement appears in `NEW.html`, `generate_paper.py`, and review prose, but no result file backing it was found.

# Findings — PD-IMU 10x Improvement Plan

**Research Date:** 2026-03-26
**Sources:** Web search (63 queries), Codex CLI (GPT-5.4 xhigh), paper analysis, codebase audit

---

## F1: Competitive Landscape — No UPDRS-III Regression Threat (2026-03-26)

**No one has published UPDRS-III regression on WearGait-PD.** Our work remains the first. The only WearGait-PD publication is TRIP (arXiv 2025) — classification only (80.07% IMU accuracy).

Cross-dataset SOTA unchanged:
- Hssayeni 2021: MAE=5.95, N=24 PD, LOOCV, wrist+ankle gyro
- Shuqair 2024: r=0.89, MAE~5.65, N=24 PD, LOOCV, same dataset as Hssayeni

**Key validation:** Mostafavi 2025 (Sensors) tried UPDRS regression from foot pressure insoles on N=163: **R2 < 0.2**. Independent confirmation that UPDRS-III total regression from gait sensors is intrinsically hard.

---

## F2: 2025-2026 Foundation Model Explosion for IMU (2026-03-26)

| Model | Source | Year | Scale | Innovation | Public Weights? |
|-------|--------|------|-------|------------|-----------------|
| **RelCon** | Apple/UIUC, ICLR 2025 | 2025 | 87K subjects, ~1B segments | Relative contrastive ranking on gait | **NO** (Apple proprietary) |
| **LSM** | Google, ICLR 2025 | 2025 | 165K subj, 40M hours | Masked autoencoder at massive scale | **NO** (Google internal) |
| **UniMTS** | UCSD, NeurIPS 2024 | 2024 | Synth from HumanML3D | Text-aligned contrastive; 340% zero-shot | **YES** |
| **SensorLM** | Google, NeurIPS 2025 | 2025 | 103K people, 59.7M hours | CLIP-style sensor-language alignment | **NO** (Google internal) |
| **FM-FoG** | W&M, 2025 | 2025 | 175 PD subjects, 5 datasets | Domain-specific PD FM; beats MOMENT (F1 98.5 vs 85.9) | **YES** |
| **NormWear** | arXiv 2024 | 2024 | 2.5M segments, 14.9K hours | Cross-modality + text alignment | **YES** |
| **LIMU-BERT-X** | MobiCom 2025 | 2025 | 60K subjects, 1.43M hours | Scaled LIMU-BERT for mobile | **YES** |

**Critical insight:** RelCon (Apple, ICLR 2025) is our closest methodological parallel — it uses **relative contrastive ranking** from accelerometer data. However:
- RelCon trains on 87K healthy subjects → our method uses 80 HC as calibration anchors on the target dataset
- RelCon does self-supervised pretraining → our method does transductive ranking with ordinal labels
- RelCon targets gait metrics (stride velocity) → we target clinical UPDRS scores
- Weights NOT public → cannot benchmark directly

**Actionable FMs (public weights):** UniMTS, FM-FoG, NormWear, LIMU-BERT-X

---

## F3: SSL for PD-Specific IMU — We Are Novel (2026-03-26)

- **LIFT-PD** (Soumma 2024): SSL for FoG detection, +7.25% precision with 40% fewer labels
- **FM-FoG** (Chi 2025): Domain-specific FM for FoG, beats MOMENT by 13% F1
- **No SSL method has been applied to UPDRS-III regression from IMU** — our approach is genuinely novel
- Our "transductive ranking with HC calibration anchors" has no published precedent

---

## F4: Paper Weaknesses Identified (2026-03-26)

### Accuracy gaps
- T3 total CCC=0.776 (LOOCV) / 0.807 (5-fold) — good but slope=0.576-0.581 means 42% compression remains
- No uncertainty quantification — point estimates only, no prediction intervals
- Single FM (MOMENT) tested — reviewers will ask about 2025 FMs

### Novelty gaps
- No comparison/positioning against 2025 foundation models (RelCon, LSM, UniMTS, SensorLM)
- Observability gradient lacks formal statistical test (Williams' test, permutation)
- No "Observability Index" — the gradient is descriptive, not a reusable metric
- No per-item analysis (only 3-tier aggregation)

### Missing analyses
- DBS subgroup (N=23 DBS vs N=75 non-DBS) — mentioned as limitation, never analyzed
- No medication ON/OFF analysis
- No sex-stratified results
- No TRIPOD+AI compliance checklist
- No patient flow diagram

### Framing issues
- Title says "ordinal ranking" but the deeper insight is observability — title may undersell
- Discussion §3.6 on "compression problem" is strong but not formalized mathematically
- No conformal/calibration intervals despite clinical deployment narrative

---

## F5: Memento Integration Opportunities (2026-03-26)

### What Memento enables
1. **Autonomous HP search** — Read results → modify config → run via gpu.sh → evaluate → iterate
2. **Skill creation for experiment pipelines** — Package feature extraction, training, evaluation as reusable skills
3. **Multi-model analysis** — GLM-5 analyzes traces and suggests non-obvious configurations
4. **Literature monitoring** — Web-search skill tracks arXiv/PubMed for scooping threats
5. **Paper consistency checking** — Filesystem skill reads NEW.html + result JSONs, flags mismatches

### What Memento CANNOT do (directly)
- Cannot SSH into GPU slave (no SSH skill) — needs wrapper via gpu.sh
- Cannot create new model architectures — can only compose existing code
- Cannot replace domain expertise for clinical interpretation

### Skill architecture
```
~/memento_s/skills/
├── pd-imu-analyze/        # Read results, compute deltas, identify best configs
│   ├── SKILL.md
│   └── scripts/analyze.py
├── pd-imu-hp-search/      # Modify autoresearch_config.py, trigger eval
│   ├── SKILL.md
│   └── scripts/hp_search.py
├── pd-imu-paper-check/    # Verify manuscript numbers against JSON artifacts
│   ├── SKILL.md
│   └── scripts/paper_check.py
└── pd-imu-literature/     # Search for new papers, flag threats
    ├── SKILL.md
    └── scripts/lit_search.py
```

---

## F6: High-Impact Improvement Directions (2026-03-26)

### Direction 1: Multi-FM Ensemble
- **What:** Replace MOMENT-only with ensemble of MOMENT + UniMTS + LIMU-BERT-X (+ FM-FoG if compatible)
- **Expected gain:** +0.02-0.05 CCC on T3 (FM-FoG shows MOMENT is suboptimal for PD)
- **Complexity:** MODERATE — need to adapt input formats (100Hz 6-axis → FM expectations)
- **Risk:** MODERATE — FMs may extract redundant features; feature selection should handle noise
- **Novelty:** HIGH — first multi-FM ensemble for clinical IMU regression

### Direction 2: Conformal Prediction / UQ
- **What:** Distribution-free prediction intervals via cross-conformal prediction
- **Expected gain:** No accuracy gain; MASSIVE reviewer value + clinical utility
- **Complexity:** LOW — well-established method, ~200 lines of code
- **Risk:** LOW — cannot fail, only adds information
- **Novelty:** HIGH — first conformal prediction for UPDRS regression

### Direction 3: Formal Observability Framework
- **What:** Williams' test + permutation test + mutual information + per-item CCC + "Observability Index"
- **Expected gain:** No accuracy gain; transforms qualitative observation into reusable framework
- **Complexity:** LOW-MODERATE — statistical tests are standard
- **Risk:** LOW — worst case, tests confirm what we already show descriptively
- **Novelty:** VERY HIGH — no one has formalized modality-target observability for clinical scores

### Direction 4: DBS + Subgroup Analysis
- **What:** Stratify by DBS (N=23 vs 75), H&Y stage, sex, medication
- **Expected gain:** Fills reviewer gaps, no accuracy improvement
- **Complexity:** LOW — run existing pipeline on subgroups
- **Risk:** LOW — DBS subgroup may be too small for significance
- **Novelty:** MODERATE — DBS-specific gait IMU analysis is underexplored

### Direction 5: RelCon/FM Landscape Positioning
- **What:** Add Related Work on 2025 FMs; explicit comparison table vs RelCon
- **Expected gain:** Paper-only — preempts reviewer "why not use X?" questions
- **Complexity:** LOW — writing only, no experiments
- **Risk:** NONE
- **Novelty:** Shows field awareness; differentiates our transductive approach

### Direction 6: Memento Autonomous Loop
- **What:** Create skills → run overnight autonomous experiment optimization
- **Expected gain:** +0.01-0.03 CCC from discovered configurations
- **Complexity:** MODERATE — need GPU bridge skill
- **Risk:** MODERATE — overfitting to autoresearch metric possible
- **Novelty:** MODERATE — "AI-driven experiment optimization" is trendy for Nature Digital Med

### Direction 7: Domain-Adapted FM Fine-Tuning (REJECTED)
- **What:** Fine-tune MOMENT or LIMU-BERT on WearGait-PD unlabeled HC data
- **Expected gain:** +0.03-0.08 CCC (based on FM-FoG results)
- **Risk:** HIGH — N=178 too small for meaningful fine-tuning
- **Decision:** REJECTED — overfitting risk exceeds expected gain

---

## F8: Codex GPT-5.4 Research (xhigh reasoning, 173K tokens) — 2026-03-26

### Core insight from Codex
> "Your moat is not 'better boosting.' It is the combination of 13 IMUs + synchronized insoles/walkway/video + three sites + medication metadata + observability structure in WearGait-PD. If you do not exploit those privileged signals, you are leaving the strongest paper on the table."

### 5 Novel Directions (Codex, rated for Nature Digital Med)

**Direction C1: Observability-Constrained Neural MIRT (9/10 novelty)**
- IMU encoder → latent factors (z_gait, z_turn, z_balance, z_global)
- Direct items get CORN ordinal heads; partial items use sparse monotone heads conditioned on direct logits
- Unobservable burden = separate heteroscedastic residual head
- Loss: `L_ordinal + λ1(1-CCC_obs) + λ2 NLL_total + λ3 KL + λ4 monotonicity`
- Expected: +0.02-0.05 CCC total, +0.00-0.02 CCC observable
- **Formalizes observability INTO the model, not post-hoc**

**Direction C2: Cross-Modal Privileged SSL (8.5/10 novelty)**
- Pretrain IMU encoder with: masked reconstruction (MaskCAE), temporal contrast (TS2Vec/CPC), IMU↔walkway/insole InfoNCE, gait-phase event prediction
- WearGait-PD has walkway, insoles, GeneralEvent annotations — ALL UNUSED
- Expected: +0.02-0.04 CCC observable, +0.01-0.03 CCC total
- **No major IMU severity paper uses privileged multimodal teacher signals**

**Direction C3: Event-Aware Body-Graph MIL (8/10 novelty)**
- Segment into event bags (walk/turn-L/turn-R/sit2stand/stand2sit/balance)
- ST-GCN or Graphormer over 13-IMU body graph with bilateral symmetry edges
- Gated attention or differentiable top-k MIL aggregation
- Expected: +0.01-0.03 CCC observable
- **Turns and transitions disproportionately informative for UPDRS**

**Direction C4: Domain-Generalized MoE for Site + Medication (8/10 novelty)**
- Task-family experts with shared encoder
- Adversarial heads for site/DBS/time-since-last-dose via gradient reversal + CORAL/IRM
- Heteroscedastic Gaussian NLL output
- Expected: +0.00-0.02 internal, but leave-site-out robustness +0.03-0.08
- **Reviewers will care more about leave-site-out than another 0.01 CCC**

**Direction C5: Privileged Teacher → Sparse Student Distillation (8.5/10 novelty)**
- Teacher on 13 IMUs + walkway/insoles → distill to 2-3 IMU student
- Loss: KL(item distributions) + hidden-state matching + sensor-budget penalty
- Target: retain 95-98% teacher CCC with lumbar + both wrists
- **Translational bridge to clinically deployable system**

### Additional References from Codex
- Rehman 2021: single-lower-back CNN, r=0.82, ICC=0.76, MAE=6.29 (longitudinal)
- Tian 2025: continuous-score, prior-aware modeling (new direction)
- WATCH-PD 2023/2024: smartwatch/smartphone deployment (Nature npj PD)
- Evers 2019: UPDRS label noise — gait items are MOST reliable
- Youssef 2026: IMU meta-analysis confirms gait strongest for progression
- TRIPOD+AI (BMJ 2024) and PROBAST+AI (BMJ 2025) — REQUIRED compliance checklists

### Critical Reviewer Risks (Codex assessment)
1. **Leave-site-out validation is MISSING** — WearGait-PD is multi-site; reviewers will demand it
2. **Medication sensitivity is MISSING** — not collected in fixed ON/OFF state
3. **No uncertainty/prediction intervals** — "model uncertainty, not hide it"
4. **Device burden criticism** — 13 IMUs vs smartwatch trend; need sparse-student story
5. **Clinical utility beyond score fit** — need worsening detection, decision impact analysis
6. **TRIPOD+AI and PROBAST+AI compliance** — now required for Nature Digital Medicine

### Codex's Recommended Sequence
> Privileged SSL → Graph MIL → Observability-constrained MIRT → leave-site-out + sparse-student distillation + clinical coverage analysis

### Memento Integration (Codex's sharper framing)
- One skill per experiment family: `obs_mirt`, `priv_ssl`, `graph_mil_turn`, `domain_gen`, `distill_sparse`, `reviewer_audit`
- Route on **experiment state vector**, not keywords: `{best CCCs, worst items, worst tasks, subgroup gaps, calibration, sensor budget, train hours}`
- Multi-objective reward: `R = 5ΔCCC_total + 3ΔCCC_obs + 2ΔCCC_leave_site - 2*cal_penalty - 1*compute_penalty - 5*leakage_flag`
- Only write back skill if bootstrap lower CI beats incumbent AND audit skill passes
- Auto-generate new skills from failure modes (e.g., `high_PIGD_turn_underprediction_skill`)
- Reviewer skill enforces TRIPOD+AI/PROBAST+AI before accepting "paper-grade" results

---

## F7: Key References for Paper Update (2026-03-26)

| Paper | Use in our paper |
|-------|-----------------|
| RelCon (Apple, ICLR 2025) | Position as methodological parallel; differentiate transductive vs contrastive |
| FM-FoG (Chi 2025) | Domain-specific FM beats general FM; supports multi-FM approach |
| Mostafavi 2025 (Sensors) | R2<0.2 for UPDRS from gait — confirms difficulty of our task |
| Portabiles (Sci Rep 2025) | N=339 longitudinal gait; validates digital gait endpoints |
| UniMTS (NeurIPS 2024) | Public FM we can benchmark against |
| LIMU-BERT-X (MobiCom 2025) | Public FM we can benchmark against |
| Gait meta-analysis (P&RD 2025) | 93 studies on wearable gait vs PD severity; context |
| FoG-STAR (Sci Data 2026) | Complementary PD dataset |

---

## Historical Findings (preserved from prior sessions)

### CCC Definition (2026-03-26, prior session)
- Canonical implementation: `lins_ccc()` in eval_utils.py
- Formula: `2 * cov / (var_true + var_pred + (mean_true - mean_pred)^2)`
- Paper uses CCC specifically to detect prediction compression

### Verified Headline Values
- T1 SSL 5-fold: CCC=0.865, MAE=0.953, slope=0.745
- T1 SSL LOOCV: CCC=0.868, MAE=0.986, slope=0.689
- T3 SSL 5-fold: CCC=0.807, MAE=4.464, slope=0.581
- T3 SSL LOOCV: CCC=0.776, MAE=4.646, slope=0.576

### Codebase State
- 129 tests pass, 4 skipped
- Clean shared core: project_paths.py, data_split.py, updrs_columns.py, eval_utils.py
- Many large standalone run_*.py scripts (800-1800 lines)
- generate_paper.py monolith (~3900 lines)
- TOKEN.md contains raw Synapse token (security issue)
- Multiple overlapping planning docs (NEXTNEXT.md, PROPOSALS.md, CODEX-PROPOSALS.md)

### Reviewer Response Results (2026-03-24)
- Age sensitivity: age NOT driving results (partial r=0.849 controlling age)
- HC ablation: ranking itself helps, HC adds marginal calibration (T1 CCC 0.857 vs 0.858)
- Obs 5-fold: gradient confirmed (direct 0.834, partial 0.730, unobs 0.759)
- Single sensor: single wrist CCC>0.78, lower back CCC=0.867
