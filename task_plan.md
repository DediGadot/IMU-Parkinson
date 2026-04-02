# Task Plan: CCC Explanation and Caveats

**Objective:** Answer what CCC means in this paper, using the manuscript and codebase to distinguish the conceptual role of CCC from the repository's concrete implementation and to summarize the main interpretation caveats.

**Audit date:** 2026-03-30
**Primary sources:** `eval_utils.py`, `run_compression_ablation.py`, `NEW.html`, `generate_paper.py`, `results/compression_P5_TT1_5split.json`, `results/compression_P5_TT3_5split.json`, `results/compression_P0_TT3.json`

## Audit Phases

| # | Phase | Status | Notes |
|---|-------|--------|-------|
| C1 | Confirm CCC definition in code | COMPLETE | `lins_ccc` uses Lin's concordance with population variance/covariance |
| C2 | Confirm manuscript framing of CCC | COMPLETE | Paper treats CCC as primary metric because it penalizes both correlation and calibration |
| C3 | Verify headline CCC examples against results | COMPLETE | T1 5-fold CCC=0.865, slope=0.745; T3 5-fold CCC=0.807, slope=0.581; P0 T3 CCC=0.186, slope=0.104 |
| C4 | Identify interpretation caveats | COMPLETE | Key caveats: range dependence, pooled-strata inflation risk, CCC does not replace MAE/calibration/UQ, small-N instability, target/protocol dependence |

# Task Plan: NEW.html Verification Audit

**Objective:** Verify every quantitative claim and material factual statement in `NEW.html` against repository evidence, prioritizing `results/*.json`, supporting Markdown notes, and any generated reports that document source metrics.

**Audit date:** 2026-03-27
**Primary artifact:** `NEW.html`
**Source-of-truth priority:** `results/*.json` > regenerated or script-produced markdown summaries > other repo markdown drafts/notes

## Audit Phases

| # | Phase | Status | Notes |
|---|-------|--------|-------|
| A1 | Read current planning context and repository state | COMPLETE | Existing planning files were stale relative to this task; git diff/status checked |
| A2 | Extract claims from `NEW.html` | IN PROGRESS | Need structured inventory of numbers and narrative assertions |
| A3 | Map each claim to a backing artifact | PENDING | Prefer direct JSON metrics over prose summaries |
| A4 | Verify all values and narrative statements | PENDING | Record exact matches, acceptable wording, and discrepancies |
| A5 | Deliver review findings and residual uncertainties | PENDING | Findings-first response with file references |

## Verification Rules

- Treat direct experiment JSONs in `results/` as the authoritative source when available.
- Use Markdown files only when they summarize computations not directly stored elsewhere; mark those as secondary support.
- If multiple artifacts disagree, note the conflict and identify which file appears most authoritative.
- Flag unsupported absolute statements even if the surrounding qualitative argument is reasonable.
- Keep exact wording distinctions clear: "improves", "confirms", "establishes", "largest", "first", and causal explanations require evidence, not just nearby numbers.

## Outputs Expected

- Claim inventory for `NEW.html`
- Verified matches
- Discrepancies / unsupported claims
- Unresolved items needing script reruns or source clarification

# Task Plan: Memento-Driven PD-IMU Improvement

**Objective:** Use Memento's Read → Execute → Reflect → Write loop as the primary execution engine for improving accuracy and novelty. Each research direction = a Memento skill. The agent orchestrates the experiment cycle.

**Created:** 2026-03-26
**Architecture:** Memento skills compose into an autonomous research pipeline:

```
┌──────────────────────────────────────────────────────────────┐
│                    MEMENTO AGENT (GLM-5)                     │
│                                                              │
│  READ: results/*.json, NEW.html, autoresearch_*.tsv          │
│  EXECUTE: run skills (analyze, search, configure, check)     │
│  REFLECT: compare metrics, identify gaps, rank next actions  │
│  WRITE: configs, shell commands, paper sections, new skills  │
│                                                              │
│  Skills:                                                     │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │ analyze │→│ configure│→│ evaluate │→│ paper-integrity │  │
│  └─────────┘ └──────────┘ └──────────┘ └─────────────────┘  │
│       ↑           │             │              │             │
│       └───────────┴─────────────┘              │             │
│                                                │             │
│  ┌───────────┐ ┌──────────────┐ ┌─────────────┐│            │
│  │ lit-watch │ │ obs-formalize│ │ conformal-uq││            │
│  └───────────┘ └──────────────┘ └─────────────┘│            │
└──────────────────────────────────────────────────────────────┘
         │ writes gpu commands          ↑ reads results
         ▼                              │
   ┌──────────┐    rsync + SSH    ┌──────────┐
   │ gpu.sh   │ ←───────────────→ │ GPU slave│
   └──────────┘                   └──────────┘
```

