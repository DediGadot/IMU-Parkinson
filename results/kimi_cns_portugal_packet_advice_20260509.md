# Kimi CNS Portugal Packet Advice - 2026-05-09

Prompt summary: advise on the local CNS Portugal / Lobo IS2022 AX3 gait author-request packet after PPMI, PPP/PD-VME, and WATCH-PD packets were made ready.

Kimi recommended a concise author/CNS data-owner packet with:

- Study context and citation of Lobo et al. IS2022 as an external transportability route, not a competing leaderboard.
- Exact data scope: raw AX3 wrist plus lumbar/lower-back accelerometry, session-level MDS-UPDRS Part III total and subitems, H&Y, age, sex, disease duration, medication state, and subject-level IDs.
- Schema/codebook request covering file formats, column names, units, windowing logic, and mapping of the 59 features to raw signals.
- Subject-session manifest request so repeated sessions and window rows cannot leak across validation folds.
- Governance and privacy terms: GDPR/institutional approval, no redistribution, encrypted storage, retention/deletion, and DUA if required.
- Methodology commitments: subject-level splits only, fold-local preprocessing, and preference for raw or session-level inputs over precomputed global features.
- Provenance commitments: derived caches with manifest sidecars and pre-registration before any zero-shot metrics.
- Return offer: acknowledgement/co-authorship per CNS policy, aggregate result sharing before publication if requested, and citation of the source paper.

Highest-risk guardrail from the advice: do not treat the published left-out 10% window result or window-level rows as deployment-valid external validation. The packet must require subject/session grouping and aggregation before reported CCC/MAE.

Additional tool status:

- Claude CLI consult was attempted but the account remained blocked by low credit.
- `glmcode` was attempted and was not available on `PATH`.
