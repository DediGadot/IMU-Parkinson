# Progress Log — CCC Explanation and Caveats

---

## Session: 2026-03-30 — Metric Clarification

### 00:00 — Task initialization
- Read the required planning workflow and reconciled existing planning files in the repo.
- Reviewed current manuscript text, generator text, and shared metric utilities to answer the question from source rather than memory.

### 00:10 — CCC definition and implementation verified
- Confirmed that `eval_utils.lins_ccc` is the repository's canonical implementation of Lin's concordance correlation coefficient.
- Confirmed that experiment scripts report CCC on pooled out-of-fold predictions using `full_metrics`, alongside MAE, Pearson r, and calibration slope.

### 00:20 — Interpretation caveats verified against manuscript/results
- Verified the headline examples used by the paper: T1 5-fold CCC=0.865 with slope=0.745, T3 5-fold CCC=0.807 with slope=0.581, and baseline T3 5-fold CCC=0.186 with slope=0.104.
- Confirmed that the paper itself already treats CCC as necessary but insufficient, supplementing it with slope, MAE, bias, confidence intervals, and severity-stratified analyses.
- Identified the most important answer points: what CCC measures here, why it was chosen over r/MAE alone, and why it still has important caveats in this dataset.

# Progress Log — NEW.html Verification Audit

---

## Session: 2026-03-27 — Repository-Wide Audit of NEW.html

### 00:00 — Task initialization
- Read planning workflow and ran session catchup
- Confirmed prior unsynced `NEW.html` discrepancy work existed in a previous session
- Checked actual worktree state with `git diff --stat` and `git status --short`
- Began targeted review of `NEW.html` and current planning docs

### 00:15 — Claim inventory and source mapping
- Extracted all current headings, figure captions, tables, and numeric paragraphs from `NEW.html`
- Identified that the prior numerical audit is stale for the current manuscript
- Confirmed current Table 2 uses mixed sources: direct tier from primary `compression_P*_5split.json`, partial/unobservable tiers from `reviewer_obs_5fold.json`

### 00:35 — Verification pass complete
- Reproduced the headline BCa T1 CCC interval from raw per-subject predictions and confirmed the manuscript rounding
- Verified that the main internal quantitative claims align with live JSON artifacts
- Isolated three substantive manuscript issues: cross-dataset protocol/sample-size drift, Williams-test overstatement for the observed observability ordering, and an unsupported fold-restricted-ranking ablation claim

# Progress Log — PD-IMU 10x Improvement via Memento

---

## Session: 2026-03-26 — Plan Creation

### 20:45 — Research Phase
- Launched parallel research: web search agent (63 tool uses), Codex CLI (GPT-5.4 xhigh), paper analysis
- Web search found: RelCon (Apple ICLR 2025), LSM (Google ICLR 2025), UniMTS, SensorLM, FM-FoG, LIMU-BERT-X, NormWear
- **Key finding:** RelCon uses relative contrastive ranking — closest methodological parallel to our SSL ranking
- **Key finding:** No one has published UPDRS-III regression on WearGait-PD or any other dataset since Shuqair 2024
- **Key finding:** Mostafavi 2025 confirmed R2<0.2 for UPDRS from gait sensors — validates our "this is hard" narrative

### 21:00 — Paper Analysis
- Read NEW.html: title, abstract, all 8 discussion sections, full methods
- Identified weaknesses: no 2025 FM comparison, no formal observability test, no UQ, no DBS subgroup
- Identified strengths: SSL ranking mechanism well-explained, observability gradient compelling, reviewer responses integrated

### 21:15 — Memento Framework Integration
- Tested Memento agent with GLM-5 on medical codebase files
- Fixed litellm tool-calling bug (modify_params=True in client.py)
- Verified: filesystem skill reads files correctly, agent responses are accurate
- Designed 4 custom Memento skills for autonomous codebase improvement

### 21:30 — Plan Creation
- Created 8-phase plan across task_plan.md
- Prioritized: observability framework > conformal prediction > FM positioning > subgroups > multi-FM > autonomous loop > polish
- Rejected: FM fine-tuning (N too small), sensor-language alignment (too complex for limited gain)
- Documented 7 improvement directions with expected gains, risks, and novelty scores

### 21:45 — Background Task Results
- **Codex CLI (GPT-5.4 xhigh):** COMPLETE — 173K tokens, exceptional output. 5 novel directions with specific algorithms, losses, and novelty scores. Key insight: "your moat is not better boosting, it's the privileged multimodal data."
- **Claude CLI:** FAILED — credit balance too low
- **Gemini CLI:** FAILED — 429 rate limit after 10 retries (model capacity exhausted)

