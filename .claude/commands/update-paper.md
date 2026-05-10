---
description: Surgically update paper.md against the latest canonical results, regenerate Nature-grade figures, render CURRENT_PAPER.html, and run a tri-CLI prose review. Authoritative paper-update skill for PD-IMU.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob, Agent, AskUserQuestion]
---

# Update Paper — Post-Audit Manuscript Skill

You are the **orchestrator** for updating the WearGait-PD UPDRS-III regression manuscript. You do not draft from scratch — you align `paper.md` with the latest canonical lockbox numbers, regenerate figures from JSON-only sources, render `CURRENT_PAPER.html`, and pass the result through a tri-CLI prose review.

## Source-of-truth pipeline (do not deviate)

| Layer | File | Role |
|---|---|---|
| Policy / leakage discipline | `AGENTS.md` | Highest authority for what counts as a valid claim. |
| Canonical numbers | `CLAUDE.md` SOTA table | The only place you cite headline numbers from. |
| Provenance / artifacts | `results/*.json`, `results/*.oof.npy`, `results/current_paper_export/manifest.json` | Every claim must trace to a specific artifact. |
| Manuscript surface | `paper.md` | Output, not source. Never the ground truth for any number. |
| Renderer | `render_current_paper.py` → `CURRENT_PAPER.html` | Pandoc gfm→html5 + CSS + audit banner + snippet validation. |
| Auto-memory | `~/.claude/projects/-home-fiod-medical/memory/MEMORY.md` and every linked file | Recent context across sessions. |

**Legacy routes are dead.** `NEW.html`, `NEW4.html`, `generate_paper.py`, `generate_paper_v4.py` are archaeology. Do not generate them, do not read them as truth, do not migrate text from them.

## Current canonical numbers (verify, do not memorise)

Always re-read these from `CLAUDE.md` and `AGENTS.md` at run time. The skill must hard-fail if `paper.md` cites a number that contradicts them.

- **T1 canonical floor**: iter12-honest LOOCV CCC `0.6550`, MAE `1.561`, N `94` (`compose_t1_iter12_honest.py`).
- **T1 strongest candidate**: iter34 hybrid LOOCV CCC `0.7366`, MAE `1.731`, N `93` (`run_t1_iter34_hybrid_8item_multibase.py`). Reportable as candidate / post-pub replication target only — never as canonical replacement. P2 leakage gate is a soft fail; framing must be "no evidence of transductive leakage; P2 indicates OOD fragility".
- **T1 LOSO transportability** (iter34 architecture): CCC `0.4564` (F72).
- **T3 canonical**: iter47 valid-range LOOCV CCC `0.3784`, MAE `7.528`, N `95` (`run_t3_iter47_invalid_code_fix.py --mode run`).
- **T3 LOSO** (iter47 valid-range): two-way mean CCC `0.150` (NLS→WPD `0.194`, WPD→NLS `0.106`). The older iter16 IPW LOOCV `0.4694` and LOSO `0.341` are **historical and target-contaminated** — never present as canonical.
- **Item 15** (postural tremor): iter17 item_only LOOCV +0.1099, MAE 1.088 (supplementary).
- **Item 18** (rest tremor): iter17 hy_residual_item_v2 LOOCV +0.4858, MAE 0.887 (supplementary).
- **Theoretical T3 ceilings**: Bound A oracle = 0.351, Bound D perfect-T1→T3 = 0.683, Bound E inductive shrinkage = 0.171. Frame as oracle / non-deployable.
- **Pareto N-asymptote** (iter22 LC sweep): `CCC(N) = 0.5975 - 2.1308·N^(-0.6408)` → asymptote 0.5975 = structural ceiling for iter5 architecture at infinite N.

**Retracted, do not cite as deployment**: T1 iter11A 0.7241, T3 iter5 0.5227, T3 iter16 0.341, T3 iter41 0.3948, pre-leakage SSL T1 0.868 / T3 0.776, pre-audit MAE 6.89 / r 0.860. They survive only as historical context with explicit `historical pre-audit` / `target-contaminated` tags.

---

## Phase 0 — Mode select

Use `AskUserQuestion` to ask:

