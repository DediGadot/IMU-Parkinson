# Kimi Hssayeni / MJFF Packet Advice - 2026-05-09

Prompt summary: advise on a concise local Synapse/MJFF DUA request packet for the MJFF Levodopa Response Study / Hssayeni route after PPMI, PPP/PD-VME, WATCH-PD, and CNS Portugal packets were made ready.

Kimi consult was requested with the public Synapse and Scientific Data source facts. The local packet follows the expected access-first pattern:

- Synapse request summary with PI, Synapse username, IRB/exemption, data custodian, and `syn20681023`.
- Intended-use statement framed as external transportability of WearGait-PD models, not a WearGait-PD canonical update.
- Minimal data scope: raw/exportable wrist accelerometry, task windows, timestamps, device metadata, and subject/visit/session/task identifiers.
- Clinical linkage request: MDS-UPDRS Part III total and item/subitem responses if available, symptom ratings, medication state/timing, and data dictionary/missing-code terms.
- Controlled-access governance: individual Synapse authorization, no redistribution, encrypted access-controlled storage, no credential or protected-metadata commits, aggregate public outputs only.
- Methodological guardrails: read-only schema probe first, pre-registration before any scoring, subject-level grouping, medication state treated as a protocol variable, valid-range target construction, and manifest sidecars.
- Stop rules: no access, no visible schema, missing subject/session IDs, missing or unlinked Part III labels, unresolved sensor units/timestamps/medication timing, or DUA terms that prohibit aggregate reporting.

Highest-risk guardrail: do not allow the existing iter26 scaffold or the presence of symptom labels to trigger a model run. The route must hard-stop if approved data expose only limb-specific symptom labels and not total Part III or valid item/subitem fields for the intended endpoint.

Additional tool status:

- Claude CLI consult was attempted but the account remained blocked by low credit.
- `glmcode` was attempted and was not available on `PATH`.
