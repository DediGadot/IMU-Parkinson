## Active Session: CCC Definition Lookup (2026-03-26)

**Objective:** Answer what CCC means in the paper, grounded in the manuscript text, source-code implementation, and stored result artifacts.

### Phases

| # | Phase | Status | Est. Time | Notes |
|---|-------|--------|-----------|-------|
| C0 | Read planning guidance and recover context | DONE | 2 min | Reviewed planning skill and existing planning files |
| C1 | Locate CCC in manuscript and source code | DONE | 5 min | Confirmed canonical implementation in `eval_utils.py` and manuscript framing in `generate_paper.py` |
| C2 | Verify headline CCC values in result artifacts | DONE | 3 min | Checked stored JSON outputs for T1/T3 baseline and SSL |
| C3 | Answer user with intuitive explanation | IN_PROGRESS | 2 min | Explain why CCC matters for prediction compression |

---

## Active Session: Paper Innovations + Result Impact (2026-03-26)

**Objective:** Identify the paper's biggest methodological innovations and quantify their impact using the current manuscript sources, experiment code, and stored result artifacts.

### Phases

| # | Phase | Status | Est. Time | Notes |
|---|-------|--------|-----------|-------|
| I0 | Recover context and refresh planning files | DONE | 3 min | Reviewed planning skill, catchup state, and current repo memory files |
| I1 | Locate paper-stated contributions in manuscript/source | DONE | 8 min | Contribution statement found in `NEW.html` and `generate_paper.py`; tables/figures anchored |
| I2 | Verify implemented methods in code | DONE | 10 min | Confirmed target definitions, P5 rank-label construction, HC subset handling, and 5-fold observability/HC ablation scripts |
| I3 | Verify numerical impact in result artifacts | DONE | 8 min | Verified headline JSON metrics for P0 vs P5, observability table, age confound, and HC ablation |
| I4 | Answer user with paper-claim vs code-implementation separation | DONE | 5 min | Synthesized main innovations, quantified effects, and noted manuscript-vs-code nuance on HC anchors |

---

## Active Session: Codebase Audit + Improvement Ideas (2026-03-25)

**Objective:** Read `NEW.html`, all Markdown files, and all code files in the repository; build a grounded understanding of the project structure and propose 10 crisp improvement ideas for the next iteration.

### Phases

| # | Phase | Status | Est. Time | Notes |
|---|-------|--------|-----------|-------|
| A0 | Inventory repository and sync prior context | DONE | 10 min | Existing planning files read; repo file inventory captured |
| A1 | Read Markdown + HTML artifacts | IN_PROGRESS | 20 min | Prioritize `NEW.html` and active project docs |
| A2 | Read code surface | PENDING | 45 min | Cover Python, shell, and tests; identify central modules vs one-off scripts |
| A3 | Synthesize architecture and recurring patterns | PENDING | 15 min | Distill what the codebase is optimizing for and where it strains |
| A4 | Propose 10 crisp improvements | PENDING | 10 min | Focus on actionable next moves, not vague wishlist items |

### Scope

- Required: `NEW.html`
- Required: all `*.md` files in repo root
- Required: all code files (`*.py`, `*.sh`, tests)
- Optional spot checks: config files if needed for execution model or dependencies

### Risks / Watchpoints

- The repo contains many generated artifacts and historical experiment runners; need to distinguish active pathways from stale branches.
- Existing planning files reflect a prior paper-revision task; avoid overwriting that context while adding current findings.

---

## Active Session: Reviewer Response — All 11 Comments (2026-03-24)

**Objective:** Address ALL reviewer comments on the PD-IMU UPDRS-III paper. Write new experiment scripts, set up a new GPU server, run experiments, and rewrite the paper.

**Synapse Token:** In `TOKEN.md` (personal access token for WearGait-PD download)
**Server:** TBD — user will provide remote GPU credentials

### Phases

| # | Phase | Status | Est. Time | Notes |
|---|-------|--------|-----------|-------|
| P0 | Write experiment scripts (C2, C3, C11) | DONE | 45 min | `run_reviewer_experiments.py` — 4 subcommands |
| P1 | Set up new GPU server | DONE | 45 min | RTX 3090 24GB, WearGait-PD 47GB, FM re-extracted |
| P2 | Run new experiments on GPU | DONE | 20 min | All 4 experiments completed successfully |
| P3 | Pull results + validate | DONE | 5 min | All 4 JSON artifacts validated |
| P4 | Rewrite generate_paper.py | PENDING | 2-3 hrs | Restructure Results, unify 5-fold, add new figures |
| P5 | Regenerate PAPER.html + verify | PENDING | 30 min | Cross-check all numbers against artifacts |