> **Update mode:**
> - **A) Incremental update** — Diff current `paper.md` claims against the latest claim ledger; surgically edit only stale/missing/inconsistent passages. Default. Use after a new lockbox iter.
> - **B) Figure-only refresh** — Skip prose edits; rebuild every figure from JSON, embed them, re-render. Use when figure code or palette changes but numbers are unchanged.
> - **C) Full regeneration** — Rebuild claim ledger, re-extract every paper claim, refit narrative framing. Use only when the paper structure must change (e.g. a new section like 3.8 / 4.11 / 4.12 / 4.13 / 5.5 was added).

If the user does not pick, default to **A**.

Create the working directory:

```bash
mkdir -p .paper_build
```

`.paper_build/` is ephemeral. Do not commit it. Clean at the end of a successful run.

---

## Phase 1 — Build the typed claim ledger (irreducible serial dependency)

The ledger is the **single source of truth** for everything downstream: figure annotations, paper edits, snippet validation. **No phase after this may read result JSONs directly for headline metrics** — they read the ledger.

Run the ledger builder:

```bash
uv run python scripts/paper_claims_audit.py --build-ledger \
  --out results/current_paper_export/claim_ledger.json
```

If `scripts/paper_claims_audit.py` does not exist, build it first using the **Script Specs** at the bottom of this file. Do not stub. Do not leave TODOs. The script must be runnable end-to-end on first invocation.

The ledger is a JSON list of typed claim records:

```json
{
  "claim_id": "t1_iter12_honest_loocv_ccc",
  "target": "T1",
  "metric": "CCC",
  "value": 0.6550,
  "unit": "ccc",
  "model": "compose_t1_iter12_honest",
  "protocol": "LOOCV",
  "N": 94,
  "cohort": "PD_only",
  "role": "canonical",
  "source_artifact": "results/lockbox_t1_iter12_honest_*.json",
  "source_sha256": "<computed at build time>",
  "paper_locations": [],
  "figure_locations": []
}
```

**`role` enum** — exactly one of: `canonical`, `strongest_candidate`, `sensitivity`, `historical_pre_audit`, `target_contaminated`, `external_only`, `diagnostic_only`, `oracle_non_deployable`.

**Hard-fail conditions** (the ledger builder must exit non-zero, the orchestrator must abort):

1. Any `source_artifact` path under `results/` does not exist.
2. Any pair of claims with the same `(target, metric, model, protocol)` has different `value` or `N`.
3. Any value contradicts `CLAUDE.md` SOTA table (re-parse it; no caching).
4. Any value matches a retracted number in the **Retracted** list above without a `historical_pre_audit` / `target_contaminated` role label.

---

## Phase 2 — Audit current `paper.md` against the ledger

```bash
uv run python scripts/paper_claims_audit.py --audit \
  --paper paper.md \
  --ledger results/current_paper_export/claim_ledger.json \
  --out results/current_paper_export/claim_audit.json
```

The audit walks `paper.md` end-to-end and classifies every numeric token as one of:

- `ledger_match` — value, N, protocol all consistent with a ledger claim.
- `ledger_drift` — model/protocol matches a ledger claim but value/N differs. **Fail.**
- `role_mismatch` — value matches a `historical_pre_audit` or `target_contaminated` claim but is presented without the required tag in surrounding text. **Fail.**
- `protocol_mix` — direct comparison (table row, dash, "vs") between two claims with incompatible protocols (LOOCV vs 5-fold vs LOSO vs held-out vs external zero-shot) without a footnote. **Fail.**
- `forbidden_semantic_context` — words like `deployment-ready`, `clinical utility`, `breakthrough`, `solves`, `state of the art`, `held-out test set` within ±200 chars of a `historical_pre_audit` / `target_contaminated` value, and not within ±50 chars of `historical`, `pre-audit`, `leakage`, `target-contaminated`, or `not deployment`. **Fail.**
- `citation_literature` — citation [N] number, year (1990–2030), or page count. Allowed.
- `method_parameter` — explicitly tagged near a hyperparameter / window-size / channel-count phrase. Allowed.
- `dataset_descriptive` — N=178, 13 IMUs, 100 Hz, 22 channels, etc. Cross-checked against `CLAUDE.md`. Allowed if matches.
- `unclassified` — any number that does not fall into the above. **Fail.**

