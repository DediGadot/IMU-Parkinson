# WearGait Raw Data Recovery Runbook Audit - 2026-05-09

This is a provenance/readiness audit, not a model result.

- Passed: `True`
- Decision: `raw_data_recovery_runbook_ready_no_download`
- Runbook: `scripts/weargait_raw_data_recovery_runbook.md`
- Preflight status: `missing_inputs`
- Credentials present in stored preflight: `False`
- Regeneration probe status: `blocked_missing_regeneration_inputs`
- Frozen cache unchanged in probe: `True`

## Entity Checks

| Entity | Synapse ID | Large transfer | Local complete | Probe status |
|---|---|---|---|---|
| `control_clinical` | `syn55105521` | `False` | `False` | `ok` |
| `control_csv_folder` | `syn61370552` | `True` | `False` | `ok` |
| `walkway_metrics` | `syn64589881` | `False` | `False` | `ok` |

## Guardrail Result

- Hard failures: `0`
- Warnings: `0`

## Decision

The runbook is ready as a human-facing recovery guide. No download, cache promotion, or model run was performed by this audit.
