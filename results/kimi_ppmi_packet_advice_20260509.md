# Kimi PPMI Packet Advice - 2026-05-09

This is an advisor note for the PPMI / Verily access packet, not a model result.

Prompt context: no local WearGait-only model actions remain; the next action is PPMI / Verily Study Watch access. Official PPMI materials classify Verily Raw Device Data as Tier 3 and require a specific data/use/analysis/team/no-sharing request packet.

Kimi recommended the packet include:

- Cover / PI credentials, including IRB protocol or exemption status.
- Granular Tier-3 data inventory rather than a request for "all data".
- Scientific rationale linking wrist IMU plus MDS-UPDRS to WearGait-PD T1/T3 objectives.
- Analysis synopsis showing competence without locking an unvalidated model architecture.
- Named research-team roster and one data custodian.
- Security and handling plan: encrypted storage, no consumer cloud sync, no sharing outside named team.
- Publications/IP acknowledgement and no re-identification language.
- No-reuse/no-redistribution/purpose reaffirmation.

Kimi recommended these methodological guardrails:

- Treat PPMI / Verily as external validation or pretraining/benchmarking first, not a direct replacement for WearGait-PD lockbox results.
- State cohort honesty boundaries for wrist-worn free-living PPMI versus protocolized WearGait-PD.
- Keep subject-level splits and prevent PPMI test-fold information from entering WearGait-PD canonical claims.
- Require screen -> pre-registration -> single-LOOCV discipline for any PPMI-augmented canonical claim.
- Pin data version/download date.
- Apply the same valid-range target construction rules used in `run_t3_iter47_invalid_code_fix.py`.

Tool friction remained unchanged:

- Claude CLI failed due low credit.
- `glmcode` was not found on `PATH`.