`claim_audit.json` carries the full classification, the `paper.md` line/column for each token, and the suggested correction (where one is unambiguous from the ledger).

**The orchestrator must read the audit and either**:
1. **In mode A**: apply every unambiguous correction surgically via `Edit`, then leave ambiguous cases (e.g. "should this paragraph emphasise iter12 or iter34?") for narrative review in Phase 4.
2. **In mode B**: skip prose edits.
3. **In mode C**: archive the current narrative spine to `.paper_build/paper.md.bak`, then rebuild section by section against the ledger.

Surgical edits **must** preserve working prose. Do not paraphrase paragraphs whose numbers are correct. Do not reorder sections. Do not rename headings.

---

## Phase 3 — Figure pipeline (data-driven, no hard-coded numbers)

Run the figure generator:

```bash
uv run python scripts/paper_figures.py \
  --ledger results/current_paper_export/claim_ledger.json \
  --out figures/current/ \
  --claims-out results/current_paper_export/figure_claims.json
```

If `scripts/paper_figures.py` does not exist, build it from the **Script Specs**. Same no-stub rule.

**Figure suite (Nature-grade, derived from tri-CLI consensus):**

| # | Figure | Story at a glance | Primary data source |
|---|---|---|---|
| 1 | `fig01_audit_timeline.png` | Pre-audit headline → iter12 / iter34 / iter47 audit-truth timeline; retracted / historical / current lanes. | `CLAUDE.md` SOTA table parse + `results/canonical_claim_consistency_audit_*.json`. |
| 2 | `fig02_observability_ceiling.png` | T1 canonical, T1 candidate, T3 corrected, T3 LOSO with theoretical Bounds A / D / E overlaid. Gait-observable axial severity is learnable; total UPDRS-III is anatomically constrained. | iter12 + iter34 + iter47 lockboxes; iter1 ceiling derivation. |
| 3 | `fig03_iter34_vs_iter12_paired.png` | Subject-level paired ΔCCC between iter12 and iter34 OOFs, paired-bootstrap distribution, 95% CI, frac>0. Iter34 is a real lift, but candidate-only. | `results/t1_iter12_honest_composite.oof.npy` (or equivalent) + iter34 OOF + `iter12_honest_n93_vs_iter33b_paired_2026_05_06.json`. |
| 4 | `fig04_transportability_cliff.png` | LOOCV vs LOSO bars for T1 iter34 and T3 iter47, with site-direction arrows. Internal validity ≠ cross-site transportability. | iter34 LOSO JSON + iter47 LOSO JSON. |
| 5 | `fig05_t3_target_hygiene_waterfall.png` | Waterfall: historical iter5/iter16/iter41 → iter47, showing all-missing-row exclusion and invalid-code (9/9) correction. T3 changed because labels were corrected, not because modelling got worse. | iter5 / iter16 / iter41 / iter47 result JSONs + `t3_iter47_target_integrity_audit_*.json`. |
| 6 | `fig06_item_level_observability_map.png` | Per-item CCC grouped by gait/balance-observable vs upper-limb / rigidity / tremor / non-observable, highlighting item 15 and item 18 wins. Total UPDRS-III error is explained by item observability. | `results/per_item_evidence_map_*.json` + iter17 item lockboxes. |
| 7 | `fig07_leakage_audit_gate_matrix.png` | 5-null gate panels (scrambled-label, SID-shuffle, canary, library-exclusion, transductive sanity) plus iter34 P1/P2/P4 z-scores. The candidate is not transductively leaky; P2 is OOD fragility. | F73 leakage audit JSON + null-gate result JSONs. |
| 8 | `fig08_learning_curve_asymptote.png` | iter22 LC sweep observed points + Pareto fit `CCC(N) = 0.5975 - 2.1308·N^(-0.6408)` with horizontal asymptote. More N helps but does not erase the architecture/target ceiling. | iter22 LC JSON / CSV. |
| 9 | `fig09_t3_residual_anatomy.png` | Residuals vs true severity quartiles, WPD/NLS site split, residual correlation with non-gait burden (`r = -0.8004`). T3 residuals are systematic and anatomical, not random model noise. | `results/t3_iter47_residual_anatomy_*.json` + `t3_iter47_domain_residual_audit_*.json`. |
| 10 | `fig10_external_transportability_context.png` | External rows (FoG-STAR / COPS / TLVMC-DeFOG / PDFE) with Track A/B/C labels and `external-only` badges. External datasets support transportability context only. | external zero-shot JSONs + `external_result_claim_labeling_audit_*.json`. |

