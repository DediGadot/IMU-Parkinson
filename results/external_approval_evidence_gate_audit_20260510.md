# External Approval Evidence Gate Audit - 2026-05-10

This verifies non-protected approval evidence before protected external schema probes. It is not a model result.

- Passed: `True`
- Decision: `external_approval_evidence_gate_passed`
- Hard failures: `0`

## Checks

- `True` clean approval evidence validates without protected content
- `True` schema probe blocks on route boolean without approval evidence
- `True` schema probe accepts clean approval evidence
- `True` approval evidence rejects placeholders, protected rows, and credentials
- `True` approval evidence route mismatch blocks schema probe
- `True` protected preregistration requires approval evidence after schema probe

## Claim

Protected external schema probes and protected preregistration now require explicit AccessApprovalEvidence; approved_access booleans alone are insufficient, and approval evidence must not include protected rows, credentials, or tokens.

Machine-readable report: `results/external_approval_evidence_gate_audit_20260510.json`
