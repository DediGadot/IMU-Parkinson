# Paper-Update Skill Redesign Brief

## Project: PD-IMU (UPDRS-III regression on WearGait-PD)

**Repo:** `/home/fiod/medical`
**Existing legacy skill:** `.claude/commands/update-paper.md` (1267 lines, marked LEGACY PRE-AUDIT, wrong pipeline route NEW.html / generate_paper.py).
**Authoritative pipeline NOW:**
- Source of truth: `paper.md` (715 lines markdown, prose-only, no figures yet)
- Renderer: `render_current_paper.py` -> `CURRENT_PAPER.html` (pandoc gfm->html5, css inject, audit banner)
- Validation: `results/current_paper_export/manifest.json` with REQUIRED_SNIPPETS (~108 must-appear strings) and FORBIDDEN_STALE_SNIPPETS (~5 must-not-appear strings). Failed validation => SystemExit(1).

## Latest canonical results (must be cited; sourced from MEMORY.md / CLAUDE.md / paper.md)

- **T1 canonical floor:** `compose_t1_iter12_honest.py` LOOCV CCC = 0.6550, MAE = 1.561, N=94 (items 9-14 axial subscore).
- **T1 strongest candidate:** `run_t1_iter34_hybrid_8item_multibase.py` LOOCV CCC = 0.7366, MAE = 1.731, N=93 (8-item RegressorChain x {LGB+XGB-hist+ExtraTrees}, 17-worker fold-parallel ProcessPool).
- **T1 LOSO transportability (iter34):** CCC = 0.4564 (F72, first published T1 transportability).
- **T1 leakage audit (iter34, F73):** P1 z=5.22 strong PASS, P4 pass, P2 borderline soft-fail (interpreted as OOD fragility, not leakage).
- **T3 canonical:** `run_t3_iter47_invalid_code_fix.py --mode run` LOOCV CCC = 0.3784, MAE = 7.528, N=95 (valid-range cohort, all-missing rows excluded, raw codes outside 0-4 -> NaN).
- **T3 LOSO transportability:** valid-range two-way CCC = 0.150 (NLS->WPD 0.419 + WPD->NLS 0.263 averaged over 3 seeds, F-pre-iter47 mode arch is iter16 0.341).
- **Item 15 (postural tremor):** iter17 item_only LOOCV +0.1099 (Δ=+0.20, MAE 1.088).
- **Item 18 (rest tremor):** iter17 hy_residual_item_v2 LOOCV +0.4858 (Δ=+0.236, MAE 0.887).
- **Theoretical T3 ceilings:** Bound D = 0.683 (perfect-T1 ->T3); Bound A = 0.351 (oracle T1 + mean R, IMU-only max); Bound E = 0.171 (inductive shrinkage T1_pred->T3).
- **Pareto asymptote (iter22 LC sweep):** CCC(N) = 0.5975 - 2.1308*N^(-0.6408), structural ceiling 0.5975 for iter5 architecture at infinite N.

## Hard rules from CLAUDE.md / AGENTS.md

1. Inductive firewall: fold-local helpers via `inductive_lib.py` only; never global imputers/z-scorers/anchors.
2. 5-null gate before any reported number (scrambled-label, SID-shuffle, canary feature, library-exclusion, transductive sanity).
3. Lockbox protocol: 5-fold for screening, single pre-registered LOOCV for headline. No re-running LOOCV across variants and picking best.
4. Promotion gate: Δ̄ >= +0.025 mean AND paired-bootstrap frac>0 >= 0.95 on 5-fold OOF; LOOCV confirmation + scrambled-label null still required before lockbox.
5. Report transductive AND inductive numbers side-by-side; the gap is the leakage estimate.
6. Source-of-truth ordering: AGENTS.md > findings.md > CLAUDE.md.
7. `paper3_split.json` (clean, seed=20260309), NEVER `data_split.json` (CONTAMINATED).
8. Cite numbers ONLY from the SOTA table in CLAUDE.md, not from findings.md or progress.md.