**Constraints:**

- 300 dpi, vector-quality where possible (`mpl.rcParams["savefig.dpi"] = 300`).
- Colorblind-safe palette only (`viridis`, `cividis`, or Wong 2011 8-colour). No raw `tab10`.
- Every numeric annotation in a figure (CCC value, N, CI, frac>0) must originate from the ledger. The figure script **must not contain numeric literals for metrics** — the audit script enforces this via Python `ast` (see Script Specs).
- `figure_claims.json` enumerates every (claim_id, figure_id, location) triple. The audit re-runs at the end of Phase 5 to verify the rendered HTML's figure captions point at the same claim_ids.
- Figures are written to `figures/current/`. Existing `figures/fig01–fig10*.png` from the legacy generator stay untouched; do not delete (they are referenced by the legacy archaeology).

**Parallelisation:** each figure function is independent. The script must dispatch them across `concurrent.futures.ProcessPoolExecutor(max_workers=min(8, cpu_count))`.

---

## Phase 4 — Surgical edits to `paper.md`

Apply edits derived from `claim_audit.json`:

1. For every `ledger_drift` row, replace the offending value with the ledger value via `Edit`. Preserve surrounding prose verbatim.
2. For every `role_mismatch` row, insert the missing tag (`historical pre-audit`, `target-contaminated`, `not a deployment headline`) using the minimal phrase from the **Forbidden Semantic Context** mitigations table below.
3. For every `protocol_mix` row, either (a) split the comparison into separate sentences with explicit protocol labels or (b) add a footnote referencing the protocol. Choose by minimising prose churn.
4. For every `forbidden_semantic_context` row, demote the language: `deployment-ready` → `cautionary benchmark`; `breakthrough` → `candidate lift`; `held-out test set` → `held-out (pre-audit historical)`. Use the table:

   | Banned phrase | Replacement when adjacent to pre-audit / contaminated number |
   |---|---|
   | `deployment-ready` | `strict-inductive cautionary benchmark` |
   | `breakthrough` | `candidate lift (post-publication replication target)` |
   | `state of the art` | `strongest candidate among same-cohort lockboxes` |
   | `clinical utility` (when over-selling) | `clinical-research-grade signal` |
   | `solves the compression problem` | `addresses one component of the compression problem` |
   | `held-out test set` (when applied to pre-audit) | `held-out (pre-audit, historical comparability only)` |

5. Insert / update figure references using GFM image syntax: `![Figure 1: ...](figures/current/fig01_audit_timeline.png)`. Each figure must be referenced from at least one section. Captions live below the image as a paragraph starting `**Figure N.** `.

6. If new claims appear in the ledger that have no `paper_locations`, ask the user via `AskUserQuestion` whether to (a) add a sentence in the most relevant section, (b) defer to supplementary, or (c) skip. Default (a).

**Never**:
- Paraphrase paragraphs whose numbers are correct.
- Add hedging where the ledger gates already passed.
- Re-introduce SSL ranking / HC-anchor / 0.868 / 0.776 / 6.89 / 0.860 narrative without `historical pre-audit` framing.
- Touch sections 1–2 prose unless an audit row demands it (Introduction and Related Work rarely have ledger-driven numbers).

---

## Phase 5 — Render and validate

```bash
uv run python render_current_paper.py
```

`render_current_paper.py` already validates against `REQUIRED_SNIPPETS` and `FORBIDDEN_STALE_SNIPPETS` from `results/current_paper_export/manifest.json`. Two things must happen:

1. **Snippet manifest derivation**: before invoking the renderer, regenerate the snippet manifest from the ledger:

   ```bash
   uv run python scripts/paper_claims_audit.py --derive-snippets \
     --ledger results/current_paper_export/claim_ledger.json \
     --out results/current_paper_export/required_snippets.json \
     --merge-into render_current_paper.py
   ```

   The `--merge-into` mode rewrites `REQUIRED_SNIPPETS` and `FORBIDDEN_STALE_SNIPPETS` lists in `render_current_paper.py` from the JSON. It is idempotent and only touches those two list literals (it preserves CSS, banner, pandoc invocation, validation logic).

