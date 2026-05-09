# Kimi ICICLE Packet Advice - 2026-05-09

Prompt summary: advise on a concise local Newcastle / ICICLE-PD / ICICLE-GAIT data-request packet after PPMI, PPP/PD-VME, WATCH-PD, CNS Portugal, and Hssayeni/MJFF packets were made ready.

Kimi recommended a packet with:

- Investigator, affiliation, PI, ethics/IRB, and data-controller / UK transfer fields.
- Scientific rationale framing ICICLE as external transportability / cohort-shift validation from WearGait structured lab tasks to lower-back free-living gait, not as an internal ceiling-break attempt.
- Precise requested data elements: age, sex, H&Y, disease duration, medication state, LEDD if available, MDS-UPDRS Part III total and subitems, visit number/date, the 88 daily digital gait measures with date stamps and subject IDs, raw lower-back AX3 files if shareable, and explicit repeated-label mapping.
- Clarification of the 89 analytic participants versus 121 ICICLE-GAIT participants and the exclusion criteria.
- Anti-leakage guardrails: no test-set imputation, participant-level splits, subject+visit grouping for repeated seven-day labels, no target-derived preprocessing, and fold-local distribution estimation.
- Longitudinal options only after access and pre-registration, such as prospective earlier-visit to later-visit evaluation.
- Data security, no re-sharing, no re-identification, destruction/retention, citation, and publication/attribution sections.

Highest-risk guardrail from the advice: daily rows are not independent because one MDS-UPDRS Part III visit score can label up to seven days. The request packet must require participant+visit grouping and visit-level aggregation before reported CCC/MAE; otherwise performance can be inflated by repeated labels.

Additional tool status:

- Claude CLI consult was attempted but the account remained blocked by low credit.
- `glmcode` was attempted and was not available on `PATH`.