### Reviewer Comments Tracking

| # | Comment | Action Type | Needs Experiment? | Script | Status |
|---|---------|-------------|-------------------|--------|--------|
| C1 | Non-comparable eval protocols | Paper edit | NO (5-fold results exist) | — | PENDING |
| C2 | HC age confound | New experiment + paper | YES | `run_reviewer_experiments.py --age-sensitivity` | PENDING |
| C3 | True signal vs PD-vs-HC separation | New experiment + paper | YES | `run_reviewer_experiments.py --hc-ablation` | PENDING |
| C4 | Over-reliance on CCC metric | Paper edit | NO | — | PENDING |
| C5 | LOOCV in small-N high-dim | Merged with C1 | NO | — | PENDING |
| C6 | No external validation | Already acknowledged | NO | — | DONE |
| C7 | Total UPDRS too prominent | Paper restructure | NO | — | PENDING |
| C8 | Pipeline complexity | Paper restructure | NO | — | PENDING |
| C9 | FM results not compelling | Paper edit (move to SM) | NO | — | PENDING |
| C10 | Per-subject scatter plots | Paper figure | NO (data in JSONs) | — | PENDING |
| C11 | Single wrist + lower back sensor | New experiment | YES | `run_reviewer_experiments.py --single-sensor` | PENDING |

### Experiment Specifications

**Experiment 1: Age-Matched SSL Sensitivity (C2)**
- Age-match HC to PD by removing HC > 75y (or propensity score)
- Re-run P5 SSL with age-matched HC subset, 5-fold CV
- Partial correlation of SSL predictions controlling for age
- Age-stratified within-PD evaluation (tertiles)

**Experiment 2: HC Ablation (C3)**
- P5 SSL pipeline WITHOUT HC (PD-only ranker, N=94)
- Compare: P0 (no ranking) vs P5-no-HC vs P5-with-HC
- All under identical 5-fold CV

**Experiment 3: Single-Sensor Ablation (C11)**
- Run single right wrist, single left wrist configs
- Already have: lower_back_1 (MAE=9.50), wrists_2 (MAE=8.75)
- Pipeline: v2 features + FM + LGB with K=150

**Experiment 4: 5-Fold Observability Decomposition (C1)**
- Re-run 3-level observability under 5-fold (currently LOOCV only)
- Need: direct/partial/unobs MAE+CCC+r under 5-fold

### Server Setup Plan

```bash
# 1. Update gpu.sh with new server credentials
export GPU_REMOTE=root@NEW_IP GPU_PORT=NEW_PORT

# 2. Provision
./gpu.sh --setup

# 3. Download WearGait-PD (52GB)
./gpu.sh synapse_download.py   # TOKEN from TOKEN.md

# 4. Upload cached artifacts (saves hours)
./gpu.sh --push-cache

# 5. Verify
./gpu.sh --status
./gpu.sh "python3 -c 'import torch; print(torch.cuda.is_available())'"
```

### Paper Structure After Revision

**Main Text Results (6 sections):**
1. Cohort Description
2. **PRIMARY: Observable Subscore via SSL Ranking** (T1 5-fold)
3. Observability Gradient (3-level decomposition)
4. **SECONDARY: Total UPDRS-III & Observability Ceiling** (T3 context)
5. **NEW: Age Confound & HC Ablation Sensitivity** (C2+C3)
6. Cross-Dataset Context

**Supplementary Material:**
- S1: Compression ablation (P0-P5 comparison)
- S2: Quartile bias reduction
- S3: Foundation model analysis
- S4: Sensor ablation (including single wrist/back)
- S5: Negative results (DL failures)
- S6: LOOCV sensitivity (all methods)
- S7: Hyperparameter specification table

### Key Data Points (existing, for reference)

**5-fold SSL results (ALREADY EXIST):**
| Target | CCC | MAE | r | slope |
|--------|-----|-----|---|-------|
| T1 | 0.865 | 0.953 | 0.877 | 0.745 |
| T2 | 0.831 | 1.162 | 0.847 | 0.707 |
| T3 | 0.807 | 4.464 | 0.877 | 0.581 |

**5-fold baselines (ALREADY EXIST):**
| Target | CCC | MAE | r |
|--------|-----|-----|---|
| T1 | 0.700 | 1.336 | 0.758 |
| T2 | 0.554 | 1.851 | 0.604 |
| T3 | 0.186 | 8.086 | 0.297 |

### Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| Gemini CLI 429 rate limit | 1 | Got partial response before error; sufficient for planning |
| (more as they arise) | | |