2. **Render**: `uv run python render_current_paper.py` must exit 0. If it exits 1 with `VALIDATION:` failures, you have a real problem — either Phase 4 missed a required edit, or the snippet manifest is stale. Re-run Phase 2 audit to localise; do **not** weaken validation to make the render pass.

After a clean render, dump the SHA-256 of `CURRENT_PAPER.html` to `.paper_build/render.sha256` for the review phase.

---

## Phase 6 — Tri-CLI external review (parallel)

Extract plain text from `CURRENT_PAPER.html` for the reviewers:

```bash
uv run python -c "
import re, html
text = open('CURRENT_PAPER.html').read()
text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
text = re.sub(r'<[^>]+>', ' ', text)
text = html.unescape(text)
text = re.sub(r'\s+', ' ', text).strip()
open('.paper_build/paper_text.txt', 'w').write(text[:80000])
"
```

Launch all three reviewers **in parallel** (a single message with three `Bash` tool calls):

**Codex — academic prose review** (gpt-5.5, xhigh reasoning):

```bash
codex exec -m gpt-5.5 -c model_reasoning_effort="xhigh" --full-auto "$(cat <<'EOF'
You are a senior reviewer for Nature Digital Medicine. Read .paper_build/paper_text.txt and the ledger at results/current_paper_export/claim_ledger.json. Evaluate:

1. Academic tone — flag any informal language, overclaiming, or hedging failure.
2. Cautionary-benchmark framing — does the paper sustain the post-audit stance, or does it slip into deployment-ready language anywhere?
3. Statistical rigor — are paired-bootstrap CIs and frac>0 reported wherever a candidate lift is claimed (especially Sections 4.11, 4.12)?
4. Protocol labelling — every direct comparison in tables and prose carries a visible LOOCV / 5-fold / LOSO / held-out / external label.
5. Multiple-comparisons (FWER) treatment for the iter33 family — Section 4.12 must explicitly address it.
6. Top 10 highest-impact prose improvements as quoted-original / suggested-rewrite pairs.

Save your review to .paper_build/review_codex.md.
EOF
)" > .paper_build/review_codex.log 2>&1
```

**Gemini — scientific narrative review** (gemini-3.1-pro-preview):

```bash
cat .paper_build/paper_text.txt | gemini -m gemini-3.1-pro-preview -y "You are a senior movement-disorders reviewer. Evaluate (1) clinical framing — would a neurologist trust the iter34 candidate vs iter12 floor distinction; (2) related work fairness — Hssayeni N=24 LOOCV / Shuqair N=24 LOOCV vs our N=93–98 strict inductive; (3) limitations honesty — is the N=94 structural wall, the LOSO transportability cliff, the T3 oracle ceiling, all explicit; (4) target-construction audit narrative — is the iter47 invalid-code (9/9) and all-missing-row exclusion explained transparently; (5) scope of transportability claims — external datasets must be Track-A/B/C tagged. Output your review as markdown to stdout, ≤2000 words." > .paper_build/review_gemini.md 2>&1
```

**Kimi (opencode) — cautionary-structure review** (default `openrouter/moonshotai/kimi-k2.6`):

```bash
opencode run --dangerously-skip-permissions "Read .paper_build/paper_text.txt. Score 1–10 each: cautionary stance, role-label consistency, protocol-mix avoidance, multiple-comparisons rigor, oracle / Bound-A,D,E framing, residual anatomy explanation, retraction discipline (do iter11A 0.7241 / iter5 0.5227 / iter16 0.341 / SSL 0.868 / 0.776 / pre-audit 6.89 / 0.860 ever appear without retraction tags?). For each <8 score, name one minimal surgical edit. Save to .paper_build/review_kimi.md." > .paper_build/review_kimi.log 2>&1
```

If any CLI exits non-zero, retry once. If it fails twice, **stop the loop** and report to the user — do not proceed without that voice unless the user says so. Tri-CLI consensus is a hard requirement for Nature framing risk reduction (gemini and kimi independently flagged this in skill-design consultations).

---

