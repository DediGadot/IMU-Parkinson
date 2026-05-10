MCP issues detected. Run /mcp list for status.Here is a comprehensive critique and structural redesign of the Paper-Update Skill to ensure Nature-grade rigor, specifically tailored for the post-audit WearGait-PD narrative.

### 1. Figure Suite (Insightful Post-Audit Narrative)
Instead of generic tables, figures must expose the fundamental limitations and boundaries of the dataset.

*   **Fig 1: The T1 Structural Ceiling (Pareto Asymptote).** Plots CCC against dataset size ($N$). Overlays the empirical curve $CCC(N) = 0.5975 - 2.1308 \cdot N^{-0.6408}$. **Story:** Proves that acquiring more data will not break the 0.60–0.65 barrier; the ceiling is a structural limitation of WearGait-PD sensors, not a sample-size issue.
*   **Fig 2: T1 Best Candidate vs. Theoretical T3 Bounds.** A horizontal bar chart showing `iter34` T1 LOOCV (0.7366) against T3 theoretical bounds A (0.351) and D (0.683). **Story:** Visually explains why predicting the unobservable non-gait UPDRS-III domains (T3) from gait-only kinematics (T1) is fundamentally bounded.
*   **Fig 3: The Transportability Cliff.** Slopegraph or paired dumbbell chart showing LOOCV vs. LOSO CCC for `iter12` and `iter34`. **Story:** Transparently admits OOD fragility (0.7366 dropping to 0.4564). A Nature reviewer demands this honesty over pure LOOCV headlining.
*   **Fig 4: Transductive vs. Inductive Gap (The Leakage Audit).** A mirrored density plot of predictions. Top half: Pre-audit transductive (leaked) predictions. Bottom half: Post-audit strictly fold-local inductive predictions. **Story:** Visually quantifies exactly how much performance was artificially inflated by target contamination.
*   **Fig 5: Paired-Bootstrap OOF Delta (iter34 vs iter12).** Histogram of the bootstrapped $\Delta$CCC with a 95% CI shaded and $frac>0$ annotated. **Story:** Establishes rigorous statistical superiority of the 8-item multibase approach, ruling out random fold variance.
*   **Fig 6: T3 Error Anatomy.** Scatter plot of Predicted vs. Actual T3 scores, color-coded by the severity of the *non-gait* UPDRS-III subscore (e.g., resting tremor, speech). **Story:** Explains the residual correlation ($r = -0.8004$); the model structurally under-predicts severe cases because those cases are driven by symptoms invisible to the IMUs.
*   **Fig 7: Valid-Range Cohort Impact.** Boxplots of metric variance before and after strict invalid-code masking ($N=95$). **Story:** Highlights the impact of strict data hygiene on reported metrics.

### 2. Validation Rules (Beyond Snippets)
Relying solely on `REQUIRED_SNIPPETS` in `render_current_paper.py` is brittle. The skill must implement a structured **Claim Ledger** (`ledger.json`) with the following hard rules:

*   **Single-Source Traceability Rule:** Every numerical claim in `paper.md` must link to a specific `results/*.json` artifact. The validator must load the JSON and assert `float(text_claim) == float(json_value)`.
*   **AST No-Hardcode Rule:** The validator must parse `paper_figures.py` via Python `ast` to ensure no float literals exist for metrics. Data *must* be loaded from the JSON ledger.
*   **Cohort $N$-Consistency Rule:** If `iter34` claims $N=93$ for CCC, the validator ensures MAE and RMSE claims for `iter34` also state $N=93$. Silent row-dropping across metrics fails the build.
*   **Transductive Pairing Rule:** Any mention of "leakage" or "pre-audit" performance must structurally require the adjacent presence of its "inductive" post-audit counterpart.

### 3. Workflow Orchestration
*   **Clean Parallelization:**
    *   *Phase 2 (Truth Extraction):* Reading `MEMORY.md`, `CLAUDE.md`, and scanning `results/*.json` can run in parallel.
    *   *Phase 4 (Figure Generation):* Each matplotlib function in `paper_figures.py` can be dispatched to separate subprocesses.
    *   *Phase 7 (Tri-CLI Review):* Codex, Gemini, and Kimi sub-agents evaluate the HTML in parallel.
*   **Irreducible Serial Dependencies:**
    *   The `ledger.json` *must* be completely resolved before any text diffing or generation begins.
    *   `render_current_paper.py` *must* wait for `paper_figures.py` to write its output arrays to ensure image checksums match the manuscript state.
*   **Nature Reviewer Traps:** Reviewers will catch parametric standard errors (e.g., $1.96 \cdot \sigma / \sqrt{n}$) instead of empirical bootstrapped CIs for non-normal distributions like CCC. Orchestration must ensure the pipeline explicitly runs `eval_utils.py` bootstrap routines and never approximates CIs.

### 4. Nature Framing Risks (Reject Criteria)
A "reject and resubmit" is guaranteed if the narrative triggers these clinical-ML red flags:
*   **MAE-Only Headlining:** Downplaying CCC drops by highlighting MAE. MAE is easily gamed by zero-variance mean-guessing on imbalanced clinical cohorts. CCC must always be the headline metric.
*   **Mixing Validation Protocols:** Comparing a 5-fold screening number against a single-seed LOOCV or LOSO without explicit juxtaposition.
*   **Euphemistic Leakage:** Calling target contamination "data alignment drift." A medical journal expects explicit terms: "transductive leakage," "target contamination," or "non-nested meta-models."
*   **Unstated Multiple Comparisons:** If `iter34` emerged from a hyperparameter sweep over 50 configurations, framing it as a zero-shot result without discussing the Family-Wise Error Rate (FWER) or Bonferroni/Benjamini-Hochberg corrections is a fatal flaw.

### 5. Skill Structural Choices
**Recommendation: Split into distinct sub-skills.**
Do not use a monolithic 1500-line markdown file. It will fail via context collapse just like `.claude/commands/update-paper.md`.

*   **`skill-paper-ledger`**: Pure data extraction. Reads results, runs consistency checks, outputs `ledger.json`. (Can be fully deterministic and non-LLM).
*   **`skill-paper-figures`**: Consumes the ledger and generates the matplotlib suite. Enforces colorblind-safe palettes and 300dpi outputs.
*   **`skill-paper-orchestrator`**: The actual LLM agent prompt. It reads the ledger, surgically diffs `paper.md`, calls the figure script, executes `render_current_paper.py`, and orchestrates the Tri-CLI reviewer feedback loop.

*Pros:* Decouples data fetching from creative prose rewriting. You can safely rebuild the ledger or figures without wasting tokens on LLM text generation.
*Cons:* Requires strict JSON schema adherence between the skills, but this is a necessary boundary for reproducibility.