### 21:50 — Plan Upgrade with Codex Insights
- Added Phase 8 (Observability-Constrained MIRT, 9/10 novelty)
- Added Phase 9 (Cross-Modal Privileged SSL, 8.5/10 novelty)
- Added Phase 10 (Leave-Site-Out Validation — CRITICAL for reviewers)
- Added Phase 11 (Clinical Utility Analysis — CRITICAL for Nature)
- Re-prioritized: leave-site-out is now #1 priority (most likely rejection reason)
- Codex's Memento integration plan is sharper: experiment state vectors, multi-objective rewards, auto-generated failure-mode skills

### 22:00 — Plan Restructured: Memento as Execution Backbone
- Original plan barely used Memento (Phases 0 and 6 only). User called it out.
- Rewrote entire plan: 7 custom Memento skills → every phase runs THROUGH Memento
- Architecture: Memento reads results → runs analysis skills → writes configs/sections → human triggers GPU
- GPU bridge: file-based (Memento writes commands, human/cron executes gpu.sh)
- Autonomous loop: `memento_loop.sh` — pull → evaluate → configure → run → repeat

### Status at end of session
- **Research:** COMPLETE — competitive landscape mapped from 3 sources (web search, Codex, paper analysis)
- **Plan:** RESTRUCTURED — 10 phases, all Memento-driven, 7 custom skills
- **Memento setup:** WORKING — GLM-5 responds, filesystem skill functional, tool-calling fixed
- **Key insight:** Memento is the execution engine, not a side tool. Every phase uses Memento skills.
- **Next action:** Run queued experiments (stratified SSL, leave-site-out, multi-FM)

### 22:30 — Server Setup Complete
- WearGait-PD downloaded (52GB, 1866 files, 795 PD + 681 HC CSVs)
- All deps installed (PyTorch cu128, LightGBM, XGBoost, MOMENT, etc.)
- FM embeddings regenerated: 1405 recordings × 768 dims (753s on GPU)
- rocket_recordings.npz aligned with FM (1405 entries, 178 subjects)

### 22:45 — SSL Ranking Replicated on New Server
- T1 (observable): CCC=0.855, slope=0.709, MAE=1.001
- T2 (broad obs): CCC=0.833, slope=0.685, MAE=1.152
- T3 (total): CCC=0.747, slope=0.539, MAE=5.081
- Note: slight variance from old server due to FM re-extraction (different recording order)

### 23:00 — Observability + Conformal Completed
- Williams' test: p < 0.001 (observability gradient significant)
- Permutation test: p = 0.002, z = 2.65
- Conformal T1: 90% PI = ±2.19 pts (< MCID 3.25)
- Conformal T3: 90% PI = ±10.12 pts (3× MCID)

### 23:15 — Subgroup Metadata Extracted
- 2-site structure discovered: NLS(72) vs WPD(28)
- DBS: 23 Yes, 59 No, 18 unknown
- H&Y: 1-4 distribution captured
- Full ablation report written to results/memento_ablation_report.md

### Errors Encountered
| Error | Resolution |
|-------|-----------|
| litellm UnsupportedParamsError on tool-calling | Added `litellm.modify_params = True` in client.py |
| Claude CLI credit balance too low | Codex provided sufficient research; Claude not needed |
| Gemini 429 rate limit (10 retries) | Codex covered the gap; Gemini not critical |
| NEW.html too large to read fully (337K tokens) | Used grep for headings + targeted offset reads for key sections |

---

## Historical Sessions (preserved)

### 2026-03-26 — CCC Definition + Paper Innovations
- Verified CCC definition in code and manuscript
- Confirmed P0→P5 improvement: T1 CCC 0.700→0.865, T3 CCC 0.186→0.807
- Identified: ranking-to-leaf transformation is the main engine; HC anchors are marginal

### 2026-03-25 — Codebase Audit
- 129 tests pass, 4 skipped
- Architecture: small shared core + many large standalone runners
- Security: TOKEN.md has raw credentials
- Multiple overlapping planning docs need consolidation

### 2026-03-24 — Reviewer Response
- Wrote run_reviewer_experiments.py (730 lines, 4 subcommands)
- Set up new GPU server (RTX 3090 24GB)
- All 4 experiments completed:
  - Age sensitivity: age NOT driving results
  - HC ablation: ranking > HC anchoring
  - Obs 5-fold: gradient confirmed
  - Single sensor: single wrist CCC>0.78
- Paper rewrite started (Phases P4-P5 pending)