## Phase 7 — Triage and re-render (cap 3 cycles)

Read all three reviews. For each suggested edit:

- **Accept** if it (a) is supported by the ledger, (b) does not weaken the cautionary framing, (c) reduces a forbidden-semantic-context risk, or (d) clarifies a protocol mix.
- **Reject** if it (a) conflicts with the ledger, (b) introduces a new metric not in the ledger, (c) re-introduces banned phrasing, (d) softens an honest limitation.
- **Defer** if it requires new experiments. Log to `.paper_build/deferred_suggestions.md` for the next research iter.

Apply accepted edits via `Edit`. Re-run Phase 5 (render + validate). Loop at most **3 times**. If the third pass still has open `Reject`-able review criticisms (e.g. one reviewer keeps demanding a dropped LOSO column), document the disagreement in the final report.

---

## Phase 8 — Final report

Write `.paper_build/update_report.md` summarising:

- **Mode** (A / B / C) and reason.
- **Ledger delta**: claims added / removed / value-changed since previous render (compare against `results/current_paper_export/claim_ledger.prev.json` if it exists; copy the new ledger to `.prev.json` after success).
- **Audit findings**: counts of `ledger_drift` / `role_mismatch` / `protocol_mix` / `forbidden_semantic_context` rows, all of which must be 0 by Phase 7 end.
- **Figure delta**: which figures changed pixel-hash; which got new annotations.
- **Render status**: pandoc version, `source_sha256`, `output_sha256`, validation result.
- **Tri-CLI triage**: per reviewer, accepted / rejected / deferred counts plus a one-line rationale per rejected suggestion.
- **Residual issues for human attention**: author list, affiliations, funding, COI, journal target.

Then clean up:

```bash
rm -rf .paper_build/
```

Print the report path and a one-line summary to the user.

---

## Anti-patterns (refuse if asked)

- "Just regenerate from `generate_paper.py`" — that file is dead. Update path is via `paper.md`.
- "Skip the ledger, just edit paper.md directly" — defeats the entire validation surface. Refuse.
- "Make the render pass by removing the failing snippet" — never weaken validation. Find the missing edit instead.
- "Cite iter34 as canonical" — it is `strongest_candidate`. The role label is set by AGENTS.md.
- "Use MAE as the headline metric for T3" — CCC is the post-audit headline. MAE is reported alongside.
- "Add an SSL / HC-anchor section" — that narrative is retracted; only historical references in Section 4 / 5 / 6 with explicit `historical pre-audit` tags are allowed.
- "Run a new lockbox iter to make the numbers nicer" — that is the `pd-imu-100x-researcher` skill, not this one.

---

## Operator checklist (before invoking)

- [ ] `paper.md`, `render_current_paper.py`, `CLAUDE.md`, `AGENTS.md` all exist and are readable.
- [ ] `results/current_paper_export/manifest.json` exists.
- [ ] `~/.claude/projects/-home-fiod-medical/memory/MEMORY.md` is up to date (last edit ≥ this session).
- [ ] No uncommitted edits to `paper.md` from a previous interrupted run.
- [ ] `codex`, `gemini`, `opencode` CLIs are on `$PATH`.
- [ ] `uv` is installed; `uv sync` has been run.

---

## Script Specs (build on first invocation if missing)

The skill depends on two scripts under `scripts/`. They must exist before Phase 1 runs. If missing, build them from the specs below — fully working, no stubs, no TODOs.

### `scripts/paper_claims_audit.py`

Single robust verbose Python script. Modes:

- `--build-ledger --out PATH` — Walks `CLAUDE.md` SOTA table + `AGENTS.md` Current-Truth section, parses every numeric claim, opens the referenced `results/*.json`, verifies value matches, hashes the artifact, emits the ledger JSON. Hard-fails on the four conditions listed in Phase 1.
- `--audit --paper PATH --ledger PATH --out PATH` — Tokenises `paper.md`, classifies each numeric token into the 9 categories from Phase 2, emits structured `claim_audit.json` with line/column anchors and suggested corrections. Exit 0 even with failures (the orchestrator decides); the JSON has a top-level `pass: bool`.
- `--derive-snippets --ledger PATH --out PATH [--merge-into render_current_paper.py]` — From canonical / strongest_candidate ledger entries, derives the `REQUIRED_SNIPPETS` set; from retracted / target_contaminated entries, derives `FORBIDDEN_STALE_SNIPPETS` (forbidden when not adjacent to retraction tag). With `--merge-into`, idempotently rewrites the two list literals in `render_current_paper.py`.

