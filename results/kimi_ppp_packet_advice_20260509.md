# Kimi PPP / PD-VME Packet Advice - 2026-05-09

This is an advisor note for the PPP / PD-VME access packet, not a model result.

Prompt context: no local WearGait-only model actions remain; PPMI access packet is ready; the next ordered gated route is Personalized Parkinson Project / PD Virtual Motor Exam.

Kimi recommended the packet include:

- Official PPP project-proposal framing around external-validity transportability.
- Personnel section naming exactly the approved researchers, including a confirmed PhD applicant and short PI CV.
- Aims and target mapping for MDS-UPDRS Part III OFF/ON totals and consensus subitems corresponding to T1 items 9-14.
- Methodology section with subject-level cross-validation, fold-local fitting, and lockbox/pre-registration protocol.
- Data-management plan covering pre-submission check, encrypted storage, access logging, no open sharing outside PEP, and derived-data upload back to PEP.
- Timeline section including the 45-day manuscript submission window to PPP Research Support.
- Budget/cost line for PPP fees and PEP repository costs.

Kimi recommended these guardrails:

- Do not promise public redistribution of PPP data.
- Do not propose window-level splits, global ranking, or test-set tuning.
- Do not submit without a confirmed PhD applicant.
- Include RDSRC readiness if the organization is not pre-approved.
- Commit to pre-registration before first LOOCV or label-informed model development.
- Explicitly agree to upload required derived data/features/predictions back to PEP.

Tool friction remained unchanged:

- Claude CLI was available but failed due low credit in the prior packet consult.
- `glmcode` was not found on `PATH`.
