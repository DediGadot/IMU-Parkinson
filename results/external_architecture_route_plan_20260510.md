# External Architecture Route Plan - 2026-05-10

This is a route-readiness artifact, not a model result.

- Passed: `True`
- Decision: `external_architecture_routes_blocked_until_access`
- Top priority route: `PPMI / Verily Study Watch`
- Compute-ready routes: `0`
- Access-request routes: `6`
- PPMI submission support ready: `True`

## Routes

| Priority | Route | Allowed action now | Compute-ready | Submission support | Access blocker |
|---:|---|---|---|---|---|
| 1 | PPMI / Verily Study Watch | `access_request_only` | `False` | `ready` | PPMI qualified-researcher account, DUA, online application, and DPC approval. |
| 2 | Personalized Parkinson Project / PD Virtual Motor Exam | `access_request_only` | `False` | `not required` | PPP RDSRC/request approval, Qualified Researcher Agreement, fees, and PEP repository access. |
| 3 | WATCH-PD | `access_request_only` | `False` | `not required` | C-Path 3DT Stage 2 membership or accepted WATCH-PD Steering Committee proposal. |
| 4 | CNS Portugal / Lobo IS2022 AX3 gait | `access_request_only` | `False` | `not required` | Author/CNS data-owner approval and row-level AX3 plus Part III schema. |
| 5 | MJFF Levodopa Response / Hssayeni | `access_request_only` | `False` | `not required` | Synapse DUA/READ approval for syn20681023. |
| 6 | ICICLE-PD / ICICLE-GAIT | `access_request_only` | `False` | `not required` | Newcastle/data-owner request approval and lower-back AX3 plus MDS-UPDRS schema. |

## Decision

No external route is compute-ready. The next valid action is access submission, then a read-only schema probe after approval.

Machine-readable report: `results/external_architecture_route_plan_20260510.json`