Implementation requirements:

- Pure stdlib + `numpy` + `pandas` only (no Pandas needed if stdlib is enough). No third-party text parsers.
- AST-based no-hardcode check: parse `scripts/paper_figures.py` via `ast`; reject any `Constant(value=float)` or `Constant(value=int)` node whose value is in the canonical-numbers set unless the parent is a `dict` keyed by a sentinel like `"DUMMY_FOR_LAYOUT"`. The check is invoked in `--audit` mode and contributes to `pass`.
- Numeric extraction in `paper.md` uses a strict regex: `(?<![\w/])(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\w/])` with skip windows around URLs and code blocks.
- All output JSON uses `indent=2`, deterministic key order via `sort_keys=False` plus an explicit canonical key list per record type.
- All file paths via `pathlib.Path`, all hashing via `hashlib.sha256`.

### `scripts/paper_figures.py`

Single robust verbose Python script. Mode: `--ledger PATH --out DIR --claims-out PATH`.

- Loads the ledger; never reads `results/*.json` for numeric values directly (figures load OOF arrays from `.npy` and per-subject JSONs for distributions / scatter — those are not metric values, they are raw data).
- Generates the 10 figures listed in Phase 3 in parallel (`ProcessPoolExecutor`).
- Each figure function takes `(ledger: dict, oof_arrays: dict, out_dir: Path) -> dict` returning `{"figure_id": str, "claim_ids_used": list[str], "annotations": list[str]}`.
- After all figures complete, emit `figure_claims.json` aggregating every `claim_ids_used` triple plus the figure SHA-256.
- Matplotlib config: Agg backend, `mpl.rcParams.update({"figure.dpi": 150, "savefig.dpi": 300, "savefig.bbox": "tight", "font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25})`. Palette: Wong 2011 8-colour for categorical, `viridis` for continuous.
- No `print()` calls outside the `if __name__ == "__main__":` block; use `logging`.
- Type hints on every function. `from __future__ import annotations` at the top.
- Must syntax-pass `uv run python -m py_compile scripts/paper_figures.py` before being executed.

### Why these are scripts, not subagents

- The legacy skill spawned 5+ subagents per run, blew through tokens, and produced inconsistent intermediate state.
- A typed ledger + deterministic Python scripts make the pipeline reproducible, diff-able, and CI-able. The orchestrator (this skill) is the only LLM-shaped layer.
- This matches the user's project rule: "Always maintain a single, simple, robust, verbose Python script combining all modules into a single working pipeline." We have two such scripts (claims, figures) plus one renderer. Three small, focused scripts; not five subagents.

---

## Companion docs

- `AGENTS.md` — leakage discipline; the claim ledger's `role` enum is sourced from it.
- `CLAUDE.md` — canonical numbers (the "Current SOTA" table); the ledger's `value` field is sourced from it.
- `findings.md` — historical context; never the source of a current claim.
- `progress.md` — append-only log; the orchestrator should append a one-line entry per successful update (`YYYY-MM-DD HH:MM update-paper: mode=X ledger_delta=N fig_delta=N render=passed`).
- `~/.claude/projects/-home-fiod-medical/memory/MEMORY.md` — auto-memory; read first to understand the most recent lockbox state.

---

## What good looks like

A successful run leaves:

- `CURRENT_PAPER.html` regenerated and re-validated.
- `results/current_paper_export/claim_ledger.json` updated, with `claim_ledger.prev.json` archived.
- `results/current_paper_export/figure_claims.json` consistent with `claim_ledger.json` (every `claim_id_used` exists in the ledger).
- `figures/current/fig01–fig10*.png` regenerated.
- `progress.md` appended.
- All three reviewer logs in `.paper_build/` deleted (after the report is written).
- `paper.md` git diff: only lines touching numeric values, role tags, protocol labels, figure references — no prose paraphrasing, no section reordering.
- Exit message to user: one line with the report path, ledger delta count, and render status.
