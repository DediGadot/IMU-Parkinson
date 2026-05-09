# CNS Portugal Request Packet Audit - 2026-05-09

This is an access-readiness guard, not a model result and not a completion marker.

- Passed: `True`
- Decision: `cns_portugal_request_packet_ready`
- Packet: `scripts/cns_portugal_request_packet.md`
- Runbook links packet: `True`
- Hard failures: `0`

## Checks

| Check | Status | Missing Terms |
|---|---|---|
| `official_source_and_public_facts` | `True` | - |
| `access_path` | `True` | - |
| `specific_data_inventory` | `True` | - |
| `clinical_linkage_inventory` | `True` | - |
| `required_packet_fields` | `True` | - |
| `security_publication_terms` | `True` | - |
| `methodology_guardrails` | `True` | - |
| `cns_specific_guardrails` | `True` | - |
| `no_premature_compute_boundary` | `True` | - |

## Decision

The CNS Portugal / Lobo AX3 gait request packet is ready to fill for the user/data-owner access step. It does not authorize a scaffold, preregistration, download, remote job, or model run. The first allowed code action after approval remains a read-only schema probe.
