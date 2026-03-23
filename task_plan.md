## Active Session: Figure Generation Review for Nature Digital Medicine (2026-03-15)

**Objective:** Review the matplotlib figure-generation functions in `generate_paper.py` for Figures 1-10 and Appendix Figures A-F, assess publication quality against the requested criteria, and write a patch-oriented review to `.paper_build/external_codex_visual.md`.

### Review Scope

- Read only the matplotlib figure-generation code paths in `generate_paper.py`
- Evaluate each figure on chart choice, color safety, print-size text readability, labeling clarity, and requested figure-specific criteria
- Prioritize the 5 highest-impact visual improvements for a Nature Digital Medicine submission
- Provide explicit matplotlib code patches rather than general advice
- Write the review to `.paper_build/external_codex_visual.md`

### Phases

| # | Phase | Status | Notes |
|---|-------|--------|-------|
| G0 | Recover planning context and locate figure functions | DONE | Read planning skill, existing planning files, and mapped all figure functions in `generate_paper.py` |
| G1 | Inspect figure-generation code and supporting style config | DONE | Reviewed shared style, all main figures, and all appendix figures; also checked rendered output from `NEW.html` |
| G2 | Score each figure against requested review criteria | DONE | Completed per-figure assessment for Figs 1-10 and Appendix A-F |
| G3 | Draft 5 highest-impact code patches | DONE | Wrote concrete patch-ready snippets covering global style, Figs 2-3, 4, 6, and 7 |
| G4 | Write `.paper_build/external_codex_visual.md` | DONE | Deliverable written to requested path |
| G5 | Final verification and planning-file update | DONE | Re-read the deliverable and recorded the main findings in planning files |

### Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| No actionable output from `session-catchup.py` | 1 | Proceeded by reading existing planning files directly |

---

## Active Session: Nature Medicine Writing Review (2026-03-15)

**Objective:** Review `.paper_build/paper_text.txt` for Nature Digital Medicine fit, focusing on writing quality, narrative logic, abstract self-sufficiency, discussion depth, CCC-versus-MAE framing, and the 10 highest-impact sentence rewrites. Deliver the review to `.paper_build/external_codex_writing.md`.

### Review Scope

- Evaluate whether tone and claim language match a high-impact clinical methods paper
- Check whether the paper cleanly integrates the SSL-ranking advance with the observability-ceiling insight
- Assess whether the abstract stands alone for readers who only see the abstract
- Judge whether the discussion explains mechanism rather than merely restating results
- Review whether CCC is motivated as an agreement/calibration metric more convincingly than MAE alone
- Propose 10 sentence-level rewrites with the highest likely editorial payoff

### Phases

| # | Phase | Status | Notes |
|---|-------|--------|-------|
| W0 | Recover planning context and manuscript text | DONE | Planning files existed; reviewed skill instructions and extracted paper text |
| W1 | Read target sections and identify editorial risks | DONE | Abstract, introduction, results, and discussion reviewed with emphasis on claims and flow |
| W2 | Synthesize critique by requested evaluation axes | DONE | Completed assessments for tone, flow, abstract, discussion depth, and CCC framing |
| W3 | Draft `.paper_build/external_codex_writing.md` | DONE | Review written with 10 prioritized sentence rewrites |
| W4 | Final verification and planning-file update | DONE | Verified output and logged completion in planning files |

### Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| No actionable output from `session-catchup.py` | 1 | Proceeded by reading existing planning files directly |

---

## Active Session: NEW.html Verification Audit (2026-03-15)

**Objective:** Verify `NEW.html` against all available result artifacts in the repository for numerical correctness, internal coherence, and consistency with the implemented evaluation workflow.

### Verification Scope

- Inventory authoritative result files under `results/` and any truth/synthesis files used to assemble the manuscript
- Cross-check all headline metrics, tables, and ablation summaries referenced in `NEW.html`
- Inspect narrative claims for consistency with evaluation mode (5-split vs LOOCV), dataset sizes, and model descriptions
- Patch `NEW.html` if clear factual inconsistencies are found and can be resolved from local evidence
- Produce a concise verification report with findings and residual risks

### Phases

| # | Phase | Status | Notes |
|---|-------|--------|-------|
| V0 | Recover prior context and planning state | DONE | Session catchup reported unsynced paper-edit context from prior session |
| V1 | Inventory result artifacts and source-of-truth files | DONE | Authoritative sources identified: `pd_only_*`, `compression_*`, `dl_experiment_results_v1.json`, `pd_only_phase6.json` |
| V2 | Cross-check `NEW.html` numeric claims | DONE | Core tables/claims checked against `pd_only_*`, `compression_*`, `dl_experiment_results_v1.json`, `pd_only_phase6.json` |
| V3 | Cross-check `NEW.html` narrative/method claims | DONE | Mixed eval-mode table, unsupported SSL split claim, and endpoint overreach identified |
| V4 | Apply corrections if needed | DONE | `NEW.html` patched with evidence-backed wording/table fixes |
| V5 | Final report and residual-risk summary | DONE | Verified manuscript fixes summarized; residual caveats logged |
| V6 | Encode audit guardrails in `update-paper` slash command | DONE | Update path now prefers `NEW.html`, enforces provenance/protocol checks, and avoids the specific coherence failures found in `NEW.html` |

### Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| `python: command not found` while inspecting result JSONs | 1 | Use `python3` explicitly for local result extraction |
| `TypeError: string indices must be integers` while probing `results/pd_only_phase6.json` | 1 | Re-read file structure; `configs` is a dict keyed by sensor configuration |

---

## Previous Active Session: Compression Ablation — 5 Proposals × 3 Targets (2026-03-14)

**Objective:** Implement and evaluate 5 anti-compression proposals across 3 prediction targets in ablation study style. Break the cal_slope=0.40 ceiling.

**Server:** `ssh -p 37397 root@142.170.89.112` — RTX 3070 8GB, 9 CPU, 49GB RAM
**Evaluation:** PD-only LOOCV (gold standard) + 5-split (fast exploration)
**Baseline per target (from prior sessions):**

| Target | Items | Range (actual) | N (PD) | Best CCC | Best slope |
|--------|-------|---------------|--------|----------|------------|
| T1: Direct observable | 3.9-3.14 (6 items) | 0-14 | 96 | 0.591 | 0.40 |
| T2: Broad observable | 3.7-3.14 (8 items, L/R summed) | 0-37 | ~96 | 0.56* | 0.40* |
| T3: Total UPDRS-III | 3.1-3.18 (all items) | 0-59 | 98 | 0.37 | 0.26 |

*Estimated from prior experiments

### 5 Proposals

| # | Proposal | Mechanism | P(success) |
|---|----------|-----------|------------|
| P1 | Per-item ordinal + temperature | Classify each item 0-4, sum expected values | 70% |
| P2 | Pairwise contrastive boosting | Predict severity differences, reconstruct from anchors | 55% |
| P3 | SMOGN tail augmentation | Synthesize severe patients in feature space | 45% |
| P4 | NGBoost distributional | Poisson distribution, CCC-tuned percentile extraction | 40% |
| P5 | Semi-supervised ranking from HC | HC as severity anchors, ranking features | 30% |

### Implementation Plan

Single script: `run_compression_ablation.py`
- `--phase 1` through `--phase 5` for each proposal
- `--target t1|t2|t3|all` for target selection
- `--eval loocv|5split` for evaluation mode (5split for exploration, loocv for validation)
- Each phase × target produces a result JSON in `results/compression_P{N}_T{M}.json`

### Phases

| # | Phase | Status | CPU/GPU | Est. Time | Dependencies |
|---|-------|--------|---------|-----------|--------------|
| S0 | Write `run_compression_ablation.py` | TODO | local | 30 min | — |
| S1 | Cache per-item scores for all 3 targets | TODO | remote | 2 min | S0 |
| S2 | Install ngboost on server | TODO | remote | 1 min | — |
| P1 | Per-item ordinal × 3 targets (5-split) | TODO | CPU | ~5 min/target | S0, S1 |
| P2 | Pairwise contrastive × 3 targets (5-split) | TODO | CPU | ~10 min/target | S0 |
| P3 | SMOGN augmentation × 3 targets (5-split) | TODO | CPU | ~3 min/target | S0 |
| P4 | NGBoost distributional × 3 targets (5-split) | TODO | CPU | ~5 min/target | S0, S2 |
| P5 | Semi-supervised ranking × 3 targets (5-split) | TODO | CPU | ~5 min/target | S0 |
| V1 | LOOCV validation of winners | TODO | CPU | ~15 min/winner | P1-P5 |
| R0 | Results synthesis + memory update | TODO | local | 10 min | V1 |

### Execution Strategy (maximize utilization)

**Wave 1 (parallel on 9 CPUs):**
- Process A: P1 (per-item ordinal) × T1, T2, T3 — CPU-heavy but per-item models are small
- Process B: P3 (SMOGN) × T1, T2, T3 — lightweight, fast

**Wave 2 (parallel):**
- Process A: P2 (pairwise) × T1, T2, T3 — memory-heavy (pair generation)
- Process B: P4 (NGBoost) × T1, T2, T3 — moderate CPU

**Wave 3:**
- P5 (SSL ranking) × T1, T2, T3 — depends on XGBRanker stage 1

**Wave 4:**
- LOOCV validation of top 3 winners (sequentially, ~15 min each)

**Total estimated time: ~2 hours**

### Metrics per experiment

- CCC (primary)
- cal_slope (key anti-compression metric)
- MAE, r (secondary)
- Quartile bias: Q1 (<3), Q2 (3-6), Q3 (6-10), Q4 (≥10) for T1; adjusted for T2/T3

### Critical Rules

- Feature selection INSIDE each fold (LOOCV or 5-split)
- Per-item scores are TARGETS, not features (no leakage)
- obs_subscore, obs_target, hy forbidden as features
- PD-only evaluation for all targets
- CPU-only LightGBM (GPU slower at N=94)
- Multi-seed ensemble (5 seeds)
- Clip predictions to [0, max_possible] per target

---

## Previous Sessions (archived)

### Session 11 — Compression Proposals Advisory (2026-03-14) — DONE
### Session 10 — Feature Space Exploration (2026-03-14) — DONE
### Session 9 — CCC HP Optimization (2026-03-14) — DONE
### Session 8 — Observable Bias Ablation (2026-03-14) — DONE