**Execution model:** Memento reads/writes files locally. GPU experiments are triggered via shell commands that Memento writes and human/cron executes through gpu.sh. Results flow back via `gpu.sh --pull`.

---

## Phase 1: Build the Memento Skill Library

Every subsequent phase runs THROUGH these skills. This is the foundation.

### Skill 1: `pd-imu-analyze` — Results Analyst

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 1.1 | Write SKILL.md: reads results/*.json, computes deltas between experiments, ranks configs by CCC/MAE/slope | PENDING | 30 min | Core loop: read → compare → report |
| 1.2 | Write scripts/analyze.py: load all JSON artifacts, compute paired bootstrap CIs, identify best/worst | PENDING | 45 min | Uses numpy, scipy, json |
| 1.3 | Write scripts/state_vector.py: extract experiment state vector {best_CCCs, worst_items, worst_tasks, subgroup_gaps, calibration, sensor_budget} | PENDING | 30 min | Codex's routing idea — skills route on state, not keywords |
| 1.4 | Test: `memento agent -m "Analyze results in /home/fiod/medical/results/ and tell me the best T1 CCC"` | PENDING | 5 min | Must correctly read JSONs and compute |

### Skill 2: `pd-imu-configure` — Experiment Configurator

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 2.1 | Write SKILL.md: reads state vector from analyze skill, modifies autoresearch_config.py with next HP config | PENDING | 30 min | Writes Python config, not just JSON |
| 2.2 | Write scripts/configure.py: parametric config generation within validated HP ranges | PENDING | 45 min | Bounds: K∈[100,800], leaf∈[5,30], reg∈[0.1,5.0] |
| 2.3 | Write scripts/gen_gpu_cmd.py: generates gpu.sh command for the configured experiment | PENDING | 20 min | Output: shell command string ready to execute |
| 2.4 | Test: `memento agent -m "Suggest a better config than K=500 leaf=8 based on current results"` | PENDING | 5 min | Must read state → reason → write config |

### Skill 3: `pd-imu-evaluate` — Post-Experiment Evaluator

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 3.1 | Write SKILL.md: reads new results after gpu.sh --pull, compares to baseline, decides ACCEPT/REJECT/ITERATE | PENDING | 30 min | Gate: bootstrap lower CI must beat incumbent |
| 3.2 | Write scripts/evaluate.py: paired bootstrap comparison, leakage checks, CCC/MAE/slope delta | PENDING | 45 min | Codex's rule: only accept if CI beats incumbent |
| 3.3 | Write scripts/log_result.py: append to autoresearch_ccc_results.tsv with full metadata | PENDING | 20 min | Append-only experiment registry |
| 3.4 | Test: run on existing P0→P5 comparison, verify it correctly identifies P5 as winner | PENDING | 5 min | Sanity check |

### Skill 4: `pd-imu-paper-check` — Manuscript Integrity

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 4.1 | Write SKILL.md: reads NEW.html, extracts all numbers (CCC, MAE, r, slope, N), cross-references against results/*.json | PENDING | 30 min | Catches stale numbers in manuscript |
| 4.2 | Write scripts/paper_check.py: parse HTML tables, extract metrics, compare to JSON source-of-truth | PENDING | 1 hr | BeautifulSoup + json |
| 4.3 | Write scripts/tripod_check.py: TRIPOD+AI compliance checklist scanner | PENDING | 45 min | Flags missing required elements |
| 4.4 | Test: run on current NEW.html, verify it catches any inconsistencies | PENDING | 5 min | |

### Skill 5: `pd-imu-literature` — Scooping Watchdog

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 5.1 | Write SKILL.md: searches PubMed/arXiv for UPDRS + IMU + wearable + regression papers since last check | PENDING | 20 min | Composes with web-search skill |
| 5.2 | Write scripts/lit_search.py: Tavily queries for key terms, dedup against known refs, flag threats | PENDING | 30 min | Uses TAVILY_API_KEY from config |
| 5.3 | Test: `memento agent -m "Check if anyone published UPDRS regression from IMU since March 2026"` | PENDING | 5 min | Should return "no new threats" |

### Skill 6: `pd-imu-obs-formalize` — Observability Framework

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 6.1 | Write SKILL.md: computes formal observability statistics from per-item results | PENDING | 30 min | Core novelty contribution |
| 6.2 | Write scripts/williams_test.py: Williams' test for ordered CCC alternatives across 3 tiers | PENDING | 1 hr | Statistical formalization |
| 6.3 | Write scripts/permutation_test.py: shuffle item↔tier (10K perms), test gradient significance | PENDING | 1 hr | Shows gradient is non-random |
| 6.4 | Write scripts/mutual_info.py: MI between each UPDRS item and IMU feature matrix | PENDING | 1 hr | sklearn.feature_selection |
| 6.5 | Write scripts/obs_index.py: formal Observability Index = f(CCC, MI, biomechanical prior) | PENDING | 1 hr | Novel metric for the field |
| 6.6 | Test: run on existing per_item_scores.json | PENDING | 5 min | |

### Skill 7: `pd-imu-conformal` — Uncertainty Quantification

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 7.1 | Write SKILL.md: computes conformal prediction intervals from LOOCV residuals | PENDING | 30 min | Distribution-free UQ |
| 7.2 | Write scripts/conformal.py: cross-conformal wrapper, coverage + width reporting | PENDING | 2 hr | 90% and 95% coverage levels |
| 7.3 | Write scripts/stratified_uq.py: intervals by H&Y stage, severity quartile | PENDING | 1 hr | Clinical utility angle |
| 7.4 | Test: run on existing P5 predictions from compression JSONs | PENDING | 5 min | |

**Deliverable:** 7 skills in `~/memento_s/skills/` that compose into an autonomous research pipeline.

---

## Phase 2: Memento Autonomous Experiment Loop

**This is where Memento drives.** The agent chains skills: analyze → configure → (human runs gpu.sh) → evaluate → iterate.

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 2.1 | Run `memento agent -m "Analyze current results and suggest 3 experiments to improve T1 CCC"` | PENDING | 10 min | Agent uses analyze + configure skills |
| 2.2 | Execute top suggestion via gpu.sh | PENDING | 30 min | Human triggers GPU; Memento wrote the command |
| 2.3 | Pull results: `gpu.sh --pull` | PENDING | 5 min | |
| 2.4 | Run `memento agent -m "Evaluate the new results and decide: accept, reject, or iterate"` | PENDING | 10 min | Agent uses evaluate skill |
| 2.5 | Repeat 2.1-2.4 for 10 iterations (batch overnight with cron) | PENDING | 5 hr | Cron: pull → memento evaluate → memento configure → gpu.sh run |
| 2.6 | Run `memento agent -m "Summarize the 10-iteration experiment trace: what worked, what didn't, what to try next"` | PENDING | 15 min | Agent reflects on its own exploration |

**Automation script for unattended loop:**
```bash
#!/bin/bash
# memento_loop.sh — autonomous experiment cycle
for i in $(seq 1 10); do
  ./gpu.sh --pull
  cd ~/memento/Memento-Skills && source .venv/bin/activate
  memento agent -m "Read results in /home/fiod/medical/results/, evaluate the latest experiment, then configure the next one. Write the gpu command to /home/fiod/medical/next_gpu_cmd.sh"
  cd /home/fiod/medical
  bash next_gpu_cmd.sh
  sleep 1800  # wait for GPU experiment
done
```

---

## Phase 3: Memento-Driven Observability Formalization

Agent runs the obs-formalize skill, which no other tool can do as coherently.

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 3.1 | Run `memento agent -m "Use the obs-formalize skill on /home/fiod/medical/results/per_item_scores.json. Compute Williams' test, permutation test, and mutual information. Write results to results/obs_formal.json"` | PENDING | 15 min | Agent orchestrates all 4 scripts |
| 3.2 | Run `memento agent -m "Compute the Observability Index for all 18 UPDRS items and write a ranked table to results/obs_index.json"` | PENDING | 10 min | Novel metric output |
| 3.3 | Run `memento agent -m "Draft a 500-word Methods subsection titled 'Formal Observability Framework' based on the results in obs_formal.json and obs_index.json. Write to paper_sections/obs_framework.md"` | PENDING | 15 min | Agent writes paper prose |
| 3.4 | Review agent output, integrate into generate_paper.py | PENDING | 1 hr | Human quality gate |

---

## Phase 4: Memento-Driven Conformal Prediction

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 4.1 | Run `memento agent -m "Use the conformal skill on P5 SSL predictions from compression_P5_TT1_5split.json. Compute 90% and 95% prediction intervals. Write to results/conformal_T1.json"` | PENDING | 10 min | |
| 4.2 | Repeat for T2 and T3 | PENDING | 10 min | |
| 4.3 | Run `memento agent -m "Analyze conformal results: coverage, median width, width by severity quartile. Draft a Results paragraph. Write to paper_sections/conformal.md"` | PENDING | 10 min | |
| 4.4 | Review and integrate | PENDING | 30 min | |

---

## Phase 5: Memento-Driven Paper Audit + Literature Watch

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 5.1 | Run `memento agent -m "Use paper-check skill on /home/fiod/medical/NEW.html. Cross-reference every number against results/*.json. List all mismatches."` | PENDING | 15 min | Automated manuscript integrity |
| 5.2 | Run `memento agent -m "Use literature skill to check PubMed and arXiv for UPDRS + IMU + wearable + regression papers from March 2026. Flag anything that scoops our work."` | PENDING | 10 min | Scooping watchdog |
| 5.3 | Run `memento agent -m "Check TRIPOD+AI compliance for NEW.html. List all missing required elements."` | PENDING | 10 min | Regulatory compliance |
| 5.4 | Fix flagged issues | PENDING | 2 hr | Human implements fixes |

---

## Phase 6: Memento-Driven Subgroup + Site Analysis

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 6.1 | Run `memento agent -m "Read WearGait-PD clinical metadata and identify site labels, DBS status, medication info, sex, H&Y stage for all 178 subjects. Write summary to results/cohort_summary.json"` | PENDING | 15 min | Agent explores metadata |
| 6.2 | Write `run_subgroup_experiments.py` based on agent's findings (site/DBS/sex/H&Y stratification) | PENDING | 2 hr | Human writes GPU script |
| 6.3 | Run on GPU, pull results | PENDING | 1 hr | |
| 6.4 | Run `memento agent -m "Evaluate subgroup results. Which subgroups show significant performance differences? Draft a supplementary table. Write to paper_sections/subgroups.md"` | PENDING | 15 min | Agent analyzes + writes |

---

## Phase 7: Memento-Driven FM Landscape Positioning

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 7.1 | Run `memento agent -m "Search the web for RelCon Apple ICLR 2025, UniMTS NeurIPS 2024, LIMU-BERT-X MobiCom 2025, FM-FoG 2025, SensorLM NeurIPS 2025, LSM Google ICLR 2025. For each: method, dataset size, key result, public weights availability. Write comparison table to paper_sections/fm_landscape.md"` | PENDING | 15 min | Agent does the lit review |
| 7.2 | Run `memento agent -m "Draft a 400-word Related Work section positioning our transductive ranking against RelCon's contrastive pretraining. Emphasize: our method works with N=178, theirs needs 87K. Write to paper_sections/related_work.md"` | PENDING | 10 min | Agent writes prose |
| 7.3 | Review, refine, integrate into paper | PENDING | 1 hr | |

---

## Phase 8: HIGH-NOVELTY — Multi-FM Ensemble (Memento discovers, human implements)

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 8.1 | Run `memento agent -m "Search for UniMTS and LIMU-BERT-X GitHub repos. Find: input format requirements (sample rate, channels, window size), installation instructions, embedding extraction API. Write setup guide to results/fm_setup_guide.md"` | PENDING | 15 min | Agent researches |
| 8.2 | Implement FM embedding extraction scripts on GPU slave | PENDING | 4 hr | Human codes based on agent's guide |
| 8.3 | Run SSL ranking with each FM alone and in combination | PENDING | 2 hr | On GPU |
| 8.4 | Run `memento agent -m "Analyze multi-FM results in results/. Compare MOMENT-only vs MOMENT+UniMTS vs triple-FM. Is the improvement significant (paired bootstrap)? Write analysis to results/multi_fm_analysis.json"` | PENDING | 10 min | Agent evaluates |
| 8.5 | Memento autonomous HP sweep on best FM combo (Phase 2 loop) | PENDING | 3 hr | Agent-driven |

---

## Phase 9: HIGH-NOVELTY BETS (Memento explores feasibility, human implements)

These are Codex's 9/10 and 8.5/10 novelty directions. Memento scouts, human builds.

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 9.1 | Run `memento agent -m "Search for CORN ordinal regression PyTorch, graded-response IRT neural networks, observability-constrained models. Find implementations, papers, code repos. Write feasibility report to results/mirt_feasibility.md"` | PENDING | 15 min | MIRT scouting |
| 9.2 | Run `memento agent -m "Read WearGait-PD data format docs. How are walkway metrics structured? How are GeneralEvent annotations formatted? Can we parse them with pandas? Write data exploration report to results/privileged_data_report.md"` | PENDING | 15 min | Privileged SSL scouting |
| 9.3 | Based on feasibility reports, decide: implement MIRT, Privileged SSL, or both | PENDING | — | Human decision gate |
| 9.4 | Implement chosen direction(s) on GPU | PENDING | 8-16 hr | Human codes |
| 9.5 | Run `memento agent -m "Evaluate MIRT/SSL results against baseline. Write comparison to results/novelty_eval.json"` | PENDING | 10 min | Agent evaluates |

---

## Phase 10: Memento Paper Assembly

| # | Task | Status | Est. | Notes |
|---|------|--------|------|-------|
| 10.1 | Run `memento agent -m "Read all files in paper_sections/. Assemble a coherent paper outline showing where each section fits. Write to paper_sections/outline.md"` | PENDING | 10 min | |
| 10.2 | Run `memento agent -m "Final paper-check: read NEW.html against all results/*.json. Verify EVERY number. Write discrepancy report to results/final_audit.json"` | PENDING | 15 min | |
| 10.3 | Run `memento agent -m "Final literature check: any new UPDRS+IMU papers in the last week?"` | PENDING | 5 min | Last-minute scooping check |
| 10.4 | Human assembles final paper from all sections | PENDING | 4 hr | |
| 10.5 | 3 rounds of Memento peer review: `memento agent -m "Act as a Nature Digital Medicine reviewer. Read NEW.html. Score it 1-10 on: novelty, rigor, clinical impact, presentation. List top 5 weaknesses."` | PENDING | 30 min | Agent simulates reviewers |

---

## Priority Order

| Priority | Phase | What | Memento Role |
|----------|-------|------|-------------|
| **1** | Phase 1 | Build 7 Memento skills | Foundation — everything depends on this |
| **2** | Phase 3 | Observability formalization | Agent runs statistical tests via obs-formalize skill |
| **3** | Phase 4 | Conformal prediction | Agent computes intervals via conformal skill |
| **4** | Phase 5 | Paper audit + literature watch | Agent checks manuscript + monitors arXiv |
| **5** | Phase 7 | FM landscape positioning | Agent does lit review + writes Related Work |
| **6** | Phase 6 | Subgroup + site analysis | Agent explores metadata, analyzes results |
| **7** | Phase 2 | Autonomous experiment loop | Agent drives HP optimization overnight |
| **8** | Phase 8 | Multi-FM ensemble | Agent scouts, human implements |
| **9** | Phase 9 | MIRT / Privileged SSL | Agent scouts feasibility, human implements |
| **10** | Phase 10 | Paper assembly + review | Agent audits, reviews, assembles |

## How Memento Is Used in EVERY Phase

| Phase | Memento Action | Skill(s) Used |
|-------|---------------|---------------|
| 1 | Creates its own skill library | skill-creator (meta-skill) |
| 2 | Drives experiment cycle: analyze → configure → evaluate → iterate | analyze, configure, evaluate |
| 3 | Runs statistical formalization scripts | obs-formalize |
| 4 | Computes prediction intervals | conformal |
| 5 | Audits manuscript + monitors literature | paper-check, literature |
| 6 | Explores metadata, analyzes subgroup results | analyze, filesystem |
| 7 | Does literature review, writes paper sections | literature, web-search, filesystem |
| 8 | Scouts FM repos, evaluates results | web-search, analyze, evaluate |
| 9 | Scouts feasibility, evaluates results | web-search, analyze |
| 10 | Assembles paper, runs peer review simulation | paper-check, filesystem |

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-26 | Memento is execution backbone, not peripheral | User explicitly asked for Memento-driven improvement |
| 2026-03-26 | 7 custom skills before any experiments | Skills compose; without them, Memento is just a chatbot |
| 2026-03-26 | GPU bridge via file-based commands, not SSH skill | Memento can't SSH; writing commands to files + human/cron execution is reliable |
| 2026-03-26 | Observability formalization before accuracy | Novelty matters more than incremental CCC for Nature |
| 2026-03-26 | Agent scouts high-risk directions, human implements | Memento's web-search + filesystem skills reduce scouting time 10x; human judgment gates risky implementations |

## Risks

| Risk | Mitigation |
|------|-----------|
| Memento skills fail on complex analysis | Test each skill individually before composing; fallback to manual |
| GLM-5 quality insufficient for paper prose | Human review gate on all agent-written sections |
| Autonomous loop overfits | Evaluate skill enforces bootstrap CI gate |
| GPU bridge too slow (file-based) | Batch experiments; overnight autonomous runs |
| Skill-creator produces poor skills | Iterate with eval-viewer; Memento's own reflection loop |