## What the new skill must do

The skill replaces `update-paper.md`. It must orchestrate updating `paper.md` and producing a Nature-grade `CURRENT_PAPER.html` with insightful figures.

The user has a `pd-imu-100x-researcher` skill that runs experiments. The paper-update skill consumes the latest results / memory / findings and surgically updates paper.md, regenerates figures, and renders + validates the HTML.

Required workflow phases:
1. Mode select: scratch (full regen) vs update (incremental). Default update.
2. Truth extraction: read MEMORY.md + every linked memory file, CLAUDE.md (SOTA table), findings.md, paper.md, results/current_paper_export/manifest.json. Build a typed claim ledger {claim_id, target, metric, value, model, protocol, N, source_file, role, artifact_exists}.
3. Diff: extract every quantitative claim from current paper.md; flag stale/missing/inconsistent vs ledger.
4. Figure pipeline: build a `paper_figures.py` that loads results/*.json + OOF arrays and renders publication-quality figures (matplotlib, 300 dpi, colorblind-safe). Required figure set should be insightful for the post-audit narrative (T1 vs T3 ceiling, iter34 vs iter12 paired bootstrap, T1 LOSO transportability cliff, item-level CCC, leakage-audit z-scores, Pareto N-asymptote, etc.). Embed as ![]() into paper.md or as a figures/ directory referenced by gfm pandoc.
5. Surgical edits: apply diffs to paper.md preserving working prose. Update REQUIRED_SNIPPETS / FORBIDDEN_STALE_SNIPPETS list in render_current_paper.py if new claims warrant. NEVER hard-code numbers in figure scripts -- always load from JSON.
6. Render: `uv run python render_current_paper.py` -- must pass snippet validation.
7. External review: codex + gemini + kimi in parallel (tri-CLI) for academic prose review (codex), scientific narrative review (gemini), and structural/cautionary-framing review (kimi).
8. Surgical fix loop: triage external feedback against typed ledger, apply accepted suggestions, re-render. Cap at 3 cycles.
9. Final report: list claim deltas, figure changes, validation status, residual issues.

## Nature-grade quality bar

- Honest framing: pre-audit results retained as historical context; deployment numbers strictly post-audit.
- Cautionary benchmark stance throughout (T1 transportability cliff, T3 iter47 0.3784 with N=95, LOSO drops).
- Statistical rigor: paired-bootstrap CIs, frac>0, FWER discussion for iter33 family, BCa intervals.
- Visual excellence: colorblind-safe palettes, every figure tells one story at a glance, statistical annotations on every panel.
- Reproducibility: every reported number traces to a specific .json artifact in results/.
- Limitations honesty: N=94 wall structurally, not data-quantity-bound.

## Your task (CLI consultant)

Critique and improve this design. Specifically:

1. **Figure suite** -- propose the 8-12 most insightful figures for the post-audit T1+T3 narrative. Each figure: name, what it shows, what data source(s) feed it, what story it tells the reader at a glance. Don't include figures that just restate a table.
2. **Validation rules** -- what claim-integrity checks beyond REQUIRED/FORBIDDEN snippets prevent silent number drift? (e.g., per-context one-data-source rule; figure-annotation match-source rule; cohort-N consistency rule per claim_id).
3. **Workflow orchestration** -- which phases parallelize cleanly? Where are the irreducible serial dependencies? Where would a Nature reviewer catch us cutting corners?
4. **Nature framing risks** -- what specific phrasing or omission would draw a "reject and resubmit" from a senior Nature Digital Medicine reviewer given our cautionary-benchmark stance? (e.g., MAE-only headlining, cross-protocol mixing, unstated multiple-comparisons).
5. **Skill structural choices** -- should this be one .md skill file or split into sub-skills (e.g., paper-figures, paper-claims-audit, paper-renderer)? Pros/cons.

Be concrete. Quote file paths. Avoid generic advice. Limit to ~600 lines.
