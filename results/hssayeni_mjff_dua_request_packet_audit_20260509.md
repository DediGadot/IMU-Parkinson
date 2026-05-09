# Hssayeni / MJFF DUA Request Packet Audit - 2026-05-09

This is an access-readiness guard, not a model result and not a completion marker.

- Passed: `True`
- Decision: `hssayeni_mjff_dua_request_packet_ready`
- Packet: `scripts/hssayeni_mjff_dua_request_packet.md`
- Runbook links packet: `True`
- Hard failures: `0`

## Checks

| Check | Status | Missing Terms |
|---|---|---|
| `official_sources_and_public_facts` | `True` | - |
| `synapse_metadata` | `True` | - |
| `scientific_data_facts` | `True` | - |
| `access_path` | `True` | - |
| `specific_data_inventory` | `True` | - |
| `clinical_linkage_inventory` | `True` | - |
| `security_publication_terms` | `True` | - |
| `methodology_guardrails` | `True` | - |
| `hssayeni_specific_guardrails` | `True` | - |
| `no_premature_compute_boundary` | `True` | - |

## Decision

The Hssayeni / MJFF Levodopa Response Study Synapse DUA request packet is ready to fill for the user/data-owner access step. It does not authorize a probe, preregistration, download, remote job, cache extraction, or model run. The first allowed code action after approval remains a read-only schema probe.
