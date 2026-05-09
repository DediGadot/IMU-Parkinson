# Paper Generator Routing Audit - 2026-05-09

Current paper work must route to render_current_paper.py -> CURRENT_PAPER.html. generate_paper_v4.py / NEW4.html may exist only as explicitly quarantined legacy archaeology.

- Passed: `True`
- Decision: `current_paper_renderer_route_guard_passed`
- Hard failures: `0`

## Current Route

- Renderer: `render_current_paper.py`
- Output: `CURRENT_PAPER.html`
- Export manifest status: `passed`
- Export validation issues: `0`
- Renderer required snippets missing: `0`
- Forbidden stale snippets in current export: `0`
- Manifest mtime >= renderer mtime: `True`

## Active Docs

- `AGENTS.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`
- `CLAUDE.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`
- `README.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`
- `task_plan.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`
- `progress.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`
- `findings.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`
- `results/current_best_pipeline_artifact_index_20260508.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`
- `results/thread_goal_completion_audit_20260508.md`: missing current-route snippets `0`, bad exact snippets `0`, unguarded legacy hits `0`

## Legacy Quarantine

- `.claude/commands/update-paper.md`: missing quarantine snippets `0`, stale/legacy hits retained `62`

## Legacy Generator Evidence

- Script: `generate_paper_v4.py`
- Output: `NEW4.html`
- Script missing stale/quarantine evidence: `0`
- NEW4 missing stale evidence: `0`
- Stale phrase counts: `{'generate_paper_v4_py_0_868': 6, 'generate_paper_v4_py_0_776': 5, 'new4_html_0_868': 10, 'new4_html_0_776': 8, 'new4_html_transductive': 17}`

## Kimi Consult

Kimi agreed this is a non-redundant publication-surface routing guard: docs should point to render_current_paper.py/CURRENT_PAPER.html, legacy generators should be marked stale, and no WearGait-only model run is justified by this issue.

Machine-readable report: `results/paper_generator_routing_audit_20260509.json`
