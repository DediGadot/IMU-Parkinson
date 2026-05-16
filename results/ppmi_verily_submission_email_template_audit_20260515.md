# PPMI / Verily Submission Email Template Audit - 2026-05-15

This is an access-submission helper audit, not a model result or access approval.

- Passed: `True`
- Decision: `ppmi_verily_submission_email_template_ready`
- Template: `scripts/ppmi_verily_submission_email_template.md`
- Hard failures: `0`

## Checks

| Check | Status | Missing Terms |
|---|---|---|
| `template_exists` | `True` | - |
| `word_template_audit_passed` | `True` | - |
| `placeholders_present` | `True` | - |
| `submission_recorder_command_aligned` | `True` | - |
| `submission_route` | `True` | - |
| `official_source_recheck` | `True` | - |
| `required_packet_context` | `True` | - |
| `compute_boundary` | `True` | - |
| `submission_recorder` | `True` | - |
| `completed_packet_preflight` | `True` | - |
| `completed_email_preflight` | `True` | - |
| `completed_package_preflight` | `True` | - |
| `protected_info_boundary` | `True` | - |

## Decision

Fill the Word packet and email it through the PPMI access workflow; record only non-protected submission metadata after sending.

Machine-readable report: `results/ppmi_verily_submission_email_template_audit_20260515.json`
